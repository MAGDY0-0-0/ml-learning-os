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
from app.routes import dashboard, library, pages, projects, review, submissions, units
from app.web import BASE


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables and the FTS5 index before the first request is served."""
    init_db()
    yield


app = FastAPI(
    title="ML Learning OS",
    description="A local curriculum and study tool for learning ML engineering.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

app.include_router(dashboard.router)
app.include_router(units.router)
app.include_router(review.router)
app.include_router(library.router)
app.include_router(projects.router)
app.include_router(submissions.router)
app.include_router(pages.router)
