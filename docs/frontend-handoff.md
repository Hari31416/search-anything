# Frontend agent handoff

## Task and scope

Build phase 4 of Search Anything, a multimodal search application for documents,
images, audio, and video. Backend phases 0–3 are complete. The previous agent
stopped before frontend implementation at the user's request. This document
hands off that work; start implementation when the user assigns it to you.

You own the exact UI and UX. Choose the navigation, layout, visual design,
interaction patterns, and components. The capabilities below describe what
users need to accomplish, not a prescribed screen design. Add controls only
when they change a real behavior or help users make a decision.

Use React, TypeScript, Vite, pnpm, and shadcn. Create a separate `frontend/`
application. Follow repository instructions. The user requested Luna with high
reasoning for implementation and regular commits. Use conventional commits,
such as `feat(frontend): add search workflow`, with a subject of at most 50
characters and an optional bullet-list body.

Keep this phase focused on the frontend and necessary integration fixes.
Relevance datasets, reranking, better segmentation algorithms, public hosting,
and multi-user authentication belong to later work.

## Read before coding

- `README.md` for service startup and API examples.
- `PLAN.md`, especially the frontend behavior and phase 4 acceptance criteria.
- `docs/backend-foundation.md` for storage and lifecycle details.
- `docs/ingestion.md` for supported formats, presets, and effective limits.
- `src/search_anything/api.py` for HTTP request and response contracts.
- `src/search_anything/ingestion.py`, `IngestionOptions`, for profile validation.
- `src/search_anything/retrieval.py`, `group_assets`, for search result shape.

The code is authoritative if a summary here differs. FastAPI exposes `/docs`
and `/openapi.json` while running. Search responses use dynamic dictionaries,
so inspect `group_assets` as well as OpenAPI when defining TypeScript types.

## Local integration

Follow the README to start Compose, apply migrations, and run the API and
worker in separate terminals. The API listens at `http://127.0.0.1:8000`.
PostgreSQL uses host port 55432; RustFS uses 9000 and 9001.

The API has no CORS middleware. Configure a Vite development proxy for `/api`
and `/health` and make browser requests with relative URLs. Keep any frontend
preview or serving arrangement consistent with that routing.

EmbeddingGemma, Whisper, and Tesseract run locally. The worker is the sole model
owner; the browser communicates with the HTTP API. Keep object-storage secrets
and model paths in backend configuration. CPU inference is the verified runtime,
so search and processing can take time. `/health/ready` checks database and
storage, not model-worker availability; handle search failures independently.

## Capabilities to deliver

- Upload supported files, inspect the library, and follow processing progress.
- Retry failed work, cancel pending processing, delete assets, and reprocess
  with a saved ingestion profile.
- Configure and save segmentation profiles, using automatic defaults and
  content-specific presets. Distinguish saved settings from settings already
  applied to an asset.
- Search with text, an uploaded image, or uploaded audio/video. Media queries
  can include optional text. A query attachment is separate from a library
  upload and should not silently become a stored library asset.
- Filter results by content type or asset and change retrieval weights without
  reprocessing. Make advanced retrieval options available where useful.
- Present results grouped by asset, with separate matching passages or moments.
  Let users inspect transcript/OCR evidence and open the matching source
  location or play from the matching timestamp.
- Make empty, loading, failed, cancelled, and partially successful states clear.
  Preserve entered queries and settings when a request fails.

## HTTP reference

