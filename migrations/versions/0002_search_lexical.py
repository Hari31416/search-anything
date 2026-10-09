"""Weight representation text and add filename lexical indexes."""

from alembic import op
import sqlalchemy as sa

revision = "0002_search_lexical"
down_revision = "0001_backend_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_representations_lexical", table_name="representations")
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
    op.create_index(
        "ix_assets_filename_lexical",
        "assets",
        [sa.text("to_tsvector('simple', coalesce(filename, ''))")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_assets_filename_lexical", table_name="assets")
    op.drop_index("ix_representations_lexical", table_name="representations")
    op.create_index(
        "ix_representations_lexical",
        "representations",
        [sa.text("to_tsvector('simple', coalesce(text_content, ''))")],
        postgresql_using="gin",
    )
