"""Conservative date proposals and private per-version analysis state."""
from datetime import date,datetime,timedelta,timezone
import json
import re
import unicodedata
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,model_validator
from sqlalchemy import DateTime,ForeignKey,Integer,String,Text,select,func,or_
from sqlalchemy.orm import Mapped,mapped_column
import app as core
from file_records import DocumentFileVersion
from file_api import FileRead,FileSubject,scoped_document,latest_version,gateway,require_enabled,enabled
from document_tools import extract,ExtractionError
from zoneinfo import ZoneInfo

ANALYSIS_RULES_VERSION=4
DRUG_VALIDITY_DAYS=30

TYPES={'alcohol_drogas':'Examen de alcohol y drogas','examen_ocupacional':'Examen ocupacional','revision_tecnica':'Revisión técnica','permiso_circulacion':'Permiso de circulación','antecedentes':'Certificado de antecedentes','procedimiento':'Procedimiento','checklist':'Lista de verificación','contrato':'Contrato o anexo','cotizaciones':'Cotizaciones previsionales','certificado':'Certificado','sin_clasificar':'Sin clasificar'}
MONTHS={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12}


def normalize(value):return ''.join(c for c in unicodedata.normalize('NFKD',value.lower()) if not unicodedata.combining(c))


def parse_date(value):
    value=re.sub(r'(?<=\d)\s*([-/.])\s*(?=\d)',r'\1',value.strip())
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
    today=today or datetime.now(ZoneInfo('America/Santiago')).date();warnings=list(notes or []);body=re.sub(r'[^\S\n]+',' ',normalize(text));body=re.sub(r'(?<=\d) *([-/.]) *(?=\d)',r'\1',body)
    patterns=[('alcohol_drogas',r'alcohol\s*(?:y|e|/)?\s*drogas|(?:test|examen(?:es)?|screening|panel|analisis)(?:\s+de)?\s+(?:alcohol|drogas)|drogas\s+(?:de\s+)?abuso'),('examen_ocupacional',r'examen(?:es)?\s+(?:pre)?ocupacional|bateria basica'),('revision_tecnica',r'revision tecnica'),('permiso_circulacion',r'permiso de circulacion'),('antecedentes',r'certificado de antecedentes'),('procedimiento',r'procedimiento'),('checklist',r'check\s*list|lista de verificacion'),('contrato',r'contrato de trabajo|anexo de contrato'),('cotizaciones',r'cotizaciones previsionales|previred')]
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
    issue_labels=r'fecha\s+(?:de\s+)?emision|emitido\s+el'
    issued=dates(issue_labels if kind=='alcohol_drogas' else issue_labels+r'|fecha\s+(?:de\s+)?realizacion')
    expiry_labels=r'fecha\s+(?:de\s+)?vencimiento|vencimiento|valido\s+hasta|vigente\s+hasta|\bvence(?:\s+el)?\b|fecha\s+(?:de\s+)?caducidad|caduca(?:\s+el)?|expira(?:\s+el)?|validez\s+hasta|\bvcto\b|\bfecha\s+venc\b'
    expires=dates(expiry_labels)
    # PDF table headings may precede a single date on the next line.
    for heading,values in zip(body.splitlines(),body.splitlines()[1:]):
        if re.search(expiry_labels,heading) and not re.search(token,heading):
            if re.search(r'emision|realizacion|nacimiento',heading):
                warnings.append('Tabla con varias columnas de fechas; revisar asociación.')
                continue
            candidates=[parse_date(m[0]) for m in re.finditer(token,values)]
            candidates=[value for value in candidates if value is not None]
            if len(set(candidates))==1 and candidates[0] not in expires:expires.append(candidates[0])
            elif len(set(candidates))>1:warnings.append('Tabla con varias fechas posibles de vencimiento; revisar.')
    if len(issued)>1:warnings.append('Varias fechas de emisión; requiere revisión.')
    if len(expires)>1:warnings.append('Varias fechas de vencimiento; requiere revisión.')
    issue=issued[0] if len(issued)==1 else None;expiry=expires[0] if len(expires)==1 else None
    printed_expiry=expiry
    rule=None
    if kind=='alcohol_drogas':
        rule='emision_mas_30_dias'
        if issue:
            expiry=issue+timedelta(days=DRUG_VALIDITY_DAYS)
            if printed_expiry and printed_expiry!=expiry:warnings.append('El vencimiento impreso difiere de la regla de 30 días. Revisar antes de aplicar.')
        else:warnings.append('Alcohol y drogas: falta una fecha de emisión explícita y única para calcular 30 días.')
    elif not expiry:warnings.append('No se encontró un vencimiento explícito y único.')
    if issue and issue>today:warnings.append('La emisión está en el futuro.')
    if issue and expiry and expiry<issue:warnings.append('El vencimiento es anterior a la emisión.')
    periods=set(int(n) for n in re.findall(r'vigencia\s*[:|]?\s*(\d{1,4})\s*dias',body))
    if kind!='alcohol_drogas' and expiry is None and issue and len(periods)==1:
        expiry=issue+timedelta(days=next(iter(periods)));warnings.append('Fecha propuesta desde un plazo escrito: confirmar su regla de cómputo.')
    if method=='ocr' and not any('OCR' in item for item in warnings):warnings.append('Lectura OCR: confirmar fechas visualmente.')
    if not text.strip():warnings.append('No se pudo leer el contenido.')
    expiry_context=re.sub(r'\bsin\s+(?:fecha\s+de\s+)?vencimiento\b|\bvencimiento\s*:?\s*no\s+aplica\b','',body)
    no_expiry=bool(text.strip()) and 'alcohol_drogas' not in matches and not expiry and not re.search(expiry_labels,expiry_context) and not any('OCR' not in note for note in (notes or []))
    return {'no_expiry':no_expiry,'rules_version':ANALYSIS_RULES_VERSION,'expiry_rule':rule,'validity_days':DRUG_VALIDITY_DAYS if rule else None,'document_expires_on':printed_expiry.isoformat() if printed_expiry else None,'document_type':kind,'issued_on':issue.isoformat() if issue else None,'expires_on':expiry.isoformat() if expiry else None,'method':method,'warnings':list(dict.fromkeys(warnings)),'safe_to_apply':bool(expiry) and not warnings}


