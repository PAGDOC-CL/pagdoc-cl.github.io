from test_file_api import files,create,upload
from test_operations_api import client,login
from datetime import date,timedelta
import io,json,zipfile
from pathlib import Path
import pytest
from sqlalchemy import select
import app as core
import file_api
import document_analysis as analysis
from document_tools import extract,office_text,pdf_pages,raster_pdf


def pdf_document():
    stream=b'BT /F1 20 Tf 60 740 Td (Certificado ficticio - Demo One) Tj 0 -35 Td (Fecha de emision: 15/10/2026) Tj 0 -35 Td (Fecha de vencimiento: 15/10/2027) Tj ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    result=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(result));result+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(result);result+=f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    for offset in offsets[1:]:result+=f'{offset:010} 00000 n \n'.encode()
    return result+f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()


def word_document(text='Certificado ficticio. Fecha de emisión: 15/10/2026. Fecha de vencimiento: 15/10/2027'):
    from xml.sax.saxutils import escape
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>');archive.writestr('_rels/.rels','<Relationships/>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+escape(text)+'</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


@pytest.mark.parametrize('text,expected,ready',[
 ('Certificado. Fecha de vencimiento: 15/10/2027','2027-10-15',True),
 ('Certificado. Valido hasta: 2027-10-15','2027-10-15',True),
 ('Certificado. Fecha de vencimiento: 15 de octubre de 2027','2027-10-15',True),
 ('Permiso de circulacion. VENCE         31/08/2026','2026-08-31',True),
 ('Permiso de circulacion. VENCE                              31/08/2026','2026-08-31',True),
 ('Permiso de circulacion. Vence el 31/08/2026','2026-08-31',True),
 ('Permiso de circulacion. VENCE 31/08/2026. VENCE 31/03/2027',None,False),
 ('Permiso de circulacion. Convence 31/08/2026',None,False),
 ('Certificado. Emisión 15/10/2026',None,False),
 ('Certificado. Vencimiento: 31/02/2027',None,False),
 ('Certificado. Vencimiento: 15/10/2027. Vencimiento: 20/10/2027',None,False),
 ('Certificado. Fecha de emisión: 20/10/2027. Vencimiento: 15/10/2027','2027-10-15',False),
 ('Certificado. Fecha de emisión: 15/10/2026. Vigencia: 30 dias','2026-11-14',False),
 ('Documento con fecha 15/10/2027 sin etiqueta',None,False),
])
def test_only_unambiguous_labelled_dates_are_automatic(text,expected,ready):
    result=analysis.interpret(text,today=date(2026,10,15))
    assert result['expires_on']==expected
    assert result['safe_to_apply'] is ready
    assert not analysis.interpret(text,method='ocr',today=date(2026,10,15))['safe_to_apply']


def test_real_pdf_render_text_and_ocr_are_bounded_and_offline(tmp_path):
    payload=pdf_document();path=tmp_path/'fictitious.pdf';path.write_bytes(payload)
    assert pdf_pages(path,tmp_path)==1
    image=raster_pdf(path,1,tmp_path);assert image.startswith(b'\x89PNG')
    text,notes,method=extract(payload,'application/pdf')
    assert 'vencimiento' in text and method=='pdf_text' and not notes
    text,notes,method=extract(image,'image/png')
    assert method=='ocr' and any('OCR' in note for note in notes)
    assert 'Certificado' in text.replace(' ','')


