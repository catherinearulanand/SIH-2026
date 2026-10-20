"""Evaluation CLI runner for Setu Supply Track 2.

Supports:
  --dev     Runs evaluation on the validation slice (days 120-149), clearly labeled 'tuning score'.
  --locked  Runs ONCE on held-out test truth (days 150-179) and writes out/metrics.json permanently.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np


from setu.contracts import Snapshot
from setu.eval.metrics import bias, empirical_coverage, mae, pinball_loss, wape
from setu.eval.sim import run_paired_simulation
from setu.forecast.baselines import ewma, pooled_fallback, seasonal_naive
from setu.forecast.run import run_forecast
from setu.planning.solve import solve_planning_run
from setu.projection import project_stock_and_drafts
from setu.snapshot_provider import load_snapshot

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT_DIR / "out"
EVAL_DIR = OUT_DIR / "eval"
TRUTH_PATH = ROOT_DIR / "fixtures" / "truth.json"
METRICS_PATH = OUT_DIR / "metrics.json"


def evaluate_forecast_on_actuals(
    snapshot: Snapshot,
    actuals_dict: dict[tuple[str, str], np.ndarray],
    horizon: int,
    use_croston: bool = False,
) -> dict:
    """Evaluate candidate forecast methods against ground truth actuals."""
    results = {
        "methods": {
            "track2_routed": {"mae": [], "bias": [], "wape": []},
            "seasonal_naive": {"mae": [], "bias": [], "wape": []},
            "ewma_alpha_0.2": {"mae": [], "bias": [], "wape": []},
        },
        "probabilistic": {
            "p10_coverage": [],
            "p50_coverage": [],
            "p90_coverage": [],
            "pinball_loss_0.9": [],
        },
    }

    fc_run, all_paths, _ = run_forecast(
        snapshot,
        cutoff=snapshot.demand_cutoff,
        horizon_days=horizon,
        seed=26251,
        use_croston=use_croston,
    )

    # Pre-index predictions by (site, item)
    daily_preds: dict[tuple[str, str], list[float]] = {}
    for p in fc_run.predictions:
        daily_preds.setdefault((p.site_id, p.item_id), []).append(p.mean)

    for site in snapshot.sites:
        for item in snapshot.items:
            key = (site.site_id, item.item_id)
            if key not in actuals_dict:
                continue

            act = actuals_dict[key][:horizon]
            clean_train = [
                d.requested for d in snapshot.demand
                if d.site_id == site.site_id and d.item_id == item.item_id and d.requested is not None
            ]
            train_arr = np.array(clean_train, dtype=float)

            # 1. Track 2 routed forecast
            routed_pred = np.array(daily_preds.get(key, [0.0] * horizon)[:horizon], dtype=float)
            results["methods"]["track2_routed"]["mae"].append(mae(act, routed_pred))
            results["methods"]["track2_routed"]["bias"].append(bias(act, routed_pred))
            w = wape(act, routed_pred)
            if w is not None:
                results["methods"]["track2_routed"]["wape"].append(w)

            # 2. Seasonal naive 7
            sn_pred = seasonal_naive(train_arr, horizon=horizon, season=7)
            results["methods"]["seasonal_naive"]["mae"].append(mae(act, sn_pred))
            results["methods"]["seasonal_naive"]["bias"].append(bias(act, sn_pred))
            w = wape(act, sn_pred)
            if w is not None:
                results["methods"]["seasonal_naive"]["wape"].append(w)

            # 3. Standard EWMA
            ew_pred = ewma(train_arr, horizon=horizon, alpha=0.2)
            results["methods"]["ewma_alpha_0.2"]["mae"].append(mae(act, ew_pred))
            results["methods"]["ewma_alpha_0.2"]["bias"].append(bias(act, ew_pred))
            w = wape(act, ew_pred)
            if w is not None:
                results["methods"]["ewma_alpha_0.2"]["wape"].append(w)

            # 4. Probabilistic coverage and pinball loss
            paths = all_paths.get(key)
            if paths is not None:
                p10_daily = np.percentile(paths[:, :horizon], 10, axis=0)
                p50_daily = np.percentile(paths[:, :horizon], 50, axis=0)
                p90_daily = np.percentile(paths[:, :horizon], 90, axis=0)

                results["probabilistic"]["p10_coverage"].append(empirical_coverage(act, p10_daily))
                results["probabilistic"]["p50_coverage"].append(empirical_coverage(act, p50_daily))
                results["probabilistic"]["p90_coverage"].append(empirical_coverage(act, p90_daily))
                results["probabilistic"]["pinball_loss_0.9"].append(pinball_loss(act, p90_daily, tau=0.9))

    summary = {}
    for m, m_data in results["methods"].items():
        summary[m] = {
            "mean_mae": round(float(np.mean(m_data["mae"])), 2),
            "mean_bias": round(float(np.mean(m_data["bias"])), 2),
            "mean_wape": round(float(np.mean(m_data["wape"])), 3) if m_data["wape"] else None,
        }

    summary["probabilistic"] = {
        "p10_empirical_coverage": round(float(np.mean(results["probabilistic"]["p10_coverage"])), 3),
        "p50_empirical_coverage": round(float(np.mean(results["probabilistic"]["p50_coverage"])), 3),
        "p90_empirical_coverage": round(float(np.mean(results["probabilistic"]["p90_coverage"])), 3),
        "mean_pinball_loss_0.9": round(float(np.mean(results["probabilistic"]["pinball_loss_0.9"])), 2),
    }

    return summary


def print_simulation(sim: dict) -> None:
    print("--------------------------------------------------------------------------------")
    print(sim["assumptions"]["fixed_rule"])
    cols = ("fill_rate_pct", "unmet_qty", "shortage_days", "avg_stock", "peak_stock", "expiry_waste")
    print(f"{'Policy':<20} | " + " | ".join(f"{c:>13}" for c in cols))
    for name in ("forecast_policy", "fixed_matched", "fixed_6d_unmatched"):
        row = sim["bootstrap"][name]
        print(f"{name:<20} | " + " | ".join(f"{row[c]:>13.1f}" for c in cols))
    d = sim["bootstrap"]["paired_forecast_minus_fixed_matched"]
    print("Paired forecast - fixed_matched (mean, 95% CI):")
    for c in ("fill_rate_pct", "unmet_qty", "shortage_days", "avg_stock"):
        print(f"  {c:<14} {d[c]['mean']:>9.2f}  [{d[c]['ci95'][0]:.2f}, {d[c]['ci95'][1]:.2f}]")
    if "actual_holdout" in sim:
        print("Actual held-out path (single realisation):")
        for name in ("forecast_policy", "fixed_matched"):
            row = sim["actual_holdout"][name]
            print(f"  {name:<18} fill {row['fill_rate_pct']:.1f}%  unmet {row['unmet_qty']:.0f}  avg stock {row['avg_stock']:.0f}")


def run_dev_evaluation():
    """Run dev evaluation on the validation slice (labeled: tuning score)."""
    print("\n================================================================================")
    print("SETU SUPPLY TRACK 2 - DEV EVALUATION (VALIDATION SLICE)")
    print("LABEL: TUNING SCORE (Hyperparameters tuned on this validation slice)")
    print("================================================================================\n")

    snap = load_snapshot("SNAP-26251-150")

    # Organize validation actuals aligned by date (30 days)
    val_dates = [
        (datetime(2026, 5, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(30)
    ]
    val_by_date: dict[tuple[str, str], dict[str, float]] = {}
    for d in snap.demand:
        if "2026-05-01" <= d.date <= "2026-05-30":
            if d.requested is not None:
                val_by_date.setdefault((d.site_id, d.item_id), {})[d.date] = float(d.requested)
            elif d.issued is not None and d.unmet is not None:
                val_by_date.setdefault((d.site_id, d.item_id), {})[d.date] = float(d.issued + d.unmet)

    val_dict = {}
    for site in snap.sites:
        for item in snap.items:
            key = (site.site_id, item.item_id)
            series_dict = val_by_date.get(key, {})
            arr = np.array([series_dict.get(dt, np.nan) for dt in val_dates], dtype=float)
            val_dict[key] = arr


    # Create a training-only snapshot (cutoff 2026-04-30)
    train_snap = snap.model_copy(deep=True)
    train_snap.demand_cutoff = "2026-04-30"
    train_snap.demand = [d for d in snap.demand if d.date <= "2026-04-30"]

    summary = evaluate_forecast_on_actuals(train_snap, val_dict, horizon=30)
    summary_cr = evaluate_forecast_on_actuals(train_snap, val_dict, horizon=30, use_croston=True)

    print("FORECAST BENCHMARK VS BASELINES (30-day Validation Slice - TUNING SCORE):")
    print("--------------------------------------------------------------------------------")
    print(f"{'Method':<25} | {'MAE':<8} | {'Bias':<8} | {'WAPE':<8}")
    print("--------------------------------------------------------------------------------")
    for m, m_data in summary.items():
        if m != "probabilistic":
            print(f"{m:<25} | {m_data['mean_mae']:<8.2f} | {m_data['mean_bias']:<8.2f} | {m_data['mean_wape']:<8.3f}")
    cr = summary_cr["track2_routed"]
    print(f"{'track2_routed+croston':<25} | {cr['mean_mae']:<8.2f} | {cr['mean_bias']:<8.2f} | {cr['mean_wape']:<8.3f}")
    print("(Croston is chosen for a locked run only if it wins here, on validation.)")

    print("\nPROBABILISTIC UNCERTAINTY METRICS (Block-Bootstrap Envelope):")
    print("--------------------------------------------------------------------------------")
    prob = summary["probabilistic"]
    print(f"P10 Empirical Coverage : {prob['p10_empirical_coverage']:.1%} (target ~10%)")
    print(f"P50 Empirical Coverage : {prob['p50_empirical_coverage']:.1%} (target ~50%)")
    print(f"P90 Empirical Coverage : {prob['p90_empirical_coverage']:.1%} (target ~90%)")
    print(f"P90 Pinball Loss       : {prob['mean_pinball_loss_0.9']:.2f}")

    print("\nPAIRED SUPPLY SIMULATION (bootstrap demand from history; fixed rule matched to the forecast policy's average stock):")
    fc_full, _, w_full = run_forecast(snap, horizon_days=30, seed=26251)
    print_simulation(run_paired_simulation(snap, fc_full, w_full, num_seeds=20, horizon_days=30))
    print("================================================================================\n")


def run_locked_evaluation():
    """Run locked evaluation ONCE against held-out test truth (days 150-179)."""
    if METRICS_PATH.exists():
        print(f"[LOCKED] {METRICS_PATH} already exists!")
        print("Per Track 2 protocol: The locked test runs ONCE. Refusing to overwrite.")
        sys.exit(0)

    if not TRUTH_PATH.exists():
        print(f"[ERROR] Ground truth file {TRUTH_PATH} not found.")
        sys.exit(1)

    print("\n================================================================================")
    print("SETU SUPPLY TRACK 2 - LOCKED TEST EVALUATION (DAYS 150-179)")
    print("LABEL: HONEST BENCHMARK (Synthetic Generator, Seed 26251)")
    print("================================================================================\n")

    truth_raw = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    truth_records = truth_raw["demand"]

    test_dates = [
        (datetime(2026, 5, 31) + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(30)
    ]
    test_by_date: dict[tuple[str, str], dict[str, float]] = {}
    for d in truth_records:
        dt = d.get("date")
        if dt:
            if d.get("requested") is not None:
                test_by_date.setdefault((d["site_id"], d["item_id"]), {})[dt] = float(d["requested"])
            elif d.get("issued") is not None and d.get("unmet") is not None:
                test_by_date.setdefault((d["site_id"], d["item_id"]), {})[dt] = float(d["issued"] + d["unmet"])

    test_actuals = {}
    for s_id, i_id in test_by_date.keys():
        key = (s_id, i_id)
        series_dict = test_by_date.get(key, {})
        arr = np.array([series_dict.get(dt, np.nan) for dt in test_dates], dtype=float)
        test_actuals[key] = arr


    snap = load_snapshot("SNAP-26251-150")
    fc_summary = evaluate_forecast_on_actuals(snap, test_actuals, horizon=30, use_croston=True)

    fc_lock, _, w_lock = run_forecast(snap, horizon_days=30, seed=26251)
    sim_res = run_paired_simulation(snap, fc_lock, w_lock, truth=test_actuals, num_seeds=20, horizon_days=30)

    # Run planning evaluation
    fc_run, _, site_windows = run_forecast(snap, horizon_days=30, seed=26251)
    drafts = project_stock_and_drafts(snap, fc_run, site_windows)

    from setu.api.track2 import get_scenario_by_id
    plan_base = solve_planning_run(snap, fc_run, drafts, get_scenario_by_id("base"))
    plan_closed = solve_planning_run(snap, fc_run, drafts, get_scenario_by_id("closed_edge"))
    plan_impossible = solve_planning_run(snap, fc_run, drafts, get_scenario_by_id("impossible_demand"))

    locked_results = {
        "benchmark_label": "synthetic_generator_seed_26251",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_window": {"days": 30, "start_date": "2026-05-31", "end_date": "2026-06-29"},
        "forecast_metrics": fc_summary,
        "paired_simulation": sim_res,
        "planner_scenarios": {
            "base": {
                "status": plan_base.solver_status,
                "allocations_count": len(plan_base.allocations),
                "unmet_count": len(plan_base.unmet),
                "objective": plan_base.objective_components.model_dump(),
            },
            "closed_edge": {
                "status": plan_closed.solver_status,
                "allocations_count": len(plan_closed.allocations),
                "unmet_count": len(plan_closed.unmet),
                "explanation_highlights": plan_closed.explanation[:3],
            },
            "impossible_demand": {
                "status": plan_impossible.solver_status,
                "unmet_count": len(plan_impossible.unmet),
                "total_unmet_qty": sum(u.qty for u in plan_impossible.unmet),
            },
        },
    }

    # Cryptographic hash of locked results
    res_json = json.dumps(locked_results, sort_keys=True, indent=2)
    res_hash = hashlib.sha256(res_json.encode("utf-8")).hexdigest()
    locked_results["verification_hash"] = res_hash

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    # Write permanent locked metrics file
    METRICS_PATH.write_text(json.dumps(locked_results, indent=2), encoding="utf-8")
    print(f"Wrote permanent locked benchmark: {METRICS_PATH}")

    # Write timestamped audit copy
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    audit_path = EVAL_DIR / f"{ts_str}_{res_hash[:12]}.json"
    audit_path.write_text(json.dumps(locked_results, indent=2), encoding="utf-8")
    print(f"Wrote audit archive: {audit_path}")

    print("\nLOCKED BENCHMARK SUMMARY (TO DECK SLIDE 5):")
    print("--------------------------------------------------------------------------------")
    print(f"Forecast WAPE (Track 2)     : {fc_summary['track2_routed']['mean_wape']}")
    print(f"P90 Empirical Coverage       : {fc_summary['probabilistic']['p90_empirical_coverage']:.1%}")
    b = sim_res['bootstrap']
    print(f"Fill rate at matched stock   : {b['forecast_policy']['fill_rate_pct']:.1f}% vs {b['fixed_matched']['fill_rate_pct']:.1f}%")
    print(f"Shortage days at matched stk : {b['forecast_policy']['shortage_days']} vs {b['fixed_matched']['shortage_days']}")
    print(f"Verification SHA-256 Hash    : {res_hash[:16]}...")
    print("================================================================================\n")


SIM_V2_PATH = OUT_DIR / "sim_v2.json"


def load_truth_actuals() -> dict[tuple[str, str], np.ndarray]:
    dates = [(datetime(2026, 5, 31) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
    by: dict[tuple[str, str], dict[str, float]] = {}
    for d in json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["demand"]:
        v = d.get("requested")
        if v is None and d.get("issued") is not None and d.get("unmet") is not None:
            v = d["issued"] + d["unmet"]
        if v is not None:
            by.setdefault((d["site_id"], d["item_id"]), {})[d["date"]] = float(v)
    return {k: np.array([s.get(dt, np.nan) for dt in dates]) for k, s in by.items()}


def aggregate_window_coverage(all_paths, site_windows, actuals, horizon: int = 30) -> dict:
    """Coverage of the AGGREGATE L+R window quantiles - the number replenishment targets actually use."""
    hits = {10: 0, 50: 0, 90: 0}
    pin, n = 0.0, 0
    for (site, item), paths in all_paths.items():
        act = actuals.get((site, item))
        if act is None:
            continue
        w = site_windows[site]
        for a in range(0, horizon - w + 1, w):
            seg = act[a:a + w]
            if np.isnan(seg).any():
                continue
            sums = paths[:, a:a + w].sum(axis=1)
            y = float(seg.sum())
            q = {p: float(np.percentile(sums, p)) for p in hits}
            for p in hits:
                hits[p] += y <= q[p]
            pin += 0.9 * (y - q[90]) if y >= q[90] else 0.1 * (q[90] - y)
            n += 1
    return {
        "n_windows": n, "window_days_by_site": site_windows,
        "p10_coverage": round(hits[10] / n, 3), "p50_coverage": round(hits[50] / n, 3),
        "p90_coverage": round(hits[90] / n, 3), "mean_pinball_0.9": round(pin / n, 2),
        "note": "non-overlapping windows inside the 30 held-out days; small n, read with care",
    }


def _aligned_history(snap: Snapshot) -> dict[tuple[str, str], np.ndarray]:
    """Date-aligned daily history; missing/censored days filled with that weekday's mean (keeps the 7-day season)."""
    start = datetime(2026, 1, 1).date()
    n = (datetime.fromisoformat(snap.demand_cutoff).date() - start).days + 1
    arrs: dict[tuple[str, str], np.ndarray] = {}
    for d in snap.demand:
        if d.requested is None:
            continue
        a = arrs.setdefault((d.site_id, d.item_id), np.full(n, np.nan))
        a[(datetime.fromisoformat(d.date).date() - start).days] = d.requested
    for a in arrs.values():
        overall = float(np.nanmean(a))
        for i in np.flatnonzero(np.isnan(a)):
            same = a[i % 7::7]
            a[i] = float(np.nanmean(same)) if not np.isnan(same).all() else overall
    return arrs


