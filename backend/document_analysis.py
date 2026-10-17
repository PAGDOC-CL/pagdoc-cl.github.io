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

ANALYSIS_RULES_VERSION=7
DRUG_VALIDITY_DAYS=30

POLICY_VALID_TYPES={'contrato','cotizaciones','afiliacion','whatsapp'}
TYPES={'afiliacion':'Certificado de afiliación','whatsapp':'Imagen de WhatsApp','epp':'Entrega de EPP','soap':'Seguro obligatorio SOAP','alcohol_drogas':'Examen de alcohol y drogas','examen_ocupacional':'Examen ocupacional','revision_tecnica':'Revisión técnica','permiso_circulacion':'Permiso de circulación','antecedentes':'Certificado de antecedentes','procedimiento':'Procedimiento','checklist':'Lista de verificación','contrato':'Contrato o anexo','cotizaciones':'Cotizaciones previsionales','certificado':'Certificado','sin_clasificar':'Sin clasificar'}
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


def interpret(text,notes=None,method='pdf_text',today=None,file_name=None):
    today=today or datetime.now(ZoneInfo('America/Santiago')).date();warnings=list(notes or []);body=re.sub(r'[^\S\n]+',' ',normalize(text));body=re.sub(r'(?<=\d) *([-/.]) *(?=\d)',r'\1',body)
    patterns=[('afiliacion',r'certificado\s+(?:de\s+)?afiliacion'),('epp',r'entrega\s+(?:de\s+)?(?:elementos\s+de\s+proteccion\s+personal|epp)\b'),('soap',r'\bsoap\b|seguro\s+obligatorio(?:\s+de)?\s+accidentes\s+personales'),('alcohol_drogas',r'alcohol\s*(?:y|e|/)?\s*drogas|(?:test|examen(?:es)?|screening|panel|analisis)(?:\s+de)?\s+(?:alcohol|drogas)|drogas\s+(?:de\s+)?abuso'),('examen_ocupacional',r'examen(?:es)?\s+(?:pre)?ocupacional|bateria basica|evaluacion(?:es)?\s+(?:pre)?ocupacional'),('revision_tecnica',r'revision tecnica'),('permiso_circulacion',r'permiso de circulacion'),('antecedentes',r'certificado de antecedentes'),('procedimiento',r'procedimiento'),('checklist',r'check\s*list|lista de verificacion'),('contrato',r'contrato\s+(?:de\s+)?trabajo|anexo\s+(?:de\s+contrato|laboral|de\s+trabajo)'),('cotizaciones',r'cotizaciones previsionales|previred|certificado\s+(?:de\s+)?cotizacion(?:es)?')]
    matches=[kind for kind,pattern in patterns if re.search(pattern,body)]
    filename=normalize(file_name or '').replace('_',' ')
    hint=None
    if re.search(r'^(?:contrato|anexo)\b',filename):hint='contrato'
    elif re.search(r'^(?:certificado\s+(?:de\s+)?)?afiliacion\b',filename):hint='afiliacion'
    elif re.search(r'^(?:certificado\s+(?:de\s+)?)?cotizacion(?:es)?\b|^previred\b',filename):hint='cotizaciones'
    elif re.search(r'whatsapp|(?:^|[ _-])wsp(?:[ _.-]|$)|^img-\d{8}-wa\d+',filename) and re.search(r'\.(?:png|jpe?g)$',filename):hint='whatsapp'
    if hint and (not matches or set(matches)<=POLICY_VALID_TYPES) and hint not in matches:matches.append(hint)
    kind=matches[0] if matches and set(matches)<=POLICY_VALID_TYPES else matches[0] if len(matches)==1 else 'certificado' if not matches and re.search(r'\bcertificado\b',body) else 'sin_clasificar'
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
    expiry_labels=r'fecha\s+(?:de\s+)?vencimiento|vencimiento|valido\s+hasta|vigente\s+hasta|\bvence(?:\s+el)?\b|fecha\s+(?:de\s+)?caducidad|caduca(?:\s+el)?|expira(?:\s+el)?|validez\s+hasta|\bvcto\b|\bfecha\s+venc\b|\bfecha\s+(?:de\s+)?vigencia(?:\s+hasta)?|\bfecha\s+(?:de\s+)?(?:termino|expiracion)|\bvalidez\s*:|\bvigencia\s*:(?=\s*\d)|\bvigencia\s+(?:de\s+este\s+(?:certificado|documento)\s+)?(?:es\s+)?hasta(?:\s+el)?(?:\s+dia)?'
    expires=dates(expiry_labels)
    valid_from=None
    if kind=='soap':
        starts=dates(r'\brige\s+desde|\bvigente\s+desde|\bvigencia\s+desde')
        ends=[]
        for match in re.finditer(r'(?:rige|vigente|vigencia)\s+desde\s*:?\s*('+token+r')\s*(?:[|;]\s*)?hasta\s*:?\s*('+token+r')',body):
            start,end=parse_date(match[1]),parse_date(match[2])
            if start is None or end is None:warnings.append('El rango de cobertura contiene una fecha inválida.')
            elif end<start:warnings.append('El vencimiento de cobertura es anterior al inicio.')
            else:
                if end not in ends:ends.append(end)
        if len(starts)==1:valid_from=starts[0]
        if len(starts)>1 or len(ends)>1:warnings.append('Varias fechas de cobertura; revisar póliza.')
        for end in ends:
            if end not in expires:expires.append(end)
        if not ends and not expires:warnings.append('SOAP: no se encontró un rango de cobertura explícito y único.')
        if valid_from and valid_from>today:warnings.append('El inicio de cobertura está en el futuro.')
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
    if method=='ocr' and 'OCR con confianza alta.' not in warnings and not any('OCR' in item for item in warnings):warnings.append('Lectura OCR: confirmar fechas visualmente.')
    if not text.strip():warnings.append('No se pudo leer el contenido.')
    expiry_context=re.sub(r'\bsin\s+(?:fecha\s+de\s+)?vencimiento\b|\bvencimiento\s*:?\s*no\s+aplica\b','',body)
    no_expiry=bool(text.strip()) and 'alcohol_drogas' not in matches and 'soap' not in matches and not expiry and not re.search(expiry_labels,expiry_context) and not any(note!='OCR con confianza alta.' for note in (notes or []))
    classification_notes={'Se detectaron varios tipos documentales; revisar clasificación.','No se identificó un tipo documental único.'}
    blocking=[warning for warning in warnings if warning!='OCR con confianza alta.' and (warning not in classification_notes or 'alcohol_drogas' in matches)]
    return {'validity_exempt':kind in POLICY_VALID_TYPES and bool(matches) and set(matches)<=POLICY_VALID_TYPES,'no_expiry':no_expiry and kind!='soap','rules_version':ANALYSIS_RULES_VERSION,'expiry_rule':rule,'validity_days':DRUG_VALIDITY_DAYS if rule else None,'document_expires_on':printed_expiry.isoformat() if printed_expiry else None,'document_type':kind,'valid_from':valid_from.isoformat() if valid_from else None,'issued_on':issue.isoformat() if issue else None,'expires_on':expiry.isoformat() if expiry else None,'method':method,'warnings':list(dict.fromkeys(warnings)),'safe_to_apply':bool(expiry) and not blocking}


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
    traffic='valid' if status=='policy_valid' and version>0 else 'expired' if doc.expires_on and doc.expires_on<today else 'valid' if status in {'ready','confirmed'} and doc.expires_on and doc.expires_on>today+timedelta(days=warning_days) else 'expiring' if status in {'ready','confirmed'} and doc.expires_on else 'valid' if status=='no_expiry' and version>0 else 'warning'
    return {'validity_exempt':status=='policy_valid','no_expiry':status=='no_expiry','expiry_rule':result.get('expiry_rule'),'validity_days':result.get('validity_days'),'document_expires_on':result.get('document_expires_on'),'warning_days':warning_days,'status':status,'version':version,'traffic_light':traffic,'document_type':result.get('document_type','sin_clasificar'),'type_label':TYPES.get(result.get('document_type'),'Sin clasificar'),'valid_from':result.get('valid_from'),'issued_on':result.get('issued_on'),'proposed_expires_on':result.get('expires_on'),'revision':result.get('revision',0),'method':result.get('method'),'warnings':result.get('warnings',[]),'expires_on':doc.expires_on}


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
    row.rules_version=ANALYSIS_RULES_VERSION;row.result_json=json.dumps(result,ensure_ascii=False);row.status='policy_valid' if data.document_type in POLICY_VALID_TYPES else 'confirmed';result['validity_exempt']=data.document_type in POLICY_VALID_TYPES;row.result_json=json.dumps(result,ensure_ascii=False);doc.expires_on=data.expires_on
    core.add_audit(db,user,'document.analysis_confirm','document',doc.id);db.commit()
    return analysis_payload(row,doc,data.expected_version)


