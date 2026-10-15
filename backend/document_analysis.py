"""Conservative date proposals and private per-version analysis state."""
from datetime import date,datetime,timedelta,timezone
import json
import re
import unicodedata
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,model_validator
from sqlalchemy import DateTime,ForeignKey,Integer,String,Text,select,func
from sqlalchemy.orm import Mapped,mapped_column
import app as core
from file_records import DocumentFileVersion
from file_api import FileRead,FileSubject,scoped_document,latest_version,gateway,require_enabled,enabled
from document_tools import extract,ExtractionError
from zoneinfo import ZoneInfo

TYPES={'alcohol_drogas':'Examen de alcohol y drogas','examen_ocupacional':'Examen ocupacional','revision_tecnica':'Revisión técnica','permiso_circulacion':'Permiso de circulación','antecedentes':'Certificado de antecedentes','procedimiento':'Procedimiento','checklist':'Lista de verificación','contrato':'Contrato o anexo','cotizaciones':'Cotizaciones previsionales','certificado':'Certificado','sin_clasificar':'Sin clasificar'}
MONTHS={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12}


def normalize(value):return ''.join(c for c in unicodedata.normalize('NFKD',value.lower()) if not unicodedata.combining(c))


def parse_date(value):
    value=value.strip()
    try:
        if re.fullmatch(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',value):year,month,day=map(int,re.split('[-/]',value))
        elif re.fullmatch(r'\d{1,2}[-/.]\d{1,2}[-/.]\d{4}',value):day,month,year=map(int,re.split('[-/.]',value))
        else:
            m=re.fullmatch(r'(\d{1,2})\s+(?:de\s+)?([a-z]+)\s+(?:de\s+)?(\d{4})',value)
            if not m:return None
            day=int(m[1]);month=MONTHS.get(m[2],0);year=int(m[3])
        return date(year,month,day) if 1980<=year<=2100 else None
    except ValueError:return None


def interpret(text,notes=None,method='pdf_text',today=None):
    today=today or datetime.now(ZoneInfo('America/Santiago')).date();warnings=list(notes or []);body=normalize(text)
    patterns=[('alcohol_drogas',r'alcohol\s*(?:y|e|/)?\s*drogas|test de drogas'),('examen_ocupacional',r'examen(?:es)?\s+(?:pre)?ocupacional|bateria basica'),('revision_tecnica',r'revision tecnica'),('permiso_circulacion',r'permiso de circulacion'),('antecedentes',r'certificado de antecedentes'),('procedimiento',r'procedimiento'),('checklist',r'check\s*list|lista de verificacion'),('contrato',r'contrato de trabajo|anexo de contrato'),('cotizaciones',r'cotizaciones previsionales|previred')]
    matches=[kind for kind,pattern in patterns if re.search(pattern,body)]
    kind=matches[0] if len(matches)==1 else 'certificado' if not matches and re.search(r'\bcertificado\b',body) else 'sin_clasificar'
    if len(matches)>1:warnings.append('Se detectaron varios tipos documentales; revisar clasificación.')
    if kind=='sin_clasificar':warnings.append('No se identificó un tipo documental único.')
    token=r'(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+(?:de\s+)?(?:'+ '|'.join(MONTHS)+r')\s+(?:de\s+)?\d{4})'
    def dates(labels):
        values=[]
        for match in re.finditer(r'(?:'+labels+r')(?:\s|[:|._-]){0,14}('+token+r')',body):
            value=parse_date(match[1])
            if value is None:warnings.append('Existe una fecha etiquetada inválida.')
            elif value not in values:values.append(value)
        return values
    issued=dates(r'fecha\s+(?:de\s+)?emision|emitido\s+el|fecha\s+(?:de\s+)?realizacion')
    expires=dates(r'fecha\s+(?:de\s+)?vencimiento|vencimiento|valido\s+hasta|vigente\s+hasta|vence\s+el|fecha\s+(?:de\s+)?caducidad')
    if len(issued)>1:warnings.append('Varias fechas de emisión; requiere revisión.')
    if len(expires)>1:warnings.append('Varias fechas de vencimiento; requiere revisión.')
    issue=issued[0] if len(issued)==1 else None;expiry=expires[0] if len(expires)==1 else None
    if not expiry:warnings.append('No se encontró un vencimiento explícito y único.')
    if issue and issue>today:warnings.append('La emisión está en el futuro.')
    if issue and expiry and expiry<issue:warnings.append('El vencimiento es anterior a la emisión.')
    periods=set(int(n) for n in re.findall(r'vigencia\s*[:|]?\s*(\d{1,4})\s*dias',body))
    if expiry is None and issue and len(periods)==1:
        expiry=issue+timedelta(days=next(iter(periods)));warnings.append('Fecha propuesta desde un plazo escrito: confirmar su regla de cómputo.')
    if method=='ocr' and not any('OCR' in item for item in warnings):warnings.append('Lectura OCR: confirmar fechas visualmente.')
    if not text.strip():warnings.append('No se pudo leer el contenido.')
    return {'document_type':kind,'issued_on':issue.isoformat() if issue else None,'expires_on':expiry.isoformat() if expiry else None,'method':method,'warnings':list(dict.fromkeys(warnings)),'safe_to_apply':bool(expiry) and not warnings}


class FileAnalysis(core.Base):
    __tablename__='file_analyses'
    id:Mapped[int]=mapped_column(primary_key=True)
    tenant_id:Mapped[int]=mapped_column(ForeignKey('tenants.id'),index=True)
    document_id:Mapped[int]=mapped_column(ForeignKey('documents.id'),index=True)
    file_version_id:Mapped[int]=mapped_column(ForeignKey('document_file_versions.id'),unique=True)
    status:Mapped[str]=mapped_column(String(20),default='processing')
    result_json:Mapped[str]=mapped_column(Text,default='{}')
    claimed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))


