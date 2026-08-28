"""SM-2 spaced repetition scheduling.

Quality grades follow the original SuperMemo-2 definition:
    0-2 = failed recall (card lapses, interval resets)
    3   = correct, but hard
    4   = correct
    5   = correct and easy
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MIN_EASE = 1.3
FAIL_THRESHOLD = 3


@dataclass
class Schedule:
    ease: float
    interval_days: int
    repetitions: int
    lapses: int


def review(
    ease: float,
    interval_days: int,
    repetitions: int,
    lapses: int,
    quality: int,
) -> Schedule:
    """Return the next schedule for a card given a review grade.

    Pure function — no DB, no clock — so it can be tested against known vectors.
    """
    if not 0 <= quality <= 5:
        raise ValueError(f"quality must be 0..5, got {quality}")

    if quality < FAIL_THRESHOLD:
        # Lapse: repetitions reset, card comes back tomorrow, ease is penalised.
        new_ease = max(MIN_EASE, ease - 0.20)
        return Schedule(ease=new_ease, interval_days=1, repetitions=0, lapses=lapses + 1)

    # SM-2 ease update.
    new_ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(MIN_EASE, new_ease)

    new_reps = repetitions + 1
    if new_reps == 1:
        new_interval = 1
    elif new_reps == 2:
        new_interval = 6
    else:
        new_interval = max(1, round(interval_days * new_ease))

    return Schedule(
        ease=new_ease,
        interval_days=new_interval,
        repetitions=new_reps,
        lapses=lapses,
    )


def next_due(interval_days: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=interval_days)
