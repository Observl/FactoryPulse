import importlib.util,json,shutil,sqlite3,uuid
from pathlib import Path
from fastapi import FastAPI
from backend import main
from backend.import_pipeline import install_import_pipeline
from tests.test_api import client
from tests.test_staged_import import prepare

def staged():return prepare('设备编号,采集时间,油温\nA,2020-01-01,310\n')

def test_cancellation_interrupts_sql_label_derivation_without_changing_live_data(monkeypatch):
    from datetime import datetime,timedelta
    from backend import import_pipeline
    route=next(route for route in main.app.routes if route.path=='/api/import/jobs/{identifier}/cancel')
    cells=dict(zip(route.endpoint.__code__.co_freevars,route.endpoint.__closure__))
    events=cells['cancellations'].cell_contents
    original=sqlite3.connect
    interrupted=[]
    def connect(database,*args,**kwargs):
        connection=original(database,*args,**kwargs)
        path=Path(str(database))
        if path.name.endswith('-stage.sqlite3'):
            identifier=path.name.removesuffix('-stage.sqlite3')
            def trace(statement):
                if statement.startswith('CREATE TABLE onsets AS'):
                    events[identifier].set();interrupted.append(identifier)
            connection.set_trace_callback(trace)
        return connection
    monkeypatch.setattr(import_pipeline.sqlite3,'connect',connect)
    before=main.rows('readings');version=main.settings_get('last_sync_at')
    start=datetime(2020,1,1)
    content='设备编号,采集时间,油温\n'+''.join(f'A,{start+timedelta(minutes=index)},310\n' for index in range(600))
    job=prepare(content)
    assert interrupted==[job['job_id']]
    assert job['status']=='cancelled' and '已取消' in job['message']
    assert main.rows('readings')==before and main.settings_get('last_sync_at')==version
    assert client.post(f"/api/import/jobs/{job['job_id']}/commit",json={'replace_existing':True,'expected_dataset_version':version}).status_code==409

def test_cancel_rechecks_committed_state_instead_of_overwriting_stale_read(monkeypatch):
    job=staged()
    route=next(route for route in main.app.routes if route.path=='/api/import/jobs/{identifier}/cancel')
    cell=dict(zip(route.endpoint.__code__.co_freevars,route.endpoint.__closure__))['get']
    original=cell.cell_contents
    receipts=[]
    entered=False
    def stale_read(identifier):
        nonlocal entered
        snapshot=original(identifier)
        if entered:return snapshot
        entered=True
        response=client.post(f'/api/import/jobs/{identifier}/commit',json={'replace_existing':True,'expected_dataset_version':job['expected_dataset_version']})
        assert response.status_code==200,response.text
        receipts.append(response.json())
        return snapshot
    monkeypatch.setattr(cell,'cell_contents',stale_read)
    response=client.post(f"/api/import/jobs/{job['job_id']}/cancel")
    assert response.status_code==409
    saved=original(job['job_id'])
    assert saved['status']=='committed' and saved['result']==receipts[0]

def test_missing_or_corrupt_preview_cannot_commit_or_change_current_data():
    job=staged();assert job['status']=='ready'
    path=main.IMPORT_SESSION_DIR/(job['job_id']+'-stage.sqlite3')
    before=main.settings_get('last_sync_at');records=main.rows('readings')
    path.unlink()
    url=f"/api/import/jobs/{job['job_id']}/commit";body={'replace_existing':True,'expected_dataset_version':job['expected_dataset_version']}
    response=client.post(url,json=body)
    assert response.status_code==409 and '临时文件缺失' in response.text
    assert not path.exists()
    path.write_bytes(b'not a sqlite database')
    assert client.post(url,json=body).status_code==409
    assert main.settings_get('last_sync_at')==before and main.rows('readings')==records

def test_restart_marks_ready_import_without_preview_as_interrupted():
    job=staged();(main.IMPORT_SESSION_DIR/(job['job_id']+'-stage.sqlite3')).unlink()
    install_import_pipeline(FastAPI(),main.connect,main.settings_get,main._lock,main.IMPORT_SESSION_DIR)
    recovered=client.get(f"/api/import/jobs/{job['job_id']}").json()
    assert recovered['status']=='interrupted' and '重新上传' in recovered['message']

def test_recovery_compares_settings_and_archive_tables_and_controls_job_changes(tmp_path):
    source=Path(__file__).resolve().parents[1]/'scripts/exercise-recovery.py'
    spec=importlib.util.spec_from_file_location('recovery_probe',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    job=staged();backup=tmp_path/'backup.sqlite3';restored=tmp_path/'restored.sqlite3'
    with main.connect() as original,sqlite3.connect(backup) as target:original.backup(target)
    shutil.copy2(backup,restored);before=module.fingerprints(backup)
    assert {'settings','archived_records','dataset_versions','planning_runs','import_jobs'}<=set(before)
    with sqlite3.connect(restored) as connection:
        updated={**job,'status':'interrupted','message':'预览缺失，重新上传'}
        connection.execute('UPDATE import_jobs SET content=? WHERE job_id=?',(json.dumps(updated),job['job_id']))
    after=module.fingerprints(restored)
    assert module.compare_after_startup(backup,restored,before,after)==1
    with sqlite3.connect(restored) as connection:connection.execute("INSERT OR REPLACE INTO settings VALUES ('unexpected-change','1')")
    import pytest
    with pytest.raises(RuntimeError,match='意外变化'):module.compare_after_startup(backup,restored,before,module.fingerprints(restored))
