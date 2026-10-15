"""Track policy versions so the worker can revisit existing document analyses."""
from alembic import op
import sqlalchemy as sa
revision='0019_analysis_rules'
down_revision='0018_long_file_paths'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('file_analyses') as batch:
        batch.add_column(sa.Column('rules_version',sa.Integer(),nullable=False,server_default='1'))


def downgrade():
    with op.batch_alter_table('file_analyses') as batch:batch.drop_column('rules_version')
