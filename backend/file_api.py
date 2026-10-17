"""Explicitly enabled company/vehicle files; authenticated, scoped, scanned and versioned."""
import asyncio
import hashlib
import os
import re
import threading
import unicodedata
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, func, or_, select, text
from sqlalchemy.orm import Mapped, mapped_column
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

import app as core
from file_gateway import GatewayError
from file_records import DocumentFileVersion, list_file_versions, read_file_version, store_new_file_version
from operations_api import owned, permit, review_state
from private_files import configured_gateway
from storage import EXTENSIONS, MAX_BYTES, StorageError


class FileSubject(core.Base):
    __tablename__ = 'file_document_subjects'
    __table_args__ = (CheckConstraint("subject_kind IN ('company','vehicle','worker','project')", name='ck_file_subject_kind'), CheckConstraint("(subject_kind IN ('company','project') AND vehicle_id IS NULL AND worker_id IS NULL) OR (subject_kind = 'vehicle' AND vehicle_id IS NOT NULL AND worker_id IS NULL) OR (subject_kind = 'worker' AND worker_id IS NOT NULL AND vehicle_id IS NULL)", name='ck_file_subject_vehicle'))
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), index=True)
    subject_kind: Mapped[str] = mapped_column(String(20))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey('vehicles.id'), nullable=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey('workers.id',name='fk_file_subject_worker'), nullable=True)


FileRead = Annotated[core.User, Depends(permit('documents.read'))]


def enabled() -> bool:
    return os.getenv('PAGDOC_BINARY_HTTP_ENABLED', '0') == '1'


def require_enabled():
    if not enabled():
        raise HTTPException(503, 'La carga y descarga privada todavía no está habilitada por el administrador del servidor.')


def gateway():
    try:
        return configured_gateway()
    except (KeyError, ValueError, OSError):
        raise HTTPException(503, 'El almacenamiento privado no está disponible.')


def scoped_document(db, user, document_id, *, lock=False):
    doc = owned(db, core.Document, user.tenant_id, document_id, lock)
    link = db.scalar(select(FileSubject).where(FileSubject.document_id == doc.id, FileSubject.tenant_id == user.tenant_id))
    if link is None:
        raise HTTPException(404, 'Documento privado no encontrado.')
    return doc, link


def latest_version(db, tenant_id, document_id):
    return db.scalar(select(func.max(DocumentFileVersion.version)).where(DocumentFileVersion.tenant_id == tenant_id, DocumentFileVersion.document_id == document_id)) or 0


@core.app.get('/ops/files/status')
def status(user: FileRead):
    ready = False
    if enabled():
        try:
            gateway().scanner.engine()
            ready = True
        except (ValueError, HTTPException, OSError):
            pass
    return {'enabled': enabled(), 'ready_for_upload': ready, 'max_bytes': MAX_BYTES, 'extensions': ['.pdf','.png','.jpg','.jpeg','.docx','.xlsx']}


@core.app.get('/ops/files/subjects')
def subjects(user: FileRead, db: core.Db):
    tenant = db.get(core.Tenant, user.tenant_id)
    vehicles = db.scalars(select(core.Vehicle).where(core.Vehicle.tenant_id == user.tenant_id, core.Vehicle.active == 1).order_by(core.Vehicle.id)).all()
    return {'company': tenant.name, 'vehicles': [{'id': v.id, 'label': v.label, 'plate': v.plate} for v in vehicles]}


