import json

from backend.main import connect,settings_get
from tests.test_api import client,workbook


def test_occupancy_includes_team_members_and_excludes_closed_orders():
    result=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert result.status_code==200,result.text
    with connect() as connection:
        for identifier,status,version in [("TEAM","待审批",settings_get("last_sync_at")),("OLD","执行中","older-version"),("CLOSED","已完成",settings_get("last_sync_at"))]:
            content={"work_order_id":identifier,"equipment_id":"CNC-001","staff_ids":["1","2"],"dataset_version":version,"start_at":"2026-10-20T08:00:00","end_at":"2026-10-20T10:00:00"}
            connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(identifier,"CNC-001",json.dumps(content),status,"2026-10-20"))
    response=client.get("/api/operations/resource-occupancy")
    assert response.status_code==200,response.text
    data=response.json();person=next(item for item in data["staff"] if item["staff_id"]=="1")
    assert {item["work_order_id"] for item in person["bookings"]}=={"TEAM","OLD"}
    assert next(item for item in person["bookings"] if item["work_order_id"]=="OLD")["current_dataset"] is False
    order=data["orders"][0]
    assert {item["work_order_id"] for item in order["related_work_orders"]}=={"TEAM","OLD"}
