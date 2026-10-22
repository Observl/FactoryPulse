from cryptography.fernet import Fernet,InvalidToken
import pytest
from backend import cloud_credentials
from backend.cloud_mode import initialize_accounts
from backend import main

def test_cloud_seed_is_idempotent_and_does_not_reset_password():
    initialize_accounts(main.connect,main._lock,'isolated-fixture-password-2026')
    with main.connect() as c:
        c.execute("UPDATE auth_users SET password_hash='changed' WHERE user_id='test'")
    initialize_accounts(main.connect,main._lock,'isolated-fixture-password-2026')
    with main.connect() as c:
        assert c.execute("SELECT password_hash FROM auth_users WHERE user_id='test'").fetchone()[0]=='changed'
        assert c.execute("SELECT role FROM auth_users WHERE user_id='cloud-viewer'").fetchone()[0]=='viewer'

def test_cloud_seed_refuses_to_overwrite_existing_local_account():
    with main.connect() as c:c.execute("INSERT INTO auth_users VALUES('local','local','Local','admin',NULL,'hash',1,1)")
    with pytest.raises(RuntimeError,match='不能覆盖'):initialize_accounts(main.connect,main._lock,'isolated-fixture-password-2026')

def test_cloud_admin_id_does_not_overwrite_same_named_local_viewer(monkeypatch):
    from backend.security import password_hash
    from tests.test_api import client
    initialize_accounts(main.connect,main._lock,'isolated-fixture-password-2026')
    with main.connect() as c:
        c.execute("INSERT INTO auth_users VALUES('existing-viewer','test','Existing viewer','viewer',NULL,?,1,1)",(password_hash('existing-viewer-password-123'),))
    monkeypatch.setenv('FACTORYPULSE_DEPLOYMENT','cloud')
    cloud=client.post('/api/auth/login',json={'username':'线上测试员','password':'isolated-fixture-password-2026'})
    assert cloud.status_code==200 and cloud.json()['user']['user_id']=='test' and cloud.json()['user']['role']=='admin'
    assert client.post('/api/auth/login',json={'username':'test','password':'isolated-fixture-password-2026'}).status_code==401
    monkeypatch.delenv('FACTORYPULSE_DEPLOYMENT')
    local=client.post('/api/auth/login',json={'username':'test','password':'existing-viewer-password-123'})
    assert local.status_code==200 and local.json()['user']['user_id']=='existing-viewer' and local.json()['user']['role']=='viewer'

def test_cloud_secret_roundtrip_and_wrong_key_failure(tmp_path,monkeypatch):
    key=tmp_path/'key';key.write_bytes(Fernet.generate_key());monkeypatch.setenv('FACTORYPULSE_CREDENTIAL_KEY_FILE',str(key))
    assert cloud_credentials.save_secret(tmp_path,'synthetic-test-value')
    assert b'synthetic-test-value' not in (tmp_path/'credentials/ai-key.fernet').read_bytes()
    assert cloud_credentials.load_secret(tmp_path)=='synthetic-test-value'
    key.write_bytes(Fernet.generate_key())
    with pytest.raises(InvalidToken):cloud_credentials.load_secret(tmp_path)
