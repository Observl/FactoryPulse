"""Versioned schema baseline; newer databases are never opened for downgrade."""
from datetime import datetime,timezone

SCHEMA_VERSION=1
REQUIRED_COLUMNS={
    "records":{"table_name","row_index","content"},
    "work_orders":{"work_order_id","equipment_id","content","status","updated_at"},
    "alerts":{"alert_id","equipment_id","dataset_version","prediction_at","defer_until","version"},
    "audit_events":{"event_id","event_type","entity_id","content","created_at"},
}


def check_compatible(connection):
    current=connection.execute("PRAGMA user_version").fetchone()[0]
    if current>SCHEMA_VERSION:
        raise RuntimeError("数据库结构版本高于当前应用，请使用匹配版本，不能直接降级打开")
    return current


def finalize_schema(connection,previous):
    for table,expected in REQUIRED_COLUMNS.items():
        actual={row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not expected.issubset(actual):
            raise RuntimeError(f"数据库结构不完整：{table}，请先备份并修复，不能继续启动")
    connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL,from_version INTEGER NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS work_orders_equipment_status ON work_orders(equipment_id,status)")
    connection.execute("CREATE INDEX IF NOT EXISTS audit_entity_event ON audit_events(entity_id,event_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS audit_type_event ON audit_events(event_type,event_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS alerts_dataset_equipment ON alerts(dataset_version,equipment_id,prediction_at)")
    connection.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?,?,?,?)",(SCHEMA_VERSION,"工业维护业务结构基线",datetime.now(timezone.utc).isoformat(),previous))
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
