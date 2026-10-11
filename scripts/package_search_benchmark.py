"""Package the frozen evaluation collections for Hugging Face, without caches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import shutil
from collections import Counter
from pathlib import Path

LOG = logging.getLogger(__name__)
COLLECTIONS = (
    "search-benchmark",
    "spoken-squad-benchmark",
    "expanded-benchmark",
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def package(source: Path, output: Path) -> None:
    if output.exists():
        raise ValueError(
            f"Output already exists: {output}. Use a new output directory."
        )
    corpus, queries, hashes = [], [], {}
    for name in COLLECTIONS:
        root = source / name
        manifest = json.loads((root / "manifest.json").read_text())
        for asset in manifest["assets"]:
            relative = Path(asset["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe asset path: {relative}")
            path = root / relative
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if digest != asset["sha256"] or path.stat().st_size != asset["bytes"]:
                raise ValueError(f"Asset checksum or size mismatch: {path}")
            target = output / name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            hashes[target.relative_to(output).as_posix()] = digest
            corpus.append(
                dict(
                    id=asset["id"],
                    collection=name,
                    task=asset["task"],
                    source_id=asset["source_id"],
                    path=target.relative_to(output).as_posix(),
                    content_type=asset["content_type"],
                    bytes=asset["bytes"],
                    sha256=digest,
                    source_url=asset.get("source_url"),
                    duration_seconds=asset.get("duration_seconds"),
                )
            )
        for query in manifest["queries"]:
            queries.append(
                dict(
                    id=query["id"],
                    collection=name,
                    task=query["task"],
                    text=query["text"],
                    split=query["split"],
                    relevant=query["relevant"],
                    pair_id=query.get("pair_id"),
                    hard_negative=query.get("hard_negative"),
                )
            )
        # Original manifests preserve crop offsets, source revisions and runner compatibility.
        shutil.copyfile(root / "manifest.json", output / name / "manifest.json")

    by_id = {row["id"]: row for row in corpus}
    if len(by_id) != len(corpus) or len({q["id"] for q in queries}) != len(queries):
        raise ValueError("Duplicate asset or query IDs")
    positive_splits: dict[str, set[str]] = {}
    for query in queries:
        if query["split"] not in {"dev", "test"} or not query["relevant"]:
            raise ValueError(f"Invalid query: {query['id']}")
        for identifier in query["relevant"] + (
            [query["hard_negative"]] if query["hard_negative"] else []
        ):
            candidate = by_id[identifier]
            if (candidate["task"], candidate["collection"]) != (
                query["task"],
                query["collection"],
            ):
                raise ValueError(f"Cross-task relevance: {query['id']}")
        for identifier in query["relevant"]:
            positive_splits.setdefault(identifier, set()).add(query["split"])
    if any(len(splits) > 1 for splits in positive_splits.values()):
        raise ValueError("Relevant assets cross query splits")
    if (len(corpus), len(queries)) != (1150, 350):
        raise ValueError("Unexpected benchmark size")
    write_jsonl(output / "data/corpus.jsonl", corpus)
    for split in ("dev", "test"):
        write_jsonl(
            output / f"data/queries-{split}.jsonl",
            [query for query in queries if query["split"] == split],
        )
    shutil.copyfile(
        Path(__file__).parents[1] / "docs/hf-dataset-card.md", output / "README.md"
    )
    notices = source / "hf-source-notices"
    shutil.copytree(notices, output / "source-notices")
    with (notices / "clotho-metadata-evaluation.csv").open(newline="") as handle:
        metadata = {row["file_name"]: row for row in csv.DictReader(handle)}
    write_jsonl(
        output / "source-notices/clotho-selected-attributions.jsonl",
        [
            dict(id=row["id"], path=row["path"], **metadata[row["source_id"]])
            for row in corpus
            if row["task"] == "audio"
        ],
    )
    report = {
        "assets": len(corpus),
        "queries": len(queries),
        "query_splits": dict(Counter(q["split"] for q in queries)),
        "asset_tasks": dict(Counter(row["task"] for row in corpus)),
        "media_bytes": sum(row["bytes"] for row in corpus),
    }
    (output / "package-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.relative_to(output).as_posix() not in hashes:
            hashes[path.relative_to(output).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
    )
    LOG.info("Verified and packaged %s", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("datasets"))
    parser.add_argument(
        "--output", type=Path, default=Path("datasets/hf-search-anything-benchmark")
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    package(args.source, args.output)
