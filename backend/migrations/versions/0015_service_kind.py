"""Classify services without guessing the category of existing records."""
from alembic import op
import sqlalchemy as sa
revision='0015_service_kind'
down_revision='0014_user_onboarding'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('services',sa.Column('service_kind',sa.String(20),nullable=False,server_default='unclassified'))


def downgrade():
    op.drop_column('services','service_kind')
