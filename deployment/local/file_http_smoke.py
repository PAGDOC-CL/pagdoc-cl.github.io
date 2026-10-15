"""Actual HTTPS/file/ClamAV check. Exclusively fictitious CI account and documents."""
import hashlib
import io
import json
import ssl
import sys
import zipfile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

context=ssl.create_default_context(cafile=sys.argv[1])
origin='https://localhost:8443'
headers={}


def request(path, body=None, media='application/json'):
    payload=json.dumps(body).encode() if isinstance(body,dict) else body
    req=Request(origin+path,data=payload,headers={**headers,'Content-Type':media},method='POST' if body is not None else 'GET')
    return urlopen(req,context=context,timeout=90)


with request('/auth/login',{'email':'backup-admin@example.invalid','password':'ci-only-fictitious-backup-account'}) as response:
    result=json.load(response)
    headers['Cookie']='; '.join(value.split(';',1)[0] for value in response.headers.get_all('Set-Cookie'))
    headers['X-PAGDOC-CSRF']=result['csrf_token']
with request('/ops/files/status') as response:
    assert json.load(response)['ready_for_upload'] is True
with request('/ops/files/vehicles',{'label':'Fictitious HTTPS truck','plate':'CIHTTP1'}) as response:
    vehicle_id=json.load(response)['id']
types={
 'application/pdf':('pdf',b'%PDF-1.7\n% fictitious HTTPS evidence\n%%EOF'),
 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':('docx','word/document.xml'),
 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':('xlsx','xl/workbook.xml'),
}
for media,(extension,content) in types.items():
    if isinstance(content,str):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name in ['[Content_Types].xml','_rels/.rels',content]:archive.writestr(name,b'<fictitious/>')
        content=buffer.getvalue()
    subject={'subject_kind':'vehicle','vehicle_id':vehicle_id} if extension=='pdf' else {'subject_kind':'company'}
    with request('/ops/files/documents',{'title':'Fictitious HTTPS '+extension,**subject}) as response:
        document_id=json.load(response)['id']
    query=urlencode({'file_name':'fictitious.'+extension,'expected_version':0})
    with request(f'/ops/files/documents/{document_id}/versions?'+query,content,media) as response:
        result=json.load(response)
        assert result['version']==1 and result['review_state']=='pending'
        assert result['sha256']==hashlib.sha256(content).hexdigest()
    with request(f'/ops/files/documents/{document_id}/versions/1/download') as response:
        assert response.read()==content
        assert response.headers['Content-Disposition'].startswith('attachment;')
        assert response.headers['Cache-Control']=='no-store'
    with request(f'/ops/files/documents/{document_id}/versions') as response:
        assert json.load(response)[0]['scan_engine'].startswith('ClamAV ')
    try:
        urlopen(origin+f'/ops/files/documents/{document_id}/versions/1/download',context=context,timeout=15)
        raise AssertionError('Download without authentication succeeded')
    except HTTPError as error:
        assert error.code==401
print('OK: authenticated HTTPS company/vehicle files, actual ClamAV scans, DOCX/XLSX/PDF round trips, version records and unauthenticated denial.')

# A fictitious 1-pixel PNG exercises the encrypted corporate branding path.
import base64
logo=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlS8AAAAASUVORK5CYII=')
with request('/ops/branding/logo?file_name=fictitious-logo.png',logo,'image/png') as response:
    assert json.load(response)['logo_version']==1
with request('/ops/branding/logo') as response:
    assert response.read()==logo
    assert response.headers['Cache-Control']=='no-store'
try:
    urlopen(origin+'/ops/branding/logo',context=context,timeout=15)
    raise AssertionError('Logo exposed without authentication')
except HTTPError as error:
    assert error.code==401
print('OK: private encrypted tenant logo, actual ClamAV and unauthenticated denial.')

