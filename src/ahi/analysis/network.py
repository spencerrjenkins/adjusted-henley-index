"""The visa system as a directed graph.

An index gives every country one number. The underlying object is a 199-node
directed network with ~39,000 edges, and most of what is interesting about
global mobility is a property of the network rather than of any node's score:
who reciprocates with whom, which clusters admit each other freely, and how far
a country's inbound openness diverges from its outbound reach.

This is also where the "mobility divide" literature (Mau et al. 2015; Recchi
et al. 2021) becomes measurable rather than rhetorical: the divide is the claim
that the graph has become more asymmetric over time, and asymmetry is an edge
property you can count.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from ..config import BLOCS, DEFAULT_LADDER, RANDOM_SEED


def build_graph(edges: pd.DataFrame, ladder: str = DEFAULT_LADDER,
                threshold: float = 0.7) -> nx.DiGraph:
    """Directed graph with an edge p -> d where the passport gets at least
    `threshold` credit. At the default this means visa-free, visa-on-arrival or
    eTA -- everything that does not require asking permission before you fly.
    """
    keep = edges[edges[f"credit_{ladder}"] >= threshold]
    graph = nx.from_pandas_edgelist(keep, "passport", "destination",
                                    edge_attr=[f"credit_{ladder}"], create_using=nx.DiGraph)
    graph.add_nodes_from(pd.unique(edges[["passport", "destination"]].to_numpy().ravel()))
    return graph


def reciprocity_table(edges: pd.DataFrame, features: pd.DataFrame,
                      ladder: str = DEFAULT_LADDER, threshold: float = 0.7) -> pd.DataFrame:
    """Per-country outbound reach, inbound openness, and the gap between them.

    The gap is the number the Henley discussion keeps circling without naming:
    the United States can enter ~180 places without a prior visa and admits
    citizens of 46 without one. A country can run a large surplus only if others
    are willing to be net creditors to it, which makes the surplus a measure of
    diplomatic standing rather than of policy.
    """
    keep = edges[edges[f"credit_{ladder}"] >= threshold]
    outbound = keep.groupby("passport").size().rename("reaches")
    inbound = keep.groupby("destination").size().rename("admits")

    pairs = set(zip(keep["passport"], keep["destination"]))
    mutual = pd.Series({
        country: sum(1 for other in features.index
                     if (country, other) in pairs and (other, country) in pairs)
        for country in features.index
    }, name="mutual")

    table = pd.concat([outbound, inbound, mutual], axis=1).fillna(0).astype(int)
    table["mobility_balance"] = table["reaches"] - table["admits"]
    # Of the places you can go, what share lets you in as freely as you let them?
    table["reciprocated_share"] = np.where(
        table["reaches"] > 0, (table["mutual"] / table["reaches"] * 100).round(1), np.nan)
    table["one_way_out"] = table["reaches"] - table["mutual"]   # you go, they can't come
    table["one_way_in"] = table["admits"] - table["mutual"]     # they come, you can't go
    table.index.name = "country"
    return table.reset_index()


def centrality_table(graph: nx.DiGraph) -> pd.DataFrame:
    """Structural position in the network, beyond raw degree.

    PageRank on the reversed graph asks "how much visa-free access flows *to*
    this destination, weighted by how well-connected the passports granting it
    are" -- a destination that is open to strong passports scores higher than
    one open to the same number of weak ones. Betweenness identifies countries
    that bridge otherwise-separate mobility clusters.
    """
    reverse = graph.reverse(copy=True)
    table = pd.DataFrame({
        "pagerank_as_destination": pd.Series(nx.pagerank(reverse, alpha=0.85)),
        "pagerank_as_passport": pd.Series(nx.pagerank(graph, alpha=0.85)),
        "in_degree": pd.Series(dict(graph.in_degree())),
        "out_degree": pd.Series(dict(graph.out_degree())),
        "betweenness": pd.Series(nx.betweenness_centrality(graph, k=None, normalized=True)),
    })
    table["hub_authority_gap"] = table["pagerank_as_passport"] - table["pagerank_as_destination"]
    table.index.name = "country"
    return table.reset_index()


def mutual_communities(edges: pd.DataFrame, ladder: str = DEFAULT_LADDER,
                       threshold: float = 0.7, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Communities in the *mutual* (undirected) access graph.

    Restricting to reciprocal pairs before clustering is the point: one-way
    access is a favor, mutual access is a relationship, and only the second
    forms blocs. Louvain then finds them without being told that the EU or the
    Gulf exist -- if the algorithm rediscovers Schengen from nothing but who
    lets whom in, that is a real result about how mobility is organized.
    """
    keep = edges[edges[f"credit_{ladder}"] >= threshold]
    pairs = set(zip(keep["passport"], keep["destination"]))
    # Sorted, not set-ordered. Python randomizes string hashing per process, so
    # iterating a set of ISO codes gives a different node insertion order on
    # every run -- and Louvain's output depends on it, which made the community
    # numbering shuffle between otherwise identical runs despite the fixed seed.
    mutual_edges = sorted((a, b) for (a, b) in pairs if (b, a) in pairs and a < b)

    graph = nx.Graph()
    graph.add_nodes_from(sorted(pd.unique(edges[["passport", "destination"]].to_numpy().ravel())))
    graph.add_edges_from(mutual_edges)

    communities = nx.community.louvain_communities(graph, seed=seed, resolution=1.0)
    # Louvain returns sets. Ordering them by size alone leaves equal-sized
    # communities in arbitrary order, and iterating a set of ISO codes is
    # process-dependent -- both of which reshuffle the community numbering
    # between identical runs. Break every tie deterministically.
    ordered = sorted(communities, key=lambda members: (-len(members), min(members)))
    rows = [
        {"country": country, "community": i, "community_size": len(members)}
        for i, members in enumerate(ordered)
        for country in sorted(members)
    ]
    table = pd.DataFrame(rows)

    # Name each community after the bloc it overlaps most, so the output is
    # readable without a lookup: a cluster is only interesting if you can say
    # what it turned out to be.
    labels = {}
    for community, group in table.groupby("community"):
        members = set(group["country"])
        best_bloc, best_overlap = "Unaligned", 0.0
        for bloc, bloc_members in BLOCS.items():
            overlap = len(members & set(bloc_members)) / max(len(bloc_members), 1)
            if overlap > best_overlap:
                best_bloc, best_overlap = bloc, overlap
        labels[community] = f"{best_bloc}-aligned" if best_overlap >= 0.5 else f"Cluster {community + 1}"
    table["community_label"] = table["community"].map(labels)
    return table


