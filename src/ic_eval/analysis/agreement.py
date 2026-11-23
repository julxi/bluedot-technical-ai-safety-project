"""Rates per judging and agreement between judgings, on a table with one column per judging
(rows: judged replies; values 1.0, 0.0 or NaN for invalid)."""

import itertools
import math

import pandas as pd


def cohen_kappa(a: pd.Series, b: pd.Series) -> float:
    """Cohen's kappa for two binary raters: agreement corrected for the agreement expected by
    chance from each rater's own rate. NaN if chance agreement is 1 (both constant and equal)."""
    assert len(a) == len(b) and len(a) > 0
    observed = float((a == b).mean())
    pa, pb = float(a.mean()), float(b.mean())
    expected = pa * pb + (1 - pa) * (1 - pb)
    return math.nan if expected == 1 else (observed - expected) / (1 - expected)


def pairwise_agreement(verdicts: pd.DataFrame) -> pd.DataFrame:
    """For each pair of judgings: replies both judged validly, share agreeing, Cohen's kappa."""
    rows = []
    for x, y in itertools.combinations(verdicts.columns, 2):
        both = verdicts[[x, y]].dropna()
        rows.append(
            {
                "judging_a": x,
                "judging_b": y,
                "n_both_valid": len(both),
                "agreement": float((both[x] == both[y]).mean()) if len(both) else math.nan,
                "kappa": cohen_kappa(both[x], both[y]) if len(both) else math.nan,
            }
        )
    return pd.DataFrame(rows)


def disagreements(verdicts: pd.DataFrame) -> pd.Index:
    """Replies on which the valid verdicts differ, or at least one judging is invalid."""
    valid = verdicts.notna()
    differ = verdicts.max(axis=1) != verdicts.min(axis=1)
    return verdicts.index[differ | ~valid.all(axis=1)]
