"""Spec: a time-limited or failed solve must never be reported as OPTIMAL."""

from types import SimpleNamespace

import numpy as np

from planning_helpers import plan_for, scenarios
from setu.planning import solve as solve_mod
from setu.planning.solve import map_solver_status


def test_status_mapping_table():
    x = np.array([1.0, 2.0])
    assert map_solver_status(0, x, True) == "OPTIMAL"
    assert map_solver_status(1, x, False) == "FEASIBLE_TIMEOUT"
    assert map_solver_status(1, None, False) == "NO_PLAN_ESTABLISHED"
    assert map_solver_status(1, np.array([]), False) == "NO_PLAN_ESTABLISHED"
    assert map_solver_status(1, np.array([np.nan]), False) == "NO_PLAN_ESTABLISHED"
    assert map_solver_status(2, None, False) == "NO_PLAN_ESTABLISHED"  # infeasible
    assert map_solver_status(4, None, False) == "NO_PLAN_ESTABLISHED"  # other failure


def test_timeout_without_solution_is_not_a_plan(monkeypatch):
    monkeypatch.setattr(
        solve_mod, "milp", lambda *a, **k: SimpleNamespace(status=1, x=None, success=False)
    )
    plan = plan_for(scenarios()["base"])
    assert plan.solver_status == "NO_PLAN_ESTABLISHED"
    assert plan.allocations == []
    # No plan means the need is still unmet; it must not be silently dropped.
    assert sum(u.qty for u in plan.unmet) > 0


def test_timeout_with_incumbent_is_labelled_feasible(monkeypatch):
    real = solve_mod.milp

    def limited(*a, **k):
        res = real(*a, **k)
        return SimpleNamespace(status=1, x=res.x, success=False)

    monkeypatch.setattr(solve_mod, "milp", limited)
    plan = plan_for(scenarios()["base"])
    assert plan.solver_status == "FEASIBLE_TIMEOUT"
