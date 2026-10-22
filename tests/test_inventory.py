import json
import pytest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from backend.main import connect,settings_get
from tests.test_api import client,workbook


def seed_stock(count):
    assert client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).status_code==200
    response=client.post("/api/resources/inventory/轴承",json={"on_hand":count,"note":"实盘确认初始库存"})
    assert response.status_code==200,response.text


def seed_order(identifier,quantity=1):
    content={"work_order_id":identifier,"equipment_id":identifier,"dataset_version":settings_get("last_sync_at"),"inventory_scope":settings_get("inventory_scope"),"version":1,"staff_id":"P-"+identifier,"start_at":"2026-10-20 08:00:00","end_at":"2026-10-20 10:00:00","spare_parts":[{"part_name":"轴承","quantity":quantity,"available_quantity":100}]}
    with connect() as connection:
        connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(identifier,identifier,json.dumps(content,ensure_ascii=False),"待审批","2026-10-20"))


def approve(identifier):
    return client.post(f"/api/work-orders/{identifier}/approval",json={"decision":"approve","approver":"设备总管","version":1})


def stock():
    return client.get("/api/resources/inventory").json()["records"][0]


def transition(identifier,action,version,**extra):
    return client.post(f"/api/work-orders/{identifier}/transition",json={"action":action,"version":version,"actor":"维护人员","note":"已核对现场实际情况","request_id":f"{identifier}-{action}-request",**extra})


def finish(identifier):
    assert approve(identifier).status_code==200
    assert transition(identifier,"accept",2).status_code==200
    assert transition(identifier,"start",3).status_code==200
    assert transition(identifier,"finish",4,actual_hours=2,actual_cost_cny=200).status_code==200


def test_concurrent_approvals_cannot_reserve_the_same_last_part():
    seed_stock(1);seed_order("A");seed_order("B")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(approve,["A","B"]))
    assert sorted(response.status_code for response in responses)==[200,409]
    assert stock()["reserved_quantity"]==1
    assert stock()["available_to_allocate"]==0


def test_cancelling_approved_order_releases_stock_for_another_order():
    seed_stock(1);seed_order("A");seed_order("B")
    assert approve("A").status_code==200
    assert approve("B").status_code==409
    assert transition("A","cancel",2).status_code==200
    assert stock()["on_hand"]==1 and stock()["reserved_quantity"]==0
    assert approve("B").status_code==200


def test_actual_consumption_is_confirmed_once_and_unused_reservation_is_released():
    seed_stock(2);seed_order("A",quantity=2);finish("A")
    assert transition("A","verify",5).status_code==422
    actual=[{"part_name":"轴承","quantity":1}]
    verified=transition("A","verify",5,actual_parts=actual)
    assert verified.status_code==200,verified.text
    assert stock()["on_hand"]==1 and stock()["reserved_quantity"]==0
    assert transition("A","verify",5,actual_parts=actual).json()==verified.json()
    assert stock()["on_hand"]==1
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM inventory_movements WHERE work_order_id='A' AND movement_type='consume'").fetchone()[0]==1


def test_cancel_after_start_requires_actual_consumption():
    seed_stock(2);seed_order("A")
    assert approve("A").status_code==200
    assert transition("A","accept",2).status_code==200
    assert transition("A","start",3).status_code==200
    assert transition("A","pause",4).status_code==200
    assert transition("A","cancel",5).status_code==422
    assert transition("A","cancel",5,actual_parts=[{"part_name":"轴承","quantity":1}]).status_code==200
    assert stock()["on_hand"]==1 and stock()["reserved_quantity"]==0


def test_stock_count_preserves_shortage_and_rejects_stale_updates():
    seed_stock(2);seed_order("A",quantity=2)
    assert approve("A").status_code==200
    current=stock()
    counted=client.post("/api/resources/inventory/轴承",json={"on_hand":1,"version":current["version"],"note":"实盘发现缺件"})
    assert counted.status_code==200
    assert counted.json()["record"]["shortfall"]==1
    stale=client.post("/api/resources/inventory/轴承",json={"on_hand":3,"version":current["version"],"note":"旧页面重复盘点"})
    assert stale.status_code==409 and stock()["on_hand"]==1


def test_restoring_sensor_data_does_not_restore_consumed_stock():
    seed_stock(3);original=settings_get("last_sync_at");seed_order("A");finish("A")
    assert transition("A","verify",5,actual_parts=[{"part_name":"轴承","quantity":1}]).status_code==200
    assert stock()["on_hand"]==2
    assert client.post("/api/import",files={"file":("replacement.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).status_code==200
    assert client.get("/api/resources/inventory").json()["records"]==[]
    response=client.post(f"/api/data/versions/{quote(original,safe='')}/restore",json={"confirmed":True,"expected_dataset_version":settings_get("last_sync_at")})
    assert response.status_code==200,response.text
    assert stock()["on_hand"]==2


@pytest.mark.parametrize("strategy",["optimized","fixed_interval","risk_threshold"])
def test_new_plan_subtracts_stock_already_reserved_by_another_order(strategy):
    seed_stock(1);seed_order("A")
    assert approve("A").status_code==200
    with connect() as connection:
        row=connection.execute("SELECT row_index,content FROM records WHERE table_name='maintenance_rules'").fetchone()
        rule=json.loads(row["content"]);rule["spare_parts"]=[{"part_name":"轴承","quantity":1,"available_quantity":1}]
        connection.execute("UPDATE records SET content=? WHERE table_name='maintenance_rules' AND row_index=?",(json.dumps(rule,ensure_ascii=False),row["row_index"]))
    result=client.post("/api/simulate",json={"scenario_id":"S-1","strategy":strategy})
    assert result.status_code==200,result.text
    assert result.json()["selected"]==[]
