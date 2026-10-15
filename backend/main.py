"""FactoryPulse MVP API: Excel import, SQLite, reproducible maintenance scenarios and API settings."""
from __future__ import annotations
import io, json, math, os, sqlite3, threading, csv, ipaddress, socket
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from typing import Optional
import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openpyxl import load_workbook

DATA_DIR = Path(os.getenv("FACTORYPULSE_DATA_DIR", Path.home() / ".factorypulse"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "factorypulse.sqlite3"
app = FastAPI(title="FactoryPulse MVP", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET","POST"], allow_headers=["*"])
_lock = threading.RLock()
_api_key = os.environ.get("FACTORYPULSE_AI_API_KEY", "")
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
def connect():
    c=sqlite3.connect(DB,timeout=15)
    c.row_factory=sqlite3.Row
    return c
def init():
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS records (table_name TEXT NOT NULL, row_index INTEGER NOT NULL, content TEXT NOT NULL, PRIMARY KEY(table_name,row_index))")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
init()
def rows(table):
    with _lock, connect() as c:
        return [json.loads(r["content"]) for r in c.execute("SELECT content FROM records WHERE table_name=? ORDER BY row_index",(table,))]
def settings_get(name, default=""):
    with connect() as c:
        r=c.execute("SELECT value FROM settings WHERE key=?",(name,)).fetchone()
        return r["value"] if r else default
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
@app.get("/api/health")
def health(): return {"status":"ok","database":str(DB),"version":"0.2.0"}
@app.post("/api/import")
async def import_excel(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"): raise HTTPException(400,"仅支持 .xlsx 工作簿")
    raw=await file.read(8*1024*1024+1)
    if len(raw)>8*1024*1024: raise HTTPException(413,"Excel 文件不可超过8MB")
    try:
        book=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
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
                if len(parsed)>200000: raise ValueError("工作表记录数量超过限制")
            data[name]=parsed
        book.close()
        validate(data)
    except (ValueError,StopIteration) as e: raise HTTPException(422,str(e))
    except Exception as e: raise HTTPException(422,f"工作簿读取失败: {str(e)[:160]}")
    with _lock,connect() as c:
        for name,recs in data.items():
            c.execute("DELETE FROM records WHERE table_name=?",(name,))
            c.executemany("INSERT INTO records(table_name,row_index,content) VALUES (?,?,?)",[(name,i,json.dumps(r,ensure_ascii=False,default=str)) for i,r in enumerate(recs)])
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('import_filename',?)",(file.filename,))
    return {"success":True,"filename":file.filename,"counts":{k:len(v) for k,v in data.items()},"data_origin":"synthetic_test_workbook"}
def snapshot():
    equipment=rows("equipment")
    risks={str(r["equipment_id"]):r for r in rows("demo_risks")}
    readings={}
    for r in rows("readings"):
        eid=str(r["equipment_id"])
        if eid not in readings or str(r.get("timestamp",""))>str(readings[eid].get("timestamp","")): readings[eid]=r
    output=[]
    for e in equipment:
        eid=str(e["equipment_id"]); risk=risks.get(eid,{}); reading=readings.get(eid,{})
        score=num(risk.get("risk_score"))
        output.append({**e,"risk_score":score,"risk_level":"高" if score>=0.7 else "中" if score>=0.4 else "低","risk_origin":risk.get("data_origin","DEMO_ONLY_NOT_MODEL_OUTPUT"),"latest_reading":reading})
    return output
@app.get("/api/overview")
def overview():
    devices=snapshot(); scores=[d["risk_score"] for d in devices]
    return {"devices":devices,"counts":{t:len(rows(t)) for t in TABLES},"metrics":{"total":len(devices),"high":sum(s>=.7 for s in scores),"warning":sum(.4<=s<.7 for s in scores),"avg_risk":round(sum(scores)/len(scores),3) if scores else 0},"filename":settings_get("import_filename"),"risk_source":"Excel 演示风险评分（非训练模型预测）"}
@app.get("/api/records/{table_name}")
def records(table_name:str,limit:int=500):
    if table_name not in TABLES: raise HTTPException(404,"Unknown table")
    if not 1<=limit<=5000: raise HTTPException(400,"limit须在1到5000之间")
    return {"records":rows(table_name)[:limit],"total":len(rows(table_name))}
class SimulationInput(BaseModel):
    scenario_id:Optional[str]=None
    strategy:str="optimized"
    budget:Optional[float]=Field(None,ge=0)
    risk_threshold:Optional[float]=Field(None,ge=0,le=1)
    staff_count:Optional[int]=Field(None,ge=1)
    max_downtime_h:Optional[float]=Field(None,ge=0)
@app.post("/api/simulate")
def simulate(inp:SimulationInput):
    devices=snapshot()
    if not devices: raise HTTPException(400,"请先导入Excel测试工作簿")
    scenarios=rows("scenarios")
    s=next((i for i in scenarios if i.get("scenario_id")==inp.scenario_id),scenarios[0] if scenarios else {})
    budget=inp.budget if inp.budget is not None else num(s.get("maintenance_budget_cny"),3000)
    threshold=inp.risk_threshold if inp.risk_threshold is not None else num(s.get("risk_threshold"),.65)
    staff_count=inp.staff_count if inp.staff_count is not None else int(num(s.get("available_staff_count"),2))
    max_hours=inp.max_downtime_h if inp.max_downtime_h is not None else num(s.get("max_downtime_h"),8)
    if inp.strategy not in ("optimized","risk_threshold","fixed_interval"): raise HTTPException(422,"未知策略")
    rules={r["equipment_id"]:r for r in rows("maintenance_rules")}
    candidates=[]
    for d in devices:
        rule=rules.get(d["equipment_id"],{})
        cost=num(rule.get("inspection_cost_cny"),250)+num(rule.get("repair_cost_cny"),900)
        hours=num(rule.get("inspection_duration_h"),2)+num(rule.get("repair_duration_h"),2)
        loss=num(rule.get("assumed_failure_loss_cny"),3000)
        people=max(1,int(num(rule.get("required_staff_count"),1)))
        risk=d["risk_score"]
        # Illustrative assumption: maintenance lowers relative risk by 60%, NOT a learned causal effect.
        benefit=.6*risk*loss
        candidates.append({ "equipment_id":d["equipment_id"],"equipment_name":d["equipment_name"],"risk":risk,"cost":cost,"hours":hours,"people":people,"expected_loss_avoided":round(benefit,2),"net_value":round(benefit-cost,2) })
    if inp.strategy=="optimized":
        candidates.sort(key=lambda x:(x["net_value"]/max(x["cost"],1),x["risk"]),reverse=True)
    elif inp.strategy=="risk_threshold": candidates.sort(key=lambda x:x["risk"],reverse=True)
    else: candidates.sort(key=lambda x:x["equipment_id"])
    selected=[]; spent=0.; elapsed=0.
    for item in candidates:
        if inp.strategy=="risk_threshold" and item["risk"]<threshold: continue
        if inp.strategy=="optimized" and item["net_value"]<=0: continue
        if item["people"]>staff_count or spent+item["cost"]>budget or elapsed+item["hours"]>max_hours: continue
        selected.append(item); spent+=item["cost"]; elapsed+=item["hours"]
    baseline=sum(d["risk_score"]*num(rules.get(d["equipment_id"],{}).get("assumed_failure_loss_cny"),3000) for d in devices)
    saved=sum(i["expected_loss_avoided"] for i in selected)
    return {"scenario":s.get("scenario_name","自定义"),"strategy":inp.strategy,"constraints":{"budget":budget,"risk_threshold":threshold,"staff_count":staff_count,"max_downtime_h":max_hours},"selected":selected,"summary":{"task_count":len(selected),"maintenance_cost":round(spent,2),"maintenance_hours":round(elapsed,2),"baseline_expected_loss":round(baseline,2),"expected_loss_after":round(baseline-saved,2),"illustrative_total_cost":round(baseline-saved+spent,2)},"disclaimer":"演示规则模型：假定维护使相关风险降低60%，不代表真实设备因果效果或实际经济收益。此版本为确定性贪心方案，不保证全局最优。"}
class ApiSettings(BaseModel):
    provider:str="custom"
    base_url:str=""
    model:str=""
    api_key:Optional[str]=None
@app.get("/api/developer/settings")
def read_api_settings():
    return {"provider":settings_get("ai_provider","custom"),"base_url":settings_get("ai_base_url",""),"model":settings_get("ai_model",""),"has_api_key":bool(_api_key),"key_storage":"当前后端进程内存（重启后需重新输入；亦可设置 FACTORYPULSE_AI_API_KEY 环境变量）"}
@app.post("/api/developer/settings")
def save_api_settings(cfg:ApiSettings):
    global _api_key
    if cfg.base_url: require_public_https(cfg.base_url)
    if cfg.api_key is not None and cfg.api_key.strip(): _api_key=cfg.api_key.strip()
    with _lock,connect() as c:
        for k,v in (("ai_provider",cfg.provider),("ai_base_url",cfg.base_url.rstrip("/")),("ai_model",cfg.model)):
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",(k,v))
    return read_api_settings()
@app.post("/api/developer/test-connection")
async def test_connection():
    base=settings_get("ai_base_url"); model=settings_get("ai_model")
    if not base or not model or not _api_key: raise HTTPException(400,"请先配置API地址、模型和密钥")
    require_public_https(base)
    try:
        async with httpx.AsyncClient(timeout=12,follow_redirects=False,trust_env=False) as client:
            r=await client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+_api_key},json={"model":model,"messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":12})
        if r.status_code>=400: raise HTTPException(400,f"上游返回 HTTP {r.status_code}；请检查地址、密钥和模型。")
        return {"success":True,"message":"API连接测试成功"}
    except httpx.RequestError as e: raise HTTPException(502,"API网络请求失败："+type(e).__name__)

@app.get("/api/strategies/compare")
def compare_strategies(scenario_id:Optional[str]=None):
    if not snapshot(): raise HTTPException(400,"请先导入测试工作簿")
    return {"strategies":[simulate(SimulationInput(scenario_id=scenario_id,strategy=k)) for k in ("fixed_interval","risk_threshold","optimized")],"description":"仅为演示假设下的三策略对照；optimized是贪心规则，不是全局最优算法"}

@app.get("/api/export/maintenance.csv")
def export_plan(scenario_id:Optional[str]=None,strategy:str="optimized"):
    result=simulate(SimulationInput(scenario_id=scenario_id,strategy=strategy))
    out=io.StringIO()
    writer=csv.writer(out)
    writer.writerow(["设备ID","设备名称","模拟风险评分","维护成本(元)","预计工时","所需人员数","模拟避免损失(元)"])
    for item in result["selected"]:
        writer.writerow([item["equipment_id"],item["equipment_name"],item["risk"],item["cost"],item["hours"],item["people"],item["expected_loss_avoided"]])
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
@app.post("/api/copilot/chat")
async def copilot_chat(inp:ChatInput):
    base=settings_get("ai_base_url"); model=settings_get("ai_model")
    if not base or not model or not _api_key: raise HTTPException(400,"请先在开发者设置中填写并保存API配置")
    require_public_https(base)
    summary=overview()
    aggregate={"device_count":summary["metrics"]["total"],"high_risk_demo_count":summary["metrics"]["high"],"warning_demo_count":summary["metrics"]["warning"],"average_demo_risk":summary["metrics"]["avg_risk"],"record_counts":summary["counts"]}
    instruction="你是FactoryPulse模拟数据助手。仅基于提供的汇总数据回答。风险评分来自模拟Excel，并非训练模型；不得编造设备故障、真实收益或维修因果结论。没有数据时明确说明。回答简洁中文。"
    payload={"model":model,"messages":[{"role":"system","content":instruction+" 汇总："+json.dumps(aggregate,ensure_ascii=False)},{"role":"user","content":inp.question}],"max_tokens":500}
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False) as client:
            response=await client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+_api_key},json=payload)
        if response.status_code>=400: raise HTTPException(502,f"AI服务商返回 HTTP {response.status_code}")
        content=response.json().get("choices",[{}])[0].get("message",{}).get("content","")
        if not isinstance(content,str) or not content.strip(): raise HTTPException(502,"AI服务未返回可用文本")
        return {"answer":content[:6000],"data_note":"仅发送设备数量、演示风险汇总与记录数量；未发送原始Excel设备/订单或维修人员记录"}
    except (httpx.RequestError,ValueError,IndexError,KeyError) as e: raise HTTPException(502,"AI服务连接或响应解析失败")
