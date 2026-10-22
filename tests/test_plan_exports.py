import csv
import io
import json

from backend.main import connect
from tests.test_api import client,workbook
from tests.test_staged_import import prepare


def csv_rows(response):
    assert response.status_code==200,response.text
    return list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))


def test_export_matches_original_snapshot_and_keeps_names_as_text():
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    with connect() as connection:
        row=connection.execute("SELECT row_index,content FROM records WHERE table_name='equipment'").fetchone()
        record=json.loads(row["content"]);record["equipment_name"]="=SUM(1+1)"
        connection.execute("UPDATE records SET content=? WHERE table_name='equipment' AND row_index=?",(json.dumps(record),row["row_index"]))
    result=client.post("/api/strategies/compare",json={"scenario_id":"S-1","executable":False}).json()
    plan=next(item for item in result["strategies"] if item["strategy"]=="optimized")
    assert plan["selected"]
    assert client.post("/api/resources/scenarios/S-1",json={"scenario_name":"预算改变","maintenance_budget_cny":0,"available_staff_count":1,"max_downtime_h":8}).status_code==200
    exported=csv_rows(client.get("/api/export/maintenance.csv?plan_id="+plan["plan_id"]))
    assert len(exported)==len(plan["selected"])
    assert exported[0]["方案编号"]==plan["plan_id"]
    assert float(exported[0]["维护成本(元)"])==plan["selected"][0]["cost"]
    assert exported[0]["设备名称"]=="'=SUM(1+1)"
    assert float(exported[0]["风险评分(0–100分，非概率)"])==80
    assert exported[0]["情景避免损失下限(元)"]=="未评估"


def test_unknown_model_evidence_does_not_export_as_zero_risk():
    job=prepare("设备编号,采集时间,油温\nA,2020-01-01 00:00:00,310\n")
    assert job["status"]=="ready"
    assert client.post(f"/api/import/jobs/{job['job_id']}/commit",json={"replace_existing":True,"expected_dataset_version":job["expected_dataset_version"]}).status_code==200
    rule={"maintenance_hours":2,"maintenance_cost_cny":200,"required_skill":"机修","required_staff_count":1,"window_start":"2026-10-20T08:00:00","window_end":"2026-10-20T16:00:00"}
    assert client.post("/api/resources/requirements/A",json=rule).status_code==200
    assert client.post("/api/resources/scenarios/S",json={"scenario_name":"人工检查","maintenance_budget_cny":1000,"available_staff_count":1,"max_downtime_h":8}).status_code==200
    assert client.post("/api/maintenance-requests",json={"equipment_id":"A","action":"现场核对油路","priority":"高","request_id":"manual-export-request"}).status_code==200
    plans=client.post("/api/strategies/compare",json={"scenario_id":"S","executable":False}).json()["strategies"]
    plan=next(item for item in plans if item["strategy"]=="optimized")
    exported=csv_rows(client.get("/api/export/maintenance.csv?plan_id="+plan["plan_id"]))
    assert exported[0]["风险评分(0–100分，非概率)"]=="未评估"
    assert exported[0]["优先级依据"]=="人工确认的维护需求"
