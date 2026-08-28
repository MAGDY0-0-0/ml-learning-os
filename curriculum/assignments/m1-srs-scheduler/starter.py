"""M1 — Implement the SM-2 spaced repetition scheduler.

This is the algorithm that actually schedules your flashcards in this app, so
you are implementing a real component, not an exercise.

SuperMemo-2 grades:
    0-2 = failed recall
    3   = correct but hard
    4   = correct
    5   = correct and easy

Rules:
  * Ease starts at 2.5 and never drops below 1.3.
  * On a FAILURE (quality < 3):
        - repetitions resets to 0
        - interval resets to 1 day
        - lapses increases by 1
        - ease is reduced by 0.20 (floored at 1.3)
  * On a SUCCESS (quality >= 3):
        - repetitions increases by 1
        - ease += 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02), floored at 1.3
        - interval is 1 day if this is repetition 1
                     6 days if this is repetition 2
                     otherwise round(previous_interval * NEW ease)
        - lapses is unchanged

Raise ValueError for a quality outside 0..5.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_EASE = 1.3


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
    """Return the next schedule for a card. Pure function: no clock, no DB."""
    raise NotImplementedError
