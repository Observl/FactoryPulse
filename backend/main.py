"""FactoryPulse MVP API: Excel import, SQLite, reproducible maintenance scenarios and API settings."""
from __future__ import annotations
import asyncio
import io, json, math, os, sqlite3, threading, csv, ipaddress, socket, re, uuid, hashlib
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import StreamingResponse,JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openpyxl import load_workbook
from .agent import run_agent
from .agent_registry import validate_arguments
from .agent_operations import operational_evidence
from .agent_config import load_config
from .agent_fast import quick_tool, evidence_answer
from .agent_policy import is_factorypulse_question, plain_answer, OUT_OF_SCOPE
from .import_pipeline import install_import_pipeline
from .resources import install_resource_routes,ScenarioInput
from . import inventory,security,backups,migrations
from .replay import event_timeline
from .analytics import combine_risks, cp_sat_select, ewma_scores, schedule_selected, xgboost_with_shap
from .score_explanation import rule_details
from .adaptive_training import load_training_config
from .cnc_demo import build_cnc_demo
from .model_validation_data import load_acceptance_dataset, build_model_validation, ORIGIN as MODEL_VALIDATION_ORIGIN
from .demo_business import initialize_demo_stock
from .nasa_ims import build_nasa_ims
from .metropt3 import build_metropt3, label_observed_history
from .smart_import import STANDARD_FIELDS, STANDARD_UNITS, infer_mapping, normalize_rows, parse_table, parse_table_path
from .field_profiles import PROFILES, COMMON, is_custom
from .execution import assert_no_formal_conflict,recheck_execution
from .connection_validation import address_validation

DATA_DIR = Path(os.getenv("FACTORYPULSE_DATA_DIR", Path.home() / ".factorypulse"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_SESSION_DIR = DATA_DIR / "import_sessions"
IMPORT_SESSION_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "factorypulse.sqlite3"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKBLAZE_DATA_FILE = Path(os.getenv("FACTORYPULSE_BACKBLAZE_FILE", PROJECT_ROOT / "data" / "backblaze" / "2013-04-10.csv"))
BACKBLAZE_SOURCE_URL = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_2013.zip"
app = FastAPI(title="FactoryPulse Industrial Operations", version="0.5.0-preview")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET","POST"], allow_headers=["*"])
_lock = threading.RLock()
_analytics_lock = threading.RLock()


@app.exception_handler(RequestValidationError)
async def validation_error(request,exception):
    # Never echo passwords, API keys or the entire submitted body in validation errors.
    errors=[]
    for error in exception.errors():
        item={key:error[key] for key in ("loc","msg","type") if key in error}
        if error.get("ctx"): item["ctx"]={key:value for key,value in error["ctx"].items() if key!="error" and isinstance(value,(str,int,float,bool,type(None)))}
        errors.append(item)
    return JSONResponse({"detail":errors},status_code=422)
def credential_get():
    if os.environ.get("FACTORYPULSE_AI_API_KEY"): return os.environ["FACTORYPULSE_AI_API_KEY"]
    try:
        import keyring
        return keyring.get_password("FactoryPulse","ai-api-key") or ""
    except Exception: return ""
def credential_set(value:str)->bool:
    try:
        import keyring
        keyring.set_password("FactoryPulse","ai-api-key",value); return True
    except Exception: return False
_api_key = credential_get()
_credential_secure = bool(_api_key and not os.environ.get("FACTORYPULSE_AI_API_KEY"))
_analytics_cache: dict = {"key": None, "devices": {}, "summary": {}}
_readings_cache: dict = {"key":None,"records":[]}
TABLES = {
 "equipment":("01_设备档案",["equipment_id","equipment_name","equipment_type","status"]),
 "readings":("02_运行监测",["reading_id","equipment_id","timestamp","air_temperature_k","process_temperature_k","rotational_speed_rpm","torque_nm","tool_wear_min"]),
 "maintenance_rules":("03_维护参数",["equipment_id","inspection_cost_cny","repair_cost_cny","inspection_duration_h","assumed_failure_loss_cny","repair_duration_h","required_staff_count"]),
 "maintenance_history":("04_维护历史",["maintenance_id","equipment_id"]),
 "staff":("05_维修人员",["staff_id","available_hours"]),
 "orders":("06_生产订单",["order_id","equipment_id"]),
 "scenarios":("07_策略情景",["scenario_id","maintenance_budget_cny","risk_threshold","available_staff_count","max_downtime_h"]),
 "demo_risks":("08_风险评分演示",["equipment_id","risk_score"])
}
class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect():
    c=sqlite3.connect(DB,timeout=15,factory=ManagedConnection)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c
def init():
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        previous_schema=migrations.check_compatible(c)
        inventory.create_schema(c)
        security.create_schema(c)
        c.execute("CREATE TABLE IF NOT EXISTS records (table_name TEXT NOT NULL, row_index INTEGER NOT NULL, content TEXT NOT NULL, PRIMARY KEY(table_name,row_index))")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS alerts (alert_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS work_orders (work_order_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS audit_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, entity_id TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS operation_requests (request_id TEXT PRIMARY KEY, request_content TEXT NOT NULL, response TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS prediction_runs (run_id TEXT PRIMARY KEY, dataset_version TEXT NOT NULL, model_version TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS maintenance_events (work_order_id TEXT PRIMARY KEY,dataset_version TEXT NOT NULL,equipment_id TEXT NOT NULL,content TEXT NOT NULL,verified_at TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS planning_runs (plan_id TEXT PRIMARY KEY,dataset_version TEXT NOT NULL,business_revision TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)")
        columns={row[1] for row in c.execute("PRAGMA table_info(alerts)")}
        for name,definition in {"dataset_version":"TEXT NOT NULL DEFAULT ''","prediction_at":"TEXT NOT NULL DEFAULT ''","defer_until":"TEXT","version":"INTEGER NOT NULL DEFAULT 1"}.items():
            if name not in columns: c.execute(f"ALTER TABLE alerts ADD COLUMN {name} {definition}")
        migrations.finalize_schema(c,previous_schema)
init()
def rows(table, limit=None):
    if table=="readings" and limit is None:
        version=(str(DB),settings_get("last_sync_at"))
        if version[1] and _analytics_cache.get("key") is not None and _readings_cache["key"]==version:
            return _readings_cache["records"]
    with _lock, connect() as c:
        sql="SELECT content FROM records WHERE table_name=? ORDER BY row_index"
        params=[table]
        if limit is not None:
            sql+=" LIMIT ?"; params.append(limit)
        result=[json.loads(r["content"]) for r in c.execute(sql,params)]
        if table=="readings" and limit is None and version[1]:_readings_cache.update(key=version,records=result)
        return result
def settings_get(name, default=""):
    with connect() as c:
        r=c.execute("SELECT value FROM settings WHERE key=?",(name,)).fetchone()
        return r["value"] if r else default
def settings_set_many(c, values):
    if "last_sync_at" in values and "data_lineage" not in values:
        values={**values,"data_lineage":"[]","restored_from":"","inventory_scope":values["last_sync_at"]}
    c.executemany("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",[(k,str(v)) for k,v in values.items()])


def archive_current_dataset(connection):
    """Archive inside the replacement transaction, including first legacy imports."""
    count=connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    if not count: return
    now=datetime.now(timezone.utc).isoformat()
    existing=connection.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
    version=existing[0] if existing and existing[0] else "legacy-"+uuid.uuid4().hex
    metadata={row["key"]:row["value"] for row in connection.execute("SELECT * FROM settings WHERE key IN ('last_sync_at','source_name','source_date','data_origin','record_count','device_count','data_lineage','inventory_scope','sensor_catalog','field_profile_config')")}
    connection.execute("INSERT OR IGNORE INTO dataset_versions VALUES (?,?,?)",(version,json.dumps(metadata,ensure_ascii=False),now))
    connection.execute("INSERT OR IGNORE INTO archived_records SELECT ?,table_name,row_index,content FROM records",(version,))

def audit(event_type:str, entity_id:str, payload:dict):
    payload={**payload,**security.actor_metadata()}
    with _lock,connect() as c:
        c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",(event_type,entity_id,json.dumps(payload,ensure_ascii=False,default=str),datetime.now(timezone.utc).isoformat()))
def num(v, default=0):
    try:
        n=float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default
def validate(data):
    known={r["equipment_id"] for r in data["equipment"]}
    if not known: raise ValueError("设备档案不可为空")
    for table in ("readings","maintenance_rules","maintenance_history","orders","demo_risks"):
        for r in data[table]:
            if str(r.get("equipment_id","")) not in known: raise ValueError(f"{table} 存在未知设备编号 {r.get('equipment_id')}")
    if len({r.get("equipment_id") for r in data["demo_risks"]}) != len(data["demo_risks"]): raise ValueError("风险评分表设备编号重复")
    for r in data["demo_risks"]:
        score=num(r.get("risk_score"),-1)
        if not 0<=score<=1: raise ValueError("演示风险评分必须在0到1之间")
    if len(known)!=len(data["equipment"]): raise ValueError("设备编号存在重复")
    for table in ("maintenance_rules","readings","staff","orders","scenarios"):
        if not data[table]: raise ValueError(f"{TABLES[table][0]} 不可为空")
    numeric_fields={"maintenance_rules":["inspection_cost_cny","repair_cost_cny","inspection_duration_h","repair_duration_h","required_staff_count"],"staff":["available_hours"],"scenarios":["maintenance_budget_cny","risk_threshold","available_staff_count","max_downtime_h"]}
    for table,fields in numeric_fields.items():
        for row in data[table]:
            for field in fields:
                value=num(row.get(field),math.nan)
                if not math.isfinite(value) or value<0: raise ValueError(f"{TABLES[table][0]} 的 {field} 必须是有效非负数值")
                if field in {"required_staff_count","available_staff_count"} and (value<1 or value!=int(value)): raise ValueError("人员数量必须是正整数")
                if field=="risk_threshold" and value>1: raise ValueError("风险阈值必须在0到1之间")
@app.get("/api/health")
def health():
    try:
        with connect() as c: c.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        raise HTTPException(503,"数据服务尚未就绪")
    return {"status":"ok","version":"0.5.0-preview","deployment_status":"validation_required"}


@app.get("/api/health/ready")
def readiness():
    try:
        with connect() as c:
            version=migrations.check_compatible(c)
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE settings SET value=value WHERE 0")
            c.rollback()
    except (sqlite3.Error,RuntimeError):
        raise HTTPException(503,"数据库暂时不能完成读写，请检查存储权限、空间或占用状态")
    return {"status":"ready","database_read_write":True,"schema_version":version,"note":"仅验证数据库访问，不代表预测准确性、备份恢复或现场业务已经验收"}

def smart_value(row, key):
    value=row.get(key)
    return num(value,0) if value not in (None,"") else 0

def backblaze_risk(row):
    if int(smart_value(row,"failure")) == 1: return .99
    # Transparent operational heuristic, not a trained failure model.
    score=.02
    score += min(smart_value(row,"smart_5_raw"),10)*.035
    score += min(smart_value(row,"smart_187_raw"),10)*.025
    score += min(smart_value(row,"smart_188_raw"),10)*.015
    score += min(smart_value(row,"smart_197_raw"),10)*.04
    score += min(smart_value(row,"smart_198_raw"),10)*.04
    temp=smart_value(row,"smart_194_raw") or smart_value(row,"smart_190_raw")
    if temp>45: score+=min((temp-45)*.02,.2)
    return round(min(score,.98),4)

def transform_backblaze(path):
    equipment=[]; readings=[]; rules=[]; risks=[]; failures=[]
    source_date=""
    with path.open("r",encoding="utf-8-sig",newline="") as handle:
        for index,row in enumerate(csv.DictReader(handle)):
            eid=(row.get("serial_number") or f"UNKNOWN-{index}").strip()
            model=(row.get("model") or "未知型号").strip()
            source_date=(row.get("date") or source_date).strip()
            capacity=int(num(row.get("capacity_bytes"),0))
            risk=backblaze_risk(row); failed=int(num(row.get("failure"),0))==1
            temperature=smart_value(row,"smart_194_raw") or smart_value(row,"smart_190_raw")
            manufacturer=model.split()[0] if model else "未知"
            status="故障" if failed else "预警" if risk>=.4 else "运行中"
            equipment.append({"equipment_id":eid,"equipment_name":model,"equipment_type":"数据中心硬盘","status":status,"production_line":manufacturer,"capacity_bytes":capacity,"data_origin":"BACKBLAZE_DRIVE_STATS"})
            readings.append({"reading_id":f"{source_date}-{eid}","equipment_id":eid,"timestamp":f"{source_date} 00:00:00","air_temperature_k":round(temperature+273.15,2) if temperature else None,"process_temperature_k":round(temperature+273.15,2) if temperature else None,"rotational_speed_rpm":None,"torque_nm":None,"tool_wear_min":round(smart_value(row,"smart_9_raw")*60,2),"smart_5_raw":smart_value(row,"smart_5_raw"),"smart_187_raw":smart_value(row,"smart_187_raw"),"smart_188_raw":smart_value(row,"smart_188_raw"),"smart_197_raw":smart_value(row,"smart_197_raw"),"smart_198_raw":smart_value(row,"smart_198_raw"),"capacity_bytes":capacity,"failure":int(failed),"data_origin":"BACKBLAZE_DRIVE_STATS"})
            risks.append({"equipment_id":eid,"risk_score":risk,"data_origin":"BACKBLAZE_SMART_HEURISTIC_NOT_MODEL_OUTPUT"})
            rules.append({"equipment_id":eid,"inspection_cost_cny":180,"repair_cost_cny":1200,"inspection_duration_h":1,"assumed_failure_loss_cny":4500,"repair_duration_h":3,"required_staff_count":1,"data_origin":"LOCAL_SIMULATION_ASSUMPTION"})
            if failed: failures.append({"maintenance_id":f"FAIL-{source_date}-{eid}","equipment_id":eid,"maintenance_type":"硬盘故障记录","maintenance_date":source_date,"data_origin":"BACKBLAZE_DRIVE_STATS"})
    if not equipment: raise ValueError("原始 CSV 没有可同步记录")
    staff=[{"staff_id":f"TECH-{i:02d}","staff_name":f"模拟维护人员{i:02d}","available_hours":8,"data_origin":"LOCAL_SIMULATION_ASSUMPTION"} for i in range(1,13)]
    models=sorted({e["equipment_name"] for e in equipment})
    orders=[{"order_id":f"MODEL-{i:03d}","equipment_id":next(e["equipment_id"] for e in equipment if e["equipment_name"]==m),"order_name":m,"data_origin":"LOCAL_SIMULATION_ASSUMPTION"} for i,m in enumerate(models,1)]
    scenarios=[{"scenario_id":"BB-BASE","scenario_name":"Backblaze 日快照基准","maintenance_budget_cny":50000,"risk_threshold":.4,"available_staff_count":12,"max_downtime_h":72},{"scenario_id":"BB-STRICT","scenario_name":"高风险优先","maintenance_budget_cny":30000,"risk_threshold":.7,"available_staff_count":8,"max_downtime_h":48}]
    return {"equipment":equipment,"readings":readings,"maintenance_rules":rules,"maintenance_history":failures,"staff":staff,"orders":orders,"scenarios":scenarios,"demo_risks":risks},source_date

def sync_status():
    return {"status":settings_get("sync_status","not_synced"),"last_sync_at":settings_get("last_sync_at"),"source_date":settings_get("source_date"),"source_name":settings_get("source_name","MetroPT-3 Air Compressor"),"source_url":settings_get("source_url",""),"record_count":int(settings_get("record_count","0") or 0),"device_count":int(settings_get("device_count","0") or 0),"error":settings_get("sync_error"),"database":str(DB),"data_origin":settings_get("data_origin","UCI_METROPT3_REAL_OPERATIONAL")}

@app.get("/api/sync/status")
def get_sync_status(): return sync_status()

@app.post("/api/sync/backblaze")
def sync_backblaze():
    if os.getenv("FACTORYPULSE_ENABLE_LEGACY_FIXTURES")!="1": raise HTTPException(410,"旧实验集已退役；请载入唯一最终模型验证集")
    if not BACKBLAZE_DATA_FILE.exists(): raise HTTPException(404,f"未找到原始数据文件：{BACKBLAZE_DATA_FILE}")
    with _lock,connect() as c:
        settings_set_many(c,{"sync_status":"syncing","sync_error":""})
    try:
        data,source_date=transform_backblaze(BACKBLAZE_DATA_FILE)
        synced_at=datetime.now(timezone.utc).isoformat()
        with _lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            archive_current_dataset(c)
            for name,recs in data.items():
                c.execute("DELETE FROM records WHERE table_name=?",(name,))
                c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,default=str,separators=(",",":"))) for i,r in enumerate(recs)])
            settings_set_many(c,{"sync_status":"synced","last_sync_at":synced_at,"source_date":source_date,"source_name":BACKBLAZE_DATA_FILE.name,"record_count":len(data["readings"]),"device_count":len(data["equipment"]),"sync_error":"","import_filename":""})
        return {"success":True,"counts":{k:len(v) for k,v in data.items()},**sync_status()}
    except Exception as exc:
        with _lock,connect() as c: settings_set_many(c,{"sync_status":"error","sync_error":str(exc)[:300]})
        raise HTTPException(422,"同步失败："+str(exc)[:180])

@app.post("/api/sync/cnc-demo")
def sync_cnc_demo():
    if os.getenv("FACTORYPULSE_ENABLE_LEGACY_FIXTURES")!="1": raise HTTPException(410,"旧实验集已退役；请载入唯一最终模型验证集")
    """Load a deterministic CNC workflow dataset; never presented as field data."""
    try:
        data,source_date=build_cnc_demo(); synced_at=datetime.now(timezone.utc).isoformat()
        with _lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            archive_current_dataset(c)
            for name,recs in data.items():
                c.execute("DELETE FROM records WHERE table_name=?",(name,))
                c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,default=str,separators=(",",":"))) for i,r in enumerate(recs)])
            pass  # Retain operational records and audit history across data replacement.
            settings_set_many(c,{"sync_status":"synced","last_sync_at":synced_at,"source_date":source_date,"source_name":"CNC连续工况演示数据","source_url":"","record_count":len(data["readings"]),"device_count":len(data["equipment"]),"sync_error":"","import_filename":"","data_origin":"SYNTHETIC_CNC_DEMO"})
            initialize_demo_stock(c,data,inventory.current_scope(c))
        _analytics_cache.update({"key":None,"devices":{},"summary":{}})
        audit("dataset_synced","CNC-DEMO",{"records":len(data["readings"]),"devices":len(data["equipment"]),"origin":"synthetic"})
        return {"success":True,"counts":{k:len(v) for k,v in data.items()},**sync_status()}
    except Exception as exc:
        raise HTTPException(422,"数控机床演示数据生成失败："+str(exc)[:180])

