# Setu Supply — Track 4 integration and security

Track 4 is a separate sidecar that integrates the existing Track 1 API with the planned Track 2
forecasting/GIS outputs. It does not edit, import private internals from, or write directly to Track 1's
database.

## What this first slice implements

- Immutable recommendation records binding a Track 1 snapshot to Track 2 run and plan identifiers.
- Validation of snapshot hash, revision, actor scope and planner role through Track 1's public HTTP API.
- Creation of a Track 1 request from an accepted recommendation without duplicating Track 1 stock logic.
- A bounded offline replay endpoint that permits only provisional observations and recommendation-based drafts.
- A separately stored, hash-chained mirror of Track 1's scoped audit feed.
- Contract and end-to-end tests against an unmodified Track 1 server.

Track 1 remains the sole authority for inventory, approval, reservation, dispatch, receipt and reconciliation.
Track 2 remains responsible for forecasts, projections and GIS feasibility. Track 4 rejects a
`NO_PLAN_ESTABLISHED` result and never turns an observation into stock.

## Run

Start Track 1 on port 8000 as documented in `docs/TRACK1_HANDOFF.md`. Then:

```bash
cd track4
python -m setu_integration.cli init
python -m setu_integration.cli serve --track1-url http://127.0.0.1:8000 --port 8010
```

The sidecar exposes:

- `GET /api/v1/integration/health`
- `POST /api/v1/integration/recommendations`
- `GET /api/v1/integration/recommendations/{id}`
- `POST /api/v1/integration/recommendations/{id}/requests`
- `POST /api/v1/integration/sync`
- `POST /api/v1/integration/audit/pull`
- `GET /api/v1/integration/audit`

It forwards the caller's bearer token to Track 1 for identity and scope resolution. Do not expose either service
outside the synthetic local environment; Track 1 currently has no TLS or token expiry.

## Test

From the repository root:

```bash
python -m unittest discover -s track4/tests -v
```

The tests launch the real, unchanged Track 1 HTTP server on an ephemeral local port.

## Track 2 handoff

Track 2 supplies the selected `ForecastRun`, `ReplenishmentDraft` and `PlanningRun`. Submit this normalized
transfer record to Track 4:

```json
{
  "snapshot_id": "snap_...",
  "snapshot_sha256": "64 lowercase hex characters",
  "input_revision": 1,
  "forecast_run_id": "fc-0123456789ab",
  "plan_id": "plan-0123456789ab",
  "graph_version": "fictional-graph-v1",
  "scenario_id": "closed_edge",
  "constraints_version": "constraints-v1",
  "source_site_id": "DEMO_A",
  "destination_site_id": "DEMO_B",
  "item_id": "WATER_1L",
  "proposed_quantity": 20,
  "solver_status": "OPTIMAL",
  "warnings": ["Synthetic planning evidence"],
  "explanation": ["Fictional edge closure changed the feasible allocation"],
  "evidence_digest": "64 lowercase hex characters"
}
```

`evidence_digest` should be the SHA-256 digest of Track 2's canonical immutable forecast, draft and planning
artifacts. The sidecar stores it for lineage; it cannot independently prove an algorithm was correct.

## Security boundaries

- The sidecar never accepts actor, role or site authority from JSON.
- It resolves identity using Track 1 `/api/v1/me` on every operation.
- It never accepts offline approval, dispatch, receipt or reconciliation.
- It never accesses the Track 1 SQLite file.
- Audit mirroring is independent storage only when deployed under a different administrator/storage boundary.
- Production identity, TLS, managed device keys, MFA and sponsor approval remain deployment gates.
