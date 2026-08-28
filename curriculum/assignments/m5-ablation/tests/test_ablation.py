"""Hidden tests for the ablation table."""

import pytest

from solution import Row, aggregate, format_table, is_distinguishable


RUNS = [
    {"label": "full", "score": 0.90, "seed": 0},
    {"label": "full", "score": 0.92, "seed": 1},
    {"label": "full", "score": 0.91, "seed": 2},
    {"label": "no-aug", "score": 0.80, "seed": 0},
    {"label": "no-aug", "score": 0.82, "seed": 1},
    {"label": "no-aug", "score": 0.81, "seed": 2},
]


def test_aggregate_groups_and_counts():
    rows = aggregate(RUNS)
    assert [r.label for r in rows] == ["full", "no-aug"]
    assert all(r.n == 3 for r in rows)


def test_aggregate_means():
    rows = {r.label: r for r in aggregate(RUNS)}
    assert rows["full"].mean == pytest.approx(0.91, abs=1e-6)
    assert rows["no-aug"].mean == pytest.approx(0.81, abs=1e-6)


def test_aggregate_spread_is_sample_stdev():
    rows = {r.label: r for r in aggregate(RUNS)}
    assert rows["full"].spread == pytest.approx(0.01, abs=1e-6)


def test_single_run_has_zero_spread():
    rows = aggregate([{"label": "solo", "score": 0.5}])
    assert rows[0].spread == 0.0
    assert rows[0].n == 1


def test_runs_without_score_ignored():
    rows = aggregate([{"label": "a", "score": 1.0}, {"label": "a"}])
    assert rows[0].n == 1


def test_sorted_descending_by_mean():
    rows = aggregate(RUNS)
    assert rows[0].mean >= rows[1].mean


def test_distinguishable_when_gap_exceeds_noise():
    a = Row("full", 3, 0.91, 0.01)
    b = Row("no-aug", 3, 0.81, 0.01)
    assert is_distinguishable(a, b) is True


def test_not_distinguishable_when_noise_swamps_gap():
    a = Row("a", 3, 0.91, 0.05)
    b = Row("b", 3, 0.90, 0.05)
    assert is_distinguishable(a, b) is False


def test_single_run_is_never_distinguishable():
    a = Row("a", 1, 0.99, 0.0)
    b = Row("b", 3, 0.10, 0.01)
    assert is_distinguishable(a, b) is False, (
        "you cannot claim a difference from a single run, however large the gap"
    )


def test_format_table_header_and_values():
    out = format_table([Row("full", 3, 0.91, 0.01)])
    lines = out.strip().splitlines()
    assert lines[0].strip() == "| variant | n | mean | spread |"
    assert lines[1].strip() == "| --- | --- | --- | --- |"
    assert "full" in lines[2] and "0.9100" in lines[2] and "0.0100" in lines[2]
