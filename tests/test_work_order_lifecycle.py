import json

from backend.main import connect, list_work_orders, settings_get
from tests.test_api import client, workbook


def test_lifecycle_concurrency_idempotency_and_verified_history():
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    work_id="WO-LIFECYCLE-TEST"
    with connect() as connection:
        connection.execute("INSERT OR REPLACE INTO work_orders VALUES (?,?,?,?,?)",(work_id,"CNC-001",json.dumps({"work_order_id":work_id,"equipment_id":"CNC-001","version":1,"dataset_version":settings_get("last_sync_at"),"approval_business_revision":settings_get("business_revision","0"),"staff_id":"ST-1","start_at":"2026-10-20 08:00:00","end_at":"2026-10-20 10:00:00"}),"已批准","2026-10-19"))
    def change(action,version,request_id,**extra):
        return client.post(f"/api/work-orders/{work_id}/transition",json={"action":action,"version":version,"actor":"维修员甲","request_id":request_id,"note":"实际维修记录",**extra})
    assert change("finish",1,"invalid-step").status_code==422
    accepted=change("accept",1,"accept-0001")
    assert accepted.status_code==200
    assert change("accept",1,"accept-0001").json()==accepted.json()
    assert change("start",1,"stale-00001").status_code==409
    assert change("start",2,"start-00001").json()["status"]=="执行中"
    assert change("finish",3,"finish-bad1").status_code==422
    assert change("pause",3,"pause-00001").json()["status"]=="已暂停"
    assert change("resume",4,"resume-0001").json()["status"]=="执行中"
    assert change("finish",5,"finish-0001",actual_hours=2.5,actual_cost_cny=600).json()["status"]=="待验收"
    assert change("verify",6,"verify-0001").json()["status"]=="已完成"
    assert change("verify",6,"verify-0001").status_code==200
    with connect() as connection:
        records=[json.loads(row[0]) for row in connection.execute("SELECT content FROM records WHERE table_name='maintenance_history'")]
    assert len([r for r in records if r.get("maintenance_id")==work_id])==1
    assert next(r for r in list_work_orders()["records"] if r["work_order_id"]==work_id)["version"]==7


def test_returned_order_can_be_revised_without_reusing_old_schedule():
    work_id="WO-RETURN-TEST"
    content={"work_order_id":work_id,"equipment_id":"CNC-001","version":1,"start_at":"2026-10-20 08:00:00","end_at":"2026-10-20 10:00:00","staff_id":"P1"}
    with connect() as connection:
        connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(work_id,"CNC-001",json.dumps(content),"待审批","2026-10-19"))
    returned=client.post(f"/api/work-orders/{work_id}/approval",json={"decision":"reject","approver":"设备总管","note":"调整停机窗口","version":1})
    assert returned.json()["status"]=="已退回"
    revised=client.post(f"/api/work-orders/{work_id}/transition",json={"action":"revise","actor":"设备总管","note":"按新的窗口安排油路检查","version":2,"request_id":"revise-request-001"})
    assert revised.json()["status"]=="草稿·待排程"
    record=next(item for item in list_work_orders()["records"] if item["work_order_id"]==work_id)
    assert "start_at" not in record and "staff_id" not in record
    assert record["maintenance_action"]=="按新的窗口安排油路检查"
