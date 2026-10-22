"""Exercise the real complete cloud service in an isolated directory; no operator data."""
import os,sys,tempfile
from pathlib import Path
from cryptography.fernet import Fernet
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
runtime=tempfile.TemporaryDirectory(prefix='factorypulse-cloud-smoke-');folder=Path(runtime.name)
(folder/'developer').write_text('isolated-fixture-password-2026',encoding='utf-8');(folder/'key').write_bytes(Fernet.generate_key())
os.environ.update(FACTORYPULSE_DEPLOYMENT='cloud',FACTORYPULSE_DATA_DIR=str(folder/'data'),FACTORYPULSE_ALLOWED_ORIGINS='https://factorypulse.invalid',FACTORYPULSE_CLOUD_ADMIN_PASSWORD_FILE=str(folder/'developer'),FACTORYPULSE_CREDENTIAL_KEY_FILE=str(folder/'key'))
os.environ.pop('FACTORYPULSE_IDENTITY_CONFIG',None)
os.environ['FACTORYPULSE_TEST_ALLOW_ANONYMOUS']='1'
os.environ['FACTORYPULSE_GUEST_USER_ID']='10002'
from backend.cloud_server import app
from fastapi.testclient import TestClient
client=TestClient(app,base_url='https://factorypulse.invalid',headers={'Origin':'https://factorypulse.invalid'})
status=client.get('/api/auth/status').json();assert status['guest_available'] is True and status['setup_needed'] is False
assert client.get('/api/overview').status_code==401
assert client.post('/api/auth/guest').status_code==200
assert client.get('/api/auth/status').json()['user']['role']=='viewer'
assert client.get('/api/work-orders').status_code==200
assert client.post('/api/sync/model-validation').status_code==403
assert client.post('/api/auth/password',json={'current_password':'isolated-fixture-password-2026','new_password':'temporary-test-change-123'}).status_code==403
assert client.post('/api/auth/logout').status_code==200
assert client.post('/api/auth/login',json={'username':'test','password':'wrong'}).status_code==401
assert client.post('/api/auth/login',json={'username':'线上测试员','password':'isolated-fixture-password-2026'}).status_code==200
for step in range(1,6):assert client.post('/api/auth/onboarding',json={'step':step}).status_code==200
assert client.post('/api/sync/model-validation').status_code==200
overview=client.get('/api/overview');assert overview.status_code==200 and len(overview.json()['devices'])==24
assert client.get('/api/developer/settings').status_code==200
assert client.get('/').status_code==200
assert client.post('/api/auth/logout',headers={'Origin':'https://untrusted.invalid'}).status_code==403
print('Full cloud service: guest restrictions, real admin session, full UI, frozen data and model calculation passed.')