class NewVehicle(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    label: str = Field(min_length=2, max_length=120)
    plate: str = Field(min_length=4, max_length=20)
    vehicle_type: str | None = Field(default=None, max_length=80)


@core.app.post('/ops/files/vehicles', status_code=201)
def create_vehicle(data: NewVehicle, user: core.Editor, db: core.Db):
    require_enabled()
    plate = re.sub(r'[ -]', '', data.plate.upper())
    if not re.fullmatch(r'[A-Z0-9]{4,12}', plate):
        raise HTTPException(422, 'Revisa la patente: usa entre 4 y 12 letras o números.')
    db.scalar(select(core.Tenant).where(core.Tenant.id == user.tenant_id).with_for_update())
    existing = db.scalars(select(core.Vehicle).where(core.Vehicle.tenant_id == user.tenant_id)).all()
    if any(re.sub(r'[ -]', '', (v.plate or '').upper()) == plate for v in existing):
        raise HTTPException(409, 'La patente ya está registrada. Selecciona el vehículo existente; no se fusionaron registros.')
    vehicle = core.Vehicle(tenant_id=user.tenant_id, label=data.label, plate=plate, vehicle_type=data.vehicle_type, active=1)
    db.add(vehicle)
    db.flush()
    core.add_audit(db, user, 'vehicle.private_create', 'vehicle', vehicle.id)
    db.commit()
    return {'id': vehicle.id, 'label': vehicle.label, 'plate': vehicle.plate}


class NewFileDocument(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=1024)
    subject_kind: Literal['company','vehicle','worker','project']
    vehicle_id: int | None = Field(default=None, gt=0)
    worker_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    expires_on: date | None = None
    @model_validator(mode='after')
    def binding(self):
        if (self.subject_kind == 'vehicle') != (self.vehicle_id is not None):
            raise ValueError('Selecciona un vehículo solo para documentos de vehículo.')
        if (self.subject_kind=='worker')!=(self.worker_id is not None) or (self.subject_kind=='project' and self.project_id is None):
            raise ValueError('Asigna explícitamente el trabajador o proyecto.')
        return self


@core.app.post('/ops/files/documents', status_code=201)
def create_document(data: NewFileDocument, user: core.Editor, db: core.Db):
    require_enabled()
    subject_name = db.get(core.Tenant, user.tenant_id).name
    if data.vehicle_id is not None:
        vehicle = owned(db, core.Vehicle, user.tenant_id, data.vehicle_id)
        if not vehicle.active:
            raise HTTPException(409, 'El vehículo está inactivo.')
        subject_name = vehicle.plate or vehicle.label
    if data.worker_id is not None:
        worker=owned(db,core.Worker,user.tenant_id,data.worker_id)
        if not worker.active:raise HTTPException(409,'El trabajador está inactivo.')
        subject_name=worker.full_name
    if data.project_id is not None:
        project=owned(db, core.Project, user.tenant_id, data.project_id)
        if not project.active:raise HTTPException(409,'El proyecto está inactivo.')
        if data.subject_kind=='project':subject_name=project.name
    doc = core.Document(tenant_id=user.tenant_id, title=data.title, subject_type=data.subject_kind, subject_name=subject_name, project_id=data.project_id, expires_on=data.expires_on)
    db.add(doc)
    db.flush()
    db.add(FileSubject(document_id=doc.id, tenant_id=user.tenant_id, subject_kind=data.subject_kind, vehicle_id=data.vehicle_id,worker_id=data.worker_id))
    core.add_audit(db, user, 'document.private_create', 'document', doc.id)
    db.commit()
    return {'id': doc.id, 'version': 0, 'review_state': 'pending'}


def document_expiry_status(doc,automatic,has_file,today):
    if automatic.get('validity_exempt') and has_file:return 'valid'
    if doc.expires_on is None:
        return 'valid' if automatic.get('no_expiry') and has_file else 'no_date'
    return 'expired' if doc.expires_on<today else 'expiring' if doc.expires_on<=today+timedelta(days=automatic.get('warning_days',30)) else 'valid'


@core.app.get('/ops/files/summary')
def document_summary(user:FileRead,db:core.Db):
    from document_analysis import FileAnalysis,analysis_payload
    today=datetime.now(ZoneInfo('America/Santiago')).date()
    latest=select(DocumentFileVersion.document_id,func.max(DocumentFileVersion.version).label('v')).where(DocumentFileVersion.tenant_id==user.tenant_id).group_by(DocumentFileVersion.document_id).subquery()
    rows=db.execute(select(core.Document,DocumentFileVersion.version,FileAnalysis).join(FileSubject,FileSubject.document_id==core.Document.id).join(latest,latest.c.document_id==core.Document.id).join(DocumentFileVersion,(DocumentFileVersion.document_id==core.Document.id)&(DocumentFileVersion.version==latest.c.v)).outerjoin(FileAnalysis,FileAnalysis.file_version_id==DocumentFileVersion.id).where(core.Document.tenant_id==user.tenant_id,FileSubject.tenant_id==user.tenant_id,DocumentFileVersion.tenant_id==user.tenant_id))
    counts={'valid':0,'expired':0,'expiring':0,'pending':0}
    for doc,version,row in rows:
        automatic=analysis_payload(row,doc,version)
        state=document_expiry_status(doc,automatic,True,today)
        counts['pending' if state=='no_date' else state]+=1
    return {'total':sum(counts.values()),'counts':counts,'as_of':today,'basis':'latest_uploaded_documents'}


class ArchiveDocumentIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(ge=0)
    reason:str=Field(min_length=5,max_length=300)
    confirmed:bool=False


def change_document_archive(document_id,data,user,db,restore=False):
    if len(data.reason.strip())<5:raise HTTPException(422,'Escribe un motivo de al menos 5 caracteres.')
    if not data.confirmed:raise HTTPException(422,'Confirma expresamente el documento y la acción.')
    doc=db.scalar(select(core.Document).where(core.Document.id==document_id,core.Document.tenant_id==user.tenant_id).execution_options(include_archived=True).with_for_update())
    link=db.scalar(select(FileSubject).where(FileSubject.document_id==document_id,FileSubject.tenant_id==user.tenant_id))
    if doc is None or link is None:raise HTTPException(404,'Documento privado no encontrado.')
    if bool(doc.archived_at)!=restore:raise HTTPException(409,'El estado del documento cambió. Actualiza la lista.')
    if latest_version(db,user.tenant_id,doc.id)!=data.expected_version:raise HTTPException(409,'La versión cambió. Revisa el archivo antes de confirmar.')
    from retention_api import DocumentRetentionState
    hold=db.scalar(select(DocumentRetentionState).where(DocumentRetentionState.document_id==doc.id,DocumentRetentionState.tenant_id==user.tenant_id))
    if not restore and hold and hold.legal_hold:raise HTTPException(409,'El documento tiene una protección de conservación activa.')
    bindings=db.scalars(select(FileDestination).where(FileDestination.document_id==doc.id,FileDestination.tenant_id==user.tenant_id)).all()
    for binding in bindings:
        key=destination_key(binding.source_path) if restore else hashlib.sha256(('archived:'+str(doc.id)+':'+binding.source_path).encode()).hexdigest()
        conflict=db.scalar(select(FileDestination.document_id).where(FileDestination.tenant_id==user.tenant_id,FileDestination.subject_scope==binding.subject_scope,FileDestination.path_key==key,FileDestination.document_id!=doc.id))
        if conflict is not None:raise HTTPException(409,'Otro documento ocupa ese destino. No se sobrescribirá al restaurar.')
        binding.path_key=key
    doc.archived_at=None if restore else datetime.now(ZoneInfo('UTC'))
    doc.archive_reason=None if restore else data.reason.strip()
    db.add(core.DocumentArchiveEvent(tenant_id=user.tenant_id,document_id=doc.id,user_id=user.id,action='restore' if restore else 'archive',reason=data.reason.strip()))
    core.add_audit(db,user,'document.restore' if restore else 'document.archive','document',doc.id)
    db.commit()
    return {'id':doc.id,'archived':not restore,'originals_preserved':True}


@core.app.post('/ops/files/documents/{document_id}/archive')
def archive_document(document_id:int,data:ArchiveDocumentIn,user:core.Editor,db:core.Db):
    return change_document_archive(document_id,data,user,db)


@core.app.post('/ops/files/documents/{document_id}/restore')
def restore_document(document_id:int,data:ArchiveDocumentIn,user:core.Editor,db:core.Db):
    return change_document_archive(document_id,data,user,db,restore=True)


@core.app.get('/ops/files/documents')
def documents(user: FileRead, db: core.Db, archived:bool=False, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), subject_kind: Literal['company','vehicle','worker','project'] | None = None,path_prefix:str|None=Query(default=None,max_length=1024),document_type:str|None=Query(default=None,max_length=40),folder_mode:bool=False,vehicle_id:int|None=Query(default=None,gt=0),worker_id:int|None=Query(default=None,gt=0),project_id:int|None=Query(default=None,gt=0)):
    query = select(core.Document, FileSubject).join(FileSubject, FileSubject.document_id == core.Document.id).where(core.Document.tenant_id == user.tenant_id, FileSubject.tenant_id == user.tenant_id)
    if archived:query=query.execution_options(include_archived=True).where(core.Document.archived_at.is_not(None))
    if subject_kind:
        query = query.where(FileSubject.subject_kind == subject_kind)
    if vehicle_id:query=query.where(FileSubject.vehicle_id==vehicle_id)
    if worker_id:query=query.where(FileSubject.worker_id==worker_id)
    if project_id:query=query.where(core.Document.project_id==project_id)
    if document_type:
        import json
        from document_analysis import FileAnalysis,TYPES
        if document_type not in TYPES:raise HTTPException(422,'Tipo documental no válido.')
        latest=select(DocumentFileVersion.document_id,func.max(DocumentFileVersion.version).label('v')).where(DocumentFileVersion.tenant_id==user.tenant_id).group_by(DocumentFileVersion.document_id).subquery()
        analyses=db.execute(select(FileAnalysis.document_id,FileAnalysis.result_json).join(DocumentFileVersion,DocumentFileVersion.id==FileAnalysis.file_version_id).join(latest,(latest.c.document_id==FileAnalysis.document_id)&(latest.c.v==DocumentFileVersion.version)).where(FileAnalysis.tenant_id==user.tenant_id)).all()
        matching=[identity for identity,result in analyses if json.loads(result).get('document_type','sin_clasificar')==document_type]
        condition=core.Document.id.in_(matching)
        if document_type=='sin_clasificar':condition=or_(condition,~core.Document.id.in_([identity for identity,_ in analyses]))
        query=query.where(condition)
    if path_prefix:
        destination_key(path_prefix.rstrip('/'))
        query=query.where(core.Document.title.startswith(path_prefix.rstrip('/')+'/',autoescape=True))
        if folder_mode:query=query.where(~func.substr(core.Document.title,len(path_prefix.rstrip('/'))+2).contains('/'))
    elif folder_mode:
        query=query.where(~core.Document.title.contains('/'))
    total = db.scalar(select(func.count()).select_from(query.subquery()).execution_options(include_archived=archived))
    rows = db.execute(query.order_by(core.Document.id.desc()).offset(offset).limit(limit).execution_options(include_archived=archived)).all()
    result = []
    for doc, link in rows:
        version = latest_version(db, user.tenant_id, doc.id)
        file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == doc.id, DocumentFileVersion.version == version))
        state, _, _ = review_state(db, doc)
        from document_analysis import current_analysis,analysis_payload
        automatic=analysis_payload(current_analysis(db,user,doc.id,version),doc,version)
        today=datetime.now(ZoneInfo('America/Santiago')).date()
        expiry_status=document_expiry_status(doc,automatic,bool(file),today)
        result.append({'archived_at':doc.archived_at,'archive_reason':doc.archive_reason,'analysis':automatic,'id': doc.id, 'title': doc.title, 'subject_kind': link.subject_kind, 'subject_name': doc.subject_name, 'vehicle_id': link.vehicle_id,'worker_id':link.worker_id,'project_id':doc.project_id, 'expires_on': doc.expires_on, 'expiry_status': expiry_status, 'version': version, 'review_state': state, 'file_name': file.original_name if file else None})
    core.add_audit(db, user, 'document.private_list', 'tenant', user.tenant_id)
    db.commit()
    return {'items': result, 'total': total, 'offset': offset, 'limit': limit}


