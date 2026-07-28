"""
Adjusted Henley Passport Index
===============================
The stock Henley Passport Index scores a passport by *counting* destinations
reachable without a prior visa -- Kiribati and the United States are both
worth exactly 1 point. This script reweights each destination by a composite
"material power & opportunity" score built from its economy and human
development, so that access to large/wealthy/high-opportunity destinations
counts for more than access to small/low-income ones.

Data sources (pulled 2026-07-13, refreshed 2026-07-13, see README.md for methodology notes):

1. Passport access matrix (199 passports x 199 destinations, Feb-2026 update)
   https://raw.githubusercontent.com/imorte/passport-index-data/main/passport-index-matrix-iso3.csv
   Successor to the archived ilyankou/passport-index-dataset; same schema,
   same visa-free/visa-on-arrival/eTA/e-Visa/visa-required categories that
   Henley & Partners itself uses (Henley's own IATA-licensed data is not
   redistributable, so this open, identically-coded dataset is the standard
   public proxy used by researchers).

2. GDP per capita, PPP (current international $) -- World Bank WDI
   https://api.worldbank.org/v2/en/indicator/NY.GDP.PCAP.PP.CD?downloadformat=csv

3. GDP, PPP (current international $) -- World Bank WDI
   https://api.worldbank.org/v2/en/indicator/NY.GDP.MKTP.PP.CD?downloadformat=csv

4. World Bank country Region / IncomeGroup metadata (for imputing the small
   number of destinations World Bank doesn't cover, e.g. Taiwan)
   bundled in the same WDI CSV download as file 2/3.

5. Human Development Index (HDI), 2025 report (data through 2023)
   https://hdr.undp.org/sites/default/files/2025_HDR/HDR25_Composite_indices_complete_time_series.csv

6. Population, total -- World Bank WDI
   https://api.worldbank.org/v2/en/indicator/SP.POP.TOTL?downloadformat=csv

7. International tourism, number of arrivals -- World Bank WDI
   https://api.worldbank.org/v2/en/indicator/ST.INT.ARVL?downloadformat=csv
   Reporting lags: most countries' latest available year is 2019 or 2020
   (pandemic-era dip), which is a real limitation -- treated here as a
   structural/relative signal of tourism draw, not a current-year figure.

8. Rule of law (V-Dem "Estimate, best", 0-1 scale), via Our World in Data
   https://ourworldindata.org/grapher/rule-of-law-index.csv?csvType=full&useColumnShortNames=true
   NOTE: the World Bank's own Worldwide Governance Indicators were originally
   tried for this (via api.worldbank.org/v2/en/indicator/PV.EST and RL.EST),
   but that archive endpoint returned internally inconsistent scales for a
   subset of countries (values like 23.7 or -46.1 mixed in with the correct
   -2.5..2.5 "Estimate" scale for others) -- a real data-quality bug in that
   specific archive mirror, not a formatting issue. Swapped to OWID's clean,
   V-Dem-sourced Rule of Law series instead. "Political stability" as a
   second, separate safety dimension was dropped rather than sourced from
   the same unreliable archive.

Run:
    python adjusted_henley_index.py
Outputs land in ./output/ (CSVs + PNG charts).
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Palette (validated categorical/sequential/diverging set; see dataviz skill)
# ---------------------------------------------------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"
RED = "#e34948"
AQUA = "#1baf7a"
GRAY_MID = "#f0efec"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

sns.set_theme(style="white", rc={
    "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK_SECONDARY,
    "text.color": INK,
    "xtick.color": INK_SECONDARY,
    "ytick.color": INK_SECONDARY,
    "grid.color": GRID,
    "font.family": "sans-serif",
})

# ---------------------------------------------------------------------------
# 1. Passport access matrix -> tidy (passport_iso3, destination_iso3, access)
# ---------------------------------------------------------------------------
# Henley's own scoring rule: a destination scores 1 (frictionless) if the
# holder can enter with *no prior visa*, i.e. visa-free (incl. numeric day
# limits), visa-on-arrival, or an eTA. An e-Visa or "visa required" scores 0,
# because both require government approval before departure.
FRICTIONLESS_TOKENS = {"visa free", "visa on arrival", "eta"}


def load_access_matrix() -> pd.DataFrame:
    mat = pd.read_csv(DATA / "passport_index_matrix_iso3.csv", index_col="Passport")
    long = mat.stack().rename("requirement").rename_axis(["passport", "destination"]).reset_index()
    long = long[long["passport"] != long["destination"]]

    def is_frictionless(val: str) -> bool:
        v = str(val).strip().lower()
        if v in FRICTIONLESS_TOKENS:
            return True
        return bool(re.fullmatch(r"\d+", v))  # numeric visa-free day count

    long["access"] = long["requirement"].map(is_frictionless)
    return long


# ---------------------------------------------------------------------------
# 2. World Bank indicator loader (wide CSV -> latest non-null value/country)
# ---------------------------------------------------------------------------
def load_wb_indicator(path: Path, value_name: str) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=4)
    year_cols = [c for c in df.columns if re.fullmatch(r"\d{4}", c)]
    year_cols_sorted = sorted(year_cols, key=int, reverse=True)

    def latest(row):
        for y in year_cols_sorted:
            if pd.notna(row[y]):
                return row[y]
        return np.nan

    df[value_name] = df.apply(latest, axis=1)
    return df[["Country Code", value_name]].rename(columns={"Country Code": "iso3"})


# World Bank/UNDP/OWID don't report these as separate economies for every
# field. Values are hand-sourced (IMF WEO Apr-2026 / CIA World Factbook for
# GDP and population; UNDP-methodology and V-Dem-comparable estimates for
# HDI and rule of law) since these jurisdictions are notable enough that
# group-median imputation would materially misstate them (e.g. Taiwan,
# Monaco, and Liechtenstein are all high-income, not "median-income"). Most
# of these entries actually have real data for most fields already (e.g.
# World Bank reports population for all but Taiwan/Vatican) -- listing every
# field for all eight keeps the table easy to audit; apply_manual_overrides
# only ever fills a cell that's genuinely missing, so a real data point
# always wins over the value here.
MANUAL_OVERRIDES = {
    #        gdp_pc_ppp   gdp_total_ppp   hdi     population   tourist_arrivals  rule_of_law
    "TWN": (76_858,       1.87e12,        0.911,  23_400_000,  11_800_000,       0.85),  # Taiwan
    "LIE": (139_100,      6.7e9,          0.938,  40_000,      60_000,           0.95),  # Liechtenstein
    "MCO": (234_300,      8.7e9,          0.950,  39_000,      300_000,          0.90),  # Monaco
    "CUB": (12_300,       1.37e11,        0.764,  11_000_000,  2_400_000,        0.35),  # Cuba
    "PRK": (1_700,        4.0e10,         0.550,  26_000_000,  10_000,           0.15),  # North Korea
    "VAT": (110_000,      1.5e9,          0.910,  880,         6_000_000,        0.85),  # Vatican City (proxy: Italy-level)
    "XKX": (17_864,       2.85e10,        0.760,  1_600_000,   250_000,          0.55),  # Kosovo
    "MAC": (126_960,      8.72e10,        0.950,  704_000,     28_000_000,       0.75),  # Macao SAR
}
MANUAL_OVERRIDE_FIELDS = ["gdp_pc_ppp", "gdp_total_ppp", "hdi", "population", "tourist_arrivals", "rule_of_law"]


def apply_manual_overrides(w: pd.DataFrame) -> pd.DataFrame:
    w = w.set_index("iso3")
    for iso3, values in MANUAL_OVERRIDES.items():
        if iso3 not in w.index:
            continue
        for field, value in zip(MANUAL_OVERRIDE_FIELDS, values):
            if pd.isna(w.loc[iso3, field]):
                w.loc[iso3, field] = value
    return w.reset_index()


def load_wb_metadata() -> pd.DataFrame:
    meta = pd.read_csv(DATA / "wb_country_metadata.csv")
    meta = meta.rename(columns={"Country Code": "iso3", "Region": "region", "IncomeGroup": "income_group"})
    return meta[meta["region"].notna() & (meta["region"] != "")][["iso3", "region", "income_group"]]


# ---------------------------------------------------------------------------
# 3. UNDP HDI loader (latest non-null hdi_YYYY per country)
# ---------------------------------------------------------------------------
def load_hdi() -> pd.DataFrame:
    df = pd.read_csv(DATA / "undp_hdi.csv", encoding="latin-1")
    hdi_cols = [c for c in df.columns if re.fullmatch(r"hdi_\d{4}", c)]
    hdi_cols_sorted = sorted(hdi_cols, key=lambda c: int(c.split("_")[1]), reverse=True)

    def latest(row):
        for c in hdi_cols_sorted:
            if pd.notna(row[c]):
                return row[c]
        return np.nan

    df = df.copy()
    df["hdi"] = df.apply(latest, axis=1)
    return df[["iso3", "hdi"]]


def load_rule_of_law() -> pd.DataFrame:
    """V-Dem 'Rule of law, estimate (best)' via Our World in Data, 0-1 scale.
    Long-format (entity, code, year, value) -- take each country's latest year."""
    df = pd.read_csv(DATA / "owid_rule_of_law.csv")
    df = df.rename(columns={"code": "iso3", "rule_of_law_vdem__estimate_best": "rule_of_law"})
    df = df.dropna(subset=["iso3", "rule_of_law"]).sort_values("year")
    return df.groupby("iso3", as_index=False).last()[["iso3", "rule_of_law"]]


