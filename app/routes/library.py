"""The library: search your own PDFs, arXiv and Open Library."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
    # A hit knows its file path but not its document id, and the drawer opens
    # documents by id. Map one to the other here rather than widening the FTS
    # table with a column it would only ever echo back.
    doc_ids = {d.path: d.id for d in docs}
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
            "doc_ids": doc_ids,
        },
    )


@router.get("/library/doc/{doc_id}")
def library_doc(doc_id: int, s: Session = Depends(get_session)):
    """Serve one indexed PDF so the quick-view drawer can render it.

    Only files that are inside library/ *and* already in the index are served -
    the id has to resolve to a LibraryDoc row, and the resolved path has to sit
    under LIBRARY_DIR, so a doctored row cannot be used to read the disk.
    """
    doc = s.get(library.LibraryDoc, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such document.")
    path = Path(doc.path).resolve()
    root = library.LIBRARY_DIR.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="That file is no longer on the shelf.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/library/reindex")
def library_reindex(s: Session = Depends(get_session)):
    library.reindex_all(s)
    return RedirectResponse("/library", status_code=303)
