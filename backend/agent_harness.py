"""Authenticated harness API. The model can request changes, never approve them."""
import json
import time
import uuid
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from . import security
from .agent_store import AgentStore, encode
from .agent_registry import REGISTRY, tool_definitions
from .resources import StaffInput, OrderInput, ScenarioInput


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionInput(Contract):
    task: str = Field(min_length=1, max_length=1000)
    success_criteria: str = Field(min_length=1, max_length=1000)
    tools: list[str] = Field(default_factory=lambda: list(REGISTRY), max_length=30)


class TurnInput(Contract):
    question: str = Field(min_length=1, max_length=1000)


class ChangeInput(Contract):
    kind: Literal["equipment", "staff", "orders", "scenarios"]
    identifier: str = Field(min_length=1, max_length=100)
    values: dict
    reason: str = Field(min_length=1, max_length=500)


class DecisionInput(Contract):
    decision: Literal["approve", "reject"]
    digest: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class MemoryInput(Contract):
    text: str = Field(min_length=1, max_length=1000)
    consent: Literal[True]


class EquipmentInput(Contract):
    equipment_name: str = Field(min_length=1, max_length=100)
    equipment_type: str = Field(min_length=1, max_length=100)


MODELS = {"equipment": EquipmentInput, "staff": StaffInput, "orders": OrderInput, "scenarios": ScenarioInput}
KEYS = {"equipment": "equipment_id", "staff": "staff_id", "orders": "order_id", "scenarios": "scenario_id"}


