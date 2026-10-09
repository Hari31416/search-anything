"""FastAPI endpoints for local uploads, status, and source previews."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, AsyncIterator
from urllib.parse import quote
from uuid import UUID, uuid4

import anyio
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from search_anything.db import make_engine
from search_anything.models import (
    Asset,
    IngestionJob,
    IngestionProfile,
    ProcessingGeneration,
    Workspace,
)
from search_anything.ranges import UnsatisfiableRange, parse_range
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


def _safe_filename(filename: str | None) -> str:
    value = (filename or "upload").replace("\\", "/").split("/")[-1].strip()
    value = "".join(character for character in value if character.isprintable())
    return value[:1024] or "upload"


def _normalized_filename(filename: str) -> str:
    return re.sub(r"\s+", " ", filename.strip()).casefold()


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
                    workspace = await session.get(Workspace, workspace_id)
                    if workspace is None:
                        await session.execute(
                            pg_insert(Workspace)
                            .values(
                                id=workspace_id,
                                name=request.app.state.settings.default_workspace_name,
                            )
                            .on_conflict_do_nothing(index_elements=[Workspace.id])
                        )
                        workspace = await session.get(Workspace, workspace_id)
                    profile = await session.scalar(
                        select(IngestionProfile).where(
                            IngestionProfile.workspace_id == workspace_id,
                            IngestionProfile.name == "automatic",
                            IngestionProfile.revision == 1,
                        )
                    )
                    if profile is None:
                        await session.execute(
                            pg_insert(IngestionProfile)
                            .values(
                                id=uuid4(),
                                workspace_id=workspace_id,
                                name="automatic",
                                revision=1,
                                config={"strategy": "automatic", "version": 1},
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
                            select(IngestionProfile).where(
                                IngestionProfile.workspace_id == workspace_id,
                                IngestionProfile.name == "automatic",
                                IngestionProfile.revision == 1,
                            )
                        )
                        assert profile is not None
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

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(stored.content_length),
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(asset.filename)}",
            "X-Content-Type-Options": "nosniff",
        }
        if ranged:
            headers["Content-Range"] = stored.content_range or (
                f"bytes {byte_range.start}-{byte_range.end}/{asset.byte_size}"
            )
        return StreamingResponse(
            chunks(),
            status_code=206 if ranged else 200,
            media_type=asset.content_type,
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

    @app.delete("/api/assets/{asset_id}", status_code=202)
    async def delete_asset(
        asset_id: UUID, request: Request, session: Session
    ) -> dict[str, str | UUID]:
        workspace_id = request.app.state.settings.default_workspace_id
        async with session.begin():
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
            asset = await session.scalar(
                select(Asset)
                .where(Asset.id == asset_id, Asset.workspace_id == workspace_id)
                .with_for_update()
            )
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
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
