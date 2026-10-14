# Local model compatibility

The reference machine is a MacBook Pro with an M4 Pro, 12 CPU cores, and 24 GB
of memory. Embedding inference defaults to Apple Metal via PyTorch MPS when
available, with CPU as the automatic fallback. Worker Whisper inference defaults
to CPU. Both models retain float32. The embedding
model card prohibits float16. No application data is sent to a hosted inference
service.

The worker uses the embedding API by default at `SEARCH_EMBEDDING_API_URL`,
with a 120-second HTTP timeout controlled by `SEARCH_EMBEDDING_API_TIMEOUT_SECONDS`.
Only the pinned tokenizer is loaded in the worker for text chunk planning.
Whisper still runs inside the worker. `make start-worker` starts the embedding
service first; `make stop-embedding` stops the process managed by this checkout.

`SEARCH_EMBEDDING_DEVICE` defaults to `auto`, and `SEARCH_WHISPER_DEVICE`
defaults to `cpu`. Set either to `auto`, `mps`, `cuda`, or `cpu` to override it.
Explicit GPU selection fails if the requested accelerator is unavailable. Device selection
is logged when each model loads. Restart the worker and embedding service after changing settings.
`SEARCH_EMBEDDING_DEVICE` configures the service launched by Make, or the
original adapter when `SEARCH_EMBEDDING_BACKEND=local` is explicitly selected.
The macOS execution sandbox hides MPS on this machine; a normal host process
can access it. The earlier CPU-only check was run inside that sandbox.

Whisper keeps its sparse alignment-head mask and dynamic time warping on CPU
because MPS does not support sparse tensors or float64. Neural inference runs
on MPS, and word timestamps remain enabled.

## Pinned models and runtime

- Embeddings: `google/embeddinggemma-2`, repository revision
  `914f7f89142e33e77833254d9c9b90c3cef7303b`, 768 dimensions.
- Speech: OpenAI Whisper `tiny`, run locally with `fp16=False`.
- Whisper tiny checkpoint SHA-256:
  `65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9`.
- OCR: Tesseract 5.5.1 with the local `eng` language data.
- Media decode: FFmpeg/ffprobe 8.1.1. Audio embedding input is mono 16 kHz.
- Python: 3.12.11. Exact package versions are in `uv.lock`.

The embedding revision is pinned in the command and smoke script. Download the
model once with Hugging Face tooling if it is not already in the local cache.
Run the smoke script with `HF_HUB_OFFLINE=1` after that download. Pass a local
Whisper checkpoint path to avoid Whisper's download-on-first-use behavior.

## Worker installation

For a worker that uses the embedding API, install the runtime dependencies:

```sh
uv sync --locked --no-dev
uv run --no-dev search-anything worker
```

The default installation excludes Sentence Transformers, Torchvision, and
Librosa. PyTorch remains required for Whisper tiny, and Transformers remains
required for the pinned tokenizer. FFmpeg/ffprobe and Tesseract with the
configured language data must be installed on the worker host.

On Linux and Windows, uv installs PyTorch and optional Torchvision from the
explicit PyTorch CPU index, excluding CUDA and NVIDIA runtime dependencies.
macOS uses the standard PyPI wheels, which also support MPS; Whisper still
defaults to CPU. The embedding service has its own environment and accelerator
configuration. Existing `.env` files override the new default, so set
`SEARCH_WHISPER_DEVICE=cpu` there and restart the worker to apply it.

Set `SEARCH_EMBEDDING_API_URL` to the running service. The worker needs only
the tokenizer files from the pinned snapshot at `SEARCH_EMBEDDING_MODEL_PATH`,
plus the Whisper checkpoint at `SEARCH_WHISPER_CHECKPOINT_PATH`. It does not
need the embedding weights. The tokenizer directory must retain the pinned
revision as its name. Keeping the full cached snapshot also works.

Workers default to `SEARCH_WHISPER_DEVICE=cpu`. Worker CPU and
memory capacity depend on transcription, media decoding, OCR, and input sizes.
The earlier 4.6 GiB measurement below includes local embedding inference and
does not describe the API-backed worker. Worker-only memory and throughput
have not been measured yet.

For the optional local embedding adapter, smoke checks, or experiments that
generate local embeddings, install and run with the extra:

```sh
uv sync --locked --extra local-embeddings
uv run --extra local-embeddings search-anything worker
```

Set `SEARCH_EMBEDDING_BACKEND=local` to select that adapter. The standalone
embedding service installs its own dependencies from `embeddinggemma-api`.

## GPU verification on the reference Mac

An unsandboxed run on 2026-10-09 verified the application's MPS embedding
adapter for text, a downloaded Apollo image, 13 seconds of Apollo audio, and
two video frames. All outputs passed the adapter's 768-dimension, finite-value,
and normalization checks. Calls took 0.19, 0.44, 1.13, and 0.48 seconds
respectively after loading. These are individual checks, not throughput
benchmarks. Whisper tiny transcribed the audio on MPS in 0.92 seconds and
returned 22 word timestamps with CPU alignment. Transcript accuracy was not
evaluated.

## Earlier CPU verification on the reference Mac

The project venv produced finite, L2-normalized 768d embeddings for text,
images, two-second 16 kHz audio, video frames, text plus image, and one combined
text/image/audio/video input. The combined input used matching `<|image|>`,
`<|audio|>`, and `<|video|>` placeholders. Every output had 768 dimensions and
a norm within 0.98–1.02.

In one smoke run after loading the model, embedding took 0.05 seconds for text,
0.72 seconds for an image, 0.93 seconds for two seconds of audio, 0.58 seconds
for two video frames, and 1.88 seconds for combined text/image/audio/video.
The first audio call includes processor initialization. The process peaked at
4.6 GiB resident memory while loading and encoding. These are one-run smoke
timings, not a throughput benchmark.

The fire-truck text query scored 0.768 cosine similarity against its image;
the unrelated tennis-ball query scored 0.573. This checks cross-modal path
compatibility, not search quality. Tesseract read `FIRE TRUCK` from the local
image fixture.

Whisper tiny loaded on CPU and transcribed a local two-second tone fixture in
0.14 seconds, returning an empty transcript. This verifies local loading and
the silent/non-speech path. A spoken fixture could not be generated by the
system speech tool in the sandbox, so speech recognition quality remains
unverified. The video fixture was created and decoded with FFmpeg. Its decoded
frames were passed through the model's video placeholder. The optional
TorchCodec decoder is not installed; ingestion will use FFmpeg directly.

## Run the local checks

```sh
uv sync --locked --extra local-embeddings
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --extra local-embeddings python scripts/local_model_smoke.py \
  --embedding-model-path /path/to/914f7f89142e33e77833254d9c9b90c3cef7303b \
  --whisper-checkpoint /path/to/whisper-tiny.pt
```

The script creates temporary fixtures and requires `ffmpeg` and `tesseract` on
`PATH`. It never uploads fixture data. It fails when an embedding has the
wrong shape, non-finite values, or a norm outside 0.98–1.02.
