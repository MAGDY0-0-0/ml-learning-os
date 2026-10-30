"""ML Learning OS - application entry point.

Routes live in app/routes/, one module per feature area. Shared view helpers
and template globals live in app/web.py.

Run it with run.bat, or:
    python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routes import (
    backup, dashboard, experiments, library, pages, projects, review,
    submissions, units,
)
from app.web import BASE


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables and the FTS5 index before the first request is served."""
    init_db()
    yield


app = FastAPI(
    title="Magdy's ML Journey",
    description="A local curriculum and study tool for learning ML engineering.",
    lifespan=lifespan,
)

@app.middleware("http")
async def never_cache_pages(request, call_next):
    """Stop the browser serving a stale page.

    Every page here renders live database state -- your progress, what is due,
    which unit is next -- so a cached copy is always wrong. FastAPI sends no
    cache headers by default, which leaves browsers free to apply heuristic
    caching, and they do: a rebuilt dashboard kept rendering as the old one
    until a hard refresh, which looks exactly like the deploy not working.

    Static files go the other way. A URL from asset() carries ?v=<mtime>, so it
    changes whenever the file does and can be cached forever; without a header
    the browser re-asked for every stylesheet on every page change, and the new
    page could not paint until they came back. Fonts are not versioned but never
    change in place, so a week is safe.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        if response.status_code == 200 and "v" in request.query_params:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif response.status_code == 200 and path.startswith("/static/fonts/"):
            response.headers["Cache-Control"] = "public, max-age=604800"
        return response
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

app.include_router(dashboard.router)
app.include_router(units.router)
app.include_router(review.router)
app.include_router(library.router)
app.include_router(projects.router)
app.include_router(experiments.router)
app.include_router(backup.router)
app.include_router(submissions.router)
app.include_router(pages.router)
