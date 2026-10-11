---
language:
- en
license: other
license_name: upstream-dataset-specific-terms
license_link: https://huggingface.co/datasets/hari31416/search-anything-benchmark#source-references-and-terms
task_categories:
- text-retrieval
tags:
- multimodal
- retrieval
- benchmark
- image
- audio
- video
size_categories:
- 1K<n<10K
configs:
- config_name: corpus
  data_files:
  - split: corpus
    path: data/corpus.jsonl
- config_name: queries
  data_files:
  - split: dev
    path: data/queries-dev.jsonl
  - split: test
    path: data/queries-test.jsonl
---

# Search Anything benchmark

Project repository: [Hari31416/search-anything](https://github.com/Hari31416/search-anything). The repository contains the search pipeline, dataset preparation scripts, and evaluation runner.

A compact, frozen multimodal retrieval benchmark with **1,150 candidate assets and 350 text queries**, sampled from seven existing datasets.

We created these subsets so we could **index and evaluate our search pipeline quickly with a low storage footprint** on a local machine. They support repeated regression checks and ranking experiments without downloading or indexing the full source datasets. They are evaluation subsets, not training data or replacements for the full benchmarks.

## Contents

| Task             | Original dataset         |              Candidate assets | Development queries | Held-out queries |
| ---------------- | ------------------------ | ----------------------------: | ------------------: | ---------------: |
| `text`           | NanoSciFact              |                 500 documents |                  30 |               20 |
| `image`          | MMEB MSCOCO_t2i          |                    200 images |                  30 |               20 |
| `audio`          | Clotho evaluation        | 100 environmental-sound clips |                  30 |               20 |
| `video`          | MSR-VTT test_1k          |                     50 videos |                  30 |               20 |
| `speech`         | MTEB Spoken SQuAD        |  100 synthesized speech clips |                  30 |               20 |
| `image_hard`     | COLA                     |                    100 images |                  30 |               20 |
| `natural_speech` | SLUE-SQA-5 verified test |      100 read-speech passages |                  30 |               20 |
| Total            |                          |                         1,150 |                 210 |              140 |

The original collections remain under `search-benchmark/`, `spoken-squad-benchmark/`, and `expanded-benchmark/`. Each contains its frozen manifest and media. The expansion uses the corrected version 2 query split. Its archived version 1 is excluded.

The package includes selected media, query text, relevance judgments, original source IDs, source revisions, crop metadata where available, and SHA-256 checksums. It excludes full source Parquet files, downloaded archives, query embeddings, generated transcripts, indexing state, credentials, and machine-specific results.

## Runtime and storage

Initial indexing measurements on a local M4 Pro on October 10, 2026 were approximately 20.4 minutes for the original 850 assets, 3.0 minutes for Spoken SQuAD, and 5.8 minutes for the expansion. These include pilots and retries or model warmup as recorded by each collection. They depend on the pipeline and hardware. Existing model caches and container images are excluded.

`package-summary.json` records the exact media payload size. The uploaded package is smaller than the original preparation directories because it omits their cached source files. Speech duration is 22.4 minutes for Spoken SQuAD and 49.9 minutes for SLUE.

## Usage

```python
from datasets import load_dataset
from huggingface_hub import snapshot_download

repo = "hari31416/search-anything-benchmark"
corpus = load_dataset(repo, "corpus", split="corpus")
development = load_dataset(repo, "queries", split="dev")
held_out = load_dataset(repo, "queries", split="test")

# Media paths in corpus rows are relative to this downloaded directory.
root = snapshot_download(repo_id=repo, repo_type="dataset")
```

`corpus` has one row per asset, including `id`, `collection`, `task`, `source_id`, `path`, `content_type`, `bytes`, `sha256`, `source_url`, and optional `duration_seconds`. Media paths are strings, not automatically decoded media objects. Original manifests contain additional source-specific metadata.

Queries contain `id`, `collection`, `task`, `text`, `split`, and `relevant`, a list of relevant corpus IDs. COLA queries also have `pair_id` and `hard_negative`. Candidate IDs are unique across the package. Preserve them when computing metrics.

Search the full candidate pool for the query's task. The same candidate pool is shared by development and held-out queries. Use development queries for tuning and held-out queries to check a selected change. The existing Search Anything runner accepts each downloaded collection directory through `--root`; it creates a new local index state.

Evaluate Recall@5, Recall@10, MRR@10 and binary nDCG@10 per task. These are local subset scores, not official MMEB, MTEB, COLA or SLUE leaderboard results. Combining all tasks into one search pool requires additional relevance judgments.

## Selection and limitations

Selection is deterministic and retains all labeled positives for selected queries. The original text, image and environmental-audio tasks add lexical neighbors and random distractors. Video selection spans source categories, with one query per selected video. Relevant assets do not cross development and held-out query splits.

Spoken SQuAD contains synthesized speech about Super Bowl 50. Source paragraphs supplying queries stay within one split, and related sentences provide distractors.

COLA retains 50 contrasting image pairs. Captions from 25 pairs supply 50 queries; the remaining pairs add distractors. Pairs stay within one query split. Labels identify the positive and paired negative but may omit other relevant images in the pool. This tests object/attribute composition, not dedicated OCR.

SLUE contains natural human readings of Wikipedia. Each of its five question sources, Natural Questions, SQuAD, CuratedTREC, TriviaQA and WebQuestions, contributes six development and four held-out queries. Positive audio passages are cropped around all labeled answer occurrences to at most 30 seconds and converted to 16-bit PCM WAV. Crop offsets and answer times remain in the original manifest. Questions come from distinct articles and speakers; the full candidate pool covers 98 articles and 98 speakers. This tests bounded passage retrieval, not full-recording localization or noisy conversation.

Reference captions and answers belong to evaluation metadata. Ingest only the media files and original text documents into the search pipeline. Do not ingest query text or relevance metadata. Opaque media filenames avoid caption leakage. Caption relevance judgments can be incomplete, and small score changes need per-query inspection.

## Source references and terms

NanoSciFact's mirror declares CC BY 4.0. Clotho captions are for experimental and non-commercial use, and publications using them must acknowledge the Audio Research Group at Tampere University. The full copyright notice is in `source-notices/clotho-LICENSE.txt`. `source-notices/clotho-selected-attributions.jsonl` maps every packaged environmental-audio clip to its creator, original source URL, individual license and upstream excerpt offsets.

This compilation does not assign a single new license to its third-party content. Each source retains its original terms. Source notices are included under `source-notices/`; original dataset links and pinned revisions are recorded below and in the manifests. Check the original sources for citations, attribution, and permitted uses.

| Subset       | Original dataset and references                                                                                                                                                                               | Source terms and provenance                                                                                                                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NanoSciFact  | [NanoSciFact](https://huggingface.co/datasets/zeta-alpha-ai/NanoSciFact), [SciFact](https://github.com/allenai/scifact)                                                                                       | Original scientific document text and claim relevance labels; retain upstream notices.                                                                                                                          |
| MSCOCO_t2i   | [COCO](https://cocodataset.org/), [COCO terms](https://cocodataset.org/#termsofuse), [MMEB-V3](https://huggingface.co/datasets/VLM2Vec/MMEB-V3)                                                               | COCO annotations and individual images have distinct terms; images retain their original rights. MMEB supplies retrieval metadata.                                                                              |
| Clotho       | [Clotho v2.1](https://zenodo.org/records/4783391), [Clotho paper](https://arxiv.org/abs/1910.09387), [Freesound](https://freesound.org/)                                                                      | Caption license is the upstream Tampere University non-commercial attribution license. Audio licenses and creator credits vary by Freesound clip; see the included metadata and license.                        |
| MSR-VTT      | [MSR-VTT](https://www.microsoft.com/en-us/research/publication/msr-vtt-a-large-video-description-dataset-for-bridging-video-and-language/), [source mirror](https://huggingface.co/datasets/VLM2Vec/MSR-VTT)  | Original video and annotation rights remain with their respective owners; the mirror does not grant a new blanket media license.                                                                                |
| Spoken SQuAD | [Original Spoken SQuAD](https://github.com/Chia-Hsuan-Lee/Spoken-SQuAD), [MTEB retrieval mirror](https://huggingface.co/datasets/mteb/spoken-squad-t2a), [SQuAD](https://rajpurkar.github.io/SQuAD-explorer/) | The MTEB mirror declares Apache-2.0; underlying speech derives from SQuAD text, whose source terms also apply.                                                                                                  |
| COLA         | [COLA author repository](https://github.com/ArijitRay1993/COLA), [self-contained mirror](https://huggingface.co/datasets/array/cola), [Visual Genome](https://visualgenome.org/)                              | COLA annotations are MIT; underlying Visual Genome images retain their original source terms.                                                                                                                   |
| SLUE-SQA-5   | [SLUE Phase 2](https://huggingface.co/datasets/asapp/slue-phase-2), [SLUE repository](https://github.com/asappresearch/slue-toolkit), [Spoken Wikipedia](https://nats.gitlab.io/swc/)                         | Spoken Wikipedia audio is CC BY-SA 4.0. Question terms depend on source: TriviaQA is Apache-2.0; the other question sources are CC BY-SA 4.0. Cropping and PCM conversion are the modifications in this subset. |

Pinned source revisions:

```text
VLM2Vec/MMEB-V3: 4a5560b2b64384204b6fea8a82ea986eba51f5aa
zeta-alpha-ai/NanoSciFact: 309f1d1ae3ae2e092444a8a0c25bed59b82318bc
VLM2Vec/MSR-VTT: 947b139d0c591235a3f311e45a31a88461bad0d2
Clotho: Zenodo record 4783391, evaluation split
mteb/spoken-squad-t2a: b311394fa5ab5e003012304799d0d724d64303b3
array/cola: daee86b15a60308cfcc277ea11ab7f6be60fdfbc
asapp/slue-phase-2: e2989c55a53593a8e39b8f8ebdb47ccaccbe484a
```
