"""Print a YouTube video's own chapters, for authoring `watch` segments.

Eleven units hand you a video longer than the unit claims to be. Fixing that
means saying which part to watch -- and a timestamp invented from memory is
worse than no timestamp, because it sends you confidently to the wrong place.

Video authors already mark their chapters, and those markers are in the watch
page. This reads them, so every segment written into the curriculum is the
author's own boundary rather than a guess.

    python -m scripts.chapters https://www.youtube.com/watch?v=0sOvCWFmrtA
    python -m scripts.chapters 0sOvCWFmrtA --yaml 38:29 1:07:27
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def video_id(s: str) -> str:
    """Accept a bare id, a watch URL, or a youtu.be link."""
    if "youtu" not in s:
        return s.strip()
    p = urlparse(s)
    if p.netloc.endswith("youtu.be"):
        return p.path.lstrip("/")
    return parse_qs(p.query).get("v", [""])[0]


def hhmmss(seconds: int) -> str:
    h, m, sec = seconds // 3600, seconds % 3600 // 60, seconds % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def to_seconds(stamp: str) -> int:
    """'1:07:27' or '38:29' or '91' -> seconds."""
    parts = [int(p) for p in stamp.strip().split(":")]
    out = 0
    for p in parts:
        out = out * 60 + p
    return out


def fetch(vid: str) -> list[tuple[int, str]]:
    """The video's chapters as (start_seconds, title), in order."""
    r = subprocess.run(
        ["curl", "-s", "--max-time", "40", "-A", UA,
         f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    html = r.stdout or ""
    out: list[tuple[int, str]] = []
    for m in re.finditer(r'"chapterRenderer":\{(.*?)"thumbnail"', html, re.S):
        blob = m.group(1)
        title = re.search(r'"title":\{"simpleText":"(.*?)"', blob)
        start = re.search(r'"timeRangeStartMillis":(\d+)', blob)
        if title and start:
            out.append((int(start.group(1)) // 1000, title.group(1)))
    # The page carries each chapter twice (player bar and description); keep
    # the first of each start time, in order.
    seen: set[int] = set()
    return [(s, t) for s, t in out if not (s in seen or seen.add(s))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", help="URL or video id")
    ap.add_argument("--yaml", nargs=2, metavar=("FROM", "TO"),
                    help="emit a ready-to-paste watch: block for this range")
    args = ap.parse_args()

    vid = video_id(args.video)
    if not vid:
        print("Could not read a video id out of that.", file=sys.stderr)
        return 2

    chapters = fetch(vid)
    if not chapters:
        print("No chapters on this video — the author did not mark any.\n"
              "Pick the range by watching it, or choose a resource that is "
              "already the right length.", file=sys.stderr)
        return 1

    total = chapters[-1][0]
    print(f"{len(chapters)} chapters\n")
    for i, (start, title) in enumerate(chapters):
        end = chapters[i + 1][0] if i + 1 < len(chapters) else None
        span = f"{hhmmss(start)} - {hhmmss(end)}" if end else hhmmss(start)
        mins = f"{(end - start) // 60} min" if end else ""
        print(f"  {span:<20} {mins:<8} {title}")
        if end:
            total = end

    if args.yaml:
        a, b = to_seconds(args.yaml[0]), to_seconds(args.yaml[1])
        names = [t for s, t in chapters if a <= s < b]
        print("\n    watch:")
        print(f'      - {{ from: "{args.yaml[0]}", to: "{args.yaml[1]}", '
              f'why: "{names[0] if names else "…"} → {names[-1] if names else "…"}" }}')
        print(f"\n    ({(b - a) // 60} min of {total // 60} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
