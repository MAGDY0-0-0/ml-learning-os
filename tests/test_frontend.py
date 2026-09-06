"""Tests for the shell: the player endpoints, the PDF route, and the mark.

The frontend rewrite added three things that can fail silently — a player that
posts state in the background, a route that serves files off disk, and a rail
whose state is derived rather than passed in. Each one of those is exactly the
kind of thing that breaks without anybody noticing, so each one is pinned here.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import library, seed  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Progress, Resource, ResourceState, StudySession, Unit,
)
from app.web import active_module, templates, youtube_ids  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    """Make sure there is a curriculum to test against.

    On a developer machine the database is already seeded, so this is a no-op.
    On CI it is empty, and without this every test that reaches for a unit
    fails with AttributeError on None -- which is exactly what happened the
    first time this suite met a fresh checkout.
    """
    init_db()
    with Session(engine) as s:
        if s.exec(select(Unit)).first() is None:
            seed.seed(seed.load_modules())


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def a_unit():
    with Session(engine) as s:
        u = s.exec(select(Unit)).first()
        r = s.exec(select(Resource).where(Resource.unit_id == u.id)).first()
        return u.slug, u.id, r.id


@pytest.fixture(autouse=True)
def restore_progress(a_unit):
    """Put back whatever these tests touched.

    The app has one database and it is the learner's real one, so a test run
    must not leave study minutes or a watch position behind. Snapshot the two
    rows these tests write, then restore them.
    """
    _, uid, rid = a_unit
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
        st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
        before = (
            (p.minutes_logged, p.status) if p else None,
            (st.position_seconds, st.done) if st else None,
        )
        sessions = {ss.id for ss in s.exec(select(StudySession))}

    yield

    with Session(engine) as s:
        for ss in s.exec(select(StudySession)):
            if ss.id not in sessions:
                s.delete(ss)
        s.commit()

    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
        if before[0] is None:
            if p:
                s.delete(p)
        elif p:
            p.minutes_logged, p.status = before[0]

        st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
        if before[1] is None:
            if st:
                s.delete(st)
        elif st:
            st.position_seconds, st.done = before[1]
        s.commit()


# --------------------------------------------------------------------------
# YouTube id parsing — the player needs the two ids apart, not a joined URL
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.youtube.com/watch?v=abc123", {"video": "abc123", "list": ""}),
        ("https://youtu.be/abc123", {"video": "abc123", "list": ""}),
        (
            "https://www.youtube.com/playlist?list=PL999",
            {"video": "", "list": "PL999"},
        ),
        (
            "https://www.youtube.com/watch?v=abc123&list=PL999",
            {"video": "abc123", "list": "PL999"},
        ),
    ],
)
def test_youtube_ids_are_split(url, expected):
    assert youtube_ids(url) == expected


def test_youtube_ids_ignores_other_hosts():
    assert youtube_ids("https://vimeo.com/12345") is None
    assert youtube_ids("https://scikit-learn.org/stable/") is None


# --------------------------------------------------------------------------
# player state
# --------------------------------------------------------------------------


def test_position_is_remembered(client, a_unit):
    _, _, rid = a_unit
    assert client.post(f"/resource/{rid}/position", json={"seconds": 137}).json()["seconds"] == 137
    with Session(engine) as s:
        st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
        assert st.position_seconds == 137


def test_auto_logged_minutes_are_capped(client, a_unit):
    """A single beacon must never be able to claim an hour of study."""
    slug, uid, _ = a_unit
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
        before = p.minutes_logged if p else 0

    client.post(f"/unit/{slug}/log-auto", json={"minutes": 9999})
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
        assert p.minutes_logged - before == 30


def _minutes(unit_id: int) -> int:
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
        return p.minutes_logged if p else 0


def test_negative_minutes_are_ignored(client, a_unit):
    slug, uid, _ = a_unit
    before = _minutes(uid)
    client.post(f"/unit/{slug}/log-auto", json={"minutes": -500})
    assert _minutes(uid) == before


# --------------------------------------------------------------------------
# the PDF route serves the shelf and nothing else
# --------------------------------------------------------------------------


def test_unknown_document_is_404(client):
    assert client.get("/library/doc/999999").status_code == 404


def test_document_route_refuses_paths_outside_the_library(client):
    """A row pointing anywhere else must not become a file read."""
    with Session(engine) as s:
        doc = library.LibraryDoc(path=str(ROOT / "app" / "main.py"), title="escape", pages=1)
        s.add(doc)
        s.commit()
        s.refresh(doc)
        doc_id = doc.id
    try:
        assert client.get(f"/library/doc/{doc_id}").status_code == 404
    finally:
        with Session(engine) as s:
            s.delete(s.get(library.LibraryDoc, doc_id))
            s.commit()


# --------------------------------------------------------------------------
# the rail derives its own state
# --------------------------------------------------------------------------


def test_active_module_from_a_module_url():
    assert active_module("/module/m4-classical") == "m4-classical"


def test_active_module_resolves_through_a_unit():
    with Session(engine) as s:
        u = s.exec(select(Unit)).first()
        slug = u.slug
    assert active_module(f"/unit/{slug}") != ""


def test_active_module_is_blank_elsewhere():
    assert active_module("/library") == ""
    assert active_module("/") == ""


# --------------------------------------------------------------------------
# the mark
# --------------------------------------------------------------------------


def _logo(pct, size):
    return templates.env.get_template("_logo.html").module.logo(pct, size)


def test_logo_ring_is_empty_at_zero():
    assert "logo-fg" not in _logo(0, 64)


def test_logo_ring_closes_at_100():
    svg = _logo(100, 64)
    assert 'stroke-dashoffset="0.0"' in svg
    assert "full" in svg


def test_logo_ring_is_partial_in_between():
    # a third of 131.95 remaining ~= 88.4 of offset
    assert 'stroke-dashoffset="88.41"' in _logo(33, 64)


def test_logo_clamps_out_of_range_progress():
    assert "logo-fg" not in _logo(-20, 64)
    assert 'stroke-dashoffset="0.0"' in _logo(400, 64)


def test_logo_drops_the_chevron_below_20px():
    """The spec: below 20px the M is dropped and the ring stands alone."""
    assert "M24 39V25" in _logo(50, 20)
    assert "M24 39V25" not in _logo(50, 16)


# --------------------------------------------------------------------------
# the palette has something to search
# --------------------------------------------------------------------------


def test_search_index_covers_units_and_modules(client):
    items = client.get("/api/search-index").json()["items"]
    assert len(items) > 30
    assert all({"k", "t", "u"} <= set(i) for i in items)
    assert any(i["u"].startswith("/unit/") for i in items)
    assert any(i["u"].startswith("/module/") for i in items)


# --------------------------------------------------------------------------
# link checking tells the truth about video
# --------------------------------------------------------------------------
# A deleted YouTube video still answers 200 on its watch page, so the obvious
# check passes every dead video in the curriculum. These pin the oEmbed route.
# Mocked, so CI needs no network.


def test_video_urls_are_checked_through_oembed(monkeypatch):
    from app import seed

    asked: list[str] = []

    def fake(url):
        asked.append(url)
        return "200"

    monkeypatch.setattr(seed, "_fetch_status", fake)
    seed._check_one("u", "https://www.youtube.com/watch?v=abc123")

    assert len(asked) == 1
    assert asked[0].startswith("https://www.youtube.com/oembed")
    assert "watch%3Fv%3Dabc123" in asked[0]


def test_a_dead_video_fails_the_check(monkeypatch):
    from app import seed

    monkeypatch.setattr(seed, "_fetch_status", lambda url: "400")
    _, _, status, note = seed._check_one("u", "https://youtu.be/abc123")

    assert status == "400"
    assert "no longer plays" in note


def test_non_video_urls_are_fetched_directly(monkeypatch):
    from app import seed

    asked: list[str] = []
    monkeypatch.setattr(seed, "_fetch_status", lambda url: asked.append(url) or "200")
    seed._check_one("u", "https://scikit-learn.org/stable/user_guide.html")

    assert asked == ["https://scikit-learn.org/stable/user_guide.html"]


def test_bot_blocked_hosts_are_warned_not_failed(monkeypatch):
    from app import seed

    monkeypatch.setattr(seed, "_fetch_status", lambda url: "403")
    _, _, status, note = seed._check_one("u", "https://exercism.org/tracks/python")

    assert status == "403"
    assert "bot-blocked" in note


def test_vimeo_uses_its_own_oembed(monkeypatch):
    from app import seed

    asked: list[str] = []
    monkeypatch.setattr(seed, "_fetch_status", lambda url: asked.append(url) or "200")
    seed._check_one("u", "https://vimeo.com/123456")

    assert asked[0].startswith("https://vimeo.com/api/oembed.json")


# --------------------------------------------------------------------------
# platforms: what the player can drive, and what must open in a new tab
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, platform, embeddable",
    [
        ("https://www.youtube.com/watch?v=x", "YouTube", True),
        ("https://youtu.be/x", "YouTube", True),
        ("https://www.deeplearning.ai/short-courses/", "DeepLearning.AI", False),
        ("https://ocw.mit.edu/courses/6-036/", "MIT OpenCourseWare", False),
        ("https://course.fast.ai/Lessons/lesson1.html", "fast.ai", False),
        ("https://academy.claude.com/", "Anthropic Academy", False),
    ],
)
def test_platform_and_embeddability(url, platform, embeddable):
    from app.web import is_embeddable, platform_of

    assert platform_of(url) == platform
    assert is_embeddable(url) is embeddable


def test_unknown_host_still_gets_a_readable_name():
    from app.web import platform_of

    assert platform_of("https://www.example.org/a") == "example.org"


def test_non_embeddable_video_primary_renders_an_offsite_card(client):
    """It must never render an empty player shell for a video it can't drive."""
    from app.models import Module

    with Session(engine) as s:
        target = None
        for u in s.exec(select(Unit)):
            r = s.exec(
                select(Resource).where(Resource.unit_id == u.id).order_by(Resource.rank)
            ).first()
            if r and r.kind.value in {"video", "playlist", "course"}:
                from app.web import is_embeddable

                if not is_embeddable(r.url):
                    target = (u.slug, r.url)
                    break
        assert target, "no non-embeddable video primary in the curriculum to test"

    html = client.get(f"/unit/{target[0]}").text
    assert 'class="offsite"' in html
    assert 'id="player"' not in html
    assert "Plays on" in html