def current_analysis(db,user,doc_id,version):
    return db.scalar(select(FileAnalysis).join(DocumentFileVersion,DocumentFileVersion.id==FileAnalysis.file_version_id).where(FileAnalysis.tenant_id==user.tenant_id,FileAnalysis.document_id==doc_id,DocumentFileVersion.version==version))


def analysis_payload(row,doc,version):
    result=json.loads(row.result_json) if row else {}
    status=row.status if row else 'pending'
    if row and status=='processing':
        claimed=row.claimed_at.replace(tzinfo=timezone.utc) if row.claimed_at.tzinfo is None else row.claimed_at
        if datetime.now(timezone.utc)-claimed>timedelta(minutes=10):status='interrupted'
    today=datetime.now(ZoneInfo('America/Santiago')).date()
    traffic='expired' if doc.expires_on and doc.expires_on<today else 'valid' if status in {'ready','confirmed'} and doc.expires_on and doc.expires_on>today+timedelta(days=30) else 'expiring' if status in {'ready','confirmed'} and doc.expires_on else 'warning'
    return {'status':status,'version':version,'traffic_light':traffic,'document_type':result.get('document_type','sin_clasificar'),'type_label':TYPES.get(result.get('document_type'),'Sin clasificar'),'issued_on':result.get('issued_on'),'proposed_expires_on':result.get('expires_on'),'revision':result.get('revision',0),'method':result.get('method'),'warnings':result.get('warnings',[]),'expires_on':doc.expires_on}


@core.app.get('/ops/files/documents/{document_id}/analysis')
def get_analysis(document_id:int,user:FileRead,db:core.Db):
    require_enabled();doc,_=scoped_document(db,user,document_id);version=latest_version(db,user.tenant_id,document_id)
    return analysis_payload(current_analysis(db,user,document_id,version),doc,version)


