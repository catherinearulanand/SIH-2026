"""Factual attribution and GeoJSON visualization layer generator for Setu Supply Track 2."""

import networkx as nx
from setu.contracts import Allocation, Scenario, UnmetLine


def explain_plan_diff(
    scenario: Scenario,
    allocations: list[Allocation],
    unmet_lines: list[UnmetLine],
    binding_constraints: list[str],
    base_path_refs: dict[str, list[str]] | None = None,
    base_used_paths: set[str] | None = None,
) -> list[str]:
    """Generate factual causal attributions without inventing reasons."""
    explanations: list[str] = []

    # Scenario header
    explanations.append(
        f"[Hypothetical - Scenario: {scenario.label}] Disruption analysis under scenario '{scenario.scenario_id}'."
    )

    # Closed edges
    if scenario.closed_edges:
        for eid in scenario.closed_edges:
            affected = []
            if base_path_refs:
                affected = [
                    r for r, edges in base_path_refs.items()
                    if eid in edges and (base_used_paths is None or r in base_used_paths)
                ]

            if affected:
                for r in affected:
                    explanations.append(
                        f"[Hypothetical - Scenario: {scenario.label}] Previous path {r} used closed edge {eid}; rerouting required."
                    )
            else:
                explanations.append(
                    f"[Hypothetical - Scenario: {scenario.label}] Corridor {eid} was closed in this scenario."
                )

    # Delays
    if scenario.delay_h:
        for eid, delay in scenario.delay_h.items():
            affected = []
            if base_path_refs:
                affected = [
                    r for r, edges in base_path_refs.items()
                    if eid in edges and (base_used_paths is None or r in base_used_paths)
                ]
            if affected:
                explanations.append(
                    f"[Hypothetical - Scenario: {scenario.label}] Transit delay on edge {eid} (+{delay:.1f}h) caused paths using it to exceed delivery window."
                )
            else:
                explanations.append(
                    f"[Hypothetical - Scenario: {scenario.label}] Transit delay of +{delay:.1f}h applied on edge {eid}."
                )


    # Capacity reductions
    if scenario.capacity_factor:
        for eid, factor in scenario.capacity_factor.items():
            explanations.append(
                f"[Hypothetical - Scenario: {scenario.label}] Edge {eid} capacity constrained by factor {factor:.2f}."
            )

    # Demand surge
    if scenario.demand_factor:
        surge_str = ", ".join(f"{k}: {v}x" for k, v in scenario.demand_factor.items())
        explanations.append(
            f"[Hypothetical - Scenario: {scenario.label}] Demand surge applied: {surge_str}."
        )

    # Binding bottleneck constraints
    if binding_constraints:
        for bc in binding_constraints:
            explanations.append(f"[Constraint] Binding bottleneck constraint: {bc}.")

    # Unmet breakdown
    cap_gaps = [u for u in unmet_lines if u.reason == "capacity_gap"]
    supply_shorts = [u for u in unmet_lines if u.reason == "supply_shortage"]

    if cap_gaps:
        total_gap = sum(u.qty for u in cap_gaps)
        explanations.append(
            f"[Storage] Destination storage space limits prevented {total_gap} units from being received (capacity_gap)."
        )

    if supply_shorts:
        total_short = sum(u.qty for u in supply_shorts)
        explanations.append(
            f"[Shortage] Supply shortage of {total_short} units due to available donor stock or transit window limits."
        )

    if not unmet_lines and allocations:
        explanations.append("[Optimal] 100% of replenishment demand was successfully allocated across available corridors.")

    return explanations


def plan_to_geojson(
    base_graph: nx.Graph,
    disrupted_graph: nx.Graph,
    allocations: list[Allocation],
    scenario: Scenario,
    binding_constraints: list[str],
) -> dict:
    """Generate GeoJSON FeatureCollection for Map visualization in Track 3."""
    features = []

    # 1. Depot / Junction Node Features
    for node_id, data in base_graph.nodes(data=True):
        coords = data.get("coordinates", [75.0, 34.0])
        props = {
            "node_id": node_id,
            "site_id": data.get("site_id"),
            "label": data.get("label", node_id),
            "type": "site" if data.get("site_id") else "junction",
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": props,
            }
        )

    # 2. Corridor Edge Features
    for u, v, data in base_graph.edges(data=True):
        edge_id = data.get("edge_id")
        coords_u = base_graph.nodes[u].get("coordinates", [75.0, 34.0])
        coords_v = base_graph.nodes[v].get("coordinates", [75.0, 34.0])

        status = "nominal"
        if edge_id in scenario.closed_edges:
            status = "closed"
        elif edge_id in scenario.capacity_factor:
            status = "reduced_capacity"

        is_binding = any(f"edge_cap_{edge_id}" in bc for bc in binding_constraints)

        props = {
            "edge_id": edge_id,
            "from_node": u,
            "to_node": v,
            "status": status,
            "binding": is_binding,
            "base_capacity_kg": data.get("base_capacity_kg"),
            "effective_capacity_kg": disrupted_graph[u][v]["capacity_kg"] if disrupted_graph.has_edge(u, v) else 0.0,
            "transit_h": disrupted_graph[u][v]["transit_h"] if disrupted_graph.has_edge(u, v) else data.get("transit_h"),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [coords_u, coords_v]},
                "properties": props,
            }
        )

    # 3. Active Allocation Flows
    for a in allocations:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        base_graph.nodes[f"NODE-{a.source.split('-')[-1]}"].get("coordinates", [75.0, 34.0]),
                        base_graph.nodes[f"NODE-{a.dest.split('-')[-1]}"].get("coordinates", [75.0, 34.0]),
                    ],
                },
                "properties": {
                    "layer": "allocation_flow",
                    "item": a.item,
                    "source": a.source,
                    "dest": a.dest,
                    "qty": a.qty,
                    "arrival_h": a.arrival_h,
                    "path_ref": a.path_ref,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "name": f"plan_geojson_{scenario.scenario_id}",
        "features": features,
    }
