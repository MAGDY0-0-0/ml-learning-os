"""ML Learning OS — FastAPI application."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app import library, rubric, runner, srs, tutor
from app.db import ROOT, engine, get_session, init_db
from app.models import (
    ActiveResource,
    Assignment,
    Card,
    CheckStatus,
    Module,
    Progress,
    Project,
    Resource,
    ResourcePreference,
    ResourceState,
    RubricCheck,
    StudySession,
    Submission,
    SwapReason,
    Unit,
    UnitStatus,
    utcnow,
)

app = FastAPI(title="ML Learning OS")
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

NOTES_DIR = ROOT / "notes"


@app.on_event("startup")
def _startup() -> None:
    init_db()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def embed_url(url: str) -> str | None:
    """Turn a YouTube watch/playlist URL into an embeddable one."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
        return None
    qs = parse_qs(parsed.query)
    if "list" in qs:
        return f"https://www.youtube.com/embed/videoseries?list={qs['list'][0]}"
    if "v" in qs:
        return f"https://www.youtube.com/embed/{qs['v'][0]}"
    if parsed.netloc.endswith("youtu.be"):
        return f"https://www.youtube.com/embed/{parsed.path.lstrip('/')}"
    return None


templates.env.globals["embed_url"] = embed_url


def asset(name: str) -> str:
    """URL for a file in app/static/, versioned by mtime so it is never stale.

    Takes a bare filename ("style.css"), not a path — passing "static/style.css"
    previously produced /static/static/... and 404'd.
    """
    name = name.lstrip("/").removeprefix("static/")
    f = BASE / "static" / name
    try:
        return f"/static/{name}?v={int(f.stat().st_mtime)}"
    except OSError:
        return f"/static/{name}"


templates.env.globals["asset"] = asset


def get_progress(s: Session, unit_id: int) -> Progress:
    p = s.exec(select(Progress).where(Progress.unit_id == unit_id)).first()
    if p is None:
        p = Progress(unit_id=unit_id)
        s.add(p)
        s.commit()
        s.refresh(p)
    return p


def notes_path(unit_slug: str) -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR / f"{unit_slug}.md"


def read_notes(unit_slug: str) -> str:
    p = notes_path(unit_slug)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def ordered_resources(s: Session, unit: Unit) -> list[Resource]:
    """Resources with the currently-active one promoted to the front."""
    res = list(
        s.exec(select(Resource).where(Resource.unit_id == unit.id).order_by(Resource.rank))
    )
    active = s.exec(select(ActiveResource).where(ActiveResource.unit_id == unit.id)).first()
    if active:
        for i, r in enumerate(res):
            if r.id == active.resource_id and i != 0:
                res.insert(0, res.pop(i))
                break
    return res


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, s: Session = Depends(get_session)):
    modules = list(s.exec(select(Module).order_by(Module.order)))
    prog = {p.unit_id: p for p in s.exec(select(Progress))}

    rows = []
    total_units = done_units = 0
    current_unit = None
    for m in modules:
        units = list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
        done = sum(1 for u in units if prog.get(u.id) and prog[u.id].status == UnitStatus.done)
        total_units += len(units)
        done_units += done
        if current_unit is None:
            for u in units:
                st = prog.get(u.id)
                if st is None or st.status != UnitStatus.done:
                    current_unit = u
                    break
        rows.append(
            {
                "module": m,
                "units": units,
                "done": done,
                "total": len(units),
                "pct": round(100 * done / len(units)) if units else 0,
            }
        )

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    minutes_week = sum(
        ss.minutes
        for ss in s.exec(select(StudySession))
        if ss.started_at and ss.started_at.replace(tzinfo=timezone.utc) >= week_ago
    )
    due = len(
        [c for c in s.exec(select(Card)) if c.due_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)]
    )

    projects = list(s.exec(select(Project)))
    rigor_total = rigor_done = 0
    for p in projects:
        checks = list(s.exec(select(RubricCheck).where(RubricCheck.project_id == p.id)))
        rigor_total += len(checks)
        rigor_done += sum(1 for c in checks if c.status != CheckStatus.unchecked)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "rows": rows,
            "prog": prog,
            "current_unit": current_unit,
            "total_units": total_units,
            "done_units": done_units,
            "overall_pct": round(100 * done_units / total_units) if total_units else 0,
            "minutes_week": minutes_week,
            "due": due,
            "projects": projects,
            "rigor_pct": round(100 * rigor_done / rigor_total) if rigor_total else 0,
            "provider": tutor.provider_status(),
        },
    )


