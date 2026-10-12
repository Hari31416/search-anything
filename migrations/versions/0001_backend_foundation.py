"""Create the workspace-scoped data model with lexical and durable search."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_backend_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "ingestion_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "name", "revision"),
    )
    op.create_index(
        "ix_ingestion_profiles_workspace", "ingestion_profiles", ["workspace_id"]
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(1024), nullable=False),
        sa.Column("normalized_filename", sa.String(1024), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(2048), nullable=False, unique=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("active_generation_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_assets_workspace_state_created",
        "assets",
        ["workspace_id", "state", "created_at"],
    )
    op.create_index(
        "ix_assets_workspace_hash", "assets", ["workspace_id", "content_hash"]
    )
    op.create_index(
        "ix_assets_filename_normalized", "assets", [sa.text("lower(filename)")]
    )
    op.create_index(
        "ix_assets_filename_lexical",
        "assets",
        [sa.text("to_tsvector('simple', coalesce(filename, ''))")],
        postgresql_using="gin",
    )

    op.create_table(
        "processing_generations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "extractor_versions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("state", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_generations_asset_state_created",
        "processing_generations",
        ["asset_id", "state", "created_at"],
    )
    op.create_foreign_key(
        "fk_assets_active_generation",
        "assets",
        "processing_generations",
        ["active_generation_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    op.create_table(
        "segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey("processing_generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column(
            "source_location",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_start", sa.BigInteger()),
        sa.Column("source_end", sa.BigInteger()),
        sa.Column("time_start", sa.Float()),
        sa.Column("time_end", sa.Float()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("generation_id", "ordinal"),
    )
    op.create_index("ix_segments_generation", "segments", ["generation_id"])

    op.create_table(
        "representations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey("processing_generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "segment_id", sa.Uuid(), sa.ForeignKey("segments.id", ondelete="CASCADE")
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text_content", sa.Text()),
        sa.Column("detected_language", sa.String(32)),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_representations_kind", "representations", ["kind"])
    op.create_index(
        "ix_representations_lexical",
        "representations",
        [
            sa.text(
                "(setweight(to_tsvector('simple', coalesce(text_content, '')), 'B') "
                "|| setweight(to_tsvector('simple', coalesce(metadata->>'heading', '')), 'A'))"
            )
        ],
        postgresql_using="gin",
    )

    op.create_table(
        "embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "representation_id",
            sa.Uuid(),
            sa.ForeignKey("representations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("model_revision", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", Vector(768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("representation_id", "model_id", "model_revision"),
    )

    op.create_table(
        "derived_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey("processing_generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(2048), nullable=False, unique=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(
                "workspaces.id", name="fk_jobs_workspace", ondelete="CASCADE"
            ),
            nullable=True,
        ),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE")
        ),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey("processing_generations.id", ondelete="CASCADE"),
        ),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="10"),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "cancellation_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency"),
    )
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", "priority", "available_at", "lease_expires_at"],
    )
    op.create_index("ix_jobs_asset_generation", "jobs", ["asset_id", "generation_id"])
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("derived_artifacts")
    op.drop_table("embeddings")
    op.drop_table("representations")
    op.drop_table("segments")
    op.drop_constraint("fk_assets_active_generation", "assets", type_="foreignkey")
    op.drop_table("processing_generations")
    op.drop_table("assets")
    op.drop_table("ingestion_profiles")
    op.drop_table("workspaces")
