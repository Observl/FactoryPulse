import sqlite3
from contextlib import closing

import pytest

from backend import main
from backend.backups import create_backup
from tests.test_api import client,workbook

@pytest.mark.parametrize('damage',['delete','truncate'])
def test_backup_status_does_not_claim_missing_or_changed_snapshot_is_ready(tmp_path,monkeypatch,damage):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.backups import install_backups
    snapshot=create_backup(main.DB,tmp_path)
    with main.connect() as connection:
        connection.execute('INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)',('database_backup',snapshot['filename'],json.dumps(snapshot),snapshot['created_at']))
    monkeypatch.setenv('FACTORYPULSE_BACKUP_DIR',str(tmp_path))
    isolated=FastAPI();install_backups(isolated,main.DB,main.connect)
    probe=TestClient(isolated)
    before=probe.get('/api/backups/status').json()
    assert before['status']=='ready' and before['backup_available'] is True
    path=tmp_path/snapshot['filename']
    if damage=='delete':path.unlink()
    else:path.write_bytes(b'truncated')
    after=probe.get('/api/backups/status').json()
    assert after['status']=='failed' and after['backup_available'] is False
    assert '重新备份' in after['last_error']
    assert after['last_success']==snapshot
    restarted=FastAPI();install_backups(restarted,main.DB,main.connect)
    recovered=TestClient(restarted).get('/api/backups/status').json()
    assert recovered['status']=='failed' and recovered['backup_available'] is False


def test_snapshot_can_be_opened_independently_and_preserves_business_records(tmp_path):
    result=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert result.status_code==200,result.text
    with main.connect() as connection:
        connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",("BACKUP-WORK","CNC-001","{}","待验收","2026-10-20"))
    folder=tmp_path/"backups"
    snapshot=create_backup(main.DB,folder)
    with main.connect() as connection:
        connection.execute("DELETE FROM work_orders WHERE work_order_id='BACKUP-WORK'")
    with closing(sqlite3.connect(folder/snapshot["filename"])) as recovered:
        assert recovered.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert recovered.execute("SELECT status FROM work_orders WHERE work_order_id='BACKUP-WORK'").fetchone()[0]=="待验收"
        assert recovered.execute("SELECT COUNT(*) FROM records").fetchone()[0]>0
    assert snapshot["size_bytes"]>0
    assert not list(folder.glob("*.partial"))


def test_missing_or_incomplete_database_never_publishes_a_backup(tmp_path):
    missing=tmp_path/"missing.sqlite3"
    folder=tmp_path/"backups"
    with pytest.raises(RuntimeError):create_backup(missing,folder)
    assert not missing.exists()
    incomplete=tmp_path/"incomplete.sqlite3"
    with closing(sqlite3.connect(incomplete)) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        connection.commit()
    with pytest.raises(RuntimeError):create_backup(incomplete,folder)
    assert not list(folder.glob("*.sqlite3"))
    assert not list(folder.glob("*.partial"))
