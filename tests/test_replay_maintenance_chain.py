import json

from backend.main import connect,settings_get
from tests.test_api import client,workbook


def setup_evidence():
    result=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert result.status_code==200,result.text
    point={"equipment_id":"CNC-001","reading_id":"R-1","timestamp":"2026-10-15T08:00:00","score":.7,"alert":True}
    with connect() as connection:
        connection.execute("INSERT INTO prediction_runs VALUES (?,?,?,?,?)",("RUN-CHAIN",settings_get("last_sync_at"),"test-frozen-model",json.dumps({"replay":[point]}),"2026-10-20"))
    return {"equipment_id":"CNC-001","action":"依据历史振动记录检查轴承","priority":"中","request_id":"replay-chain-request","prediction_run_id":"RUN-CHAIN","evidence_reading_id":"R-1"}


def test_historical_reference_survives_schedule_execution_and_verification():
    payload=setup_evidence()
    requested=client.post("/api/maintenance-requests",json=payload)
    assert requested.status_code==200,requested.text
    work_id=requested.json()["work_order_id"]
    assert client.post("/api/maintenance-requests",json=payload).json()==requested.json()
    schedule=client.post("/api/schedule/generate",json={"scenario_id":"S-1","start_at":"2026-10-20T08:00:00","request_id":"replay-chain-schedule"})
    assert schedule.status_code==200,schedule.text
    order=client.get("/api/work-orders").json()["records"][0]
    assert order["source_evidence"]["reading_id"]=="R-1"
    assert order["source_evidence"]["model_version"]=="test-frozen-model"
    approval=client.post(f"/api/work-orders/{work_id}/approval",json={"decision":"approve","approver":"测试总管","accept_assumptions":True,"version":order["version"]})
    assert approval.status_code==200,approval.text
    version=approval.json()["version"]
    for action,extra in [("accept",{}),("start",{}),("finish",{"actual_hours":2,"actual_cost_cny":600}),("verify",{})]:
        result=client.post(f"/api/work-orders/{work_id}/transition",json={"action":action,"actor":"测试人员","note":"隔离测试维修结果","version":version,"request_id":"replay-chain-"+action,**extra})
        assert result.status_code==200,result.text
        version=result.json()["version"]
    with connect() as connection:
        record=json.loads(connection.execute("SELECT content FROM maintenance_events WHERE work_order_id=?",(work_id,)).fetchone()[0])
    assert record["source_evidence"]["run_id"]=="RUN-CHAIN"
    assert record["source_evidence"]["kind"]=="historical_replay_manual_request"


def test_wrong_record_and_stale_evidence_are_rejected_without_creating_work():
    payload=setup_evidence()
    assert client.post("/api/maintenance-requests",json={**payload,"evidence_reading_id":"wrong"}).status_code==422
    with connect() as connection:
        connection.execute("UPDATE prediction_runs SET dataset_version='older-version' WHERE run_id='RUN-CHAIN'")
    assert client.post("/api/maintenance-requests",json=payload).status_code==409
    assert client.get("/api/work-orders").json()["records"]==[]
