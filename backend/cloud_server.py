"""Full same-origin application: the same business API and React UI as local delivery."""
import os
from pathlib import Path
from urllib.parse import urlparse
from .cloud_mode import enabled,initialize_accounts,read_secret_file

if not enabled():raise RuntimeError('云端入口需要 FACTORYPULSE_DEPLOYMENT=cloud')
if not os.environ.get('FACTORYPULSE_DATA_DIR'):raise RuntimeError('云端入口需要独立的持久数据目录')
origins=os.environ.get('FACTORYPULSE_ALLOWED_ORIGINS','').split(',')
if not origins or any(urlparse(v).scheme not in {'http','https'} or not urlparse(v).netloc or urlparse(v).path not in {'','/'} for v in origins):
    raise RuntimeError('必须设置完整的云端访问来源，不能包含路径或通配符')
os.environ['FACTORYPULSE_AUTH_REQUIRED']='1'
os.environ.pop('FACTORYPULSE_TEST_ALLOW_ANONYMOUS',None)
os.environ['FACTORYPULSE_SERVE_UI']='1'
ui=Path(os.environ.get('FACTORYPULSE_UI_DIR',Path(__file__).resolve().parents[1]/'dist'))
from .build_artifact import validate_build
validate_build(ui)
password=read_secret_file('FACTORYPULSE_CLOUD_ADMIN_PASSWORD_FILE')
from .cloud_credentials import cipher,load_secret,save_secret
cipher()  # Validate the key before accepting any traffic.
from . import main
from .d1_identity import configuration,D1Store
if configuration():
    _,identities=D1Store(configuration()).snapshot()
    if not identities['auth_users']:raise RuntimeError('D1账号中心尚未初始化')
else:initialize_accounts(main.connect,main._lock,password)
password=None
main.credential_get=lambda:os.environ.get('FACTORYPULSE_AI_API_KEY') or load_secret(main.DATA_DIR)
main.credential_set=lambda value:save_secret(main.DATA_DIR,value)
main._api_key=main.credential_get()
main._credential_secure=bool(main._api_key and not os.environ.get('FACTORYPULSE_AI_API_KEY'))
app=main.app
