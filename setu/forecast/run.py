"""Forecast run orchestrator, cryptographic fingerprinting, and run assembly for Setu Supply Track 2."""

from datetime import date, timedelta
import hashlib
import json
from typing import Literal
import numpy as np

from setu.contracts import (
    AggregatePrediction,
    DailyPrediction,
    DemandRecord,
    ForecastRun,
    ReplenishmentDraft,
    Snapshot,
)
from setu.forecast.route import route_and_fit_series
from setu.forecast.uncertainty import (
    RANGE_METHOD,
    compute_aggregate_quantiles,
    generate_block_bootstrap_paths,
)
from setu.planning.graph import compute_base_lead_times, load_base_graph

MODEL_VERSION = "setu_forecast_v1.0.0"
REVIEW_PERIOD_DAYS = 7


def compute_dataset_fingerprint(
    snapshot: Snapshot,
    cutoff: str,
    horizon_days: int,
    policy_mode: str,
    seed: int,
) -> str:
    """Generate SHA-256 fingerprint over canonical JSON of all consumed snapshot data + config."""
    # Filter demand up to cutoff and sort
    filtered_demand = [
        {"s": d.site_id, "i": d.item_id, "dt": d.date, "req": d.requested, "iss": d.issued, "unm": d.unmet}
        for d in snapshot.demand
        if d.date <= cutoff
    ]
    filtered_demand.sort(key=lambda x: (x["s"], x["i"], x["dt"]))

    consumed = {
        "items": sorted([{"id": i.item_id, "mass": i.mass_kg_per_unit, "prio": i.priority} for i in snapshot.items], key=lambda x: x["id"]),
        "sites": sorted([{"id": s.site_id, "cap": s.storage_capacity_base} for s in snapshot.sites], key=lambda x: x["id"]),
        "batches": sorted([{"id": b.batch_id, "s": b.site_id, "i": b.item_id, "qty": b.qty_base, "exp": b.expiry_date, "st": b.quality_state} for b in snapshot.batches], key=lambda x: x["id"]),
        "reservations": sorted([{"s": r.site_id, "i": r.item_id, "qty": r.qty_base} for r in snapshot.reservations], key=lambda x: (x["s"], x["i"])),
        "inbound": sorted([{"s": o.site_id, "i": o.item_id, "qty": o.qty_base, "eta": o.eta} for o in snapshot.inbound], key=lambda x: (x["s"], x["i"], x["eta"])),
        "demand": filtered_demand,
        "config": {
            "cutoff": cutoff,
            "horizon_days": horizon_days,
            "policy_mode": policy_mode,
            "seed": seed,
            "model_version": MODEL_VERSION,
        },
    }

    canonical_json = json.dumps(consumed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def run_forecast(
    snapshot: Snapshot,
    cutoff: str | None = None,
    horizon_days: int = 30,
    policy_mode: Literal["quantile", "mean_plus_buffer"] = "quantile",
    seed: int = 26251,
    use_croston: bool = False,
) -> tuple[ForecastRun, dict[tuple[str, str], np.ndarray], dict[str, int]]:
    """Execute forecast pipeline over a Snapshot.

    Returns
    -------
    tuple[ForecastRun, dict[tuple[str, str], np.ndarray], dict[str, int]]
        (forecast_run, all_simulated_paths, lead_time_windows)
    """
    cutoff_str = cutoff or snapshot.demand_cutoff
    rng = np.random.default_rng(seed)

    # 1. Base graph and lead-time window per depot
    base_graph = load_base_graph()
    lead_times = compute_base_lead_times(base_graph, snapshot.sites)
    site_windows = {s_id: L + REVIEW_PERIOD_DAYS for s_id, L in lead_times.items()}
    max_w = max(site_windows.values()) if site_windows else 8

    # Input guard: horizon_days must cover lead time window
    if horizon_days < max_w:
        raise ValueError(
            f"horizon_days ({horizon_days}) must be >= maximum lead time window ({max_w})"
        )

    # Auto-extend internal simulation horizon for full quantile/projection coverage
    sim_horizon = max(horizon_days, max_w + 7)

    # 2. Filter demand up to cutoff strictly (leakage prevention)
    valid_demand = [d for d in snapshot.demand if d.date <= cutoff_str]

    # Organize demand by (site_id, item_id, date)
    date_set = sorted({d.date for d in valid_demand})
    grouped_demand: dict[tuple[str, str], dict[str, DemandRecord]] = {}
    for d in valid_demand:
        grouped_demand.setdefault((d.site_id, d.item_id), {})[d.date] = d

    all_series: dict[tuple[str, str], np.ndarray] = {}
    censored_warnings: list[str] = []

    for site in snapshot.sites:
        for item in snapshot.items:
            key = (site.site_id, item.item_id)
            site_item_records = grouped_demand.get(key, {})

            series_vals = []
            for dt in date_set:
                rec = site_item_records.get(dt)
                if rec is None or rec.missing_flag:
                    # Missing day: NaN, never 0
                    series_vals.append(np.nan)
                elif rec.requested is not None:
                    series_vals.append(float(rec.requested))
                elif rec.issued is not None and rec.unmet is not None:
                    series_vals.append(float(rec.issued + rec.unmet))
                elif rec.stockout_flag and rec.unmet is None:
                    # Stockout day without recorded unmet: CENSORED!
                    series_vals.append(np.nan)
                    censored_warnings.append(
                        f"Day {dt} for series {key} was censored (stockout with unrecorded unmet demand); excluded from fit."
                    )
                else:
                    series_vals.append(float(rec.issued))

            all_series[key] = np.array(series_vals, dtype=float)

    # 3. Route, fit, bootstrap uncertainty, and assemble predictions
    method_by_series: dict[str, str] = {}
    all_predictions: list[DailyPrediction] = []
    all_aggregates: list[AggregatePrediction] = []
    all_warnings: list[str] = list(censored_warnings)
    all_low_evidence: list[str] = []
    all_paths: dict[tuple[str, str], np.ndarray] = {}

    start_future = date.fromisoformat(cutoff_str) + timedelta(days=1)

    for site in snapshot.sites:
        w_site = site_windows[site.site_id]
        windows_to_compute = sorted(list({3, 7, 14, 21, w_site}))

        for item in snapshot.items:
            key = (site.site_id, item.item_id)
            series = all_series[key]
            series_label = f"{site.site_id}:{item.item_id}"

            mean_fc, method_name, s_warnings, is_low_ev = route_and_fit_series(
                site.site_id,
                item.item_id,
                series,
                all_series,
                sim_horizon,
                use_croston=use_croston,
            )

            method_by_series[series_label] = method_name
            all_warnings.extend(s_warnings)
            if is_low_ev:
                all_low_evidence.append(series_label)

            # Residuals for bootstrap
            clean_actuals = series[~np.isnan(series)]
            if len(clean_actuals) > 0:
                in_sample_level = np.mean(clean_actuals)
                residuals = clean_actuals - in_sample_level
            else:
                residuals = np.array([0.0])

            # Block-bootstrap sample paths
            paths = generate_block_bootstrap_paths(
                fitted_mean=mean_fc,
                residuals=residuals,
                horizon=sim_horizon,
                num_paths=500,
                block_size=7,
                rng=rng,
            )
            all_paths[key] = paths

            # Aggregate quantiles
            aggs = compute_aggregate_quantiles(
                site_id=site.site_id,
                item_id=item.item_id,
                paths=paths,
                windows=windows_to_compute,
            )
            all_aggregates.extend(aggs)

            # Daily mean predictions for requested horizon
            for h in range(horizon_days):
                pred_date = start_future + timedelta(days=h)
                all_predictions.append(
                    DailyPrediction(
                        site_id=site.site_id,
                        item_id=item.item_id,
                        date=pred_date.isoformat(),
                        mean=round(float(mean_fc[h]), 2),
                    )
                )

    # 4. Fingerprint and run ID
    fingerprint = compute_dataset_fingerprint(
        snapshot=snapshot,
        cutoff=cutoff_str,
        horizon_days=horizon_days,
        policy_mode=policy_mode,
        seed=seed,
    )
    run_id = f"fc-{fingerprint[:12]}"

    forecast_run = ForecastRun(
        run_id=run_id,
        input_snapshot_id=snapshot.snapshot_id,
        cutoff=cutoff_str,
        horizon_days=horizon_days,
        model_version=MODEL_VERSION,
        method_by_series=method_by_series,
        predictions=all_predictions,
        aggregate=all_aggregates,
        range_method=RANGE_METHOD,
        calibrated=False,
        evaluation_ref=None,
        warnings=all_warnings,
        low_evidence=all_low_evidence,
        dataset_fingerprint=fingerprint,
        seed=seed,
        lib_versions={"numpy": np.__version__},
    )

    return forecast_run, all_paths, site_windows
