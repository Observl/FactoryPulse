"""Stock counts, work-order reservations and actual consumption share one transaction."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

ACTIVE_STATES={"已批准","已接单","执行中","已暂停","待验收"}


def create_schema(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS inventory_stock (scope TEXT NOT NULL,part_name TEXT NOT NULL,on_hand INTEGER NOT NULL CHECK(on_hand>=0),version INTEGER NOT NULL,counted_at TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(scope,part_name))")
    connection.execute("CREATE TABLE IF NOT EXISTS inventory_reservations (work_order_id TEXT NOT NULL,scope TEXT NOT NULL,part_name TEXT NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>=0),state TEXT NOT NULL,PRIMARY KEY(work_order_id,part_name))")
    connection.execute("CREATE TABLE IF NOT EXISTS inventory_movements (movement_id TEXT PRIMARY KEY,scope TEXT NOT NULL,part_name TEXT NOT NULL,work_order_id TEXT,movement_type TEXT NOT NULL,quantity INTEGER NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS inventory_reserved_lookup ON inventory_reservations(scope,part_name,state)")


def current_scope(connection):
    for key in ("inventory_scope","last_sync_at"):
        row=connection.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        if row and row[0]: return row[0]
    return "uninitialized"


def quantities(parts):
    result={}
    for part in parts:
        name=str(part.get("part_name") or "").strip()
        if not name: raise HTTPException(422,"备件名称不能为空，请核对检修条件")
        quantity=part.get("quantity",0)
        if not isinstance(quantity,(int,float)) or int(quantity)!=quantity or quantity<0: raise HTTPException(422,"备件数量必须是非负整数")
        result[name]=result.get(name,0)+int(quantity)
    return result


def reserved_quantity(connection,scope,name,exclude=None):
    return connection.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory_reservations WHERE scope=? AND part_name=? AND state='reserved' AND work_order_id<>?",(scope,name,exclude or "")).fetchone()[0]


def stock_records(connection,scope):
    records=[]
    for row in connection.execute("SELECT * FROM inventory_stock WHERE scope=? ORDER BY part_name",(scope,)):
        held=reserved_quantity(connection,scope,row["part_name"])
        records.append({**dict(row),"reserved_quantity":held,"available_to_allocate":max(0,row["on_hand"]-held),"shortfall":max(0,held-row["on_hand"])})
    return records


def register_requirement_stock(connection,scope,parts):
    for part in parts:
        name=part["part_name"]
        existing=connection.execute("SELECT * FROM inventory_stock WHERE scope=? AND part_name=?",(scope,name)).fetchone()
        count=int(part["available_quantity"])
        if existing:
            if existing["on_hand"]!=count: raise HTTPException(409,f"备件 {name} 的库存已改变，请重新加载；实盘调整请使用“备件库存”")
        else:
            now=datetime.now(timezone.utc).isoformat()
            connection.execute("INSERT INTO inventory_stock VALUES (?,?,?,?,?,?)",(scope,name,count,1,now,"requirements_confirmed"))
            connection.execute("INSERT INTO inventory_movements VALUES (?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,scope,name,None,"initial_count",count,"首次录入检修条件",now))


def seed_legacy_stock(connection,scope,rules):
    counts={}
    for rule in rules:
        for part in rule.get("spare_parts",[]):
            name=str(part.get("part_name") or "").strip()
            if name:
                count=max(0,int(part.get("available_quantity") or 0))
                counts[name]=min(counts.get(name,count),count)
    for name,count in counts.items():
        connection.execute("INSERT OR IGNORE INTO inventory_stock VALUES (?,?,?,?,?,?)",(scope,name,count,1,datetime.now(timezone.utc).isoformat(),"legacy_unverified"))


def import_legacy_reservations(connection):
    # Existing approved tasks must not silently stop holding stock after migration.
    for row in connection.execute("SELECT work_order_id,status,content FROM work_orders"):
        if row["status"] not in ACTIVE_STATES: continue
        work=json.loads(row["content"])
        scope=work.get("inventory_scope") or work.get("dataset_version")
        if not scope or not work.get("spare_parts"): continue
        seed_legacy_stock(connection,scope,[work])
        for name,quantity in quantities(work["spare_parts"]).items():
            connection.execute("INSERT OR IGNORE INTO inventory_reservations VALUES (?,?,?,?,?)",(row["work_order_id"],scope,name,quantity,"reserved"))


def available_parts(connection,scope,parts):
    result=[]
    for part in parts:
        name=str(part.get("part_name") or "").strip()
        row=connection.execute("SELECT * FROM inventory_stock WHERE scope=? AND part_name=?",(scope,name)).fetchone()
        free=max(0,row["on_hand"]-reserved_quantity(connection,scope,name)) if row else 0
        result.append({**part,"available_quantity":free,"stock_on_hand":row["on_hand"] if row else 0,"stock_verified":bool(row and row["source"]!="legacy_unverified")})
    return result


def reserve(connection,work_id,scope,parts):
    for name,quantity in quantities(parts).items():
        row=connection.execute("SELECT * FROM inventory_stock WHERE scope=? AND part_name=?",(scope,name)).fetchone()
        if not row or row["source"]=="legacy_unverified": raise HTTPException(409,f"备件 {name} 尚未实盘确认，请先在“备件库存”核对")
        free=row["on_hand"]-reserved_quantity(connection,scope,name,exclude=work_id)
        if quantity>free: raise HTTPException(409,f"备件 {name} 需要 {quantity}，扣除其他工单预留后仅余 {max(0,free)}，请调整安排或补充库存")
        connection.execute("INSERT OR REPLACE INTO inventory_reservations VALUES (?,?,?,?,?)",(work_id,scope,name,quantity,"reserved"))


def release(connection,work_id):
    connection.execute("UPDATE inventory_reservations SET state='released' WHERE work_order_id=? AND state='reserved'",(work_id,))


def consume(connection,work_id,scope,planned,actual):
    planned_counts=quantities(planned)
    actual_counts=quantities(actual)
    if set(actual_counts)-set(planned_counts): raise HTTPException(422,"实际耗用包含工单未列出的备件，请先补充维修需求")
    # A missing line is deliberately not treated as zero; the operator must confirm every part.
    if set(actual_counts)!=set(planned_counts): raise HTTPException(422,"请逐项填写实际耗用；未使用的备件填写0")
    for name,quantity in actual_counts.items():
        row=connection.execute("SELECT * FROM inventory_stock WHERE scope=? AND part_name=?",(scope,name)).fetchone()
        if not row or row["source"]=="legacy_unverified": raise HTTPException(409,f"备件 {name} 缺少实盘确认，请先核对库存")
        free=row["on_hand"]-reserved_quantity(connection,scope,name,exclude=work_id)
        if quantity>max(0,free): raise HTTPException(409,f"备件 {name} 的实际耗用与库存不符，请先盘点或协调其他工单预留")
        now=datetime.now(timezone.utc).isoformat()
        connection.execute("UPDATE inventory_stock SET on_hand=on_hand-?,version=version+1 WHERE scope=? AND part_name=?",(quantity,scope,name))
        connection.execute("INSERT INTO inventory_movements VALUES (?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,scope,name,work_id,"consume",-quantity,"工单验收确认实际耗用",now))
    connection.execute("UPDATE inventory_reservations SET state='consumed' WHERE work_order_id=? AND state='reserved'",(work_id,))
