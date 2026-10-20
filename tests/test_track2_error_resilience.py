"""Test 10: Error resilience: Series errors return fallback + warning (never 500); bad inputs return 404/409/422."""

from fastapi.testclient import TestClient
import numpy as np
from setu.api.app import app
from setu.forecast.route import route_and_fit_series


def test_series_exception_fallback_never_throws():
    # Corrupt array with infinite values or empty series
    corrupt_series = np.array([np.inf, -np.inf, np.nan])
    all_series = {("FICTIONAL-A", "CORRUPT"): corrupt_series}

    fc, method, warnings, is_low_ev = route_and_fit_series(
        site_id="FICTIONAL-A",
        item_id="CORRUPT",
        series=corrupt_series,
        all_series=all_series,
        horizon=14,
    )

    # Must return a valid array, descriptive warning, and low_evidence flag
    assert isinstance(fc, np.ndarray)
    assert len(fc) == 14
    assert len(warnings) > 0
    assert is_low_ev is True


def test_api_error_status_codes():
    client = TestClient(app)

    # 1. Path traversal or missing snapshot returns 404 (not 500)
    res_traversal = client.post("/api/v1/forecast-runs", json={"snapshot_id": "../../etc/passwd"})
    assert res_traversal.status_code == 404

    res_missing_snap = client.post("/api/v1/forecast-runs", json={"snapshot_id": "SNAP-DOES-NOT-EXIST"})
    assert res_missing_snap.status_code == 404

    # 2. Horizon < max lead time window returns 422
    res_short_horizon = client.post(
        "/api/v1/forecast-runs",
        json={"snapshot_id": "SNAP-26251-150", "horizon_days": 3},
    )
    assert res_short_horizon.status_code == 422

    # 3. Create valid forecast run to test planning errors
    res_valid_fc = client.post(
        "/api/v1/forecast-runs",
        json={"snapshot_id": "SNAP-26251-150", "horizon_days": 30},
    )
    assert res_valid_fc.status_code == 200
    valid_fc_id = res_valid_fc.json()["forecast_run"]["run_id"]

    # 4. Planning run with non-existent forecast_run_id returns 404
    res_missing_fc = client.post(
        "/api/v1/planning-runs",
        json={
            "snapshot_id": "SNAP-26251-150",
            "scenario_id": "base",
            "forecast_run_id": "fc-nonexistent",
        },
    )
    assert res_missing_fc.status_code == 404

    # 5. Planning run with unknown scenario_id returns 404
    res_unknown_sc = client.post(
        "/api/v1/planning-runs",
        json={
            "snapshot_id": "SNAP-26251-150",
            "scenario_id": "unknown_scenario_xyz",
            "forecast_run_id": valid_fc_id,
        },
    )
    assert res_unknown_sc.status_code == 404
