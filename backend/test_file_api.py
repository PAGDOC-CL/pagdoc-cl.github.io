from datetime import date, timedelta
import os
import io
import zipfile

os.environ.setdefault('PAGDOC_SECRET_KEY','test-only-not-for-production-secret-at-least-32-characters')
os.environ.setdefault('PAGDOC_ENCRYPTION_KEY','mFmtvXGV6G9z6uAQo4-EyWzZi-DLZfHototZ6LtCL_4=')

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import app as core
import file_api
from file_gateway import ScanVerdict, SecureDocumentGateway
from storage import EncryptedLocalStore, OFFICE_TYPES, StorageError, validate_payload
from test_operations_api import client, login


class Scanner:
    def __init__(self): self.mode='clean';self.calls=0
    def engine(self):
        if self.mode=='offline':raise ValueError('scanner offline')
        return 'fictitious-ci-only-scanner'
    def scan(self, data, media_type):
        self.calls+=1
        if self.mode=='offline':raise RuntimeError('offline')
        return ScanVerdict(clean=self.mode=='clean',engine='fictitious-ci-only-scanner',detail='Fictitious blocked content')


@pytest.fixture()
def files(client, tmp_path, monkeypatch):
    store=EncryptedLocalStore(tmp_path/'private',Fernet.generate_key().decode());scanner=Scanner()
    monkeypatch.setenv('PAGDOC_BINARY_HTTP_ENABLED','1')
    monkeypatch.setattr(file_api,'configured_gateway',lambda:SecureDocumentGateway(store,scanner))
    with core.SessionLocal() as db:
        db.add_all([core.Vehicle(id=1,tenant_id=1,label='Fictitious vehicle',plate='TEST11'),core.Vehicle(id=2,tenant_id=2,label='Other fictitious vehicle',plate='TEST22')]);db.commit()
    login(client)
    return client,store,scanner


def create(c, **extra):
    response=c.post('/ops/files/documents',json={'title':'Fictitious company evidence','subject_kind':'company',**extra})
    assert response.status_code==201,response.text
    return response.json()['id']


def upload(c, id, version=0, payload=b'%PDF-1.7\n% fictitious evidence\n%%EOF', filename='fictitious.pdf', media='application/pdf', **kwargs):
    return c.post(f'/ops/files/documents/{id}/versions',params={'file_name':filename,'expected_version':version},content=payload,headers={'Content-Type':media,**kwargs})


def test_upload_versions_download_and_review_invalidation(files):
    c,store,scanner=files;id=create(c)
    first=b'%PDF-1.7\n% fictitious version one\n%%EOF'
    response=upload(c,id,payload=first);assert response.status_code==201;assert response.json()['version']==1
    assert c.get(f'/ops/files/documents/{id}/versions/1/download').content==first
    for state in ['received','in_review','approved']:
        current=next(r for r in c.get('/ops/reviews').json() if r['id']==id)
        response=c.post(f'/ops/documents/{id}/review',json={'state':state,'expected_version':current['version']});assert response.status_code==200,response.text
    assert c.get('/ops/files/documents').json()['items'][0]['review_state']=='approved'
    assert upload(c,id,version=0).status_code==409
    assert scanner.calls==1
    second=b'%PDF-1.7\n% fictitious version two\n%%EOF'
    assert upload(c,id,version=1,payload=second).status_code==201
    assert c.get('/ops/files/documents').json()['items'][0]['review_state']=='pending'
    assert len(c.get(f'/ops/files/documents/{id}/versions').json())==2
    assert c.get(f'/ops/files/documents/{id}/versions/1/download').content==first
    download=c.get(f'/ops/files/documents/{id}/versions/2/download');assert download.content==second
    assert download.headers['content-disposition'].startswith('attachment;')
    assert download.headers['cache-control']=='no-store'
    blobs=list(store.root.rglob('*.bin'));assert len(blobs)==2
    assert all(path.read_bytes() not in (first,second) and path.stat().st_mode&0o777==0o600 for path in blobs)


def test_disabled_feature_and_csrf_are_enforced(files, monkeypatch):
    c,store,scanner=files;id=create(c)
    del c.headers['X-PAGDOC-CSRF']
    assert upload(c,id).status_code==403
    assert c.post('/ops/files/documents',json={'title':'Fictitious','subject_kind':'company'}).status_code==403
    login(c);monkeypatch.setenv('PAGDOC_BINARY_HTTP_ENABLED','0')
    assert upload(c,id).status_code==503
    assert c.get('/ops/files/status').json()['enabled'] is False
    assert c.get(f'/ops/files/documents/{id}/versions/1/download').status_code==503
    assert not list(store.root.rglob('*.bin'))


@pytest.mark.parametrize('role',[3,5,6])
def test_non_writers_cannot_upload(files,role):
    c,store,scanner=files;id=create(c);login(c,role)
    assert upload(c,id).status_code==403
    assert c.post('/ops/files/documents',json={'title':'Fictitious','subject_kind':'company'}).status_code==403
    assert not list(store.root.rglob('*.bin'))