def test_word_and_excel_dates_are_read_without_executing_formulas():
    media='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    text,notes=office_text(word_document(),media)
    assert analysis.interpret(text,notes,today=date(2026,10,15))['safe_to_apply']
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>');archive.writestr('_rels/.rels','<Relationships/>')
        archive.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        archive.writestr('xl/styles.xml','<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="14"/></cellXfs></styleSheet>')
        archive.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c t="inlineStr"><is><t>Certificado Vencimiento:</t></is></c><c s="0"><v>46675</v></c></row><row><c><f>NOW()</f><v>99999</v></c></row></sheetData></worksheet>')
    text,notes=office_text(output.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert '2027-10-15' in text and '99999' not in text
    assert notes and not analysis.interpret(text,notes)['safe_to_apply']


def test_background_analysis_applies_dates_and_replacement_clears_old_validity(files):
    c,store,scanner=files;identity=create(c);assert upload(c,identity,payload=pdf_document()).status_code==201
    with core.SessionLocal() as db:assert analysis.process_next(db)
    result=c.get(f'/ops/files/documents/{identity}/analysis').json()
    assert result['status']=='ready' and result['expires_on']=='2027-10-15'
    assert c.get('/ops/files/documents',params={'document_type':'certificado'}).json()['total']==1
    assert c.get('/ops/files/documents',params={'document_type':'sin_clasificar'}).json()['total']==0
    assert c.get('/ops/files/documents',params={'document_type':'invalid'}).status_code==422
    assert c.get('/ops/files/documents').json()['items'][0]['review_state']=='pending'
    assert upload(c,identity,version=1,payload=b'%PDF-1.7\n% fictitious unreadable replacement\n%%EOF').status_code==201
    assert c.get(f'/ops/files/documents/{identity}/analysis').json()['expires_on'] is None
    assert c.get('/ops/files/documents',params={'document_type':'sin_clasificar'}).json()['total']==1
    with core.SessionLocal() as db:assert analysis.process_next(db)
    assert c.get(f'/ops/files/documents/{identity}/analysis').json()['status']=='review'
    assert c.get(f'/ops/files/documents/{identity}/versions/1/download').content==pdf_document()


def test_analysis_confirmation_is_scoped_csrf_protected_and_version_checked(files):
    c,store,scanner=files;identity=create(c);assert upload(c,identity).status_code==201
    with core.SessionLocal() as db:analysis.process_next(db,lambda *args:('Certificado Vencimiento: 15/10/2027',['Lectura OCR pendiente'],'ocr'))
    route=f'/ops/files/documents/{identity}/analysis/confirm';payload={'document_type':'certificado','issued_on':'2026-10-15','expires_on':'2027-10-15','expected_version':1,'reason':'Verificado contra vista previa ficticia'}
    login(c,2);assert c.post(route,json=payload).status_code==404
    login(c,5);assert c.post(route,json=payload).status_code==403
    login(c);del c.headers['X-PAGDOC-CSRF'];assert c.post(route,json=payload).status_code==403
    login(c);assert c.post(route,json={**payload,'expected_version':2}).status_code==409
    assert c.post(route,json=payload).json()['status']=='confirmed'
    assert c.post(route,json=payload).status_code==409
    assert c.get('/ops/files/documents').json()['items'][0]['review_state']=='pending'


def test_preview_is_private_and_does_not_download_the_original(files):
    c,store,scanner=files;identity=create(c);assert upload(c,identity,payload=pdf_document()).status_code==201
    route=f'/ops/files/documents/{identity}/versions/1/preview'
    assert c.get(route).json()['kind']=='pdf'
    image=c.get(route+'/page?page=1');assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    assert image.headers['cache-control']=='no-store' and image.headers['content-disposition']=='inline'
    assert c.get(route+'/page?page=2').status_code==404
    login(c,2);assert c.get(route).status_code==404 and c.get(route+'/page').status_code==404
    login(c,3);assert c.get(route).status_code==403
    login(c);c.post('/auth/logout');assert c.get(route).status_code==401


def test_office_preview_is_text_and_escapable_not_executable(files):
    c,store,scanner=files;identity=create(c)
    payload=word_document('Certificado ficticio. <img src=x onerror=alert(1)>')
    assert upload(c,identity,payload=payload,filename='fictitious.docx',media='application/vnd.openxmlformats-officedocument.wordprocessingml.document').status_code==201
    data=c.get(f'/ops/files/documents/{identity}/versions/1/preview').json()
    assert data['kind']=='text' and '<img' in data['text'] and 'formato original' in data['note']


def test_folder_destinations_are_exact_scoped_and_support_workers_and_projects(files):
    c,store,scanner=files
    paths=['01_ACREDITACION_EMPRESA/Certificados/a.pdf','Vehiculos/TEST11/a.pdf','Trabajadores/Demo Worker/a.pdf','Proyectos/Demo Project/a.pdf','Vehiculos/TEST22/a.pdf','Sin destino/a.pdf']
    result=c.post('/ops/files/batch/destinations',json={'paths':paths}).json()['items']
    assert [item['subject_kind'] for item in result]==['company','vehicle','worker','project',None,None]
    for index in [2,3]:
        item=result[index];entry={key:item.get(key) for key in ['path','subject_kind','vehicle_id','worker_id','project_id']};entry['sha256']='0'*64
        preview=c.post('/ops/files/batch/preview',json={'entries':[entry]});assert preview.status_code==200,preview.text
        plan=preview.json()['items'][0]
        query={key:value for key,value in entry.items() if key!='sha256' and value is not None};query['expected_version']=0
        saved=c.post('/ops/files/batch/item',params=query,content=pdf_document(),headers={'Content-Type':'application/pdf'})
        assert saved.status_code==201,saved.text
    folders=c.get('/ops/files/folders').json()['folders'];assert any(f['path']=='Trabajadores/Demo Worker' for f in folders)
    assert c.get('/ops/files/documents',params={'path_prefix':'Trabajadores'}).json()['total']==1
    login(c,2);assert c.get('/ops/files/folders').json()['folders']==[]


def test_conflicting_metadata_and_superseded_analysis_are_never_applied(files):
    c,store,scanner=files;identity=create(c,expires_on='2099-01-01');assert upload(c,identity,payload=pdf_document()).status_code==201
    with core.SessionLocal() as db:analysis.process_next(db)
    result=c.get(f'/ops/files/documents/{identity}/analysis').json()
    assert result['status']=='review' and result['expires_on']=='2099-01-01'
    assert upload(c,identity,version=1,payload=b'%PDF-1.7\n% fictitious v2\n%%EOF').status_code==201
    def replaced_during_analysis(*args):
        assert upload(c,identity,version=2,payload=b'%PDF-1.7\n% fictitious v3\n%%EOF').status_code==201
        return ('Certificado Vencimiento: 15/10/2027',[],'pdf_text')
    with core.SessionLocal() as db:analysis.process_next(db,replaced_during_analysis)
    current=c.get(f'/ops/files/documents/{identity}/analysis').json()
    assert current['version']==3 and current['status']=='pending' and current['expires_on'] is None
    with core.SessionLocal() as db:
        old=db.scalar(select(analysis.FileAnalysis).join(analysis.DocumentFileVersion,analysis.DocumentFileVersion.id==analysis.FileAnalysis.file_version_id).where(analysis.FileAnalysis.document_id==identity,analysis.DocumentFileVersion.version==2))
        assert old.status=='superseded'


def test_worker_restart_requeues_only_incomplete_analysis(files):
    from analysis_worker import recover_interrupted
    c,store,scanner=files
    first=create(c);second=create(c)
    assert upload(c,first).status_code==201 and upload(c,second).status_code==201
    with core.SessionLocal() as db:
        versions=list(db.scalars(select(analysis.DocumentFileVersion).order_by(analysis.DocumentFileVersion.id)))
        db.add(analysis.FileAnalysis(tenant_id=1,document_id=first,file_version_id=versions[0].id,status='processing'))
        db.add(analysis.FileAnalysis(tenant_id=1,document_id=second,file_version_id=versions[1].id,status='confirmed',result_json='{"document_type":"certificado","revision":1}'))
        db.commit()
        assert recover_interrupted(db)==1
        assert db.scalar(select(analysis.FileAnalysis).where(analysis.FileAnalysis.document_id==second)).status=='confirmed'
        assert len(list(db.scalars(select(analysis.DocumentFileVersion))))==2
    assert len(list(store.root.rglob('*.bin')))==2


@pytest.mark.parametrize('text,expiry,safe',[
 ('Examen de drogas. Fecha de emisión: 15/10/2026','2026-11-14',True),
 ('Alcohol y drogas. Fecha de emisión: 31/12/2025','2026-01-30',True),
 ('Test de drogas. Fecha de emisión: 01/02/2024','2024-03-02',True),
 ('Alcohol y drogas. Fecha de realización: 15/10/2026',None,False),
 ('Alcohol y drogas. Fecha de emisión: 15/10/2026. Vencimiento: 15/10/2027','2026-11-14',False),
 ('Alcohol y drogas. Fecha de emisión: 15/10/2026. Fecha de emisión: 16/10/2026',None,False),
 ('Alcohol y drogas. Fecha de emisión: 15/10/2027','2027-11-14',False),
])
def test_drug_policy_uses_unique_issue_and_thirty_days(text,expiry,safe):
    result=analysis.interpret(text,today=date(2026,10,15))
    assert result['document_type']=='alcohol_drogas'
    assert result['expires_on']==expiry and result['safe_to_apply']==safe
    assert result['validity_days']==30
    assert not analysis.interpret(text,method='ocr',today=date(2026,10,15))['safe_to_apply']


def test_existing_confirmed_drug_dates_recalculated_without_replacing_binary(files):
    c,_,_=files;identity=create(c);assert upload(c,identity,payload=pdf_document()).status_code==201
    from file_records import DocumentFileVersion
    issued=date.today()-timedelta(days=20)
    with core.SessionLocal() as db:
        version=db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.document_id==identity))
        db.get(core.Document,identity).expires_on=issued+timedelta(days=365)
        db.add(analysis.FileAnalysis(tenant_id=1,document_id=identity,file_version_id=version.id,status='confirmed',rules_version=1,result_json=json.dumps({'document_type':'alcohol_drogas','issued_on':issued.isoformat(),'expires_on':(issued+timedelta(days=365)).isoformat(),'revision':3})));db.commit()
        assert analysis.process_next(db,extractor=lambda *_:pytest.fail('No need to reread verified issue'))
        assert not analysis.process_next(db)
    payload=c.get(f'/ops/files/documents/{identity}/analysis').json()
    assert payload['expires_on']==(issued+timedelta(days=30)).isoformat() and payload['revision']==4
    assert len(c.get(f'/ops/files/documents/{identity}/versions').json())==1
    assert c.get('/ops/files/documents').json()['items'][0]['expiry_status']=='valid'
    assert c.get('/ops/files/analysis/status').json()['counts']['confirmed']==1
    login(c,2);assert c.get('/ops/files/analysis/status').json()['total']==0


