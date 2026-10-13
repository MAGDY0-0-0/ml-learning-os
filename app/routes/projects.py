"""Projects and the rigor gate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import rubric, tutor
from app.db import get_session
from app.models import CheckStatus, Project, RubricCheck, utcnow
from app.web import templates

router = APIRouter()


@router.get("/projects", response_class=HTMLResponse)
def projects_view(request: Request, s: Session = Depends(get_session)):
    projects = list(s.exec(select(Project)))
    summary = {}
    for p in projects:
        checks = rubric.ensure_checks(s, p)
        summary[p.id] = {
            "total": len(checks),
            "done": sum(1 for c in checks if c.status != CheckStatus.unchecked),
        }
    return templates.TemplateResponse(
        request,
        "projects.html", {"request": request, "projects": projects, "summary": summary}
    )


@router.get("/project/{slug}", response_class=HTMLResponse)
def project_view(slug: str, request: Request, s: Session = Depends(get_session)):
    p = s.exec(select(Project).where(Project.slug == slug)).first()
    if p is None:
        return RedirectResponse("/projects", status_code=303)
    checks = rubric.ensure_checks(s, p)
    groups: dict[str, list[RubricCheck]] = {}
    for c in checks:
        groups.setdefault(c.group, []).append(c)
    return templates.TemplateResponse(
        request,
        "project.html",
        {
            "request": request,
            "project": p,
            "groups": groups,
            "blocking": rubric.blocking(checks),
            "can_complete": rubric.can_complete(checks),
        },
    )


@router.post("/project/{slug}/check/{code}")
def set_check(
    slug: str,
    code: str,
    status: str = Form(...),
    justification: str = Form(""),
    s: Session = Depends(get_session),
):
    p = s.exec(select(Project).where(Project.slug == slug)).first()
    if p is None:
        return RedirectResponse("/projects", status_code=303)
    c = s.exec(
        select(RubricCheck).where(RubricCheck.project_id == p.id, RubricCheck.code == code)
    ).first()
    if c:
        if status == "skipped":
            if not justification.strip():
                # A skip without a written justification is refused outright.
                return RedirectResponse(f"/project/{slug}?err=justify", status_code=303)
            c.status = CheckStatus.skipped
            c.justification = justification
            tutor.write_inbox(
                "rubric-skip",
                f"{p.slug}-{code}",
                tutor.rubric_skip_prompt(p.title, code, c.label, justification),
            )
        elif status == "passed":
            # R5 is the one rung the app can actually verify rather than take
            # on trust: an ablation means comparing at least two variants, and
            # the run log knows whether you have. Everything else here is an
            # honesty checkbox; this one is evidence.
            if code == "R5":
                from app.routes.experiments import distinct_labels, project_runs

                if len(distinct_labels(project_runs(s, p.id))) < 2:
                    return RedirectResponse(f"/project/{slug}?err=ablation", status_code=303)
            c.status = CheckStatus.passed
            c.justification = ""
        else:
            c.status = CheckStatus.unchecked
        c.updated_at = utcnow()
        s.commit()
    return RedirectResponse(f"/project/{slug}", status_code=303)


@router.post("/project/{slug}/complete")
def complete_project(slug: str, s: Session = Depends(get_session)):
    p = s.exec(select(Project).where(Project.slug == slug)).first()
    if p is None:
        return RedirectResponse("/projects", status_code=303)
    checks = rubric.ensure_checks(s, p)
    if not rubric.can_complete(checks):
        # The gate: refuse, and say which checks are blocking.
        return RedirectResponse(f"/project/{slug}?err=blocked", status_code=303)
    p.completed = True
    p.completed_at = utcnow()
    s.commit()
    return RedirectResponse(f"/project/{slug}", status_code=303)


@router.post("/project/{slug}/links")
def project_links(
    slug: str,
    github_url: str = Form(""),
    hf_url: str = Form(""),
    demo_url: str = Form(""),
    s: Session = Depends(get_session),
):
    p = s.exec(select(Project).where(Project.slug == slug)).first()
    if p:
        p.github_url, p.hf_url, p.demo_url = github_url, hf_url, demo_url
        s.commit()
    return RedirectResponse(f"/project/{slug}", status_code=303)
