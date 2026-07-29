"""The index family.

Every passport index in existence is the same expression:

    score(p) = sum over destinations d of  credit(p -> d) * weight(d)

Henley sets `credit` to a binary and `weight` to 1 for every destination on
Earth. That is not the absence of a modeling choice, it is a strong one: it
asserts that reaching Kiribati and reaching the United States are worth exactly
the same. This module makes both terms explicit and then varies them, so the
question stops being "what is the right index" and becomes "which conclusions
survive changing it".

Three families are computed:

  * **Judgment-weighted** -- the five lenses in `config.LENSES`, each a
    defensible answer to a different question about whose mobility we mean.
  * **Data-driven** -- PCA and entropy weights, which nobody chose. They are the
    control group: if the analyst-set weights produce the same story as weights
    derived mechanically from the covariance structure, the story is not an
    artifact of the analyst.
  * **Unit-denominated** -- share of world GDP and share of world population
    reachable, plus permitted person-days. These need no weighting scheme at
    all, and are the most literally interpretable numbers in the project.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from .config import (ACCESS_LADDERS, DEFAULT_LADDER, HEADLINE_LENS, INDICATORS,
                     LENSES, PILLARS, RANDOM_SEED, STAY_DAYS_CAP)


# ---------------------------------------------------------------------------
# Destination weighting schemes
# ---------------------------------------------------------------------------
def lens_weights(features: pd.DataFrame, lens_key: str, pillar_weights: dict[str, float] | None = None) -> pd.Series:
    """Composite destination weight under one lens, mean-normalized to 1.0.

    Mean-normalization is what keeps the adjusted score on the same scale as the
    raw count: a passport whose destinations are all exactly average scores the
    same as it would under Henley, and any deviation is a statement about the
    *composition* of its access rather than the size of it.
    """
    from .config import LENS_BY_KEY
    weights = pillar_weights if pillar_weights is not None else LENS_BY_KEY[lens_key].weights
    raw = sum(features[f"p_{pillar}"] * w for pillar, w in weights.items())
    return raw / raw.mean()


def pca_weights(features: pd.DataFrame) -> tuple[pd.Series, pd.Series, float]:
    """Weights from the first principal component of the indicator matrix.

    Following the factor-analysis approach in the OECD/JRC handbook: weight each
    indicator in proportion to its squared loading on the first component, which
    is the direction along which destinations differ most. No analyst opinion
    enters, which is the point -- it is a check on the hand-set weights, not a
    better answer, because "the axis of maximum variance" is not the same thing
    as "what a traveler values".
    """
    cols = [f"n_{ind.key}" for ind in INDICATORS]
    matrix = features[cols].to_numpy()
    centered = (matrix - matrix.mean(axis=0)) / matrix.std(axis=0, ddof=0)
    pca = PCA(n_components=1, random_state=RANDOM_SEED).fit(centered)
    loadings = pca.components_[0]
    if loadings.sum() < 0:            # sign of a component is arbitrary
        loadings = -loadings
    w = pd.Series(loadings ** 2, index=[ind.key for ind in INDICATORS])
    w = w / w.sum()
    composite = features[cols].to_numpy() @ w.to_numpy()
    weight = pd.Series(composite, index=features.index)
    return weight / weight.mean(), pd.Series(loadings, index=w.index), float(pca.explained_variance_ratio_[0])


def entropy_weights(features: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Shannon-entropy weights (the standard objective scheme in the
    multi-criteria decision literature).

    An indicator on which every destination scores about the same carries little
    information and gets little weight; one that separates destinations sharply
    gets more. Like PCA this is a control, not a truth: it rewards dispersion,
    which is a property of the measurement, not of what matters.
    """
    cols = [f"n_{ind.key}" for ind in INDICATORS]
    x = features[cols].clip(lower=1e-9)
    p = x / x.sum(axis=0)
    n = len(x)
    entropy = -(p * np.log(p)).sum(axis=0) / np.log(n)
    divergence = 1 - entropy
    w = divergence / divergence.sum()
    w.index = [c[2:] for c in cols]
    composite = (features[cols].to_numpy() @ w.to_numpy())
    weight = pd.Series(composite, index=features.index)
    return weight / weight.mean(), w


