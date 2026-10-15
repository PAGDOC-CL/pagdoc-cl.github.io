"""Single-use password recovery and bounded authentication attempts."""
from alembic import op
import sqlalchemy as sa
revision='0020_password_recovery'
down_revision='0019_analysis_rules'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('password_recoveries',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('tenant_id',sa.Integer(),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('token_hash',sa.String(64),nullable=False),sa.Column('credential_hash',sa.String(64),nullable=False),sa.Column('email_hash',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('used_at',sa.DateTime(timezone=True),nullable=True),sa.Column('delivery_status',sa.String(20),nullable=False))
    for name in ['tenant_id','user_id','token_hash','expires_at']:op.create_index('ix_password_recoveries_'+name,'password_recoveries',[name],unique=name=='token_hash')
    op.create_table('password_attempts',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('scope',sa.String(30),nullable=False),sa.Column('identity_hash',sa.String(64),nullable=False),sa.Column('ip_hash',sa.String(64),nullable=False),sa.Column('occurred_at',sa.DateTime(timezone=True),nullable=False))
    for name in ['scope','identity_hash','ip_hash','occurred_at']:op.create_index('ix_password_attempts_'+name,'password_attempts',[name])


def downgrade():
    op.drop_table('password_attempts');op.drop_table('password_recoveries')
