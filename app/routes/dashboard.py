"""Dashboard and module listing."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import tutor
from app.db import get_session
from app.models import (
    Card, CheckStatus, Module, Progress, Project, Resource, RubricCheck,
    StudySession, Unit, UnitStatus,
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
            }
        )

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
    rigor_total = rigor_done = 0
    for p in projects:
        checks = list(s.exec(select(RubricCheck).where(RubricCheck.project_id == p.id)))
        rigor_total += len(checks)
        rigor_done += sum(1 for c in checks if c.status != CheckStatus.unchecked)

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
            "overall_pct": round(100 * done_units / total_units) if total_units else 0,
            "minutes_week": minutes_week,
            "due": due,
            "projects": projects,
            "rigor_pct": round(100 * rigor_done / rigor_total) if rigor_total else 0,
            "provider": tutor.provider_status(),
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
