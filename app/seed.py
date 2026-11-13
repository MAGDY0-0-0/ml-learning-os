"""Seed the DB from curriculum/*.yaml, and validate the curriculum's rules.

Run:
    python -m app.seed             # seed / re-seed (idempotent)
    python -m app.seed --check     # validate only, no writes
    python -m app.seed --check --urls   # also verify every URL returns 200
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

import yaml
from sqlmodel import Session, select

from app import youtube
from app.db import DB_PATH, ROOT, engine, init_db
from app.models import (
    FREE_COSTS,
    VIDEO_KINDS,
    ActiveResource,
    Assignment,
    Card,
    Cost,
    Module,
    Project,
    Resource,
    ResourceKind,
    ResourcePreference,
    ResourceState,
    Unit,
    modality,
)

CURRICULUM_DIR = ROOT / "curriculum"


class CurriculumError(Exception):
    """Raised when the curriculum violates one of the plan's hard rules."""


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

MIN_RESOURCES_PER_UNIT = 3


def parse_stamp(value: Any) -> int | None:
    """"1:07:27" / "38:29" / 91 -> seconds. None when it is not a timestamp."""
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    if not all(p.isdigit() for p in parts) or len(parts) > 3:
        return None
    out = 0
    for part in parts:
        out = out * 60 + int(part)
    return out


#: A YouTube id is 11 characters of base64url. Matching the shape catches a
#: pasted URL or a truncated id at build time rather than as a dead player.
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_parts(url: str) -> tuple[str, str]:
    """(video_id, playlist_id) from a YouTube URL; empty strings otherwise.

    Deliberately a local three-liner rather than importing app.web.youtube_ids:
    web.py pulls in Jinja and the template environment, and the seeder is a
    command-line tool that should not need any of that to validate a file.
    """
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    video = m.group(1) if m else ""
    if not video:
        m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
        video = m.group(1) if m else ""
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", url)
    return video, (m.group(1) if m else "")


def validate_watch(slug: str, res: dict[str, Any], errors: list[str]) -> list[dict]:
    """Check a resource's `watch` block and return it with stamps as seconds.

    A segment has to say *which video* its timestamps belong to. Seventeen of
    the twenty-four YouTube primaries in this curriculum are playlists, and
    "38:29" means nothing against a playlist of a hundred videos -- so on a
    playlist `video` is required, and on a single video it defaults to that
    video. Identifying the entry by id rather than by position also survives
    the author reordering the playlist, which they do.
    """
    raw = res.get("watch") or []
    name = res.get("title", "?")
    if not isinstance(raw, list):
        errors.append(f"{slug}: `watch` on '{name}' must be a list")
        return []

    res_video, res_list = youtube_parts(res.get("url", ""))
    out = []

    for seg in raw:
        if not isinstance(seg, dict):
            errors.append(f"{slug}: a `watch` entry on '{name}' is not a mapping")
            continue

        # -- the label shown on the card ------------------------------------
        title = str(seg.get("title", "")).strip()
        if not title:
            errors.append(f"{slug}: a `watch` entry on '{name}' needs a short `title` — "
                          "it is what the unit page shows instead of the full runtime")
            continue

        # -- which video these stamps belong to -----------------------------
        video = str(seg.get("video", "")).strip() or res_video
        if not video:
            errors.append(
                f"{slug}: `watch` entry '{title}' has no `video`. '{name}' is a "
                "playlist, so a timestamp on its own is ambiguous — name the "
                "video id the stamps belong to."
            )
            continue
        if not YT_ID.match(video):
            errors.append(f"{slug}: `watch` entry '{title}' has `video: {video}`, "
                          "which is not an 11-character YouTube id")
            continue
        if res_video and not res_list and video != res_video:
            errors.append(
                f"{slug}: `watch` entry '{title}' points at {video}, but '{name}' "
                f"is the single video {res_video}."
            )
            continue

        # -- the stamps -----------------------------------------------------
        start = parse_stamp(seg.get("from"))
        end = parse_stamp(seg.get("to"))
        if start is None:
            errors.append(f"{slug}: `watch.from` on '{title}' is not a timestamp "
                          f"({seg.get('from')!r})")
            continue
        if end is not None and end <= start:
            errors.append(f"{slug}: `watch` entry '{title}' ends at {seg.get('to')} "
                          f"which is not after {seg.get('from')}")
            continue
        if not str(seg.get("why", "")).strip():
            errors.append(f"{slug}: `watch` entry '{title}' needs a `why` — "
                          "say what this part covers and what you are skipping")
            continue

        out.append({
            "title": title,
            "video": video,
            "from": start,
            "to": end,
            "why": str(seg["why"]).strip(),
        })
    return out