@app.post("/api/sync/model-validation")
def sync_model_validation():
    """An explicit opt-in fixture; previous datasets and work orders are retained."""
    security.require_roles("admin","manager")
    data,source_date=load_acceptance_dataset()
    validate(data)
    synced_at=datetime.now(timezone.utc).isoformat()
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        archive_current_dataset(c)
        for name,recs in data.items():
            c.execute("DELETE FROM records WHERE table_name=?",(name,))
            c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,separators=(",",":"))) for i,r in enumerate(recs)])
        settings_set_many(c,{"sync_status":"synced","last_sync_at":synced_at,"source_date":source_date,"source_name":"CNC 多故障模型验证集（模拟）","source_url":"","record_count":len(data["readings"]),"device_count":len(data["equipment"]),"sync_error":"","import_filename":"","data_origin":MODEL_VALIDATION_ORIGIN})
        initialize_demo_stock(c,data,inventory.current_scope(c))
    _analytics_cache.update({"key":None,"devices":{},"summary":{}})
    audit("dataset_synced","MODEL-VALIDATION",{"records":len(data["readings"]),"devices":len(data["equipment"]),"origin":MODEL_VALIDATION_ORIGIN})
    return {"success":True,"counts":{key:len(value) for key,value in data.items()},**sync_status()}

@app.post("/api/sync/nasa-ims")
def sync_nasa_ims():
    if os.getenv("FACTORYPULSE_ENABLE_LEGACY_FIXTURES")!="1": raise HTTPException(410,"旧实验集已退役；请载入唯一最终模型验证集")
    """Load locally downloaded NASA IMS vibration data as the primary dataset."""
    try:
        data,source_date=build_nasa_ims(); synced_at=datetime.now(timezone.utc).isoformat()
        with _lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            archive_current_dataset(c)
            for name,recs in data.items():
                c.execute("DELETE FROM records WHERE table_name=?",(name,))
                c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,default=str,separators=(",",":"))) for i,r in enumerate(recs)])
            pass  # Retain operational records and audit history across data replacement.
            settings_set_many(c,{"sync_status":"synced","last_sync_at":synced_at,"source_date":source_date,"source_name":"NASA IMS Bearings · 最新15天","source_url":"https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/","record_count":len(data["readings"]),"device_count":len(data["equipment"]),"sync_error":"","import_filename":"NASA IMS Bearings · latest 15 days","data_origin":"NASA_IMS_BEARING_RUN_TO_FAILURE"})
            initialize_demo_stock(c,data,inventory.current_scope(c))
        _analytics_cache.update({"key":None,"devices":{},"summary":{}})
        audit("dataset_synced","NASA-IMS",{"records":len(data["readings"]),"devices":len(data["equipment"]),"origin":"NASA IMS"})
        return {"success":True,"counts":{k:len(v) for k,v in data.items()},**sync_status()}
    except Exception as exc:
        raise HTTPException(422,"NASA IMS 数据载入失败："+str(exc)[:180])

@app.post("/api/sync/metropt3")
def sync_metropt3():
    if os.getenv("FACTORYPULSE_ENABLE_LEGACY_FIXTURES")!="1": raise HTTPException(410,"旧实验集已退役；请载入唯一最终模型验证集")
    """Load six months of real MetroPT-3 compressor operation as the primary dataset."""
    try:
        data,source_date=build_metropt3(); synced_at=datetime.now(timezone.utc).isoformat()
        with _lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            archive_current_dataset(c)
            for name,recs in data.items():
                c.execute("DELETE FROM records WHERE table_name=?",(name,))
                c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,default=str,separators=(",",":"))) for i,r in enumerate(recs)])
            pass  # Retain operational records and audit history across data replacement.
            settings_set_many(c,{"sync_status":"synced","last_sync_at":synced_at,"source_date":source_date,"source_name":"MetroPT-3 · 2020-02 至 2020-08","source_url":"https://archive.ics.uci.edu/dataset/791/metropt%2B3%2Bdataset","record_count":len(data["readings"]),"device_count":len(data["equipment"]),"sync_error":"","import_filename":"MetroPT-3 Air Compressor · 10分钟长期序列","data_origin":"UCI_METROPT3_REAL_OPERATIONAL"})
            initialize_demo_stock(c,data,inventory.current_scope(c))
        _analytics_cache.update({"key":None,"devices":{},"summary":{}})
        audit("dataset_synced","METROPT3",{"records":len(data["readings"]),"devices":len(data["equipment"]),"origin":"UCI MetroPT-3"})
        return {"success":True,"counts":{k:len(v) for k,v in data.items()},**sync_status()}
    except Exception as exc:
        with _lock,connect() as c: settings_set_many(c,{"sync_status":"error","sync_error":str(exc)[:300]})
        raise HTTPException(422,"MetroPT-3 数据载入失败："+str(exc)[:180])
@app.post("/api/import")
def import_excel(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"): raise HTTPException(400,"仅支持 .xlsx 工作簿")
    try:
        book=load_workbook(file.file,read_only=True,data_only=True)
        data={}
        for name,(sheet,required) in TABLES.items():
            if sheet not in book.sheetnames: raise ValueError(f"缺少工作表: {sheet}")
            iterator=book[sheet].values
            headers=[str(h).strip() if h is not None else "" for h in next(iterator)]
            missing=set(required)-set(headers)
            if missing: raise ValueError(f"{sheet} 缺少字段: {', '.join(sorted(missing))}")
            parsed=[]
            for row_index,values in enumerate(iterator,start=2):
                if all(v is None for v in values): continue
                rec={}
                for k,v in zip(headers,values):
                    if not k: continue
                    rec[k]=v.isoformat(sep=" ") if isinstance(v,datetime) else v
                parsed.append(rec)
            data[name]=parsed
        book.close()
        validate(data)
    except (ValueError,StopIteration) as e: raise HTTPException(422,str(e))
    except Exception as e: raise HTTPException(422,f"工作簿读取失败: {str(e)[:160]}")
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        archive_current_dataset(c)
        for name,recs in data.items():
            c.execute("DELETE FROM records WHERE table_name=?",(name,))
            c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,default=str)) for i,r in enumerate(recs)])
        settings_set_many(c,{"import_filename":file.filename,"last_sync_at":datetime.now(timezone.utc).isoformat(),"sync_status":"synced","source_name":file.filename,"source_date":max((str(row.get("timestamp","")) for row in data["readings"]),default="")[:10],"data_origin":"USER_WORKBOOK_UNVERIFIED","record_count":len(data["readings"]),"device_count":len(data["equipment"]),"source_url":"","sync_error":""})
    return {"success":True,"filename":file.filename,"counts":{k:len(v) for k,v in data.items()},"data_origin":"synthetic_test_workbook"}

async def ai_mapping_suggestions(mapping:list[dict]) -> tuple[list[dict],str]:
    base=settings_get("ai_base_url"); model=settings_get("ai_model")
    if not (_api_key and base and model): return mapping,"local_rules"
    safe_columns=[{"source_column":item["source_column"],"samples":item["samples"],"local_target":item["target_field"],"local_confidence":item["confidence"]} for item in mapping]
    prompt=("你是工业数据字段映射器。只能把源字段映射到以下标准字段之一，无法判断则target_field为空。"
            f"标准字段：{json.dumps(STANDARD_FIELDS,ensure_ascii=False)}。"
            "返回纯JSON数组，每项含source_column,target_field,confidence(0到1),reason。不要生成源数据中不存在的字段。源字段："
            +json.dumps(safe_columns,ensure_ascii=False,default=str))
    try:
        async with httpx.AsyncClient(timeout=25,follow_redirects=False,trust_env=False) as client:
            response=await client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+_api_key},json={"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0,"max_tokens":1800})
        if response.status_code>=400: return mapping,"local_rules_ai_unavailable"
        content=response.json()["choices"][0]["message"]["content"].strip()
        match=re.search(r"\[[\s\S]*\]",content); suggestions=json.loads(match.group(0) if match else content)
        by_source={str(item.get("source_column")):item for item in suggestions if isinstance(item,dict)}
        for item in mapping:
            suggestion=by_source.get(item["source_column"],{}); target=str(suggestion.get("target_field") or "")
            confidence=num(suggestion.get("confidence"),0)
            if target in STANDARD_FIELDS and confidence>item["confidence"]:
                item.update({"target_field":target,"target_label":STANDARD_FIELDS[target],"confidence":round(min(confidence,1),2),"reason":"AI建议："+str(suggestion.get("reason") or "根据字段名和样例值判断")[:180]})
        return mapping,"local_rules_plus_ai"
    except Exception:
        return mapping,"local_rules_ai_unavailable"

@app.post("/api/import/intelligent/analyze")
async def analyze_industrial_file(file:UploadFile=File(...)):
    if not file.filename: raise HTTPException(400,"缺少文件名")
    suffix=Path(file.filename).suffix.lower()
    if suffix not in (".csv",".xlsx"): raise HTTPException(422,"仅支持 .xlsx 或 .csv 文件")
    session_id=str(uuid.uuid4()); upload_file=IMPORT_SESSION_DIR/(session_id+suffix); session_file=IMPORT_SESSION_DIR/(session_id+".json")
    try:
        with upload_file.open("wb") as target:
            while chunk:=await file.read(1024*1024): target.write(chunk)
        sheet,source_rows=parse_table_path(upload_file,file.filename,sample_only=True); mapping=infer_mapping(source_rows)
        mapping,engine=await ai_mapping_suggestions(mapping)
        used=set()
        for item in mapping:
            target=item["target_field"]
            if target and target in used:
                item.update(target_field="",confidence=0,reason="重复映射，需人工选择另一指标或扩展数值指标")
            elif target: used.add(target)
            item["use_for_prediction"]=bool(item["target_field"] and item["target_field"] not in COMMON)
        session_file.write_text(json.dumps({"filename":file.filename,"sheet":sheet,"upload_path":str(upload_file)},ensure_ascii=False,default=str),encoding="utf-8")
        return {"upload_id":session_id,"filename":file.filename,"sheet":sheet,"row_count":None,"sampled_row_count":len(source_rows),"mapping":mapping,"profiles":PROFILES,"metadata_fields":COMMON,"standard_fields":STANDARD_FIELDS,"standard_units":STANDARD_UNITS,"mapping_engine":engine,"ai_used":engine=="local_rules_plus_ai","privacy_note":"AI仅接收第一行字段名和第二行样例值；确认映射后才读取完整文件"}
    except (ValueError,StopIteration) as exc:
        upload_file.unlink(missing_ok=True); session_file.unlink(missing_ok=True); raise HTTPException(422,str(exc))
    except Exception as exc:
        upload_file.unlink(missing_ok=True); session_file.unlink(missing_ok=True); raise HTTPException(422,"智能解析失败："+str(exc)[:180])

class MappingChoice(BaseModel):
    source_column:str
    target_field:str=""
class IntelligentImportConfirm(BaseModel):
    upload_id:str
    mapping:list[MappingChoice]

@app.post("/api/import/intelligent/confirm")
def confirm_industrial_import(payload:IntelligentImportConfirm):
    try: session_id=str(uuid.UUID(payload.upload_id))
    except ValueError: raise HTTPException(422,"无效的上传会话")
    session_file=IMPORT_SESSION_DIR/(session_id+".json")
    if not session_file.exists(): raise HTTPException(404,"上传会话已失效，请重新分析文件")
    source=json.loads(session_file.read_text(encoding="utf-8")); choices={item.source_column:item.target_field for item in payload.mapping if item.target_field in STANDARD_FIELDS}
    if "timestamp" not in choices.values(): raise HTTPException(422,"必须确认一个采集时间字段")
    targets=list(choices.values())
    if len(targets)!=len(set(targets)): raise HTTPException(422,"同一标准指标只能映射一个源字段")
    upload_path=Path(source.get("upload_path", ""))
    if not upload_path.exists() or upload_path.parent.resolve()!=IMPORT_SESSION_DIR.resolve(): raise HTTPException(404,"上传文件已失效，请重新分析文件")
    try: _,source_rows=parse_table_path(upload_path,source["filename"],sample_only=False)
    except (ValueError,StopIteration) as exc: raise HTTPException(422,str(exc))
    default_id=Path(source["filename"]).stem[:60] or "IMPORTED-EQUIPMENT"
    try: normalized=normalize_rows(source_rows,choices,default_id)
    except ValueError as exc: raise HTTPException(422,str(exc))
    equipment_ids=sorted({row["equipment_id"] for row in normalized})
    equipment=[]; risks=[]
    for equipment_id in equipment_ids:
        device_rows=[row for row in normalized if row["equipment_id"]==equipment_id]; latest=device_rows[-1]
        failed=num(latest.get("failure"))>=1
        equipment.append({"equipment_id":equipment_id,"equipment_name":equipment_id,"equipment_type":"用户导入工业设备","status":"故障" if failed else str(latest.get("status") or "运行中"),"production_line":str(latest.get("production_line") or "未分配"),"data_origin":"AI_ASSISTED_USER_IMPORT"})
        risks.append({"equipment_id":equipment_id,"risk_score":.98 if failed else .05,"data_origin":"IMPORTED_FAILURE_BASELINE"})
    rules=[{"equipment_id":eid,"inspection_cost_cny":300,"repair_cost_cny":2000,"inspection_duration_h":1,"repair_duration_h":3,"assumed_failure_loss_cny":10000,"required_staff_count":1,"required_skill":"机修","data_origin":"SIMULATED_BUSINESS_DATA"} for eid in equipment_ids]
    tables={"equipment":equipment,"readings":normalized,"maintenance_rules":rules,"maintenance_history":[],"staff":[{"staff_id":"IMPORT-TECH-01","staff_name":"待配置维修人员","skills":"机修","available_hours":8,"data_origin":"SIMULATED_BUSINESS_DATA"}],"orders":[{"order_id":f"IMPORT-ORDER-{i+1:03d}","equipment_id":eid,"data_origin":"SIMULATED_BUSINESS_DATA"} for i,eid in enumerate(equipment_ids)],"scenarios":[{"scenario_id":"IMPORT-BASE","scenario_name":"导入数据基础情景","maintenance_budget_cny":10000,"risk_threshold":.35,"available_staff_count":1,"max_downtime_h":8,"data_origin":"SIMULATED_BUSINESS_DATA"}],"demo_risks":risks}
    synced_at=datetime.now(timezone.utc).isoformat()
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        archive_current_dataset(c)
        for name,recs in tables.items():
            c.execute("DELETE FROM records WHERE table_name=?",(name,)); c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(row,ensure_ascii=False,default=str,separators=(",",":"))) for i,row in enumerate(recs)])
        pass  # Retain operational records and audit history across data replacement.
        settings_set_many(c,{"sync_status":"synced","last_sync_at":synced_at,"source_date":max((str(row["timestamp"]) for row in normalized),default="")[:10],"source_name":source["filename"],"source_url":"","record_count":len(normalized),"device_count":len(equipment),"sync_error":"","import_filename":source["filename"],"data_origin":"AI_ASSISTED_USER_IMPORT"})
    _analytics_cache.update({"key":None,"devices":{},"summary":{}}); audit("intelligent_import",source["filename"],{"rows":len(normalized),"devices":len(equipment),"mapping":choices})
    upload_path.unlink(missing_ok=True); session_file.unlink(missing_ok=True)
    return {"success":True,"filename":source["filename"],"record_count":len(normalized),"device_count":len(equipment),"data_origin":"AI_ASSISTED_USER_IMPORT"}
