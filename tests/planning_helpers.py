"""Shared builders for the planning spec tests: one real forecast world, plus independent re-checks."""

from __future__ import annotations

import functools

from fastapi.testclient import TestClient

from setu.api.app import app
from setu.contracts import ForecastRunResponse, PlanningRun, Scenario
from setu.planning.graph import apply_scenario, load_base_graph, load_scenarios
from setu.planning.solve import solve_planning_run
from setu.snapshot_provider import load_snapshot

SNAP = "SNAP-26251-150"


@functools.lru_cache(maxsize=1)
def world() -> tuple:
    """(snapshot, forecast_response) from the real forecast pipeline, computed once per test run."""
    r = TestClient(app).post(
        "/api/v1/forecast-runs",
        json={"snapshot_id": SNAP, "horizon_days": 28, "policy_mode": "quantile"},
    )
    assert r.status_code == 200, r.text
    return load_snapshot(SNAP), ForecastRunResponse.model_validate(r.json())


def scenarios() -> dict[str, Scenario]:
    return load_scenarios()


def plan_for(scenario: Scenario, time_limit_sec: float = 5.0) -> PlanningRun:
    snap, fc = world()
    return solve_planning_run(
        snapshot=snap, forecast_run=fc.forecast_run, drafts=fc.drafts,
        scenario=scenario, time_limit_sec=time_limit_sec,
    )


def custom(scenario_id: str, **kw) -> Scenario:
    return Scenario(scenario_id=scenario_id, label=f"Test {scenario_id}", hypothetical=True, **kw)


def edge_flows_kg(plan: PlanningRun) -> dict[str, float]:
    """Recompute kg per edge from allocations + path_refs only (no solver internals)."""
    snap, _ = world()
    mass = {i.item_id: i.mass_kg_per_unit for i in snap.items}
    flow: dict[str, float] = {}
    for a in plan.allocations:
        for e in plan.path_refs[a.path_ref]:
            flow[e] = flow.get(e, 0.0) + mass[a.item] * a.qty
    return flow


def scenario_capacities(scenario: Scenario) -> dict[str, float]:
    G = apply_scenario(load_base_graph(), scenario)
    return {d["edge_id"]: d["capacity_kg"] for _, _, d in G.edges(data=True)}


def busiest_edge(plan: PlanningRun) -> str:
    """An edge the plan actually uses, so closing or delaying it must matter."""
    flows = edge_flows_kg(plan)
    assert flows, "base plan has no allocations; fixture world has no replenishment need"
    return max(sorted(flows), key=lambda e: flows[e])
