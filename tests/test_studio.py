"""The studio redesign: what it promises, and what it must not have changed.

Two kinds of test. The first kind pins the redesign's own claims — one obvious
action per screen, the unit read as Learn / Practice / Reflect / Finish, the
roadmap behind Explore, focus mode only where there is a lesson to focus on.
The second kind is the guard rail: every form, endpoint and script hook the
backend and the JS depend on is still on the page, so a layout change can
never quietly break progress.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import seed  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Assignment, Module, Progress, Unit, UnitStatus  # noqa: E402
from app.web import templates  # noqa: E402

PRIMARY = re.compile(r'<(?:a|button)\b[^>]*\bclass="[^"]*\bprimary\b')


@pytest.fixture(scope="module", autouse=True)
def seeded():
    init_db()
    with Session(engine) as s:
        if s.exec(select(Unit)).first() is None:
            seed.seed(seed.load_modules())


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _unit_with_practice() -> str:
    with Session(engine) as s:
        a = s.exec(select(Assignment)).first()
        return s.get(Unit, a.unit_id).slug


def _unit_without_practice() -> str:
    with Session(engine) as s:
        with_practice = {a.unit_id for a in s.exec(select(Assignment))}
        return next(u.slug for u in s.exec(select(Unit)) if u.id not in with_practice)


# --------------------------------------------------------------------------
# one obvious action per screen
# --------------------------------------------------------------------------


def test_today_has_exactly_one_primary_action(client):
    html = client.get("/").text
    assert len(PRIMARY.findall(html)) == 1, "Today must lead with one action, not several"


@pytest.mark.parametrize("which", ["practice", "no-practice"])
def test_a_unit_has_exactly_one_primary_action(client, which):
    slug = _unit_with_practice() if which == "practice" else _unit_without_practice()
    html = client.get(f"/unit/{slug}").text
    found = PRIMARY.findall(html)
    assert len(found) == 1, f"{slug}: {len(found)} primary buttons"


def test_today_offers_at_most_one_secondary_action(client):
    assert client.get("/").text.count('class="also"') <= 1


# --------------------------------------------------------------------------
# Today keeps the roadmap behind Explore
# --------------------------------------------------------------------------


def test_the_full_module_list_lives_under_explore(client):
    html = client.get("/").text
    head, sep, explore = html.partition('<details class="explore"')
    assert sep, "Explore disclosure is missing"
    assert 'class="rowlink"' not in head, "module rows leaked above Explore"
    with Session(engine) as s:
        slugs = [m.slug for m in s.exec(select(Module))]
    for slug in slugs:
        assert f'href="/module/{slug}"' in explore, f"{slug} unreachable from Explore"


def test_explore_starts_closed(client):
    assert re.search(r'<details class="explore"\s*>', client.get("/").text)


def test_the_path_shows_every_module_once(client):
    html = client.get("/").text
    path = html[html.index('class="path"'):html.index('<details class="explore"')]
    with Session(engine) as s:
        n = len(s.exec(select(Module)).all())
    assert len(re.findall(r'class="node[ "]', path)) == n


# --------------------------------------------------------------------------
# the unit reads Learn -> Practice -> Reflect -> Finish
# --------------------------------------------------------------------------


def test_unit_sections_come_in_learning_order(client):
    html = client.get(f"/unit/{_unit_with_practice()}").text
    order = [html.index(f'id="{s}"') for s in ("learn", "practice", "reflect", "finish")]
    assert order == sorted(order)


def test_practice_is_omitted_when_a_unit_has_none(client):
    html = client.get(f"/unit/{_unit_without_practice()}").text
    assert 'id="practice"' not in html
    assert 'href="#practice"' not in html


def test_completing_comes_after_the_lesson(client):
    slug = _unit_with_practice()
    html = client.get(f"/unit/{slug}").text
    complete = html.index(f'action="/unit/{slug}/complete"')
    assert complete > html.index('id="finish"')
    assert complete > html.index('id="learn"')


def test_optional_material_is_folded_away(client):
    html = client.get(f"/unit/{_unit_with_practice()}").text
    reflect = html[html.index('id="reflect"'):html.index('id="finish"')]
    assert reflect.count('<details class="fold"') >= 3   # notes, ask, ladder (+ cards)
    assert 'action="' in reflect and "<details" in reflect


def test_completed_unit_says_so_in_finish(client):
    slug = _unit_without_practice()
    with Session(engine) as s:
        uid = s.exec(select(Unit).where(Unit.slug == slug)).one().id
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
        before = (p.status, p.completed_at) if p else None
        if p is None:
            p = Progress(unit_id=uid)
            s.add(p)
        p.status = UnitStatus.done
        s.commit()
    try:
        html = client.get(f"/unit/{slug}").text
        finish = html[html.index('id="finish"'):]
        assert "Completed" in finish
    finally:
        with Session(engine) as s:
            p = s.exec(select(Progress).where(Progress.unit_id == uid)).one()
            if before is None:
                s.delete(p)
            else:
                p.status, p.completed_at = before
            s.commit()


# --------------------------------------------------------------------------
# guard rail: nothing the backend or the scripts depend on went missing
# --------------------------------------------------------------------------


def test_unit_page_keeps_every_form_endpoint(client):
    slug = _unit_with_practice()
    html = client.get(f"/unit/{slug}").text
    actions = set(re.findall(r'<form[^>]*\baction="([^"]+)"', html))
    for expected in (
        f"/unit/{slug}/swap",
        f"/unit/{slug}/notes",
        f"/unit/{slug}/ask",
        f"/unit/{slug}/log",
        f"/unit/{slug}/complete",
    ):
        assert expected in actions, f"missing form -> {expected}"
    assert any(re.fullmatch(r"/resource/\d+/toggle", a) for a in actions)
    for method in re.findall(r'<form[^>]*\bmethod="([^"]+)"', html):
        assert method == "post"


def test_unit_page_keeps_every_script_hook(client):
    with Session(engine) as s:
        unit = s.exec(select(Unit).where(Unit.slug == "m2-pandas")).first()
    slug = unit.slug if unit else _unit_with_practice()
    html = client.get(f"/unit/{slug}").text
    for hook in ('id="open-at"', "data-watched-label", 'class="check-set"',
                 "data-check-count", "data-reveal-q", "data-knew=", 'details class="alts"'):
        assert hook in html, f"player.js / app.js hook gone: {hook}"
    assert 'id="player"' in html or 'class="offsite"' in html


def test_checkpoint_marks_start_hidden(client):
    """Regression: 'I knew it' used to be visible before the answer was."""
    css = (ROOT / "app" / "static" / "studio.css").read_text(encoding="utf-8")
    assert ".check-q [hidden] { display: none !important; }" in css


# --------------------------------------------------------------------------
# focus mode, phases, and the layer that was removed
# --------------------------------------------------------------------------


def test_focus_mode_is_offered_on_units_only(client):
    unit = client.get(f"/unit/{_unit_with_practice()}").text
    assert "data-focus-toggle" in unit and "data-focusable" in unit
    today = client.get("/").text
    assert "data-focus-toggle" not in today and "data-focusable" not in today


def test_every_module_belongs_to_a_named_phase():
    mod = templates.env.get_template("_phase.html").module
    with Session(engine) as s:
        slugs = [m.slug for m in s.exec(select(Module))]
    seen = set()
    for slug in slugs:
        key = str(mod.phase(slug)).strip()
        assert key in {"python", "data", "classic", "deep", "transformer", "systems"}, slug
        assert str(mod.phase_name(slug)).strip()
        seen.add(key)
    assert len(seen) == 6, f"every phase should be used, saw {sorted(seen)}"


@pytest.mark.parametrize("slug,phase", [
    ("m0-setup", "python"), ("m2-data", "data"), ("m4-classical", "classic"),
    ("m5-deeplearning", "deep"), ("m6-transformers", "transformer"), ("m8-mlops", "systems"),
])
def test_phase_colours_follow_the_brief(slug, phase):
    mod = templates.env.get_template("_phase.html").module
    assert str(mod.phase(slug)).strip() == phase


def test_unit_page_carries_its_module_phase(client):
    with Session(engine) as s:
        u = s.exec(select(Unit).where(Unit.slug == "m2-pandas")).first()
    if u is None:
        pytest.skip("curriculum renamed m2-pandas")
    assert 'data-phase="data"' in client.get("/unit/m2-pandas").text


def test_the_atmosphere_layer_is_gone(client):
    html = client.get("/").text
    assert "atmosphere.css" not in html
    assert 'class="grain"' not in html
    assert not (ROOT / "app" / "static" / "atmosphere.css").exists()
    assert "studio.css" in html


def test_studio_css_is_served(client):
    r = client.get("/static/studio.css")
    assert r.status_code == 200 and "[data-phase=" in r.text