| Operation | Contract |
| --- | --- |
| Upload | `POST /api/assets`, multipart `file`; returns 201 with `asset`, `generation_id`, `job_id` |
| List assets | `GET /api/assets?limit=50&offset=0`; returns an array, limit at most 200 |
| Asset metadata | `GET /api/assets/{id}` |
| Processing status | `GET /api/assets/{id}/status` |
| Retry | `POST /api/assets/{id}/retry` |
| Cancel | `POST /api/assets/{id}/cancel`, JSON `{}` or `{"generation_id":"..."}` |
| Reprocess | `POST /api/assets/{id}/reprocess`, JSON `{"profile_name":"automatic"}` |
| Delete | `DELETE /api/assets/{id}`; returns 202, cleanup is asynchronous |
| List profiles | `GET /api/profiles`; returns the latest revision of each name |
| Save profile | `PUT /api/profiles/{name}`, JSON `{"options":{...}}`; creates an immutable revision |
| Original source | `GET /api/assets/{id}/content`; supports byte ranges for playback |
| Temporary source URL | `GET /api/assets/{id}/presigned`; returns `url` and `expires_in_seconds` |
| Text search | `POST /api/search`, JSON search options; returns 200 with results or 202 with job ID |
| Image query | `POST /api/search/image`, multipart `file` plus search options; returns 200 or 202 |
| Audio/video query | `POST /api/search/media`, multipart `file` plus search options; returns 200 or 202 |
| Search status/result | `GET /api/search/jobs/{id}` with the submission workspace scope |

Search submissions wait up to `SEARCH_QUERY_WAIT_SECONDS`, default 5 seconds,
configurable from 0 to 5. Completed requests return 200 with the search response;
failures return 422 or 503. Timed-out waits return 202 with
`{"id":"UUID","status":"queued"}` and the job continues. Poll the search
status endpoint for `queued`, `running`, or `retry`; stop at `succeeded` or
`failed`. Successful jobs contain the existing search response in `result`.
Failed jobs contain `error: {"code":"...","message":"..."}`. Unknown or
other-workspace jobs return 404. Terminal jobs expire after 24 hours by default.
The API client handles direct results and fallback polling internally, so
search components still receive `Promise<SearchResponse>`. Aborting that promise stops polling;
it does not cancel durable execution. No worker URL or socket is exposed.

Uploads use the latest `automatic` profile. There is no upload-time profile
selector parameter. To use another profile, save it and explicitly reprocess
the asset. Saving a profile alone does not change existing indexed content.

Poll processing status while work is pending, with bounded retries and backoff
on failures. There is no SSE or WebSocket status endpoint. Stop polling when
appropriate and release timers on unmount. A `ready` asset can still have a
new generation processing. Use `current_generation_id`, `active_generation_id`,
and generation/job states together. The prior active generation stays
searchable until replacement succeeds. Running cancellations can take time.

Status includes `generations[].profile_snapshot`, `extractor_versions`, and
`jobs`. Jobs expose stage, status, progress from 0 to 1, attempts, cancellation
state, and structured errors. These are stage/job values, not an overall ETA.
Expose context adjustments and combined-representation failures from returned
metadata where available. Silence or absent streams can legitimately produce
no transcript or audio representation.

## Search options and results

Start with the backend defaults:

```json
{
  "query": "blue bicycle",
  "mode": "hybrid",
  "representation_mode": "separate",
  "limit": 10,
  "candidate_limit": 60
}
```

`mode` accepts `hybrid`, `semantic`, or `keyword`. `limit` is 1–50 and
`candidate_limit` is 10–200, at least `limit`. `content_types` holds exact MIME
types and `asset_ids` holds UUIDs. Map any broader file-type choices to the
actual MIME values used by assets.

`weights` accepts `text`, `transcript`, `ocr`, `image`, `audio`, `video`,
`combined`, `lexical`, `identifier`, and `filename`. Defaults are 1. Values
are finite numbers from 0 to 10; zero disables a channel. `similarity_cutoffs`
accepts only the seven dense channels, with values from -1 to 1. Cutoffs are
optional and have no calibrated universal default.

`representation_mode` accepts `separate`, `combined`, or `both`. Separate is
the default. Combined-only disables lexical retrieval and requires assets
indexed with combined representations. It can therefore return no results
for otherwise searchable assets. Combined indexing is an opt-in profile
setting, independent of the retrieval selection.

