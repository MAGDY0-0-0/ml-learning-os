"""Hidden tests for the SM-2 scheduler, checked against known-good vectors."""

import pytest

from solution import MIN_EASE, review


def test_first_success_gives_one_day():
    r = review(2.5, 0, 0, 0, 4)
    assert r.repetitions == 1
    assert r.interval_days == 1
    assert r.lapses == 0


def test_second_success_gives_six_days():
    r = review(2.5, 1, 1, 0, 4)
    assert r.repetitions == 2
    assert r.interval_days == 6


def test_third_success_multiplies_by_new_ease():
    # quality 4 leaves ease unchanged at 2.5 -> 6 * 2.5 = 15
    r = review(2.5, 6, 2, 0, 4)
    assert r.repetitions == 3
    assert r.interval_days == 15
    assert r.ease == pytest.approx(2.5)


def test_quality_five_increases_ease():
    r = review(2.5, 6, 2, 0, 5)
    assert r.ease == pytest.approx(2.6)
    assert r.interval_days == round(6 * 2.6)


def test_quality_three_decreases_ease():
    # q=3: 0.1 - 2*(0.08 + 2*0.02) = 0.1 - 0.24 = -0.14
    r = review(2.5, 6, 2, 0, 3)
    assert r.ease == pytest.approx(2.36)


def test_failure_resets_and_counts_a_lapse():
    r = review(2.5, 15, 3, 1, 1)
    assert r.repetitions == 0
    assert r.interval_days == 1
    assert r.lapses == 2
    assert r.ease == pytest.approx(2.3)


def test_ease_floor_is_respected_on_failure():
    r = review(1.3, 10, 4, 0, 0)
    assert r.ease == pytest.approx(MIN_EASE)
    assert r.ease >= MIN_EASE


def test_ease_floor_is_respected_on_hard_success():
    r = review(1.3, 10, 4, 0, 3)
    assert r.ease >= MIN_EASE


def test_interval_never_below_one_day():
    r = review(1.3, 0, 5, 0, 3)
    assert r.interval_days >= 1


def test_invalid_quality_raises():
    with pytest.raises(ValueError):
        review(2.5, 1, 1, 0, 6)
    with pytest.raises(ValueError):
        review(2.5, 1, 1, 0, -1)


def test_is_pure_no_mutation_of_inputs():
    """The function must not depend on or mutate global state."""
    a = review(2.5, 6, 2, 0, 4)
    b = review(2.5, 6, 2, 0, 4)
    assert (a.ease, a.interval_days, a.repetitions, a.lapses) == (
        b.ease,
        b.interval_days,
        b.repetitions,
        b.lapses,
    )
