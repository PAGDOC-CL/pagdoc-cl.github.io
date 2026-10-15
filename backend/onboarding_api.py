"""One-time onboarding per private account, shared across browsers and roles."""
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
import app as core


class UserOnboarding(core.Base):
    __tablename__ = 'user_onboarding'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), index=True)
    shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))


class OnboardingStart(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    legacy_seen: bool = False


@core.app.post('/ops/onboarding/start')
def start_onboarding(data:OnboardingStart,user:core.Auth,_:core.Csrf,db:core.Db):
    if db.scalar(select(UserOnboarding).where(UserOnboarding.user_id==user.id,UserOnboarding.tenant_id==user.tenant_id)) is not None:
        return {'show_tutorial':False}
    db.add(UserOnboarding(user_id=user.id,tenant_id=user.tenant_id))
    try:
        db.flush()
        core.add_audit(db,user,'user.onboarding_seen','user',user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        return {'show_tutorial':False}
    return {'show_tutorial':not data.legacy_seen}
