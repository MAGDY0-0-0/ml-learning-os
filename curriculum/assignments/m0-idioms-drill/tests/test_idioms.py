"""Hidden tests for the M0 idioms drill."""

import inspect

import pytest

import solution as s


def test_evens_squared():
    assert s.evens_squared([1, 2, 3, 4, 5, 6]) == [4, 16, 36]
    assert s.evens_squared([]) == []
    assert s.evens_squared([1, 3, 5]) == []
    assert s.evens_squared([-2, -1]) == [4]


def test_evens_squared_uses_comprehension():
    src = inspect.getsource(s.evens_squared)
    assert "for" in src and "[" in src, "use a list comprehension, not an append loop"
    assert ".append(" not in src, "this one is meant to be a comprehension, not append()"


def test_reverse_copy_does_not_mutate():
    original = [1, 2, 3]
    out = s.reverse_copy(original)
    assert out == [3, 2, 1]
    assert original == [1, 2, 3], "the original list must not be modified"
    assert out is not original
    assert isinstance(out, list), "must return a list, not a reversed-iterator"


def test_word_count():
    assert s.word_count("a A b") == {"a": 2, "b": 1}
    assert s.word_count("") == {}
    assert s.word_count("  spaced   out  ") == {"spaced": 1, "out": 1}


def test_first_matching():
    assert s.first_matching([1, 2, 3, 4], lambda x: x > 2) == 3
    assert s.first_matching([1, 2], lambda x: x > 99) is None
    assert s.first_matching([], lambda x: True, default="none") == "none"


def test_first_matching_is_lazy():
    """It must stop at the first hit, not scan the whole iterable."""
    seen = []

    def spy(x):
        seen.append(x)
        return x == 1

    assert s.first_matching([1, 2, 3, 4, 5], spy) == 1
    assert seen == [1], f"predicate ran {len(seen)} times; it should short-circuit"


def test_swap():
    assert s.swap(1, 2) == (2, 1)
    assert s.swap("a", "b") == ("b", "a")


def test_flatten():
    assert s.flatten([[1, 2], [3], []]) == [1, 2, 3]
    assert s.flatten([]) == []
    assert s.flatten([[], []]) == []


def test_group_by_length():
    assert s.group_by_length(["a", "bb", "cc", "ddd"]) == {
        1: ["a"],
        2: ["bb", "cc"],
        3: ["ddd"],
    }
    assert s.group_by_length([]) == {}


def test_truthy_only():
    assert s.truthy_only([0, 1, "", "x", None, [], [0], False, {}]) == [1, "x", [0]]
    assert s.truthy_only([]) == []


def test_truthy_only_uses_truthiness_not_explicit_comparisons():
    src = inspect.getsource(s.truthy_only)
    assert "!= 0" not in src and "is not None" not in src, (
        "rely on Python truthiness rather than enumerating falsy values"
    )
