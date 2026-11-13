"""Read facts about a YouTube video from its public watch page.

Two callers need the same page: `python -m app.seed --check --urls`, which
compares the length a resource claims against the video's real length, and
`scripts/chapters.py`, which prints the chapters segments are authored from.

No API key and no extra dependency: the watch page embeds the player's own
data as JSON, and curl fetches it the same way the link checker fetches
everything else (httpx is blocked in some sandboxed shells; curl is not).

Every function here returns None or an empty list when the page does not
say, rather than raising. YouTube serves a consent page to some data-centre
IPs, and a missing fact must come back as "unknown", never as a wrong number.
"""

from __future__ import annotations

import json
import re
import subprocess

#: A full browser User-Agent. With a bare "Mozilla/5.0" YouTube sometimes
#: answers with a stripped page that carries no player data at all.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def watch_page(video_id: str, timeout: int = 40) -> str:
    """The HTML of a video's watch page, or "" when it could not be fetched."""
    try:
        out = subprocess.run(
            ["curl", "-s", "-L", "--max-time", str(timeout), "-A", BROWSER_UA,
             "-H", "Accept-Language: en-US,en",
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout + 15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout or ""


def length_seconds(html: str, video_id: str) -> int | None:
    """The video's length in seconds, read from its own `videoDetails`.

    Anchored on the video id: a watch page also carries lengths for the
    recommended videos beside it, and taking the first number on the page
    would be right only by luck.
    """
    m = re.search(
        r'"videoDetails":\{"videoId":"' + re.escape(video_id) + r'".{0,2000}?"lengthSeconds":"(\d+)"',
        html, re.S,
    )
    return int(m.group(1)) if m else None


def chapters(html: str) -> list[tuple[int, str]]:
    """The video's own chapter markers as (start_seconds, title), in order."""
    out: list[tuple[int, str]] = []
    for m in re.finditer(r'"chapterRenderer":\{(.*?)"thumbnail"', html, re.S):
        blob = m.group(1)
        title = re.search(r'"title":\{"simpleText":"(.*?)"', blob)
        start = re.search(r'"timeRangeStartMillis":(\d+)', blob)
        if title and start:
            out.append((int(start.group(1)) // 1000, _unescape(title.group(1))))
    # The page carries each chapter twice (player bar and description); keep
    # the first of each start time, in order.
    seen: set[int] = set()
    return [(s, t) for s, t in out if not (s in seen or seen.add(s))]


def _unescape(s: str) -> str:
    """Undo the JSON string escapes a chapter title can carry (\\u0026, \\")."""
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s
