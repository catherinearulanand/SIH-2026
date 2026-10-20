"""Test 2: Missing days are excluded (not zero-filled); stockouts without unmet are censored in warnings."""

from copy import deepcopy
import numpy as np
from setu.contracts import DemandRecord
from setu.forecast.baselines import seasonal_naive
from setu.forecast.run import run_forecast
from setu.snapshot_provider import load_snapshot


def test_missing_days_not_zero_filled():
    # Seasonal naive should ignore NaNs rather than treating them as 0s
    data_with_nans = np.array([10.0, np.nan, 12.0, np.nan, 14.0, 16.0, 18.0, 20.0])
    fc = seasonal_naive(data_with_nans, horizon=7, season=7)
    # The output should NOT contain 0.0 values from the NaNs
    assert not np.any(fc == 0.0)
    assert np.all(fc >= 10.0)


def test_stockout_censoring_logged_in_warnings():
    snap = load_snapshot("SNAP-26251-150")
    fc_run, _, _ = run_forecast(snap, horizon_days=30, seed=26251)

    # In our generated data, ~30% of stockout days omitted unmet demand
    censored_warnings = [w for w in fc_run.warnings if "censored" in w.lower()]
    assert len(censored_warnings) > 0

    # Verify that a custom injected censored day produces the expected warning
    snap_custom = deepcopy(snap)
    snap_custom.demand.append(
        DemandRecord(
            site_id="FICTIONAL-D",
            item_id="SOCKS",
            date="2026-05-15",
            requested=None,
            issued=0.0,
            unmet=None,
            missing_flag=False,
            stockout_flag=True,  # Stockout with no unmet recorded = censored
        )
    )
    fc_custom, _, _ = run_forecast(snap_custom, horizon_days=30, seed=26251)
    custom_censored = [
        w for w in fc_custom.warnings if "FICTIONAL-D" in w and "SOCKS" in w and "censored" in w.lower()
    ]
    assert len(custom_censored) > 0
