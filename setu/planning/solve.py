"""MILP supply allocation solver using SciPy HiGHS for Setu Supply Track 2."""

from datetime import date
import hashlib
import json
from typing import Literal
import numpy as np
from scipy.optimize import LinearConstraint, milp

from setu.contracts import (
    Allocation,
    ForecastRun,
    ObjectiveComponents,
    PlanningRun,
    ReplenishmentDraft,
    Scenario,
    Snapshot,
    UnmetLine,
)
from setu.planning.baseline import run_nearest_source_baseline
from setu.planning.explain import explain_plan_diff, plan_to_geojson
from setu.planning.graph import apply_scenario, find_feasible_paths, load_base_graph

CONSTRAINTS_VERSION = "milp_highs_v1.0.0"
DEFAULT_WEIGHTS = {"shortage": 10000.0, "transport": 1.0, "expiry": 10.0}


def map_solver_status(res_status: int, res_x: np.ndarray | None, res_success: bool = False) -> Literal["OPTIMAL", "FEASIBLE_TIMEOUT", "NO_PLAN_ESTABLISHED"]:
    """Map solver return code and solution vector to standard status string."""
    if res_status == 0 or res_success:
        return "OPTIMAL"
    # Status 1 corresponds to HiGHS iteration / time limit reached
    if res_status == 1:
        if res_x is not None and len(res_x) > 0 and not np.isnan(res_x).any():
            return "FEASIBLE_TIMEOUT"
        return "NO_PLAN_ESTABLISHED"
    return "NO_PLAN_ESTABLISHED"