def test_other_tenant_cannot_list_bind_read_or_upload(files):
    c,store,scanner=files;id=create(c);assert upload(c,id).status_code==201
    login(c,2)
    assert c.get('/ops/files/documents').json()['items']==[]
    assert [v['id'] for v in c.get('/ops/files/subjects').json()['vehicles']]==[2]
    assert c.get(f'/ops/files/documents/{id}/versions').status_code==404
    assert c.get(f'/ops/files/documents/{id}/versions/1/download').status_code==404
    assert upload(c,id,version=1).status_code==404
    assert c.post('/ops/files/documents',json={'title':'Fictitious','subject_kind':'vehicle','vehicle_id':1}).status_code==404
    assert scanner.calls==1


def test_planner_has_no_document_access(files):
    c,_,_=files;id=create(c);login(c,3)
    for endpoint in ['/ops/files/status','/ops/files/documents','/ops/files/subjects',f'/ops/files/documents/{id}/versions']:
        assert c.get(endpoint).status_code==403


def test_unavailable_or_blocked_scanner_leaves_no_files(files):
    c,store,scanner=files;id=create(c)
    scanner.mode='offline';assert upload(c,id).status_code==503
    assert c.get('/ops/files/status').json()['ready_for_upload'] is False
    scanner.mode='blocked';assert upload(c,id).status_code==422
    assert c.get(f'/ops/files/documents/{id}/versions').json()==[]
    assert not list(store.root.rglob('*.bin'))


def test_size_type_and_signature_are_validated(files, monkeypatch):
    c,store,scanner=files;id=create(c)
    assert upload(c,id,payload=b'<html>fictitious</html>').status_code==422
    assert upload(c,id,filename='fictitious.exe').status_code==422
    assert upload(c,id,media='text/html').status_code==415
    assert upload(c,id,**{'Content-Length':str(16*1024*1024)}).status_code==413
    monkeypatch.setattr(file_api,'MAX_BYTES',10)
    assert upload(c,id).status_code==413
    assert not list(store.root.rglob('*.bin'));assert scanner.calls==0


def test_corrupted_stored_file_is_never_downloaded(files):
    c,store,_=files;id=create(c);assert upload(c,id).status_code==201
    path=next(store.root.rglob('*.bin'));path.write_bytes(b'corrupted fictitious ciphertext')
    assert c.get(f'/ops/files/documents/{id}/versions/1/download').status_code==503


def test_vehicle_identity_and_subject_cannot_be_reassigned(files):
    c,_,_=files
    assert c.post('/ops/files/vehicles',json={'label':'Fictitious duplicate','plate':'test-11'}).status_code==409
    vehicle=c.post('/ops/files/vehicles',json={'label':'New fictitious vehicle','plate':'TEST33','vehicle_type':'Fictitious truck'});assert vehicle.status_code==201
    id=create(c,subject_kind='vehicle',vehicle_id=vehicle.json()['id'])
    assert c.patch(f'/documents/{id}',json={'subject_name':'Other vehicle'}).status_code==409
    assert c.patch(f'/documents/{id}',json={'title':'Updated fictitious title','expires_on':(date.today()+timedelta(days=30)).isoformat()}).status_code==200
    assert c.get('/ops/files/documents?subject_kind=company').json()['total']==0
    assert c.get('/ops/files/documents?subject_kind=vehicle').json()['total']==1


def test_private_document_without_binary_cannot_be_approved(files):
    c,_,_=files;id=create(c)
    for version,state in enumerate(['received','in_review']):
        assert c.post(f'/ops/documents/{id}/review',json={'state':state,'expected_version':version}).status_code==200
    assert c.post(f'/ops/documents/{id}/review',json={'state':'approved','expected_version':2}).status_code==409


def office(media, extras=None):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ['[Content_Types].xml','_rels/.rels',OFFICE_TYPES[media][0]]:archive.writestr(name,b'<fictitious/>')
        for name,body in (extras or {}).items():archive.writestr(name,body)
    return buffer.getvalue()


@pytest.mark.parametrize('media',list(OFFICE_TYPES))
def test_office_package_upload_and_download(files,media):
    c,_,_=files;id=create(c);payload=office(media);filename='fictitious'+OFFICE_TYPES[media][1]
    assert upload(c,id,payload=payload,filename=filename,media=media).status_code==201
    assert c.get(f'/ops/files/documents/{id}/versions/1/download').content==payload


@pytest.mark.parametrize('extra',[{'word/vbaProject.bin':b'fake'},{'word/embeddings/object.bin':b'fake'},{'../unsafe':b'fake'},{'word/extra.xml':b'<!DOCTYPE fake>'},{'word/extra.xml':b'x'*100000}])
def test_office_active_or_oversized_content_rejected(extra):
    media=next(iter(OFFICE_TYPES))
    with pytest.raises(StorageError):validate_payload(office(media,extra),media)