@app.get("/module/{slug}", response_class=HTMLResponse)
def module_view(slug: str, request: Request, s: Session = Depends(get_session)):
    m = s.exec(select(Module).where(Module.slug == slug)).first()
    if m is None:
        return RedirectResponse("/", status_code=303)
    units = list(s.exec(select(Unit).where(Unit.module_id == m.id).order_by(Unit.order)))
    prog = {p.unit_id: p for p in s.exec(select(Progress))}
    counts = {
        u.id: len(list(s.exec(select(Resource).where(Resource.unit_id == u.id))))
        for u in units
    }
    return templates.TemplateResponse(
        request,
        "module.html",
        {"request": request, "module": m, "units": units, "prog": prog, "counts": counts},
    )


# --------------------------------------------------------------------------
# unit
# --------------------------------------------------------------------------


@app.get("/unit/{slug}", response_class=HTMLResponse)
def unit_view(slug: str, request: Request, s: Session = Depends(get_session)):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return RedirectResponse("/", status_code=303)
    m = s.get(Module, u.module_id)
    resources = ordered_resources(s, u)
    states = {st.resource_id: st for st in s.exec(select(ResourceState))}
    assignments = list(s.exec(select(Assignment).where(Assignment.unit_id == u.id)))
    cards = list(s.exec(select(Card).where(Card.unit_id == u.id)))
    return templates.TemplateResponse(
        request,
        "unit.html",
        {
            "request": request,
            "unit": u,
            "module": m,
            "resources": resources,
            "states": states,
            "assignments": assignments,
            "cards": cards,
            "progress": get_progress(s, u.id),
            "notes": read_notes(u.slug),
            "reasons": [r.value for r in SwapReason],
        },
    )


@app.post("/unit/{slug}/notes")
def save_notes(slug: str, notes: str = Form(""), s: Session = Depends(get_session)):
    notes_path(slug).write_text(notes, encoding="utf-8")
    return RedirectResponse(f"/unit/{slug}", status_code=303)


@app.post("/unit/{slug}/log")
def log_time(slug: str, minutes: int = Form(25), s: Session = Depends(get_session)):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u:
        p = get_progress(s, u.id)
        p.minutes_logged += minutes
        if p.status == UnitStatus.not_started:
            p.status = UnitStatus.in_progress
            p.started_at = utcnow()
        s.add(StudySession(unit_id=u.id, minutes=minutes, ended_at=utcnow()))
        s.commit()
    return RedirectResponse(f"/unit/{slug}", status_code=303)


@app.post("/unit/{slug}/complete")
def complete_unit(slug: str, s: Session = Depends(get_session)):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u:
        p = get_progress(s, u.id)
        p.status = UnitStatus.done
        p.completed_at = utcnow()
        s.commit()
    return RedirectResponse(f"/unit/{slug}", status_code=303)


@app.post("/unit/{slug}/swap")
def swap_resource(
    slug: str,
    resource_id: int = Form(...),
    reason: str = Form("other"),
    note: str = Form(""),
    s: Session = Depends(get_session),
):
    """Promote the alternative the learner picked to be the primary resource.

    `resource_id` is the one they chose. The preference is recorded against the
    resource that *was* primary - that is the one that did not work for them.
    """
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return RedirectResponse("/", status_code=303)

    current = ordered_resources(s, u)
    if not current:
        return RedirectResponse(f"/unit/{slug}", status_code=303)
    outgoing = current[0]

    try:
        reason_enum = SwapReason(reason)
    except ValueError:
        reason_enum = SwapReason.other
    s.add(ResourcePreference(resource_id=outgoing.id, reason=reason_enum, note=note))

    if resource_id in {r.id for r in current}:
        active = s.exec(select(ActiveResource).where(ActiveResource.unit_id == u.id)).first()
        if active is None:
            s.add(ActiveResource(unit_id=u.id, resource_id=resource_id))
        else:
            active.resource_id = resource_id
    s.commit()
    return RedirectResponse(f"/unit/{slug}?swapped=1", status_code=303)