def identity_confirmed(name,text,identifier=None):
    canonical=lambda value:' '.join(re.sub(r'[^a-z0-9]+',' ',normalize(value)).split())
    expected=canonical(name or '')
    if expected and re.search(r'(?<![a-z0-9])'+re.escape(expected)+r'(?![a-z0-9])',canonical(text)):return True
    # Exact registered worker identifier handles reordered names without fuzzy matching.
    key=re.sub(r'[^0-9K]','',(identifier or '').upper())
    if identifier and re.fullmatch(r'[0-9 .kK-]+',identifier) and re.fullmatch(r'\d{7,8}[0-9K]',key):
        return bool(re.search(r'(?<![A-Z0-9])'+r'[ .-]*'.join(key)+r'(?![A-Z0-9])',text.upper()))
    return False


def worker_identity_confirmed(db,worker,text):
    if identity_confirmed(worker.full_name,text,worker.identifier):return True
    if worker.identifier:return False
    stop={'de','del','la','las','los','y'}
    def tokens(value):return [part for part in re.findall(r'[a-z]+',normalize(value)) if part not in stop]
    def matches(name,line):
        wanted=tokens(name);available=tokens(re.split(r'\b(?:rut|run)\b',normalize(line))[0])
        if len(wanted)<2 or any(len(part)<3 for part in wanted) or len(available)>10:return False
        iterator=iter(available)
        return all(any(part==target for part in iterator) for target in wanted)
    lines=[line for line in text.splitlines() if re.search(r'\b(?:rut|run)\b',normalize(line)) and matches(worker.full_name,line)]
    if not lines:return False
    others=db.scalars(select(core.Worker).where(core.Worker.tenant_id==worker.tenant_id,core.Worker.id!=worker.id)).all()
    return any(not any(matches(other.full_name,line) for other in others) for line in lines)


