"""Build a fixed four-dataset local regression benchmark.

Run with uv run --with pyarrow==19.0.1 python scripts/prepare_search_benchmark.py.
Only preparation requires PyArrow. Media captions never enter indexed files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import random
import re
import shutil
import subprocess
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

LOG = logging.getLogger(__name__)
SEED = 20261010
MMEB = "4a5560b2b64384204b6fea8a82ea986eba51f5aa"
SCIFACT = "309f1d1ae3ae2e092444a8a0c25bed59b82318bc"
MSRVTT = "947b139d0c591235a3f311e45a31a88461bad0d2"
HF = "https://huggingface.co/datasets"
SOURCE_URLS = {
    "coco.parquet": f"{HF}/VLM2Vec/MMEB-V3/resolve/{MMEB}/image-query/MSCOCO_t2i/test-00000-of-00001.parquet",
    "clotho.csv": "https://zenodo.org/records/4783391/files/clotho_captions_evaluation.csv?download=1",
    "msrvtt.json": f"{HF}/VLM2Vec/MSR-VTT/resolve/{MSRVTT}/msrvtt_test_1k.json",
    **{
        f"scifact-{kind}.parquet": f"{HF}/zeta-alpha-ai/NanoSciFact/resolve/{SCIFACT}/{kind}/train-00000-of-00001.parquet"
        for kind in ("corpus", "queries", "qrels")
    },
}
TYPES = {
    "text": "text/plain",
    "image": "image/jpeg",
    "audio": "audio/wav",
    "video": "video/mp4",
}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class Budget:
    """Bound retained preparation files, including in-flight downloads."""

    def __init__(self, root: Path, cap: int):
        self.remaining = cap - sum(
            p.stat().st_size for p in root.rglob("*") if p.is_file()
        )
        self.lock = threading.Lock()

    def consume(self, size: int) -> None:
        with self.lock:
            if size > self.remaining:
                raise RuntimeError("Preparation storage cap exceeded")
            self.remaining -= size


def download(url: str, path: Path, budget: Budget) -> None:
    if path.exists():
        return
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        for attempt in range(3):
            try:
                with (
                    urlopen(url, timeout=120) as source,
                    temporary.open("wb") as target,
                ):
                    while chunk := source.read(1024 * 1024):
                        budget.consume(len(chunk))
                        target.write(chunk)
                temporary.replace(path)
                return
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                LOG.warning("Retrying %s", url)
    finally:
        temporary.unlink(missing_ok=True)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def select_candidates(
    descriptions: dict[str, str], queries: list[dict], count: int, rng: random.Random
) -> list[str]:
    """Keep every positive, add lexical neighbors, then random distractors."""
    selected = {key for q in queries for key in q["relevant"]}
    if len(selected) > count:
        raise ValueError("Candidate target cannot hold all query positives")
    words = {key: tokens(value) for key, value in descriptions.items()}
    for query in queries:
        query_words = tokens(query["text"])
        neighbors = sorted(
            descriptions,
            key=lambda key: (
                -len(query_words & words[key]) / max(1, len(query_words | words[key])),
                key,
            ),
        )
        for key in [k for k in neighbors if k not in query["relevant"]][:2]:
            if len(selected) < count:
                selected.add(key)
    remaining = sorted(set(descriptions) - selected)
    rng.shuffle(remaining)
    selected.update(remaining[: count - len(selected)])
    return sorted(selected)


def make_query(
    identifier: str, text: str, relevant: list[str], task: str, index: int
) -> dict:
    return dict(
        id=identifier,
        text=text,
        relevant=relevant,
        task=task,
        split="test" if index % 5 >= 3 else "dev",
    )


def prepare(root: Path, cap: int) -> None:
    import pyarrow.parquet as parquet

    source, media = root / "source", root / "media"
    source.mkdir(parents=True, exist_ok=True)
    media.mkdir(exist_ok=True)
    if (root / "manifest.json").exists():
        raise RuntimeError("Manifest already frozen. Use --verify or a new --root.")
    budget = Budget(root, cap)
    for name, url in SOURCE_URLS.items():
        download(url, source / name, budget)
    rng = random.Random(SEED)
    assets, queries, downloads = [], [], []

    def asset(task: str, identifier: str, suffix: str, url: str | None = None) -> Path:
        key = f"{task}:{identifier}"
        name = hashlib.sha256(key.encode()).hexdigest()[:24] + suffix
        path = media / name
        assets.append(
            dict(
                id=key,
                source_id=identifier,
                task=task,
                path=f"media/{name}",
                content_type=TYPES[task],
                source_url=url,
            )
        )
        if url:
            downloads.append((url, path))
        return path

    # NanoSciFact has exactly 50 queries. Preserve every labeled positive.
    corpus = {
        r["_id"]: r["text"]
        for r in parquet.read_table(source / "scifact-corpus.parquet").to_pylist()
    }
    rows = parquet.read_table(source / "scifact-queries.parquet").to_pylist()
    qrels = parquet.read_table(source / "scifact-qrels.parquet").to_pylist()
    rows.sort(key=lambda r: r["_id"])
    rng.shuffle(rows)
    text_queries = [
        make_query(
            f"scifact:{r['_id']}",
            r["text"],
            [rel["corpus-id"] for rel in qrels if rel["query-id"] == r["_id"]],
            "text",
            i,
        )
        for i, r in enumerate(rows[:50])
    ]
    for key in select_candidates(corpus, text_queries, 500, rng):
        path = asset("text", key, ".txt")
        if not path.exists():
            raw = (corpus[key] + "\n").encode()
            budget.consume(len(raw))
            path.write_bytes(raw)
    for query in text_queries:
        query["relevant"] = [f"text:{key}" for key in query["relevant"]]
    queries.extend(text_queries)

    # The official image adapter labels the first candidate as positive.
    coco = parquet.read_table(source / "coco.parquet").to_pylist()
    by_image = {}
    for row in coco:
        by_image.setdefault(Path(row["tgt_img_path"][0]).name, []).append(
            row["qry_text"]
        )
    image_keys = sorted(by_image)
    rng.shuffle(image_keys)
    image_queries = [
        make_query(f"coco:{key}", by_image[key][0], [key], "image", i)
        for i, key in enumerate(image_keys[:50])
    ]
    all_images = {Path(p).name for row in coco for p in row["tgt_img_path"]}
    descriptions = {key: " ".join(by_image.get(key, [])) for key in sorted(all_images)}
    for key in select_candidates(descriptions, image_queries, 200, rng):
        asset(
            "image",
            key,
            ".jpg",
            f"https://s3.amazonaws.com/images.cocodataset.org/val2014/{key}",
        )
    for query in image_queries:
        query["relevant"] = [f"image:{key}" for key in query["relevant"]]
    queries.extend(image_queries)

    with (source / "clotho.csv").open(newline="") as handle:
        clotho = list(csv.DictReader(handle))
    clotho.sort(key=lambda r: r["file_name"])
    rng.shuffle(clotho)
    audio_queries = [
        make_query(
            f"clotho:{r['file_name']}", r["caption_1"], [r["file_name"]], "audio", i
        )
        for i, r in enumerate(clotho[:50])
    ]
    descriptions = {
        r["file_name"]: " ".join(r[f"caption_{i}"] for i in range(1, 6)) for r in clotho
    }
    audio_targets = {
        key: asset("audio", key, ".wav")
        for key in select_candidates(descriptions, audio_queries, 100, rng)
    }
    for query in audio_queries:
        query["relevant"] = [f"audio:{key}" for key in query["relevant"]]
    queries.extend(audio_queries)

    videos = json.loads((source / "msrvtt.json").read_text())
    videos.sort(key=lambda r: r["video_id"])
    rng.shuffle(videos)
    # One caption per video. Category round-robin avoids a few dominant topics.
    categories = {}
    for row in videos:
        categories.setdefault(row["category"], []).append(row)
    selected = []
    while len(selected) < 50:
        for category in sorted(categories):
            if categories[category] and len(selected) < 50:
                selected.append(categories[category].pop())
    for i, row in enumerate(selected):
        asset(
            "video",
            row["video_id"],
            ".mp4",
            f"{HF}/VLM2Vec/MSR-VTT/resolve/{MSRVTT}/raw_videos/{row['video']}",
        )
        queries.append(
            make_query(
                f"msrvtt:{row['video_id']}",
                row["caption"],
                [f"video:{row['video_id']}"],
                "video",
                i,
            )
        )

    # Write the deterministic selection before starting the larger transfers.
    save_json(root / "selection.json", dict(assets=assets, queries=queries))
    LOG.info("Selected %d candidates and %d queries", len(assets), len(queries))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: download(*pair, budget), downloads))
    missing = {key: path for key, path in audio_targets.items() if not path.exists()}
    if missing:
        url = (
            f"{HF}/VLM2Vec/MMEB-V3/resolve/{MMEB}/audio_tasks/Clotho.tar?download=true"
        )
        LOG.info(
            "Streaming Clotho archive, retaining %d evaluation clips", len(missing)
        )
        with (
            urlopen(url, timeout=180) as response,
            tarfile.open(fileobj=response, mode="r|") as archive,
        ):
            for member in archive:
                key = Path(member.name).name
                if (
                    key not in missing
                    or not member.isfile()
                    or "/evaluation/" not in member.name
                ):
                    continue
                budget.consume(member.size)
                path = missing[key]
                temporary = path.with_suffix(".part")
                body = archive.extractfile(member)
                assert body is not None
                try:
                    with temporary.open("wb") as handle:
                        shutil.copyfileobj(body, handle)
                    if temporary.stat().st_size != member.size:
                        raise RuntimeError(f"Truncated archive member {key}")
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
                del missing[key]
                if len(missing) % 10 == 0:
                    LOG.info("Clotho clips remaining: %d", len(missing))
                if not missing:
                    break
        if missing:
            raise RuntimeError(f"Missing Clotho files: {sorted(missing)}")
    for entry in assets:
        path = root / entry["path"]
        entry.update(bytes=path.stat().st_size, sha256=digest(path))
        if entry["task"] == "image":
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
        if entry["task"] in {"audio", "video"}:
            probe = json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "json",
                        str(path),
                    ]
                )
            )
            entry["duration_seconds"] = float(probe["format"]["duration"])
    manifest = dict(
        version=1,
        name="search-anything-regression-v1",
        seed=SEED,
        sources={
            "MMEB-V3": MMEB,
            "NanoSciFact": SCIFACT,
            "MSR-VTT": MSRVTT,
            "Clotho": "Zenodo 4783391, evaluation",
        },
        source_files={
            name: dict(url=url, sha256=digest(source / name))
            for name, url in SOURCE_URLS.items()
        },
        assets=assets,
        queries=queries,
        limitations=[
            "Subset scores are not official MMEB scores",
            "Caption relevance labels are incomplete",
            "Mixed-dataset search is diagnostic only",
            "Media captions excluded from indexed content",
            "No timestamp localization labels in v1",
        ],
    )
    save_json(root / "manifest.json", manifest)
    verify(root)


def verify(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    keys = {a["id"] for a in manifest["assets"]}
    assert len(keys) == len(manifest["assets"])
    for asset in manifest["assets"]:
        path = root / asset["path"]
        assert path.stat().st_size == asset["bytes"], path
        assert digest(path) == asset["sha256"], path
    for name, source in manifest.get("source_files", {}).items():
        assert digest(root / "source" / name) == source["sha256"], name
    for query in manifest["queries"]:
        assert query["relevant"] and set(query["relevant"]) <= keys, query["id"]
    dev = {
        key for q in manifest["queries"] if q["split"] == "dev" for key in q["relevant"]
    }
    test = {
        key
        for q in manifest["queries"]
        if q["split"] == "test"
        for key in q["relevant"]
    }
    assert not dev & test, "Relevant asset appears in both query splits"
    LOG.info(
        "Verified %d assets, %d queries, %.1f MB media",
        len(keys),
        len(manifest["queries"]),
        sum(a["bytes"] for a in manifest["assets"]) / 1e6,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("datasets/search-benchmark"))
    parser.add_argument("--prepare-cap-mb", type=int, default=1000)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.root)
    else:
        prepare(args.root, args.prepare_cap_mb * 1_000_000)
