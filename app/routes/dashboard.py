"""Dashboard and module listing."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import rig, studio, tutor
from app.db import get_session
from app.models import (
    Card, Module, Progress, StudySession, Unit, UnitStatus,
)
from app.web import as_utc, now_utc, templates

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

    # The projects are the point of all of it, so the dashboard counts down to
    # the next one rather than reporting a percentage of the whole.
    milestones = studio.milestones()
    for r in rows:
        r["minutes"] = sum(int(u.est_minutes or 0) for u in r["units"])
    # What each unit on the shelf asks of you, not just how long it takes.
    briefs = studio.briefs_for(current_row["units"]) if current_row else {}

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
            "briefs": briefs,
        },
    )


@router.get("/module/{slug}", response_class=HTMLResponse)
def module_view(slug: str, request: Request, s: Session = Depends(get_session)):
    m = s.exec(select(Module).where(Module.slug == slug)).first()
    if m is None:
        return RedirectResponse("/", status_code=303)
    units = list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
    ids = [u.id for u in units]
    prog = {
        p.unit_id: p for p in s.exec(select(Progress).where(Progress.unit_id.in_(ids)))
    } if ids else {}
    done_ids = {uid for uid, p in prog.items() if p.status == UnitStatus.done}
    briefs = studio.briefs_for(units)
    summary = studio.module_summary(units, briefs, done_ids)
    summary["started"] = any(p.status != UnitStatus.not_started for p in prog.values())
    milestone = next((x for x in studio.milestones() if x["gate_module"] == m.slug), None)
    return templates.TemplateResponse(
        request,
        "module.html",
        {
            "request": request, "module": m, "units": units, "prog": prog,
            "briefs": briefs, "summary": summary, "milestone": milestone,
            "outcomes": studio.json_list(m.outcomes_json),
        },
    )
