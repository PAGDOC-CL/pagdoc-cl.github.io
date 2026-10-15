"""Remember the first tutorial presentation per account."""
from alembic import op
import sqlalchemy as sa
revision='0014_user_onboarding'
down_revision='0013_email_alerts'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('user_onboarding',sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),primary_key=True),sa.Column('tenant_id',sa.Integer(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('shown_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_user_onboarding_tenant_id','user_onboarding',['tenant_id'])


def downgrade():
    op.drop_table('user_onboarding')
