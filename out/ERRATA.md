# ERRATA to out/metrics.json (locked run of 2026-10-20 08:18 UTC)

`out/metrics.json` is kept exactly as written. This note says which parts of it must not be quoted, and where
the corrected numbers are. Corrected results: `out/sim_v2.json` (written once, refuses to overwrite).
All numbers are from the synthetic generator, seed 26251, not field data.

## 1. `paired_simulation` is withdrawn
The simulation behind it never used the Track 2 forecast. Its "forecast policy" was a closed-form Poisson formula
and demand was drawn from the same Poisson mean, so the policy was handed the true demand process. The fixed rule
was arbitrary (6 days of cover, shorter than the 8-day lead-time window), the forecast policy held 58% more stock
(42.8 vs 27.1), no storage cap applied, and `mean_expiry_waste` was never computed.
**Do not use "96.05% vs 80.62% fill rate".**

Replacement (`out/sim_v2.json`, `paired_simulation`): both policies start from the snapshot's real stock, inbound
orders and storage caps, with FEFO issue and expiry; the forecast policy orders up to the Track 2 aggregate P90 over
the site's L+R window; the fixed (s,S) rule is calibrated so its average stock matches (3127 vs 3120 units).
- 20 bootstrap demand paths: fill rate 99.2% vs 93.3%, paired difference +5.9 points (95% CI 5.3 to 6.5);
  shortage days 9.0 vs 40.8.
- The one actual held-out path (days 150-179): 99.9% vs 94.5% fill.
- Caveats: supply from the external source is unlimited; bootstrap demand comes from the same history the forecast
  was fitted on; expiry waste is 0 because no starting batch expires inside the 30-day window.

## 2. Forecast comparison: the routed model does not beat a correctly aligned seasonal-naive baseline
The locked table trained the baselines on the history with missing days dropped, which shifts the 7-day season.
With date-aligned training (`out/sim_v2.json`, `forecast_baselines_date_aligned`), on the same held-out days:

| Method | WAPE | MAE |
|---|---|---|
| seasonal_naive (date-aligned) | 0.699 | 5.18 |
| Track 2 routed (locked file) | 0.739 | 5.94 |
| ewma alpha 0.2 (date-aligned) | 0.758 | 6.01 |

Say "comparable to simple baselines", not "better than". The locked-file margin of the routed model over
seasonal-naive (0.739 vs 0.753) came from the misaligned baseline.

## 3. Protocol slips in the locked run (disclosed, not fixable after the fact)
- It used `use_croston=True`. On the validation slice Croston scored WAPE 0.761 vs 0.746 without it, so the
  validation-based rule would not have selected it. The effect on the locked forecast metrics was not isolated.
- Coverage in `forecast_metrics.probabilistic` is for daily quantiles. Replenishment uses the aggregate L+R P90;
  its coverage is in `out/sim_v2.json`: P90 86.5% (target 90%), P10 21.6% (target 10%), n = 37 windows (small).
  The lower tail is poorly calibrated, which is why `calibrated` stays false.
- The addendum read the held-out truth a second time (to score aggregate windows and the simulation). Nothing was
  tuned on it, and the forecast and planner code were unchanged between the two reads.

## 4. Planner vs nearest-source (`out/sim_v2.json`, `planner_vs_nearest_source`)
Zero constraint violations in all five scenarios, every solve under 0.05 s. The MILP's unmet quantity equals the
nearest-source baseline's in every scenario and its weighted cost is lower by under 0.05%. On this instance the
planner is correct and feasible but gives little advantage over the greedy baseline; do not claim otherwise.
