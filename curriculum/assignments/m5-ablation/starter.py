"""M5 — Build an ablation table.

The rigor point: a single-seed difference is often smaller than seed noise, so
an "improvement" reported without a spread may be indistinguishable from luck.

Implement the aggregation and the decision rule. Pure Python — you'll wire this
to real training runs afterwards via app.experiments.log_run().
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Row:
    label: str
    n: int
    mean: float
    spread: float


def aggregate(runs: list[dict]) -> list[Row]:
    """Group runs by 'label' and compute mean and sample stdev of run['score'].

    * Sorted by mean, descending.
    * spread is 0.0 when a label has only one run.
    * Ignore runs with no 'score' key.
    """
    raise NotImplementedError


def is_distinguishable(a: Row, b: Row) -> bool:
    """Is the difference between two variants bigger than their noise?

    Return True only if |a.mean - b.mean| exceeds the sum of the two spreads.
    This is a deliberately crude rule — the lesson is that you must compare a
    difference against variability at all, not that this is the right test.

    If either row has n < 2, the spread is unknown, so return False: you cannot
    claim a difference from single runs.
    """
    raise NotImplementedError


def format_table(rows: list[Row]) -> str:
    """Render as a markdown table with columns: variant | n | mean | ± spread.

    Means and spreads formatted to 4 decimal places.
    Header must be exactly:
        | variant | n | mean | spread |
        | --- | --- | --- | --- |
    """
    raise NotImplementedError
