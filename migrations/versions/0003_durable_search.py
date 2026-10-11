"""Durable workspace-scoped search jobs.

Revision ID: 0003_durable_search
Revises: 0002_search_lexical
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_durable_search"
down_revision = "0002_search_lexical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_workspace",
        "jobs",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"])
    op.add_column("jobs", sa.Column("result", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "result")
    op.drop_index("ix_jobs_workspace_id", table_name="jobs")
    op.drop_constraint("fk_jobs_workspace", "jobs", type_="foreignkey")
    op.drop_column("jobs", "workspace_id")
