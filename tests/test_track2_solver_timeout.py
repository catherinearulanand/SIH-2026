"""Test 8: Solver status mapping tests on mocked milp results."""

import numpy as np
from setu.planning.solve import map_solver_status


def test_map_solver_status_optimal():
    assert map_solver_status(res_status=0, res_x=np.array([1.0, 2.0])) == "OPTIMAL"
    assert map_solver_status(res_status=0, res_x=None, res_success=True) == "OPTIMAL"


def test_map_solver_status_timeout_with_feasible_solution():
    # Status 1 (HiGHS iteration/time limit reached) with partial feasible solution
    res_x = np.array([5.0, 10.0, 0.0])
    status = map_solver_status(res_status=1, res_x=res_x)
    assert status == "FEASIBLE_TIMEOUT"


def test_map_solver_status_timeout_without_solution():
    # Status 1 without a valid solution vector
    status_none = map_solver_status(res_status=1, res_x=None)
    assert status_none == "NO_PLAN_ESTABLISHED"

    status_empty = map_solver_status(res_status=1, res_x=np.array([]))
    assert status_empty == "NO_PLAN_ESTABLISHED"

    status_nan = map_solver_status(res_status=1, res_x=np.array([np.nan, 2.0]))
    assert status_nan == "NO_PLAN_ESTABLISHED"


def test_map_solver_status_infeasible():
    # Status 2 (infeasible / unbounded)
    assert map_solver_status(res_status=2, res_x=None) == "NO_PLAN_ESTABLISHED"
