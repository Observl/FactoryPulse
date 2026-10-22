import asyncio
import pytest
from backend.agent_registry import validate_arguments, tool_definitions
from backend.agent_config import AgentConfig
from backend.agent import run_agent

@pytest.mark.parametrize("name,args", [
    ("history", {}), ("history", {"equipment_id": 1}),
    ("equipment", {"equipment_id": " "}), ("equipment", {"sql": "DROP TABLE work_orders"}),
    ("draft_constraints", {"scenario_id":"S", "note":"检查", "staff_count": True}),
    ("compare_plans", {"budget": float("nan")}), ("compare_plans", {"budget": -1}),
    ("operations_context", {"category":"accounts"}),
    ("operations_context", {"category":"staff", "limit":51}),
    ("work_order_flow", {}), ("approve_work_order", {}),
])
def test_tool_contract_rejects_unsafe_or_invalid_parameters(name,args):
    with pytest.raises(ValueError): validate_arguments(name,args)

def test_registry_schema_and_permissions():
    tools=tool_definitions(True, ["history"])
    names={tool["function"]["name"] for tool in tools}
    assert {"operations_context", "work_order_flow"} <= names
    assert not names & {"history", "draft_schedule", "draft_constraints", "draft_work_order"}
    assert all(tool["function"]["parameters"]["additionalProperties"] is False for tool in tools)
    with pytest.raises(ValueError): AgentConfig(disabled_tools=["unknown"])
    with pytest.raises(ValueError): AgentConfig(max_rounds=999)

def test_invalid_model_arguments_never_reach_business_dispatch(monkeypatch):
    bodies=[{"choices":[{"message":{"tool_calls":[{"id":"bad", "function":{"name":"history", "arguments":'{"equipment_id":123}'}}]}}]},
            {"choices":[{"message":{"content":"读取失败"}}]}]
    class Response:
        status_code=200
        def json(self): return bodies.pop(0)
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return Response()
    monkeypatch.setattr("backend.agent.httpx.AsyncClient",Client)
    def forbidden(*args): raise AssertionError("无效参数不得到达业务执行")
    result=asyncio.run(run_agent("https://example.org","test","unused","查询设备维修历史",forbidden))
    assert result["trace"][0]["status"]=="error"
    assert "无法判断" in result["answer"]

def test_operational_queries_are_version_scoped_and_paginated():
    from tests.test_api import client, workbook
    from backend.main import agent_dispatch, connect, settings_get
    import json
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    version=settings_get("last_sync_at")
    with connect() as c:
        for identifier,scope in [("CURRENT",version),("ARCHIVED","old-dataset")]:
            item={"work_order_id":identifier,"equipment_id":"CNC-001","dataset_version":scope}
            c.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(identifier,"CNC-001",json.dumps(item),"待审批","2026-10-21"))
    evidence=agent_dispatch("operations_context",{"category":"work_orders","limit":1})
    assert evidence["total"]==1 and evidence["records"][0]["work_order_id"]=="CURRENT"
    assert evidence["data_time"] is None
    assert agent_dispatch("work_order_flow",{"work_order_id":"CURRENT"})["record"]["status"]=="待审批"
    with pytest.raises(ValueError,match="其他数据版本"):
        agent_dispatch("work_order_flow",{"work_order_id":"ARCHIVED"})
    for category in ("staff","orders","inventory","scenarios","requirements"):
        page=agent_dispatch("operations_context",{"category":category,"limit":1})
        assert page["returned"]<=1 and page["data_version"]==version
    with pytest.raises(ValueError,match="不支持"):
        agent_dispatch("operations_context",{"category":"staff","equipment_id":"CNC-001"})