def store_upload(db, user, document_id, expected_version, name, media_type, payload):
    doc,_ = scoped_document(db, user, document_id, lock=True)
    if latest_version(db, user.tenant_id, document_id) != expected_version:
        raise HTTPException(409, 'El archivo cambió. Actualiza la lista antes de cargar otra versión.')
    if expected_version>0:
        doc.expires_on=None  # A replacement cannot inherit the old file's validity.
    try:
        row = store_new_file_version(db, user, document_id, gateway(), name, media_type, payload)
    except GatewayError as exc:
        db.rollback()
        if 'scanner unavailable' in str(exc).lower():
            raise HTTPException(503, 'El antivirus no está disponible o no pudo completar el análisis. No se guardó el archivo.')
        raise HTTPException(422, 'Archivo rechazado por validación o análisis antimalware. No se guardó: ' + str(exc))
    return {'document_id': document_id, 'version': row.version, 'sha256': row.sha256, 'size_bytes': row.size_bytes, 'review_state': 'pending'}


async def receive_file_body(request, file_name):
    media_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if media_type not in EXTENSIONS:
        raise HTTPException(415, 'Tipo no admitido. Usa PDF, PNG, JPEG, DOCX o XLSX.')
    suffix = Path(file_name).suffix.lower()
    if suffix != EXTENSIONS[media_type] and not (media_type == 'image/jpeg' and suffix == '.jpeg'):
        raise HTTPException(422, 'El nombre y el tipo del archivo no coinciden.')
    try:
        declared = int(request.headers.get('content-length', '0'))
    except ValueError:
        raise HTTPException(400, 'Tamaño de carga inválido.')
    if declared < 0 or declared > MAX_BYTES:
        raise HTTPException(413, f'El límite por archivo es de {MAX_BYTES / 1048576:g} MiB.')
    payload = bytearray()
    try:
        async with asyncio.timeout(60):
            async for block in request.stream():
                if len(payload) + len(block) > MAX_BYTES:
                    raise HTTPException(413, 'El archivo excede el límite de carga.')
                payload.extend(block)
    except TimeoutError:
        raise HTTPException(408, 'La carga tardó demasiado. Intenta nuevamente.')
    except ClientDisconnect:
        raise HTTPException(400, 'La carga se interrumpió.')
    return media_type, bytes(payload)


