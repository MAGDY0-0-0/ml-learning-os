"""Shared web plumbing: templates, template globals, and small view helpers.

Kept separate from main.py so the route modules can import these without
importing the app itself (which would be a circular import).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlmodel import Session, select

from app.db import ROOT, engine
from app.models import ActiveResource, Progress, Resource, Unit, UnitStatus

BASE = Path(__file__).parent
NOTES_DIR = ROOT / "notes"

templates = Jinja2Templates(directory=BASE / "templates")


# --------------------------------------------------------------------------
# template globals
# --------------------------------------------------------------------------


def youtube_ids(url: str) -> dict[str, str] | None:
    """Split a YouTube URL into the video and playlist ids the player needs.

    player.js drives the IFrame API rather than dropping in a plain <iframe>,
    and it needs the two ids separately: to start a playlist at the right
    entry, and to rebuild a "watch on YouTube at 4:12" link from live position.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
        return None
    qs = parse_qs(parsed.query)
    video = qs.get("v", [""])[0]
    if not video and parsed.netloc.endswith("youtu.be"):
        video = parsed.path.lstrip("/")
    playlist = qs.get("list", [""])[0]
    if not video and not playlist:
        return None
    return {"video": video, "list": playlist}


#: Where a resource actually lives, keyed by host. Naming the platform on the
#: card matters once the curriculum stops being YouTube-only: "opens on
#: DeepLearning.AI" sets the expectation before the click, rather than after.
PLATFORMS = {
    "youtube.com": "YouTube",
    "www.youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "vimeo.com": "Vimeo",
    "www.deeplearning.ai": "DeepLearning.AI",
    "deeplearning.ai": "DeepLearning.AI",
    "learn.deeplearning.ai": "DeepLearning.AI",
    "www.coursera.org": "Coursera",
    "coursera.org": "Coursera",
    "www.edx.org": "edX",
    "ocw.mit.edu": "MIT OpenCourseWare",
    "course.fast.ai": "fast.ai",
    "www.fast.ai": "fast.ai",
    "academy.claude.com": "Anthropic Academy",
    "huggingface.co": "Hugging Face",
    "www.kaggle.com": "Kaggle",
    "scikit-learn.org": "scikit-learn docs",
    "pytorch.org": "PyTorch docs",
    "docs.pytorch.org": "PyTorch docs",
    "github.com": "GitHub",
    "arxiv.org": "arXiv",
}

#: Hosts the in-app player can actually drive. Everything else opens in a new
#: tab, and the unit page says so instead of showing an empty player.
EMBEDDABLE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
}


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def platform_of(url: str) -> str:
    """A human name for where this resource lives, or the bare host."""
    host = _host(url)
    return PLATFORMS.get(host) or host.removeprefix("www.")


def is_embeddable(url: str) -> bool:
    """True when the in-app player can drive this URL.

    Most top-tier video is YouTube-hosted even when it is *presented*
    elsewhere: course.fast.ai embeds youtube-nocookie, MIT OCW serves through
    youtube.com/mitocw. The genuine exceptions are platforms with their own
    players -- DeepLearning.AI, Coursera, Anthropic Academy -- which cannot be
    embedded at all, and must be linked out to honestly.
    """
    return _host(url) in EMBEDDABLE_HOSTS


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


def icon(name: str, cls: str = "i") -> Markup:
    """Reference one symbol from the sprite in templates/_icons.html.

    Stroke geometry lives in the sprite; size and colour come from CSS, so an
    icon inherits the text colour of whatever it sits in.
    """
    return Markup(
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true"><use href="#ic-{name}"/></svg>'
    )


def nav_modules() -> list[dict]:
    """Modules with their completion, for the rail that every page renders.

    Opens its own short-lived session: the rail is chrome, not part of any one
    view's data, and threading a session through every template context just to
    draw it would couple every route to it.
    """
    from app.models import Module, Progress, Unit

    with Session(engine) as s:
        mods = list(s.exec(select(Module).order_by(Module.order)))
        units = list(s.exec(select(Unit)))
        done_ids = {
            p.unit_id
            for p in s.exec(select(Progress).where(Progress.status == UnitStatus.done))
        }

    by_module: dict[int, list[Unit]] = {}
    for u in units:
        by_module.setdefault(u.module_id, []).append(u)

    out = []
    for m in mods:
        mine = by_module.get(m.id, [])
        done = sum(1 for u in mine if u.id in done_ids)
        out.append(
            {
                "slug": m.slug,
                "title": m.title,
                "code": m.slug.split("-")[0].upper(),
                "total": len(mine),
                "done": done,
                "pct": round(100 * done / len(mine)) if mine else 0,
            }
        )
    return out


def search_index() -> list[dict]:
    """Everything the command palette can jump to: units, modules, projects."""
    from app.models import Module, Project, Unit

    with Session(engine) as s:
        mods = {m.id: m for m in s.exec(select(Module))}
        items = [
            {"k": m.slug.split("-")[0].upper(), "t": m.title, "u": f"/module/{m.slug}"}
            for m in mods.values()
        ]
        items += [
            {
                "k": mods[u.module_id].slug.split("-")[0].upper() if u.module_id in mods else "",
                "t": u.title,
                "u": f"/unit/{u.slug}",
            }
            for u in s.exec(select(Unit).order_by(Unit.order))
        ]
        items += [
            {"k": "PROJ", "t": p.title, "u": f"/project/{p.slug}"}
            for p in s.exec(select(Project))
        ]
    return items


def active_module(path: str) -> str:
    """Which module the current URL sits in, so the rail can mark it.

    Derived from the path rather than passed in by each route: the rail is
    rendered by the base template on every page, and making ten routes all
    remember to supply the same context key is how it silently stops working —
    which is exactly what had happened.
    """
    from app.models import Module, Unit

    if path.startswith("/module/"):
        return path.removeprefix("/module/").split("/")[0]
    if path.startswith("/unit/"):
        slug = path.removeprefix("/unit/").split("/")[0]
        with Session(engine) as s:
            u = s.exec(select(Unit).where(Unit.slug == slug)).first()
            if u is None:
                return ""
            m = s.get(Module, u.module_id)
            return m.slug if m else ""
    return ""


def due_count() -> int:
    """Cards due right now, for the badge on the Review link."""
    from app.models import Card

    with Session(engine) as s:
        return sum(1 for c in s.exec(select(Card)) if as_utc(c.due_at) <= now_utc())


templates.env.globals["asset"] = asset
templates.env.globals["icon"] = icon
templates.env.globals["platform_of"] = platform_of
templates.env.globals["is_embeddable"] = is_embeddable
templates.env.globals["nav_modules"] = nav_modules
templates.env.globals["active_module"] = active_module
templates.env.globals["due_count"] = due_count


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