# ---------------------------------------------------------------------------
# 4. Build the destination weight table
# ---------------------------------------------------------------------------
def build_destination_weights(destinations: pd.Index) -> pd.DataFrame:
    gdp_pc = load_wb_indicator(DATA / "wb_gdp_per_capita_ppp.csv", "gdp_pc_ppp")
    gdp_tot = load_wb_indicator(DATA / "wb_gdp_total_ppp.csv", "gdp_total_ppp")
    population = load_wb_indicator(DATA / "wb_population.csv", "population")
    tourist_arrivals = load_wb_indicator(DATA / "wb_tourist_arrivals.csv", "tourist_arrivals")
    hdi = load_hdi()
    rule_of_law = load_rule_of_law()
    meta = load_wb_metadata()

    w = pd.DataFrame({"iso3": destinations})
    w = w.merge(gdp_pc, on="iso3", how="left")
    w = w.merge(gdp_tot, on="iso3", how="left")
    w = w.merge(population, on="iso3", how="left")
    w = w.merge(tourist_arrivals, on="iso3", how="left")
    w = w.merge(hdi, on="iso3", how="left")
    w = w.merge(rule_of_law, on="iso3", how="left")
    w = w.merge(meta, on="iso3", how="left")
    w = apply_manual_overrides(w)

    # A handful of passport-index territories aren't in World Bank/UNDP/OWID
    # as separate economies (e.g. Taiwan, Kosovo edge cases, some
    # microstates), or are missing just one field (e.g. many small countries
    # don't report tourist arrivals). Impute whatever's still missing from
    # the income-group median, falling back to the region median, falling
    # back to the global median.
    for col in ["gdp_pc_ppp", "gdp_total_ppp", "hdi", "population", "tourist_arrivals", "rule_of_law"]:
        grp_income = w.groupby("income_group")[col].transform("median")
        grp_region = w.groupby("region")[col].transform("median")
        global_med = w[col].median()
        w[col] = w[col].fillna(grp_income).fillna(grp_region).fillna(global_med)

    return w


