# Track 1 handoff — data backend v1.0

## What works

Track 1 implements the data/backend portion of the supplied final proposal: canonical inventory-event import, source authority, batch accounting, independent approval, atomic FEFO reservation, partial dispatch/receipt, disposition reconciliation, ledger lineage, frozen planning snapshots and separate demand observations. All data and locations remain fictional ordinary supplies.

Python 3.10+ standard library and SQLite are used so teammates can run immediately without fetching packages. This is a modular application with a replaceable HTTP transport, not a FastAPI implementation. SQLite `BEGIN IMMEDIATE` serializes all business writers; the API also reads a consistent database snapshot. One local API instance is the supported deployment. PostgreSQL/concurrent distributed deployments require a reviewed migration; do not point multiple hosts at a shared SQLite file.

## Quick start

From the repository root:

```bash
cd backend
python -m setu_backend.cli init
python -m setu_backend.cli demo-users
python -m setu_backend.cli serve
```

From a second terminal, also in `backend/`:

```bash
python demo_client.py --import-only
python demo_client.py --import-only
python demo_client.py
```

The first import accepts **9** events; the second accepts **0** and reports **9** exact duplicates. The full client imports (or skips the same events), freezes a snapshot, creates/submits a 20-bottle request, approves with a separate identity, dispatches, receives 12 then 8, reconciles and closes. The client makes real HTTP calls and does not print tokens. Each full run moves another 20 bottles; use a fresh database for a clean rehearsal. It is not a mock UI or forecasting demo.

Windows: use `py` in place of `python` if needed. No Unix shell activation is necessary. Never run `demo-users` again on the same credentials file: it refuses overwrite. To reset, stop the API and select a new database and new token file:

```bash
python -m setu_backend.cli --db rehearsal.sqlite3 init
python -m setu_backend.cli --db rehearsal.sqlite3 demo-users --output rehearsal.env
python -m setu_backend.cli --db rehearsal.sqlite3 serve
```

The client then uses `--secrets rehearsal.env`. No generated credentials or databases belong in Git.

### Container option

From `backend/`, `docker compose up --build`. This creates a named persistent volume, initializes once, runs as UID 10001, drops capabilities and exposes only host localhost:8000. Demo tokens are in `/data/demo-secrets.env` inside that volume. For an in-container rehearsal:

```bash
docker compose exec backend python demo_client.py --secrets /data/demo-secrets.env
```

The Python runtime is the tested path in this delivery; the Docker packaging must be built and exercised on a machine with Docker. Track 4 should pin the reviewed base-image digest and CI action SHAs before any pilot. No image/dependency security certification is claimed.

## Contract rules

- API prefix `/api/v1`; OpenAPI at `/openapi.json` and `docs/openapi.json`.
- Every data call requires `Authorization: Bearer <role token>`. Only health and the API description are public.
- All retryable POSTs require `Idempotency-Key` except import preview/commit: import commit uses the actor-bound `preview_id`. Store keys with offline evidence before transmission. Exact retry returns the original result, including its old object version. Fetch current state for the next action. A changed payload with the same key is a 409.
- Object transitions use `expected_version`; inventory/count writes use the global stock/input `revision` as `expected_version`. A 409 must trigger refresh/review, not blind version substitution.
- Unknown top-level JSON fields are rejected. Actor, roles, source authority and approval identity come from the server, never from JSON.
- Quantities use positive **integer canonical units** (counts of PACK/BOTTLE), maximum 10,000,000 per event. Receipt dispositions/counts permit zero. This fixture requires no fractional unit; fractional supply types require a versioned fixed-point schema change, never floats.
- Timestamps are UTC on output; observation timestamps require a nonfuture explicit offset. Times of occurrence, server posting and last count remain separate. Independent source synchronization time is explicitly unknown (`last_synchronization_at: null`); it is not inferred from server posting time.
- Existing CSV event IDs are preserved for fixture interoperability; generated records use UUID-based IDs. Identifiers are immutable.
- Errors: `{code,message,field_errors,correlation_id,current_version}`; 401 identity, 403 authority, 404 inaccessible/missing object, 409 conflict/staleness/accounting, 422 validation, 503 database contention. UI should display reason codes and offer explicit review.
- Transport bounds: 2.1 MB JSON, 2 MB CSV, 5,000 CSV rows, 100 lines per receipt, 32 active HTTP handlers, 10-second socket timeout. CORS permits only configured origins (default localhost ports 5173/3000). This is not an enterprise API gateway or abuse-resistant internet deployment.

