"""Exact hybrid retrieval, aligned rank fusion, and asset grouping."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from search_anything.embeddings import DIMENSIONS, MODEL_ID, MODEL_REVISION
from search_anything.models import (
    Asset,
    Embedding,
    ProcessingGeneration,
    Representation,
    Segment,
)

FUSION_CONSTANT = 60
DEFAULT_WEIGHTS = {
    "text": 1.0,
    "transcript": 1.0,
    "ocr": 1.0,
    "image": 1.0,
    "audio": 1.0,
    "video": 1.0,
    "lexical": 1.0,
    "identifier": 1.0,
    "filename": 1.0,
}


@dataclass
class Candidate:
    asset_id: UUID
    filename: str
    content_type: str
    representation_id: UUID
    generation_id: UUID
    kind: str
    text: str | None
    location: dict[str, Any]
    source_start: int | None
    source_end: int | None
    time_start: float | None
    time_end: float | None
    similarity: float | None = None
    score: float = 0.0
    channels: dict[str, float] = field(default_factory=dict)
    channel_evidence: dict[str, Candidate] = field(default_factory=dict)
    aligned_members: list[Candidate] = field(default_factory=list)

    @property
    def alignment_scope(self) -> tuple[Any, ...] | None:
        base = (self.asset_id, self.generation_id)
        if self.time_start is not None and self.time_end is not None:
            return (*base, "time")
        if self.location.get("page") is not None:
            return (*base, "page", self.location["page"])
        if self.source_start is not None and self.source_end is not None:
            # Offsets can restart within pages or structural sections.
            return (
                *base,
                "source",
                self.location.get("table_id", self.location.get("table")),
                self.location.get("section"),
                self.location.get("heading"),
            )
        if self.kind == "image" or (
            self.kind == "ocr"
            and self.location.get("width") is not None
            and self.location.get("height") is not None
        ):
            return (*base, "static_image")
        return None


def reciprocal_rank_fusion(
    channels: dict[str, Sequence[Candidate]], weights: dict[str, float] | None = None
) -> list[Candidate]:
    """Align candidates first, then contribute only the best rank per channel/span."""
    resolved = {**DEFAULT_WEIGHTS, **(weights or {})}
    channels = {
        name: candidates
        for name, candidates in channels.items()
        if resolved.get(name, 1.0) > 0 and candidates
    }
    if not channels:
        return []
    all_candidates = [candidate for items in channels.values() for candidate in items]
    parents = list(range(len(all_candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[root_right] = root_left

    indexes: dict[UUID, int] = {}
    scopes: dict[tuple[Any, ...], list[int]] = {}
    for index, candidate in enumerate(all_candidates):
        existing = indexes.get(candidate.representation_id)
        if existing is not None:
            union(index, existing)
        else:
            indexes[candidate.representation_id] = index
        scope = candidate.alignment_scope
        if scope is not None:
            for other_index in scopes.setdefault(scope, []):
                if _overlaps(candidate, all_candidates[other_index]):
                    union(index, other_index)
            scopes[scope].append(index)

    group_members: dict[int, list[Candidate]] = {}
    group_representation_ids: dict[int, set[UUID]] = {}
    for index, candidate in enumerate(all_candidates):
        root = find(index)
        seen = group_representation_ids.setdefault(root, set())
        if candidate.representation_id in seen:
            existing = next(
                item
                for item in group_members[root]
                if item.representation_id == candidate.representation_id
            )
            if existing.similarity is None and candidate.similarity is not None:
                existing.similarity = candidate.similarity
            continue
        seen.add(candidate.representation_id)
        group_members.setdefault(root, []).append(
            replace(candidate, channels={}, channel_evidence={}, aligned_members=[])
        )
    candidate_group: dict[int, int] = {}
    index = 0
    for channel_candidates in channels.values():
        for candidate in channel_candidates:
            candidate_group[index] = find(index)
            index += 1

    # Locate each channel's best-ranked representative for each aligned span.
    channel_groups: dict[str, dict[int, Candidate]] = {}
    index = 0
    for channel, candidates in channels.items():
        ranked = channel_groups.setdefault(channel, {})
        for candidate in candidates:
            root = candidate_group[index]
            ranked.setdefault(root, candidate)
            index += 1

    fused: list[Candidate] = []
    for root, members in group_members.items():
        evidence: dict[str, Candidate] = {}
        contributions: dict[str, float] = {}
        for channel, ranked in channel_groups.items():
            representative = ranked.get(root)
            if representative is None:
                continue
            rank = list(ranked).index(root) + 1
            contributions[channel] = resolved.get(channel, 1.0) / (
                FUSION_CONSTANT + rank
            )
            evidence[channel] = representative
        best = max(members, key=lambda item: (item.similarity or 0, item.text or ""))
        fused.append(
            replace(
                best,
                score=sum(contributions.values()),
                channels=contributions,
                channel_evidence=evidence,
                aligned_members=members,
            )
        )
    return sorted(
        fused,
        key=lambda hit: (-hit.score, str(hit.asset_id), str(hit.representation_id)),
    )


def group_assets(candidates: Sequence[Candidate]) -> list[dict[str, Any]]:
    """Return one outer result per asset while keeping separate matched spans."""
    by_asset: dict[UUID, list[Candidate]] = {}
    for candidate in candidates:
        by_asset.setdefault(candidate.asset_id, []).append(candidate)
    results: list[dict[str, Any]] = []
    for asset_id, spans in by_asset.items():
        spans.sort(
            key=lambda hit: (-hit.score, hit.time_start or -1, hit.source_start or -1)
        )
        best = spans[0]
        matches: list[dict[str, Any]] = []
        for span in spans:
            members = span.aligned_members or [span]
            time_starts = [
                item.time_start for item in members if item.time_start is not None
            ]
            time_ends = [item.time_end for item in members if item.time_end is not None]
            source_starts = [
                item.source_start for item in members if item.source_start is not None
            ]
            source_ends = [
                item.source_end for item in members if item.source_end is not None
            ]
            matches.append(
                {
                    "score": span.score,
                    "channels": span.channels,
                    "time_start": min(time_starts) if time_starts else None,
                    "time_end": max(time_ends) if time_ends else None,
                    "source_start": min(source_starts) if source_starts else None,
                    "source_end": max(source_ends) if source_ends else None,
                    "representations": [
                        {
                            "representation_id": str(item.representation_id),
                            "kind": item.kind,
                            "text": item.text,
                            "location": item.location,
                            "time_start": item.time_start,
                            "time_end": item.time_end,
                            "source_start": item.source_start,
                            "source_end": item.source_end,
                            "similarity": item.similarity,
                            "channels": [
                                channel
                                for channel, evidence in span.channel_evidence.items()
                                if evidence.representation_id == item.representation_id
                            ],
                        }
                        for item in members
                    ],
                    "channel_evidence": {
                        channel: {
                            "contribution": contribution,
                            "representation_id": str(
                                span.channel_evidence[channel].representation_id
                            ),
                            "kind": span.channel_evidence[channel].kind,
                            "similarity": span.channel_evidence[channel].similarity,
                        }
                        for channel, contribution in span.channels.items()
                    },
                }
            )
        results.append(
            {
                "asset_id": str(asset_id),
                "filename": best.filename,
                "content_type": best.content_type,
                "generation_id": str(best.generation_id),
                "score": best.score,
                "matches": matches,
            }
        )
    return sorted(results, key=lambda item: (-item["score"], item["filename"]))


def _overlaps(left: Candidate, right: Candidate) -> bool:
    if left.alignment_scope is None or left.alignment_scope != right.alignment_scope:
        return False
    if (
        left.time_start is not None
        and left.time_end is not None
        and right.time_start is not None
        and right.time_end is not None
    ):
        return left.time_start <= right.time_end and right.time_start <= left.time_end
    if (
        left.source_start is not None
        and left.source_end is not None
        and right.source_start is not None
        and right.source_end is not None
    ):
        if left.location.get("page") is not None and (
            left.location.get("table_id", left.location.get("table")),
            left.location.get("section"),
            left.location.get("heading"),
        ) != (
            right.location.get("table_id", right.location.get("table")),
            right.location.get("section"),
            right.location.get("heading"),
        ):
            return False
        return (
            left.source_start <= right.source_end
            and right.source_start <= left.source_end
        )
    # Page OCR and static-image OCR cover their entire source when no range exists.
    if (
        left.location.get("page") is not None
        or left.kind == "image"
        or right.kind == "image"
        or left.location.get("width") is not None
        or right.location.get("width") is not None
    ):
        return True
    return False


async def search_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    query: str,
    vector: list[float] | None,
    mode: str,
    limit: int,
    candidate_limit: int,
    content_types: list[str] | None = None,
    asset_ids: list[UUID] | None = None,
    weights: dict[str, float] | None = None,
    similarity_cutoffs: dict[str, float] | None = None,
    model_revision: str = MODEL_REVISION,
) -> list[dict[str, Any]]:
    base = (
        select(Asset, ProcessingGeneration, Representation, Segment)
        .join(
            ProcessingGeneration, ProcessingGeneration.id == Asset.active_generation_id
        )
        .join(Representation, Representation.generation_id == ProcessingGeneration.id)
        .outerjoin(Segment, Segment.id == Representation.segment_id)
        .where(
            Asset.workspace_id == workspace_id,
            Asset.state == "ready",
            ProcessingGeneration.state == "active",
        )
    )
    if content_types:
        base = base.where(Asset.content_type.in_(content_types))
    if asset_ids is not None:
        base = base.where(Asset.id.in_(asset_ids))

    channels: dict[str, list[Candidate]] = {}
    if mode in {"semantic", "hybrid"} and vector is not None:
        for kind in ("text", "transcript", "ocr", "image", "audio", "video"):
            distance = Embedding.vector.cosine_distance(vector)
            rows = (
                await session.execute(
                    base.add_columns(distance)
                    .join(Embedding, Embedding.representation_id == Representation.id)
                    .where(
                        Representation.kind == kind,
                        Embedding.model_id == MODEL_ID,
                        Embedding.model_revision == model_revision,
                        Embedding.dimensions == DIMENSIONS,
                    )
                    .order_by(distance)
                    .limit(candidate_limit)
                )
            ).all()
            cutoff = (similarity_cutoffs or {}).get(kind)
            channels[kind] = []
            for asset, generation, representation, segment, distance_value in rows:
                similarity = 1.0 - float(distance_value)
                if cutoff is None or similarity >= cutoff:
                    channels[kind].append(
                        _candidate(
                            asset,
                            generation,
                            representation,
                            segment,
                            similarity=similarity,
                        )
                    )

    if mode in {"keyword", "hybrid"} and query.strip():
        tsquery = func.websearch_to_tsquery("simple", query.strip())
        body_vector = func.setweight(
            func.to_tsvector(
                literal_column("'simple'"),
                func.coalesce(Representation.text_content, ""),
            ),
            literal_column("'B'"),
        )
        heading_vector = func.setweight(
            func.to_tsvector(
                literal_column("'simple'"),
                func.coalesce(
                    literal_column("representations.metadata->>'heading'"), ""
                ),
            ),
            literal_column("'A'"),
        )
        document = body_vector.op("||")(heading_vector)
        filename_vector = func.to_tsvector(
            literal_column("'simple'"), func.coalesce(Asset.filename, "")
        )
        rank = func.ts_rank_cd(document, tsquery) + 2.0 * func.ts_rank_cd(
            filename_vector, tsquery
        )
        rows = (
            await session.execute(
                base.where(
                    document.op("@@")(tsquery) | filename_vector.op("@@")(tsquery)
                )
                .order_by(rank.desc(), Asset.id, Segment.ordinal, Representation.id)
                .limit(candidate_limit)
            )
        ).all()
        channels["lexical"] = [_candidate(*row) for row in rows]
        normalized = " ".join(query.split()).casefold()
        filename_rows = (
            await session.execute(
                base.where(
                    func.lower(Asset.filename).contains(normalized, autoescape=True)
                )
                .distinct(Asset.id)
                .order_by(
                    Asset.id,
                    case((Representation.text_content.is_not(None), 0), else_=1),
                    Segment.ordinal,
                    Representation.id,
                )
                .limit(candidate_limit)
            )
        ).all()
        channels["filename"] = [_candidate(*row) for row in filename_rows]
        exact_rows = (
            await session.execute(
                base.where(
                    func.lower(Representation.text_content).contains(
                        normalized, autoescape=True
                    )
                )
                .order_by(Asset.filename, Asset.id, Segment.ordinal, Representation.id)
                .limit(candidate_limit)
            )
        ).all()
        channels["identifier"] = [_candidate(*row) for row in exact_rows]

    fused = reciprocal_rank_fusion(channels, weights)
    return group_assets(fused)[:limit]


def _candidate(
    asset: Asset,
    generation: ProcessingGeneration,
    representation: Representation,
    segment: Segment | None,
    *,
    similarity: float | None = None,
) -> Candidate:
    location = dict(representation.metadata_json)
    if segment is not None:
        location.update(segment.source_location)
    return Candidate(
        asset_id=asset.id,
        filename=asset.filename,
        content_type=asset.content_type,
        representation_id=representation.id,
        generation_id=generation.id,
        kind=representation.kind,
        text=representation.text_content,
        location=location,
        source_start=segment.source_start if segment else None,
        source_end=segment.source_end if segment else None,
        time_start=segment.time_start if segment else None,
        time_end=segment.time_end if segment else None,
        similarity=similarity,
    )
