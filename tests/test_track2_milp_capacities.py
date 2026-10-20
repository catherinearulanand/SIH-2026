"""Test 6: Accepted planner output has 0 edge/source/storage capacity violations; impossible demand gives unmet > 0."""

from setu.api.track2 import get_scenario_by_id
from setu.forecast.run import run_forecast
from setu.planning.graph import load_base_graph
from setu.planning.solve import solve_planning_run
from setu.projection import project_stock_and_drafts
from setu.snapshot_provider import load_snapshot


def test_milp_plan_zero_capacity_violations():
    snap = load_snapshot("SNAP-26251-150")
    fc_run, _, site_windows = run_forecast(snap, horizon_days=30, seed=26251)
    drafts = project_stock_and_drafts(snap, fc_run, site_windows)

    scenario_base = get_scenario_by_id("base")
    plan = solve_planning_run(snap, fc_run, drafts, scenario_base)

    assert plan.solver_status == "OPTIMAL"

    # Verify donor capacities: no donor ships more than its donor availability
    donor_shipped: dict[tuple[str, str], int] = {}
    for a in plan.allocations:
        donor_shipped[(a.source, a.item)] = donor_shipped.get((a.source, a.item), 0) + a.qty

    draft_map = {(d.site, d.item): d for d in drafts}
    p50_map = {(ag.site_id, ag.item_id, ag.window_days): ag.p50 for ag in fc_run.aggregate}

    for (src, item), shipped_qty in donor_shipped.items():
        draft_src = draft_map[(src, item)]
        p50_val = p50_map.get((src, item, site_windows[src]), float(draft_src.target * 0.5))
        max_avail = max(0, draft_src.allocatable - int(p50_val))
        assert shipped_qty <= max_avail, f"Donor {src} overshipped item {item}: {shipped_qty} > {max_avail}"

    # Verify storage capacities: destination cannot receive more than its free storage
    dest_received: dict[tuple[str, str], int] = {}
    for a in plan.allocations:
        dest_received[(a.dest, a.item)] = dest_received.get((a.dest, a.item), 0) + a.qty

    for (dest, item), rec_qty in dest_received.items():
        free_storage = draft_map[(dest, item)].capacity_free
        assert rec_qty <= free_storage, f"Dest {dest} exceeded storage capacity for {item}: {rec_qty} > {free_storage}"

    # Verify edge mass capacities
    base_graph = load_base_graph()
    edge_cap_map = {data["edge_id"]: float(data["capacity_kg"]) for _, _, data in base_graph.edges(data=True)}
    item_mass = {i.item_id: i.mass_kg_per_unit for i in snap.items}

    edge_mass_used: dict[str, float] = {}
    for a in plan.allocations:
        edge_ids = plan.path_refs[a.path_ref]
        mass = a.qty * item_mass[a.item]
        for e_id in edge_ids:
            edge_mass_used[e_id] = edge_mass_used.get(e_id, 0.0) + mass

    for e_id, used_mass in edge_mass_used.items():
        cap_kg = edge_cap_map[e_id]
        assert used_mass <= cap_kg + 1e-4, f"Edge {e_id} exceeded capacity: {used_mass} > {cap_kg}"


def test_impossible_demand_produces_unmet_without_error():
    snap = load_snapshot("SNAP-26251-150")
    fc_run, _, site_windows = run_forecast(snap, horizon_days=30, seed=26251)
    drafts = project_stock_and_drafts(snap, fc_run, site_windows)

    scenario_impossible = get_scenario_by_id("impossible_demand")
    plan = solve_planning_run(snap, fc_run, drafts, scenario_impossible)

    assert plan.solver_status == "OPTIMAL"
    assert len(plan.unmet) > 0, "Impossible demand scenario must produce unmet slack"
    total_unmet = sum(u.qty for u in plan.unmet)
    assert total_unmet > 100, f"Expected massive unmet slack, got {total_unmet}"