def test_drug_confirmation_enforces_thirty_day_rule(files):
    c,_,_=files;identity=create(c);assert upload(c,identity,payload=pdf_document()).status_code==201
    with core.SessionLocal() as db:assert analysis.process_next(db)
    issued=date.today()-timedelta(days=2)
    data={'expected_version':1,'expected_revision':0,'document_type':'alcohol_drogas','issued_on':issued.isoformat(),'expires_on':(issued+timedelta(days=31)).isoformat(),'reason':'Fictitious date review'}
    assert c.post(f'/ops/files/documents/{identity}/analysis/confirm',json=data).status_code==422
    data['expires_on']=(issued+timedelta(days=30)).isoformat()
    assert c.post(f'/ops/files/documents/{identity}/analysis/confirm',json=data).status_code==200
    data['issued_on']=None
    assert c.post(f'/ops/files/documents/{identity}/analysis/confirm',json=data).status_code==422


def test_prior_automatic_drug_analysis_is_revisited_once(files):
    c,_,_=files;identity=create(c);assert upload(c,identity,payload=pdf_document()).status_code==201
    from file_records import DocumentFileVersion
    issued=date.today()-timedelta(days=5)
    with core.SessionLocal() as db:
        version=db.scalar(select(DocumentFileVersion).where(DocumentFileVersion.document_id==identity))
        db.get(core.Document,identity).expires_on=issued+timedelta(days=365)
        db.add(analysis.FileAnalysis(tenant_id=1,document_id=identity,file_version_id=version.id,status='ready',rules_version=1,result_json=json.dumps({'document_type':'alcohol_drogas','issued_on':issued.isoformat(),'expires_on':(issued+timedelta(days=365)).isoformat()})));db.commit()
        text='Examen de drogas. Demo One. Fecha de emisión: '+issued.isoformat()
        assert analysis.process_next(db,extractor=lambda *_:(text,[],'pdf_text'))
        assert not analysis.process_next(db)
    result=c.get(f'/ops/files/documents/{identity}/analysis').json()
    assert result['status']=='ready' and result['expires_on']==(issued+timedelta(days=30)).isoformat()


