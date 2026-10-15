"""Opt-in email preferences and a daily delivery ledger."""
from alembic import op
import sqlalchemy as sa
revision='0013_email_alerts'
down_revision='0012_file_destinations'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('email_preferences',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False,unique=True),sa.Column('enabled',sa.Integer(),nullable=False),sa.Column('days_before',sa.Integer(),nullable=False),sa.Column('include_expiring',sa.Integer(),nullable=False),sa.Column('include_expired',sa.Integer(),nullable=False),sa.Column('include_overdue',sa.Integer(),nullable=False),sa.UniqueConstraint('tenant_id','user_id',name='uq_email_preference_user'))
    op.create_index('ix_email_preferences_tenant_id','email_preferences',['tenant_id'])
    op.create_table('email_dispatches',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('send_date',sa.Date(),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('tenant_id','user_id','send_date',name='uq_email_digest_day'))
    op.create_index('ix_email_dispatches_tenant_id','email_dispatches',['tenant_id']);op.create_index('ix_email_dispatches_user_id','email_dispatches',['user_id'])

def downgrade():
    op.drop_table('email_dispatches');op.drop_table('email_preferences')
