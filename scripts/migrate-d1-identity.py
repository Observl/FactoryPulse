"""Copy only identities to an empty owner-selected D1 database; never print credentials."""
import argparse,json,os,sqlite3,sys
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.d1_identity import D1Store,configuration
from backend.security import password_hash,validate_password

def migrate(source,config_file,password_file):
    os.environ['FACTORYPULSE_IDENTITY_CONFIG']=str(config_file.resolve())
    store=D1Store(configuration())
    schema=(ROOT/'deploy/d1-identity-schema.sql').read_text(encoding='utf-8')
    store.batch([{'sql':statement} for statement in schema.split(';') if statement.strip()])
    revision,remote=store.snapshot()
    if remote['auth_users']:raise RuntimeError('D1账号库已有用户，拒绝覆盖或重复迁移')
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as local:
        local.row_factory=sqlite3.Row
        users=[dict(row) for row in local.execute('SELECT * FROM auth_users')]
        onboarding=[dict(row) for row in local.execute('SELECT * FROM auth_onboarding')]
    if not users:raise RuntimeError('源数据库中没有账号，未执行迁移')
    if not any(user['role']=='admin' and user['active'] for user in users):raise RuntimeError('源数据库缺少有效管理员')
    if not any(user['user_id']=='test' for user in users):
        if any(user['username']=='线上测试员' for user in users):raise RuntimeError('线上测试员登录名已存在，需先人工核对')
        password=password_file.read_text(encoding='utf-8').strip();validate_password(password)
        users.append(dict(user_id='test',username='线上测试员',display_name='线上测试员',role='admin',staff_id=None,password_hash=password_hash(password),active=1,version=1))
    if not any(user['user_id']=='cloud-viewer' for user in users):
        import secrets
        users.append(dict(user_id='cloud-viewer',username='cloud-viewer',display_name='只读访客',role='viewer',staff_id=None,password_hash=password_hash(secrets.token_urlsafe(48)),active=1,version=1))
        onboarding.append(dict(user_id='cloud-viewer',step=5,completed_at=datetime.now(timezone.utc).isoformat()))
    writes=[]
    for table,records in [('auth_users',users),('auth_onboarding',onboarding)]:
        for row in records:
            fields=list(row);writes.append({'sql':f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",'params':list(row.values())})
    writes.append({'sql':'INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)','params':['identity_migrated','owner',json.dumps({'users':len(users),'sessions_copied':False}),datetime.now(timezone.utc).isoformat()]})
    store.commit(revision,writes)
    _,verified=store.snapshot()
    expected={row['user_id']:row['password_hash'] for row in users}
    if {row['user_id']:row['password_hash'] for row in verified['auth_users']}!=expected:raise RuntimeError('迁移后验证失败，未启用连接')
    print(json.dumps({'migrated_users':len(users),'password_hashes_verified':True,'sessions_copied':False,'database_id':store.config['database_id']},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--config',type=Path,required=True);parser.add_argument('--admin-password-file',type=Path,required=True);args=parser.parse_args()
    migrate(args.source,args.config,args.admin_password_file)