@pytest.mark.parametrize('days,light',[(8,'valid'),(7,'expiring'),(-1,'expired')])
def test_drug_traffic_lights_use_last_seven_days(days,light):
    from types import SimpleNamespace
    today=analysis.datetime.now(analysis.ZoneInfo('America/Santiago')).date()
    row=SimpleNamespace(status='ready',result_json=json.dumps({'document_type':'alcohol_drogas'}))
    assert analysis.analysis_payload(row,SimpleNamespace(expires_on=today+timedelta(days=days)),1)['traffic_light']==light


@pytest.mark.parametrize('label',['VÁLIDO HASTA','PERIODO / VENCIMIENTO','CADUCA EL','EXPIRA EL','VALIDEZ HASTA','VCTO','FECHA VENC'])
def test_expiry_table_headings_on_previous_line(label):
    result=analysis.interpret('Permiso de circulacion\n'+label+'     PLACA UNICA\n31-03-2027     TEST11')
    assert result['expires_on']=='2027-03-31' and result['safe_to_apply']


def test_ambiguous_table_dates_do_not_become_no_expiry():
    result=analysis.interpret('Certificado\nVÁLIDO HASTA FECHA EMISION\n31/03/2027 01/02/2026')
    assert not result['safe_to_apply'] and not result['no_expiry']


