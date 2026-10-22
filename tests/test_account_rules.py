import hashlib
import pytest
from backend.security import password_hash,verify_password
from backend.main import connect
from tests.test_api import client
from tests.test_security import initialize,PASSWORD


def test_sha256_format_and_wrong_password():
    encoded=password_hash('only-a-test-password-123')
    assert encoded==hashlib.sha256(b'only-a-test-password-123').hexdigest()
    assert len(encoded)==64 and verify_password('only-a-test-password-123',encoded)
    assert not verify_password('wrong-password',encoded)


def test_ids_increase_and_are_not_reused_after_deletion():
    owner=initialize()
    def create():
        r=client.post('/api/auth/users',headers=owner,json={'display_name':'Company user','role':'user','staff_id':8,'password':PASSWORD})
        assert r.status_code==200,r.text
        return int(r.json()['user_id'])
    first=create()
    assert first>=10002
    with connect() as c:c.execute('DELETE FROM auth_users WHERE user_id=?',(str(first),))
    assert create()==first+1


@pytest.mark.parametrize('role,staff,valid',[('developer',0,True),('developer',-1,False),('admin',-1,True),('admin',0,False),('user',1,True),('user',0,False),('viewer',2,True),('viewer',-1,False),('manager',1,False)])
def test_role_and_staff_number_contract(role,staff,valid):
    owner=initialize()
    r=client.post('/api/auth/users',headers=owner,json={'display_name':'Contract user','role':role,'staff_id':staff,'password':PASSWORD})
    assert r.status_code==(200 if valid else 422),r.text


def test_numeric_id_login_and_disabled_account_rejection():
    owner=initialize()
    r=client.post('/api/auth/users',headers=owner,json={'display_name':'Viewer','role':'viewer','staff_id':5,'password':PASSWORD})
    identifier=r.json()['user_id']
    login=client.post('/api/auth/login',json={'username':identifier,'password':PASSWORD})
    assert login.status_code==200
    with connect() as c:c.execute('UPDATE auth_users SET active=0 WHERE user_id=?',(identifier,))
    assert client.post('/api/auth/login',json={'username':identifier,'password':PASSWORD}).status_code==401


def test_d1_table_enforces_ids_roles_staff_and_active(tmp_path):
    import sqlite3
    from pathlib import Path
    db=sqlite3.connect(tmp_path/'schema.sqlite3')
    db.executescript((Path(__file__).parents[1]/'deploy/d1-identity-schema.sql').read_text(encoding='utf-8'))
    assert 'username' not in [row[1] for row in db.execute('PRAGMA table_info(auth_users)')]
    db.execute("INSERT INTO auth_users(display_name,role,staff_id,password_hash) VALUES ('Owner','开发者',0,?)",('0'*64,))
    assert db.execute('SELECT user_id FROM auth_users').fetchone()[0]==10001
    for role,staff,active in [('开发者',1,1),('管理员',0,1),('普通用户',-1,1),('只读用户',0,1),('未知',1,1),('普通用户',1,2)]:
        with pytest.raises(sqlite3.IntegrityError):db.execute('INSERT INTO auth_users(display_name,role,staff_id,password_hash,active) VALUES (?,?,?,?,?)',('Invalid',role,staff,'0'*64,active))
    db.close()
