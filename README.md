# Search Anything

Search Anything indexes personal documents and media for local multimodal
search. The backend runs PostgreSQL with pgvector and RustFS, and keeps the
EmbeddingGemma and Whisper models on this Mac. The API and one worker run as
separate local processes; the worker owns model inference.

## Start the backend

Requirements: macOS with Python 3.12.11, `uv`, Docker Compose, FFmpeg,
Tesseract, and enough disk space for the local model files.

```sh
docker compose up -d
cp .env.example .env
uv sync
uv run search-anything migrate
```

In separate terminals, run the API and worker:

```sh
uv run search-anything api
uv run search-anything worker
```

The API listens on `http://127.0.0.1:8000`. PostgreSQL is mapped to port
55432; RustFS S3 and console endpoints use ports 9000 and 9001. Model paths and
local service URLs are configured in `.env`. No hosted inference endpoint is
used. The first local model setup downloads the pinned model snapshot; see
[`docs/local-models.md`](docs/local-models.md) for the measured model checks.

## Upload and inspect an asset

```sh
curl -F 'file=@notes.pdf' http://127.0.0.1:8000/api/assets
curl http://127.0.0.1:8000/api/assets/ASSET_ID/status
```

The upload response returns both `asset.id` and `generation_id`. Status shows
the current and active generation, processing jobs, progress, retry attempts,
and errors. A newly uploaded or reprocessed generation does not replace the
active generation until indexing succeeds.

Profiles are immutable revisions. Save a revision, then reprocess an asset
with the latest revision of that profile:

```sh
curl -X PUT http://127.0.0.1:8000/api/profiles/automatic \
  -H 'Content-Type: application/json' \
  -d '{"options":{"strategy":"automatic","text_chunk_tokens":700,"text_overlap_tokens":80,"ocr_languages":"eng","media_preset":"automatic"}}'

curl -X POST http://127.0.0.1:8000/api/assets/ASSET_ID/reprocess \
  -H 'Content-Type: application/json' \
  -d '{"profile_name":"automatic"}'
```

Other lifecycle endpoints are `POST /api/assets/{id}/retry`,
`POST /api/assets/{id}/cancel` (optionally with `{"generation_id":"..."}`),
and `DELETE /api/assets/{id}`. Upload, source byte ranges, presigned local
previews, profiles, and extraction details are documented in
[`docs/backend-foundation.md`](docs/backend-foundation.md) and
[`docs/ingestion.md`](docs/ingestion.md).

## Validation

Run formatting, lint, and unit checks with:

```sh
uv run black --check src tests
uv run ruff check src tests
uv run pytest -q
```

The live acceptance test requires the local Compose services and downloaded
local models:

```sh
SEARCH_INTEGRATION_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest -q tests/test_infrastructure_live.py -s
```

The current backend indexes and processes uploaded content. Search endpoints
are not available until the next backend milestone; there is no frontend yet.
