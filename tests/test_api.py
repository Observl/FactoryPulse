import io
from openpyxl import Workbook
from fastapi.testclient import TestClient
from backend.main import app, TABLES

client=TestClient(app)
def workbook():
    w=Workbook();w.remove(w.active)
    for table,(sheet,required) in TABLES.items():
        s=w.create_sheet(sheet)
        s.append(required)
        record={name: "x" for name in required}
        record.update({"equipment_id":"CNC-001","equipment_name":"测试数控机床","reading_id":"R-1","timestamp":"2026-10-15 08:00:00","scenario_id":"S-1","risk_score":0.8,"maintenance_budget_cny":2000,"risk_threshold":0.65,"available_staff_count":2,"max_downtime_h":8,"inspection_cost_cny":100,"repair_cost_cny":500,"inspection_duration_h":1,"repair_duration_h":2,"required_staff_count":1,"assumed_failure_loss_cny":5000,"staff_id":"ST-1","available_hours":8,"order_id":"O-1","maintenance_id":"M-1","rotational_speed_rpm":1300,"torque_nm":25,"air_temperature_k":298,"process_temperature_k":310,"tool_wear_min":80})
        s.append([record[k] for k in required])
    b=io.BytesIO();w.save(b);return b.getvalue()
def test_health():
    assert client.get("/api/health").status_code==200
def test_import_and_simulate():
    r=client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code==200,r.text
    assert r.json()["counts"]["equipment"]==1
    r=client.get("/api/overview")
    assert r.status_code==200
    assert r.json()["metrics"]["total"]==1
    assert r.json()["devices"][0]["risk_score"]==.8
    r=client.post("/api/simulate",json={"scenario_id":"S-1","strategy":"optimized"})
    assert r.status_code==200,r.text
    assert r.json()["summary"]["maintenance_cost"]<=2000
    assert r.json()["summary"]["maintenance_hours"]<=8
def test_reject_non_xlsx():
    r=client.post("/api/import",files={"file":("bad.txt",b"hello","text/plain")})
    assert r.status_code==400
def test_developer_settings_do_not_expose_key(monkeypatch):
    monkeypatch.setattr('backend.main.require_public_https', lambda value: None)
    r=client.post("/api/developer/settings",json={"provider":"custom","base_url":"https://example.org/v1","model":"example","api_key":"synthetic-test-secret"})
    assert r.status_code==200
    assert "synthetic-test-secret" not in r.text
    got=client.get("/api/developer/settings")
    assert got.json()["has_api_key"] is True
    assert "synthetic-test-secret" not in got.text

def test_all_strategy_comparison_and_csv():
    uploaded=client.post("/api/import", files={"file":("test.xlsx", workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert uploaded.status_code==200,uploaded.text
    response=client.get("/api/strategies/compare?scenario_id=S-1")
    assert response.status_code==200,response.text
    results=response.json()["strategies"]
    assert {x["strategy"] for x in results}=={"fixed_interval","risk_threshold","optimized"}
    assert all(x["summary"]["maintenance_cost"]<=2000 for x in results)
    assert all(x["summary"]["maintenance_hours"]<=8 for x in results)
    csv_result=client.get("/api/export/maintenance.csv?scenario_id=S-1")
    assert csv_result.status_code==200
    assert "text/csv" in csv_result.headers["content-type"]
    assert "设备ID" in csv_result.text

def test_invalid_risk_is_rejected():
    from openpyxl import load_workbook
    b=io.BytesIO(workbook()); wb=load_workbook(b)
    ws=wb["08_风险评分演示"]
    risk_col=list(next(ws.values)).index("risk_score")+1
    ws.cell(row=2,column=risk_col).value=1.5
    bad=io.BytesIO();wb.save(bad)
    res=client.post("/api/import",files={"file":("invalid.xlsx",bad.getvalue(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert res.status_code==422
    assert "风险评分" in res.text

def test_reject_local_api_destination():
    response=client.post("/api/developer/settings",json={"provider":"custom","base_url":"https://127.0.0.1/v1","model":"demo"})
    assert response.status_code==422
