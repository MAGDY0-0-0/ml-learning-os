"""Experiment logging and automatic ablation tables.

Import `log_run` in a notebook or training script:

    from app.experiments import log_run
    log_run("baseline", metrics={"acc": 0.81}, seed=0, config={"aug": True})

Every run records the git commit, so an ablation table doubles as a
reproducibility record.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.db import ROOT, engine
from app.models import ExperimentRun, Project

RUNS_DIR = ROOT / "experiments"


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (out.stdout or "").strip() or "uncommitted"
    except Exception:  # noqa: BLE001
        return "unknown"


def log_run(
    label: str,
    metrics: dict[str, float],
    seed: int | None = None,
    config: dict[str, Any] | None = None,
    notes: str = "",
    project_slug: str | None = None,
) -> ExperimentRun:
    """Record one training run. Writes to the DB and to a JSONL append log."""
    config = config or {}
    with Session(engine) as s:
        project_id = None
        if project_slug:
            p = s.exec(select(Project).where(Project.slug == project_slug)).first()
            project_id = p.id if p else None

        run = ExperimentRun(
            project_id=project_id,
            label=label,
            git_commit=git_commit(),
            seed=seed,
            config_json=json.dumps(config, sort_keys=True, default=str),
            metrics_json=json.dumps(metrics, sort_keys=True),
            notes=notes,
        )
        s.add(run)
        s.commit()
        s.refresh(run)

    target = RUNS_DIR / (project_slug or "unassigned")
    target.mkdir(parents=True, exist_ok=True)
    with (target / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "label": label,
                    "seed": seed,
                    "commit": run.git_commit,
                    "config": config,
                    "metrics": metrics,
                    "notes": notes,
                }
            )
            + "\n"
        )
    return run


@dataclass
class AblationRow:
    label: str
    n: int
    mean: float
    spread: float
    seeds: list[int]


def ablation_table(runs: list[ExperimentRun], metric: str) -> list[AblationRow]:
    """Group runs by label and report mean +/- stdev of a metric.

    Reporting spread is the point: single-seed differences are often smaller
    than seed noise, so a mean without a spread can't support a claim.
    """
    grouped: dict[str, list[ExperimentRun]] = {}
    for r in runs:
        grouped.setdefault(r.label, []).append(r)

    rows = []
    for label, group in grouped.items():
        values, seeds = [], []
        for r in group:
            m = json.loads(r.metrics_json or "{}")
            if metric in m:
                values.append(float(m[metric]))
                if r.seed is not None:
                    seeds.append(r.seed)
        if not values:
            continue
        rows.append(
            AblationRow(
                label=label,
                n=len(values),
                mean=statistics.fmean(values),
                spread=statistics.stdev(values) if len(values) > 1 else 0.0,
                seeds=sorted(set(seeds)),
            )
        )
    return sorted(rows, key=lambda r: r.mean, reverse=True)
