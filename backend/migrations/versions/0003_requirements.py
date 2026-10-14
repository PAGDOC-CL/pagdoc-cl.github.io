"""Add configurable document requirements.

Revision ID: 0003_requirements
Revises: 0002_user_mfa
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_requirements"
down_revision: Union[str, None] = "0002_user_mfa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("warning_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_requirements_tenant_id", "requirements", ["tenant_id"])

    op.create_table(
        "document_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.UniqueConstraint("document_id", name="uq_document_policies_document"),
    )
    op.create_index("ix_document_policies_tenant_id", "document_policies", ["tenant_id"])
    op.create_index("ix_document_policies_document_id", "document_policies", ["document_id"])
    op.create_index("ix_document_policies_requirement_id", "document_policies", ["requirement_id"])


def downgrade() -> None:
    op.drop_index("ix_document_policies_requirement_id", table_name="document_policies")
    op.drop_index("ix_document_policies_document_id", table_name="document_policies")
    op.drop_index("ix_document_policies_tenant_id", table_name="document_policies")
    op.drop_table("document_policies")
    op.drop_index("ix_requirements_tenant_id", table_name="requirements")
    op.drop_table("requirements")
