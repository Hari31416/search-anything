# Ingestion and indexing

The durable worker owns extraction and the pinned local EmbeddingGemma model.
Each generation snapshots its chunk target, overlap, and OCR language options.
Text input is checked with the model's actual processor with truncation disabled;
an input over 8,192 processed tokens is split at structural or sentence
boundaries, or fails with an explicit context error if even its required heading
context cannot fit.

The first supported formats are UTF-8 `.txt` and `.md`, `.html`/`.htm`, `.pdf`,
`.docx`, `.py`, and PNG/JPEG/WebP/TIFF images. PDF pages retain page numbers;
scanned pages fall back to local Tesseract OCR. DOCX paragraphs and tables keep
document order. Python source is segmented at top-level functions and classes
using the AST parser, with a line-preserving fallback for invalid source.
Markdown headings and fenced code are retained as context; tables stay intact
when they fit and repeat column headers when split into multiple segments.
Oversized single table rows and code lines use token-safe bounded splitting.

Images create a visual representation and a separate OCR text representation.
OCR text retains per-line bounding boxes and confidence values. Document text
segments retain page, heading, table, or source-offset metadata. Each textual
representation and image representation gets its own finite, normalized 768d
vector. A weighted GIN full-text index covers representation bodies and
headings, with a separate filename GIN index and escaped normalized substring
matching for identifiers. `/api/search` combines text, transcript, OCR, image,
audio, and video dense channels with lexical and identifier channels.
`/api/search/image` queues visual queries for the worker. All search endpoints
return 202 with a durable job ID; `/api/search/jobs/{id}` returns status and
results. API and worker share Postgres and object storage, with no shared socket.

Audio and video files are probed with local FFprobe. The worker splits media
into overlapping windows and uses FFmpeg to decode mono 16 kHz audio and
sampled video frames. Whisper tiny runs locally on each audio window. Transcript
segments keep their start/end times and detected language. Audio windows and
video windows get separate EmbeddingGemma representations. Video frames also
pass through local Tesseract; repeated OCR text in adjacent frames is merged
with its observed time span.

The default media presets are `speech_lectures` (30-second windows, 5-second
overlap, 0.5 sampled frames/second), `general_video` (20/5 seconds, 1 frame per
second), `music_sounds` (15/3 seconds, 0.5 frames/second), and `camera_footage`
(10/3 seconds, 1 frame/second). Automatic selection uses `speech_lectures` for
audio and `general_video` for video. A generation can override window length,
overlap, frame sampling rate, and transcription language. Validation resolves
partial overrides against the selected preset and rejects overlap that would
leave no forward progress. When a requested frame rate would exceed 32 decoded
frames in one window, the worker lowers the effective rate and stores both
requested and effective rates in generation metadata. A video shorter than one
sampling interval still gets one frame. The installed audio processor limits
its audio sequence to 750 feature frames, or about 30 seconds. `embed_audio`
rejects longer WAV inputs, and the worker splits longer media into overlapping
30-second audio windows. The live test puts a second spoken phrase after 30
seconds and verifies that local Whisper indexes it with a source time beyond
30 seconds.

Frame images and temporary audio windows are deleted after indexing. The
original asset remains in RustFS and timed segments point into it. Video window
metadata stores the actual FFmpeg timestamps used for its visual embedding;
OCR segments store their own time ranges and per-line geometry. Audio assets
with attached cover art do not get a video representation. Silent audio still
gets an audio embedding and simply has no transcript segments. Video with no
audio stream gets video/OCR representations and records the skipped audio
stream state.

The HTTP upload path defaults to the latest immutable `automatic` profile
revision. Profile editing, retry/cancel/reprocess endpoints, and preservation
of the previous active generation are implemented. Uploads whose container
has no decodable audio or video stream fail explicitly rather than becoming
searchable.
