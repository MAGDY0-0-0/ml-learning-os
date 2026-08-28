"""Seed the DB from curriculum/*.yaml, and validate the curriculum's rules.

Run:
    python -m app.seed             # seed / re-seed (idempotent)
    python -m app.seed --check     # validate only, no writes
    python -m app.seed --check --urls   # also verify every URL returns 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml
from sqlmodel import Session, select

from app.db import ROOT, engine, init_db
from app.models import (
    FREE_COSTS,
    Assignment,
    Card,
    Cost,
    Module,
    Project,
    Resource,
    ResourceKind,
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


def validate_unit(unit: dict[str, Any], errors: list[str]) -> None:
    slug = unit.get("slug", "<no slug>")
    resources = unit.get("resources") or []

    if len(resources) < MIN_RESOURCES_PER_UNIT:
        errors.append(
            f"{slug}: has {len(resources)} resources, needs >= {MIN_RESOURCES_PER_UNIT} "
            "(so 'swap' always has somewhere to go)"
        )
        return

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


def validate(modules: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_units: set[str] = set()
    for mod in modules:
        if not mod.get("slug"):
            errors.append(f"{mod.get('_file')}: module has no slug")
        for unit in mod.get("units") or []:
            slug = unit.get("slug")
            if not slug:
                errors.append(f"{mod.get('_file')}: a unit has no slug")
                continue
            if slug in seen_units:
                errors.append(f"duplicate unit slug: {slug}")
            seen_units.add(slug)
            validate_unit(unit, errors)
            validate_assignments(unit, errors)
    return errors


#: Hosts that return 403/429 to any non-browser client but work fine for a
#: human. A 403 from these is reported as a warning, not a build failure.
BOT_BLOCKING_HOSTS = {
    "exercism.org",
    "www.coursera.org",
    "coursera.org",
    "www.amazon.com",
    "www.manning.com",
    "medium.com",
}


def _fetch_status(url: str) -> str:
    """Return an HTTP status code as a string, or an error token.

    Uses curl rather than httpx: httpx is blocked in some sandboxed shells,
    while curl is available and honours the system proxy configuration.
    """
    import subprocess

    try:
        out = subprocess.run(
            [
                "curl", "-sL", "-o", "/dev/null", "-w", "%{http_code}",
                "--max-time", "25", "-A", "Mozilla/5.0", url,
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        return (out.stdout or "").strip() or "000"
    except Exception as exc:  # noqa: BLE001
        return f"ERR:{type(exc).__name__}"


def check_urls(modules: Iterable[dict[str, Any]]) -> list[str]:
    from urllib.parse import urlparse

    errors: list[str] = []
    seen: set[str] = set()
    urls: list[tuple[str, str]] = []
    for mod in modules:
        for unit in mod.get("units") or []:
            for r in unit.get("resources") or []:
                url = r.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    urls.append((unit["slug"], url))

    for slug, url in urls:
        host = urlparse(url).netloc
        if host.startswith(("127.0.0.1", "localhost")):
            print(f"  --   {url}  (local app route; checked by the test suite)")
            continue
        status = _fetch_status(url)
        if status == "200":
            print(f"  200  {url}")
        elif status in {"403", "429"} and host in BOT_BLOCKING_HOSTS:
            print(f"  {status}  {url}  (bot-blocked host; fine in a browser)")
        else:
            errors.append(f"{slug}: HTTP {status} for {url}")
    return errors


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
                for stale in existing.values():
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only, no writes")
    ap.add_argument("--urls", action="store_true", help="also verify every URL")
    args = ap.parse_args()

    modules = load_modules()
    errors = validate(modules)
    if args.urls:
        print("checking urls...")
        errors += check_urls(modules)

    n_units = sum(len(m.get("units") or []) for m in modules)
    n_res = sum(
        len(u.get("resources") or []) for m in modules for u in (m.get("units") or [])
    )

    if errors:
        print(f"\nFAILED — {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK: {len(modules)} modules, {n_units} units, {n_res} resources, all rules pass")

    if not args.check:
        seed(modules)
        print("seeded ->", ROOT / "data" / "app.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
