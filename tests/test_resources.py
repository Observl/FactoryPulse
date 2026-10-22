from backend.main import settings_get
from tests.test_api import client,workbook


def test_valid_resources_and_invalid_shift():
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    staff={"staff_name":"维修员","skills":["机修"],"available_hours":8,"shift_start":"2026-10-20T08:00:00","shift_end":"2026-10-20T16:00:00"}
    assert client.post("/api/resources/staff/P1",json={**staff,"available_hours":9}).status_code==422
    saved=client.post("/api/resources/staff/P1",json=staff)
    assert saved.status_code==200,saved.text
    assert saved.json()["record"]["skills"]=="机修"
    revision=settings_get("business_revision")
    order={"order_name":"生产批次","equipment_id":"CNC-001","start_at":"2026-10-20T08:00:00","end_at":"2026-10-20T10:00:00","due_at":"2026-10-20T12:00:00"}
    assert client.post("/api/resources/orders/O1",json=order).status_code==200
    assert int(settings_get("business_revision"))==int(revision)+1
    assert client.post("/api/resources/orders/O2",json={**order,"equipment_id":"missing"}).status_code==422
    requirement={"maintenance_hours":2,"maintenance_cost_cny":600,"required_skill":"机修","required_staff_count":1,"window_start":"2026-10-20T10:00:00","window_end":"2026-10-20T16:00:00","spare_parts":[{"part_name":"轴承","quantity":1,"available_quantity":1}]}
    assert client.post("/api/resources/requirements/CNC-001",json=requirement).status_code==200
    assert client.get("/api/resources/requirements").json()["records"][0]["configuration_status"]=="configured"


def test_resource_change_invalidates_pending_schedule():
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert client.post("/api/maintenance-requests",json={"equipment_id":"CNC-001","action":"检查主轴","priority":"中","request_id":"resource-test-request"}).status_code==200
    plan=client.post("/api/schedule/generate",json={"scenario_id":"S-1","start_at":"2026-10-20T08:00:00"})
    assert plan.status_code==200,plan.text
    work=plan.json()["scheduled"][0]
    response=client.post("/api/resources/scenarios/S-1",json={"scenario_name":"新预算","maintenance_budget_cny":100,"available_staff_count":1,"max_downtime_h":8})
    assert response.status_code==200
    approval=client.post(f"/api/work-orders/{work['work_order_id']}/approval",json={"decision":"approve","approver":"总管","version":client.get("/api/work-orders").json()["records"][0]["version"],"accept_assumptions":True})
    assert approval.status_code==409
    assert "资源已更新" in approval.json()["detail"]


def test_blank_name_and_mixed_timezones_produce_validation_results():
    staff={"staff_name":"   ","skills":["机修"],"available_hours":2,"shift_start":"2026-10-20T08:00:00+08:00","shift_end":"2026-10-20T16:00:00"}
    assert client.post("/api/resources/staff/P1",json=staff).status_code==422
    staff["staff_name"]="维修员"
    # Different timezone notation must not cause an unhandled comparison TypeError.
    assert client.post("/api/resources/staff/P1",json=staff).status_code==200