# ---------------------------------------------------------------------------
# 5. Composite weight -- six dimensions, each min-max normalized to [0,1]
#    (GDP per capita / GDP total / population / tourist arrivals are
#    log-transformed first, since all four are extremely right-skewed --
#    without the log, the composite would be almost entirely about the US,
#    China, and India), then combined as a weighted sum:
#
#      0.22 * GDP per capita, PPP      (individual opportunity: wages,
#                                        purchasing power, standard of living)
#    + 0.18 * GDP total, PPP           (market size / economic power --
#                                        business, investment, employment
#                                        opportunity at the country level)
#    + 0.15 * HDI                      (human development: health,
#                                        education, quality of institutions)
#    + 0.10 * Population               (demographic reach/scale, independent
#                                        of wealth -- a large, poorer market
#                                        still means access to more people,
#                                        culture, and business contacts)
#    + 0.15 * Tourist arrivals         (global draw / "the value of visiting"
#                                        -- captures destinations that rank
#                                        low on GDP per capita or total but
#                                        are nonetheless major, sought-after
#                                        destinations, e.g. Thailand, Morocco)
#    + 0.20 * Rule of law              (safety & institutional reliability --
#                                        access to a destination is only
#                                        worth as much as your ability to
#                                        safely and predictably use it)
#
#    Note: GDP total and population are correlated by construction (GDP
#    total is roughly GDP per capita x population), so this isn't six fully
#    independent axes -- it's a deliberate choice, common in composite
#    national-power indices, to let both "wealth x scale" and "raw
#    demographic reach" register as separate signals rather than collapsing
#    them into one.
#
#    The composite is then mean-normalized so the average destination
#    carries weight 1.0 (keeps scores on a familiar scale, comparable in
#    magnitude to the original equal-weight counts).
# ---------------------------------------------------------------------------
COMPOSITE_WEIGHTS = {
    "n_gdp_pc": 0.22,
    "n_gdp_total": 0.18,
    "n_hdi": 0.15,
    "n_population": 0.10,
    "n_tourist_arrivals": 0.15,
    "n_rule_of_law": 0.20,
}


