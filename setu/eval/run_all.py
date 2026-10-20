"""Evaluation CLI runner for Setu Supply Track 2.

Supports:
  --dev     Runs evaluation on the validation slice (days 120-149), clearly labeled 'tuning score'.
  --locked  Runs ONCE on held-out test truth (days 150-179) and writes out/metrics.json permanently.
"""

from datetime import datetime, timezone
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


def run_dev_evaluation():
    """Run dev evaluation on the validation slice (labeled: tuning score)."""
    print("\n================================================================================")
    print("SETU SUPPLY TRACK 2 - DEV EVALUATION (VALIDATION SLICE)")
    print("LABEL: TUNING SCORE (Hyperparameters tuned on this validation slice)")
    print("================================================================================\n")

    snap = load_snapshot("SNAP-26251-150")

    # Extract validation slice (days 120-149: 2026-05-01 to 2026-05-30)
    val_demand: dict[tuple[str, str], list[float]] = {}
    for d in snap.demand:
        if "2026-05-01" <= d.date <= "2026-05-30" and d.requested is not None:
            val_demand.setdefault((d.site_id, d.item_id), []).append(float(d.requested))

    val_dict = {k: np.array(v, dtype=float) for k, v in val_demand.items()}

    # Create a training-only snapshot (cutoff 2026-04-30)
    train_snap = snap.model_copy(deep=True)
    train_snap.demand_cutoff = "2026-04-30"
    train_snap.demand = [d for d in snap.demand if d.date <= "2026-04-30"]

    summary = evaluate_forecast_on_actuals(train_snap, val_dict, horizon=30)

    print("FORECAST BENCHMARK VS BASELINES (30-day Validation Slice - TUNING SCORE):")
    print("--------------------------------------------------------------------------------")
    print(f"{'Method':<25} | {'MAE':<8} | {'Bias':<8} | {'WAPE':<8}")
    print("--------------------------------------------------------------------------------")
    for m, m_data in summary.items():
        if m != "probabilistic":
            print(f"{m:<25} | {m_data['mean_mae']:<8.2f} | {m_data['mean_bias']:<8.2f} | {m_data['mean_wape']:<8.3f}")

    print("\nPROBABILISTIC UNCERTAINTY METRICS (Block-Bootstrap Envelope):")
    print("--------------------------------------------------------------------------------")
    prob = summary["probabilistic"]
    print(f"P10 Empirical Coverage : {prob['p10_empirical_coverage']:.1%} (target ~10%)")
    print(f"P50 Empirical Coverage : {prob['p50_empirical_coverage']:.1%} (target ~50%)")
    print(f"P90 Empirical Coverage : {prob['p90_empirical_coverage']:.1%} (target ~90%)")
    print(f"P90 Pinball Loss       : {prob['mean_pinball_loss_0.9']:.2f}")

    print("\nPAIRED SIMULATION BENCHMARK (20 seeds, Static (s,S) vs Dynamic Forecast Policy):")
    print("--------------------------------------------------------------------------------")
    sim_res = run_paired_simulation(snap, num_seeds=20, horizon_days=30)
    print(f"{'Policy':<20} | {'Fill Rate':<10} | {'Unmet Qty':<10} | {'Shortage Days':<14} | {'Avg Stock':<10}")
    print("--------------------------------------------------------------------------------")
    for pol, p_data in sim_res.items():
        print(f"{pol:<20} | {p_data['mean_fill_rate_pct']:>8.1f}% | {p_data['mean_unmet_qty']:>9.1f} | {p_data['mean_shortage_days']:>13.1f} | {p_data['mean_avg_stock_holding']:>9.1f}")
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

    test_dict: dict[tuple[str, str], list[float]] = {}
    for d in truth_records:
        if d.get("requested") is not None:
            test_dict.setdefault((d["site_id"], d["item_id"]), []).append(float(d["requested"]))

    test_actuals = {k: np.array(v, dtype=float) for k, v in test_dict.items()}

    snap = load_snapshot("SNAP-26251-150")
    fc_summary = evaluate_forecast_on_actuals(snap, test_actuals, horizon=30, use_croston=True)

    sim_res = run_paired_simulation(snap, num_seeds=20, horizon_days=30)

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
    print(f"Simulation Fill Rate Gain    : {sim_res['forecast_policy']['mean_fill_rate_pct']:.1f}% vs {sim_res['fixed_reorder']['mean_fill_rate_pct']:.1f}%")
    print(f"Shortage Days Reduction      : {sim_res['forecast_policy']['mean_shortage_days']} vs {sim_res['fixed_reorder']['mean_shortage_days']}")
    print(f"Verification SHA-256 Hash    : {res_hash[:16]}...")
    print("================================================================================\n")


def main():
    if "--locked" in sys.argv:
        run_locked_evaluation()
    else:
        run_dev_evaluation()


if __name__ == "__main__":
    main()
