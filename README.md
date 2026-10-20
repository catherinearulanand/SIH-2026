# Setu Supply — SIH26251

Synthetic general-supply decision-support prototype. **Track 1 owns `backend/`.**
The supplied foundation is in [`docs/FOUNDATION.md`](docs/FOUNDATION.md).

## Track 1: run locally

Python 3.10+; no pip installation, external service or internet required.

```bash
cd backend
python -m setu_backend.cli init
python -m setu_backend.cli demo-users
python -m setu_backend.cli serve
```

In another terminal, from `backend/`:

```bash
python demo_client.py
python -m unittest discover -s tests -v
```

API: `http://127.0.0.1:8000`; contract: `http://127.0.0.1:8000/openapi.json`.
Demo tokens are generated into the private, Git-ignored `demo-secrets.env` file.
Use separate role tokens; never place tokens in source code or commit the database.
The included fixture is dated October 2026. Freshness/expiry rules can deliberately block old evidence; see the handoff guide.

## Team integration

Read [`docs/TRACK1_HANDOFF.md`](docs/TRACK1_HANDOFF.md) first.
Machine-readable contract: [`docs/openapi.json`](docs/openapi.json).

| Owner | Area | Integration |
|---|---|---|
| Track 1 | Data, stock, requests and fulfilment | `backend/` and this API |
| Track 2 | Forecasts, projections, GIS and recommendations | Read frozen snapshots; retain snapshot/version lineage |
| Track 3 | Workbench, simulated captures and offline queue | Use HTTP API and role tokens; retain idempotency keys |
| Track 4 | Integration, security review, independent audit and packaging | Run acceptance suite; review deployment and identity |

Avoid editing another track's directory during parallel work. Open pull requests from your own branches.
This is a local SQLite demonstration, not an Army integration or accredited deployment.
