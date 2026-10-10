# Local search regression benchmark

This collection measures changes to Search Anything. It uses four retrieval
datasets included in MMEB-V3, with a smaller, frozen candidate collection.
Scores are not comparable to the MMEB leaderboard.

The first local run on 2026-10-10 indexed all 850 assets in 20.4 minutes of
recorded indexing runs, including the pilot and retries. Local files plus
allocated Docker volume growth used 532 MB. A warm run of all 200 queries took
8.21 seconds, with cached query embeddings. Existing model caches are excluded
from storage. An idle interval spent repairing a video timestamp error is
excluded from indexing time. Runtime details and baseline reports are in
`datasets/search-benchmark/README.md`.

| Task   | Source            | Candidates | Queries |
| ------ | ----------------- | ---------: | ------: |
| Text   | NanoSciFact       |        500 |      50 |
| Images | MMEB MSCOCO_t2i   |        200 |      50 |
| Audio  | Clotho evaluation |        100 |      50 |
| Video  | MSR-VTT test_1k   |         50 |      50 |

Each task has 30 development and 20 held-out queries. Relevant candidates do
not cross query splits. The candidate collection is shared between splits,
as is usual for retrieval evaluation. Use development queries while tuning;
use held-out queries to check a chosen change. These small samples are useful
for regressions, but small score differences need inspection of individual
queries.

## Prepare

From the repository root:

```sh
uv run --with pyarrow==19.0.1 python scripts/prepare_search_benchmark.py
uv run python scripts/prepare_search_benchmark.py --verify
```

PyArrow is only needed to prepare the collection. It is not an application
dependency. The script pins Hugging Face revisions. Clotho captions come from
the versioned Zenodo record 4783391. The final manifest records source-file
hashes and every media-file hash. Preparation can resume after a failed
download; once a manifest exists, it refuses to overwrite the frozen dataset.
Use a different `--root` for a new dataset version.

Preparation retains at most 1 GB by default. Downloads use four concurrent
connections. Clotho's uncompressed 2 GB archive is streamed, with only the
selected evaluation clips written to disk. Network transfer can exceed the
retained collection size. No full media archive is saved.

Queries are selected deterministically. Every labeled positive is retained.
Text, image and audio candidates include up to two lexical neighbors per query,
then random distractors. The image task only has captions for part of its
candidate pool; uncaptained candidates enter through random sampling.
Video selection cycles through source categories. All 50 selected videos have
one query each and act as distractors for other video queries.

Indexed filenames are opaque hashes. Image/audio/video captions stay in
evaluation metadata and are never uploaded as content or descriptive
filenames. Text files contain the original source document text.

## Index and measure

Start the normal infrastructure, API and worker, with models cached locally.
For sequential benchmark uploads, start the worker with
`SEARCH_JOB_POLL_SECONDS=0.1 uv run search-anything worker` to avoid its default
one-second idle poll delay between files. Use only one worker on this Mac.
Then run:

```sh
uv run python scripts/benchmark_search.py index --pilot
uv run python scripts/benchmark_search.py index
```

The script creates a dedicated workspace and saves its ID and asset mappings
in `datasets/search-benchmark/index-state.json`. Repeating the command skips
ready assets. It checks file hashes before indexing.
It retries failed assets and reprocesses cancelled assets when resumed.

The pilot indexes eight files: the median and largest input in each task.
It warms the embedding model before timing individual assets, records that
warmup separately, and projects full indexing with 25% headroom. Full indexing
refuses to start if this exceeds the time budget. If it does, reduce the
collection and freeze a new version before proceeding.

The default indexing budget is 2,700 seconds, including earlier pilot/index
runs. The initial 30-minute target was extended after the pilot projected
31 minutes for all 850 assets, or 39 minutes with headroom. A timeout cancels
the current benchmark asset. This is a
measured target, not a guarantee for future embedding models or ingestion
algorithms. The report includes local preparation files, object payload bytes,
and database growth. It also measures allocated disk blocks in the PostgreSQL
and RustFS Docker volumes, including storage-engine overhead. Both accounting
methods are checked against 5 GB during indexing. Existing model files are
excluded. Run from the repository root so Docker Compose uses the right project.

