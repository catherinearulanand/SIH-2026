"""Spec: the locked/addendum outputs refuse to overwrite, and the eval helpers measure what they claim."""

import dataclasses

import numpy as np
import pytest

from planning_helpers import plan_for, scenarios, world
from setu.eval import run_all


@pytest.mark.parametrize("fn,attr", [("run_locked_evaluation", "METRICS_PATH"), ("run_addendum_evaluation", "SIM_V2_PATH")])
def test_locked_outputs_refuse_to_overwrite(tmp_path, monkeypatch, fn, attr):
    target = tmp_path / "locked.json"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(run_all, attr, target)
    with pytest.raises(SystemExit) as e:
        getattr(run_all, fn)()
    assert e.value.code == 0
    assert target.read_text(encoding="utf-8") == "original"


def test_aggregate_window_coverage_counts_hits_and_misses():
    paths = {("S", "I"): np.ones((500, 30))}  # every path sums to W per window
    w = {"S": 8}
    hit = run_all.aggregate_window_coverage(paths, w, {("S", "I"): np.ones(30)})
    miss = run_all.aggregate_window_coverage(paths, w, {("S", "I"): np.full(30, 5.0)})
    assert hit["n_windows"] == 3 and hit["p90_coverage"] == 1.0
    assert miss["p90_coverage"] == 0.0


def test_windows_with_missing_days_are_skipped():
    paths = {("S", "I"): np.ones((500, 30))}
    act = np.ones(30)
    act[2] = np.nan
    assert run_all.aggregate_window_coverage(paths, {"S": 8}, {("S", "I"): act})["n_windows"] == 2


def test_plan_violations_detects_an_overloaded_plan():
    snap, fc = world()
    sc = scenarios()["base"]
    plan = plan_for(sc)
    assert run_all.plan_violations(plan, snap, fc.drafts, sc) == []
    bad = plan.model_copy(update={"allocations": [a.model_copy(update={"qty": a.qty * 1000}) for a in plan.allocations]})
    assert run_all.plan_violations(bad, snap, fc.drafts, sc)


def test_aligned_history_keeps_weekly_alignment_after_gaps():
    snap, _ = world()
    h = run_all._aligned_history(snap)
    n = (np.datetime64(snap.demand_cutoff) - np.datetime64("2026-01-01")).astype(int) + 1
    assert all(len(a) == n and not np.isnan(a).any() for a in h.values())
