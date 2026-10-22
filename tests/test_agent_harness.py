import asyncio
import json
import sqlite3
import threading
import time
import httpx
import pytest
from fastapi import FastAPI
from backend.agent_harness import install_harness
from backend.agent_store import encode


@pytest.fixture
def harness(tmp_path, monkeypatch):
    from backend import security
    from backend.main import ManagedConnection
    db = tmp_path / "harness.sqlite"
    def connect():
        c = sqlite3.connect(db, factory=ManagedConnection)
        c.row_factory = sqlite3.Row
        return c
    with connect() as c:
        c.execute("CREATE TABLE records (table_name TEXT,row_index INTEGER,content TEXT,PRIMARY KEY(table_name,row_index))")
        c.execute("CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT)")
        c.execute("CREATE TABLE audit_events (event_id INTEGER PRIMARY KEY,event_type TEXT,entity_id TEXT,content TEXT,created_at TEXT)")
        c.execute("INSERT INTO records VALUES ('equipment',0,?)", (encode({"equipment_id":"E1","equipment_name":"旧名称","equipment_type":"CNC"}),))
        c.execute("INSERT INTO settings VALUES ('business_revision','1')")
        c.execute("INSERT INTO settings VALUES ('last_sync_at','v1')")
    user = {"user_id":"u1", "role":"manager"}
    monkeypatch.setattr(security, "principal", lambda: user or None)
    app = FastAPI()
    store = install_harness(app, connect, threading.RLock(), lambda *a: {})
    real_client = httpx.AsyncClient
    def request(method, path, body=None):
        async def run():
            async with real_client(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.request(method, "/api/copilot" + path, json=body)
        return asyncio.run(run())
    return request, user, connect, store


def session(request, tools=None):
    r = request("POST", "/sessions", {"task":"设备名称修改", "success_criteria":"授权后更新数据库并写入审计", "tools": tools if tools is not None else ["equipment","request_change"]})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def change(request, sid):
    return request("POST", f"/sessions/{sid}/permissions", {"kind":"equipment","identifier":"E1","values":{"equipment_name":"新名称","equipment_type":"CNC"},"reason":"核对铭牌"})


def decide(request, sid, p, decision="approve", digest=None):
    return request("POST", f"/sessions/{sid}/permissions/{p['permission_id']}", {"decision":decision,"digest":digest or p["digest"],"reason":"人工已核对"})


def test_permission_transaction_and_idempotency(harness):
    request, user, connect, _ = harness
    sid = session(request)
    p = change(request,sid).json()
    with connect() as c:
        assert json.loads(c.execute("SELECT content FROM records").fetchone()[0])["equipment_name"] == "旧名称"
    assert decide(request,sid,p).json()["status"] == "executed"
    assert decide(request,sid,p).json()["status"] == "executed"
    with connect() as c:
        assert json.loads(c.execute("SELECT content FROM records").fetchone()[0])["equipment_name"] == "新名称"
        assert c.execute("SELECT value FROM settings WHERE key='business_revision'").fetchone()[0] == "2"
        assert c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1


def test_permission_rejects_cross_user_tamper_role_and_stale(harness):
    request, user, connect, _ = harness
    sid = session(request)
    p = change(request,sid).json()
    user["user_id"] = "u2"
    assert request("GET",f"/sessions/{sid}").status_code == 404
    assert decide(request,sid,p).status_code == 404
    user["user_id"] = "u1"
    user["role"] = "viewer"
    assert decide(request,sid,p).status_code == 403
    user["role"] = "manager"
    assert decide(request,sid,p,digest="a"*64).status_code == 403
    with connect() as c: c.execute("UPDATE settings SET value='2' WHERE key='business_revision'")
    assert decide(request,sid,p).status_code == 409
    with connect() as c: assert c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_expired_rejected_and_disabled_requests(harness):
    request, _, connect, _ = harness
    sid = session(request)
    p = change(request,sid).json()
    assert decide(request,sid,p,"reject").json()["status"] == "rejected"
    assert decide(request,sid,p).json()["status"] == "rejected"
    p = change(request,sid).json()
    p["expires_at"] = time.time()-1
    with connect() as c: c.execute("UPDATE agent_permissions SET content=? WHERE id=?", (encode(p),p["permission_id"]))
    assert decide(request,sid,p).status_code == 409
    assert change(request, session(request,["equipment"])).status_code == 403


def test_schema_unknown_fields_and_anonymous(harness):
    request, user, _, _ = harness
    assert request("GET","/harness").json()["schemas"]["DecisionInput"]["additionalProperties"] is False
    assert request("POST","/sessions",{"task":"x","success_criteria":"y","tools":["execute_sql"]}).status_code == 422
    sid = session(request)
    assert request("POST",f"/sessions/{sid}/permissions",{"kind":"equipment","identifier":"E1","values":{"equipment_name":"X","equipment_type":"CNC","status":"running"},"reason":"x"}).status_code == 422
    user.clear()
    assert request("GET","/harness").status_code == 401


def test_memory_consent_isolation_compaction_and_forget(harness):
    request, user, _, store = harness
    sid = session(request)
    assert request("POST",f"/sessions/{sid}/memories",{"text":"优先白班","consent":False}).status_code == 422
    mid = request("POST",f"/sessions/{sid}/memories",{"text":"优先白班","consent":True}).json()["memory_id"]
    for i in range(9): store.save_turn(sid,"u1",f"查询设备{i}",{"answer":"待复核"})
    data = request("GET",f"/sessions/{sid}").json()
    assert len(data["turns"]) == 6 and "非当前证据" in data["summary"]
    assert data["memories"][0]["text"] == "优先白班"
    user["user_id"] = "u2"
    sid2 = session(request)
    assert request("GET",f"/sessions/{sid2}").json()["memories"] == []
    request("POST",f"/sessions/{sid2}/memories/{mid}/forget")
    user["user_id"] = "u1"
    assert len(request("GET",f"/sessions/{sid}").json()["memories"]) == 1
    request("POST",f"/sessions/{sid}/memories/{mid}/forget")
    assert request("GET",f"/sessions/{sid}").json()["memories"] == []


def model_client(monkeypatch, messages, requests=None):
    class Response:
        status_code = 200
        def json(self): return {"choices":[{"message":messages.pop(0)}]}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs):
            if requests is not None:
                import copy
                requests.append(copy.deepcopy(kwargs["json"]))
            return Response()
    monkeypatch.setattr("backend.agent.httpx.AsyncClient",Client)


