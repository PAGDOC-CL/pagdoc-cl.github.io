"""Allow 1024-character logical paths without oversized PostgreSQL index keys."""
import hashlib
import unicodedata
from alembic import op
import sqlalchemy as sa
revision='0018_long_file_paths'
down_revision='0017_file_worker_project'
branch_labels=None
depends_on=None


def normalized(path):
    return unicodedata.normalize('NFKC',path).strip().casefold()


def upgrade():
    bind=op.get_bind()
    with op.batch_alter_table('file_destinations') as batch:
        batch.drop_constraint('uq_file_destination',type_='unique')
    rows=bind.execute(sa.text('SELECT id,source_path FROM file_destinations')).all()
    for identity,path in rows:
        bind.execute(sa.text('UPDATE file_destinations SET path_key=:key WHERE id=:id'),{'id':identity,'key':hashlib.sha256(normalized(path).encode('utf-8')).hexdigest()})
    with op.batch_alter_table('file_destinations') as batch:
        batch.alter_column('path_key',existing_type=sa.String(500),type_=sa.String(64),existing_nullable=False)
        batch.alter_column('source_path',existing_type=sa.String(200),type_=sa.String(1024),existing_nullable=False)
        batch.create_unique_constraint('uq_file_destination',['tenant_id','subject_scope','path_key'])
    with op.batch_alter_table('documents') as batch:
        batch.alter_column('title',existing_type=sa.String(200),type_=sa.String(1024),existing_nullable=False)


def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT count(*) FROM documents WHERE length(title)>200')).scalar() or bind.execute(sa.text('SELECT count(*) FROM file_destinations WHERE length(source_path)>200')).scalar():
        raise RuntimeError('Cannot downgrade while long document paths exist; no data was truncated.')
    with op.batch_alter_table('file_destinations') as batch:
        batch.drop_constraint('uq_file_destination',type_='unique')
        batch.alter_column('path_key',existing_type=sa.String(64),type_=sa.String(500),existing_nullable=False)
        batch.alter_column('source_path',existing_type=sa.String(1024),type_=sa.String(200),existing_nullable=False)
    for identity,path in bind.execute(sa.text('SELECT id,source_path FROM file_destinations')).all():
        bind.execute(sa.text('UPDATE file_destinations SET path_key=:key WHERE id=:id'),{'id':identity,'key':normalized(path)})
    with op.batch_alter_table('file_destinations') as batch:
        batch.create_unique_constraint('uq_file_destination',['tenant_id','subject_scope','path_key'])
    with op.batch_alter_table('documents') as batch:
        batch.alter_column('title',existing_type=sa.String(1024),type_=sa.String(200),existing_nullable=False)