def iso_date(value: Any) -> str | None:
    """A YAML date (parsed or quoted) as "YYYY-MM-DD"; None if it is not one."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    return None


def validate_checkpoint(slug: str, unit: dict[str, Any], errors: list[str]) -> list[dict]:
    """Questions a unit asks before it will let itself be marked complete."""
    raw = unit.get("checkpoint") or []
    if not isinstance(raw, list):
        errors.append(f"{slug}: `checkpoint` must be a list")
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("q", "")).strip():
            errors.append(f"{slug}: every `checkpoint` entry needs a `q`")
            continue
        if not str(item.get("a", "")).strip():
            errors.append(f"{slug}: checkpoint '{str(item['q'])[:40]}' needs an `a` — "
                          "a question you cannot check yourself is not a checkpoint")
            continue
        out.append({"q": str(item["q"]).strip(), "a": str(item["a"]).strip()})
    return out


def validate_unit(unit: dict[str, Any], errors: list[str]) -> None:
    slug = unit.get("slug", "<no slug>")
    resources = unit.get("resources") or []

    if len(resources) < MIN_RESOURCES_PER_UNIT:
        errors.append(
            f"{slug}: has {len(resources)} resources, needs >= {MIN_RESOURCES_PER_UNIT} "
            "(so 'swap' always has somewhere to go)"
        )
        return

    # The same URL twice in one unit offers the learner a choice that is not a
    # choice, and seed() keys existing rows by URL per unit -- so the second
    # entry is never matched and a fresh row is inserted on *every* reseed.
    # Three such pairs had quietly accumulated three copies each before this
    # check existed.
    seen_urls: dict[str, str] = {}
    for r in resources:
        url = r.get("url", "")
        if url in seen_urls:
            errors.append(
                f"{slug}: lists {url} twice — as '{seen_urls[url]}' and "
                f"'{r.get('title', '?')}'. One resource, one entry."
            )
        seen_urls[url] = r.get("title", "?")

    kinds: list[ResourceKind] = []
    for r in resources:
        try:
            kinds.append(ResourceKind(r["kind"]))
        except (KeyError, ValueError):
            errors.append(f"{slug}: resource {r.get('title', '?')} has bad/missing kind")
            return

    # --- rule: alternates must span more than one modality -----------------
    modalities = {modality(k) for k in kinds}
    if len(modalities) < 2:
        errors.append(
            f"{slug}: all {len(resources)} resources are '{modalities.pop()}' — "
            "a swap must change modality, not just source"
        )

    # --- rule: video-first --------------------------------------------------
    primary_kind = kinds[0]
    if modality(primary_kind) != "video":
        if not unit.get("no_good_video"):
            errors.append(
                f"{slug}: primary is '{primary_kind.value}' (not video). Set "
                "no_good_video: true with a reason, or promote a video."
            )
        elif not unit.get("no_good_video_reason"):
            errors.append(f"{slug}: no_good_video is set but no reason given")

    # --- rule: primary must be free ----------------------------------------
    primary_cost = Cost(resources[0].get("cost", "free"))
    if primary_cost not in FREE_COSTS:
        errors.append(
            f"{slug}: primary resource costs money ({primary_cost.value}). "
            "Primaries must be free."
        )

    # --- rule: every resource must carry a verdict + caveat ----------------
    for r in resources:
        if not r.get("community_verdict"):
            errors.append(f"{slug}: '{r.get('title', '?')}' has no community_verdict")
        if "caveat" not in r:
            errors.append(f"{slug}: '{r.get('title', '?')}' has no caveat field")

    # --- rule: name the teacher, not the platform --------------------------
    # "YouTube (2025)" told the learner nothing about who is teaching, which
    # is the one thing that decides whether a swap is worth trying.
    for r in resources:
        provider = str(r.get("provider", "")).strip()
        if provider.lower().startswith("youtube"):
            errors.append(
                f"{slug}: '{r.get('title', '?')}' gives its provider as '{provider}'. "
                "Name the channel or person (oEmbed's author_name)."
            )

    # --- rule: a human review date is a real date --------------------------
    for r in resources:
        if r.get("reviewed_at") is not None and iso_date(r["reviewed_at"]) is None:
            errors.append(
                f"{slug}: '{r.get('title', '?')}' has reviewed_at "
                f"{r['reviewed_at']!r}; write it as YYYY-MM-DD"
            )

    # --- rule: a `watch` block must be well formed, wherever it appears ----
    for r in resources:
        validate_watch(slug, r, errors)
    validate_checkpoint(slug, unit, errors)

    # --- rule: don't hand someone more video than the unit claims ----------
    # Being told "about 75 minutes" and given a 116-minute playlist is the
    # moment a plan stops being followed. If the primary is longer than the
    # unit, it has to say which part earns its place.
    primary = resources[0]
    unit_minutes = unit.get("est_minutes", 0)
    primary_minutes = primary.get("est_minutes", 0)
    is_video_primary = primary.get("kind") in {k.value for k in VIDEO_KINDS}

    if is_video_primary and unit_minutes and primary_minutes > unit_minutes:
        segments = validate_watch(slug, primary, [])  # errors already collected above
        if not segments and not primary.get("lookup_only"):
            errors.append(
                f"{slug}: the primary is {primary_minutes} min but the unit claims "
                f"{unit_minutes} min, and it doesn't say which part to watch. "
                "Add a `watch:` block (python -m scripts.chapters <url> lists the "
                "real chapters), set lookup_only, or correct est_minutes."
            )
        elif segments:
            # The point of the gate is the number the learner is actually asked
            # for, not the presence of a field. A `watch` block that selects
            # three hours for a ninety-minute unit is the same broken promise
            # the gate exists to catch.
            open_ended = [s for s in segments if s["to"] is None]
            if open_ended:
                errors.append(
                    f"{slug}: `watch` entry '{open_ended[0]['title']}' has no `to`, so the "
                    "time it asks for cannot be measured. Give it an end stamp."
                )
            else:
                selected = sum(s["to"] - s["from"] for s in segments) // 60
                if selected > unit_minutes:
                    errors.append(
                        f"{slug}: the `watch` block selects {selected} min but the unit "
                        f"claims {unit_minutes} min. Narrow the segments or correct "
                        "est_minutes — the unit's number has to be the one you are "
                        "actually asked to watch."
                    )


def load_modules() -> list[dict[str, Any]]:
    files = sorted(CURRICULUM_DIR.glob("m*.yaml"))
    if not files:
        raise CurriculumError(f"no curriculum yaml found in {CURRICULUM_DIR}")
    out = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not data:
            raise CurriculumError(f"{f.name} is empty")
        data["_file"] = f.name
        out.append(data)
    return out


def validate_assignments(unit: dict[str, Any], errors: list[str]) -> None:
    """Every assignment must have a starter file and a runnable tests dir."""
    for a in unit.get("assignments") or []:
        slug = a.get("slug", "?")
        starter = ROOT / a.get("starter_path", "")
        tests = ROOT / a.get("tests_path", "")
        if not a.get("starter_path") or not starter.is_file():
            errors.append(f"{slug}: starter file missing ({a.get('starter_path')})")
        if not a.get("tests_path") or not tests.is_dir():
            errors.append(f"{slug}: tests directory missing ({a.get('tests_path')})")
        elif not list(tests.glob("test_*.py")):
            errors.append(f"{slug}: tests directory has no test_*.py files")


#: How long an outcome may be. Longer than this and it is a paragraph, not
#: something you could be asked to do in five minutes.
OUTCOME_MAX_CHARS = 90


def _outcome_list(owner: str, raw: Any, lo: int, hi: int, errors: list[str]) -> list[str]:
    """Validate an `outcomes` list and return it cleaned."""
    if not isinstance(raw, list) or not raw:
        errors.append(f"{owner}: needs `outcomes` — {lo} to {hi} things you can do afterwards")
        return []
    items = [" ".join(str(o).split()) for o in raw]
    if not lo <= len(items) <= hi:
        errors.append(f"{owner}: has {len(items)} outcomes; give {lo} to {hi}")
    for o in items:
        if not o:
            errors.append(f"{owner}: an outcome is empty")
        elif len(o) > OUTCOME_MAX_CHARS:
            errors.append(f"{owner}: outcome '{o[:40]}…' is {len(o)} characters; "
                          f"keep each under {OUTCOME_MAX_CHARS}")
    return items


#: Units whose main resource is still a whole playlist with no video named.
#: Stage A of the plan named the videos for M0-M4; these are Stage B. The
#: list may only shrink -- a unit added to it is a unit that stops saying
#: what to watch.
UNNAMED_PLAYLIST_ALLOWED = {
    "m5-backprop", "m5-cnns",
    "m6-attention", "m6-architecture", "m6-mini-transformer", "m6-finetune-lora",
    "m7-apis-prompting",
    "m8-tracking", "m8-monitoring",
    "m9-deploy-demo", "m9-interview",
}

#: A playlist may be assigned whole only if it is short enough to be one
#: sitting's worth of named parts; past this, it has to say which videos.
WHOLE_PLAYLIST_MAX = 12

#: Minutes a plan gives each checkpoint question; mirrors studio.CHECK_MINUTES.
CHECK_MINUTES = 2
#: The least time a unit may leave each of its exercises.
EXERCISE_MIN_MINUTES = 20


def is_playlist_url(url: str) -> bool:
    """A playlist with no video chosen: `list=` and no `v=`."""
    video, playlist = youtube_parts(url)
    return bool(playlist) and not video


def validate_named_videos(unit: dict[str, Any], errors: list[str]) -> None:
    """The main resource says exactly what to watch, and the unit has room for it.

    Rule 1: a main resource that is a whole playlist names its videos in a
    `watch` block, or says `lookup_only` (dip in for single chapters), or
    `whole_playlist` (short enough to watch end to end).

    Rule 2: est_minutes covers the watching, two minutes per checkpoint
    question, and at least EXERCISE_MIN_MINUTES per exercise. A unit that
    leaves its exercise four minutes is promising something it cannot keep.
    """
    slug = unit.get("slug", "<no slug>")
    resources = unit.get("resources") or []
    if not resources:
        return
    primary = resources[0]
    url = str(primary.get("url", ""))

    if primary.get("whole_playlist") and not is_playlist_url(url):
        errors.append(f"{slug}: `whole_playlist` is set on '{primary.get('title', '?')}', "
                      "which is not a playlist URL")

    segments = validate_watch(slug, primary, [])
    if (is_playlist_url(url) and not segments and not primary.get("lookup_only")
            and not primary.get("whole_playlist") and slug not in UNNAMED_PLAYLIST_ALLOWED):
        errors.append(
            f"{slug}: the main resource is a whole playlist and does not say which videos "
            "to watch. Name them in a `watch` block, or set lookup_only or whole_playlist."
        )

    if segments and all(sg["to"] is not None for sg in segments):
        watch = sum(sg["to"] - sg["from"] for sg in segments) // 60
    else:
        watch = int(primary.get("est_minutes") or 0)
    n_ex = len(unit.get("assignments") or [])
    n_checks = len(unit.get("checkpoint") or [])
    need = watch + EXERCISE_MIN_MINUTES * n_ex + CHECK_MINUTES * n_checks
    have = int(unit.get("est_minutes") or 0)
    if have < need:
        errors.append(
            f"{slug}: claims {have} min but asks for at least {need}: {watch} min of "
            f"watching, {n_ex} exercise(s) at {EXERCISE_MIN_MINUTES} min, and {n_checks} "
            f"check(s) at {CHECK_MINUTES} min. Raise est_minutes or watch less."
        )


def validate_briefing(unit: dict[str, Any], earlier: set[str], errors: list[str]) -> None:
    """The four authored parts of a unit's briefing.

    `earlier` is every unit slug that comes before this one in the curriculum:
    a `needs` entry has to exist and has to come first, or "do this first"
    would send you forward or nowhere.
    """
    slug = unit.get("slug", "<no slug>")
    if not " ".join(str(unit.get("why", "")).split()):
        errors.append(f"{slug}: needs a `why` — one sentence on where this gets used later")
    _outcome_list(slug, unit.get("outcomes"), 2, 4, errors)

    needs = unit.get("needs") or []
    if not isinstance(needs, list):
        errors.append(f"{slug}: `needs` must be a list of unit slugs")
        needs = []
    for n in needs:
        if n == slug:
            errors.append(f"{slug}: needs itself")
        elif n not in earlier:
            errors.append(f"{slug}: needs '{n}', which is not a unit that comes before it")

    if str(unit.get("skip_if", "")).strip() and not unit.get("checkpoint"):
        errors.append(f"{slug}: has `skip_if` but no checkpoint, so it would never be "
                      "shown — the skip is a jump to the checks")


def validate(modules: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_units: set[str] = set()
    for mod in modules:
        if not mod.get("slug"):
            errors.append(f"{mod.get('_file')}: module has no slug")
        _outcome_list(mod.get("slug", mod.get("_file", "?")), mod.get("outcomes"), 3, 5, errors)
        for unit in mod.get("units") or []:
            slug = unit.get("slug")
            if not slug:
                errors.append(f"{mod.get('_file')}: a unit has no slug")
                continue
            if slug in seen_units:
                errors.append(f"duplicate unit slug: {slug}")
            validate_unit(unit, errors)
            validate_named_videos(unit, errors)
            validate_briefing(unit, seen_units, errors)
            validate_assignments(unit, errors)
            seen_units.add(slug)
    return errors


# --------------------------------------------------------------------------
# link checking (`--urls`)
# --------------------------------------------------------------------------
# The question is "is this link gone?", and only an answer that means gone
# may fail the build. A 403 or 429 is a site refusing to talk to a script --
# madewithml.com refuses GitHub's runners and serves a browser on this
# machine -- so it is reported as "could not verify", never as dead. The old
# allow-list of such hosts could only ever be one refusal behind.

#: What a check concluded. Only DEAD fails the build.
OK, UNVERIFIED, DEAD = "ok", "unverified", "dead"

#: Answers that mean "you are a script", not "this is gone".
REFUSED = {"403", "429"}


@dataclass(frozen=True)
class LinkResult:
    slug: str
    url: str
    status: str
    verdict: str
    note: str = ""


@dataclass
class LinkReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: URLs that answered and still play -- what `verified_at` is stamped from.
    verified: set[str] = field(default_factory=set)


def _fetch_status(url: str, user_agent: str = "Mozilla/5.0") -> str:
    """Return an HTTP status code as a string, or an error token.

    Uses curl rather than httpx: httpx is blocked in some sandboxed shells,
    while curl is available and honours the system proxy configuration.
    """
    import subprocess

    try:
        out = subprocess.run(
            [
                "curl", "-sL", "-o", os.devnull, "-w", "%{http_code}",
                "--max-time", "25", "-A", user_agent, url,
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        return (out.stdout or "").strip() or "000"
    except Exception as exc:  # noqa: BLE001
        return f"ERR:{type(exc).__name__}"


#: Hosts whose player pages answer 200 even when the media behind them is
#: gone, so a plain fetch proves nothing. Each has an oEmbed endpoint that
#: does tell the truth.
OEMBED_ENDPOINTS = {
    "youtube.com": "https://www.youtube.com/oembed?url={url}&format=json",
    "www.youtube.com": "https://www.youtube.com/oembed?url={url}&format=json",
    "m.youtube.com": "https://www.youtube.com/oembed?url={url}&format=json",
    "youtu.be": "https://www.youtube.com/oembed?url={url}&format=json",
    "vimeo.com": "https://vimeo.com/api/oembed.json?url={url}",
    "player.vimeo.com": "https://vimeo.com/api/oembed.json?url={url}",
}


def _check_one(slug: str, url: str) -> LinkResult:
    """Check one URL.

    Videos are checked through oEmbed rather than by fetching the page. A
    deleted YouTube video still answers 200 on its watch page -- verified
    against a nonexistent id -- so the obvious check silently passes every
    dead video in the curriculum. oEmbed answers 400 (video) or 404
    (playlist) for something that is really gone, and 200 for something that
    still plays.
    """
    from urllib.parse import quote, urlparse

    host = urlparse(url).netloc
    if host.startswith(("127.0.0.1", "localhost")):
        return LinkResult(slug, url, "--", OK, "local app route; checked by the test suite")

    endpoint = OEMBED_ENDPOINTS.get(host)
    if endpoint:
        status = _fetch_status(endpoint.format(url=quote(url, safe="")))
        if status == "200":
            return LinkResult(slug, url, status, OK, "oEmbed")
        if status in REFUSED:
            return LinkResult(slug, url, status, UNVERIFIED, "oEmbed refused to answer; try again later")
        return LinkResult(slug, url, status, DEAD, "oEmbed says this no longer plays")

    status = _fetch_status(url)
    if status == "000" or status.startswith("ERR"):
        # No answer at all. One dropped connection is not a dead page; a
        # dead host fails the second time too.
        status = _fetch_status(url)
    if status in REFUSED:
        # Many sites refuse a bare "Mozilla/5.0" and serve a browser's full
        # User-Agent; ask once more as a browser before settling.
        status = _fetch_status(url, youtube.BROWSER_UA)
    if status.startswith("2"):
        return LinkResult(slug, url, status, OK)
    if status in REFUSED:
        return LinkResult(slug, url, status, UNVERIFIED,
                          "refuses scripts; open it in a browser to check")
    return LinkResult(slug, url, status, DEAD)


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def check_urls(modules: Iterable[dict[str, Any]]) -> LinkReport:
    """Verify every resource URL, and every video a `watch` block names.

    In parallel: serial checking made this take minutes, which meant nobody
    ran it, which made the gate decorative. A segment's video is checked too,
    because a segment can point at a video other than its resource's URL --
    and a dead one there would play nothing while the URL check stayed green.
    """
    from concurrent.futures import ThreadPoolExecutor

    seen: set[str] = set()
    urls: list[tuple[str, str]] = []

    def add(slug: str, url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            urls.append((slug, url))

    for mod in modules:
        for unit in mod.get("units") or []:
            for r in unit.get("resources") or []:
                add(unit["slug"], r.get("url", ""))
                own_video, _ = youtube_parts(r.get("url", ""))
                for seg in validate_watch(unit["slug"], r, []):
                    if seg["video"] != own_video:
                        add(unit["slug"], _watch_url(seg["video"]))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda a: _check_one(*a), urls))

    report = LinkReport()
    for res in results:
        suffix = f"  ({res.note})" if res.note else ""
        print(f"  {res.status:<4} {res.url}{suffix}")
        if res.verdict == OK:
            report.verified.add(res.url)
        elif res.verdict == UNVERIFIED:
            report.warnings.append(f"{res.slug}: HTTP {res.status} for {res.url}{suffix}")
        else:
            report.errors.append(f"{res.slug}: HTTP {res.status} for {res.url}{suffix}")
    return report


# --------------------------------------------------------------------------
# video lengths (`--urls`)
# --------------------------------------------------------------------------
# The time gate above compares a resource's est_minutes against the unit's,
# and it can only be as honest as that number. m5-training-loop's main video
# was claimed as 120 minutes and is 25 h 37 min, so the gate never fired.
# Here the claimed number is checked against the video itself.


def _video_length(video_id: str) -> int | None:
    """Seconds, read from the watch page; None when the page did not say."""
    return youtube.length_seconds(youtube.watch_page(video_id), video_id)


def _playlist_size(list_id: str) -> int | None:
    return youtube.playlist_size(youtube.playlist_page(list_id))


def length_tolerance(real_minutes: float) -> float:
    """How far a claimed length may be from the real one: 5 min or 20%."""
    return max(5.0, 0.2 * real_minutes)


def _clock(seconds: int) -> str:
    h, m, s = seconds // 3600, seconds % 3600 // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def check_lengths(modules: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(errors, warnings) from comparing claims against the videos' real lengths.

    Two claims are checked: a single video's `est_minutes`, and that no
    `watch` segment ends after its video does. A length the page would not
    give up is a warning -- YouTube sometimes serves a consent page to
    data-centre IPs, and "could not read it" is not "it is wrong".
    """
    from concurrent.futures import ThreadPoolExecutor

    claims: list[tuple[str, str, str, int]] = []  # slug, title, video, minutes
    ends: list[tuple[str, str, str, int]] = []    # slug, segment title, video, `to`
    for mod in modules:
        for unit in mod.get("units") or []:
            slug = unit["slug"]
            for r in unit.get("resources") or []:
                video, playlist = youtube_parts(r.get("url", ""))
                if video and not playlist:
                    claims.append((slug, r.get("title", "?"), video, int(r.get("est_minutes") or 0)))
                for seg in validate_watch(slug, r, []):
                    if seg["to"] is not None:
                        ends.append((slug, seg["title"], seg["video"], seg["to"]))

    wholes: list[tuple[str, str, str]] = []   # slug, title, playlist id
    for mod in modules:
        for unit in mod.get("units") or []:
            for r in unit.get("resources") or []:
                if r.get("whole_playlist") and is_playlist_url(r.get("url", "")):
                    wholes.append((unit["slug"], r.get("title", "?"), youtube_parts(r["url"])[1]))

    ids = sorted({c[2] for c in claims} | {e[2] for e in ends})
    lists = sorted({w[2] for w in wholes})
    with ThreadPoolExecutor(max_workers=8) as pool:
        lengths = dict(zip(ids, pool.map(_video_length, ids)))
        sizes = dict(zip(lists, pool.map(_playlist_size, lists)))

    errors: list[str] = []
    warnings: list[str] = []
    for slug, title, pl in wholes:
        n = sizes[pl]
        if n is None:
            warnings.append(f"could not read how many videos playlist {pl} holds ({slug})")
        elif n > WHOLE_PLAYLIST_MAX:
            errors.append(f"{slug}: '{title}' is marked whole_playlist but holds {n} videos; "
                          f"past {WHOLE_PLAYLIST_MAX}, name the ones to watch")
    for vid in ids:
        if lengths[vid] is None:
            warnings.append(f"could not read the length of {_watch_url(vid)} "
                            "(YouTube may have served a consent page)")

    for slug, title, vid, claimed in claims:
        real = lengths[vid]
        if real is None:
            continue
        real_min = real / 60
        if abs(claimed - real_min) > length_tolerance(real_min):
            errors.append(
                f"{slug}: '{title}' claims {claimed} min but the video is "
                f"{_clock(real)} long. Set est_minutes: {round(real_min)}."
            )

    for slug, title, vid, end in ends:
        real = lengths[vid]
        # Two seconds of slack: a chapter's end stamp and the reported length
        # are rounded independently.
        if real is not None and end > real + 2:
            errors.append(
                f"{slug}: `watch` entry '{title}' ends at {_clock(end)}, but "
                f"video {vid} is only {_clock(real)} long."
            )
    return errors, warnings

