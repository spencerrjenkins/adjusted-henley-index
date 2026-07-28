"""Explanatory models: what predicts a passport, and who defies the prediction.

Two complementary questions:

  * **Regression.** How much of a passport's strength is explained by the
    country's own wealth, development, size and institutions? The R-squared is
    the headline: if own-country characteristics explain most of the variance,
    passport strength is mostly a mirror of national development. The residuals
    are the interesting part -- the countries whose mobility is far better or
    worse than their fundamentals predict, which is where diplomacy, history
    and geopolitics show up as a number.

  * **Clustering.** Passports do not vary along one axis. A country can have
    broad but shallow access (many small destinations), narrow but deep access
    (few large ones), or be open while nobody opens to it. k-means on the
    pillar profile finds those regimes without imposing them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from ..config import HEADLINE_LENS, PILLARS, RANDOM_SEED

PREDICTORS = {
    "log_gdp_pc_ppp": "Own GDP per capita (log, PPP)",
    "hdi": "Own Human Development Index",
    "log_population": "Own population (log)",
    "rule_of_law": "Own rule of law (V-Dem)",
    "electoral_democracy": "Own electoral democracy (V-Dem)",
    "trade_openness": "Own trade openness (% of GDP)",
}


def build_design(family: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    design = features.loc[:, ["gdp_pc_ppp", "hdi", "population", "rule_of_law",
                              "electoral_democracy", "trade_openness", "region",
                              "income_group"]].copy()
    design["log_gdp_pc_ppp"] = np.log(design["gdp_pc_ppp"])
    design["log_population"] = np.log(design["population"])
    merged = family.set_index("passport").join(design, how="inner")
    return merged


def fit_strength_model(family: pd.DataFrame, features: pd.DataFrame,
                       target: str = f"ahi_{HEADLINE_LENS}_pct") -> tuple:
    """OLS of passport strength on the passport country's own characteristics.

    Heteroskedasticity-robust (HC3) standard errors, because the residual
    variance is visibly larger among weak passports than strong ones -- there
    are many ways to be excluded and comparatively few ways to be admitted
    everywhere.
    """
    merged = build_design(family, features)
    X = sm.add_constant(merged[list(PREDICTORS)])
    y = merged[target]
    model = sm.OLS(y, X).fit(cov_type="HC3")

    residuals = pd.DataFrame({
        "actual": y,
        "predicted": model.fittedvalues.round(2),
        "residual": model.resid.round(2),
    })
    residuals["overperformance"] = residuals["residual"]
    residuals.index.name = "passport"
    return model, residuals.reset_index().sort_values("residual", ascending=False)


def variance_inflation(family: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Variance inflation factors for the predictors.

    Necessary rather than decorative here: GDP per capita, HDI and rule of law
    are three measurements of substantially the same underlying thing, so
    individual coefficients are not separately identified and should not be read
    as "the effect of wealth holding development constant". The VIFs make the
    scale of that problem explicit instead of leaving the reader to infer it
    from a surprising sign.
    """
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    merged = build_design(family, features)
    X = sm.add_constant(merged[list(PREDICTORS)]).to_numpy()
    names = ["const"] + list(PREDICTORS)
    return pd.DataFrame({
        "term": names,
        "vif": [round(variance_inflation_factor(X, i), 2) for i in range(X.shape[1])],
    })


def coefficient_table(model) -> pd.DataFrame:
    table = pd.DataFrame({
        "term": model.params.index,
        "coefficient": model.params.round(3).to_numpy(),
        "std_error": model.bse.round(3).to_numpy(),
        "t": model.tvalues.round(2).to_numpy(),
        "p_value": model.pvalues.round(4).to_numpy(),
        "ci_low": model.conf_int()[0].round(3).to_numpy(),
        "ci_high": model.conf_int()[1].round(3).to_numpy(),
    })
    table["label"] = table["term"].map(PREDICTORS).fillna("Intercept")
    return table


