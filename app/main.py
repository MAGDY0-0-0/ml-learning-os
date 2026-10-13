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

    Static files are exempt. They are already versioned by mtime in asset(),
    so they should be cached hard.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
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
