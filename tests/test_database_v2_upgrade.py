"""Whole-schema migration, compatibility writes and SQL-side analytics tests."""
import json
import sqlite3

import pytest

from backend.database_v2_upgrade import upgrade_statements
from backend.database_v2 import schema_statements
from backend.d1_business import Connection, initialize


def v1():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    for sql in [
        'CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT,PRIMARY KEY(table_name,row_index))',
        'CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)',
        'CREATE TABLE fp_business_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER,commit_nonce TEXT)',
        'CREATE TABLE fp_business_guard(id INTEGER PRIMARY KEY CHECK(id=1))',
        'CREATE TABLE fp_db_metadata(key TEXT PRIMARY KEY,value TEXT)',
        'CREATE TABLE work_orders(work_order_id TEXT PRIMARY KEY,equipment_id TEXT,content TEXT,status TEXT,updated_at TEXT)',
        'CREATE TABLE fp_resource_revisions(resource TEXT PRIMARY KEY,revision INTEGER)',
        'CREATE TABLE fp_computed_views(dataset_id TEXT,view_key TEXT,content TEXT,PRIMARY KEY(dataset_id,view_key))',
        'CREATE TABLE fp_computed_freshness(dataset_id TEXT,view_key TEXT,input_revision INTEGER,PRIMARY KEY(dataset_id,view_key))',
        "INSERT INTO settings VALUES('last_sync_at','v1')",
        "INSERT INTO fp_db_metadata VALUES('user_version','1')",
        "INSERT INTO fp_business_revision VALUES(1,7,'original')",
    ]:db.execute(sql)
    db.execute('INSERT INTO records VALUES(?,?,?)',['equipment',0,json.dumps({'equipment_id':'E1','equipment_name':'One'})])
    db.commit();return db


def objects(db):return [dict(r) for r in db.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")]


def upgrade(db,revision=7):
    statements=upgrade_statements(objects(db),revision)
    try:
        with db:
            for item in statements:db.execute(item['sql'],item.get('params',[]))
    except Exception:
        db.rollback();raise
    return db


def test_inplace_keeps_uuid_semantics_moves_facts_and_preserves_history():
    db=v1()
    db.execute('INSERT INTO work_orders VALUES(?,?,?,?,?)',['W','E1','{"work_order_id":"W","actual_cost_cny":30}','待验收','2026-01-01T00:00:00Z']);db.commit()
    upgrade(db)
    assert db.execute('SELECT migration_state FROM database_schema').fetchone()[0]=='ready'
    assert db.execute("SELECT type FROM sqlite_master WHERE name='records'").fetchone()[0]=='view'
    assert db.execute("SELECT type FROM sqlite_master WHERE name='maintenance_work_orders'").fetchone()[0]=='table'
    assert json.loads(db.execute('SELECT content FROM work_orders').fetchone()[0])['work_order_id']=='W'
    assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE '_v1_backup_%' OR name LIKE '_v2_obsolete_%'").fetchall()
    db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',['equipment',0,'{"equipment_id":"E1","equipment_name":"Updated"}'])
    assert db.execute('SELECT equipment_name FROM equipment').fetchone()[0]=='Updated'
    db.execute("UPDATE work_orders SET status='已完成' WHERE work_order_id='W'")
    assert db.execute('SELECT status FROM maintenance_work_orders').fetchone()[0]=='已完成'


def test_atomic_upgrade_refuses_stale_source_revision():
    db=v1()
    with pytest.raises(sqlite3.IntegrityError):upgrade(db,6)
    assert db.execute("SELECT type FROM sqlite_master WHERE name='records'").fetchone()[0]=='table'
    assert db.execute('SELECT COUNT(*) FROM records').fetchone()[0]==1
    assert not db.execute("SELECT name FROM sqlite_master WHERE name='database_schema'").fetchall()


class Store:
    def __init__(self,db):self.db=db
    def batch(self,statements):
        out=[]
        with self.db:
            for item in statements:
                c=self.db.execute(item['sql'],item.get('params',[]))
                out.append({'results':[dict(r) for r in c.fetchall()],'meta':{'changes':c.rowcount,'last_row_id':c.lastrowid}})
        return out


def test_python_transaction_adapter_uses_views_with_real_primary_keys():
    db=upgrade(v1());store=Store(db);initialize(store)
    with Connection(store) as c:
        c.execute('UPDATE records SET content=? WHERE table_name=? AND row_index=?',['{"equipment_id":"E1","equipment_name":"Through Python"}','equipment',0])
    assert db.execute('SELECT equipment_name FROM equipment').fetchone()[0]=='Through Python'
    assert not db.execute("SELECT name FROM sqlite_master WHERE name GLOB '_fp_tx_*'").fetchall()


def test_sql_quality_reports_complete_coverage_without_sending_readings_to_ai():
    db=upgrade(v1())
    for i,(stamp,value) in enumerate([('2026-01-01T00:00:00Z',1),('2026-01-01T01:00:00Z',None),('2026-01-01T01:00:00Z',3),('2026-01-01T10:00:00Z',4)]):
        row={'reading_id':str(i),'equipment_id':'E1','timestamp':stamp,'failure':0,'motor_current_a':value,'_feature_fields':['motor_current_a']}
        db.execute('INSERT INTO records VALUES(?,?,?)',['readings',i,json.dumps(row)])
    result=dict(db.execute('SELECT * FROM v_quality_report').fetchone())
    assert result['reading_count']==4 and result['duplicate_readings']==1
    assert result['missing_count']==1 and result['missing_rate']==.25
    metric=dict(db.execute('SELECT * FROM v_equipment_metric_statistics').fetchone())
    assert metric['average']==pytest.approx(8/3) and metric['maximum']==4


def test_work_order_conflicts_are_computed_in_sql_and_ignore_archives():
    db=upgrade(v1())
    for i,device,staff in [('1','E1','P'),('2','E2','P')]:
        details=json.dumps({'start_at':'2026-01-01T00:00:00Z','end_at':'2026-01-01T02:00:00Z','staff_ids':[staff]})
        db.execute('INSERT INTO work_orders VALUES(?,?,?,?,?)',[i,device,details,'已批准','2026-01-01T00:00:00Z'])
    row=dict(db.execute('SELECT * FROM v_work_order_conflicts').fetchone())
    assert row['staff_conflict']==1 and row['equipment_conflict']==0
    db.execute("UPDATE maintenance_work_orders SET details=json_set(details,'$.deleted_at','2026-01-02') WHERE work_order_id='2'")
    assert db.execute('SELECT * FROM v_work_order_conflicts').fetchall()==[]


def test_dashboard_preserves_prediction_identity_for_alert_concurrency_guard():
    db=upgrade(v1())
    db.execute('INSERT INTO records VALUES(?,?,?)',['readings',0,json.dumps({'reading_id':'R','equipment_id':'E1','timestamp':'2026-01-01T00:00:00Z','failure':0})])
    prediction='2026-01-01 08:00:00'
    evidence={'devices':[{'equipment_id':'E1','model_risk':.5,'prediction_at':prediction}]}
    db.execute('INSERT INTO fp_computed_views VALUES(?,?,?)',['v1','overview',json.dumps(evidence)])
    device=json.loads(db.execute('SELECT content FROM v_dashboard_devices').fetchone()[0])
    assert device['prediction_at']==prediction
    assert device['latest_reading']['timestamp']=='2026-01-01T00:00:00.000Z'