## Run comparisons

```sh
uv run python scripts/benchmark_search.py run \
  --output datasets/search-benchmark/results/baseline-dev.json

uv run python scripts/benchmark_search.py run --split test \
  --output datasets/search-benchmark/results/baseline-test.json

uv run python scripts/benchmark_search.py run --split all \
  --output datasets/search-benchmark/results/baseline-warm-all.json
```

The first semantic/hybrid run encodes queries through the local worker and
saves a cache. Warm runs reuse those vectors. The cache identity includes
model ID, revision, dimensions, context length, model path and manifest hash.
If you modify local model weights without changing those identifiers, delete
`query-vectors.json` before running again.

The runner calls the application's `search_workspace` directly. Reported
retrieval time includes database queries, ranking and grouping, but excludes
HTTP, query inference and frontend rendering. Query encoding time is reported
separately. Each query searches the full candidate collection for its media
type. The runner requires every manifest asset to be ready and rejects extra
ready assets in the benchmark workspace.

Use a JSON configuration file for ranking variants:

```json
{
  "mode": "hybrid",
  "candidate_limit": 100,
  "representation_mode": "separate",
  "weights": {"lexical": 1.5, "image": 1.0}
}
```

```sh
uv run python scripts/benchmark_search.py run --config variant.json \
  --output datasets/search-benchmark/results/variant-dev.json
```

The allowed options are `mode`, `candidate_limit`, `representation_mode`,
`weights`, and `similarity_cutoffs`. To benchmark code changes, run the same
command after editing retrieval code. Preserve the dataset. Extraction,
chunking and embedding changes require reprocessing the collection and
refreshing affected query vectors. Reports record active generation/profile
identity so results from different indexes can be distinguished.

Use `--task audio` to evaluate only the audio queries. For an audio-only
comparison, set `mode` to `semantic`, keep `representation_mode` as `separate`,
and set every channel weight except `audio` to zero. This excludes transcript
embeddings and lexical matches. The saved report includes the exact weights.
With query vectors already cached, only PostgreSQL needs to run.

```sh
uv run python scripts/benchmark_search.py run --task audio --split all \
  --config datasets/search-benchmark/configs/audio-only.json \
  --output datasets/search-benchmark/results/audio-only-all.json
```

The initial comparison used the same 50 audio queries and active index.
Audio-only Recall@5/10 was 48%/64%, versus 42%/58% for the default hybrid
fusion. MRR@10 was 0.319 versus 0.302. These results concern this sound-caption
subset; they do not establish the best configuration for spoken audio.

Reports include Recall@5, Recall@10, MRR@10, binary nDCG@10, mean query latency,
and per-query ranked IDs. Inspect per-task scores and individual regressions.
Media-caption labels are incomplete: an unlabelled image or clip can still
match a caption. This version has no timestamp localization labels. A mixed
workspace evaluation would also need extra relevance judgments and is not
part of the primary score.

## Sources and terms

- [MMEB-V3](https://huggingface.co/datasets/VLM2Vec/MMEB-V3), including image task metadata.
- [NanoSciFact](https://huggingface.co/datasets/zeta-alpha-ai/NanoSciFact).
- [Clotho v2.1 record](https://zenodo.org/records/4783391), evaluation captions;
  evaluation audio is fetched from the MMEB mirror. Individual audio licenses
  are described by the source dataset's metadata.
- [MSR-VTT](https://huggingface.co/datasets/VLM2Vec/MSR-VTT), test_1k annotations
  and original video clips.
- [COCO](https://cocodataset.org/), original validation images via its S3 origin.

Source datasets retain their own terms. Downloaded files, local asset mappings,
query vectors and result reports stay under the gitignored `datasets/` root.
