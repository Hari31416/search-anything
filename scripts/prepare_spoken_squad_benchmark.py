"""Prepare a frozen speech-content task alongside the original benchmark.

Run with uv run --with pyarrow==19.0.1 python scripts/prepare_spoken_squad_benchmark.py.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import random
import wave
from collections import defaultdict
from pathlib import Path

from prepare_search_benchmark import Budget, SEED, digest, download, save_json, verify

LOG = logging.getLogger(__name__)
REVISION = "b311394fa5ab5e003012304799d0d724d64303b3"
SOURCE_URLS = {
    f"{group}.parquet": (
        "https://huggingface.co/datasets/mteb/spoken-squad-t2a/resolve/"
        f"{REVISION}/{group}/{split}-00000-of-00001.parquet"
    )
    for group, split in (("query", "test"), ("qrels", "test"), ("corpus", "corpus"))
}


def paragraph(identifier: str) -> str:
    return identifier.rsplit("_", 1)[0]


def select_queries(rows: list[dict], qrels: list[dict]) -> list[dict]:
    """Round-robin source paragraphs; assign each paragraph to one split."""
    positives = defaultdict(set)
    for row in qrels:
        if row["score"] > 0:
            positives[row["query-id"]].add(row["corpus-id"])
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["id"]):
        relevant = sorted(positives[row["id"]])
        if not relevant:
            continue
        origins = {paragraph(key) for key in relevant}
        if len(origins) != 1:
            raise ValueError("Query spans paragraphs; paragraph split is unsafe")
        groups[next(iter(origins))].append(
            dict(
                id=f"spoken-squad:{row['id']}",
                text=row["text"],
                relevant=relevant,
                task="speech",
            )
        )
    rng = random.Random(SEED)
    keys = sorted(groups)
    rng.shuffle(keys)
    for group in groups.values():
        rng.shuffle(group)
    # Separate whole paragraphs before selecting questions. Each source
    # paragraph contributes once per pass, preventing large groups dominating.
    boundary = round(len(keys) * 0.6)
    queries = []
    for split, origins, count in (
        ("dev", keys[:boundary], 30),
        ("test", keys[boundary:], 20),
    ):
        selected = []
        while len(selected) < count:
            progress = False
            for key in origins:
                if groups[key] and len(selected) < count:
                    query = groups[key].pop()
                    query["split"] = split
                    selected.append(query)
                    progress = True
            if not progress:
                raise ValueError(f"Insufficient queries for {split}")
        queries.extend(selected)
    return queries


def prepare(root: Path, cap: int) -> None:
    import pyarrow.parquet as parquet

    if (root / "manifest.json").exists():
        raise RuntimeError("Manifest already frozen. Use --verify or a new --root.")
    source, media = root / "source", root / "media"
    source.mkdir(parents=True, exist_ok=True)
    media.mkdir(exist_ok=True)
    budget = Budget(root, cap)
    for name, url in SOURCE_URLS.items():
        download(url, source / name, budget)
    queries = select_queries(
        parquet.read_table(source / "query.parquet").to_pylist(),
        parquet.read_table(source / "qrels.parquet").to_pylist(),
    )
    corpus = {
        row["id"]: row["audio"]["bytes"]
        for row in parquet.read_table(source / "corpus.parquet").to_pylist()
    }
    selected = {key for q in queries for key in q["relevant"]}
    if len(selected) > 100 or not selected <= corpus.keys():
        raise ValueError("Cannot retain all positives in 100 candidates")
    rng = random.Random(SEED)
    # Same-paragraph sentences are distractors about closely related content.
    neighbors = sorted(set(corpus) - selected)
    rng.shuffle(neighbors)
    origins = {paragraph(key) for key in selected}
    for key in neighbors:
        if paragraph(key) in origins and len(selected) < 100:
            selected.add(key)
    for key in neighbors:
        if len(selected) < 100:
            selected.add(key)
    if len(selected) != 100:
        raise ValueError("Corpus cannot supply 100 candidates")
    assets = []
    for key in sorted(selected):
        identifier = f"speech:{key}"
        path = media / (hashlib.sha256(identifier.encode()).hexdigest()[:24] + ".wav")
        if not path.exists():
            budget.consume(len(corpus[key]))
            path.write_bytes(corpus[key])
        with wave.open(str(path)) as audio:
            duration = audio.getnframes() / audio.getframerate()
        if duration <= 0:
            raise ValueError(f"Empty audio: {key}")
        assets.append(
            dict(
                id=identifier,
                source_id=key,
                task="speech",
                path=f"media/{path.name}",
                content_type="audio/wav",
                bytes=path.stat().st_size,
                sha256=digest(path),
                duration_seconds=duration,
                source_url=SOURCE_URLS["corpus.parquet"],
            )
        )
    for query in queries:
        query["relevant"] = [f"speech:{key}" for key in query["relevant"]]
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    disabled = dict.fromkeys(
        (
            "text",
            "transcript",
            "ocr",
            "image",
            "audio",
            "video",
            "combined",
            "lexical",
            "identifier",
            "filename",
        ),
        0,
    )
    for name, mode, enabled in (
        ("audio-only", "semantic", ("audio",)),
        ("transcript-only", "hybrid", ("transcript", "lexical", "identifier")),
    ):
        save_json(
            configs / f"{name}.json",
            dict(
                mode=mode,
                candidate_limit=60,
                representation_mode="separate",
                weights={**disabled, **dict.fromkeys(enabled, 1.0)},
            ),
        )
    manifest = dict(
        version=1,
        name="search-anything-spoken-squad-v1",
        seed=SEED,
        sources={"mteb/spoken-squad-t2a": REVISION},
        source_files={
            name: dict(url=url, sha256=digest(source / name))
            for name, url in SOURCE_URLS.items()
        },
        assets=assets,
        queries=queries,
        limitations=[
            "Synthesized speech, not natural conversations or meetings",
            "This upstream subset covers Super Bowl 50 only",
            "Source sentence boundaries define retrieval candidates",
            "Reference transcripts are not supplied to ingestion",
            "Whole source paragraphs assigned to a single query split",
            "Scores are not official MTEB or MMEB scores",
        ],
    )
    save_json(root / "selection.json", dict(assets=assets, queries=queries))
    save_json(root / "manifest.json", manifest)
    verify(root)
    LOG.info(
        "Prepared %.1f minutes of speech",
        sum(a["duration_seconds"] for a in assets) / 60,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("datasets/spoken-squad-benchmark")
    )
    parser.add_argument("--prepare-cap-mb", type=int, default=500)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.root)
    else:
        prepare(args.root, args.prepare_cap_mb * 1_000_000)
