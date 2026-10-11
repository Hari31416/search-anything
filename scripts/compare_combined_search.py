#!/usr/bin/env python3
"""Compare separate, combined, and mixed retrieval against the local API."""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg

from search_anything.embeddings import DIMENSIONS, MODEL_ID, MODEL_REVISION
from search_anything.settings import Settings


def active_index_stats(settings: Settings) -> dict[str, object]:
    database_url = settings.sync_database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT r.kind, count(e.id)
            FROM assets AS a
            JOIN processing_generations AS g
              ON g.id = a.active_generation_id AND g.state = 'active'
            JOIN representations AS r ON r.generation_id = g.id
            LEFT JOIN embeddings AS e
              ON e.representation_id = r.id
             AND e.model_id = %s
             AND e.model_revision = %s
             AND e.dimensions = %s
            WHERE a.workspace_id = %s AND a.state = 'ready'
            GROUP BY r.kind
            ORDER BY r.kind
            """,
            (MODEL_ID, MODEL_REVISION, DIMENSIONS, settings.default_workspace_id),
        ).fetchall()
        profile_rows = connection.execute(
            """
            SELECT coalesce((g.profile_snapshot->>'combined_media_text')::boolean, false),
                   count(*),
                   avg((g.extractor_versions->>'index_duration_seconds')::double precision)
            FROM assets AS a
            JOIN processing_generations AS g ON g.id = a.active_generation_id
            WHERE a.workspace_id = %s AND a.state = 'ready' AND g.state = 'active'
            GROUP BY 1
            ORDER BY 1
            """,
            (settings.default_workspace_id,),
        ).fetchall()
    return {
        "vectors_by_kind": {kind: count for kind, count in rows},
        "active_generation_indexing": [
            {
                "combined_profile_enabled": bool(combined_enabled),
                "generation_count": generation_count,
                "mean_index_duration_seconds": (
                    round(mean_duration, 3) if mean_duration is not None else None
                ),
            }
            for combined_enabled, generation_count, mean_duration in profile_rows
        ],
    }


def search(
    base_url: str, payload: dict[str, object]
) -> tuple[dict[str, object], float]:
    request = Request(
        f"{base_url.rstrip('/')}/api/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=180) as response:
            submitted = json.loads(response.read())
            if response.status == 200:
                return submitted, time.perf_counter() - started
        deadline = time.monotonic() + 600
        while True:
            with urlopen(
                f"{base_url.rstrip('/')}/api/search/jobs/{submitted['id']}", timeout=30
            ) as response:
                job = json.loads(response.read())
            if job["status"] == "succeeded":
                result = job["result"]
                break
            if job["status"] == "failed":
                raise RuntimeError(job["error"]["message"])
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Search {submitted['id']} is still pending")
            time.sleep(0.5)
    except HTTPError as error:
        raise RuntimeError(
            f"search returned HTTP {error.code}: {error.read()!r}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"could not reach the local API: {error}") from error
    return result, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="text query to run against all three modes")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--candidate-limit", type=int, default=60)
    args = parser.parse_args()

    settings = Settings()
    stats = active_index_stats(settings)
    counts = stats["vectors_by_kind"]
    assert isinstance(counts, dict)
    separate_kinds = {"text", "transcript", "ocr", "image", "audio", "video"}
    separate_count = sum(
        count for kind, count in counts.items() if kind in separate_kinds
    )
    combined_count = counts.get("combined", 0)
    report: dict[str, object] = {
        "query": args.query,
        "representations": {
            "separate_vectors": separate_count,
            "combined_vectors": combined_count,
            "separate_estimated_vector_bytes": separate_count * DIMENSIONS * 4,
            "combined_estimated_vector_bytes": combined_count * DIMENSIONS * 4,
            "estimated_bytes_note": "float32 vector payload only; excludes PostgreSQL row and index overhead",
        },
        "active_generation_indexing": stats["active_generation_indexing"],
        "modes": {},
    }
    results = report["modes"]
    assert isinstance(results, dict)
    for mode in ("separate", "combined", "both"):
        response, elapsed = search(
            args.base_url,
            {
                "query": args.query,
                "mode": "hybrid",
                "limit": args.limit,
                "candidate_limit": args.candidate_limit,
                "representation_mode": mode,
            },
        )
        hits = response.get("results", [])
        results[mode] = {
            "latency_seconds": round(elapsed, 4),
            "asset_hit_count": len(hits),
            "top_hits": [
                {
                    "asset_id": hit.get("asset_id"),
                    "filename": hit.get("filename"),
                    "score": hit.get("score"),
                    "matches": [
                        {
                            "score": match.get("score"),
                            "channel_evidence": match.get("channel_evidence"),
                        }
                        for match in hit.get("matches", [])
                    ],
                }
                for hit in hits[: args.limit]
            ],
        }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