## Identity and scopes

`demo-users` generates separate tokens for custodian, storekeeper, planner, approver, dispatcher, receiver, QA, auditor and admin, each scoped to DEMO_A and DEMO_B. Only token hashes are stored. Provision narrower accounts with:

```bash
python -m setu_backend.cli actor alice --roles receiver --sites DEMO_B
python -m setu_backend.cli revoke alice
```

`actor` prints the new token once and rotates any previous token for that ID. Provisioning is a trusted local administrator operation. Roles/scopes are reloaded for every API call; tokens do not expire automatically. Track 4 owns approved identity/SSO, MFA, session expiry, local-administration auditing, gateway/device authentication and TLS. Existing opaque tokens must remain local to this synthetic demo.

| Role | Mutations/read authority |
|---|---|
| custodian | CSV import, demand, physical-count reconciliation; ordinary stock evidence |
| storekeeper | Ordinary stock evidence; simulated observations |
| planner | Draft/submit, freeze snapshots; creator may cancel undispatched requests |
| approver | Independent approval/rejection, reconciliation, closure; reviewer may cancel |
| dispatcher | Dispatch from an approved reservation |
| receiver | Receipt evidence at the destination scope |
| qa | Quarantine RELEASE; never implicitly granted by admin role |
| auditor | Scoped audit reads and snapshots |
| admin | No ordinary business approval privileges |

Inventory/events/catalog/demand reads filter by authorized site. Request reads and approval/dispatch require both endpoint sites. A shipment is visible to its authorized source or destination for handover/receipt; a receiver needs destination authority to receive, not blanket source-inventory access. Audit records whose full scope is not authorized are omitted. Snapshot access requires all sites frozen into that snapshot; guessed IDs cannot expand scope.

## Dataset and import

The supplied CSV is retained exactly at `backend/data/synthetic_inventory_events.csv`, alongside `rejected_example.csv`. It contains 9 events, 2 sites, 3 items and 5 batches. It is not a 180-day forecasting dataset.

| Batch | Site | Usable | Quarantined | Unit |
|---|---|---:|---:|---|
| WATER_A1 | DEMO_A | 265 | 0 | BOTTLE |
| WATER_A2 | DEMO_A | 60 | 0 | BOTTLE |
| WATER_B1 | DEMO_B | 90 | 0 | BOTTLE |
| RATIONS_A1 | DEMO_A | 134 | 0 | PACK |
| MED_A1 | DEMO_A | 108 | 12 | PACK |

`POST /imports/validate` takes `{source_id:"SIH_SYNTHETIC_CSV",csv_text:"..."}`. It runs syntax, mapping, role, batch metadata, duplicate and balance checks against a rollback-only savepoint. It returns row errors or an actor-bound `preview_id`, original-content SHA-256 and current revision. No stock changes during preview.

`POST /imports/commit` takes the same fields plus `preview_id`. A valid preview lasts 15 minutes, binds actor/source/content/revision, and is revalidated inside the write transaction. Commit is all-or-nothing. Repeating the committed preview returns the original result. Reimporting the same CSV via a new preview skips exact events; a changed payload under an existing event ID is rejected. `preview_sha256` is returned for display; if echoed, it is informational. The server binds the actual content to its stored preview hash.

Only the explicit synthetic source is enabled. The source registry records owner, authoritative fields, permitted use, sites, freshness rule and version. There is no Army/CICP/MISO/ERP connector. `setu_backend/adapters.py` declares a read-only adapter boundary; adding a real source requires approved mappings and authority, not a renamed simulator.

Events are append-only. Historical observations are **posted** against current balances and never rewrite earlier snapshots. Posting sequence, not occurred-time sorting across separate imports, is the authoritative replay order. A late historical issue must still pass current accounting checks. Corrections must be new authorized evidence events; arbitrary balance replacement is unavailable.

## Accounting and fulfilment

Physical on-hand is the sum of **disjoint** usable, quarantined, damaged, rejected and expired buckets. Expiry dynamically makes all remaining goods unavailable once `expiry_date < current UTC date`; the physical total stays unchanged. Reservations remain visible even if their batch later expires, but allocation/dispatch is blocked. Allocatable is `max(usable - reserved, 0)`.