async def receive_upload(document_id, request, user, db, file_name, expected_version):
    require_enabled()
    await run_in_threadpool(scoped_document, db, user, document_id)
    media_type, payload = await receive_file_body(request, file_name)
    return await run_in_threadpool(store_upload, db, user, document_id, expected_version, file_name, media_type, payload)


_upload_slots = threading.BoundedSemaphore(2)


@core.app.post('/ops/files/documents/{document_id}/versions', status_code=201)
async def upload(document_id: int, request: Request, user: core.Editor, db: core.Db, file_name: str = Query(min_length=1, max_length=160), expected_version: int = Query(ge=0)):
    if not _upload_slots.acquire(blocking=False):
        raise HTTPException(429, 'Hay dos cargas en curso. Espera y vuelve a intentarlo.')
    try:
        return await receive_upload(document_id, request, user, db, file_name, expected_version)
    finally:
        _upload_slots.release()


@core.app.get('/ops/files/documents/{document_id}/versions')
def versions(document_id: int, user: FileRead, db: core.Db):
    scoped_document(db, user, document_id)
    return list_file_versions(db, user, document_id)


@core.app.get('/ops/files/documents/{document_id}/versions/{version}/download')
def download(document_id: int, version: int, user: FileRead, db: core.Db):
    require_enabled()
    scoped_document(db, user, document_id)
    row = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == document_id, DocumentFileVersion.version == version))
    if row is None:
        raise HTTPException(404, 'Versión no encontrada.')
    filename, media_type = row.original_name, row.media_type
    try:
        payload = read_file_version(db, user, document_id, version, gateway())
    except (GatewayError, StorageError):
        raise HTTPException(503, 'No se pudo verificar la integridad del archivo almacenado.')
    return Response(payload, media_type=media_type, headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


class TenantBranding(core.Base):
    """One encrypted logo document per tenant; previous versions remain immutable."""
    __tablename__ = 'tenant_branding'
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), unique=True)
    login_visible: Mapped[int] = mapped_column(Integer, default=0, server_default='0')


@core.app.get('/ops/branding')
def branding(user: core.Auth, db: core.Db, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    row = db.get(TenantBranding, user.tenant_id)
    return {'logo_version': latest_version(db, user.tenant_id, row.document_id) if row else 0}


@core.app.get('/ops/branding/logo')
def branding_logo(user: core.Auth, db: core.Db):
    require_enabled()
    row = db.get(TenantBranding, user.tenant_id)
    if row is None:
        raise HTTPException(404, 'La empresa todavía no tiene un logo cargado.')
    version = latest_version(db, user.tenant_id, row.document_id)
    file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == row.document_id, DocumentFileVersion.version == version))
    if file is None or file.media_type not in {'image/png', 'image/jpeg'}:
        raise HTTPException(404, 'Logo no disponible.')
    try:
        payload = read_file_version(db, user, row.document_id, version, gateway())
    except (GatewayError, StorageError):
        raise HTTPException(503, 'No se pudo comprobar la integridad del logo.')
    return Response(payload, media_type=file.media_type, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Disposition': 'inline'})


def store_logo(db, user, file_name, media_type, payload, login_visible=False):
    db.scalar(select(core.Tenant).where(core.Tenant.id == user.tenant_id).with_for_update())
    row = db.get(TenantBranding, user.tenant_id)
    if row is None:
        doc = core.Document(tenant_id=user.tenant_id, title='Logo corporativo', subject_type='company', subject_name=db.get(core.Tenant, user.tenant_id).name)
        db.add(doc)
        db.flush()
        row = TenantBranding(tenant_id=user.tenant_id, document_id=doc.id)
        db.add(row)
        db.flush()
    row.login_visible = int(login_visible)
    core.add_audit(db, user, 'branding.login_publish' if login_visible else 'branding.private_update', 'tenant', user.tenant_id)
    try:
        file = store_new_file_version(db, user, row.document_id, gateway(), file_name, media_type, payload)
    except (GatewayError, HTTPException):
        db.rollback()
        raise HTTPException(422, 'No se guardó el logo: el almacenamiento o el análisis antimalware no pudieron validarlo. El logo anterior se conserva.')
    return {'logo_version': file.version}


@core.app.post('/ops/branding/logo', status_code=201)
async def upload_logo(request: Request, user: core.AdminWrite, db: core.Db, file_name: str = Query(min_length=1, max_length=160), login_visible: bool = False):
    require_enabled()
    media = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    suffix = Path(file_name).suffix.lower()
    if media not in {'image/png', 'image/jpeg'} or suffix not in ({'.png'} if media == 'image/png' else {'.jpg', '.jpeg'}):
        raise HTTPException(415, 'El logo debe ser PNG o JPEG. No se admiten SVG ni contenido activo.')
    if not _upload_slots.acquire(blocking=False):
        raise HTTPException(429, 'Hay dos cargas en curso. Espera y vuelve a intentarlo.')
    try:
        payload = bytearray()
        try:
            async with asyncio.timeout(60):
                async for block in request.stream():
                    if len(payload) + len(block) > 2 * 1024 * 1024:
                        raise HTTPException(413, 'El logo no puede superar 2 MiB.')
                    payload.extend(block)
        except TimeoutError:
            raise HTTPException(408, 'La carga tardó demasiado.')
        except ClientDisconnect:
            raise HTTPException(400, 'La carga se interrumpió.')
        return await run_in_threadpool(store_logo, db, user, file_name, media, bytes(payload), login_visible)
    finally:
        _upload_slots.release()


def login_branding_row(db):
    # Public presentation is explicitly opted into by an administrator. If multiple
    # tenants opt in, do not guess which company's identity to publish on this host.
    rows = db.scalars(select(TenantBranding).where(TenantBranding.login_visible == 1).limit(2)).all()
    return rows[0] if len(rows) == 1 else None


@core.app.get('/login/branding')
def login_branding(db: core.Db, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    row = login_branding_row(db)
    if not row:
        return {'logo_version': 0}
    return {'name': db.get(core.Tenant, row.tenant_id).name, 'logo_version': latest_version(db, row.tenant_id, row.document_id)}


@core.app.get('/login/branding/logo')
def login_branding_logo(db: core.Db):
    require_enabled()
    row = login_branding_row(db)
    if row is None:
        raise HTTPException(404, 'Logo de acceso no configurado.')
    file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == row.tenant_id, DocumentFileVersion.document_id == row.document_id).order_by(DocumentFileVersion.version.desc()).limit(1))
    if file is None or file.media_type not in {'image/png', 'image/jpeg'}:
        raise HTTPException(404, 'Logo no disponible.')
    try:
        payload = gateway().store.get(row.tenant_id, file.object_key)
        if len(payload) != file.size_bytes or hashlib.sha256(payload).hexdigest() != file.sha256:
            raise StorageError('Logo integrity mismatch')
    except StorageError:
        raise HTTPException(503, 'No se pudo comprobar la integridad del logo.')
    return Response(payload, media_type=file.media_type, headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff', 'Content-Disposition':'inline'})


class FileDestination(core.Base):
    """Stable tenant/subject/path identity for confirmed, versioned replacements."""
    __tablename__ = 'file_destinations'
    __table_args__ = (UniqueConstraint('tenant_id', 'subject_scope', 'path_key', name='uq_file_destination'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), index=True)
    subject_scope: Mapped[str] = mapped_column(String(40))
    path_key: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(String(1024))
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), unique=True)