def unit_weights(features: pd.DataFrame, column: str) -> pd.Series:
    """Weight proportional to a raw quantity (GDP, people), scaled so the index
    reads as a *share of the world total* -- no normalization choices at all."""
    values = features[column].astype(float)
    return values / values.sum()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score(edges: pd.DataFrame, dest_weight: pd.Series, ladder: str = DEFAULT_LADDER,
          direction: str = "outbound") -> pd.Series:
    """Sum of (credit x destination weight) over all destinations.

    `direction="inbound"` flips the graph: instead of "how much world can this
    passport reach", it answers "how much of the world can reach this country",
    which is the openness side of the reciprocity question.
    """
    group_col, weight_col = ("passport", "destination") if direction == "outbound" else ("destination", "passport")
    credit = edges[f"credit_{ladder}"]
    w = edges[weight_col].map(dest_weight)
    contribution = credit * w
    return contribution.groupby(edges[group_col]).sum()


def henley_rank(scores: pd.Series, decimals: int = 1) -> pd.Series:
    """Rank under Henley's published convention.

    Henley uses *dense* ranking: "the passport with the next lowest score
    receives the next consecutive rank number, regardless of how many passports
    occupy the rank above". So a five-way tie for 3rd is followed by 4th, not
    8th -- which is why their published table can show a country at rank 10 with
    36 passports ahead of it. Competition ranking (pandas' `method="min"`) is
    the more common convention and gives visibly different numbers; matching
    Henley matters because the whole project is a comparison against them.

    Scores are rounded before ranking so that two passports displayed as the
    same number always share a rank instead of being split by float noise.
    """
    return scores.round(decimals).rank(ascending=False, method="dense").astype(int)


def competition_rank(scores: pd.Series, decimals: int = 1) -> pd.Series:
    """Standard competition ranking ("1224"): ties share a rank and the next
    rank skips ahead by the size of the tie.

    This is the intuitive reading of "what position is this passport in", and it
    is what the tables and the website display. It exists because dense ranks are
    *not comparable across indices*: Henley's scores are integers, so 199
    passports compress into about 100 distinct dense ranks, while a weighted
    score is continuous and spreads them across 199. Under dense ranking the
    world's weakest passport is "97th" on one index and "171st" on the other
    while being last on both.

    It is still the wrong basis for measuring *movement* -- see
    `fractional_rank`.
    """
    return scores.round(decimals).rank(ascending=False, method="min").astype(int)


def fractional_rank(scores: pd.Series, decimals: int = 1) -> pd.Series:
    """Average ("fractional") ranking: a tie occupying positions p..p+k-1 gives
    every member p + (k-1)/2.

    This is the only convention under which two indices with different tie
    structures can be compared without a built-in drift, and it is what every
    movement figure in this project uses.

    Why competition ranking is not enough. It awards every member of a tie the
    *best* position in the group: thirteen passports tied on 160 destinations all
    become 6th, when between them they actually occupy positions 6 through 18.
    Because 154 of the 199 passports sit in some tie under Henley's integer
    scores, and almost none do under a continuous weighted score, simply
    resolving those ties can only push members downward. The result is a
    systematic drift -- mean movement of about -1 rank, 104 passports "falling"
    against 54 "rising" -- that is arithmetic about ties, not a finding about
    passports.

    Averaging removes it exactly. The sum of fractional ranks is n(n+1)/2 for
    *any* tie structure, so both indices sit on the same total and the mean
    movement is zero by construction; what remains is real reordering. Under
    Henley's scores the thirteen-way tie lands at 12.0, which is the expected
    position of a member of that group if the tie were broken at random.
    """
    return scores.round(decimals).rank(ascending=False, method="average")


