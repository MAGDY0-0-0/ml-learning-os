"""Hidden tests for retrieval metrics."""

import pytest

from solution import mean_recall_at_k, mrr, recall_at_k, reciprocal_rank


def test_recall_at_k_hit_and_miss():
    assert recall_at_k(["a", "b", "c"], {"c"}, 3) == 1.0
    assert recall_at_k(["a", "b", "c"], {"c"}, 2) == 0.0
    assert recall_at_k(["a", "b"], {"z"}, 5) == 0.0


def test_recall_at_k_first_position():
    assert recall_at_k(["x"], {"x"}, 1) == 1.0


def test_recall_at_k_rejects_bad_k():
    with pytest.raises(ValueError):
        recall_at_k(["a"], {"a"}, 0)


def test_reciprocal_rank():
    assert reciprocal_rank(["a", "b", "c"], {"a"}) == pytest.approx(1.0)
    assert reciprocal_rank(["a", "b", "c"], {"b"}) == pytest.approx(0.5)
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0


def test_reciprocal_rank_uses_first_relevant():
    assert reciprocal_rank(["a", "b", "c"], {"b", "c"}) == pytest.approx(0.5)


def test_reciprocal_rank_empty():
    assert reciprocal_rank([], {"a"}) == 0.0


def test_mean_recall_averages():
    results = {"q1": ["a", "b"], "q2": ["x", "y"]}
    gold = {"q1": {"a"}, "q2": {"z"}}
    assert mean_recall_at_k(results, gold, 2) == pytest.approx(0.5)


def test_missing_query_counts_as_zero():
    """The edge case: the retriever returned nothing for q2."""
    results = {"q1": ["a"]}
    gold = {"q1": {"a"}, "q2": {"b"}}
    assert mean_recall_at_k(results, gold, 1) == pytest.approx(0.5), (
        "a query with no results must count as 0, not be skipped"
    )
    assert mrr(results, gold) == pytest.approx(0.5)


def test_mrr_averages():
    results = {"q1": ["a", "b"], "q2": ["x", "y"]}
    gold = {"q1": {"b"}, "q2": {"x"}}
    assert mrr(results, gold) == pytest.approx((0.5 + 1.0) / 2)


def test_empty_gold_is_zero_not_crash():
    assert mean_recall_at_k({}, {}, 3) == 0.0
    assert mrr({}, {}) == 0.0
