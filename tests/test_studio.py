"""The studio redesign: Today, lesson mode, and the helpers behind them.

Three kinds of test:

* the read-only helpers in app/studio.py, checked against the real curriculum
  (next unit, module position, exercise check counts, practice status);
* honesty — every number the screens show is derived from the database or the
  exercise files, and a value that does not exist yet is omitted rather than
  invented;
* guard rails — every form, endpoint and script hook the backend and the JS
  depend on is still on the page, so a layout change cannot break progress.

The database is the learner's own, so every test that writes restores what it
touched (see the `restoring` helpers).
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import seed, studio  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Assignment, Card, CheckpointAnswer, Module, Progress, Project, Submission, Unit, UnitStatus,
)
from app.web import due_count, notes_path, now_utc  # noqa: E402

PHASE_KEYS = {"python", "data", "classic", "deep", "transformer", "systems"}


@pytest.fixture(scope="module", autouse=True)
def seeded():
    init_db()
    with Session(engine) as s:
        if s.exec(select(Unit)).first() is None:
            seed.seed(seed.load_modules())


@pytest.fixture(scope="module")
def client():
    return TestClient(app, follow_redirects=False)


def _unit(slug: str) -> Unit:
    with Session(engine) as s:
        return s.exec(select(Unit).where(Unit.slug == slug)).one()


def _units_in_order() -> list[Unit]:
    with Session(engine) as s:
        out = []
        for m in s.exec(select(Module).order_by(Module.order)):
            out += list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
        return out


def _unit_with(kind: str) -> Unit:
    """A unit that has (or lacks) an exercise / checkpoints."""
    with Session(engine) as s:
        with_ex = {a.unit_id for a in s.exec(select(Assignment))}
        for u in _units_in_order():
            cp = u.checkpoint_json not in ("", "[]")
            if kind == "exercise+checks" and u.id in with_ex and cp:
                return u
            if kind == "no-exercise" and u.id not in with_ex:
                return u
            if kind == "no-checks" and not cp:
                return u
    raise LookupError(kind)


# --------------------------------------------------------------------------
# restoring helpers: tests may write, but they always put things back
# --------------------------------------------------------------------------


@contextmanager
def restoring_progress(unit_id: int):
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
        before = None if p is None else (p.status, p.minutes_logged, p.started_at, p.completed_at)
    try:
        yield
    finally:
        with Session(engine) as s:
            p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
            if before is None:
                if p is not None:
                    s.delete(p)
            else:
                p.status, p.minutes_logged, p.started_at, p.completed_at = before
            s.commit()


def set_progress(unit_id: int, status: UnitStatus, minutes: int = 0):
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
        if p is None:
            p = Progress(unit_id=unit_id)
            s.add(p)
        p.status, p.minutes_logged = status, minutes
        s.commit()


@contextmanager
def restoring_answers(unit_id: int):
    with Session(engine) as s:
        keep = {a.id for a in s.exec(select(CheckpointAnswer).where(CheckpointAnswer.unit_id == unit_id))}
    try:
        yield
    finally:
        with Session(engine) as s:
            for a in s.exec(select(CheckpointAnswer).where(CheckpointAnswer.unit_id == unit_id)):
                if a.id not in keep:
                    s.delete(a)
            s.commit()


def answer(unit_id: int, idxs, knew: bool = True):
    with Session(engine) as s:
        for i in idxs:
            s.add(CheckpointAnswer(unit_id=unit_id, idx=i, knew=knew))
        s.commit()


@contextmanager
def restoring_submissions(assignment_id: int):
    with Session(engine) as s:
        keep = {x.id for x in s.exec(select(Submission).where(Submission.assignment_id == assignment_id))}
    try:
        yield
    finally:
        with Session(engine) as s:
            for x in s.exec(select(Submission).where(Submission.assignment_id == assignment_id)):
                if x.id not in keep:
                    s.delete(x)
            s.commit()


# --------------------------------------------------------------------------
# helpers: phases and artwork
# --------------------------------------------------------------------------


def test_every_module_belongs_to_a_named_phase():
    with Session(engine) as s:
        slugs = [m.slug for m in s.exec(select(Module))]
    seen = {studio.phase(slug) for slug in slugs}
    assert seen == PHASE_KEYS, "every phase colour should be in use"
    for slug in slugs:
        assert studio.phase_name(slug)


@pytest.mark.parametrize("slug,phase", [
    ("m0-setup", "python"), ("m1-build", "python"), ("m2-data", "data"), ("m3-math", "data"),
    ("m4-classical", "classic"), ("m5-deeplearning", "deep"), ("m6-transformers", "transformer"),
    ("m7-llm", "transformer"), ("m8-mlops", "systems"), ("m9-portfolio", "systems"),
])
def test_phase_colours_follow_the_brief(slug, phase):
    assert studio.phase(slug) == phase


def test_phase_art_is_self_contained_and_namespaced():
    a = str(studio.phase_art("m2-data", "one"))
    b = str(studio.phase_art("m2-data", "two"))
    assert a.startswith("<svg") and a.endswith("</svg>")
    assert 'id="pa-one1"' in a and 'id="pa-two1"' in b, "gradient ids must be unique per key"
    assert "http" not in a.replace("http://www.w3.org", ""), "no external references"
    assert studio.PALETTE["data"][1] in a, "drawn in the phase's own colours"


def test_icon_sprite_is_generated_from_the_same_glyphs(client):
    html = client.get("/").text
    for key, d in studio.GLYPHS.items():
        assert f'<g id="ph-{key}">{d}</g>' in html


@pytest.mark.parametrize("minutes,text", [(0, "0 min"), (45, "45 min"), (60, "1 h"), (154, "2 h 34 min")])
def test_fmt_minutes(minutes, text):
    assert studio.fmt_minutes(minutes) == text


# --------------------------------------------------------------------------
# helpers: derived facts, against the real curriculum
# --------------------------------------------------------------------------


def test_next_unit_follows_curriculum_order_across_modules():
    units = _units_in_order()
    for here, there in zip(units, units[1:]):
        nxt = studio.next_unit(here)
        assert nxt is not None and nxt["unit"].id == there.id, here.slug
        assert nxt["module"].id == there.module_id
    assert studio.next_unit(units[-1]) is None, "nothing after the last unit"


def test_module_position_counts_real_progress():
    u = _unit("m2-pandas")
    before = studio.module_position(u)
    assert before["total"] == len([x for x in _units_in_order() if x.module_id == u.module_id])
    assert 1 <= before["index"] <= before["total"]
    with restoring_progress(u.id):
        set_progress(u.id, UnitStatus.done)
        after = studio.module_position(u)
    assert after["done"] == before["done"] + (0 if u.id in before["done_ids"] else 1)
    assert u.id in after["done_ids"]


def test_count_checks_matches_the_test_files_for_every_exercise():
    with Session(engine) as s:
        assignments = list(s.exec(select(Assignment)))
    assert assignments
    for a in assignments:
        d = ROOT / a.tests_path
        expected = sum(len(re.findall(r"^def test_\w+", f.read_text(encoding="utf-8"), re.M))
                       for f in d.glob("test_*.py"))
        assert studio.count_checks(a.tests_path) == expected > 0, a.slug


def test_count_checks_counts_class_tests_and_survives_missing_dirs(tmp_path):
    (tmp_path / "test_x.py").write_text(
        "def test_a(): pass\nclass TestB:\n    def test_c(self): pass\n    def helper(self): pass\n"
        "def helper(): pass\n", encoding="utf-8")
    assert studio.count_checks(str(tmp_path)) == 2
    assert studio.count_checks(str(tmp_path / "nope")) == 0
    assert studio.count_checks("") == 0


def test_practice_status_reports_real_runs_only():
    u = _unit_with("exercise+checks")
    with Session(engine) as s:
        a = s.exec(select(Assignment).where(Assignment.unit_id == u.id)).first()
    static = studio.count_checks(a.tests_path)
    with restoring_submissions(a.id):
        with Session(engine) as s:
            for x in s.exec(select(Submission).where(Submission.assignment_id == a.id)):
                s.delete(x)
            s.commit()
        p = studio.practice_status(u.id)[0]
        assert (p["runs"], p["last"], p["best"], p["passed_all"]) == (0, None, None, False)
        assert p["checks"] == static

        with Session(engine) as s:
            s.add(Submission(assignment_id=a.id, path="x", tests_passed=3, tests_total=static))
            s.commit()
        p = studio.practice_status(u.id)[0]
        assert p["runs"] == 1 and p["last"].tests_passed == 3 and not p["passed_all"]

        with Session(engine) as s:
            s.add(Submission(assignment_id=a.id, path="y", tests_passed=static, tests_total=static))
            s.commit()
        p = studio.practice_status(u.id)[0]
        assert p["runs"] == 2 and p["best"].tests_passed == static and p["passed_all"]


# --------------------------------------------------------------------------
# Today
# --------------------------------------------------------------------------


def _hero_actions(html: str) -> list[str]:
    acts = html[html.index('class="hero-acts"'):]
    acts = acts[:acts.index("</div>")]
    return re.findall(r"<(?:a|button)\b[^>]*>", acts)


def test_hero_has_exactly_two_actions_and_the_review_count_is_real(client):
    html = client.get("/").text
    due = due_count()
    actions = _hero_actions(html)
    if due:
        assert len(actions) == 2
        assert 'href="/review"' in actions[1]
        assert f"Review {due} card" in html
    else:
        assert len(actions) == 1


def test_hero_has_one_action_when_nothing_is_due(client):
    with Session(engine) as s:
        cards = list(s.exec(select(Card)))
        saved = {c.id: c.due_at for c in cards}
        for c in cards:
            c.due_at = now_utc() + timedelta(days=30)
        s.commit()
    try:
        html = client.get("/").text
        assert len(_hero_actions(html)) == 1
        assert 'href="/review"' not in html[html.index('class="hero-acts"'):html.index('class="hero-where"')]
    finally:
        with Session(engine) as s:
            for c in s.exec(select(Card)):
                if c.id in saved:
                    c.due_at = saved[c.id]
            s.commit()


def test_time_estimate_is_plain_text_not_a_button(client):
    html = client.get("/").text
    meta = re.search(r'<span class="hero-meta">(.*?)</span>\s*</div>', html, re.S)
    assert meta and "About" in meta.group(1)
    assert "<a " not in meta.group(1) and "<button" not in meta.group(1)


def test_start_becomes_continue_once_the_unit_is_in_progress(client):
    first_open = next(u for u in _units_in_order()
                      if not _is_done(u.id))
    with restoring_progress(first_open.id):
        set_progress(first_open.id, UnitStatus.not_started)
        assert re.search(r"</svg> Start</a>", client.get("/").text)
        set_progress(first_open.id, UnitStatus.in_progress, minutes=23)
        html = client.get("/").text
        assert re.search(r"</svg> Continue</a>", html)
        assert "23 min logged" in html


def _is_done(unit_id: int) -> bool:
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
        return bool(p and p.status == UnitStatus.done)


def test_posters_are_the_current_module_with_one_up_next(client):
    html = client.get("/").text
    current = next(u for u in _units_in_order() if not _is_done(u.id))
    units = [u for u in _units_in_order() if u.module_id == current.module_id]
    posters = re.findall(r'<li class="poster[^"]*">', html)
    assert len(posters) == len(units)
    assert sum('now' in p for p in posters) == 1
    for i, u in enumerate(units, start=1):
        assert f'href="/unit/{u.slug}"' in html
        assert f">{i:02d}</span>" in html
        assert studio.fmt_minutes(u.est_minutes) in html


def test_road_ahead_shows_later_modules_and_real_project_distances(client):
    html = client.get("/").text
    road = html[html.index('class="road"'):html.index('id="explore"')]
    units = _units_in_order()
    current = next(u for u in units if not _is_done(u.id))
    with Session(engine) as s:
        mods = list(s.exec(select(Module).order_by(Module.order)))
        projects = list(s.exec(select(Project)))
    order = [m.id for m in mods]
    later = [m for m in mods if order.index(m.id) > order.index(current.module_id)]
    assert len(re.findall(r'<li class="module-tile"', road)) == len(later)
    for m in later:
        assert f'href="/module/{m.slug}"' in road
    # units away = units through the gate module - units done, as the dashboard counts it
    done = sum(_is_done(u.id) for u in units)
    for p in projects:
        if p.completed:
            continue
        gate_idx = next(i for i, m in enumerate(mods) if m.slug == p.module_slug)
        through = sum(1 for u in units if order.index(u.module_id) <= gate_idx)
        away = max(0, through - done)
        assert f'href="/project/{p.slug}"' in road
        if away:
            assert f"{away} unit{'s' if away != 1 else ''} away" in road, p.slug


def test_explore_holds_the_full_system_and_starts_closed(client):
    html = client.get("/").text
    assert re.search(r'<details class="explore" id="explore">', html), "closed by default"
    explore = html[html.index('id="explore"'):]
    with Session(engine) as s:
        for m in s.exec(select(Module)):
            assert f'href="/module/{m.slug}"' in explore
    for link in ('href="/library"', 'href="/tour"', 'href="/backup"'):
        assert link in explore


# --------------------------------------------------------------------------
# lesson mode
# --------------------------------------------------------------------------


def test_lesson_mode_hides_the_site_navigation(client):
    html = client.get("/unit/m2-pandas").text
    assert 'class="shell"' not in html and 'class="tabs' not in html
    assert '<header class="lessonbar">' in html
    assert re.search(r'<a class="pill glass back" href="/">', html)
    assert 'class="tracker"' in html and "data-focus-toggle" in html
    assert 'class="nextbar' in html


def test_lesson_sections_come_in_order_with_one_next_action_each(client):
    u = _unit_with("exercise+checks")
    html = client.get(f"/unit/{u.slug}").text
    ids = ["learn", "practice", "reflect", "finish"]
    pos = [html.index(f'<section class="step" id="{i}"') for i in ids]
    assert pos == sorted(pos)
    for here, nxt in zip(ids, ids[1:]):
        section = html[html.index(f'id="{here}"'):html.index(f'id="{nxt}"', html.index(f'id="{here}"') + 1)]
        nexts = re.findall(r'<a class="btn fill xl next" href="#(\w+)"', section)
        assert nexts == [nxt], (here, nexts)
    assert f'action="/unit/{u.slug}/complete"' in html[html.index('id="finish"'):]


def test_practice_is_omitted_when_a_unit_has_no_exercise(client):
    u = _unit_with("no-exercise")
    html = client.get(f"/unit/{u.slug}").text
    assert 'id="practice"' not in html
    assert "Step 1 of 3" in html


def test_practice_shows_the_real_check_count_and_never_hidden_tests(client):
    u = _unit_with("exercise+checks")
    html = client.get(f"/unit/{u.slug}").text
    p = studio.practice_status(u.id)[0]
    practice = html[html.index('id="practice"'):html.index('id="reflect"')]
    if p["last"] is None:
        assert f"Not attempted yet · {p['checks']} check" in practice
    assert f"Run the {p['checks']} check" in practice
    for tpl in (ROOT / "app" / "templates").glob("*.html"):
        assert "hidden test" not in tpl.read_text(encoding="utf-8").lower(), tpl.name


def test_completion_is_locked_until_every_checkpoint_is_attempted(client):
    u = _unit_with("exercise+checks")
    total = len(__import__("json").loads(u.checkpoint_json))
    with restoring_answers(u.id):
        with Session(engine) as s:
            for a in s.exec(select(CheckpointAnswer).where(CheckpointAnswer.unit_id == u.id)):
                s.delete(a)
            s.commit()
        bar = _finish_bar(client.get(f"/unit/{u.slug}").text)
        assert re.search(r"<button[^>]*data-complete[^>]*disabled", bar)
        assert f"Answer <span data-check-left>{total}</span> more" in bar
        assert f"0</span> of {total} checks answered" in bar

        answer(u.id, range(total - 1))
        bar = _finish_bar(client.get(f"/unit/{u.slug}").text)
        assert re.search(r"<button[^>]*data-complete[^>]*disabled", bar)
        assert "Answer <span data-check-left>1</span> more" in bar

        answer(u.id, [total - 1])
        bar = _finish_bar(client.get(f"/unit/{u.slug}").text)
        assert not re.search(r"<button[^>]*data-complete[^>]*disabled", bar)
        assert re.search(r"<span class=\"hint\" data-check-hint\s+hidden", bar)
        # the server stays the authority either way
        assert f"{total}</span> of {total} checks answered" in bar


def test_a_unit_without_checkpoints_can_be_completed_straight_away(client):
    u = _unit_with("no-checks")
    bar = _finish_bar(client.get(f"/unit/{u.slug}").text)
    assert "No checks in this unit" in bar
    assert not re.search(r"<button[^>]*data-complete[^>]*disabled", bar)


def _finish_bar(html: str) -> str:
    return html[html.index('class="nextbar finish-bar"'):]


def test_completion_screen_shows_only_real_facts(client):
    u = _unit_with("exercise+checks")
    total = len(__import__("json").loads(u.checkpoint_json))
    with restoring_progress(u.id), restoring_answers(u.id):
        with Session(engine) as s:
            for a in s.exec(select(CheckpointAnswer).where(CheckpointAnswer.unit_id == u.id)):
                s.delete(a)
            s.commit()
        answer(u.id, range(total - 1), knew=True)
        answer(u.id, [total - 1], knew=False)

        set_progress(u.id, UnitStatus.done, minutes=0)
        html = client.get(f"/unit/{u.slug}").text
        done = html[html.index('id="done"'):html.index('id="learn"')]
        assert "Unit complete" in done
        assert "studied" not in done, "no time logged -> no time shown"
        assert f"{total} of {total}" in done and "1 added to review" in done
        nxt = studio.next_unit(u)
        assert nxt["unit"].title in done and f'href="/unit/{nxt["unit"].slug}"' in done
        pos = studio.module_position(u)
        assert f"{pos['done']} of {pos['total']} done" in done

        set_progress(u.id, UnitStatus.done, minutes=94)
        done = client.get(f"/unit/{u.slug}").text
        assert "1 h 34 min</b><span>studied" in done


def test_completion_screen_after_the_last_unit_points_to_projects(client):
    last = _units_in_order()[-1]
    with restoring_progress(last.id):
        set_progress(last.id, UnitStatus.done)
        html = client.get(f"/unit/{last.slug}").text
        done = html[html.index('id="done"'):html.index('id="learn"')]
        assert "That was the last unit" in done and 'href="/projects"' in done


def test_completion_screen_only_appears_once_done(client):
    u = _unit_with("no-exercise")
    with restoring_progress(u.id):
        set_progress(u.id, UnitStatus.in_progress)
        assert 'id="done"' not in client.get(f"/unit/{u.slug}").text


def test_notes_count_on_the_completion_screen_is_the_real_word_count(client):
    u = _unit_with("no-exercise")
    path = notes_path(u.slug)
    before = path.read_text(encoding="utf-8") if path.is_file() else None
    try:
        path.write_text("one two three four five", encoding="utf-8")
        with restoring_progress(u.id):
            set_progress(u.id, UnitStatus.done)
            done = client.get(f"/unit/{u.slug}").text
            assert "<b>5</b><span>words of notes</span>" in done
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(before, encoding="utf-8")


# --------------------------------------------------------------------------
# guard rails
# --------------------------------------------------------------------------


def test_unit_page_keeps_every_form_endpoint(client):
    u = _unit_with("exercise+checks")
    html = client.get(f"/unit/{u.slug}").text
    actions = set(re.findall(r'<form[^>]*\baction="([^"]+)"', html))
    for expected in (f"/unit/{u.slug}/notes", f"/unit/{u.slug}/ask", f"/unit/{u.slug}/log",
                     f"/unit/{u.slug}/complete"):
        assert expected in actions, expected
    assert any(re.fullmatch(r"/resource/\d+/toggle", a) for a in actions)
    for method in re.findall(r'<form[^>]*\bmethod="([^"]+)"', html):
        assert method == "post"


def test_unit_page_keeps_every_script_hook(client):
    html = client.get("/unit/m2-pandas").text
    for hook in ('id="open-at"', "data-watched-label", 'class="check-set"', "data-check-count",
                 "data-reveal-q", "data-knew=", 'id="notes"', "data-quiet=", "data-step-link=",
                 "data-lesson-root"):
        assert hook in html, hook
    assert 'id="player"' in html or 'class="offsite"' in html


def test_focus_mode_is_offered_in_lessons_only(client):
    assert "data-focus-toggle" in client.get("/unit/m2-pandas").text
    today = client.get("/").text
    assert "data-focus-toggle" not in today and "data-focusable" not in today


def test_inter_is_bundled_for_offline_use():
    css = (ROOT / "app" / "static" / "fonts.css").read_text(encoding="utf-8")
    for f in ("inter-latin.woff2", "inter-latin-ext.woff2"):
        assert f"/static/fonts/{f}" in css
        assert (ROOT / "app" / "static" / "fonts" / f).read_bytes()[:4] == b"wOF2"
    assert (ROOT / "app" / "static" / "fonts" / "Inter-OFL.txt").is_file()


def test_no_image_files_to_maintain():
    static = ROOT / "app" / "static"
    images = [p for p in static.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}]
    assert images == []


def test_the_atmosphere_layer_is_gone(client):
    html = client.get("/").text
    assert "atmosphere.css" not in html and 'class="grain"' not in html
    assert not (ROOT / "app" / "static" / "atmosphere.css").exists()


def test_checkpoint_marks_start_hidden():
    """Regression: 'I knew it' used to be visible before the answer was."""
    css = (ROOT / "app" / "static" / "studio.css").read_text(encoding="utf-8")
    assert ".check-q [hidden] { display: none !important; }" in css