def analytics_snapshot(all_readings, risks):
    with _analytics_lock:
        version=(str(DB),settings_get("last_sync_at"),json.dumps(load_training_config().model_dump(),sort_keys=True))
        if version[1] and _analytics_cache.get("source_version")==version and _analytics_cache.get("key") is not None:
            return _analytics_cache
        result=_compute_analytics_snapshot(all_readings,risks)
        result["source_version"]=version
        return result


def _compute_analytics_snapshot(all_readings, risks):
    fingerprint=hashlib.sha256(json.dumps(all_readings,ensure_ascii=False,sort_keys=True,default=str,separators=(",",":")).encode()).hexdigest()
    training_config=load_training_config().model_dump()
    key=(str(DB),fingerprint,settings_get("last_sync_at"),json.dumps(training_config,sort_keys=True))
    if _analytics_cache["key"]==key: return _analytics_cache
    algorithm_sha256=hashlib.sha256(b"".join((PROJECT_ROOT/"backend"/name).read_bytes() for name in ("main.py","analytics.py","adaptive_training.py","field_profiles.py"))).hexdigest()
    # Reuse only snapshots matching data, configuration AND current analysis implementation.
    with connect() as c:
        previous=c.execute("SELECT content FROM prediction_runs WHERE dataset_version=? ORDER BY created_at DESC",(settings_get("last_sync_at"),)).fetchall()
    for saved in previous:
        try: evidence=json.loads(saved["content"])
        except (ValueError,TypeError): continue
        if evidence.get("input_sha256")==fingerprint and evidence.get("training_config")==training_config and evidence.get("algorithm_sha256")==algorithm_sha256:
            _analytics_cache.update(key=key,devices=evidence["devices"],summary=evidence["summary"])
            return _analytics_cache
    if settings_get("data_origin")=="UCI_METROPT3_REAL_OPERATIONAL": label_observed_history(all_readings)
    ewma=ewma_scores(all_readings)
    model=xgboost_with_shap(all_readings)
    devices={}
    for reading in all_readings:
        eid=str(reading.get("equipment_id",""))
        rule=num(risks.get(eid,{}).get("risk_score"))
        ewma_item=ewma.get(eid,{"score":None,"status":"insufficient_history","samples":0,"alpha":.35})
        model_score=model.predictions.get(eid)
        devices[eid]={"rule_risk":rule,"ewma_risk":ewma_item.get("score"),"ewma_status":ewma_item.get("status"),"ewma_samples":ewma_item.get("samples",0),"model_risk":model_score,"combined_risk":model_score if model_score is not None else (ewma_item.get("score") if ewma_item.get("score") is not None else rule),"shap_top":model.explanations.get(eid,[]),"scoring_details":{"model":model.calculations.get(eid),"trend":ewma_item}}
    summary={"rule_engine":"baseline_only","ewma":"ready" if any(item.get("score") is not None for item in ewma.values()) else "insufficient_history","xgboost":model.status,"shap":"ready" if model.explanations else "unavailable","training_rows":model.training_rows,"positive_labels":model.positives,"label_basis":model.label_basis,"message":model.message,"scoring_policy":"model_else_trend_else_rule_no_fusion","evaluation_scope":"模型分数及验证集阈值；规则和趋势回退未验证，不继承模型成绩","model_version":model.model_version,"evaluation":model.evaluation}
    _analytics_cache.update({"key":key,"devices":devices,"summary":summary})
    with connect() as c:
        run_id=uuid.uuid5(uuid.NAMESPACE_URL,str(key)+model.model_version+algorithm_sha256).hex
        evidence={"algorithm_sha256":algorithm_sha256,"training_artifact":model.artifact,"input_sha256":fingerprint,"training_config":training_config,"summary":summary,"devices":devices,"replay":model.replay,"source_readings":{str(row["equipment_id"]):{"reading_id":row.get("reading_id"),"timestamp":row.get("timestamp")} for row in sorted(all_readings,key=lambda r:str(r.get("timestamp","")))}}
        c.execute("INSERT OR IGNORE INTO prediction_runs VALUES (?,?,?,?,?)",(run_id,settings_get("last_sync_at"),model.model_version,json.dumps(evidence,ensure_ascii=False,default=str),datetime.now(timezone.utc).isoformat()))
    return _analytics_cache

def snapshot():
    # Training blocks this request, but does not hold the business mutation lock.
    if settings_get("sync_status")=="synced":
        for attempt in range(3):
            with _lock:
                version=settings_get("last_sync_at")
                readings=rows("readings")
                risks={str(r["equipment_id"]):r for r in rows("demo_risks")}
            analytics_snapshot(readings,risks)
            with _lock:
                if settings_get("last_sync_at")==version:
                    return _snapshot_consistent()
        raise HTTPException(409,"训练期间数据版本已变化，请刷新")
    with _lock:
        return _snapshot_consistent()


def _snapshot_consistent():
    equipment=rows("equipment")
    risks={str(r["equipment_id"]):r for r in rows("demo_risks")}
    all_readings=rows("readings")
    readings={}
    for r in all_readings:
        eid=str(r["equipment_id"])
        if eid not in readings or str(r.get("timestamp",""))>str(readings[eid].get("timestamp","")): readings[eid]=r
    analytics=analytics_snapshot(all_readings,risks) if settings_get("sync_status")=="synced" else {"devices":{},"summary":{"rule_engine":"ready","ewma":"not_applicable","xgboost":"not_applicable","shap":"not_applicable","message":"Excel 导入模式沿用工作簿风险分数"}}
    with connect() as c:
        alert_states={r["equipment_id"]:dict(r) for r in c.execute("SELECT * FROM alerts WHERE dataset_version=? ORDER BY updated_at ASC",(settings_get("last_sync_at"),))}
    order_map={}
    for order in rows("orders"):
        order_map.setdefault(str(order.get("equipment_id","")),[]).append(order)
    output=[]
    for e in equipment:
        eid=str(e["equipment_id"]); risk=risks.get(eid,{}); reading=readings.get(eid,{})
        rule_score=num(risk.get("risk_score")); analysis=analytics["devices"].get(eid,{})
        score=num(analysis.get("model_risk"),num(analysis.get("ewma_risk"),rule_score))
        level="高" if score>.35 else "中" if score>=.15 else "低"
        threshold=analytics.get("summary",{}).get("evaluation",{}).get("threshold")
        if analysis.get("model_risk") is not None and threshold is None:
            threshold=next((item["evaluation"].get("threshold") for item in analytics.get("summary",{}).get("evaluation",{}).get("profile_results",[]) if eid in item.get("equipment_ids",[])),None)
        review_required=bool(score>=threshold) if analysis.get("model_risk") is not None and threshold is not None else score>=.15
        evidence=[]
        if reading.get("vibration_g") not in (None,""): evidence.append(f"振动RMS {num(reading.get('vibration_g')):.4f} g")
        elif num(reading.get("vibration_mm_s"))>2.5: evidence.append(f"振动 {num(reading.get('vibration_mm_s')):.2f} mm/s")
        if reading.get("motor_current_a") not in (None,""): evidence.append(f"电机电流 {num(reading.get('motor_current_a')):.2f} A")
        if reading.get("tp3_bar") not in (None,""): evidence.append(f"压力TP3 {num(reading.get('tp3_bar')):.2f} bar")
        if reading.get("oil_temperature_c") not in (None,""): evidence.append(f"油温 {num(reading.get('oil_temperature_c')):.1f} ℃")
        elif reading.get("process_temperature_k") not in (None,""): evidence.append(f"工艺温度 {num(reading.get('process_temperature_k'))-273.15:.1f} ℃")
        if num(reading.get("spindle_load_pct"))>70: evidence.append(f"主轴负载 {num(reading.get('spindle_load_pct')):.1f}%")
        if not evidence and "_feature_fields" in reading:
            catalog=json.loads(settings_get("sensor_catalog","{}"))
            evidence=[f"{catalog.get(field,{}).get('label',STANDARD_FIELDS.get(field,field))} {num(reading[field]):.3g} {catalog.get(field,{}).get('unit',STANDARD_UNITS.get(field,''))}" for field in reading["_feature_fields"] if reading.get(field) not in (None,"")][:3]
            evidence=evidence or ["没有可用监测读数"]
        else: evidence=evidence or ["当前指标未越过业务阈值"]
        state=alert_states.get(eid,{})
        metro=reading.get("data_origin")=="UCI_METROPT3_REAL_OPERATIONAL"
        action=("检查空气泄漏、压力回路与进气阀" if level=="高" else "复核压力、油温和电流趋势") if metro else ("检查主轴轴承、润滑与刀具状态" if level=="高" else "复核工况并持续观察")
        if reading.get("_equipment_profile") not in (None,"cnc"):
            action="复核监测趋势、历史故障与设备手册，再确定检修动作"
        horizon=int(num(reading.get("prediction_horizon_hours"),168))
        available=not (settings_get("data_origin")=="USER_IMPORTED_OPERATIONAL" and analysis.get("model_risk") is None and analysis.get("ewma_risk") is None and num(reading.get("failure"))!=1)
        if not available: level="待评估"
        window=(f"未来{horizon//24}天" if horizon%24==0 else f"未来{horizon}小时") if analysis.get("model_risk") is not None else "当前工况参考"
        output.append({**e,**analysis,"risk_score":score,"scoring_details":{**analysis.get("scoring_details",{}),"rule":rule_details(risk,reading),"selected_source":"model" if analysis.get("model_risk") is not None else "trend" if analysis.get("ewma_risk") is not None else "rule"},"review_required":review_required,"model_alert_threshold":threshold,"risk_available":available,"risk_level":level,"risk_origin":"TIME_SPLIT_MODEL_WITH_RULE_BASELINE" if analysis.get("model_risk") is not None else risk.get("data_origin","RULE_OR_TREND_ONLY"),"latest_reading":reading,"prediction_at":reading.get("timestamp"),"prediction_window":window,"risk_semantics":("模型分数用于检查排序，不是故障概率；等级线仅作展示，模型提醒线见历史验证" if analysis.get("model_risk") is not None else "规则或趋势参考，未通过模型历史评估，不继承模型成绩") if available else "证据不足，尚不能评估；不能解读为低风险","model_version":analytics.get("summary",{}).get("model_version","workbook-provided-score"),"primary_evidence":evidence,"recommended_action":action,"recommended_by":reading.get("timestamp"),"affected_orders":[str(o.get("order_id")) for o in order_map.get(eid,[])],"alert_status":state.get("status","待确认" if level in ("高","中") else "观察"),"alert_note":state.get("note","")})
    return output
@app.get("/api/overview")
def overview(limit:int=500):
    if not 1<=limit<=2000: raise HTTPException(400,"limit须在1到2000之间")
    devices=snapshot(); scores=[d["risk_score"] for d in devices if d.get("risk_available",True)]
    ranked=sorted([device for device in devices if device.get("risk_available",True)],key=lambda device:device["risk_score"],reverse=True)
    window=devices[0].get("prediction_window","当前窗口") if devices else "当前窗口"
    return {"devices":devices[:limit],"top_risk_devices":ranked[:100],"counts":{t:len(rows(t)) for t in TABLES},"metrics":{"total":len(devices),"high":sum(s>.35 for s in scores),"warning":sum(.15<=s<=.35 for s in scores),"unknown":sum(not d.get("risk_available",True) for d in devices),"avg_risk":round(sum(scores)/len(scores),3) if scores else None},"filename":settings_get("import_filename"),"risk_source":f"{window}模型评分；规则与趋势单独展示，评分未经概率校准" if settings_get("sync_status")=="synced" else "Excel 提供风险评分（非训练模型预测）","analytics":_analytics_cache["summary"] if settings_get("sync_status")=="synced" else {"rule_engine":"baseline_only","ewma":"not_applicable","xgboost":"not_applicable","shap":"not_applicable"},"sync":sync_status(),"returned_devices":min(len(devices),limit)}
@app.get("/api/records/{table_name}")
def records(table_name:str,limit:int=500):
    if table_name not in TABLES: raise HTTPException(404,"Unknown table")
    if not 1<=limit<=25000: raise HTTPException(400,"limit须在1到25000之间")
    return {"records":rows(table_name,limit),"total":len(rows(table_name))}

def _history_signal(row:dict)->tuple[float|None,str,str]:
    for key,label,unit in (("vibration_g","振动 RMS","g"),("vibration_mm_s","振动速度","mm/s"),("motor_current_a","电机电流","A"),("oil_temperature_c","油温","°C"),("process_temperature_k","工艺温度","K")):
        if row.get(key) not in (None,""):
            return num(row.get(key)),label,unit
    catalog=json.loads(settings_get("sensor_catalog","{}"))
    for key in row.get("_feature_fields",[]) or [key for key in row if key in STANDARD_FIELDS or is_custom(key)]:
        if key not in COMMON and row.get(key) not in (None,""):
            entry=catalog.get(key,{})
            return num(row[key]),entry.get("label",STANDARD_FIELDS.get(key,key)),entry.get("unit",STANDARD_UNITS.get(key,""))
    return None,"设备指标",""