@pytest.mark.parametrize('text',['Carta simple sin fechas','Procedimiento. Fecha de emisión: 01/02/2026','Lista de verificacion sin vencimiento indicado'])
def test_internal_policy_no_expiry_without_inventing_dates(text):
    result=analysis.interpret(text)
    assert result['no_expiry'] and result['expires_on'] is None


@pytest.mark.parametrize('text,notes',[('',None),('Alcohol y drogas sin fecha',None),('Certificado VENCE ilegible',None),('Carta simple',['Lectura parcial: PDF supera 12 páginas.'])])
def test_missing_or_failed_reading_is_not_no_expiry(text,notes):
    assert not analysis.interpret(text,notes)['no_expiry']


def test_no_expiry_policy_applies_existing_private_file_and_preserves_review(files):
    c,_,_=files;identity=create(c);assert upload(c,identity,payload=pdf_document()).status_code==201
    with core.SessionLocal() as db:
        assert analysis.process_next(db,extractor=lambda *_:('Demo One. Carta simple sin fechas',[],'pdf_text'))
    row=c.get('/ops/files/documents').json()['items'][0]
    assert row['expiry_status']=='valid' and row['expires_on'] is None
    assert row['analysis']['no_expiry'] and row['analysis']['traffic_light']=='valid'
    assert row['review_state']=='pending'
    assert c.get('/ops/files/analysis/status').json()['counts']['no_expiry']==1


def test_spaced_numeric_dates_and_mixed_table_columns():
    result=analysis.interpret('Certificado. Válido hasta 31 / 03 / 2027')
    assert result['expires_on']=='2027-03-31' and result['safe_to_apply']
    result=analysis.interpret('Certificado\nVENCIMIENTO FECHA EMISION\n31/03/2027')
    assert result['expires_on'] is None and not result['no_expiry']


def test_clear_expiry_is_independent_of_general_classification():
    result=analysis.interpret('Documento general. Fecha de vencimiento: 31/03/2027')
    assert result['document_type']=='sin_clasificar' and result['safe_to_apply']
    result=analysis.interpret('Examen de drogas y procedimiento. Fecha de vencimiento: 31/03/2027')
    assert not result['safe_to_apply']


@pytest.mark.parametrize('label',[
    'La vigencia de este certificado es hasta el día',
    'Vigencia hasta el día',
    'Vigencia de este documento hasta',
])
def test_worker_certificate_narrative_validity(label):
    result=analysis.interpret('Certificado de aprobación. '+label+' 09 de Septiembre de 2028.')
    assert result['expires_on']=='2028-09-09'
    assert result['safe_to_apply'] and not result['no_expiry']


def test_worker_ppe_delivery_date_is_not_expiration():
    result=analysis.interpret('FORMULARIO DE ENTREGA DE ELEMENTOS DE PROTECCION PERSONAL. Fecha: 15-06-2026. FECHA ENTREGA 15-06-2026')
    assert result['expires_on'] is None and result['no_expiry']


def test_worker_narrative_expiry_unreadable_requires_review():
    result=analysis.interpret('Certificado. La vigencia de este certificado es hasta el día [ilegible]')
    assert not result['no_expiry'] and not result['safe_to_apply']


@pytest.mark.parametrize('kind,label',[
    ('Examen preocupacional','Fecha de vigencia'),
    ('Evaluación preocupacional','Vigente hasta'),
    ('Examen ocupacional','Vencimiento'),
])
def test_worker_occupational_explicit_validity(kind,label):
    result=analysis.interpret(kind+'. '+label+': 15/10/2027', ['OCR con confianza alta.'], 'ocr')
    assert result['document_type']=='examen_ocupacional'
    assert result['expires_on']=='2027-10-15' and result['safe_to_apply']


def test_high_confidence_ocr_preserves_drug_rule_and_low_confidence_review():
    text='Alcohol y drogas. Fecha de emisión: 01/10/2026'
    result=analysis.interpret(text,['OCR con confianza alta.'],'ocr',today=date(2026,10,16))
    assert result['expires_on']=='2026-10-31' and result['safe_to_apply']
    result=analysis.interpret(text,['OCR con confianza insuficiente: revisar lectura.'],'ocr')
    assert not result['safe_to_apply'] and not result['no_expiry']
    assert not analysis.interpret('Carta sin fechas',['OCR con confianza insuficiente: revisar lectura.'],'ocr')['no_expiry']


