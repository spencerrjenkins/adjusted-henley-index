"""The static figure suite.

Each function takes the pipeline's tables and renders one figure in both light
and dark modes. Form is chosen by the job the data has to do, per the ordering in
`choosing-a-form.md`: emphasis where one series is the point, sequential where
the job is magnitude, diverging only where there is a real zero to be above or
below, categorical only where the series themselves are the subject.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..config import FIGURES, PILLARS, PILLAR_LABELS
from . import theme
from .theme import MODES, Mode


def _pct(ax, axis="x"):
    fmt = lambda v, _: f"{v:g}%"
    (ax.xaxis if axis == "x" else ax.yaxis).set_major_formatter(plt.FuncFormatter(fmt))


# ---------------------------------------------------------------------------
# 1. Who moves when destinations stop being worth one point each
# ---------------------------------------------------------------------------
def fig_rank_movement(movement: pd.DataFrame, mode: Mode, n: int = 14) -> None:
    theme.apply(mode)
    movers = pd.concat([movement.nlargest(n, "total_move"),
                        movement.nsmallest(n, "total_move")]).drop_duplicates("passport")
    movers = movers.sort_values("total_move")

    fig, ax = plt.subplots(figsize=(9.5, 8.6))
    y = np.arange(len(movers))

    for yi, row in zip(y, movers.itertuples()):
        color = theme.diverging_color(mode, row.total_move, 30)
        ax.plot([row.baseline_rank, row.target_rank], [yi, yi],
                color=color, linewidth=2.0, solid_capstyle="round", zorder=2)
        ax.scatter(row.baseline_rank, yi, s=44, color=mode.deemphasis,
                   edgecolor=mode.surface, linewidth=2.0, zorder=3)
        ax.scatter(row.target_rank, yi, s=62, color=color,
                   edgecolor=mode.surface, linewidth=2.0, zorder=4)
        # The x-axis is inverted (rank 1 on the right), so the label goes on the
        # far side of whichever end of the dumbbell is the outer one.
        outer = max(row.baseline_rank, row.target_rank)
        ax.annotate(f"{row.total_move:+.1f}", (outer, yi), xytext=(-11, 0),
                    textcoords="offset points", ha="right", va="center",
                    fontsize=8.5, color=mode.ink_secondary)

    ax.set_yticks(y, movers["name"], fontsize=9)
    ax.invert_xaxis()
    ax.set_xlim(movers[["baseline_rank", "target_rank"]].to_numpy().max() + 22, -4)
    ax.set_xlabel("Expected position out of 199 (1 = strongest). Gray dot: Henley-rule count. "
                  "Colored dot: opportunity-weighted.")
    theme.frame(ax, mode, keep=("bottom",), grid_axis="x")
    theme.title(ax, mode, "Who gains and who falls when destinations stop being worth one point each",
                "Fractional ranks: a tied group sits at the average of the positions it actually "
                f"occupies, so neither index is flattered by its ties. Top {n} movers each way.")
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", markersize=7, color=mode.deemphasis,
               label="Henley-rule rank"),
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.diverging[2],
               label="Adjusted: moves up"),
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.diverging[0],
               label="Adjusted: moves down"),
    ], loc="lower left", labelcolor=mode.ink_secondary)
    theme.save(fig, "01_rank_movement", mode, FIGURES)


# ---------------------------------------------------------------------------
# 2. Do the index variants actually disagree?
# ---------------------------------------------------------------------------
def fig_index_agreement(agreement: pd.DataFrame, mode: Mode) -> None:
    theme.apply(mode)
    labels = {
        "henley": "Henley rule (count)", "graded_count": "Graded friction, flat weights",
        "binary_weighted": "Binary friction, weighted", "ahi_balanced": "AHI Balanced",
        "ahi_business": "AHI Business", "ahi_leisure": "AHI Leisure",
        "ahi_settlement": "AHI Settlement", "ahi_reach": "AHI Raw reach",
        "ahi_pca": "PCA weights", "ahi_entropy": "Entropy weights",
        "gdp_share": "Share of world GDP", "pop_share": "Share of world people",
        "ahi_gamma_flat": "Flat dispersion", "ahi_gamma_sharp": "Sharp dispersion",
        "ahi_gamma_extreme": "Extreme dispersion", "stay_days": "Permitted person-days",
    }
    order = [k for k in labels if k in agreement.index]
    matrix = agreement.loc[order, order].astype(float)

    fig, ax = plt.subplots(figsize=(9.6, 8.4))
    cmap = plt.matplotlib.colors.LinearSegmentedColormap.from_list("seq", mode.sequential)
    lo = float(np.nanmin(matrix.to_numpy()))
    im = ax.imshow(matrix, cmap=cmap, vmin=max(lo, 0.5), vmax=1.0)

    for i in range(len(order)):
        for j in range(len(order)):
            v = matrix.iloc[i, j]
            # Text on a sequential cell flips ink at the ramp midpoint so it
            # never sits dark-on-dark at the top of the scale.
            dark_cell = (v - max(lo, 0.5)) / (1 - max(lo, 0.5)) > 0.55
            ink = mode.surface if (dark_cell and mode.name == "light") else (
                mode.ink if dark_cell else mode.ink_secondary)
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7.4, color=ink)

    ax.set_xticks(range(len(order)), [labels[k] for k in order], rotation=45,
                  ha="right", fontsize=8.5)
    ax.set_yticks(range(len(order)), [labels[k] for k in order], fontsize=8.5)
    ax.tick_params(length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    theme.title(ax, mode, "Which modeling choices actually change the answer",
                "Kendall's tau-b between every pair of index variants. 1.00 = identical ordering; "
                "the low cells are where a choice mattered.")
    cbar = fig.colorbar(im, ax=ax, shrink=0.62, pad=0.02)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(length=0, labelcolor=mode.ink_secondary, labelsize=8)
    theme.save(fig, "02_index_agreement", mode, FIGURES)


# ---------------------------------------------------------------------------
# 3. How much rank does a passport really have?
# ---------------------------------------------------------------------------
def fig_monte_carlo(mc: pd.DataFrame, mode: Mode, n: int = 32) -> None:
    theme.apply(mode)
    top = mc.nsmallest(n, "rank_median").sort_values("rank_median", ascending=False)

    fig, ax = plt.subplots(figsize=(9, 9))
    y = np.arange(len(top))
    for yi, row in zip(y, top.itertuples()):
        ax.plot([row.rank_p05, row.rank_p95], [yi, yi], color=mode.sequential[2],
                linewidth=6, solid_capstyle="round", alpha=0.85, zorder=2)
        ax.scatter(row.rank_median, yi, s=48, color=mode.series[0],
                   edgecolor=mode.surface, linewidth=2.0, zorder=3)

    ax.set_yticks(y, top["name"], fontsize=9)
    ax.invert_xaxis()
    ax.set_xlabel("Expected position across 3,000 resampled pillar weightings")
    theme.frame(ax, mode, keep=("bottom",), grid_axis="x")
    theme.title(ax, mode, "A rank is an interval, not a number",
                "Dot: median position. Bar: 5th-95th percentile as the six pillar weights "
                "are resampled from a Dirichlet around the published lens.")
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.series[0],
               label="Median position"),
        Line2D([], [], linewidth=6, color=mode.sequential[2], label="90% of weightings"),
    ], loc="upper left", labelcolor=mode.ink_secondary)
    theme.save(fig, "03_monte_carlo_ranks", mode, FIGURES)


# ---------------------------------------------------------------------------
# 4. The friction ladder is the biggest lever
# ---------------------------------------------------------------------------
def fig_ladder(ladder: pd.DataFrame, names: dict, mode: Mode, n: int = 12) -> None:
    theme.apply(mode)
    data = ladder.copy()
    data["name"] = data["passport"].map(names)
    movers = data.nlargest(n, "rank_spread")

    fig, ax = plt.subplots(figsize=(8.6, 7.4))
    stages = ["rank_binary_henley", "rank_graded", "rank_strict"]
    stage_labels = ["Henley's binary\n(VOA and eTA count fully)",
                    "Graded friction\n(partial credit)",
                    "Strict\n(only true visa-free)"]
    x = np.arange(len(stages))

    endpoints = []
    for row in movers.itertuples():
        values = [getattr(row, s) for s in stages]
        drops = values[-1] - values[0]
        color = theme.diverging_color(mode, -drops, 20)
        ax.plot(x, values, color=color, linewidth=2.0, marker="o", markersize=6,
                markeredgecolor=mode.surface, markeredgewidth=2.0, alpha=0.9)
        endpoints.append((values[-1], row.name))

    # Passports landing on the same strict-ladder position would print their
    # names on top of each other -- Japan and South Korea both end at 35.5.
    # Walk the endpoints in order and push each label just far enough clear of
    # the previous one, with a leader line back to the mark it belongs to.
    span = max(e[0] for e in endpoints) - min(e[0] for e in endpoints)
    gap = max(span * 0.032, 1.5)
    last_label_y = float("-inf")
    for value, label in sorted(endpoints):
        label_y = max(value, last_label_y + gap)
        last_label_y = label_y
        ax.annotate(label, xy=(x[-1], value), xytext=(x[-1] + 0.10, label_y),
                    textcoords="data", va="center", ha="left", fontsize=8.5,
                    color=mode.ink_secondary, annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=mode.grid, linewidth=0.9,
                                    shrinkA=2, shrinkB=6))

    ax.set_xticks(x, stage_labels, fontsize=9)
    ax.set_xlim(-0.25, len(stages) - 0.28)
    ax.invert_yaxis()
    ax.set_ylabel("Expected position out of 199 (1 = strongest)")
    theme.frame(ax, mode, keep=("left",), grid_axis="y")
    theme.title(ax, mode, "How much of the top of the table is visa-on-arrival?",
                f"The {n} passports most sensitive to how entry regimes are scored, "
                "with destination weighting held fixed.")
    theme.save(fig, "04_ladder_sensitivity", mode, FIGURES)


# ---------------------------------------------------------------------------
# 5. The distribution of destination value
# ---------------------------------------------------------------------------
def fig_weight_distribution(weights: pd.DataFrame, mode: Mode) -> None:
    theme.apply(mode)
    fig, ax = plt.subplots(figsize=(9.4, 5.6))
    values = weights["balanced"]
    counts, bins, patches = ax.hist(values, bins=34, color=mode.sequential[3],
                                    edgecolor=mode.surface, linewidth=1.5)
    ax.axvline(1.0, color=mode.ink_muted, linewidth=1.5, linestyle=(0, (4, 3)), zorder=3)
    ax.annotate("average destination = 1.0", (1.0, counts.max() * 0.97),
                xytext=(8, 0), textcoords="offset points", fontsize=9,
                color=mode.ink_secondary, va="top")

    # Callouts are staggered in height and spread across the range: eight
    # markers at one height collide into an unreadable stripe (Germany, Ireland
    # and the United States sit within 0.02 of each other).
    named = weights.set_index("name")["balanced"]
    callouts = ["Burundi", "Nigeria", "India", "China", "United States", "Germany"]
    heights = [0.30, 0.46, 0.30, 0.46, 0.62, 0.30]
    for label, h in zip(callouts, heights):
        if label not in named.index:
            continue
        v = float(named[label])
        top = counts.max() * h
        ax.plot([v, v], [0, top], color=mode.series[1], linewidth=2.0, zorder=3)
        ax.annotate(label, (v, top), xytext=(0, 5), textcoords="offset points",
                    fontsize=8.5, color=mode.ink_secondary, ha="center", va="bottom")

    ax.set_xlabel("Destination weight under the Balanced lens (multiple of the average destination)")
    ax.set_ylabel("Destinations")
    theme.frame(ax, mode, keep=("bottom",), grid_axis="y")
    theme.title(ax, mode, "The world is less unequal as a set of destinations than as a set of economies",
                f"Averaging fifteen indicators into six pillars compresses the spread to "
                f"{values.max() / values.min():.1f}x from best to worst — far narrower than the "
                "underlying GDP gap.")
    theme.save(fig, "05_weight_distribution", mode, FIGURES)


# ---------------------------------------------------------------------------
# 6. What kind of world does each passport open?
# ---------------------------------------------------------------------------
def fig_pillar_profiles(attainment: pd.DataFrame, family: pd.DataFrame,
                        mode: Mode, picks: tuple[str, ...] = (
                            "SGP", "ARE", "JPN", "DEU", "USA", "GBR", "MYS", "CHN",
                            "RUS", "BRA", "ZAF", "IND", "NGA", "AFG")) -> None:
    """Diverging heatmap of each passport's tilt: where it reaches more or less
    of the world than its own average would suggest."""
    theme.apply(mode)
    data = attainment.set_index("passport").reindex(
        [p for p in picks if p in set(attainment["passport"])])
    labels = family.set_index("passport")["name"].reindex(data.index)
    tilt = data[[f"tilt_{p}" for p in PILLARS]]

    fig, ax = plt.subplots(figsize=(9.4, 6.8))
    span = float(np.abs(tilt.to_numpy()).max())
    cmap = plt.matplotlib.colors.LinearSegmentedColormap.from_list(
        "div", [mode.diverging[0], mode.diverging[1], mode.diverging[2]])
    im = ax.imshow(tilt, cmap=cmap, vmin=-span, vmax=span, aspect="auto")

    for i in range(len(data)):
        for j, pillar in enumerate(PILLARS):
            value = data.iloc[i][f"att_{pillar}"]
            delta = tilt.iloc[i, j]
            strong = abs(delta) / span > 0.55
            ink = mode.surface if (strong and mode.name == "light") else (
                mode.ink if strong else mode.ink_secondary)
            ax.text(j, i, f"{value:.0f}%", ha="center", va="center", fontsize=8.6, color=ink)

    ax.set_xticks(range(len(PILLARS)), [PILLAR_LABELS[p] for p in PILLARS], fontsize=9.5)
    ax.set_yticks(range(len(data)),
                  [f"{n}   ({v:.0f}% overall)" for n, v in zip(labels, data["att_overall"])],
                  fontsize=9)
    ax.tick_params(length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    theme.title(ax, mode, "Two passports of the same size can open different worlds",
                "Cell: share of the world's total value in that pillar the passport can reach. "
                "Color: how far that sits above (blue) or below (red) the passport's own average.")
    cbar = fig.colorbar(im, ax=ax, shrink=0.55, pad=0.02)
    cbar.set_label("percentage points vs. own average", color=mode.ink_secondary, fontsize=8.5)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(length=0, labelcolor=mode.ink_secondary, labelsize=8)
    theme.save(fig, "06_pillar_profiles", mode, FIGURES)


# ---------------------------------------------------------------------------
# 7. Reciprocity: where you can go vs who you let in
# ---------------------------------------------------------------------------
def fig_reciprocity(recip: pd.DataFrame, mode: Mode) -> None:
    theme.apply(mode)
    fig, ax = plt.subplots(figsize=(8.6, 8.2))

    lim = max(recip["reaches"].max(), recip["admits"].max()) * 1.06
    ax.plot([0, lim], [0, lim], color=mode.ink_muted, linewidth=1.5,
            linestyle=(0, (4, 3)), zorder=1)
    ax.annotate("perfect balance", (lim * 0.72, lim * 0.72), rotation=45,
                fontsize=8.5, color=mode.ink_muted, ha="center", va="bottom")

    ax.scatter(recip["admits"], recip["reaches"], s=34, color=mode.deemphasis,
               edgecolor=mode.surface, linewidth=1.5, zorder=2)

    highlight = pd.concat([recip.nlargest(6, "mobility_balance"),
                           recip.nsmallest(6, "mobility_balance")])
    for row in highlight.itertuples():
        color = theme.diverging_color(mode, row.mobility_balance, 100)
        ax.scatter(row.admits, row.reaches, s=76, color=color,
                   edgecolor=mode.surface, linewidth=2.0, zorder=3)
        ax.annotate(row.name, (row.admits, row.reaches), xytext=(9, 4),
                    textcoords="offset points", fontsize=8.5, color=mode.ink_secondary)

    ax.set_xlabel("Nationalities admitted without a prior visa")
    ax.set_ylabel("Destinations reachable without a prior visa")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    theme.frame(ax, mode, keep=("bottom", "left"), grid_axis="both")
    theme.title(ax, mode, "Almost nobody sits on the diagonal",
                "Above the line: you travel more freely than you admit. Below it: the reverse. "
                "The system's surpluses have to be somebody's deficits.")
    theme.save(fig, "07_reciprocity", mode, FIGURES)


# ---------------------------------------------------------------------------
# 8. Lorenz curves of mobility
# ---------------------------------------------------------------------------
def fig_lorenz(curves: dict[str, pd.DataFrame], ginis: dict[str, float], mode: Mode) -> None:
    theme.apply(mode)
    fig, ax = plt.subplots(figsize=(7.8, 7.4))
    ax.plot([0, 1], [0, 1], color=mode.ink_muted, linewidth=1.5,
            linestyle=(0, (4, 3)), zorder=1, label="Perfect equality")

    for i, (label, curve) in enumerate(curves.items()):
        ax.plot(curve["population_share"], curve["value_share"], color=mode.series[i],
                linewidth=2.0, zorder=2 + i,
                label=f"{label}  (Gini {ginis[label]:.2f})")

    ax.set_xlabel("Cumulative share of passports, weakest first")
    ax.set_ylabel("Cumulative share of total access")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    theme.frame(ax, mode, keep=("bottom", "left"), grid_axis="both")
    theme.title(ax, mode, "How unequally mobility is distributed",
                "The further a curve sags below the diagonal, the more concentrated that "
                "measure of access is among a few passports.")
    ax.legend(loc="upper left", labelcolor=mode.ink_secondary)
    theme.save(fig, "08_lorenz", mode, FIGURES)


# ---------------------------------------------------------------------------
# 9. Who over- and under-performs their own fundamentals
# ---------------------------------------------------------------------------
def fig_residuals(residuals: pd.DataFrame, r_squared: float, mode: Mode) -> None:
    theme.apply(mode)
    fig, ax = plt.subplots(figsize=(8.8, 7.6))

    lim = [min(residuals["predicted"].min(), residuals["actual"].min()) - 4,
           max(residuals["predicted"].max(), residuals["actual"].max()) + 4]
    ax.plot(lim, lim, color=mode.ink_muted, linewidth=1.5, linestyle=(0, (4, 3)), zorder=1)
    ax.scatter(residuals["predicted"], residuals["actual"], s=34, color=mode.deemphasis,
               edgecolor=mode.surface, linewidth=1.5, zorder=2)

    highlight = pd.concat([residuals.nlargest(7, "residual"), residuals.nsmallest(7, "residual")])
    for row in highlight.itertuples():
        color = theme.diverging_color(mode, row.residual, 20)
        ax.scatter(row.predicted, row.actual, s=76, color=color,
                   edgecolor=mode.surface, linewidth=2.0, zorder=3)
        ax.annotate(row.name, (row.predicted, row.actual), xytext=(9, 4),
                    textcoords="offset points", fontsize=8.5, color=mode.ink_secondary)

    ax.set_xlabel("Predicted access from the country's own wealth, development, size and institutions")
    ax.set_ylabel("Actual access (% of the theoretical maximum)")
    _pct(ax, "x"); _pct(ax, "y")
    theme.frame(ax, mode, keep=("bottom", "left"), grid_axis="both")
    theme.title(ax, mode, "Passport strength is mostly national development — and partly diplomacy",
                f"OLS on six own-country characteristics explains {r_squared:.0%} of the variance. "
                "The labeled points are what the model cannot explain.")
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.diverging[2],
               label="Punches above its fundamentals"),
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.diverging[0],
               label="Punches below"),
    ], loc="upper left", labelcolor=mode.ink_secondary)
    theme.save(fig, "09_residuals", mode, FIGURES)


# ---------------------------------------------------------------------------
# 10. The divide, by income group
# ---------------------------------------------------------------------------
def fig_divide(divide: pd.DataFrame, mode: Mode) -> None:
    theme.apply(mode)
    data = divide.dropna(subset=["income_group"]).sort_values("mean_access_pct")
    fig, ax = plt.subplots(figsize=(9.2, 5.4))
    y = np.arange(len(data))
    span = data["mean_access_pct"].max() - data["mean_access_pct"].min()
    colors = [theme.sequential_color(mode, (v - data["mean_access_pct"].min()) / span)
               for v in data["mean_access_pct"]]
    ax.barh(y, data["mean_access_pct"], height=0.6, color=colors,
            edgecolor=mode.surface, linewidth=2.0)

    for yi, row in zip(y, data.itertuples()):
        ax.annotate(f"{row.mean_access_pct:.0f}%   ({row.countries} countries, "
                    f"{row.people_share_pct:.0f}% of the world's people)",
                    (row.mean_access_pct, yi), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=8.8, color=mode.ink_secondary)

    ax.set_yticks(y, data["income_group"], fontsize=9.5)
    ax.set_xlim(0, data["mean_access_pct"].max() * 1.62)
    # Room for the annotations without ticking past 100%, which is not a
    # meaningful value for a share.
    ax.set_xticks([t for t in range(0, 101, 20)])
    ax.set_xlabel("Mean share of the world's weighted opportunity reachable without a prior visa")
    _pct(ax, "x")
    theme.frame(ax, mode, keep=("bottom",), grid_axis="x")
    theme.title(ax, mode, "The mobility divide, in one bar chart",
                "Balanced-lens attainment by World Bank income group. The bottom two groups "
                "hold most of the world's population.")
    theme.save(fig, "10_divide_by_income", mode, FIGURES)


# ---------------------------------------------------------------------------
# 11. What the data thinks matters, versus what we said matters
# ---------------------------------------------------------------------------
def fig_weight_comparison(datadriven: pd.DataFrame, explained: float, mode: Mode) -> None:
    theme.apply(mode)
    data = datadriven.copy()
    data["abs_loading"] = data["pc1_loading"].abs()
    data = data.sort_values("abs_loading")

    fig, ax = plt.subplots(figsize=(9.2, 6.4))
    y = np.arange(len(data))
    colors = [theme.diverging_color(mode, v, 0.3) for v in data["pc1_loading"]]
    ax.barh(y, data["pc1_loading"], height=0.6, color=colors,
            edgecolor=mode.surface, linewidth=2.0)
    ax.axvline(0, color=mode.axis, linewidth=1.2)

    ax.set_yticks(y, [f"{r.indicator}  ·  {r.pillar}" for r in data.itertuples()], fontsize=9)
    ax.set_xlabel("Loading on the first principal component of the destination indicator matrix")
    theme.frame(ax, mode, keep=("bottom",), grid_axis="x")
    theme.title(ax, mode, "Left to itself, the data builds a development index — not a size one",
                f"PC1 explains {explained:.0%} of the variance across destinations. Population and "
                "surface area load near zero: raw size is orthogonal to everything else.")
    theme.save(fig, "11_pca_loadings", mode, FIGURES)


# ---------------------------------------------------------------------------
# 12. The four mobility regimes
# ---------------------------------------------------------------------------
def fig_clusters(clusters: pd.DataFrame, recip: pd.DataFrame, profiles: pd.DataFrame,
                 mode: Mode) -> None:
    theme.apply(mode)
    data = clusters.merge(recip[["country", "reaches", "admits"]],
                          left_on="passport", right_on="country")
    order = profiles.sort_values("mean_attainment_pct", ascending=False)["label"].tolist()

    fig, ax = plt.subplots(figsize=(9.0, 7.8))
    # All-pairs form (every cluster can sit beside every other), so the palette
    # is capped at the three slots that clear the all-pairs gates; a fourth
    # group is carried by the muted ink instead of a generated hue.
    palette = list(mode.series[:3]) + [mode.ink_muted]
    for i, label in enumerate(order):
        subset = data[data["label"] == label]
        ax.scatter(subset["admits"], subset["reaches"], s=54, color=palette[i],
                   edgecolor=mode.surface, linewidth=2.0, label=f"{label}  (n={len(subset)})",
                   zorder=3 - i * 0.1)

    for iso in ("USA", "CHN", "IND", "NGA", "DEU", "ARE", "SGP", "BRA", "RUS", "ZAF"):
        row = data[data["passport"] == iso]
        if row.empty:
            continue
        ax.annotate(row.iloc[0]["name"], (row.iloc[0]["admits"], row.iloc[0]["reaches"]),
                    xytext=(9, 4), textcoords="offset points", fontsize=8.5,
                    color=mode.ink_secondary)

    ax.set_xlabel("Nationalities admitted without a prior visa")
    ax.set_ylabel("Destinations reachable without a prior visa")
    theme.frame(ax, mode, keep=("bottom", "left"), grid_axis="both")
    theme.title(ax, mode, "Four mobility regimes, found without being told they exist",
                "k-means on each passport's access composition, breadth and openness. "
                "Cluster count chosen by silhouette score.")
    ax.legend(loc="lower right", labelcolor=mode.ink_secondary, fontsize=8.6)
    theme.save(fig, "12_clusters", mode, FIGURES)


# ---------------------------------------------------------------------------
# 13. Does the story survive sharper weights?
# ---------------------------------------------------------------------------
def fig_dispersion(dispersion: pd.DataFrame, mode: Mode) -> None:
    theme.apply(mode)
    fig, ax = plt.subplots(figsize=(8.6, 5.4))
    x = np.arange(len(dispersion))
    ax.plot(x, dispersion["kendall_tau_vs_henley"], color=mode.series[0], linewidth=2.0,
            marker="o", markersize=8, markeredgecolor=mode.surface, markeredgewidth=2.0)
    for xi, row in zip(x, dispersion.itertuples()):
        ax.annotate(f"{row.kendall_tau_vs_henley:.3f}\n{row.weight_max_min_ratio:g}x spread",
                    (xi, row.kendall_tau_vs_henley), xytext=(0, 14),
                    textcoords="offset points", ha="center", fontsize=8.5,
                    color=mode.ink_secondary)

    ax.set_xticks(x, dispersion["variant"], fontsize=9)
    ax.set_ylim(0.85, 1.005)
    ax.set_ylabel("Kendall's tau vs. the Henley-rule count")
    theme.frame(ax, mode, keep=("bottom", "left"), grid_axis="y")
    theme.title(ax, mode, "Even a 143x spread in destination value barely reorders the table",
                "The composite is raised to a power to stretch or compress the gap between the "
                "best and worst destination, holding the ordering of destinations fixed.")
    theme.save(fig, "13_weight_dispersion", mode, FIGURES)


# ---------------------------------------------------------------------------
# 14. Blocs
# ---------------------------------------------------------------------------
def fig_blocs(blocs: pd.DataFrame, mode: Mode) -> None:
    """Internal cohesion turns out to be a non-story — every bloc but one is
    already at or near 100% internal frictionless density, so a bar chart of it
    is seven identical bars. What separates the blocs is what they buy their
    members *outside* the club, so that is what the bars encode, with internal
    density carried as an annotation."""
    theme.apply(mode)
    data = blocs.sort_values("mean_external_reach")
    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    y = np.arange(len(data))
    span = max(data["mean_external_reach"].max(), 1)
    colors = [theme.sequential_color(mode, v / span) for v in data["mean_external_reach"]]
    ax.barh(y, data["mean_external_reach"], height=0.6, color=colors,
            edgecolor=mode.surface, linewidth=2.0)
    for yi, row in zip(y, data.itertuples()):
        ax.annotate(f"{row.mean_external_reach:.0f} outside the bloc  ·  "
                    f"{row.internal_density:.0f}% frictionless within it",
                    (row.mean_external_reach, yi), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=8.8, color=mode.ink_secondary)
    ax.set_yticks(y, data["bloc"], fontsize=9.5)
    ax.set_xlim(0, span * 1.95)
    ax.set_xlabel("Mean destinations a member can reach outside its own bloc")
    theme.frame(ax, mode, keep=("bottom",), grid_axis="x")
    theme.title(ax, mode, "Every bloc is already a free-movement area. What differs is the world outside it.",
                "Internal density is at or near 100% for all but the African Union — membership "
                "is not the variable; what membership buys you elsewhere is.")
    theme.save(fig, "14_blocs", mode, FIGURES)


# ---------------------------------------------------------------------------
# 15. Days, not doors
# ---------------------------------------------------------------------------
def fig_stay_days(family: pd.DataFrame, mode: Mode) -> None:
    theme.apply(mode)
    fig, ax = plt.subplots(figsize=(8.6, 7.4))
    ax.scatter(family["henley_score"], family["stay_days_score"] / 365, s=34,
               color=mode.deemphasis, edgecolor=mode.surface, linewidth=1.5, zorder=2)

    family = family.copy()
    ratio = family["stay_days_score"] / family["henley_score"].clip(lower=1)
    family["ratio"] = ratio
    highlight = (pd.concat([family.nlargest(4, "ratio"), family.nsmallest(4, "ratio")])
                 .drop_duplicates("passport")
                 .sort_values("henley_score"))
    # Labels alternate above and below their marker; at this density a fixed
    # offset stacks Singapore on South Korea and Myanmar on Iran.
    offsets = [(12, 10), (12, -16), (-12, 10), (-12, -16)]
    for i, row in enumerate(highlight.itertuples()):
        color = mode.series[0] if row.ratio > ratio.median() else mode.series[1]
        ax.scatter(row.henley_score, row.stay_days_score / 365, s=76, color=color,
                   edgecolor=mode.surface, linewidth=2.0, zorder=3)
        dx, dy = offsets[i % len(offsets)]
        ax.annotate(row.name, (row.henley_score, row.stay_days_score / 365),
                    xytext=(dx, dy), textcoords="offset points", fontsize=8.5,
                    ha="left" if dx > 0 else "right", color=mode.ink_secondary)

    ax.set_xlabel("Destinations reachable without a prior visa (the published index)")
    ax.set_ylabel("Permitted person-years of frictionless presence")
    theme.frame(ax, mode, keep=("bottom", "left"), grid_axis="both")
    theme.title(ax, mode, "A door you can hold open for 90 days is not the same door",
                "The access matrix records permitted stay for 86% of visa-free pairs. Every "
                "published index throws that column away.")
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.series[0],
               label="More time than its door count suggests"),
        Line2D([], [], marker="o", linestyle="", markersize=8, color=mode.series[1],
               label="Less time than its door count suggests"),
    ], loc="upper left", labelcolor=mode.ink_secondary)
    theme.save(fig, "15_stay_days", mode, FIGURES)


# ---------------------------------------------------------------------------
def render_all(tables: dict, results: dict) -> list[str]:
    """Render every figure in both modes; returns the base names produced."""
    from ..analysis.inequality import gini, lorenz_curve

    names = dict(zip(tables["family"]["passport"], tables["family"]["name"]))
    family = tables["family"]

    lorenz_inputs = {
        "Henley-rule count": "henley_score",
        "Adjusted (Balanced)": "ahi_balanced_score",
        "Share of world GDP": "gdp_share_score",
    }
    curves = {label: lorenz_curve(family.set_index("passport")[col])
              for label, col in lorenz_inputs.items()}
    ginis = {label: gini(family[col]) for label, col in lorenz_inputs.items()}

    produced = []
    for mode in MODES:
        fig_rank_movement(tables["movement"], mode)
        fig_index_agreement(tables["agreement"], mode)
        fig_monte_carlo(tables["monte_carlo"], mode)
        fig_ladder(tables["ladder"], names, mode)
        fig_weight_distribution(tables["weights"], mode)
        fig_pillar_profiles(tables["attainment"], family, mode)
        fig_reciprocity(tables["reciprocity"], mode)
        fig_lorenz(curves, ginis, mode)
        fig_residuals(tables["residuals"], results["regression"]["r_squared"], mode)
        fig_divide(tables["divide"], mode)
        fig_weight_comparison(tables["datadriven"],
                              results["pca"]["explained_variance_pc1"], mode)
        fig_clusters(tables["clusters"], tables["reciprocity"], tables["cluster_profiles"], mode)
        fig_dispersion(tables["dispersion"], mode)
        fig_blocs(tables["blocs"], mode)
        fig_stay_days(family, mode)
    produced = sorted({p.name.rsplit(".", 2)[0] for p in FIGURES.glob("*.png")})
    return produced