def destination_key(path):
    normalized = unicodedata.normalize('NFKC', path).strip()
    if not normalized or len(path) > 1024 or '\\' in normalized or any(ord(c) < 32 or ord(c) == 127 for c in normalized) or any(part in {'', '.', '..'} for part in normalized.split('/')):
        raise HTTPException(422, 'Revisa la ruta del documento: hasta 1024 caracteres, sin rutas absolutas ni segmentos de navegación.')
    key = normalized.casefold()
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


class BatchEntry(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    path: str = Field(min_length=1, max_length=1024)
    subject_kind: Literal['company', 'vehicle','worker','project']
    vehicle_id: int | None = Field(default=None, gt=0)
    worker_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    @model_validator(mode='after')
    def binding(self):
        if (self.subject_kind == 'vehicle') != (self.vehicle_id is not None):
            raise ValueError('Asigna el vehículo correspondiente a este documento.')
        if (self.subject_kind=='worker')!=(self.worker_id is not None) or (self.subject_kind=='project' and self.project_id is None):
            raise ValueError('Asigna explícitamente el trabajador o proyecto.')
        return self


class BatchPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entries: list[BatchEntry] = Field(min_length=1, max_length=250)


def batch_target(db, user, entry):
    if entry.project_id is not None:
        project=owned(db,core.Project,user.tenant_id,entry.project_id)
        if not project.active:raise HTTPException(409,'El proyecto está inactivo.')
        if entry.subject_kind=='project':return 'project:'+str(project.id),project.name
    if entry.worker_id is not None:
        worker=owned(db,core.Worker,user.tenant_id,entry.worker_id)
        if not worker.active:raise HTTPException(409,'El trabajador está inactivo.')
        return 'worker:'+str(worker.id),worker.full_name
    if entry.vehicle_id is not None:
        vehicle = owned(db, core.Vehicle, user.tenant_id, entry.vehicle_id)
        if not vehicle.active:
            raise HTTPException(409, 'El vehículo está inactivo.')
        return 'vehicle:' + str(vehicle.id), vehicle.plate or vehicle.label
    return 'company', db.get(core.Tenant, user.tenant_id).name


def resolve_destination(db, user, entry):
    scope, name = batch_target(db, user, entry)
    key = destination_key(entry.path)
    destination = db.scalar(select(FileDestination).where(FileDestination.tenant_id == user.tenant_id, FileDestination.subject_scope == scope, FileDestination.path_key == key))
    if destination:
        doc, link = scoped_document(db, user, destination.document_id)
        if link.subject_kind != entry.subject_kind or link.vehicle_id != entry.vehicle_id or link.worker_id!=entry.worker_id or (entry.project_id is not None and doc.project_id!=entry.project_id):
            raise HTTPException(409, 'El destino del documento requiere revisión administrativa.')
        return doc, destination, name
    # Exact source paths remain distinct. Loose files uploaded into a selected
    # destination reuse a unique latest filename, including already bound files.
    latest = select(DocumentFileVersion.document_id, func.max(DocumentFileVersion.version).label('number')).where(DocumentFileVersion.tenant_id == user.tenant_id).group_by(DocumentFileVersion.document_id).subquery()
    match = core.Document.title == entry.path
    if '/' not in entry.path:
        match = or_(match, DocumentFileVersion.original_name == entry.path)
    query = select(core.Document).join(FileSubject, FileSubject.document_id == core.Document.id).outerjoin(latest, latest.c.document_id == core.Document.id).outerjoin(DocumentFileVersion, (DocumentFileVersion.document_id == core.Document.id) & (DocumentFileVersion.version == latest.c.number)).where(core.Document.tenant_id == user.tenant_id, FileSubject.tenant_id == user.tenant_id, FileSubject.subject_kind == entry.subject_kind, FileSubject.vehicle_id == entry.vehicle_id,FileSubject.worker_id==entry.worker_id, match).limit(2)
    if '/' in entry.path:query=query.where(~core.Document.id.in_(select(FileDestination.document_id)))
    if entry.project_id is not None:query=query.where(core.Document.project_id==entry.project_id)
    candidates = db.scalars(query).all()
    if len(candidates) > 1:
        raise HTTPException(409, 'Hay varios documentos posibles para «' + entry.path + '». Revisa los registros existentes antes de reemplazar.')
    doc=candidates[0] if candidates else None
    bound=db.scalar(select(FileDestination).where(FileDestination.tenant_id==user.tenant_id,FileDestination.document_id==doc.id,FileDestination.subject_scope==scope)) if doc else None
    return doc,bound,name


def destination_plan(db, user, entry):
    doc, destination, name = resolve_destination(db, user, entry)
    version = latest_version(db, user.tenant_id, doc.id) if doc else 0
    file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == doc.id, DocumentFileVersion.version == version)) if version else None
    status = 'identical' if file and file.sha256 == entry.sha256 else 'replace' if version else 'resume' if doc else 'new'
    return {'path': entry.path,'destination_path':destination.source_path if destination else doc.title if doc else entry.path, 'subject_kind': entry.subject_kind, 'vehicle_id': entry.vehicle_id,'worker_id':entry.worker_id,'project_id':entry.project_id, 'subject_name': name, 'document_id': doc.id if doc else None, 'expected_version': version, 'status': status}


