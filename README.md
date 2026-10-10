# Search Anything

Search Anything indexes personal documents and media for Multimodal
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

## Workspaces

Use the workspace selector in the header to switch collections. The adjacent
controls create and rename workspaces. Each workspace has its own assets,
search results, and ingestion profile revisions. Selection persists in the
browser, and switching clears the previous workspace's results and dialogs.
Existing assets remain in their original workspace.

The API exposes `GET /api/workspaces`, `POST /api/workspaces` with
`{"name":"Apollo 11"}`, and `PATCH /api/workspaces/{id}` with a new name.
Asset, profile, and search endpoints accept `?workspace_id=UUID`, including
content and preview routes. Omitting it preserves the configured default
workspace for existing API clients. An unknown workspace returns 404; assets
belonging to another workspace also return 404.

Workspaces share PostgreSQL and the local model worker. They separate
collections; they do not provide user authentication or separate physical
databases. No database migration is needed for this change.

## Search

Text search is hybrid by default. Results are grouped by asset, with separate
passages or moments and channel evidence under each asset. Filters, channel
weights, and optional dense similarity cutoffs apply at request time; changing
them does not reindex content.

Ranking uses the strongest weighted channel score, with a supporting bonus
of at most 1%. Dense channel scores combine reciprocal rank with squared,
clamped cosine similarity; similarity is a relevance heuristic, not a
calibrated probability across media types. Adding more channels cannot grow
the bonus beyond the strongest supporting channel's contribution.

OCR fragments without a two-character alphanumeric token are excluded from
content matching. When OCR confidence metadata exists, at least half of its
alphanumeric characters must come from words or lines with confidence 60 or
higher. Short labels such as `A1` and `42` remain searchable, as do filenames
regardless of OCR quality. These filters apply to existing indexed assets.

Timed evidence only combines when every member shares a common interval.
The returned match range is that interval, with each representation retaining
its original timestamps. Overlapping windows cannot chain into a clip-wide
match. Asset rank uses its best moment, rather than summing all moments.

```sh
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"fire truck","mode":"hybrid","limit":10,"candidate_limit":60}'

curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"license plate","mode":"semantic","content_types":["video/mp4"],"weights":{"transcript":1,"video":2},"similarity_cutoffs":{"video":0.25}}'

curl -F 'file=@reference.png' http://127.0.0.1:8000/api/search/image

curl -F 'file=@recording.wav' -F 'query=blue bicycle' \
  -F 'mode=hybrid' http://127.0.0.1:8000/api/search/media
```

Text, image, audio, and video query embeddings go through the worker's private,
local Unix socket and its single model scheduler. `mode` can be `hybrid`,
`semantic`, or `keyword`. Image queries use cross-modal semantic retrieval. On
multipart image/media routes, `content_types`, `asset_ids`, `weights`, and
`similarity_cutoffs` are JSON-encoded form fields. Media query files
can be up to 16 MiB. To guarantee full coverage, audio queries are limited to
120 seconds and video queries to 80 seconds; the response reports the covered
time ranges. Longer inputs receive a clear 422 response. When text accompanies
a media query, its text embedding is pooled equally with the audio/video
embeddings, and its text is used for lexical matching; without supplied text,
the extracted transcript/OCR text is used for lexical matching.

Search uses `representation_mode="separate"` by default, even when combined
vectors exist. `combined` uses only combined vectors and disables lexical
search. `both` searches separate and combined vectors together. Enable combined
indexing in a profile, then reprocess assets to add those vectors:

```sh
curl -X PUT http://127.0.0.1:8000/api/profiles/combined \
  -H 'Content-Type: application/json' \
  -d '{"options":{"strategy":"automatic","text_chunk_tokens":700,"text_overlap_tokens":80,"ocr_languages":"eng","media_preset":"automatic","combined_media_text":true}}'

curl -X POST http://127.0.0.1:8000/api/assets/ASSET_ID/reprocess \
  -H 'Content-Type: application/json' \
  -d '{"profile_name":"combined"}'

uv run python scripts/compare_combined_search.py 'fire truck'
```

The comparison command runs the same hybrid text query in separate, combined,
and both modes. It reports API latency and top results alongside active
representation counts and estimated float32 vector payload bytes. The byte
estimate excludes database row and index overhead; latency includes local
inference and PostgreSQL retrieval.

## Frontend

The frontend is a React, TypeScript, and Vite application located in `frontend/`. It uses shadcn/ui and Radix primitives with Tailwind CSS.

### Development and proxy

The FastAPI backend runs without CORS headers. The frontend uses Vite's development proxy to route all relative requests to `/api` and `/health` to `http://127.0.0.1:8000`.

Start the frontend development server:

```sh
cd frontend
pnpm install
pnpm dev
```

The frontend listens on `http://127.0.0.1:5173`.

### Frontend verification

Run TypeScript type checks, linting, tests, and production build with:

```sh
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

## Management via Makefile

A root `Makefile` provides full-stack lifecycle and development commands:

```sh
make start          # Start infrastructure, run migrations, and launch backend, worker, frontend
make stop           # Stop all background services and Docker infrastructure
make status         # Show status of Docker containers and local processes
make health         # Check RustFS and API readiness endpoints
make check          # Run backend Black/Ruff/Pytest and frontend typecheck/lint/test/build
make format         # Format backend with Black and frontend with Prettier
make logs-backend   # Follow logs/backend.log
make logs-worker    # Follow logs/worker.log
make logs-frontend  # Follow logs/frontend.log
```

## Validation

The fixed local retrieval dataset and repeatable algorithm comparisons are
documented in [docs/search-benchmark.md](docs/search-benchmark.md). The collection
uses text, images, audio, and video from four MMEB-V3 source datasets, with a
separate benchmark workspace and cached query embeddings.
A separate Spoken SQuAD task adds 100 speech clips and 50 questions to measure
retrieval of spoken information.

Run formatting, lint, and unit checks with:

```sh
uv run black --check src tests
uv run ruff check src tests
uv run pytest -q
make frontend-check
```

Workspace API tests use mocked database sessions and storage. Ordinary tests
never connect to PostgreSQL or RustFS.

The optional infrastructure acceptance test requires explicitly configured,
separate test services with an already migrated database and cached models:

```sh
SEARCH_TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55433/search_test \
SEARCH_TEST_STORAGE_ENDPOINT=http://localhost:9100 \
SEARCH_TEST_STORAGE_BUCKET=search-anything-test-acceptance \
SEARCH_TEST_STORAGE_ACCESS_KEY=search-test \
SEARCH_TEST_STORAGE_SECRET_KEY=testing-only \
SEARCH_INTEGRATION_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest -q tests/test_infrastructure_live.py -s
```

These example services are not the application's Compose services. The test
refuses missing test targets, the app database name, database names without
`_test`, the app storage endpoint, and buckets without the
`search-anything-test-` prefix. It removes its own workspace and stored objects
on completion or failure. Enabling `SEARCH_INTEGRATION_TESTS` alone cannot use
the app's services.

The application provides an upload library, segmentation and sampling profile
management, and multimodal hybrid search with grouped passage and timestamp
playback.