def plan_violations(plan, snap, drafts, scenario) -> list[str]:
    """Independent re-check of a plan against the scenario graph and drafts."""
    from setu.planning.graph import apply_scenario, load_base_graph

    caps = {d["edge_id"]: d["capacity_kg"] for _, _, d in apply_scenario(load_base_graph(), scenario).edges(data=True)}
    mass = {i.item_id: i.mass_kg_per_unit for i in snap.items}
    free = {(d.site, d.item): d.capacity_free for d in drafts}
    alloc = {(d.site, d.item): d.allocatable for d in drafts}
    window = {s.site_id: s.delivery_window_h for s in snap.sites}
    bad: list[str] = []
    flow: dict[str, float] = {}
    into: dict = {}
    out_of: dict = {}
    for a in plan.allocations:
        if a.arrival_h > window[a.dest] + 1e-6:
            bad.append(f"window {a.path_ref}")
        into[(a.dest, a.item)] = into.get((a.dest, a.item), 0) + a.qty
        out_of[(a.source, a.item)] = out_of.get((a.source, a.item), 0) + a.qty
        for e in plan.path_refs[a.path_ref]:
            flow[e] = flow.get(e, 0.0) + mass[a.item] * a.qty
    bad += [f"edge {e}" for e, kg in flow.items() if e not in caps or kg > caps[e] + 1e-6]
    bad += [f"storage {k}" for k, q in into.items() if q > free[k]]
    bad += [f"donor {k}" for k, q in out_of.items() if q > alloc[k]]
    bad += [f"receives and donates {k}" for k in set(into) & set(out_of)]
    return bad


