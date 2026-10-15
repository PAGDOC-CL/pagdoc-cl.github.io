"""Per-version analysis results; never store extracted document bodies."""
from alembic import op
import sqlalchemy as sa
revision='0016_file_analyses'
down_revision='0015_service_kind'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('file_analyses',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('document_id',sa.Integer(),sa.ForeignKey('documents.id'),nullable=False),sa.Column('file_version_id',sa.Integer(),sa.ForeignKey('document_file_versions.id'),nullable=False,unique=True),sa.Column('status',sa.String(20),nullable=False),sa.Column('result_json',sa.Text(),nullable=False),sa.Column('claimed_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_file_analyses_tenant_id','file_analyses',['tenant_id'])
    op.create_index('ix_file_analyses_document_id','file_analyses',['document_id'])


def downgrade():
    op.drop_table('file_analyses')
