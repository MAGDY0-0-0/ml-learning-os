"""Hidden tests for the leak hunt."""

import inspect

import pytest

pytest.importorskip("sklearn", reason="pip install scikit-learn pandas")
pytest.importorskip("pandas")

import solution as s


EXPECTED = {"L1.4", "L2", "L3.2"}


def test_identified_the_right_leaks():
    assert s.LEAKS_FOUND == EXPECTED, (
        "Expected the duplicate-rows leak, the illegitimate-feature leak, and "
        "the repeat-customer (non-independence) leak."
    )


def test_illegitimate_feature_removed():
    """L2 — cancellation_reason_code only exists after churn happens."""
    cols = s.feature_columns(s.clean(s.make_data()))
    assert "cancellation_reason_code" not in cols, (
        "cancellation_reason_code is recorded after the event — it can't be a feature"
    )
    assert "churn" not in cols


def test_duplicates_removed_before_split():
    """L1.4 — deduplicate before splitting, not after."""
    df = s.clean(s.make_data())
    assert not df.duplicated().any(), "duplicate rows must be dropped during clean()"


def test_split_is_grouped_by_customer():
    """L3.2 — the same customer must not appear on both sides."""
    df = s.clean(s.make_data())
    train, test = s.make_splits(df)
    overlap = set(train["customer_id"]) & set(test["customer_id"])
    assert not overlap, (
        f"{len(overlap)} customers appear in both train and test — use GroupKFold "
        "or GroupShuffleSplit on customer_id"
    )


def test_scaling_happens_inside_a_pipeline():
    """L1.2 — preprocessing must be fit inside the fold."""
    from sklearn.pipeline import Pipeline

    model = s.build_pipeline()
    assert isinstance(model, Pipeline), (
        "wrap preprocessing + estimator in a sklearn Pipeline so scalers are fit "
        "on training data only"
    )


def test_score_is_realistic_not_inflated():
    auc = s.evaluate()
    assert 0.5 <= auc <= 0.92, (
        f"AUC {auc:.3f} — an honest model on this data should be good but not "
        "near-perfect. A very high score means a leak survives."
    )


def test_no_fillna_over_full_dataset():
    src = inspect.getsource(s.clean)
    assert "df.mean(" not in src or "numeric_only" not in src or "fillna" not in src, (
        "imputing with statistics computed over the whole dataset is L1.2"
    )
