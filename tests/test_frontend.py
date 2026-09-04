"""Tests for the shell: the player endpoints, the PDF route, and the mark.

The frontend rewrite added three things that can fail silently — a player that
posts state in the background, a route that serves files off disk, and a rail
whose state is derived rather than passed in. Each one of those is exactly the
kind of thing that breaks without anybody noticing, so each one is pinned here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import library  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Progress, Resource, ResourceState, StudySession, Unit,
)
from app.web import active_module, templates, youtube_ids  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
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
