"""M0 — Idioms drill.

Eight small functions. Each has an obvious transliterated-from-another-language
solution and an idiomatic Python one. The tests check correctness AND, for a few
of them, that you actually used the idiom (via the function's source text).

Write Python, not Java-in-Python.
"""

from __future__ import annotations


def evens_squared(numbers: list[int]) -> list[int]:
    """Squares of the even numbers, in order.

    Idiom: a list comprehension with a filter.
    >>> evens_squared([1, 2, 3, 4])
    [4, 16]
    """
    raise NotImplementedError


def reverse_copy(items: list) -> list:
    """A reversed *copy* of the list (the original must be unchanged).

    Idiom: slicing with a negative step.
    """
    raise NotImplementedError


def word_count(text: str) -> dict[str, int]:
    """Count whitespace-separated words, case-insensitively.

    >>> word_count("a A b")
    {'a': 2, 'b': 1}
    """
    raise NotImplementedError


def first_matching(items, predicate, default=None):
    """First item for which predicate(item) is true, else default.

    Idiom: next() with a generator expression and a default.
    Must not build an intermediate list.
    """
    raise NotImplementedError


def swap(a, b):
    """Return (b, a).

    Idiom: tuple unpacking — no temporary variable.
    """
    raise NotImplementedError


def flatten(nested: list[list]) -> list:
    """One level of flattening.

    >>> flatten([[1, 2], [3], []])
    [1, 2, 3]
    """
    raise NotImplementedError


def group_by_length(words: list[str]) -> dict[int, list[str]]:
    """Group words by their length, preserving input order within each group.

    >>> group_by_length(["a", "bb", "cc"])
    {1: ['a'], 2: ['bb', 'cc']}
    """
    raise NotImplementedError


def truthy_only(items: list) -> list:
    """Keep only truthy items.

    Remember Python's falsy values: False, None, 0, 0.0, '', [], {}, set().
    """
    raise NotImplementedError
