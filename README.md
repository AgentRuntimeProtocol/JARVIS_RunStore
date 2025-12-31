# JARVIS Run Store

Internal JARVIS service that persists `Run` and `NodeRun` state for the Coordinator.
This is a JARVIS-only contract (not part of the ARP Standard).

## Requirements

- Python >= 3.11

## Install

```bash
python3 -m pip install -e .
```

## Run

```bash
python3 -m pip install -e .
arp-jarvis-runstore
```

> [!TIP]
> Use `bash src/scripts/dev_server.sh --host ... --port ... --reload` for dev convenience.

## Configuration

Environment variables:
- `JARVIS_RUN_STORE_DB_URL` (default `sqlite:///./runs/jarvis_run_store.sqlite`)
- `JARVIS_RUN_STORE_MAX_SIZE_MB` (optional guardrail)
- `ARP_AUTH_*` (JWT auth settings, shared across JARVIS services)

Auth is enabled by default (JWT). To disable for local dev, set `ARP_AUTH_PROFILE=dev-insecure`
or `ARP_AUTH_MODE=disabled`. Health/version endpoints are always exempt.
If no `ARP_AUTH_*` env vars are set, the service defaults to the dev Keycloak issuer.

## API (v0.3.3)

Health/version:
- `GET /v1/health`
- `GET /v1/version`

Runs:
- `POST /v1/runs` -> `{ run: Run }`
- `GET /v1/runs/{run_id}`
- `PUT /v1/runs/{run_id}` -> `{ run: Run }`

NodeRuns:
- `POST /v1/node-runs` -> `{ node_run: NodeRun }`
- `GET /v1/node-runs/{node_run_id}`
- `PUT /v1/node-runs/{node_run_id}` -> `{ node_run: NodeRun }`
- `GET /v1/runs/{run_id}/node-runs?limit=100&page_token=...`

Idempotency:
- `POST` endpoints accept `idempotency_key` and will return the existing record if the key matches.

## Notes

- The store is owned by the Coordinator; no cross-component DB access.
- Uses SQLite by default for v0.3.3.