@app.get("/api/equipment/{equipment_id}/history")
def equipment_history(equipment_id:str,points:int=360):
    if not 24<=points<=1200: raise HTTPException(400,"points须在24到1200之间")
    series=sorted((row for row in rows("readings") if str(row.get("equipment_id"))==equipment_id),key=lambda row:str(row.get("timestamp","")))
    if not series: raise HTTPException(404,"该设备没有运行记录")
    signal_values=[]; enriched=[]
    for row in series:
        signal,label,unit=_history_signal(row)
        ordered=sorted(signal_values[-144:])
        low=ordered[int((len(ordered)-1)*.10)] if ordered else 0.
        high=ordered[int((len(ordered)-1)*.95)] if ordered else 1.
        severity=max(0.,min(1.,((signal if signal is not None else low)-low)/max(high-low,1e-9)))
        if signal is not None: signal_values.append(signal)
        risk=.03+.42*severity
        if row.get("tp3_bar") not in (None,"") and row.get("reservoirs_bar") not in (None,""): risk+=min(abs(num(row.get("tp3_bar"))-num(row.get("reservoirs_bar")))*.2,.25)
        if num(row.get("oil_temperature_c"))>75: risk+=min((num(row.get("oil_temperature_c"))-75)*.015,.2)
        if num(row.get("spindle_load_pct"))>70: risk+=min((num(row.get("spindle_load_pct"))-70)*.01,.2)
        enriched.append({"timestamp":row.get("timestamp"),"risk":round(min(risk,1)*100,2) if signal is not None else None,"signal":signal,"signal_label":label,"signal_unit":unit,"temperature_k":row.get("process_temperature_k"),"oil_temperature_c":row.get("oil_temperature_c"),"motor_current_a":row.get("motor_current_a"),"tp3_bar":row.get("tp3_bar"),"vibration_g":row.get("vibration_g"),"failure":None if row.get("failure") in (None,"") else int(num(row.get("failure")))})
    fault_intervals=[]
    active_fault=None
    for point in enriched:
        if point["failure"]==1:
            if active_fault is None:
                active_fault={"start_at":point["timestamp"],"end_at":point["timestamp"],"source":"原始故障标记"}
                fault_intervals.append(active_fault)
            active_fault["end_at"]=point["timestamp"]
        else:
            active_fault=None
    if len(enriched)>points:
        # Keep actual coverage endpoints; interior buckets retain peak observed risk.
        interior=enriched[1:-1];buckets=points-2;step=len(interior)/buckets;sampled=[]
        for index in range(buckets):
            group=interior[int(index*step):max(int((index+1)*step),int(index*step)+1)]
            sampled.append(max(group,key=lambda item:item["risk"] if item["risk"] is not None else -1))
        enriched=[enriched[0],*sampled,enriched[-1]]
    maintenance=sorted((row for row in rows("maintenance_history") if str(row.get("equipment_id"))==equipment_id),key=lambda row:str(row.get("maintenance_date","")),reverse=True)
    lineage=[settings_get("last_sync_at")]
    try: lineage.extend(json.loads(settings_get("data_lineage","[]")))
    except (ValueError,TypeError): pass
    with connect() as c:
        events=[json.loads(row["content"]) for row in c.execute("SELECT content,dataset_version FROM maintenance_events WHERE equipment_id=?",(equipment_id,)) if row["dataset_version"] in lineage]
    known={record.get("maintenance_id") for record in maintenance}
    maintenance.extend(record for record in events if record["maintenance_id"] not in known)
    maintenance.sort(key=lambda row:str(row.get("maintenance_date","")),reverse=True)
    first_signal=_history_signal(series[0])
    return {"equipment_id":equipment_id,"total_readings":len(series),"returned_points":len(enriched),"start_at":series[0].get("timestamp"),"end_at":series[-1].get("timestamp"),"signal_label":first_signal[1],"signal_unit":first_signal[2],"risk_basis":"历史工况规则分（仅用当时及此前读数，不是模型预测）","series":enriched,"maintenance":maintenance,"fault_intervals":fault_intervals,"aggregation":"首尾原始时间点与内部窗口最高风险点；故障区间由聚合前的完整标签提取"}

class MaintenanceRuleUpdate(BaseModel):
    maintenance_hours:float=Field(ge=0,le=10000)
    maintenance_cost_cny:float=Field(ge=0,le=100000000)

def update_maintenance_rules(updates:list[dict]):
    current=rows("maintenance_rules")
    by_id={str(item.get("equipment_id")):item for item in current}
    equipment_ids={str(item.get("equipment_id")) for item in rows("equipment")}
    changed=0
    for update in updates:
        equipment_id=str(update.get("equipment_id","")).strip()
        if equipment_id not in equipment_ids: raise HTTPException(422,f"未知设备编号：{equipment_id}")
        item=by_id.setdefault(equipment_id,{"equipment_id":equipment_id})
        item.update({"maintenance_hours":num(update.get("maintenance_hours")),"maintenance_cost_cny":num(update.get("maintenance_cost_cny")),"data_origin":"USER_MAINTENANCE_INPUT","configuration_status":"configured"})
        changed+=1
    records=list(by_id.values())
    with _lock,connect() as c:
        revision=int(settings_get("business_revision","0"))+1
        settings_set_many(c,{"business_revision":revision})
        c.execute("DELETE FROM records WHERE table_name='maintenance_rules'")
        c.executemany("INSERT INTO records(table_name,row_index,content) VALUES ('maintenance_rules',?,?)",[(index,json.dumps(item,ensure_ascii=False)) for index,item in enumerate(records)])
    return changed

@app.put("/api/maintenance-rules/{equipment_id}")
def update_maintenance_rule(equipment_id:str, payload:MaintenanceRuleUpdate):
    update_maintenance_rules([{"equipment_id":equipment_id,**payload.model_dump()}])
    return {"success":True,"equipment_id":equipment_id,**payload.model_dump()}

@app.post("/api/import/maintenance")
async def import_maintenance_file(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"): raise HTTPException(400,"请选择 .xlsx 维修参数表")
    try:
        workbook=load_workbook(io.BytesIO(await file.read()),read_only=True,data_only=True)
        sheet=workbook.active
        raw_headers=[str(value or "").strip() for value in next(sheet.iter_rows(values_only=True))]
        aliases={"设备编号":"equipment_id","设备ID":"equipment_id","维修工时":"maintenance_hours","所需维修工时":"maintenance_hours","维修费用":"maintenance_cost_cny","维修费用（元）":"maintenance_cost_cny"}
        headers=[aliases.get(value,value) for value in raw_headers]
        required={"equipment_id","maintenance_hours","maintenance_cost_cny"}
        if not required.issubset(headers): raise ValueError("表头必须包含：设备编号、维修工时、维修费用（元）")
        updates=[]
        for values in sheet.iter_rows(values_only=True):
            row=dict(zip(headers,values))
            if row.get("equipment_id") not in (None,""): updates.append({key:row.get(key) for key in required})
        workbook.close()
        if not updates: raise ValueError("维修参数表没有可导入的数据")
        changed=update_maintenance_rules(updates)
        return {"success":True,"updated":changed,"filename":file.filename}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422,f"维修参数表导入失败：{str(exc)[:160]}")
class SimulationInput(BaseModel):
    model_config={"allow_inf_nan":False}
    scenario_id:Optional[str]=None
    strategy:str="optimized"
    budget:Optional[float]=Field(None,ge=0)
    risk_threshold:Optional[float]=Field(None,ge=0,le=1)
    staff_count:Optional[int]=Field(None,ge=1)
    max_downtime_h:Optional[float]=Field(None,ge=0)
    equipment_ids:Optional[list[str]]=None
    confirmed_priorities:dict[str,float]=Field(default_factory=dict)
@app.post("/api/simulate")
def simulate(inp:SimulationInput):
    with _lock:
        return _simulate_consistent(inp)


def _simulate_consistent(inp:SimulationInput,candidate_only=False,read_only=False,prepared_devices=None,skip_preselection=False):
    devices=prepared_devices if prepared_devices is not None else snapshot()
    if not devices: raise HTTPException(400,"请先导入Excel测试工作簿")
    scenarios=rows("scenarios")
    if not scenarios: raise HTTPException(422,"请先在维护资源中填写预算、人数和累计停机工时限制")
    if inp.scenario_id and not any(item.get("scenario_id")==inp.scenario_id for item in scenarios): raise HTTPException(404,"所选排程条件已不存在，请刷新并重新选择")
    s=next((i for i in scenarios if i.get("scenario_id")==inp.scenario_id),scenarios[0] if scenarios else {})
    budget=inp.budget if inp.budget is not None else num(s.get("maintenance_budget_cny"),3000)
    threshold=inp.risk_threshold if inp.risk_threshold is not None else num(s.get("risk_threshold"),.65)
    staff_count=inp.staff_count if inp.staff_count is not None else int(num(s.get("available_staff_count"),2))
    max_hours=inp.max_downtime_h if inp.max_downtime_h is not None else num(s.get("max_downtime_h"),8)
    effect_low=max(0,min(1,num(s.get("scenario_risk_reduction_low"),.25)))
    effect_high=max(effect_low,min(1,num(s.get("scenario_risk_reduction_high"),.65)))
    if inp.strategy not in ("optimized","risk_threshold","fixed_interval"): raise HTTPException(422,"未知策略")
    rules={r["equipment_id"]:r for r in rows("maintenance_rules")}
    with connect() as c:
        # Legacy inventory migration runs on explicit mutations, never read previews.
        scope=inventory.current_scope(c)
        if not candidate_only and not read_only: inventory.seed_legacy_stock(c,scope,rules.values())
        rules={identifier:{**rule,"spare_parts":inventory.available_parts(c,scope,rule.get("spare_parts",[]))} for identifier,rule in rules.items()}
    unconfigured=[identifier for identifier,rule in rules.items() if rule.get("configuration_status")=="required" and (inp.equipment_ids is None or identifier in inp.equipment_ids)]
    if unconfigured: raise HTTPException(422,"请先配置真实维护工时和费用，不能使用猜测参数排程："+"、".join(unconfigured[:10]))
    candidates=[]
    for d in devices:
        if inp.equipment_ids is not None and d["equipment_id"] not in inp.equipment_ids: continue
        if not d.get("risk_available",True) and d["equipment_id"] not in inp.confirmed_priorities: continue
        rule=rules.get(d["equipment_id"],{})
        cost=num(rule.get("maintenance_cost_cny"),num(rule.get("inspection_cost_cny"),250)+num(rule.get("repair_cost_cny"),900))
        hours=num(rule.get("maintenance_hours"),num(rule.get("inspection_duration_h"),2)+num(rule.get("repair_duration_h"),2))
        loss=num(rule.get("assumed_failure_loss_cny"),3000)
        people=max(1,int(num(rule.get("required_staff_count"),1)))
        risk=d["risk_score"] if d.get("risk_available",True) else 0
        priority=max(0,min(1,inp.confirmed_priorities.get(d["equipment_id"],risk)))
        scenario_probability=s.get("assumed_failure_probability")
        benefit_low=effect_low*num(scenario_probability)*loss; benefit_high=effect_high*num(scenario_probability)*loss
        candidates.append({"equipment_id":d["equipment_id"],"equipment_name":d["equipment_name"],"risk":risk,"risk_available":d.get("risk_available",True),"priority_basis":"人工确认的维护需求" if d["equipment_id"] in inp.confirmed_priorities else "工况风险参考分","cost":cost,"hours":hours,"people":people,"required_skill":rule.get("required_skill",d.get("required_skill","机修")),"expected_loss_avoided_low":round(benefit_low,2),"expected_loss_avoided_high":round(benefit_high,2),"priority_score":priority,"net_value":priority,"window_start":rule.get("window_start"),"window_end":rule.get("window_end"),"spare_parts":rule.get("spare_parts",[])})
    if candidate_only:
        return {"selected":candidates,"constraints":{"budget":budget,"risk_threshold":threshold,"staff_count":staff_count,"max_downtime_h":max_hours,"maintenance_effect_range":[effect_low,effect_high]},"summary":{}}
    optimizer_status="not_used"
    if inp.strategy=="optimized":
        pool=sorted((item for item in candidates if item["net_value"]>0),key=lambda x:(x["net_value"]/max(x["cost"],1),x["risk"]),reverse=True)
        selected,optimizer_status=(pool,"feasible") if skip_preselection else cp_sat_select(pool,budget,max_hours,staff_count)
        if optimizer_status in ("optimal","feasible"):
            spent=sum(item["cost"] for item in selected); elapsed=sum(item["hours"] for item in selected)
        else:
            candidates.sort(key=lambda x:(x["net_value"]/max(x["cost"],1),x["risk"]),reverse=True)
    elif inp.strategy=="risk_threshold": candidates.sort(key=lambda x:x["risk"],reverse=True)
    else: candidates.sort(key=lambda x:x["equipment_id"])
    if inp.strategy!="optimized" or optimizer_status not in ("optimal","feasible"):
        selected=[]; spent=0.; elapsed=0.; used_parts={}
        for item in candidates:
            if inp.strategy=="risk_threshold" and (not item.get("risk_available",True) or item["risk"]<threshold): continue
            if inp.strategy=="optimized" and item["net_value"]<=0: continue
            if item["people"]>staff_count or spent+item["cost"]>budget or elapsed+item["hours"]>max_hours: continue
            demand=inventory.quantities(item.get("spare_parts",[]))
            limits={part["part_name"]:int(part.get("available_quantity",0)) for part in item.get("spare_parts",[])}
            if any(used_parts.get(name,0)+quantity>limits[name] for name,quantity in demand.items()): continue
            selected.append(item); spent+=item["cost"]; elapsed+=item["hours"]
            for name,quantity in demand.items(): used_parts[name]=used_parts.get(name,0)+quantity
    baseline=sum(num(s.get("assumed_failure_probability"))*num(rules.get(d["equipment_id"],{}).get("assumed_failure_loss_cny"),3000) for d in devices)
    saved_low=sum(i["expected_loss_avoided_low"] for i in selected); saved_high=sum(i["expected_loss_avoided_high"] for i in selected)
    return {"scenario":s.get("scenario_name","自定义"),"strategy":inp.strategy,"optimizer_status":optimizer_status,"constraints":{"budget":budget,"risk_threshold":threshold,"staff_count":staff_count,"max_downtime_h":max_hours,"maintenance_effect_range":[effect_low,effect_high]},"selected":selected,"summary":{"task_count":len(selected),"maintenance_cost":round(spent,2),"maintenance_hours":round(elapsed,2),"baseline_expected_loss":round(baseline,2) if s.get("assumed_failure_probability") is not None else None,"avoided_loss_range":[round(saved_low,2),round(saved_high,2)],"total_cost_range":[round(baseline-saved_high+spent,2),round(baseline-saved_low+spent,2)],"illustrative_total_cost":round(baseline-saved_low+spent,2) if s.get("assumed_failure_probability") is not None else None,"financial_basis":"explicit_scenario_probability" if s.get("assumed_failure_probability") is not None else "insufficient_parameters"},"disclaimer":"维护收益以情景区间展示，不是因果估计；optimized 使用 CP-SAT 在预算、停机与人员工时约束下选择任务，再由排程接口分配人员和时间。"}

class AlertAction(BaseModel):
    action:str
    note:str=Field(default="",max_length=500)
    defer_until:Optional[datetime]=None
    expected_dataset_version:Optional[str]=None
    prediction_at:Optional[str]=None
    alert_id:Optional[str]=None
    version:Optional[int]=Field(default=None,ge=0)
    request_id:Optional[str]=Field(default=None,min_length=8,max_length=100)


@app.post("/api/alerts/{equipment_id}/action")
def alert_action(equipment_id:str,payload:AlertAction):
    with _lock:
        return _alert_action_consistent(equipment_id,payload)


