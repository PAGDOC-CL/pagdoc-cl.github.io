"""Add tenant-scoped retention rules and document legal holds.

Revision ID: 0008_retention_policy
Revises: 0007_audit_seals
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_retention_policy"
down_revision: Union[str, None] = "0007_audit_seals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retention_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("days_after_expiry", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "subject_type", name="uq_retention_rule_subject_type"),
    )
    op.create_index("ix_retention_rules_tenant_id", "retention_rules", ["tenant_id"])
    op.create_index("ix_retention_rules_subject_type", "retention_rules", ["subject_type"])
    op.create_index("ix_retention_rules_updated_by_user_id", "retention_rules", ["updated_by_user_id"])
    op.create_index("ix_retention_rules_updated_at", "retention_rules", ["updated_at"])

    op.create_table(
        "document_retention_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("legal_hold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hold_note", sa.String(length=250), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "document_id", name="uq_document_retention_state"),
    )
    op.create_index("ix_document_retention_states_tenant_id", "document_retention_states", ["tenant_id"])
    op.create_index("ix_document_retention_states_document_id", "document_retention_states", ["document_id"])
    op.create_index("ix_document_retention_states_updated_by_user_id", "document_retention_states", ["updated_by_user_id"])
    op.create_index("ix_document_retention_states_updated_at", "document_retention_states", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_document_retention_states_updated_at", table_name="document_retention_states")
    op.drop_index("ix_document_retention_states_updated_by_user_id", table_name="document_retention_states")
    op.drop_index("ix_document_retention_states_document_id", table_name="document_retention_states")
    op.drop_index("ix_document_retention_states_tenant_id", table_name="document_retention_states")
    op.drop_table("document_retention_states")
    op.drop_index("ix_retention_rules_updated_at", table_name="retention_rules")
    op.drop_index("ix_retention_rules_updated_by_user_id", table_name="retention_rules")
    op.drop_index("ix_retention_rules_subject_type", table_name="retention_rules")
    op.drop_index("ix_retention_rules_tenant_id", table_name="retention_rules")
    op.drop_table("retention_rules")
