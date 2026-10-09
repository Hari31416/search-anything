# Backend foundation

Phase 1 provides the local API, persistence, object storage, and durable worker
foundation. Phase 2 has started: supported text and image uploads are extracted,
segmented, OCR'd where appropriate, embedded locally, and published as an active
generation. Audio and video processing is still being implemented.

## Run locally

Start PostgreSQL and RustFS with `docker compose up -d`, copy `.env.example` to
`.env`, then run `uv sync`, `search-anything migrate`, and start the API and the
single worker in separate terminals with `search-anything api` and
`search-anything worker`. The API binds to `127.0.0.1` by default. PostgreSQL
uses host port 55432 so it can coexist with a PostgreSQL server already using
5432. RustFS uses ports 9000 and 9001.

The worker is the sole owner of local model instances. Its scheduler serializes
inference calls and accepts bounded ingestion batches so later query work can
take priority. Do not load a second model in the API when adding query routes;
send inference work through the worker's owner process.

## Current API behavior

- `POST /api/assets` stores an upload, creates a workspace-scoped asset and
  generation, and queues a probe followed by ingestion.
- `GET /api/assets` and `GET /api/assets/{id}` report upload and probe state.
- `GET /api/assets/{id}/content` streams the source and supports one HTTP byte
  range, including suffix and open-ended ranges.
- `GET /api/assets/{id}/presigned` returns a short-lived local RustFS URL.
- `DELETE /api/assets/{id}` hides the asset immediately, requests cancellation,
  and queues retryable storage and database cleanup.
- `/health/live` and `/health/ready` report process and PostgreSQL/RustFS state.

Supported initial text formats and image handling are described in
`docs/ingestion.md`.

The PostgreSQL job queue uses `FOR UPDATE SKIP LOCKED`, expiring leases, a new
random fencing token for every claim, bounded retries, and cancellation checks.
Generation activation verifies the lease and ownership in the same transaction
as the asset update. Retrieval should only expose the active generation.

`SEARCH_INTEGRATION_TESTS=1 uv run pytest -q tests/test_infrastructure_live.py`
runs the live PostgreSQL/RustFS acceptance test. The ordinary test suite skips
that test unless explicitly enabled.