def _alert_action_consistent(equipment_id,payload):
    mapping={"confirm":"已确认","reject":"已驳回","defer":"已延期","work_order":"已转工单","undo":"待确认"}
    if payload.action not in mapping: raise HTTPException(422,"未知预警操作")
    if payload.action in {"reject","undo"} and not payload.note.strip(): raise HTTPException(422,"驳回必须填写原因")
    if payload.action=="defer" and (payload.defer_until is None or payload.defer_until.tzinfo is None or payload.defer_until<=datetime.now(timezone.utc)): raise HTTPException(422,"延期需填写带时区的未来复核时间")
    device=next((item for item in snapshot() if str(item["equipment_id"])==equipment_id),None)
    if not device: raise HTTPException(404,"设备不存在")
    now=datetime.now(timezone.utc).isoformat();dataset=settings_get("last_sync_at");prediction=str(device.get("prediction_at") or "")
    alert_id="ALERT-"+uuid.uuid5(uuid.NAMESPACE_URL,f"{dataset}/{equipment_id}/{prediction}").hex[:20]
    signature=json.dumps({"equipment_id":equipment_id,**payload.model_dump(mode="json",exclude={"request_id"}),**security.actor_metadata()},sort_keys=True,ensure_ascii=False)
    request_id=payload.request_id or "alert-"+hashlib.sha256((alert_id+signature).encode()).hexdigest()
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        receipt=c.execute("SELECT * FROM operation_requests WHERE request_id=?",(request_id,)).fetchone()
        if receipt:
            if receipt["request_content"]!=signature: raise HTTPException(409,"请求标识已用于不同预警处理")
            return json.loads(receipt["response"])
        current_dataset=c.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
        if (current_dataset[0] if current_dataset else "")!=dataset: raise HTTPException(409,"读取预警后数据已变化，请重新核对")
        if payload.alert_id and payload.alert_id!=alert_id:
            historical=c.execute("SELECT * FROM alerts WHERE alert_id=? AND equipment_id=? AND dataset_version=?",(payload.alert_id,equipment_id,dataset)).fetchone()
            if historical:
                if payload.action=="work_order": raise HTTPException(409,"历史预警需先完成复核；创建维修需求请重新核对当前设备证据")
                if payload.version is None or payload.expected_dataset_version is None or payload.prediction_at is None or not payload.request_id:
                    raise HTTPException(422,"历史预警复核需提供记录编号、数据版本、原采样时间、记录版本及操作编号")
                if not payload.note.strip(): raise HTTPException(422,"历史预警复核需填写处理意见")
                alert_id=historical["alert_id"];prediction=historical["prediction_at"]
        if payload.expected_dataset_version is not None and payload.expected_dataset_version!=dataset: raise HTTPException(409,"数据版本已变化，请重新打开预警核对")
        if payload.prediction_at is not None and payload.prediction_at!=prediction: raise HTTPException(409,"预警采样时间已变化，请重新复核")
        if payload.alert_id is not None and payload.alert_id!=alert_id: raise HTTPException(409,"预警对象已变化，请重新选择")
        existing=c.execute("SELECT * FROM alerts WHERE alert_id=?",(alert_id,)).fetchone()
        if payload.action=="undo":
            if not existing: raise HTTPException(409,"尚无可撤回的复核记录")
            linked=c.execute("SELECT work_order_id,status,content FROM work_orders WHERE json_extract(content,'$.source_alert_id')=?",(alert_id,)).fetchall()
            if any(row["status"] == "已完成" or json.loads(row["content"]).get("actual_start_at") or (row["status"] != "已取消" and not json.loads(row["content"]).get("deleted_at")) for row in linked):
                raise HTTPException(409,"此预警已关联工单，请先处理或删除未执行的维护需求，不能撤销已形成的维修事实")
        current_version=existing["version"] if existing else 0
        if payload.version is not None and payload.version!=current_version: raise HTTPException(409,"预警已由其他人员处理，请刷新后核对")
        version=current_version+1
        c.execute("INSERT OR REPLACE INTO alerts(alert_id,equipment_id,status,note,updated_at,dataset_version,prediction_at,defer_until,version) VALUES (?,?,?,?,?,?,?,?,?)",(alert_id,equipment_id,mapping[payload.action],payload.note,now,dataset,prediction,payload.defer_until.isoformat() if payload.defer_until else None,version))
        work_id=None
        if payload.action=="work_order":
            linked=c.execute("SELECT work_order_id FROM work_orders WHERE json_extract(content,'$.source_alert_id')=? AND json_extract(content,'$.deleted_at') IS NULL AND status NOT IN ('已取消','已完成') ORDER BY updated_at DESC LIMIT 1",(alert_id,)).fetchone()
            if linked: work_id=linked[0]
            else:
                active=c.execute("SELECT * FROM work_orders WHERE equipment_id=? AND json_extract(content,'$.dataset_version')=? AND json_extract(content,'$.deleted_at') IS NULL AND status NOT IN ('已取消','已完成') ORDER BY updated_at DESC LIMIT 1",(equipment_id,dataset)).fetchone()
                if active:
                    content=json.loads(active["content"])
                    if active["status"]!="草稿·待排程" or content.get("source_alert_id"):
                        raise HTTPException(409,f"设备已有未完成工单 {active['work_order_id']}，请先处理该工单，不能重复创建")
                    work_id=active["work_order_id"]
                    content.update(source_alert_id=alert_id,version=content.get("version",1)+1)
                    content.setdefault("execution_history",[]).append({"at":now,"actor":security.identity("设备总管"),"from":active["status"],"to":active["status"],"action":"link_alert","note":"关联预警复核，复用已有人工维修需求"})
                    c.execute("UPDATE work_orders SET content=?,updated_at=? WHERE work_order_id=?",(json.dumps(content,ensure_ascii=False),now,work_id))
                    c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("work_order_link_alert",work_id,json.dumps({"source_alert_id":alert_id,**security.actor_metadata()},ensure_ascii=False),now))
                else:
                    work_id=f"WO-DRAFT-{uuid.uuid4().hex[:12].upper()}"
                    content={"work_order_id":work_id,"equipment_id":equipment_id,"equipment_name":device.get("equipment_name"),"affected_orders":device.get("affected_orders",[]),"maintenance_action":payload.note or device.get("recommended_action"),"priority":"中","order_impact":"待排程确认","created_at":now,"source_alert_id":alert_id,"dataset_version":dataset,"version":1}
                    c.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(work_id,equipment_id,json.dumps(content,ensure_ascii=False),"草稿·待排程",now))
        result={"success":True,"alert_id":alert_id,"equipment_id":equipment_id,"status":mapping[payload.action],"version":version,"work_order_id":work_id,"note":payload.note,"updated_at":now,"next_step":"维护中心" if work_id else "处理记录"}
        c.execute("INSERT INTO operation_requests VALUES (?,?,?)",(request_id,signature,json.dumps(result,ensure_ascii=False)))
        c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("alert_action",alert_id,json.dumps({"equipment_id":equipment_id,**payload.model_dump(mode="json"),"status":mapping[payload.action],"work_order_id":work_id,**security.actor_metadata()},ensure_ascii=False),now))
    return result

@app.get("/api/alerts")
def list_alerts():
    with connect() as c:
        records=[dict(row) for row in c.execute("SELECT * FROM alerts ORDER BY updated_at DESC")]
    return {"records":records}

@app.get("/api/model/evaluation")
def model_evaluation():
    summary=overview()["analytics"]
    return {"status":summary.get("xgboost"),"model_version":summary.get("model_version"),"training_rows":summary.get("training_rows",0),"positive_labels":summary.get("positive_labels",0),"evaluation":summary.get("evaluation",{}),"message":summary.get("message","")}


@app.get("/api/model/replay")
def model_replay():
    with _lock:
        return _model_replay_consistent()


def _model_replay_consistent():
    evaluation=model_evaluation()
    with connect() as c:
        row=c.execute("SELECT * FROM prediction_runs WHERE dataset_version=? ORDER BY created_at DESC LIMIT 1",(settings_get("last_sync_at"),)).fetchone()
    if not row: return {**evaluation,"series":[],"events":[],"message":"没有可回放的模型证据"}
    content=json.loads(row["content"])
    replay=content.get("replay",[])
    # Timeline remains complete; client renders a bounded prefix while stepping.
    events=content["summary"].get("evaluation",{}).get("events",[])
    timeline=event_timeline(replay,events,rows("maintenance_history"))
    return {**evaluation,"run_id":row["run_id"],"dataset_version":row["dataset_version"],"series":replay,"events":events,"timeline":timeline,"replay_basis":"冻结模型的时间外测试回放；非现场实时预警，非滚动重训；故障、维修与核验结论仅供事后复盘"}

@app.get("/api/data-quality")
def data_quality():
    with _lock:
        return _data_quality_consistent()


def _data_quality_consistent():
    readings=rows("readings"); devices=rows("equipment"); origin=settings_get("data_origin"); nasa=origin=="NASA_IMS_BEARING_RUN_TO_FAILURE"; metro=origin=="UCI_METROPT3_REAL_OPERATIONAL"; expected=["timestamp","tp2_bar","tp3_bar","oil_temperature_c","motor_current_a"] if metro else (["timestamp","vibration_g","vibration_peak_g","vibration_kurtosis"] if nasa else ["timestamp","process_temperature_k","rotational_speed_rpm","torque_nm","tool_wear_min","vibration_mm_s","spindle_load_pct"])
    if not metro and not nasa and origin!="SYNTHETIC_CNC_DEMO":
        observed={field for row in readings for field,value in row.items() if field in STANDARD_FIELDS or is_custom(field)}
        expected=["equipment_id","timestamp"]+sorted(observed-set(COMMON))
    def expected_for(row): return ["equipment_id","timestamp"]+row["_feature_fields"] if "_feature_fields" in row else expected
    missing=sum(1 for row in readings for key in expected_for(row) if row.get(key) in (None,"")); total=max(1,sum(len(expected_for(row)) for row in readings))
    latest=max((str(row.get("timestamp","")) for row in readings),default="")
    duplicates=len(readings)-len({(str(row.get("equipment_id")),str(row.get("timestamp"))) for row in readings})
    from statistics import median
    grouped={}; invalid_timestamps=0; abnormal_values=0; future_timestamps=0
    clock=datetime.now(timezone.utc).replace(tzinfo=None)
    for row in readings:
        try: moment=datetime.fromisoformat(str(row.get("timestamp","")))
        except ValueError: invalid_timestamps+=1; continue
        if moment.tzinfo: moment=moment.astimezone(timezone.utc).replace(tzinfo=None)
        if (moment-clock).total_seconds()>300: future_timestamps+=1
        grouped.setdefault(str(row.get("equipment_id")),[]).append(moment)
        for key in expected:
            if key in {"timestamp","equipment_id","status","production_line"} or row.get(key) in (None,""): continue
            try:
                if not math.isfinite(float(row[key])): abnormal_values+=1
            except (ValueError,TypeError): abnormal_values+=1
    gaps=[]
    for identifier,moments in grouped.items():
        ordered=sorted(set(moments)); intervals=[(b-a).total_seconds() for a,b in zip(ordered,ordered[1:]) if b>a]
        expected_interval=median(intervals) if intervals else None
        if expected_interval:
            for first,second in zip(ordered,ordered[1:]):
                if (second-first).total_seconds()>expected_interval*3:
                    gaps.append({"equipment_id":identifier,"start_at":first.isoformat(),"end_at":second.isoformat(),"duration_seconds":(second-first).total_seconds(),"inferred_interval_seconds":expected_interval})
    latest=max((moment for moments in grouped.values() for moment in moments),default=None)
    latest=latest.isoformat(sep=" ") if latest else ""
    age_hours=None
    try:
        timestamp=datetime.fromisoformat(latest)
        if timestamp.tzinfo is None: timestamp=timestamp.replace(tzinfo=timezone.utc)
        age_hours=max(0,(datetime.now(timezone.utc)-timestamp).total_seconds()/3600)
    except ValueError: pass
    return {"device_count":len(devices),"reading_count":len(readings),"missing_rate":round(missing/total,4),"duplicate_readings":duplicates,"latest_timestamp":latest,"data_origin":settings_get("data_origin","uploaded_workbook"),"quality_status":"基础校验通过，需核对现场适用性" if readings and missing/total<.05 and not duplicates and not invalid_timestamps and not abnormal_values and not future_timestamps else "需补充或修复数据","field_coverage":expected,"field_labels":[STANDARD_FIELDS.get(field,field) for field in expected],"future_timestamps":future_timestamps,"invalid_timestamps":invalid_timestamps,"abnormal_values":abnormal_values,"sampling_gap_count":len(gaps),"sampling_gaps":gaps[:100],"data_age_hours":age_hours,"freshness":"future_timestamp" if future_timestamps else ("historical" if age_hours is not None and age_hours>24 else "recent_or_unknown"),"gap_method":"按设备采样间隔中位数推断，超过3倍标为中断；不是采集SLA"}


class ScheduleRequest(BaseModel):
    scenario_id:Optional[str]=None
    start_at:Optional[str]=None
    request_id:Optional[str]=Field(default=None,min_length=8,max_length=100)


class MaintenanceRequestInput(BaseModel):
    equipment_id:str
    action:str=Field(min_length=2,max_length=1000)
    priority:str="中"
    request_id:str=Field(min_length=8,max_length=100)
    prediction_run_id:Optional[str]=Field(default=None,max_length=100)
    evidence_reading_id:Optional[str]=Field(default=None,max_length=200)


@app.post("/api/maintenance-requests")
def create_maintenance_request(payload:MaintenanceRequestInput):
    if payload.priority not in {"高","中","低"}: raise HTTPException(422,"优先级必须是高、中或低")
    equipment=next((record for record in rows("equipment") if record["equipment_id"]==payload.equipment_id),None)
    if not equipment: raise HTTPException(404,"设备不存在")
    signature=json.dumps(payload.model_dump(exclude={"request_id"}),ensure_ascii=False,sort_keys=True)
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        previous=c.execute("SELECT * FROM operation_requests WHERE request_id=?",(payload.request_id,)).fetchone()
        if previous:
            if previous["request_content"]!=signature: raise HTTPException(409,"请求编号已被用于不同维护需求")
            return json.loads(previous["response"])
        source_evidence=None
        if bool(payload.prediction_run_id)!=bool(payload.evidence_reading_id): raise HTTPException(422,"历史需求需同时提供预测运行及原始记录编号")
        if payload.prediction_run_id:
            evidence=c.execute("SELECT * FROM prediction_runs WHERE run_id=?",(payload.prediction_run_id,)).fetchone()
            if not evidence: raise HTTPException(404,"预测证据不存在")
            if evidence["dataset_version"]!=settings_get("last_sync_at"): raise HTTPException(409,"历史证据属于其他数据版本，不能直接用于当前设备需求")
            point=next((item for item in json.loads(evidence["content"]).get("replay",[]) if str(item.get("reading_id"))==payload.evidence_reading_id and str(item.get("equipment_id"))==payload.equipment_id),None)
            if not point: raise HTTPException(422,"原始记录与设备不属于指定预测证据")
            source_evidence={"kind":"historical_replay_manual_request","run_id":payload.prediction_run_id,"reading_id":payload.evidence_reading_id,"timestamp":point["timestamp"],"model_version":evidence["model_version"],"dataset_version":evidence["dataset_version"],"score":point["score"],"alert":point["alert"],"note":"历史证据供人工复盘，不表示当年真实派工或实测维修收益"}
        outstanding=[json.loads(row["content"]) for row in c.execute("SELECT content FROM work_orders WHERE equipment_id=? AND status NOT IN ('已完成','已取消','已驳回')",(payload.equipment_id,))]
        if any(item.get("dataset_version")==settings_get("last_sync_at") for item in outstanding): raise HTTPException(409,"该设备已有未完成维护需求，请先处理现有工单")
        now=datetime.now(timezone.utc).isoformat();work_id="WO-DRAFT-"+uuid.uuid4().hex[:12].upper()
        content={"work_order_id":work_id,"equipment_id":payload.equipment_id,"equipment_name":equipment.get("equipment_name"),"maintenance_action":payload.action,"priority":payload.priority,"dataset_version":settings_get("last_sync_at"),"created_at":now,"version":1,"source":"manual_confirmed_request"}
        if source_evidence: content["source_evidence"]=source_evidence
        c.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(work_id,payload.equipment_id,json.dumps(content,ensure_ascii=False),"草稿·待排程",now))
        result={"success":True,"work_order_id":work_id,"status":"草稿·待排程","next_step":"核对检修条件、人员班次、生产占用和预算，然后生成检修安排"}
        c.execute("INSERT INTO operation_requests VALUES (?,?,?)",(payload.request_id,signature,json.dumps(result,ensure_ascii=False)))
        c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("manual_maintenance_request",work_id,signature,now))
    return result