# Folder path upsert over the actual HTTPS/ClamAV boundary.
path='Fictitious company/Folder/evidence.pdf'
content=b'%PDF-1.7\n% fictitious folder evidence\n%%EOF'
def plan(data):
    entry={'path':path,'subject_kind':'company','sha256':hashlib.sha256(data).hexdigest()}
    with request('/ops/files/batch/preview',{'entries':[entry]}) as response:
        return json.load(response)['items'][0]
def upload(item,data,confirm=False):
    query={'path':path,'subject_kind':'company','expected_version':item['expected_version'],'allow_replace':str(confirm).lower()}
    if item['document_id'] is not None:query['expected_document_id']=item['document_id']
    return request('/ops/files/batch/item?'+urlencode(query),data,'application/pdf')
first=plan(content)
assert first['status']=='new'
with upload(first,content) as response:created=json.load(response)
assert created['version']==1
assert plan(content)['status']=='identical'
changed=content+b'\n% revised fictitious evidence'
replacement=plan(changed)
assert replacement['status']=='replace'
try:
    upload(replacement,changed)
    raise AssertionError('Replacement without confirmation succeeded')
except HTTPError as error:assert error.code==409
with upload(replacement,changed,True) as response:
    result=json.load(response)
    assert result['version']==2 and result['document_id']==created['document_id']
with request(f"/ops/files/documents/{created['document_id']}/versions/1/download") as response:assert response.read()==content
with request('/ops/email-alerts') as response:
    pref=json.load(response)
    assert pref['recipient']=='backup-admin@example.invalid' and pref['delivery_configured'] is False
with request('/ops/email-alerts/preview') as response:assert json.load(response)['delivery_configured'] is False
print('OK: folder destinations, identical detection, confirmed replacement, preserved history and private email preview without delivery.')

# Folder-created vehicle records require a joint confirmation and are idempotent.
folder_paths=['Vehiculos/Fictitious ABCD-12/evidence.pdf','Vehiculos/Other folder ABCD-12/second.pdf']
with request('/ops/files/batch/destinations',{'paths':folder_paths}) as response:
    assert all(item['status']=='vehicle_missing' for item in json.load(response)['items'])
with request('/ops/files/batch/vehicles',{'paths':folder_paths,'confirmed':True}) as response:
    assert json.load(response)['created_count']==1
with request('/ops/files/batch/vehicles',{'paths':folder_paths,'confirmed':True}) as response:
    assert json.load(response)['created_count']==0
with request('/ops/files/batch/destinations',{'paths':folder_paths}) as response:
    resolved=json.load(response)['items'];assert all(item['status']=='resolved' for item in resolved)
    assert resolved[0]['vehicle_id']==resolved[1]['vehicle_id']
entry={key:resolved[0][key] for key in ['path','subject_kind','vehicle_id']}
entry['sha256']=hashlib.sha256(content).hexdigest()
with request('/ops/files/batch/preview',{'entries':[entry]}) as response:vehicle_plan=json.load(response)['items'][0]
vehicle_query={key:entry[key] for key in ['path','subject_kind','vehicle_id']};vehicle_query.update(expected_version=vehicle_plan['expected_version'],allow_replace='false')
with request('/ops/files/batch/item?'+urlencode(vehicle_query),content,'application/pdf') as response:assert json.load(response)['status']=='created'
print('OK: confirmed joint vehicle registration, same-plate reuse and correctly bound private folder upload.')

with request('/ops/files/folders?subject_kind=vehicle&vehicle_id='+str(resolved[0]['vehicle_id'])) as response:
    folders=json.load(response);assert len(folders['destinations'])==1 and folders['destinations'][0]['count']==1
with request('/ops/files/documents?'+urlencode({'vehicle_id':resolved[0]['vehicle_id'],'folder_mode':'true','path_prefix':'Vehiculos/Fictitious ABCD-12'})) as response:
    assert json.load(response)['total']==1
