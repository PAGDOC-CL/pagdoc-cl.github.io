"""Tenant logo references; binary content stays in encrypted private storage."""
from alembic import op
import sqlalchemy as sa

revision = '0011_tenant_branding'
down_revision = '0010_file_subjects'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tenant_branding',
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), primary_key=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=False, unique=True),
        sa.Column('login_visible', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_table('tenant_branding')
