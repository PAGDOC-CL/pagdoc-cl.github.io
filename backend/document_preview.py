"""Session-scoped previews. PDF pages render as PNG; Office content is plain text."""
import tempfile
import os
from pathlib import Path
import threading
from fastapi import HTTPException,Query,Response
from sqlalchemy import select
import app as core
from file_api import FileRead,scoped_document,gateway,require_enabled
from file_records import DocumentFileVersion,read_file_version
from document_tools import pdf_pages,raster_pdf,office_text,image_dimensions,ExtractionError

slots=threading.BoundedSemaphore(2)


def load(db,user,document_id,version):
    require_enabled();scoped_document(db,user,document_id)
    file=db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.tenant_id==user.tenant_id,DocumentFileVersion.document_id==document_id,DocumentFileVersion.version==version))
    if file is None:raise HTTPException(404,'Versión no encontrada.')
    try:payload=read_file_version(db,user,document_id,version,gateway())
    except Exception:db.rollback();raise HTTPException(503,'No se pudo verificar la integridad del archivo.')
    return file,payload


@core.app.get('/ops/files/documents/{document_id}/versions/{version}/preview')
def preview(document_id:int,version:int,user:FileRead,db:core.Db):
    file,payload=load(db,user,document_id,version)
    if not slots.acquire(blocking=False):raise HTTPException(429,'Hay dos vistas previas en proceso. Vuelve a intentar.')
    try:
        if file.media_type=='application/pdf':
            with tempfile.TemporaryDirectory(prefix='pagdoc-preview-') as directory:
                os.chmod(directory,0o700);path=Path(directory)/'source.pdf';path.write_bytes(payload);pages=pdf_pages(path,directory)
            return {'kind':'pdf','pages':min(pages,100),'total_pages':pages,'limited':pages>100,'name':file.original_name}
        if file.media_type in {'image/png','image/jpeg'}:
            image_dimensions(payload,file.media_type);return {'kind':'image','pages':1,'name':file.original_name}
        text,notes=office_text(payload,file.media_type)
        return {'kind':'text','pages':1,'name':file.original_name,'text':text[:50_000],'notes':notes+(['Vista parcial: descarga para revisar el contenido completo.'] if len(text)>50_000 else []),'note':'Vista previa de texto; el formato original y sus fórmulas no se reproducen.'}
    except HTTPException:raise
    except Exception:raise HTTPException(422,'No se pudo generar la vista previa de este archivo. Conserva el original para su revisión.')
    finally:slots.release()


@core.app.get('/ops/files/documents/{document_id}/versions/{version}/preview/page')
def preview_page(document_id:int,version:int,user:FileRead,db:core.Db,page:int=Query(default=1,ge=1,le=100)):
    file,payload=load(db,user,document_id,version)
    if not slots.acquire(blocking=False):raise HTTPException(429,'Hay dos vistas previas en proceso. Vuelve a intentar.')
    try:
        if file.media_type=='application/pdf':
            with tempfile.TemporaryDirectory(prefix='pagdoc-preview-') as directory:
                os.chmod(directory,0o700);path=Path(directory)/'source.pdf';path.write_bytes(payload)
                if page>pdf_pages(path,directory):raise HTTPException(404,'Página no encontrada.')
                body=raster_pdf(path,page,directory);media='image/png'
        elif file.media_type in {'image/png','image/jpeg'}:
            if page!=1:raise HTTPException(404,'Página no encontrada.')
            image_dimensions(payload,file.media_type);body=payload;media=file.media_type
        else:raise HTTPException(422,'Usa la vista previa de texto para Word o Excel.')
        return Response(body,media_type=media,headers={'Content-Disposition':'inline','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    except HTTPException:raise
    except Exception:raise HTTPException(422,'No se pudo renderizar la página.')
    finally:slots.release()
