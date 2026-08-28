"""M2 — Clean a messy CSV.

The generated data is deliberately awful: mixed types, duplicate rows, dates in
three formats, whitespace, inconsistent casing, and one column that leaks the
target. Produce a tidy DataFrame.

Requires: pip install pandas
"""

from __future__ import annotations

import io

import pandas as pd

RAW = """order_id,customer,order_date,amount,status,refund_issued
1, alice ,2024-01-05,10.50,SHIPPED,0
2,BOB,05/01/2024,20,shipped,0
3,Carol,Jan 6 2024,15.25,Cancelled,1
4, alice ,2024-01-07,,shipped,0
5,dave,2024-01-08,30.00,CANCELLED,1
2,BOB,05/01/2024,20,shipped,0
6,Erin,2024-01-09,12.75,Shipped,0
"""


def load_raw() -> pd.DataFrame:
    return pd.read_csv(io.StringIO(RAW))


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Return a tidy frame.

    Requirements:
      * drop exact duplicate rows
      * strip whitespace from `customer` and title-case it ("alice" -> "Alice")
      * parse `order_date` (all three formats) into real datetimes
      * `amount` must be numeric; fill missing with the MEDIAN amount
      * `status` lower-cased and consistent
      * DROP `refund_issued` — it is only known after cancellation, so keeping it
        to predict `status` would be leakage L2
      * reset the index
    """
    raise NotImplementedError


def target_column() -> str:
    return "status"


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Columns safe to use as features for predicting `status`."""
    raise NotImplementedError


if __name__ == "__main__":
    print(clean(load_raw()))
