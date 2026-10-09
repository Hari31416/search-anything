"""FastAPI endpoints for local uploads, status, and source previews."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator, Any
from urllib.parse import quote
from uuid import UUID, uuid4

import anyio
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from search_anything.db import make_engine
from search_anything.ingestion import IngestionOptions
from search_anything.models import (
    Asset,
    IngestionJob,
    IngestionProfile,
    ProcessingGeneration,
    Workspace,
)
from search_anything.ranges import UnsatisfiableRange, parse_range
from search_anything.retrieval import DEFAULT_WEIGHTS, search_workspace
from search_anything.settings import Settings, get_settings
from search_anything.storage import S3ObjectStorage

logger = logging.getLogger(__name__)


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    byte_size: int
    content_hash: str
    state: str
    duration_seconds: float | None
    page_count: int | None
    created_at: datetime
    active_generation_id: UUID | None


class UploadResponse(BaseModel):
    asset: AssetResponse
    generation_id: UUID
    job_id: UUID


class PresignedURLResponse(BaseModel):
    url: str
    expires_in_seconds: int


class ReadinessResponse(BaseModel):
    status: str
    database: str
    storage: str


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stage: str
    status: str
    attempts: int
    max_attempts: int
    progress: float
    cancellation_requested: bool
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class GenerationStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    state: str
    profile_snapshot: dict[str, Any]
    extractor_versions: dict[str, Any]
    created_at: datetime
    jobs: list[JobStatusResponse]


class AssetStatusResponse(BaseModel):
    asset_id: UUID
    state: str
    active_generation_id: UUID | None
    current_generation_id: UUID | None
    generations: list[GenerationStatusResponse]


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    revision: int
    config: dict[str, Any]
    created_at: datetime


class ProfileWriteRequest(BaseModel):
    options: IngestionOptions


class ReprocessRequest(BaseModel):
    profile_name: str = Field(default="automatic", min_length=1, max_length=120)


class CancelRequest(BaseModel):
    generation_id: UUID | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8192)
    mode: str = Field(default="hybrid", pattern="^(hybrid|semantic|keyword)$")
    limit: int = Field(default=10, ge=1, le=50)
    candidate_limit: int = Field(default=60, ge=10, le=200)
    content_types: list[str] | None = Field(default=None, max_length=32)
    asset_ids: list[UUID] | None = Field(default=None, max_length=100)
    weights: dict[str, float] | None = None
    similarity_cutoffs: dict[str, float] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, query: str) -> str:
        clean = query.strip()
        if not clean:
            raise ValueError("search query cannot be empty")
        return clean

    @field_validator("weights")
    @classmethod
    def validate_weights(
        cls, weights: dict[str, float] | None
    ) -> dict[str, float] | None:
        if weights is None:
            return None
        if set(weights) - set(DEFAULT_WEIGHTS):
            raise ValueError("unknown search channel weight")
        if any(
            not math.isfinite(value) or not 0 <= value <= 10
            for value in weights.values()
        ):
            raise ValueError(
                "search channel weights must be finite and between 0 and 10"
            )
        return weights

    @field_validator("similarity_cutoffs")
    @classmethod
    def validate_similarity_cutoffs(
        cls, cutoffs: dict[str, float] | None
    ) -> dict[str, float] | None:
        if cutoffs is None:
            return None
        dense_channels = {"text", "transcript", "ocr", "image", "audio", "video"}
        if set(cutoffs) - dense_channels:
            raise ValueError(
                "similarity cutoffs must use dense representation channels"
            )
        if any(
            not math.isfinite(value) or not -1 <= value <= 1
            for value in cutoffs.values()
        ):
            raise ValueError(
                "cosine similarity cutoffs must be finite and between -1 and 1"
            )
        return cutoffs

    @model_validator(mode="after")
    def validate_limits_and_enabled_weights(self) -> "SearchRequest":
        if self.candidate_limit < self.limit:
            raise ValueError("candidate_limit must be at least limit")
        resolved_weights = {**DEFAULT_WEIGHTS, **(self.weights or {})}
        if not any(resolved_weights.values()):
            raise ValueError("at least one search channel weight must be positive")
        return self


def _default_profile_config(settings: Settings) -> dict[str, Any]:
    return IngestionOptions(
        text_chunk_tokens=settings.chunk_target_tokens,
        text_overlap_tokens=settings.chunk_overlap_tokens,
        ocr_languages=settings.ocr_languages,
    ).model_dump(mode="json")


async def _ensure_default_profile(
    session: AsyncSession, settings: Settings
) -> IngestionProfile:
    workspace_id = settings.default_workspace_id
    await session.execute(
        pg_insert(Workspace)
        .values(id=workspace_id, name=settings.default_workspace_name)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )
    profile = await session.scalar(
        select(IngestionProfile)
        .where(
            IngestionProfile.workspace_id == workspace_id,
            IngestionProfile.name == "automatic",
        )
        .order_by(IngestionProfile.revision.desc())
        .limit(1)
    )
    if profile is None:
        await session.execute(
            pg_insert(IngestionProfile)
            .values(
                id=uuid4(),
                workspace_id=workspace_id,
                name="automatic",
                revision=1,
                config=_default_profile_config(settings),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IngestionProfile.workspace_id,
                    IngestionProfile.name,
                    IngestionProfile.revision,
                ]
            )
        )
        profile = await session.scalar(
            select(IngestionProfile)
            .where(
                IngestionProfile.workspace_id == workspace_id,
                IngestionProfile.name == "automatic",
            )
            .order_by(IngestionProfile.revision.desc())
            .limit(1)
        )
    assert profile is not None
    return profile


def _safe_filename(filename: str | None) -> str:
    value = (filename or "upload").replace("\\", "/").split("/")[-1].strip()
    value = "".join(character for character in value if character.isprintable())
    return value[:1024] or "upload"


def _normalized_filename(filename: str) -> str:
    return re.sub(r"\s+", " ", filename.strip()).casefold()


_ACTIVE_DOCUMENT_TYPES = {
    "application/xhtml+xml",
    "image/svg+xml",
    "text/html",
    "text/javascript",
    "application/javascript",
    "application/xml",
    "text/xml",
}


def _source_response_type(content_type: str) -> tuple[str, bool]:
    """Keep uploaded active documents from executing on the API origin."""
    normalized = content_type.split(";", 1)[0].strip().casefold()
    if normalized in _ACTIVE_DOCUMENT_TYPES:
        return "application/octet-stream", True
    return content_type, False


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(_session)]


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    storage: S3ObjectStorage | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = None
    if session_factory is None:
        engine = make_engine(settings)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = storage or S3ObjectStorage(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await storage.ensure_bucket()
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Search Anything API", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.settings = settings

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", response_model=ReadinessResponse)
    async def ready(session: Session, request: Request) -> ReadinessResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as error:
            logger.warning("Database readiness check failed: %s", type(error).__name__)
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        try:
            await request.app.state.storage.check_bucket()
        except Exception as error:
            logger.warning("Storage readiness check failed: %s", type(error).__name__)
            raise HTTPException(
                status_code=503, detail="storage unavailable"
            ) from error
        return ReadinessResponse(status="ready", database="ready", storage="ready")

    @app.post("/api/assets", response_model=UploadResponse, status_code=201)
    async def upload_asset(
        request: Request,
        session: Session,
        file: Annotated[UploadFile, File()],
    ) -> UploadResponse:
        filename = _safe_filename(file.filename)
        content_type = (file.content_type or "application/octet-stream")[:255]
        asset_id = uuid4()
        generation_id = uuid4()
        job_id = uuid4()
        workspace_id = request.app.state.settings.default_workspace_id
        object_key = f"workspaces/{workspace_id}/assets/{asset_id}/original"
        digest = hashlib.sha256()
        size = 0

        with tempfile.SpooledTemporaryFile(
            max_size=8 * 1024 * 1024, mode="w+b"
        ) as body:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > request.app.state.settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail="upload exceeds configured size limit"
                    )
                digest.update(chunk)
                body.write(chunk)
            if size == 0:
                raise HTTPException(
                    status_code=400, detail="empty files cannot be indexed"
                )
            body.seek(0)
            content_hash = digest.hexdigest()
            try:
                await request.app.state.storage.put_file(
                    object_key, body, content_type, content_hash
                )
                async with session.begin():
                    profile = await _ensure_default_profile(
                        session, request.app.state.settings
                    )
                    asset = Asset(
                        id=asset_id,
                        workspace_id=workspace_id,
                        filename=filename,
                        normalized_filename=_normalized_filename(filename),
                        content_type=content_type,
                        byte_size=size,
                        content_hash=content_hash,
                        storage_key=object_key,
                        state="queued",
                    )
                    generation = ProcessingGeneration(
                        id=generation_id,
                        asset_id=asset_id,
                        profile_snapshot={
                            "profile_id": str(profile.id),
                            "name": profile.name,
                            "revision": profile.revision,
                            **profile.config,
                        },
                        extractor_versions={},
                        state="queued",
                    )
                    job = IngestionJob(
                        id=job_id,
                        asset_id=asset_id,
                        generation_id=generation_id,
                        stage="probe",
                        status="queued",
                        priority=10,
                        payload={
                            "asset_id": str(asset_id),
                            "generation_id": str(generation_id),
                        },
                        idempotency_key=f"generation:{generation_id}:probe",
                        max_attempts=request.app.state.settings.job_max_attempts,
                    )
                    session.add(asset)
                    await session.flush()
                    session.add(generation)
                    await session.flush()
                    session.add(job)
                    await session.flush()
            except Exception:
                await request.app.state.storage.delete_object(object_key)
                raise

        return UploadResponse(
            asset=AssetResponse.model_validate(asset),
            generation_id=generation_id,
            job_id=job_id,
        )

    @app.get("/api/assets", response_model=list[AssetResponse])
    async def list_assets(
        request: Request,
        session: Session,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[AssetResponse]:
        rows = (
            await session.scalars(
                select(Asset)
                .where(
                    Asset.workspace_id
                    == request.app.state.settings.default_workspace_id,
                    Asset.state.not_in(("deleting", "deleted")),
                )
                .order_by(Asset.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [AssetResponse.model_validate(asset) for asset in rows]

    async def get_asset_or_404(
        session: AsyncSession, workspace_id: UUID, asset_id: UUID
    ) -> Asset:
        asset = await session.scalar(
            select(Asset).where(
                Asset.id == asset_id,
                Asset.workspace_id == workspace_id,
                Asset.state.not_in(("deleting", "deleted")),
            )
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return asset

    @app.get("/api/assets/{asset_id}", response_model=AssetResponse)
    async def get_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> AssetResponse:
        asset = await get_asset_or_404(
            session, request.app.state.settings.default_workspace_id, asset_id
        )
        return AssetResponse.model_validate(asset)

    @app.get("/api/assets/{asset_id}/status", response_model=AssetStatusResponse)
    async def asset_status(
        asset_id: UUID, request: Request, session: Session
    ) -> AssetStatusResponse:
        asset = await get_asset_or_404(
            session, request.app.state.settings.default_workspace_id, asset_id
        )
        generations = (
            await session.scalars(
                select(ProcessingGeneration)
                .where(ProcessingGeneration.asset_id == asset.id)
                .order_by(ProcessingGeneration.created_at.desc())
                .limit(20)
            )
        ).all()
        generation_ids = [generation.id for generation in generations]
        jobs = (
            (
                await session.scalars(
                    select(IngestionJob)
                    .where(IngestionJob.generation_id.in_(generation_ids))
                    .order_by(IngestionJob.created_at)
                )
            ).all()
            if generation_ids
            else []
        )
        jobs_by_generation: dict[UUID, list[JobStatusResponse]] = {}
        for job in jobs:
            if job.generation_id is not None:
                jobs_by_generation.setdefault(job.generation_id, []).append(
                    JobStatusResponse.model_validate(job)
                )
        return AssetStatusResponse(
            asset_id=asset.id,
            state=asset.state,
            active_generation_id=asset.active_generation_id,
            current_generation_id=generations[0].id if generations else None,
            generations=[
                GenerationStatusResponse(
                    id=generation.id,
                    state=generation.state,
                    profile_snapshot=generation.profile_snapshot,
                    extractor_versions=generation.extractor_versions,
                    created_at=generation.created_at,
                    jobs=jobs_by_generation.get(generation.id, []),
                )
                for generation in generations
            ],
        )

    @app.get("/api/profiles", response_model=list[ProfileResponse])
    async def list_profiles(
        request: Request, session: Session
    ) -> list[ProfileResponse]:
        async with session.begin():
            await _ensure_default_profile(session, request.app.state.settings)
        rows = (
            await session.scalars(
                select(IngestionProfile)
                .where(
                    IngestionProfile.workspace_id
                    == request.app.state.settings.default_workspace_id
                )
                .order_by(IngestionProfile.name, IngestionProfile.revision.desc())
            )
        ).all()
        latest: dict[str, IngestionProfile] = {}
        for profile in rows:
            latest.setdefault(profile.name, profile)
        return [ProfileResponse.model_validate(profile) for profile in latest.values()]

    async def local_embedding(payload: dict[str, Any]) -> list[float]:
        socket_path = settings.model_socket_path
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(socket_path)), timeout=2
            )
        except (OSError, asyncio.TimeoutError) as error:
            raise HTTPException(
                status_code=503,
                detail="local model owner is unavailable; start the worker",
            ) from error
        try:
            writer.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
            await writer.drain()
            response_line = await asyncio.wait_for(reader.readline(), timeout=120)
        except asyncio.TimeoutError as error:
            raise HTTPException(
                status_code=504, detail="local query inference timed out"
            ) from error
        finally:
            writer.close()
            await writer.wait_closed()
        try:
            response = json.loads(response_line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise HTTPException(
                status_code=503, detail="invalid worker response"
            ) from error
        if "error" in response:
            status_code = (
                422
                if response["error"]
                in {"ContextLimitError", "ValueError", "IngestionError"}
                else 503
            )
            raise HTTPException(status_code=status_code, detail=response["message"])
        return response["vector"]

    @app.post("/api/search")
    async def search(
        body: SearchRequest, request: Request, session: Session
    ) -> dict[str, Any]:
        vector = (
            await local_embedding({"kind": "text", "text": body.query})
            if body.mode in {"hybrid", "semantic"}
            else None
        )
        results = await search_workspace(
            session,
            request.app.state.settings.default_workspace_id,
            query=body.query,
            vector=vector,
            mode=body.mode,
            limit=body.limit,
            candidate_limit=body.candidate_limit,
            content_types=body.content_types,
            asset_ids=body.asset_ids,
            weights=body.weights,
            similarity_cutoffs=body.similarity_cutoffs,
        )
        return {"query": body.query, "mode": body.mode, "results": results}

    @app.post("/api/search/image")
    async def search_image(
        request: Request,
        session: Session,
        file: Annotated[UploadFile, File()],
        limit: Annotated[int, Form(ge=1, le=50)] = 10,
        candidate_limit: Annotated[int, Form(ge=10, le=200)] = 60,
    ) -> dict[str, Any]:
        if candidate_limit < limit:
            raise HTTPException(
                status_code=422, detail="candidate_limit must be at least limit"
            )
        content = await file.read(8 * 1024 * 1024 + 1)
        await file.close()
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="query image exceeds 8 MiB")
        vector = await local_embedding(
            {
                "kind": "image",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
        results = await search_workspace(
            session,
            request.app.state.settings.default_workspace_id,
            query="",
            vector=vector,
            mode="semantic",
            limit=limit,
            candidate_limit=candidate_limit,
        )
        return {"mode": "semantic", "results": results}

    @app.put("/api/profiles/{profile_name}", response_model=ProfileResponse)
    async def save_profile(
        profile_name: str,
        body: ProfileWriteRequest,
        request: Request,
        session: Session,
    ) -> ProfileResponse:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", profile_name):
            raise HTTPException(status_code=422, detail="invalid profile name")
        workspace_id = request.app.state.settings.default_workspace_id
        async with session.begin():
            await session.execute(
                pg_insert(Workspace)
                .values(
                    id=workspace_id,
                    name=request.app.state.settings.default_workspace_name,
                )
                .on_conflict_do_nothing(index_elements=[Workspace.id])
            )
            await session.scalar(
                select(Workspace).where(Workspace.id == workspace_id).with_for_update()
            )
            previous = await session.scalar(
                select(IngestionProfile)
                .where(
                    IngestionProfile.workspace_id == workspace_id,
                    IngestionProfile.name == profile_name,
                )
                .order_by(IngestionProfile.revision.desc())
                .limit(1)
                .with_for_update()
            )
            profile = IngestionProfile(
                id=uuid4(),
                workspace_id=workspace_id,
                name=profile_name,
                revision=(previous.revision + 1) if previous else 1,
                config=body.options.model_dump(mode="json"),
            )
            session.add(profile)
            await session.flush()
        return ProfileResponse.model_validate(profile)

    @app.get("/api/assets/{asset_id}/content")
    async def get_asset_content(
        asset_id: UUID,
        request: Request,
        session: Session,
    ) -> StreamingResponse:
        # Read Range directly from the request so FastAPI does not reinterpret it as a query parameter.
        asset = await get_asset_or_404(
            session, request.app.state.settings.default_workspace_id, asset_id
        )
        try:
            byte_range = parse_range(request.headers.get("range"), asset.byte_size)
        except UnsatisfiableRange as error:
            return StreamingResponse(
                iter(()),
                status_code=416,
                headers={
                    "Content-Range": f"bytes */{error.size}",
                    "Accept-Ranges": "bytes",
                },
            )
        ranged = byte_range is not None
        stored = await request.app.state.storage.get_object(
            asset.storage_key, byte_range.header_value() if byte_range else None
        )

        async def chunks() -> AsyncIterator[bytes]:
            try:
                while chunk := await anyio.to_thread.run_sync(
                    stored.body.read, 64 * 1024
                ):
                    yield chunk
            finally:
                await anyio.to_thread.run_sync(stored.body.close)

        response_type, attachment = _source_response_type(asset.content_type)
        disposition = "attachment" if attachment else "inline"
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(stored.content_length),
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(asset.filename)}",
            "X-Content-Type-Options": "nosniff",
        }
        if ranged:
            headers["Content-Range"] = stored.content_range or (
                f"bytes {byte_range.start}-{byte_range.end}/{asset.byte_size}"
            )
        return StreamingResponse(
            chunks(),
            status_code=206 if ranged else 200,
            media_type=response_type,
            headers=headers,
        )

    @app.get("/api/assets/{asset_id}/presigned", response_model=PresignedURLResponse)
    async def presigned_asset_url(
        asset_id: UUID, request: Request, session: Session
    ) -> PresignedURLResponse:
        asset = await get_asset_or_404(
            session, request.app.state.settings.default_workspace_id, asset_id
        )
        url = await request.app.state.storage.presigned_get_url(asset.storage_key)
        return PresignedURLResponse(
            url=url,
            expires_in_seconds=request.app.state.settings.storage_presign_seconds,
        )

    @app.post("/api/assets/{asset_id}/retry", status_code=202)
    async def retry_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> dict[str, str | UUID]:
        workspace_id = request.app.state.settings.default_workspace_id
        now = datetime.now(timezone.utc)
        async with session.begin():
            asset = await session.scalar(
                select(Asset)
                .where(Asset.id == asset_id, Asset.workspace_id == workspace_id)
                .with_for_update()
            )
            if asset is None or asset.state in {"deleting", "deleted"}:
                raise HTTPException(status_code=404, detail="asset not found")
            generation_id = await session.scalar(
                select(ProcessingGeneration)
                .where(ProcessingGeneration.asset_id == asset_id)
                .order_by(ProcessingGeneration.created_at.desc())
                .limit(1)
            )
            if generation_id is None:
                raise HTTPException(status_code=404, detail="generation not found")
            failed = await session.scalar(
                select(IngestionJob)
                .where(
                    IngestionJob.asset_id == asset_id,
                    IngestionJob.generation_id == generation_id.id,
                    IngestionJob.stage != "cleanup",
                    IngestionJob.status == "failed",
                )
                .order_by(IngestionJob.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if failed is None:
                raise HTTPException(
                    status_code=409, detail="current generation has no failed job"
                )
            generation = await session.scalar(
                select(ProcessingGeneration)
                .where(ProcessingGeneration.id == generation_id.id)
                .with_for_update()
            )
            assert generation is not None
            failed.status = "retry"
            failed.attempts = 0
            failed.max_attempts = request.app.state.settings.job_max_attempts
            failed.progress = 0
            failed.available_at = now
            failed.cancellation_requested = False
            failed.error_code = None
            failed.error_message = None
            failed.lease_owner = None
            failed.lease_token = None
            failed.lease_expires_at = None
            generation.state = "queued"
            asset.state = "ready" if asset.active_generation_id else "queued"
        return {
            "status": "retrying",
            "asset_id": asset_id,
            "generation_id": generation.id,
            "job_id": failed.id,
        }

    @app.post("/api/assets/{asset_id}/cancel", status_code=202)
    async def cancel_asset(
        asset_id: UUID,
        request: Request,
        session: Session,
        body: CancelRequest,
    ) -> dict[str, str | UUID | int]:
        workspace_id = request.app.state.settings.default_workspace_id
        async with session.begin():
            asset = await session.scalar(
                select(Asset)
                .where(Asset.id == asset_id, Asset.workspace_id == workspace_id)
                .with_for_update()
            )
            if asset is None or asset.state in {"deleting", "deleted"}:
                raise HTTPException(status_code=404, detail="asset not found")
            if body.generation_id is None:
                generation = await session.scalar(
                    select(ProcessingGeneration)
                    .where(ProcessingGeneration.asset_id == asset_id)
                    .order_by(ProcessingGeneration.created_at.desc())
                    .limit(1)
                )
                generation_id = generation.id if generation else None
            else:
                generation_id = body.generation_id
            if generation_id is None:
                raise HTTPException(status_code=404, detail="generation not found")
            if asset.active_generation_id == generation_id:
                raise HTTPException(
                    status_code=409, detail="the active generation cannot be cancelled"
                )
            jobs = (
                await session.scalars(
                    select(IngestionJob)
                    .where(
                        IngestionJob.asset_id == asset_id,
                        IngestionJob.generation_id == generation_id,
                        IngestionJob.stage != "cleanup",
                        IngestionJob.status.in_(("queued", "retry", "running")),
                    )
                    .with_for_update()
                )
            ).all()
            generation = await session.scalar(
                select(ProcessingGeneration)
                .where(
                    ProcessingGeneration.id == generation_id,
                    ProcessingGeneration.asset_id == asset_id,
                )
                .with_for_update()
            )
            if generation is None:
                raise HTTPException(status_code=404, detail="generation not found")
            running = 0
            for job in jobs:
                if job.status == "running":
                    job.cancellation_requested = True
                    running += 1
                else:
                    job.status = "cancelled"
            generation.state = "cancelled"
            latest_generation_id = await session.scalar(
                select(ProcessingGeneration.id)
                .where(ProcessingGeneration.asset_id == asset_id)
                .order_by(ProcessingGeneration.created_at.desc())
                .limit(1)
            )
            if latest_generation_id == generation_id:
                asset.state = "ready" if asset.active_generation_id else "cancelled"
        return {
            "status": "cancellation_requested" if running else "cancelled",
            "asset_id": asset_id,
            "generation_id": generation_id,
            "running_jobs": running,
        }

    @app.post("/api/assets/{asset_id}/reprocess", status_code=202)
    async def reprocess_asset(
        asset_id: UUID,
        body: ReprocessRequest,
        request: Request,
        session: Session,
    ) -> dict[str, str | UUID | int]:
        workspace_id = request.app.state.settings.default_workspace_id
        generation_id = uuid4()
        job_id = uuid4()
        async with session.begin():
            asset = await session.scalar(
                select(Asset)
                .where(Asset.id == asset_id, Asset.workspace_id == workspace_id)
                .with_for_update()
            )
            if asset is None or asset.state in {"deleting", "deleted"}:
                raise HTTPException(status_code=404, detail="asset not found")
            if body.profile_name == "automatic":
                await _ensure_default_profile(session, request.app.state.settings)
            profile = await session.scalar(
                select(IngestionProfile)
                .where(
                    IngestionProfile.workspace_id == workspace_id,
                    IngestionProfile.name == body.profile_name,
                )
                .order_by(IngestionProfile.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if profile is None:
                raise HTTPException(status_code=404, detail="profile not found")
            try:
                options = IngestionOptions.model_validate(profile.config)
            except ValueError as error:
                raise HTTPException(
                    status_code=422, detail="profile configuration is invalid"
                ) from error
            jobs = (
                await session.scalars(
                    select(IngestionJob)
                    .where(
                        IngestionJob.asset_id == asset_id,
                        IngestionJob.stage != "cleanup",
                        IngestionJob.status.in_(("queued", "retry", "running")),
                    )
                    .with_for_update()
                )
            ).all()
            old_generation_ids = {
                job.generation_id for job in jobs if job.generation_id is not None
            }
            for job in jobs:
                if job.status == "running":
                    job.cancellation_requested = True
                else:
                    job.status = "cancelled"
            old_generations = (
                (
                    await session.scalars(
                        select(ProcessingGeneration)
                        .where(ProcessingGeneration.id.in_(old_generation_ids))
                        .with_for_update()
                    )
                ).all()
                if old_generation_ids
                else []
            )
            for old_generation in old_generations:
                if old_generation.state != "active":
                    old_generation.state = "cancelled"
            generation = ProcessingGeneration(
                id=generation_id,
                asset_id=asset_id,
                profile_snapshot={
                    "profile_id": str(profile.id),
                    "name": profile.name,
                    "revision": profile.revision,
                    **options.model_dump(mode="json"),
                },
                extractor_versions={},
                state="queued",
            )
            session.add(generation)
            await session.flush()
            session.add(
                IngestionJob(
                    id=job_id,
                    asset_id=asset_id,
                    generation_id=generation_id,
                    stage="probe",
                    status="queued",
                    priority=10,
                    payload={
                        "asset_id": str(asset_id),
                        "generation_id": str(generation_id),
                    },
                    idempotency_key=f"generation:{generation_id}:probe",
                    max_attempts=request.app.state.settings.job_max_attempts,
                )
            )
            asset.state = "ready" if asset.active_generation_id else "queued"
        return {
            "status": "queued",
            "asset_id": asset_id,
            "generation_id": generation_id,
            "job_id": job_id,
            "profile_revision": profile.revision,
        }

    @app.delete("/api/assets/{asset_id}", status_code=202)
    async def delete_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> dict[str, str | UUID]:
        workspace_id = request.app.state.settings.default_workspace_id
        async with session.begin():
            asset = await session.scalar(
                select(Asset)
                .where(Asset.id == asset_id, Asset.workspace_id == workspace_id)
                .with_for_update()
            )
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
            jobs = (
                await session.scalars(
                    select(IngestionJob)
                    .where(
                        IngestionJob.asset_id == asset_id,
                        IngestionJob.stage != "cleanup",
                        IngestionJob.status.in_(("queued", "retry", "running")),
                    )
                    .with_for_update()
                )
            ).all()
            if asset.state == "deleted":
                return {"status": "deleted", "asset_id": asset_id}
            asset.state = "deleting"
            for job in jobs:
                if job.status == "running":
                    job.cancellation_requested = True
                else:
                    job.status = "cancelled"
            cleanup = await session.scalar(
                select(IngestionJob).where(
                    IngestionJob.idempotency_key == f"asset:{asset_id}:cleanup"
                )
            )
            if cleanup is None:
                cleanup = IngestionJob(
                    id=uuid4(),
                    asset_id=asset_id,
                    stage="cleanup",
                    status="queued",
                    priority=-100,
                    payload={"asset_id": str(asset_id)},
                    idempotency_key=f"asset:{asset_id}:cleanup",
                    max_attempts=request.app.state.settings.job_max_attempts,
                )
                session.add(cleanup)
        return {"status": "deleting", "asset_id": asset_id}

    return app


app = create_app()
