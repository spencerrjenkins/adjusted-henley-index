"""Build the GitHub Pages data story into `docs/`.

Every number quoted in the prose is a `{{token}}` resolved here from the
pipeline's own tables. Nothing in the narrative is typed by hand, so the page
cannot drift out of agreement with the data when an upstream series updates --
which is the failure mode of every hand-written data article.
"""

from __future__ import annotations

import json
import re
import shutil

import numpy as np
import pandas as pd

from ..config import (ASSETS, DOCS, FIGURES, INDICATORS, LENSES, LENS_BY_KEY,
                      PILLARS, PILLAR_BLURBS, PILLAR_LABELS, ROOT, TABLES,
                      ACCESS_LADDERS, HEADLINE_LENS)

SITE_ASSETS = ASSETS / "site"

# Jurisdictions too small to render as filled polygons at 110m map resolution;
# drawn as dot markers instead. Coordinates are (lon, lat).
MARKER_CENTROIDS = {
    "AND": (1.52, 42.51), "ATG": (-61.80, 17.06), "BHR": (50.55, 26.03), "BRB": (-59.60, 13.19),
    "COM": (43.33, -11.70), "CPV": (-23.60, 15.12), "DMA": (-61.37, 15.41), "FSM": (150.55, 6.92),
    "GRD": (-61.68, 12.11), "HKG": (114.17, 22.28), "KIR": (173.00, 1.35), "KNA": (-62.75, 17.30),
    "LCA": (-60.98, 13.91), "LIE": (9.53, 47.14), "MAC": (113.55, 22.20), "MCO": (7.42, 43.73),
    "MDV": (73.50, 3.20), "MHL": (171.18, 7.10), "MLT": (14.51, 35.90), "MUS": (57.55, -20.35),
    "NRU": (166.93, -0.52), "PLW": (134.58, 7.50), "SGP": (103.80, 1.35), "SMR": (12.46, 43.94),
    "STP": (6.60, 0.19), "SYC": (55.45, -4.68), "TON": (-175.20, -21.20), "TUV": (179.20, -8.52),
    "VAT": (12.45, 41.90), "VCT": (-61.20, 13.25), "WSM": (-172.10, -13.75),
}
PROJECTION_W, PROJECTION_H = 1000, 500  # must match assets/world_paths.js


