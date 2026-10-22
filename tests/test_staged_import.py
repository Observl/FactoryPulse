import json
import time

from backend.main import connect, rows, settings_get
from tests.test_api import client, workbook


def prepare(content):
    response=client.post("/api/import/intelligent/analyze",files={"file":("factory.csv",content.encode("utf-8-sig"),"text/csv")})
    assert response.status_code==200,response.text
    analysis=response.json()
    mapping=[{"source_column":"设备编号","target_field":"equipment_id"},{"source_column":"采集时间","target_field":"timestamp"},{"source_column":"油温","target_field":"oil_temperature_c","source_unit":"K"}]
    response=client.post("/api/import/intelligent/preview",json={"upload_id":analysis["upload_id"],"mapping":mapping})
    assert response.status_code==200,response.text
    identifier=response.json()["job_id"]
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        job=client.get(f"/api/import/jobs/{identifier}").json()
        if job["status"] not in {"queued","validating"}: return job
        time.sleep(.02)
    raise AssertionError("background import did not finish")


def test_preview_does_not_mutate_live_data_and_commit_archives_version(monkeypatch):
    monkeypatch.setattr("backend.main._api_key","")
    uploaded=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert uploaded.status_code==200
    previous=settings_get("last_sync_at")
    job=prepare("设备编号,采集时间,油温\nAPU-1,2020-01-01 00:00:00,310\nAPU-1,2020-01-02 00:00:00,312\n")
    assert job["status"]=="ready",job
    assert rows("equipment")[0]["equipment_id"]=="CNC-001"
    assert abs(job["preview"][0]["oil_temperature_c"]-36.85)<.001
    url=f"/api/import/jobs/{job['job_id']}/commit"
    payload={"replace_existing":True,"expected_dataset_version":previous}
    result=client.post(url,json=payload)
    assert result.status_code==200,result.text
    assert client.post(url,json=payload).json()==result.json()
    assert rows("equipment")[0]["equipment_id"]=="APU-1"
    assert all(row["future_failure"] is None for row in rows("readings"))
    assert rows("staff")==[]
    assert rows("maintenance_rules")[0]["configuration_status"]=="required"
    overview=client.get("/api/overview").json()
    assert overview["devices"][0]["risk_available"] is False
    assert overview["devices"][0]["risk_level"]=="待评估"
    assert overview["metrics"]["unknown"]==1
    assert overview["metrics"]["avg_risk"] is None
    quality=client.get("/api/data-quality").json()
    assert quality["missing_rate"]==0
    assert quality["abnormal_values"]==0
    assert "oil_temperature_c" in quality["field_coverage"]
    assert "torque_nm" not in quality["field_coverage"]
    with connect() as connection:
        count=connection.execute("SELECT COUNT(*) FROM archived_records WHERE version=?",(previous,)).fetchone()[0]
    assert count>0


def test_invalid_rows_cannot_be_committed(monkeypatch):
    monkeypatch.setattr("backend.main._api_key","")
    before=rows("equipment")
    job=prepare("设备编号,采集时间,油温\nA,2020-01-01 00:00:00,310\nA,2020-01-01 00:00:00,312\nA,invalid,315\n")
    assert job["status"]=="invalid",job
    assert job["error_count"]==2
    response=client.post(f"/api/import/jobs/{job['job_id']}/commit",json={"replace_existing":True,"expected_dataset_version":job["expected_dataset_version"]})
    assert response.status_code==409
    assert rows("equipment")==before


def test_cancelled_preview_cannot_replace_data(monkeypatch):
    monkeypatch.setattr("backend.main._api_key","")
    job=prepare("设备编号,采集时间,油温\nA,2020-01-01 00:00:00,310\n")
    assert client.post(f"/api/import/jobs/{job['job_id']}/cancel").status_code==200
    assert client.post(f"/api/import/jobs/{job['job_id']}/commit",json={"replace_existing":True,"expected_dataset_version":job["expected_dataset_version"]}).status_code==409


def test_restore_keeps_current_version_and_rejects_stale_confirmation(monkeypatch):
    monkeypatch.setattr("backend.main._api_key","")
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    original=settings_get("last_sync_at")
    job=prepare("设备编号,采集时间,油温\nNEW-APU,2020-01-01 00:00:00,310\n")
    result=client.post(f"/api/import/jobs/{job['job_id']}/commit",json={"replace_existing":True,"expected_dataset_version":original})
    assert result.status_code==200
    replacement=result.json()["data_version"]
    url=f"/api/data/versions/{original}/restore"
    assert client.post(url,json={"confirmed":True,"expected_dataset_version":original}).status_code==409
    restored=client.post(url,json={"confirmed":True,"expected_dataset_version":replacement})
    assert restored.status_code==200,restored.text
    assert rows("equipment")[0]["equipment_id"]=="CNC-001"
    versions=client.get("/api/data/versions").json()["records"]
    assert any(item["version"]==replacement for item in versions)
