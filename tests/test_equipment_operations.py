import json

from backend.main import connect,settings_get
from tests.test_api import client,workbook


def test_device_operations_distinguish_versions_and_audit_follows_work_order():
    imported=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert imported.status_code==200,imported.text
    with connect() as connection:
        for identifier,version,equipment in [("CURRENT",settings_get("last_sync_at"),"CNC-001"),("OLD","older-version","CNC-001"),("OTHER","older-version","OTHER-DEVICE")]:
            content={"work_order_id":identifier,"dataset_version":version,"equipment_id":equipment}
            connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(identifier,equipment,json.dumps(content),"执行中","2026-10-20"))
        connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("work_order_transition","OLD",json.dumps({"status":"执行中"}),"2026-10-20"))
    result=client.get("/api/equipment/CNC-001/operations")
    assert result.status_code==200,result.text
    work={item["work_order_id"]:item for item in result.json()["work_orders"]}
    assert set(work)=={"CURRENT","OLD"}
    assert work["CURRENT"]["current_dataset"] is True
    assert work["OLD"]["current_dataset"] is False
    assert all(item["equipment_id"]=="CNC-001" for item in result.json()["orders"])
    events=client.get("/api/audit?entity=CNC-001").json()["records"]
    assert any(event["entity_id"]=="OLD" for event in events)
    assert client.get("/api/equipment/NOT-FOUND/operations").status_code==404