def _ordinal(n: int) -> str:
    """1 -> '1st', 32 -> '32nd'. Templates that append a bare 'th' produce '32th',
    which is the kind of detail a reader takes as evidence nothing was checked."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _ladder_row(ladder, iso3: str):
    return ladder[ladder["passport"] == iso3].iloc[0]


def _n_tests() -> int:
    """Read off the test files rather than typed into the page, so the count
    cannot drift from the suite. Every test is a plain function -- nothing is
    parametrised -- so counting definitions is what pytest collects."""
    return sum(len(re.findall(r"^def test_", path.read_text(), re.M))
               for path in sorted((ROOT / "tests").glob("test_*.py")))


def _project(lon: float, lat: float) -> list[float]:
    return [round((lon + 180) * (PROJECTION_W / 360), 2),
            round((90 - lat) * (PROJECTION_H / 180), 2)]


def _country_payload(master: pd.DataFrame, features: pd.DataFrame,
                     ladder: pd.DataFrame, engine: dict) -> dict:
    """One compact record per passport. Kept flat and short-keyed: the whole
    payload is inlined into the page, so every byte is on the critical path."""
    lens_keys = [lens.key for lens in LENSES]
    lad = ladder.set_index("passport")
    contrib = engine["contributions"]
    own = engine["own"]
    payload = {}
    for row in master.itertuples():
        iso = row.passport
        payload[iso] = {
            "iso": iso,
            "name": row.name,
            "region": features.at[iso, "region"] if iso in features.index else None,
            "incomeGroup": features.at[iso, "income_group"] if iso in features.index else None,
            "henleyScore": int(row.henley_score),
            "henleyRank": int(row.henley_rank),
            "henleyPos": int(row.henley_pos),
            # Fractional rank: the basis for every movement figure, because it
            # is the only convention under which a heavily-tied index and a
            # continuous one can be differenced without a built-in drift.
            "henleyFrac": float(row.henley_frac),
            "balancedFrac": float(row.ahi_balanced_frac),
            "gradedScore": float(row.graded_count_score),
            "balancedScore": float(row.ahi_balanced_score),
            "lenses": {k: float(getattr(row, f"ahi_{k}_pct")) for k in lens_keys},
            "pos": {**{k: int(getattr(row, f"ahi_{k}_pos")) for k in lens_keys},
                    "gdpShare": int(row.gdp_share_pos),
                    "popShare": int(row.pop_share_pos),
                    "stayDays": int(row.stay_days_pos)},
            "gdpShare": float(row.gdp_share_score),
            "popShare": float(row.pop_share_score),
            "stayDays": int(row.stay_days_score),
            "reaches": int(row.reaches),
            "admits": int(row.admits),
            "balance": int(row.mobility_balance),
            "reciprocated": float(row.reciprocated_share) if pd.notna(row.reciprocated_share) else None,
            "mcMedian": int(row.rank_median),
            "mcLow": int(row.rank_p05),
            "mcHigh": int(row.rank_p95),
            "clusterLabel": row.label,
            "predicted": float(row.predicted),
            "residual": float(row.residual),
            "pillars": {p: {"att": float(getattr(row, f"att_{p}")),
                            "tilt": float(getattr(row, f"tilt_{p}"))} for p in PILLARS},
            # Per-pillar credit sums and own-country pillar scores: the two
            # vectors the live weight explorer needs to rebuild the index.
            "c": [float(contrib.at[iso, p]) for p in PILLARS],
            "own": [float(own.at[iso, p]) for p in PILLARS],
            "ladder": {"binary": float(lad.at[iso, "rank_binary_henley"]),
                       "graded": float(lad.at[iso, "rank_graded"]),
                       "strict": float(lad.at[iso, "rank_strict"])},
            "weightingEffect": float(row.weighting_effect),
            "frictionEffect": float(row.friction_effect),
        }
    return payload


def _series(results: dict, master: pd.DataFrame, tables: dict, engine: dict) -> dict:
    """Aggregate series the per-passport records cannot carry.

    Everything here is small (the largest is a 16x16 correlation matrix), so it
    ships inline with the page rather than as a second request -- the charts
    render on first paint instead of after a round trip.
    """
    agreement = tables["agreement"]
    order = [c for c in ["henley", "graded_count", "binary_weighted", "ahi_balanced",
                         "ahi_business", "ahi_leisure", "ahi_settlement", "ahi_reach",
                         "ahi_pca", "ahi_entropy", "gdp_share", "pop_share",
                         "ahi_gamma_flat", "ahi_gamma_sharp", "ahi_gamma_extreme",
                         "stay_days"] if c in agreement.index]
    labels = {"henley": "Henley rule", "graded_count": "Graded, flat weights",
              "binary_weighted": "Binary, weighted", "ahi_balanced": "AHI Balanced",
              "ahi_business": "AHI Business", "ahi_leisure": "AHI Leisure",
              "ahi_settlement": "AHI Settlement", "ahi_reach": "AHI Raw reach",
              "ahi_pca": "PCA weights", "ahi_entropy": "Entropy weights",
              "gdp_share": "World GDP share", "pop_share": "World people share",
              "ahi_gamma_flat": "Flat dispersion", "ahi_gamma_sharp": "Sharp dispersion",
              "ahi_gamma_extreme": "Extreme dispersion", "stay_days": "Person-days"}

    weights = tables["weights"]
    lorenz = pd.read_csv(TABLES / "26_lorenz_passports.csv")
    from ..analysis.inequality import gini, lorenz_curve
    fam = tables["family"]
    curves = {}
    for label, col in (("Henley-rule count", "henley_score"),
                       ("Adjusted (Balanced)", "ahi_balanced_score"),
                       ("Share of world GDP", "gdp_share_score")):
        curve = lorenz_curve(fam.set_index("passport")[col])
        step = max(len(curve) // 100, 1)
        curves[label] = {
            "gini": round(gini(fam[col]), 3),
            "points": [[round(float(a), 4), round(float(b), 4)]
                       for a, b in curve.iloc[::step][["population_share", "value_share"]]
                       .to_numpy()],
        }

    divide = tables["divide"].dropna(subset=["income_group"])
    dd = tables["datadriven"]

    return {
        "agreement": {"order": order, "labels": [labels[o] for o in order],
                      "matrix": [[round(float(agreement.loc[a, b]), 3) for b in order]
                                 for a in order]},
        "destinationWeights": [
            {"iso": r.destination, "name": r.name, "w": round(float(r.balanced), 3)}
            for r in weights.itertuples()],
        "lorenz": curves,
        "divide": [{"group": r.income_group, "countries": int(r.countries),
                    "access": round(float(r.mean_access_pct), 1),
                    "people": round(float(r.people_share_pct), 1)}
                   for r in divide.itertuples()],
        "pca": [{"indicator": r.indicator, "pillar": r.pillar,
                 "loading": round(float(r.pc1_loading), 3),
                 "entropy": round(float(r.entropy_weight), 4)} for r in dd.itertuples()],
        "dispersion": [{"variant": r.variant, "ratio": float(r.weight_max_min_ratio),
                        "gini": float(r.gini_of_weight),
                        "tau": float(r.kendall_tau_vs_henley)}
                       for r in tables["dispersion"].itertuples()],
        "blocs": [{"bloc": r.bloc, "members": int(r.members_in_data),
                   "internal": float(r.internal_density),
                   "external": float(r.mean_external_reach)}
                  for r in tables["blocs"].itertuples()],
        "clusters": [{"label": c["label"], "members": c["members"],
                      "breadth": c["mean_breadth"], "openness": c["mean_openness_count"],
                      "attainment": c["mean_attainment_pct"], "description": c["description"]}
                     for c in results["clusters"]],
        "ladders": ACCESS_LADDERS,
        "pillars": [{"key": p, "label": PILLAR_LABELS[p], "blurb": PILLAR_BLURBS[p],
                     "indicators": [{"key": i.key, "label": i.label, "unit": i.unit,
                                     "direction": i.direction, "transform": i.transform,
                                     "note": i.note}
                                    for i in INDICATORS if i.pillar == p]}
                    for p in PILLARS],
        "lenses": [{"key": l.key, "label": l.label, "question": l.question,
                    "weights": l.weights} for l in LENSES],
        "engine": {
            "totals": engine["totals"],
            "n": engine["n_destinations"],
            "headline": LENS_BY_KEY[HEADLINE_LENS].weights,
        },
        "regression": {
            "r2": results["regression"]["r_squared"],
            "coefficients": [{"label": c["label"], "coef": c["coefficient"],
                              "p": c["p_value"], "lo": c["ci_low"], "hi": c["ci_high"]}
                             for c in results["regression"]["coefficients"]
                             if c["term"] != "const"],
        },
        "validation": results["validation"]["rows"],
        "movementBalance": results["movement_balance"],
        "categories": [{"category": r.category, "pairs": int(r.pairs),
                        "share": float(r.share_of_pairs),
                        "credit": float(r.credit_graded),
                        "binary": float(r.credit_binary_henley),
                        "strict": float(r.credit_strict),
                        "days": float(r.median_stay_days)}
                       for r in tables["categories"].itertuples()],
    }


def _tokens(results: dict, master: pd.DataFrame, tables: dict) -> dict[str, str]:
    """Resolve every `{{token}}` in the template from the computed tables."""
    meta = results["meta"]
    by_iso = master.set_index("passport")

    ladder = tables["ladder"]
    mys = ladder[ladder["passport"] == "MYS"].iloc[0]
    categories = tables["categories"]
    visa_free = categories[categories["category"] == "visa_free"].iloc[0]

    agreement = tables["agreement"]
    family_cols = [c for c in agreement.index
                   if c.startswith("ahi_") or c in ("henley", "graded_count", "binary_weighted")]
    sub = agreement.loc[family_cols, family_cols].astype(float)
    min_tau_family = float(np.nanmin(sub.to_numpy()))

    dispersion = tables["dispersion"].set_index("variant")
    divide = tables["divide"]
    ineq = {r["index"]: r for r in results["inequality"]}
    communities = {r["community_label"]: r["members"] for r in results["communities"]}
    clusters = {r["label"]: r for r in results["clusters"]}
    open_cluster = next((v for k, v in clusters.items() if k.startswith("Open")), None)

    prov = tables["provenance"]
    total_cells = int(prov[["observed", "manual", "proxied", "imputed"]].to_numpy().sum())
    non_observed = int(prov[["manual", "proxied", "imputed"]].to_numpy().sum())

    registry = tables["registry"].set_index("indicator")

    def community(prefix: str) -> int:
        for label, members in communities.items():
            if label.startswith(prefix):
                return int(members)
        return 0

    fully_open = int(((master["admits"] > 190) & (master["reaches"] < 70)).sum())

    return {
        "generated_date": meta["generated_at"][:10],
        "generated_at": meta["generated_at"],
        "runtime": str(meta["runtime_seconds"]),
        "n_passports": f"{meta['n_passports']}",
        "n_edges": f"{meta['n_edges']:,}",
        "n_indicators": f"{meta['n_indicators']}",
        "n_variants": str(len([c for c in tables["family"].columns if c.endswith("_pos")])),
        "n_tests": str(_n_tests()),
        "n_tables": str(len(list(TABLES.glob("*.csv")))),
        "n_figures": str(len(list(FIGURES.glob("*.light.png")))),

        "malaysia_henley": _ordinal(int(by_iso.at["MYS", "henley_pos"])),
        "malaysia_adjusted": _ordinal(int(by_iso.at["MYS", "ahi_balanced_pos"])),
        "malaysia_henley_frac": f'{by_iso.at["MYS", "henley_frac"]:.1f}',
        "malaysia_adjusted_frac": f'{by_iso.at["MYS", "ahi_balanced_frac"]:.1f}',
        "move_mean": f'{results["movement_balance"]["mean_move"]:.2f}',
        "move_down": str(results["movement_balance"]["n_down"]),
        "move_up": str(results["movement_balance"]["n_up"]),
        "largest_fall": f'{abs(results["movement_balance"]["largest_fall"]):.1f}',
        "largest_rise": f'{results["movement_balance"]["largest_rise"]:.1f}',
        "tied_passports": str(int(tables["family"]["henley_score"]
                                  .duplicated(keep=False).sum())),
        "malaysia_move": f'{abs(by_iso.at["MYS", "henley_frac"] - by_iso.at["MYS", "ahi_balanced_frac"]):.1f}',

        # Fractional ranks, so these are expected positions and can be halves;
        # int() here would quietly report 33.5 as 33.
        "ladder_median": f'{ladder["rank_spread"].median():g}',
        "ladder_max": f'{ladder["rank_spread"].max():g}',
        "myss_binary": f'{mys["rank_binary_henley"]:g}',
        "myss_strict": f'{mys["rank_strict"]:g}',
        "kor_binary": f'{_ladder_row(ladder, "KOR")["rank_binary_henley"]:g}',
        "kor_strict": f'{_ladder_row(ladder, "KOR")["rank_strict"]:g}',
        "jpn_binary": f'{_ladder_row(ladder, "JPN")["rank_binary_henley"]:g}',
        "explicit_days_pct": str(round(visa_free["with_explicit_days"] / visa_free["pairs"] * 100)),

        # Spread across min-max / rank / z-score normalization: the evidence that
        # the compression is the recipe rather than one arbitrary scaling choice.
        "norm_median": f'{tables["normalization"]["rank_spread"].median():g}',
        "norm_max": f'{tables["normalization"]["rank_spread"].max():g}',

        "min_tau_family": f"{min_tau_family:.2f}",
        "mc_median_width": f'{results["monte_carlo"]["median_interval_width"]:g}',
        "gamma1_ratio": f"{dispersion.at['headline (gamma 1)', 'weight_max_min_ratio']:.1f}",
        "gamma4_ratio": f"{dispersion.at['extreme (gamma 4)', 'weight_max_min_ratio']:.0f}",
        "gamma4_tau": f"{dispersion.at['extreme (gamma 4)', 'kendall_tau_vs_henley']:.2f}",
        "jpn_low": f'{by_iso.at["JPN", "rank_p05"]:g}',
        "jpn_high": f'{by_iso.at["JPN", "rank_p95"]:g}',

        "usa_reaches": str(int(by_iso.at["USA", "reaches"])),
        "usa_admits": str(int(by_iso.at["USA", "admits"])),
        "n_full_open": str(fully_open),
        "gini_henley": f"{ineq['henley']['gini_by_country']:.2f}",
        "gini_balanced": f"{ineq['ahi_balanced']['gini_by_country']:.2f}",
        "gini_gdp": f"{ineq['gdp_share']['gini_by_country']:.2f}",

        "r_squared_pct": str(round(results["regression"]["r_squared"] * 100)),

        "open_unrecip_n": str(open_cluster["members"]) if open_cluster else "—",
        "open_unrecip_admits": str(round(open_cluster["mean_openness_count"])) if open_cluster else "—",
        "open_unrecip_reaches": str(round(open_cluster["mean_breadth"])) if open_cluster else "—",
        "eu_cluster_n": str(community("EU-27")),
        "af_cluster_n": str(community("African Union")),
        "cis_cluster_n": str(community("CIS")),

        "spearman": f"{results['validation']['spearman_rho']:.2f}",
        "rank_spearman": f"{results['validation']['rank_spearman_rho']:.2f}",
        "within_two": str(results["validation"]["within_two_ranks"]),
        "validation_rows": _validation_rows(results),
        "n_reference": str(results["validation"]["n_reference_points"]),
        "tourism_vintage": str(int(registry.at["tourist_arrivals", "median_vintage"])),
        "imputed_pct": f"{non_observed / total_cells * 100:.0f}",
        "imputation_shift": f'{tables["imputation"]["rank_shift"].abs().median():g}',
    }


def _validation_rows(results: dict) -> str:
    """Render the published-vs-reproduced comparison as table rows.

    Built as HTML rather than a figure because the point is the individual
    country-by-country agreement, which a reader wants to scan, not a summary
    statistic they have to take on trust.
    """
    rows = []
    for r in results["validation"]["rows"]:
        rows.append(
            f"<tr><td class=\"name\">{r['country']}</td>"
            f"<td>{r['henley_published_rank']}</td>"
            f"<td>{r['henley_rank']}</td>"
            f"<td>{r['henley_published_score']}</td>"
            f"<td>{r['henley_score']:.0f}</td></tr>")
    return "".join(rows)


def _load_engine() -> dict:
    """Rebuild the live-explorer inputs from the raw edges and features.

    Recomputed rather than round-tripped through a CSV so the browser's engine
    is fed by the same code path the pipeline scores with; a test asserts the
    two agree to the last decimal the site displays.
    """
    from ..features import build_features
    from ..indices import live_engine_inputs
    from ..ingest.access import load_access_edges

    edges = load_access_edges()
    destinations = pd.Index(sorted(edges["destination"].unique()), name="iso3")
    features, _ = build_features(destinations)
    return live_engine_inputs(edges, features)


def build(results: dict) -> None:
    tables = {
        "family": pd.read_csv(TABLES / "04_index_family.csv"),
        "ladder": pd.read_csv(TABLES / "11_ladder_sensitivity.csv"),
        "categories": pd.read_csv(TABLES / "01_access_categories.csv"),
        "agreement": pd.read_csv(TABLES / "14_index_agreement.csv", index_col=0),
        "dispersion": pd.read_csv(TABLES / "16b_weight_dispersion.csv"),
        "weights": pd.read_csv(TABLES / "07_destination_weights.csv"),
        "blocs": pd.read_csv(TABLES / "20_blocs.csv"),
        "datadriven": pd.read_csv(TABLES / "09_datadriven_weights.csv"),
        "divide": pd.read_csv(TABLES / "23_divide_by_income.csv"),
        "provenance": pd.read_csv(TABLES / "02_data_provenance.csv"),
        "registry": pd.read_csv(TABLES / "03_indicator_registry.csv"),
        "imputation": pd.read_csv(TABLES / "13_imputation_sensitivity.csv"),
        "normalization": pd.read_csv(TABLES / "12_normalization_sensitivity.csv"),
    }
    from ..config import PROCESSED
    master = pd.read_csv(PROCESSED / "passport_master.csv")
    features = pd.read_csv(TABLES / "08_destination_features.csv").set_index("iso3")
    engine = _load_engine()

    payload = {
        "meta": results["meta"],
        "countries": _country_payload(master, features, tables["ladder"], engine),
        "series": _series(results, master, tables, engine),
    }

    template = (SITE_ASSETS / "index.template.html").read_text()
    html = (template
            .replace("__CSS__", (SITE_ASSETS / "site.css").read_text())
            .replace("__CHARTS_JS__", (SITE_ASSETS / "charts.js").read_text())
            .replace("__JS__", (SITE_ASSETS / "site.js").read_text())
            .replace("__WORLD_PATHS_JS__", (ASSETS / "world_paths.js").read_text())
            .replace("__MARKERS_JSON__", json.dumps(
                {iso: _project(lon, lat) for iso, (lon, lat) in MARKER_CENTROIDS.items()}))
            .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":"))))

    tokens = _tokens(results, master, tables)
    missing = set(re.findall(r"\{\{(\w+)\}\}", html)) - set(tokens)
    if missing:
        raise KeyError(f"template references undefined tokens: {sorted(missing)}")
    for key, value in tokens.items():
        html = html.replace("{{" + key + "}}", value)

    (DOCS / "index.html").write_text(html)

    figures_out = DOCS / "figures"
    figures_out.mkdir(exist_ok=True)
    for png in FIGURES.glob("*.png"):
        shutil.copy2(png, figures_out / png.name)

    # Machine-readable copies alongside the page, so the site doubles as a
    # small open-data endpoint rather than only a rendering of one.
    data_out = DOCS / "data"
    data_out.mkdir(exist_ok=True)
    (data_out / "passports.json").write_text(json.dumps(payload, indent=1))
    master.to_csv(data_out / "passports.csv", index=False)
    pd.read_csv(PROCESSED / "destination_master.csv").to_csv(
        data_out / "destinations.csv", index=False)
    (DOCS / ".nojekyll").write_text("")

    size_kb = (DOCS / "index.html").stat().st_size / 1024
    print(f"Site: {DOCS / 'index.html'} ({size_kb:.0f} KB, "
          f"{len(payload['countries'])} passports, {len(list(figures_out.glob('*.png')))} figures)")
