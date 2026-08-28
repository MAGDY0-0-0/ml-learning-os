"""Hidden tests for the messy-CSV cleanup."""

import pytest

pd = pytest.importorskip("pandas", reason="pip install pandas")

import solution as s


@pytest.fixture
def df():
    return s.clean(s.load_raw())


def test_duplicates_dropped(df):
    assert len(df) == 6, f"expected 6 unique rows, got {len(df)}"
    assert not df.duplicated().any()


def test_customer_normalised(df):
    names = set(df["customer"])
    assert names == {"Alice", "Bob", "Carol", "Dave", "Erin"}, names
    assert not any(n != n.strip() for n in names), "whitespace not stripped"


def test_dates_parsed(df):
    assert pd.api.types.is_datetime64_any_dtype(df["order_date"]), "dates not parsed"
    assert df["order_date"].isna().sum() == 0, "some date formats failed to parse"
    assert df["order_date"].min().year == 2024


def test_amount_numeric_and_imputed(df):
    assert pd.api.types.is_numeric_dtype(df["amount"])
    assert df["amount"].isna().sum() == 0
    # median of [10.50, 20, 15.25, 30.00, 12.75] = 15.25
    assert df.loc[df["order_id"] == 4, "amount"].iloc[0] == pytest.approx(15.25)


def test_status_consistent(df):
    assert set(df["status"]) == {"shipped", "cancelled"}


def test_leaky_column_dropped(df):
    assert "refund_issued" not in df.columns, (
        "refund_issued is only known after cancellation — dropping it is L2"
    )


def test_feature_columns_exclude_target_and_leak(df):
    cols = s.feature_columns(df)
    assert "status" not in cols
    assert "refund_issued" not in cols


def test_index_reset(df):
    assert list(df.index) == list(range(len(df)))