class FileAnalysis(core.Base):
    __tablename__='file_analyses'
    id:Mapped[int]=mapped_column(primary_key=True)
    tenant_id:Mapped[int]=mapped_column(ForeignKey('tenants.id'),index=True)
    document_id:Mapped[int]=mapped_column(ForeignKey('documents.id'),index=True)
    file_version_id:Mapped[int]=mapped_column(ForeignKey('document_file_versions.id'),unique=True)
    status:Mapped[str]=mapped_column(String(20),default='processing')
    rules_version:Mapped[int]=mapped_column(Integer,default=ANALYSIS_RULES_VERSION,server_default='1')
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
    warning_days=7 if result.get('document_type')=='alcohol_drogas' else 30
    traffic='expired' if doc.expires_on and doc.expires_on<today else 'valid' if status in {'ready','confirmed'} and doc.expires_on and doc.expires_on>today+timedelta(days=warning_days) else 'expiring' if status in {'ready','confirmed'} and doc.expires_on else 'valid' if status=='no_expiry' and version>0 else 'warning'
    return {'no_expiry':status=='no_expiry','expiry_rule':result.get('expiry_rule'),'validity_days':result.get('validity_days'),'document_expires_on':result.get('document_expires_on'),'warning_days':warning_days,'status':status,'version':version,'traffic_light':traffic,'document_type':result.get('document_type','sin_clasificar'),'type_label':TYPES.get(result.get('document_type'),'Sin clasificar'),'issued_on':result.get('issued_on'),'proposed_expires_on':result.get('expires_on'),'revision':result.get('revision',0),'method':result.get('method'),'warnings':result.get('warnings',[]),'expires_on':doc.expires_on}


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
        if self.document_type=='alcohol_drogas':
            if self.issued_on is None:raise ValueError('Alcohol y drogas requiere una emisión verificada.')
            if self.issued_on>datetime.now(ZoneInfo('America/Santiago')).date():raise ValueError('La emisión no puede estar en el futuro.')
            if self.expires_on!=self.issued_on+timedelta(days=DRUG_VALIDITY_DAYS):raise ValueError('Alcohol y drogas vence 30 días después de la emisión.')
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
    result.update(rules_version=ANALYSIS_RULES_VERSION,expiry_rule='emision_mas_30_dias' if data.document_type=='alcohol_drogas' else None,validity_days=DRUG_VALIDITY_DAYS if data.document_type=='alcohol_drogas' else None)
    row.rules_version=ANALYSIS_RULES_VERSION;row.result_json=json.dumps(result,ensure_ascii=False);row.status='confirmed';doc.expires_on=data.expires_on
    core.add_audit(db,user,'document.analysis_confirm','document',doc.id);db.commit()
    return analysis_payload(row,doc,data.expected_version)


