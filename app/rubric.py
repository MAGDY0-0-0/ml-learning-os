"""The Rigor Ladder and the 8-type leakage checklist.

Grounded in Kapoor & Narayanan, "Leakage and the Reproducibility Crisis in
ML-based Science" (arXiv:2207.07048), which found leakage in 329 papers across
17 fields. Their taxonomy is reproduced here as literal checks that gate a
project's completion.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import CheckStatus, Project, RubricCheck


@dataclass(frozen=True)
class CheckSpec:
    code: str
    label: str
    question: str
    group: str


# --- The Rigor Ladder, in the order it must be practised ------------------
LADDER: tuple[CheckSpec, ...] = (
    CheckSpec("R1", "Split", "Is there a held-out test set created before any exploration?", "ladder"),
    CheckSpec("R2", "Baseline", "Did you build a dumb baseline (majority/mean/single-feature/linear) first?", "ladder"),
    CheckSpec("R3", "Metric", "Was the evaluation metric chosen and written down BEFORE seeing results?", "ladder"),
    CheckSpec("R4", "Error analysis", "Have you looked at actual errors, sliced by subgroup, not just an aggregate score?", "ladder"),
    CheckSpec("R5", "Ablation", "Did you remove components one at a time to show which part earns the gain?", "ladder"),
    CheckSpec("R6", "Reproducibility", "Can a clean clone + one command reproduce your reported number? Seed, config and commit recorded?", "ladder"),
)

# --- The 8 leakage types --------------------------------------------------
LEAKAGE: tuple[CheckSpec, ...] = (
    CheckSpec("L1.1", "No test set", "Is there a held-out set you have genuinely never fit on?", "leakage"),
    CheckSpec("L1.2", "Preprocessing on train+test", "Were imputation/scaling/resampling fit INSIDE the CV fold (e.g. via a Pipeline)?", "leakage"),
    CheckSpec("L1.3", "Feature selection on train+test", "Was feature selection done without touching the test set?", "leakage"),
    CheckSpec("L1.4", "Duplicates across splits", "Did you deduplicate BEFORE splitting?", "leakage"),
    CheckSpec("L2", "Illegitimate features", "Is every feature actually available at prediction time, and none a proxy for the target?", "leakage"),
    CheckSpec("L3.1", "Temporal leakage", "Does any training row postdate any test row?", "leakage"),
    CheckSpec("L3.2", "Non-independence", "Do the same subject/group/session appear on both sides? (needs grouped splits)", "leakage"),
    CheckSpec("L3.3", "Sampling bias", "Is the test set drawn from the distribution you actually care about?", "leakage"),
)

# --- Deployment triple, only for projects that require it -----------------
DEPLOYMENT: tuple[CheckSpec, ...] = (
    CheckSpec("D1", "GitHub", "Clean README (problem/data/approach/results/what failed), reproducible from a clean clone?", "deployment"),
    CheckSpec("D2", "Hugging Face", "Model AND dataset published with an honest model card covering limitations?", "deployment"),
    CheckSpec("D3", "Live demo", "Is there a link a stranger can click — a HF Space or deployed API?", "deployment"),
)


def specs_for(project: Project) -> list[CheckSpec]:
    specs = list(LADDER) + list(LEAKAGE)
    if project.requires_deployment:
        specs += list(DEPLOYMENT)
    return specs


def ensure_checks(session: Session, project: Project) -> list[RubricCheck]:
    """Create any missing checks for a project. Idempotent."""
    existing = {
        c.code: c
        for c in session.exec(select(RubricCheck).where(RubricCheck.project_id == project.id))
    }
    for spec in specs_for(project):
        if spec.code not in existing:
            check = RubricCheck(
                project_id=project.id,
                code=spec.code,
                label=spec.label,
                question=spec.question,
                group=spec.group,
            )
            session.add(check)
            existing[spec.code] = check
    session.commit()
    order = {s.code: i for i, s in enumerate(specs_for(project))}
    return sorted(existing.values(), key=lambda c: order.get(c.code, 999))


def blocking(checks: list[RubricCheck]) -> list[RubricCheck]:
    """Checks that prevent completion: anything still unchecked.

    A 'skipped' check does NOT block, but requires a written justification —
    enforced at the point of skipping, and surfaced to Claude via the inbox.
    """
    return [c for c in checks if c.status == CheckStatus.unchecked]


def can_complete(checks: list[RubricCheck]) -> bool:
    return not blocking(checks)
