"""Presentation helpers for the studio interface: phases, generated artwork,
and the few derived facts the Today screen and lesson mode display.

Everything here is read-only. Every number a template shows through these
helpers comes from the database or from the exercise files on disk — nothing
is estimated, so a value that does not exist yet (no submission, no minutes)
comes back as None/0 and the template omits it rather than inventing one.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from markupsafe import Markup, escape
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import ROOT, engine
from app.models import (
    ActiveResource, Assignment, Card, Module, Progress, Project, Resource, Submission, Unit,
    UnitStatus,
)

# --------------------------------------------------------------------------
# phases: one colour and one glyph per kind of work
# --------------------------------------------------------------------------

PHASES = {
    "M0": "python", "M1": "python",
    "M2": "data", "M3": "data",
    "M4": "classic",
    "M5": "deep",
    "M6": "transformer", "M7": "transformer",
    "M8": "systems", "M9": "systems",
}
PHASE_NAMES = {
    "python": "Python", "data": "Data", "classic": "Classical ML",
    "deep": "Deep learning", "transformer": "Transformers", "systems": "Systems",
}

#: base, glow, highlight, glyph ink — the artwork palette per phase.
PALETTE = {
    "python":      ("#081a36", "#2f7cff", "#6fd2ff", "#a9d4ff"),
    "data":        ("#2a1702", "#ff9f0a", "#ffd27a", "#ffe2a8"),
    "classic":     ("#062012", "#30d158", "#b6f2a3", "#c9f7c0"),
    "deep":        ("#1b0b2c", "#9a4fd4", "#e6a8ff", "#ecc9ff"),
    "transformer": ("#2b0d0a", "#ff6a55", "#ffb39b", "#ffd0c2"),
    "systems":     ("#042220", "#3fd9c4", "#a8fff1", "#c4fff6"),
}

#: 24x24 line glyphs. The icon sprite in _icons.html is generated from this
#: too, so the small icon and the large artwork can never drift apart.
GLYPHS = {
    "python": '<path d="M8 3H7a2 2 0 0 0-2 2v4a2 2 0 0 1-2 2 2 2 0 0 1 2 2v4a2 2 0 0 0 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-4a2 2 0 0 1 2-2 2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/>',
    "data": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/>',
    "classic": '<path d="M3 3v18h18"/><circle cx="8" cy="15" r="1.2"/><circle cx="11" cy="11" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="18" cy="7" r="1.2"/><path d="m6 17 13-11"/>',
    "deep": '<circle cx="5" cy="7" r="2"/><circle cx="5" cy="17" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="12" r="2"/><path d="m7 7.5 3-1.6M7 8l3 3M7 16l3-3M7 16.5l3 1.6M14 5.8l3.4 4.8M14 12h3M14 18.2l3.4-4.8"/>',
    "transformer": '<path d="M12 3v3"/><path d="M12 18v3"/><path d="M5.6 5.6l2.1 2.1"/><path d="M16.3 16.3l2.1 2.1"/><path d="M3 12h3"/><path d="M18 12h3"/><path d="M5.6 18.4l2.1-2.1"/><path d="M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="3"/>',
    "systems": '<rect width="18" height="7" x="3" y="3" rx="2"/><rect width="18" height="7" x="3" y="14" rx="2"/><path d="M7 6.5h.01"/><path d="M7 17.5h.01"/>',
}


def phase(code: str | None) -> str:
    """A module code ("M4") or slug ("m4-classical") -> phase key."""
    return PHASES.get((code or "").split("-")[0].upper(), "systems")


def phase_name(code: str | None) -> str:
    return PHASE_NAMES[phase(code)]


def phase_icon(code: str | None, cls: str = "i") -> Markup:
    return Markup(
        f'<svg class="{escape(cls)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f'<use href="#ph-{phase(code)}"/></svg>'
    )


def short_title(module: Module | None) -> str:
    """'M2 · The data stack + first rigor rung' -> 'The data stack + first rigor rung'."""
    return module.title.split("·")[-1].strip() if module else ""


# --------------------------------------------------------------------------
# generated artwork — no image files to maintain
# --------------------------------------------------------------------------

_LIGHT = [((.15, .20), (.85, .90), (.55, .05)), ((.75, .15), (.20, .80), (.95, .55)),
          ((.30, .85), (.80, .20), (.05, .40)), ((.88, .70), (.25, .18), (.50, .95)),
          ((.50, .30), (.10, .95), (.90, .10))]

#: Four glyph poses so neighbouring posters in a row never look identical.
POSES = [((.70, .46), .78, -6), ((.74, .52), .95, 8), ((.62, .44), .70, 0), ((.78, .40), .85, -12)]


def phase_art(code: str | None, key: str, seed: int = 0, at: tuple[float, float] = (.7, .5),
              size: float = .75, rot: float = 0, w: int = 1600, h: int = 900,
              vignette: float = .3, pose: int | None = None, glyph: bool = True) -> Markup:
    """An SVG that fills its box: light fields in the phase's colours, the
    phase glyph drawn crisp, and a soft echo of it behind for depth.

    `key` must be unique on the page — it namespaces the gradient ids.
    `pose` picks one of POSES and overrides at/size/rot.
    """
    ph = phase(code)
    base, g1, g2, ink = PALETTE[ph]
    uid = "pa-" + re.sub(r"[^a-zA-Z0-9_-]", "-", str(key))
    if pose is not None:
        at, size, rot = POSES[pose % len(POSES)]
    (x1, y1), (x2, y2), (x3, y3) = _LIGHT[seed % len(_LIGHT)]
    gs = size * h / 24
    gx, gy = at[0] * w - 12 * gs, at[1] * h - 12 * gs
    sw = max(min(1.25 * 24 / (size * h) * (h / 450), 1.6), .5)
    glyph_svg = ""
    if glyph:
        glyph_svg = (
            f'<g transform="translate({gx + gs * 1.2:.1f},{gy + gs * .9:.1f}) rotate({rot} {12 * gs:.1f} {12 * gs:.1f}) '
            f'scale({gs * 1.18:.2f})" fill="none" stroke="{g2}" stroke-width="{sw * 1.6:.2f}" stroke-linecap="round" '
            f'stroke-linejoin="round" opacity=".22" filter="url(#{uid}b)">{GLYPHS[ph]}</g>'
            f'<g transform="translate({gx:.1f},{gy:.1f}) rotate({rot} {12 * gs:.1f} {12 * gs:.1f}) scale({gs:.2f})" '
            f'fill="none" stroke="url(#{uid}s)" stroke-width="{sw:.2f}" stroke-linecap="round" '
            f'stroke-linejoin="round">{GLYPHS[ph]}</g>'
        )
    return Markup(f'''<svg class="art" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false"><defs>
<radialGradient id="{uid}1" cx="{x1}" cy="{y1}" r=".7"><stop offset="0" stop-color="{g1}" stop-opacity=".9"/><stop offset="1" stop-color="{g1}" stop-opacity="0"/></radialGradient>
<radialGradient id="{uid}2" cx="{x2}" cy="{y2}" r=".55"><stop offset="0" stop-color="{g2}" stop-opacity=".4"/><stop offset="1" stop-color="{g2}" stop-opacity="0"/></radialGradient>
<radialGradient id="{uid}3" cx="{x3}" cy="{y3}" r=".45"><stop offset="0" stop-color="{g1}" stop-opacity=".35"/><stop offset="1" stop-color="{g1}" stop-opacity="0"/></radialGradient>
<radialGradient id="{uid}v" cx=".5" cy=".5" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="{vignette}"/></radialGradient>
<linearGradient id="{uid}s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff"/><stop offset=".5" stop-color="{ink}" stop-opacity=".8"/><stop offset="1" stop-color="{g1}" stop-opacity=".35"/></linearGradient>
<filter id="{uid}b" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="{max(gs * .25, 1):.1f}"/></filter>
</defs><rect width="{w}" height="{h}" fill="{base}"/><rect width="{w}" height="{h}" fill="url(#{uid}1)"/><rect width="{w}" height="{h}" fill="url(#{uid}2)"/><rect width="{w}" height="{h}" fill="url(#{uid}3)"/>{glyph_svg}<rect width="{w}" height="{h}" fill="url(#{uid}v)"/></svg>''')


# --------------------------------------------------------------------------
# derived facts
# --------------------------------------------------------------------------


def fmt_minutes(minutes: int | None) -> str:
    """45 -> '45 min', 154 -> '2 h 34 min', 120 -> '2 h'."""
    m = int(minutes or 0)
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} h {r} min" if r else f"{h} h"


def next_unit(unit: Unit) -> dict | None:
    """The unit after this one: next in its module, else the first unit of the
    next module. None after the last unit of the curriculum."""
    with Session(engine) as s:
        mods = list(s.exec(select(Module).order_by(Module.order)))
        for i, m in enumerate(mods):
            if m.id != unit.module_id:
                continue
            here = list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
            ids = [u.id for u in here]
            pos = ids.index(unit.id) if unit.id in ids else len(ids) - 1
            if pos + 1 < len(here):
                return {"unit": here[pos + 1], "module": m}
            for later in mods[i + 1:]:
                first = s.exec(
                    select(Unit).where(Unit.module_id == later.id).order_by(Unit.order)
                ).first()
                if first is not None:
                    return {"unit": first, "module": later}
            return None
    return None


def module_position(unit: Unit) -> dict:
    """Where a unit sits in its module, and how much of the module is done."""
    with Session(engine) as s:
        m = s.get(Module, unit.module_id)
        units = list(s.exec(select(Unit).where(Unit.module_id == unit.module_id).order_by(Unit.order)))
        ids = [u.id for u in units]
        done_ids = {
            p.unit_id for p in s.exec(
                select(Progress).where(Progress.status == UnitStatus.done, Progress.unit_id.in_(ids))
            )
        } if ids else set()
    return {
        "module": m,
        "units": units,
        "index": ids.index(unit.id) + 1 if unit.id in ids else 0,
        "total": len(units),
        "done": len(done_ids),
        "done_ids": done_ids,
    }


def count_checks(tests_path: str) -> int:
    """How many tests an exercise's test files define, read with `ast`.

    Counts module-level `test_*` functions and `test_*` methods of `Test*`
    classes — what pytest collects for these files. A parametrised test would
    be counted once, which is why the last run's own total is preferred as soon
    as there is one (see practice_status).
    """
    if not tests_path:
        return 0
    p = Path(tests_path)
    d = p if p.is_absolute() else ROOT / p
    if not d.is_dir():
        return 0
    n = 0
    for f in sorted(d.glob("test_*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                n += 1
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                n += sum(
                    1 for b in node.body
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name.startswith("test_")
                )
    return n


def practice_status(unit_id: int) -> list[dict]:
    """Per exercise on a unit: its check count and what your runs achieved."""
    with Session(engine) as s:
        out = []
        for a in s.exec(select(Assignment).where(Assignment.unit_id == unit_id)):
            runs = list(s.exec(
                select(Submission).where(Submission.assignment_id == a.id)
                .order_by(Submission.created_at.desc(), Submission.id.desc())
            ))
            last = runs[0] if runs else None
            best = max(runs, key=lambda r: (r.tests_passed, -r.timed_out), default=None)
            static = count_checks(a.tests_path)
            total = (last.tests_total if last and last.tests_total else static)
            out.append({
                "assignment": a,
                "checks": total,
                "runs": len(runs),
                "last": last,
                "best": best,
                "passed_all": bool(best and best.tests_total and best.tests_passed == best.tests_total),
            })
        return out


# --------------------------------------------------------------------------
# the briefing: what you are walking into, before you start
# --------------------------------------------------------------------------
# Four parts of a briefing are authored (why, outcomes, needs, skip_if) and
# live on the Unit. Everything here is derived from the resources, the
# exercises and the checks, so the plan a unit shows cannot drift away from
# what the unit actually asks you to do.

#: Minutes the plan allows for each checkpoint question.
CHECK_MINUTES = 2
#: The least time a plan may give one exercise; seed --check enforces it too.
EXERCISE_MIN_MINUTES = 20

#: What you do with a resource, by kind.
VERBS = {
    "video": "Watch", "playlist": "Watch", "course": "Watch",
    "book": "Read", "paper": "Read", "article": "Read", "docs": "Read",
    "interactive": "Work through", "repo": "Read the code",
}


def json_list(raw: str | None) -> list:
    try:
        out = json.loads(raw or "[]")
    except ValueError:
        return []
    return out if isinstance(out, list) else []


def build_plan(unit: Unit, primary: Resource | None, exercises: list[dict], n_checks: int) -> list[dict]:
    """The numbered "what you'll do" list, with minutes that add up.

    Learn takes what the main resource (or its `watch` segments) really
    takes. Checks take CHECK_MINUTES each. What the unit's total leaves over
    goes to the exercise, or, with no exercise, to trying it yourself. So the
    items sum to the unit's est_minutes exactly -- unless learning plus checks
    already exceed it, which is a dishonest total, and the curriculum test
    over every unit fails on exactly that.
    """
    items: list[dict] = []
    if primary is not None:
        kind = getattr(primary.kind, "value", primary.kind)
        verb = VERBS.get(kind, "Study")
        segments = json_list(primary.watch_json)
        if segments:
            for seg in segments:
                end = seg.get("to")
                if end is None:
                    end = (primary.est_minutes or 0) * 60
                items.append({"kind": "learn", "verb": verb, "title": seg.get("title", primary.title),
                              "minutes": max(1, round((end - seg.get("from", 0)) / 60))})
        else:
            items.append({"kind": "learn", "verb": verb, "title": primary.title,
                          "minutes": int(primary.est_minutes or 0)})

    learn = sum(i["minutes"] for i in items)
    checks = CHECK_MINUTES * n_checks
    left = int(unit.est_minutes or 0) - learn - checks

    if exercises:
        title = exercises[0]["title"] if len(exercises) == 1 else f"{len(exercises)} exercises"
        n = sum(e["checks"] for e in exercises)
        items.append({"kind": "practice", "verb": "Practise", "title": title,
                      "detail": f"{n} automatic check{'s' if n != 1 else ''}" if n else "",
                      "minutes": max(left, 0)})
    elif left > 0:
        items.append({"kind": "try", "verb": "Try it", "title": "Follow along in your own code and keep notes",
                      "minutes": left})
    if n_checks:
        items.append({"kind": "check", "verb": "Check",
                      "title": f"{n_checks} quick question{'s' if n_checks != 1 else ''}",
                      "minutes": checks})
    return items


def summary_parts(plan: list[dict], n_exercises: int, n_checks: int) -> list[str]:
    """["Watch 33 min", "1 exercise", "3 checks"] -- what a row or tile shows."""
    learn = [i for i in plan if i["kind"] == "learn"]
    parts = []
    if learn:
        parts.append(f"{learn[0]['verb']} {fmt_minutes(sum(i['minutes'] for i in learn))}")
    if n_exercises:
        parts.append(f"{n_exercises} exercise{'s' if n_exercises != 1 else ''}")
    if n_checks:
        parts.append(f"{n_checks} check{'s' if n_checks != 1 else ''}")
    return parts


def briefs_for(units: list[Unit]) -> dict[int, dict]:
    """Every unit's briefing, in a fixed number of queries however many units.

    The module page shows one per row and Today one per poster; asking unit
    by unit would cost a handful of queries each.
    """
    ids = [u.id for u in units]
    if not ids:
        return {}
    with Session(engine) as s:
        res_by_unit: dict[int, list[Resource]] = {}
        for r in s.exec(select(Resource).where(Resource.unit_id.in_(ids)).order_by(Resource.rank)):
            res_by_unit.setdefault(r.unit_id, []).append(r)
        active = {a.unit_id: a.resource_id
                  for a in s.exec(select(ActiveResource).where(ActiveResource.unit_id.in_(ids)))}
        asg_by_unit: dict[int, list[Assignment]] = {}
        for a in s.exec(select(Assignment).where(Assignment.unit_id.in_(ids))):
            asg_by_unit.setdefault(a.unit_id, []).append(a)
        cards = dict(s.exec(
            select(Card.unit_id, func.count(Card.id)).where(Card.unit_id.in_(ids)).group_by(Card.unit_id)
        ).all())
        need_slugs = sorted({n for u in units for n in json_list(u.needs_json)})
        needed = list(s.exec(select(Unit).where(Unit.slug.in_(need_slugs)))) if need_slugs else []
        needed_ids = [n.id for n in needed]
        done = {p.unit_id for p in s.exec(
            select(Progress).where(Progress.status == UnitStatus.done, Progress.unit_id.in_(needed_ids))
        )} if needed_ids else set()

    by_slug = {n.slug: n for n in needed}
    out: dict[int, dict] = {}
    for u in units:
        resources = res_by_unit.get(u.id, [])
        primary = next((r for r in resources if r.id == active.get(u.id)), resources[0] if resources else None)
        exercises = [{"title": a.title, "slug": a.slug, "checks": count_checks(a.tests_path)}
                     for a in asg_by_unit.get(u.id, [])]
        n_checks = len(json_list(u.checkpoint_json))
        plan = build_plan(u, primary, exercises, n_checks)
        out[u.id] = {
            "why": u.why,
            "outcomes": json_list(u.outcomes_json),
            "skip_if": u.skip_if,
            "needs": [{"unit": by_slug[n], "done": by_slug[n].id in done}
                      for n in json_list(u.needs_json) if n in by_slug],
            "plan": plan,
            "total": sum(i["minutes"] for i in plan),
            "exercises": exercises,
            "checks": n_checks,
            "cards": int(cards.get(u.id, 0)),
            "parts": summary_parts(plan, len(exercises), n_checks),
            "summary": " · ".join(summary_parts(plan, len(exercises), n_checks)),
        }
    return out


def unit_brief(unit: Unit) -> dict:
    return briefs_for([unit])[unit.id]


def module_summary(units: list[Unit], briefs: dict[int, dict], done_ids: set[int]) -> dict:
    """Real totals for a module page, and which unit "Start" should open."""
    nxt = next((u for u in units if u.id not in done_ids), None)
    return {
        "units": len(units),
        "minutes": sum(int(u.est_minutes or 0) for u in units),
        "exercises": sum(len(briefs[u.id]["exercises"]) for u in units if u.id in briefs),
        "checks": sum(briefs[u.id]["checks"] for u in units if u.id in briefs),
        "next": nxt,
        "started": bool(done_ids & {u.id for u in units}),
    }


def milestones() -> list[dict]:
    """Each project, and how many units stand between you and it.

    A project unlocks when every unit up to the end of its module is done.
    The distance counts units, not modules: "4 units away" is an evening's
    work, which is the number worth showing.
    """
    with Session(engine) as s:
        mods = list(s.exec(select(Module).order_by(Module.order)))
        per_module = dict(s.exec(select(Unit.module_id, func.count(Unit.id)).group_by(Unit.module_id)).all())
        done_units = s.exec(
            select(func.count(Progress.id)).where(Progress.status == UnitStatus.done)
        ).one()
        projects = list(s.exec(select(Project)))
    cumulative, reached = 0, {}
    for m in mods:
        cumulative += per_module.get(m.id, 0)
        reached[m.slug] = cumulative
    out = []
    for p in projects:
        away = max(0, reached.get(p.module_slug, cumulative) - done_units)
        out.append({"project": p, "units_away": away, "unlocked": away == 0, "gate_module": p.module_slug})
    return out
