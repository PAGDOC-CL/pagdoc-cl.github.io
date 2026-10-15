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