@core.app.post('/ops/files/batch/preview')
def preview_batch(data: BatchPreview, user: core.Editor, db: core.Db):
    require_enabled()
    keys = [(entry.subject_kind, entry.vehicle_id,entry.worker_id,entry.project_id if entry.subject_kind=='project' else None, destination_key(entry.path)) for entry in data.entries]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, 'La carga contiene rutas repetidas para el mismo destino.')
    items = [destination_plan(db, user, entry) for entry in data.entries]
    identities=[item['document_id'] for item in items if item['document_id'] is not None]
    if len(identities)!=len(set(identities)):raise HTTPException(409,'Dos archivos apuntan al mismo documento existente. Selecciona una sola actualización por documento.')
    core.add_audit(db, user, 'document.batch_preview', 'tenant', user.tenant_id)
    db.commit()
    return {'items': items}


def store_batch_item(db, user, entry, expected_document_id, expected_version, allow_replace, media, payload):
    # Serialize a scoped path before resolving it, without taking the tenant
    # audit lock ahead of document locks used by ordinary attachment uploads.
    if db.get_bind().dialect.name == 'postgresql':
        identity = f'{user.tenant_id}:{entry.subject_kind}:{entry.vehicle_id}:{entry.worker_id}:{entry.project_id if entry.subject_kind=="project" else None}:{destination_key(entry.path)}'
        key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], 'big', signed=True)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
    doc, destination, name = resolve_destination(db, user, entry)
    if doc is not None:
        scoped_document(db, user, doc.id, lock=True)
    version = latest_version(db, user.tenant_id, doc.id) if doc else 0
    if (doc.id if doc else None) != expected_document_id or version != expected_version:
        raise HTTPException(409, 'El destino cambió después de la comprobación. Vuelve a comprobar y confirmar antes de guardar.')
    if version:
        file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == doc.id, DocumentFileVersion.version == version))
        if file.sha256 == hashlib.sha256(payload).hexdigest():
            return {'document_id': doc.id, 'version': version, 'status': 'identical'}
        if not allow_replace:
            raise HTTPException(409, 'Se necesita confirmar el reemplazo en destino. La versión anterior se conservará en el historial.')
    if doc is None:
        doc = core.Document(tenant_id=user.tenant_id, title=entry.path, subject_type=entry.subject_kind, subject_name=name,project_id=entry.project_id)
        db.add(doc);db.flush()
        db.add(FileSubject(document_id=doc.id, tenant_id=user.tenant_id, subject_kind=entry.subject_kind, vehicle_id=entry.vehicle_id,worker_id=entry.worker_id));db.flush()
    if destination is None:
        scope, _ = batch_target(db, user, entry)
        db.add(FileDestination(tenant_id=user.tenant_id, subject_scope=scope, path_key=destination_key(entry.path), source_path=entry.path, document_id=doc.id));db.flush()
    core.add_audit(db, user, 'document.batch_replace' if version else 'document.batch_create', 'document', doc.id)
    result = store_upload(db, user, doc.id, version, entry.path.rsplit('/', 1)[-1], media, payload)
    result['status'] = 'replaced' if version else 'created'
    return result


@core.app.post('/ops/files/batch/item', status_code=201)
async def upload_batch_item(request: Request, user: core.Editor, db: core.Db, path: str = Query(min_length=1, max_length=1024), subject_kind: Literal['company', 'vehicle','worker','project'] = 'company', vehicle_id: int | None = Query(default=None, gt=0),worker_id:int|None=Query(default=None,gt=0),project_id:int|None=Query(default=None,gt=0), expected_document_id: int | None = Query(default=None, gt=0), expected_version: int = Query(ge=0), allow_replace: bool = False):
    require_enabled()
    try:
        entry = BatchEntry(path=path, subject_kind=subject_kind, vehicle_id=vehicle_id,worker_id=worker_id,project_id=project_id, sha256='0' * 64)
    except ValueError:
        raise HTTPException(422, 'Revisa la empresa o el vehículo asignado al documento.')
    destination_key(entry.path)
    await run_in_threadpool(batch_target, db, user, entry)
    if not _upload_slots.acquire(blocking=False):
        raise HTTPException(429, 'Hay dos cargas en curso. Espera y vuelve a intentarlo.')
    try:
        media, payload = await receive_file_body(request, entry.path.rsplit('/', 1)[-1])
        return await run_in_threadpool(store_batch_item, db, user, entry, expected_document_id, expected_version, allow_replace, media, payload)
    finally:
        _upload_slots.release()


class DestinationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    paths:list[str]=Field(min_length=1,max_length=250)
    worker_choices:dict[Annotated[str,Field(max_length=1024)],Annotated[int,Field(strict=True,ge=0)]]=Field(default_factory=dict,max_length=250)


@core.app.post('/ops/files/batch/destinations')
def detect_destinations(data:DestinationRequest,user:core.Editor,db:core.Db):
    require_enabled()
    return destination_proposals(data.paths,user,db,data.worker_choices)