def install_harness(app, connect, lock, dispatch):
    store = AgentStore(connect)
    active = set()

    def actor(write=False):
        user = security.principal()
        if not user: raise HTTPException(401, "Agent 需要登录后的明确用户")
        if write and user["role"] not in {"developer", "admin"}: raise HTTPException(403, "当前账号无变更权限")
        return user["user_id"]

    def revision(c):
        return dict(c.execute("SELECT key,value FROM settings WHERE key IN ('last_sync_at','business_revision')").fetchall())

    def record(c, kind, identifier):
        row = c.execute("SELECT row_index,content FROM records WHERE table_name=? AND json_extract(content,?)=?", (kind, "$." + KEYS[kind], identifier)).fetchone()
        if not row: raise HTTPException(404, "目标记录不存在；请先在业务页面创建")
        return row["row_index"], json.loads(row["content"])

    def normalize(change):
        model = MODELS[change.kind]
        if set(change.values) - set(model.model_fields): raise HTTPException(422, "变更含未许可字段")
        try: values = model.model_validate(change.values).model_dump(mode="json")
        except ValueError: raise HTTPException(422, "字段、班次或生产时间校验失败")
        if change.kind == "staff": values["skills"] = ",".join(v.strip() for v in values["skills"])
        return values

    def propose(sid, change):
        owner = actor(True)
        session = store.session(sid, owner)
        if "request_change" not in session["tools"]: raise HTTPException(403, "本会话未启用业务变更工具")
        from .agent_config import load_config
        if "request_change" in load_config().disabled_tools: raise HTTPException(403, "管理员已禁用业务变更工具")
        values = normalize(change)
        with lock, connect() as c:
            _, before = record(c, change.kind, change.identifier)
            state = revision(c)
        return store.request(sid, dict(owner=owner, kind=change.kind, identifier=change.identifier,
                                      before=before, after={**before, **values}, reason=change.reason, revision=state))

    @app.get("/api/copilot/harness")
    def manifest():
        actor()
        from .agent_config import load_config
        config = load_config()
        read_only = security.principal()["role"] not in {"developer", "admin"}
        return {"tools": tool_definitions(read_only, config.disabled_tools), "config": config.model_dump(),
                "schemas": {m.__name__: m.model_json_schema() for m in (SessionInput, TurnInput, ChangeInput, DecisionInput, MemoryInput, EquipmentInput, StaffInput, OrderInput, ScenarioInput)},
                "skills": ["risk-review", "maintenance-planning", "change-control"],
                "multi_agent": "single_orchestrator; specialist skills share one permission gate"}

    @app.post("/api/copilot/sessions")
    def create(payload: SessionInput):
        owner = actor()
        if set(payload.tools) - REGISTRY.keys(): raise HTTPException(422, "未知工具")
        return store.create(owner, payload.task, payload.success_criteria, list(dict.fromkeys(payload.tools)))

    @app.get("/api/copilot/sessions/{sid}")
    def get(sid: str):
        owner = actor()
        session = store.session(sid, owner)
        with connect() as c:
            permissions = [{"permission_id": r["id"], **json.loads(r["content"])} for r in c.execute("SELECT * FROM agent_permissions WHERE session_id=?", (sid,))]
            runs = [{"run_id": r["id"], **json.loads(r["content"])} for r in c.execute("SELECT * FROM agent_runs WHERE session_id=? ORDER BY rowid DESC LIMIT 20", (sid,))]
            memories = [{"memory_id": r["id"], **json.loads(r["content"])} for r in c.execute("SELECT * FROM agent_memory WHERE owner=? ORDER BY rowid DESC LIMIT 20", (owner,))]
        return {"session_id": sid, **session, "permissions": permissions, "runs": runs, "memories": memories}

    @app.post("/api/copilot/sessions/{sid}/permissions")
    def request_change(sid: str, payload: ChangeInput):
        return propose(sid, payload)

    @app.post("/api/copilot/sessions/{sid}/permissions/{pid}")
    def decide(sid: str, pid: str, payload: DecisionInput):
        owner = actor(True)
        store.session(sid, owner)
        # Permission receipt, business write, revision and audit commit atomically.
        with lock, connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT content FROM agent_permissions WHERE id=? AND session_id=?", (pid, sid)).fetchone()
            if not row: raise HTTPException(404, "权限请求不存在")
            p = json.loads(row[0])
            if p["owner"] != owner or p["digest"] != payload.digest: raise HTTPException(403, "权限请求不匹配")
            if p["status"] != "pending": return p
            if p["expires_at"] < time.time(): raise HTTPException(409, "授权已过期，请重新申请")
            if payload.decision == "approve":
                from .agent_config import load_config
                if "request_change" in load_config().disabled_tools: raise HTTPException(403, "管理员已禁用变更工具")
                if revision(c) != p["revision"]: raise HTTPException(409, "数据已变化，请重新查询并申请授权")
                index, before = record(c, p["kind"], p["identifier"])
                if before != p["before"]: raise HTTPException(409, "目标已变化，请重新申请")
                if p["kind"] == "orders": record(c, "equipment", p["after"]["equipment_id"])
                c.execute("UPDATE records SET content=? WHERE table_name=? AND row_index=?", (encode(p["after"]), p["kind"], index))
                rev = str(int(p["revision"].get("business_revision", "0")) + 1)
                c.execute("INSERT OR REPLACE INTO settings VALUES ('business_revision',?)", (rev,))
                p["status"] = "executed"
            else: p["status"] = "rejected"
            p.update(decided_by=owner, decision_reason=payload.reason, decided_at=time.time())
            c.execute("UPDATE agent_permissions SET content=? WHERE id=?", (encode(p), pid))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,datetime('now'))", ("agent_permission_" + p["status"], p["identifier"], encode(p)))
        return p

    @app.post("/api/copilot/sessions/{sid}/memories")
    def remember(sid: str, payload: MemoryInput):
        owner = actor()
        store.session(sid, owner)
        mid = uuid.uuid4().hex
        with connect() as c:
            if c.execute("SELECT COUNT(*) FROM agent_memory WHERE owner=?", (owner,)).fetchone()[0] >= 50: raise HTTPException(409, "长期记忆已达50条，请先删除旧记忆")
            c.execute("INSERT INTO agent_memory VALUES (?,?,?)", (mid, owner, encode({"text": payload.text, "created_at": time.time()})))
        return {"memory_id": mid}

    @app.post("/api/copilot/sessions/{sid}/memories/{mid}/forget")
    def forget(sid: str, mid: str):
        owner = actor()
        store.session(sid, owner)
        with connect() as c: c.execute("DELETE FROM agent_memory WHERE id=? AND owner=?", (mid, owner))
        return {"success": True}

    @app.post("/api/copilot/sessions/{sid}/chat")
    async def turn(sid: str, payload: TurnInput, request: Request):
        owner = actor()
        session = store.session(sid, owner)
        if sid in active: raise HTTPException(409, "会话已有运行中的任务")
        active.add(sid)
        rid = store.run(sid, {"status": "running", "started_at": time.time(), "owner": owner})
        permissions = []
        try:
            from .agent import run_agent
            from .agent_config import load_config
            from .main import settings_get, _api_key, address_validation, require_public_https
            base, model = settings_get("ai_base_url"), settings_get("ai_model")
            if not base or not model or not _api_key:
                from .agent_fast import quick_tool, evidence_answer
                name = quick_tool(payload.question)
                if name and name in session["tools"] and name not in load_config().disabled_tools and not REGISTRY[name][2]:
                    import asyncio
                    evidence = await asyncio.wait_for(asyncio.to_thread(dispatch, name, {}), timeout=load_config().tool_timeout_seconds)
                    result = {**evidence_answer(name,evidence), "completion_status": "complete", "mode": "local_fallback"}
                    result["answer"] = "当前未连接 AI 模型，以下仅为本地查询结果。\n\n" + result["answer"]
                else:
                    result = {"answer": "当前未连接 AI 模型，无法完成此问题的多步骤分析。请先在系统设置保存密钥并测试连接；当前会话已保存。", "completion_status": "incomplete", "mode": "unavailable", "trace": [], "proposals": []}
            else:
                await address_validation.check(base, require_public_https)
                def controlled(name, arguments):
                    if name == "request_change":
                        p = propose(sid, ChangeInput.model_validate(arguments))
                        permissions.append(p)
                        return {"source": "permission_gate", "permission_request": p, "message": "等待用户明确授权，尚未执行"}
                    return dispatch(name, arguments)
                with connect() as c:
                    memory = [json.loads(r[0])["text"] for r in c.execute("SELECT content FROM agent_memory WHERE owner=? ORDER BY rowid DESC LIMIT 10", (owner,))]
                from pathlib import Path
                skill_root = Path(__file__).resolve().parent.parent / "skills"
                skills = {name: (skill_root / name / "SKILL.md").read_text(encoding="utf-8") for name in ("risk-review", "maintenance-planning", "change-control")}
                context = encode({"task": session["task"], "success_criteria": session["success_criteria"], "summary": session["summary"], "turns": session["turns"], "preferences_untrusted": memory, "workflow_guidance": skills,
                                  "change_field_schemas": {name: cls.model_json_schema() for name, cls in MODELS.items()}})
                result = await run_agent(base, model, _api_key, payload.question, controlled,
                    read_only=security.principal()["role"] not in {"developer", "admin"}, should_stop=request.is_disconnected,
                    enabled_tools=session["tools"], session_context=context,
                    on_progress=lambda budget, trace:store.run(sid,{"status":"running","owner":owner,"budget":budget,"trace":trace},rid))
            result.update(run_id=rid, session_id=sid, permissions=permissions)
            if permissions:
                result["completion_status"] = "waiting_permission"
                result["answer"] = "已准备具体变更，等待您逐项核对并授权。尚未修改业务数据；请查看权限请求中的变更前后值。"
            store.save_turn(sid, owner, payload.question, result)
            store.run(sid, {"status": result.get("completion_status", "incomplete"), "result": result, "finished_at": time.time()}, rid)
            return result
        except Exception as exc:
            store.run(sid, {"status": "failed", "error_type": type(exc).__name__, "finished_at": time.time()}, rid)
            if isinstance(exc, HTTPException): raise
            raise HTTPException(502, "运行失败；请查看运行记录，未授权变更不会执行") from None
        finally: active.discard(sid)

    return store
