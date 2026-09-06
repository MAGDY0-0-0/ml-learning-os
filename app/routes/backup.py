"""Download and restore your progress.

data/app.db and notes/ are both gitignored and both single copies. This is the
only way to get your progress off this machine, and the only way to get it back.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import backup
from app.web import templates

router = APIRouter()

#: A restore replaces the whole of your progress, so it is refused unless the
#: upload actually parses and announces itself as one of our backups.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


@router.get("/backup", response_class=HTMLResponse)
def backup_view(request: Request):
    data = backup.export_state()
    return templates.TemplateResponse(
        request,
        "backup.html",
        {"request": request, "counts": data["counts"], "result": None},
    )


@router.get("/backup/download")
def download(_: Request):
    """The whole of your progress as one JSON file."""
    data = backup.export_state()
    body = json.dumps(data, indent=2, ensure_ascii=False)
    name = f"ml-journey-{date.today().isoformat()}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/backup/restore", response_class=HTMLResponse)
async def restore(request: Request, file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return _fail(request, "That file is larger than 32 MB, which no backup should be.")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _fail(request, "That file isn't valid JSON, so it isn't a backup.")

    try:
        result = backup.import_state(data)
    except ValueError as exc:
        return _fail(request, str(exc))

    counts = backup.export_state()["counts"]
    return templates.TemplateResponse(
        request,
        "backup.html",
        {"request": request, "counts": counts, "result": result, "error": None},
    )


def _fail(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "backup.html",
        {
            "request": request,
            "counts": backup.export_state()["counts"],
            "result": None,
            "error": message,
        },
        status_code=400,
    )
