"""Pydantic v2 data contracts for Setu Supply Track 2."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    base_unit: str
    mass_kg_per_unit: float
    min_shelf_days: int
    priority: int = Field(ge=1, le=5, description="1 is critical, 5 is low priority")


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    node_id: str
    storage_capacity_base: dict[str, int]
    delivery_window_h: float = 48.0


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    site_id: str
    item_id: str
    qty_base: int
    expiry_date: str  # YYYY-MM-DD
    quality_state: Literal["USABLE", "QUARANTINED", "REJECTED", "DAMAGED"]


class Reservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    item_id: str
    qty_base: int


class InboundOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    item_id: str
    qty_base: int
    eta: str  # YYYY-MM-DD


class DemandRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    item_id: str
    date: str  # YYYY-MM-DD
    requested: float | None = None
    issued: float
    unmet: float | None = None
    missing_flag: bool = False
    stockout_flag: bool = False


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    as_of: str  # YYYY-MM-DD
    demand_cutoff: str  # YYYY-MM-DD
    items: list[Item]
    sites: list[Site]
    batches: list[Batch]
    reservations: list[Reservation]
    inbound: list[InboundOrder]
    demand: list[DemandRecord]
    graph_version: str
    source_versions: dict[str, str] = Field(default_factory=dict)


class DailyPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    item_id: str
    date: str  # YYYY-MM-DD
    mean: float


class AggregatePrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    item_id: str
    window_days: int
    p10: float
    p50: float
    p90: float


class ForecastRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    input_snapshot_id: str
    cutoff: str  # YYYY-MM-DD
    horizon_days: int
    model_version: str
    method_by_series: dict[str, str]
    predictions: list[DailyPrediction]
    aggregate: list[AggregatePrediction]
    range_method: str
    calibrated: bool
    evaluation_ref: str | None = None
    warnings: list[str] = Field(default_factory=list)
    low_evidence: list[str] = Field(default_factory=list)
    dataset_fingerprint: str
    seed: int
    lib_versions: dict[str, str] = Field(default_factory=dict)


class ReplenishmentSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int
    arrival: str  # YYYY-MM-DD


class ReplenishmentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str
    item: str
    target: int
    allocatable: int
    inbound_in_horizon: int
    proposed_qty: int
    capacity_free: int
    capacity_gap: int
    split: list[ReplenishmentSplit] = Field(default_factory=list)
    shortage_days_projected: int
    unmet_projected_qty: float
    expiry_waste_projected: int
    policy_mode: Literal["quantile", "mean_plus_buffer"]
    inputs_ref: dict = Field(default_factory=dict)


class ForecastRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_run: ForecastRun
    drafts: list[ReplenishmentDraft]


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    label: str
    hypothetical: bool = True
    closed_edges: list[str] = Field(default_factory=list)
    capacity_factor: dict[str, float] = Field(default_factory=dict)
    delay_h: dict[str, float] = Field(default_factory=dict)
    demand_factor: dict[str, float] = Field(default_factory=dict)


class Allocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    source: str
    dest: str
    qty: int
    path_ref: str
    arrival_h: float


class ObjectiveComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shortage: float
    transport: float
    expiry: float
    weights: dict[str, float]


class UnmetLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    dest: str
    qty: int
    reason: Literal["supply_shortage", "capacity_gap"] = "supply_shortage"


class BaselinePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocations: list[Allocation] = Field(default_factory=list)
    unmet: list[UnmetLine] = Field(default_factory=list)
    objective_components: ObjectiveComponents


class PlanningRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    snapshot_id: str
    forecast_run_id: str
    graph_version: str
    scenario_id: str
    scenario_label: str
    constraints_version: str
    allocations: list[Allocation]
    path_refs: dict[str, list[str]]
    unmet: list[UnmetLine]
    objective_components: ObjectiveComponents
    binding_constraints: list[str]
    solver_status: Literal["OPTIMAL", "FEASIBLE_TIMEOUT", "NO_PLAN_ESTABLISHED"]
    baseline: BaselinePlan
    explanation: list[str]
    geojson: dict
