# Retrieval experiments with fixed models

This experiment compares changes around the existing EmbeddingGemma and Whisper
models. Production retrieval, indexed assets, query embeddings and dataset
manifests remain unchanged. Alternative embeddings exist only in local experiment
files. No reference captions, answer annotations or reference transcripts enter
model inputs.

All comparisons use the 210 development queries across seven tasks. Held-out
queries were not evaluated for this experiment. Each task searches its entire
existing candidate collection. The natural speech task is a ceiling check because
its default development score is already perfect.

## Results

Nineteen variants were compared against the current baseline. None establishes
a universal improvement across tasks. The useful leads are local image views,
shorter audio windows, sentence passages and selective extraction-quality weights.

Every task has 30 development queries. All 210 baseline top-ten lists matched
a fresh production run exactly.

| Task | Baseline Recall@5 | Baseline MRR@10 | Relevant candidate coverage at 60 |
| --- | ---: | ---: | ---: |
| Clotho sounds | 0.433 | 0.297 | 0.967 |
| Spoken SQuAD | 0.833 | 0.632 | 1.000 |
| Natural speech | 1.000 | 1.000 | 1.000 |
| COLA images | 0.733 | 0.569 | 0.967 |
| COCO images | 1.000 | 0.906 | 1.000 |
| NanoSciFact text | 0.967 | 0.928 | 0.967 |
| MSR-VTT video | 0.900 | 0.800 | 1.000 |

The strongest-looking changes still have small samples and mixed query-level
effects. The following intervals describe changes in MRR, not absolute scores.

| Variant and task | Recall@5 before / after | MRR before / after | Queries improved / regressed | Paired 95% interval for MRR change |
| --- | ---: | ---: | ---: | ---: |
| `image_crops_max`, COLA images | 0.733 / 0.800 | 0.569 / 0.590 | 6 / 6 | [-0.057, +0.098] |
| `audio_15s_only`, Clotho sounds | 0.433 / 0.500 | 0.297 / 0.317 | 5 / 5 | [-0.051, +0.102] |
| `audio_15s`, Spoken SQuAD | 0.833 / 0.850 | 0.632 / 0.657 | 2 / 2 | [-0.014, +0.078] |
| `transcript_sentences`, Spoken SQuAD | 0.833 / 0.833 | 0.632 / 0.675 | 9 / 3 | [-0.053, +0.146] |
| `quality_confidence`, Clotho sounds | 0.433 / 0.433 | 0.297 / 0.301 | 2 / 0 | [+0.000, +0.013] |
| `quality_ocr`, MSR-VTT video | 0.900 / 0.900 | 0.800 / 0.867 | 3 / 0 | [+0.000, +0.150] |
| `quality_ocr`, COCO images | 1.000 / 1.000 | 0.906 / 0.911 | 1 / 0 | [+0.000, +0.017] |
| `audio_15s`, Natural speech | 1.000 / 1.000 | 1.000 / 0.983 | 0 / 1 | [-0.050, +0.000] |

Sentence passages and either short-audio variant each moved one natural-speech
query from first to second place. They retained perfect Recall@5. The sentence
passage gain on Spoken SQuAD preserved baseline Recall@5. The final alignment
audit tightened passage timestamps to their overlapping original ASR segments,
reused identical cached text embeddings, and reran ranking before recording
these scores.

Other comparisons argue against blanket changes:

- Rank-only fusion lowered MRR from 0.297 to 0.194 on Clotho, 0.906 to 0.612 on COCO, and 0.800 to 0.567 on video. Linear and square-root cosine scaling also failed to improve those tasks overall.
- Summing aligned evidence raised Spoken SQuAD MRR from 0.632 to 0.670, but lowered video MRR to 0.332 and Clotho to 0.138.
- The tested BM25 replacement lowered text MRR from 0.928 to 0.679 and natural-speech MRR from 1.000 to 0.889. This does not rule out better lexical algorithms or calibration; it rejects this replacement at the default fusion weight.
- Reducing dense transcript weight to 0.25 improved five Clotho query positions without regressions, but hurt spoken-content retrieval overall. Its Clotho scores matched the audio-only control.
- Averaging image views lowered COLA MRR from 0.569 to 0.546. Best-view scoring improved six query positions and worsened six, despite its higher Recall@5.
- A replay cap of 20 preserved all reported accuracy metrics, although 41 top-ten lists changed. A cap of 200 provided no accuracy benefit and slightly hurt one Clotho query. Doubling current lexical/exact-match weights did not change scores.

