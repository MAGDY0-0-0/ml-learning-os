"""The library: search your own PDFs, arXiv and Open Library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import library
from app.db import get_session
from app.web import templates

router = APIRouter()


@router.get("/library", response_class=HTMLResponse)
def library_view(
    request: Request, q: str = "", source: str = "local", s: Session = Depends(get_session)
):
    hits, papers, books = [], [], []
    if q:
        if source == "arxiv":
            papers = library.search_arxiv(q)
        elif source == "books":
            books = library.search_openlibrary(q)
        else:
            hits = library.search(q)
    docs = list(s.exec(select(library.LibraryDoc)))
    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "request": request,
            "q": q,
            "source": source,
            "hits": hits,
            "papers": papers,
            "books": books,
            "docs": docs,
        },
    )


@router.post("/library/reindex")
def library_reindex(s: Session = Depends(get_session)):
    library.reindex_all(s)
    return RedirectResponse("/library", status_code=303)
