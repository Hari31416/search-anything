"""Prepare hard image matching and natural spoken-content retrieval tasks.

uv run --with pyarrow==19.0.1 python scripts/prepare_expanded_benchmark.py
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from prepare_search_benchmark import Budget, SEED, digest, download, save_json, verify

LOG = logging.getLogger(__name__)
COLA = "daee86b15a60308cfcc277ea11ab7f6be60fdfbc"
SLUE = "e2989c55a53593a8e39b8f8ebdb47ccaccbe484a"
HF = "https://huggingface.co/datasets"
SOURCE_URLS = {
    "cola.parquet": f"{HF}/array/cola/resolve/{COLA}/data/multiobjects.parquet",
    **{
        f"slue-{i}.parquet": (
            f"{HF}/asapp/slue-phase-2/resolve/{SLUE}/"
            f"sqa5/verified_test-{i:05d}-of-00003.parquet"
        )
        for i in range(3)
    },
}


def select_image_pairs(rows: list[dict], count: int = 50) -> list[dict]:
    rows = sorted(rows, key=lambda r: (r["image1"], r["image2"], r["caption1"]))
    random.Random(SEED).shuffle(rows)
    selected, used = [], set()
    for row in rows:
        keys = {row["image1"], row["image2"]}
        if len(keys) != 2 or used & keys:
            continue
        selected.append(row)
        used.update(keys)
        if len(selected) == count:
            return selected
    raise ValueError("Not enough disjoint image pairs")


def crop_bounds(
    spans: dict, duration: float, seconds: float = 30
) -> tuple[float, float]:
    starts, ends = spans["start_second"], spans["end_second"]
    if not starts or len(starts) != len(ends):
        raise ValueError("Missing answer alignment")
    if any(s < 0 or e <= s or e > duration + 0.01 for s, e in zip(starts, ends)):
        raise ValueError("Invalid answer alignment")
    length = min(seconds, duration)
    lower, upper = max(0.0, max(ends) - length), min(min(starts), duration - length)
    if lower > upper:
        raise ValueError("All labeled answers cannot fit in one bounded passage")
    start = min(max(min(starts) - 10.0, lower), upper)
    return start, start + length


def article(row: dict) -> str:
    return row["document_id"].rsplit("_", 1)[0]


def select_speech(rows: list[dict], durations: dict[str, float]) -> list[dict]:
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["question_id"]):
        try:
            start, end = crop_bounds(row["answer_spans"], durations[row["document_id"]])
        except ValueError:
            continue
        groups[row["question_id"].split("-")[0]].append(
            dict(row, clip_start=start, clip_end=end)
        )
    rng = random.Random(SEED)
    for group in groups.values():
        rng.shuffle(group)
    selected, used = [], set()
    while len(selected) < 50:
        progress = False
        for family in sorted(groups):
            while groups[family]:
                row = groups[family].pop()
                if article(row) in used:
                    continue
                selected.append(row)
                used.add(article(row))
                progress = True
                break
            if len(selected) == 50:
                break
        if not progress:
            raise ValueError("Need 50 eligible questions from distinct source articles")
    family_counts = defaultdict(int)
    for row in selected:
        family = row["question_id"].split("-")[0]
        row["split"] = "dev" if family_counts[family] % 5 < 3 else "test"
        family_counts[family] += 1
    return selected


def prepare(root: Path, cap: int) -> None:
    import pyarrow.parquet as parquet
    import soundfile as sf
    from PIL import Image

    if (root / "manifest.json").exists():
        raise RuntimeError("Manifest already frozen. Use --verify or a new --root.")
    source, media = root / "source", root / "media"
    source.mkdir(parents=True, exist_ok=True)
    media.mkdir(exist_ok=True)
    budget = Budget(root, cap)
    for name, url in SOURCE_URLS.items():
        download(url, source / name, budget)
    assets, queries, downloads = [], [], []

    def asset(task: str, key: str, suffix: str, **metadata) -> tuple[dict, Path]:
        identifier = f"{task}:{key}"
        name = hashlib.sha256(identifier.encode()).hexdigest()[:24] + suffix
        entry = dict(
            id=identifier,
            source_id=key,
            task=task,
            path=f"media/{name}",
            content_type="image/jpeg" if task == "image_hard" else "audio/wav",
            **metadata,
        )
        assets.append(entry)
        return entry, media / name

    pairs = select_image_pairs(parquet.read_table(source / "cola.parquet").to_pylist())
    for i, pair in enumerate(pairs):
        entries = []
        for side in (1, 2):
            key = pair[f"image{side}"]
            url = f"{HF}/array/cola/resolve/{COLA}/{key}"
            entry, path = asset("image_hard", key, ".jpg", source_url=url)
            entries.append(entry)
            downloads.append((url, path))
        # 25 labeled pairs give 50 queries; 25 more pairs supply distractors.
        # Keep each pair wholly within one query split.
        if i < 25:
            for side in (1, 2):
                queries.append(
                    dict(
                        id=f"cola:{i}:{side}",
                        text=pair[f"caption{side}"],
                        relevant=[entries[side - 1]["id"]],
                        task="image_hard",
                        split="dev" if i < 15 else "test",
                        pair_id=f"cola:{i}",
                        hard_negative=entries[2 - side]["id"],
                    )
                )
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: download(*pair, budget), downloads))

    rows, documents, durations = [], {}, {}
    for name in sorted(SOURCE_URLS):
        if not name.startswith("slue-"):
            continue
        # Drop question audio and reference transcripts from working rows.
        # Document bytes are deduplicated by source document ID.
        for row in parquet.read_table(
            source / name,
            columns=[
                "question_id",
                "raw_question_text",
                "document_id",
                "document_audio",
                "document_speaker_id",
                "answer_spans",
            ],
        ).to_pylist():
            body = row.pop("document_audio")["bytes"]
            key = row["document_id"]
            if key not in documents:
                info = sf.info(io.BytesIO(body))
                if info.samplerate != 16000 or info.channels != 1:
                    raise ValueError("Unexpected source audio format")
                documents[key] = body
                durations[key] = info.duration
            rows.append(dict(row, source_file=name))
    selected = select_speech(rows, durations)
    targets = {r["document_id"]: r for r in selected}
    positive_articles = {article(r) for r in selected}
    distractors = sorted({r["document_id"] for r in rows} - targets.keys())
    random.Random(SEED).shuffle(distractors)
    # Prefer unrelated source articles to reduce unlabeled alternative answers.
    distractors.sort(key=lambda key: key.rsplit("_", 1)[0] in positive_articles)
    by_document = {r["document_id"]: r for r in rows}
    for key in distractors[:50]:
        targets[key] = dict(
            by_document[key], clip_start=0, clip_end=min(30, durations[key])
        )
    if len(targets) != 100:
        raise ValueError("Need 100 distinct speech documents")
    for key, row in sorted(targets.items()):
        start, end = row["clip_start"], row["clip_end"]
        entry, path = asset(
            "natural_speech",
            key,
            ".wav",
            source_url=SOURCE_URLS[row["source_file"]],
            source_start=start,
            source_end=end,
            source_article=article(row),
            speaker_id=row["document_speaker_id"],
        )
        if not path.exists():
            data, rate = sf.read(
                io.BytesIO(documents[key]),
                start=round(start * 16000),
                stop=round(end * 16000),
            )
            budget.consume(len(data) * 2 + 128)
            sf.write(path, data, rate, subtype="PCM_16")
        entry["duration_seconds"] = sf.info(path).duration
    for i, row in enumerate(selected):
        start = row["clip_start"]
        queries.append(
            dict(
                id=f"slue:{row['question_id']}",
                text=row["raw_question_text"],
                relevant=[f"natural_speech:{row['document_id']}"],
                task="natural_speech",
                split=row["split"],
                source_article=article(row),
                answer_spans=[
                    dict(start=s - start, end=e - start)
                    for s, e in zip(
                        row["answer_spans"]["start_second"],
                        row["answer_spans"]["end_second"],
                    )
                ],
            )
        )
    for entry in assets:
        path = root / entry["path"]
        entry.update(bytes=path.stat().st_size, sha256=digest(path))
        if entry["task"] == "image_hard":
            with Image.open(path) as image:
                image.verify()
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
        ("image-only", "semantic", ("image",)),
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
        version=2,
        name="search-anything-expanded-v2",
        seed=SEED,
        sources={"array/cola": COLA, "asapp/slue-phase-2": SLUE},
        source_files={
            name: dict(url=url, sha256=digest(source / name))
            for name, url in SOURCE_URLS.items()
        },
        assets=assets,
        queries=queries,
        limitations=[
            "Subset scores are not official COLA, SLUE, MMEB or MTEB scores",
            "COLA labels are exhaustive within each paired contrast, not the whole pool",
            "COLA tests attribute/object composition, not dedicated OCR retrieval",
            "SLUE clips use answer-aligned crops of up to 30 seconds",
            "SLUE is natural read Wikipedia speech, not meetings or noisy conversations",
            "SLUE queries use distinct source articles; speakers may overlap splits",
            "Reference captions, transcripts and answers are never indexed",
        ],
    )
    save_json(root / "selection.json", dict(assets=assets, queries=queries))
    save_json(root / "manifest.json", manifest)
    verify_expansion(root)
    LOG.info(
        "Natural speech: %d speakers, %.1f minutes",
        len({a["speaker_id"] for a in assets if a["task"] == "natural_speech"}),
        sum(a.get("duration_seconds", 0) for a in assets) / 60,
    )


def verify_expansion(root: Path) -> None:
    verify(root)
    manifest = json.loads((root / "manifest.json").read_text())
    assets = {a["id"]: a for a in manifest["assets"]}
    assert len({a["sha256"] for a in assets.values()}) == len(assets), "Duplicate media"
    splits = defaultdict(set)
    for query in manifest["queries"]:
        if query["task"] == "image_hard":
            assert query["hard_negative"] in assets
            assert query["hard_negative"] not in query["relevant"]
            splits[query["pair_id"]].add(query["split"])
        else:
            splits[query["source_article"]].add(query["split"])
            duration = assets[query["relevant"][0]]["duration_seconds"]
            assert query["answer_spans"]
            assert all(
                0 <= span["start"] < span["end"] <= duration + 0.0001
                for span in query["answer_spans"]
            ), query["id"]
    assert all(
        len(values) == 1 for values in splits.values()
    ), "Source group crosses splits"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("datasets/expanded-benchmark")
    )
    parser.add_argument("--prepare-cap-mb", type=int, default=1400)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_expansion(args.root)
    else:
        prepare(args.root, args.prepare_cap_mb * 1_000_000)
