"""Transport graph for the GIS planner: load GeoJSON, apply a scenario, enumerate feasible paths."""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path as FsPath
from typing import Any

import networkx as nx

from setu.contracts import Scenario

FIXTURES_DIR = FsPath(__file__).resolve().parents[2] / "fixtures"
K_PATHS = 3
REVIEW_DAYS = 7  # R in W = L + R; the forecast side uses the same value


@dataclass(frozen=True)
class Path:
    ref: str
    nodes: tuple[str, ...]
    edge_ids: tuple[str, ...]
    transit_h: float
    cost_per_kg: float


def load_graph_geojson(path: str | FsPath | None = None) -> dict:
    return json.loads(FsPath(path or FIXTURES_DIR / "graph.geojson").read_text(encoding="utf-8"))


def load_scenarios(path: str | FsPath | None = None) -> dict[str, Scenario]:
    raw = json.loads(FsPath(path or FIXTURES_DIR / "scenarios.json").read_text(encoding="utf-8"))
    return {s["scenario_id"]: Scenario.model_validate(s) for s in raw}



def build_graph(geojson: dict) -> nx.Graph:
    """Undirected: a corridor works both ways and shares one capacity_kg."""
    G = nx.Graph()
    features = geojson["features"]
    for f in features:
        if f["geometry"]["type"] == "Point":
            p = f["properties"]
            G.add_node(p["node_id"], site_id=p.get("site_id"), label=p.get("label", p["node_id"]),
                       coordinates=f["geometry"]["coordinates"])
    for f in features:
        if f["geometry"]["type"] == "LineString":
            p = f["properties"]
            G.add_edge(
                p["from_node"], p["to_node"],
                edge_id=p["edge_id"], transit_h=float(p["transit_h"]),
                capacity_kg=float(p["capacity_kg"]), cost_per_kg=float(p["cost_per_kg"]),
                base_capacity_kg=float(p["capacity_kg"]),
            )
    return G


def edges_by_id(G: nx.Graph) -> dict[str, dict]:
    return {d["edge_id"]: d for _, _, d in G.edges(data=True)}


def base_lead_days(geojson: dict) -> dict[str, int]:
    """L per depot = ceil(shortest transit_h to the nearest OTHER depot on the nominal graph / 24)."""
    G = build_graph(geojson)
    out: dict[str, int] = {}
    for node, site in G.nodes(data="site_id"):
        if site is None:
            continue
        dist = nx.single_source_dijkstra_path_length(G, node, weight="transit_h")
        others = [d for n, d in dist.items() if n != node and G.nodes[n]["site_id"]]
        if not others:
            raise ValueError(f"Depot {site} cannot reach any other depot on the base graph")
        out[site] = math.ceil(min(others) / 24)
    return out


def apply_scenario(G: nx.Graph, scenario: Scenario) -> nx.Graph:
    """Return a copy with closed edges removed, capacities scaled and delays added."""
    known = set(edges_by_id(G))
    unknown = (set(scenario.closed_edges) | set(scenario.capacity_factor) | set(scenario.delay_h)) - known
    if unknown:
        raise ValueError(f"Scenario {scenario.scenario_id} references unknown edges: {sorted(unknown)}")
    S = G.copy()
    for u, v, d in list(S.edges(data=True)):
        eid = d["edge_id"]
        if eid in scenario.closed_edges:
            S.remove_edge(u, v)
            continue
        d["capacity_kg"] = d["capacity_kg"] * scenario.capacity_factor.get(eid, 1.0)
        d["transit_h"] = d["transit_h"] + scenario.delay_h.get(eid, 0.0)
    return S


def load_base_graph(geojson_path: str | Path | None = None) -> nx.Graph:
    """Load base graph from GeoJSON."""
    data = load_graph_geojson(geojson_path)
    return build_graph(data)


def compute_base_lead_times(graph: nx.Graph | None = None, sites: list[Any] | None = None) -> dict[str, int]:
    """Compute base lead time L in whole days per depot on nominal graph."""
    data = load_graph_geojson()
    return base_lead_days(data)


def candidate_paths(G: nx.Graph, src: str, dst: str, window_h: float, label: str = "P", k: int = K_PATHS) -> list[Path]:
    """Up to k shortest simple paths (by transit_h) that arrive within window_h."""
    out: list[Path] = []
    if src == dst or src not in G or dst not in G:
        return out
    try:
        for rank, nodes in enumerate(itertools.islice(nx.shortest_simple_paths(G, src, dst, weight="transit_h"), k), 1):
            edges = [G[a][b] for a, b in zip(nodes, nodes[1:])]
            transit = sum(e["transit_h"] for e in edges)
            if transit > window_h:
                break  # paths come shortest-first, the rest are later still
            out.append(Path(
                ref=f"{label}:{rank}", nodes=tuple(nodes),
                edge_ids=tuple(e["edge_id"] for e in edges),
                transit_h=transit, cost_per_kg=sum(e["cost_per_kg"] for e in edges),
            ))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass
    return out


def find_feasible_paths(
    graph: nx.Graph,
    source_node: str,
    dest_node: str,
    max_transit_h: float,
    k: int = K_PATHS,
) -> list[dict]:

    """Find up to k shortest simple paths arriving strictly within max_transit_h."""
    paths = candidate_paths(graph, source_node, dest_node, max_transit_h, label=f"PATH-{source_node}-{dest_node}", k=k)
    out = []
    for p in paths:
        # Compute bottleneck edge capacity
        min_cap = float("inf")
        for u, v in zip(p.nodes, p.nodes[1:]):
            if graph.has_edge(u, v):
                min_cap = min(min_cap, float(graph[u][v].get("capacity_kg", float("inf"))))
        out.append({
            "path_ref": p.ref,
            "nodes": list(p.nodes),
            "edge_ids": list(p.edge_ids),
            "transit_h": p.transit_h,
            "cost_per_kg": p.cost_per_kg,
            "bottleneck_capacity_kg": min_cap,
        })
    return out
