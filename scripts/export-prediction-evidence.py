"""Recompute evidence from a read-only SQLite snapshot; never import backend.main."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.analytics import xgboost_with_shap


def export(database:Path,destination:Path):
    if not database.is_file(): raise ValueError("指定数据库不存在，不能创建空库代替")
    with closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro",uri=True,timeout=30)) as connection:
        connection.execute("BEGIN")
        settings=dict(connection.execute("SELECT key,value FROM settings WHERE key IN ('last_sync_at','source_name','data_origin','source_date')"))
        raw=[row[0] for row in connection.execute("SELECT content FROM records WHERE table_name='readings' ORDER BY row_index")]
        connection.rollback()
    readings=[json.loads(value) for value in raw]
    if not readings: raise ValueError("数据库中没有监测记录，不能导出预测成绩")
    digest=hashlib.sha256()
    for row in readings:
        digest.update(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode());digest.update(b"\n")
    model=xgboost_with_shap(readings)
    now=datetime.now(timezone.utc)
    folder=destination/(now.strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    dependencies={}
    for package in ("numpy","xgboost","shap"):
        try: dependencies[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: dependencies[package]="unavailable"
    stamps=sorted(str(row["timestamp"]) for row in readings if row.get("timestamp"))
    evidence={"generated_at":now.isoformat(),"source":settings,"input_sha256":digest.hexdigest(),"analytics_code_sha256":hashlib.sha256((ROOT/"backend/analytics.py").read_bytes()).hexdigest(),"dependencies":dependencies,"readings":len(readings),"devices":len({str(row.get("equipment_id")) for row in readings}),"coverage_start":stamps[0] if stamps else None,"coverage_end":stamps[-1] if stamps else None,"model_version":model.model_version,"status":model.status,"message":model.message,"training_rows":model.training_rows,"training_positive_rows":model.positives,"label_basis":model.label_basis,"evaluation":model.evaluation,"probability_claim_allowed":False,"field_trial":"not_provided","downtime_improvement":"not_measured"}
    evidence["code_sha256"]={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ("backend/analytics.py","backend/field_profiles.py","backend/smart_import.py","backend/import_pipeline.py","backend/metropt3.py","backend/nasa_ims.py")}
    evidence["comparison_scope"]="规则对照优先使用baseline.matched_model，与规则采用完全相同的可评估测试窗口；总体模型指标涵盖全部有效测试窗口"
    (folder/"evaluation.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    with (folder/"test-replay.csv").open("w",newline="",encoding="utf-8-sig") as file:
        fields=["equipment_id","timestamp","reading_id","score","alert","observed_future_failure"]
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for row in model.replay:
            safe={key:row.get(key) for key in fields}
            for key in ("equipment_id","reading_id"):
                value=safe[key]
                if isinstance(value,str) and value.startswith(("=","+","-","@")): safe[key]="'"+value
            writer.writerow(safe)
    metrics=model.evaluation
    def percent(key):
        value=metrics.get(key)
        return f"{value*100:.2f}%" if isinstance(value,(int,float)) else "无法计算"
    lead=metrics.get("average_lead_hours")
    summary=f"""# 历史预测证据

生成时间（UTC）：{now.isoformat()}。数据来源：{settings.get('source_name','未提供')}。

监测记录 {len(readings)} 条，设备 {evidence['devices']} 台；覆盖 {evidence['coverage_start']} 至 {evidence['coverage_end']}。

|指标|本次复算结果|
|---|---|
|模型状态|{model.status}|
|测试窗口数|{metrics.get('test_rows','无法计算')}|
|独立测试故障|{metrics.get('independent_test_events','无法计算')}|
|故障前窗口召回率|{percent('recall')}|
|预警命中率|{percent('precision')}|
|正常窗口误报率|{percent('false_alarm_rate')}|
|F1|{metrics.get('f1','无法计算')}|
|独立事件检出率|{percent('event_recall')}|
|实测平均提前量|{str(lead)+' 小时' if lead is not None else '无法计算'}|

{model.message}

模型与规则基线使用相同测试范围；分区、阈值和事件明细见 evaluation.json。test-replay.csv 保留本次测试的逐窗口结果，便于核对提醒、漏报和误报。

当前输出不是校准故障概率。独立事件少不能证明跨设备泛化；未提供真实设备主管试用，未测量停机改善，不承诺比赛奖项。

输入摘要：{evidence['input_sha256']}。代码摘要：{evidence['analytics_code_sha256']}。复算需保留同一输入、代码与依赖版本；摘要不能替代原始数据留存。
"""
    (folder/"README.md").write_text(summary,encoding="utf-8")
    return folder,evidence


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="只读复算并导出历史预测证据")
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"outputs/prediction-evidence")
    args=parser.parse_args()
    folder,evidence=export(args.database,args.output)
    print(json.dumps({"output":str(folder),"status":evidence["status"],"readings":evidence["readings"],"evaluation":{key:evidence["evaluation"].get(key) for key in ("test_rows","independent_test_events","precision","recall","false_alarm_rate","average_lead_hours")}},ensure_ascii=False))
