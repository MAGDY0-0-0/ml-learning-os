"""M7 — Evaluate your retriever.

Retrieval eval must be SEPARATE from generation eval. If the retriever never
surfaces the right chunk, no amount of prompting fixes it.

Implement recall@k and MRR over a labelled set of (query -> relevant chunk ids).
Pure Python — no dependencies.
"""

from __future__ import annotations


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """1.0 if any relevant id appears in the top k, else 0.0.

    This is the per-query binary hit rate. Raise ValueError if k < 1.
    """
    raise NotImplementedError


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """1 / (rank of the first relevant result), 1-indexed. 0.0 if none found."""
    raise NotImplementedError


def mean_recall_at_k(
    results: dict[str, list[str]], gold: dict[str, set[str]], k: int
) -> float:
    """Mean recall@k across all queries in `gold`.

    A query present in `gold` but missing from `results` counts as 0.0 — a
    retriever that returns nothing must not be rewarded by being skipped.
    """
    raise NotImplementedError


def mrr(results: dict[str, list[str]], gold: dict[str, set[str]]) -> float:
    """Mean reciprocal rank across all queries in `gold`."""
    raise NotImplementedError
