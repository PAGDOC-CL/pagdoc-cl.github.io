"""Add immutable encrypted document file version metadata.

Revision ID: 0006_document_file_versions
Revises: 0005_alert_inbox
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_document_file_versions"
down_revision: Union[str, None] = "0005_alert_inbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_file_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=32), nullable=False),
        sa.Column("original_name", sa.String(length=160), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("scan_engine", sa.String(length=120), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "document_id", "version", name="uq_document_file_version"),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_document_file_object_key"),
    )
    op.create_index("ix_document_file_versions_tenant_id", "document_file_versions", ["tenant_id"])
    op.create_index("ix_document_file_versions_document_id", "document_file_versions", ["document_id"])
    op.create_index("ix_document_file_versions_created_by_user_id", "document_file_versions", ["created_by_user_id"])
    op.create_index("ix_document_file_versions_created_at", "document_file_versions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_document_file_versions_created_at", table_name="document_file_versions")
    op.drop_index("ix_document_file_versions_created_by_user_id", table_name="document_file_versions")
    op.drop_index("ix_document_file_versions_document_id", table_name="document_file_versions")
    op.drop_index("ix_document_file_versions_tenant_id", table_name="document_file_versions")
    op.drop_table("document_file_versions")
