# Setu Supply — Track 2 Plan (Forecasting, Projection & GIS Planning)

## Goal Description
Build the **Track 2 (Forecasting, Projection & GIS Planning)** pipeline for SIH26251 Setu Supply.
Track 2 owns one single pipeline: **demand history → forecast with honest uncertainty → dated stock projection → replenishment draft → feasible GIS supply plan → measured comparison against simple baselines.**

Track 2 operates under strict boundaries:
- **Zero mutation / zero auth:** Track 2 never mutates live stock, never issues warehouse dispatches, and never owns auth. It reads a frozen planning `Snapshot` and produces immutable run records (`ForecastRun`, `ReplenishmentDraft`, `PlanningRun`).
- **Fixture stubs to real DB:** Other tracks are in progress. Track 2 works against fixture stubs matching frozen contracts. When T1/T3/T4 land, stubs are swapped using the adjustment checklist (§8).
- **No overclaiming:** All models, metrics, and explanations are honest and transparent. Baselines (seasonal naive, EWMA, nearest-feasible-source greedy) are reported alongside results. Dev validation scores are explicitly labeled "tuning score" since hyperparameters are tuned on that slice; the locked test is the single honest benchmark.
- **Project Location & Environment:** Initialized under `hackathons/setu-supply/` with `uv` and pinned Python 3.12 (for wheel safety). Git commits use the designated noreply author (`Aakash A <230161983+Oxyrine@users.noreply.github.com>`).

---

## Decisions Taken at Contract Freeze

1. **Priority Weighting:**
   Priority 1 is critical (life-saving) and 5 is low priority. The MILP shortage penalty multiplies the shortage cost by `(6 - priority_i)`, giving Priority 1 a multiplier of 5 and Priority 5 a multiplier of 1. Leaving critical items unmet is penalized most severely.

2. **Demand Surge & Capacity Gap Distinction:**
   - In `impossible_demand`, demand surge is applied to demand rather than proposed draft:
     $$\text{requirement}_{d, i} = \max(0, \lceil \text{demand\_factor}_{d, i} \cdot P90_{d, i} \rceil - \text{allocatable}_{d, i} - \text{inbound}_{d, i})$$
   - Storage capacity enforces $\sum_{s, p} x_{i, s, d, p} \le \text{storage\_free}_{d, i}$. When raw requirement exceeds destination storage capacity, the shortfall caused by warehouse space limits is explicitly distinguished in the output as `capacity_gap = max(0, requirement - storage_free)`, while shortfall due to lack of donor inventory or edge transport capacity is reported as supply shortage.

3. **Cryptographic Fingerprinting with `policy_mode`:**
   - `dataset_fingerprint` is computed using `hashlib.sha256` over the canonical JSON serialization of **all** snapshot fields consumed (`items`, `sites`, `batches`, `reservations`, `inbound`, and filtered `demand`) plus run configuration (`cutoff`, `horizon_days`, `policy_mode`, `seed`).
   - Including `policy_mode` ensures that runs requesting `quantile` vs `mean_plus_buffer` produce distinct fingerprints and distinct `run_id`s, preventing cache collisions in `runs_db`.
   - `run_id = f"fc-{fingerprint[:12]}"`.
   - `plan_id = f"plan-{hashlib.sha256(f'{forecast_fingerprint}:{scenario_id}:{graph_version}:{weights_json}'.encode()).hexdigest()[:12]}"`.

4. **Horizon vs Lead-Time Alignment:**
   - For each site $s$, lead-time window is $W_s = L_s + R$, with $L_s = \lceil \text{shortest\_transit\_h\_on\_base\_graph} / 24 \rceil$ and $R = 7$.
   - The API enforces `horizon_days >= max_s(W_s)` (returns **HTTP 422** if client requests a horizon shorter than the maximum lead-time window).
   - Furthermore, the forecasting engine automatically extends internal simulation horizon to $\max(\text{horizon\_days}, \max_s(W_s) + 7)$ to ensure full projection and aggregate quantile coverage.

