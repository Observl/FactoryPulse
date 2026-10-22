import asyncio
import json

from backend.agent import run_agent
from backend.main import agent_dispatch
from tests.test_api import client, workbook


def test_agent_draft_requires_explicit_confirmation_and_is_idempotent():
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    before=len(client.get("/api/work-orders").json()["records"])
    proposal=agent_dispatch("draft_work_order",{"equipment_id":"CNC-001","note":"检查润滑与轴承"})["proposal"]
    assert len(client.get("/api/work-orders").json()["records"])==before
    path=f"/api/copilot/proposals/{proposal['proposal_id']}/confirm"
    assert client.post(path,json={"confirmed":False}).status_code==422
    result=client.post(path,json={"confirmed":True})
    assert result.status_code==200
    assert client.post(path,json={"confirmed":True}).json()==result.json()
    assert len(client.get("/api/work-orders").json()["records"])==before+1


def test_agent_calls_controlled_tools_before_answer(monkeypatch):
    responses=[{"choices":[{"message":{"content":None,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"evaluation","arguments":"{}"}}]}}]}, {"choices":[{"message":{"content":"评估证据不足，需要更多独立故障事件。"}}]}]
    class FakeResponse:
        status_code=200
        def __init__(self,body): self.body=body
        def json(self): return self.body
    class FakeClient:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return FakeResponse(responses.pop(0))
    monkeypatch.setattr("backend.agent.httpx.AsyncClient",FakeClient)
    calls=[]
    def dispatch(name,arguments):
        calls.append(name)
        return {"source":"model/evaluation","data_time":"2020-07-01","events":1}
    result=asyncio.run(run_agent("https://example.org","test","fake","查询模型评估",dispatch))
    assert calls==["evaluation"]
    assert result["trace"][0]["source"]=="model/evaluation"
    assert "不足" in result["answer"]


def test_agent_unavailable_falls_back_to_local_evidence(monkeypatch):
    monkeypatch.setattr("backend.main._api_key","")
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    result=client.post("/api/copilot/chat",json={"question":"本周设备风险"})
    assert result.status_code==200
    assert result.json()["mode"]=="local_fallback"
    assert result.json()["evidence"]["devices"]


def test_constraint_proposal_is_explicit_versioned_and_idempotent():
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    original=client.get("/api/records/scenarios").json()["records"]
    proposal=agent_dispatch("draft_constraints",{"scenario_id":"S-1","budget":1200,"staff_count":1,"note":"本轮只有一名维修人员可用"})["proposal"]
    assert client.get("/api/records/scenarios").json()["records"]==original
    path=f"/api/copilot/proposals/{proposal['proposal_id']}/confirm"
    assert client.post(path,json={"confirmed":False}).status_code==422
    result=client.post(path,json={"confirmed":True})
    assert result.status_code==200,result.text
    assert client.post(path,json={"confirmed":True}).json()==result.json()
    scenarios=client.get("/api/records/scenarios").json()["records"]
    assert len(scenarios)==len(original)+1
    saved=next(item for item in scenarios if item["scenario_id"]==result.json()["scenario_id"])
    assert saved["maintenance_budget_cny"]==1200 and saved["available_staff_count"]==1
    assert next(item for item in scenarios if item["scenario_id"]=="S-1")==original[0]
    assert client.get("/api/work-orders").json()["records"]==[]


def test_stale_constraint_proposal_cannot_replace_updated_resources():
    from backend.main import connect,settings_set_many
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    proposal=agent_dispatch("draft_constraints",{"scenario_id":"S-1","budget":500,"note":"调整预算"})["proposal"]
    with connect() as connection: settings_set_many(connection,{"business_revision":99})
    result=client.post(f"/api/copilot/proposals/{proposal['proposal_id']}/confirm",json={"confirmed":True})
    assert result.status_code==409
    assert len(client.get("/api/records/scenarios").json()["records"])==1


def prepare_schedule_proposal():
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    result=client.post("/api/maintenance-requests",json={"equipment_id":"CNC-001","action":"检查轴承","priority":"中","request_id":"agent-schedule-request"})
    assert result.status_code==200,result.text
    return agent_dispatch("draft_schedule",{"scenario_id":"S-1","start_at":"2026-10-20T08:00:00"})["proposal"]


def test_schedule_preview_requires_confirmation_and_preserves_displayed_assignment():
    proposal=prepare_schedule_proposal()
    assert proposal["scheduled"]
    assert client.get("/api/work-orders").json()["records"][0]["status"]=="草稿·待排程"
    path=f"/api/copilot/proposals/{proposal['proposal_id']}/confirm"
    assert client.post(path,json={"confirmed":False}).status_code==422
    result=client.post(path,json={"confirmed":True})
    assert result.status_code==200,result.text
    assert client.post(path,json={"confirmed":True}).json()==result.json()
    saved=result.json()["scheduled"][0];preview=proposal["scheduled"][0]
    for key in ("equipment_id","staff_ids","start_at","end_at"): assert saved.get(key)==preview.get(key)
    orders=client.get("/api/work-orders").json()["records"]
    assert len(orders)==1 and orders[0]["status"]=="待审批"


def test_schedule_preview_rejects_changed_work_order_occupancy():
    from backend.main import connect
    proposal=prepare_schedule_proposal()
    with connect() as connection:
        connection.execute("UPDATE work_orders SET updated_at='changed-after-preview'")
    result=client.post(f"/api/copilot/proposals/{proposal['proposal_id']}/confirm",json={"confirmed":True})
    assert result.status_code==409,result.text
    assert client.get("/api/work-orders").json()["records"][0]["status"]=="草稿·待排程"


def test_agent_cancel_and_deadline_do_not_dispatch_business_tools(monkeypatch):
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): raise AssertionError("取消或超时后不能发起模型调用")
    monkeypatch.setattr("backend.agent.httpx.AsyncClient",Client)
    async def disconnected(): return True
    def forbidden(*args): raise AssertionError("不能执行工具")
    cancelled=asyncio.run(run_agent("https://example.org","test","fake","查询设备",forbidden,should_stop=disconnected))
    assert "取消" in cancelled["answer"] and cancelled["proposals"]==[]
    expired=asyncio.run(run_agent("https://example.org","test","fake","查询设备",forbidden,total_timeout=0))
    assert "时间上限" in expired["answer"] and expired["trace"]==[]


def test_disconnection_after_model_reply_prevents_new_tool_execution(monkeypatch):
    class Response:
        status_code=200
        def json(self): return {"choices":[{"message":{"content":None,"tool_calls":[{"id":"tool1","function":{"name":"draft_schedule","arguments":"{}"}}]}}]}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return Response()
    monkeypatch.setattr("backend.agent.httpx.AsyncClient",Client)
    checks=[]
    async def disconnected(): checks.append(True);return len(checks)>1
    def forbidden(*args): raise AssertionError("断开后不能继续生成草稿")
    result=asyncio.run(run_agent("https://example.org","test","fake","生成排程草稿",forbidden,should_stop=disconnected))
    assert "取消" in result["answer"] and result["proposals"]==[]
