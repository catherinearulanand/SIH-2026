"""Greedy nearest-source allocation baseline for Setu Supply Track 2."""

import networkx as nx
from setu.contracts import (
    Allocation,
    BaselinePlan,
    ObjectiveComponents,
    ReplenishmentDraft,
    Snapshot,
    UnmetLine,
)
from setu.planning.graph import find_feasible_paths


def run_nearest_source_baseline(
    snapshot: Snapshot,
    drafts: list[ReplenishmentDraft],
    requirements: dict[tuple[str, str], int],
    donor_avail: dict[tuple[str, str], int],
    disrupted_graph: nx.Graph,
    weights: dict[str, float],
) -> BaselinePlan:
    """Greedy nearest-source allocation baseline evaluated under identical objective weights."""
    item_map = {i.item_id: i for i in snapshot.items}
    site_map = {s.site_id: s for s in snapshot.sites}
    draft_map = {(d.site, d.item): d for d in drafts}

    # Remaining donor capacities (mutable copy)
    rem_donor_stock = dict(donor_avail)

    # Edge capacities copy
    edge_cap_rem = {
        data["edge_id"]: float(data["capacity_kg"])
        for _, _, data in disrupted_graph.edges(data=True)
    }

    allocations: list[Allocation] = []
    path_cost: dict[str, float] = {}
    unmet_lines: list[UnmetLine] = []

    # Sort deficits: highest priority first (priority 1 before priority 5)
    sorted_deficits = sorted(
        requirements.items(),
        key=lambda item: (item_map[item[0][1]].priority, -item[1]),
    )

    for (d_id, i_id), req_qty in sorted_deficits:
        dest_site = site_map[d_id]
        item = item_map[i_id]
        dest_free_storage = draft_map[(d_id, i_id)].capacity_free
        needed = min(req_qty, dest_free_storage)
        unmet_storage = req_qty - needed

        # Find candidate donors ordered by shortest path transit hours
        candidate_donors = []
        for s_id, s_site in site_map.items():
            if s_id == d_id or rem_donor_stock.get((s_id, i_id), 0) <= 0:
                continue

            paths = find_feasible_paths(
                disrupted_graph,
                s_site.node_id,
                dest_site.node_id,
                max_transit_h=dest_site.delivery_window_h,
                k=1,
            )
            if paths:
                candidate_donors.append((paths[0]["transit_h"], s_id, paths[0]))

        candidate_donors.sort(key=lambda x: x[0])

        allocated_for_deficit = 0
        for _, s_id, path_info in candidate_donors:
            if allocated_for_deficit >= needed:
                break

            still_needed = needed - allocated_for_deficit
            avail_stock = rem_donor_stock.get((s_id, i_id), 0)

            # Check bottleneck edge capacity
            mass_unit = item.mass_kg_per_unit
            max_packs_by_edge = min(
                int(edge_cap_rem[e_id] // mass_unit) for e_id in path_info["edge_ids"]
            )

            ship_qty = min(still_needed, avail_stock, max_packs_by_edge)
            if ship_qty > 0:
                allocations.append(
                    Allocation(
                        item=i_id,
                        source=s_id,
                        dest=d_id,
                        qty=ship_qty,
                        path_ref=path_info["path_ref"],
                        arrival_h=path_info["transit_h"],
                    )
                )
                path_cost[path_info["path_ref"]] = path_info["cost_per_kg"]
                allocated_for_deficit += ship_qty
                rem_donor_stock[(s_id, i_id)] -= ship_qty
                for e_id in path_info["edge_ids"]:
                    edge_cap_rem[e_id] -= ship_qty * mass_unit

        shortfall = req_qty - allocated_for_deficit
        if shortfall > 0:
            if unmet_storage > 0:
                cap_gap = min(shortfall, unmet_storage)
                supply_short = shortfall - cap_gap
                if cap_gap > 0:
                    unmet_lines.append(UnmetLine(item=i_id, dest=d_id, qty=cap_gap, reason="capacity_gap"))
                if supply_short > 0:
                    unmet_lines.append(UnmetLine(item=i_id, dest=d_id, qty=supply_short, reason="supply_shortage"))
            else:
                unmet_lines.append(UnmetLine(item=i_id, dest=d_id, qty=shortfall, reason="supply_shortage"))

    # Compute baseline objective components
    shortage_cost = sum((6.0 - item_map[u.item].priority) * u.qty for u in unmet_lines if u.reason == "supply_shortage")
    transport_cost = sum(
        path_cost[a.path_ref] * item_map[a.item].mass_kg_per_unit * a.qty for a in allocations
    )
    expiry_cost = sum(
        100.0 * (a.arrival_h / 24.0) / item_map[a.item].min_shelf_days * a.qty for a in allocations
    )

    obj = ObjectiveComponents(
        shortage=round(shortage_cost, 2),
        transport=round(transport_cost, 2),
        expiry=round(expiry_cost, 2),
        weights=weights,
    )

    return BaselinePlan(
        allocations=allocations,
        unmet=unmet_lines,
        objective_components=obj,
    )