5. **Uniform ISO Dates & Explicit Cutoff Boundary:**
   All dates across all models are strict ISO 8601 calendar dates (`YYYY-MM-DD`):
   - Fictional Start Date (Day 0): `2026-01-01`.
   - Train Window: Days 0–119 (`2026-01-01` to `2026-04-30`).
   - Validation Window: Days 120–149 (`2026-05-01` to `2026-05-30`).
   - Snapshot Cutoff: `demand_cutoff = "2026-05-30"`. `fixtures/SNAP-26251-150.json` contains demand rows strictly $\le \text{2026-05-30}$.
   - `setu/forecast/run.py` explicitly drops any demand row with `date > demand_cutoff` (essential for leakage prevention).
   - Locked Test Truth Window: Days 150–179 (`2026-05-31` to `2026-06-29`).

6. **Strict HTTP Error Mapping & Input Guards:**
   - `load_snapshot` validates `snapshot_id` against `^[A-Za-z0-9-]{1,64}$`.
   - The FastAPI router explicitly catches `ValueError` and `FileNotFoundError` from `load_snapshot` and returns **HTTP 404** (preventing path traversal and avoiding 500 errors).
   - `POST /api/v1/planning-runs` validates that `forecast_run_id` exists in `runs_db` (returns **HTTP 404** if not found).
   - It validates that the forecast run's `input_snapshot_id == requested snapshot_id` (returns **HTTP 409 Conflict** on mismatch).
   - Unknown `scenario_id` returns **HTTP 404**.
   - In-memory caches `runs_db` and `plans_db` are capped at 100 entries via FIFO eviction to guard against memory exhaustion.

7. **Site-Specific Lead-Time Window ($L+R$) & Donor Rule:**
   - $L$ is unambiguously defined as $\lceil \text{transit\_h} / 24 \rceil$ for the shortest path to the nearest *other* depot on the **nominal base graph** (no scenario applied).
   - $R = 7$ (declared review period).
   - Quantiles are simulated over each site's specific $W = L + R$ window; integer replenishment targets are rounded up: $\text{target} = \lceil P90_{L+R} \rceil$.
   - Deficit sites (`requirement > 0`) cannot act as donors ($s \ne d$, donor availability $= 0$).
   - Candidate donor availability is capped at $\max(0, \text{allocatable} - \text{P50 lead-time demand})$.

---

## Open Decisions to Raise at Team Contract Freeze (H0–H1)

1. **Recommendation Record Ownership & Policy Check:** Who owns the recommendation record and policy check (T1 or T4)? Track 2 hands them `ReplenishmentDraft` alongside `plan_id`.
2. **Planner Multi-Site Visibility Scope:** The planner inspects system-wide stock to evaluate candidate donors. What may a planner scoped to Site A see about Site B?
   *Default adopted:* Full quantities are used internally by the solver, but the published `PlanningRun` allocations display only `source_id` and transfer quantities for out-of-scope sites.
3. **Storage Capacity Units:** Are site storage capacities in packs per item or in kg?
   *Default adopted:* Site storage capacities are in packs per item (`storage_capacity_base{item_id: qty}`), while transport edge capacities are in total mass (`capacity_kg`), converted using each item's `mass_kg_per_unit`.

---

## What T2 Hands to Other Tracks (§7)

- **Track 1 (Data/Backend):**
  - `fixtures/demand_raw.csv` (dirty rows with wrong units, corrupted headers, and unknown batch IDs for import validation).
  - The `Snapshot` contract T1 must produce.
  - The `ReplenishmentDraft` shape for the recommendation record.
- **Track 3 (UI/Device):**
  - All sample JSON files (`contracts/samples/*.json`) by G3/G4.
  - GeoJSON layers (nodes, edges with `open/closed/binding` status, and allocation flows).
  - UI fields that must remain visible: `warnings`, `low_evidence`, `range_method`, `calibrated`, `solver_status`, `objective_components`, `explanation`, `scenario.hypothetical`.
- **Track 4 (Integration/Security):**
  - The router with `Depends(current_actor)` placeholder.
  - The scope rule from decision 2.
  - Evaluation files (`out/metrics.json`) and run hashes for the evaluation panel and audit logging.
  - Note that GET endpoints use an in-memory run store capped at 100 entries (runs are deterministic and reproducible; persistent DB storage lands with T1).
- **Deck & Video Presentation:**
  - Metrics exclusively from `out/metrics.json`, labeled "synthetic generator, seed 26251".

