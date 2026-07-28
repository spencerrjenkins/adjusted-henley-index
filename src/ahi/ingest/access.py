"""Parse the passport access matrix into a tidy, graded edge list.

The source is a 199 x 199 matrix whose cells are free text: `visa free`,
`visa on arrival`, `eta`, `e-visa`, `visa required`, `no admission`, `-1` for
the diagonal, or a bare integer giving the number of visa-free days permitted.
Roughly 55% of all frictionless cells carry an explicit day count, which is a
dimension of the data that every published passport index throws away.

This module produces one row per ordered (passport, destination) pair with:
  * `category`      - the normalized entry-regime label
  * `stay_days`     - permitted length of stay, explicit where stated
  * one column per access ladder in `config.ACCESS_LADDERS`, giving the credit
    that ladder assigns to the pair.
"""

from __future__ import annotations

import re

import pandas as pd

from ..config import ACCESS_LADDERS, DEFAULT_STAY_DAYS, RAW

MATRIX_ISO3 = RAW / "passport_index_matrix_iso3.csv"
MATRIX_NAMES = RAW / "passport_index_matrix_names.csv"

# The raw vocabulary, normalized. Anything not matched here and not an integer
# raises rather than being silently dropped into `visa_required` -- an unknown
# token is a schema change upstream, and should fail loudly.
CATEGORY_MAP = {
    "visa free": "visa_free",
    "visa on arrival": "visa_on_arrival",
    "eta": "eta",
    "e-visa": "e_visa",
    "evisa": "e_visa",
    "visa required": "visa_required",
    "no admission": "no_admission",
    "covid ban": "no_admission",
    "-1": "self",
}
_INT_RE = re.compile(r"^\d+$")


def _normalize(value: object) -> tuple[str, float | None]:
    """Return (category, explicit_stay_days or None) for one matrix cell."""
    token = str(value).strip().lower()
    if _INT_RE.match(token):
        # A bare integer is a visa-free allowance in days.
        return "visa_free", float(token)
    category = CATEGORY_MAP.get(token)
    if category is None:
        raise ValueError(f"unrecognized access token in matrix: {value!r}")
    return category, None


def load_access_edges() -> pd.DataFrame:
    """Tidy edge list of every ordered passport -> destination pair."""
    matrix = pd.read_csv(MATRIX_ISO3, index_col="Passport")
    long = (matrix.stack()
            .rename("raw")
            .rename_axis(["passport", "destination"])
            .reset_index())

    parsed = long["raw"].map(_normalize)
    long["category"] = [c for c, _ in parsed]
    long["explicit_days"] = [d for _, d in parsed]

    # The diagonal is your own country: not a mobility right the index is about.
    long = long[long["category"] != "self"].copy()
    if (long["passport"] == long["destination"]).any():
        raise AssertionError("self-pairs survived the diagonal filter")

    long["stay_days"] = long["explicit_days"].fillna(
        long["category"].map(DEFAULT_STAY_DAYS).astype(float)
    )
    long["days_are_explicit"] = long["explicit_days"].notna()

    for ladder_name, ladder in ACCESS_LADDERS.items():
        long[f"credit_{ladder_name}"] = long["category"].map(ladder).astype(float)

    return long.reset_index(drop=True)


def load_iso3_to_name() -> dict[str, str]:
    """The ISO3 and human-name matrices share a column order, so the headers
    line up positionally. Cheaper and more faithful than a third-party mapping
    that would disagree with the matrix about e.g. Kosovo or Taiwan."""
    iso3 = pd.read_csv(MATRIX_ISO3, nrows=0).columns[1:]
    names = pd.read_csv(MATRIX_NAMES, nrows=0).columns[1:]
    if len(iso3) != len(names):
        raise AssertionError("ISO3 and name matrices have different widths")
    return dict(zip(iso3, names))


def category_summary(edges: pd.DataFrame) -> pd.DataFrame:
    """Counts and shares by entry regime -- the descriptive table the article
    opens with, and the thing that makes the binary/graded gap concrete."""
    total = len(edges)
    summary = (edges.groupby("category")
               .agg(pairs=("category", "size"),
                    with_explicit_days=("days_are_explicit", "sum"),
                    median_stay_days=("stay_days", "median"))
               .reset_index())
    summary["share_of_pairs"] = (summary["pairs"] / total * 100).round(2)
    for ladder_name, ladder in ACCESS_LADDERS.items():
        summary[f"credit_{ladder_name}"] = summary["category"].map(ladder)
    return summary.sort_values("pairs", ascending=False).reset_index(drop=True)