## What to consider next

1. Keep the current fusion formula. Its cosine scaling protects against weak channels winning solely through rank.
2. Consider a selectable best-view image mode and a shorter-audio mode for the next validation round. Both change the input evidence without changing models. Their uncertainty intervals include no improvement, so avoid treating the development gains as settled.
3. Consider sentence passages for spoken-content retrieval, with Recall@5 and MRR both tracked. Do not replace current segmentation globally from this sample.
4. Retain ASR confidence at ingestion and keep extraction-quality weighting configurable. Recovered confidence improved only two Clotho query positions, so the larger benefit is still unproven.
5. Add an OCR-focused validation set before adopting the OCR penalty universally. Visual-only controls achieved the same COCO/video scores as the softer OCR penalty; these tasks show OCR interference, but do not test whether helpful OCR would survive the rule.

The natural-speech pool still needs same-topic distractors before it can guide
content-retrieval tuning. Existing Spoken SQuAD queries provide the informative
speech comparison in this experiment. After choosing a small set of variants,
validate those on held-out queries once rather than selecting among every
variant using held-out scores.

## Runtime and storage

The four augmentation commands took 741.4 seconds in total, about 12.4 minutes:
image crops 168.7 seconds, Whisper confidence 290.6 seconds, sentence passages
52.2 seconds, and short audio windows 229.9 seconds. These wall times include
local checkpoint work. Existing indexed assets were reused; no reindexing or
application database writes were performed.

The fresh production baseline took 7.65 seconds for all 210 development queries
with cached query embeddings. Full variant replay took about nine seconds, but
that in-memory timing cannot predict SQL latency after a production change.

The experiment directory uses about 224 MB. Alternative vector payloads total
5.97 MB as float32, excluding their JSON encoding and metadata. All local datasets
plus PostgreSQL and RustFS volumes total 3.12 GB, below the 5 GB budget. Model
caches, container images and logs are excluded. Data volumes were measured through
read-only mounts while services were stopped.

No production settings or models were changed. All experiment processes exited
and application services remain stopped. The full numeric matrix, paired
intervals and artifact identities are in
[the compact JSON summary](benchmarks/retrieval-experiments-2026-10-11.json).

## Reproduce

Start only PostgreSQL for the capture and production timing commands. Existing
indexed collections and development query-vector caches are required. These
commands describe a first run. Capture refuses to overwrite existing snapshots.
For another run or changed experiment definitions, use a fresh `--output`
directory on every experiment command and place production baseline files there.

```sh
uv run python scripts/experiment_retrieval.py capture
for task_root in search-benchmark spoken-squad-benchmark expanded-benchmark; do
  uv run python scripts/benchmark_search.py --root datasets/$task_root run \
    --split dev \
    --output datasets/retrieval-experiments/$task_root-production-baseline.json
done
docker compose stop postgres

uv run python scripts/experiment_retrieval.py augment --component image
uv run python scripts/experiment_retrieval.py augment --component confidence
uv run python scripts/experiment_retrieval.py augment --component transcript
uv run python scripts/experiment_retrieval.py augment --component audio
uv run python scripts/experiment_retrieval.py evaluate
```

Run inference components sequentially on this Mac. Each augmentation command has
a 1,800-second default budget and checkpoints after each asset. Repeating it
resumes completed assets. Capture validates media hashes, manifest/index mappings,
and query-cache model identity. It records exact production candidate lists at 60
per channel plus exhaustive candidates for a 200-candidate replay. Evaluation
asserts that baseline top-ten results match the production capture exactly.

