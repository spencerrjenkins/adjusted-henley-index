"""Tests for the invariants that would silently corrupt the whole index.

These are not coverage tests. Each one guards a mistake that produces a
plausible-looking wrong answer rather than a crash -- the class of bug that
actually ships in analysis code.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ahi.analysis.inequality import gini, lorenz_curve
from ahi.config import ACCESS_LADDERS, INDICATORS, LENSES, PILLARS
from ahi.features import build_features
from ahi.analysis.sensitivity import movement_balance, rank_movement
from ahi.indices import (build_index_family, competition_rank, fractional_rank,
                         henley_rank, lens_weights, openness_frame, score)
from ahi.ingest.access import load_access_edges


@pytest.fixture(scope="session")
def edges():
    return load_access_edges()


@pytest.fixture(scope="session")
def destinations(edges):
    return pd.Index(sorted(edges["destination"].unique()), name="iso3")


@pytest.fixture(scope="session")
def features(destinations):
    frame, _ = build_features(destinations)
    return frame


@pytest.fixture(scope="session")
def family(edges, features):
    frame, _ = build_index_family(edges, features)
    return frame


# ---------------------------------------------------------------------------
# Access parsing
# ---------------------------------------------------------------------------
def test_edge_list_is_complete_and_diagonal_free(edges):
    n = edges["passport"].nunique()
    assert n == 199
    assert len(edges) == n * (n - 1), "every ordered pair except self-pairs"
    assert not (edges["passport"] == edges["destination"]).any()


def test_every_cell_maps_to_a_known_category(edges):
    assert edges["category"].isna().sum() == 0
    assert set(edges["category"]) <= set(ACCESS_LADDERS["graded"])


def test_ladders_are_ordered_consistently():
    """A stricter ladder must never award more credit than a looser one, or the
    three-ladder sensitivity analysis compares incomparable things."""
    for category in ACCESS_LADDERS["graded"]:
        strict = ACCESS_LADDERS["strict"][category]
        graded = ACCESS_LADDERS["graded"][category]
        assert strict <= graded, category


def test_stay_days_present_for_every_frictionless_pair(edges):
    frictionless = edges[edges["credit_graded"] >= 0.7]
    assert frictionless["stay_days"].notna().all()
    assert (frictionless["stay_days"] > 0).all()


# ---------------------------------------------------------------------------
# Ranking conventions
# ---------------------------------------------------------------------------
def test_henley_rank_is_dense():
    """Henley: 'the passport with the next lowest score receives the next
    consecutive rank number, regardless of how many passports occupy the rank
    above'. A three-way tie for first is followed by second."""
    scores = pd.Series({"a": 10.0, "b": 10.0, "c": 10.0, "d": 9.0})
    assert henley_rank(scores).to_dict() == {"a": 1, "b": 1, "c": 1, "d": 2}


def test_competition_rank_skips():
    scores = pd.Series({"a": 10.0, "b": 10.0, "c": 10.0, "d": 9.0})
    assert competition_rank(scores).to_dict() == {"a": 1, "b": 1, "c": 1, "d": 4}


def test_fractional_rank_averages_tied_positions():
    """A three-way tie for first occupies positions 1, 2 and 3, so each member's
    expected position is 2.0 -- not 1 (competition) and not 1 (dense)."""
    scores = pd.Series({"a": 10.0, "b": 10.0, "c": 10.0, "d": 9.0})
    assert fractional_rank(scores).to_dict() == {"a": 2.0, "b": 2.0, "c": 2.0, "d": 4.0}


def test_fractional_ranks_sum_to_the_same_total_whatever_the_ties(family):
    """The property that makes fractional ranks the only tie-neutral basis for
    comparing two indices: the total is n(n+1)/2 regardless of tie structure, so
    differencing two of them cannot introduce a drift."""
    n = len(family)
    expected = n * (n + 1) / 2
    for column in [c for c in family.columns if c.endswith("_frac")]:
        assert family[column].sum() == pytest.approx(expected), column


def test_movement_between_indices_has_no_built_in_drift(family):
    """Henley's integer scores tie 154 of 199 passports; the weighted index ties
    almost none. On competition ranks that asymmetry alone makes roughly twice as
    many passports "fall" as "rise". On fractional ranks it cancels exactly."""
    movement = rank_movement(family)
    balance = movement_balance(movement)
    assert balance["mean_move"] == pytest.approx(0.0, abs=1e-9)
    assert balance["sum_move"] == pytest.approx(0.0, abs=1e-6)
    assert abs(balance["n_down"] - balance["n_up"]) < 0.15 * len(family)

    # And confirm the drift is real on the competition basis, so the test is
    # guarding a live hazard rather than restating an identity.
    naive = family["henley_pos"] - family["ahi_balanced_pos"]
    assert naive.mean() < -0.5
    assert (naive < 0).sum() > (naive > 0).sum()


