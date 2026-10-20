"""Test 9: Determinism: Same seed + snapshot + policy_mode -> identical fingerprint and outputs."""

from setu.api.track2 import get_scenario_by_id
from setu.forecast.run import run_forecast
from setu.planning.solve import solve_planning_run
from setu.projection import project_stock_and_drafts
from setu.snapshot_provider import load_snapshot


def test_forecast_and_planning_determinism():
    snap = load_snapshot("SNAP-26251-150")

    # Run 1
    fc1, _, site_windows1 = run_forecast(snap, horizon_days=30, policy_mode="quantile", seed=26251)
    drafts1 = project_stock_and_drafts(snap, fc1, site_windows1)
    plan1 = solve_planning_run(snap, fc1, drafts1, get_scenario_by_id("base"))

    # Run 2
    fc2, _, site_windows2 = run_forecast(snap, horizon_days=30, policy_mode="quantile", seed=26251)
    drafts2 = project_stock_and_drafts(snap, fc2, site_windows2)
    plan2 = solve_planning_run(snap, fc2, drafts2, get_scenario_by_id("base"))

    # Fingerprints and IDs must be identical
    assert fc1.dataset_fingerprint == fc2.dataset_fingerprint
    assert fc1.run_id == fc2.run_id
    assert plan1.plan_id == plan2.plan_id

    # Byte-for-byte JSON equality
    assert fc1.model_dump_json() == fc2.model_dump_json()
    assert plan1.model_dump_json() == plan2.model_dump_json()


def test_different_policy_mode_changes_fingerprint():
    snap = load_snapshot("SNAP-26251-150")

    fc_q, _, _ = run_forecast(snap, horizon_days=30, policy_mode="quantile", seed=26251)
    fc_m, _, _ = run_forecast(snap, horizon_days=30, policy_mode="mean_plus_buffer", seed=26251)

    # Different policy modes must produce distinct fingerprints to prevent cache collision
    assert fc_q.dataset_fingerprint != fc_m.dataset_fingerprint
    assert fc_q.run_id != fc_m.run_id
