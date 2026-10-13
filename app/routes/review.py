"""Spaced-repetition review.

A review session is dozens of cards in a row, so the cost of a page load is
paid dozens of times. Grading therefore answers with the *next* card as JSON
and review.js swaps it in place; the plain form post still works and still
redirects, so the page is fully usable with no JavaScript at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import srs
from app.db import get_session
from app.models import Card
from app.web import as_utc, now_utc, templates

router = APIRouter()


def due_cards(s: Session) -> list[Card]:
    now = now_utc()
    due = [c for c in s.exec(select(Card)) if as_utc(c.due_at) <= now]
    due.sort(key=lambda c: c.due_at)
    return due


def as_json(card: Card | None, remaining: int) -> dict:
    """The shape review.js expects. `card` is null when the queue is empty."""
    return {
        "remaining": remaining,
        "card": None
        if card is None
        else {
            "id": card.id,
            "front": card.front,
            "back": card.back,
            "ease": round(card.ease, 2),
            "interval_days": card.interval_days,
            "lapses": card.lapses,
        },
    }


@router.get("/review", response_class=HTMLResponse)
def review_view(request: Request, s: Session = Depends(get_session)):
    due = due_cards(s)
    total = len(list(s.exec(select(Card))))
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "request": request,
            "card": due[0] if due else None,
            "remaining": len(due),
            "total": total,
        },
    )


def _grade(s: Session, card_id: int, quality: int) -> None:
    c = s.get(Card, card_id)
    if c is None:
        return
    sched = srs.review(c.ease, c.interval_days, c.repetitions, c.lapses, quality)
    c.ease = sched.ease
    c.interval_days = sched.interval_days
    c.repetitions = sched.repetitions
    c.lapses = sched.lapses
    c.due_at = srs.next_due(sched.interval_days)
    s.commit()


@router.post("/review/{card_id}")
def grade_card(card_id: int, quality: int = Form(...), s: Session = Depends(get_session)):
    """Grade a card the no-JavaScript way: post, then redirect to the next."""
    _grade(s, card_id, quality)
    return RedirectResponse("/review", status_code=303)


@router.post("/api/review/{card_id}")
def grade_card_json(card_id: int, payload: dict, s: Session = Depends(get_session)):
    """Grade a card and hand back the next one, so the page never reloads."""
    try:
        quality = int(payload.get("quality", -1))
    except (TypeError, ValueError):
        return {"ok": False, "error": "quality must be a whole number 0-5"}
    if not 0 <= quality <= 5:
        return {"ok": False, "error": "quality must be 0-5"}

    _grade(s, card_id, quality)
    due = due_cards(s)
    return {"ok": True, **as_json(due[0] if due else None, len(due))}
