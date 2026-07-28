"""Build the destination feature table: load, patch, impute, transform, scale.

The output is one row per destination in the access matrix, carrying:
  * raw indicator values and the vintage year of each
  * a per-cell provenance label (`observed`, `manual`, `imputed:<group>`)
  * winsorized, direction-corrected, min-max-scaled versions of each indicator
  * a score for each of the six pillars

Everything downstream consumes this table and nothing else, so the seam between
"what the world is like" and "how we chose to score it" stays visible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (INDICATOR_BY_KEY, INDICATORS, MANUAL, PILLARS, RAW,
                     VINTAGE_FLOOR, VINTAGE_FLOOR_EXEMPT, WINSOR_LIMITS)

MANUAL_PATCH_PATH = MANUAL / "manual_overrides.csv"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _load_worldbank(key: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / f"wb_{key}.csv")
    return df[["iso3", "value", "year"]].rename(columns={"value": key, "year": f"{key}_year"})


def _load_owid(key: str, code: str) -> pd.DataFrame:
    """OWID grapher CSVs are long (entity, code, year, value); take each
    country's most recent observation."""
    fname = {"rule_of_law_vdem__estimate_best": "owid_rule_of_law.csv",
             "electdem_vdem__estimate_best": "owid_electoral_democracy.csv"}[code]
    df = pd.read_csv(RAW / fname)
    df = df.rename(columns={"code": "iso3", code: key})
    df = df.dropna(subset=["iso3", key]).sort_values("year")
    latest = df.groupby("iso3", as_index=False).last()
    return latest[["iso3", key, "year"]].rename(columns={"year": f"{key}_year"})


def _load_hdi() -> pd.DataFrame:
    df = pd.read_csv(RAW / "undp_hdi.csv", encoding="latin-1")
    hdi_cols = sorted([c for c in df.columns if c.startswith("hdi_") and c[4:].isdigit()],
                      key=lambda c: int(c[4:]), reverse=True)
    melted = df.melt(id_vars=["iso3"], value_vars=hdi_cols, var_name="col", value_name="hdi")
    melted["year"] = melted["col"].str[4:].astype(int)
    melted = melted.dropna(subset=["hdi"]).sort_values("year")
    latest = melted.groupby("iso3", as_index=False).last()
    return latest[["iso3", "hdi", "year"]].rename(columns={"year": "hdi_year"})


def load_country_meta() -> pd.DataFrame:
    wb = pd.read_csv(RAW / "wb_country_meta.csv")[["iso3", "region", "income_group"]]
    ref = pd.read_csv(RAW / "country_reference.csv")
    return ref.merge(wb, on="iso3", how="outer")


# ---------------------------------------------------------------------------
# Manual patches
# ---------------------------------------------------------------------------
def load_manual_patches() -> pd.DataFrame:
    """Hand-sourced values for jurisdictions the multilateral agencies do not
    report as separate economies. Kept in a CSV rather than in code so that
    every hand-entered number carries a citation column and can be diffed.

    Two mechanisms: an explicit `value`, or a `proxy_iso3` naming a country to
    copy from. The proxy exists because for some entries the honest answer is
    not "we estimate X" but "administratively, this *is* that place" -- Vatican
    City's price level is Italy's, Liechtenstein's air connectivity is
    Switzerland's, because there is no separate thing to measure.
    """
    columns = ["iso3", "indicator", "value", "year", "proxy_iso3", "source"]
    if not MANUAL_PATCH_PATH.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(MANUAL_PATCH_PATH, comment="#")


