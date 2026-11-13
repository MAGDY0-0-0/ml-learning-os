"""The briefing: knowing what you are walking into before you start.

Four parts are authored (why, outcomes, needs, skip_if) and the gate checks
them. Everything else -- what to watch and for how long, the exercise, the
checks -- is derived, and these tests pin that the derived numbers add up.
"""

from __future__ import annotations

import json
import re

import pytest
from sqlmodel import Session, select

from app import seed, studio
from app.db import engine
from app.models import Module, Progress, Resource, ResourceKind, Unit, UnitStatus


def _unit(slug: str) -> Unit:
    with Session(engine) as s:
        return s.exec(select(Unit).where(Unit.slug == slug)).one()


# --------------------------------------------------------------------------
# the plan: derived, and its minutes add up
# --------------------------------------------------------------------------


def _fake_unit(est=90, checkpoint=0):
    return Unit(slug="t", title="T", module_id=1, est_minutes=est,
                checkpoint_json=json.dumps([{"q": "q", "a": "a"}] * checkpoint))


def _fake_res(kind="video", minutes=60, watch=None, title="A video"):
    return Resource(unit_id=1, kind=ResourceKind(kind), title=title, url="u",
                    est_minutes=minutes, watch_json=json.dumps(watch or []))


def test_plan_without_segments_watches_the_whole_resource_and_gives_the_rest_to_trying():
    plan = studio.build_plan(_fake_unit(90), _fake_res(minutes=60), [], 0)
    assert [(i["kind"], i["minutes"]) for i in plan] == [("learn", 60), ("try", 30)]
    assert plan[0]["verb"] == "Watch"


def test_plan_lists_each_segment_by_its_own_title():
    watch = [{"title": "Part A", "from": 0, "to": 600}, {"title": "Part B", "from": 1200, "to": 2100}]
    plan = studio.build_plan(_fake_unit(60), _fake_res(minutes=300, watch=watch), [], 0)
    learn = [i for i in plan if i["kind"] == "learn"]
    assert [(i["title"], i["minutes"]) for i in learn] == [("Part A", 10), ("Part B", 15)]
    assert sum(i["minutes"] for i in plan) == 60


def test_plan_gives_the_exercise_what_is_left_and_counts_its_checks():
    exercises = [{"title": "Idioms drill", "slug": "d", "checks": 11}]
    plan = studio.build_plan(_fake_unit(110, checkpoint=3), _fake_res(minutes=50), exercises, 3)
    assert [(i["kind"], i["minutes"]) for i in plan] == [("learn", 50), ("practice", 54), ("check", 6)]
    practice = plan[1]
    assert practice["title"] == "Idioms drill" and "11 automatic checks" in practice["detail"]


def test_reading_is_read_not_watched():
    plan = studio.build_plan(_fake_unit(45), _fake_res(kind="paper", minutes=45), [], 0)
    assert plan == [{"kind": "learn", "verb": "Read", "title": "A video", "minutes": 45}]


def test_summary_parts_name_what_a_row_asks_of_you():
    plan = studio.build_plan(_fake_unit(110, checkpoint=3), _fake_res(minutes=50),
                             [{"title": "x", "slug": "x", "checks": 1}], 3)
    assert studio.summary_parts(plan, 1, 3) == ["Watch 50 min", "1 exercise", "3 checks"]


def test_every_units_plan_adds_up_to_the_minutes_it_claims():
    """The unit's number has to be the time it really asks for.

    Learning takes what the main resource or its segments take, checks take
    two minutes each, and the rest goes to practice. If learning and checks
    already exceed the unit's total, the total is not honest.
    """
    with Session(engine) as s:
        units = list(s.exec(select(Unit)))
    briefs = studio.briefs_for(units)
    wrong = {u.slug: (briefs[u.id]["total"], u.est_minutes)
             for u in units if briefs[u.id]["total"] != u.est_minutes}
    assert not wrong, f"plan total != est_minutes: {wrong}"


def test_briefs_for_a_whole_module_cost_a_fixed_number_of_queries():
    from sqlalchemy import event

    count = {"n": 0}

    def tick(*_):
        count["n"] += 1

    with Session(engine) as s:
        many = list(s.exec(select(Unit).order_by(Unit.id)))
    few = many[-8:]   # the last units all name a unit they need, like the whole set
    event.listen(engine, "before_cursor_execute", tick)
    try:
        studio.briefs_for(few)
        n_few, count["n"] = count["n"], 0
        studio.briefs_for(many)
        n_many = count["n"]
    finally:
        event.remove(engine, "before_cursor_execute", tick)
    assert n_many == n_few, f"{len(few)} units took {n_few} queries, {len(many)} took {n_many}"
    assert n_many <= 6


# --------------------------------------------------------------------------
# the gate: the authored half
# --------------------------------------------------------------------------


def _briefed(**extra):
    unit = {"slug": "b", "why": "Used in Project 1.",
            "outcomes": ["Do one thing", "Do another thing"]}
    unit.update(extra)
    return unit


def test_a_unit_without_why_fails():
    errors: list[str] = []
    seed.validate_briefing(_briefed(why=""), set(), errors)
    assert any("needs a `why`" in e for e in errors)


@pytest.mark.parametrize("outcomes", [[], ["only one"], ["a", "b", "c", "d", "e"]])
def test_a_unit_needs_two_to_four_outcomes(outcomes):
    errors: list[str] = []
    seed.validate_briefing(_briefed(outcomes=outcomes), set(), errors)
    assert any("outcomes" in e for e in errors), errors


