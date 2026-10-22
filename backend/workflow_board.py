"""Version-scoped work queues, reversible lifecycle actions and validated timeline edits."""
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from . import inventory, security


class ManageInput(BaseModel):
    action: str
    version: int = Field(ge=1)
    request_id: str = Field(min_length=8, max_length=100)
    note: str = Field(min_length=2, max_length=1000)


class TimelineInput(BaseModel):
    version: int = Field(ge=1)
    staff_ids: list[str] = Field(min_length=1, max_length=100)
    start_at: datetime
    end_at: datetime
    scenario_id: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=2, max_length=1000)
    apply: bool = False
    state_fingerprint: Optional[str] = None
    request_id: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def normalize(self):
        for key in ("start_at", "end_at"):
            value = getattr(self, key)
            if value.tzinfo:
                setattr(self, key, value.astimezone().replace(tzinfo=None))
        if self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间")
        if len(set(self.staff_ids)) != len(self.staff_ids):
            raise ValueError("参与人员不能重复")
        return self


NEXT = {
    "草稿·待排程": ("设备总管", "核对检修条件，在人员时间轴生成安排"),
    "待审批": ("设备总管", "核对人员、时间、费用与约束，然后批准或退回"),
    "已批准": ("维修人员", "分配人员确认接单"),
    "已接单": ("维修人员", "实际开始维修时记录开工"),
    "执行中": ("维修人员", "记录维修过程及实际工时、费用，提交完工"),
    "已暂停": ("维修人员", "记录原因，具备条件后恢复维修"),
    "待验收": ("设备总管", "核对结果与实际备件耗用，验收或退回维修"),
    "已完成": ("设备总管", "已归档维修履历，继续观察设备"),
    "已取消": ("设备总管", "已结束；未开工需求可撤回取消后重新排程"),
    "已退回": ("设备总管", "根据退回意见修改需求并重新排程"),
    "已驳回": ("设备总管", "修改维护需求并重新排程"),
}
ACTIVE = {"待审批", "已批准", "已接单", "执行中", "已暂停", "待验收"}