def test_competition_rank_spans_the_full_field(family):
    """Cross-index comparison is only valid if both indices use a rank scale of
    the same length; dense ranks do not, which is the bug this guards."""
    for column in [c for c in family.columns if c.endswith("_pos")]:
        assert family[column].min() == 1
        assert family[column].max() == len(family), column


def test_ranks_agree_with_scores(family):
    for name in ("henley", "ahi_balanced", "gdp_share"):
        for suffix in ("_pos", "_frac", "_rank"):
            ordered = family.sort_values(f"{name}{suffix}")
            assert ordered[f"{name}_score"].is_monotonic_decreasing, name + suffix


def test_the_three_rank_conventions_are_ordered(family):
    """For any passport: dense <= competition <= fractional-rounded-up. All three
    encode the same ordering; they differ only in how they price a tie."""
    for name in ("henley", "ahi_balanced"):
        assert (family[f"{name}_rank"] <= family[f"{name}_pos"]).all(), name
        assert (family[f"{name}_pos"] <= family[f"{name}_frac"] + 1e-9).all(), name


# ---------------------------------------------------------------------------
# Features and weights
# ---------------------------------------------------------------------------
def test_no_missing_values_survive_imputation(features):
    for indicator in INDICATORS:
        assert features[indicator.key].notna().all(), indicator.key


def test_normalized_indicators_are_bounded_and_directed(features):
    for indicator in INDICATORS:
        column = features[f"n_{indicator.key}"]
        assert column.min() >= -1e-9 and column.max() <= 1 + 1e-9, indicator.key


def test_lower_is_better_indicators_are_flipped(features):
    """Homicide rate has direction -1, so the normalized column must rank a safe
    country above a dangerous one. Getting this backwards would be invisible in
    the composite but would invert the security pillar."""
    safe, dangerous = features["n_homicide_rate"].idxmax(), features["n_homicide_rate"].idxmin()
    assert features.at[safe, "homicide_rate"] < features.at[dangerous, "homicide_rate"]


def test_pillar_scores_are_bounded(features):
    for pillar in PILLARS:
        column = features[f"p_{pillar}"]
        assert column.between(0, 1).all(), pillar


def test_lens_weights_average_to_one(features):
    for lens in LENSES:
        weights = lens_weights(features, lens.key)
        assert weights.mean() == pytest.approx(1.0)
        assert (weights > 0).all()


def test_lens_weight_vectors_sum_to_one():
    for lens in LENSES:
        assert sum(lens.weights.values()) == pytest.approx(1.0), lens.key
        assert set(lens.weights) == set(PILLARS), lens.key


# ---------------------------------------------------------------------------
# Scoring identities
# ---------------------------------------------------------------------------
def test_flat_weights_binary_ladder_reproduces_a_plain_count(edges, features):
    """The whole project rests on the claim that its machinery reduces to
    Henley's when both knobs are set to Henley's positions."""
    ones = pd.Series(1.0, index=features.index)
    computed = score(edges, ones, ladder="binary_henley")
    expected = edges[edges["credit_binary_henley"] == 1].groupby("passport").size()
    pd.testing.assert_series_equal(computed.sort_index(), expected.astype(float).sort_index(),
                                   check_names=False)


def test_share_indices_are_bounded_percentages(family):
    for column in ("gdp_share_score", "pop_share_score"):
        assert family[column].between(0, 100).all(), column


def test_inbound_and_outbound_totals_match(edges, features):
    """Summing the same credits by passport and by destination must give the
    same grand total; if it does not, the graph has been transposed somewhere."""
    ones = pd.Series(1.0, index=features.index)
    out = score(edges, ones, ladder="graded", direction="outbound").sum()
    inb = score(edges, ones, ladder="graded", direction="inbound").sum()
    assert out == pytest.approx(inb)


def test_openness_matches_published_us_figure(edges, features):
    """Henley's Openness Index reports that the United States admits 46
    nationalities without a prior visa. An independent reconstruction landing on
    the same number is the strongest external check available on the inbound
    direction."""
    openness = openness_frame(edges, features).set_index("passport")
    assert openness.at["USA", "openness_count"] == 46


# ---------------------------------------------------------------------------
# Inequality math
# ---------------------------------------------------------------------------
def test_gini_endpoints():
    assert gini(np.ones(50)) == pytest.approx(0.0)
    concentrated = np.zeros(1000)
    concentrated[-1] = 1.0
    assert gini(concentrated) > 0.99


def test_lorenz_curve_is_monotone_and_closes():
    curve = lorenz_curve(pd.Series([1, 2, 3, 4, 5]))
    assert curve["value_share"].is_monotonic_increasing
    assert curve["value_share"].iloc[0] == pytest.approx(0.0)
    assert curve["value_share"].iloc[-1] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_pipeline_is_deterministic(edges, features):
    first, _ = build_index_family(edges, features)
    second, _ = build_index_family(edges, features)
    pd.testing.assert_frame_equal(first, second)
