"""Preserve private file links while allowing explicit worker/project destinations."""
from alembic import op
import sqlalchemy as sa
revision='0017_file_worker_project'
down_revision='0016_file_analyses'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('file_document_subjects') as batch:
        batch.add_column(sa.Column('worker_id',sa.Integer(),sa.ForeignKey('workers.id',name='fk_file_subject_worker'),nullable=True))
        batch.drop_constraint('ck_file_subject_kind',type_='check')
        batch.drop_constraint('ck_file_subject_vehicle',type_='check')
        batch.create_check_constraint('ck_file_subject_kind',"subject_kind IN ('company','vehicle','worker','project')")
        batch.create_check_constraint('ck_file_subject_vehicle',"(subject_kind IN ('company','project') AND vehicle_id IS NULL AND worker_id IS NULL) OR (subject_kind = 'vehicle' AND vehicle_id IS NOT NULL AND worker_id IS NULL) OR (subject_kind = 'worker' AND worker_id IS NOT NULL AND vehicle_id IS NULL)")


def downgrade():
    # Refuse a downgrade that would discard worker/project links.
    count=op.get_bind().execute(sa.text("SELECT count(*) FROM file_document_subjects WHERE subject_kind IN ('worker','project')")).scalar()
    if count:raise RuntimeError('Cannot downgrade while worker/project files exist.')
    with op.batch_alter_table('file_document_subjects') as batch:
        batch.drop_constraint('ck_file_subject_kind',type_='check');batch.drop_constraint('ck_file_subject_vehicle',type_='check')
        batch.drop_constraint('fk_file_subject_worker',type_='foreignkey');batch.drop_column('worker_id')
        batch.create_check_constraint('ck_file_subject_kind',"subject_kind IN ('company','vehicle')")
        batch.create_check_constraint('ck_file_subject_vehicle',"(subject_kind = 'company' AND vehicle_id IS NULL) OR (subject_kind = 'vehicle' AND vehicle_id IS NOT NULL)")