def install_workflow_routes(app, ctx):
    connect, rows, settings_get, lock = (ctx[name] for name in ("connect", "rows", "settings_get", "_lock"))

    def record(connection, identifier):
        row = connection.execute("SELECT * FROM work_orders WHERE work_order_id=?", (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, "工单不存在")
        return {**json.loads(row["content"]), "status": row["status"], "updated_at": row["updated_at"]}

    def receipt(connection, identifier, signature):
        saved = connection.execute("SELECT * FROM operation_requests WHERE request_id=?", (identifier,)).fetchone()
        if saved:
            if saved["request_content"] != signature:
                raise HTTPException(409, "操作编号已用于不同操作")
            return json.loads(saved["response"])

    def save(connection, item, old_status, action, note, now, extra=None):
        item["version"] = item.get("version", 1) + 1
        event = {"at": now, "from": old_status, "to": item["status"], "action": action,
                 "actor": security.identity("设备总管"), "note": note, **(extra or {})}
        item.setdefault("execution_history", []).append(event)
        connection.execute("UPDATE work_orders SET content=?,status=?,updated_at=? WHERE work_order_id=?",
                           (json.dumps(item, ensure_ascii=False), item["status"], now, item["work_order_id"]))
        connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",
                           ("work_order_" + action, item["work_order_id"], json.dumps({**event, **security.actor_metadata()}, ensure_ascii=False), now))

    @app.get("/api/maintenance/timeline")
    def timeline(dataset_version: Optional[str] = None, include_deleted: bool = False):
        with lock, connect() as c:
            current = settings_get("last_sync_at")
            scope = dataset_version if dataset_version is not None else current
            all_orders = [{**json.loads(r["content"]), "status": r["status"], "updated_at": r["updated_at"]}
                          for r in c.execute("SELECT * FROM work_orders ORDER BY updated_at DESC")]
            metadata = {r["version"]: json.loads(r["metadata"]) for r in c.execute("SELECT * FROM dataset_versions")}
            metadata[current] = {"source_name": settings_get("source_name"), "data_origin": settings_get("data_origin")}
            versions = set(metadata) | {o.get("dataset_version", "") for o in all_orders} | {current}
            datasets = [{"version": v, "name": metadata.get(v, {}).get("source_name") or "历史数据源",
                         "origin": metadata.get(v, {}).get("data_origin", ""), "current": v == current,
                         "count": sum(o.get("dataset_version", "") == v and not o.get("deleted_at") for o in all_orders)}
                        for v in sorted(versions, reverse=True)]
            def resource(table):
                if scope == current:
                    return rows(table)
                return [json.loads(r[0]) for r in c.execute("SELECT content FROM archived_records WHERE version=? AND table_name=? ORDER BY row_index", (scope, table))]
            return {"dataset_version": scope, "current": scope == current, "datasets": datasets,
                    "equipment":resource("equipment"),"staff": resource("staff"), "orders": resource("orders"), "scenarios": resource("scenarios"),
                    "work_orders": [o for o in all_orders if o.get("dataset_version", "") == scope and (include_deleted or not o.get("deleted_at"))]}

    @app.get("/api/work-orders/{identifier}/flow")
    def flow(identifier: str):
        with connect() as c:
            item = record(c, identifier)
            owner, next_step = NEXT.get(item["status"], ("设备总管", "核对当前状态"))
            events = [{**dict(r), "content": json.loads(r["content"])} for r in c.execute(
                "SELECT * FROM audit_events WHERE entity_id=? OR entity_id=? ORDER BY event_id ASC",
                (identifier, item.get("source_alert_id", identifier)))]
            return {"record": item, "owner": item.get("staff_name") if owner == "维修人员" else owner,
                    "next_step": "已移入回收站，可恢复；历史和库存流水仍保留" if item.get("deleted_at") else next_step,
                    "events": events}

    @app.post("/api/work-orders/{identifier}/manage")
    def manage(identifier: str, payload: ManageInput):
        security.require_roles("developer", "admin")
        if payload.action not in {"withdraw", "archive", "restore"}:
            raise HTTPException(422, "未知管理操作")
        if not payload.note.strip():
            raise HTTPException(422, "请填写操作原因")
        signature = json.dumps({"work_order_id": identifier, **payload.model_dump(exclude={"request_id"}), **security.actor_metadata()}, sort_keys=True, ensure_ascii=False)
        with lock, connect() as c:
            c.execute("BEGIN IMMEDIATE")
            prior = receipt(c, payload.request_id, signature)
            if prior:
                return prior
            item = record(c, identifier)
            if item.get("version", 1) != payload.version:
                raise HTTPException(409, "工单已变化，请刷新后再操作")
            old = item["status"]; now = datetime.now(timezone.utc).isoformat()
            if payload.action == "restore":
                if not item.get("deleted_at"):
                    raise HTTPException(409, "该工单不在回收站")
                restored = item.get("deleted_from_status", old)
                if restored not in {"已完成", "已取消"}:
                    for r in c.execute("SELECT * FROM work_orders WHERE equipment_id=? AND work_order_id<>?", (item["equipment_id"], identifier)):
                        other = json.loads(r["content"])
                        if other.get("dataset_version") == item.get("dataset_version") and r["status"] not in {"已完成", "已取消"} and not other.get("deleted_at"):
                            raise HTTPException(409, "该数据版本的设备已有未完成工单，不能恢复重复需求")
                item["status"] = restored
                for key in ("deleted_at", "deleted_from_status", "deleted_by"):
                    item.pop(key, None)
            elif item.get("deleted_at"):
                raise HTTPException(409, "请先从回收站恢复工单")
            elif payload.action == "archive":
                if old not in {"草稿·待排程", "已退回", "已驳回", "已取消", "已完成"}:
                    raise HTTPException(409, "请先撤回未开工安排，执行中任务需先完成或按正常流程取消")
                item.update(deleted_at=now, deleted_by=security.identity("设备总管"), deleted_from_status=old)
                if old != "已完成":
                    item["status"] = "已取消"
                inventory.release(c, identifier)
            elif payload.action == "withdraw":
                if old == "待验收":
                    item["status"] = "执行中"
                    for key in ("actual_finish_at", "actual_hours", "actual_cost_cny", "repair_result"):
                        item.pop(key, None)
                else:
                    if old not in {"待审批", "已批准", "已接单", "已取消", "已退回", "已驳回"} or item.get("actual_start_at"):
                        raise HTTPException(409, "已开工或已验收记录不能抹除，请使用暂停、返修或新的维护需求")
                    item["status"] = "草稿·待排程"
                    inventory.release(c, identifier)
                    for key in ("start_at", "end_at", "staff_id", "staff_ids", "staff_name", "approved_at", "approval_decision_at", "last_approval_request_id", "approver", "approval_note", "approval_business_revision", "execution_check", "business_revision", "constraints_snapshot", "order_impact"):
                        item.pop(key, None)
            save(c, item, old, payload.action, payload.note, now)
            result = {"success": True, "work_order_id": identifier, "status": item["status"], "version": item["version"]}
            c.execute("INSERT INTO operation_requests VALUES (?,?,?)", (payload.request_id, signature, json.dumps(result)))
            return result

    @app.post("/api/work-orders/{identifier}/timeline")
    def edit_timeline(identifier: str, payload: TimelineInput):
        security.require_roles("developer", "admin")
        signature = json.dumps({"work_order_id": identifier, **payload.model_dump(mode="json", exclude={"request_id"}), **security.actor_metadata()}, sort_keys=True, ensure_ascii=False)
        with lock:
            with connect() as c:
                if payload.apply:
                    prior = receipt(c, payload.request_id, signature)
                    if prior:
                        return prior
                item = record(c, identifier)
            if item.get("deleted_at") or item["status"] not in {"待审批", "已批准", "已接单"} or item.get("actual_start_at"):
                raise HTTPException(409, "仅未开工的排程可调整；草稿请先自动生成安排")
            if item.get("dataset_version") != settings_get("last_sync_at"):
                raise HTTPException(409, "历史数据版本的安排仅可查看，不可套用当前资源修改")
            if item.get("version", 1) != payload.version:
                raise HTTPException(409, "工单版本已变化，请刷新")
            fingerprint = ctx["schedule_state_fingerprint"]()
            if payload.apply and payload.state_fingerprint != fingerprint:
                raise HTTPException(409, "预览后资源或工单已变化，请重新校验")
            result = ctx["_simulate_consistent"](ctx["SimulationInput"](scenario_id=payload.scenario_id, equipment_ids=[item["equipment_id"]], confirmed_priorities={item["equipment_id"]: .6}), candidate_only=True)
            if not result["selected"]:
                raise HTTPException(422, "当前数据中没有该设备的可用检修条件")
            candidate = result["selected"][0]; constraints = result["constraints"]
            start, end = payload.start_at, payload.end_at
            hours = (end - start).total_seconds() / 3600
            if start < datetime.now():
                raise HTTPException(422, "不能把未开工任务安排到过去")
            if hours + 1e-6 < candidate["hours"]:
                raise HTTPException(422, f"时长不能少于检修条件要求的 {candidate['hours']} 小时")
            if not candidate.get("window_start") or not candidate.get("window_end"):
                raise HTTPException(422,"请先补齐设备允许停机窗口")
            if (candidate.get("window_start") and start < datetime.fromisoformat(candidate["window_start"])) or (candidate.get("window_end") and end > datetime.fromisoformat(candidate["window_end"])):
                raise HTTPException(422, "调整超出设备允许停机窗口")
            if len(payload.staff_ids) != candidate["people"]:
                raise HTTPException(422, f"此任务必须同时安排 {candidate['people']} 人")
            all_orders = ctx["list_work_orders"]()["records"]
            others = [o for o in all_orders if o["work_order_id"] != identifier and o["status"] in ACTIVE]
            same = [o for o in others if o.get("dataset_version") == item.get("dataset_version")]
            if candidate["cost"] + sum(float(o.get("cost", 0)) for o in same) > constraints["budget"]:
                raise HTTPException(422, "调整后的本数据版本计划超出预算，请先调整情景或撤回其他任务")
            if hours + sum(float(o.get("hours", 0)) for o in same) > constraints["max_downtime_h"]:
                raise HTTPException(422, "调整后累计停机工时超出排程限制")
            with connect() as c:
                scope = inventory.current_scope(c)
                for part in candidate.get("spare_parts", []):
                    stock = c.execute("SELECT * FROM inventory_stock WHERE scope=? AND part_name=?", (scope, part["part_name"])).fetchone()
                    if not stock or stock["source"] == "legacy_unverified":
                        raise HTTPException(422, "备件尚未核对，请先确认库存")
                    demand = sum(sum(int(p.get("quantity", 0)) for p in o.get("spare_parts", []) if p["part_name"] == part["part_name"]) for o in others if (o.get("inventory_scope") or o.get("dataset_version")) == scope)
                    part["available_quantity"] = max(0, stock["on_hand"] - demand)
            people = [p for p in rows("staff") if p["staff_id"] in payload.staff_ids]
            if any(not p.get("shift_start") or not p.get("shift_end") for p in people):
                raise HTTPException(422,"请先补齐所选人员的班次")
            if len(people) != len(payload.staff_ids):
                raise HTTPException(422, "人员不存在于当前数据版本")
            candidate.update(hours=hours, window_start=start.isoformat(sep=" "), window_end=end.isoformat(sep=" "))
            scheduled, conflicts = ctx["schedule_selected"]([candidate], people, rows("orders"), start.isoformat(sep=" "), staff_limit=constraints["staff_count"], bookings=others)
            if not scheduled or conflicts:
                raise HTTPException(422, "；".join(c["reason"] for c in conflicts) or "调整违反排程约束")
            checked = scheduled[0]
            if set(checked["staff_ids"]) != set(payload.staff_ids):
                raise HTTPException(422, "参与人员不满足技能或班次条件")
            response = {"success": True, "preview": not payload.apply, "scheduled": checked,
                        "state_fingerprint": fingerprint, "requires_approval": True,
                        "message": "校验通过；保存后退回待审批，原审批失效"}
            if not payload.apply:
                return response
            now = datetime.now(timezone.utc).isoformat()
            with connect() as c:
                c.execute("BEGIN IMMEDIATE")
                if ctx["schedule_state_fingerprint"]() != fingerprint:
                    raise HTTPException(409, "资源已变化，请重新预览")
                old = item["status"]
                before = {k: item.get(k) for k in ("staff_ids", "start_at", "end_at", "hours")}
                inventory.release(c, identifier)
                item.update(checked, status="待审批", scenario_id=payload.scenario_id, constraints_snapshot=constraints,
                            business_revision=settings_get("business_revision", "0"), inventory_scope=scope)
                for key in ("approver", "approved_at", "approval_decision_at", "last_approval_request_id", "approval_note", "approval_business_revision", "execution_check"):
                    item.pop(key, None)
                save(c, item, old, "timeline_adjusted", payload.note, now, {"before": before, "after": {k: item.get(k) for k in before}})
                response.update(work_order_id=identifier, status=item["status"], version=item["version"])
                c.execute("INSERT INTO operation_requests VALUES (?,?,?)", (payload.request_id, signature, json.dumps(response, ensure_ascii=False)))
            return response