def process_next(db,extractor=extract):
    if not enabled():return False
    latest=select(DocumentFileVersion.document_id,func.max(DocumentFileVersion.version).label('v')).group_by(DocumentFileVersion.document_id).subquery()
    query=select(DocumentFileVersion).join(FileSubject,FileSubject.document_id==DocumentFileVersion.document_id).join(latest,(latest.c.document_id==DocumentFileVersion.document_id)&(latest.c.v==DocumentFileVersion.version)).outerjoin(FileAnalysis,FileAnalysis.file_version_id==DocumentFileVersion.id).where(or_(FileAnalysis.id.is_(None),FileAnalysis.rules_version<ANALYSIS_RULES_VERSION)).order_by(DocumentFileVersion.id).limit(1).with_for_update(skip_locked=True,of=DocumentFileVersion)
    file=db.scalar(query)
    if file is None:return False
    identity=(file.id,file.document_id,file.tenant_id,file.version,file.created_by_user_id)
    row=db.scalar(select(FileAnalysis).where(FileAnalysis.file_version_id==file.id))
    if row and row.status=='confirmed':
        doc=db.scalar(select(core.Document).where(core.Document.id==file.document_id,core.Document.tenant_id==file.tenant_id).with_for_update());user=db.get(core.User,file.created_by_user_id)
        if latest_version(db,file.tenant_id,doc.id)!=file.version:row.status='superseded'
        else:
            result=json.loads(row.result_json)
            if result.get('document_type')=='alcohol_drogas':
                issued=parse_date(result.get('issued_on') or '')
                result['previous_policy']={key:result.get(key) for key in ['issued_on','expires_on','expiry_rule']}
                result['revision']=result.get('revision',0)+1
                if issued and issued<=datetime.now(ZoneInfo('America/Santiago')).date():
                    target=issued+timedelta(days=DRUG_VALIDITY_DAYS);doc.expires_on=target
                    result.update(expires_on=target.isoformat(),expiry_rule='emision_mas_30_dias',validity_days=DRUG_VALIDITY_DAYS)
                else:
                    row.status='review';result.setdefault('warnings',[]).append('Alcohol y drogas requiere una emisión verificada para aplicar la regla de 30 días.')
            result['rules_version']=ANALYSIS_RULES_VERSION;row.result_json=json.dumps(result,ensure_ascii=False)
            core.add_audit(db,user,'document.analysis_policy','document',doc.id)
        row.rules_version=ANALYSIS_RULES_VERSION;db.commit();return True
    previous=json.loads(row.result_json) if row else None
    if row is None:row=FileAnalysis(file_version_id=file.id,document_id=file.document_id,tenant_id=file.tenant_id);db.add(row)
    row.status='processing';row.claimed_at=datetime.now(timezone.utc);row.rules_version=ANALYSIS_RULES_VERSION
    db.commit();analysis_id=row.id
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
    elif result.get('no_expiry') and doc.expires_on is None:
        row.status='no_expiry'
    elif result['safe_to_apply']:
        proposed=date.fromisoformat(result['expires_on'])
        if doc.expires_on is None or doc.expires_on==proposed or (previous and previous.get('expires_on')==doc.expires_on.isoformat() and result.get('expiry_rule')=='emision_mas_30_dias'):
            doc.expires_on=proposed;row.status='ready'
        else:result['warnings'].append('La fecha registrada difiere de la detectada. Requiere confirmación.');row.status='review'
    else:row.status='review'
    if previous:result['previous_policy']={key:previous.get(key) for key in ['document_type','issued_on','expires_on','expiry_rule']}
    result['rules_version']=ANALYSIS_RULES_VERSION
    row.result_json=json.dumps(result,ensure_ascii=False)
    core.add_audit(db,user,'document.auto_analysis','document',doc.id);db.commit();return True


@core.app.get('/ops/files/analysis/status')
def analysis_status(user:FileRead,db:core.Db):
    latest=select(DocumentFileVersion.document_id,func.max(DocumentFileVersion.version).label('v')).where(DocumentFileVersion.tenant_id==user.tenant_id).group_by(DocumentFileVersion.document_id).subquery()
    rows=db.execute(select(FileAnalysis.status,FileAnalysis.rules_version).select_from(DocumentFileVersion).join(FileSubject,FileSubject.document_id==DocumentFileVersion.document_id).join(latest,(latest.c.document_id==DocumentFileVersion.document_id)&(latest.c.v==DocumentFileVersion.version)).outerjoin(FileAnalysis,FileAnalysis.file_version_id==DocumentFileVersion.id).where(DocumentFileVersion.tenant_id==user.tenant_id,FileSubject.tenant_id==user.tenant_id)).all()
    counts={key:0 for key in ['pending','processing','review','ready','confirmed','no_expiry','superseded']}
    for status,version in rows:counts['pending' if version is None or version<ANALYSIS_RULES_VERSION else status if status in counts else 'review']+=1
    return {'total':len(rows),'counts':counts,'rules_version':ANALYSIS_RULES_VERSION,'alcohol_drugs_days':DRUG_VALIDITY_DAYS,'drug_warning_days':7,'as_of':datetime.now(ZoneInfo('America/Santiago')).date()}