def call(name="equipment", arguments="{}", identifier="a"):
    return {"id":identifier,"function":{"name":name,"arguments":arguments}}


def test_read_retry_empty_duplicate_and_false_citation(monkeypatch):
    from backend.agent import run_agent
    model_client(monkeypatch,[{"tool_calls":[call(),call(identifier="b")]},{"content":"参见 EVID-fabricated"}])
    attempts = []
    def dispatch(*args):
        attempts.append(args)
        if len(attempts)==1: raise ConnectionError("temporary")
        return {"devices":[],"source":"sqlite"}
    result = asyncio.run(run_agent("https://example.org","model","secret","查询设备",dispatch))
    assert len(attempts)==2
    assert result["trace"][0]["attempts"]==2
    assert result["trace"][0]["empty"] is True
    assert result["trace"][1]["cached"] is True
    assert result["completion_status"]=="incomplete"
    assert "拦截" in result["answer"]


def test_legacy_money_budget_no_longer_blocks_model_call(monkeypatch):
    from backend.agent import run_agent
    from backend.agent_config import AgentConfig
    monkeypatch.setattr("backend.agent.load_config",lambda:AgentConfig(max_run_cost_usd=.000001))
    model_client(monkeypatch,[{"tool_calls":[call()]},{"content":"已读取设备证据。"}])
    result = asyncio.run(run_agent("https://example.org","model","secret","查询设备",lambda *a:{"devices":[{"equipment_id":"E1"}]}))
    assert result["timing"]["model_calls"] == 2
    assert result["budget"]["mode"]=="staged_time"
    assert result["budget"]["run_limit_seconds"]==40
    assert result["budget"]["current_limit_seconds"]==30


