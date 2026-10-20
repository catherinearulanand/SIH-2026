"""Test 7: Closing an edge alters the plan, and explanation explicitly cites that edge ID."""

from setu.api.track2 import get_scenario_by_id
from setu.forecast.run import run_forecast
from setu.planning.solve import solve_planning_run
from setu.projection import project_stock_and_drafts
from setu.snapshot_provider import load_snapshot


def test_closed_edge_alters_allocation_and_names_edge():
    snap = load_snapshot("SNAP-26251-150")
    fc_run, _, site_windows = run_forecast(snap, horizon_days=30, seed=26251)
    drafts = project_stock_and_drafts(snap, fc_run, site_windows)

    # 1. Base plan
    sc_base = get_scenario_by_id("base")
    plan_base = solve_planning_run(snap, fc_run, drafts, sc_base)

    # 2. Closed edge plan
    sc_closed = get_scenario_by_id("closed_edge")
    plan_closed = solve_planning_run(snap, fc_run, drafts, sc_closed)

    # Verify explanation explicitly cites the scenario label and closed edge ID
    assert any("E-A-J1" in exp for exp in plan_closed.explanation), (
        f"Explanation must cite closed edge 'E-A-J1': {plan_closed.explanation}"
    )
    assert any("Hypothetical" in exp for exp in plan_closed.explanation)
    assert any(sc_closed.label in exp for exp in plan_closed.explanation)

    # Verify that closing the edge E-A-J1 means NO active allocation path uses E-A-J1
    for a in plan_closed.allocations:
        edge_ids = plan_closed.path_refs[a.path_ref]
        assert "E-A-J1" not in edge_ids, f"Path {a.path_ref} still used closed edge E-A-J1!"