def solve_planning_run(
    snapshot: Snapshot,
    forecast_run: ForecastRun,
    drafts: list[ReplenishmentDraft],
    scenario: Scenario,
    weights: dict[str, float] | None = None,
    time_limit_sec: float = 5.0,
    _is_base_pass: bool = False,
) -> PlanningRun:
    """Solve the multi-echelon GIS distribution MILP."""
    w = weights or DEFAULT_WEIGHTS
    w_shortage = float(w.get("shortage", 10000.0))
    w_transport = float(w.get("transport", 1.0))
    w_expiry = float(w.get("expiry", 10.0))

    # 1. Base graph and scenario graph
    base_graph = load_base_graph()
    disrupted_graph = apply_scenario(base_graph, scenario)

    # Pre-index draft by (site, item)
    draft_map: dict[tuple[str, str], ReplenishmentDraft] = {(d.site, d.item): d for d in drafts}
    item_map = {i.item_id: i for i in snapshot.items}
    site_map = {s.site_id: s for s in snapshot.sites}
    p50_map = {(a.site_id, a.item_id, a.window_days): a.p50 for a in forecast_run.aggregate}

    # 2. Determine requirement per deficit site and donor availabilities
    # requirement[d, i]: if demand_factor exists, recompute: max(0, ceil(factor * P90) - allocatable - inbound)
    requirements: dict[tuple[str, str], int] = {}
    cap_deficits: dict[tuple[str, str], int] = {}

    for (s_id, i_id), draft in draft_map.items():
        factor = float(scenario.demand_factor.get(i_id, scenario.demand_factor.get(s_id, 1.0)))
        lead_w = draft.inputs_ref.get("lead_window_days", 8)

        if factor != 1.0:
            p90_val = draft.target  # draft.target was ceil(P90)
            target_surge = int(np.ceil(factor * p90_val))
            raw_req = max(0, target_surge - draft.allocatable - draft.inbound_in_horizon)
        else:
            raw_req = draft.proposed_qty + draft.capacity_gap

        if raw_req > 0:
            requirements[(s_id, i_id)] = raw_req
            # Deficit due to storage limits
            cap_deficits[(s_id, i_id)] = max(0, raw_req - draft.capacity_free)

    deficit_keys = list(requirements.keys())

    # Donor availability: site cannot donate item if it is in deficit for that item!
    # donor_avail = max(0, allocatable - P50_lead_demand)
    donor_avail: dict[tuple[str, str], int] = {}
    for (s_id, i_id), draft in draft_map.items():
        if (s_id, i_id) in requirements:
            # Deficit site: strictly 0 donor availability for this item
            donor_avail[(s_id, i_id)] = 0
        else:
            lead_w = draft.inputs_ref.get("lead_window_days", 8)
            p50_val = p50_map.get((s_id, i_id, lead_w), float(draft.target * 0.5))
            avail = max(0, draft.allocatable - int(np.ceil(p50_val)))
            donor_avail[(s_id, i_id)] = avail

    # 3. Candidate flows and feasible paths
    # Flow variable index: x[(i_id, s_id, d_id, path_idx)]
    candidate_flows = []
    path_refs_dict: dict[str, list[str]] = {}

    for (d_id, i_id), req_qty in requirements.items():
        dest_site = site_map[d_id]
        delivery_window = dest_site.delivery_window_h

        for s_id in site_map:
            if s_id == d_id:
                continue  # No self-donation
            if donor_avail.get((s_id, i_id), 0) <= 0:
                continue

            src_node = site_map[s_id].node_id
            dst_node = dest_site.node_id

            paths = find_feasible_paths(disrupted_graph, src_node, dst_node, max_transit_h=delivery_window, k=3)
            for p in paths:
                path_ref = p["path_ref"]
                path_refs_dict[path_ref] = p["edge_ids"]
                candidate_flows.append(
                    {
                        "item_id": i_id,
                        "source_id": s_id,
                        "dest_id": d_id,
                        "path_ref": path_ref,
                        "transit_h": p["transit_h"],
                        "cost_per_kg": p["cost_per_kg"],
                        "edge_ids": p["edge_ids"],
                    }
                )

    num_flows = len(candidate_flows)
    num_deficits = len(deficit_keys)

    # Decision variables vector: [x_0, ..., x_{N-1}, u_0, ..., u_{M-1}]
    # x: integer flow variables
    # u: continuous slack variables (unmet shortage)
    n_vars = num_flows + num_deficits

    c = np.zeros(n_vars, dtype=float)
    integrality = np.zeros(n_vars, dtype=int)

    # Flow cost coefficients
    for idx, f in enumerate(candidate_flows):
        item = item_map[f["item_id"]]
        mass = item.mass_kg_per_unit
        transport_cost = f["cost_per_kg"] * mass
        shelf_penalty = 100.0 * (f["transit_h"] / 24.0) / item.min_shelf_days  # % of shelf life used in transit
        c[idx] = w_transport * transport_cost + w_expiry * shelf_penalty
        integrality[idx] = 1  # Integer pack quantities

    # Slack cost coefficients: w_shortage * (6 - priority)
    for idx, (d_id, i_id) in enumerate(deficit_keys):
        item = item_map[i_id]
        prio = item.priority
        slack_cost = w_shortage * (6.0 - prio)
        c[num_flows + idx] = slack_cost
        integrality[num_flows + idx] = 0  # Continuous slack

    # Bounds: x >= 0, u >= 0
    bounds_lb = np.zeros(n_vars, dtype=float)
    bounds_ub = np.full(n_vars, np.inf, dtype=float)

    # Constraints list
    A_rows = []
    lhs_list = []
    rhs_list = []
    constraint_names = []

    # (A) Demand balance with slack: sum_{s, p} x + u = requirement
    for d_idx, (d_id, i_id) in enumerate(deficit_keys):
        row = np.zeros(n_vars, dtype=float)
        # Slack variable
        row[num_flows + d_idx] = 1.0
        # Flow variables
        for f_idx, f in enumerate(candidate_flows):
            if f["item_id"] == i_id and f["dest_id"] == d_id:
                row[f_idx] = 1.0

        req_qty = float(requirements[(d_id, i_id)])
        A_rows.append(row)
        lhs_list.append(req_qty)
        rhs_list.append(req_qty)
        constraint_names.append(f"demand_balance_{d_id}_{i_id}")

    # (B) Donor availability: sum_{d, p} x <= donor_available
    donor_keys = [(s_id, i_id) for (s_id, i_id), av in donor_avail.items() if av > 0]
    for s_id, i_id in donor_keys:
        row = np.zeros(n_vars, dtype=float)
        for f_idx, f in enumerate(candidate_flows):
            if f["item_id"] == i_id and f["source_id"] == s_id:
                row[f_idx] = 1.0

        max_avail = float(donor_avail[(s_id, i_id)])
        A_rows.append(row)
        lhs_list.append(-np.inf)
        rhs_list.append(max_avail)
        constraint_names.append(f"donor_avail_{s_id}_{i_id}")

    # (C) Destination storage free capacity: sum_{s, p} x <= capacity_free
    for d_id, i_id in deficit_keys:
        row = np.zeros(n_vars, dtype=float)
        for f_idx, f in enumerate(candidate_flows):
            if f["item_id"] == i_id and f["dest_id"] == d_id:
                row[f_idx] = 1.0

        free_cap = float(draft_map[(d_id, i_id)].capacity_free)
        A_rows.append(row)
        lhs_list.append(-np.inf)
        rhs_list.append(free_cap)
        constraint_names.append(f"dest_storage_{d_id}_{i_id}")

    # (D) Edge transport capacity: sum mass_i * x <= edge_capacity_kg
    for u, v, edge_data in disrupted_graph.edges(data=True):
        edge_id = edge_data["edge_id"]
        cap_kg = float(edge_data["capacity_kg"])

        row = np.zeros(n_vars, dtype=float)
        flow_uses_edge = False

        for f_idx, f in enumerate(candidate_flows):
            if edge_id in f["edge_ids"]:
                mass = item_map[f["item_id"]].mass_kg_per_unit
                row[f_idx] = mass
                flow_uses_edge = True

        if flow_uses_edge:
            A_rows.append(row)
            lhs_list.append(-np.inf)
            rhs_list.append(cap_kg)
            constraint_names.append(f"edge_cap_{edge_id}")

    # 4. Solve with HiGHS
    allocations: list[Allocation] = []
    unmet_lines: list[UnmetLine] = []
    binding_constraints: list[str] = []
    solver_status: Literal["OPTIMAL", "FEASIBLE_TIMEOUT", "NO_PLAN_ESTABLISHED"] = "NO_PLAN_ESTABLISHED"

    if n_vars > 0 and len(A_rows) > 0:
        A = np.array(A_rows, dtype=float)
        lhs = np.array(lhs_list, dtype=float)
        rhs = np.array(rhs_list, dtype=float)

        constraints = LinearConstraint(A, lhs, rhs)
        res = milp(
            c=c,
            integrality=integrality,
            bounds=(bounds_lb, bounds_ub),
            constraints=constraints,
            options={"time_limit": time_limit_sec, "mip_rel_gap": 0.0},
        )

        solver_status = map_solver_status(res.status, getattr(res, "x", None), getattr(res, "success", False))

        if solver_status in ("OPTIMAL", "FEASIBLE_TIMEOUT") and res.x is not None:
            sol_x = res.x

            # Extract allocations
            for idx, f in enumerate(candidate_flows):
                qty = int(round(sol_x[idx]))
                if qty > 0:
                    allocations.append(
                        Allocation(
                            item=f["item_id"],
                            source=f["source_id"],
                            dest=f["dest_id"],
                            qty=qty,
                            path_ref=f["path_ref"],
                            arrival_h=f["transit_h"],
                        )
                    )

            # Extract unmet slacks
            for d_idx, (d_id, i_id) in enumerate(deficit_keys):
                slack_qty = int(round(sol_x[num_flows + d_idx]))
                if slack_qty > 0:
                    cap_def = cap_deficits.get((d_id, i_id), 0)
                    if cap_def > 0:
                        cap_gap_qty = min(slack_qty, cap_def)
                        supply_shortage_qty = slack_qty - cap_gap_qty

                        if cap_gap_qty > 0:
                            unmet_lines.append(
                                UnmetLine(item=i_id, dest=d_id, qty=cap_gap_qty, reason="capacity_gap")
                            )
                        if supply_shortage_qty > 0:
                            unmet_lines.append(
                                UnmetLine(item=i_id, dest=d_id, qty=supply_shortage_qty, reason="supply_shortage")
                            )
                    else:
                        unmet_lines.append(
                            UnmetLine(item=i_id, dest=d_id, qty=slack_qty, reason="supply_shortage")
                        )

            # Check binding constraints (slack < 1e-6)
            activity = A @ sol_x
            storage_limited = {f"dest_storage_{d}_{i}" for (d, i), g in cap_deficits.items() if g > 0}
            for c_idx, c_name in enumerate(constraint_names):
                if c_name.startswith("demand_balance_"):
                    continue  # equality rows are always tight and say nothing
                if c_name.startswith("dest_storage_") and c_name not in storage_limited:
                    continue
                upper = rhs[c_idx]
                if np.isfinite(upper) and abs(upper - activity[c_idx]) < 1e-6:
                    binding_constraints.append(c_name)
    else:
        solver_status = "OPTIMAL"

    if solver_status == "NO_PLAN_ESTABLISHED":
        allocations, unmet_lines, binding_constraints = [], [], []
        for (d_id, i_id), req_qty in sorted(requirements.items()):
            eff = min(req_qty, max(0, draft_map[(d_id, i_id)].capacity_free))
            if eff > 0:
                unmet_lines.append(UnmetLine(item=i_id, dest=d_id, qty=eff, reason="supply_shortage"))
            if req_qty - eff > 0:
                unmet_lines.append(UnmetLine(item=i_id, dest=d_id, qty=req_qty - eff, reason="capacity_gap"))

    # Compute objective components: the same raw terms the MILP minimises (weights reported separately)
    cost_by_ref = {f["path_ref"]: f["cost_per_kg"] for f in candidate_flows}
    shortage_val = sum((6.0 - item_map[u.item].priority) * u.qty for u in unmet_lines if u.reason == "supply_shortage")
    transport_val = sum(
        cost_by_ref[a.path_ref] * item_map[a.item].mass_kg_per_unit * a.qty for a in allocations
    )
    expiry_val = sum(
        100.0 * (a.arrival_h / 24.0) / item_map[a.item].min_shelf_days * a.qty for a in allocations
    )

    obj_components = ObjectiveComponents(
        shortage=round(shortage_val, 2),
        transport=round(transport_val, 2),
        expiry=round(expiry_val, 2),
        weights=w,
    )

    # 5. Baseline Comparison
    baseline_plan = run_nearest_source_baseline(
        snapshot=snapshot,
        drafts=drafts,
        requirements=requirements,
        donor_avail=donor_avail,
        disrupted_graph=disrupted_graph,
        weights=w,
    )

    # 6. Explanations vs base nominal plan
    base_plan = None
    is_nominal = not (scenario.closed_edges or scenario.capacity_factor or scenario.delay_h or scenario.demand_factor)
    if not is_nominal and not _is_base_pass:
        base_plan = solve_planning_run(
            snapshot, forecast_run, drafts,
            Scenario(scenario_id="base", label="Nominal network", hypothetical=False),
            weights=weights, time_limit_sec=time_limit_sec, _is_base_pass=True,
        )
    explanation = explain_plan_diff(
        scenario=scenario,
        allocations=allocations,
        unmet_lines=unmet_lines,
        binding_constraints=binding_constraints,
        base_path_refs=base_plan.path_refs if base_plan else None,
        base_used_paths={a.path_ref for a in base_plan.allocations} if base_plan else None,
    )

    # 7. GeoJSON layers for Map visualization
    geojson_layers = plan_to_geojson(
        base_graph=base_graph,
        disrupted_graph=disrupted_graph,
        allocations=allocations,
        scenario=scenario,
        binding_constraints=binding_constraints,
    )

    # 8. Deterministic plan_id
    weights_str = json.dumps(w, sort_keys=True)
    hash_payload = f"{forecast_run.dataset_fingerprint}:{scenario.scenario_id}:{snapshot.graph_version}:{weights_str}"
    plan_id = f"plan-{hashlib.sha256(hash_payload.encode('utf-8')).hexdigest()[:12]}"

    return PlanningRun(
        plan_id=plan_id,
        snapshot_id=snapshot.snapshot_id,
        forecast_run_id=forecast_run.run_id,
        graph_version=snapshot.graph_version,
        scenario_id=scenario.scenario_id,
        scenario_label=scenario.label,
        constraints_version=CONSTRAINTS_VERSION,
        allocations=allocations,
        path_refs={r: path_refs_dict[r] for r in sorted({a.path_ref for a in allocations})},
        unmet=unmet_lines,
        objective_components=obj_components,
        binding_constraints=binding_constraints,
        solver_status=solver_status,
        baseline=baseline_plan,
        explanation=explanation,
        geojson=geojson_layers,
    )
