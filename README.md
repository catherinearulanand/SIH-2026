# Setu Supply — SIH26251

Team repository for the synthetic predictive logistics and supply-assurance demonstration.

Build ownership:
1. Track 1 — data/backend, imports, inventory and fulfilment.
2. Track 2 — forecasting, projections and GIS planning.
3. Track 3 — workbench, capture and offline queue (`frontend/`, [`docs/TRACK3_HANDOFF.md`](docs/TRACK3_HANDOFF.md)).
4. Track 4 — integration, security review, recovery and packaging.

Work on separate feature branches and integrate through pull requests. All demonstration data is fictional ordinary supplies. Do not commit credentials, generated databases or operational data.

> **Submission Sentence:** *"Setu Supply joins uncertainty-aware forecasting, constraint-aware GIS planning and authenticated inventory evidence in one accountable replenishment workflow, with offline evidence capture and human-controlled execution."*

---

## Track 3 Deliverable: UI / Device Owner (`frontend/`)

This directory contains the complete **Person 3 (UI / Device Owner)** implementation aligned with the Final Product & Implementation Proposal (see also [`docs/TRACK3_HANDOFF.md`](docs/TRACK3_HANDOFF.md)):

1. **Tab 1 — Operator Workbench, Stock Authority, Freshness & CSV Evidence (`src/views/WorkbenchOverviewView.tsx`)**
   - Depot Digital Representation header with frozen planning snapshot (`SNAP-NORTH01-V14`), graph version, policy version, data custodian, and the 3 independent timestamps (*Observed As-Of*, *Last Server Sync*, *Last Physical Count*).
   - Owned exception cards with severity and 1-click navigation.
   - Deterministic Inventory Accounting Matrix enforcing $\text{Quality-Unavailable} = \text{Expired} \cup \text{Damaged} \cup \text{Quarantined}$ (union, never double-subtracted), $\text{Usable} = \text{Physical} - \text{Quality-Unavailable}$, and $\text{Allocatable} = \text{Usable} - \text{Reserved}$.
   - Batch quality table with **Medical QA Quarantine Release** (`MEDICAL_QA_OFFICER` role check — Scenario 5), **CSV Import Validator** (`POST /api/v1/imports/validate` & `/commit` — Scenario 7), and **Compensating Physical Count Adjustment**.

2. **Tab 2 — IoT Capture Adapter, Gateway Buffer & Physical-Truth Controls (`src/views/IoTCaptureGatewayView.tsx`)**
   - Implements the exact Section 8 & Section 11 `IoTObservation` contract (`POST /api/v1/observations`), including the `evt-demo-00042` record (`scanner-demo-01`, `boot-demo-03`, `sequence: 42`).
   - Provisioned device registry (`scanner-demo-01`, `coldchain-sensor-02`, `rfid-portal-03`) bound to site compartments.
   - One-click injectors for **Scenario 12**: Valid barcode scan, duplicate sequence replay (`DUPLICATE_IGNORED`), sequence gap detection, cold-chain excursion (`31.8°C`), implausible/spoofed probe reading (`96.5°C`), and passive RFID read (proving repeated RFID detections never auto-increment stock without an authorized business event).

3. **Tab 3 — 180-Day Forecasting (120/30/30), Constrained GIS Graph Planner & Deterministic Policy (`src/views/ForecastAndGisPlannerView.tsx`)**
   - **180-Day Synthetic Dataset (`seed = 26251`):** 120d Training / 30d Selection / 30d Locked Test comparing **Seasonal-Naive (7d)**, **EWMA ($\alpha=0.3$)**, and **Croston-SBA** (intermittent demand), plus the **Minimum-Evidence Gate** (`ITM-MED-ANTISEP`) and **Scenario 10 Forecast Failure Fallback Toggle**.
   - **Constrained GIS Freight Replenishment Planner (`POST /api/v1/planning-runs`):** Interactive fictional 6-node, 7-corridor graph. Click any corridor chip (e.g., `EDG-N1-MAIN`) to close/reopen an edge (**Scenario 11**) and compare the Setu Constrained Planner against the Nearest-Feasible-Source Baseline.
   - **Section 5 Illustrative Replenishment & Storage Split-Arrival Trace:** Demonstrates $\max(0, 100 + 20 - 50 - 10) = 60\text{ Crates}$ against a $40\text{-Crate}$ depot storage headroom cap $\rightarrow$ proposing $40\text{ Crates}$ (Wave 1) + $20\text{ Crates}$ (Reviewed Split-Arrival Wave 2).
   - **Deterministic Policy Engine (`DET-POLICY-2026.1`):** Evaluates 7 hard rules (`ALLOW` / `REQUIRES_REVIEW` / `DENY`).

4. **Tab 4 — Independent Approval, Atomic Reservation, Dispatch & Partial Receipt (`src/views/ApprovalFulfilmentView.tsx`)**
   - Enforces **Separation of Duties (Scenario 4)**: request creator cannot self-approve (`403 SELF_APPROVAL_PROHIBITED`).
   - Enforces **Stale Snapshot Gate (Scenario 9)** and **Atomic Reservation Bounds (Scenario 2)**.
   - **Partial Receipt Disposition Reconciliation (`POST /api/v1/shipments/{id}/receipt-parts`):** Enforces the `Accepted + Damaged + Rejected` partition and `Quarantine` subset rule, plus 1-click verifiers for **Scenario 1** (idempotent retry vs altered payload `409`) and **Scenario 6** (overage `422`).

5. **Tab 5 — IndexedDB Offline Queue, Conflict Resolution, Audit Sink & Subordinate Extensions (`src/views/OfflineSyncAndExtensionsView.tsx`)**
   - **IndexedDB Provisional Queue & Sync (`POST /api/v1/sync`):** Simulates stale-version offline conflicts (**Scenario 8**) with zero last-write-wins overwrites, plus **Expired Offline Authority Lease Mode (Section 12)** which hides protected cached records and presents a Blank Supervised Evidence Form.
   - **Subordinate Extension A — Optional Local Explanation Assistant:** Pre-filters SOP compartments by role/site before context assembly, defaults to the Deterministic Template when disabled, and blocks adversarial prompt injection (**Scenario 14**).
   - **Subordinate Extension B — Conditional Custody Acknowledgement Digests:** Asynchronous off-chain commitment hashes where pausing validator quorum never freezes local operations.

---

## Quickstart (Offline-Ready)

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173` and use the **Section 20 — 3-Minute Demo Video Script Bar** at the top of the screen to step through every scene (`0:00–3:00`).