def test_embeddable_video_primary_renders_the_player(client):
    html = client.get("/unit/m4-sklearn-api").text
    assert 'id="player"' in html
    assert 'class="offsite"' not in html


# --------------------------------------------------------------------------
# the experiment log — and the one rigor rung the app can actually verify
# --------------------------------------------------------------------------


@pytest.fixture
def a_project():
    from app.models import ExperimentRun, Project, RubricCheck

    with Session(engine) as s:
        p = s.exec(select(Project)).first()
        pid, slug = p.id, p.slug
    yield slug, pid
    # These write real runs into the learner's own project; take them back out.
    with Session(engine) as s:
        for r in s.exec(select(ExperimentRun).where(ExperimentRun.project_id == pid)):
            s.delete(r)
        c = s.exec(
            select(RubricCheck).where(RubricCheck.project_id == pid, RubricCheck.code == "R5")
        ).first()
        if c:
            from app.models import CheckStatus

            c.status = CheckStatus.unchecked
        s.commit()
    shutil.rmtree(ROOT / "experiments" / slug, ignore_errors=True)


def _log(client, slug, label, value, seed):
    return client.post(
        f"/project/{slug}/runs",
        data={
            "label": label, "metric_name": "auc",
            "metric_value": str(value), "seed": str(seed), "config": "", "notes": "",
        },
        follow_redirects=False,
    )


