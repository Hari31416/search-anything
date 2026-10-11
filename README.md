# Search Anything

Search Anything is a multimodal search application for documents, images,
audio, and video. Upload files, organize them into workspaces, and search with
text or reference media. Results include matching passages and timestamps for
audio and video playback.

The application uses EmbeddingGemma and Whisper to index and search content.
It stores metadata and search vectors in PostgreSQL with pgvector, and files
in RustFS.

## Features

- Search documents and media with keyword, semantic, or hybrid search.
- Use text, images, audio, or video as search queries.
- Extract document text, recognize text in images, and transcribe speech.
- Browse results grouped by file, with passage previews and timestamp playback.
- Keep collections and ingestion profiles in separate workspaces.
- Configure chunking, OCR languages, and media sampling with versioned profiles.
- Track indexing progress and retry, cancel, or reprocess uploads.

## Requirements

The reference setup runs on macOS with:

- Python 3.12.11 and `uv`
- Node.js and `pnpm`
- Docker with Docker Compose
- FFmpeg and Tesseract with English language data
- Local EmbeddingGemma and Whisper model files

This setup runs model inference locally without a hosted inference service.
See [Local model setup](docs/local-models.md) for model versions, device
settings, and verification commands. Inference uses Apple Metal when available
and falls back to CPU. Allow enough disk space for model files and uploaded
content.

## Getting started

Run these commands from the repository root:

```sh
make setup
```

This creates `.env` from `.env.example` if needed and installs the backend and
frontend dependencies. Review `.env` and set the model paths to your local
EmbeddingGemma snapshot and Whisper checkpoint. Download the models first if
they are not already cached, following the [model setup notes](docs/local-models.md).

Start the application:

```sh
make start
```

This starts PostgreSQL and RustFS, runs database migrations, and launches the
API, worker, and frontend in the background.

| Service            | Default address       |
| ------------------ | --------------------- |
| Web application    | http://127.0.0.1:5173 |
| API                | http://127.0.0.1:8000 |
| PostgreSQL         | localhost:55432       |
| RustFS S3 endpoint | http://127.0.0.1:9000 |
| RustFS console     | http://127.0.0.1:9001 |

To stop the application and Docker services:

```sh
make stop
```

## Usage

Open the web application, select or create a workspace, and upload files to the
library. Once indexing finishes, search using text or a reference image, audio
clip, or video. Select a result to view the matching passage or play the
matching moment.

Use ingestion profiles to adjust how files are split and sampled. Reprocess a
file to apply a new profile revision. The previous indexed version remains
searchable until the new version finishes indexing.

Workspaces have separate assets, search results, and profile revisions. They
share the database and model worker and do not provide user authentication.

### API examples

Upload a file and check its indexing status:

```sh
curl -F 'file=@notes.pdf' http://127.0.0.1:8000/api/assets
curl http://127.0.0.1:8000/api/assets/ASSET_ID/status
```

Replace `ASSET_ID` with the `asset.id` returned by the upload request.

Search with text:

```sh
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"fire truck","mode":"hybrid","limit":10,"candidate_limit":60}'
```

Search with a reference image or an audio clip:

```sh
curl -F 'file=@reference.png' http://127.0.0.1:8000/api/search/image

curl -F 'file=@recording.wav' -F 'query=blue bicycle' \
  -F 'mode=hybrid' http://127.0.0.1:8000/api/search/media
```

Search modes are `hybrid`, `semantic`, and `keyword`. Filters and channel
weights apply at query time without reindexing. Media query files have a
16 MiB limit, with a maximum duration of 120 seconds for audio and 80 seconds
for video.

Pass `?workspace_id=UUID` to scope asset, profile, and search requests to a
workspace. Requests without it use the configured default workspace.

See the [API reference](docs/frontend-handoff.md#http-reference) for endpoints
and request fields, and [Ingestion and indexing](docs/ingestion.md) for profiles
and asset lifecycle details.

## Development

The backend uses Python and FastAPI. The frontend uses React, TypeScript,
Vite, Tailwind CSS, and shadcn/ui. The API and worker run as separate processes;
the worker handles model inference.

To run services in separate terminals:

```sh
# Start infrastructure and apply migrations once.
make up
make migrate
```

```sh
make api
```

```sh
make worker
```

```sh
make frontend
```

Vite proxies `/api` and `/health` requests to `http://127.0.0.1:8000`. The
backend does not send CORS headers. If you change the API port, update the
proxy target in `frontend/vite.config.ts` too.

### Common commands

| Command               | Description                                      |
| --------------------- | ------------------------------------------------ |
| `make status`         | Show container and local process status          |
| `make health`         | Check API and RustFS readiness                   |
| `make logs-backend`   | Follow API logs                                  |
| `make logs-worker`    | Follow worker logs                               |
| `make logs-frontend`  | Follow frontend logs                             |
| `make format`         | Format Python and frontend code                  |
| `make check`          | Run backend checks and frontend checks and build |
| `make test`           | Run backend unit tests                           |
| `make frontend-check` | Run frontend type checks, lint, tests, and build |
| `make help`           | List available commands                          |

### Testing

Run the standard checks with:

```sh
make check
```

Unit tests do not connect to PostgreSQL or RustFS. The optional infrastructure
acceptance test requires separate test services, a migrated test database, and
cached models:

```sh
SEARCH_TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55433/search_test \
SEARCH_TEST_STORAGE_ENDPOINT=http://localhost:9100 \
SEARCH_TEST_STORAGE_BUCKET=search-anything-test-acceptance \
SEARCH_TEST_STORAGE_ACCESS_KEY=search-test \
SEARCH_TEST_STORAGE_SECRET_KEY=testing-only \
SEARCH_INTEGRATION_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest -q tests/test_infrastructure_live.py -s
```

These example services are separate from the application's Compose services.
The test rejects application service targets and removes its test workspace
and stored objects when it finishes.

## Documentation

- [Backend setup and API behavior](docs/backend-foundation.md)
- [Ingestion, profiles, and indexing](docs/ingestion.md)
- [Local models and hardware verification](docs/local-models.md)
- [Frontend integration and API reference](docs/frontend-handoff.md)
- [Search benchmarks](docs/search-benchmark.md)
- [Retrieval experiments](docs/retrieval-experiments-2026-10-11.md)
- [Media and retrieval fixes](docs/retrieval-fixes-2026-10-11.md)
