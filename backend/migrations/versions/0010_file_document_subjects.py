"""Bind private company/vehicle documents to their actual tenant/vehicle."""
from alembic import op
import sqlalchemy as sa

revision = '0010_file_subjects'
down_revision = '0009_operations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('file_document_subjects',
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id'), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('subject_kind', sa.String(20), nullable=False),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id'), nullable=True),
        sa.CheckConstraint("subject_kind IN ('company','vehicle')", name='ck_file_subject_kind'),
        sa.CheckConstraint("(subject_kind = 'company' AND vehicle_id IS NULL) OR (subject_kind = 'vehicle' AND vehicle_id IS NOT NULL)", name='ck_file_subject_vehicle'))
    op.create_index('ix_file_document_subjects_tenant_id','file_document_subjects',['tenant_id'])


def downgrade():
    op.drop_table('file_document_subjects')
