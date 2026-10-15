"""Explicitly enabled company/vehicle files; authenticated, scoped, scanned and versioned."""
import asyncio
import hashlib
import os
import re
import threading
import unicodedata
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, func, or_, select
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
    __table_args__ = (CheckConstraint("subject_kind IN ('company','vehicle')", name='ck_file_subject_kind'), CheckConstraint("(subject_kind = 'company' AND vehicle_id IS NULL) OR (subject_kind = 'vehicle' AND vehicle_id IS NOT NULL)", name='ck_file_subject_vehicle'))
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey('tenants.id'), index=True)
    subject_kind: Mapped[str] = mapped_column(String(20))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey('vehicles.id'), nullable=True)


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
    title: str = Field(min_length=2, max_length=200)
    subject_kind: Literal['company','vehicle']
    vehicle_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    expires_on: date | None = None
    @model_validator(mode='after')
    def binding(self):
        if (self.subject_kind == 'vehicle') != (self.vehicle_id is not None):
            raise ValueError('Selecciona un vehículo solo para documentos de vehículo.')
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
    if data.project_id is not None:
        owned(db, core.Project, user.tenant_id, data.project_id)
    doc = core.Document(tenant_id=user.tenant_id, title=data.title, subject_type=data.subject_kind, subject_name=subject_name, project_id=data.project_id, expires_on=data.expires_on)
    db.add(doc)
    db.flush()
    db.add(FileSubject(document_id=doc.id, tenant_id=user.tenant_id, subject_kind=data.subject_kind, vehicle_id=data.vehicle_id))
    core.add_audit(db, user, 'document.private_create', 'document', doc.id)
    db.commit()
    return {'id': doc.id, 'version': 0, 'review_state': 'pending'}


@core.app.get('/ops/files/documents')
def documents(user: FileRead, db: core.Db, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), subject_kind: Literal['company','vehicle'] | None = None):
    query = select(core.Document, FileSubject).join(FileSubject, FileSubject.document_id == core.Document.id).where(core.Document.tenant_id == user.tenant_id, FileSubject.tenant_id == user.tenant_id)
    if subject_kind:
        query = query.where(FileSubject.subject_kind == subject_kind)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(core.Document.id.desc()).offset(offset).limit(limit)).all()
    result = []
    for doc, link in rows:
        version = latest_version(db, user.tenant_id, doc.id)
        file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == doc.id, DocumentFileVersion.version == version))
        state, _, _ = review_state(db, doc)
        result.append({'id': doc.id, 'title': doc.title, 'subject_kind': link.subject_kind, 'subject_name': doc.subject_name, 'vehicle_id': link.vehicle_id, 'expires_on': doc.expires_on, 'expiry_status': core.doc_state(doc), 'version': version, 'review_state': state, 'file_name': file.original_name if file else None})
    core.add_audit(db, user, 'document.private_list', 'tenant', user.tenant_id)
    db.commit()
    return {'items': result, 'total': total, 'offset': offset, 'limit': limit}


def store_upload(db, user, document_id, expected_version, name, media_type, payload):
    scoped_document(db, user, document_id, lock=True)
    if latest_version(db, user.tenant_id, document_id) != expected_version:
        raise HTTPException(409, 'El archivo cambió. Actualiza la lista antes de cargar otra versión.')
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
        raise HTTPException(413, 'El límite por archivo es de 15 MiB.')
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
    path_key: Mapped[str] = mapped_column(String(500))
    source_path: Mapped[str] = mapped_column(String(200))
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), unique=True)


def destination_key(path):
    normalized = unicodedata.normalize('NFKC', path).strip()
    if not normalized or len(path) > 200 or '\\' in normalized or any(ord(c) < 32 or ord(c) == 127 for c in normalized) or any(part in {'', '.', '..'} for part in normalized.split('/')):
        raise HTTPException(422, 'Revisa la ruta del documento: hasta 200 caracteres, sin rutas absolutas ni segmentos de navegación.')
    key = normalized.casefold()
    if len(key) > 500:
        raise HTTPException(422, 'La ruta normalizada es demasiado larga.')
    return key


