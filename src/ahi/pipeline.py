"""End-to-end pipeline: raw data in, tables and a results bundle out.

Run with `python -m ahi.pipeline`. Every table lands in `output/tables/` as CSV
and the numbers the article and the website quote are collected into
`output/results.json`, so no figure in the prose is typed by hand.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (DEFAULT_LADDER, FIGURES, HEADLINE_LENS, INDICATORS, LENSES,
                     MANUAL, OUTPUT, PILLARS, PROCESSED, TABLES)
from .features import build_features, provenance_summary
from .indices import (build_index_family, openness_frame, pillar_attainment,
                      pillar_contributions)
from .ingest.access import category_summary, load_access_edges, load_iso3_to_name
from .analysis import inequality, models, network, sensitivity


def _save(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    frame.to_csv(TABLES / f"{name}.csv", index=False)
    return frame


def _json_safe(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return round(float(obj), 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, pd.Series):
        return _json_safe(obj.to_dict())
    if isinstance(obj, pd.DataFrame):
        return _json_safe(obj.to_dict(orient="records"))
    return obj


def run(n_monte_carlo: int = 3000, build_website: bool = True) -> dict:
    started = time.time()
    results: dict[str, object] = {}

    # -- 1. Access graph ---------------------------------------------------
    edges = load_access_edges()
    names = load_iso3_to_name()
    destinations = pd.Index(sorted(edges["destination"].unique()), name="iso3")
    _save(category_summary(edges), "01_access_categories")

    # -- 2. Destination features ------------------------------------------
    features, provenance = build_features(destinations)
    features["name"] = features.index.map(names)
    prov_summary = _save(provenance_summary(provenance), "02_data_provenance")
    provenance.assign(name=provenance.index.map(names)).to_csv(TABLES / "02b_provenance_cells.csv")

    vintages = pd.DataFrame({
        "indicator": [ind.key for ind in INDICATORS],
        "pillar": [ind.pillar for ind in INDICATORS],
        "label": [ind.label for ind in INDICATORS],
        "source": [ind.source for ind in INDICATORS],
        "code": [ind.code for ind in INDICATORS],
        "direction": [ind.direction for ind in INDICATORS],
        "transform": [ind.transform for ind in INDICATORS],
        "median_vintage": [int(features[f"{ind.key}_year"].median())
                           if f"{ind.key}_year" in features else None
                           for ind in INDICATORS],
        "note": [ind.note for ind in INDICATORS],
    })
    _save(vintages, "03_indicator_registry")

    # -- 3. Index family ---------------------------------------------------
    family, diagnostics = build_index_family(edges, features)
    family["name"] = family["passport"].map(names)
    contributions = pillar_contributions(edges, features, HEADLINE_LENS)
    openness = openness_frame(edges, features)
    openness["name"] = openness["passport"].map(names)

    _save(family, "04_index_family")
    _save(contributions.assign(name=contributions["passport"].map(names)), "05_pillar_contributions")
    attainment = pillar_attainment(edges, features)
    _save(attainment.assign(name=attainment["passport"].map(names)), "05b_pillar_attainment")
    _save(openness, "06_openness")

    weight_table = diagnostics["weight_table"].copy()
    weight_table.insert(0, "name", weight_table.index.map(names))
    weight_table = weight_table.reset_index().rename(columns={"iso3": "destination"})
    _save(weight_table, "07_destination_weights")
    _save(features.reset_index(), "08_destination_features")

    _save(pd.DataFrame({
        "indicator": diagnostics["pca_loadings"].index,
        "pc1_loading": diagnostics["pca_loadings"].round(4).to_numpy(),
        "entropy_weight": diagnostics["entropy_weights"].round(4).to_numpy(),
        "pillar": [ind.pillar for ind in INDICATORS],
    }), "09_datadriven_weights")

    # -- 4. Sensitivity ----------------------------------------------------
    mc_summary, mc_draws = sensitivity.monte_carlo_ranks(edges, features, n_draws=n_monte_carlo)
    mc_summary["name"] = mc_summary["passport"].map(names)
    _save(mc_summary, "10_monte_carlo_ranks")
    _save(sensitivity.ladder_sensitivity(edges, features), "11_ladder_sensitivity")
    _save(sensitivity.normalization_sensitivity(edges, destinations), "12_normalization_sensitivity")

    imp_frame, n_kept, n_total = sensitivity.imputation_sensitivity(edges, features, provenance)
    _save(imp_frame, "13_imputation_sensitivity")

    agreement = sensitivity.index_agreement(family)
    agreement.to_csv(TABLES / "14_index_agreement.csv")

    movement = _save(sensitivity.rank_movement(family).assign(
        name=lambda d: d["passport"].map(names)), "15_rank_movement")
    movement_balance = sensitivity.movement_balance(movement)

    published = pd.read_csv(MANUAL / "henley_published_2026.csv", comment="#")
    validation = sensitivity.validate_against_published(family, published)
    _save(validation.pop("comparison"), "16_henley_validation")

    dispersion = pd.DataFrame({
        "variant": ["flat (gamma 0.5)", "headline (gamma 1)", "sharp (gamma 2)", "extreme (gamma 4)"],
        "weight_max_min_ratio": [
            round(float(diagnostics["weight_table"][c].max() /
                        diagnostics["weight_table"][c].min()), 2)
            for c in ["gamma_flat", HEADLINE_LENS, "gamma_sharp", "gamma_extreme"]],
        "gini_of_weight": [
            round(inequality.gini(diagnostics["weight_table"][c]), 4)
            for c in ["gamma_flat", HEADLINE_LENS, "gamma_sharp", "gamma_extreme"]],
        "kendall_tau_vs_henley": [
            round(float(__import__("scipy.stats", fromlist=["kendalltau"])
                        .kendalltau(family["henley_pos"], family[c], variant="b").statistic), 4)
            for c in ["ahi_gamma_flat_pos", f"{'ahi_' + HEADLINE_LENS}_pos",
                      "ahi_gamma_sharp_pos", "ahi_gamma_extreme_pos"]],
    })
    _save(dispersion, "16b_weight_dispersion")

    # -- 5. Network --------------------------------------------------------
    graph = network.build_graph(edges)
    recip = network.reciprocity_table(edges, features)
    recip["name"] = recip["country"].map(names)
    _save(recip, "17_reciprocity")
    _save(network.centrality_table(graph).assign(
        name=lambda d: d["country"].map(names)), "18_centrality")
    communities = _save(network.mutual_communities(edges).assign(
        name=lambda d: d["country"].map(names)), "19_communities")
    _save(network.bloc_summary(edges, features), "20_blocs")
    _save(network.asymmetry_pairs(edges, features).assign(
        enters=lambda d: d["can_enter"].map(names),
        blocked=lambda d: d["cannot_be_entered_by"].map(names)), "21_asymmetry_pairs")

    # -- 6. Inequality -----------------------------------------------------
    ineq = _save(inequality.mobility_inequality(family, features), "22_mobility_inequality")
    concentration = inequality.destination_value_concentration(features)
    _save(inequality.divide_by_group(family, features), "23_divide_by_income")
    _save(inequality.divide_by_group(family, features, group_col="region"), "24_divide_by_region")
    gap = _save(inequality.access_to_wealth_gap(family, features).assign(
        name=lambda d: d["passport"].map(names)), "25_access_to_wealth")
    _save(inequality.lorenz_curve(family.set_index("passport")[f"ahi_{HEADLINE_LENS}_score"]),
          "26_lorenz_passports")

    # -- 7. Models ---------------------------------------------------------
    model, residuals = models.fit_strength_model(family, features)
    residuals["name"] = residuals["passport"].map(names)
    _save(residuals, "27_strength_residuals")
    _save(models.coefficient_table(model), "28_strength_coefficients")
    vif = _save(models.variance_inflation(family, features), "28b_variance_inflation")

    assignment, centroids, best_k, silhouette = models.cluster_passports(
        family, contributions, openness)
    assignment["name"] = assignment["passport"].map(names)
    cluster_labels = models.label_clusters(assignment, centroids, family)
    _save(assignment.merge(cluster_labels[["cluster", "label"]], on="cluster"), "29_passport_clusters")
    _save(cluster_labels, "30_cluster_profiles")
    _save(silhouette, "31_cluster_silhouette")
    mc_draws.describe().round(3).to_csv(TABLES / "10b_monte_carlo_weight_draws.csv")

    # -- 8. Results bundle -------------------------------------------------
    headline = f"ahi_{HEADLINE_LENS}"
    top = family.nsmallest(15, f"{headline}_pos")
    results["meta"] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "n_passports": int(family["passport"].nunique()),
        "n_destinations": int(len(destinations)),
        "n_edges": int(len(edges)),
        "n_indicators": len(INDICATORS),
        "n_pillars": len(PILLARS),
        "n_lenses": len(LENSES),
        "headline_lens": HEADLINE_LENS,
        "default_ladder": DEFAULT_LADDER,
        "runtime_seconds": round(time.time() - started, 1),
    }
    results["validation"] = validation
    results["provenance"] = {
        "mean_observed_pct": round(float(prov_summary["observed_pct"].mean()), 1),
        "min_observed_pct": round(float(prov_summary["observed_pct"].min()), 1),
        "worst_indicator": prov_summary.iloc[0]["indicator"],
        "destinations_well_measured": int(n_kept),
        "destinations_total": int(n_total),
    }
    results["top15"] = top[["passport", "name", "henley_score", "henley_rank", "henley_pos",
                            "henley_frac", f"{headline}_score", f"{headline}_rank",
                            f"{headline}_pos", f"{headline}_frac",
                            f"{headline}_pct", "gdp_share_score", "pop_share_score"]]
    movement_cols = ["passport", "name", "baseline_rank", "target_rank", "baseline_pos",
                     "target_pos", "total_move", "weighting_effect", "friction_effect"]
    results["biggest_gainers"] = movement.nlargest(12, "total_move")[movement_cols]
    results["biggest_losers"] = movement.nsmallest(12, "total_move")[movement_cols]
    results["movement_balance"] = movement_balance
    results["concentration"] = concentration
    results["inequality"] = ineq[ineq["index"].isin(["henley", headline, "gdp_share", "pop_share"])]
    results["regression"] = {
        "r_squared": round(float(model.rsquared), 4),
        "adj_r_squared": round(float(model.rsquared_adj), 4),
        "n_obs": int(model.nobs),
        "coefficients": models.coefficient_table(model),
        "vif": vif,
    }
    results["overperformers"] = residuals.nlargest(10, "residual")[
        ["passport", "name", "actual", "predicted", "residual"]]
    results["underperformers"] = residuals.nsmallest(10, "residual")[
        ["passport", "name", "actual", "predicted", "residual"]]
    results["clusters"] = cluster_labels
    results["best_k"] = best_k
    results["pca"] = {
        "explained_variance_pc1": round(float(diagnostics["pca_explained_variance"]), 4),
        "loadings": diagnostics["pca_loadings"].round(3),
    }
    results["reciprocity"] = {
        "largest_surplus": recip.nlargest(10, "mobility_balance")[
            ["country", "name", "reaches", "admits", "mobility_balance", "reciprocated_share"]],
        "largest_deficit": recip.nsmallest(10, "mobility_balance")[
            ["country", "name", "reaches", "admits", "mobility_balance", "reciprocated_share"]],
        "mean_reciprocated_share": round(float(recip["reciprocated_share"].mean()), 1),
    }
    results["monte_carlo"] = {
        "n_draws": n_monte_carlo,
        "median_interval_width": float(mc_summary["rank_interval_width"].median()),
        "widest": mc_summary.nlargest(10, "rank_interval_width")[
            ["passport", "name", "rank_median", "rank_p05", "rank_p95", "rank_interval_width"]],
        "narrowest_top20": mc_summary.nsmallest(20, "rank_median").nsmallest(
            10, "rank_interval_width")[["passport", "name", "rank_median",
                                        "rank_p05", "rank_p95"]],
    }
    results["agreement"] = agreement.round(3)
    results["weight_dispersion"] = dispersion
    results["communities"] = (communities.groupby(["community", "community_label"])
                              .size().rename("members").reset_index()
                              .sort_values("members", ascending=False))

    (OUTPUT / "results.json").write_text(json.dumps(_json_safe(results), indent=2) + "\n")

    # Processed artifacts for the website, kept small and denormalized.
    site_frame = (family.merge(contributions, on="passport")
                  .merge(openness.drop(columns="name"), on="passport")
                  .merge(mc_summary.drop(columns="name"), on="passport")
                  .merge(recip.drop(columns="name"), left_on="passport", right_on="country")
                  .merge(assignment.drop(columns="name"), on="passport")
                  .merge(cluster_labels[["cluster", "label"]], on="cluster")
                  .merge(residuals[["passport", "predicted", "residual"]], on="passport")
                  .merge(attainment, on="passport"))
    site_frame.to_csv(PROCESSED / "passport_master.csv", index=False)
    weight_table.to_csv(PROCESSED / "destination_master.csv", index=False)

    # -- 9. Figures --------------------------------------------------------
    from .viz.figures import render_all
    figure_tables = {
        "family": family, "movement": movement, "agreement": agreement,
        "monte_carlo": mc_summary, "ladder": pd.read_csv(TABLES / "11_ladder_sensitivity.csv"),
        "weights": weight_table, "contributions": contributions, "reciprocity": recip,
        "attainment": attainment,
        "residuals": residuals, "divide": pd.read_csv(TABLES / "23_divide_by_income.csv"),
        "datadriven": pd.read_csv(TABLES / "09_datadriven_weights.csv"),
        "clusters": pd.read_csv(TABLES / "29_passport_clusters.csv"),
        "cluster_profiles": cluster_labels, "dispersion": dispersion,
        "blocs": pd.read_csv(TABLES / "20_blocs.csv"),
    }
    figures = render_all(figure_tables, results)
    print(f"Rendered {len(figures)} figures x 2 modes to {FIGURES}")

    # -- 10. Website -------------------------------------------------------
    if build_website:
        from .viz.site import build as build_site
        # Read the bundle back rather than passing `results` directly: the site
        # must be built from exactly the JSON that ships next to it, not from
        # live DataFrames that serialize into something subtly different.
        build_site(json.loads((OUTPUT / "results.json").read_text()))

    print(f"\nWrote {len(list(TABLES.glob('*.csv')))} tables to {TABLES}")
    print(f"Results bundle: {OUTPUT / 'results.json'}")
    print(f"Runtime: {results['meta']['runtime_seconds']}s")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=3000,
                        help="Monte Carlo weight resamples (default 3000)")
    parser.add_argument("--no-site", action="store_true",
                        help="skip building docs/ (tables and figures only)")
    args = parser.parse_args()
    run(n_monte_carlo=args.draws, build_website=not args.no_site)


if __name__ == "__main__":
    main()