@pytest.mark.parametrize('score,numeric_score,expected',[(96,96,True),(96,70,False),(60,96,False),(96,None,True)])
def test_ocr_confidence_gate_uses_numeric_words_and_overall_quality(tmp_path,monkeypatch,score,numeric_score,expected):
    import document_tools as tools
    def fake_command(args,directory,timeout):
        target=tmp_path/'ocr-result'
        target.with_suffix('.txt').write_text('Certificado ficticio')
        rows='level\tconf\ttext\n5\t'+str(score)+'\tCertificado\n'
        if numeric_score is not None:rows+='5\t'+str(numeric_score)+'\t15/10/2027\n'
        target.with_suffix('.tsv').write_text(rows)
    monkeypatch.setattr(tools,'command',fake_command)
    notes=[]
    assert tools.ocr_text(tmp_path/'source.png',tmp_path,notes)=='Certificado ficticio'
    assert ('OCR con confianza alta.' in notes) is expected



def test_document_summary_counts_current_files_all_modules_and_drug_window(files):
    c,_,_=files
    today=analysis.datetime.now(analysis.ZoneInfo('America/Santiago')).date()
    entries=[
        ({'subject_kind':'company'},None,'no_expiry','certificado'),
        ({'subject_kind':'vehicle','vehicle_id':1},today-timedelta(days=1),'ready','revision_tecnica'),
        ({'subject_kind':'worker','worker_id':1},today+timedelta(days=30),'ready','examen_ocupacional'),
        ({'subject_kind':'project','project_id':1},None,None,None),
        ({'subject_kind':'worker','worker_id':1},today+timedelta(days=8),'ready','alcohol_drogas'),
    ]
    for i,(subject,expiry,status,kind) in enumerate(entries):
        identity=create(c,title='Fictitious summary '+str(i),expires_on=expiry.isoformat() if expiry else None,**subject)
        assert upload(c,identity).status_code==201
        if i==0:assert upload(c,identity,version=1,payload=b'%PDF-1.7\n% fictitious latest version\n%%EOF').status_code==201
        if status:
            with core.SessionLocal() as db:
                version=db.scalar(select(analysis.DocumentFileVersion).where(analysis.DocumentFileVersion.document_id==identity).order_by(analysis.DocumentFileVersion.version.desc()))
                db.add(analysis.FileAnalysis(document_id=identity,tenant_id=1,file_version_id=version.id,status=status,result_json=json.dumps({'document_type':kind})));db.commit()
    create(c,title='Metadata without uploaded file',expires_on=(today+timedelta(days=365)).isoformat())
    result=c.get('/ops/files/summary').json()
    assert result['total']==5 and result['counts']=={'valid':2,'expired':1,'expiring':1,'pending':1}
    listed=c.get('/ops/files/documents').json()['items']
    for state,key in [('valid','valid'),('expired','expired'),('expiring','expiring'),('no_date','pending')]:
        assert sum(item['expiry_status']==state for item in listed if item['version'])==result['counts'][key]
    login(c,2)
    assert c.get('/ops/files/summary').json()['total']==0
    login(c,3)
    assert c.get('/ops/files/summary').status_code==403
    c.post('/auth/logout')
    assert c.get('/ops/files/summary').status_code==401



@pytest.mark.parametrize('label',['Vigencia:','Fecha de término:','Fecha de expiración:','Validez:'])
def test_additional_explicit_expiry_labels(label):
    result=analysis.interpret('Certificado ficticio. '+label+' 15/10/2027')
    assert result['expires_on']=='2027-10-15' and result['safe_to_apply']


@pytest.mark.parametrize('second,conflict',[
    ('Certificado. Vence 15/10/2027',False),
    ('Certificado. Vence 16/10/2027',True),
    ('Certificado sin fecha legible',True),
])
def test_deep_ocr_second_layout_and_date_disagreements(tmp_path,monkeypatch,second,conflict):
    import document_tools as tools
    modes=[]
    def fake_ocr(path,directory,notes,psm=3):
        modes.append(psm)
        notes.append('OCR con confianza insuficiente: revisar lectura.' if psm==3 else 'OCR con confianza alta.')
        return 'Certificado. Vence 15/10/2027' if psm==3 else second
    monkeypatch.setattr(tools,'ocr_text',fake_ocr)
    notes=[];text=tools.ocr_deep(tmp_path/'scan.png',tmp_path,notes)
    assert modes==[3,6] and text==second
    result=analysis.interpret(text,notes,'ocr')
    assert result['safe_to_apply'] is (not conflict)
    if conflict:assert any('no coinciden' in note for note in notes)


