# Local search regression benchmark

Fixed-model retrieval experiments from 2026-10-11 are recorded in
[the experiment report](retrieval-experiments-2026-10-11.md), including individual
query gains and regressions, paired uncertainty, runtime and storage. Production
defaults remain unchanged.

The subsequent confidence-metadata, window-termination, channel-skipping and
stable-ordering fixes are described in
[the follow-up validation](retrieval-fixes-2026-10-11.md).

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

## Spoken content

A separate task adds 100 Spoken SQuAD candidates and 50 question queries
under `datasets/spoken-squad-benchmark`. The original four-task collection,
workspace and baseline reports remain frozen. Across both collections there
are 950 assets and 250 queries.

This task uses `mteb/spoken-squad-t2a` at revision
`b311394fa5ab5e003012304799d0d724d64303b3`. Questions describe information to
find in speech. Candidates are original sentence-level WAV files. Ingestion
receives only opaque filenames and audio; it creates its own Whisper
transcripts. Reference text is not uploaded.

The upstream subset contains synthesized speech about Super Bowl 50. It tests
spoken content retrieval within that topic, not natural meetings or broad
topic coverage. Related sentences provide useful distractors. Add a natural
speech collection such as SLUE-SQA-5 before drawing conclusions about meetings.

Selection shuffles whole source paragraphs deterministically, assigns 60% to
development and the remainder to held-out, then samples questions round-robin
within each split. There are 30 development and 20 held-out questions. Every
positive is retained. Remaining candidate slots use same-paragraph sentences,
then random distractors. Source paragraphs never supply queries to both splits.

```sh
uv run --with pyarrow==19.0.1 python scripts/prepare_spoken_squad_benchmark.py
uv run python scripts/prepare_spoken_squad_benchmark.py --verify

uv run python scripts/benchmark_search.py --root datasets/spoken-squad-benchmark \
  index --pilot
uv run python scripts/benchmark_search.py --root datasets/spoken-squad-benchmark \
  index

uv run python scripts/benchmark_search.py --root datasets/spoken-squad-benchmark \
  run --task speech --output datasets/spoken-squad-benchmark/results/experiment-dev.json
```

Preparation retains at most 500 MB by default, including the source corpus
Parquet file. It downloads approximately 150 MB and extracts about 65 MB of
selected audio. The manifest records source revisions, file hashes and clip
durations. The shared index runner supports this standalone task and creates
a separate workspace named after its manifest.

Compare the same speech queries using audio-only, transcript-only and default
hybrid fusion. Audio-only uses semantic mode with only the `audio` weight
enabled. Transcript-only uses hybrid mode with `transcript`, `lexical` and
`identifier` enabled, and all other weights zero. This includes keyword matching
on generated transcripts. Fusion uses the application's default weights.
Reports under this task's `results/` directory record exact configurations.
Preparation also writes `configs/audio-only.json` and
`configs/transcript-only.json`. Pass either with `--config` to the run command.
Use `--split all` for an initial diagnostic comparison; use the default
development split while tuning algorithms.

The first run indexed this speech task in 3.0 minutes. Source files plus
allocated index storage added 293 MB. Retrieval across all 50 queries took
0.76–1.34 seconds with cached query embeddings. The initial scores were:

| Speech configuration | Recall@5 | Recall@10 | MRR@10 |
| -------------------- | -------: | --------: | -----: |
| Audio only           |      80% |       90% |  0.643 |
| Transcript only      |      77% |       92% |  0.679 |
| Default fusion       |      86% |       88% |  0.688 |

Fusion ranked relevant clips better near the top, but had lower Recall@10.
This result differs from the environmental-sound task and supports keeping
the two tasks separate when choosing ranking weights.

## Hard images and natural speech

`datasets/expanded-benchmark` adds two tasks to the earlier collections:

| Task | Source | Candidates | Queries |
| ---- | ------ | ---------: | ------: |
| `image_hard` | COLA multi-object matching | 100 images | 50 |
| `natural_speech` | SLUE-SQA-5 verified test | 100 passages | 50 |

Both have 30 development and 20 held-out queries. Across all three local
collections there are 1,150 assets and 350 queries. Each collection uses a
separate workspace and keeps its own frozen manifest and results.

COLA pairs images whose objects and attributes appear in different
configurations. Selection keeps 50 disjoint image pairs. Both captions from
25 pairs become queries; the other 25 pairs provide additional distractors.
Each queried pair supplies a labeled positive and a known hard negative.
Pairs never cross query splits. Primary retrieval still searches the full
100-image pool. Labels are complete for the paired contrast, not necessarily
every image in the pool. These are local regression metrics, not COLA's
official two-image matching metric. This task tests compositional matching;
it does not directly measure reading text in images.

