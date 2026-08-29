"""Assignments: submit code, run hidden tests, request a review."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import runner, tutor
from app.db import ROOT, get_session
from app.models import Assignment, Submission, Unit
from app.web import templates

router = APIRouter()


@router.get("/assignment/{slug}", response_class=HTMLResponse)
def assignment_view(slug: str, request: Request, s: Session = Depends(get_session)):
    a = s.exec(select(Assignment).where(Assignment.slug == slug)).first()
    if a is None:
        return RedirectResponse("/", status_code=303)
    unit = s.get(Unit, a.unit_id)
    subs = list(
        s.exec(
            select(Submission)
            .where(Submission.assignment_id == a.id)
            .order_by(Submission.created_at.desc())
        )
    )
    starter = ""
    sp = runner.resolve(a.starter_path) if a.starter_path else None
    if sp and sp.is_file():
        starter = sp.read_text(encoding="utf-8")
    return templates.TemplateResponse(
        request,
        "assignment.html",
        {
            "request": request,
            "assignment": a,
            "unit": unit,
            "submissions": subs,
            "starter": starter,
        },
    )


@router.post("/assignment/{slug}/submit")
def submit(slug: str, code: str = Form(...), s: Session = Depends(get_session)):
    a = s.exec(select(Assignment).where(Assignment.slug == slug)).first()
    if a is None:
        return RedirectResponse("/", status_code=303)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    subdir = ROOT / "submissions" / a.slug / stamp
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / "solution.py"
    path.write_text(code, encoding="utf-8")

    result = runner.run_submission(path, runner.resolve(a.tests_path))
    sub = Submission(
        assignment_id=a.id,
        path=str(path.relative_to(ROOT)),
        tests_passed=result.passed,
        tests_total=result.total,
        timed_out=result.timed_out,
        stdout=result.output,
    )
    s.add(sub)
    s.commit()
    return RedirectResponse(f"/assignment/{slug}", status_code=303)


@router.post("/submission/{sid}/review")
def request_review(sid: int, s: Session = Depends(get_session)):
    sub = s.get(Submission, sid)
    if sub is None:
        return RedirectResponse("/", status_code=303)
    a = s.get(Assignment, sub.assignment_id)
    code_path = ROOT / sub.path
    code = code_path.read_text(encoding="utf-8") if code_path.is_file() else ""
    tutor.write_inbox(
        "review",
        a.slug,
        tutor.review_prompt(a.title, a.brief, code, sub.stdout, sub.tests_passed, sub.tests_total),
    )
    sub.review_status = "requested"
    s.commit()
    return RedirectResponse(f"/assignment/{a.slug}", status_code=303)