def process_next(db,extractor=extract):
    if not enabled():return False
    latest=select(DocumentFileVersion.document_id,func.max(DocumentFileVersion.version).label('v')).group_by(DocumentFileVersion.document_id).subquery()
    query=select(DocumentFileVersion).join(core.Document,core.Document.id==DocumentFileVersion.document_id).join(FileSubject,FileSubject.document_id==DocumentFileVersion.document_id).join(latest,(latest.c.document_id==DocumentFileVersion.document_id)&(latest.c.v==DocumentFileVersion.version)).outerjoin(FileAnalysis,FileAnalysis.file_version_id==DocumentFileVersion.id).where(or_(FileAnalysis.id.is_(None),FileAnalysis.rules_version<ANALYSIS_RULES_VERSION)).order_by(DocumentFileVersion.id).limit(1).with_for_update(skip_locked=True,of=DocumentFileVersion)
    file=db.scalar(query)
    if file is None:return False
    identity=(file.id,file.document_id,file.tenant_id,file.version,file.created_by_user_id)
    row=db.scalar(select(FileAnalysis).where(FileAnalysis.file_version_id==file.id))
    if row and (row.status=='confirmed' or json.loads(row.result_json or '{}').get('confirmed_by')):
        doc=db.scalar(select(core.Document).where(core.Document.id==file.document_id,core.Document.tenant_id==file.tenant_id).with_for_update());user=db.get(core.User,file.created_by_user_id)
        if doc is None:
            row.status='superseded';row.rules_version=ANALYSIS_RULES_VERSION;db.commit();return True
        if latest_version(db,file.tenant_id,doc.id)!=file.version:row.status='superseded'
        else:
            result=json.loads(row.result_json)
            if result.get('document_type') in POLICY_VALID_TYPES:
                row.status='policy_valid';result['validity_exempt']=True
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
        result=interpret(text,notes,method,file_name=file.original_name)
        link=db.get(FileSubject,doc.id)
        identity_name=None;identity_identifier=None;worker=None
        if link.subject_kind=='company':identity_name=db.get(core.Tenant,doc.tenant_id).name
        elif link.subject_kind=='worker':
            worker=db.get(core.Worker,link.worker_id);identity_name=worker.full_name;identity_identifier=worker.identifier
        elif link.subject_kind=='project':identity_name=db.get(core.Project,doc.project_id).name
        if identity_name:
            if not (worker_identity_confirmed(db,worker,text) if worker else identity_confirmed(identity_name,text,identity_identifier)):
                result['warnings'].append('El contenido no confirma el nombre completo del destino. Revisa identidad y fechas.')
                result['safe_to_apply']=False
        elif link.subject_kind=='vehicle':
            plate=re.sub('[^A-Z0-9]','',(db.get(core.Vehicle,link.vehicle_id).plate or '').upper())
            pattern=r'(?<![A-Z0-9])'+r'[ .-]*'.join(re.escape(c) for c in plate)+r'(?![A-Z0-9])'
            if not plate or not re.search(pattern,text.upper()):
                result['warnings'].append('El contenido no confirma la patente del destino. Revisa identidad y fechas.')
                result['safe_to_apply']=False
    except Exception:
        db.rollback();result=interpret('', ['No se completó la lectura. Revisa el archivo original.'], 'unavailable',file_name=file.original_name)
    # End extraction's read transaction, then reload fresh metadata under lock.
    db.rollback()
    # Use the same document→tenant audit lock order as ordinary uploads.
    doc=db.scalar(select(core.Document).where(core.Document.id==identity[1],core.Document.tenant_id==identity[2]).with_for_update())
    row=db.get(FileAnalysis,analysis_id)
    if doc is None or doc.archived_at is not None:
        row.status='superseded';db.commit();return True
    if row.status=='confirmed' or json.loads(row.result_json or '{}').get('confirmed_by'):return True
    if latest_version(db,identity[2],doc.id)!=identity[3]:
        row.status='superseded'
    elif result.get('validity_exempt'):
        row.status='policy_valid'
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
    rows=db.execute(select(FileAnalysis.status,FileAnalysis.rules_version,FileAnalysis.result_json).select_from(DocumentFileVersion).join(core.Document,core.Document.id==DocumentFileVersion.document_id).join(FileSubject,FileSubject.document_id==DocumentFileVersion.document_id).join(latest,(latest.c.document_id==DocumentFileVersion.document_id)&(latest.c.v==DocumentFileVersion.version)).outerjoin(FileAnalysis,FileAnalysis.file_version_id==DocumentFileVersion.id).where(DocumentFileVersion.tenant_id==user.tenant_id,FileSubject.tenant_id==user.tenant_id)).all()
    counts={key:0 for key in ['pending','processing','review','ready','confirmed','no_expiry','policy_valid','superseded']}
    reasons={key:0 for key in ['ocr','identity','dates','missing_issue','partial','reading','other']}
    for status,version,result in rows:
        effective='pending' if version is None or version<ANALYSIS_RULES_VERSION else status if status in counts else 'review'
        counts[effective]+=1
        if effective=='review':
            categories=set()
            for warning in json.loads(result or '{}').get('warnings',[]):
                value=normalize(warning)
                if 'ocr' in value and warning!='OCR con confianza alta.':categories.add('ocr')
                if 'nombre completo' in value or 'patente del destino' in value:categories.add('identity')
                if any(word in value for word in ['varias fechas','varias columnas','contrad','difiere','anterior','invalida','futuro','no coinciden']):categories.add('dates')
                if 'alcohol y drogas' in value and 'emision' in value:categories.add('missing_issue')
                if 'parcial' in value:categories.add('partial')
                if 'no se completo' in value or 'no se pudo leer' in value:categories.add('reading')
            for category in categories or {'other'}:reasons[category]+=1
    return {'total':len(rows),'counts':counts,'review_reasons':reasons,'remaining':counts['pending']+counts['processing'],'rules_version':ANALYSIS_RULES_VERSION,'alcohol_drugs_days':DRUG_VALIDITY_DAYS,'drug_warning_days':7,'as_of':datetime.now(ZoneInfo('America/Santiago')).date()}
