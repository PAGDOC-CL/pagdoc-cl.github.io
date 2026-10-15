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


def upload_logo(c, payload=b'\x89PNG\r\n\x1a\nFictitious logo for automated tests', filename='fictitious.png', media='image/png'):
    return c.post('/ops/branding/logo', params={'file_name': filename}, content=payload, headers={'Content-Type': media})


def test_branding_is_private_encrypted_and_scoped(files):
    c,store,scanner=files
    assert c.get('/ops/branding').json()=={'logo_version':0}
    assert c.get('/ops/branding/logo').status_code==404
    first=b'\x89PNG\r\n\x1a\nFictitious logo one'
    assert upload_logo(c,first).json()=={'logo_version':1}
    response=c.get('/ops/branding/logo');assert response.content==first
    assert response.headers['content-type']=='image/png'
    assert response.headers['cache-control']=='no-store'
    assert c.get('/ops/files/documents').json()['total']==0
    assert all(p.read_bytes()!=first for p in store.root.rglob('*.bin'))
    login(c,2)
    assert c.get('/ops/branding').json()=={'logo_version':0}
    assert c.get('/ops/branding/logo').status_code==404
    login(c,3)  # Calendar-only roles can see their own corporate mark, not documents.
    assert c.get('/ops/branding/logo').content==first
    assert c.get('/ops/files/documents').status_code==403
    c.cookies.clear();c.headers.pop('X-PAGDOC-CSRF',None)
    assert c.get('/ops/branding').status_code==401
    assert c.get('/ops/branding/logo').status_code==401


@pytest.mark.parametrize('role',[3,4,5,6])
def test_only_administrators_can_change_branding(files,role):
    c,store,_=files;login(c,role)
    assert upload_logo(c).status_code==403
    assert not list(store.root.rglob('*.bin'))


def test_branding_rejection_keeps_previous_logo_and_versions(files,monkeypatch):
    c,store,scanner=files
    first=b'\x89PNG\r\n\x1a\nFictitious first logo'
    assert upload_logo(c,first).status_code==201
    scanner.mode='blocked';assert upload_logo(c).status_code==422
    assert c.get('/ops/branding/logo').content==first
    assert c.get('/ops/branding').json()['logo_version']==1
    scanner.mode='clean';assert upload_logo(c).json()['logo_version']==2
    assert len(list(store.root.rglob('*.bin')))==2
    del c.headers['X-PAGDOC-CSRF'];assert upload_logo(c).status_code==403
    login(c)
    assert upload_logo(c,b'<svg/>','logo.svg','image/svg+xml').status_code==415
    assert upload_logo(c,b'\x89PNG\r\n\x1a\n'+b'x'*(2*1024*1024)).status_code==413
    assert upload_logo(c,b'not a PNG').status_code==422
    assert c.get('/ops/branding').json()['logo_version']==2
    monkeypatch.setenv('PAGDOC_BINARY_HTTP_ENABLED','0')
    assert upload_logo(c).status_code==503
    assert c.get('/ops/branding/logo').status_code==503


def test_first_rejected_logo_rolls_back_metadata(files):
    c,_,scanner=files;scanner.mode='blocked'
    assert upload_logo(c).status_code==422
    with core.SessionLocal() as db:
        assert db.get(file_api.TenantBranding,1) is None
        assert db.scalar(select(core.Document).where(core.Document.title=='Logo corporativo')) is None


def test_login_logo_publication_is_opt_in_and_can_be_removed(files):
    c,_,_=files
    assert upload_logo(c).status_code==201
    assert c.get('/login/branding').json()=={'logo_version':0}
    assert c.get('/login/branding/logo').status_code==404
    payload=b'\x89PNG\r\n\x1a\nFictitious opted-in brand'
    assert c.post('/ops/branding/logo?file_name=fictitious.png&login_visible=true',content=payload,headers={'Content-Type':'image/png'}).status_code==201
    c.cookies.clear();c.headers.pop('X-PAGDOC-CSRF',None)
    response=c.get('/login/branding');assert response.json()=={'name':'Demo One','logo_version':2}
    assert response.headers['cache-control']=='no-store'
    assert c.get('/login/branding/logo').content==payload
    assert c.get('/ops/branding/logo').status_code==401
    assert c.get('/ops/files/documents').status_code==401
    login(c)
    assert upload_logo(c).status_code==201
    assert c.get('/login/branding').json()=={'logo_version':0}
    assert c.get('/login/branding/logo').status_code==404


def test_login_never_selects_between_two_published_tenants(files):
    c,_,_=files
    for user in [1,2]:
        login(c,user)
        response=c.post('/ops/branding/logo?file_name=fictitious.png&login_visible=true',content=b'\x89PNG\r\n\x1a\nFictitious brand',headers={'Content-Type':'image/png'})
        assert response.status_code==201
    assert c.get('/login/branding').json()=={'logo_version':0}
    assert c.get('/login/branding/logo').status_code==404
    assert c.get('/ops/branding').json()['logo_version']==1
