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


# --------------------------------------------------------------------------
# review runs as a session, not one page load per card
# --------------------------------------------------------------------------


@pytest.fixture
def restore_deck():
    """Grading mutates the real deck's schedule; snapshot and put it back."""
    from app.models import Card

    with Session(engine) as s:
        before = {
            c.id: (c.ease, c.interval_days, c.repetitions, c.lapses, c.due_at)
            for c in s.exec(select(Card))
        }
    yield
    with Session(engine) as s:
        for c in s.exec(select(Card)):
            if c.id in before:
                c.ease, c.interval_days, c.repetitions, c.lapses, c.due_at = before[c.id]
        s.commit()


def test_grading_returns_the_next_card(client, restore_deck):
    from app.models import Card

    with Session(engine) as s:
        first = s.exec(select(Card)).first()
        first_id, first_front = first.id, first.front

    d = client.post(f"/api/review/{first_id}", json={"quality": 4}).json()
    assert d["ok"] is True
    assert d["card"] is not None
    assert d["card"]["front"] != first_front, "must hand back a different card"
    assert isinstance(d["remaining"], int)


def test_grading_decrements_the_queue(client, restore_deck):
    from app.models import Card

    with Session(engine) as s:
        c = s.exec(select(Card)).first()
        cid = c.id
    before = len(client.get("/review").text)  # page renders
    d = client.post(f"/api/review/{cid}", json={"quality": 5}).json()
    d2 = client.post(f"/api/review/{d['card']['id']}", json={"quality": 5}).json()
    assert d2["remaining"] < d["remaining"]
    assert before > 0


@pytest.mark.parametrize("bad", [-1, 6, "x", None])
def test_bad_grades_are_refused(client, restore_deck, bad):
    from app.models import Card

    with Session(engine) as s:
        cid = s.exec(select(Card)).first().id
    d = client.post(f"/api/review/{cid}", json={"quality": bad}).json()
    assert d["ok"] is False


