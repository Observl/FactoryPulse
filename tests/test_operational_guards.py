import json
from datetime import datetime, timedelta, timezone

from backend.main import connect, settings_get
from backend.smart_import import normalize_rows
from tests.test_api import client, workbook


def test_invalid_import_rolls_back_and_missing_labels_stay_unknown():
    rows=[{"id":"A","time":"2020-01-01 00:00:00","v":"0.5"},{"id":"A","time":"not-a-time","v":"nan"}]
    mapping={"id":"equipment_id","time":"timestamp","v":"vibration_g"}
    try: normalize_rows(rows,mapping,"default")
    except ValueError as error: assert "第 3 行" in str(error)
    else: raise AssertionError("invalid timestamp accepted")
    clean=normalize_rows(rows[:1],mapping,"default")
    assert clean[0]["future_failure"] is None
    assert clean[0]["prediction_horizon_hours"]==168


def test_defer_requires_real_time_and_reject_requires_reason():
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    path="/api/alerts/CNC-001/action"
    assert client.post(path,json={"action":"defer"}).status_code==422
    assert client.post(path,json={"action":"reject"}).status_code==422
    assert client.post(path,json={"action":"defer","defer_until":(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}).status_code==200


def test_approval_revalidates_formal_resource_occupancy():
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    version=settings_get("last_sync_at")
    data={"equipment_id":"CNC-001","staff_id":"P1","start_at":"2026-10-20 08:00:00","end_at":"2026-10-20 10:00:00","dataset_version":version,"version":1}
    with connect() as connection:
        for identifier,status in [("GUARD-BOOKED","已批准"),("GUARD-NEW","待审批")]:
            connection.execute("INSERT OR REPLACE INTO work_orders VALUES (?,?,?,?,?)",(identifier,"CNC-001",json.dumps({**data,"work_order_id":identifier}),status,"2026-10-19"))
    response=client.post("/api/work-orders/GUARD-NEW/approval",json={"decision":"approve","approver":"总管","version":1})
    assert response.status_code==409
    assert "冲突" in response.json()["detail"]


def test_keyring_failure_does_not_silently_keep_new_secret(monkeypatch):
    monkeypatch.setattr("backend.main.credential_set",lambda value:False)
    monkeypatch.setattr("backend.main._api_key","")
    result=client.post("/api/developer/settings",json={"model":"deepseek-chat","api_key":"synthetic-key-not-real"})
    assert result.status_code==503
    assert client.get("/api/developer/settings").json()["has_api_key"] is False
