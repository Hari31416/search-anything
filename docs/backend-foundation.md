# Backend foundation

Phase 1 provides the local API, persistence, object storage, and durable worker
foundation. Uploads are stored in RustFS and probed for basic metadata. They are
queued for phase 2 processing; they are not extracted, embedded, or searchable
yet.

## Run locally

Start PostgreSQL and RustFS with `docker compose up -d`, copy `.env.example` to
`.env`, then run `uv sync`, `search-anything migrate`, and start the API and the
single worker in separate terminals with `search-anything api` and
`search-anything worker`. The API binds to `127.0.0.1` by default. PostgreSQL
uses host port 55432 so it can coexist with a PostgreSQL server already using
5432. RustFS uses ports 9000 and 9001.

The worker is the intended sole owner of local model instances. The phase 1
scheduler serializes inference calls and puts query work ahead of ingestion,
but API query routing and model loading arrive with later backend phases. Do not
start an API-side model copy when adding those routes; send inference work to
the worker's owner process.

## Current API behavior

- `POST /api/assets` stores an upload, creates a workspace-scoped asset and
  generation, and queues a probe.
- `GET /api/assets` and `GET /api/assets/{id}` report upload and probe state.
- `GET /api/assets/{id}/content` streams the source and supports one HTTP byte
  range, including suffix and open-ended ranges.
- `GET /api/assets/{id}/presigned` returns a short-lived local RustFS URL.
- `DELETE /api/assets/{id}` hides the asset immediately, requests cancellation,
  and queues retryable storage and database cleanup.
- `/health/live` and `/health/ready` report process and PostgreSQL/RustFS state.

The PostgreSQL job queue uses `FOR UPDATE SKIP LOCKED`, expiring leases, a new
random fencing token for every claim, bounded retries, and cancellation checks.
Generation activation verifies the lease and ownership in the same transaction
as the asset update. Retrieval should only expose the active generation.

`SEARCH_INTEGRATION_TESTS=1 uv run pytest -q tests/test_infrastructure_live.py`
runs the live PostgreSQL/RustFS acceptance test. The ordinary test suite skips
that test unless explicitly enabled.