A quarantined receipt is one physical receipt into quarantine, not both usable and quarantine. A rejected receipt represents physical goods held at the destination in a rejected bucket; it is not an automatic return. Reverse logistics and stock loss/discrepancy exception closure are not implemented. Damaged/rejected goods require reasoned reviewer reconciliation. Forecast demand cannot mutate stock.

1. `POST /requests`: `{source_site_id,destination_site_id,item_id,quantity,input_revision,reason,snapshot_id?}` → DRAFT version 1.
2. `POST /requests/{id}/submit`: `{expected_version}` → SUBMITTED.
3. `POST /requests/{id}/approve`: `{expected_version,reason}` → APPROVED and reserve all quantities in the **same transaction**, using earliest-expiry-first batches. The creator cannot approve. `/reject` is the alternative.
4. `POST /requests/{id}/dispatch`: `{expected_version,quantity}` → shipment with lines. Partial dispatch leaves remaining reservations; actual dispatch reduces source physical stock and reservation once. Shipment version starts at 1.
5. `POST /shipments/{id}/receipt-parts`: `{expected_version,receipt_part_id,lines:[{batch_id,accepted,quarantined,damaged,rejected}]}`. The four quantities partition that receipt part. Cumulative physical receipts cannot exceed dispatch per batch. Each part has a unique ID; retries reuse the original key and body.
6. `POST /shipments/{id}/reconcile`: `{expected_version,reason}` only after all quantities are physically accounted for. Complete physical receipt alone does not automatically reconcile damage/condition.
7. `POST /requests/{id}/close`: `{expected_version}` only after all approved quantities were dispatched, reservations are zero and all shipments reconciled. APPROVED is never a receipt status.

Approval is the atomic authorization/reservation operation; a separate `/reserve` endpoint would introduce an unnecessary unreserved approval state in this slice. The foundation's proposed `/dispatch-record` maps here to request `/dispatch`, which creates the shipment together with the stock movement. Freeze this mapping with the team; do not implement a second stock writer.

`/cancel` releases reservations only before any dispatch and only for the creator/reviewer with the required role. After partial dispatch there is no silent cancellation/forced closure. A future discrepancy process needs explicit authority, evidence, reason, scope and ledger treatment.

### Freshness and physical counts

The explicitly labelled **demo policy v1** requires a current revision, stock evidence freshness (the later of posting or verified count observation) within 24 hours, and physical-count evidence within 30 days for each allocated batch. These thresholds are demonstration choices, not defence requirements. Received WATER_A2 has no physical-count record; approval needing that batch is blocked until a count is verified. The default 20-bottle flow uses WATER_A1.

`POST /physical-counts`:

```json
{"count_id":"count-demo-1","site_id":"DEMO_A","batch_id":"WATER_A2","counted_quantity":60,"occurred_at":"<current offset-aware timestamp>","source_ref":"operator-count-evidence","expected_version":1}
```

Use the **current** global revision. A count must match physical on-hand and not predate current posted evidence; mismatches return COUNT_DISCREPANCY without overwriting stock. A matching count records the operator's assertion, not proof that a physical count occurred. Resolve differences through supported, authorized receipt/issue/damage evidence before recounting; complex adjustments and formal discrepancy workflow are deferred.

The fixture's October 2026 opening counts intentionally age. For later rehearsals, record fresh matching counts; currently expired stock remains blocked regardless of a fresh count. Never silently refresh evidence timestamps or disable policy to make a demo appear current.

## Track 2 contract