Results and query-level rankings are in
`datasets/retrieval-experiments/results.json` and `per-query.json`. Snapshots and
alternative embeddings are ignored by Git. The compact result summary beside
this report records their hashes, model identity and index identity.

## Variants

| Variant | Change from the default |
| --- | --- |
| `baseline` | Current strongest-evidence fusion, cosine squared, bounded supporting-evidence bonus, 60 candidates per channel. |
| `rank_only` | Remove cosine scaling from channel contributions. |
| `cosine_linear`, `cosine_sqrt` | Replace the cosine exponent of 2 with 1 or 0.5. |
| `sum_rrf` | Sum all aligned channel contributions, retaining cosine scaling and grouped channel ranks. |
| `candidates_20`, `candidates_200` | Replay with fewer or more candidates per channel. |
| `lexical_weight_2` | Double lexical and exact-substring channel weights. |
| `bm25` | Replace the PostgreSQL lexical candidate list with BM25 over indexed text, OCR and ASR passages. Dense channels remain unchanged. |
| `transcript_weight_025` | Reduce dense transcript weight to 0.25. Lexical matching of transcripts retains its default weight. |
| `quality_structural` | Reduce contributions from transcript segments with repeated trigrams or no usable terms to 0.1. |
| `quality_confidence` | Apply the structural filter and reduce contributions to 0.1 when recovered ASR confidence is poor. Applies to dense and lexical evidence from transcripts. |
| `quality_ocr` | Multiply OCR contributions by squared character-weighted OCR confidence. Retain the current hard OCR filter; missing confidence stays neutral. |
| `image_only`, `audio_only` | Existing single-modality controls. |
| `image_crops_max` | Embed four fixed corner crops, each 70% of image width and height. Retain the best-scoring view among the original image and crops, with one candidate per asset before truncation. COLA only. |
| `image_crops_mean` | Average full-image and four crop similarities, with one candidate per asset. COLA only. |
| `audio_15s` | Add 15-second audio windows with a 12-second stride, keeping original windows. Identical time windows are deduplicated. |
| `audio_15s_only` | Replace original audio windows with those short windows. |
| `transcript_sentences` | Join indexed ASR segments within their original audio window, then embed sentences with the preceding sentence as context. Bound text to 80 words with a 60-word stride. Replace dense transcript representations; retain original lexical candidates. |

ASR confidence is recomputed with the same local Whisper model and each original
audio window. The index did not retain the original values. Thresholds are
`no_speech_prob > 0.6`, `avg_logprob < -1.0`, or `compression_ratio > 2.4`, averaged
by temporal overlap with the indexed segment. Missing signals stay neutral apart
from structural checks. These recovered values are proxies, not a direct audit
of the original decoder output. Video confidence was not recomputed.

Sentence-passage timestamps cover the original ASR segments that overlap their
text context. This experiment measures asset ranking, not timestamp accuracy.
Word-level timing would need separate validation before deployment.

BM25 uses indexed representations as documents, word tokens, a fixed English
stop-word list, `k1=1.2` and `b=0.75`. It admits partial query matches that the
current PostgreSQL query may exclude. It is one baseline implementation, not a
sweep of lexical ranking settings.

## How to read the results

MRR@10 rewards the position of the first relevant result. Recall@5 measures how
many labeled relevant candidates enter the first five results. Report tasks
separately because a gain on spoken content can hide a regression on sounds.

Paired bootstrap intervals resample the same query-level score differences.
COLA queries are resampled by contrast pair because both descriptions concern
the same pair of images. Intervals are exploratory and do not correct for testing
multiple variants. Small development samples do not justify choosing a universal
rule from the highest aggregate score.

Replay timing measures in-memory ranking. It excludes SQL, HTTP and query/model
inference and is not an end-to-end latency comparison. Production baseline runs
measure SQL retrieval and ranking with cached query vectors. Augmentation stats
record per-asset processing time, including model loading in the first processed
asset and excluding checkpoint writes. Component wall times are recorded in the
logs. Vector payload estimates exclude database indexes and metadata overhead.
