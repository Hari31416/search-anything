"""Validate retrieval fixes without modifying the frozen benchmark indexes.

The tail-window ablation excludes cached audio and transcript representations
from redundant profile windows. It reruns SQL with exclusion BEFORE truncation.
No assets are reprocessed and no query embeddings are recomputed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from benchmark_search import run
from experiment_retrieval import ROOTS, METRICS
from prepare_search_benchmark import digest, save_json
from search_anything.media import window_ranges
from search_anything.models import Representation

OUTPUT = Path("datasets/retrieval-fixes")


def compare(before, after):
    by_id = {q["id"]: q for q in before["queries"]}
    return dict(
        changed_rankings=sum(
            q["ranked"] != by_id[q["id"]]["ranked"] for q in after["queries"]
        ),
        tasks={
            task: dict(
                before={m: s[m] for m in METRICS},
                after={m: after["summary"][task][m] for m in METRICS},
                mrr_delta=after["summary"][task]["mrr@10"] - s["mrr@10"],
            )
            for task, s in before["summary"].items()
        },
    )


async def main():
    OUTPUT.mkdir(exist_ok=True)
    report = dict(
        split="dev",
        index_writes=False,
        datasets={},
        note="Current SQL validated on unchanged indexes. Tail ablation excludes redundant audio windows and their ASR segments before candidate limits; it is not a full reindex. Existing video OCR is unchanged. Confidence storage is covered by worker tests, not backfilled.",
    )
    for root in ROOTS:
        snapshot_path = (
            Path("datasets/retrieval-experiments") / f"{root.name}-snapshot.json"
        )
        snapshot = json.loads(snapshot_path.read_text())
        assets = {a["id"]: a for a in snapshot["assets"]}
        excluded = []
        removed_windows = 0
        for r in snapshot["representations"]:
            asset = assets[r["key"]]
            c = r["candidate"]
            if not asset["content_type"].startswith("audio/") or c["kind"] not in {
                "audio",
                "transcript",
            }:
                continue
            retained = {
                w.start
                for w in window_ranges(asset["duration_seconds"], "speech_lectures")
            }
            start = (
                c["location"].get("profile_window_start")
                if c["kind"] == "audio"
                else c["location"].get("window_start")
            )
            if start is None:
                raise RuntimeError("Missing original window provenance")
            if start not in retained:
                excluded.append(UUID(c["representation_id"]))
                removed_windows += int(c["kind"] == "audio")
        before = json.loads(
            (
                Path("datasets/retrieval-experiments")
                / f"{root.name}-production-baseline.json"
            ).read_text()
        )
        current_path = OUTPUT / f"{root.name}-current.json"
        await run(root, current_path, "dev", None)
        current = json.loads(current_path.read_text())
        if (
            current["index_identity"] != before["index_identity"]
            or current["manifest_sha256"] != before["manifest_sha256"]
        ):
            raise RuntimeError("Benchmark identity changed")
        original_execute = AsyncSession.execute

        async def without_tail(self, statement, *args, **kwargs):
            if any(
                c.get("entity") is Representation
                for c in getattr(statement, "column_descriptions", ())
            ):
                statement = statement.where(Representation.id.not_in(excluded))
            return await original_execute(self, statement, *args, **kwargs)

        tail_path = OUTPUT / f"{root.name}-without-tails.json"
        with patch.object(AsyncSession, "execute", without_tail):
            await run(root, tail_path, "dev", None)
        tail = json.loads(tail_path.read_text())
        report["datasets"][root.name] = dict(
            index_identity=current["index_identity"],
            manifest_sha256=current["manifest_sha256"],
            retrieval_source_sha256=current["retrieval_source_sha256"],
            current_vs_previous=compare(before, current),
            tail_ablation_vs_current=compare(current, tail),
            excluded_representations=len(excluded),
            removed_audio_windows=removed_windows,
            current_seconds=current["retrieval_seconds"],
            tail_ablation_seconds=tail["retrieval_seconds"],
            current_report_sha256=digest(current_path),
            tail_report_sha256=digest(tail_path),
        )
    report["validation_source_sha256"] = digest(Path(__file__))
    save_json(Path("docs/benchmarks/retrieval-fixes-2026-10-11.json"), report)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(main())