@app.post("/api/schedule/generate")
def generate_schedule(payload:ScheduleRequest):
    with _lock:
        return _generate_schedule_consistent(payload)


def schedule_state_fingerprint():
    with connect() as c:
        state={"dataset":settings_get("last_sync_at"),"revision":settings_get("business_revision","0")}
        state["resources"]=[dict(row) for row in c.execute("SELECT * FROM records WHERE table_name IN ('maintenance_rules','staff','orders','scenarios') ORDER BY table_name,row_index")]
        for table in ("work_orders","inventory_stock","inventory_reservations"):
            state[table]=[dict(row) for row in c.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
    return hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _generate_schedule_consistent(payload:ScheduleRequest,preview_only=False,prepared=None):
    request_content=json.dumps(payload.model_dump(exclude={"request_id"}),sort_keys=True)
    request_id=payload.request_id or str(uuid.uuid5(uuid.NAMESPACE_URL,request_content+settings_get("last_sync_at")+settings_get("business_revision","0")+datetime.now().strftime("%Y%m%d%H")))
    with connect() as c:
        receipt=c.execute("SELECT * FROM operation_requests WHERE request_id=?",(request_id,)).fetchone()
        if receipt:
            if receipt["request_content"]!=request_content: raise HTTPException(409,"请求标识已用于不同排程")
            return json.loads(receipt["response"])
    if prepared is None:
        requirements=[record for record in list_work_orders()["records"] if record["status"]=="草稿·待排程" and record.get("dataset_version")==settings_get("last_sync_at")]
        if not requirements: raise HTTPException(409,"请先复核预警并创建维护需求，或在设备检修条件中手工创建检查需求")
        priorities={record["equipment_id"]:{"高":.9,"中":.6,"低":.3}.get(record.get("priority","中"),.6) for record in requirements}
        result=_simulate_consistent(SimulationInput(scenario_id=payload.scenario_id,strategy="optimized",equipment_ids=list(priorities),confirmed_priorities=priorities),candidate_only=True)
        bookings=[record for record in list_work_orders()["records"] if record["status"] in {"待审批","已批准","已接单","执行中","已暂停"}]
        active={str(record["equipment_id"]):record for record in bookings}
        candidates=[item for item in result["selected"] if str(item["equipment_id"]) not in active]
        try: scheduled,conflicts=schedule_selected(candidates,rows("staff"),rows("orders"),payload.start_at,staff_limit=result["constraints"]["staff_count"],bookings=bookings,allow_subset=True,budget=result["constraints"]["budget"],max_hours=result["constraints"]["max_downtime_h"])
        except ValueError as exc: raise HTTPException(422,"排程时间配置错误："+str(exc))
        conflicts.extend({"equipment_id":item["equipment_id"],"reason":"已有未完成工单，未重复创建维护任务","suggestion":"请先处理工单 "+str(active[str(item["equipment_id"])]["work_order_id"])} for item in result["selected"] if str(item["equipment_id"]) in active)
    else:
        scheduled=prepared["scheduled"];conflicts=prepared["conflicts"];result=prepared["result"]
    result["summary"]={"task_count":len(scheduled),"maintenance_cost":round(sum(item["cost"] for item in scheduled),2),"maintenance_hours":round(sum(item["hours"] for item in scheduled),2),"method":"joint_selection_team_time_budget_stock"}
    if preview_only:
        return {"scheduled":scheduled,"conflicts":conflicts,"result":result,"state_fingerprint":schedule_state_fingerprint()}
    now=datetime.now(timezone.utc).isoformat()
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        receipt=c.execute("SELECT * FROM operation_requests WHERE request_id=?",(request_id,)).fetchone()
        if receipt: return json.loads(receipt["response"])
        if prepared is not None and prepared["state_fingerprint"]!=schedule_state_fingerprint(): raise HTTPException(409,"排程占用或资源已变化，请重新生成草案")
        for index,item in enumerate(scheduled):
            work_id=f"WO-{uuid.uuid4().hex[:12].upper()}"; content={**item,"scenario_id":payload.scenario_id,"work_order_id":work_id,"created_at":now,"version":1,"dataset_version":settings_get("last_sync_at"),"inventory_scope":inventory.current_scope(c),"constraints_snapshot":result["constraints"],"business_revision":settings_get("business_revision","0")}
            draft=next((dict(row) for row in c.execute("SELECT * FROM work_orders WHERE equipment_id=? AND status='草稿·待排程' ORDER BY updated_at DESC",(item["equipment_id"],)) if json.loads(row["content"]).get("dataset_version")==settings_get("last_sync_at")),None)
            if draft:
                previous=json.loads(draft["content"]);work_id=draft["work_order_id"]
                content.update(work_order_id=work_id,created_at=previous.get("created_at",now),operation_receipts=previous.get("operation_receipts",{}),execution_history=previous.get("execution_history",[]),source_alert_id=previous.get("source_alert_id"),source_evidence=previous.get("source_evidence"),maintenance_action=previous.get("maintenance_action") or previous.get("note"),priority=previous.get("priority","中"),version=previous.get("version",1)+1)
            content.setdefault("execution_history",[]).append({"from":"草稿·待排程","to":"待审批","action":"schedule","actor":security.identity("设备总管"),"at":now,"note":"自动约束排程生成"})
            item["work_order_id"]=work_id
            c.execute("INSERT OR REPLACE INTO work_orders(work_order_id,equipment_id,content,status,updated_at) VALUES (?,?,?,?,?)",(work_id,item["equipment_id"],json.dumps(content,ensure_ascii=False),"待审批",now))
        response={"scheduled":scheduled,"conflicts":conflicts,"selection":result["summary"],"human_approval_required":True,"optimizer_status":scheduled[0].get("optimizer_status","feasible") if scheduled else "no_plan","request_id":request_id}
        c.execute("INSERT INTO operation_requests VALUES (?,?,?)",(request_id,request_content,json.dumps(response,ensure_ascii=False)))
    audit("schedule_generated",payload.scenario_id or "default",{"scheduled":len(scheduled),"conflicts":len(conflicts)})
    return response

@app.get("/api/work-orders")
def list_work_orders(dataset_version:Optional[str]=None,include_deleted:bool=False):
    with connect() as c:
        records=[]
        for row in c.execute("SELECT * FROM work_orders ORDER BY updated_at DESC"):
            item=json.loads(row["content"])
            if item.get("deleted_at") and not include_deleted: continue
            if dataset_version is not None and item.get("dataset_version","")!=dataset_version: continue
            item.update({"status":row["status"],"updated_at":row["updated_at"]}); records.append(item)
    return {"records":records}


@app.get("/api/equipment/{equipment_id}/operations")
def equipment_operations(equipment_id:str):
    with _lock:
        if not any(str(item.get("equipment_id"))==equipment_id for item in rows("equipment")):
            raise HTTPException(404,"当前数据版本中不存在该设备")
        version=settings_get("last_sync_at")
        production=[item for item in rows("orders") if str(item.get("equipment_id"))==equipment_id]
        with connect() as c:
            work=[]
            for row in c.execute("SELECT * FROM work_orders WHERE equipment_id=? ORDER BY updated_at DESC",(equipment_id,)):
                item=json.loads(row["content"])
                item.update(status=row["status"],updated_at=row["updated_at"],current_dataset=item.get("dataset_version")==version)
                work.append(item)
        return {"equipment_id":equipment_id,"dataset_version":version,"orders":production,"work_orders":work}


@app.get("/api/operations/resource-occupancy")
def resource_occupancy():
    with _lock:
        version=settings_get("last_sync_at")
        work=list_work_orders()["records"]
        active=[item for item in work if item["status"] in {"待审批","已批准","已接单","执行中","已暂停","待验收"}]
        def summary(item):
            return {key:item.get(key) for key in ("work_order_id","equipment_id","status","start_at","end_at","dataset_version")}|{"current_dataset":item.get("dataset_version")==version}
        people=[]
        for person in rows("staff"):
            bookings=[summary(item) for item in active if person["staff_id"] in (item.get("staff_ids") or [item.get("staff_id")])]
            people.append({"staff_id":person["staff_id"],"staff_name":person.get("staff_name"),"skills":person.get("skills"),"shift_start":person.get("shift_start"),"shift_end":person.get("shift_end"),"available_hours":person.get("available_hours"),"bookings":bookings})
        orders=[]
        for order in rows("orders"):
            related=[summary(item) for item in active if item["equipment_id"]==order.get("equipment_id")]
            orders.append({**order,"related_work_orders":related})
        return {"dataset_version":version,"staff":people,"orders":orders,"note":"待审批是计划占用，不代表已执行；关联工单按设备或人员关联，不自动认定与订单时间冲突"}


class PartUsage(BaseModel):
    part_name:str=Field(min_length=1,max_length=100)
    quantity:int=Field(ge=0,strict=True)


class WorkOrderTransition(BaseModel):
    model_config={"allow_inf_nan":False}
    action: str
    version: int = Field(ge=1)
    actor: str = Field(min_length=1,max_length=100)
    note: str = Field(default="",max_length=1000)
    actual_hours: Optional[float] = Field(default=None,ge=0)
    actual_cost_cny: Optional[float] = Field(default=None,ge=0)
    request_id: str = Field(min_length=8,max_length=100)
    actual_parts: Optional[list[PartUsage]]=Field(default=None,max_length=100)


@app.post("/api/work-orders/{work_order_id}/transition")
def transition_work_order(work_order_id: str, payload: WorkOrderTransition):
    security.require_roles("admin","manager","technician")
    payload=payload.model_copy(update={"actor":security.identity(payload.actor)})
    transitions = {"accept":({"已批准"},"已接单"),"start":({"已接单"},"执行中"),"pause":({"执行中"},"已暂停"),"resume":({"已暂停"},"执行中"),"finish":({"执行中"},"待验收"),"verify":({"待验收"},"已完成"),"rework":({"待验收"},"执行中"),"revise":({"已退回","已驳回"},"草稿·待排程"),"cancel":({"草稿·待排程","待审批","已批准","已接单","已暂停","已退回","已驳回"},"已取消")}
    if payload.action not in transitions: raise HTTPException(422,"未知工单操作")
    if payload.action in {"pause","finish","verify","rework","revise","cancel"} and not payload.note.strip(): raise HTTPException(422,"请填写处理说明")
    if payload.action == "finish" and (payload.actual_hours is None or payload.actual_cost_cny is None): raise HTTPException(422,"完工必须填写实际工时和费用")
    now = datetime.now(timezone.utc).isoformat()
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM work_orders WHERE work_order_id=?",(work_order_id,)).fetchone()
        if not row: raise HTTPException(404,"工单不存在")
        content=json.loads(row["content"])
        if content.get("deleted_at"): raise HTTPException(409,"工单已在回收站，请先恢复")
        security.check_work_order_action(payload.action,content)
        receipts=content.setdefault("operation_receipts",{})
        signature={**payload.model_dump(exclude={"request_id"}),**security.actor_metadata()}
        if payload.request_id in receipts:
            if receipts[payload.request_id]["input"] != signature: raise HTTPException(409,"重复请求标识不能用于不同操作")
            return receipts[payload.request_id]["result"]
        if payload.version != content.get("version",1): raise HTTPException(409,"工单已被更新，请刷新")
        allowed,target=transitions[payload.action]
        if row["status"] not in allowed: raise HTTPException(409,f"当前状态 {row['status']} 不允许该操作")
        if payload.action in {"accept","start"}:
            content["execution_check"]=recheck_execution(c,content,settings_get("last_sync_at"),settings_get("business_revision","0"),payload.action)
        needs_parts=content.get("spare_parts") and (payload.action=="verify" or (payload.action=="cancel" and (content.get("actual_start_at") or row["status"]=="已暂停")))
        if needs_parts:
            if payload.actual_parts is None: raise HTTPException(422,"请逐项确认备件实际耗用；未使用的填写0")
            scope=content.get("inventory_scope") or content.get("dataset_version")
            if not scope: raise HTTPException(409,"旧工单缺少库存归属，请先核对工单来源")
            inventory.import_legacy_reservations(c)
            actual_parts=[part.model_dump() for part in payload.actual_parts]
            inventory.consume(c,work_order_id,scope,content["spare_parts"],actual_parts)
            content["actual_parts"]=actual_parts
        if payload.action=="cancel": inventory.release(c,work_order_id)
        content["version"]=payload.version+1
        execution_evidence={"execution_check":content["execution_check"]} if payload.action in {"accept","start"} else {}
        content.setdefault("execution_history",[]).append({**signature,**execution_evidence,"from":row["status"],"to":target,"at":now})
        if payload.action == "start": content["actual_start_at"]=now
        if payload.action == "finish": content.update(actual_hours=payload.actual_hours,actual_cost_cny=payload.actual_cost_cny,repair_result=payload.note,actual_finish_at=now)
        if payload.action == "revise":
            content["maintenance_action"]=payload.note
            for key in ("start_at","end_at","staff_id","staff_ids","staff_name","approved_at","approval_decision_at","last_approval_request_id","approver","approval_note","approval_business_revision","execution_check","business_revision","constraints_snapshot"):
                content.pop(key,None)
        result={"success":True,"work_order_id":work_order_id,"status":target,"version":content["version"]}
        receipts[payload.request_id]={"input":signature,"result":result}
        c.execute("UPDATE work_orders SET content=?,status=?,updated_at=? WHERE work_order_id=?",(json.dumps(content,ensure_ascii=False),target,now,work_order_id))
        c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("work_order_transition",work_order_id,json.dumps({**signature,**execution_evidence,"status":target},ensure_ascii=False),now))
        if target == "已完成":
            index=c.execute("SELECT COALESCE(MAX(row_index),-1)+1 FROM records WHERE table_name='maintenance_history'").fetchone()[0]
            record={"maintenance_id":work_order_id,"work_order_id":work_order_id,"equipment_id":row["equipment_id"],"maintenance_date":content.get("actual_finish_at",now),"verified_at":now,"actual_start_at":content.get("actual_start_at"),"maintenance_type":"工单维修验收","maintenance_result":content.get("repair_result"),"actual_hours":content.get("actual_hours"),"actual_cost_cny":content.get("actual_cost_cny"),"verified_by":payload.actor,"data_origin":"USER_VERIFIED_MAINTENANCE","source_alert_id":content.get("source_alert_id"),"source_evidence":content.get("source_evidence")}
            c.execute("INSERT INTO maintenance_events VALUES (?,?,?,?,?)",(work_order_id,content.get("dataset_version",""),row["equipment_id"],json.dumps(record,ensure_ascii=False),now))
            if content.get("dataset_version")==settings_get("last_sync_at"):
                c.execute("INSERT INTO records VALUES ('maintenance_history',?,?)",(index,json.dumps(record,ensure_ascii=False)))
    return result

class ApprovalInput(BaseModel):
    decision:str
    approver:str=Field(min_length=1,max_length=100)
    note:str=Field(default="",max_length=500)
    version:int=Field(ge=1,strict=True)
    request_id:Optional[str]=Field(default=None,min_length=8,max_length=100)
    accept_assumptions:bool=False

