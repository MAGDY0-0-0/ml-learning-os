"""Spaced-repetition review."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import srs
from app.db import get_session
from app.models import Card
from app.web import as_utc, now_utc, templates

router = APIRouter()


@router.get("/review", response_class=HTMLResponse)
def review_view(request: Request, s: Session = Depends(get_session)):
    now = now_utc()
    due = [c for c in s.exec(select(Card)) if as_utc(c.due_at) <= now]
    due.sort(key=lambda c: c.due_at)
    total = len(list(s.exec(select(Card))))
    return templates.TemplateResponse(
        request,
        "review.html",
        {"request": request, "card": due[0] if due else None, "remaining": len(due), "total": total},
    )


@router.post("/review/{card_id}")
def grade_card(card_id: int, quality: int = Form(...), s: Session = Depends(get_session)):
    c = s.get(Card, card_id)
    if c:
        sched = srs.review(c.ease, c.interval_days, c.repetitions, c.lapses, quality)
        c.ease = sched.ease
        c.interval_days = sched.interval_days
        c.repetitions = sched.repetitions
        c.lapses = sched.lapses
        c.due_at = srs.next_due(sched.interval_days)
        s.commit()
    return RedirectResponse("/review", status_code=303)