class BatchEntry(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    path: str = Field(min_length=1, max_length=200)
    subject_kind: Literal['company', 'vehicle']
    vehicle_id: int | None = Field(default=None, gt=0)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    @model_validator(mode='after')
    def binding(self):
        if (self.subject_kind == 'vehicle') != (self.vehicle_id is not None):
            raise ValueError('Asigna el vehículo correspondiente a este documento.')
        return self


class BatchPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entries: list[BatchEntry] = Field(min_length=1, max_length=250)


def batch_target(db, user, entry):
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
        if link.subject_kind != entry.subject_kind or link.vehicle_id != entry.vehicle_id:
            raise HTTPException(409, 'El destino del documento requiere revisión administrativa.')
        return doc, destination, name
    # Adopt an old unbound record only on an exact source-path match. A loose
    # file can also match its latest original filename. Ambiguous matches stop.
    latest = select(DocumentFileVersion.document_id, func.max(DocumentFileVersion.version).label('number')).where(DocumentFileVersion.tenant_id == user.tenant_id).group_by(DocumentFileVersion.document_id).subquery()
    match = core.Document.title == entry.path
    if '/' not in entry.path:
        match = or_(match, DocumentFileVersion.original_name == entry.path)
    query = select(core.Document).join(FileSubject, FileSubject.document_id == core.Document.id).outerjoin(latest, latest.c.document_id == core.Document.id).outerjoin(DocumentFileVersion, (DocumentFileVersion.document_id == core.Document.id) & (DocumentFileVersion.version == latest.c.number)).where(core.Document.tenant_id == user.tenant_id, FileSubject.tenant_id == user.tenant_id, FileSubject.subject_kind == entry.subject_kind, FileSubject.vehicle_id == entry.vehicle_id, match, ~core.Document.id.in_(select(FileDestination.document_id))).limit(2)
    candidates = db.scalars(query).all()
    if len(candidates) > 1:
        raise HTTPException(409, 'Hay varios documentos posibles para «' + entry.path + '». Revisa los registros existentes antes de reemplazar.')
    return candidates[0] if candidates else None, None, name


def destination_plan(db, user, entry):
    doc, destination, name = resolve_destination(db, user, entry)
    version = latest_version(db, user.tenant_id, doc.id) if doc else 0
    file = db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id == user.tenant_id, DocumentFileVersion.document_id == doc.id, DocumentFileVersion.version == version)) if version else None
    status = 'identical' if file and file.sha256 == entry.sha256 else 'replace' if version else 'resume' if doc else 'new'
    return {'path': entry.path, 'subject_kind': entry.subject_kind, 'vehicle_id': entry.vehicle_id, 'subject_name': name, 'document_id': doc.id if doc else None, 'expected_version': version, 'status': status}


@core.app.post('/ops/files/batch/preview')
def preview_batch(data: BatchPreview, user: core.Editor, db: core.Db):
    require_enabled()
    keys = [(entry.subject_kind, entry.vehicle_id, destination_key(entry.path)) for entry in data.entries]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, 'La carga contiene rutas repetidas para el mismo destino.')
    items = [destination_plan(db, user, entry) for entry in data.entries]
    core.add_audit(db, user, 'document.batch_preview', 'tenant', user.tenant_id)
    db.commit()
    return {'items': items}


def store_batch_item(db, user, entry, expected_document_id, expected_version, allow_replace, media, payload):
    db.scalar(select(core.Tenant).where(core.Tenant.id == user.tenant_id).with_for_update())
    doc, destination, name = resolve_destination(db, user, entry)
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
        doc = core.Document(tenant_id=user.tenant_id, title=entry.path, subject_type=entry.subject_kind, subject_name=name)
        db.add(doc);db.flush()
        db.add(FileSubject(document_id=doc.id, tenant_id=user.tenant_id, subject_kind=entry.subject_kind, vehicle_id=entry.vehicle_id));db.flush()
    if destination is None:
        scope, _ = batch_target(db, user, entry)
        db.add(FileDestination(tenant_id=user.tenant_id, subject_scope=scope, path_key=destination_key(entry.path), source_path=entry.path, document_id=doc.id));db.flush()
    core.add_audit(db, user, 'document.batch_replace' if version else 'document.batch_create', 'document', doc.id)
    result = store_upload(db, user, doc.id, version, entry.path.rsplit('/', 1)[-1], media, payload)
    result['status'] = 'replaced' if version else 'created'
    return result


@core.app.post('/ops/files/batch/item', status_code=201)
async def upload_batch_item(request: Request, user: core.Editor, db: core.Db, path: str = Query(min_length=1, max_length=200), subject_kind: Literal['company', 'vehicle'] = 'company', vehicle_id: int | None = Query(default=None, gt=0), expected_document_id: int | None = Query(default=None, gt=0), expected_version: int = Query(ge=0), allow_replace: bool = False):
    require_enabled()
    try:
        entry = BatchEntry(path=path, subject_kind=subject_kind, vehicle_id=vehicle_id, sha256='0' * 64)
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
