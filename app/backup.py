"""Export and restore everything the learner owns.

`data/app.db` and `notes/` are both gitignored, so they are a single copy of
the only irreplaceable thing here: your progress. One bad delete and the
minutes, the card schedules, the rigor answers and the notes are all gone.

Two rules shape this file.

**Identify by slug and URL, never by id.** Every id in the database is handed
out by SQLite and reassigned whenever the curriculum is reseeded. A backup
keyed on ids would restore quietly onto the wrong units. Everything here is
keyed on `unit.slug`, `resource.url`, `project.slug`, `assignment.slug` and
card question text, all of which are stable across a reseed.

**Restore state onto the current curriculum, don't recreate it.** Cards,
projects and rubric checks are created by the seeder from YAML; only their
*state* is yours. So importing updates matching rows and never invents
curriculum. A backup taken before a curriculum update still applies cleanly
afterwards, and anything whose unit no longer exists is reported as skipped
rather than silently dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.db import ROOT, engine
from app.models import (
    ActiveResource, Assignment, Card, CheckStatus, ExperimentRun, Progress,
    Project, Resource, ResourcePreference, ResourceState, RubricCheck,
    StudySession, Submission, SwapReason, Unit, UnitStatus,
)

FORMAT = "magdys-ml-journey-backup"
VERSION = 1

NOTES_DIR = ROOT / "notes"


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def export_state() -> dict[str, Any]:
    """Everything you own, as plain JSON-able data."""
    with Session(engine) as s:
        units = {u.id: u.slug for u in s.exec(select(Unit))}
        res = {r.id: (units.get(r.unit_id), r.url) for r in s.exec(select(Resource))}
        projects = {p.id: p.slug for p in s.exec(select(Project))}
        assignments = {a.id: a.slug for a in s.exec(select(Assignment))}

        data: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "exported_at": datetime.now().astimezone().isoformat(),
            "progress": [
                {
                    "unit": units.get(p.unit_id),
                    "status": p.status.value,
                    "minutes_logged": p.minutes_logged,
                    "started_at": _dt(p.started_at),
                    "completed_at": _dt(p.completed_at),
                }
                for p in s.exec(select(Progress))
                if units.get(p.unit_id)
            ],
            "resource_states": [
                {
                    "unit": res.get(st.resource_id, (None, None))[0],
                    "url": res.get(st.resource_id, (None, None))[1],
                    "done": st.done,
                    "position_seconds": st.position_seconds,
                }
                for st in s.exec(select(ResourceState))
                if res.get(st.resource_id, (None,))[0]
            ],
            "preferences": [
                {
                    "unit": res.get(pr.resource_id, (None, None))[0],
                    "url": res.get(pr.resource_id, (None, None))[1],
                    "reason": pr.reason.value,
                    "note": pr.note,
                    "created_at": _dt(pr.created_at),
                }
                for pr in s.exec(select(ResourcePreference))
                if res.get(pr.resource_id, (None,))[0]
            ],
            "active_resources": [
                {
                    "unit": units.get(a.unit_id),
                    "url": res.get(a.resource_id, (None, None))[1],
                }
                for a in s.exec(select(ActiveResource))
                if units.get(a.unit_id) and res.get(a.resource_id, (None, None))[1]
            ],
            "sessions": [
                {
                    "unit": units.get(ss.unit_id),
                    "started_at": _dt(ss.started_at),
                    "ended_at": _dt(ss.ended_at),
                    "minutes": ss.minutes,
                }
                for ss in s.exec(select(StudySession))
            ],
            "cards": [
                {
                    "unit": units.get(c.unit_id),
                    "front": c.front,
                    "ease": c.ease,
                    "interval_days": c.interval_days,
                    "repetitions": c.repetitions,
                    "lapses": c.lapses,
                    "due_at": _dt(c.due_at),
                }
                for c in s.exec(select(Card))
            ],
            "projects": [
                {
                    "slug": p.slug,
                    "completed": p.completed,
                    "completed_at": _dt(p.completed_at),
                    "github_url": p.github_url,
                    "hf_url": p.hf_url,
                    "demo_url": p.demo_url,
                }
                for p in s.exec(select(Project))
            ],
            "rubric_checks": [
                {
                    "project": projects.get(c.project_id),
                    "code": c.code,
                    "status": c.status.value,
                    "justification": c.justification,
                    "updated_at": _dt(c.updated_at),
                }
                for c in s.exec(select(RubricCheck))
                if projects.get(c.project_id)
            ],
            "runs": [
                {
                    "project": projects.get(r.project_id),
                    "label": r.label,
                    "git_commit": r.git_commit,
                    "seed": r.seed,
                    "config_json": r.config_json,
                    "metrics_json": r.metrics_json,
                    "notes": r.notes,
                    "created_at": _dt(r.created_at),
                }
                for r in s.exec(select(ExperimentRun))
            ],
            "submissions": [
                {
                    "assignment": assignments.get(sub.assignment_id),
                    "path": sub.path,
                    "tests_passed": sub.tests_passed,
                    "tests_total": sub.tests_total,
                    "timed_out": sub.timed_out,
                    "stdout": sub.stdout,
                    "review_status": sub.review_status,
                    "created_at": _dt(sub.created_at),
                }
                for sub in s.exec(select(Submission))
                if assignments.get(sub.assignment_id)
            ],
        }

    # Notes are files on disk, not rows, and are just as irreplaceable.
    notes: dict[str, str] = {}
    if NOTES_DIR.is_dir():
        for f in sorted(NOTES_DIR.glob("*.md")):
            try:
                notes[f.stem] = f.read_text(encoding="utf-8")
            except OSError:
                continue
    data["notes"] = notes

    data["counts"] = {k: len(v) for k, v in data.items() if isinstance(v, (list, dict))}
    return data


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------


def import_state(data: dict[str, Any]) -> dict[str, Any]:
    """Restore a backup onto the curriculum as it stands today.

    Returns a per-section count of what was restored and what was skipped,
    because a silent restore is indistinguishable from a failed one.
    """
    if data.get("format") != FORMAT:
        raise ValueError("That file is not a Magdy's ML Journey backup.")
    if int(data.get("version", 0)) > VERSION:
        raise ValueError(
            f"That backup is version {data.get('version')}, and this app only "
            f"understands up to {VERSION}. Update the app first."
        )

    restored: dict[str, int] = {}
    skipped: dict[str, int] = {}

    def note(section: str, ok: bool) -> None:
        (restored if ok else skipped)[section] = (
            (restored if ok else skipped).get(section, 0) + 1
        )

    with Session(engine) as s:
        units = {u.slug: u.id for u in s.exec(select(Unit))}
        by_url: dict[tuple[int, str], int] = {
            (r.unit_id, r.url): r.id for r in s.exec(select(Resource))
        }
        projects = {p.slug: p.id for p in s.exec(select(Project))}
        assignments = {a.slug: a.id for a in s.exec(select(Assignment))}

        def resource_id(unit_slug: str | None, url: str | None) -> int | None:
            uid = units.get(unit_slug or "")
            return by_url.get((uid, url or "")) if uid else None

        # -- progress ------------------------------------------------------
        for row in data.get("progress", []):
            uid = units.get(row.get("unit", ""))
            if uid is None:
                note("progress", False)
                continue
            p = s.exec(select(Progress).where(Progress.unit_id == uid)).first()
            if p is None:
                p = Progress(unit_id=uid)
                s.add(p)
            try:
                p.status = UnitStatus(row.get("status", "not_started"))
            except ValueError:
                p.status = UnitStatus.not_started
            p.minutes_logged = int(row.get("minutes_logged", 0) or 0)
            p.started_at = _parse(row.get("started_at"))
            p.completed_at = _parse(row.get("completed_at"))
            note("progress", True)

        # -- resource state -------------------------------------------------
        for row in data.get("resource_states", []):
            rid = resource_id(row.get("unit"), row.get("url"))
            if rid is None:
                note("resource_states", False)
                continue
            st = s.exec(
                select(ResourceState).where(ResourceState.resource_id == rid)
            ).first()
            if st is None:
                st = ResourceState(resource_id=rid)
                s.add(st)
            st.done = bool(row.get("done"))
            st.position_seconds = int(row.get("position_seconds", 0) or 0)
            note("resource_states", True)

        # -- swap preferences (append-only history; replaced wholesale) -----
        if "preferences" in data:
            for old in s.exec(select(ResourcePreference)):
                s.delete(old)
            for row in data.get("preferences", []):
                rid = resource_id(row.get("unit"), row.get("url"))
                if rid is None:
                    note("preferences", False)
                    continue
                try:
                    reason = SwapReason(row.get("reason", "other"))
                except ValueError:
                    reason = SwapReason.other
                s.add(
                    ResourcePreference(
                        resource_id=rid,
                        reason=reason,
                        note=row.get("note", ""),
                        created_at=_parse(row.get("created_at")) or datetime.now(),
                    )
                )
                note("preferences", True)

        # -- which alternate is promoted -----------------------------------
        if "active_resources" in data:
            for old in s.exec(select(ActiveResource)):
                s.delete(old)
            for row in data.get("active_resources", []):
                uid = units.get(row.get("unit", ""))
                rid = resource_id(row.get("unit"), row.get("url"))
                if uid is None or rid is None:
                    note("active_resources", False)
                    continue
                s.add(ActiveResource(unit_id=uid, resource_id=rid))
                note("active_resources", True)

        # -- study sessions -------------------------------------------------
        if "sessions" in data:
            for old in s.exec(select(StudySession)):
                s.delete(old)
            for row in data.get("sessions", []):
                s.add(
                    StudySession(
                        unit_id=units.get(row.get("unit", "")),
                        started_at=_parse(row.get("started_at")) or datetime.now(),
                        ended_at=_parse(row.get("ended_at")),
                        minutes=int(row.get("minutes", 0) or 0),
                    )
                )
                note("sessions", True)

        # -- card schedules -------------------------------------------------
        # Cards themselves come from YAML; only the scheduling is yours.
        cards = {(c.unit_id, c.front): c for c in s.exec(select(Card))}
        for row in data.get("cards", []):
            uid = units.get(row.get("unit", "")) if row.get("unit") else None
            c = cards.get((uid, row.get("front", "")))
            if c is None:
                note("cards", False)
                continue
            c.ease = float(row.get("ease", 2.5) or 2.5)
            c.interval_days = int(row.get("interval_days", 0) or 0)
            c.repetitions = int(row.get("repetitions", 0) or 0)
            c.lapses = int(row.get("lapses", 0) or 0)
            c.due_at = _parse(row.get("due_at")) or datetime.now()
            note("cards", True)

        # -- projects and the rigor gate ------------------------------------
        for row in data.get("projects", []):
            p = s.exec(select(Project).where(Project.slug == row.get("slug", ""))).first()
            if p is None:
                note("projects", False)
                continue
            p.completed = bool(row.get("completed"))
            p.completed_at = _parse(row.get("completed_at"))
            p.github_url = row.get("github_url", "")
            p.hf_url = row.get("hf_url", "")
            p.demo_url = row.get("demo_url", "")
            note("projects", True)

        for row in data.get("rubric_checks", []):
            pid = projects.get(row.get("project", ""))
            if pid is None:
                note("rubric_checks", False)
                continue
            c = s.exec(
                select(RubricCheck).where(
                    RubricCheck.project_id == pid, RubricCheck.code == row.get("code", "")
                )
            ).first()
            if c is None:
                note("rubric_checks", False)
                continue
            try:
                c.status = CheckStatus(row.get("status", "unchecked"))
            except ValueError:
                c.status = CheckStatus.unchecked
            c.justification = row.get("justification", "")
            c.updated_at = _parse(row.get("updated_at")) or datetime.now()
            note("rubric_checks", True)

        # -- experiment runs -------------------------------------------------
        if "runs" in data:
            for old in s.exec(select(ExperimentRun)):
                s.delete(old)
            for row in data.get("runs", []):
                s.add(
                    ExperimentRun(
                        project_id=projects.get(row.get("project", "")),
                        label=row.get("label", ""),
                        git_commit=row.get("git_commit", ""),
                        seed=row.get("seed"),
                        config_json=row.get("config_json", "{}"),
                        metrics_json=row.get("metrics_json", "{}"),
                        notes=row.get("notes", ""),
                        created_at=_parse(row.get("created_at")) or datetime.now(),
                    )
                )
                note("runs", True)

        # -- submissions ------------------------------------------------------
        if "submissions" in data:
            for old in s.exec(select(Submission)):
                s.delete(old)
            for row in data.get("submissions", []):
                aid = assignments.get(row.get("assignment", ""))
                if aid is None:
                    note("submissions", False)
                    continue
                s.add(
                    Submission(
                        assignment_id=aid,
                        path=row.get("path", ""),
                        tests_passed=int(row.get("tests_passed", 0) or 0),
                        tests_total=int(row.get("tests_total", 0) or 0),
                        timed_out=bool(row.get("timed_out")),
                        stdout=row.get("stdout", ""),
                        review_status=row.get("review_status", "none"),
                        created_at=_parse(row.get("created_at")) or datetime.now(),
                    )
                )
                note("submissions", True)

        s.commit()

    # -- notes ---------------------------------------------------------------
    notes = data.get("notes") or {}
    if notes:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        for slug, text in notes.items():
            # A slug from the file must never escape notes/.
            safe = "".join(ch for ch in str(slug) if ch.isalnum() or ch in "-_")
            if not safe:
                note("notes", False)
                continue
            (NOTES_DIR / f"{safe}.md").write_text(str(text), encoding="utf-8")
            note("notes", True)

    return {"restored": restored, "skipped": skipped}