def test_real_auth_middleware_allows_viewer_chat_but_blocks_changes():
    from tests.test_api import client
    from tests.test_security import initialize, create_user, login
    admin = initialize()
    create_user(admin,"agentviewer","viewer")
    viewer = login("agentviewer")
    r = client.post("/api/copilot/sessions",headers=viewer,json={"task":"查询设备","success_criteria":"读取证据","tools":["equipment","request_change"]})
    assert r.status_code==200,r.text
    sid = r.json()["session_id"]
    r = client.post(f"/api/copilot/sessions/{sid}/chat",headers=viewer,json={"question":"查询设备"})
    assert r.status_code==200,r.text
    assert r.json()["run_id"]
    assert client.post(f"/api/copilot/sessions/{sid}/permissions",headers=viewer,json={"kind":"equipment","identifier":"CNC-001","values":{"equipment_name":"X","equipment_type":"CNC"},"reason":"x"}).status_code==403
    assert client.get(f"/api/copilot/sessions/{sid}",headers=admin).status_code==404


def test_model_can_request_but_cannot_execute_change(harness,monkeypatch):
    request, _, connect, _ = harness
    from backend import main
    monkeypatch.setattr(main,"settings_get",lambda key: {"ai_base_url":"https://example.org","ai_model":"model"}.get(key,""))
    monkeypatch.setattr(main,"_api_key","synthetic-key")
    async def check(*args): pass
    monkeypatch.setattr(main.address_validation,"check",check)
    args=encode({"kind":"equipment","identifier":"E1","values":{"equipment_name":"新名称","equipment_type":"CNC"},"reason":"铭牌校对"})
    model_client(monkeypatch,[{"tool_calls":[call("request_change",args)]},{"content":"等待用户授权"}])
    sid = session(request)
    r = request("POST",f"/sessions/{sid}/chat",{"question":"修改设备名称"})
    assert r.status_code==200,r.text
    result = r.json()
    assert result["completion_status"]=="waiting_permission"
    assert len(result["permissions"])==1
    with connect() as c:
        assert json.loads(c.execute("SELECT content FROM records").fetchone()[0])["equipment_name"]=="旧名称"
    assert decide(request,sid,result["permissions"][0]).json()["status"]=="executed"


@pytest.mark.parametrize("kind,key,values",[
    ("staff","staff_id",{"staff_name":"维修甲","skills":["机修"],"available_hours":4.0,"shift_start":"2026-10-23T08:00:00","shift_end":"2026-10-23T16:00:00"}),
    ("orders","order_id",{"order_name":"生产甲","equipment_id":"E1","start_at":"2026-10-23T08:00:00","end_at":"2026-10-23T12:00:00","due_at":"2026-10-23T16:00:00"}),
    ("scenarios","scenario_id",{"scenario_name":"白班维护","maintenance_budget_cny":1000.0,"available_staff_count":2,"max_downtime_h":4.0}),
])
def test_resource_updates_use_business_models(harness,kind,key,values):
    request, _, connect, _ = harness
    with connect() as c: c.execute("INSERT INTO records VALUES (?,0,?)",(kind,encode({key:"TARGET"})))
    sid = session(request)
    r = request("POST",f"/sessions/{sid}/permissions",{"kind":kind,"identifier":"TARGET","values":values,"reason":"调整维护资源"})
    assert r.status_code==200,r.text
    assert decide(request,sid,r.json()).json()["status"]=="executed"
    with connect() as c:
        stored = json.loads(c.execute("SELECT content FROM records WHERE table_name=?",(kind,)).fetchone()[0])
    assert stored[key]=="TARGET"
    assert stored.get("staff_name",stored.get("order_name",stored.get("scenario_name"))) in {"维修甲","生产甲","白班维护"}


