"""Test 1: Forecast at cutoff c is invariant to mutations/additions after c (no leakage)."""

from copy import deepcopy
from setu.contracts import DemandRecord
from setu.forecast.run import run_forecast
from setu.snapshot_provider import load_snapshot


def test_forecast_no_future_leakage():
    snap1 = load_snapshot("SNAP-26251-150")
    fc1, _, _ = run_forecast(snap1, cutoff="2026-05-30", horizon_days=30, seed=26251)

    # Clone snapshot and inject mutated demand rows AFTER the cutoff date
    snap2 = deepcopy(snap1)
    future_leak_rows = [
        DemandRecord(
            site_id="FICTIONAL-A",
            item_id="RATION-PACK",
            date="2026-06-05",  # Future date > cutoff
            requested=99999.0,
            issued=99999.0,
            unmet=0.0,
        ),
        DemandRecord(
            site_id="FICTIONAL-B",
            item_id="WATER-20L",
            date="2026-06-15",  # Future date > cutoff
            requested=88888.0,
            issued=88888.0,
            unmet=0.0,
        ),
    ]
    snap2.demand.extend(future_leak_rows)

    fc2, _, _ = run_forecast(snap2, cutoff="2026-05-30", horizon_days=30, seed=26251)

    # Forecasts covering t > cutoff must be strictly identical
    preds1 = [(p.site_id, p.item_id, p.date, p.mean) for p in fc1.predictions]
    preds2 = [(p.site_id, p.item_id, p.date, p.mean) for p in fc2.predictions]

    assert preds1 == preds2
    assert fc1.dataset_fingerprint == fc2.dataset_fingerprint
    assert fc1.run_id == fc2.run_id