def test_deep_ocr_partial_failure_never_automatically_applies(tmp_path,monkeypatch):
    import document_tools as tools
    def fake_ocr(path,directory,notes,psm=3):
        if psm==6:raise tools.ExtractionError('timeout')
        notes.append('OCR con confianza alta.');return 'Certificado Vence 15/10/2027'
    monkeypatch.setattr(tools,'ocr_text',fake_ocr)
    notes=[];text=tools.ocr_deep(tmp_path/'scan.png',tmp_path,notes)
    assert not analysis.interpret(text,notes,'ocr')['safe_to_apply']


def test_hybrid_pdf_reads_raster_dates_with_long_digital_text(monkeypatch):
    import document_tools as tools
    monkeypatch.setattr(tools,'pdf_pages',lambda *_:1)
    monkeypatch.setattr(tools,'pdf_image_pages',lambda *_,**kw:({1},set()))
    def fake_command(args,directory,timeout=35):
        Path(args[-1]).write_text('Certificado ficticio. Nombre y texto digital sin fecha.'*3)
    monkeypatch.setattr(tools,'command',fake_command)
    monkeypatch.setattr(tools,'raster_pdf',lambda *_,**kw:b'fake bounded raster')
    def fake_deep(path,directory,notes):
        notes.append('OCR con confianza alta.');return 'Vigente hasta 15/10/2027'
    monkeypatch.setattr(tools,'ocr_deep',fake_deep)
    text,notes,method=tools.extract(b'%PDF-fictitious','application/pdf')
    assert 'Nombre y texto digital' in text and '15/10/2027' in text and method=='ocr'
    assert analysis.interpret(text,notes,method)['safe_to_apply']


def test_pdf_inventory_detects_large_raster_regions(tmp_path,monkeypatch):
    import document_tools as tools
    def fake_run(args,**kwargs):
        kwargs['stdout'].write(b'page num type width height\n1 0 image 100 100\n2 1 image 1800 2400\n3 2 image 900 200\n')
    monkeypatch.setattr(tools.subprocess,'run',fake_run)
    assert tools.pdf_image_pages(tmp_path/'test.pdf',tmp_path)=={2,3}


def test_rules_six_reprocesses_automatic_analysis_and_reports_causes(files):
    c,_,_=files;identity=create(c);assert upload(c,identity).status_code==201
    with core.SessionLocal() as db:
        version=db.scalar(select(analysis.DocumentFileVersion).where(analysis.DocumentFileVersion.document_id==identity))
        db.add(analysis.FileAnalysis(tenant_id=1,document_id=identity,file_version_id=version.id,status='review',rules_version=5,result_json='{}'));db.commit()
    progress=c.get('/ops/files/analysis/status').json()
    assert progress['total']==1 and progress['remaining']==1
    with core.SessionLocal() as db:
        assert analysis.process_next(db,extractor=lambda *_:('Certificado. Demo One. Vence 15/10/2027',['OCR con confianza insuficiente: revisar lectura.'],'ocr'))
    progress=c.get('/ops/files/analysis/status').json()
    assert progress['remaining']==0 and progress['counts']['review']==1
    assert progress['review_reasons']['ocr']==1
    with core.SessionLocal() as db:assert not analysis.process_next(db)



@pytest.mark.parametrize('name,text,identifier,expected',[
    ('Persona Ficticia','Certificado Persona Ficticia',None,True),
    ('Persona Ficticia','Certificado Ficticia Persona. RUT 12.345.678-5','12345678-5',True),
    ('Persona Ficticia','Certificado Ficticia Persona. RUT 12.345.678-6','12345678-5',False),
    ('Persona Ficticia','Certificado RUT 1123456785','12345678-5',False),
    ('Persona Ficticia','Certificado RUT 12345678-5A','12345678-5',False),
    ('Persona Ficticia','Otra persona',None,False),
])
def test_exact_worker_identifier_handles_name_order_without_fuzzy_matching(name,text,identifier,expected):
    assert analysis.identity_confirmed(name,text,identifier) is expected