def cluster_passports(family: pd.DataFrame, contributions: pd.DataFrame,
                      openness: pd.DataFrame, k_range: range = range(2, 9),
                      seed: int = RANDOM_SEED) -> tuple[pd.DataFrame, pd.DataFrame, int, pd.DataFrame]:
    """k-means on the *composition* of each passport's access, not its size.

    Pillar contributions are converted to shares of the passport's own total
    before clustering, so a country is grouped by what kind of world it can
    reach rather than by how much of it. Breadth (destination count) and
    openness (how many admit you) are carried in as extra dimensions because
    they are the axes on which same-sized passports differ most.

    k is chosen by silhouette score over `k_range`.
    """
    profile = contributions.set_index("passport")[list(PILLARS)]
    shares = profile.div(profile.sum(axis=1).clip(lower=1e-9), axis=0)
    shares.columns = [f"share_{p}" for p in PILLARS]

    extras = pd.DataFrame({
        "breadth": family.set_index("passport")["henley_score"],
        "openness": openness.set_index("passport")["openness_count"],
        "attainment": family.set_index("passport")[f"ahi_{HEADLINE_LENS}_pct"],
    })
    matrix = shares.join(extras).dropna()
    scaled = StandardScaler().fit_transform(matrix)

    scores = {}
    for k in k_range:
        labels = KMeans(n_clusters=k, n_init=25, random_state=seed).fit_predict(scaled)
        scores[k] = float(silhouette_score(scaled, labels))

    # Silhouette is maximised at k=2, which recovers the split everyone already
    # knows about -- strong passports and weak ones -- and says nothing new. The
    # typology is therefore taken from the best k of at least three, with the
    # k=2 score still reported so the choice is visible rather than quietly made.
    candidates = {k: v for k, v in scores.items() if k >= 3} or scores
    best_k = max(candidates, key=candidates.get)

    model = KMeans(n_clusters=best_k, n_init=50, random_state=seed).fit(scaled)
    assignment = pd.DataFrame({"passport": matrix.index, "cluster": model.labels_})

    centroids = matrix.assign(cluster=model.labels_).groupby("cluster").mean()
    centroids["members"] = pd.Series(model.labels_).value_counts().sort_index()
    centroids = centroids.round(3).reset_index()

    silhouette = pd.DataFrame({"k": list(scores),
                               "silhouette": [round(v, 4) for v in scores.values()]})
    return assignment, centroids, best_k, silhouette


def label_clusters(assignment: pd.DataFrame, centroids: pd.DataFrame,
                   family: pd.DataFrame) -> pd.DataFrame:
    """Give each cluster a name a reader can hold in their head.

    Named from where the cluster sits on attainment and openness rather than
    from its members, so the label describes the regime rather than being a
    list of examples that then begs the question.
    """
    merged = assignment.merge(family[["passport", f"ahi_{HEADLINE_LENS}_pct"]], on="passport")
    stats = centroids.set_index("cluster")
    tiers = stats["attainment"].rank(ascending=False).astype(int)
    # "Open" and "closed" are relative to the other clusters, not to an absolute
    # threshold -- there is no natural number of nationalities that counts as
    # welcoming, only more or less than everyone else.
    open_median = stats["openness"].median()

    labels, descriptions = {}, {}
    n_tiers = len(stats)
    for cluster in stats.index:
        tier = int(tiers[cluster])
        breadth = float(stats.loc[cluster, "breadth"])
        openness = float(stats.loc[cluster, "openness"])
        balance = breadth - openness
        is_open = openness >= open_median

        if tier == 1:
            labels[cluster] = "Frictionless core"
        elif tier == n_tiers and not is_open:
            labels[cluster] = "Doubly closed"
        elif is_open:
            labels[cluster] = f"Open but unreciprocated (tier {tier})"
        else:
            labels[cluster] = f"Guarded middle (tier {tier})"

        # Descriptions are generated from the centroid rather than written per
        # cluster, so they cannot drift out of agreement with the numbers when
        # the data updates and k lands somewhere else.
        direction = ("runs a mobility surplus of about "
                     f"{abs(balance):.0f} destinations" if balance > 0 else
                     "runs a mobility deficit of about "
                     f"{abs(balance):.0f} destinations")
        descriptions[cluster] = (
            f"Reaches ~{breadth:.0f} destinations without a prior visa and admits "
            f"~{openness:.0f} nationalities on the same terms, so it {direction}.")

    counts = merged["cluster"].value_counts()
    out = pd.DataFrame({
        "cluster": list(labels),
        "label": [labels[c] for c in labels],
        "description": [descriptions[c] for c in labels],
        "members": [int(counts.get(c, 0)) for c in labels],
        "mean_attainment_pct": [round(float(stats.loc[c, "attainment"]), 1) for c in labels],
        "mean_breadth": [round(float(stats.loc[c, "breadth"]), 1) for c in labels],
        "mean_openness_count": [round(float(stats.loc[c, "openness"]), 1) for c in labels],
    })
    return out.sort_values("mean_attainment_pct", ascending=False)