def compute_weights(w: pd.DataFrame) -> pd.DataFrame:
    w = w.copy()
    w["log_gdp_pc"] = np.log(w["gdp_pc_ppp"])
    w["log_gdp_total"] = np.log(w["gdp_total_ppp"])
    w["log_population"] = np.log(w["population"])
    w["log_tourist_arrivals"] = np.log(w["tourist_arrivals"].clip(lower=1))

    def minmax(s):
        return (s - s.min()) / (s.max() - s.min())

    w["n_gdp_pc"] = minmax(w["log_gdp_pc"])
    w["n_gdp_total"] = minmax(w["log_gdp_total"])
    w["n_hdi"] = minmax(w["hdi"])
    w["n_population"] = minmax(w["log_population"])
    w["n_tourist_arrivals"] = minmax(w["log_tourist_arrivals"])
    w["n_rule_of_law"] = minmax(w["rule_of_law"])

    w["composite_raw"] = sum(w[col] * weight for col, weight in COMPOSITE_WEIGHTS.items())
    w["weight"] = w["composite_raw"] / w["composite_raw"].mean()
    return w


# ---------------------------------------------------------------------------
# 6. Score every passport, original (count) and adjusted (weighted sum)
# ---------------------------------------------------------------------------
def score_passports(access_long: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    merged = access_long.merge(
        weights[["iso3", "weight"]], left_on="destination", right_on="iso3", how="left"
    )
    granted = merged[merged["access"]]

    scores = granted.groupby("passport").agg(
        original_score=("access", "size"),
        adjusted_score=("weight", "sum"),
    ).reset_index()

    # Henley's own convention: passports with the same score share the same
    # rank, and the next rank skips ahead by the tie size (e.g. a 3-way tie
    # for 1st is followed by 4th, not 2nd) -- pandas' method="min" does
    # exactly this. For the adjusted score, ties are evaluated at the same
    # one-decimal precision the score is actually reported at, so two
    # passports both showing "170.4" always tie in rank instead of being
    # silently split by float precision beyond what's displayed.
    scores["adjusted_score"] = scores["adjusted_score"].round(1)
    scores["original_rank"] = scores["original_score"].rank(ascending=False, method="min").astype(int)
    scores["adjusted_rank"] = scores["adjusted_score"].rank(ascending=False, method="min").astype(int)
    scores["rank_change"] = scores["original_rank"] - scores["adjusted_rank"]

    max_possible = weights["weight"].sum()
    scores["adjusted_pct_of_max"] = (scores["adjusted_score"] / max_possible * 100).round(1)

    return scores.sort_values("adjusted_rank")


def load_iso3_to_name() -> dict:
    iso3_header = pd.read_csv(DATA / "passport_index_matrix_iso3.csv", nrows=0).columns[1:]
    name_header = pd.read_csv(DATA / "passport_index_matrix_names.csv", nrows=0).columns[1:]
    return dict(zip(iso3_header, name_header))


# ---------------------------------------------------------------------------
# 7. Charts
# ---------------------------------------------------------------------------
def make_charts(scores: pd.DataFrame, weights: pd.DataFrame):
    names = load_iso3_to_name()
    scores = scores.copy()
    scores["name"] = scores["passport"].map(names)
    weights = weights.copy()
    weights["name"] = weights["iso3"].map(names)

    _chart_rank_movers(scores)
    _chart_rank_scatter(scores)
    _chart_top20_comparison(scores)
    _chart_weight_distribution(weights)
    _chart_interactive_map(scores, weights)


def _savefig(fig, filename):
    fig.savefig(OUT / filename, dpi=200, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def _chart_rank_movers(scores: pd.DataFrame, n=15):
    top_up = scores.sort_values("rank_change", ascending=False).head(n)
    top_down = scores.sort_values("rank_change").head(n)
    combined = pd.concat([top_up, top_down]).sort_values("rank_change")
    combined = combined.drop_duplicates(subset="passport")

    fig, ax = plt.subplots(figsize=(9, 9))
    colors = [BLUE if v >= 0 else RED for v in combined["rank_change"]]
    ax.barh(combined["name"], combined["rank_change"], color=colors, height=0.65)
    ax.axvline(0, color=INK_MUTED, linewidth=1)
    ax.set_xlabel("Rank change (original rank − adjusted rank; positive = moves up)")
    ax.set_title("Who gains and who falls under an opportunity-weighted index", loc="left",
                  fontsize=13, fontweight="bold", color=INK)
    ax.set_ylabel("")
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _savefig(fig, "01_rank_movers.png")


def _chart_rank_scatter(scores: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(scores["original_rank"], scores["adjusted_rank"], s=36,
               color=BLUE, alpha=0.75, edgecolor=SURFACE, linewidth=0.5)

    lims = [1, max(scores["original_rank"].max(), scores["adjusted_rank"].max())]
    ax.plot(lims, lims, color=INK_MUTED, linewidth=1, linestyle="--", zorder=0)

    highlight = pd.concat([
        scores.nsmallest(3, "adjusted_rank"),
        scores.reindex(scores["rank_change"].abs().sort_values(ascending=False).index).head(8),
    ]).drop_duplicates(subset="passport").sort_values("adjusted_rank")
    offsets = [(8, 6), (8, -14), (8, 18), (8, -22), (8, 28), (8, -30)]
    for i, (_, row) in enumerate(highlight.iterrows()):
        dx, dy = offsets[i % len(offsets)]
        ax.annotate(row["name"], (row["original_rank"], row["adjusted_rank"]),
                    fontsize=8, color=INK_SECONDARY, xytext=(dx, dy), textcoords="offset points",
                    arrowprops=dict(arrowstyle="-", color=INK_MUTED, linewidth=0.6, shrinkA=3, shrinkB=3))

    ax.set_xlabel("Original Henley-style rank (equal-weight count)")
    ax.set_ylabel("Adjusted rank (opportunity-weighted)")
    ax.set_title("Original vs. opportunity-weighted passport rank", loc="left",
                  fontsize=13, fontweight="bold", color=INK)
    ax.invert_yaxis()
    ax.invert_xaxis()
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _savefig(fig, "02_rank_scatter.png")


def _chart_top20_comparison(scores: pd.DataFrame, n=20):
    top = scores.sort_values("adjusted_rank").head(n).sort_values("adjusted_score")
    fig, ax = plt.subplots(figsize=(9.5, 9))
    ax.barh(top["name"], top["adjusted_score"], color=BLUE, height=0.6, label="Adjusted (weighted)")
    ax.scatter(top["original_score"], top["name"], color=RED, zorder=3, s=40,
               label="Original (equal-weight count)")
    ax.set_xlabel("Score (destinations reachable, weighted vs. raw count)")
    ax.set_title("Top 20 passports: adjusted score vs. original count", loc="left",
                  fontsize=13, fontweight="bold", color=INK)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _savefig(fig, "03_top20_comparison.png")


def _chart_weight_distribution(weights: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    sns.histplot(weights["weight"], bins=30, color=BLUE, ax=ax, edgecolor=SURFACE)
    ax.axvline(1.0, color=INK_MUTED, linewidth=1, linestyle="--")
    ax.text(1.02, ax.get_ylim()[1] * 0.95, "mean weight = 1.0", color=INK_SECONDARY, fontsize=9)

    callouts = weights.nlargest(2, "weight").to_dict("records") + weights.nsmallest(2, "weight").to_dict("records")
    heights = [0.95, 0.75, 0.95, 0.75]
    for row, h in zip(callouts, heights):
        ax.axvline(row["weight"], color=RED, linewidth=0.8, alpha=0.5)
        ax.annotate(row["name"], (row["weight"], ax.get_ylim()[1] * h), rotation=90,
                    fontsize=8, color=INK_SECONDARY, ha="right", va="top")

    ax.set_xlabel("Destination weight (composite opportunity/power multiplier)")
    ax.set_ylabel("Number of destinations")
    ax.set_title("How destination weights are distributed", loc="left",
                  fontsize=13, fontweight="bold", color=INK)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _savefig(fig, "04_weight_distribution.png")


# Centroids for jurisdictions too small to render as filled polygons at 110m
# map resolution (used as dot markers instead). Coordinates are (lon, lat).
MAP_MARKER_CENTROIDS = {
    "AND": (1.52, 42.51), "ATG": (-61.80, 17.06), "BHR": (50.55, 26.03), "BRB": (-59.60, 13.19),
    "COM": (43.33, -11.70), "CPV": (-23.60, 15.12), "DMA": (-61.37, 15.41), "FSM": (150.55, 6.92),
    "GRD": (-61.68, 12.11), "HKG": (114.17, 22.28), "KIR": (173.00, 1.35), "KNA": (-62.75, 17.30),
    "LCA": (-60.98, 13.91), "LIE": (9.53, 47.14), "MAC": (113.55, 22.20), "MCO": (7.42, 43.73),
    "MDV": (73.50, 3.20), "MHL": (171.18, 7.10), "MLT": (14.51, 35.90), "MUS": (57.55, -20.35),
    "NRU": (166.93, -0.52), "PLW": (134.58, 7.50), "SGP": (103.80, 1.35), "SMR": (12.46, 43.94),
    "STP": (6.60, 0.19), "SYC": (55.45, -4.68), "TON": (-175.20, -21.20), "TUV": (179.20, -8.52),
    "VAT": (12.45, 41.90), "VCT": (-61.20, 13.25), "WSM": (-172.10, -13.75),
}
MAP_PROJECTION_W, MAP_PROJECTION_H = 1000, 500  # must match data/world_paths.js


def _project_lonlat(lon, lat):
    x = (lon + 180) * (MAP_PROJECTION_W / 360)
    y = (90 - lat) * (MAP_PROJECTION_H / 180)
    return round(x, 2), round(y, 2)


def _chart_interactive_map(scores: pd.DataFrame, weights: pd.DataFrame):
    """Builds a dependency-free interactive choropleth: real geometry (Natural
    Earth 110m) is baked into static SVG <path> data at data/world_paths.js,
    and this function only injects the (small) per-country stats plus a
    vanilla-JS interaction layer -- no charting library needed at runtime.
    This keeps the output a few hundred KB instead of several MB, which
    matters when the file is embedded somewhere with a script-size-sensitive
    host (e.g. as a hosted artifact) rather than just opened locally.
    """
    merged = scores.merge(weights[["iso3", "weight"]], left_on="passport", right_on="iso3", how="left")
    merged = merged.dropna(subset=["weight"])
    names = load_iso3_to_name()
    merged["name"] = merged["passport"].map(names)

    country_data = {
        row.passport: {
            "name": row.name, "oRank": int(row.original_rank), "oScore": int(row.original_score),
            "aRank": int(row.adjusted_rank), "aScore": round(float(row.adjusted_score), 1),
            "delta": int(row.rank_change), "weight": round(float(row.weight), 3),
        }
        for row in merged.itertuples()
    }

    markers = {iso3: list(_project_lonlat(lon, lat)) for iso3, (lon, lat) in MAP_MARKER_CENTROIDS.items()}

    world_paths_js = (DATA / "world_paths.js").read_text()
    viewbox_match = re.search(r"const WORLD_VIEWBOX = '([^']+)';", world_paths_js)
    viewbox = viewbox_match.group(1)

    template = (Path(__file__).parent / "assets" / "map_template.html").read_text()
    html = (template
            .replace("__VIEWBOX__", viewbox)
            .replace("__WORLD_PATHS_JS__", world_paths_js)
            .replace("__MARKERS_JSON__", json.dumps(markers))
            .replace("__COUNTRY_DATA_JSON__", json.dumps(country_data)))

    (OUT / "05_passport_strength_map.html").write_text(html)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    access_long = load_access_matrix()
    destinations = pd.Index(access_long["destination"].unique(), name="iso3")

    weights = build_destination_weights(destinations)
    weights = compute_weights(weights)
    weights.to_csv(OUT / "destination_weights.csv", index=False)

    scores = score_passports(access_long, weights)
    scores.to_csv(OUT / "adjusted_passport_scores.csv", index=False)

    print(f"Destinations weighted: {len(weights)}")
    print(f"Passports scored:      {len(scores)}")
    print("\nTop 10 by adjusted score:")
    print(scores.head(10).to_string(index=False))
    print("\nBiggest rank gainers (adjusted vs original):")
    print(scores.sort_values("rank_change", ascending=False).head(10)
          [["passport", "original_rank", "adjusted_rank", "rank_change"]].to_string(index=False))
    print("\nBiggest rank losers (adjusted vs original):")
    print(scores.sort_values("rank_change").head(10)
          [["passport", "original_rank", "adjusted_rank", "rank_change"]].to_string(index=False))

    make_charts(scores, weights)


if __name__ == "__main__":
    main()
