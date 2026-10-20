"""FastAPI router for Setu Supply Track 2 (Forecasting, Projection & GIS Planning)."""

from collections import OrderedDict
import json
from pathlib import Path
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from setu.contracts import (
    ForecastRun,
    ForecastRunResponse,
    PlanningRun,
    ReplenishmentDraft,
    Scenario,
)
from setu.forecast.run import run_forecast
from setu.planning.solve import solve_planning_run
from setu.projection import project_stock_and_drafts
from setu.snapshot_provider import load_snapshot

router = APIRouter(prefix="/api/v1", tags=["Track 2 - Forecasting & GIS Planning"])

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
SCENARIOS_PATH = FIXTURES_DIR / "scenarios.json"

# Bounded in-memory stores (capped at 100 entries with FIFO eviction)
MAX_STORE_ENTRIES = 100
runs_db: OrderedDict[str, ForecastRunResponse] = OrderedDict()
plans_db: OrderedDict[str, PlanningRun] = OrderedDict()


def current_actor():
    """Placeholder dependency for Track 4 authentication and authorization."""
    return {"actor_id": "system_planner", "role": "logistics_officer", "scope": "all_depots"}


def put_run(run_id: str, resp: ForecastRunResponse):
    runs_db[run_id] = resp
    if len(runs_db) > MAX_STORE_ENTRIES:
        runs_db.popitem(last=False)


def put_plan(plan_id: str, plan: PlanningRun):
    plans_db[plan_id] = plan
    if len(plans_db) > MAX_STORE_ENTRIES:
        plans_db.popitem(last=False)


def get_scenario_by_id(scenario_id: str) -> Scenario:
    if not SCENARIOS_PATH.exists():
        raise HTTPException(status_code=500, detail="Scenarios fixture file missing")

    scenarios_list = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    for s_dict in scenarios_list:
        if s_dict.get("scenario_id") == scenario_id:
            return Scenario.model_validate(s_dict)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Scenario '{scenario_id}' not found in scenarios catalog.",
    )


class ForecastRunRequest(BaseModel):
    snapshot_id: str
    cutoff: str | None = None
    horizon_days: int = Field(default=30, ge=1, le=60)
    policy_mode: Literal["quantile", "mean_plus_buffer"] = "quantile"
    seed: int = 26251


class PlanningRunRequest(BaseModel):
    snapshot_id: str
    scenario_id: str
    forecast_run_id: str
    weights: dict[str, float] | None = None


@router.post(
    "/forecast-runs",
    response_model=ForecastRunResponse,
    status_code=status.HTTP_200_OK,
)
def create_forecast_run(
    req: ForecastRunRequest,
    actor: dict[str, Any] = Depends(current_actor),
) -> ForecastRunResponse:
    """Generate demand forecasts and replenishment drafts from a Snapshot."""
    try:
        snapshot = load_snapshot(req.snapshot_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot error: {exc!s}",
        ) from exc

    try:
        forecast_run, _, site_windows = run_forecast(
            snapshot=snapshot,
            cutoff=req.cutoff,
            horizon_days=req.horizon_days,
            policy_mode=req.policy_mode,
            seed=req.seed,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(val_err),
        ) from val_err

    # Compute replenishment drafts
    drafts = project_stock_and_drafts(
        snapshot=snapshot,
        forecast_run=forecast_run,
        site_windows=site_windows,
    )

    response = ForecastRunResponse(
        forecast_run=forecast_run,
        drafts=drafts,
    )

    put_run(forecast_run.run_id, response)
    return response


@router.get(
    "/forecast-runs/{run_id}",
    response_model=ForecastRunResponse,
    status_code=status.HTTP_200_OK,
)
def get_forecast_run(
    run_id: str,
    actor: dict[str, Any] = Depends(current_actor),
) -> ForecastRunResponse:
    """Retrieve past forecast run by ID from in-memory cache."""
    if run_id in runs_db:
        return runs_db[run_id]

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Forecast run '{run_id}' not found in server cache.",
    )


@router.post(
    "/planning-runs",
    response_model=PlanningRun,
    status_code=status.HTTP_200_OK,
)
def create_planning_run(
    req: PlanningRunRequest,
    actor: dict[str, Any] = Depends(current_actor),
) -> PlanningRun:
    """Generate GIS distribution plan solving multi-echelon MILP."""
    # 1. Snapshot check
    try:
        snapshot = load_snapshot(req.snapshot_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot error: {exc!s}",
        ) from exc

    # 2. Forecast run existence check
    if req.forecast_run_id not in runs_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forecast run '{req.forecast_run_id}' not found. Please create forecast run first.",
        )

    fc_resp = runs_db[req.forecast_run_id]
    forecast_run = fc_resp.forecast_run
    drafts = fc_resp.drafts

    # 3. Snapshot ID consistency check (prevent cross-snapshot mismatch)
    if forecast_run.input_snapshot_id != req.snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Snapshot mismatch: Forecast run was computed on '{forecast_run.input_snapshot_id}' "
                f"but planning run requested '{req.snapshot_id}'."
            ),
        )

    # 4. Scenario check
    scenario = get_scenario_by_id(req.scenario_id)

    # 5. Solve MILP with server-configured 5.0s time limit
    plan = solve_planning_run(
        snapshot=snapshot,
        forecast_run=forecast_run,
        drafts=drafts,
        scenario=scenario,
        weights=req.weights,
        time_limit_sec=5.0,
    )

    put_plan(plan.plan_id, plan)
    return plan


@router.get(
    "/planning-runs/{plan_id}",
    response_model=PlanningRun,
    status_code=status.HTTP_200_OK,
)
def get_planning_run(
    plan_id: str,
    actor: dict[str, Any] = Depends(current_actor),
) -> PlanningRun:
    """Retrieve planning run by ID from in-memory cache."""
    if plan_id in plans_db:
        return plans_db[plan_id]

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Planning run '{plan_id}' not found in server cache.",
    )
