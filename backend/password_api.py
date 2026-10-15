"""Self-service password changes and single-use recovery, without automatic login."""
import os
import secrets
from datetime import datetime,timedelta,timezone
from email.headerregistry import Address
from email.message import EmailMessage
from urllib.parse import urlsplit

from fastapi import BackgroundTasks,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import DateTime,ForeignKey,String,func,select,update
from sqlalchemy.orm import Mapped,mapped_column
import app as core
import email_alerts
from password_policy import MESSAGE,valid_password


class PasswordRecovery(core.Base):
    __tablename__='password_recoveries'
    id:Mapped[int]=mapped_column(primary_key=True)
    tenant_id:Mapped[int]=mapped_column(ForeignKey('tenants.id'),index=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    token_hash:Mapped[str]=mapped_column(String(64),unique=True,index=True)
    credential_hash:Mapped[str]=mapped_column(String(64))
    email_hash:Mapped[str]=mapped_column(String(64))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    used_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    delivery_status:Mapped[str]=mapped_column(String(20),default='pending')


class PasswordAttempt(core.Base):
    __tablename__='password_attempts'
    id:Mapped[int]=mapped_column(primary_key=True)
    scope:Mapped[str]=mapped_column(String(30),index=True)
    identity_hash:Mapped[str]=mapped_column(String(64),index=True)
    ip_hash:Mapped[str]=mapped_column(String(64),index=True)
    occurred_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)


class ForgotIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email:str=Field(min_length=3,max_length=255)


class ChangeIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    current_password:str=Field(min_length=1,max_length=1024)
    new_password:str=Field(min_length=1,max_length=1024)
    otp:str|None=Field(default=None,max_length=8)


class RecoverIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=32,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')
    new_password:str=Field(min_length=1,max_length=1024)


def now():return datetime.now(timezone.utc)


def rate_limit(db,request,scope,identity,per_identity=5,per_ip=20):
    cutoff=now()-timedelta(minutes=15)
    ip=core._client_hash(request);identity_hash=core._sha256(identity)
    base=select(func.count(PasswordAttempt.id)).where(PasswordAttempt.scope==scope,PasswordAttempt.occurred_at>=cutoff)
    if (db.scalar(base.where(PasswordAttempt.identity_hash==identity_hash)) or 0)>=per_identity or (db.scalar(base.where(PasswordAttempt.ip_hash==ip)) or 0)>=per_ip:
        raise HTTPException(429,'Demasiados intentos. Espera 15 minutos antes de volver a intentarlo.')
    db.add(PasswordAttempt(scope=scope,identity_hash=identity_hash,ip_hash=ip,occurred_at=now()));db.commit()


def policy(password):
    if not valid_password(password):raise HTTPException(422,MESSAGE)


def recovery_url():
    # Never build security links from Host, Origin, or user-supplied redirect URLs.
    value=os.getenv('PAGDOC_PASSWORD_RESET_URL','https://localhost:8443/app')
    try:parts=urlsplit(value)
    except ValueError:return None
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path!='/app':return None
    return value


def close_sessions(db,user,response,action):
    user.password_change_required=0;user.temporary_password_expires_at=None
    core.revoke_user_sessions(db,user.id)
    db.execute(update(PasswordRecovery).where(PasswordRecovery.user_id==user.id,PasswordRecovery.used_at.is_(None)).values(used_at=now()))
    core.add_audit(db,user,action,'user',user.id);db.commit()
    response.delete_cookie('pagdoc_session',path='/',secure=True,httponly=True,samesite='strict')
    response.delete_cookie('pagdoc_csrf',path='/',secure=True,samesite='strict')
    return {'password_changed':True,'sessions_revoked':True,'sign_in_required':True}


def send_recovery(recovery_id,token):
    # Plaintext token lives only in this task, never in database, logs, or API output.
    with core.SessionLocal() as db:
        row=db.get(PasswordRecovery,recovery_id)
        if row is None:return
        user=db.get(core.User,row.user_id)
        if not user or not user.active or row.used_at or row.expires_at.replace(tzinfo=timezone.utc)<=now() or core._sha256(user.email)!=row.email_hash or core._sha256(user.password_hash)!=row.credential_hash:return
        row.delivery_status='attempting';db.commit()
        try:
            url=recovery_url()
            if not url or not email_alerts.smtp_configured():raise ValueError('Delivery unavailable')
            message=EmailMessage();message['From']=os.environ['PAGDOC_SMTP_FROM'];message['To']=user.email
            Address(addr_spec=user.email);Address(addr_spec=message['From'])
            message['Subject']='PAGDOC · Restablecer tu contraseña'
            message.set_content('Recibimos una solicitud para restablecer tu contraseña de PAGDOC.\n\nAbre este enlace en el equipo donde utilizas tu plataforma privada:\n'+url+'#restablecer='+token+'\n\nEl enlace vence en 30 minutos y solo puede usarse una vez. Si no solicitaste el cambio, ignora este mensaje. No compartas este enlace. Nunca enviamos contraseñas por correo. Tu segundo factor, si existe, se mantiene activo.\n')
            email_alerts.send_message(message,user.email)
            row.delivery_status='sent'
        except Exception:row.delivery_status='failed'
        core.add_audit(db,user,'auth.recovery_'+row.delivery_status,'user',user.id);db.commit()


