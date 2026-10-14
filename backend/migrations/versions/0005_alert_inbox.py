"""Add user-scoped internal alert preferences and acknowledgements.

Revision ID: 0005_alert_inbox
Revises: 0004_document_revisions
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_alert_inbox"
down_revision: Union[str, None] = "0004_document_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("include_expiring", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("include_expired", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_alert_preference_user"),
    )
    op.create_index("ix_alert_preferences_tenant_id", "alert_preferences", ["tenant_id"])
    op.create_index("ix_alert_preferences_user_id", "alert_preferences", ["user_id"])

    op.create_table(
        "alert_acknowledgements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("requirements.id"), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "document_id",
            "requirement_id",
            name="uq_alert_ack_user_document_requirement",
        ),
    )
    op.create_index("ix_alert_acknowledgements_tenant_id", "alert_acknowledgements", ["tenant_id"])
    op.create_index("ix_alert_acknowledgements_user_id", "alert_acknowledgements", ["user_id"])
    op.create_index("ix_alert_acknowledgements_document_id", "alert_acknowledgements", ["document_id"])
    op.create_index("ix_alert_acknowledgements_requirement_id", "alert_acknowledgements", ["requirement_id"])
    op.create_index("ix_alert_acknowledgements_acknowledged_at", "alert_acknowledgements", ["acknowledged_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_acknowledgements_acknowledged_at", table_name="alert_acknowledgements")
    op.drop_index("ix_alert_acknowledgements_requirement_id", table_name="alert_acknowledgements")
    op.drop_index("ix_alert_acknowledgements_document_id", table_name="alert_acknowledgements")
    op.drop_index("ix_alert_acknowledgements_user_id", table_name="alert_acknowledgements")
    op.drop_index("ix_alert_acknowledgements_tenant_id", table_name="alert_acknowledgements")
    op.drop_table("alert_acknowledgements")
    op.drop_index("ix_alert_preferences_user_id", table_name="alert_preferences")
    op.drop_index("ix_alert_preferences_tenant_id", table_name="alert_preferences")
    op.drop_table("alert_preferences")
