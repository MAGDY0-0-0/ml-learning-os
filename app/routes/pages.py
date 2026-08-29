"""Static explanatory pages: the guided tour and the maths recap sheet."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import templates

router = APIRouter()


@router.get("/tour", response_class=HTMLResponse)
def tour(request: Request):
    return templates.TemplateResponse(
        request,
        "tour.html", {"request": request})


@router.get("/recap", response_class=HTMLResponse)
def recap(request: Request):
    """The M3 math recap sheet — the whole of the math module's reading."""
    return templates.TemplateResponse(request, "recap.html", {"request": request})