def test_the_plain_form_still_works_without_javascript(client, restore_deck):
    """The page must remain usable with scripting off."""
    from app.models import Card

    with Session(engine) as s:
        cid = s.exec(select(Card)).first().id
    r = client.post(f"/review/{cid}", data={"quality": "4"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/review"


# --------------------------------------------------------------------------
# swap preferences: recorded since day one, read back for the first time
# --------------------------------------------------------------------------


@pytest.fixture
def clean_preferences():
    from app.models import ActiveResource, ResourcePreference

    yield
    with Session(engine) as s:
        for p in s.exec(select(ResourcePreference)):
            s.delete(p)
        for a in s.exec(select(ActiveResource)):
            s.delete(a)
        s.commit()


def test_swap_reasons_are_counted(client, a_unit, clean_preferences):
    from app.models import ResourcePreference, SwapReason
    from app.web import swap_reasons

    with Session(engine) as s:
        _, _, rid = a_unit
        s.add(ResourcePreference(resource_id=rid, reason=SwapReason.too_slow))
        s.add(ResourcePreference(resource_id=rid, reason=SwapReason.too_slow))
        s.add(ResourcePreference(resource_id=rid, reason=SwapReason.boring))
        s.commit()

    assert swap_reasons() == [("too_slow", 2), ("boring", 1)]


def test_alternates_you_rejected_are_offered_last(client, clean_preferences):
    """Three strikes against a teacher should stop it being suggested first."""
    from app.models import ResourcePreference, SwapReason
    from app.web import ordered_resources, rejected_counts, split_alternatives

    with Session(engine) as s:
        # Any unit with two same-format alternates will do; pick one rather
        # than hardcoding a slug whose resources may be re-curated later.
        slug = None
        for u in s.exec(select(Unit)):
            if len(split_alternatives(ordered_resources(s, u))[0]) >= 2:
                slug = u.slug
                break
        assert slug, "no unit has two same-format alternates"

        u = s.exec(select(Unit).where(Unit.slug == slug)).first()
        alts = split_alternatives(ordered_resources(s, u))[0]
        unwanted = alts[0].id
        for _ in range(3):
            s.add(ResourcePreference(resource_id=unwanted, reason=SwapReason.too_slow))
        s.commit()

    with Session(engine) as s:
        u = s.exec(select(Unit).where(Unit.slug == slug)).first()
        alts = split_alternatives(ordered_resources(s, u))[0]
        rej = rejected_counts()
        alts.sort(key=lambda r: rej.get(r.id, 0))
        assert alts[-1].id == unwanted, "the thrice-rejected one must sink to the bottom"


def test_dashboard_shows_the_pattern(client, a_unit, clean_preferences):
    from app.models import ResourcePreference, SwapReason

    with Session(engine) as s:
        _, _, rid = a_unit
        for _ in range(2):
            s.add(ResourcePreference(resource_id=rid, reason=SwapReason.bad_audio))
        s.commit()

    html = client.get("/").text
    assert "What doesn't work for you" in html
    assert "bad audio" in html


def test_dashboard_hides_the_panel_when_nothing_swapped(client, clean_preferences):
    """An empty panel about data you have not generated is noise."""
    assert "What doesn't work for you" not in client.get("/").text


# --------------------------------------------------------------------------
# nothing the interface needs may come from the network
# --------------------------------------------------------------------------


def test_no_template_pulls_a_stylesheet_or_font_from_the_internet():
    """The app runs on one laptop with no account and no network.

    Fonts used to come from Google on every cold start, which meant an offline
    first run silently fell back to system faces and lost the type system.
    They are vendored now; this stops them drifting back out.
    """
    offenders = []
    for tpl in (ROOT / "app" / "templates").glob("*.html"):
        text = tpl.read_text(encoding="utf-8")
        for host in ("fonts.googleapis.com", "fonts.gstatic.com", "cdnjs.cloudflare.com",
                     "cdn.jsdelivr.net", "unpkg.com"):
            if host in text:
                offenders.append(f"{tpl.name} -> {host}")
    assert not offenders, f"external assets in templates: {offenders}"


def test_every_vendored_font_file_exists_and_is_real():
    import re

    css = (ROOT / "app" / "static" / "fonts.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\('(/static/fonts/[^']+)'\)", css)
    assert len(urls) == 6, f"expected 6 faces, found {len(urls)}"
    for u in urls:
        f = ROOT / "app" / u.removeprefix("/")
        assert f.is_file(), f"missing {u}"
        # woff2 files start with the magic word 'wOF2'
        assert f.read_bytes()[:4] == b"wOF2", f"{u} is not a woff2"


def test_font_faces_cover_all_three_families():
    css = (ROOT / "app" / "static" / "fonts.css").read_text(encoding="utf-8")
    for family in ("Bricolage Grotesque", "Geist", "Geist Mono"):
        assert f"font-family: '{family}'" in css


def test_the_page_links_the_local_font_stylesheet(client):
    html = client.get("/").text
    assert "/static/fonts.css" in html


# --------------------------------------------------------------------------
# backup — the only copy of your progress
# --------------------------------------------------------------------------


@pytest.fixture
def restorable():
    """Snapshot everything backup touches, and put it all back."""
    from app import backup as bk

    snapshot = bk.export_state()
    notes_before = {p.name for p in (ROOT / "notes").glob("*.md")} if (ROOT / "notes").is_dir() else set()
    yield
    bk.import_state(snapshot)
    if (ROOT / "notes").is_dir():
        for p in (ROOT / "notes").glob("*.md"):
            if p.name not in notes_before:
                p.unlink()


def test_backup_contains_no_database_ids(client, restorable):
    """Ids are reassigned on every reseed, so a backup keyed on them would
    restore quietly onto the wrong units."""
    data = client.get("/backup/download").json()
    for section, rows in data.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            offenders = [k for k in row if k == "id" or k.endswith("_id")]
            assert not offenders, f"{section} leaks {offenders}"


def test_backup_downloads_as_a_named_file(client, restorable):
    r = client.get("/backup/download")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert ".json" in r.headers["content-disposition"]


def test_round_trip_restores_progress_and_notes(client, a_unit, restorable):
    import json

    from app.models import Progress, UnitStatus
    from app.web import get_progress

    slug, uid, rid = a_unit
    with Session(engine) as s:
        p = get_progress(s, uid)
        p.status, p.minutes_logged = UnitStatus.done, 87
        st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
        if st is None:
            st = ResourceState(resource_id=rid)
            s.add(st)
        st.done, st.position_seconds = True, 421
        s.commit()
    (ROOT / "notes").mkdir(exist_ok=True)
    (ROOT / "notes" / f"{slug}.md").write_text("kept", encoding="utf-8")

    saved = client.get("/backup/download").json()

    with Session(engine) as s:
        for row in s.exec(select(Progress).where(Progress.unit_id == uid)):
            s.delete(row)
        for row in s.exec(select(ResourceState).where(ResourceState.resource_id == rid)):
            s.delete(row)
        s.commit()
    (ROOT / "notes" / f"{slug}.md").unlink()

    r = client.post(
        "/backup/restore",
        files={"file": ("b.json", json.dumps(saved), "application/json")},
    )
    assert r.status_code == 200

    with Session(engine) as s:
        p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
        st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
        assert p and p.minutes_logged == 87 and p.status == UnitStatus.done
        assert st and st.position_seconds == 421 and st.done
    assert (ROOT / "notes" / f"{slug}.md").read_text(encoding="utf-8") == "kept"


def test_restore_survives_resource_ids_changing(client, a_unit, restorable):
    """The point of keying on slug and URL: a reseed reassigns every id."""
    import json

    from app.db import raw_connection

    slug, uid, rid = a_unit
    with Session(engine) as s:
        st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
        if st is None:
            st = ResourceState(resource_id=rid)
            s.add(st)
        st.position_seconds = 999
        s.commit()
        url = s.get(Resource, rid).url

    saved = client.get("/backup/download").json()

    conn = raw_connection()
    conn.execute("UPDATE resource SET id = id + 5000")
    conn.execute("DELETE FROM resourcestate")
    conn.commit()
    conn.close()

    client.post("/backup/restore",
                files={"file": ("b.json", json.dumps(saved), "application/json")})

    with Session(engine) as s:
        moved = s.exec(select(Resource).where(Resource.url == url)).first()
        st = s.exec(select(ResourceState).where(ResourceState.resource_id == moved.id)).first()
        assert st and st.position_seconds == 999, "state did not follow the URL"

    conn = raw_connection()
    conn.execute("UPDATE resource SET id = id - 5000")
    conn.commit()
    conn.close()


def test_a_file_that_is_not_a_backup_is_refused(client):
    r = client.post("/backup/restore",
                    files={"file": ("x.json", '{"hello": 1}', "application/json")})
    assert r.status_code == 400
    assert "not a Magdy" in r.text or "isn&#39;t a backup" in r.text or "not a" in r.text


def test_broken_json_is_refused(client):
    r = client.post("/backup/restore",
                    files={"file": ("x.json", "{not json", "application/json")})
    assert r.status_code == 400


def test_a_future_backup_version_is_refused(client):
    import json

    from app import backup as bk

    r = client.post(
        "/backup/restore",
        files={"file": ("x.json",
                        json.dumps({"format": bk.FORMAT, "version": bk.VERSION + 99}),
                        "application/json")},
    )
    assert r.status_code == 400
