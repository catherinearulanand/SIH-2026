"""Spec: the paired simulation is fair (matched stock, same start, storage cap, FEFO + expiry, uses the forecast)."""

import numpy as np

from planning_helpers import world
from setu.eval import sim
from setu.eval.sim import Series, simulate_series


def make(**kw) -> Series:
    base = dict(site="S", item="I", hist=np.array([10.0] * 14), mu=10.0, lead=2, cap=10_000, other_phys=0,
                shelf_days=365, lots=[], inbound=[], target=100.0)
    base.update(kw)
    return Series(**base)


def test_order_arrives_after_lead_time_and_is_issued():
    s = make(target=50.0, lead=2)
    r = simulate_series(s, np.full(6, 5.0), "forecast")
    # day 0: nothing on hand -> shortage; the order of 50 placed on day 0 lands on day 2
    assert r["unmet"] == 10.0 and r["issued"] == 20.0
    assert r["stocks"][0] == 0 and r["stocks"][2] == 45.0


def test_forecast_target_drives_orders():
    lo = simulate_series(make(target=20.0), np.full(10, 5.0), "forecast")
    hi = simulate_series(make(target=200.0), np.full(10, 5.0), "forecast")
    assert hi["stocks"].max() > lo["stocks"].max()


def test_storage_cap_is_never_exceeded():
    s = make(target=10_000.0, cap=120, other_phys=20)
    r = simulate_series(s, np.zeros(30), "forecast")
    assert r["stocks"].max() <= 120 - 20


def test_expiring_stock_is_counted_as_waste_and_fefo_uses_earliest_first():
    s = make(target=0.0, lots=[[3, 50], [40, 100]])
    r = simulate_series(s, np.zeros(10), "forecast")
    assert r["waste"] == 50.0
    r2 = simulate_series(make(target=0.0, lots=[[3, 50], [40, 100]]), np.full(5, 10.0), "forecast")
    assert r2["waste"] == 20.0  # 30 of the earliest lot was issued first, 20 expired on day 3


def test_same_seed_gives_identical_paths_and_policies_share_them():
    snap, fc = world()
    from setu.forecast.run import run_forecast
    fc_run, _, windows = run_forecast(snap, horizon_days=30, seed=26251)
    series = sim.build_series(snap, fc_run, windows)
    a, b = sim._paths(series, 7, 30), sim._paths(series, 7, 30)
    assert all(np.array_equal(a[k], b[k]) for k in a)


def test_matched_comparison_really_matches_stock_and_reports_all_metrics():
    from setu.forecast.run import run_forecast
    snap, _ = world()
    fc_run, _, windows = run_forecast(snap, horizon_days=30, seed=26251)
    res = sim.run_paired_simulation(snap, fc_run, windows, num_seeds=8, horizon_days=30)
    f, m = res["bootstrap"]["forecast_policy"], res["bootstrap"]["fixed_matched"]
    assert abs(f["avg_stock"] - m["avg_stock"]) / f["avg_stock"] < 0.03
    assert set(sim.METRICS) <= set(f)
    assert res["assumptions"]["forecast_fallback_series"] == 0