class ConfirmAnalysis(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(gt=0)
    expected_revision:int=Field(default=0,ge=0)
    document_type:str=Field(max_length=40)
    issued_on:date|None=None
    expires_on:date
    reason:str=Field(min_length=5,max_length=300)
    @model_validator(mode='after')
    def dates(self):
        if self.document_type not in TYPES or self.document_type=='sin_clasificar':raise ValueError('Selecciona el tipo documental.')
        if self.issued_on and self.expires_on<self.issued_on:raise ValueError('El vencimiento no puede ser anterior a la emisión.')
        return self


@core.app.post('/ops/files/documents/{document_id}/analysis/confirm')
def confirm_analysis(document_id:int,data:ConfirmAnalysis,user:core.Editor,db:core.Db):
    require_enabled();doc,_=scoped_document(db,user,document_id,lock=True)
    if latest_version(db,user.tenant_id,document_id)!=data.expected_version:raise HTTPException(409,'La versión cambió. Revisa la vista previa antes de confirmar.')
    row=current_analysis(db,user,document_id,data.expected_version)
    if row is None or (row.status=='processing' and analysis_payload(row,doc,data.expected_version)['status']!='interrupted'):raise HTTPException(409,'Espera a que termine el análisis antes de confirmar.')
    result=json.loads(row.result_json)
    if result.get('revision',0)!=data.expected_revision:raise HTTPException(409,'Las fechas fueron modificadas por otro usuario. Actualiza antes de confirmar.')
    result.setdefault('original_proposal',{key:result.get(key) for key in ['document_type','issued_on','expires_on']})
    result['revision']=result.get('revision',0)+1
    result.update(document_type=data.document_type,issued_on=data.issued_on.isoformat() if data.issued_on else None,expires_on=data.expires_on.isoformat(),confirmed_by=user.id,confirmation_reason=data.reason)
    row.result_json=json.dumps(result,ensure_ascii=False);row.status='confirmed';doc.expires_on=data.expires_on
    core.add_audit(db,user,'document.analysis_confirm','document',doc.id);db.commit()
    return analysis_payload(row,doc,data.expected_version)


def process_next(db,extractor=extract):
    if not enabled():return False
    latest=select(DocumentFileVersion.document_id,func.max(DocumentFileVersion.version).label('v')).group_by(DocumentFileVersion.document_id).subquery()
    query=select(DocumentFileVersion).join(FileSubject,FileSubject.document_id==DocumentFileVersion.document_id).join(latest,(latest.c.document_id==DocumentFileVersion.document_id)&(latest.c.v==DocumentFileVersion.version)).where(~DocumentFileVersion.id.in_(select(FileAnalysis.file_version_id))).order_by(DocumentFileVersion.id).limit(1).with_for_update(skip_locked=True,of=DocumentFileVersion)
    file=db.scalar(query)
    if file is None:return False
    identity=(file.id,file.document_id,file.tenant_id,file.version,file.created_by_user_id)
    row=FileAnalysis(file_version_id=file.id,document_id=file.document_id,tenant_id=file.tenant_id,status='processing');db.add(row);db.commit();analysis_id=row.id
    user=db.get(core.User,identity[4]);doc=db.get(core.Document,identity[1])
    try:
        from file_records import read_file_version
        payload=read_file_version(db,user,doc.id,identity[3],gateway())
        text,notes,method=extractor(payload,file.media_type)
        result=interpret(text,notes,method)
        link=db.get(FileSubject,doc.id)
        identity_name=None
        if link.subject_kind=='company':identity_name=db.get(core.Tenant,doc.tenant_id).name
        elif link.subject_kind=='worker':identity_name=db.get(core.Worker,link.worker_id).full_name
        elif link.subject_kind=='project':identity_name=db.get(core.Project,doc.project_id).name
        if identity_name:
            canonical=lambda value:' '.join(re.sub(r'[^a-z0-9]+',' ',normalize(value)).split())
            if not canonical(identity_name) or not re.search(r'(?<![a-z0-9])'+re.escape(canonical(identity_name))+r'(?![a-z0-9])',canonical(text)):
                result['warnings'].append('El contenido no confirma el nombre completo del destino. Revisa identidad y fechas.')
                result['safe_to_apply']=False
        elif link.subject_kind=='vehicle':
            plate=re.sub('[^A-Z0-9]','',(db.get(core.Vehicle,link.vehicle_id).plate or '').upper())
            pattern=r'(?<![A-Z0-9])'+r'[ .-]*'.join(re.escape(c) for c in plate)+r'(?![A-Z0-9])'
            if not plate or not re.search(pattern,text.upper()):
                result['warnings'].append('El contenido no confirma la patente del destino. Revisa identidad y fechas.')
                result['safe_to_apply']=False
    except Exception:
        db.rollback();result={'document_type':'sin_clasificar','issued_on':None,'expires_on':None,'method':'unavailable','warnings':['No se completó la lectura. Revisa el archivo original.'],'safe_to_apply':False}
    # End extraction's read transaction, then reload fresh metadata under lock.
    db.rollback()
    # Use the same document→tenant audit lock order as ordinary uploads.
    doc=db.scalar(select(core.Document).where(core.Document.id==identity[1],core.Document.tenant_id==identity[2]).with_for_update())
    row=db.get(FileAnalysis,analysis_id)
    if row.status=='confirmed':return True
    if latest_version(db,identity[2],doc.id)!=identity[3]:
        row.status='superseded'
    elif result['safe_to_apply']:
        proposed=date.fromisoformat(result['expires_on'])
        if doc.expires_on is None or doc.expires_on==proposed:
            doc.expires_on=proposed;row.status='ready'
        else:result['warnings'].append('La fecha registrada difiere de la detectada. Requiere confirmación.');row.status='review'
    else:row.status='review'
    row.result_json=json.dumps(result,ensure_ascii=False)
    core.add_audit(db,user,'document.auto_analysis','document',doc.id);db.commit();return True
