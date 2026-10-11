"""Read-only, development-only experiments around frozen local embedding models.

Capture production candidate lists once, replay ranking variants, then optionally
create local alternative embeddings. Never writes application database records.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import math
import re
import statistics
import tempfile
import time
from datetime import datetime, timezone
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, NAMESPACE_URL, uuid5

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from benchmark_search import load_state, metrics
from prepare_search_benchmark import digest, save_json, verify
from search_anything import retrieval
from search_anything.db import make_engine
from search_anything.embeddings import (
    DIMENSIONS,
    MODEL_ID,
    MODEL_REVISION,
    LocalEmbeddingModel,
    document_embedding_text,
)
from search_anything.models import (
    Asset,
    Embedding,
    ProcessingGeneration,
    Representation,
    Segment,
)
from search_anything.settings import Settings

LOG = logging.getLogger(__name__)
ROOTS = [
    Path("datasets/search-benchmark"),
    Path("datasets/spoken-squad-benchmark"),
    Path("datasets/expanded-benchmark"),
]
METRICS = ("recall@5", "recall@10", "mrr@10", "ndcg@10")
STOP = set(
    "a an the is are was were be been being to of in on at for with and or by as from it its this that which what who when where how does do did can would".split()
)


def plain(candidate):
    return json.loads(json.dumps(asdict(candidate), default=str))


def restore(value):
    value = dict(value)
    for key in ("asset_id", "representation_id", "generation_id"):
        value[key] = UUID(value[key])
    return retrieval.Candidate(**value)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def capture(output: Path):
    if output.exists() and any(output.glob("*-snapshot.json")):
        raise RuntimeError(
            "Snapshot output already exists; use a fresh --output directory"
        )
    settings = Settings()
    engine = make_engine(settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    output.mkdir(parents=True, exist_ok=True)
    try:
        async with sessions() as session:
            for root in ROOTS:
                verify(root)
                manifest, state = load_state(root)
                workspace = UUID(state["workspace_id"])
                cache = json.loads((root / "query-vectors.json").read_text())
                identity = cache["identity"]
                expected = dict(
                    model=MODEL_ID,
                    revision=MODEL_REVISION,
                    dimensions=DIMENSIONS,
                    context_tokens=settings.embedding_context_tokens,
                    model_path=str(settings.embedding_model_path),
                    manifest=digest(root / "manifest.json"),
                )
                if identity != expected:
                    raise RuntimeError(f"{root}: incompatible query-vector cache")
                reverse = {r["asset_id"]: key for key, r in state["assets"].items()}
                ready = set(
                    str(x)
                    for x in (
                        await session.scalars(
                            select(Asset.id).where(
                                Asset.workspace_id == workspace, Asset.state == "ready"
                            )
                        )
                    ).all()
                )
                if ready != set(reverse) or len(ready) != len(manifest["assets"]):
                    raise RuntimeError(f"{root}: incomplete or unexpected index")
                rows = (
                    await session.execute(
                        select(
                            Asset,
                            ProcessingGeneration,
                            Representation,
                            Segment,
                            Embedding.vector,
                        )
                        .join(
                            ProcessingGeneration,
                            ProcessingGeneration.id == Asset.active_generation_id,
                        )
                        .join(
                            Representation,
                            Representation.generation_id == ProcessingGeneration.id,
                        )
                        .outerjoin(Segment, Segment.id == Representation.segment_id)
                        .outerjoin(
                            Embedding,
                            (Embedding.representation_id == Representation.id)
                            & (Embedding.model_id == MODEL_ID)
                            & (Embedding.model_revision == MODEL_REVISION),
                        )
                        .where(Asset.workspace_id == workspace)
                        .order_by(Representation.id)
                    )
                ).all()
                reps = []
                for asset, generation, rep, segment, vector in rows:
                    item = plain(retrieval._candidate(asset, generation, rep, segment))
                    reps.append(
                        dict(
                            candidate=item,
                            vector=None if vector is None else list(map(float, vector)),
                            key=reverse[str(asset.id)],
                        )
                    )
                generations = [
                    [str(a), str(g), p]
                    for a, g, p in (
                        await session.execute(
                            select(
                                Asset.id,
                                ProcessingGeneration.id,
                                ProcessingGeneration.profile_snapshot,
                            )
                            .join(
                                ProcessingGeneration,
                                ProcessingGeneration.id == Asset.active_generation_id,
                            )
                            .where(Asset.workspace_id == workspace)
                            .order_by(Asset.id)
                        )
                    ).all()
                ]
                queries = []
                for query in manifest["queries"]:
                    if query["split"] != "dev":
                        continue
                    if query["id"] not in cache["vectors"]:
                        raise RuntimeError(
                            f'Missing dev query embedding: {query["id"]}'
                        )
                    captured = {}

                    def intercept(channels, weights=None):
                        captured.update(
                            {k: [plain(c) for c in v] for k, v in channels.items()}
                        )
                        return []

                    started = time.perf_counter()
                    with patch.object(retrieval, "reciprocal_rank_fusion", intercept):
                        await retrieval.search_workspace(
                            session,
                            workspace,
                            mode="hybrid",
                            query=query["text"],
                            vector=cache["vectors"][query["id"]],
                            limit=len(reverse),
                            candidate_limit=10000,
                            content_types=[
                                next(
                                    a["content_type"]
                                    for a in manifest["assets"]
                                    if a["task"] == query["task"]
                                )
                            ],
                        )
                    extended_channels = {k: v[:200] for k, v in captured.items()}
                    exact_channels = {}

                    def production_intercept(channels, weights=None):
                        exact_channels.update(
                            {k: [plain(c) for c in v] for k, v in channels.items()}
                        )
                        return original_fusion(channels, weights)

                    original_fusion = retrieval.reciprocal_rank_fusion
                    production_started = time.perf_counter()
                    with patch.object(
                        retrieval, "reciprocal_rank_fusion", production_intercept
                    ):
                        production = await retrieval.search_workspace(
                            session,
                            workspace,
                            mode="hybrid",
                            query=query["text"],
                            vector=cache["vectors"][query["id"]],
                            limit=10,
                            candidate_limit=60,
                            content_types=[
                                next(
                                    a["content_type"]
                                    for a in manifest["assets"]
                                    if a["task"] == query["task"]
                                )
                            ],
                        )
                    production_seconds = time.perf_counter() - production_started
                    eligible = set()
                    for values in captured.values():
                        eligible.update(reverse[c["asset_id"]] for c in values)
                    top60 = {
                        reverse[c["asset_id"]]
                        for values in exact_channels.values()
                        for c in values[:60]
                    }
                    queries.append(
                        dict(
                            **query,
                            vector=cache["vectors"][query["id"]],
                            channels=exact_channels,
                            extended_channels=extended_channels,
                            candidate_recall60=len(set(query["relevant"]) & top60)
                            / len(query["relevant"]),
                            candidate_recall_full=len(set(query["relevant"]) & eligible)
                            / len(query["relevant"]),
                            capture_seconds=time.perf_counter() - started,
                            production_ranked=[
                                reverse[str(h["asset_id"])] for h in production
                            ],
                            production_seconds=production_seconds,
                        )
                    )
                    if len(queries) % 10 == 0:
                        LOG.info("%s captured %d dev queries", root.name, len(queries))
                snapshot = dict(
                    root=str(root),
                    manifest_sha256=digest(root / "manifest.json"),
                    embedding_identity=identity,
                    index_identity=fingerprint(generations),
                    retrieval_source_sha256=digest(Path(inspect.getfile(retrieval))),
                    assets=manifest["assets"],
                    reverse=reverse,
                    representations=reps,
                    queries=queries,
                    note="Full candidate capture is read-only; replay defaults truncate each channel to 60. Only dev queries captured.",
                )
                save_json(output / f"{root.name}-snapshot.json", snapshot)
                LOG.info(
                    "Saved %s: %d representations, %d queries",
                    root.name,
                    len(reps),
                    len(queries),
                )
    finally:
        await engine.dispose()


def terms(value):
    return [t for t in re.findall(r"[^\W_]+", value.casefold()) if t not in STOP]


def text_quality(value):
    """Conservative structural checks, independent of relevance labels."""
    words = terms(value)
    if not words:
        return 0.1
    if len(words) >= 8:
        repeated = Counter(tuple(words[i : i + 3]) for i in range(len(words) - 2))
        if max(repeated.values(), default=0) >= 3:
            return 0.1
    return 1.0


def confidence_quality(candidate, segments):
    relevant = [
        s
        for s in segments
        if candidate.time_start is not None
        and s.get("window_start", candidate.location.get("window_start"))
        == candidate.location.get("window_start")
        and min(candidate.time_end, s["end"]) > max(candidate.time_start, s["start"])
    ]
    if not relevant:
        return text_quality(candidate.text or "")
    weights = [
        min(candidate.time_end, s["end"]) - max(candidate.time_start, s["start"])
        for s in relevant
    ]

    def average(key):
        return sum(s[key] * w for s, w in zip(relevant, weights)) / sum(weights)

    bad = (
        average("no_speech_prob") > 0.6
        or average("avg_logprob") < -1.0
        or average("compression_ratio") > 2.4
    )
    return min(0.1 if bad else 1.0, text_quality(candidate.text or ""))


def ocr_quality(candidate):
    words = candidate.location.get("ocr_words") or candidate.location.get(
        "source_location", {}
    ).get("ocr_words")
    if not words:
        return 1.0
    total = confidence = 0.0
    for word in words:
        length = sum(c.isalnum() for c in str(word.get("text", "")))
        try:
            value = float(word.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            total += length
            confidence += length * min(100.0, value)
    return max(0.1, (confidence / (100 * total)) ** 2) if total else 1.0


def lexical(channels, representations, query, task_keys):
    docs = [
        r
        for r in representations
        if r["key"] in task_keys
        and r["candidate"]["kind"] in {"text", "transcript", "ocr"}
        and r["candidate"]["text"]
        and retrieval._usable_ocr(restore(r["candidate"]))
    ]
    counters = [Counter(terms(r["candidate"]["text"])) for r in docs]
    q = set(terms(query))
    df = Counter(t for c in counters for t in q if t in c)
    average = statistics.mean(sum(c.values()) for c in counters) if counters else 1
    ranked = []
    for r, c in zip(docs, counters):
        length = sum(c.values())
        score = sum(
            math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            * c[t]
            * 2.2
            / (c[t] + 1.2 * (0.25 + 0.75 * length / max(average, 1)))
            for t in q
            if c[t]
        )
        if score:
            ranked.append((score, r["candidate"]))
    ranked.sort(key=lambda x: (-x[0], x[1]["asset_id"], x[1]["representation_id"]))
    return [restore(r) for _, r in ranked]


def rank(snapshot, query, variant, augmentation):
    raw_channels = (
        query["extended_channels"] if variant == "candidates_200" else query["channels"]
    )
    channels = {
        k: [restore(c) for c in v] for k, v in raw_channels.items() if k != "combined"
    }
    weights = {}
    if variant == "lexical_weight_2":
        weights = {"lexical": 2.0, "identifier": 2.0}
    if variant == "transcript_weight_025":
        weights = {"transcript": 0.25}
    if variant == "audio_only":
        weights = {k: float(k == "audio") for k in retrieval.DEFAULT_WEIGHTS}
    if variant == "image_only":
        weights = {k: float(k in {"image", "video"}) for k in retrieval.DEFAULT_WEIGHTS}
    if variant == "bm25":
        task_keys = {a["id"] for a in snapshot["assets"] if a["task"] == query["task"]}
        channels["lexical"] = lexical(
            channels, snapshot["representations"], query["text"], task_keys
        )
    if variant in {
        "image_crops_max",
        "image_crops_mean",
        "audio_15s",
        "audio_15s_only",
        "transcript_sentences",
    }:
        kind = {
            "image_crops_max": "image",
            "image_crops_mean": "image",
            "audio_15s": "audio",
            "audio_15s_only": "audio",
            "transcript_sentences": "transcript",
        }[variant]
        alternatives = augmentation.get("alternatives", {}).get(kind, [])
        task_keys = {a["id"] for a in snapshot["assets"] if a["task"] == query["task"]}
        alternatives = [r for r in alternatives if r["key"] in task_keys]
        if alternatives:
            records = [
                r
                for r in snapshot["representations"]
                if r["key"] in task_keys
                and r["candidate"]["kind"] == kind
                and r["vector"] is not None
            ]
            if variant not in {"transcript_sentences", "audio_15s_only"}:
                records += alternatives
            else:
                records = alternatives
            vector = np.asarray(query["vector"], dtype=np.float32)
            values = (
                np.asarray([r["vector"] for r in records], dtype=np.float32) @ vector
            )
            candidates = [
                replace(restore(r["candidate"]), similarity=float(s))
                for r, s in zip(records, values)
            ]
            if kind == "audio":
                unique = {}
                for c in candidates:
                    key = (c.asset_id, round(c.time_start, 3), round(c.time_end, 3))
                    if key not in unique or c.similarity > unique[key].similarity:
                        unique[key] = c
                candidates = list(unique.values())
            if variant in {"image_crops_mean", "image_crops_max"}:
                grouped = {}
                for c in candidates:
                    grouped.setdefault(c.asset_id, []).append(c)
                candidates = [
                    (
                        max(cs, key=lambda c: c.similarity)
                        if variant == "image_crops_max"
                        else replace(
                            cs[0], similarity=statistics.mean(c.similarity for c in cs)
                        )
                    )
                    for cs in grouped.values()
                ]
            channels[kind] = sorted(
                candidates,
                key=lambda c: (
                    -c.similarity,
                    str(c.asset_id),
                    str(c.representation_id),
                ),
            )
    cap = {"candidates_20": 20, "candidates_200": 200}.get(variant, 60)
    channels = {k: v[:cap] for k, v in channels.items()}
    exponent = {"rank_only": 0.0, "cosine_linear": 1.0, "cosine_sqrt": 0.5}.get(
        variant, 2.0
    )
    original = retrieval._channel_score

    def score(candidate, weight, rank):
        value = weight / (retrieval.FUSION_CONSTANT + rank)
        if candidate.similarity is not None and exponent:
            value *= max(0.0, min(1.0, candidate.similarity)) ** exponent
        if (
            variant in {"quality_structural", "quality_confidence"}
            and candidate.kind == "transcript"
        ):
            quality = text_quality(candidate.text or "")
            if variant == "quality_confidence":
                quality = confidence_quality(
                    candidate,
                    augmentation.get("confidence", {}).get(str(candidate.asset_id), []),
                )
            value *= quality
        if variant == "quality_ocr" and candidate.kind == "ocr":
            value *= ocr_quality(candidate)
        return value

    if variant == "sum_rrf":
        # Compare sum over aligned evidence with current strongest+bounded-support.
        fused = retrieval.reciprocal_rank_fusion(channels, weights)
        grouped_ranks = {}
        for channel, members in channels.items():
            positions = {c.representation_id: i for i, c in enumerate(members)}
            evidence = [
                hit.channel_evidence[channel]
                for hit in fused
                if channel in hit.channel_evidence
            ]
            evidence.sort(key=lambda c: positions[c.representation_id])
            grouped_ranks[channel] = {
                c.representation_id: i + 1 for i, c in enumerate(evidence)
            }
        for hit in fused:
            hit.score = sum(
                original(
                    c,
                    {**retrieval.DEFAULT_WEIGHTS, **weights}.get(k, 1),
                    grouped_ranks[k][c.representation_id],
                )
                for k, c in hit.channel_evidence.items()
            )
        fused.sort(key=lambda c: (-c.score, str(c.asset_id), str(c.representation_id)))
    else:
        with patch.object(retrieval, "_channel_score", score):
            fused = retrieval.reciprocal_rank_fusion(channels, weights)
    hits = retrieval.group_assets(fused)
    return [snapshot["reverse"][str(h["asset_id"])] for h in hits]


def paired_interval(differences, seed=20261011, groups=None):
    if not differences:
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    clustered = {}
    for key, value in zip(groups or range(len(differences)), differences):
        clustered.setdefault(key, []).append(value)
    sums = np.asarray([sum(v) for v in clustered.values()])
    counts = np.asarray([len(v) for v in clustered.values()])
    indices = rng.integers(len(sums), size=(4000, len(sums)))
    draws = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    return [float(x) for x in np.quantile(draws, [0.025, 0.975])]


def evaluate(output):
    variants = [
        "baseline",
        "rank_only",
        "cosine_linear",
        "cosine_sqrt",
        "sum_rrf",
        "candidates_20",
        "candidates_200",
        "lexical_weight_2",
        "bm25",
        "transcript_weight_025",
        "quality_structural",
        "quality_ocr",
        "quality_confidence",
        "image_only",
        "audio_only",
        "image_crops_max",
        "image_crops_mean",
        "audio_15s",
        "audio_15s_only",
        "transcript_sentences",
    ]
    report = dict(
        created_at=datetime.now(timezone.utc).isoformat(),
        experiment_source_sha256=digest(Path(__file__)),
        split="dev",
        seed=20261011,
        variants={},
        artifacts={},
        timing_note="Replay seconds measure in-memory ranking only, not end-to-end search; capture seconds include exhaustive SQL retrieval. Compare production SQL timing separately.",
        limitations=[
            "Small development samples; no held-out evaluation or selected production change.",
            "Natural speech currently at ceiling with mostly unrelated distractors.",
            "OCR extraction filter is inherited; no dedicated noisy OCR relevance benchmark.",
            "Existing multiple-window and lexical retrieval remain enabled.",
            "Alternative views add vector storage and model inference; no application index writes.",
            "Whisper confidence is recomputed with original windows, and is a proxy for discarded original confidence values.",
            "Bootstrap intervals are exploratory, without correction for testing multiple variants.",
        ],
    )
    detailed = []
    for root in ROOTS:
        path = output / f"{root.name}-snapshot.json"
        snapshot = json.loads(path.read_text())
        if snapshot["retrieval_source_sha256"] != digest(
            Path(inspect.getfile(retrieval))
        ):
            raise RuntimeError("Retrieval implementation changed since capture")
        ap = output / f"{root.name}-augmentation.json"
        augmentation = json.loads(ap.read_text()) if ap.exists() else {}
        if augmentation and augmentation["snapshot_sha256"] != digest(path):
            raise RuntimeError("Augmentation is from a different snapshot")
        report["artifacts"][root.name] = dict(
            snapshot_sha256=digest(path),
            index_identity=snapshot["index_identity"],
            manifest_sha256=snapshot["manifest_sha256"],
            embedding_identity=snapshot["embedding_identity"],
            augmentation_sha256=digest(ap) if ap.exists() else None,
            augmentation_stats=augmentation.get("stats", {}),
        )
        production_path = output / f"{root.name}-production-baseline.json"
        if production_path.exists():
            production = json.loads(production_path.read_text())
            if (
                production["index_identity"] != snapshot["index_identity"]
                or production["manifest_sha256"] != snapshot["manifest_sha256"]
            ):
                raise RuntimeError("Production timing baseline has a different index")
            report["artifacts"][root.name].update(
                production_baseline_sha256=digest(production_path),
                production_retrieval_seconds=production["retrieval_seconds"],
            )
        baselines = {}
        for variant in variants:
            component = {
                "quality_confidence": "confidence",
                "image_crops_max": "image",
                "image_crops_mean": "image",
                "audio_15s": "audio",
                "audio_15s_only": "audio",
                "transcript_sentences": "transcript",
            }.get(variant)
            if component and component not in augmentation.get("complete", []):
                continue
            for task in sorted({q["task"] for q in snapshot["queries"]}):
                if variant.startswith("image_") and task not in {
                    "image",
                    "image_hard",
                    "video",
                }:
                    continue
                if variant in {
                    "audio_only",
                    "audio_15s",
                    "audio_15s_only",
                    "transcript_sentences",
                    "quality_structural",
                    "quality_confidence",
                    "transcript_weight_025",
                } and task not in {"audio", "speech", "natural_speech", "video"}:
                    continue
                if variant.startswith("image_crops") and not (
                    task == "image_hard"
                    and augmentation.get("alternatives", {}).get("image")
                ):
                    continue
                if (
                    variant in {"audio_15s", "audio_15s_only", "transcript_sentences"}
                    and task == "video"
                ):
                    continue
                if variant == "quality_confidence" and task == "video":
                    continue
                rows = []
                for query in snapshot["queries"]:
                    if query["task"] != task:
                        continue
                    before = time.perf_counter()
                    ranked = rank(snapshot, query, variant, augmentation)
                    elapsed = time.perf_counter() - before
                    score = metrics(ranked, query["relevant"])
                    if variant == "baseline":
                        if ranked[:10] != query["production_ranked"]:
                            raise RuntimeError(
                                f'Baseline replay differs from production: {query["id"]}'
                            )
                        baselines[query["id"]] = score
                    rows.append(
                        dict(
                            id=query["id"],
                            ranked=ranked[:10],
                            relevant=query["relevant"],
                            seconds=elapsed,
                            **score,
                        )
                    )
                differences = [r["mrr@10"] - baselines[r["id"]]["mrr@10"] for r in rows]
                groups = [
                    q.get("pair_id", q["id"])
                    for q in snapshot["queries"]
                    if q["task"] == task
                ]
                result = {m: statistics.mean(r[m] for r in rows) for m in METRICS}
                result.update(
                    queries=len(rows),
                    ranking_seconds=sum(r["seconds"] for r in rows),
                    mrr_delta=statistics.mean(differences),
                    mrr_delta_bootstrap95=paired_interval(differences, groups=groups),
                    bootstrap_unit="contrast_pair" if task == "image_hard" else "query",
                    improved=sum(d > 1e-9 for d in differences),
                    regressed=sum(d < -1e-9 for d in differences),
                )
                if variant == "baseline":
                    qs = [q for q in snapshot["queries"] if q["task"] == task]
                    result.update(
                        candidate_recall60=statistics.mean(
                            q["candidate_recall60"] for q in qs
                        ),
                        candidate_recall_full=statistics.mean(
                            q["candidate_recall_full"] for q in qs
                        ),
                        production_retrieval_seconds=sum(
                            q["production_seconds"] for q in qs
                        ),
                    )
                report["variants"].setdefault(variant, {})[task] = result
                detailed.append(
                    dict(dataset=root.name, task=task, variant=variant, queries=rows)
                )
                LOG.info(
                    "%s %s R5 %.3f MRR %.3f delta %+.3f",
                    task,
                    variant,
                    result["recall@5"],
                    result["mrr@10"],
                    result["mrr_delta"],
                )
    save_json(output / "results.json", report)
    save_json(output / "per-query.json", detailed)


def sentence_parts(text):
    # Retain adjacent sentence context; split long unpunctuated speech by word count.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    parts = []
    for i, sentence in enumerate(sentences):
        context = " ".join(sentences[max(0, i - 1) : i + 1])
        words = context.split()
        parts.extend(" ".join(words[j : j + 80]) for j in range(0, len(words), 60))
    return list(dict.fromkeys(p for p in parts if p.strip()))


def boxes(width, height):
    # Fixed crops without a detector, labels, or query-dependent selection.
    result = []
    for x, y in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        w, h = round(width * 0.7), round(height * 0.7)
        result.append(
            (
                x * (width - w),
                y * (height - h),
                x * (width - w) + w,
                y * (height - h) + h,
            )
        )
    return result


def alternative(base, vector, label, *, text=None, start=None, end=None):
    candidate = dict(base["candidate"])
    candidate["representation_id"] = str(
        uuid5(NAMESPACE_URL, candidate["representation_id"] + label)
    )
    if text is not None:
        candidate["text"] = text
    if start is not None:
        candidate.update(time_start=start, time_end=end)
    return dict(candidate=candidate, vector=vector, key=base["key"])


def sentence_passages(members):
    """Map sentence context back to overlapping original ASR segment bounds."""
    spans = []
    texts = []
    cursor = 0
    for member in members:
        text = " ".join(member["candidate"]["text"].split())
        spans.append((cursor, cursor + len(text), member["candidate"]))
        texts.append(text)
        cursor += len(text) + 1
    full = " ".join(texts)
    result = []
    for part in sentence_parts(full):
        start = full.find(part)
        if start < 0:
            raise RuntimeError("Sentence passage cannot be located in indexed ASR text")
        end = start + len(part)
        matched = [c for lo, hi, c in spans if min(hi, end) > max(lo, start)]
        result.append(
            (
                part,
                min(c["time_start"] for c in matched),
                max(c["time_end"] for c in matched),
            )
        )
    return result


def augment(output: Path, component: str, max_seconds: int):
    from PIL import Image
    from search_anything.media import (
        MediaWindow,
        extract_audio_window,
        load_whisper,
        transcribe_window,
    )

    settings = Settings()
    model = None
    whisper = None
    started = time.monotonic()
    for root in ROOTS:
        sp = output / f"{root.name}-snapshot.json"
        snapshot = json.loads(sp.read_text())
        ap = output / f"{root.name}-augmentation.json"
        data = (
            json.loads(ap.read_text())
            if ap.exists()
            else dict(
                snapshot_sha256=digest(sp),
                alternatives={},
                confidence={},
                stats={},
                complete=[],
            )
        )
        if data["snapshot_sha256"] != digest(sp):
            raise RuntimeError("Stale augmentation snapshot")
        if component in data["complete"]:
            LOG.info("%s %s already complete", root.name, component)
            continue

        def check_time():
            if time.monotonic() - started > max_seconds:
                save_json(ap, data)
                raise TimeoutError(
                    "Experiment inference budget exceeded; progress retained"
                )

        selected = [
            a
            for a in snapshot["assets"]
            if (
                a["task"] == "image_hard"
                if component == "image"
                else a["task"] in {"audio", "speech", "natural_speech"}
            )
        ]
        reps = snapshot["representations"]
        for i, asset in enumerate(selected):
            check_time()
            marker = f'{component}:{asset["id"]}'
            if marker in data["complete"]:
                continue
            media = root / asset["path"]
            if digest(media) != asset["sha256"]:
                raise RuntimeError("Media checksum changed")
            record_started = time.monotonic()
            if component != "confidence" and model is None:
                model = LocalEmbeddingModel(
                    settings.embedding_model_path,
                    context_tokens=settings.embedding_context_tokens,
                    batch_size=settings.embedding_batch_size,
                    device=settings.embedding_device,
                )
            bases = [r for r in reps if r["key"] == asset["id"]]
            if component == "image":
                base = next(r for r in bases if r["candidate"]["kind"] == "image")
                with Image.open(media) as image:
                    image = image.convert("RGB")
                    crops = [image.crop(b) for b in boxes(*image.size)]
                    vectors = model.embed_images(crops)
                data["alternatives"].setdefault("image", []).extend(
                    alternative(base, v, f"crop-{j}") for j, v in enumerate(vectors)
                )
            elif component == "audio":
                import wave

                with wave.open(str(media)) as wav:
                    duration = wav.getnframes() / wav.getframerate()
                base = next(r for r in bases if r["candidate"]["kind"] == "audio")
                with tempfile.TemporaryDirectory(prefix="search-experiment-") as folder:
                    for j, start in enumerate(np.arange(0, duration, 12.0)):
                        end = min(duration, float(start) + 15.0)
                        path = Path(folder) / f"{j}.wav"
                        extract_audio_window(
                            media, path, MediaWindow(float(start), end)
                        )
                        matching = next(
                            (
                                r
                                for r in bases
                                if r["candidate"]["kind"] == "audio"
                                and abs(r["candidate"]["time_start"] - start) < 0.001
                                and abs(r["candidate"]["time_end"] - end) < 0.001
                            ),
                            None,
                        )
                        vector = (
                            matching["vector"] if matching else model.embed_audio(path)
                        )
                        data["alternatives"].setdefault("audio", []).append(
                            alternative(
                                base, vector, f"15s-{j}", start=float(start), end=end
                            )
                        )
                        if end >= duration:
                            break
            elif component == "transcript":
                groups = {}
                for base in bases:
                    c = base["candidate"]
                    if c["kind"] == "transcript" and c["text"]:
                        groups.setdefault(
                            c["location"].get("window_start", 0), []
                        ).append(base)
                for start, members in groups.items():
                    members.sort(
                        key=lambda r: (
                            r["candidate"]["time_start"],
                            r["candidate"]["representation_id"],
                        )
                    )
                    base = members[0]
                    passages = sentence_passages(members)
                    parts = [p for p, _, _ in passages]
                    vectors = model.embed_texts(
                        [
                            document_embedding_text(base["candidate"]["filename"], p)
                            for p in parts
                        ]
                    )
                    data["alternatives"].setdefault("transcript", []).extend(
                        alternative(
                            base,
                            v,
                            f"sentence-{j}",
                            text=p,
                            start=passages[j][1],
                            end=passages[j][2],
                        )
                        for j, (p, v) in enumerate(zip(parts, vectors))
                    )
            else:
                if whisper is None:
                    whisper = load_whisper(
                        settings.whisper_checkpoint_path, device=settings.whisper_device
                    )
                # Recover confidence with each original audio window's context.
                # Ranking still uses the ORIGINAL indexed text.
                segments = []
                with tempfile.TemporaryDirectory(prefix="search-confidence-") as folder:
                    for j, base in enumerate(
                        r for r in bases if r["candidate"]["kind"] == "audio"
                    ):
                        c = base["candidate"]
                        start, end = c["time_start"], c["time_end"]
                        path = Path(folder) / f"{j}.wav"
                        extract_audio_window(media, path, MediaWindow(start, end))
                        transcription = transcribe_window(whisper, path)
                        for s in transcription["segments"]:
                            item = {
                                k: float(s[k])
                                for k in [
                                    "start",
                                    "end",
                                    "avg_logprob",
                                    "no_speech_prob",
                                    "compression_ratio",
                                ]
                            }
                            item.update(
                                start=item["start"] + start,
                                end=item["end"] + start,
                                window_start=start,
                            )
                            segments.append(item)
                asset_id = next(r["candidate"]["asset_id"] for r in bases)
                data["confidence"][asset_id] = segments
            data["complete"].append(marker)
            stat = data["stats"].setdefault(
                component, dict(seconds=0.0, assets=0, vectors=0)
            )
            stat["seconds"] += time.monotonic() - record_started
            stat["assets"] += 1
            stat["vectors"] = len(
                data["alternatives"].get(
                    {
                        "image": "image",
                        "audio": "audio",
                        "transcript": "transcript",
                    }.get(component, ""),
                    [],
                )
            )
            save_json(ap, data)
            if i % 5 == 0:
                LOG.info(
                    "%s %s %d/%d elapsed %.1fs",
                    root.name,
                    component,
                    i + 1,
                    len(selected),
                    time.monotonic() - started,
                )
        data["complete"].append(component)
        save_json(ap, data)
    LOG.info("%s completed in %.1fs", component, time.monotonic() - started)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("datasets/retrieval-experiments")
    )
    parser.add_argument("command", choices=["capture", "evaluate", "augment"])
    parser.add_argument(
        "--component", choices=["image", "audio", "transcript", "confidence"]
    )
    parser.add_argument("--max-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.command == "capture":
        asyncio.run(capture(args.output))
    elif args.command == "evaluate":
        evaluate(args.output)
    else:
        if not args.component:
            parser.error("augment requires --component")
        augment(args.output, args.component, args.max_seconds)