def score_frame(edges: pd.DataFrame, dest_weight: pd.Series, name: str,
                ladder: str = DEFAULT_LADDER, decimals: int = 1) -> pd.DataFrame:
    """Score, rank, and attainment percentage for one index variant.

    `_pct` is the score as a share of the maximum attainable one -- full credit
    at every destination on Earth. Raw scores are not comparable across ladders
    (the graded ladder hands out partial credit the binary one does not, so its
    ceiling is higher), and `_pct` is what makes the variants readable side by
    side on one axis.
    """
    s = score(edges, dest_weight, ladder=ladder).round(decimals)
    # Each passport's ceiling excludes its own country, which is not a
    # destination it can hold a visa right to.
    universe = dest_weight.reindex(sorted(edges["destination"].unique())).fillna(0.0)
    top_credit = max(ACCESS_LADDERS[ladder].values())
    ceiling = (universe.sum() - universe.reindex(s.index).fillna(0.0)) * top_credit
    return pd.DataFrame({
        f"{name}_score": s,
        f"{name}_rank": henley_rank(s, decimals=decimals),
        f"{name}_pos": competition_rank(s, decimals=decimals),
        f"{name}_frac": fractional_rank(s, decimals=decimals),
        f"{name}_pct": (s / ceiling * 100).round(2),
    })


