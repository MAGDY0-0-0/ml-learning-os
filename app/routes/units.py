"""Unit page: resources, swapping, notes, time logging, asking for help."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import tutor
from app.db import get_session
from app.models import (
    ActiveResource, Assignment, Card, Module, ResourcePreference,
    ResourceState, StudySession, SwapReason, Unit, UnitStatus, utcnow,
)
from app.web import (
    get_progress, notes_path, ordered_resources, read_notes, rejected_counts,
    split_alternatives, templates, youtube_ids,
)

router = APIRouter()


@router.get("/unit/{slug}", response_class=HTMLResponse)
def unit_view(slug: str, request: Request, s: Session = Depends(get_session)):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return RedirectResponse("/", status_code=303)
    m = s.get(Module, u.module_id)
    resources = ordered_resources(s, u)
    same_alts, other_alts = split_alternatives(resources)
    # Offer the teachers you have rejected least often first. If three
    # things have been marked "too slow", the next suggestion should not
    # be the one you already walked away from.
    rejects = rejected_counts()
    same_alts.sort(key=lambda r: rejects.get(r.id, 0))
    other_alts.sort(key=lambda r: rejects.get(r.id, 0))
    states = {st.resource_id: st for st in s.exec(select(ResourceState))}
    primary = resources[0] if resources else None
    assignments = list(s.exec(select(Assignment).where(Assignment.unit_id == u.id)))
    cards = list(s.exec(select(Card).where(Card.unit_id == u.id)))
    return templates.TemplateResponse(
        request,
        "unit.html",
        {
            "request": request,
            "unit": u,
            "module": m,
            "resources": resources,
            "same_alts": same_alts,
            "other_alts": other_alts,
            "states": states,
            "assignments": assignments,
            "cards": cards,
            "progress": get_progress(s, u.id),
            "notes": read_notes(u.slug),
            "reasons": [r.value for r in SwapReason],
            "yt": youtube_ids(primary.url) if primary else None,
        },
    )


@router.post("/unit/{slug}/notes")
def save_notes(slug: str, notes: str = Form(""), s: Session = Depends(get_session)):
    notes_path(slug).write_text(notes, encoding="utf-8")
    return RedirectResponse(f"/unit/{slug}", status_code=303)


@router.post("/unit/{slug}/log")
def log_time(slug: str, minutes: int = Form(25), s: Session = Depends(get_session)):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u:
        p = get_progress(s, u.id)
        p.minutes_logged += minutes
        if p.status == UnitStatus.not_started:
            p.status = UnitStatus.in_progress
            p.started_at = utcnow()
        s.add(StudySession(unit_id=u.id, minutes=minutes, ended_at=utcnow()))
        s.commit()
    return RedirectResponse(f"/unit/{slug}", status_code=303)


@router.post("/unit/{slug}/complete")
def complete_unit(slug: str, s: Session = Depends(get_session)):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u:
        p = get_progress(s, u.id)
        p.status = UnitStatus.done
        p.completed_at = utcnow()
        s.commit()
    return RedirectResponse(f"/unit/{slug}", status_code=303)


@router.post("/unit/{slug}/swap")
def swap_resource(
    slug: str,
    resource_id: int = Form(...),
    reason: str = Form("other"),
    note: str = Form(""),
    s: Session = Depends(get_session),
):
    """Promote the alternative the learner picked to be the primary resource.

    `resource_id` is the one they chose. The preference is recorded against the
    resource that *was* primary - that is the one that did not work for them.
    """
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return RedirectResponse("/", status_code=303)

    current = ordered_resources(s, u)
    if not current:
        return RedirectResponse(f"/unit/{slug}", status_code=303)
    outgoing = current[0]

    try:
        reason_enum = SwapReason(reason)
    except ValueError:
        reason_enum = SwapReason.other
    s.add(ResourcePreference(resource_id=outgoing.id, reason=reason_enum, note=note))

    if resource_id in {r.id for r in current}:
        active = s.exec(select(ActiveResource).where(ActiveResource.unit_id == u.id)).first()
        if active is None:
            s.add(ActiveResource(unit_id=u.id, resource_id=resource_id))
        else:
            active.resource_id = resource_id
    s.commit()
    return RedirectResponse(f"/unit/{slug}?swapped=1", status_code=303)


@router.post("/resource/{rid}/toggle")
def toggle_resource(rid: int, unit_slug: str = Form(...), s: Session = Depends(get_session)):
    st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
    if st is None:
        st = ResourceState(resource_id=rid, done=True)
        s.add(st)
    else:
        st.done = not st.done
    s.commit()
    return RedirectResponse(f"/unit/{unit_slug}", status_code=303)


# --------------------------------------------------------------------------
# Player state. These are called by app/static/player.js, often through
# sendBeacon on page hide, so they answer with a tiny JSON body and never a
# redirect - a 303 would be followed and waste a page render.
# --------------------------------------------------------------------------


@router.post("/resource/{rid}/position")
def save_position(rid: int, payload: dict = Body(...), s: Session = Depends(get_session)):
    """Remember where you stopped watching, so the card reopens there."""
    seconds = max(0, int(payload.get("seconds", 0) or 0))
    st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
    if st is None:
        st = ResourceState(resource_id=rid)
        s.add(st)
    st.position_seconds = seconds
    s.commit()
    return {"ok": True, "seconds": seconds}


@router.post("/resource/{rid}/watched")
def set_watched(rid: int, payload: dict = Body(default={}), s: Session = Depends(get_session)):
    """Tick a resource off once it has actually been watched to the end."""
    done = bool(payload.get("done", True))
    st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
    if st is None:
        st = ResourceState(resource_id=rid)
        s.add(st)
    st.done = done
    s.commit()
    return {"ok": True, "done": done}


@router.post("/unit/{slug}/log-auto")
def log_time_auto(slug: str, payload: dict = Body(...), s: Session = Depends(get_session)):
    """Credit minutes the player watched you spend, so you never type them in.

    Capped per call: a single beacon should never be able to claim an hour.
    """
    minutes = max(0, min(int(payload.get("minutes", 0) or 0), 30))
    if minutes == 0:
        return {"ok": True, "minutes": 0}
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return {"ok": False}
    p = get_progress(s, u.id)
    p.minutes_logged += minutes
    if p.status == UnitStatus.not_started:
        p.status = UnitStatus.in_progress
        p.started_at = utcnow()
    s.add(StudySession(unit_id=u.id, minutes=minutes, ended_at=utcnow()))
    s.commit()
    return {"ok": True, "minutes": p.minutes_logged}


@router.post("/unit/{slug}/notes/append")
def append_notes(slug: str, payload: dict = Body(...)):
    """Append a quote from the PDF drawer to this unit's notes file."""
    text = str(payload.get("text", "")).strip()
    if not text:
        return {"ok": False}
    path = notes_path(slug)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    sep = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + sep + text + "\n", encoding="utf-8")
    return {"ok": True}


@router.post("/unit/{slug}/ask")
def ask_help(
    slug: str,
    question: str = Form(...),
    resource_title: str = Form(""),
    s: Session = Depends(get_session),
):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return RedirectResponse("/", status_code=303)
    prompt = tutor.unit_help_prompt(
        u.title, u.objective, resource_title, read_notes(u.slug), question
    )
    path = tutor.write_inbox("ask", u.slug, prompt)
    answer = tutor.ask_inline(prompt)
    if answer:
        path.write_text(prompt + "\n\n---\n\n## Answer\n\n" + answer, encoding="utf-8")
    return RedirectResponse(f"/unit/{slug}?asked={path.name}", status_code=303)