@pytest.mark.parametrize('text,expected,safe',[
    ('SOAP RIGE DESDE: 01-03-2026 HASTA: 31-03-2027','2027-03-31',True),
    ('Seguro Obligatorio de Accidentes Personales. RIGE DESDE: 01-03-2026 HASTA: 31-03-2027\nRIGE DESDE: 01-03-2026 HASTA: 31-03-2027','2027-03-31',True),
    ('SOAP RIGE DESDE: 01-03-2026 HASTA: 31-03-2027\nRIGE DESDE: 01-03-2026 HASTA: 31-08-2027',None,False),
    ('SOAP RIGE DESDE: 01-03-2026 HASTA: 31-02-2027',None,False),
    ('SOAP RIGE DESDE: 01-03-2027 HASTA: 01-03-2026',None,False),
    ('SOAP sin fechas',None,False),
])
def test_soap_coverage_range_is_explicit_not_issue_date(text,expected,safe):
    result=analysis.interpret(text,today=date(2026,10,17))
    assert result['document_type']=='soap' and result['expires_on']==expected
    assert result['safe_to_apply'] is safe and not result['no_expiry']
    assert result['issued_on'] is None
    if safe:assert result['valid_from']=='2026-03-01'


def test_generic_hasta_or_rige_desde_is_not_soap_expiration():
    result=analysis.interpret('Contrato. Rige desde: 01-03-2026 hasta: 31-03-2027')
    assert result['expires_on'] is None


@pytest.mark.parametrize('full_scan',[False,True])
def test_small_graphics_do_not_override_clear_digital_dates_but_full_scans_are_checked(monkeypatch,full_scan):
    import document_tools as tools
    monkeypatch.setattr(tools,'pdf_pages',lambda *_:1)
    monkeypatch.setattr(tools,'pdf_image_pages',lambda *_,**kw:({1},{1} if full_scan else set()))
    def fake_command(args,directory,timeout=35):
        Path(args[-1]).write_text('Seguro Obligatorio de Accidentes Personales. RIGE DESDE: 01-03-2026 HASTA: 31-03-2027')
    monkeypatch.setattr(tools,'command',fake_command)
    monkeypatch.setattr(tools,'raster_pdf',lambda *_,**kw:b'synthetic raster')
    calls=[]
    def fake_ocr(path,directory,notes):
        calls.append(True);notes.append('OCR con confianza insuficiente: revisar lectura.')
        return 'SOAP Vence 31-03-2028'
    monkeypatch.setattr(tools,'ocr_deep',fake_ocr)
    text,notes,method=tools.extract(b'%PDF-fictitious','application/pdf')
    assert bool(calls) is full_scan
    result=analysis.interpret(text,notes,method,today=date(2026,10,17))
    assert result['safe_to_apply'] is (not full_scan)
    if not full_scan:assert method=='pdf_text' and result['expires_on']=='2027-03-31'



def test_image_inventory_distinguishes_signature_from_full_page_scan(tmp_path,monkeypatch):
    import document_tools as tools
    (tmp_path/'info.txt').write_text('Page size: 612 x 792 pts (letter)')
    def fake_run(args,**kwargs):
        kwargs['stdout'].write(b'page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio\n1 0 image 615 223 rgb 3 8 jpeg no 1 0 72 72 123B 1%\n2 1 image 2550 3300 rgb 3 8 jpeg no 2 0 300 300 123B 1%\n')
    monkeypatch.setattr(tools.subprocess,'run',fake_run)
    assert tools.pdf_image_pages(tmp_path/'synthetic.pdf',tmp_path,with_scans=True)==({1,2},{2})



def test_soap_explicit_expiry_does_not_require_a_coverage_range():
    result=analysis.interpret('SOAP. Fecha de vencimiento: 31/03/2027')
    assert result['safe_to_apply'] and result['expires_on']=='2027-03-31'
    assert result['valid_from'] is None and result['issued_on'] is None


def test_mixed_soap_classification_without_dates_is_not_no_expiry():
    result=analysis.interpret('SOAP y procedimiento. Sin fechas legibles')
    assert not result['no_expiry'] and not result['safe_to_apply']



def test_soap_coverage_is_saved_and_returned_separately_from_emission(files):
    c,_,_=files;identity=create(c,subject_kind='vehicle',vehicle_id=1)
    payload=word_document('Seguro Obligatorio de Accidentes Personales. TEST11. RIGE DESDE: 01-03-2026 HASTA: 31-03-2027')
    assert upload(c,identity,payload=payload,filename='synthetic-soap.docx',media='application/vnd.openxmlformats-officedocument.wordprocessingml.document').status_code==201
    with core.SessionLocal() as db:assert analysis.process_next(db)
    result=c.get(f'/ops/files/documents/{identity}/analysis').json()
    assert result['status']=='ready' and result['document_type']=='soap'
    assert result['valid_from']=='2026-03-01' and result['issued_on'] is None
    assert result['expires_on']=='2027-03-31'
    assert c.get('/ops/files/documents',params={'document_type':'soap'}).json()['total']==1
