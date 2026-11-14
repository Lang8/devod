"""passage source attribution, license and level provenance

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("passage", sa.Column("source_url", sa.String(500)))
    op.add_column("passage", sa.Column("source_title", sa.String(300)))
    op.add_column("passage", sa.Column("author", sa.String(300)))
    # NOT NULL; the server default backfills existing LLM passages.
    op.add_column("passage", sa.Column("license", sa.String(50), nullable=False,
                                       server_default="llm-generated"))
    op.add_column("passage", sa.Column("license_tier", sa.String(12), nullable=False,
                                       server_default="open"))
    op.add_column("passage", sa.Column("source_level", sa.String(2)))
    op.add_column("passage", sa.Column("adapted", sa.Boolean, nullable=False,
                                       server_default=sa.false()))
    op.create_index("ix_passage_source_url", "passage", ["source_url"])


def downgrade() -> None:
    op.drop_index("ix_passage_source_url", table_name="passage")
    for c in ("adapted", "source_level", "license_tier", "license", "author", "source_title", "source_url"):
        op.drop_column("passage", c)
