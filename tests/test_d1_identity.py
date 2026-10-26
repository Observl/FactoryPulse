import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
import pytest
from fastapi import HTTPException
from backend.d1_identity import D1Store,IdentityConnection

class FakeD1(D1Store):
    """Exercise real SQLite batch rollback and CAS; no network or operator database."""
    def __init__(self,path):
        self.path=path;self.lock=threading.RLock()
        with sqlite3.connect(path) as c:c.executescript((Path(__file__).parents[1]/'deploy/d1-identity-schema.sql').read_text())
    def batch(self,statements):
        with self.lock,sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row;output=[]
            try:
                c.execute('BEGIN IMMEDIATE')
                for statement in statements:
                    cursor=c.execute(statement['sql'],statement.get('params',[]))
                    output.append({'success':True,'results':[dict(row) for row in cursor.fetchall()],'meta':{'changes':max(0,cursor.rowcount),'last_row_id':cursor.lastrowid}})
                return output
            except sqlite3.IntegrityError as exc:
                if 'fp_identity_guard' in str(exc):raise HTTPException(409,'conflict') from None
                raise

@contextmanager
def local():
    with sqlite3.connect(':memory:') as c:
        c.execute('CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT)');yield c

def test_stale_writes_are_rejected_and_batch_is_rolled_back(tmp_path):
    store=FakeD1(tmp_path/'identities.sqlite3');first=IdentityConnection(store,local);stale=IdentityConnection(store,local)
    with first as c:c.execute("INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)",('10001','10001','Owner','developer','0','hash'))
    with pytest.raises(HTTPException) as error:
        with stale as c:c.execute("INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)",('10002','10002','Stale','developer','0','hash'))
    assert error.value.status_code==409
    revision,rows=store.snapshot();assert revision==1 and [u['user_id'] for u in rows['auth_users']]==[10001]

def test_exception_never_commits_partial_identity_changes(tmp_path):
    store=FakeD1(tmp_path/'identities.sqlite3')
    with pytest.raises(ValueError):
        with IdentityConnection(store,local) as c:
            c.execute("INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)",('10001','10001','A','developer','0','hash'));raise ValueError()
    assert store.snapshot()[1]['auth_users']==[]

def test_read_only_snapshot_does_not_write_or_advance_revision(tmp_path):
    store=FakeD1(tmp_path/'identities.sqlite3')
    with IdentityConnection(store,local) as c:assert c.execute('SELECT * FROM auth_users').fetchall()==[]
    assert store.snapshot()[0]==0

def test_auth_sql_round_trip_preserves_rows_and_versions(tmp_path):
    store=FakeD1(tmp_path/'identities.sqlite3')
    with IdentityConnection(store,local) as c:
        c.execute('BEGIN IMMEDIATE');c.execute("INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)",('10001','10001','A','developer','0','hash'));c.execute('INSERT INTO auth_onboarding VALUES (?,?,?)',('10001',1,None))
    with IdentityConnection(store,local) as c:
        row=c.execute('SELECT * FROM auth_users WHERE user_id=?',('10001',)).fetchone();assert row['password_hash']=='hash'
        c.execute('UPDATE auth_users SET version=version+1 WHERE user_id=?',('10001',))
    assert store.snapshot()[1]['auth_users'][0]['version']==2

def test_remote_outage_is_fail_closed_without_exposing_request(tmp_path,monkeypatch):
    import httpx
    token=tmp_path/'token';token.write_text('synthetic-private-token')
    store=D1Store({'account_id':'a'*32,'database_id':'b'*36,'token_file':str(token)})
    def fail(*args,**kwargs):raise httpx.ConnectError('synthetic-private-token')
    monkeypatch.setattr(httpx,'post',fail)
    with pytest.raises(HTTPException) as error:store.snapshot()
    assert error.value.status_code==503 and 'synthetic-private-token' not in error.value.detail

def test_d1_http_errors_never_echo_sql_or_hashes(tmp_path,monkeypatch):
    import httpx
    token=tmp_path/'token';token.write_text('synthetic-private-token')
    store=D1Store({'account_id':'a'*32,'database_id':'b'*36,'token_file':str(token)})
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(403,json={'success':False,'errors':[{'message':'private-sql-and-hashes'}]}))
    with pytest.raises(HTTPException) as error:store.snapshot()
    assert error.value.status_code==503 and 'private-sql-and-hashes' not in error.value.detail


def test_normal_service_requires_d1_and_never_falls_back(tmp_path,monkeypatch):
    import backend.d1_identity as identity
    monkeypatch.setattr(identity,'ROOT',tmp_path)
    monkeypatch.delenv('FACTORYPULSE_IDENTITY_CONFIG',raising=False)
    monkeypatch.delenv('FACTORYPULSE_TEST_ALLOW_ANONYMOUS',raising=False)
    with pytest.raises(RuntimeError,match='Cloudflare D1'):identity.configuration()


def test_default_private_identity_config_is_shared_in_every_environment(tmp_path,monkeypatch):
    import json
    import backend.d1_identity as identity
    monkeypatch.setattr(identity,'ROOT',tmp_path)
    monkeypatch.delenv('FACTORYPULSE_IDENTITY_CONFIG',raising=False)
    monkeypatch.delenv('FACTORYPULSE_TEST_ALLOW_ANONYMOUS',raising=False)
    secret=tmp_path/'.secrets';secret.mkdir()
    (secret/'identity.json').write_text(json.dumps({'account_id':'a'*32,'database_id':'a'*36,'token_file':'token'}))
    for deployment in ('local','cloud',''):
        monkeypatch.setenv('FACTORYPULSE_DEPLOYMENT',deployment)
        assert identity.configuration()['token_file']==str(secret/'token')
