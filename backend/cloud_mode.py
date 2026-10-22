"""Server-controlled cloud identity; never infer access rights from a browser flag."""
import json
import os
import secrets
from datetime import datetime,timezone
from pathlib import Path

GUEST_ID=os.environ.get('FACTORYPULSE_GUEST_USER_ID','')
ADMIN_ID='10001'

def enabled():
    return os.environ.get('FACTORYPULSE_DEPLOYMENT')=='cloud'

def initialize_accounts(connect,lock,password):
    from .security import password_hash,validate_password
    validate_password(password)
    with lock,connect() as c:
        c.execute('BEGIN IMMEDIATE')
        initialized=c.execute("SELECT value FROM settings WHERE key='cloud_accounts_initialized'").fetchone()
        if initialized:return
        if c.execute('SELECT 1 FROM auth_users LIMIT 1').fetchone():
            raise RuntimeError('云端首次启动必须使用独立数据库，不能覆盖已有本地账号')
        c.execute('INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)',(ADMIN_ID,'线上测试员','线上测试员','developer','0',password_hash(password)))
        c.execute('INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)',(GUEST_ID,'cloud-viewer','只读访客','viewer','1',password_hash(secrets.token_urlsafe(48))))
        # The shared visitor account does not own a personal onboarding workflow.
        c.execute('INSERT INTO auth_onboarding VALUES (?,?,?)',(GUEST_ID,5,datetime.now(timezone.utc).isoformat()))
        c.execute("INSERT INTO settings VALUES ('cloud_accounts_initialized','1')")
        c.execute('INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)',('cloud_accounts_initialized',ADMIN_ID,json.dumps({'roles':['developer','viewer']}),datetime.now(timezone.utc).isoformat()))

def read_secret_file(variable):
    path=os.environ.get(variable)
    if not path:raise RuntimeError(f'缺少云端机密文件配置：{variable}')
    value=Path(path).read_text(encoding='utf-8').strip()
    if not value:raise RuntimeError(f'云端机密文件为空：{variable}')
    return value
