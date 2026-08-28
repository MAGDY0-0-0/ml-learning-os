"""M4 — Find the leaks.

The pipeline below reports a suspiciously good score. It contains THREE planted
leaks from different classes of the Kapoor & Narayanan taxonomy.

Your job:
  1. Identify each leak by code (L1.2, L1.3, L1.4, L2, L3.1, L3.2, L3.3).
  2. Fix them in `build_pipeline` / `make_splits` / `clean`.
  3. Report the honest score.

Fill in LEAKS_FOUND with the three codes. The tests check both that you named
the right ones AND that the leaky operations are actually gone from your code.

Requires: pip install scikit-learn pandas
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- FILL THIS IN: the three leak codes you found, e.g. {"L1.2", "L2", "L3.1"}
LEAKS_FOUND: set[str] = set()


def make_data(n: int = 600, seed: int = 0) -> pd.DataFrame:
    """Synthetic customer-churn-ish data with a time column and repeat customers."""
    rng = np.random.default_rng(seed)
    customer_id = rng.integers(0, n // 3, size=n)  # customers appear multiple times
    day = rng.integers(0, 365, size=n)
    tenure = rng.normal(30, 10, size=n)
    spend = rng.normal(100, 40, size=n)
    noise = rng.normal(0, 1, size=n)
    churn = ((0.03 * tenure - 0.01 * spend + noise) > 0).astype(int)

    df = pd.DataFrame(
        {
            "customer_id": customer_id,
            "day": day,
            "tenure": tenure,
            "spend": spend,
            # This column is recorded only AFTER the customer churns.
            "cancellation_reason_code": np.where(churn == 1, rng.integers(1, 5, n), 0),
            "churn": churn,
        }
    )
    # Duplicate some rows outright.
    return pd.concat([df, df.iloc[: n // 20]], ignore_index=True)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the frame. NOTE: currently leaks."""
    df = df.copy()
    # Fill missing values using statistics over the WHOLE dataset.
    df = df.fillna(df.mean(numeric_only=True))
    return df


def make_splits(df: pd.DataFrame):
    """Return (train_df, test_df). NOTE: currently leaks."""
    from sklearn.model_selection import train_test_split

    return train_test_split(df, test_size=0.25, random_state=0, shuffle=True)


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Columns to train on. NOTE: currently includes something it shouldn't."""
    return [c for c in df.columns if c != "churn"]


def build_pipeline():
    """Build the model. Should be a Pipeline so scaling stays inside the fold."""
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(max_iter=1000)


def evaluate() -> float:
    from sklearn.metrics import roc_auc_score

    df = clean(make_data())
    train, test = make_splits(df)
    cols = feature_columns(df)

    model = build_pipeline()
    model.fit(train[cols], train["churn"])
    preds = model.predict_proba(test[cols])[:, 1]
    return float(roc_auc_score(test["churn"], preds))


if __name__ == "__main__":
    print("AUC:", round(evaluate(), 4))
    print("leaks found:", sorted(LEAKS_FOUND))
