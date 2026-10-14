"""Add HMAC chain seals for new audit events.

Revision ID: 0007_audit_seals
Revises: 0006_document_file_versions
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_audit_seals"
down_revision: Union[str, None] = "0006_document_file_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_seals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("audit_id", sa.Integer(), sa.ForeignKey("audit.id"), nullable=False, unique=True),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False, unique=True),
    )
    op.create_index("ix_audit_seals_tenant_id", "audit_seals", ["tenant_id"])
    op.create_index("ix_audit_seals_audit_id", "audit_seals", ["audit_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_seals_audit_id", table_name="audit_seals")
    op.drop_index("ix_audit_seals_tenant_id", table_name="audit_seals")
    op.drop_table("audit_seals")