# ---------------------------------------------------------------------------
# The whole family, in one table
# ---------------------------------------------------------------------------
def build_index_family(edges: pd.DataFrame, features: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Compute every index variant on the same edge list and return them joined
    on passport, plus a diagnostics dict describing how the weights were set."""
    diagnostics: dict[str, object] = {}
    frames: list[pd.DataFrame] = []

    ones = pd.Series(1.0, index=features.index)

    # -- Baselines ---------------------------------------------------------
    # Henley's own index, reproduced: binary credit, every destination worth 1.
    frames.append(score_frame(edges, ones, "henley", ladder="binary_henley"))
    # Same flat weighting, graded credit: isolates the effect of the friction
    # ladder alone, with destination weighting held out.
    frames.append(score_frame(edges, ones, "graded_count", ladder="graded"))
    # Same destination weighting, binary credit: isolates the effect of the
    # weighting alone. Between them these two bracket the headline index.
    headline_w = lens_weights(features, HEADLINE_LENS)
    frames.append(score_frame(edges, headline_w, "binary_weighted", ladder="binary_henley"))

    # -- Judgment-weighted lenses ----------------------------------------
    weight_table = pd.DataFrame(index=features.index)
    for lens in LENSES:
        w = lens_weights(features, lens.key)
        weight_table[lens.key] = w
        frames.append(score_frame(edges, w, f"ahi_{lens.key}"))

    # -- Data-driven ------------------------------------------------------
    w_pca, loadings, explained = pca_weights(features)
    weight_table["pca"] = w_pca
    frames.append(score_frame(edges, w_pca, "ahi_pca"))
    diagnostics["pca_loadings"] = loadings
    diagnostics["pca_explained_variance"] = explained

    w_entropy, entropy_w = entropy_weights(features)
    weight_table["entropy"] = w_entropy
    frames.append(score_frame(edges, w_entropy, "ahi_entropy"))
    diagnostics["entropy_weights"] = entropy_w

    # -- Unit-denominated -------------------------------------------------
    # These read directly as percentages of the world, so they need no scale
    # convention and no defense of a weighting choice. Computed on the binary
    # ladder specifically so the number means what it says: the share of world
    # GDP (or population) you can reach without asking anyone's permission.
    # Partial credit would make it a share of nothing in particular.
    for column, name in (("gdp_total_ppp", "gdp_share"), ("population", "pop_share")):
        share = (score(edges, unit_weights(features, column), ladder="binary_henley") * 100).round(2)
        frames.append(pd.DataFrame({f"{name}_score": share,
                                    f"{name}_rank": henley_rank(share, decimals=2),
                                    f"{name}_pos": competition_rank(share, decimals=2),
                                    f"{name}_frac": fractional_rank(share, decimals=2)}))

    # -- Weight dispersion -------------------------------------------------
    # Averaging fifteen min-max-scaled indicators into six pillars and six
    # pillars into one composite is a variance sink: the resulting destination
    # weights span only about 3.5x from Germany to Burundi, which is a much
    # narrower claim than "some destinations are worth far more than others".
    # Raising the composite to a power before mean-normalizing stretches or
    # compresses that spread without changing the ordering, and asking whether
    # the conclusions move is a cleaner test than arguing about the ratio.
    for gamma, tag in ((0.5, "flat"), (2.0, "sharp"), (4.0, "extreme")):
        stretched = lens_weights(features, HEADLINE_LENS) ** gamma
        stretched = stretched / stretched.mean()
        weight_table[f"gamma_{tag}"] = stretched
        frames.append(score_frame(edges, stretched, f"ahi_gamma_{tag}"))

    # Permitted person-days: the dimension the published indices discard. A
    # 90-day Schengen right and a 14-day visa-on-arrival are one point each in
    # every ranking on the market; here they are not.
    days = edges["stay_days"].clip(upper=STAY_DAYS_CAP) * edges["credit_graded"]
    day_score = days.groupby(edges["passport"]).sum().round(0)
    frames.append(pd.DataFrame({"stay_days_score": day_score,
                                "stay_days_rank": henley_rank(day_score, decimals=0),
                                "stay_days_pos": competition_rank(day_score, decimals=0),
                                "stay_days_frac": fractional_rank(day_score, decimals=0)}))

    family = pd.concat(frames, axis=1)
    family.index.name = "passport"
    diagnostics["weight_table"] = weight_table
    return family.reset_index(), diagnostics


def pillar_contributions(edges: pd.DataFrame, features: pd.DataFrame,
                         lens_key: str = HEADLINE_LENS,
                         ladder: str = DEFAULT_LADDER) -> pd.DataFrame:
    """Decompose each passport's headline score into the six pillars.

    Answers "*what kind* of access does this passport buy" rather than "how
    much": two passports with the same total can be built out of completely
    different worlds, and this is what makes that visible.
    """
    from .config import LENS_BY_KEY
    weights = LENS_BY_KEY[lens_key].weights
    denom = sum(features[f"p_{p}"] * w for p, w in weights.items()).mean()

    out = {}
    credit = edges[f"credit_{ladder}"]
    for pillar in PILLARS:
        per_dest = features[f"p_{pillar}"] * weights[pillar] / denom
        contribution = credit * edges["destination"].map(per_dest)
        out[pillar] = contribution.groupby(edges["passport"]).sum()
    frame = pd.DataFrame(out)
    frame.index.name = "passport"
    return frame.reset_index()


def live_engine_inputs(edges: pd.DataFrame, features: pd.DataFrame,
                       ladder: str = DEFAULT_LADDER) -> dict:
    """The minimum a browser needs to recompute the whole index from scratch.

    The composite is linear in the pillar weights, which means the entire index
    collapses to six numbers per passport. Writing the score out in full:

        score(p, w) = SUM_d credit(p,d) * SUM_i w_i * pillar_i(d)
                      -------------------------------------------
                              mean_d SUM_i w_i * pillar_i(d)

    the weights factor straight out of both sums:

        score(p, w) = N * SUM_i w_i * C_i(p)  /  SUM_i w_i * T_i

    where C_i(p) = SUM_d credit(p,d) * pillar_i(d) is fixed per passport and
    T_i = SUM_d pillar_i(d) is a global constant. Attainment is even cleaner --
    the mean-normalisation cancels entirely:

        pct(p, w) = 100 * SUM_i w_i * C_i(p) / SUM_i w_i * (T_i - own_i(p))

    So 199 x 6 contributions plus two vectors of six reproduce every lens
    exactly, and any weighting a reader invents, at a few thousand
    multiply-adds. Sending the 39,402-edge matrix to the browser would be three
    orders of magnitude more data to compute the same thing.
    """
    credit = edges[f"credit_{ladder}"]
    contributions = {}
    for pillar in PILLARS:
        values = features[f"p_{pillar}"]
        contributions[pillar] = (credit * edges["destination"].map(values)
                                 ).groupby(edges["passport"]).sum()
    frame = pd.DataFrame(contributions)
    frame.index.name = "passport"
    return {
        "contributions": frame.round(4),
        "totals": {p: round(float(features[f"p_{p}"].sum()), 4) for p in PILLARS},
        "own": features[[f"p_{p}" for p in PILLARS]].round(4).rename(
            columns={f"p_{p}": p for p in PILLARS}),
        "n_destinations": int(features.shape[0]),
    }


def pillar_attainment(edges: pd.DataFrame, features: pd.DataFrame,
                      ladder: str = DEFAULT_LADDER) -> pd.DataFrame:
    """Share of the *world's* total value in each pillar that a passport reaches.

    Deliberately independent of any lens: the denominator is the sum of that
    pillar's scores over every destination, so the number answers "how much of
    the planet's economic weight / safety / draw is open to you" without a
    weighting choice in sight.

    This is the diagnostic that shows composition. Expressing each passport's
    score as *shares of its own total* does not: because pillar scores are
    distributed similarly across destinations, every passport's share vector
    comes out near the global average and the chart says nothing. Attainment
    against the world total varies from 8% to 95% and separates passports that
    are strong in different directions.
    """
    credit = edges[f"credit_{ladder}"]
    out = {}
    for pillar in PILLARS:
        values = features[f"p_{pillar}"]
        world_total = values.sum()
        contribution = credit * edges["destination"].map(values)
        out[f"att_{pillar}"] = contribution.groupby(edges["passport"]).sum() / world_total * 100
    frame = pd.DataFrame(out).round(2)
    frame["att_overall"] = frame[[f"att_{p}" for p in PILLARS]].mean(axis=1).round(2)
    # Tilt: how far above or below its own average this passport reaches on each
    # pillar. Isolates the *shape* of a passport from its size.
    for pillar in PILLARS:
        frame[f"tilt_{pillar}"] = (frame[f"att_{pillar}"] - frame["att_overall"]).round(2)
    frame.index.name = "passport"
    return frame.reset_index()


def openness_frame(edges: pd.DataFrame, features: pd.DataFrame,
                   ladder: str = DEFAULT_LADDER) -> pd.DataFrame:
    """The inbound mirror: how open is each country to everyone else?

    Two versions. `openness_count` is Henley's own Openness Index -- how many
    nationalities you admit without a prior visa. `openness_people` weights each
    admitted nationality by its population, which is a materially different
    question: admitting India and admitting Nauru are one point each in the
    count, and 1.4 billion versus twelve thousand people in reality.
    """
    ones = pd.Series(1.0, index=features.index)
    count = score(edges, ones, ladder="binary_henley", direction="inbound")
    graded = score(edges, ones, ladder=ladder, direction="inbound")
    people = score(edges, unit_weights(features, "population"),
                   ladder=ladder, direction="inbound") * 100

    frame = pd.DataFrame({
        "openness_count": count,
        "openness_graded": graded.round(1),
        "openness_people_pct": people.round(2),
    })
    frame["openness_rank"] = henley_rank(frame["openness_count"], decimals=0)
    frame["openness_pos"] = competition_rank(frame["openness_count"], decimals=0)
    frame["openness_frac"] = fractional_rank(frame["openness_count"], decimals=0)
    frame.index.name = "passport"
    return frame.reset_index()
