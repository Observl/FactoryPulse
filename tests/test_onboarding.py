"""Account login and first-use progress must persist per authenticated identity."""
from backend import main
from backend.security import COOKIE
from tests.test_api import client
from tests.test_security import PASSWORD,initialize,create_user,login


def status(headers):return client.get('/api/auth/status',headers=headers).json()


def test_normal_service_requires_login_even_if_old_optional_flag_is_zero(monkeypatch):
    monkeypatch.delenv('FACTORYPULSE_TEST_ALLOW_ANONYMOUS',raising=False)
    monkeypatch.setenv('FACTORYPULSE_AUTH_REQUIRED','0')
    result=client.get('/api/auth/status').json()
    assert result['required'] and result['setup_needed'] and result['user'] is None
    assert client.get('/api/overview').status_code==401
    assert client.post('/api/auth/onboarding',json={'step':1}).status_code==401
    assert client.get('/api/health').status_code==200


def test_progress_is_ordered_monotonic_idempotent_and_retained_on_relogin():
    admin=initialize()
    assert status(admin)['onboarding']=={'step':0,'completed_at':None,'total_steps':5}
    assert client.post('/api/auth/onboarding',headers=admin,json={'step':5}).status_code==409
    for step in range(1,6):
        response=client.post('/api/auth/onboarding',headers=admin,json={'step':step})
        assert response.status_code==200,response.text
    saved=status(admin)['onboarding']
    assert saved['step']==5 and saved['completed_at']
    assert client.post('/api/auth/onboarding',headers=admin,json={'step':5}).json()==saved
    assert client.post('/api/auth/onboarding',headers=admin,json={'step':1}).json()==saved
    client.post('/api/auth/logout',headers=admin)
    assert client.get('/api/overview',headers=admin).status_code==401
    renewed=login('developer')
    assert status(renewed)['onboarding']==saved
    with main.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='onboarding_completed'").fetchone()[0]==1


def test_each_user_has_independent_tutorial_and_refresh_resumes_saved_step():
    admin=initialize();create_user(admin,'tutorial-viewer','viewer')
    assert client.post('/api/auth/onboarding',headers=admin,json={'step':1}).status_code==200
    viewer=login('tutorial-viewer')
    assert status(viewer)['onboarding']['step']==0
    assert client.post('/api/auth/onboarding',headers=viewer,json={'step':1}).status_code==200
    assert client.post('/api/auth/onboarding',headers=viewer,json={'step':2}).status_code==200
    assert status(admin)['onboarding']['step']==1
    assert status(login('tutorial-viewer'))['onboarding']['step']==2
    assert client.post('/api/auth/onboarding',headers=viewer,json={'step':-1}).status_code==422
    assert client.post('/api/auth/onboarding',headers=viewer,json={'step':'3'}).status_code==422


def test_reinstalling_auth_schema_does_not_reset_completed_tutorial():
    from backend.security import create_schema
    admin=initialize()
    for step in range(1,6):client.post('/api/auth/onboarding',headers=admin,json={'step':step})
    before=status(admin)['onboarding']
    with main.connect() as c:create_schema(c)
    assert status(admin)['onboarding']==before