def run_addendum_evaluation():
    """Corrected simulation + aggregate coverage + planner-vs-baseline. Written ONCE to out/sim_v2.json.

    Supersedes only the `paired_simulation` section of out/metrics.json (see out/ERRATA.md); the locked file itself
    is not modified. Uses the frozen forecast code and the held-out truth for evaluation only - nothing is tuned.
    """
    import platform
    import subprocess
    import time

    import networkx
    import scipy

    from setu.api.track2 import get_scenario_by_id

    if SIM_V2_PATH.exists():
        print(f"[ADDENDUM] {SIM_V2_PATH} already exists. Refusing to overwrite.")
        sys.exit(0)

    snap = load_snapshot("SNAP-26251-150")
    actuals = load_truth_actuals()
    fc, paths, windows = run_forecast(snap, horizon_days=30, seed=26251)
    sim = run_paired_simulation(snap, fc, windows, truth=actuals, num_seeds=20, horizon_days=30)
    coverage = aggregate_window_coverage(paths, windows, actuals)

    # Baselines on date-aligned history (the locked table dropped NaN days, shifting the weekly season).
    hist = _aligned_history(snap)
    fair = {"seasonal_naive": {"mae": [], "wape": []}, "ewma_alpha_0.2": {"mae": [], "wape": []}}
    for key, act in actuals.items():
        if key not in hist:
            continue
        for name, pred in (("seasonal_naive", seasonal_naive(hist[key], horizon=30, season=7)),
                           ("ewma_alpha_0.2", ewma(hist[key], horizon=30, alpha=0.2))):
            fair[name]["mae"].append(mae(act, pred))
            w = wape(act, pred)
            if w is not None:
                fair[name]["wape"].append(w)
    fair = {k: {"mean_mae": round(float(np.mean(v["mae"])), 2), "mean_wape": round(float(np.mean(v["wape"])), 3)}
            for k, v in fair.items()}

    drafts = project_stock_and_drafts(snap, fc, windows)
    planner = {}
    for sid in ("base", "closed_edge", "reduced_capacity", "delayed_arrival", "impossible_demand"):
        sc = get_scenario_by_id(sid)
        t0 = time.perf_counter()
        plan = solve_planning_run(snap, fc, drafts, sc)
        secs = time.perf_counter() - t0
        w = plan.objective_components.weights

        def total(oc):
            return w["shortage"] * oc.shortage + w["transport"] * oc.transport + w["expiry"] * oc.expiry

        short = lambda lines: sum(u.qty for u in lines if u.reason == "supply_shortage")
        planner[sid] = {
            "status": plan.solver_status, "runtime_s": round(secs, 3),
            "constraint_violations": plan_violations(plan, snap, drafts, sc),
            "milp": {"supply_shortage_qty": short(plan.unmet), "weighted_cost": round(total(plan.objective_components), 2)},
            "nearest_source": {"supply_shortage_qty": short(plan.baseline.unmet),
                               "weighted_cost": round(total(plan.baseline.objective_components), 2)},
        }

    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT_DIR).stdout.strip()
    except OSError:
        commit = "unknown"
    result = {
        "benchmark_label": "synthetic_generator_seed_26251",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "supersedes": {"file": "out/metrics.json", "section": "paired_simulation", "see": "out/ERRATA.md"},
        "build": {"git_commit": commit, "dataset_fingerprint": fc.dataset_fingerprint, "python": platform.python_version(),
                  "numpy": np.__version__, "scipy": scipy.__version__, "networkx": networkx.__version__},
        "paired_simulation": sim,
        "aggregate_window_coverage": coverage,
        "forecast_baselines_date_aligned": fair,
        "planner_vs_nearest_source": planner,
    }
    body = json.dumps(result, sort_keys=True, indent=2)
    result["verification_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SIM_V2_PATH, "x", encoding="utf-8") as fh:  # "x": atomic refuse-to-overwrite
        fh.write(json.dumps(result, indent=2))
    print(f"Wrote {SIM_V2_PATH}")
    print_simulation(sim)
    print("Aggregate-window coverage:", coverage)
    print("Date-aligned baselines:", fair)
    for sid, p in planner.items():
        print(f"{sid:<18} {p['status']:<8} {p['runtime_s']:>6.2f}s violations={len(p['constraint_violations'])} "
              f"MILP short/cost {p['milp']['supply_shortage_qty']}/{p['milp']['weighted_cost']} "
              f"nearest {p['nearest_source']['supply_shortage_qty']}/{p['nearest_source']['weighted_cost']}")


def main():
    if "--locked" in sys.argv:
        run_locked_evaluation()
    elif "--addendum" in sys.argv:
        run_addendum_evaluation()
    else:
        run_dev_evaluation()


if __name__ == "__main__":
    main()