def destination_proposals(paths,user,db,worker_choices=None):
    worker_choices=worker_choices or {}
    vehicles=db.scalars(select(core.Vehicle).where(core.Vehicle.tenant_id==user.tenant_id)).all()
    workers=db.scalars(select(core.Worker).where(core.Worker.tenant_id==user.tenant_id)).all()
    projects=db.scalars(select(core.Project).where(core.Project.tenant_id==user.tenant_id,core.Project.active==1)).all()
    def clean_name(value):
        value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().casefold()
        return ' '.join(re.sub(r'[^a-z0-9]+',' ',value).split())
    company_name=db.get(core.Tenant,user.tenant_id).name
    results=[]
    for path in paths:
        destination_key(path)
        folders=path.rsplit('/',1)[0] if '/' in path else ''
        normalized=unicodedata.normalize('NFKD',folders).encode('ascii','ignore').decode().lower().replace('_',' ')
        tokens=re.findall(r'(?<![a-z0-9])[a-z]{2,4}[ -]?[0-9]{2,4}(?![a-z0-9])',normalized)
        plates={re.sub(r'[ -]','',token).upper() for token in tokens}
        matched=[v for v in vehicles if re.sub(r'[ -]','',(v.plate or '').upper()) in plates]
        segments={re.sub(r'^\d+\s+','',clean_name(part)) for part in folders.split('/')}
        matched_workers=[w for w in workers if clean_name(w.full_name) in segments]
        matched_projects=[p for p in projects if clean_name(p.name) in segments]
        excluded={'trabajadores','trabajador','personal','colaboradores','acreditacion','empresa','empresarial','examen','examenes','certificado','certificados','contrato','anexo','registro','entrega','elementos','proteccion','fotografia','fotografias','cursos','curso','documentos','documentacion','licencia','cedula','identidad','finiquito','cotizaciones','pago','salud','seguridad','prevencion','induccion','procedimiento','ocupacional','preocupacional','alcohol','drogas','riesgos','hoja','vida','capacitacion','capacitaciones','varios','varias','generales','general','mufas','chile','curriculum','vitae','difusion','procedimientos','trabajo','seguro','antecedentes','traslado','competencias','laborales','extintores','electrico'}
        person_candidates={}
        person_parts=[]
        workforce_seen=False
        folder_parts=folders.split('/')
        for position,segment in enumerate(folder_parts):
            words=clean_name(segment).split()
            if re.search(r'trabajador|personal|colaborador',clean_name(segment)):
                workforce_seen=True
            # A one-letter final initial is valid; category folders are not people.
            if workforce_seen and 2<=len(words)<=7 and not any(word in excluded or any(c.isdigit() for c in word) for word in words) and all(len(word)>=2 for word in words[:2]) and len(segment)<=150:
                person_parts.append((clean_name(segment),' '.join(segment.replace('_',' ').split()),'/'.join(folder_parts[:position+1])))
        hierarchy_warning=None
        if person_parts:
            root_key,root_name,_=person_parts[0]
            person_candidates[root_key]=root_name
            aliases=sorted({name for key,name,_ in person_parts[1:] if key!=root_key})
            if aliases:
                hierarchy_warning=f'Carpeta principal: {root_name}. Subcarpetas con otro nombre: '+', '.join(aliases)+'. Confirma que sus documentos pertenecen a la persona de la carpeta principal; el nombre de carpeta no verifica identidad.'
            # Never silently combine an existing different identity or an inactive root.
            descendant_keys={key for key,_,_ in person_parts[1:] if key!=root_key}
            conflicting_workers=[w for w in workers if clean_name(w.full_name) in descendant_keys]
            matched_workers=[w for w in workers if clean_name(w.full_name)==root_key]
        else:
            conflicting_workers=[]
        company=bool(re.search(r'\bempresa\b|\bcompany\b',normalized))
        worker=bool(re.search(r'trabajador|personal|colaborador',normalized))
        conflict=None
        if conflicting_workers and worker and not company and not matched and not plates and len(matched_projects)<=1:
            conflict_keys={clean_name(w.full_name) for w in conflicting_workers}
            scope=next(part_path for key,_,part_path in person_parts[1:] if key in conflict_keys)
            candidates={w.id:w for w in [*matched_workers,*conflicting_workers]}
            options=[{'worker_id':w.id,'name':w.full_name,'identifier':w.identifier,'active':bool(w.active)} for w in candidates.values()]
            if not matched_workers:options.insert(0,{'worker_id':0,'name':root_name,'identifier':None,'active':True,'create':True})
            choice=worker_choices.get(scope)
            selected=candidates.get(choice)
            if choice==0 and len(matched_workers)<=1 and (not matched_workers or matched_workers[0].active):
                conflicting_workers=[]
                selected_name=root_name
            elif selected is not None and selected.active:
                matched_workers=[selected];conflicting_workers=[];selected_name=selected.full_name
            else:
                conflict={'scope':scope,'options':options}
            if not conflicting_workers:
                hierarchy_warning=f'Destino elegido explícitamente para {scope}: {selected_name}. Se conservan las rutas originales; no se fusionan fichas ni se trasladan documentos existentes.'
        if conflicting_workers:
            result={'path':path,'status':'review','subject_kind':None,'vehicle_id':None,'reason':'Hay nombres de personas ya registradas en la misma rama. Selecciona el destinatario de sus documentos; no se fusionan las fichas.'}
            if conflict:result['worker_conflict']=conflict
        elif len(matched_workers)==1 and matched_workers[0].active and not matched and not company and len(matched_projects)<=1:
            result={'path':path,'status':'resolved','subject_kind':'worker','worker_id':matched_workers[0].id,'vehicle_id':None,'project_id':matched_projects[0].id if matched_projects else None,'subject_name':matched_workers[0].full_name}
        elif len(matched_projects)==1 and not matched and not matched_workers and not company and not worker:
            result={'path':path,'status':'resolved','subject_kind':'project','project_id':matched_projects[0].id,'worker_id':None,'vehicle_id':None,'subject_name':matched_projects[0].name}
        elif len(matched)==1 and len(plates)==1 and matched[0].active and not company and not worker and not matched_workers and not matched_projects:
            result={'path':path,'status':'resolved','subject_kind':'vehicle','vehicle_id':matched[0].id,'subject_name':matched[0].plate or matched[0].label}
        elif company and not matched and not worker and not plates and not matched_workers and not matched_projects:
            result={'path':path,'status':'resolved','subject_kind':'company','vehicle_id':None,'subject_name':company_name}
        elif not matched and len(plates)==1 and not company and not worker and not matched_workers and not matched_projects and re.search(r'vehicul|veihuc|fleet|arrendad',normalized) and re.fullmatch(r'(?:[A-Z]{4}[0-9]{2}|[A-Z]{2}[0-9]{4})',next(iter(plates))):
            plate=next(iter(plates))
            result={'path':path,'status':'vehicle_missing','subject_kind':None,'vehicle_id':None,'proposed_plate':plate,'proposed_label':'Vehículo '+plate,'reason':'Ficha de vehículo pendiente. Se puede crear junto a las demás con confirmación; no acredita el vehículo.'}
        elif worker and not company and not matched and not plates and not matched_workers and not matched_projects and len(person_candidates)==1:
            person_key,person_name=next(iter(person_candidates.items()))
            result={'path':path,'status':'worker_missing','subject_kind':None,'vehicle_id':None,'proposed_worker_name':person_name,'proposed_worker_key':person_key,'reason':'Ficha operacional propuesta desde la carpeta; requiere confirmar identidad. No crea usuario ni acredita.'}
        else:
            result={'path':path,'status':'review','subject_kind':None,'vehicle_id':None,'reason':'Destino ambiguo, patente inactiva o sin identidad reconocible. Revisa la carpeta; no se asigna por aproximación.'}
        if hierarchy_warning and result['status']!='review':result['hierarchy_warning']=hierarchy_warning
        results.append(result)
    return {'items':results,'note':'La detección usa empresa explícita, patentes o nombres completos de trabajadores y proyectos registrados. Las coincidencias ambiguas requieren revisión.'}


