"""Uncertainty and sensitivity analysis.

The OECD/JRC handbook's position is that a composite indicator published without
an uncertainty analysis is not a measurement, it is an opinion with decimal
places. Every discretionary choice in this pipeline is therefore perturbed and
the rankings recomputed:

  * **pillar weights** -- resampled from a Dirichlet centred on the headline
    lens, so the whole simplex of "reasonable" weightings gets explored rather
    than a handful of hand-picked alternatives
  * **the friction ladder** -- all three ladders in `config.ACCESS_LADDERS`
  * **normalisation** -- winsorised min-max vs percentile rank vs clipped z-score
  * **imputation** -- destinations whose data is mostly imputed are dropped and
    the index recomputed without them

What comes out is a rank interval per passport. A country whose 90% interval
spans thirty places does not have a rank, and saying so is the point.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr

from ..config import (ACCESS_LADDERS, HEADLINE_LENS, LENS_BY_KEY, PILLARS,
                      RANDOM_SEED)
from ..features import build_features, normalise, pillar_scores
from ..indices import competition_rank, lens_weights, score


def monte_carlo_ranks(edges: pd.DataFrame, features: pd.DataFrame,
                      n_draws: int = 2000, concentration: float = 12.0,
                      seed: int = RANDOM_SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resample the pillar weight vector and recompute the ranking each time.

    Draws come from a Dirichlet centred on the headline lens. `concentration`
    controls how far they wander: at 12 a pillar published at 0.25 typically
    lands anywhere between about 0.08 and 0.48, which spans essentially every
    weighting a reasonable analyst could defend -- deliberately wider than the
    handful of alternative lenses, because the point is to find the conclusions
    that survive *any* reasonable weighting rather than four hand-picked ones.

    Returns per-passport rank quantiles, and the full draw matrix for plotting.
    """
    rng = np.random.default_rng(seed)
    base = np.array([LENS_BY_KEY[HEADLINE_LENS].weights[p] for p in PILLARS], dtype=float)
    # A pillar with weight 0 in the base lens must stay at 0 under Dirichlet
    # (alpha=0 is undefined), so give every pillar a small floor before drawing.
    alpha = np.clip(base, 0.01, None) * concentration

    pillar_matrix = features[[f"p_{p}" for p in PILLARS]].to_numpy()
    dest_index = features.index
    credit = edges["credit_graded"].to_numpy()
    passports = edges["passport"].to_numpy()
    dest_pos = pd.Index(dest_index).get_indexer(edges["destination"])

    passport_index = pd.Index(sorted(pd.unique(passports)), name="passport")
    passport_pos = passport_index.get_indexer(passports)
    n_passports = len(passport_index)

    draws = rng.dirichlet(alpha, size=n_draws)
    rank_matrix = np.empty((n_draws, n_passports), dtype=np.int32)

    for i, w in enumerate(draws):
        composite = pillar_matrix @ w
        composite = composite / composite.mean()
        totals = np.bincount(passport_pos, weights=credit * composite[dest_pos],
                             minlength=n_passports)
        ranks = competition_rank(pd.Series(totals, index=passport_index))
        rank_matrix[i] = ranks.to_numpy()

    ranks_df = pd.DataFrame(rank_matrix, columns=passport_index)
    summary = pd.DataFrame({
        "rank_median": ranks_df.median().astype(int),
        "rank_p05": ranks_df.quantile(0.05).astype(int),
        "rank_p95": ranks_df.quantile(0.95).astype(int),
        "rank_best": ranks_df.min().astype(int),
        "rank_worst": ranks_df.max().astype(int),
    })
    summary["rank_interval_width"] = summary["rank_p95"] - summary["rank_p05"]
    summary.index.name = "passport"
    draw_frame = pd.DataFrame(draws, columns=list(PILLARS))
    return summary.reset_index(), draw_frame


