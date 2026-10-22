from tests.test_security import initialize,create_user,login,PASSWORD
from tests.test_api import client
from backend.main import connect


def profile(headers):return client.get('/api/auth/status',headers=headers).json()['user']


def test_manager_can_rename_only_self_and_login_uses_new_name():
    admin=initialize();create_user(admin,'manager01','admin');manager=login('manager01');user=profile(manager)
    payload={'username':'manager-renamed','display_name':'新设备总管','version':user['version']}
    result=client.post('/api/auth/profile',headers=manager,json=payload)
    assert result.status_code==200,result.text
    assert profile(manager)['display_name']=='新设备总管'
    assert profile(admin)['username']=='developer'
    assert client.post('/api/auth/login',json={'username':'manager01','password':PASSWORD}).status_code==401
    assert client.post('/api/auth/login',json={'username':'manager-renamed','password':PASSWORD}).status_code==200
    assert client.post('/api/auth/profile',headers=manager,json=payload).status_code==409
    with connect() as c:assert c.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='auth_profile_updated'").fetchone()[0]==1


def test_profile_rejects_other_identity_fields_and_name_collision():
    admin=initialize();other=create_user(admin,'manager01','admin');user=profile(admin)
    payload={'username':'new-admin','display_name':'本人名称','version':user['version']}
    assert client.post('/api/auth/profile',headers=admin,json={**payload,'user_id':other}).status_code==422
    assert client.post('/api/auth/profile',headers=admin,json={**payload,'username':'manager01'}).status_code==409
    assert client.post('/api/auth/profile',headers=admin,json={**payload,'display_name':'   '}).status_code==422
    assert client.post('/api/auth/profile',headers=admin,json={**payload,'username':'bad name'}).status_code==422
    assert profile(admin)['username']=='developer'


def test_admin_cannot_rename_another_user_using_account_management():
    admin=initialize();other=create_user(admin,'manager01','admin')
    result=client.post('/api/auth/users/'+other,headers=admin,json={'display_name':'他人改名','role':'admin','active':True,'version':1})
    assert result.status_code==403
    result=client.post('/api/auth/users/'+other,headers=admin,json={'display_name':'manager01','role':'viewer','staff_id':'1','active':True,'version':1})
    assert result.status_code==200,result.text


def test_viewer_and_technician_cannot_rename():
    admin=initialize();create_user(admin,'viewer01','viewer');create_user(admin,'technician01','user','1')
    for name in ['viewer01','technician01']:
        headers=login(name);user=profile(headers)
        assert client.post('/api/auth/profile',headers=headers,json={'username':'new-name','display_name':'新名称','version':user['version']}).status_code==403
        assert profile(headers)['username']==name
    assert client.post('/api/auth/profile',json={'username':'new-name','display_name':'新名称','version':1}).status_code==401