@app.post("/api/work-orders/{work_order_id}/approval")
def approve_work_order(work_order_id:str,payload:ApprovalInput):
    security.require_roles("admin","manager")
    payload=payload.model_copy(update={"approver":security.identity(payload.approver)})
    if not payload.approver.strip(): raise HTTPException(422,"请填写审批人员")
    if payload.request_id is not None and not payload.request_id.strip(): raise HTTPException(422,"操作编号不能为空")
    if payload.decision not in ("approve","reject"): raise HTTPException(422,"decision必须是approve或reject")
    if payload.decision=="reject" and not payload.note.strip(): raise HTTPException(422,"退回需填写原因")
    status="已批准" if payload.decision=="approve" else "已退回"; now=datetime.now(timezone.utc).isoformat()
    signature=json.dumps({"operation":"work_order_approval","work_order_id":work_order_id,**payload.model_dump(exclude={"request_id"}),**security.actor_metadata()},ensure_ascii=False,sort_keys=True)
    request_id=payload.request_id or "approval-"+hashlib.sha256(signature.encode()).hexdigest()
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        saved=c.execute("SELECT request_content,response FROM operation_requests WHERE request_id=?",(request_id,)).fetchone()
        if saved:
            if saved["request_content"]!=signature: raise HTTPException(409,"操作编号已用于另一条工单、其他审批内容或其他人员，请刷新后重新操作")
            return json.loads(saved["response"])
        row=c.execute("SELECT content,status FROM work_orders WHERE work_order_id=?",(work_order_id,)).fetchone()
        if not row: raise HTTPException(404,"工单不存在")
        content=json.loads(row["content"])
        if content.get("deleted_at"): raise HTTPException(409,"工单已在回收站，请先恢复")
        if payload.version != content.get("version",1): raise HTTPException(409,"工单已更新，请刷新后重试")
        if row["status"] != "待审批": raise HTTPException(409,"只有待审批工单可审批")
        if payload.decision == "approve" and (not content.get("start_at") or not content.get("staff_id")): raise HTTPException(422,"缺少排程或人员，不能批准")
        if payload.decision == "approve":
            if not content.get("dataset_version"): raise HTTPException(409,"旧工单缺少数据版本，请重新建立维护需求并排程")
            if content.get("business_revision") is not None and content["business_revision"]!=settings_get("business_revision","0"): raise HTTPException(409,"维护资源已更新，请重新排程后审批")
            if content.get("dataset_version") and content["dataset_version"]!=settings_get("last_sync_at"): raise HTTPException(409,"数据版本已改变，请重新排程后审批")
            if content.get("assumptions") and not payload.accept_assumptions: raise HTTPException(422,"此方案含未验证的情景假设，需逐项核对并明确确认")
            inventory.import_legacy_reservations(c)
            scope=content.get("inventory_scope") or content["dataset_version"]
            inventory.reserve(c,work_order_id,scope,content.get("spare_parts",[]))
            assert_no_formal_conflict(c,content)
            content["approval_business_revision"]=settings_get("business_revision","0")
        content.setdefault("execution_history",[]).append({"from":row["status"],"to":status,"action":payload.decision,"actor":payload.approver,"at":now,"note":payload.note,"request_id":request_id})
        content.update({"approver":payload.approver,"approval_note":payload.note,"approval_decision_at":now,"last_approval_request_id":request_id,"version":content.get("version",1)+1})
        if payload.decision=="approve": content["approved_at"]=now
        else:
            for key in ("approved_at","approval_business_revision","execution_check"): content.pop(key,None)
        c.execute("UPDATE work_orders SET content=?,status=?,updated_at=? WHERE work_order_id=?",(json.dumps(content,ensure_ascii=False),status,now,work_order_id))
        c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("work_order_approval",work_order_id,json.dumps(payload.model_dump()|{"request_id":request_id,"status":status,**security.actor_metadata()},ensure_ascii=False),now))
        result={"success":True,"work_order_id":work_order_id,"status":status,"version":content["version"],"request_id":request_id}
        c.execute("INSERT INTO operation_requests VALUES (?,?,?)",(request_id,signature,json.dumps(result,ensure_ascii=False)))
    return result

@app.get("/api/audit")
def audit_log(limit:int=100,event_type:str="",entity:str="",before_id:int=0):
    clauses=[];parameters=[]
    if event_type:
        clauses.append("event_type=?");parameters.append(event_type[:100])
    if entity:
        clauses.append("(instr(entity_id,?)>0 OR instr(COALESCE(json_extract(content,'$.equipment_id'),''),?)>0 OR EXISTS (SELECT 1 FROM work_orders w WHERE w.work_order_id=audit_events.entity_id AND w.equipment_id=?))")
        parameters.extend([entity[:200],entity[:200],entity[:200]])
    if before_id>0:
        clauses.append("event_id<?");parameters.append(before_id)
    count=max(1,min(limit,500))
    query="SELECT * FROM audit_events"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY event_id DESC LIMIT ?"
    with connect() as c:
        records=[{**dict(row),"content":json.loads(row["content"])} for row in c.execute(query,(*parameters,count))]
    return {"records":records,"next_cursor":records[-1]["event_id"] if len(records)==count else None}
MODEL_CATALOG = {
    "deepseek-ai/DeepSeek-V4-Flash": {"label": "硅基流动 · DeepSeek V4 Flash", "provider": "siliconflow", "base_url": "https://api.siliconflow.cn/v1"},
    "deepseek-ai/DeepSeek-V4-Pro": {"label": "硅基流动 · DeepSeek V4 Pro", "provider": "siliconflow", "base_url": "https://api.siliconflow.cn/v1"},
    "deepseek-chat": {"label": "DeepSeek 官方 · Chat", "provider": "deepseek", "base_url": "https://api.deepseek.com"},
    "qwen-plus": {"label": "通义千问 Plus", "provider": "qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    "gpt-4.1-mini": {"label": "OpenAI GPT-4.1 mini", "provider": "openai", "base_url": "https://api.openai.com/v1"},
}

class ApiSettings(BaseModel):
    model:str=""
    api_key:Optional[str]=None
    # Kept only for compatibility with older local clients; the current UI never asks for it.
    provider:Optional[str]=None
    base_url:Optional[str]=None
@app.get("/api/developer/settings")
def read_api_settings():
    return {"model":settings_get("ai_model",""),"models":[{"id":model,**details} for model,details in MODEL_CATALOG.items()],"has_api_key":bool(_api_key),"key_storage":"系统凭据存储" if _credential_secure else ("环境变量" if os.environ.get("FACTORYPULSE_AI_API_KEY") else "未配置")}
@app.post("/api/developer/settings")
def save_api_settings(cfg:ApiSettings):
    global _api_key,_credential_secure
    selected=MODEL_CATALOG.get(cfg.model)
    if selected:
        provider=selected["provider"]; base_url=selected["base_url"]
    elif cfg.base_url:  # Backward-compatible API path; intentionally absent from the UI.
        require_public_https(cfg.base_url)
        provider=cfg.provider or "custom"; base_url=cfg.base_url.rstrip("/")
    else:
        raise HTTPException(422,"请选择受支持的模型")
    if cfg.api_key is not None and cfg.api_key.strip():
        candidate=cfg.api_key.strip()
        if not credential_set(candidate): raise HTTPException(503,"系统凭据存储不可用，未保存密钥；请修复系统凭据服务，或由部署管理员配置环境变量")
        _api_key=candidate; _credential_secure=True
    with _lock,connect() as c:
        for k,v in (("ai_provider",provider),("ai_base_url",base_url),("ai_model",cfg.model)):
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",(k,v))
    return read_api_settings()
@app.post("/api/developer/test-connection")
async def test_connection():
    base=settings_get("ai_base_url"); model=settings_get("ai_model"); provider=settings_get("ai_provider")
    if not base or not model or not _api_key: raise HTTPException(400,"请先配置API地址、模型和密钥")
    await address_validation.check(base,require_public_https)
    try:
        async with httpx.AsyncClient(timeout=12,follow_redirects=False,trust_env=False) as client:
            r=await client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+_api_key},json={"model":model,"messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":12})
        if r.status_code==401:
            detail="硅基流动拒绝了该 API Key，请确认密钥来自 cloud.siliconflow.cn 且仍然有效" if provider=="siliconflow" else "API Key 无效或不属于当前模型服务商，请重新输入与所选模型匹配的密钥"
            raise HTTPException(400,detail)
        if r.status_code>=400: raise HTTPException(400,f"模型服务返回 HTTP {r.status_code}；请检查模型权限、账户余额或稍后重试")
        return {"success":True,"message":"API连接测试成功"}
    except httpx.RequestError as e: raise HTTPException(502,"API网络请求失败："+type(e).__name__)

@app.get("/api/strategies/compare")
def compare_strategies(scenario_id:Optional[str]=None):
    with _lock:
        return _compare_strategies_consistent(scenario_id,persist=False)


class ComparisonInput(BaseModel):
    scenario_id:Optional[str]=None
    executable:bool=True

@app.post("/api/strategies/compare")
def calculate_comparison(payload:ComparisonInput):
    security.require_roles("admin","manager")
    with _lock:
        return _compare_strategies_consistent(payload.scenario_id,persist=True,executable=payload.executable)

def _compare_strategies_consistent(scenario_id,persist=False,executable=False):
    devices=snapshot()
    if not devices: raise HTTPException(400,"请先导入测试工作簿")
    requirements=[record for record in list_work_orders()["records"] if record["status"]=="草稿·待排程" and record.get("dataset_version")==settings_get("last_sync_at")]
    priorities={record["equipment_id"]:{"高":.9,"中":.6,"低":.3}.get(record.get("priority","中"),.6) for record in requirements}
    strategies=[]
    now=datetime.now(timezone.utc).isoformat()
    staff=rows("staff");production_orders=rows("orders")
    bookings=[record for record in list_work_orders()["records"] if record["status"] in {"待审批","已批准","已接单","执行中","已暂停"}]
    scheduled_cache={}
    planning_clock=datetime.now();planning_origin=(planning_clock.replace(second=0,microsecond=0)+timedelta(minutes=int(bool(planning_clock.second or planning_clock.microsecond)))).isoformat(sep=" ")
    for strategy in ("fixed_interval","risk_threshold","optimized"):
        result=_simulate_consistent(SimulationInput(scenario_id=scenario_id,strategy=strategy,equipment_ids=list(priorities) if priorities else None,confirmed_priorities=priorities),read_only=not persist,prepared_devices=devices,skip_preselection=executable)
        if executable:
            # Every strategy is checked against the same actual staff, shifts, orders and reservations.
            pool=result["selected"]
            busy={str(record["equipment_id"]) for record in bookings}
            pool=[item for item in pool if str(item["equipment_id"]) not in busy]
            signature=json.dumps({"pool":sorted(pool,key=lambda item:item["equipment_id"]),"constraints":result["constraints"]},sort_keys=True)
            if signature not in scheduled_cache:
                scheduled_cache[signature]=schedule_selected(sorted(pool,key=lambda item:item["equipment_id"]),staff,production_orders,start_at=planning_origin,staff_limit=result["constraints"]["staff_count"],bookings=bookings,allow_subset=True,budget=result["constraints"]["budget"],max_hours=result["constraints"]["max_downtime_h"])
            scheduled,conflicts=json.loads(json.dumps(scheduled_cache[signature]))
            result["selected"]=scheduled
            result["conflicts"]=conflicts
            result["summary"].update(task_count=len(scheduled),maintenance_cost=round(sum(i["cost"] for i in scheduled),2),maintenance_hours=round(sum(i["hours"] for i in scheduled),2))
            low=sum(i["expected_loss_avoided_low"] for i in scheduled);high=sum(i["expected_loss_avoided_high"] for i in scheduled)
            result["summary"]["avoided_loss_range"]=[round(low,2),round(high,2)]
            baseline=result["summary"]["baseline_expected_loss"]
            result["summary"]["total_cost_range"]=[round(baseline-high+result["summary"]["maintenance_cost"],2),round(baseline-low+result["summary"]["maintenance_cost"],2)] if baseline is not None else [None,None]
            result["summary"]["illustrative_total_cost"]=round(baseline-low+result["summary"]["maintenance_cost"],2) if baseline is not None else None
            result["optimizer_status"]=scheduled[0]["optimizer_status"] if scheduled else "no_plan"
        result.update(comparison_scope="joint_staff_time_resources" if executable else "budget_workload_selection_only",objective="sum_of_review_priorities_not_financial_optimum",execution_validated=bool(executable and result["selected"] and all(i.get("constraint_status")=="validated" for i in result["selected"])),baseline_kind="identifier_order_not_enterprise_policy" if strategy=="fixed_interval" else strategy,plan_id=uuid.uuid4().hex,dataset_version=settings_get("last_sync_at"),business_revision=settings_get("business_revision","0"),calculated_at=now)
        strategies.append(result)
    if persist:
      with connect() as c:
        c.executemany("INSERT INTO planning_runs VALUES (?,?,?,?,?)",[(result["plan_id"],result["dataset_version"],result["business_revision"],json.dumps(result,ensure_ascii=False),now) for result in strategies])
    return {"strategies":strategies,"description":"三策略在同一人员、班次、订单、库存、预算和累计工时条件下校验。仍含情景假设时不可视为现场可执行。编号顺序为弱对照，非企业现行策略；目标为优先级总分而非收益最优。" if executable else "预算与工时预选；未检查联合时间安排"}

