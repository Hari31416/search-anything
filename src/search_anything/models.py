"""Persistent assets, generations, representations, and job leases."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    assets: Mapped[list["Asset"]] = relationship(back_populates="workspace")


class IngestionProfile(Base):
    __tablename__ = "ingestion_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", "revision"),
        Index("ix_ingestion_profiles_workspace", "workspace_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index(
            "ix_assets_workspace_state_created", "workspace_id", "state", "created_at"
        ),
        Index("ix_assets_workspace_hash", "workspace_id", "content_hash"),
        Index("ix_assets_filename_normalized", text("lower(filename)")),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    page_count: Mapped[int | None] = mapped_column(Integer)
    active_generation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_generations.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="assets")
    generations: Mapped[list["ProcessingGeneration"]] = relationship(
        back_populates="asset",
        foreign_keys="ProcessingGeneration.asset_id",
        cascade="all, delete-orphan",
    )
    active_generation: Mapped["ProcessingGeneration | None"] = relationship(
        foreign_keys=[active_generation_id], post_update=True
    )


class ProcessingGeneration(Base):
    __tablename__ = "processing_generations"
    __table_args__ = (
        Index("ix_generations_asset_state_created", "asset_id", "state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    extractor_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    asset: Mapped[Asset] = relationship(
        back_populates="generations", foreign_keys=[asset_id]
    )
    segments: Mapped[list["Segment"]] = relationship(
        back_populates="generation", cascade="all, delete-orphan"
    )


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("generation_id", "ordinal"),
        Index("ix_segments_generation", "generation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_generations.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    source_start: Mapped[int | None] = mapped_column(BigInteger)
    source_end: Mapped[int | None] = mapped_column(BigInteger)
    time_start: Mapped[float | None] = mapped_column(Float)
    time_end: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    generation: Mapped[ProcessingGeneration] = relationship(back_populates="segments")
    representations: Mapped[list["Representation"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


class Representation(Base):
    __tablename__ = "representations"
    __table_args__ = (
        Index("ix_representations_kind", "kind"),
        Index(
            "ix_representations_lexical",
            text("to_tsvector('simple', coalesce(text_content, ''))"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_generations.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    detected_language: Mapped[str | None] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    segment: Mapped[Segment | None] = relationship(back_populates="representations")
    embedding: Mapped[list["Embedding"]] = relationship(
        back_populates="representation", cascade="all, delete-orphan"
    )


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("representation_id", "model_id", "model_revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    representation_id: Mapped[UUID] = mapped_column(
        ForeignKey("representations.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    representation: Mapped[Representation] = relationship(back_populates="embedding")


class DerivedArtifact(Base):
    __tablename__ = "derived_artifacts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_generations.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IngestionJob(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency"),
        Index(
            "ix_jobs_claim", "status", "priority", "available_at", "lease_expires_at"
        ),
        Index("ix_jobs_asset_generation", "asset_id", "generation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE")
    )
    generation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_generations.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
