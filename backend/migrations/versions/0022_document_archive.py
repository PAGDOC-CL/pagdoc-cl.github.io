"""Reversible document removal with retained originals and audit history."""
from alembic import op
import sqlalchemy as sa
revision='0022_document_archive'
down_revision='0021_temporary_password'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('archived_at',sa.DateTime(timezone=True),nullable=True))
        batch.add_column(sa.Column('archive_reason',sa.String(300),nullable=True))

    op.create_table('document_archive_events',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('tenant_id',sa.Integer(),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('document_id',sa.Integer(),sa.ForeignKey('documents.id'),nullable=False),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('action',sa.String(10),nullable=False),
        sa.Column('reason',sa.String(300),nullable=False),
        sa.Column('at',sa.DateTime(timezone=True),nullable=False))


def downgrade():
    connection=op.get_bind()
    if connection.execute(sa.text('SELECT count(*) FROM document_archive_events')).scalar() or connection.execute(sa.text('SELECT count(*) FROM documents WHERE archived_at IS NOT NULL')).scalar():
        raise RuntimeError('Archive history would be lost; restore or export records before downgrade.')
    op.drop_table('document_archive_events')
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('archive_reason');batch.drop_column('archived_at')
