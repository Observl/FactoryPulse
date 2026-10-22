"""Read-only, version-scoped evidence, with explicit pagination and limitations."""
import json
from datetime import datetime, timezone
from . import inventory

def operational_evidence(name, arguments, *, connect, rows, settings_get):
    version = settings_get("last_sync_at")
    result = {"source": "SQLite / " + name, "data_version": version,
              "business_revision": settings_get("business_revision", "0"),
              "queried_at": datetime.now(timezone.utc).isoformat(), "data_time": None,
              "limitations": ["查询时间不是现场采样时间；未提供的字段不能假设正常或可用。",
                               "模拟资源和成本仅用于演示；关联记录本身不证明时间冲突或因果关系。"]}
    with connect() as connection:
        if name == "work_order_flow":
            row = connection.execute("SELECT * FROM work_orders WHERE work_order_id=?", (arguments["work_order_id"],)).fetchone()
            if not row:
                raise ValueError("工单不存在")
            item = {**json.loads(row["content"]), "status": row["status"], "updated_at": row["updated_at"]}
            if item.get("dataset_version") != version:
                raise ValueError("该工单属于其他数据版本，请先在界面切换数据源")
            total = connection.execute("SELECT COUNT(*) FROM audit_events WHERE entity_id=?", (arguments["work_order_id"],)).fetchone()[0]
            events = [{**dict(r), "content": json.loads(r["content"])} for r in connection.execute(
                "SELECT * FROM audit_events WHERE entity_id=? ORDER BY event_id DESC LIMIT 50", (arguments["work_order_id"],))]
            return {**result, "data_time": row["updated_at"], "record": item,
                    "events": list(reversed(events)), "event_total": total, "events_truncated": total > 50}
        category = arguments["category"]
        equipment = arguments.get("equipment_id")
        if equipment and category not in {"orders", "requirements", "work_orders"}:
            raise ValueError("此类资源不支持按设备过滤，请查询完整分页资源")
        if category == "work_orders":
            records = []
            for row in connection.execute("SELECT * FROM work_orders ORDER BY updated_at DESC,work_order_id"):
                item = json.loads(row["content"])
                if item.get("dataset_version") == version and not item.get("deleted_at"):
                    records.append({**item, "status": row["status"], "updated_at": row["updated_at"]})
        elif category == "inventory":
            records = inventory.stock_records(connection, inventory.current_scope(connection))
            result["limitations"].append("库存是账面记录；未盘点不保证实物可用，不能替代领料和审批。")
        else:
            records = rows({"requirements": "maintenance_rules"}.get(category, category))
        if equipment:
            records = [r for r in records if str(r.get("equipment_id")) == equipment]
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 20)
        page = records[offset:offset + limit]
        return {**result, "category": category, "records": page, "total": len(records),
                "offset": offset, "returned": len(page), "truncated": offset + limit < len(records),
                "next_offset": offset + limit if offset + limit < len(records) else None}
