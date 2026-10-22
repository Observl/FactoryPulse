"""Upgrade the owner's D1 account table without changing passwords or creating users."""
import json,re,secrets,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.d1_identity import D1Store,configuration,ROLE_CODES,ROLE_LABELS

def upgrade():
    config=configuration();store=D1Store(config)
    tables=['auth_users','auth_sessions','auth_attempts','auth_onboarding','audit_events','fp_identity_revision']
    result=store.batch([{'sql':'SELECT * FROM '+name} for name in tables])
    data={name:row['results'] for name,row in zip(tables,result)}
    normalized=[]
    for row in data['auth_users']:
        identifier=int(row['user_id']);role=ROLE_CODES.get(row['role'],row['role']);staff=int(row['staff_id'])
        if identifier<10001 or role not in ROLE_LABELS:raise RuntimeError('账号编号或角色不符合新规则，未修改数据库')
        if not ((role=='developer' and staff==0) or (role=='admin' and staff==-1) or (role in {'user','viewer'} and staff>0)):raise RuntimeError('人员编号与角色不匹配，未修改数据库')
        if row['active'] not in (0,1):raise RuntimeError('启用状态必须为0或1')
        if not (re.fullmatch('[a-fA-F0-9]{64}',row['password_hash']) or row['password_hash'].startswith('pbkdf2_sha256$')):raise RuntimeError('密码格式无效，未修改数据库')
        normalized.append([identifier,row['display_name'],ROLE_LABELS[role],staff,row['password_hash'],row['active'],row['version']])
    folder=ROOT/'.secrets';folder.mkdir(exist_ok=True)
    backup=folder/('account-schema-backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    backup.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    schema=(ROOT/'deploy/d1-identity-schema.sql').read_text(encoding='utf-8')
    create_users=schema.split(';')[0].replace('IF NOT EXISTS auth_users','IF NOT EXISTS auth_users_next')
    revision=data['fp_identity_revision'][0]['revision'];nonce=secrets.token_hex(24)
    writes=[{'sql':'CREATE TABLE IF NOT EXISTS fp_identity_guard(id INTEGER PRIMARY KEY CONSTRAINT fp_identity_guard_revision CHECK(id=1))'},
            {'sql':'UPDATE fp_identity_revision SET revision=revision+1,commit_nonce=? WHERE id=1 AND revision=?','params':[nonce,revision]},
            {'sql':'INSERT INTO fp_identity_guard(id) SELECT 0 WHERE NOT EXISTS(SELECT 1 FROM fp_identity_revision WHERE id=1 AND commit_nonce=?)','params':[nonce]},
            {'sql':create_users}]
    for row in normalized:writes.append({'sql':'INSERT INTO auth_users_next(user_id,display_name,role,staff_id,password_hash,active,version) VALUES (?,?,?,?,?,?,?)','params':row})
    writes += [{'sql':'DROP TABLE auth_onboarding'},{'sql':'DROP TABLE auth_users'},{'sql':'ALTER TABLE auth_users_next RENAME TO auth_users'}]
    writes += [{'sql':part} for part in schema.split(';')[1:] if part.strip()]
    for row in data['auth_onboarding']:writes.append({'sql':'INSERT INTO auth_onboarding VALUES (?,?,?)','params':[row['user_id'],row['step'],row['completed_at']]})
    writes += [{'sql':'DELETE FROM auth_sessions'},{'sql':'DELETE FROM auth_attempts'},
               {'sql':'UPDATE auth_id_sequence SET next_id=MAX(next_id,?) WHERE id=1','params':[max([10000]+[row[0] for row in normalized])+1]}]
    store.batch(writes)
    _,verified=store.snapshot()
    assert len(verified['auth_users'])==len(normalized)
    assert all('username' not in row for row in verified['auth_users'])
    assert {str(row['user_id']):row['password_hash'] for row in verified['auth_users']}=={str(row[0]):row[4] for row in normalized}
    print(json.dumps({'account_count':len(normalized),'passwords_preserved':True,'username_removed':True,'backup_saved':True,'next_id':verified['auth_id_sequence'][0]['next_id']},ensure_ascii=False))

if __name__=='__main__':upgrade()
