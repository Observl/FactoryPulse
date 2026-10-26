"""D1-backed identity transactions with optimistic revision checks and no offline fallback.

Identity lookups, compatibility projections and transaction workspaces run on D1.
No local file or in-memory SQLite database is created.
"""
import hashlib
import json
import os
import re
import secrets
import time
import logging
from pathlib import Path
import httpx
from fastapi import HTTPException

TABLES=('auth_users','auth_sessions','auth_attempts','auth_onboarding','auth_id_sequence')
ROOT=Path(__file__).resolve().parents[1]
ROLE_LABELS={'developer':'开发者','admin':'管理员','user':'普通用户','viewer':'只读用户'}
ROLE_CODES={label:code for code,label in ROLE_LABELS.items()}

def configuration():
    file=os.environ.get('FACTORYPULSE_IDENTITY_CONFIG')
    if not file and os.environ.get('FACTORYPULSE_TEST_ALLOW_ANONYMOUS')!='1':
        default=ROOT/'.secrets/identity.json'
        if default.is_file():file=str(default)
        else:raise RuntimeError('必须配置 Cloudflare D1 账号中心；不会使用本地账号数据库')
    if not file:return None
    try:
        value=json.loads(Path(file).read_text(encoding='utf-8'))
        if not re.fullmatch('[a-f0-9]{32}',value['account_id']) or not re.fullmatch('[a-f0-9-]{36}',value['database_id']):raise ValueError()
        token=Path(value['token_file'])
        if not token.is_absolute():token=Path(file).resolve().parent/token
        value['token_file']=str(token)
        return value
    except (KeyError,ValueError,OSError):raise RuntimeError('账号中心配置无效，未回退到本地账号') from None

class D1Store:
    def __init__(self,config):
        self.config=config
        self.url=f"https://api.cloudflare.com/client/v4/accounts/{config['account_id']}/d1/database/{config['database_id']}/query"
        self.client=httpx.Client(timeout=30,trust_env=not config.get('direct_https',False)) if config.get('persistent_connection') else None

    def batch(self,statements):
        safe=all(re.match(r'\s*(SELECT\b|PRAGMA\s+\w+\s*(?:\([^)]*\))?\s*$|CREATE\s+(?:TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\b)',item['sql'],re.I) for item in statements)
        for attempt in range(3 if safe else 1):
            try:
                token=Path(self.config['token_file']).read_text(encoding='utf-8').strip()
                if not token:raise ValueError()
                sender=self.client.post if self.client is not None else httpx.post
                response=sender(self.url,headers={'Authorization':'Bearer '+token},json={'batch':statements},timeout=30 if self.client is not None else 20)
                body=response.json()
                break
            except (OSError,ValueError,httpx.HTTPError) as error:
                logging.getLogger(__name__).warning('D1 transport failure: %s; statements=%d; retryable=%s',type(error).__name__,len(statements),safe)
                if safe and attempt<2:time.sleep(.25*(attempt+1));continue
                raise HTTPException(503,'无法连接 Cloudflare 数据中心，未使用离线数据库放行') from None
        if not response.is_success or not body.get('success') or any(not r.get('success') for r in body.get('result',[])):
            # Never return remote query text, parameters, secrets, or password hashes.
            message=json.dumps(body.get('errors',[]))
            if 'fp_identity_guard_revision' in message and 'constraint' in message.lower():raise HTTPException(409,'账号中心记录已变化，请重新执行操作')
            raise HTTPException(503,'账号中心暂时无法完成操作，请检查服务端配置')
        return body['result']

    def snapshot(self):
        result=self.batch([{'sql':'SELECT revision FROM fp_identity_revision WHERE id=1'}]+[{'sql':'SELECT * FROM '+table} for table in TABLES]+[{'sql':"SELECT COALESCE(MAX(seq),9999) AS high_id FROM sqlite_sequence WHERE name='auth_users'"}])
        if not result[0].get('results'):raise HTTPException(503,'账号中心尚未初始化')
        rows={name:r.get('results',[]) for name,r in zip(TABLES,result[1:])}
        if rows['auth_id_sequence']:
            rows['auth_id_sequence'][0]['next_id']=max(rows['auth_id_sequence'][0]['next_id'],int(result[-1]['results'][0]['high_id'])+1)
        return result[0]['results'][0]['revision'],rows

    def commit(self,revision,writes):
        nonce=secrets.token_hex(24)
        guard=[{'sql':'UPDATE fp_identity_revision SET revision=revision+1,commit_nonce=? WHERE id=1 AND revision=?','params':[nonce,revision]},
               {'sql':'INSERT INTO fp_identity_guard(id) SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM fp_identity_revision WHERE id=1 AND commit_nonce=?)','params':[nonce]}]
        self.batch(guard+writes)

class IdentityConnection:
    # Retain the public constructor for existing integrations; no local snapshot.
    def __new__(cls,store,local_connect=None):return RemoteIdentityConnection(store)


def wrap_connection(local_connect):
    config=configuration()
    if not config:return local_connect
    store=D1Store(config)
    return lambda:RemoteIdentityConnection(store)


class RemoteIdentityConnection:
    """Compatibility projection evaluated on D1, without a local SQLite snapshot."""
    def __init__(self,store):
        from .d1_business import Connection
        self.connection=Connection(store,'fp_identity_revision','fp_identity_guard')
        self.connection.baseline()
    def __enter__(self):return self
    def __exit__(self,*args):return self.connection.__exit__(*args)
    def execute(self,sql,params=()):
        remote_sql=sql;values=list(params)
        if re.match(r'INSERT INTO auth_users VALUES',sql,re.I):
            remote_sql='INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash,active,version) VALUES (?,?,?,?,?,1,1)'
            values.pop(1);values[2]=ROLE_LABELS.get(values[2],values[2])
        elif re.match(r'UPDATE auth_users SET username=\?,',sql,re.I):
            remote_sql=sql.replace('username=?,','',1);values.pop(0)
        if re.match(r'UPDATE auth_users SET display_name=\?,role=\?,',remote_sql,re.I):values[1]=ROLE_LABELS.get(values[1],values[1])
        if re.match(r'\s*SELECT\b',remote_sql,re.I) and re.search(r'\bauth_users\b',remote_sql):
            from .d1_business import identifiers,Cursor
            c=self.connection;c.baseline()
            table=c.tables.get('auth_users','auth_users')
            cases=' '.join("WHEN '"+label+"' THEN '"+code+"'" for label,code in ROLE_CODES.items())
            projection=f'(SELECT CAST(user_id AS TEXT) AS user_id,CAST(user_id AS TEXT) AS username,display_name,CASE role {cases} ELSE role END AS role,CAST(staff_id AS TEXT) AS staff_id,password_hash,active,version FROM "{table}")'
            mapped=identifiers(remote_sql,{**c.tables,'auth_users':projection})
            return Cursor(c.query(mapped,values))
        return self.connection.execute(remote_sql,values)
