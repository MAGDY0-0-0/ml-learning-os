"""Static explanatory pages: the guided tour and the maths recap sheet."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import search_index, templates

router = APIRouter()


@router.get("/api/search-index")
def api_search_index():
    """Everything the Ctrl-K palette can jump to.

    Fetched once, on the first time the palette is opened, and held in memory
    for the rest of the visit — the curriculum does not change while you study.
    """
    return {"items": search_index()}


@router.get("/tour", response_class=HTMLResponse)
def tour(request: Request):
    return templates.TemplateResponse(
        request,
        "tour.html", {"request": request})


@router.get("/recap", response_class=HTMLResponse)
def recap(request: Request):
    """The M3 math recap sheet — the whole of the math module's reading."""
    return templates.TemplateResponse(request, "recap.html", {"request": request})
