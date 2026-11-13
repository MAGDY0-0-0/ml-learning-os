"""How many SQL statements each page may run.

Pages render in well under 50 ms, so this is not about speed today. It is
about the shape of the code: a query inside a loop does not show up as slow
until there is enough data, and by then it is everywhere. The projects page
once ran 99 statements to draw seven progress bars. Counting at the engine
includes the queries the shared page chrome makes, which no route can see.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from app.db import engine

BUDGETS = {
    "/projects": 12,
    "/": 22,
    "/unit/m0-python-idioms": 22,   # six named parts, an exercise, checks
    "/unit/m2-pandas": 22,          # a segment, an exercise, checks, needs
    "/module/m2-data": 12,
    "/module/m4-classical": 12,     # unlocks a project
}


def _count(client, path: str) -> int:
    client.get(path)  # first visit may create a progress row; count the second
    n = {"c": 0}

    def tick(*_):
        n["c"] += 1

    event.listen(engine, "before_cursor_execute", tick)
    try:
        r = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", tick)
    assert r.status_code == 200, path
    return n["c"]


@pytest.mark.parametrize("path,budget", sorted(BUDGETS.items()))
def test_page_stays_within_its_statement_budget(client, path, budget):
    used = _count(client, path)
    assert used <= budget, f"{path} ran {used} SQL statements; its budget is {budget}"


def test_the_module_rail_counts_what_the_slow_way_counted():
    """nav_modules became one grouped query; its numbers must not change."""
    from app.models import Module, Progress, Unit, UnitStatus
    from app.web import nav_modules

    with Session(engine) as s:
        done = {p.unit_id for p in s.exec(select(Progress).where(Progress.status == UnitStatus.done))}
        expected = []
        for m in s.exec(select(Module).order_by(Module.order)):
            units = list(s.exec(select(Unit).where(Unit.module_id == m.id)))
            expected.append((m.slug, len(units), sum(1 for u in units if u.id in done)))
    assert [(x["slug"], x["total"], x["done"]) for x in nav_modules()] == expected


def test_loading_rubric_checks_does_not_commit_when_nothing_is_missing(client):
    from app import rubric
    from app.models import Project

    commits = {"n": 0}
    with Session(engine) as s:
        projects = list(s.exec(select(Project)))
        rubric.ensure_checks_for(s, projects)  # create anything missing first
        event.listen(s, "after_commit", lambda *_: commits.__setitem__("n", commits["n"] + 1))
        checks = rubric.ensure_checks_for(s, projects)
    assert commits["n"] == 0
    assert all(len(v) >= 14 for v in checks.values())
