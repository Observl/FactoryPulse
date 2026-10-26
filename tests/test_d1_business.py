"""SQLite here is an isolated D1 emulator, never a website database."""
import sqlite3
import threading
import pytest
from fastapi import HTTPException
from backend.d1_business import Connection,initialize,identifiers
from backend.d1_identity import RemoteIdentityConnection


class Store:
    def __init__(self,path):self.path=path;self.lock=threading.RLock()
    def batch(self,statements):
        with self.lock,sqlite3.connect(self.path) as db:
            db.row_factory=sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            result=[]
            try:
                for item in statements:
                    cursor=db.execute(item['sql'],item.get('params',[]))
                    result.append({'results':[dict(r) for r in cursor.fetchall()],'meta':{'changes':max(0,cursor.rowcount),'last_row_id':cursor.lastrowid}})
            except sqlite3.IntegrityError:raise HTTPException(503,'constraint') from None
            return result


@pytest.fixture
def store(tmp_path):
    value=Store(tmp_path/'isolated-d1.sqlite3');initialize(value)
    value.batch([{'sql':'CREATE TABLE items(id INTEGER PRIMARY KEY,value TEXT NOT NULL CHECK(length(value)>0))'}])
    return value


def test_remote_transaction_read_your_writes_and_publish(store):
    with Connection(store) as c:
        c.execute('INSERT INTO items VALUES (?,?)',[1,'one'])
        assert c.execute('SELECT * FROM items').fetchone()['value']=='one'
        assert store.batch([{'sql':'SELECT * FROM items'}])[0]['results']==[]
    assert store.batch([{'sql':'SELECT * FROM items'}])[0]['results']==[{'id':1,'value':'one'}]


def test_exception_and_constraint_failure_never_publish(store):
    with pytest.raises(ValueError):
        with Connection(store) as c:
            c.execute('INSERT INTO items VALUES(1,?)',['one']);raise ValueError()
    with pytest.raises(HTTPException):
        with Connection(store) as c:c.execute('INSERT INTO items VALUES(1,?)',[''])
    assert store.batch([{'sql':'SELECT * FROM items'}])[0]['results']==[]


def test_stale_write_rejects_entire_transaction(store):
    a,b=Connection(store),Connection(store)
    a.execute('SELECT * FROM items');b.execute('SELECT * FROM items')
    a.execute('INSERT INTO items VALUES(1,?)',['one']);a.commit()
    b.execute('INSERT INTO items VALUES(2,?)',['two'])
    with pytest.raises(HTTPException) as error:b.commit()
    assert error.value.status_code==409
    assert store.batch([{'sql':'SELECT * FROM items'}])[0]['results']==[{'id':1,'value':'one'}]
    assert store.batch([{'sql':"SELECT name FROM sqlite_master WHERE name LIKE '_fp_tx_%'"}])[0]['results']==[]


def test_sql_literals_and_comments_not_rewritten():
    assert identifiers("SELECT 'items',items FROM items -- items",{'items':'remote'})=="SELECT 'items',remote FROM remote -- items"


def test_bulk_inserts_are_bounded_and_remain_unpublished_until_commit(store,monkeypatch):
    original=store.batch;bound=[]
    def capture(statements):
        bound.extend(len(s.get('params',[])) for s in statements)
        return original(statements)
    monkeypatch.setattr(store,'batch',capture)
    with Connection(store) as c:
        c.executemany('INSERT INTO items VALUES (?,?)',[(i,str(i)) for i in range(1000)])
        assert c.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1000
        assert original([{'sql':'SELECT COUNT(*) AS n FROM items'}])[0]['results'][0]['n']==0
    assert max(bound)<=100
    assert original([{'sql':'SELECT COUNT(*) AS n FROM items'}])[0]['results'][0]['n']==1000


def test_remote_identity_projection_and_cas(store):
    store.batch([
        {'sql':'CREATE TABLE fp_identity_revision(id INTEGER PRIMARY KEY,revision INTEGER,commit_nonce TEXT)'},
        {'sql':'INSERT INTO fp_identity_revision VALUES(1,0,NULL)'},
        {'sql':'CREATE TABLE fp_identity_guard(id INTEGER PRIMARY KEY CHECK(id=1))'},
        {'sql':'CREATE TABLE auth_users(user_id INTEGER PRIMARY KEY,display_name TEXT,role TEXT,staff_id INTEGER,password_hash TEXT,active INTEGER,version INTEGER)'},
    ])
    with RemoteIdentityConnection(store) as c:
        c.execute('INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)',['10001','10001','Owner','developer','0','hash'])
        row=c.execute('SELECT * FROM auth_users WHERE username=?',['10001']).fetchone()
        assert row['role']=='developer' and row['username']=='10001'
    assert store.batch([{'sql':'SELECT role FROM auth_users'}])[0]['results']==[{'role':'开发者'}]


def test_import_staging_is_remote_and_flushes_before_validation(store,monkeypatch):
    import backend.d1_business as module
    monkeypatch.setattr(module,'configuration',lambda:{})
    monkeypatch.setattr(module,'D1Store',lambda config:store)
    stage=module.RemoteStage('12345678-1234-1234-1234-123456789abc')
    stage.execute('CREATE TABLE staged(row_index INTEGER PRIMARY KEY,equipment_id TEXT,timestamp TEXT,failure INTEGER,content TEXT)')
    stage.execute('INSERT INTO staged VALUES(?,?,?,?,?)',[0,'D1','2026-10-01',0,'{}'])
    stage.execute('INSERT INTO staged VALUES(?,?,?,?,?)',[1,'D1','2026-10-02',1,'{}'])
    assert stage.execute('SELECT COUNT(*) AS n FROM staged').fetchone()[0]==2
    stage.execute('CREATE TABLE onsets AS SELECT equipment_id,timestamp FROM (SELECT equipment_id,timestamp,failure,LAG(failure) OVER(PARTITION BY equipment_id ORDER BY timestamp) AS previous FROM staged) WHERE failure=1 AND previous=0')
    assert stage.execute('SELECT COUNT(*) FROM onsets').fetchone()[0]==1
    assert stage.exists()