@app.get("/api/export/maintenance.csv")
def export_plan(scenario_id:Optional[str]=None,strategy:str="optimized",plan_id:Optional[str]=None):
    if plan_id:
        with connect() as c: row=c.execute("SELECT content FROM planning_runs WHERE plan_id=?",(plan_id,)).fetchone()
        if not row: raise HTTPException(404,"方案快照不存在，请重新计算")
        result=json.loads(row["content"])
    else:
        comparison=_compare_strategies_consistent(scenario_id,persist=False)
        result=next((item for item in comparison["strategies"] if item["strategy"]==strategy),None)
        if result is None: raise HTTPException(422,"未知维护策略")
    out=io.StringIO()
    writer=csv.writer(out)
    writer.writerow(["方案编号","数据版本","业务条件版本","计算时间","设备ID","设备名称","风险评分(0–100分，非概率)","优先级依据","维护成本(元)","预计工时","所需人员数","情景避免损失下限(元)","情景避免损失上限(元)"])
    def cell(value):
        # Spreadsheet exports must retain imported names as text, never formulas.
        if isinstance(value,str) and value.lstrip().startswith(("=","+","-","@")): return "'"+value
        return value
    for item in result["selected"]:
        estimated=result["summary"].get("financial_basis")=="explicit_scenario_probability"
        writer.writerow([cell(value) for value in [result["plan_id"],result["dataset_version"],result["business_revision"],result["calculated_at"],item["equipment_id"],item["equipment_name"],round(item["risk"]*100,2) if item.get("risk_available",True) else "未评估",item.get("priority_basis","参考分"),item["cost"],item["hours"],item["people"],item["expected_loss_avoided_low"] if estimated else "未评估",item["expected_loss_avoided_high"] if estimated else "未评估"]])
    return StreamingResponse(iter(["\ufeff"+out.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":'attachment; filename="factorypulse_maintenance_plan.csv"'})

def require_public_https(value:str):
    parsed=urlparse(value)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(422,"API地址必须是无账号信息的公开 HTTPS URL")
    host=parsed.hostname.lower()
    if host in ("localhost","localhost.localdomain") or host.endswith(".local") or host.endswith(".internal"):
        raise HTTPException(422,"不允许配置内网或本机API地址")
    try:
        addresses=socket.getaddrinfo(host,parsed.port or 443,type=socket.SOCK_STREAM)
        if not addresses: raise HTTPException(422,"无法解析API地址")
        for record in addresses:
            ip=ipaddress.ip_address(record[4][0])
            if not ip.is_global: raise HTTPException(422,"不允许连接内网、保留地址或环回地址")
    except socket.gaierror: raise HTTPException(422,"API地址DNS解析失败")

class ChatInput(BaseModel):
    question:str=Field(min_length=1,max_length=1000)
    scenario_id:Optional[str]=Field(default=None,min_length=1,max_length=100)

def compact_ai_answer(content:str)->str:
    return plain_answer(content)

def copilot_calculation_context(question:str)->dict:
    """Build auditable aggregates from the current application records.

    The language model explains these results; it never performs the financial
    arithmetic itself. Financial effects remain scenario estimates because the
    current dataset has no observed causal maintenance-uplift field.
    """
    devices=snapshot()
    rules={str(row.get("equipment_id")):row for row in rows("maintenance_rules")}

    def maintenance_values(device:dict)->tuple[float,float,float]:
        rule=rules.get(str(device.get("equipment_id")),{})
        cost=num(rule.get("maintenance_cost_cny"),num(rule.get("inspection_cost_cny"),250)+num(rule.get("repair_cost_cny"),900))
        hours=num(rule.get("maintenance_hours"),num(rule.get("inspection_duration_h"),2)+num(rule.get("repair_duration_h"),2))
        failure_loss=num(rule.get("assumed_failure_loss_cny"),3000)
        return cost,hours,failure_loss

    def summarize_scope(name:str, scoped:list[dict])->dict:
        maintenance_cost=0.; maintenance_hours=0.; expected_failure_loss=0.
        for device in scoped:
            cost,hours,failure_loss=maintenance_values(device)
            maintenance_cost+=cost
            maintenance_hours+=hours
            expected_failure_loss+=num(device.get("risk_score"))*failure_loss
        avoided_low=.25*expected_failure_loss; avoided_high=.65*expected_failure_loss
        return {
            "scope":name,
            "device_count":len(scoped),
            "maintenance_cost_cny":round(maintenance_cost,2),
            "maintenance_hours":round(maintenance_hours,2),
            "expected_failure_loss_before_cny":round(expected_failure_loss,2),
            "scenario_avoided_loss_range_cny":[round(avoided_low,2),round(avoided_high,2)],
            "net_financial_impact_range_cny":[round(maintenance_cost-avoided_high,2),round(maintenance_cost-avoided_low,2)],
        }

    high=[device for device in devices if num(device.get("risk_score"))>.35]
    elevated=[device for device in devices if num(device.get("risk_score"))>=.15]
    context={
        "calculation_basis":{
            "currency":"CNY",
            "risk_thresholds":"低风险 <15 分；中风险 15–35 分；高风险 >35 分",
            "risk_score_limit":"风险评分未经概率校准，不能作为故障概率。按评分加权计算的金额只是敏感性情景，不能作为实际预计亏损。",
            "maintenance_effect_assumption":"维护效果按25%–65%情景区间展示，非因果估计",
            "net_financial_impact_formula":"维修费用 - 情景避免故障损失；仅用于敏感性分析",
        },
        "maintenance_scenarios":[
            summarize_scope("全部当前设备（将“大规模维护”解释为全量维护）",devices),
            summarize_scope("全部中高风险设备（评分>=15分）",elevated),
            summarize_scope("全部高风险设备（评分>35分）",high),
        ],
    }
    if any(term in question for term in ("产线","产品线")):
        grouped:dict[str,list[dict]]={}
        for device in devices:
            grouped.setdefault(str(device.get("production_line") or "未分配"),[]).append(device)
        context["production_line_summary"]=sorted(
            (summarize_scope(line,items) for line,items in grouped.items()),
            key=lambda item:item["maintenance_cost_cny"],reverse=True,
        )[:20]
    return context

def agent_dispatch(name: str, arguments: dict) -> dict:
    with _lock:
        return _agent_dispatch_consistent(name,arguments)


def _agent_dispatch_consistent(name: str, arguments: dict) -> dict:
    arguments=validate_arguments(name,arguments)
    if name in {"operations_context","work_order_flow"}:
        return operational_evidence(name,arguments,connect=connect,rows=rows,settings_get=settings_get)
    if name=="evaluation":
        evaluation=model_evaluation()
        metrics=evaluation.get("evaluation") or {}
        return {"source":"SQLite / evaluation","data_time":metrics.get("test_end"),"data_version":settings_get("last_sync_at"),"business_revision":settings_get("business_revision","0"),**evaluation}
    identifier=str(arguments.get("equipment_id") or "")
    devices=[{**device,"risk_score":device["risk_score"] if device.get("risk_available",True) else None} for device in snapshot()]
    selected=next((d for d in devices if d["equipment_id"]==identifier),None)
    source={"source":"SQLite / "+name,"data_time":max((str(d.get("prediction_at") or "") for d in devices),default=""),"data_version":settings_get("last_sync_at"),"business_revision":settings_get("business_revision","0")}
    if name=="draft_schedule":
        security.require_roles("admin","manager")
        payload=ScheduleRequest(scenario_id=arguments.get("scenario_id"),start_at=arguments.get("start_at"),request_id="agent-preview-"+uuid.uuid4().hex)
        preview=_generate_schedule_consistent(payload,preview_only=True)
        proposal={"proposal_id":uuid.uuid4().hex,"kind":"schedule","scenario_id":payload.scenario_id,"start_at":payload.start_at,"dataset_version":source["data_version"],"business_revision":source["business_revision"],"prepared":preview,"scheduled":preview["scheduled"],"conflicts":preview["conflicts"],"note":"后端约束计算的排程草案；用户确认后进入待审批，不能直接派工","created_at":datetime.now(timezone.utc).isoformat()}
        with connect() as c: c.execute("INSERT INTO settings VALUES (?,?)",("agent_proposal:"+proposal["proposal_id"],json.dumps(proposal,ensure_ascii=False)))
        return {**source,"proposal":{key:value for key,value in proposal.items() if key!="prepared"},"message":"排程草案已计算，请核对人员、时间与冲突后人工确认"}
    if name=="draft_constraints":
        security.require_roles("admin","manager")
        original=next((item for item in rows("scenarios") if item.get("scenario_id")==arguments.get("scenario_id")),None)
        if not original: raise ValueError("请提供已录入的排程条件编号")
        note=str(arguments.get("note") or "").strip()[:500]
        if not note: raise ValueError("请说明修改条件的原因")
        changes={target:arguments[key] for key,target in {"budget":"maintenance_budget_cny","staff_count":"available_staff_count","max_downtime_h":"max_downtime_h"}.items() if key in arguments}
        if not changes: raise ValueError("至少明确修改预算、人数或累计工时中的一项")
        proposed=ScenarioInput(**{**original,"scenario_name":original.get("scenario_name") or original["scenario_id"],**changes}).model_dump(mode="json")
        proposal={"proposal_id":uuid.uuid4().hex,"kind":"constraints","scenario_id":original["scenario_id"],"original":original,"proposed":proposed,"note":note,"dataset_version":source["data_version"],"business_revision":source["business_revision"],"created_at":datetime.now(timezone.utc).isoformat()}
        with connect() as c: c.execute("INSERT INTO settings VALUES (?,?)",("agent_proposal:"+proposal["proposal_id"],json.dumps(proposal,ensure_ascii=False)))
        return {**source,"proposal":proposal,"message":"条件草稿已准备，用户确认后另存新条件；不覆盖原条件，不自动批准或派工"}
    if name in ("history","draft_work_order") and not selected: raise ValueError("设备编号不存在，请先查询设备")
    if name=="equipment":
        if identifier and not selected: raise ValueError("设备不存在")
        return {**source,"devices":[selected] if selected else sorted(devices,key=lambda d:-(d["risk_score"] or 0))[:10]}
    if name=="history": return {**source,**equipment_history(identifier,points=48)}
    if name=="compare_plans":
        allowed={key:value for key,value in arguments.items() if key in {"scenario_id","budget","max_downtime_h"}}
        return {**source,"strategies":[simulate(SimulationInput(**allowed,strategy=strategy)) for strategy in ("fixed_interval","risk_threshold","optimized")]}
    if name=="draft_work_order":
        security.require_roles("admin","manager")
        note=str(arguments.get("note") or "")[:500]
        if not note.strip(): raise ValueError("维护动作不能为空")
        proposal={"proposal_id":uuid.uuid4().hex,"equipment_id":identifier,"equipment_name":selected.get("equipment_name"),"note":note,"dataset_version":settings_get("last_sync_at"),"created_at":datetime.now(timezone.utc).isoformat(),"status":"等待用户确认"}
        with connect() as c:
            c.execute("INSERT INTO settings VALUES (?,?)",("agent_proposal:"+proposal["proposal_id"],json.dumps(proposal,ensure_ascii=False)))
        return {**source,"proposal":proposal,"message":"草稿已准备，用户确认后才创建待排程维护需求"}
    raise ValueError("未知工具")


class ProposalConfirmation(BaseModel):
    confirmed: bool


@app.post("/api/copilot/proposals/{proposal_id}/confirm")
def confirm_agent_proposal(proposal_id: str, payload: ProposalConfirmation):
    security.require_roles("admin","manager")
    if not payload.confirmed: raise HTTPException(422,"需要明确确认维护需求")
    with _lock:
        with connect() as c:
            saved=c.execute("SELECT value FROM settings WHERE key=?",("agent_proposal:"+proposal_id,)).fetchone()
        candidate=json.loads(saved[0]) if saved else {}
        if candidate.get("kind")=="schedule":
            request=ScheduleRequest(scenario_id=candidate.get("scenario_id"),start_at=candidate.get("start_at"),request_id="agent-schedule-"+proposal_id)
            with connect() as c:
                receipt=c.execute("SELECT response FROM operation_requests WHERE request_id=?",(request.request_id,)).fetchone()
            if receipt: return {"success":True,"kind":"schedule",**json.loads(receipt[0])}
            if candidate["dataset_version"]!=settings_get("last_sync_at") or candidate["prepared"]["state_fingerprint"]!=schedule_state_fingerprint(): raise HTTPException(409,"数据、库存或工单占用已变化，请重新生成排程草案")
            if not candidate["prepared"]["scheduled"]: raise HTTPException(422,"当前草案没有可安排任务，请先处理冲突")
            result=_generate_schedule_consistent(request,prepared=candidate["prepared"])
            return {"success":True,"kind":"schedule",**result}
    with _lock,connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT value FROM settings WHERE key=?",("agent_proposal:"+proposal_id,)).fetchone()
        if not row: raise HTTPException(404,"草稿不存在")
        proposal=json.loads(row["value"])
        if proposal.get("kind")=="constraints":
            if proposal.get("confirmed_scenario_id"): return {"success":True,"scenario_id":proposal["confirmed_scenario_id"],"status":"新条件已保存，待重新比较和排程"}
            if proposal["dataset_version"]!=settings_get("last_sync_at") or proposal["business_revision"]!=settings_get("business_revision","0"): raise HTTPException(409,"数据或资源条件已变化，请重新起草并核对")
            scenario_id="AI-CONFIRMED-"+proposal_id[:12].upper()
            values=ScenarioInput(**proposal["proposed"]).model_dump(mode="json")
            values.update(scenario_id=scenario_id,scenario_name=str(values["scenario_name"])[:80]+" · 人工确认调整",data_origin="USER_CONFIRMED_AGENT_CONSTRAINTS")
            index=c.execute("SELECT COALESCE(MAX(row_index),-1)+1 FROM records WHERE table_name='scenarios'").fetchone()[0]
            c.execute("INSERT INTO records VALUES ('scenarios',?,?)",(index,json.dumps(values,ensure_ascii=False)))
            settings_set_many(c,{"business_revision":int(proposal["business_revision"])+1})
            proposal["confirmed_scenario_id"]=scenario_id
            c.execute("UPDATE settings SET value=? WHERE key=?",(json.dumps(proposal,ensure_ascii=False),"agent_proposal:"+proposal_id))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("agent_constraints_confirmed",scenario_id,json.dumps({"proposal_id":proposal_id,"before":proposal["original"],"after":values,**security.actor_metadata()},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
            return {"success":True,"scenario_id":scenario_id,"status":"新条件已保存，待重新比较和排程"}
        if proposal.get("work_order_id"): return {"success":True,"work_order_id":proposal["work_order_id"],"status":"草稿·待排程"}
        if proposal["dataset_version"]!=settings_get("last_sync_at"): raise HTTPException(409,"数据版本已变化，请重新起草")
        work_id="WO-DRAFT-"+uuid.uuid4().hex[:12].upper()
        now=datetime.now(timezone.utc).isoformat()
        content={**proposal,"work_order_id":work_id,"version":1,"created_at":now,"source":"agent_user_confirmed","recommended_action":proposal["note"]}
        c.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(work_id,proposal["equipment_id"],json.dumps(content,ensure_ascii=False),"草稿·待排程",now))
        proposal["work_order_id"]=work_id
        c.execute("UPDATE settings SET value=? WHERE key=?",(json.dumps(proposal,ensure_ascii=False),"agent_proposal:"+proposal_id))
        c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("agent_draft_confirmed",work_id,json.dumps(proposal,ensure_ascii=False),now))
    return {"success":True,"work_order_id":work_id,"status":"草稿·待排程"}


@app.post("/api/copilot/chat")
async def copilot_chat(inp:ChatInput,request:Request):
    if not is_factorypulse_question(inp.question):
        return {"answer":OUT_OF_SCOPE,"trace":[],"proposals":[]}
    try:
        agent_config=load_config()
    except (ValueError,OSError):
        return {"answer":"Agent配置无效，请核对config/agent.json后重试。","mode":"unavailable","trace":[],"proposals":[]}
    fast_tool=quick_tool(inp.question)
    if fast_tool in agent_config.disabled_tools:
        fast_tool=None
    if fast_tool:
        try:
            evidence=await asyncio.wait_for(asyncio.to_thread(agent_dispatch,fast_tool,{"scenario_id":inp.scenario_id} if fast_tool=="compare_plans" and inp.scenario_id else {}),timeout=15)
            return evidence_answer(fast_tool,evidence)
        except TimeoutError:
            return {"answer":"本地证据计算尚未完成，请稍后重试或进入设备与风险中心核对。","mode":"unavailable","trace":[],"proposals":[]}
        except (ValueError,HTTPException) as exc:
            detail=str(exc.detail) if isinstance(exc,HTTPException) else str(exc)
            return {"answer":plain_answer("本次未完成查询："+detail),"mode":"unavailable","trace":[],"proposals":[]}
    base=settings_get("ai_base_url"); model=settings_get("ai_model")
    if not base or not model or not _api_key:
        if "equipment" in agent_config.disabled_tools:
            return {"answer":"AI服务未连接且本地设备工具已禁用，无法读取证据。","mode":"unavailable","trace":[],"proposals":[]}
        evidence=await asyncio.to_thread(agent_dispatch,"equipment",{})
        return {"answer":"当前未连接AI服务。以下为本地设备查询结果，仍可在工作台完成复核和排程。","mode":"local_fallback","evidence":evidence,"trace":[{"tool":"equipment","source":evidence["source"],"data_time":evidence["data_time"],"status":"success"}],"proposals":[]}
    try: await address_validation.check(base,require_public_https)
    except HTTPException as exc:
        return {"answer":plain_answer("AI连接未就绪："+str(exc.detail)+"。可继续在工作台查询设备和处理维护。"),"mode":"unavailable","trace":[],"proposals":[]}
    try:
        result=await run_agent(base,model,_api_key,inp.question,agent_dispatch,read_only=bool(security.principal() and security.principal()["role"] not in {"admin","manager"}),should_stop=request.is_disconnected)
        return {**result,"mode":"tool_agent","data_note":"模型按需读取所选设备和计算结果；仅可起草需求，正式排程和审批需人工操作"}
    except (httpx.RequestError,RuntimeError,ValueError,IndexError,KeyError):
        return {"answer":"AI服务暂不可用，设备查询和人工维护流程不受影响。请稍后重试或进入工作台继续处理。","mode":"unavailable","trace":[],"proposals":[]}


from .database_import import install_database_import
install_database_import(app,IMPORT_SESSION_DIR,analyze_industrial_file)
install_import_pipeline(app,connect,settings_get,_lock,IMPORT_SESSION_DIR)

install_resource_routes(app,connect,rows,_lock)

from .workflow_board import install_workflow_routes
install_workflow_routes(app,globals())

security.install_auth(app,connect,_lock)

backups.install_backups(app,DB,connect)

# Opt-in local delivery: serve the built UI and API from one loopback origin.
if os.getenv("FACTORYPULSE_SERVE_UI") == "1":
    from fastapi.staticfiles import StaticFiles
    ui_directory = Path(os.getenv("FACTORYPULSE_UI_DIR", PROJECT_ROOT / "dist"))
    if not (ui_directory / "index.html").is_file():
        raise RuntimeError("找不到已构建的前端文件，请先完成前端构建或设置 FACTORYPULSE_UI_DIR")
    app.mount("/", StaticFiles(directory=ui_directory, html=True), name="factorypulse-ui")


from .agent_harness import install_harness
agent_store = install_harness(app, connect, _lock, agent_dispatch, copilot_chat, ChatInput)
