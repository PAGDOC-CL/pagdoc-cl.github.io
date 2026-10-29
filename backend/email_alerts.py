"""Opt-in daily email summaries. Disabled until a private SMTP account is configured."""
import os
import smtplib
import ssl
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.headerregistry import Address
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

import app as core
from access_policy import capabilities
from operations_api import Task
from file_api import TenantBranding


class EmailPreference(core.Base):
    __tablename__ = 'email_preferences'
    __table_args__ = (UniqueConstraint('tenant_id','user_id',name='uq_email_preference_user'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True)
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    days_before: Mapped[int] = mapped_column(Integer, default=30)
    include_expiring: Mapped[int] = mapped_column(Integer, default=1)
    include_expired: Mapped[int] = mapped_column(Integer, default=1)
    include_overdue: Mapped[int] = mapped_column(Integer, default=1)


class EmailDispatch(core.Base):
    __tablename__ = 'email_dispatches'
    __table_args__ = (UniqueConstraint('tenant_id','user_id','send_date',name='uq_email_digest_day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    send_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default='attempting')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    days_before: int = Field(default=30, ge=1, le=90)
    include_expiring: bool = True
    include_expired: bool = True
    include_overdue: bool = True


def smtp_configured():
    mode=os.getenv('PAGDOC_SMTP_AUTH_MODE','password')
    if mode=='microsoft_oauth':
        from smtp_oauth import configured,HOST
        return os.getenv('PAGDOC_EMAIL_DELIVERY_ENABLED')=='1' and os.getenv('PAGDOC_SMTP_HOST')==HOST and os.getenv('PAGDOC_SMTP_PORT','587')=='587' and os.getenv('PAGDOC_SMTP_FROM')==os.getenv('PAGDOC_SMTP_USERNAME') and configured()
    if mode!='password':return False
    return os.getenv('PAGDOC_EMAIL_DELIVERY_ENABLED') == '1' and all(os.getenv(key) for key in ('PAGDOC_SMTP_HOST','PAGDOC_SMTP_USERNAME','PAGDOC_SMTP_PASSWORD','PAGDOC_SMTP_FROM')) and os.getenv('PAGDOC_SMTP_PORT','587') in {'465','587'}


def preference(db,user):
    return db.scalar(select(EmailPreference).where(EmailPreference.tenant_id == user.tenant_id,EmailPreference.user_id == user.id))


def preference_data(pref):
    return {'enabled':bool(pref.enabled) if pref else False,'days_before':pref.days_before if pref else 30,'include_expiring':bool(pref.include_expiring) if pref else True,'include_expired':bool(pref.include_expired) if pref else True,'include_overdue':bool(pref.include_overdue) if pref else True}


def digest_counts(db,user,pref,today):
    result={'expiring':0,'expired':0,'overdue_tasks':0,'missing_dates':0}
    allowed=capabilities(user.role)
    if 'documents.read' in allowed:
        query=select(core.Document.expires_on).where(core.Document.tenant_id==user.tenant_id,~core.Document.id.in_(select(TenantBranding.document_id)))
        for expiry in db.scalars(query):
            if expiry is None:result['missing_dates']+=1
            elif expiry<today and pref.include_expired:result['expired']+=1
            elif today<=expiry<=today+timedelta(days=pref.days_before) and pref.include_expiring:result['expiring']+=1
    if pref.include_overdue and 'tasks.read' in allowed:
        query=select(func.count()).select_from(Task).where(Task.tenant_id==user.tenant_id,Task.status!='done',Task.due_on<today)
        if user.role!='admin':query=query.where(Task.assignee_id==user.id)
        result['overdue_tasks']=db.scalar(query) or 0
    return result


@core.app.get('/ops/email-alerts')
def get_preferences(user:core.Auth,db:core.Db):
    pref=preference(db,user)
    last=db.scalar(select(EmailDispatch).where(EmailDispatch.tenant_id==user.tenant_id,EmailDispatch.user_id==user.id).order_by(EmailDispatch.id.desc()).limit(1))
    return {**preference_data(pref),'recipient':user.email,'delivery_configured':bool(smtp_configured()),'frequency':'daily','last_delivery':{'date':last.send_date,'status':last.status} if last else None}


@core.app.put('/ops/email-alerts')
def set_preferences(data:PreferenceIn,user:core.Auth,_:core.Csrf,db:core.Db):
    pref=preference(db,user)
    if pref is None:pref=EmailPreference(tenant_id=user.tenant_id,user_id=user.id);db.add(pref)
    for key,value in data.model_dump().items():setattr(pref,key,int(value) if isinstance(value,bool) else value)
    core.add_audit(db,user,'email.preference_update','user',user.id)
    db.commit()
    return get_preferences(user,db)


@core.app.get('/ops/email-alerts/preview')
def preview_digest(user:core.Auth,db:core.Db):
    pref=preference(db,user) or EmailPreference(**{**preference_data(None),'tenant_id':user.tenant_id,'user_id':user.id})
    today=datetime.now(ZoneInfo('America/Santiago')).date()
    return {'recipient':user.email,**digest_counts(db,user,pref,today),'delivery_configured':bool(smtp_configured()),'note':'Solo se consideran fechas de vencimiento registradas; no se infiere vigencia.'}


def smtp_send(recipient,counts,today):
    Address(addr_spec=recipient)
    sender=os.environ['PAGDOC_SMTP_FROM'];Address(addr_spec=sender)
    message=EmailMessage();message['From']=sender;message['To']=recipient
    message['Subject']='PAGDOC · Alertas de vencimientos y retrasos · '+today.isoformat()
    message.set_content(f"Resumen diario PAGDOC\n\nDocumentos próximos a vencer: {counts['expiring']}\nDocumentos vencidos: {counts['expired']}\nTareas atrasadas: {counts['overdue_tasks']}\n\nIngresa a tu plataforma privada para consultar los detalles. No se adjuntan documentos.\nLas fechas deben estar verificadas en cada registro. Puedes desactivar estos avisos en Mi seguridad.\n")
    send_message(message,recipient)


def send_message(message,recipient):
    sender=os.environ['PAGDOC_SMTP_FROM'];Address(addr_spec=sender);Address(addr_spec=recipient)
    host=os.environ['PAGDOC_SMTP_HOST'];port=int(os.getenv('PAGDOC_SMTP_PORT','587'));context=ssl.create_default_context()
    mode=os.getenv('PAGDOC_SMTP_AUTH_MODE','password')
    if mode not in {'password','microsoft_oauth'}:raise ValueError('Método SMTP inválido.')
    if mode=='microsoft_oauth':
        from smtp_oauth import HOST,access_token,authenticate
        if host!=HOST or port!=587 or sender!=os.environ['PAGDOC_SMTP_USERNAME']:raise ValueError('Configuración Microsoft OAuth inválida.')
        token=access_token(os.environ['PAGDOC_SMTP_USERNAME'])
    connection=smtplib.SMTP_SSL(host,port,timeout=30,context=context) if port==465 else smtplib.SMTP(host,port,timeout=30)
    with connection as smtp:
        if port==587:smtp.starttls(context=context)
        if mode=='microsoft_oauth':
            smtp.ehlo()
            authenticate(smtp,os.environ['PAGDOC_SMTP_USERNAME'],token)
        else:smtp.login(os.environ['PAGDOC_SMTP_USERNAME'],os.environ['PAGDOC_SMTP_PASSWORD'])
        smtp.send_message(message,from_addr=sender,to_addrs=[recipient])


def dispatch_one(db,user_id,today,send=smtp_send):
    if not smtp_configured():return 'disabled'
    user=db.get(core.User,user_id)
    if user is None or not user.active:return 'disabled'
    pref=preference(db,user)
    if pref is None or not pref.enabled:return 'disabled'
    counts=digest_counts(db,user,pref,today)
    if not any(counts[key] for key in ('expiring','expired','overdue_tasks')):return 'empty'
    row=EmailDispatch(tenant_id=user.tenant_id,user_id=user.id,send_date=today,status='attempting')
    db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();return 'already_attempted'
    # Commit the attempt before SMTP. An ambiguous disconnect is never retried
    # automatically on the same day, preventing accidental repeated messages.
    try:send(user.email,counts,today);row.status='sent'
    except Exception:row.status='unknown'
    core.add_audit(db,user,'email.auto_digest_'+row.status,'email_dispatch',row.id)
    db.commit()
    return row.status