# --------------------------------------------------------------------------
# seeding
# --------------------------------------------------------------------------


def seed(modules: list[dict[str, Any]]) -> None:
    init_db()
    with Session(engine) as s:
        for m_order, mod in enumerate(modules):
            module = s.exec(select(Module).where(Module.slug == mod["slug"])).first()
            if module is None:
                module = Module(slug=mod["slug"])
                s.add(module)
            module.title = mod["title"]
            module.blurb = mod.get("blurb", "")
            module.outcomes_json = json.dumps(
                _outcome_list(mod["slug"], mod.get("outcomes"), 3, 5, []), ensure_ascii=False
            )
            module.order = mod.get("order", m_order)
            s.commit()
            s.refresh(module)

            for u_order, u in enumerate(mod.get("units") or []):
                unit = s.exec(select(Unit).where(Unit.slug == u["slug"])).first()
                if unit is None:
                    unit = Unit(slug=u["slug"], module_id=module.id)
                    s.add(unit)
                unit.module_id = module.id
                unit.title = u["title"]
                unit.objective = u.get("objective", "")
                unit.est_minutes = u.get("est_minutes", 60)
                unit.order = u.get("order", u_order)
                unit.needs_gpu = u.get("needs_gpu", False)
                unit.optional_stretch = u.get("optional_stretch", False)
                unit.no_good_video = u.get("no_good_video", False)
                unit.no_good_video_reason = u.get("no_good_video_reason", "")
                unit.rigor_note = u.get("rigor_note", "")
                unit.checkpoint_json = json.dumps(
                    validate_checkpoint(u["slug"], u, []), separators=(",", ":")
                )
                unit.why = " ".join(str(u.get("why", "")).split())
                unit.outcomes_json = json.dumps(
                    _outcome_list(u["slug"], u.get("outcomes"), 2, 4, []), ensure_ascii=False
                )
                unit.needs_json = json.dumps([str(n) for n in (u.get("needs") or [])])
                unit.skip_if = " ".join(str(u.get("skip_if", "")).split())
                s.commit()
                s.refresh(unit)

                # resources: replace wholesale, keyed by url within the unit
                existing = {
                    r.url: r
                    for r in s.exec(select(Resource).where(Resource.unit_id == unit.id))
                }
                for rank, r in enumerate(u.get("resources") or []):
                    res = existing.pop(r["url"], None)
                    if res is None:
                        res = Resource(unit_id=unit.id, url=r["url"], kind=ResourceKind(r["kind"]))
                        s.add(res)
                    res.kind = ResourceKind(r["kind"])
                    res.title = r["title"]
                    res.provider = r.get("provider", "")
                    res.est_minutes = r.get("est_minutes", 0)
                    res.rank = rank
                    res.community_verdict = r.get("community_verdict", "")
                    res.caveat = r.get("caveat", "")
                    res.cost = Cost(r.get("cost", "free"))
                    res.lookup_only = r.get("lookup_only", False)
                    res.concept = r.get("concept", "")
                    # Written by a person in the YAML after actually watching
                    # it. verified_at is the machine's half; see stamp_verified.
                    res.reviewed_at = iso_date(r.get("reviewed_at"))
                    # Stamps are stored already parsed to seconds, so nothing
                    # downstream has to re-parse "1:22:46" on every render.
                    res.watch_json = json.dumps(
                        validate_watch(u["slug"], r, []), separators=(",", ":")
                    )
                for stale in existing.values():
                    # SQLite doesn't enforce FKs here, so drop dependants by hand
                    # or a swap would keep pointing at a resource that is gone.
                    for model in (ActiveResource, ResourceState, ResourcePreference):
                        for row in s.exec(select(model).where(model.resource_id == stale.id)):
                            s.delete(row)
                    s.delete(stale)
                s.commit()

                for a in u.get("assignments") or []:
                    asg = s.exec(
                        select(Assignment).where(Assignment.slug == a["slug"])
                    ).first()
                    if asg is None:
                        asg = Assignment(slug=a["slug"], unit_id=unit.id)
                        s.add(asg)
                    asg.unit_id = unit.id
                    asg.title = a["title"]
                    asg.brief = a.get("brief", "")
                    asg.starter_path = a.get("starter_path", "")
                    asg.tests_path = a.get("tests_path", "")
                    asg.difficulty = a.get("difficulty", "core")
                s.commit()

                for c in u.get("cards") or []:
                    exists = s.exec(
                        select(Card).where(Card.unit_id == unit.id, Card.front == c["front"])
                    ).first()
                    if exists is None:
                        s.add(Card(unit_id=unit.id, front=c["front"], back=c["back"]))
                s.commit()

            for p in mod.get("projects") or []:
                proj = s.exec(select(Project).where(Project.slug == p["slug"])).first()
                if proj is None:
                    proj = Project(slug=p["slug"])
                    s.add(proj)
                proj.title = p["title"]
                proj.brief = p.get("brief", "")
                proj.module_slug = mod["slug"]
                proj.requires_deployment = p.get("requires_deployment", False)
            s.commit()