def test_ablation_needs_two_variants_not_a_promise(client, a_project):
    """R5 is the only rung backed by evidence rather than an honesty checkbox."""
    slug, _ = a_project

    r = client.post(f"/project/{slug}/check/R5", data={"status": "passed"},
                    follow_redirects=False)
    assert "err=ablation" in r.headers["location"]

    _log(client, slug, "baseline", 0.81, 0)
    r = client.post(f"/project/{slug}/check/R5", data={"status": "passed"},
                    follow_redirects=False)
    assert "err=ablation" in r.headers["location"], "one label is not an ablation"

    _log(client, slug, "with-encoding", 0.85, 0)
    r = client.post(f"/project/{slug}/check/R5", data={"status": "passed"},
                    follow_redirects=False)
    assert "err=ablation" not in r.headers["location"]

    with Session(engine) as s:
        from app.models import CheckStatus, RubricCheck

        c = s.exec(
            select(RubricCheck).where(RubricCheck.code == "R5")
        ).first()
        assert c.status == CheckStatus.passed


def test_ablation_table_reports_spread_across_seeds(client, a_project):
    slug, _ = a_project
    _log(client, slug, "baseline", 0.80, 0)
    _log(client, slug, "baseline", 0.82, 1)

    html = client.get(f"/project/{slug}/runs?metric=auc").text
    assert "0.8100" in html          # mean of the two
    assert "±" in html               # and its spread, which is the point


def test_a_single_run_reports_no_spread(client, a_project):
    slug, _ = a_project
    _log(client, slug, "solo", 0.9, 0)
    html = client.get(f"/project/{slug}/runs?metric=auc").text
    assert "no spread to report" in html


def test_run_log_records_the_commit(client, a_project):
    from app.models import ExperimentRun

    slug, pid = a_project
    _log(client, slug, "baseline", 0.5, 0)
    with Session(engine) as s:
        run = s.exec(select(ExperimentRun).where(ExperimentRun.project_id == pid)).first()
        assert run.git_commit and run.git_commit != "unknown"


def test_malformed_config_is_refused(client, a_project):
    slug, _ = a_project
    r = client.post(
        f"/project/{slug}/runs",
        data={"label": "x", "metric_name": "auc", "metric_value": "1", "config": "not json"},
        follow_redirects=False,
    )
    assert "err=config" in r.headers["location"]
