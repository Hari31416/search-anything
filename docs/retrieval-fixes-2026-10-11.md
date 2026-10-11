# Media and retrieval fixes

The four follow-up fixes preserve the existing models, fusion formula and channel
weights. They implement the changes discussed after the fixed-model experiments.

- Transcript segments now retain finite `avg_logprob`, `no_speech_prob` and
  `compression_ratio` values under `source_location.whisper_confidence`. These
  signals are exposed with the segment metadata and do not affect ranking yet.
  Missing or nonfinite values remain unknown rather than becoming zero.
- Media windows stop once a window covers the recording's end. With the default
  speech preset, a 30-second clip now produces only `0–30s`, instead of also
  producing `25–30s`. Intentional overlap remains for longer recordings. The
  shared window planner also handles video presets.
- Dense, lexical, filename and identifier channels with weight zero skip their
  database queries. An audio-only hybrid search executes one candidate query
  instead of nine. Unspecified weights retain their existing defaults.
- Dense queries break equal-distance ties by asset ID, segment ordinal and
  representation ID before applying the candidate limit.

Confidence metadata and corrected windows apply to newly indexed or reprocessed
files. Existing indexes were not modified or backfilled. Retrieval query skipping
and stable tie ordering apply immediately. No database migration is needed.

## Validation

The full test suite passed with 126 tests and one skipped test. Worker checks
verify that a 30-second clip is transcribed once, that its confidence values
survive text chunk planning, and that its segment timestamps are preserved.
Retrieval checks verify disabled channels execute no SQL and dense queries carry
stable ordering before truncation. Coverage checks include all four media presets.

A fresh production run reproduced all 210 previous development top-ten lists
exactly, with unchanged index and manifest identities. Held-out queries were not
used. PostgreSQL was stopped after validation; the API and worker were not started.

A separate read-only ablation excluded representations from redundant audio
windows before SQL candidate limits. It removed 31 audio windows from Clotho,
six from Spoken SQuAD and 99 from natural speech, together with their associated
ASR representations. It reused original query vectors and retained-window
embeddings. This is a simulation on the existing index, not a full reindex.

| Task | Recall@5 before / after | MRR@10 before / after |
| --- | ---: | ---: |
| Clotho sounds | 0.433 / 0.500 | 0.297 / 0.314 |
| Spoken SQuAD | 0.833 / 0.833 | 0.632 / 0.632 |
| Natural speech | 1.000 / 1.000 | 1.000 / 0.975 |

Removing fully covered tail windows reduces duplicate inference, but can change
ranking because a short crop is distinct evidence for the embedding model. The
natural-speech regression moves one development query from rank one to rank four
and should remain visible when choosing an intentional
short-window strategy. This change fixes window termination; it does not claim
an accuracy improvement for every task. Video/OCR reindexing effects were not
measured by the audio ablation.

The numeric results, artifact hashes and index identities are in
[the validation summary](benchmarks/retrieval-fixes-2026-10-11.json).
Query-level reports remain in `datasets/retrieval-fixes/`.

To repeat the read-only comparison, keep the original experiment snapshots and
baselines, start PostgreSQL, and run:

```sh
uv run python scripts/validate_retrieval_fixes.py
docker compose stop postgres
```

No local model inference or asset uploads are needed for this validation.
