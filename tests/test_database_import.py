import io,sqlite3,time
from pathlib import Path
import pytest
from backend import main
from backend.database_import import load_dump,export_table
from backend.security import COOKIE
from tests.test_api import client


def database(tmp_path):
    path=tmp_path/'factory.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE sensor_samples(equipment_id TEXT,timestamp TEXT,vibration_mm_s REAL,failure INTEGER)')
        c.executemany('INSERT INTO sensor_samples VALUES (?,?,?,?)',[('SQL-E1','2026-10-01 00:00:00',1.2,0),('SQL-E1','2026-10-01 01:00:00',1.3,0)])
        c.execute('CREATE TABLE auth_users(username TEXT,password_hash TEXT)')
        c.execute("INSERT INTO auth_users VALUES ('secret-user','not-exportable')")
    return path


def test_sqlite_inspect_and_staged_import(tmp_path):
    path=database(tmp_path)
    before=main.rows('readings')
    response=client.post('/api/import/database/inspect',files={'file':('factory.db',path.read_bytes(),'application/octet-stream')})
    assert response.status_code==200,response.text
    data=response.json();assert data['tables']==['sensor_samples'];assert main.rows('readings')==before
    analysis=client.post('/api/import/database/analyze',json={'upload_id':data['upload_id'],'table':'sensor_samples'})
    assert analysis.status_code==200,analysis.text
    mapping=analysis.json()
    preview=client.post('/api/import/intelligent/preview',json={'upload_id':mapping['upload_id'],'mapping':mapping['mapping'],'profile_id':'generic'})
    assert preview.status_code==200,preview.text
    identifier=preview.json()['job_id']
    for _ in range(100):
        job=client.get('/api/import/jobs/'+identifier).json()
        if job['status'] not in {'queued','validating'}:break
        time.sleep(.02)
    assert job['status']=='ready',job
    assert main.rows('readings')==before
    result=client.post('/api/import/jobs/'+identifier+'/commit',json={'replace_existing':True,'expected_dataset_version':job['expected_dataset_version']})
    assert result.status_code==200,result.text
    assert [x['equipment_id'] for x in main.rows('equipment')]==['SQL-E1']


def test_sqlite_rejects_sensitive_table_and_injected_name(tmp_path):
    path=database(tmp_path)
    data=client.post('/api/import/database/inspect',files={'file':('factory.sqlite3',path.read_bytes())}).json()
    for table in ['auth_users','sensor_samples; DROP TABLE sensor_samples;--','../secret']:
        result=client.post('/api/import/database/analyze',json={'upload_id':data['upload_id'],'table':table})
        assert result.status_code==422
    assert client.post('/api/import/database/analyze',json={'upload_id':'../outside','table':'sensor_samples'}).status_code==422
    assert 'SQL-E1' in export_table(path,'sensor_samples').decode('utf-8-sig')


def test_sql_dump_import_and_reject_executable_statements(tmp_path):
    dump=b"BEGIN TRANSACTION; CREATE TABLE samples(equipment_id TEXT,timestamp TEXT,vibration_mm_s REAL); INSERT INTO samples VALUES('E1','2026-10-01 00:00:00',1.5); COMMIT;"
    response=client.post('/api/import/database/inspect',files={'file':('samples.sql',dump)})
    assert response.status_code==200,response.text
    assert response.json()['tables']==['samples']
    outside=tmp_path/'forbidden.sqlite3'
    for sql in [f"ATTACH DATABASE '{outside.as_posix()}' AS leak;", "SELECT load_extension('evil');",'CREATE VIEW malicious AS SELECT 1;', 'PRAGMA writable_schema=ON;']:
        response=client.post('/api/import/database/inspect',files={'file':('malicious.sql',sql.encode())})
        assert response.status_code==422,response.text
    assert not outside.exists()
    assert client.post('/api/import/database/inspect',files={'file':('not.db',b'not a sqlite file')}).status_code==422


def test_database_import_requires_authorized_manager(tmp_path):
    path=database(tmp_path)
    admin=client.post('/api/auth/bootstrap',json={'username':'developer','display_name':'测试管理员','password':'test-database-password-2026'})
    assert admin.status_code==200,admin.text
    assert client.post('/api/auth/users',headers={'Cookie':f'{COOKIE}={admin.cookies.get(COOKIE)}'},json={'username':'viewer','display_name':'只读','password':'test-database-password-2026','role':'viewer','staff_id':-1}).status_code==200
    client.post('/api/auth/logout')
    assert client.post('/api/import/database/inspect',files={'file':('test.db',path.read_bytes())}).status_code==401
    viewer=client.post('/api/auth/login',json={'username':'viewer','password':'test-database-password-2026'})
    assert viewer.status_code==200
    assert client.post('/api/import/database/inspect',headers={'Cookie':f'{COOKIE}={viewer.cookies.get(COOKIE)}'},files={'file':('test.db',path.read_bytes())}).status_code==403


def test_project_database_exports_only_monitoring_records(tmp_path):
    import json
    path=tmp_path/'project.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE records(table_name TEXT,row_index INTEGER,content TEXT)')
        c.execute('INSERT INTO records VALUES (?,?,?)',('readings',0,json.dumps({'equipment_id':'E9','timestamp':'2026-10-01','vibration_mm_s':2})))
        c.execute('INSERT INTO records VALUES (?,?,?)',('staff',0,json.dumps({'staff_name':'PRIVATE-NAME'})))
    exported=export_table(path,'records').decode('utf-8-sig')
    assert 'equipment_id' in exported and 'E9' in exported
    assert 'PRIVATE-NAME' not in exported and 'staff_name' not in exported