def ladder_sensitivity(edges: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Rank under each of the three friction ladders, holding weights fixed."""
    weight = lens_weights(features, HEADLINE_LENS)
    out = pd.DataFrame(index=pd.Index(sorted(edges["passport"].unique()), name="passport"))
    for ladder in ACCESS_LADDERS:
        s = score(edges, weight, ladder=ladder)
        out[f"rank_{ladder}"] = competition_rank(s)
        out[f"score_{ladder}"] = s.round(1)
    rank_cols = [c for c in out.columns if c.startswith("rank_")]
    out["rank_spread"] = out[rank_cols].max(axis=1) - out[rank_cols].min(axis=1)
    return out.reset_index()


def normalisation_sensitivity(edges: pd.DataFrame, destinations: pd.Index) -> pd.DataFrame:
    """Rank under each normalisation scheme, holding weights and ladder fixed.

    Rebuilds features from scratch per method rather than rescaling in place,
    because the winsorisation happens before scaling and cannot be undone.
    """
    out = pd.DataFrame(index=pd.Index(sorted(edges["passport"].unique()), name="passport"))
    for method in ("winsor_minmax", "rank", "zscore"):
        features, _ = build_features(destinations, norm_method=method)
        s = score(edges, lens_weights(features, HEADLINE_LENS), ladder="graded")
        out[f"rank_{method}"] = competition_rank(s)
    rank_cols = list(out.columns)
    out["rank_spread"] = out[rank_cols].max(axis=1) - out[rank_cols].min(axis=1)
    return out.reset_index()


def imputation_sensitivity(edges: pd.DataFrame, features: pd.DataFrame,
                           provenance: pd.DataFrame, max_imputed: int = 3) -> pd.DataFrame:
    """Recompute the index with heavily-imputed destinations removed.

    If a passport's standing depends on destinations whose data we largely made
    up, that is worth knowing. Destinations with more than `max_imputed`
    non-observed cells are dropped entirely and everything is rescored on the
    surviving universe.
    """
    non_observed = (~provenance.isin(["observed"])).sum(axis=1)
    keep = non_observed[non_observed <= max_imputed].index
    trimmed_edges = edges[edges["destination"].isin(keep)]
    trimmed_features = features.loc[keep]

    full = score(edges, lens_weights(features, HEADLINE_LENS), ladder="graded")
    trimmed = score(trimmed_edges, lens_weights(trimmed_features, HEADLINE_LENS), ladder="graded")

    out = pd.DataFrame({
        "rank_all_destinations": competition_rank(full),
        "rank_well_measured_only": competition_rank(trimmed),
    })
    out["rank_shift"] = out["rank_all_destinations"] - out["rank_well_measured_only"]
    out.index.name = "passport"
    return out.reset_index(), len(keep), len(features)


def index_agreement(family: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Kendall tau-b between every index variant's ranking.

    Kendall rather than Pearson because the object of interest is the ordering,
    and tau-b because dense ranking produces a lot of ties. Two indices at
    tau = 0.99 are the same index with extra steps; the interesting cells are
    the low ones, which is where a weighting choice actually changed an answer.
    """
    rank_cols = [c for c in family.columns if c.endswith("_pos")]
    names = [c[:-4] for c in rank_cols]
    matrix = pd.DataFrame(index=names, columns=names, dtype=float)
    for i, a in enumerate(rank_cols):
        for j, b in enumerate(rank_cols):
            if j < i:
                continue
            tau = kendalltau(family[a], family[b], variant="b").statistic
            matrix.iloc[i, j] = matrix.iloc[j, i] = tau
    return matrix


def rank_movement(family: pd.DataFrame, baseline: str = "henley",
                  target: str = f"ahi_{HEADLINE_LENS}") -> pd.DataFrame:
    """Movement between two indices, with the effect decomposed.

    `weighting_effect` is what changes when destinations stop being worth one
    point each; `friction_effect` is what changes when entry regimes stop being
    a binary. Reporting the total alone would leave a reader unable to tell
    which of the two modelling choices is doing the work.
    """
    indexed = family.set_index("passport")
    out = pd.DataFrame({
        "baseline_rank": indexed[f"{baseline}_pos"],
        "target_rank": indexed[f"{target}_pos"],
        "weighting_only_rank": indexed["binary_weighted_pos"],
        "friction_only_rank": indexed["graded_count_pos"],
    })
    out["total_move"] = out["baseline_rank"] - out["target_rank"]
    out["weighting_effect"] = out["baseline_rank"] - out["weighting_only_rank"]
    out["friction_effect"] = out["baseline_rank"] - out["friction_only_rank"]
    out.index.name = "passport"
    return out.reset_index()


def validate_against_published(family: pd.DataFrame, published: pd.DataFrame) -> dict:
    """Compare the reproduction of Henley's rule against Henley's own published
    figures on the subset where they are available.

    The comparison is ordinal by necessity: Henley scores against 227
    destinations using licensed IATA data, this project against the 199 in the
    open matrix, so the levels cannot match and it would be dishonest to present
    a level agreement. What can be tested is whether the same rule applied to a
    comparable universe puts countries in the same order.
    """
    merged = family.merge(published, left_on="passport", right_on="iso3", how="inner")
    rho = spearmanr(merged["henley_score"], merged["henley_published_score"])
    tau = kendalltau(merged["henley_score"], merged["henley_published_score"], variant="b")
    # The rank comparison is the sharper test: it checks that the dense-ranking
    # convention was implemented the way Henley describes it, not merely that
    # the same countries score highly.
    rank_rho = spearmanr(merged["henley_rank"], merged["henley_published_rank"])
    tier_match = int((merged["henley_rank"] - merged["henley_published_rank"]).abs().le(2).sum())
    return {
        "n_reference_points": len(merged),
        "spearman_rho": round(float(rho.statistic), 4),
        "spearman_p": float(rho.pvalue),
        "kendall_tau": round(float(tau.statistic), 4),
        "rank_spearman_rho": round(float(rank_rho.statistic), 4),
        "within_two_ranks": tier_match,
        "comparison": merged[["passport", "country", "henley_score", "henley_rank",
                              "henley_published_score", "henley_published_rank"]]
                        .sort_values("henley_published_rank"),
        "rows": merged[["country", "henley_score", "henley_rank",
                        "henley_published_score", "henley_published_rank"]]
                  .sort_values("henley_published_rank").to_dict(orient="records"),
    }
