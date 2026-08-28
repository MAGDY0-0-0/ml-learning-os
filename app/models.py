"""SQLModel tables for the ML Learning OS."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------


class ResourceKind(str, Enum):
    video = "video"
    playlist = "playlist"
    course = "course"
    book = "book"
    paper = "paper"
    article = "article"
    interactive = "interactive"
    docs = "docs"
    repo = "repo"


#: Formats that count as "watching". Used by seed validation to enforce the
#: video-first policy and the mixed-modality rule for alternates.
VIDEO_KINDS = {ResourceKind.video, ResourceKind.playlist, ResourceKind.course}
TEXT_KINDS = {ResourceKind.book, ResourceKind.paper, ResourceKind.article, ResourceKind.docs}
DOING_KINDS = {ResourceKind.interactive, ResourceKind.repo}


def modality(kind: ResourceKind) -> str:
    if kind in VIDEO_KINDS:
        return "video"
    if kind in TEXT_KINDS:
        return "text"
    return "interactive"


class Cost(str, Enum):
    free = "free"
    free_audit = "free-audit"
    paid_optional = "paid-optional"


FREE_COSTS = {Cost.free, Cost.free_audit}


class UnitStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"


class SwapReason(str, Enum):
    too_slow = "too_slow"
    too_hard = "too_hard"
    too_basic = "too_basic"
    boring = "boring"
    bad_audio = "bad_audio"
    wrong_level = "wrong_level"
    dead_link = "dead_link"
    other = "other"


class CheckStatus(str, Enum):
    unchecked = "unchecked"
    passed = "passed"
    skipped = "skipped"


# --------------------------------------------------------------------------
# curriculum
# --------------------------------------------------------------------------


class Module(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    blurb: str = ""
    order: int = 0


class Unit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: int = Field(foreign_key="module.id", index=True)
    slug: str = Field(index=True, unique=True)
    title: str
    objective: str = ""
    est_minutes: int = 60
    order: int = 0
    needs_gpu: bool = False
    optional_stretch: bool = False
    #: set when no free video exists for this topic; required to pass the
    #: video-first seed check with a text primary.
    no_good_video: bool = False
    no_good_video_reason: str = ""
    #: free-text rigor rung this unit adds, rendered on the unit page
    rigor_note: str = ""


class Resource(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id", index=True)
    kind: ResourceKind
    title: str
    url: str
    provider: str = ""
    est_minutes: int = 0
    #: 0 = primary; higher numbers are the alternates offered by "swap"
    rank: int = 0
    community_verdict: str = ""
    caveat: str = ""
    cost: Cost = Cost.free
    #: for playlists where only one chapter is assigned (M3 lookup-only)
    lookup_only: bool = False
    concept: str = ""


class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id", index=True)
    slug: str = Field(index=True, unique=True)
    title: str
    brief: str = ""
    starter_path: str = ""
    tests_path: str = ""
    difficulty: str = "core"  # easier | core | harder


# --------------------------------------------------------------------------
# progress
# --------------------------------------------------------------------------


class Progress(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id", index=True, unique=True)
    status: UnitStatus = UnitStatus.not_started
    minutes_logged: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ResourceState(SQLModel, table=True):
    """Per-resource 'I finished this' + which alternate is currently active."""

    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id", index=True, unique=True)
    done: bool = False
    position_seconds: int = 0


class ResourcePreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id", index=True)
    reason: SwapReason = SwapReason.other
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ActiveResource(SQLModel, table=True):
    """Which resource is currently promoted to primary for a unit."""

    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id", index=True, unique=True)
    resource_id: int = Field(foreign_key="resource.id")


class StudySession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: Optional[int] = Field(default=None, foreign_key="unit.id", index=True)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: Optional[datetime] = None
    minutes: int = 0


# --------------------------------------------------------------------------
# spaced repetition (SM-2)
# --------------------------------------------------------------------------


class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: Optional[int] = Field(default=None, foreign_key="unit.id", index=True)
    front: str
    back: str
    #: permanent cards (the 8 leakage types) are never suspended
    permanent: bool = False
    ease: float = 2.5
    interval_days: int = 0
    repetitions: int = 0
    lapses: int = 0
    due_at: datetime = Field(default_factory=utcnow, index=True)
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# rigor + experiments
# --------------------------------------------------------------------------


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    module_slug: str = ""
    brief: str = ""
    completed: bool = False
    completed_at: Optional[datetime] = None
    #: M9 deployment triple
    github_url: str = ""
    hf_url: str = ""
    demo_url: str = ""
    requires_deployment: bool = False


class RubricCheck(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    code: str  # L1.1 ... L3.3, or ladder rungs: split, baseline, metric, ...
    label: str
    question: str = ""
    group: str = "leakage"  # leakage | ladder | deployment
    status: CheckStatus = CheckStatus.unchecked
    justification: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class ExperimentRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)
    label: str = ""
    git_commit: str = ""
    seed: Optional[int] = None
    config_json: str = "{}"
    metrics_json: str = "{}"
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)


# --------------------------------------------------------------------------
# submissions
# --------------------------------------------------------------------------


class Submission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id", index=True)
    path: str
    tests_passed: int = 0
    tests_total: int = 0
    timed_out: bool = False
    stdout: str = ""
    review_status: str = "none"  # none | requested
    created_at: datetime = Field(default_factory=utcnow, index=True)


# --------------------------------------------------------------------------
# library
# --------------------------------------------------------------------------


class LibraryDoc(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    path: str = Field(index=True, unique=True)
    title: str
    kind: str = "book"  # book | paper
    pages: int = 0
    indexed_at: datetime = Field(default_factory=utcnow)
