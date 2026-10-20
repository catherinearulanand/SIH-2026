# Track 1 validation evidence

Local validation: **20 October 2026**. Python **3.12.14**, SQLite **3.53.1**.

Result: **49 tests passed**; Python syntax compilation passed; exported OpenAPI equals the runtime-generated contract.

Reproduce from `backend/`:

```bash
python -m unittest discover -s tests -v
python -m compileall -q setu_backend
```

The acceptance suite freezes the application clock at 20 October 2026 for deterministic fixture freshness/expiry checks. The live application uses the actual UTC clock. The CLI bootstrap and HTTP client are exercised against a real local HTTP server in the test suite; HTTP requests are not mocked.

## Tested outcomes

| Area | Evidence |
|---|---|
| Supplied CSV | 9 initial events accepted; same content reimported accepts 0 and reports 9 duplicates |
| Validation | Wrong units, unknown sites, malformed times, invalid quantities, invalid shape, conflicting IDs and oversize CSV rejected |
| Preview | No stock changes; commit bound to actor, source, exact content, age and revision |
| Authorization | Invalid/revoked token, cross-site query/body access, forged actor fields, admin business actions and self-approval denied |
| Atomic reservations | FEFO allocation; insufficient totals roll back; two simultaneous 250-bottle requests cannot both reserve against 325 bottles |
| Idempotency | Concurrent same-key approval returns one result; duplicate receipt does not repeat movement; changed-payload key rejected |
| Partial fulfilment | Partial dispatch, 12+8 receipt via HTTP rehearsal, mixed dispositions, explicit reconciliation and closure |
| Receipt race | Simultaneous receipts using the same object version cannot over-receive |
| Quality/counts | Quarantine release needs QA; expired stock unavailable; verified counts preserve physical totals; stale/missing count blocks allocation |
| Failure rollback | Failure injected during audit insertion rolls back stock movement, revision and idempotency result together |
| Lineage | Immutable snapshot, protected events/decisions/audit; original creator reason and independent reviewer reason retained |
| Forecast boundary | Empty demand history is explicit; issue events are not fabricated consumption; inbound kept separate with unknown timing |
| Capture boundary | Simulated observations do not mutate stock; sequence replay rejected and gaps flagged |
| Persistence/recovery | Restart retains approval; SQLite backup restores balances and revision; ledger/projection verification detects tampering |
| HTTP | Bearer enforcement, CORS, structured errors, correlation IDs, duplicate JSON key rejection and published OpenAPI |

Fixture SHA-256 (`backend/data/synthetic_inventory_events.csv`):

```text
a0cca1a13d010cf2dc33d39726796fa2ebee62b2f55f19fc6a782fe29b2d7909
```

## Limits of this evidence

This is a small local acceptance suite, not a load benchmark, independent penetration test, hardware reliability test or production assurance report. Docker is unavailable in this environment, so the container packaging has not been built/run here. CI is configured for Python 3.10/3.12/3.13; only the local Python 3.12.14 result is asserted until GitHub reports its own runs.

Forecast accuracy, GIS feasibility/capacity, offline UI durability, hardware identity, independent audit retention, encryption/TLS, SSO/MFA and sponsor approval remain other-track or future deployment work. No Army connector, operational data access or defence accreditation is claimed.