SLUE-SQA-5 uses natural human readings of Wikipedia. Selection uses the three
manually verified test shards, then chooses one question per source article.
The 50 questions are balanced across Natural Questions, SQuAD, CuratedTREC,
TriviaQA and WebQuestions, with six development and four held-out questions
per source in manifest version 2. Positive passages contain every labeled occurrence
of the answer and are at most 30 seconds long. Questions whose answer
occurrences cannot all fit are excluded. The other 50 candidates are passages
from distinct documents, preferring articles without selected questions.
Selected questions use 50 source articles and 50 speakers; all 100 speech
candidates cover 98 articles and 98 speakers. Source articles supplying queries
never cross splits, but speakers may overlap. This is read speech, not noisy
meetings or conversation.

The preparation retains original source offsets and answer times relative to
each cropped file. Evaluation currently scores retrieval, not timestamp
localization. Answer-based cropping deliberately tests bounded passage retrieval,
not finding an answer in an entire recording. Reference transcripts, captions
and answer strings stay in source/evaluation metadata. Ingestion only receives
opaque filenames and original media, with speech converted to 16-bit PCM WAV.

```sh
uv run --with pyarrow==19.0.1 python scripts/prepare_expanded_benchmark.py
uv run python scripts/prepare_expanded_benchmark.py --verify

uv run python scripts/benchmark_search.py --root datasets/expanded-benchmark index --pilot
uv run python scripts/benchmark_search.py --root datasets/expanded-benchmark index

uv run python scripts/benchmark_search.py --root datasets/expanded-benchmark run \
  --task image_hard --output datasets/expanded-benchmark/results/images-dev.json
uv run python scripts/benchmark_search.py --root datasets/expanded-benchmark run \
  --task natural_speech --output datasets/expanded-benchmark/results/speech-dev.json
```

Preparation downloads approximately 867 MB of source Parquet files plus only
the selected images. Extracted media totals 110 MB, including 49.9 minutes of
speech. The default retained preparation cap is 1.4 GB. All source revisions,
file hashes, crop offsets and durations are recorded in the manifest.

Preparation writes `configs/image-only.json`, `configs/audio-only.json` and
`configs/transcript-only.json`. Pass a preset with `--config` to compare it
with default fusion on the corresponding task. Use development queries while
tuning. Preserve held-out queries for checking a selected change.

The first run indexed the expansion in 5.8 minutes, including the pilot and
model warmup. New preparation files plus allocated index growth used 1.10 GB.
All local dataset files and application data volumes totaled 2.92 GB, excluding
model caches and container images. Only development queries were evaluated:

| Development task / configuration | Recall@5 | Recall@10 | MRR@10 |
| -------------------------------- | -------: | --------: | -----: |
| COLA / default fusion            |    73.3% |     86.7% |  0.569 |
| COLA / image only                |    73.3% |     86.7% |  0.569 |
| SLUE / default fusion            |     100% |      100% |  1.000 |
| SLUE / audio only                |     100% |      100% |  0.967 |
| SLUE / transcript only           |     100% |      100% |  1.000 |

COLA exposes more ranking errors than the original COCO subset. The natural
speech task covers more topics and speakers, but remains clean read speech
with answer-centered crops and mostly unrelated candidate articles. Same-topic
distractors, noisy conversations and dedicated OCR retrieval are still gaps.
Detailed reports are in `datasets/expanded-benchmark/README.md`.
An initial source-separated split was superseded by version 2, which balances
question sources within both splits. Its manifest and initial baseline are
archived locally under `datasets/expanded-benchmark-v1`. Media files are hard
linked between versions, and identical asset hashes allowed reuse of the active
index. No ranking changes were made during the correction. Current published
results use version 2 development queries; no current held-out baseline was run.

## Sources and terms

- [MMEB-V3](https://huggingface.co/datasets/VLM2Vec/MMEB-V3), including image task metadata.
- [NanoSciFact](https://huggingface.co/datasets/zeta-alpha-ai/NanoSciFact).
- [Clotho v2.1 record](https://zenodo.org/records/4783391), evaluation captions;
  evaluation audio is fetched from the MMEB mirror. Individual audio licenses
  are described by the source dataset's metadata.
- [MSR-VTT](https://huggingface.co/datasets/VLM2Vec/MSR-VTT), test_1k annotations
  and original video clips.
- [COCO](https://cocodataset.org/), original validation images via its S3 origin.
- [MTEB Spoken SQuAD retrieval](https://huggingface.co/datasets/mteb/spoken-squad-t2a)
  and [original Spoken SQuAD](https://github.com/Chia-Hsuan-Lee/Spoken-SQuAD).
  The MTEB mirror declares Apache-2.0; the speech derives from SQuAD text.
- [COLA](https://github.com/ArijitRay1993/COLA) via
  [the self-contained author mirror](https://huggingface.co/datasets/array/cola).
  Annotations are MIT; the selected Visual Genome images retain their source terms.
- [SLUE-SQA-5](https://huggingface.co/datasets/asapp/slue-phase-2).
  Spoken Wikipedia audio is CC BY-SA 4.0. Question terms depend on the source:
  TriviaQA is Apache-2.0 and the other question sources are CC BY-SA 4.0.

Source datasets retain their own terms. Downloaded files, local asset mappings,
query vectors and result reports stay under the gitignored `datasets/` root.