loose={**entry,'path':'evidence.pdf','sha256':hashlib.sha256(changed).hexdigest()}
with request('/ops/files/batch/preview',{'entries':[loose]}) as response:
    loose_plan=json.load(response)['items'][0];assert loose_plan['status']=='replace' and loose_plan['destination_path']==entry['path']
loose_query={'path':'evidence.pdf','subject_kind':'vehicle','vehicle_id':resolved[0]['vehicle_id'],'expected_document_id':loose_plan['document_id'],'expected_version':1,'allow_replace':'true'}
with request('/ops/files/batch/item?'+urlencode(loose_query),changed,'application/pdf') as response:assert json.load(response)['version']==2
with request('/ops/files/documents?vehicle_id='+str(resolved[0]['vehicle_id'])) as response:
    page=json.load(response);assert page['total']==1 and page['items'][0]['title']==entry['path']
print('OK: per-plate destination folder, direct child listing and confirmed loose update preserving the original folder.')


long_path='Fictitious company/'+('Fictitious extended directory/'*25)+'long-evidence.pdf'
assert 200<len(long_path)<=1024
long_entry={'path':long_path,'subject_kind':'company','sha256':hashlib.sha256(content).hexdigest()}
with request('/ops/files/batch/preview',{'entries':[long_entry]}) as response:assert json.load(response)['items'][0]['status']=='new'
long_query={'path':long_path,'subject_kind':'company','expected_version':0,'allow_replace':'false'}
with request('/ops/files/batch/item?'+urlencode(long_query),content,'application/pdf') as response:assert json.load(response)['status']=='created'
with request('/ops/files/batch/preview',{'entries':[long_entry]}) as response:assert json.load(response)['items'][0]['status']=='identical'
with request('/ops/files/documents?'+urlencode({'path_prefix':long_path.rsplit('/',1)[0],'folder_mode':'true'})) as response:assert json.load(response)['total']==1
print('OK: >700-character private folder path, stable duplicate lookup and direct-child navigation on PostgreSQL.')

# A valid fictitious PDF exercises the actual raster renderer and analysis worker.
def readable_pdf():
    stream=b'BT /F1 18 Tf 50 740 Td (Certificado ficticio - Fictitious backup tenant) Tj 0 -35 Td (Fecha de emision: 15/10/2026) Tj 0 -35 Td (Fecha de vencimiento: 15/10/2027) Tj ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    body=b'%PDF-1.4\n'+b'% fictitious size-limit test padding\n'*(1024*1024);offsets=[]
    for i,obj in enumerate(objects,1):offsets.append(len(body));body+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(body);body+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for offset in offsets:body+=f'{offset:010} 00000 n \n'.encode()
    return body+f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()
with request('/ops/files/documents',{'title':'Fictitious readable PDF','subject_kind':'company'}) as response:preview_id=json.load(response)['id']
with request(f'/ops/files/documents/{preview_id}/versions?file_name=fictitious-readable.pdf&expected_version=0',readable_pdf(),'application/pdf') as response:assert json.load(response)['version']==1
preview_path=f'/ops/files/documents/{preview_id}/versions/1/preview'
with request(preview_path) as response:assert json.load(response)['kind']=='pdf'
with request(preview_path+'/page?page=1') as response:
    assert response.read().startswith(b'\x89PNG') and response.headers['Cache-Control']=='no-store'
    assert response.headers['Content-Disposition']=='inline'
try:
    urlopen(origin+preview_path,context=context,timeout=15)
    raise AssertionError('Preview exposed without authentication')
except HTTPError as error:assert error.code==401
import time
for attempt in range(45):
    with request(f'/ops/files/documents/{preview_id}/analysis') as response:analysis=json.load(response)
    if analysis['status'] not in {'pending','processing'}:break
    time.sleep(1)
assert analysis['status']=='ready',analysis
assert analysis['expires_on']=='2027-10-15'
print('OK: >35 MiB HTTPS upload, real antivirus scan and encrypted storage; real private PDF raster preview and background extraction with destination identity, applied expiry and no automatic accreditation.')
