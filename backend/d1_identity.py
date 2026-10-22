"""D1-backed identity transactions with optimistic revision checks and no offline fallback.

Only identity tables live remotely. Existing validated auth SQL runs against a transient
snapshot; its write set is replayed in a single D1 batch guarded by a compare-and-swap.
This preserves branching validations and prevents lost updates between deployments.
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
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

    def batch(self,statements):
        try:
            token=Path(self.config['token_file']).read_text(encoding='utf-8').strip()
            if not token:raise ValueError()
            response=httpx.post(self.url,headers={'Authorization':'Bearer '+token},json={'batch':statements},timeout=20)
            body=response.json()
        except (OSError,ValueError,httpx.HTTPError):raise HTTPException(503,'无法连接账号中心，未使用离线账号放行') from None
        if not response.is_success or not body.get('success') or any(not r.get('success') for r in body.get('result',[])):
            # Never return remote query text, parameters, secrets, or password hashes.
            message=json.dumps(body.get('errors',[]))
            if 'fp_identity_guard_revision' in message and 'constraint' in message.lower():raise HTTPException(409,'账号中心记录已变化，请重新执行操作')
            raise HTTPException(503,'账号中心暂时无法完成操作，请检查服务端配置')
        return body['result']

    def snapshot(self):
        result=self.batch([{'sql':'SELECT revision FROM fp_identity_revision WHERE id=1'}]+[{'sql':'SELECT * FROM '+table} for table in TABLES]+[{'sql':"SELECT COALESCE(MAX(seq),10000) AS high_id FROM sqlite_sequence WHERE name='auth_users'"}])
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
    def __init__(self,store,local_connect):
        from .security import create_schema
        self.store=store;self.revision,rows=store.snapshot();self.writes=[]
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        create_schema(self.db)
        self.db.execute('CREATE TABLE audit_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT,entity_id TEXT,content TEXT,created_at TEXT)')
        self.db.execute('CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT)')
        self.db.execute("DELETE FROM auth_id_sequence")
        for table,records in rows.items():
            for record in records:
                record=dict(record)
                if table=="auth_users":
                    record["username"]=str(record["user_id"])
                    record["role"]=ROLE_CODES.get(record["role"],record["role"])
                fields=list(record)
                if any(not re.fullmatch('[a-z_]+',name) for name in fields):raise HTTPException(503,'账号中心结构异常')
                self.db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",list(record.values()))
        with local_connect() as local:
            staff=local.execute("SELECT table_name,row_index,content FROM records WHERE table_name='staff'").fetchall()
        self.db.executemany('INSERT INTO records VALUES (?,?,?)',[tuple(row) for row in staff]);self.db.commit()

    def __enter__(self):return self
    def execute(self,sql,params=()):
        keyword=sql.strip().split()[0].upper()
        if keyword not in {'SELECT','INSERT','UPDATE','DELETE','REPLACE','BEGIN'}:raise RuntimeError('Unsupported identity SQL')
        cursor=self.db.execute(sql,params)
        if keyword in {'INSERT','UPDATE','DELETE','REPLACE'}:
            remote_sql=sql;remote_params=list(params)
            # The compatibility snapshot exposes username as the immutable numeric ID;
            # D1 stores no username column.
            if re.match(r"INSERT INTO auth_users VALUES",sql,re.I):
                remote_sql="INSERT INTO auth_users(user_id,display_name,role,staff_id,password_hash,active,version) VALUES (?,?,?,?,?,1,1)"
                remote_params.pop(1)
                remote_params[2]=ROLE_LABELS.get(remote_params[2],remote_params[2])
            elif re.match(r"UPDATE auth_users SET username=\?,",sql,re.I):
                remote_sql=sql.replace("username=?,", "",1);remote_params.pop(0)
            if re.match(r"UPDATE auth_users SET display_name=\?,role=\?,",remote_sql,re.I):
                remote_params[1]=ROLE_LABELS.get(remote_params[1],remote_params[1])
            self.writes.append({'sql':remote_sql,'params':remote_params})
        return cursor
    def __exit__(self,kind,error,tb):
        try:
            if kind is None and self.writes:self.store.commit(self.revision,self.writes)
        finally:self.db.close()

def wrap_connection(local_connect):
    config=configuration()
    if not config:return local_connect
    store=D1Store(config)
    return lambda:IdentityConnection(store,local_connect)
