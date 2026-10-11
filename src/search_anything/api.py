"""FastAPI endpoints for local uploads, status, and source previews."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator, Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import anyio
from fastapi import (
    APIRouter,
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
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
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
from search_anything.search_requests import SearchRequest
from search_anything.events import notify_work
from search_anything.settings import Settings, get_settings
from search_anything.storage import S3ObjectStorage

logger = logging.getLogger(__name__)


class WorkspaceWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(value.split())
        return value


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime


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


class SearchSubmissionResponse(BaseModel):
    id: UUID
    status: Literal["queued"]


class SearchJobError(BaseModel):
    code: str | None
    message: str | None


class SearchJobResponse(BaseModel):
    id: UUID
    status: Literal["queued", "retry", "running", "succeeded", "failed", "cancelled"]
    result: dict[str, Any] | None
    error: SearchJobError | None


def _search_form_options(
    query: str,
    mode: str,
    limit: int,
    candidate_limit: int,
    content_types: str | None,
    asset_ids: str | None,
    weights: str | None,
    similarity_cutoffs: str | None,
    representation_mode: str,
) -> SearchRequest:
    def parse_json_field(name: str, value: str | None) -> Any:
        if value is None or not value.strip():
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=422, detail=f"{name} must be valid JSON"
            ) from error

    try:
        return SearchRequest.model_validate(
            {
                "query": query or "media query",
                "mode": mode,
                "limit": limit,
                "candidate_limit": candidate_limit,
                "content_types": parse_json_field("content_types", content_types),
                "asset_ids": parse_json_field("asset_ids", asset_ids),
                "weights": parse_json_field("weights", weights),
                "similarity_cutoffs": parse_json_field(
                    "similarity_cutoffs", similarity_cutoffs
                ),
                "representation_mode": representation_mode,
            }
        )
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error


def _default_profile_config(settings: Settings) -> dict[str, Any]:
    return IngestionOptions(
        text_chunk_tokens=settings.chunk_target_tokens,
        text_overlap_tokens=settings.chunk_overlap_tokens,
        ocr_languages=settings.ocr_languages,
    ).model_dump(mode="json")


async def _ensure_default_profile(
    session: AsyncSession, settings: Settings, workspace_id: UUID | None = None
) -> IngestionProfile:
    workspace_id = workspace_id or settings.default_workspace_id
    if workspace_id == settings.default_workspace_id:
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

    async def select_workspace(
        request: Request,
        workspace_id: Annotated[UUID | None, Query()] = None,
    ) -> None:
        selected = workspace_id or settings.default_workspace_id
        async with session_factory() as selection_session:
            async with selection_session.begin():
                if selected == settings.default_workspace_id:
                    await _ensure_default_profile(selection_session, settings)
                elif await selection_session.get(Workspace, selected) is None:
                    raise HTTPException(status_code=404, detail="workspace not found")
        request.state.workspace_id = selected

    scoped = APIRouter(dependencies=[Depends(select_workspace)])

    @app.get("/api/workspaces", response_model=list[WorkspaceResponse])
    async def list_workspaces(session: Session) -> list[WorkspaceResponse]:
        async with session.begin():
            await _ensure_default_profile(session, settings)
            rows = (
                await session.scalars(
                    select(Workspace).order_by(
                        Workspace.id != settings.default_workspace_id,
                        Workspace.created_at,
                        Workspace.id,
                    )
                )
            ).all()
        return [WorkspaceResponse.model_validate(row) for row in rows]

    @app.post("/api/workspaces", response_model=WorkspaceResponse, status_code=201)
    async def create_workspace(
        body: WorkspaceWriteRequest, session: Session
    ) -> WorkspaceResponse:
        async with session.begin():
            workspace = Workspace(id=uuid4(), name=body.name)
            session.add(workspace)
            await session.flush()
            await _ensure_default_profile(session, settings, workspace.id)
        return WorkspaceResponse.model_validate(workspace)

    @app.patch("/api/workspaces/{workspace_id}", response_model=WorkspaceResponse)
    async def rename_workspace(
        workspace_id: UUID, body: WorkspaceWriteRequest, session: Session
    ) -> WorkspaceResponse:
        async with session.begin():
            workspace = await session.get(Workspace, workspace_id)
            if workspace is None:
                raise HTTPException(status_code=404, detail="workspace not found")
            workspace.name = body.name
            await session.flush()
        return WorkspaceResponse.model_validate(workspace)

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

    @scoped.post("/api/assets", response_model=UploadResponse, status_code=201)
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
        workspace_id = request.state.workspace_id
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
                        session, request.app.state.settings, request.state.workspace_id
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
                    await notify_work(session)
            except Exception:
                await request.app.state.storage.delete_object(object_key)
                raise

        return UploadResponse(
            asset=AssetResponse.model_validate(asset),
            generation_id=generation_id,
            job_id=job_id,
        )

    @scoped.get("/api/assets", response_model=list[AssetResponse])
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
                    Asset.workspace_id == request.state.workspace_id,
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

    @scoped.get("/api/assets/{asset_id}", response_model=AssetResponse)
    async def get_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> AssetResponse:
        asset = await get_asset_or_404(session, request.state.workspace_id, asset_id)
        return AssetResponse.model_validate(asset)

    @scoped.get("/api/assets/{asset_id}/status", response_model=AssetStatusResponse)
    async def asset_status(
        asset_id: UUID, request: Request, session: Session
    ) -> AssetStatusResponse:
        asset = await get_asset_or_404(session, request.state.workspace_id, asset_id)
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

    @scoped.get("/api/profiles", response_model=list[ProfileResponse])
    async def list_profiles(
        request: Request, session: Session
    ) -> list[ProfileResponse]:
        async with session.begin():
            await _ensure_default_profile(
                session, request.app.state.settings, request.state.workspace_id
            )
        rows = (
            await session.scalars(
                select(IngestionProfile)
                .where(IngestionProfile.workspace_id == request.state.workspace_id)
                .order_by(IngestionProfile.name, IngestionProfile.revision.desc())
            )
        ).all()
        latest: dict[str, IngestionProfile] = {}
        for profile in rows:
            latest.setdefault(profile.name, profile)
        return [ProfileResponse.model_validate(profile) for profile in latest.values()]

    async def enqueue_search(
        request: Request,
        session: AsyncSession,
        options: SearchRequest,
        *,
        kind: str = "text",
        query: str | None = None,
        content: bytes | None = None,
        content_type: str = "application/octet-stream",
        filename: str | None = None,
    ) -> dict[str, Any]:
        job_id = uuid4()
        key = None
        if content is not None:
            key = f"queries/{request.state.workspace_id}/{job_id}"
            await storage.put_file(
                key,
                io.BytesIO(content),
                content_type,
                hashlib.sha256(content).hexdigest(),
            )
        payload = {
            "options": options.model_dump(mode="json"),
            "kind": kind,
            "query": options.query if query is None else query,
            "storage_key": key,
            "content_type": content_type,
            "filename": filename,
        }
        try:
            job = IngestionJob(
                id=job_id,
                workspace_id=request.state.workspace_id,
                stage="search",
                priority=0,
                payload=payload,
                idempotency_key=f"search:{job_id}",
                max_attempts=settings.job_max_attempts,
            )
            session.add(job)
            await notify_work(session)
            await session.commit()
        except Exception:
            await session.rollback()
            # A commit failure can have an ambiguous outcome. Keep the object
            # for a possibly committed job; bucket lifecycle handles orphans.
            raise
        return {"id": str(job_id), "status": "queued"}

    @scoped.get("/api/search/jobs/{job_id}", response_model=SearchJobResponse)
    async def search_status(
        job_id: UUID, request: Request, session: Session
    ) -> dict[str, Any]:
        job = await session.scalar(
            select(IngestionJob).where(
                IngestionJob.id == job_id,
                IngestionJob.stage == "search",
                IngestionJob.workspace_id == request.state.workspace_id,
            )
        )
        if job is None:
            raise HTTPException(status_code=404, detail="search job not found")
        return {
            "id": str(job.id),
            "status": job.status,
            "result": job.result if job.status == "succeeded" else None,
            "error": (
                {"code": job.error_code, "message": job.error_message}
                if job.status == "failed"
                else None
            ),
        }

    @scoped.post(
        "/api/search", status_code=202, response_model=SearchSubmissionResponse
    )
    async def search(
        body: SearchRequest, request: Request, session: Session
    ) -> dict[str, Any]:
        return await enqueue_search(request, session, body)

    @scoped.post(
        "/api/search/image", status_code=202, response_model=SearchSubmissionResponse
    )
    async def search_image(
        request: Request,
        session: Session,
        file: Annotated[UploadFile, File()],
        query: Annotated[str, Form()] = "",
        mode: Annotated[str | None, Form(pattern="^(hybrid|semantic|keyword)$")] = None,
        limit: Annotated[int, Form(ge=1, le=50)] = 10,
        candidate_limit: Annotated[int, Form(ge=10, le=200)] = 60,
        content_types: Annotated[str | None, Form()] = None,
        asset_ids: Annotated[str | None, Form()] = None,
        weights: Annotated[str | None, Form()] = None,
        similarity_cutoffs: Annotated[str | None, Form()] = None,
        representation_mode: Annotated[
            str, Form(pattern="^(separate|combined|both)$")
        ] = "separate",
    ) -> dict[str, Any]:
        if candidate_limit < limit:
            raise HTTPException(
                status_code=422, detail="candidate_limit must be at least limit"
            )
        content = await file.read(8 * 1024 * 1024 + 1)
        content_type = file.content_type or "application/octet-stream"
        await file.close()
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="query image exceeds 8 MiB")
        clean_query = query.strip()
        resolved_mode = mode or ("hybrid" if clean_query else "semantic")
        options = _search_form_options(
            clean_query,
            resolved_mode,
            limit,
            candidate_limit,
            content_types,
            asset_ids,
            weights,
            similarity_cutoffs,
            representation_mode,
        )
        return await enqueue_search(
            request,
            session,
            options,
            kind="image_text" if clean_query else "image",
            query=clean_query,
            content=content,
            content_type=content_type,
        )

    @scoped.post(
        "/api/search/media", status_code=202, response_model=SearchSubmissionResponse
    )
    async def search_media(
        request: Request,
        session: Session,
        file: Annotated[UploadFile, File()],
        query: Annotated[str, Form()] = "",
        mode: Annotated[str | None, Form(pattern="^(hybrid|semantic|keyword)$")] = None,
        limit: Annotated[int, Form(ge=1, le=50)] = 10,
        candidate_limit: Annotated[int, Form(ge=10, le=200)] = 60,
        content_types: Annotated[str | None, Form()] = None,
        asset_ids: Annotated[str | None, Form()] = None,
        weights: Annotated[str | None, Form()] = None,
        similarity_cutoffs: Annotated[str | None, Form()] = None,
        representation_mode: Annotated[
            str, Form(pattern="^(separate|combined|both)$")
        ] = "separate",
    ) -> dict[str, Any]:
        content = await file.read(16 * 1024 * 1024 + 1)
        content_type = file.content_type or "application/octet-stream"
        filename = file.filename or "query-media"
        await file.close()
        if len(content) > 16 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="query media exceeds 16 MiB")
        clean_query = query.strip()
        resolved_mode = mode or ("hybrid" if clean_query else "semantic")
        options = _search_form_options(
            clean_query or "media query",
            resolved_mode,
            limit,
            candidate_limit,
            content_types,
            asset_ids,
            weights,
            similarity_cutoffs,
            representation_mode,
        )
        return await enqueue_search(
            request,
            session,
            options,
            kind="media",
            query=clean_query,
            content=content,
            content_type=content_type,
            filename=filename,
        )

    @scoped.put("/api/profiles/{profile_name}", response_model=ProfileResponse)
    async def save_profile(
        profile_name: str,
        body: ProfileWriteRequest,
        request: Request,
        session: Session,
    ) -> ProfileResponse:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", profile_name):
            raise HTTPException(status_code=422, detail="invalid profile name")
        workspace_id = request.state.workspace_id
        async with session.begin():
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

    @scoped.get("/api/assets/{asset_id}/content")
    async def get_asset_content(
        asset_id: UUID,
        request: Request,
        session: Session,
    ) -> StreamingResponse:
        # Read Range directly from the request so FastAPI does not reinterpret it as a query parameter.
        asset = await get_asset_or_404(session, request.state.workspace_id, asset_id)
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

    @scoped.get("/api/assets/{asset_id}/presigned", response_model=PresignedURLResponse)
    async def presigned_asset_url(
        asset_id: UUID, request: Request, session: Session
    ) -> PresignedURLResponse:
        asset = await get_asset_or_404(session, request.state.workspace_id, asset_id)
        url = await request.app.state.storage.presigned_get_url(asset.storage_key)
        return PresignedURLResponse(
            url=url,
            expires_in_seconds=request.app.state.settings.storage_presign_seconds,
        )

    @scoped.post("/api/assets/{asset_id}/retry", status_code=202)
    async def retry_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> dict[str, str | UUID]:
        workspace_id = request.state.workspace_id
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
            await notify_work(session)
        return {
            "status": "retrying",
            "asset_id": asset_id,
            "generation_id": generation.id,
            "job_id": failed.id,
        }

    @scoped.post("/api/assets/{asset_id}/cancel", status_code=202)
    async def cancel_asset(
        asset_id: UUID,
        request: Request,
        session: Session,
        body: CancelRequest,
    ) -> dict[str, str | UUID | int]:
        workspace_id = request.state.workspace_id
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

    @scoped.post("/api/assets/{asset_id}/reprocess", status_code=202)
    async def reprocess_asset(
        asset_id: UUID,
        body: ReprocessRequest,
        request: Request,
        session: Session,
    ) -> dict[str, str | UUID | int]:
        workspace_id = request.state.workspace_id
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
                await _ensure_default_profile(
                    session, request.app.state.settings, request.state.workspace_id
                )
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
            await notify_work(session)
        return {
            "status": "queued",
            "asset_id": asset_id,
            "generation_id": generation_id,
            "job_id": job_id,
            "profile_revision": profile.revision,
        }

    @scoped.delete("/api/assets/{asset_id}", status_code=202)
    async def delete_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> dict[str, str | UUID]:
        workspace_id = request.state.workspace_id
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
                await notify_work(session)
        return {"status": "deleting", "asset_id": asset_id}

    app.include_router(scoped)
    return app


app = create_app()
