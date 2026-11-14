"""Say exactly what to watch, and leave the unit room for it.

A main resource that is a whole playlist has to name its videos. A unit has
to have time for its watching, its exercise and its checks. And the player
has to move between named videos even when they are not in one playlist.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app import seed, youtube
from app.db import ROOT

PLAYLIST = "https://www.youtube.com/playlist?list=PL-osiE80TeTt2d9bfVyTiXJA-UTHn6WwU"


def _unit(primary: dict, est=100, exercises=0, checks=0, slug="m0-x") -> dict:
    base = {"kind": "playlist", "title": "P", "url": PLAYLIST, "est_minutes": 60}
    base.update(primary)
    return {
        "slug": slug, "est_minutes": est,
        "resources": [base],
        "assignments": [{"slug": f"a{i}"} for i in range(exercises)],
        "checkpoint": [{"q": "q", "a": "a"}] * checks,
    }


def _errors(unit: dict) -> list[str]:
    errors: list[str] = []
    seed.validate_named_videos(unit, errors)
    return errors


# --------------------------------------------------------------------------
# rule 1: a playlist names its videos
# --------------------------------------------------------------------------


def test_a_whole_playlist_with_nothing_named_fails():
    assert any("does not say which videos" in e for e in _errors(_unit({})))


@pytest.mark.parametrize("flag", ["lookup_only", "whole_playlist"])
def test_lookup_only_or_whole_playlist_says_what_to_do(flag):
    assert _errors(_unit({flag: True})) == []


def test_naming_the_videos_passes():
    watch = [{"title": "Comprehensions", "video": "3dt4OGnU5sM", "from": "0:00",
              "to": "18:29", "why": "w"}]
    assert _errors(_unit({"watch": watch})) == []


def test_a_single_video_is_not_a_playlist():
    assert _errors(_unit({"kind": "video", "url": "https://www.youtube.com/watch?v=3dt4OGnU5sM"})) == []
    # and a video inside a playlist has chosen its video
    assert not seed.is_playlist_url("https://www.youtube.com/watch?v=3dt4OGnU5sM&list=PLx")


def test_whole_playlist_on_a_single_video_is_a_mistake():
    errors = _errors(_unit({"kind": "video", "whole_playlist": True,
                            "url": "https://www.youtube.com/watch?v=3dt4OGnU5sM"}))
    assert any("not a playlist URL" in e for e in errors)


def test_no_unit_points_at_an_unnamed_playlist():
    """Every module, M0 to M9: the main resource says which videos to watch.
    (M5-M9 sat on an allow-list while Stage A named M0-M4; it is gone.)"""
    assert not hasattr(seed, "UNNAMED_PLAYLIST_ALLOWED")
    for m in seed.load_modules():
        for u in m["units"]:
            assert _errors_for_rule_1(u) == [], u["slug"]


def _errors_for_rule_1(unit: dict) -> list[str]:
    return [e for e in _errors(unit) if "does not say which videos" in e]


# --------------------------------------------------------------------------
# rule 2: room for the watching, the exercise and the checks
# --------------------------------------------------------------------------


def test_a_unit_too_short_for_its_exercise_fails():
    # 60 min of watching + 20 for the exercise + 6 for three checks = 86
    errors = _errors(_unit({"lookup_only": True}, est=70, exercises=1, checks=3))
    assert any("claims 70 min but asks for at least 86" in e for e in errors), errors
    assert _errors(_unit({"lookup_only": True}, est=86, exercises=1, checks=3)) == []


def test_room_is_counted_from_the_selected_segments_not_the_whole_video():
    watch = [{"title": "Part", "video": "3dt4OGnU5sM", "from": "0:00", "to": "30:00", "why": "w"}]
    unit = _unit({"kind": "video", "url": "https://www.youtube.com/watch?v=3dt4OGnU5sM",
                  "est_minutes": 600, "watch": watch}, est=50, exercises=1)
    assert _errors(unit) == []


# --------------------------------------------------------------------------
# --urls: a playlist assigned whole really is short
# --------------------------------------------------------------------------


def _whole(pl: str = "PLshort") -> list[dict]:
    return [{"units": [{"slug": "u", "resources": [
        {"title": "Series", "url": f"https://www.youtube.com/playlist?list={pl}",
         "whole_playlist": True, "est_minutes": 60}]}]}]


def test_a_long_playlist_cannot_be_assigned_whole(monkeypatch):
    monkeypatch.setattr(seed, "_playlist_size", lambda pl: 106)
    monkeypatch.setattr(seed, "_video_length", lambda vid: None)
    errors, _ = seed.check_lengths(_whole())
    assert any("holds 106 videos" in e for e in errors), errors


def test_a_short_playlist_can(monkeypatch):
    monkeypatch.setattr(seed, "_playlist_size", lambda pl: 6)
    assert seed.check_lengths(_whole()) == ([], [])


def test_an_unknown_playlist_size_is_a_warning(monkeypatch):
    monkeypatch.setattr(seed, "_playlist_size", lambda pl: None)
    errors, warnings = seed.check_lengths(_whole())
    assert errors == [] and len(warnings) == 1


def test_playlist_size_reads_the_page():
    html = 'x"stats":[{"runs":[{"text":"106"},{"text":" videos"}]},{"simpleText":"6,764,034 views"}'
    assert youtube.playlist_size(html) == 106
    assert youtube.playlist_size('"stats":[{"runs":[{"text":"1"},{"text":" video"}]}') == 1
    assert youtube.playlist_size("<html>consent</html>") is None


# --------------------------------------------------------------------------
# the result, as the learner sees it
# --------------------------------------------------------------------------


def test_the_idioms_unit_names_its_videos_in_the_briefing_and_the_rail(client):
    html = client.get("/unit/m0-python-idioms").text
    brief = html[html.index('<details class="brief"'):]
    brief = brief[:brief.index("</details>")]
    for title in ("Comprehensions", "Slicing, with negative indexes and steps", "f-strings"):
        assert title in brief
    assert "158" not in brief
    # the player gets every part, and there is a rail to list them
    segs = json.loads(html.split("data-segments='")[1].split("'")[0])
    assert [s["video"] for s in segs][:2] == ["3dt4OGnU5sM", "ajrtAuDg3yw"]
    assert segs[-1]["video"] == "qUeud6DvOWI"  # outside the playlist: loaded by id
    assert 'id="rail"' in html


# --------------------------------------------------------------------------
# player.js: moving between named videos (run under node)
# --------------------------------------------------------------------------

NODE = shutil.which("node")


def _player(expr: str):
    script = (
        f"const p = require({json.dumps(str(ROOT / 'app' / 'static' / 'player.js'))});"
        f"process.stdout.write(JSON.stringify({expr}));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


SEGS = [{"video": "aaaaaaaaaaa", "from": 0, "to": 60},
        {"video": "bbbbbbbbbbb", "from": 47, "to": 600},
        {"video": "ccccccccccc", "from": 0, "to": 552}]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_when_a_part_ends_the_next_one_starts_in_its_own_video():
    step = _player(f"p.afterPart({json.dumps(SEGS)}, 0)")
    assert step == {"action": "next", "at": 1, "video": "bbbbbbbbbbb", "from": 47}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_last_part_stops():
    assert _player(f"p.afterPart({json.dumps(SEGS)}, 2)") == {"action": "stop"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_resuming_picks_the_part_you_were_in():
    assert _player(f"p.resumeSegment({json.dumps(SEGS)}, {{video: 'bbbbbbbbbbb', seconds: 300}})") == 1
    assert _player(f"p.resumeSegment({json.dumps(SEGS)}, null)") == 0
    assert _player(f"p.resumeSegment({json.dumps(SEGS)}, {{video: 'zzzzzzzzzzz'}})") == 0


def test_parts_are_played_as_clips_that_youtube_ends_itself():
    """The browser bug this pins: watching the clock once a second missed a
    part ending at its video's last second, and the playlist rolled on into an
    unrelated video. A clip with endSeconds is ended by YouTube, exactly."""
    js = (ROOT / "app" / "static" / "player.js").read_text(encoding="utf-8")
    assert "endSeconds" in js and "loadVideoById(clip(" in js
    assert "vars.end = seg.to" in js
    # nothing advances a part on a timer any more
    tick = js[js.index("function tick()"):js.index("function clip(")]
    assert "goToSegment" not in tick


# --------------------------------------------------------------------------
# "link checked" (a machine) and "reviewed" (a person) are shown apart
# --------------------------------------------------------------------------


def test_the_page_says_who_checked_what():
    from app.models import Resource
    from app.web import checked_line

    r = Resource(unit_id=1, kind="video", title="t", url="u")
    assert str(checked_line(r)) == ""
    r.verified_at = "2026-11-14"
    line = str(checked_line(r))
    assert "link checked 14 Nov 2026" in line and "reviewed" not in line
    assert "does not mean anyone re-watched it" in line
    r.reviewed_at = "2026-11-12"
    assert "reviewed 12 Nov 2026" in str(checked_line(r))


def test_a_stamped_resource_shows_on_its_unit_page(client):
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Resource, Unit

    with Session(engine) as s:
        u = s.exec(select(Unit).where(Unit.slug == "m2-numpy")).one()
        r = s.exec(select(Resource).where(Resource.unit_id == u.id, Resource.rank == 0)).one()
        rid, before, r.verified_at = r.id, r.verified_at, "2026-11-14"
        s.commit()
    try:
        assert "link checked 14 Nov 2026" in client.get("/unit/m2-numpy").text
    finally:
        with Session(engine) as s:
            r = s.get(Resource, rid)
            r.verified_at = before
            s.commit()