def _apply_manual(wide: pd.DataFrame, provenance: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Fill only genuinely-missing cells. A real observation always wins over a
    hand-entered one, so the patch file can be over-inclusive without silently
    overriding the agencies."""
    patches = load_manual_patches()
    applied = 0
    for row in patches.itertuples():
        if row.iso3 not in wide.index or row.indicator not in wide.columns:
            continue
        if pd.notna(wide.at[row.iso3, row.indicator]):
            continue

        proxy = getattr(row, "proxy_iso3", None)
        if pd.notna(proxy):
            if proxy not in wide.index or pd.isna(wide.at[proxy, row.indicator]):
                continue
            value = wide.at[proxy, row.indicator]
            label = f"proxy:{proxy}"
        else:
            if pd.isna(row.value):
                continue
            value = row.value
            label = "manual"

        wide.at[row.iso3, row.indicator] = value
        year_col = f"{row.indicator}_year"
        if year_col in wide.columns and pd.notna(row.year):
            wide.at[row.iso3, year_col] = row.year
        provenance.at[row.iso3, row.indicator] = label
        applied += 1
    return wide, applied


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def build_raw_features(destinations: pd.Index) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assemble raw indicator values for every destination, plus a same-shaped
    provenance frame recording where each cell came from."""
    wide = pd.DataFrame(index=pd.Index(destinations, name="iso3"))

    for ind in INDICATORS:
        if ind.source == "worldbank":
            part = _load_worldbank(ind.key)
        elif ind.source == "owid":
            part = _load_owid(ind.key, ind.code)
        elif ind.source == "undp":
            part = _load_hdi()
        elif ind.source == "derived":
            continue
        else:
            raise ValueError(f"unknown source {ind.source!r} for {ind.key}")
        wide = wide.join(part.set_index("iso3"), how="left")

    # Support series and the indicators derived from them.
    gdp_usd = _load_worldbank("gdp_total_usd")
    wide = wide.join(gdp_usd.set_index("iso3"), how="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        wide["price_level"] = wide["gdp_total_usd"] / wide["gdp_total_ppp"]
    wide["price_level_year"] = wide[["gdp_total_usd_year", "gdp_total_ppp_year"]].min(axis=1)

    meta = load_country_meta().set_index("iso3")
    wide = wide.join(meta, how="left")

    keys = [ind.key for ind in INDICATORS]
    provenance = pd.DataFrame("observed", index=wide.index, columns=keys)
    provenance = provenance.mask(wide[keys].isna(), "missing")

    # Stale observations are not observations. World Bank carries a country's
    # last reported figure forward indefinitely, so without this a 1994
    # tertiary-enrollment number would sit next to a 2025 GDP number and be
    # treated as equally current.
    for ind in INDICATORS:
        year_col = f"{ind.key}_year"
        if year_col not in wide.columns or ind.key in VINTAGE_FLOOR_EXEMPT:
            continue
        stale = wide[year_col].notna() & (wide[year_col] < VINTAGE_FLOOR)
        provenance.loc[stale, ind.key] = "stale"
        wide.loc[stale, ind.key] = np.nan

    wide, n_manual = _apply_manual(wide, provenance)
    return wide, provenance


def impute(wide: pd.DataFrame, provenance: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hot-deck from the narrowest available peer group.

    Order is income group -> World Bank region -> UN subregion -> global median.
    A missing microstate looks far more like other high-income microstates than
    like the world median, so imputing from the narrowest group that has data
    is both less biased and easier to defend than a single global fallback.
    """
    wide = wide.copy()
    for ind in INDICATORS:
        col = ind.key
        for group, label in (("income_group", "income"), ("region", "region"),
                             ("un_subregion", "subregion")):
            if group not in wide.columns:
                continue
            filler = wide.groupby(group)[col].transform("median")
            fill_mask = wide[col].isna() & filler.notna()
            provenance.loc[fill_mask, col] = f"imputed:{label}"
            wide.loc[fill_mask, col] = filler[fill_mask]
        fill_mask = wide[col].isna()
        provenance.loc[fill_mask, col] = "imputed:global"
        wide[col] = wide[col].fillna(wide[col].median())
    return wide, provenance


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _winsorized_minmax(series: pd.Series) -> pd.Series:
    lo, hi = series.quantile(WINSOR_LIMITS[0]), series.quantile(WINSOR_LIMITS[1])
    clipped = series.clip(lo, hi)
    span = clipped.max() - clipped.min()
    if span == 0:
        return pd.Series(0.5, index=series.index)
    return (clipped - clipped.min()) / span


def normalize(wide: pd.DataFrame, method: str = "winsor_minmax") -> pd.DataFrame:
    """Transform each indicator onto a common [0, 1] scale where 1 is always
    "better for a traveler".

    Money- and count-denominated indicators span five to nine orders of
    magnitude, so they are logged first: without it the composite would be a
    three-country index about the United States, China and India. Winsorizing
    at the 1st/99th percentile before scaling stops a single extreme (Monaco's
    GDP per capita) from compressing everyone else into the bottom of the range.

    `method="rank"` swaps min-max for a percentile rank and is used as a
    robustness check in `analysis/sensitivity.py`.
    """
    out = pd.DataFrame(index=wide.index)
    for ind in INDICATORS:
        values = wide[ind.key].astype(float)
        if ind.transform == "log":
            values = np.log(values.clip(lower=values[values > 0].min() * 1e-3 if (values > 0).any() else 1))
        if ind.direction < 0:
            values = -values
        if method == "rank":
            scaled = values.rank(pct=True)
        elif method == "zscore":
            std = values.std(ddof=0)
            scaled = (values - values.mean()) / std if std else pd.Series(0.0, index=values.index)
            scaled = (scaled.clip(-3, 3) + 3) / 6
        else:
            scaled = _winsorized_minmax(values)
        out[f"n_{ind.key}"] = scaled
    return out


def pillar_scores(normalized: pd.DataFrame) -> pd.DataFrame:
    """Each pillar is the unweighted mean of its member indicators.

    Weighting happens once, at the pillar level, where it is a small enough set
    of numbers to argue about honestly. Indicators inside a pillar are treated
    as interchangeable measurements of the same latent thing.
    """
    out = pd.DataFrame(index=normalized.index)
    for pillar in PILLARS:
        cols = [f"n_{ind.key}" for ind in INDICATORS if ind.pillar == pillar]
        out[f"p_{pillar}"] = normalized[cols].mean(axis=1)
    return out


def build_features(destinations: pd.Index, norm_method: str = "winsor_minmax"):
    """Full pipeline: raw -> patched -> imputed -> normalized -> pillars."""
    wide, provenance = build_raw_features(destinations)
    wide, provenance = impute(wide, provenance)
    normalized = normalize(wide, method=norm_method)
    pillars = pillar_scores(normalized)
    features = wide.join(normalized).join(pillars)
    return features, provenance


def provenance_summary(provenance: pd.DataFrame) -> pd.DataFrame:
    """Share of cells by origin, per indicator -- printed in the README and
    shown in the article so the reader knows which pillars rest on real data."""
    rows = []
    for col in provenance.columns:
        counts = provenance[col].value_counts()
        total = counts.sum()
        rows.append({
            "indicator": col,
            "pillar": INDICATOR_BY_KEY[col].pillar,
            "observed": int(counts.get("observed", 0)),
            "manual": int(counts.get("manual", 0)),
            "proxied": int(sum(v for k, v in counts.items() if str(k).startswith("proxy"))),
            "imputed": int(sum(v for k, v in counts.items() if str(k).startswith("imputed"))),
            "observed_pct": round(counts.get("observed", 0) / total * 100, 1),
        })
    return pd.DataFrame(rows).sort_values("observed_pct")
