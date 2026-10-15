"""Require temporary passwords to be changed before accessing platform data."""
from alembic import op
import sqlalchemy as sa
revision='0021_temporary_password'
down_revision='0020_password_recovery'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('password_change_required',sa.Integer(),nullable=False,server_default='0'))
        batch.add_column(sa.Column('temporary_password_expires_at',sa.DateTime(timezone=True),nullable=True))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('temporary_password_expires_at');batch.drop_column('password_change_required')