def stamp_verified(urls: set[str], today: str | None = None) -> int:
    """Record that a machine saw these URLs answer and, for video, still play.

    Says nothing about whether the content is still the right choice -- that
    is `reviewed_at`, which only a person can write (in the YAML).
    """
    if not urls:
        return 0
    today = today or date.today().isoformat()
    n = 0
    with Session(engine) as s:
        for r in s.exec(select(Resource).where(Resource.url.in_(urls))):
            r.verified_at = today
            n += 1
        s.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only, no writes")
    ap.add_argument("--urls", action="store_true", help="also verify every URL")
    args = ap.parse_args()

    modules = load_modules()
    errors = validate(modules)
    warnings: list[str] = []
    links = LinkReport()
    if args.urls:
        print("checking urls...")
        links = check_urls(modules)
        errors += links.errors
        warnings += links.warnings
        print("checking video lengths...")
        length_errors, length_warnings = check_lengths(modules)
        errors += length_errors
        warnings += length_warnings

    n_units = sum(len(m.get("units") or []) for m in modules)
    n_res = sum(
        len(u.get("resources") or []) for m in modules for u in (m.get("units") or [])
    )

    if warnings:
        # Printed, never fatal: each of these is "could not check", and a
        # build that fails on a site refusing robots teaches you to ignore it.
        print(f"\n{len(warnings)} could not be verified (not a failure):")
        for w in warnings:
            print(f"  ? {w}")

    if errors:
        print(f"\nFAILED — {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK: {len(modules)} modules, {n_units} units, {n_res} resources, all rules pass")

    if not args.check:
        seed(modules)
        print("seeded ->", DB_PATH)
        if args.urls:
            n = stamp_verified(links.verified)
            print(f"verified_at stamped on {n} resource(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
