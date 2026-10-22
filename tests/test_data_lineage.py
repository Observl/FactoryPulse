import json
from urllib.parse import quote

from backend.main import connect,rows,settings_get
from tests.test_api import client,workbook


def import_data():
    response=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code==200,response.text
    return settings_get("last_sync_at")


def test_late_old_work_order_completion_stays_with_its_source_dataset():
    original=import_data()
    work_id="OLD-SOURCE-WORK"
    content={"work_order_id":work_id,"equipment_id":"CNC-001","dataset_version":original,"version":1,"repair_result":"完成密封检查","actual_hours":2,"actual_cost_cny":100}
    with connect() as connection:
        connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(work_id,"CNC-001",json.dumps(content),"待验收","2026-10-20"))
    replacement=import_data()
    verify=client.post(f"/api/work-orders/{work_id}/transition",json={"action":"verify","actor":"总管","version":1,"request_id":"late-verify-0001","note":"验收通过"})
    assert verify.status_code==200,verify.text
    assert not any(row.get("maintenance_id")==work_id for row in rows("maintenance_history"))
    current=client.get("/api/equipment/CNC-001/history").json()["maintenance"]
    assert not any(row.get("maintenance_id")==work_id for row in current)
    restore=client.post(f"/api/data/versions/{quote(original,safe='')}/restore",json={"confirmed":True,"expected_dataset_version":replacement})
    assert restore.status_code==200,restore.text
    restored=client.get("/api/equipment/CNC-001/history").json()["maintenance"]
    assert len([row for row in restored if row.get("maintenance_id")==work_id])==1
    import_data()
    unrelated=client.get("/api/equipment/CNC-001/history").json()["maintenance"]
    assert not any(row.get("maintenance_id")==work_id for row in unrelated)


def test_reimported_equipment_does_not_inherit_old_alert_decision():
    original=import_data()
    response=client.post("/api/alerts/CNC-001/action",json={"action":"reject","note":"旧版本现场复核"})
    assert response.status_code==200
    assert client.get("/api/overview").json()["devices"][0]["alert_status"]=="已驳回"
    current=import_data()
    assert current!=original
    assert client.get("/api/overview").json()["devices"][0]["alert_status"]=="待确认"
