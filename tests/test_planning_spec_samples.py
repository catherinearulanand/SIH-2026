"""Spec: the sample payloads handed to T1/T3 are valid contracts and never stale."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_samples  # noqa: E402
from setu.contracts import ForecastRun, PlanningRun, ReplenishmentDraft  # noqa: E402


@pytest.fixture(scope="module")
def fresh():
    return gen_samples.build()


def test_samples_validate_against_contracts(fresh):
    for name in fresh:
        data = json.loads((gen_samples.SAMPLES / name).read_text(encoding="utf-8"))
        if name == "forecast_run.json":
            ForecastRun.model_validate(data)
        elif name == "replenishment_drafts.json":
            [ReplenishmentDraft.model_validate(d) for d in data]
        else:
            PlanningRun.model_validate(data)


def test_samples_are_not_stale(fresh):
    for name, obj in fresh.items():
        on_disk = json.loads((gen_samples.SAMPLES / name).read_text(encoding="utf-8"))
        assert on_disk == obj, f"{name} is stale: run `uv run python scripts/gen_samples.py`"
