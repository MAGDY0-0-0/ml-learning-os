"""Tests for the ML Learning OS itself."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rubric, seed, srs  # noqa: E402
from app.models import CheckStatus, Project, RubricCheck  # noqa: E402
from app.runner import run_submission  # noqa: E402


# --------------------------------------------------------------------------
# environment invariants
# --------------------------------------------------------------------------


def test_sqlite_has_fts5():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    conn.close()


# --------------------------------------------------------------------------
# SM-2
# --------------------------------------------------------------------------


def test_srs_known_vectors():
    assert srs.review(2.5, 0, 0, 0, 4).interval_days == 1
    assert srs.review(2.5, 1, 1, 0, 4).interval_days == 6
    assert srs.review(2.5, 6, 2, 0, 4).interval_days == 15


def test_srs_failure_resets_and_lapses():
    r = srs.review(2.5, 15, 3, 1, 1)
    assert (r.repetitions, r.interval_days, r.lapses) == (0, 1, 2)


def test_srs_ease_floor():
    assert srs.review(1.3, 10, 4, 0, 0).ease >= srs.MIN_EASE
    assert srs.review(1.3, 10, 4, 0, 3).ease >= srs.MIN_EASE


def test_srs_rejects_bad_quality():
    with pytest.raises(ValueError):
        srs.review(2.5, 1, 1, 0, 9)


# --------------------------------------------------------------------------
# sandbox safety — the properties that matter most
# --------------------------------------------------------------------------


def test_runner_times_out_on_infinite_loop(tmp_path):
    """An infinite loop must time out, not hang the server."""
    sub = tmp_path / "sol.py"
    sub.write_text("while True:\n    pass\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("import solution\ndef test_ok():\n    assert True\n", encoding="utf-8")

    result = run_submission(sub, tests, timeout=5)
    assert result.timed_out is True
    assert "TIMED OUT" in result.output


def test_runner_blocks_network(tmp_path):
    sub = tmp_path / "sol.py"
    sub.write_text(
        "import socket\n"
        "def phone_home():\n"
        "    socket.create_connection(('example.com', 80), timeout=3)\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_net.py").write_text(
        "import pytest, solution\n"
        "def test_network_is_blocked():\n"
        "    with pytest.raises(OSError):\n"
        "        solution.phone_home()\n",
        encoding="utf-8",
    )
    result = run_submission(sub, tests, timeout=20)
    assert result.passed == 1, result.output


def test_runner_reports_failures(tmp_path):
    sub = tmp_path / "sol.py"
    sub.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_add.py").write_text(
        "import solution\n"
        "def test_a():\n    assert solution.add(1, 1) == 2\n"
        "def test_b():\n    assert solution.add(0, 0) == 0\n",
        encoding="utf-8",
    )
    result = run_submission(sub, tests, timeout=20)
    assert result.total == 2
    assert result.passed == 1


def test_reference_srs_passes_its_own_assignment():
    """app/srs.py must satisfy the hidden tests students are graded against."""
    result = run_submission(
        ROOT / "app" / "srs.py",
        ROOT / "curriculum" / "assignments" / "m1-srs-scheduler" / "tests",
        timeout=60,
    )
    assert result.ok, result.output


# --------------------------------------------------------------------------
# curriculum rules
# --------------------------------------------------------------------------


def test_curriculum_passes_all_rules():
    modules = seed.load_modules()
    assert seed.validate(modules) == []


def test_curriculum_is_nonempty():
    modules = seed.load_modules()
    units = [u for m in modules for u in m.get("units") or []]
    assert len(modules) >= 9
    assert len(units) >= 25


def test_every_primary_is_free():
    for m in seed.load_modules():
        for u in m.get("units") or []:
            primary = (u.get("resources") or [])[0]
            assert primary.get("cost", "free") in {"free", "free-audit"}, u["slug"]


def test_validator_catches_text_primary_without_flag():
    """The video-first rule must actually fail a bad unit."""
    bad = {
        "slug": "x",
        "resources": [
            {"kind": "book", "title": "b", "url": "u", "community_verdict": "v", "caveat": ""},
            {"kind": "video", "title": "v", "url": "u2", "community_verdict": "v", "caveat": ""},
            {"kind": "interactive", "title": "i", "url": "u3", "community_verdict": "v", "caveat": ""},
        ],
    }
    errors: list[str] = []
    seed.validate_unit(bad, errors)
    assert any("not video" in e for e in errors)


def test_validator_catches_single_modality_alternates():
    bad = {
        "slug": "y",
        "resources": [
            {"kind": "video", "title": "a", "url": "1", "community_verdict": "v", "caveat": ""},
            {"kind": "playlist", "title": "b", "url": "2", "community_verdict": "v", "caveat": ""},
            {"kind": "course", "title": "c", "url": "3", "community_verdict": "v", "caveat": ""},
        ],
    }
    errors: list[str] = []
    seed.validate_unit(bad, errors)
    assert any("modality" in e for e in errors)


def test_validator_catches_too_few_resources():
    bad = {
        "slug": "z",
        "resources": [
            {"kind": "video", "title": "a", "url": "1", "community_verdict": "v", "caveat": ""},
        ],
    }
    errors: list[str] = []
    seed.validate_unit(bad, errors)
    assert any("needs >=" in e for e in errors)


def test_validator_catches_paid_primary():
    bad = {
        "slug": "w",
        "resources": [
            {"kind": "video", "title": "a", "url": "1", "community_verdict": "v", "caveat": "", "cost": "paid-optional"},
            {"kind": "book", "title": "b", "url": "2", "community_verdict": "v", "caveat": ""},
            {"kind": "interactive", "title": "c", "url": "3", "community_verdict": "v", "caveat": ""},
        ],
    }
    errors: list[str] = []
    seed.validate_unit(bad, errors)
    assert any("costs money" in e for e in errors)


# --------------------------------------------------------------------------
# rigor gate
# --------------------------------------------------------------------------


def _checks(codes_status):
    return [
        RubricCheck(project_id=1, code=c, label=c, question="", group="leakage", status=st)
        for c, st in codes_status
    ]


def test_gate_blocks_on_unchecked():
    checks = _checks([("L1.1", CheckStatus.passed), ("L1.2", CheckStatus.unchecked)])
    assert rubric.can_complete(checks) is False
    assert [c.code for c in rubric.blocking(checks)] == ["L1.2"]


def test_gate_allows_when_all_resolved():
    checks = _checks([("L1.1", CheckStatus.passed), ("L3.1", CheckStatus.skipped)])
    assert rubric.can_complete(checks) is True


def test_leakage_taxonomy_is_complete():
    codes = {c.code for c in rubric.LEAKAGE}
    assert codes == {"L1.1", "L1.2", "L1.3", "L1.4", "L2", "L3.1", "L3.2", "L3.3"}


def test_deployment_checks_only_for_deploy_projects():
    plain = Project(slug="a", title="a", requires_deployment=False)
    deploy = Project(slug="b", title="b", requires_deployment=True)
    assert len(rubric.specs_for(deploy)) == len(rubric.specs_for(plain)) + 3


# --------------------------------------------------------------------------
# every page must actually load its stylesheet
# --------------------------------------------------------------------------


def test_asset_helper_does_not_double_the_static_prefix():
    from app.main import asset

    for name in ("style.css", "/style.css", "static/style.css"):
        url = asset(name)
        assert url.startswith("/static/style.css"), url
        assert "/static/static/" not in url, f"doubled prefix: {url}"


def test_asset_helper_versions_by_mtime():
    from app.main import asset

    assert "?v=" in asset("style.css")


def test_every_page_links_a_stylesheet_that_exists():
    """Regression: a bad asset() URL rendered every page as raw unstyled HTML."""
    import re

    from fastapi.testclient import TestClient

    from app.main import app

    pages = [
        "/", "/tour", "/recap", "/review", "/projects", "/library",
        "/module/m0-setup", "/unit/m2-pandas",
        "/project/p5-portfolio", "/assignment/m0-idioms-drill",
    ]
    with TestClient(app) as client:
        for page in pages:
            resp = client.get(page)
            assert resp.status_code == 200, f"{page} -> {resp.status_code}"
            hrefs = re.findall(r'href="([^"]*\.css[^"]*)"', resp.text)
            assert hrefs, f"{page} links no stylesheet at all"
            for href in hrefs:
                css = client.get(href)
                assert css.status_code == 200, f"{page} -> {href} is {css.status_code}"
                assert "text/css" in css.headers.get("content-type", ""), href
                assert ":root" in css.text, f"{href} did not return real CSS"