def bloc_summary(edges: pd.DataFrame, features: pd.DataFrame,
                 ladder: str = DEFAULT_LADDER, threshold: float = 0.7) -> pd.DataFrame:
    """Internal cohesion and external reach per political bloc.

    `internal_density` is the share of within-bloc ordered pairs that are
    frictionless -- how much of a free-movement area the bloc actually is,
    which is not the same as what its treaties say.
    """
    keep = edges[edges[f"credit_{ladder}"] >= threshold]
    pairs = set(zip(keep["passport"], keep["destination"]))
    rows = []
    for bloc, members in BLOCS.items():
        present = [m for m in members if m in features.index]
        n = len(present)
        if n < 2:
            continue
        internal = sum(1 for a in present for b in present if a != b and (a, b) in pairs)
        external = sum(1 for a in present for b in features.index
                       if b not in present and (a, b) in pairs)
        rows.append({
            "bloc": bloc,
            "members_in_data": n,
            "internal_density": round(internal / (n * (n - 1)) * 100, 1),
            "mean_external_reach": round(external / n, 1),
        })
    return pd.DataFrame(rows).sort_values("internal_density", ascending=False)


def asymmetry_pairs(edges: pd.DataFrame, features: pd.DataFrame,
                    ladder: str = DEFAULT_LADDER, threshold: float = 0.7,
                    top_n: int = 25) -> pd.DataFrame:
    """The most lopsided bilateral relationships, weighted by how much traffic
    the asymmetry actually affects.

    A one-way relationship between two microstates is a curiosity; a one-way
    relationship between two large economies is a policy. Ranking by the
    combined population of the pair surfaces the second.
    """
    keep = edges[edges[f"credit_{ladder}"] >= threshold]
    pairs = set(zip(keep["passport"], keep["destination"]))
    population = features["population"]
    # Sorted for the same reason as above: set iteration order is not stable
    # across processes, and ties in the population ranking would reshuffle.
    rows = [
        {"can_enter": a, "cannot_be_entered_by": b,
         "pop_a": population.get(a, np.nan), "pop_b": population.get(b, np.nan)}
        for a, b in sorted(pairs) if (b, a) not in pairs
    ]
    table = pd.DataFrame(rows)
    table["combined_population"] = table["pop_a"] + table["pop_b"]
    return table.nlargest(top_n, "combined_population").reset_index(drop=True)