class RegisterFolderVehicles(DestinationRequest):
    confirmed:Literal[True]


@core.app.post('/ops/files/batch/vehicles')
def register_folder_vehicles(data:RegisterFolderVehicles,user:core.Editor,db:core.Db):
    require_enabled()
    # Serialize with manual registration; retries reuse the tenant's exact plate.
    db.scalar(select(core.Tenant).where(core.Tenant.id==user.tenant_id).with_for_update())
    proposals=destination_proposals(data.paths,user,db,data.worker_choices)['items']
    if any(item['status']=='review' for item in proposals):
        raise HTTPException(409,'Hay destinos ambiguos o vehículos inactivos. No se crearon fichas en este grupo.')
    pending={item['proposed_plate']:item for item in proposals if item['status']=='vehicle_missing'}
    created=[]
    for plate,item in sorted(pending.items()):
        vehicle=core.Vehicle(tenant_id=user.tenant_id,label=item['proposed_label'],plate=plate,active=1)
        db.add(vehicle);db.flush()
        core.add_audit(db,user,'vehicle.folder_create','vehicle',vehicle.id)
        created.append({'id':vehicle.id,'plate':plate,'label':vehicle.label})
    db.commit()
    return {'created':created,'created_count':len(created),'note':'Solo fichas operacionales; sin acreditación ni aprobación automática.'}


@core.app.post('/ops/files/batch/subjects')
def register_folder_subjects(data:RegisterFolderVehicles,user:core.Editor,db:core.Db):
    require_enabled()
    db.scalar(select(core.Tenant).where(core.Tenant.id==user.tenant_id).with_for_update())
    proposals=destination_proposals(data.paths,user,db,data.worker_choices)['items']
    if any(item['status']=='review' for item in proposals):raise HTTPException(409,'Hay destinos ambiguos o inactivos. No se crearon fichas en este grupo.')
    pending={('worker',item['proposed_worker_key']) if item['status']=='worker_missing' else ('vehicle',item['proposed_plate']):item for item in proposals if item['status'] in {'vehicle_missing','worker_missing'}}
    created=[]
    for (kind,key),item in sorted(pending.items()):
        if kind=='worker':record=core.Worker(tenant_id=user.tenant_id,full_name=item['proposed_worker_name'],active=1)
        else:record=core.Vehicle(tenant_id=user.tenant_id,label=item['proposed_label'],plate=item['proposed_plate'],active=1)
        db.add(record);db.flush();core.add_audit(db,user,kind+'.folder_create',kind,record.id)
        created.append({'kind':kind,'id':record.id,'label':record.full_name if kind=='worker' else record.plate})
    db.commit()
    return {'created':created,'created_count':len(created),'note':'Solo fichas operacionales, sin crear cuentas, enviar invitaciones o acreditar.'}


@core.app.get('/ops/files/folders')
def folders(user:FileRead,db:core.Db,subject_kind:Literal['company','vehicle','worker','project']|None=None,vehicle_id:int|None=Query(default=None,gt=0),worker_id:int|None=Query(default=None,gt=0),project_id:int|None=Query(default=None,gt=0)):
    query=select(core.Document,FileSubject).join(FileSubject,FileSubject.document_id==core.Document.id).where(core.Document.tenant_id==user.tenant_id,FileSubject.tenant_id==user.tenant_id)
    if subject_kind:query=query.where(FileSubject.subject_kind==subject_kind)
    if vehicle_id:query=query.where(FileSubject.vehicle_id==vehicle_id)
    if worker_id:query=query.where(FileSubject.worker_id==worker_id)
    if project_id:query=query.where(core.Document.project_id==project_id)
    counts={};destinations={}
    for doc,link in db.execute(query).all():
        identity=link.vehicle_id if link.subject_kind=='vehicle' else link.worker_id if link.subject_kind=='worker' else doc.project_id if link.subject_kind=='project' else None
        key=link.subject_kind+(':'+str(identity) if identity else '')
        label=doc.subject_name
        if link.subject_kind=='vehicle' and key not in destinations:
            vehicle=db.get(core.Vehicle,link.vehicle_id)
            label=vehicle.plate or vehicle.label
        destination=destinations.setdefault(key,{'key':key,'subject_kind':link.subject_kind,'subject_id':identity,'label':label,'count':0})
        destination['count']+=1
        parts=doc.title.split('/')[:-1]
        for index in range(1,len(parts)+1):
            path='/'.join(parts[:index]);counts[path]=counts.get(path,0)+1
    return {'folders':[{'path':path,'count':counts[path]} for path in sorted(counts)],'destinations':sorted(destinations.values(),key=lambda item:(item['subject_kind'],item['label']))}