@core.app.post('/auth/password/forgot',status_code=202)
def forgot(data:ForgotIn,request:Request,tasks:BackgroundTasks,db:core.Db):
    email=data.email.strip().lower()
    rate_limit(db,request,'recovery_request',email)
    if not email_alerts.smtp_configured() or not recovery_url():raise HTTPException(503,'La recuperación por correo está pendiente de configurar en el servidor privado. Puedes cambiar tu contraseña desde Mi seguridad si puedes iniciar sesión.')
    token=secrets.token_urlsafe(48)
    user=db.scalar(select(core.User).where(core.User.email==email,core.User.active==1).with_for_update())
    if user:
        db.execute(update(PasswordRecovery).where(PasswordRecovery.user_id==user.id,PasswordRecovery.used_at.is_(None)).values(used_at=now()))
        row=PasswordRecovery(tenant_id=user.tenant_id,user_id=user.id,token_hash=core._sha256(token),credential_hash=core._sha256(user.password_hash),email_hash=core._sha256(user.email),created_at=now(),expires_at=now()+timedelta(minutes=30),delivery_status='pending')
        db.add(row);db.flush();recovery_id=row.id
        core.add_audit(db,user,'auth.recovery_requested','user',user.id);db.commit()
        tasks.add_task(send_recovery,recovery_id,token)
    return {'message':'Si el correo corresponde a una cuenta activa, recibirás un enlace para restablecer la contraseña. Revisa también correo no deseado.'}


@core.app.post('/auth/password/change')
def change(data:ChangeIn,request:Request,response:Response,user:core.Auth,_:core.Csrf,db:core.Db):
    rate_limit(db,request,'password_change',str(user.id))
    user=db.scalar(select(core.User).where(core.User.id==user.id).with_for_update())
    if not core.hasher.verify(data.current_password,user.password_hash):raise HTTPException(400,'La contraseña actual no es correcta.')
    if user.mfa_enabled and (not user.mfa_secret_enc or not data.otp or not core.pyotp.TOTP(core._decrypt_mfa(user.mfa_secret_enc)).verify(data.otp,valid_window=1)):raise HTTPException(400,'Revisa el código de tu segundo factor.')
    policy(data.new_password)
    if core.hasher.verify(data.new_password,user.password_hash):raise HTTPException(422,'Elige una contraseña diferente de la actual.')
    user.password_hash=core.hasher.hash(data.new_password)
    return close_sessions(db,user,response,'auth.password_changed')


@core.app.post('/auth/password/reset')
def recover(data:RecoverIn,request:Request,response:Response,db:core.Db):
    rate_limit(db,request,'password_recovery',core._sha256(data.token),per_identity=10,per_ip=30)
    row=db.scalar(select(PasswordRecovery).where(PasswordRecovery.token_hash==core._sha256(data.token)))
    invalid='El enlace no es válido, ya se utilizó o venció. Solicita uno nuevo.'
    if row is None:raise HTTPException(400,invalid)
    user=db.scalar(select(core.User).where(core.User.id==row.user_id).with_for_update())
    db.refresh(row)
    if not user or not user.active or user.tenant_id!=row.tenant_id or row.used_at or row.expires_at.replace(tzinfo=timezone.utc)<=now() or core._sha256(user.email)!=row.email_hash or core._sha256(user.password_hash)!=row.credential_hash:raise HTTPException(400,invalid)
    policy(data.new_password)
    if core.hasher.verify(data.new_password,user.password_hash):raise HTTPException(422,'Elige una contraseña diferente de la actual.')
    user.password_hash=core.hasher.hash(data.new_password)
    return close_sessions(db,user,response,'auth.password_recovered')



@core.app.post('/users/{user_id}/temporary-password')
def temporary_password(user_id:int,user:core.AdminWrite,db:core.Db):
    if user_id==user.id:raise HTTPException(409,'Para tu propia cuenta usa Cambiar mi contraseña en Mi seguridad.')
    target=db.scalar(select(core.User).where(core.User.id==user_id,core.User.tenant_id==user.tenant_id).with_for_update())
    if target is None:raise HTTPException(404,'Usuario no disponible.')
    if not target.active:raise HTTPException(409,'Activa el usuario antes de generar una clave temporal.')
    # Guaranteed policy compliance, with 192 random bits; the cleartext is returned once.
    password=secrets.token_urlsafe(24)+'Aa1!'
    target.password_hash=core.hasher.hash(password);target.password_change_required=1
    target.temporary_password_expires_at=now()+timedelta(hours=24)
    core.revoke_user_sessions(db,target.id)
    db.execute(update(PasswordRecovery).where(PasswordRecovery.user_id==target.id,PasswordRecovery.used_at.is_(None)).values(used_at=now()))
    core.add_audit(db,user,'user.temporary_password_created','user',target.id);db.commit()
    return {'id':target.id,'email':target.email,'temporary_password':password,'expires_at':target.temporary_password_expires_at,'password_change_required':True,'sessions_revoked':True}
