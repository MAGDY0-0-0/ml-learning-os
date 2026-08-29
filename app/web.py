"""Shared web plumbing: templates, template globals, and small view helpers.

Kept separate from main.py so the route modules can import these without
importing the app itself (which would be a circular import).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import ROOT
from app.models import ActiveResource, Progress, Resource, Unit

BASE = Path(__file__).parent
NOTES_DIR = ROOT / "notes"

templates = Jinja2Templates(directory=BASE / "templates")


# --------------------------------------------------------------------------
# template globals
# --------------------------------------------------------------------------


def embed_url(url: str) -> str | None:
    """Turn a YouTube watch/playlist URL into an embeddable one, else None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
        return None
    qs = parse_qs(parsed.query)
    if "list" in qs:
        return f"https://www.youtube.com/embed/videoseries?list={qs['list'][0]}"
    if "v" in qs:
        return f"https://www.youtube.com/embed/{qs['v'][0]}"
    if parsed.netloc.endswith("youtu.be"):
        return f"https://www.youtube.com/embed/{parsed.path.lstrip('/')}"
    return None


def asset(name: str) -> str:
    """URL for a file in app/static/, versioned by mtime so it is never stale.

    Takes a bare filename ("style.css"). Any leading "static/" is stripped —
    passing the full path once produced /static/static/... and 404'd, which
    silently rendered every page unstyled.
    """
    name = name.lstrip("/").removeprefix("static/")
    f = BASE / "static" / name
    try:
        return f"/static/{name}?v={int(f.stat().st_mtime)}"
    except OSError:
        return f"/static/{name}"


templates.env.globals["embed_url"] = embed_url
templates.env.globals["asset"] = asset


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything we store is UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_progress(s: Session, unit_id: int) -> Progress:
    """Fetch a unit's progress row, creating it on first access."""
    p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
    if p is None:
        p = Progress(unit_id=unit_id)
        s.add(p)
        s.commit()
        s.refresh(p)
    return p


def notes_path(unit_slug: str) -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR / f"{unit_slug}.md"


def read_notes(unit_slug: str) -> str:
    p = notes_path(unit_slug)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def ordered_resources(s: Session, unit: Unit) -> list[Resource]:
    """A unit's resources, with the currently-chosen one promoted to the front."""
    res = list(
        s.exec(select(Resource).where(Resource.unit_id == unit.id).order_by(Resource.rank))
    )
    active = s.exec(select(ActiveResource).where(ActiveResource.unit_id == unit.id)).first()
    if active:
        for i, r in enumerate(res):
            if r.id == active.resource_id and i != 0:
                res.insert(0, res.pop(i))
                break
    return res

VIDEO_KINDS = {"video", "playlist", "course"}


def is_video(kind) -> bool:
    """True for anything you watch."""
    return getattr(kind, "value", kind) in VIDEO_KINDS


def split_alternatives(resources: list[Resource]) -> tuple[list[Resource], list[Resource]]:
    """Split the non-primary resources into (same format, other formats).

    When someone rejects a video they almost always want a *different video*,
    not a different medium. So same-format alternatives are offered first, and
    other formats sit behind a separate, quieter heading.
    """
    if not resources:
        return [], []
    primary, rest = resources[0], resources[1:]
    same = [r for r in rest if is_video(r.kind) == is_video(primary.kind)]
    other = [r for r in rest if is_video(r.kind) != is_video(primary.kind)]
    return same, other


templates.env.globals["is_video"] = is_video
