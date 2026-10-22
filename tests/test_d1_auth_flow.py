from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import d1_identity,security
from tests.test_d1_identity import FakeD1,IdentityConnection,local


def test_numeric_login_create_password_and_roles_with_d1_schema(tmp_path,monkeypatch):
    store=FakeD1(tmp_path/'d1.sqlite3')
    password='isolated-d1-owner-password-2026'
    with IdentityConnection(store,local) as c:
        c.execute('INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)',('10001','10001','Owner','developer','0',security.password_hash(password)))
    monkeypatch.setattr(d1_identity,'configuration',lambda:{'fake':True})
    monkeypatch.setattr(d1_identity,'D1Store',lambda config:store)
    app=FastAPI();security.install_auth(app,local,__import__('threading').RLock())
    client=TestClient(app)
    assert client.post('/api/auth/login',json={'username':'10001','password':password}).status_code==200
    status=client.get('/api/auth/status').json()
    assert status['user']['role']=='developer' and not status['guest_available']
    created=client.post('/api/auth/users',json={'display_name':'Company user','role':'user','staff_id':7,'password':'isolated-d1-user-password-2026'})
    assert created.status_code==200,created.text
    assert created.json()['user_id']=='10002'
    rows=store.snapshot()[1]['auth_users']
    assert all('username' not in row for row in rows)
    assert next(row for row in rows if str(row['user_id'])=='10002')['role']=='普通用户'
    assert not client.get('/api/auth/status').json()['guest_available']
    assert client.post('/api/auth/guest').status_code==503
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login',json={'username':'10002','password':'isolated-d1-user-password-2026'}).status_code==200
    assert client.get('/api/auth/users').status_code==403
    replacement='isolated-d1-new-password-2026'
    assert client.post('/api/auth/password',json={'current_password':'isolated-d1-user-password-2026','new_password':replacement}).status_code==200
    assert client.get('/api/auth/status').json()['user'] is None
    assert client.post('/api/auth/login',json={'username':'10002','password':replacement}).status_code==200
