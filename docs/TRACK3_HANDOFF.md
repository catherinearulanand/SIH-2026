# Setu Supply (SIH26251) — Track 3 Handoff (Workbench, Capture & Offline Queue)

**Owner:** Person 3 — UI / Device Owner (`frontend/`)

## 1. Quick Start

```bash
cd frontend
npm.cmd install
npm.cmd run dev
```

- **Local Dev URL:** `http://localhost:5173`
- **Typecheck & Production Build:**
  ```bash
  cd frontend
  npm.cmd run typecheck
  npm.cmd run build
  ```

## 2. Delivered Modules (`frontend/src/`)

1. **Operator Workbench & Stock Authority (`src/views/WorkbenchOverviewView.tsx`)**
   - Depot Digital Representation (`SITE-NORTH-01`, `SITE-EAST-02`, `SITE-WEST-03`, `SITE-SOUTH-04`) with capacity, receiving window, and frozen planning snapshot (`snapshot_id`, `as_of_time`, `version`, `content_sha256`).
   - Freshness Timestamp Trio (`occurred_at`, `ingested_at`, `as_of_time`) with stale-snapshot alerts (>24h).
   - Owned Exceptions queue (`Needs Action` cards with role owner and target SLA).
   - Authoritative Usable vs Gross Stock Matrix enforcing the Union Rule (`Quality-Unavailable = Expired ∪ Damaged ∪ Quarantined` counted once per batch).
   - Medical QA Quarantine Release control (`MEDICAL_QA_OFFICER` only) and CSV Import Schema Validator (`POST /api/v1/imports/csv`).

2. **IoT Capture Adapter & Gateway Store-and-Forward Controls (`src/views/IoTCaptureGatewayView.tsx`)**
   - Registered Device Provisioning Registry (`DEV-GW-NORTH-01`, `DEV-COLD-NORTH-02`, `DEV-BAR-EAST-01`, plus revoked device `DEV-REVOKED-09`).
   - Exact Section 6 `evt-demo-00042` JSON payload inspector (`POST /api/v1/observations`).
   - Monotonic `(boot_session, sequence)` replay/gap detection, calibration check, cold-chain excursion (`+9.6°C` flagging `BCH-MED-2026-M1`), and spoofed signature rejection (`403`).
   - Explicit operator promotion workflow ensuring raw IoT observations never silently mutate inventory or auto-release medical quarantine.

3. **180-Day Forecasting, Constrained GIS Logistics Planner & Deterministic Policy Engine (`src/views/ForecastAndGisPlannerView.tsx`)**
   - Rolling-origin evaluation across the 180-day synthetic dataset (`120d Train / 30d Selection / 30d Locked Test`, `seed = 26251`) comparing `SEASONAL_NAIVE`, `EWMA`, and `CROSTON_SBA` (`MAE`, `RMSE`, `MAPE`, `Stockout Miss Rate`, `Overbuild Ratio`).
   - Forecast Failure Fallback toggle (`Last-Verified Snapshot + Conservative Safety Buffer`).
   - Interactive 6-node / 7-corridor fictional GIS transport network (`POST /api/v1/planning-runs`) with one-click corridor closure chips (`CORR-N1` Landslide Block), Nearest-Feasible-Source baseline comparison, and Section 5 illustrative replenishment math (`max(0, 100 + 20 - 50 - 10) = 60` packs vs `40`-pack storage headroom $\rightarrow$ `40` Wave 1 + `20` Split-Arrival Wave 2).
   - Server-side Deterministic Policy Engine (`DET-POLICY-2026.1`) returning `ALLOW` / `REQUIRES_REVIEW` / `DENY`.

4. **Independent Approval (`Creator ≠ Approver`), Atomic Reservation & Partial Receipt (`src/views/ApprovalFulfilmentView.tsx`)**
   - Enforces separation of duties (`Creator ≠ Approver` $\rightarrow$ `403 SEPARATION_OF_DUTIES_VIOLATION`), Stale Snapshot Gate (`409 STALE_SNAPSHOT_GATE_BLOCKED`), and Atomic Reservation bounds (`409 INSUFFICIENT_ALLOCATABLE_STOCK`).
   - Partial Receipt Reconciliation (`POST /api/v1/shipments/{id}/receipt-parts`) partitioning `Accepted + Damaged + Rejected` (with `Quarantine` as a non-additive subset) while keeping missing shipment balance open.

5. **IndexedDB Offline Evidence Queue, Scoped Audit Sink & Section 10 Extensions (`src/views/OfflineSyncAndExtensionsView.tsx`)**
   - Browser `IndexedDB` (`src/services/indexedDbQueue.ts`) storing cached snapshots and provisional offline evidence (`POST /api/v1/sync`), with explicit `CONFLICT` resolution (`SUPERSEDED_BY_SERVER` / `RESUBMIT_AS_NEW_VERSION`).
   - Expired Offline Authority Lease fallback (Section 12): hides protected cached records and presents only a blank supervised minimal evidence form.
   - Optional Local Explanation Assistant (Section 10.1) with pre-retrieval compartment filtering and prompt-injection containment (`UNTRUSTED-FIELD-NOTE-999`).
   - Conditional Custody Acknowledgement Digests (Section 10.2) with `SHA-256` payload digest and `Ed25519` dual signatures.

6. **Section 17 Critical Acceptance Suite Runner (`src/components/AcceptanceTestSuiteModal.tsx`)**
   - Accessible from the top bar via **"Verify 15 Scenarios"**, executing all 15 Section 17 Critical Acceptance Scenarios end-to-end and recording build ID, dataset fingerprint, expected result, and actual result.
