"""Validated operational inputs; never infer company constraints from sensor data."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from . import inventory,security
from .readiness import resource_time_readiness


class ResourceModel(BaseModel):
    model_config={"allow_inf_nan":False}

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls,values):
        if not isinstance(values,dict): return values
        normalized={key:value.strip() if isinstance(value,str) else value for key,value in values.items()}
        for key in {"shift_start","shift_end","start_at","end_at","due_at","window_start","window_end"}:
            value=normalized.get(key)
            if isinstance(value,str):
                try: value=datetime.fromisoformat(value)
                except ValueError: continue
            if isinstance(value,datetime) and value.tzinfo: normalized[key]=value.astimezone().replace(tzinfo=None)
        return normalized


class StaffInput(ResourceModel):
    staff_name:str=Field(min_length=1,max_length=100)
    skills:list[str]=Field(min_length=1,max_length=30)
    available_hours:float=Field(gt=0,le=24)
    shift_start:datetime
    shift_end:datetime

    @model_validator(mode="after")
    def valid(self):
        if self.shift_end<=self.shift_start: raise ValueError("班次结束必须晚于开始")
        if self.available_hours>(self.shift_end-self.shift_start).total_seconds()/3600: raise ValueError("可用工时不能超过班次时长")
        if any(not skill.strip() for skill in self.skills): raise ValueError("技能不能为空")
        return self


class OrderInput(ResourceModel):
    order_name:str=Field(min_length=1,max_length=200)
    equipment_id:str
    start_at:datetime
    end_at:datetime
    due_at:datetime
    priority:str="普通"
    delay_cost_cny_per_hour:float=Field(default=0,ge=0)

    @model_validator(mode="after")
    def valid(self):
        if self.end_at<=self.start_at: raise ValueError("生产结束必须晚于开始")
        if self.due_at<self.end_at: raise ValueError("计划生产结束晚于交期，请先调整订单计划")
        return self


class ScenarioInput(ResourceModel):
    scenario_name:str=Field(min_length=1,max_length=100)
    maintenance_budget_cny:float=Field(ge=0)
    available_staff_count:int=Field(ge=1,le=1000)
    max_downtime_h:float=Field(gt=0,le=100000)
    risk_threshold:float=Field(default=.35,ge=0,le=1)


class SparePart(ResourceModel):
    part_name:str=Field(min_length=1,max_length=100)
    quantity:int=Field(ge=1)
    available_quantity:int=Field(ge=0)


class RequirementInput(ResourceModel):
    maintenance_hours:float=Field(gt=0,le=10000)
    maintenance_cost_cny:float=Field(ge=0)
    required_skill:str=Field(min_length=1,max_length=100)
    required_staff_count:int=Field(ge=1,le=100)
    window_start:datetime
    window_end:datetime
    spare_parts:list[SparePart]=Field(default_factory=list,max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if self.window_end<=self.window_start: raise ValueError("停机窗口结束必须晚于开始")
        if self.maintenance_hours>(self.window_end-self.window_start).total_seconds()/3600: raise ValueError("维修工时长于可停机窗口")
        return self


class InventoryCountInput(ResourceModel):
    on_hand:int=Field(ge=0,strict=True)
    version:Optional[int]=Field(default=None,ge=1)
    note:str=Field(min_length=2,max_length=500)


def install_resource_routes(app,connect,rows,lock):
    tables={"staff":("staff","staff_id"),"orders":("orders","order_id"),"scenarios":("scenarios","scenario_id"),"requirements":("maintenance_rules","equipment_id")}

    def persist(kind,identifier,payload):
        if not identifier.strip() or len(identifier)>100: raise HTTPException(422,"编号不能为空且不超过100字符")
        data=payload.model_dump(mode="json")
        if kind in {"orders","requirements"}:
            equipment=data.get("equipment_id",identifier)
            if equipment not in {r["equipment_id"] for r in rows("equipment")}: raise HTTPException(422,"设备编号不存在")
        if kind=="staff": data["skills"]=",".join(skill.strip() for skill in data["skills"])
        # Store operational times consistently in deployment-local time without mixed offsets.
        for key,value in list(data.items()):
            if key.endswith(("_at","_start","_end")) and isinstance(value,str):
                try:
                    moment=datetime.fromisoformat(value)
                    if moment.tzinfo: moment=moment.astimezone().replace(tzinfo=None)
                    data[key]=moment.isoformat(sep=" ")
                except ValueError: pass
        table,key=tables[kind]
        with lock,connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if kind in {"orders","requirements"}:
                equipment=data.get("equipment_id",identifier)
                if not connection.execute("SELECT 1 FROM records WHERE table_name='equipment' AND json_extract(content,'$.equipment_id')=?",(equipment,)).fetchone():
                    raise HTTPException(409,"设备数据已改变，请刷新后重新选择设备")
            existing=connection.execute("SELECT row_index,content FROM records WHERE table_name=? AND json_extract(content,?)=?",(table,"$."+key,identifier)).fetchone()
            index=existing["row_index"] if existing else connection.execute("SELECT COALESCE(MAX(row_index),-1)+1 FROM records WHERE table_name=?",(table,)).fetchone()[0]
            content=json.loads(existing["content"]) if existing else {}
            if kind=="requirements": inventory.register_requirement_stock(connection,inventory.current_scope(connection),data.get("spare_parts",[]))
            content.update(data)
            content.update({key:identifier,"data_origin":"USER_CONFIRMED_OPERATIONAL_INPUT","configuration_status":"configured"})
            connection.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)",(table,index,json.dumps(content,ensure_ascii=False)))
            revision=connection.execute("SELECT value FROM settings WHERE key='business_revision'").fetchone()
            revision=int(revision[0])+1 if revision else 1
            connection.execute("INSERT OR REPLACE INTO settings VALUES ('business_revision',?)",(str(revision),))
            connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("resource_updated",identifier,json.dumps({"kind":kind,"revision":revision,"values":data,**security.actor_metadata()},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return {"success":True,"record":content,"business_revision":revision,"message":"已保存；旧排程需要重新计算后再审批"}

    @app.get("/api/maintenance/time-readiness")
    def time_readiness():
        with lock:
            return resource_time_readiness(rows("maintenance_rules"),rows("staff"))

    @app.get("/api/resources/{kind}")
    def get_resources(kind:str):
        if kind=="inventory":
            with lock,connect() as connection:
                inventory.import_legacy_reservations(connection)
                inventory.seed_legacy_stock(connection,inventory.current_scope(connection),rows("maintenance_rules"))
                records=inventory.stock_records(connection,inventory.current_scope(connection))
            return {"records":records,"meaning":"实盘库存减去其他未完成工单预留，才是本轮可分配数量"}
        if kind not in tables: raise HTTPException(404,"未知资源类别")
        records=rows(tables[kind][0])
        if kind=="requirements":
            with lock,connect() as connection:
                scope=inventory.current_scope(connection)
                inventory.seed_legacy_stock(connection,scope,records)
                stock={record["part_name"]:record for record in inventory.stock_records(connection,scope)}
                for record in records:
                    record["spare_parts"]=[{**part,"available_quantity":stock[part["part_name"]]["on_hand"],"reserved_quantity":stock[part["part_name"]]["reserved_quantity"],"available_to_allocate":stock[part["part_name"]]["available_to_allocate"]} if part.get("part_name") in stock else part for part in record.get("spare_parts",[])]
        return {"records":records,"meaning":{"staff":"技能和班次决定谁能维修、何时能维修","orders":"生产占用时间决定设备何时不能停机","scenarios":"预算、累计停机工时和人数是排程的限制条件","requirements":"维修工时、技能、备件和设备停机窗口决定任务是否可执行"}[kind]}

    @app.post("/api/resources/inventory/{part_name}")
    def count_inventory(part_name:str,payload:InventoryCountInput):
        part_name=part_name.strip()
        if not part_name or len(part_name)>100: raise HTTPException(422,"请填写有效备件名称")
        now=datetime.now(timezone.utc).isoformat()
        with lock,connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope=inventory.current_scope(connection)
            if scope=="uninitialized": raise HTTPException(422,"请先载入企业设备数据，再登记库存")
            existing=connection.execute("SELECT * FROM inventory_stock WHERE scope=? AND part_name=?",(scope,part_name)).fetchone()
            if existing and payload.version!=existing["version"]: raise HTTPException(409,"库存已被更新，请重新选择备件后再提交实盘结果")
            version=existing["version"]+1 if existing else 1
            previous=existing["on_hand"] if existing else 0
            connection.execute("INSERT OR REPLACE INTO inventory_stock VALUES (?,?,?,?,?,?)",(scope,part_name,payload.on_hand,version,now,"manual_count"))
            connection.execute("INSERT INTO inventory_movements VALUES (?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,scope,part_name,None,"count",payload.on_hand-previous,payload.note,now))
            revision=connection.execute("SELECT value FROM settings WHERE key='business_revision'").fetchone()
            revision=int(revision[0])+1 if revision else 1
            connection.execute("INSERT OR REPLACE INTO settings VALUES ('business_revision',?)",(str(revision),))
            held=inventory.reserved_quantity(connection,scope,part_name)
            result={"part_name":part_name,"on_hand":payload.on_hand,"version":version,"reserved_quantity":held,"available_to_allocate":max(0,payload.on_hand-held),"shortfall":max(0,held-payload.on_hand)}
            connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("inventory_count",part_name,json.dumps({**result,"note":payload.note,**security.actor_metadata()},ensure_ascii=False),now))
        return {"success":True,"record":result,"message":"实盘库存已保存；库存不足时请协调已预留工单。旧排程需重新核对。"}

    @app.post("/api/resources/staff/{identifier}")
    def staff(identifier:str,payload:StaffInput): return persist("staff",identifier,payload)

    @app.post("/api/resources/orders/{identifier}")
    def order(identifier:str,payload:OrderInput): return persist("orders",identifier,payload)

    @app.post("/api/resources/scenarios/{identifier}")
    def scenario(identifier:str,payload:ScenarioInput): return persist("scenarios",identifier,payload)

    @app.post("/api/resources/requirements/{identifier}")
    def requirement(identifier:str,payload:RequirementInput): return persist("requirements",identifier,payload)
