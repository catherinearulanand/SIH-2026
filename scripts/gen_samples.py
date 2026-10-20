"""Regenerate contracts/samples/*.json from the real pipeline (deterministic; same calls T3 will make).

    uv run python scripts/gen_samples.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from setu.api.app import app  # noqa: E402

SAMPLES = ROOT / "contracts" / "samples"
SNAPSHOT_ID = "SNAP-26251-150"
PLANS = {  # sample file -> scenario_id in fixtures/scenarios.json
    "planning_run_base.json": "base",
    "planning_run_closed_edge.json": "closed_edge",
    "planning_run_low_cap.json": "reduced_capacity",
    "planning_run_delay.json": "delayed_arrival",
    "planning_run_impossible_demand.json": "impossible_demand",
}


def build() -> dict[str, object]:
    client = TestClient(app)
    r = client.post(
        "/api/v1/forecast-runs",
        json={"snapshot_id": SNAPSHOT_ID, "horizon_days": 28, "policy_mode": "quantile"},
    )
    r.raise_for_status()
    fc = r.json()
    out: dict[str, object] = {
        "forecast_run.json": fc["forecast_run"],
        "replenishment_drafts.json": fc["drafts"],
    }
    for name, scenario_id in PLANS.items():
        p = client.post(
            "/api/v1/planning-runs",
            json={
                "snapshot_id": SNAPSHOT_ID,
                "scenario_id": scenario_id,
                "forecast_run_id": fc["forecast_run"]["run_id"],
            },
        )
        p.raise_for_status()
        out[name] = p.json()
    return out


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for name, obj in build().items():
        (SAMPLES / name).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
        print("wrote", SAMPLES / name)


if __name__ == "__main__":
    main()
