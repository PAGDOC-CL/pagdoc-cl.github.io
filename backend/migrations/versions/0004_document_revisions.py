"""Add tenant-scoped document revision history.

Revision ID: 0004_document_revisions
Revises: 0003_requirements
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_document_revisions"
down_revision: Union[str, None] = "0003_requirements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False, server_default="metadata.update"),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_name", sa.String(length=150), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "document_id", "revision", name="uq_document_revision_number"),
    )
    op.create_index("ix_document_revisions_tenant_id", "document_revisions", ["tenant_id"])
    op.create_index("ix_document_revisions_document_id", "document_revisions", ["document_id"])
    op.create_index("ix_document_revisions_changed_by_user_id", "document_revisions", ["changed_by_user_id"])
    op.create_index("ix_document_revisions_changed_at", "document_revisions", ["changed_at"])


def downgrade() -> None:
    op.drop_index("ix_document_revisions_changed_at", table_name="document_revisions")
    op.drop_index("ix_document_revisions_changed_by_user_id", table_name="document_revisions")
    op.drop_index("ix_document_revisions_document_id", table_name="document_revisions")
    op.drop_index("ix_document_revisions_tenant_id", table_name="document_revisions")
    op.drop_table("document_revisions")