---

## Adjustment Checklist When Other Tracks Finish (§8)

### When Track 1 (T1) Lands:
- [ ] Replace the fixture branch in `setu.snapshot_provider.load_snapshot` with T1's query.
- [ ] Run `tests/test_track2_contract.py` against T1's real snapshot.
- [ ] Reconcile enum and field names (`quality_state`, `qty_base`) in `setu/contracts.py` only.
- [ ] Confirm reservations are deducted at $t_0$ only and not double counted against the forecast.
- [ ] Confirm the demand table carries `requested`, `issued`, `unmet`, and `stockout_flag`. If `requested` is absent, fall back to `issued + unmet` and add a warning.

### When Track 3 (T3) Lands:
- [ ] Verify that every essential field (`warnings`, `low_evidence`, `range_method`, `calibrated`, `solver_status`, `explanation`, `hypothetical`) is rendered in the UI.
- [ ] If the UI requires a transformed shape, add a view field to `setu/contracts.py` rather than recomputing client-side.
- [ ] Confirm the map renders using local assets only (no external CDN tile dependency).

### When Track 4 (T4) Lands:
- [ ] Swap the `Depends(current_actor)` placeholder in `setu/api/track2.py` for T4's real auth dependency.
- [ ] Add negative test cases: forecast-run for an out-of-scope site returns HTTP 403; planning output redacts out-of-scope site details.
- [ ] Confirm server-side execution requires no external egress (offline-first).
- [ ] Include `run_id` and `plan_id` in audit log events.

### When Recommendation Owner Lands:
- [ ] Confirm the consumer reads `proposed_qty`, `split`, and `plan_id`.
- [ ] Verify policy re-checks at commit time.

---

## Hour-by-Hour Timeline (H0–H36)

| Hours | Focus & Deliverables | Gate / Milestone |
|---|---|---|
| **H0–1** | Contract freeze with team. Settle decisions 1–3. Write `setu/contracts.py`. | Contracts merged |
| **H1–3** | `gen.py`, `graph.geojson`, `scenarios.json`, `fixtures/SNAP-26251-150.json`. | **G1 (H3):** T1 + T3 have fixtures and snapshot sample |
| **H3–6** | `baselines.py`, `route.py` (intermittent $\to$ EWMA + warning), `split.py`, `metrics.py`; tests for leakage, missing $\ne$ 0, and censoring. | **G2 (H6):** `uv run python -m setu.eval.run_all --dev` prints baseline comparison table |
| **H6–8** | `uncertainty.py` (block-bootstrap aggregate quantiles over site $L+R$ windows), `run.py`, dataset fingerprinting. | `forecast_run.json` sample handed to T3 |
| **H8–10** | `projection.py` (FEFO, arrival-date physical stock check, replenishment draft + capacity split). | **G3 (H10):** `POST /forecast-runs` live; `ReplenishmentDraft` handed to recommendation owner |
| **H10–11** | Midpoint team sync: review what T1/T3/T4 expose. | Adjust stubs only; freeze core logic |
| **H11–16** | `planning/graph.py` (undirected `nx.Graph`), `planning/solve.py` (HiGHS MILP), binding slacks, geojson layers. | Core planner operational |
| **H16–18** | `baseline.py` (greedy nearest), `explain.py` (factual attribution), tests for 3 scenarios + impossible demand. | **G4 (H18):** `POST /planning-runs` returns plan + explanation; 4 planning samples handed to T3 |
| **H18–22** | **Sleep block.** Non-negotiable; G4 is the demo-critical floor. | Rest |
| **H22–24** | Integration: swap T1's provider, mount under T4's auth dependency, run contract tests on real data (§8). | Integrated forecast + planning pipeline |
| **H24–27** | P1 items: Croston-SBA intermittent method, empirical coverage check, `sim.py` paired simulation. | Evaluated simulation |
| **H27–28** | **Locked test evaluation** (run once) $\to$ `out/metrics.json` $\to$ numbers to deck. | Frozen benchmark numbers |
| **H28–30** | Rehearse demo video beats (forecast vs baseline; edge closure $\to$ plan reroutes). Freeze code, write README. | Code freeze |
| **H30–36** | Buffer: bug fixes only, zero new features. | Submission |