@app.post("/resource/{rid}/toggle")
def toggle_resource(rid: int, unit_slug: str = Form(...), s: Session = Depends(get_session)):
    st = s.exec(select(ResourceState).where(ResourceState.resource_id == rid)).first()
    if st is None:
        st = ResourceState(resource_id=rid, done=True)
        s.add(st)
    else:
        st.done = not st.done
    s.commit()
    return RedirectResponse(f"/unit/{unit_slug}", status_code=303)


@app.post("/unit/{slug}/ask")
def ask_help(
    slug: str,
    question: str = Form(...),
    resource_title: str = Form(""),
    s: Session = Depends(get_session),
):
    u = s.exec(select(Unit).where(Unit.slug == slug)).first()
    if u is None:
        return RedirectResponse("/", status_code=303)
    prompt = tutor.unit_help_prompt(
        u.title, u.objective, resource_title, read_notes(u.slug), question
    )
    path = tutor.write_inbox("ask", u.slug, prompt)
    answer = tutor.ask_inline(prompt)
    if answer:
        path.write_text(prompt + "\n\n---\n\n## Answer\n\n" + answer, encoding="utf-8")
    return RedirectResponse(f"/unit/{slug}?asked={path.name}", status_code=303)


# --------------------------------------------------------------------------
# review (SRS)
# --------------------------------------------------------------------------


@app.get("/review", response_class=HTMLResponse)
def review_view(request: Request, s: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    due = [c for c in s.exec(select(Card)) if c.due_at.replace(tzinfo=timezone.utc) <= now]
    due.sort(key=lambda c: c.due_at)
    total = len(list(s.exec(select(Card))))
    return templates.TemplateResponse(
        request,
        "review.html",
        {"request": request, "card": due[0] if due else None, "remaining": len(due), "total": total},
    )


@app.post("/review/{card_id}")
def grade_card(card_id: int, quality: int = Form(...), s: Session = Depends(get_session)):
    c = s.get(Card, card_id)
    if c:
        sched = srs.review(c.ease, c.interval_days, c.repetitions, c.lapses, quality)
        c.ease = sched.ease
        c.interval_days = sched.interval_days
        c.repetitions = sched.repetitions
        c.lapses = sched.lapses
        c.due_at = srs.next_due(sched.interval_days)
        s.commit()
    return RedirectResponse("/review", status_code=303)


# --------------------------------------------------------------------------
# library
# --------------------------------------------------------------------------


@app.get("/library", response_class=HTMLResponse)
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


@app.post("/library/reindex")
def library_reindex(s: Session = Depends(get_session)):
    library.reindex_all(s)
    return RedirectResponse("/library", status_code=303)


# --------------------------------------------------------------------------
# projects + rigor gate
# --------------------------------------------------------------------------


@app.get("/projects", response_class=HTMLResponse)
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


@app.get("/project/{slug}", response_class=HTMLResponse)
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


@app.post("/project/{slug}/check/{code}")
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
            c.status = CheckStatus.passed
            c.justification = ""
        else:
            c.status = CheckStatus.unchecked
        c.updated_at = utcnow()
        s.commit()
    return RedirectResponse(f"/project/{slug}", status_code=303)


@app.post("/project/{slug}/complete")
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


@app.post("/project/{slug}/links")
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


# --------------------------------------------------------------------------
# submissions
# --------------------------------------------------------------------------


@app.get("/assignment/{slug}", response_class=HTMLResponse)
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


@app.post("/assignment/{slug}/submit")
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


@app.post("/submission/{sid}/review")
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


# --------------------------------------------------------------------------
# tour
# --------------------------------------------------------------------------


@app.get("/tour", response_class=HTMLResponse)
def tour(request: Request):
    return templates.TemplateResponse(
        request,
        "tour.html", {"request": request})


@app.get("/recap", response_class=HTMLResponse)
def recap(request: Request):
    """The M3 math recap sheet — the whole of the math module's reading."""
    return templates.TemplateResponse(request, "recap.html", {"request": request})