For multipart queries, JSON-encode `content_types`, `asset_ids`, `weights`,
and `similarity_cutoffs` as form-field strings. Send other fields as strings
and let the browser set the multipart boundary. With no explicit `mode`, media
routes use semantic retrieval without accompanying text and hybrid with text.

Image queries are limited to 8 MiB. Audio/video queries are limited to 16 MiB,
with at most 120 seconds of audio or 80 seconds of video. The media response
reports transcript/OCR text, duration, window counts, pooled inputs, and
`covered_ranges_seconds`. Longer inputs fail with 422 rather than silently
searching only a prefix. Client checks improve feedback; server validation
remains authoritative. These query limits are distinct from library ingestion.

Every response has a `results` array. Each result contains `asset_id`,
`filename`, `content_type`, `generation_id`, `score`, and `matches`. Each match
has its own score, channel contributions, optional time/source bounds,
`representations`, and `channel_evidence`. Representations contain kind, text,
location metadata, optional offsets/timestamps, and optional dense similarity.

Preserve the server's grouping and ranking. A result can contain distant
matches in one asset; retain those as distinct navigable passages or moments.
The fused score is a ranking score, not a probability or percentage confidence.
Show readable evidence by default and make raw ranking details optional.

## Profiles and source navigation

Available media presets are `automatic`, `speech_lectures`, `general_video`,
`music_sounds`, and `camera_footage`. The only implemented text strategy is
`automatic`, which dispatches by content structure. Profile options also
include text token target/overlap, AV window/overlap, video sampling FPS, OCR
languages, transcription language, and `combined_media_text`. Read the
Pydantic fields and validators for bounds and cross-field constraints.

The backend checks actual model context budgets. It can lower effective frame
sampling and splits audio into windows of at most 30 seconds because of the
installed processor limit. Requested settings and effective processing can
differ. Whisper model selection is backend configuration, not a per-profile
setting. Segment preview and an endpoint listing derived artifacts are not
implemented; build the initial experience around available status and results.

Use the original-content endpoint for image, PDF, audio, and video previews
where the browser supports their format. Seek AV after metadata loads. For
unsupported browser codecs, offer the original download and explain the
limitation. There is no browser-compatible transcoding endpoint.

Locations vary by representation and can include page, heading, OCR geometry,
source offsets, and timestamps. Use available metadata without inventing
missing coordinates. Extracted-text offsets are not byte offsets into a PDF
or DOCX. There is no general extracted-document viewer endpoint. Show returned
passage text and a source download when exact source navigation is unavailable.
Generated thumbnails are not currently exposed by a dedicated API.

Render filenames, extracted text, transcripts, and OCR as untrusted text.
HTML/SVG/XML originals are intentionally served as inert attachments. Preserve
that behavior. Presigned URLs expire; refresh them when needed, or use the
relative content endpoint for playback.

## Delivery and verification

Implement in coherent milestones and commit each completed milestone. Choose
the component architecture and UX yourself. Keep API calls and response types
centralized. Handle FastAPI errors whose `detail` is either text or validation
items, including 409 lifecycle conflicts, 413 size errors, 422 validation
errors, and worker/service failures. Prevent stale search responses from
replacing newer results.

Before calling this phase complete, run the frontend build, type checks, and
appropriate behavioral tests. Verify a real upload-to-search workflow against
the local backend, including text, image, and AV query routes. Verify grouped
matches, filtering, saving/applying a profile, retry/cancel/delete behavior,
timestamp playback, and useful feedback for query limits and worker downtime.
Use deterministic fixtures for failure paths that are difficult to trigger
manually. Check keyboard access and a narrow viewport.

Document frontend startup and proxy configuration in the README. Report what
was tested, any remaining browser/preview limits, and the final commits. Keep
the repository clean. Finish phase 4; leave the deferred phases for a separate
assignment.
