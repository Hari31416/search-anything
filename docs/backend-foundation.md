# Backend foundation

Phase 1 provides the API, persistence, object storage, and durable worker
foundation. Phase 2 supports structural extraction and indexing for the
document and image formats in `docs/ingestion.md`, plus bounded audio/video
transcription, frame OCR, and timed representations. Profile, status, retry,
cancel, and reprocess APIs are available. Phase 3 now includes hybrid text
search and semantic image search; audio/video query uploads and the combined
representation experiment remain to complete search.

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
- `GET /api/assets/{id}/status` reports current and active generations, job
  attempts/progress/errors, and the immutable options snapshot used to process
  each generation.
- `GET /api/profiles` lists the latest revision of each ingestion profile.
- `PUT /api/profiles/{name}` creates a new immutable profile revision. The
  request body is `{"options": {"strategy": "automatic"}}`; supported tuning
  options are validated by `IngestionOptions`.
- `POST /api/assets/{id}/retry`, `/cancel`, and `/reprocess` manage processing.
  Reprocess accepts `{"profile_name": "automatic"}`. A new generation is
  indexed before it replaces the prior active generation.
- `POST /api/search` performs exact dense, PostgreSQL full-text, and normalized
  identifier retrieval with filters, per-channel weights, and optional dense
  similarity cutoffs. `POST /api/search/image` accepts a local image query.
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
as the asset update. Retrieval filters to the workspace's active generation.
Search fuses aligned time/source spans before ranking assets, preserves distant
matches as separate moments/passages, and includes contributing representation
and channel evidence. Query embeddings run through the worker's private Unix
socket so the API does not load a second local model.

`SEARCH_INTEGRATION_TESTS=1 uv run pytest -q tests/test_infrastructure_live.py`
runs the optional PostgreSQL/RustFS acceptance test only with explicit isolated
`SEARCH_TEST_DATABASE_URL`, `SEARCH_TEST_STORAGE_ENDPOINT`, and
`SEARCH_TEST_STORAGE_BUCKET` targets. See README.md for required credentials
and guards. It cannot fall back to the app services. Workspace API tests use
mocked sessions and storage; the ordinary suite makes no service connections.
