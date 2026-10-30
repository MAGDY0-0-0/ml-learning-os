"""Dashboard and module listing."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import rig, tutor
from app.db import get_session
from app.models import (
    Card, Module, Progress, Project, Resource, StudySession, Unit, UnitStatus,
)
from app.web import as_utc, is_video, now_utc, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, s: Session = Depends(get_session)):
    modules = list(s.exec(select(Module).order_by(Module.order)))
    prog = {p.unit_id: p for p in s.exec(select(Progress))}

    rows = []
    total_units = done_units = 0
    current_unit = None
    for m in modules:
        units = list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
        done = sum(1 for u in units if prog.get(u.id) and prog[u.id].status == UnitStatus.done)
        total_units += len(units)
        done_units += done
        if current_unit is None:
            for u in units:
                st = prog.get(u.id)
                if st is None or st.status != UnitStatus.done:
                    current_unit = u
                    break
        rows.append(
            {
                "module": m,
                "units": units,
                "done": done,
                "total": len(units),
                "pct": round(100 * done / len(units)) if units else 0,
                "current": False,
            }
        )

    # Which module you are standing in, and how far to the end of it. At the
    # start of a long curriculum this is the only number that feels reachable:
    # "6% complete" is discouraging, "2 units left in M0" is a evening's work.
    current_row = None
    for r in rows:
        if current_unit is not None and current_unit.module_id == r["module"].id:
            r["current"] = True
            current_row = r
            break

    week_ago = now_utc() - timedelta(days=7)
    minutes_week = sum(
        ss.minutes
        for ss in s.exec(select(StudySession))
        if ss.started_at and as_utc(ss.started_at) >= week_ago
    )
    due = len(
        [c for c in s.exec(select(Card)) if as_utc(c.due_at) <= now_utc()]
    )

    projects = list(s.exec(select(Project)))

    # The projects are the point of all of it, so the dashboard counts down to
    # the next one rather than reporting a percentage of the whole.
    cumulative = 0
    reached: dict[str, int] = {}
    for r in rows:
        cumulative += r["total"]
        reached[r["module"].slug] = cumulative

    milestones = []
    for p in projects:
        gate = reached.get(p.module_slug, total_units)
        away = max(0, gate - done_units)
        milestones.append(
            {
                "project": p,
                "units_away": away,
                "unlocked": away == 0,
                "gate_module": p.module_slug,
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "rows": rows,
            "prog": prog,
            "current_unit": current_unit,
            "total_units": total_units,
            "done_units": done_units,
            "minutes_week": minutes_week,
            "due": due,
            "provider": tutor.provider_status(),
            "rig": rig.describe(),
            "current_row": current_row,
            "milestones": milestones,
        },
    )


@router.get("/module/{slug}", response_class=HTMLResponse)
def module_view(slug: str, request: Request, s: Session = Depends(get_session)):
    m = s.exec(select(Module).where(Module.slug == slug)).first()
    if m is None:
        return RedirectResponse("/", status_code=303)
    units = list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
    prog = {p.unit_id: p for p in s.exec(select(Progress))}
    counts, vcounts = {}, {}
    for u in units:
        rs = list(s.exec(select(Resource).where(Resource.unit_id == u.id)))
        counts[u.id] = len(rs)
        vcounts[u.id] = sum(1 for r in rs if is_video(r.kind))
    return templates.TemplateResponse(
        request,
        "module.html",
        {"request": request, "module": m, "units": units, "prog": prog, "counts": counts, "vcounts": vcounts},
    )
