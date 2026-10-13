"""The experiment log and the ablation table.

app/experiments.py has been able to record runs and build ablation tables
since the first commit, and nothing could reach it -- no route, no template,
not even a CLI entry point. Meanwhile rung R5 of the Rigor Ladder asks whether
you removed components one at a time to show which part earns the gain, and
the only way to answer was to promise you had.

This module is the door. It adds no logic: log_run() and ablation_table() are
used exactly as they were already written.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app import experiments
from app.db import get_session
from app.models import ExperimentRun, Project
from app.web import templates

router = APIRouter()


def project_runs(s: Session, project_id: int) -> list[ExperimentRun]:
    return list(
        s.exec(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project_id)
            .order_by(ExperimentRun.created_at.desc())
        )
    )


def metrics_in(runs: list[ExperimentRun]) -> list[str]:
    """Every metric name that appears in any run, so the table can be pivoted."""
    names: set[str] = set()
    for r in runs:
        try:
            names.update(json.loads(r.metrics_json or "{}").keys())
        except json.JSONDecodeError:
            continue
    return sorted(names)


def distinct_labels(runs: list[ExperimentRun]) -> set[str]:
    return {r.label for r in runs if r.label}


@router.get("/project/{slug}/runs", response_class=HTMLResponse)
def runs_view(
    slug: str, request: Request, metric: str = "", s: Session = Depends(get_session)
):
    p = s.exec(select(Project).where(Project.slug == slug)).first()
    if p is None:
        return RedirectResponse("/projects", status_code=303)

    runs = project_runs(s, p.id)
    metrics = metrics_in(runs)
    chosen = metric if metric in metrics else (metrics[0] if metrics else "")
    table = experiments.ablation_table(runs, chosen) if chosen else []

    return templates.TemplateResponse(
        request,
        "experiment.html",
        {
            "request": request,
            "project": p,
            "runs": runs,
            "rows": [
                {
                    "label": r.label,
                    "commit": r.git_commit,
                    "seed": r.seed,
                    "metrics": json.loads(r.metrics_json or "{}"),
                    "config": json.loads(r.config_json or "{}"),
                    "notes": r.notes,
                    "created_at": r.created_at,
                }
                for r in runs
            ],
            "metrics": metrics,
            "metric": chosen,
            "table": table,
            "labels": sorted(distinct_labels(runs)),
        },
    )


@router.post("/project/{slug}/runs")
def log_run_view(
    slug: str,
    label: str = Form(...),
    metric_name: str = Form(...),
    metric_value: float = Form(...),
    seed: str = Form(""),
    notes: str = Form(""),
    config: str = Form(""),
    s: Session = Depends(get_session),
):
    """Log one run from the browser.

    The commit is captured for you by experiments.git_commit(), because a
    number you cannot trace back to code is not a result.
    """
    p = s.exec(select(Project).where(Project.slug == slug)).first()
    if p is None:
        return RedirectResponse("/projects", status_code=303)

    label = label.strip()
    metric_name = metric_name.strip()
    if not label or not metric_name:
        return RedirectResponse(f"/project/{slug}/runs?err=empty", status_code=303)

    try:
        parsed_config = json.loads(config) if config.strip() else {}
        if not isinstance(parsed_config, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        return RedirectResponse(f"/project/{slug}/runs?err=config", status_code=303)

    try:
        seed_val = int(seed) if seed.strip() else None
    except ValueError:
        seed_val = None

    experiments.log_run(
        label=label,
        metrics={metric_name: metric_value},
        seed=seed_val,
        config=parsed_config,
        notes=notes.strip(),
        project_slug=slug,
    )
    return RedirectResponse(f"/project/{slug}/runs?metric={metric_name}", status_code=303)
