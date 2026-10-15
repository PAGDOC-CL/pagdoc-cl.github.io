from test_operations_api import client,login
from sqlalchemy import select
import app as core
from onboarding_api import UserOnboarding


def test_onboarding_is_once_per_user_across_sessions_roles_and_tenants(client):
    assert client.post('/ops/onboarding/start',json={}).status_code==401
    login(client)
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':True}
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':False}
    with core.SessionLocal() as db:
        user=db.get(core.User,1);user.role='editor';db.commit()
    client.post('/auth/logout');login(client)
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':False}
    login(client,2)
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':True}
    login(client,3)
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':True}
    with core.SessionLocal() as db:
        rows=list(db.scalars(select(UserOnboarding)))
        assert {(r.user_id,r.tenant_id) for r in rows}=={(1,1),(2,2),(3,1)}


def test_onboarding_preserves_legacy_seen_state_and_rejects_forged_targets(client):
    login(client)
    assert client.post('/ops/onboarding/start',json={'user_id':2}).status_code==422
    assert client.post('/ops/onboarding/start',json={'legacy_seen':True}).json()=={'show_tutorial':False}
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':False}
    login(client,2)
    del client.headers['X-PAGDOC-CSRF']
    assert client.post('/ops/onboarding/start',json={}).status_code==403
    client.headers['X-PAGDOC-CSRF']=client.cookies.get('pagdoc_csrf')
    assert client.post('/ops/onboarding/start',json={}).json()=={'show_tutorial':True}
