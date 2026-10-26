"""Isolated SQL fixtures only; never connects to a website database."""
import json
import sqlite3
from contextlib import contextmanager
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from backend.data_sync import schema_statements, delta, install_data_sync, cached_business_response, refresh_rule_baselines
from backend.security import _principal

@pytest.fixture
def connection(tmp_path):
    path=tmp_path/'sync-fixture.sqlite3'
    @contextmanager
    def connect():
        with sqlite3.connect(path) as db:
            db.row_factory=sqlite3.Row
            yield db
    with connect() as db:
        db.executescript('''CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT,PRIMARY KEY(table_name,row_index));
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE alerts(alert_id TEXT PRIMARY KEY,equipment_id TEXT,status TEXT,note TEXT,updated_at TEXT,dataset_version TEXT);
        CREATE TABLE work_orders(work_order_id TEXT PRIMARY KEY,content TEXT);
        CREATE TABLE fp_computed_views(dataset_id TEXT,view_key TEXT,content TEXT,PRIMARY KEY(dataset_id,view_key));
        INSERT INTO settings VALUES('last_sync_at','v1');
        INSERT INTO records VALUES('equipment',0,'{"equipment_id":"E1"}');''')
        names=['records','settings','alerts','work_orders','fp_computed_views']
        tables={name:[r['name'] for r in db.execute(f'PRAGMA table_info({name})')] for name in names}
        for sql in schema_statements(tables):db.execute(sql)
    return connect

def test_resource_revisions_are_selective_atomic_and_ignore_noop(connection):
    with connection() as db:
        db.execute("INSERT INTO work_orders VALUES('W1','{}')")
        assert dict(db.execute('SELECT * FROM fp_resource_revisions').fetchone())=={'resource':'work_orders','revision':1}
        db.execute("UPDATE work_orders SET content=content")
        assert db.execute("SELECT revision FROM fp_resource_revisions WHERE resource='work_orders'").fetchone()[0]==1
        db.execute('BEGIN') if not db.in_transaction else None
        db.execute("UPDATE records SET content='new' WHERE table_name='equipment'")
        db.rollback()
    with connection() as db:
        assert not db.execute("SELECT * FROM fp_resource_revisions WHERE resource='records/equipment'").fetchall()

def test_precomputed_view_invalidates_only_when_its_inputs_change(connection):
    with connection() as db:
        db.execute("INSERT INTO fp_computed_views VALUES('v1','data-quality','{}')")
        assert db.execute('SELECT COUNT(*) FROM fp_v_processed_results').fetchone()[0]==1
        db.execute("INSERT INTO work_orders VALUES('W1','{}')")
        assert db.execute('SELECT COUNT(*) FROM fp_v_processed_results').fetchone()[0]==1
        db.execute("UPDATE records SET content='new'")
        assert db.execute('SELECT COUNT(*) FROM fp_v_processed_results').fetchone()[0]==0
        db.execute("UPDATE fp_computed_views SET content='{}'")
        assert db.execute('SELECT COUNT(*) FROM fp_v_processed_results').fetchone()[0]==1
        assert db.execute('SELECT record_count FROM fp_v_data_source').fetchone()[0]==0

def test_record_rebucket_invalidates_both_resources(connection):
    with connection() as db:
        db.execute("UPDATE records SET table_name='readings'")
        assert {r['resource']:r['revision'] for r in db.execute('SELECT * FROM fp_resource_revisions')}=={'records/equipment':1,'records/readings':1}

def test_auth_conditional_reads_and_delta_transfer(connection):
    app=FastAPI();install_data_sync(app,connection);calls=[]
    @app.middleware('http')
    async def guard(request:Request,call_next):
        user=request.headers.get('x-test-user')
        if not user:return JSONResponse({'detail':'login required'},401)
        token=_principal.set({'user_id':user,'role':'viewer','version':1})
        try:return await cached_business_response(request,lambda:call_next(request))
        finally:_principal.reset(token)
    @app.get('/api/work-orders')
    def work():
        calls.append(1)
        with connection() as db:return {'records':[dict(r) for r in db.execute('SELECT * FROM work_orders')],'static':'unchanged'*100}
    client=TestClient(app);headers={'x-test-user':'A'}
    first=client.get('/api/work-orders',headers=headers);assert first.status_code==200
    tag=first.headers['etag']
    same=client.get('/api/work-orders',headers={**headers,'If-None-Match':tag})
    assert same.status_code==304 and len(calls)==1
    assert client.get('/api/work-orders',headers={'If-None-Match':tag}).status_code==401
    other=client.get('/api/work-orders',headers={'x-test-user':'B','If-None-Match':tag})
    assert other.status_code==200 and other.headers['etag']!=tag
    with connection() as db:db.execute("INSERT INTO work_orders VALUES('W1','new')")
    changed=client.get('/api/work-orders',headers={**headers,'If-None-Match':tag,'X-FP-Delta-Base':tag})
    assert changed.status_code==200 and changed.headers['X-FP-Delta']=='1'
    assert changed.json()['base']==tag and changed.json()['patch'][0]['path']==['records',0]
    assert len(calls)==3
    assert client.get('/api/data/revisions',headers=headers).json()['resources']['work_orders']==1

def test_delta_preserves_deletions_and_escaped_keys():
    patch=delta({'a/b':{'~':1},'rows':[1,2,3]},{'a/b':{'~':2},'rows':[1]})
    assert {'op':'set','path':['a/b','~'],'value':2} in patch
    assert [p['path'] for p in patch if p['op']=='remove']==[['rows',2],['rows',1]]

def test_rule_only_changes_preserve_model_results_and_unchanged_devices():
    original={'rule_risk':.1,'model_risk':.8,'combined_risk':.8}
    untouched={'rule_risk':.2,'model_risk':None,'ewma_risk':.3,'combined_risk':.3}
    summary={'model':'frozen'}
    state={'devices':{'E1':original,'E2':untouched},'summary':summary}
    refresh_rule_baselines(state,{'E1':{'risk_score':.5},'E2':{'risk_score':.2}},float)
    assert state['devices']['E1']['rule_risk']==.5
    assert state['devices']['E1']['combined_risk']==.8
    assert state['devices']['E2'] is untouched and state['summary'] is summary
    assert original['rule_risk']==.1