`POST /snapshots` with `{site_ids:["DEMO_A","DEMO_B"]}` (or `{}` for the caller's full scope) freezes:

- scoped batch stock/freshness/version and the input revision;
- ledger sequence cutoff, source configuration versions and policy version;
- actual recorded daily demand, or an explicit NO_DEMAND_HISTORY warning;
- outstanding outbound reservations, marked as already subtracted from allocatable;
- dispatched/not-yet-received inbound, separate from stock, with **unknown arrival time**;
- creation time and canonical content SHA-256.

`GET /snapshots/{id}` returns identical frozen data after subsequent writes. Store snapshot ID and content hash in forecast/planning outputs. Track 2 must attach graph/scenario/constraints/model/run versions to its own results. Do not treat unknown inbound timing as a dated receipt, add reservations twice, or use future stock observations as historic training features.

`GET /demand` is initially empty. `/demand` POST accepts `record_id,site_id,item_id,period,requested,issued,consumed_if_known,returned,unmet,missing_flag,stockout_flag,source_ref`. All observation quantities are nullable; nonmissing rows require requested/issued/returned/unmet, while unknown consumption stays null. Missing rows require null quantities. Periods are dates, quantities canonical integer units; a duplicate site/item/date is rejected instead of silently replaced. Consumption is never inferred from issue events. Track 2 owns generation of additional explicitly synthetic demand, forecasting, projection and evaluation; none is fabricated here.

Track 1 enforces stock, expiry, authority, freshness and workflow invariants. **GIS capacity, receiving windows, storage mass/volume, plan expiry, budget and model constraints are not enforced by Track 1 yet.** A request is an accountable stock-transfer draft, not certification that a Track 2 transport plan is feasible. Track 4 must wire validated plan evidence and server-side constraint rechecks before presenting the combined system as meeting those foundation requirements.

## Track 3 contract

Workbench reads: `/me`, `/catalog`, `/inventory`, `/sources`, `/requests`, `/shipments`. Responses are objects (`inventory.batches`, `requests.requests`, `shipments.shipments`), not bare arrays. Freshness and expiry flags should be shown independently of quantity. The UI must not calculate or replace authoritative balances.

`POST /observations` stores only explicitly synthetic evidence. Fields: schema_version `1.0`, event_id, site_id, device_id, boot_session, sequence, batch_id, observation_type (`barcode_seen`, `temperature`, `humidity`), value, unit, occurred_at, calibration_status and synthetic `true`. Temperature uses CELSIUS and humidity PERCENT_RH. Replay/conflicting IDs are rejected; exact retries are harmless; sequence gaps are flagged. Unknown batches and implausible values fail. No observation changes inventory or releases medical stock.

The identity is the authenticated operator, **not a provisioned hardware identity**. `device_id` is a simulator label; this endpoint does not authenticate a physical sensor/gateway. Track 3/4 own device enrollment, calibration evidence and gateway verification before hardware claims.

For offline observations, retain payload+idempotency key locally and replay the same POST when online, showing per-event conflicts. There is no bulk `/sync` endpoint in this track. There is no offline shared reservation: offline drafts are provisional and need live snapshot/version checks. Later observations do not silently become authorized stock receipts. The queue, cache encryption, login-expiry handling and actual hardware read reliability are owned by the other tracks.

## Track 4 verification and recovery

```bash
cd backend
python -m unittest discover -s tests -v
python -m setu_backend.cli verify
python -m setu_backend.cli backup rehearsal-backup.sqlite3
```

Backup uses SQLite's online backup API including committed WAL state; never copy only the live main DB file. `verify` checks SQLite integrity, foreign keys, inventory projection replay, reservation totals and the local audit hash chain. To restore, stop the API, verify a backup, use that backup under a **new** database path, and restart with `--db recovered.sqlite3`. Tokens in the backup remain usable until rotated/revoked. Protect backups like the original credentials/data. Tests exercise an actual backup/restore and restart persistence.

Events and audit have update/delete denial triggers. The hash-chained local audit is an application control; a database administrator can remove triggers and rewrite the chain. An independently controlled, authenticated audit sink, signed export/outbox, cryptographic key management and administrator-resistant retention remain Track 4 work. Do not label local SQLite audit immutable against administrators or defence-grade security.

The code does not add public AI endpoints, telemetry, map requests, external adapters, blockchain dependencies or background network activity. The HTTP demo has no TLS and bearer tokens have no lifetime: keep it on localhost or inside the explicitly approved synthetic team environment. It is not ready for operational data.

## Repository integration

Track 1 publishes on its own branch. Teammates should pull the completed backend through the PR into a shared integration branch, then create their own work branches. Do not put generated `.env` tokens, SQLite DBs, sensitive inputs or runtime backups into the public repository. Tracks 2–4 should add code in their own directories and depend on the frozen HTTP/OpenAPI contracts. Any API change needs an explicit contract/version review with all owners.

The original supplied import script remains the provenance of the strict CSV schema; it is superseded by this authenticated, transactional implementation. The foundation remains a requirements/reference document, not evidence every module is complete.

Executed acceptance evidence is recorded in [`TEST_RESULTS.md`](TEST_RESULTS.md). The test clock is frozen for the dated fixture; the live application clock is not changed.
