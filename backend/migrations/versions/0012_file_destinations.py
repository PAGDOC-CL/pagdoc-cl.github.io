"""Stable scoped paths for warned replacements and duplicate suppression."""
from alembic import op
import sqlalchemy as sa
revision = '0012_file_destinations'
down_revision = '0011_tenant_branding'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('file_destinations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('subject_scope', sa.String(40), nullable=False),
        sa.Column('path_key', sa.String(500), nullable=False),
        sa.Column('source_path', sa.String(200), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=False, unique=True),
        sa.UniqueConstraint('tenant_id','subject_scope','path_key',name='uq_file_destination'))
    op.create_index('ix_file_destinations_tenant_id','file_destinations',['tenant_id'])

def downgrade():
    op.drop_table('file_destinations')