def test_an_outcome_is_short():
    errors: list[str] = []
    seed.validate_briefing(_briefed(outcomes=["x" * 91, "fine"]), set(), errors)
    assert any("91 characters" in e for e in errors)


def test_needs_must_name_an_earlier_unit():
    errors: list[str] = []
    seed.validate_briefing(_briefed(needs=["m9-later"]), {"m0-env"}, errors)
    assert any("not a unit that comes before" in e for e in errors)
    errors = []
    seed.validate_briefing(_briefed(needs=["m0-env"]), {"m0-env"}, errors)
    assert errors == []


def test_skip_if_without_checks_would_never_show():
    errors: list[str] = []
    seed.validate_briefing(_briefed(skip_if="You know this."), set(), errors)
    assert any("never be shown" in e for e in errors)
    errors = []
    seed.validate_briefing(_briefed(skip_if="You know this.", checkpoint=[{"q": "q", "a": "a"}]),
                           set(), errors)
    assert errors == []


@pytest.mark.parametrize("n", [2, 6])
def test_a_module_needs_three_to_five_outcomes(n):
    modules = [{"slug": "mx", "outcomes": [f"o{i}" for i in range(n)], "units": []}]
    assert any("outcomes" in e for e in seed.validate(modules))


def test_the_real_curriculum_is_fully_briefed():
    with Session(engine) as s:
        for u in s.exec(select(Unit)):
            assert u.why and 2 <= len(json.loads(u.outcomes_json)) <= 4, u.slug
        for m in s.exec(select(Module)):
            assert 3 <= len(json.loads(m.outcomes_json)) <= 5, m.slug


# --------------------------------------------------------------------------
# the pages
# --------------------------------------------------------------------------


def _brief_html(html: str) -> str:
    start = html.index('<details class="brief"')
    return html[start:html.index("</details>", start)]


@pytest.fixture
def fresh_unit():
    """m0-python-idioms with no progress, put back afterwards."""
    u = _unit("m0-python-idioms")
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == u.id)).first()
        saved = (p.status, p.minutes_logged) if p else None
        if p:
            p.status, p.minutes_logged = UnitStatus.not_started, 0
            s.commit()
    yield u
    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == u.id)).first()
        if saved is None:
            if p:
                s.delete(p)
        else:
            p.status, p.minutes_logged = saved
        s.commit()


def test_a_first_visit_opens_the_briefing_above_the_player(client, fresh_unit):
    html = client.get(f"/unit/{fresh_unit.slug}").text
    brief = _brief_html(html)
    assert re.match(r'<details class="brief" open>', brief)
    assert html.index('class="brief"') < html.index('id="player"')
    assert "By the end you can" in brief and "What you'll do" in brief
    for outcome in json.loads(fresh_unit.outcomes_json):
        assert outcome.split(",")[0] in brief.replace("&#39;", "'")
    # exercise and checks both appear as steps, with minutes
    assert "Practise" in brief and "Idioms drill" in brief and "Check" in brief
    # this unit has checks and a skip_if: the skip jumps to them
    assert 'href="#finish" data-step-link="finish"' in brief


def test_the_briefing_folds_once_you_have_started(client, fresh_unit):
    from app.web import get_progress

    with Session(engine) as s:
        p = get_progress(s, fresh_unit.id)
        p.minutes_logged = 12
        s.commit()
    brief = _brief_html(client.get(f"/unit/{fresh_unit.slug}").text)
    assert re.match(r'<details class="brief">', brief), brief[:80]
    assert "Before you start" in brief  # still one click away


def test_a_unit_with_segments_lists_the_segment_not_the_whole_video(client):
    brief = _brief_html(client.get("/unit/m5-training-loop").text)
    assert "Write the training and testing loops" in brief
    assert "1 h 35 min" in brief and "25 h" not in brief


def test_a_unit_without_exercise_or_checks_shows_neither(client):
    brief = _brief_html(client.get("/unit/m1-fastapi-basics").text)
    assert 'data-kind="practice"' not in brief and 'data-kind="check"' not in brief
    assert 'data-kind="try"' in brief
    assert 'data-step-link="finish"' not in brief  # nothing to skip to


def test_needs_are_linked_with_their_state(client):
    brief = _brief_html(client.get("/unit/m4-leakage-audit").text)
    assert 'href="/unit/m2-rigor-splits"' in brief and 'href="/unit/m4-sklearn-api"' in brief


def test_the_module_page_says_what_it_asks_and_where_to_start(client):
    html = client.get("/module/m2-data").text
    assert "After this module you can" in html
    assert re.search(r"3 units · \d+ h", html)
    assert re.search(r'<a class="btn fill" href="/unit/m2-[a-z-]+">', html)
    # rows show what they ask of you, not how many alternates they carry
    assert " resources</span>" not in html
    assert "1 exercise" in html and "3 checks" in html


def test_the_module_page_names_the_project_it_unlocks(client):
    html = client.get("/module/m4-classical").text
    assert 'class="mod-proj" href="/project/p1-tabular"' in html


def test_today_shows_what_each_unit_asks(client):
    html = client.get("/").text
    meta = re.search(r'<span class="hero-meta">(.*?)</span>\s*</div>', html, re.S)
    assert meta and re.search(r"(Watch|Read) ", meta.group(1))
    assert '<span class="s">' in html
    assert re.search(r'class="m">\d+ units? · ', html) or re.search(r"units · \d", html)