def test_audit_failure_rolls_back_write_and_permission(harness):
    request, _, connect, _ = harness
    sid = session(request)
    p = change(request,sid).json()
    with connect() as c: c.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError,match="audit unavailable"): decide(request,sid,p)
    with connect() as c:
        assert json.loads(c.execute("SELECT content FROM records").fetchone()[0])["equipment_name"]=="旧名称"
        assert json.loads(c.execute("SELECT content FROM agent_permissions").fetchone()[0])["status"]=="pending"
        assert c.execute("SELECT value FROM settings WHERE key='business_revision'").fetchone()[0]=="1"


def test_complex_question_without_model_does_not_return_irrelevant_ranking(harness):
    request, _, _, _ = harness
    sid=session(request)
    r=request("POST",f"/sessions/{sid}/chat",{"question":"比较设备风险、订单交期、班次和备件约束，给出维护安排并解释取舍"})
    assert r.status_code==200
    assert r.json()["completion_status"]=="incomplete"
    assert r.json()["trace"]==[]
    assert "未连接 AI 模型" in r.json()["answer"]


def test_complex_analysis_has_more_than_four_rounds_and_preserves_long_answer(monkeypatch):
    from backend.agent import run_agent
    messages=[{"tool_calls":[call("history",encode({"equipment_id":f"E{i}"}),str(i))]} for i in range(6)]
    long_answer="设备维护方案。"+"已根据维修历史复核，人员与交期约束仍需进一步校验。"*60
    messages.append({"content":long_answer})
    model_client(monkeypatch,messages)
    result=asyncio.run(run_agent("https://example.org","model","unused","比较多台设备维修历史后说明维护方案",lambda *a:{"source":"SQLite","records":[{"event":"inspection"}]}))
    assert result["completion_status"]=="complete"
    assert result["timing"]["model_calls"]==7
    assert len(result["trace"])==6
    assert len(result["answer"])>900


def test_reasoning_provider_tool_field_is_preserved_but_not_exposed(monkeypatch):
    from backend.agent import run_agent
    requests=[]
    model_client(monkeypatch,[{"reasoning_content":"synthetic-private-provider-field","tool_calls":[call()]},{"content":"设备证据已读取，待复核。"}],requests)
    result=asyncio.run(run_agent("https://example.org","model","unused","查询设备",lambda *a:{"devices":[],"source":"SQLite"}))
    assert any(m.get("reasoning_content")=="synthetic-private-provider-field" for m in requests[1]["messages"])
    assert "synthetic-private-provider-field" not in encode(result)


def test_context_compaction_keeps_task_and_newest_evidence(monkeypatch):
    from backend.agent import run_agent
    from backend.agent_config import AgentConfig
    monkeypatch.setattr("backend.agent.load_config",lambda:AgentConfig(max_input_tokens=12000))
    requests=[]
    messages=[{"tool_calls":[call("history",encode({"equipment_id":f"E{i}"}),str(i))]} for i in range(4)]
    messages.append({"content":"设备维护历史已读取，需现场复核。"})
    model_client(monkeypatch,messages,requests)
    result=asyncio.run(run_agent("https://example.org","model","unused","分析设备维修历史",lambda *a:{"source":"SQLite","observations":"synthetic-data "*220},enabled_tools=["history"],session_context="DO_NOT_DROP_TASK"))
    assert result["context_compactions"]>0
    assert result["completion_status"]=="complete"
    assert all("DO_NOT_DROP_TASK" in encode(r["messages"]) for r in requests)


def test_round_of_only_cached_reads_forces_final_answer_without_extra_credit(monkeypatch):
    from backend.agent import run_agent
    requests=[]
    model_client(monkeypatch,[{"tool_calls":[call()]},{"tool_calls":[call(identifier="repeat")]},{"content":"设备证据已复核，需进一步核对维修安排。"}],requests)
    result=asyncio.run(run_agent("https://example.org","model","unused","查询设备",lambda *a:{"devices":[{"equipment_id":"E1"}]}))
    assert requests[-1]["tool_choice"]=="none"
    assert result["budget"]["useful_progress_count"]==1
    assert result["budget"]["run_limit_seconds"]==40
    assert result["budget"]["current_limit_seconds"]==30
