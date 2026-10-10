"""Index and evaluate the frozen local regression collection.

The run command calls the application's retrieval function with cached query
vectors. Warm timing excludes query encoding, HTTP and model loading.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import math
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from search_anything.db import make_engine
from search_anything.embeddings import DIMENSIONS, MODEL_ID, MODEL_REVISION
from search_anything.models import Asset, ProcessingGeneration
from search_anything.retrieval import search_workspace
from search_anything.settings import Settings
from search_anything.storage import S3ObjectStorage

from prepare_search_benchmark import digest, save_json, verify

LOG = logging.getLogger(__name__)


def metrics(ranked: list[str], relevant: list[str]) -> dict[str, float]:
    relevant_set = set(relevant)
    if not relevant_set:
        raise ValueError("A benchmark query must have a relevant candidate")
    ranked = list(dict.fromkeys(ranked))
    hits = [int(key in relevant_set) for key in ranked[:10]]
    dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(relevant_set))))
    return {
        "recall@5": sum(hits[:5]) / len(relevant_set),
        "recall@10": sum(hits) / len(relevant_set),
        "mrr@10": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
        "ndcg@10": dcg / ideal,
    }


def load_state(root: Path) -> tuple[dict, dict]:
    manifest = json.loads((root / "manifest.json").read_text())
    state_path = root / "index-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    fingerprint = digest(root / "manifest.json")
    if state and state["manifest_sha256"] != fingerprint:
        raise RuntimeError(
            "Manifest differs from indexed collection; use a new workspace/root"
        )
    return manifest, state


async def database_size(settings: Settings) -> int:
    engine = make_engine(settings)
    try:
        async with engine.connect() as connection:
            return int(
                await connection.scalar(
                    text("SELECT pg_database_size(current_database())")
                )
            )
    finally:
        await engine.dispose()


def storage_size(settings: Settings, workspace: str) -> int:
    storage = S3ObjectStorage(settings)
    pages = storage.client.get_paginator("list_objects_v2").paginate(
        Bucket=storage.bucket, Prefix=f"workspaces/{workspace}/"
    )
    return sum(item["Size"] for page in pages for item in page.get("Contents", []))


def select_pilot(assets: list[dict]) -> list[dict]:
    result = []
    for task in ("text", "image", "audio", "video"):
        group = sorted(
            [a for a in assets if a["task"] == task],
            key=lambda a: a.get("duration_seconds", a["bytes"]),
        )
        # Include median and largest input to avoid an optimistic time estimate.
        result.extend([group[len(group) // 2], group[-1]])
    return result


def volume_sizes() -> dict[str, int]:
    """Allocated blocks, including object-storage metadata overhead."""
    return {
        service: int(
            subprocess.check_output(
                ["docker", "compose", "exec", "-T", service, "du", "-sk", path],
                text=True,
            ).split()[0]
        )
        * 1024
        for service, path in (
            ("rustfs", "/data"),
            ("postgres", "/var/lib/postgresql/data"),
        )
    }


async def index(root: Path, base_url: str, pilot: bool, max_seconds: int) -> None:
    verify(root)
    manifest, state = load_state(root)
    settings = Settings()
    state_path = root / "index-state.json"
    with httpx.Client(base_url=base_url, timeout=120) as client:
        client.get("/health/ready").raise_for_status()
        if not state:
            response = client.post(
                "/api/workspaces", json={"name": "Search benchmark v1"}
            )
            response.raise_for_status()
            state = dict(
                workspace_id=response.json()["id"],
                manifest_sha256=digest(root / "manifest.json"),
                assets={},
                db_bytes_before=await database_size(settings),
                runs=[],
                volume_bytes_before=volume_sizes(),
            )
            save_json(state_path, state)
        workspace = state["workspace_id"]
        params = {"workspace_id": workspace}
        selected = select_pilot(manifest["assets"]) if pilot else manifest["assets"]
        if not pilot:
            report_path = root / "pilot-report.json"
            if not report_path.exists():
                raise RuntimeError("Run index --pilot before full indexing")
            report = json.loads(report_path.read_text())
            if report["projected_seconds_with_headroom"] > max_seconds:
                raise RuntimeError(
                    "Pilot projects indexing beyond budget; reduce the subset first"
                )
        started = time.monotonic()
        prior_seconds = sum(r["seconds"] for r in state["runs"])
        remaining_seconds = max_seconds - prior_seconds
        warmup_seconds = 0.0
        if pilot and not state["assets"]:
            await query_vector("benchmark model warmup", settings)
            warmup_seconds = time.monotonic() - started
        completed = []
        current_asset_id = None
        try:
            for position, asset in enumerate(selected):
                record = state["assets"].get(asset["id"])
                if record:
                    response = client.get(
                        f"/api/assets/{record['asset_id']}/status", params=params
                    )
                    response.raise_for_status()
                    if response.json()["state"] == "ready":
                        completed.append(asset["id"])
                        continue
                    if response.json()["state"] == "failed":
                        client.post(
                            f"/api/assets/{record['asset_id']}/retry",
                            params=params,
                            json={},
                        ).raise_for_status()
                    elif response.json()["state"] == "cancelled":
                        client.post(
                            f"/api/assets/{record['asset_id']}/reprocess",
                            params=params,
                            json={"profile_name": "automatic"},
                        ).raise_for_status()
                if time.monotonic() - started >= remaining_seconds:
                    raise TimeoutError("Indexing time budget exhausted")
                item_started = time.monotonic()
                if not record:
                    path = root / asset["path"]
                    with path.open("rb") as handle:
                        response = client.post(
                            "/api/assets",
                            params=params,
                            files={"file": (path.name, handle, asset["content_type"])},
                        )
                    response.raise_for_status()
                    record = dict(
                        asset_id=response.json()["asset"]["id"], status="uploaded"
                    )
                    state["assets"][asset["id"]] = record
                    save_json(state_path, state)
                current_asset_id = record["asset_id"]
                while True:
                    response = client.get(
                        f"/api/assets/{current_asset_id}/status", params=params
                    )
                    response.raise_for_status()
                    status = response.json()
                    if status["state"] == "ready":
                        break
                    if status["state"] in {"failed", "cancelled"}:
                        raise RuntimeError(
                            f"Indexing failed for {asset['id']}: {status}"
                        )
                    if time.monotonic() - started >= remaining_seconds:
                        raise TimeoutError("Indexing time budget exhausted")
                    await asyncio.sleep(0.25)
                elapsed = time.monotonic() - item_started
                record.update(status="ready", index_seconds=elapsed)
                completed.append(asset["id"])
                save_json(state_path, state)
                current_asset_id = None
                if pilot or position % 25 == 0:
                    LOG.info(
                        "Indexed %s in %.2fs; %d/%d",
                        asset["id"],
                        elapsed,
                        position + 1,
                        len(selected),
                    )
                if position % 25 == 0:
                    root_bytes = sum(
                        p.stat().st_size for p in root.rglob("*") if p.is_file()
                    )
                    stored = storage_size(settings, workspace)
                    db_growth = max(
                        0, await database_size(settings) - state["db_bytes_before"]
                    )
                    if root_bytes + stored + db_growth > 5_000_000_000:
                        raise RuntimeError(
                            "Benchmark incremental storage budget exceeded"
                        )
                    growth = sum(
                        max(0, value - state["volume_bytes_before"][key])
                        for key, value in volume_sizes().items()
                    )
                    if root_bytes + growth > 5_000_000_000:
                        raise RuntimeError("Benchmark physical disk budget exceeded")
        except BaseException as error:
            state["runs"].append(
                dict(
                    pilot=pilot,
                    seconds=time.monotonic() - started,
                    completed=len(completed),
                    status="interrupted",
                )
            )
            save_json(state_path, state)
            if current_asset_id and isinstance(
                error, (TimeoutError, KeyboardInterrupt)
            ):
                try:
                    client.post(
                        f"/api/assets/{current_asset_id}/cancel", params=params, json={}
                    ).raise_for_status()
                except httpx.HTTPError:
                    LOG.exception("Could not cancel the interrupted indexing job")
            raise
        elapsed = time.monotonic() - started
        state["runs"].append(
            dict(pilot=pilot, seconds=elapsed, completed=len(completed))
        )
        save_json(state_path, state)
        if pilot:
            counts = Counter(a["task"] for a in manifest["assets"])
            task_times = defaultdict(list)
            for asset in selected:
                task_times[asset["task"]].append(
                    state["assets"][asset["id"]]["index_seconds"]
                )
            means = {
                task: statistics.mean(values) for task, values in task_times.items()
            }
            projection = warmup_seconds + sum(
                means[task] * counts[task] for task in counts
            )
            save_json(
                root / "pilot-report.json",
                dict(
                    seconds=elapsed,
                    seconds_per_asset=means,
                    counts=dict(counts),
                    projected_seconds=projection,
                    projected_seconds_with_headroom=projection * 1.25,
                    includes_model_cold_start=True,
                    model_warmup_seconds=warmup_seconds,
                ),
            )
            LOG.info(
                "Projected full indexing %.1f minutes, %.1f with headroom",
                projection / 60,
                projection * 1.25 / 60,
            )
        else:
            root_bytes = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
            stored = storage_size(settings, workspace)
            db_growth = max(0, await database_size(settings) - state["db_bytes_before"])
            volume_after = volume_sizes()
            physical_growth = sum(
                max(0, value - state["volume_bytes_before"][key])
                for key, value in volume_after.items()
            )
            save_json(
                root / "index-report.json",
                dict(
                    workspace_id=workspace,
                    assets=len(state["assets"]),
                    final_run_seconds=elapsed,
                    initial_index_seconds=sum(r["seconds"] for r in state["runs"]),
                    prepared_bytes=root_bytes,
                    object_payload_bytes=stored,
                    database_growth_bytes=db_growth,
                    total_measured_bytes=root_bytes + stored + db_growth,
                    total_physical_bytes=root_bytes + physical_growth,
                    volume_bytes_before=state["volume_bytes_before"],
                    volume_bytes_after=volume_after,
                    storage_note="Includes local files, object payloads and whole-database growth; excludes storage-engine overhead and existing model cache",
                ),
            )
            LOG.info(
                "Indexed collection in %.1f minutes including pilot",
                sum(r["seconds"] for r in state["runs"]) / 60,
            )


async def query_vector(query: str, settings: Settings) -> list[float]:
    reader, writer = await asyncio.open_unix_connection(str(settings.model_socket_path))
    try:
        writer.write(json.dumps(dict(kind="text", text=query)).encode() + b"\n")
        await writer.drain()
        result = json.loads(await asyncio.wait_for(reader.readline(), timeout=180))
        if "error" in result:
            raise RuntimeError(str(result))
        return result["vector"]
    finally:
        writer.close()
        await writer.wait_closed()


async def run(root: Path, output: Path, split: str, config_path: Path | None) -> None:
    from search_anything.api import SearchRequest

    manifest, state = load_state(root)
    if not state:
        raise RuntimeError("Index the collection first")
    settings = Settings()
    config = json.loads(config_path.read_text()) if config_path else {}
    allowed = {
        "mode",
        "candidate_limit",
        "weights",
        "similarity_cutoffs",
        "representation_mode",
    }
    if set(config) - allowed:
        raise ValueError(f"Unsupported options: {set(config) - allowed}")
    options = dict(mode="hybrid", candidate_limit=60, representation_mode="separate")
    options.update(config)
    options = SearchRequest(query="benchmark", **options).model_dump(include=allowed)
    queries = [q for q in manifest["queries"] if split == "all" or q["split"] == split]
    cache_path = root / "query-vectors.json"
    identity = dict(
        model=MODEL_ID,
        revision=MODEL_REVISION,
        dimensions=DIMENSIONS,
        context_tokens=settings.embedding_context_tokens,
        model_path=str(settings.embedding_model_path),
        manifest=digest(root / "manifest.json"),
    )
    cache = (
        json.loads(cache_path.read_text())
        if cache_path.exists()
        else dict(identity=identity, vectors={})
    )
    if cache["identity"] != identity:
        cache = dict(identity=identity, vectors={})
    encoding_started = time.monotonic()
    for i, query in enumerate(queries):
        if options["mode"] != "keyword" and query["id"] not in cache["vectors"]:
            cache["vectors"][query["id"]] = await query_vector(query["text"], settings)
            save_json(cache_path, cache)
        if i % 25 == 0:
            LOG.info("Query vectors %d/%d", i + 1, len(queries))
    encoding_seconds = time.monotonic() - encoding_started
    reverse = {r["asset_id"]: key for key, r in state["assets"].items()}
    workspace = UUID(state["workspace_id"])
    engine = make_engine(settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    rows = []
    started = time.monotonic()
    try:
        async with sessions() as session:
            ready = set(
                str(i)
                for i in (
                    await session.scalars(
                        select(Asset.id).where(
                            Asset.workspace_id == workspace, Asset.state == "ready"
                        )
                    )
                ).all()
            )
            expected = set(reverse)
            if ready != expected or len(expected) != len(manifest["assets"]):
                raise RuntimeError("Workspace is incomplete or has unexpected assets")
            generations = (
                await session.execute(
                    select(
                        Asset.id,
                        Asset.active_generation_id,
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
            index_identity = hashlib.sha256(
                json.dumps(
                    [[str(a), str(g), profile] for a, g, profile in generations],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            for query in queries:
                before = time.monotonic()
                hits = await search_workspace(
                    session,
                    workspace,
                    query=query["text"],
                    vector=(
                        cache["vectors"].get(query["id"])
                        if options["mode"] != "keyword"
                        else None
                    ),
                    limit=10,
                    content_types=[
                        next(
                            a["content_type"]
                            for a in manifest["assets"]
                            if a["task"] == query["task"]
                        )
                    ],
                    **options,
                )
                latency = time.monotonic() - before
                ranked = [reverse[str(hit["asset_id"])] for hit in hits]
                rows.append(
                    dict(
                        id=query["id"],
                        task=query["task"],
                        split=query["split"],
                        query=query["text"],
                        relevant=query["relevant"],
                        ranked=ranked,
                        seconds=latency,
                        **metrics(ranked, query["relevant"]),
                    )
                )
    finally:
        await engine.dispose()
    elapsed = time.monotonic() - started
    summary = {}
    for task in sorted({r["task"] for r in rows}):
        group = [r for r in rows if r["task"] == task]
        summary[task] = {
            key: statistics.mean(r[key] for r in group)
            for key in ("recall@5", "recall@10", "mrr@10", "ndcg@10", "seconds")
        }
        summary[task]["queries"] = len(group)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_json(
        output,
        dict(
            created_at=datetime.now(timezone.utc).isoformat(),
            manifest_sha256=digest(root / "manifest.json"),
            index_identity=index_identity,
            embedding_identity=identity,
            retrieval_source_sha256=digest(Path(inspect.getfile(search_workspace))),
            config=options,
            split=split,
            encoding_seconds=encoding_seconds,
            retrieval_seconds=elapsed,
            summary=summary,
            queries=rows,
        ),
    )
    LOG.info(
        "Saved %s: encoding %.2fs, retrieval %.2fs", output, encoding_seconds, elapsed
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("datasets/search-benchmark"))
    commands = parser.add_subparsers(dest="command", required=True)
    indexing = commands.add_parser("index")
    indexing.add_argument("--pilot", action="store_true")
    indexing.add_argument("--base-url", default="http://127.0.0.1:8000")
    indexing.add_argument("--max-seconds", type=int, default=2700)
    running = commands.add_parser("run")
    running.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    running.add_argument("--config", type=Path)
    running.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "index":
        asyncio.run(index(args.root, args.base_url, args.pilot, args.max_seconds))
    else:
        asyncio.run(run(args.root, args.output, args.split, args.config))
