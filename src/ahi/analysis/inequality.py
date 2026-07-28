"""Measuring the mobility divide.

Mau et al. (2015) argue that global visa liberalization has been real but
unequally distributed: the world got more open on average while the gap between
the most and least mobile passports widened. That is an inequality claim, and
inequality claims have standard instruments -- Gini coefficients, Lorenz curves,
concentration shares. This module applies them to mobility rights instead of to
income, and to two different questions:

  1. how unequally is *access* distributed across passports, and
  2. how unequally is *value* distributed across destinations -- because if
     three quarters of the world's weighted opportunity sits in a fifth of its
     countries, then who holds the keys to that fifth is the entire story.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import HEADLINE_LENS


def gini(values: np.ndarray | pd.Series) -> float:
    """Standard Gini coefficient. 0 = everyone identical, 1 = one holder takes all."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return float("nan")
    index = np.arange(1, n + 1)
    return float((2 * index - n - 1).dot(x) / (n * x.sum()))


def lorenz_curve(values: pd.Series) -> pd.DataFrame:
    x = np.sort(np.asarray(values, dtype=float))
    cumulative = np.insert(np.cumsum(x) / x.sum(), 0, 0.0)
    population = np.linspace(0, 1, len(x) + 1)
    return pd.DataFrame({"population_share": population, "value_share": cumulative})


def mobility_inequality(family: pd.DataFrame, features: pd.DataFrame,
                        population_weighted: bool = True) -> pd.DataFrame:
    """Gini of each index across passports, unweighted and population-weighted.

    The unweighted Gini treats Tuvalu's passport and India's as one observation
    each, which measures inequality between *states*. The population-weighted
    version measures inequality between *people*, which is the quantity the
    mobility-divide argument is actually about -- and the two differ, because
    weak passports are disproportionately held by large populations.
    """
    rows = []
    score_cols = [c for c in family.columns if c.endswith("_score")]
    pop = family["passport"].map(features["population"]).to_numpy()
    for col in score_cols:
        values = family[col].to_numpy(dtype=float)
        entry = {"index": col[:-6], "gini_by_country": round(gini(values), 4)}
        if population_weighted:
            # Replicate each country in proportion to its population (to the
            # nearest ten thousand people) and take the Gini of that.
            reps = np.maximum((pop / 1e4).round().astype(int), 1)
            entry["gini_by_person"] = round(gini(np.repeat(values, reps)), 4)
        entry["p90_p10_ratio"] = round(float(np.percentile(values, 90) /
                                             max(np.percentile(values, 10), 1e-9)), 2)
        rows.append(entry)
    return pd.DataFrame(rows).sort_values("gini_by_country", ascending=False)


def destination_value_concentration(features: pd.DataFrame,
                                    lens_key: str = HEADLINE_LENS) -> dict:
    """How concentrated is the world's travel-value in a few destinations?"""
    from ..indices import lens_weights
    weight = lens_weights(features, lens_key).sort_values(ascending=False)
    total = weight.sum()
    shares = weight.cumsum() / total
    return {
        "gini_of_destination_weight": round(gini(weight), 4),
        "top10_share_pct": round(float(shares.iloc[9] * 100), 1),
        "top20_share_pct": round(float(shares.iloc[19] * 100), 1),
        "top50_share_pct": round(float(shares.iloc[49] * 100), 1),
        "max_to_min_ratio": round(float(weight.max() / weight.min()), 1),
        "highest": weight.head(10).round(3).to_dict(),
        "lowest": weight.tail(10).round(3).to_dict(),
    }


def divide_by_group(family: pd.DataFrame, features: pd.DataFrame,
                    group_col: str = "income_group",
                    index_col: str = f"ahi_{HEADLINE_LENS}_pct") -> pd.DataFrame:
    """Mean access by income group and region -- the divide, tabulated.

    Uses the attainment percentage rather than the raw score so the number
    reads as "this group's citizens can reach x% of what is theoretically
    reachable", which is comparable across index variants.
    """
    merged = family.merge(features[[group_col, "population"]],
                          left_on="passport", right_index=True, how="left")
    grouped = merged.groupby(group_col, dropna=False).agg(
        countries=("passport", "size"),
        people=("population", "sum"),
        mean_access_pct=(index_col, "mean"),
        median_access_pct=(index_col, "median"),
        henley_mean_count=("henley_score", "mean"),
    ).reset_index()
    grouped["people_share_pct"] = (grouped["people"] / grouped["people"].sum() * 100).round(1)
    return grouped.sort_values("mean_access_pct", ascending=False)


def access_to_wealth_gap(family: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Each passport's share of world GDP reachable, against its own share.

    The ratio is a compact statement of the divide: a country whose citizens can
    reach 5% of world output while producing 2% of it is a net beneficiary of
    the visa system; one that produces 3% and can reach 20% is not. It also
    separates the two ways a passport can be weak -- being poor, and being
    distrusted -- because they are not the same thing and are not fixed the
    same way.
    """
    world_gdp = features["gdp_total_ppp"].sum()
    own_share = (features["gdp_total_ppp"] / world_gdp * 100)
    table = pd.DataFrame({
        "reachable_gdp_share_pct": family.set_index("passport")["gdp_share_score"],
        "own_gdp_share_pct": own_share,
    })
    table["reach_to_own_ratio"] = (table["reachable_gdp_share_pct"] /
                                   table["own_gdp_share_pct"].clip(lower=1e-6)).round(1)
    table.index.name = "passport"
    return table.reset_index()
