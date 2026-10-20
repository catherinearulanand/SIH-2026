"""Spec: every accepted plan satisfies every hard constraint, re-derived from the output alone."""

import math

import pytest

from planning_helpers import edge_flows_kg, plan_for, scenario_capacities, scenarios, world
from setu.planning.graph import apply_scenario, load_base_graph

NAMES = ["base", "closed_edge", "reduced_capacity", "delayed_arrival", "impossible_demand"]


@pytest.mark.parametrize("name", NAMES)
def test_hard_constraints_hold(name):
    snap, fc = world()
    sc = scenarios()[name]
    plan = plan_for(sc)
    assert plan.solver_status in ("OPTIMAL", "FEASIBLE_TIMEOUT")

    caps = scenario_capacities(sc)
    for e, kg in edge_flows_kg(plan).items():
        assert e in caps, f"{e} is closed or unknown in {name}"
        assert kg <= caps[e] + 1e-6, f"edge {e}: {kg} kg > {caps[e]} kg"

    free = {(d.site, d.item): d.capacity_free for d in fc.drafts}
    alloc = {(d.site, d.item): d.allocatable for d in fc.drafts}
    window = {s.site_id: s.delivery_window_h for s in snap.sites}
    into, out_of = {}, {}
    for a in plan.allocations:
        assert a.qty > 0 and a.source != a.dest
        assert a.arrival_h <= window[a.dest] + 1e-6
        into[(a.dest, a.item)] = into.get((a.dest, a.item), 0) + a.qty
        out_of[(a.source, a.item)] = out_of.get((a.source, a.item), 0) + a.qty
    for k, q in into.items():
        assert q <= free[k], f"storage at {k}: {q} > {free[k]}"
    # A site receiving an item in this plan is in deficit for it and must not also donate it.
    assert not (set(into) & set(out_of))
    for k, q in out_of.items():
        assert q <= alloc[k], f"donor {k} gives {q} but holds {alloc[k]}"


def test_impossible_demand_reports_unmet_without_error():
    plan = plan_for(scenarios()["impossible_demand"])
    assert plan.solver_status == "OPTIMAL"
    assert sum(u.qty for u in plan.unmet if u.reason == "supply_shortage") > 0


@pytest.mark.parametrize("name", NAMES)
def test_binding_constraints_are_real_limits_not_demand_equalities(name):
    plan = plan_for(scenarios()[name])
    bad = [b for b in plan.binding_constraints if "demand" in b.lower()]
    assert not bad, f"equality rows are always tight and say nothing: {bad}"


def test_objective_components_match_what_the_solver_optimises():
    """transport = sum(path cost_per_kg * mass * qty); shortage counts supply shortage only."""
    snap, _ = world()
    mass = {i.item_id: i.mass_kg_per_unit for i in snap.items}
    prio = {i.item_id: i.priority for i in snap.items}
    sc = scenarios()["base"]
    G = apply_scenario(load_base_graph(), sc)
    cost = {d["edge_id"]: d["cost_per_kg"] for _, _, d in G.edges(data=True)}
    plan = plan_for(sc)
    transport = sum(
        sum(cost[e] for e in plan.path_refs[a.path_ref]) * mass[a.item] * a.qty for a in plan.allocations
    )
    shortage = sum((6 - prio[u.item]) * u.qty for u in plan.unmet if u.reason == "supply_shortage")
    oc = plan.objective_components
    assert math.isclose(oc.transport, transport, rel_tol=1e-6, abs_tol=0.01), (oc.transport, transport)
    assert math.isclose(oc.shortage, shortage, rel_tol=1e-6, abs_tol=0.01), (oc.shortage, shortage)


@pytest.mark.parametrize("name", NAMES)
def test_milp_is_never_worse_than_nearest_source_baseline(name):
    plan = plan_for(scenarios()[name])
    w = plan.objective_components.weights

    def total(oc):
        return w["shortage"] * oc.shortage + w["transport"] * oc.transport + w["expiry"] * oc.expiry

    assert total(plan.objective_components) <= total(plan.baseline.objective_components) + 1e-6


def test_critical_items_cost_more_to_leave_unmet_than_low_priority():
    snap, _ = world()
    p = {i.item_id: i.priority for i in snap.items}
    assert p["RATION-PACK"] < p["SOCKS"]  # 1 = critical, 5 = low
    assert (6 - p["RATION-PACK"]) > (6 - p["SOCKS"])
