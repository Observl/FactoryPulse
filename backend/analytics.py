"""Auditable predictive-maintenance analytics for CNC equipment."""
from __future__ import annotations
import math
import re
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from .field_profiles import EXTRA_FIELDS, COMMON, feature_candidates

FEATURES = ["air_temperature_k", "process_temperature_k", "rotational_speed_rpm", "torque_nm", "tool_wear_min", "vibration_mm_s", "vibration_g", "vibration_peak_g", "vibration_kurtosis", "spindle_load_pct", "oil_temperature_c", "motor_current_a", "tp2_bar", "tp3_bar", "h1_bar", "dv_pressure_bar", "reservoirs_bar", "comp", "pressure_switch", "oil_level"]
FEATURES=list(dict.fromkeys(FEATURES+[field for field in EXTRA_FIELDS if field not in COMMON]))

def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError): return default


def skill_set(value: Any) -> set[str]:
    values=value if isinstance(value,list) else re.split(r"[,，;；|]",str(value or ""))
    return {str(item).strip().casefold() for item in values if str(item).strip()}

def _feature_row(reading: dict[str, Any], features: list[str] | None = None) -> list[float]:
    return [_num(reading.get(name), math.nan) for name in (features or FEATURES)]

def ewma_scores(readings: list[dict[str, Any]], alpha: float = 0.35) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in readings: grouped.setdefault(str(row.get("equipment_id", "")), []).append(row)
    result = {}
    for equipment_id, series in grouped.items():
        ordered = sorted(series, key=lambda row: str(row.get("timestamp", "")))
        values = []
        names=ordered[0].get("_feature_fields",["vibration_g", "vibration_mm_s", "motor_current_a", "tp2_bar"])
        chosen=next((name for name in names if any(math.isfinite(_num(row.get(name),math.nan)) for row in ordered)),None)
        for row in ordered:
            signal = row.get(chosen,math.nan)
            values.append(_num(signal, math.nan))
        values = [value for value in values if math.isfinite(value)]
        if chosen is not None and not math.isfinite(_num(ordered[-1].get(chosen),math.nan)):
            result[equipment_id] = {"score":None,"status":"missing_latest_reading","samples":len(values),"alpha":alpha,"feature":chosen}; continue
        if len(values) < 12:
            result[equipment_id] = {"score": None, "status": "insufficient_history", "samples": len(values), "alpha": alpha}; continue
        mean, residuals = values[0], []
        for value in values[1:]:
            previous = mean; mean = alpha * value + (1 - alpha) * mean; residuals.append(abs(value - previous))
        baseline = max(sum(residuals[:-1] or residuals) / max(len(residuals[:-1]), 1), 0.05)
        result[equipment_id] = {"score": round(min(abs(values[-1] - mean) / baseline / 6, 1), 4), "status": "ready", "samples": len(values), "alpha": alpha, "ewma": round(mean, 3)}
    return result

@dataclass
class ModelOutput:
    predictions: dict[str, float]
    explanations: dict[str, list[dict[str, Any]]]
    status: str
    message: str
    training_rows: int
    positives: int
    label_basis: str
    evaluation: dict[str, Any]
    model_version: str = "industrial-xgb-purged-v8"
    replay: list[dict] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)

def _metrics(labels: Any, probabilities: Any, threshold: float = .5) -> dict[str, float]:
    predicted = probabilities >= threshold
    tp=int(((predicted==1)&(labels==1)).sum()); fp=int(((predicted==1)&(labels==0)).sum())
    fn=int(((predicted==0)&(labels==1)).sum()); tn=int(((predicted==0)&(labels==0)).sum())
    precision=tp/(tp+fp) if tp+fp else 0.; recall=tp/(tp+fn) if tp+fn else 0.
    return {"precision":round(precision,4),"recall":round(recall,4),"f1":round(2*precision*recall/(precision+recall),4) if precision+recall else 0.,"false_alarm_rate":round(fp/(fp+tn),4) if fp+tn else 0.,"true_positives":tp,"false_positives":fp,"false_negatives":fn,"true_negatives":tn}


def pool_window_metrics(evaluations: list[dict]) -> dict:
    """Pool underlying counts, never average percentages across unequal groups."""
    keys=("true_positives","false_positives","false_negatives","true_negatives")
    available=[item for item in evaluations if all(isinstance(item.get(key),(int,float)) and math.isfinite(item[key]) and item[key]>=0 for key in keys)]
    if not available: return {key:None for key in ("precision","recall","f1","false_alarm_rate")}
    counts={key:sum(int(item[key]) for item in available) for key in keys}
    tp,fp,fn,tn=(counts[key] for key in keys)
    return {**counts,"precision":round(tp/(tp+fp),4) if tp+fp else 0.,"recall":round(tp/(tp+fn),4) if tp+fn else 0.,"f1":round(2*tp/(2*tp+fp+fn),4) if 2*tp+fp+fn else 0.,"false_alarm_rate":round(fp/(fp+tn),4) if fp+tn else 0.}


def chronological_partitions(readings: list[dict], horizon: int) -> tuple[list, list, list]:
    """Reserve validation separately and purge labels crossing either boundary."""
    ordered = sorted(readings, key=lambda row: str(row["timestamp"]))
    explicit_test = [r for r in ordered if r.get("evaluation_split") == "test"]
    boundary = datetime.fromisoformat(explicit_test[0]["timestamp"]) if explicit_test else datetime.fromisoformat(ordered[int(len(ordered)*.8)]["timestamp"])
    before = [r for r in ordered if datetime.fromisoformat(r["timestamp"]) + timedelta(hours=horizon) < boundary]
    if not before:
        return [], [], []
    validation_start = datetime.fromisoformat(before[int(len(before)*.75)]["timestamp"])
    train = [r for r in before if datetime.fromisoformat(r["timestamp"]) + timedelta(hours=horizon) < validation_start]
    validation = [r for r in before if datetime.fromisoformat(r["timestamp"]) >= validation_start]
    test = [r for r in ordered if datetime.fromisoformat(r["timestamp"]) >= boundary]
    return train, validation, test


def event_evaluation(history: list[dict], test: list[dict], scores: Any, threshold: float, horizon: int) -> dict:
    """Score independent fault onsets, never substitute horizon for measured lead."""
    onsets = []
    previous: dict[str, int|None] = {}
    for row in sorted(history, key=lambda r: str(r["timestamp"])):
        equipment = str(row["equipment_id"])
        observed=_num(row.get("failure"),math.nan)
        failed=int(observed) if observed in (0.,1.) else None
        if failed==1 and previous.get(equipment)==0:
            onsets.append((equipment, datetime.fromisoformat(row["timestamp"])))
        previous[equipment] = failed
    leads = []
    events = []
    for equipment, onset in onsets:
        eligible = [(datetime.fromisoformat(row["timestamp"]), float(score)) for row, score in zip(test, scores) if str(row["equipment_id"]) == equipment and onset-timedelta(hours=horizon) <= datetime.fromisoformat(row["timestamp"]) < onset]
        if not eligible:
            continue
        hits = [moment for moment, score in eligible if score >= threshold]
        lead = (onset-min(hits)).total_seconds()/3600 if hits else None
        if lead is not None:
            leads.append(lead)
        events.append({"equipment_id":equipment,"failure_at":onset.isoformat(),"detected":bool(hits),"first_alert_at":min(hits).isoformat() if hits else None,"lead_hours":round(lead,2) if lead is not None else None})
    return {"independent_test_events":len(events),"detected_events":len(leads),"event_recall":len(leads)/len(events) if events else None,"average_lead_hours":round(sum(leads)/len(leads),2) if leads else None,"events":events}

def alarm_burden(history, rows, scores, threshold, horizon):
    """Merge contiguous alert windows into episodes and expose review workload."""
    grouped={}
    for row,score in zip(rows,scores): grouped.setdefault(str(row["equipment_id"]),[]).append((row,float(score)))
    episodes=[];days=set();alert_windows=0
    for equipment,series in grouped.items():
        series.sort(key=lambda item:item[0]["timestamp"])
        deltas=[(datetime.fromisoformat(b[0]["timestamp"])-datetime.fromisoformat(a[0]["timestamp"])).total_seconds()/3600 for a,b in zip(series,series[1:])]
        cadence=sorted([v for v in deltas if v>0]);gap=(cadence[len(cadence)//2]*1.5 if cadence else 24)
        active=None
        for row,score in series:
            moment=datetime.fromisoformat(row["timestamp"]);days.add((equipment,moment.date().isoformat()))
            if score<threshold: active=None;continue
            alert_windows+=1
            if active is None or (moment-datetime.fromisoformat(active["end_at"])).total_seconds()/3600>gap:
                active={"equipment_id":equipment,"start_at":row["timestamp"],"end_at":row["timestamp"],"windows":0,"matched_future_fault":False};episodes.append(active)
            active["end_at"]=row["timestamp"];active["windows"]+=1
            active["matched_future_fault"]|=row.get("future_failure")==1
    events=event_evaluation(history,rows,scores,threshold,horizon)["events"]
    confirmed=[]
    for event in events:
        onset=datetime.fromisoformat(event["failure_at"])
        hits=[datetime.fromisoformat(row["timestamp"]) for row,score in zip(rows,scores) if str(row["equipment_id"])==event["equipment_id"] and onset-timedelta(hours=horizon)<=datetime.fromisoformat(row["timestamp"])<onset and float(score)>=threshold]
        # Second consecutive alert is an operational confirmation, reported separately from first hit.
        eligible=sorted([row for row in rows if str(row["equipment_id"])==event["equipment_id"] and onset-timedelta(hours=horizon)<=datetime.fromisoformat(row["timestamp"])<onset],key=lambda row:row["timestamp"])
        hit_set=set(hits);pair=next((datetime.fromisoformat(b["timestamp"]) for a,b in zip(eligible,eligible[1:]) if datetime.fromisoformat(a["timestamp"]) in hit_set and datetime.fromisoformat(b["timestamp"]) in hit_set),None)
        confirmed.append({"equipment_id":event["equipment_id"],"failure_at":event["failure_at"],"confirmed_lead_hours":round((onset-pair).total_seconds()/3600,2) if pair else None})
    return {"alert_windows":alert_windows,"alert_window_fraction":round(alert_windows/len(rows),4) if rows else None,"alert_episodes":len(episodes),"false_alert_episodes":sum(not e["matched_future_fault"] for e in episodes),"episodes_per_device_week":round(len(episodes)/len(days)*7,4) if days else None,"device_days":len(days),"episode_definition":"相邻提醒窗口合并，超过1.5倍设备中位采样间隔重新计次；不是实际出勤数","confirmation_definition":"连续两条可评估记录达到提醒线；首次命中提前量仍独立保留","confirmed_events":confirmed}


def _xgboost_single(readings: list[dict[str, Any]]) -> ModelOutput:
    try:
        import numpy as np
        import shap
        from xgboost import XGBClassifier
    except ImportError:
        return ModelOutput({}, {}, "dependency_missing", "未安装 xgboost / shap / numpy", 0, 0, "unavailable", {})
    usable = sorted([r for r in readings if r.get("equipment_id") and r.get("timestamp") and r.get("future_failure") in (0, 1) and not _num(r.get("failure"))], key=lambda r: str(r["timestamp"]))
    positives = sum(int(r["future_failure"]) for r in usable)
    horizon = int(_num(usable[0].get("prediction_horizon_hours"), 168)) if usable else 168
    basis = f"observed_future_failure_{horizon}h"
    def insufficient(message):
        return ModelOutput({}, {}, "insufficient_labels", message, len(usable), positives, basis, {})
    if len(usable) < 200 or positives < 4:
        return insufficient("完整未来窗口的故障标签不足，未生成模型评分")
    train, validation, test = chronological_partitions(usable, horizon)
    if any(len(part) < 20 or len({r["future_failure"] for r in part}) < 2 for part in (train, validation, test)):
        return insufficient("隔离预测窗口后，训练、验证或测试段缺少正负样本；证据不足")
    # Select only available training features. Missing readings stay NaN for XGBoost.
    features = [name for name in feature_candidates(train,FEATURES) if any(r.get(name) not in (None, "") for r in train)]
    if not features:
        return insufficient("训练段无可用监测指标")
    from .adaptive_training import load_training_config,causal_features,context_residuals,choose_model
    config=load_training_config()
    raw_features=[name for name in features if name not in config.excluded_features];engineered=[]
    if not raw_features:return insufficient("所选指标已全部禁用，无法训练")
    if config.enabled:
        originals=readings
        if config.temporal_features:prepared,engineered=causal_features(originals,raw_features)
        else:prepared=[dict(row) for row in originals]
        mapping={id(row):prepared[i] for i,row in enumerate(originals)}
        train,validation,test=([mapping[id(row)] for row in part] for part in (train,validation,test))
        readings=prepared
    preprocessing={}
    if config.enabled:
        added,preprocessing=context_residuals(readings,train,raw_features)
        engineered.extend(added)
    def has_sensor(row): return any(math.isfinite(_num(row.get(name),math.nan)) for name in raw_features)
    excluded={name:sum(not has_sensor(row) for row in part) for name,part in (("train",train),("validation",validation),("test",test))}
    train,validation,test=([row for row in part if has_sensor(row)] for part in (train,validation,test))
    if any(len(part)<20 or len({row["future_failure"] for row in part})<2 for part in (train,validation,test)):
        return insufficient("剔除全部指标缺失的窗口后，训练、验证或测试证据不足")
    matrix = lambda part: np.asarray([_feature_row(r, features) for r in part], dtype=float)
    labels = lambda part: np.asarray([int(r["future_failure"]) for r in part], dtype=int)
    y_train = labels(train)
    model,features,threshold,training_report,artifact=choose_model(train,validation,raw_features,engineered,config)
    artifact["context_residuals"]=preprocessing
    artifact["temporal_features"]=config.enabled and config.temporal_features
    training_report["weights_sha256"]=hashlib.sha256(json.dumps({key:value for key,value in artifact.items() if key!="training"},sort_keys=True,separators=(",",":")).encode()).hexdigest()
    test_scores = model.predict_proba(matrix(test))[:,1]
    # Same evaluation window and labels for the transparent operational baseline.
    def baseline_score(row):
        if "tp3_bar" in raw_features:
            if any(not math.isfinite(_num(row.get(field),math.nan)) for field in ("tp3_bar","reservoirs_bar","oil_temperature_c")): return math.nan
            return min(.95,.03+abs(float(row["tp3_bar"])-float(row["reservoirs_bar"]))*.12+max(float(row["oil_temperature_c"])-75,0)*.012)
        available=[_num(row.get(field),math.nan)/scale for field,scale in (("vibration_mm_s",10),("vibration_g",2))]
        available=[value for value in available if math.isfinite(value)]
        return min(1.,max(available)) if available else math.nan
    baseline_scores=np.asarray([baseline_score(row) for row in test])
    baseline_valid=np.isfinite(baseline_scores)
    baseline_metrics=_metrics(labels(test)[baseline_valid],baseline_scores[baseline_valid],.35) if baseline_valid.any() else {key:None for key in ("precision","recall","f1","false_alarm_rate")}
    baseline_metrics.update(evaluated_rows=int(baseline_valid.sum()),unavailable_rows=int((~baseline_valid).sum()),coverage=float(baseline_valid.mean()),comparison_basis="同一测试时间范围；缺少规则必要指标的窗口不伪造结果，比较时需核对覆盖率")
    baseline_metrics["matched_model"]=_metrics(labels(test)[baseline_valid],test_scores[baseline_valid],threshold) if baseline_valid.any() else {key:None for key in ("precision","recall","f1","false_alarm_rate")}
    baseline_metrics["comparison_basis"]="模型与规则对照使用完全相同的可评估窗口；模型提醒线仍由各自验证集确定，未在测试集重新选择"
    event_metrics = event_evaluation(readings, test, test_scores, threshold, horizon)
    evaluation = {**_metrics(labels(test),test_scores,threshold),**event_metrics,"test_start":test[0]["timestamp"],"test_end":test[-1]["timestamp"],"test_rows":len(test),"test_failures":int(labels(test).sum()),"positive_windows":int(labels(test).sum()),"prediction_horizon_hours":horizon,"split_method":"purged_train_validation_test","purge_hours":horizon,"threshold":threshold,"threshold_source":"validation_f1","validation_start":validation[0]["timestamp"],"validation_end":validation[-1]["timestamp"],"train_end":train[-1]["timestamp"],"baseline":baseline_metrics,"label_basis":basis,"probability_calibrated":False,"feature_names":features,"evidence_status":"limited_independent_events" if event_metrics["independent_test_events"] < 10 else "requires_external_validation"}
    origins=sorted({str(row.get("data_origin") or "unspecified") for row in readings})
    evaluation["data_origins"]=origins
    evaluation["synthetic_validation_only"]=bool(origins) and all(origin.startswith("SYNTHETIC_") for origin in origins)
    evaluation["alarm_burden"]=alarm_burden(readings,test,test_scores,threshold,horizon)
    evaluation["score_scope"]="模型评分与验证集阈值；设备等级展示线不等于模型告警策略"
    evaluation["adaptive_training"]=training_report
    fitted_version="industrial-adaptive-v1-"+training_report["weights_sha256"][:12]
    latest = {}
    for row in sorted(readings, key=lambda r:str(r.get("timestamp",""))):
        if row.get("equipment_id") and row.get("timestamp"):
            latest[str(row["equipment_id"])] = row
    evaluation["excluded_sensorless_windows"]=excluded
    latest_rows = [row for row in latest.values() if has_sensor(row) and _num(row.get("failure"))!=1]
    evaluation["unscored_latest_equipment"]=[{"equipment_id":eid,"reason":"already_failed" if _num(row.get("failure"))==1 else "missing_latest_features"} for eid,row in latest.items() if not has_sensor(row) or _num(row.get("failure"))==1]
    replay=[{"equipment_id":row["equipment_id"],"timestamp":row["timestamp"],"reading_id":row.get("reading_id"),"score":round(float(score),5),"alert":bool(score>=threshold),"observed_future_failure":int(row["future_failure"])} for row,score in zip(test,test_scores)]
    if not latest_rows:
        return ModelOutput({}, {},"ready","历史评估完成；最新采样指标缺失或设备已故障，未生成当前模型评分",len(train),int(y_train.sum()),basis,evaluation,model_version=fitted_version,replay=replay,artifact=artifact)
    latest_matrix = matrix(latest_rows)
    scores = model.predict_proba(latest_matrix)[:,1]
    predictions = {str(r["equipment_id"]):round(float(scores[i]),4) for i,r in enumerate(latest_rows)}
    explanations = {}
    try:
        values = shap.TreeExplainer(model).shap_values(latest_matrix)
        values = values[-1] if isinstance(values,list) else values
        for ri,row in enumerate(latest_rows):
            explanations[str(row["equipment_id"])] = sorted(({"feature":name,"value":float(latest_matrix[ri,col]) if math.isfinite(latest_matrix[ri,col]) else None,"shap":round(float(values[ri,col]),4)} for col,name in enumerate(features)),key=lambda item:abs(item["shap"]),reverse=True)[:5]
    except Exception as exc:
        return ModelOutput(predictions,{},"shap_error",f"评分已计算，解释不可用：{type(exc).__name__}",len(train),int(y_train.sum()),basis,evaluation,model_version=fitted_version,artifact=artifact)
    replay=[{"equipment_id":row["equipment_id"],"timestamp":row["timestamp"],"reading_id":row.get("reading_id"),"score":round(float(score),5),"alert":bool(score>=threshold),"observed_future_failure":int(row["future_failure"])} for row,score in zip(test,test_scores)]
    limitation="模拟数据仅验证程序，不代表现场效果" if evaluation["synthetic_validation_only"] else ("独立故障事件有限" if event_metrics["independent_test_events"]<10 else "现场效果仍需独立验证")
    return ModelOutput(predictions,explanations,"ready",f"未来{horizon}小时风险评分；已隔离时间窗口，{limitation}，未经概率校准",len(train),int(y_train.sum()),basis,evaluation,model_version=fitted_version,replay=replay,artifact=artifact)


def xgboost_with_shap(readings: list[dict[str, Any]]) -> ModelOutput:
    # Different device families and selected feature contracts never share a model.
    groups={}
    for row in readings:
        key=(row.get("_equipment_profile","legacy"),tuple(sorted(row.get("_feature_fields",FEATURES))))
        groups.setdefault(key,[]).append(row)
    if len(groups)<=1:
        result=_xgboost_single(readings)
        if groups and next(iter(groups))[0]!="legacy":
            result.evaluation["equipment_profile"]=next(iter(groups))[0]
        return result
    predictions={}; explanations={}; replay=[]; details=[]; outputs=[]
    for (profile,features),history in groups.items():
        item=_xgboost_single(history);outputs.append(item)
        predictions.update(item.predictions);explanations.update(item.explanations);replay.extend(item.replay)
        details.append({"profile_id":profile,"feature_names":list(features),"equipment_ids":sorted({str(row['equipment_id']) for row in history}),"status":item.status,"message":item.message,"evaluation":item.evaluation})
    valid=[item.evaluation for item in outputs if item.evaluation.get("test_rows")]
    evaluation={"profile_results":details,"prediction_horizon_hours":168,"probability_calibrated":False,"split_method":"per_profile_purged_train_validation_test","threshold_source":"each_profile_validation_f1","baseline":{},"evidence_status":"requires_profile_review"}
    if valid:
        for key in ("true_positives","false_positives","false_negatives","true_negatives","test_rows","positive_windows","independent_test_events","detected_events"):
            evaluation[key]=sum(item.get(key,0) for item in valid)
        tp,fp,fn,tn=(evaluation[key] for key in ("true_positives","false_positives","false_negatives","true_negatives"))
        evaluation.update(precision=tp/(tp+fp) if tp+fp else 0,recall=tp/(tp+fn) if tp+fn else 0,false_alarm_rate=fp/(fp+tn) if fp+tn else 0,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,test_start=min(item["test_start"] for item in valid),test_end=max(item["test_end"] for item in valid),events=[event for item in valid for event in item.get("events",[])],feature_names=sorted({name for item in valid for name in item.get("feature_names",[])}))
        leads=[event["lead_hours"] for event in evaluation["events"] if event.get("lead_hours") is not None]
        evaluation["average_lead_hours"]=sum(leads)/len(leads) if leads else None
        evaluation.update(pool_window_metrics(valid))
        evaluation["test_failures"]=evaluation["positive_windows"]
        evaluation["event_recall"]=evaluation["detected_events"]/evaluation["independent_test_events"] if evaluation["independent_test_events"] else None
        baselines=[item.get("baseline",{}) for item in valid]
        evaluated=sum(item.get("evaluated_rows",0) for item in baselines)
        evaluation["baseline"]={**pool_window_metrics(baselines),"evaluated_rows":evaluated,"unavailable_rows":evaluation["test_rows"]-evaluated,"coverage":evaluated/evaluation["test_rows"],"matched_model":pool_window_metrics([item.get("matched_model",{}) for item in baselines]),"comparison_basis":"按各设备方案的共同可评估窗口汇总计数；不直接平均百分比，未在测试集调整提醒线"}
        evaluation["excluded_sensorless_windows"]={split:sum(item.get("excluded_sensorless_windows",{}).get(split,0) for item in valid) for split in ("train","validation","test")}
    evaluation.update(validated_profiles=len(valid),total_profiles=len(groups),available_current_predictions=len(predictions),unscored_latest_equipment=[row for item in outputs for row in item.evaluation.get("unscored_latest_equipment",[])])
    status="ready" if len(valid)==len(groups) else "partially_ready" if valid else "insufficient_labels"
    artifacts={"profiles":[{"profile_id":details[index]["profile_id"],"equipment_ids":details[index]["equipment_ids"],"artifact":output.artifact} for index,output in enumerate(outputs) if output.artifact]}
    version="industrial-adaptive-multi-"+hashlib.sha256(json.dumps(artifacts,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:12] if artifacts["profiles"] else "industrial-xgb-purged-v8"
    return ModelOutput(predictions,explanations,status,f"{len(groups)}套设备字段方案中{len(valid)}套完成历史验证；{len(predictions)}台有当前模型评分，未评分原因请查看设备方案；评分未经概率校准",sum(item.training_rows for item in outputs),sum(item.positives for item in outputs),"observed_future_failure_168h",evaluation,replay=sorted(replay,key=lambda row:row['timestamp']),model_version=version,artifact=artifacts)


def combine_risks(rule_score: float, ewma: float|None, model: float|None) -> float:
    weighted=[(max(0,min(rule_score,1)),.35)]
    if ewma is not None: weighted.append((max(0,min(ewma,1)),.15))
    if model is not None: weighted.append((max(0,min(model,1)),.5))
    total=sum(w for _,w in weighted); return round(sum(v*w for v,w in weighted)/total,4)

def cp_sat_select(candidates:list[dict[str,Any]],budget:float,max_hours:float,staff_count:int)->tuple[list[dict[str,Any]],str]:
    try: from ortools.sat.python import cp_model
    except ImportError: return [],"dependency_missing"
    model=cp_model.CpModel(); variables=[model.new_bool_var(f"maintain_{i}") for i in range(len(candidates))]; scale=100
    model.add(sum(int(round(x["cost"]*scale))*variables[i] for i,x in enumerate(candidates))<=int(round(budget*scale)))
    model.add(sum(int(round(x["hours"]*scale))*variables[i] for i,x in enumerate(candidates))<=int(round(max_hours*scale)))
    model.add(sum(int(round(x["hours"]*x["people"]*scale))*variables[i] for i,x in enumerate(candidates))<=int(round(max_hours*staff_count*scale)))
    stock={}
    for item in candidates:
        for part in item.get("spare_parts",[]):
            name=str(part.get("part_name",""))
            stock[name]=min(stock.get(name,int(_num(part.get("available_quantity")))),int(_num(part.get("available_quantity"))))
    for name,quantity in stock.items():
        model.add(sum(sum(int(_num(part.get("quantity"))) for part in item.get("spare_parts",[]) if str(part.get("part_name",""))==name)*variables[index] for index,item in enumerate(candidates))<=quantity)
    model.maximize(sum(int(round(max(x.get("priority_score",x.get("risk",0)),0)*10000))*variables[i] for i,x in enumerate(candidates)))
    solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=5.; solver.parameters.num_search_workers=4; status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        return [],"time_limit" if status==cp_model.UNKNOWN else ("invalid" if status==cp_model.MODEL_INVALID else "infeasible")
    return [x for i,x in enumerate(candidates) if solver.value(variables[i])],"optimal" if status==cp_model.OPTIMAL else "feasible"

def schedule_selected(selected:list[dict[str,Any]],staff:list[dict[str,Any]],orders:list[dict[str,Any]],start_at:str|None=None,staff_limit:int|None=None,bookings:list[dict]|None=None,allow_subset:bool=False,budget:float|None=None,max_hours:float|None=None)->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    """Jointly assign teams and nonoverlapping maintenance intervals with CP-SAT."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return [],[{"reason":"排程引擎不可用","suggestion":"安装 OR-Tools 后重新生成"}]
    base=datetime.fromisoformat(start_at) if start_at else datetime.now().replace(minute=0,second=0,microsecond=0)
    def minute(value, fallback):
        if not value: return fallback
        return int((datetime.fromisoformat(str(value))-base).total_seconds()/60)
    model=cp_model.CpModel()
    intervals_by_staff={str(p.get("staff_id")):[] for p in staff}
    intervals_by_device={}
    tasks=[]; conflicts=[]; capacity_intervals=[]; capacity_demands=[];presence={}
    stock={}; demand={}; end_limits={}
    for item in selected:
        for part in item.get("spare_parts",[]):
            name=str(part.get("part_name",""))
            if not name: continue
            stock[name]=min(stock.get(name,int(_num(part.get("available_quantity")))),int(_num(part.get("available_quantity"))))
            demand[name]=demand.get(name,0)+int(_num(part.get("quantity")))
    insufficient=[name for name in demand if demand[name]>stock[name]]
    shared_conflicts=[{"reason":f"共享备件 {name} 合计需要 {demand[name]}，可用 {stock[name]}","suggestion":"补充库存或减少本轮任务后重算"} for name in insufficient]
    for booking_index,booking in enumerate(bookings or []):
        if not booking.get("start_at") or not booking.get("end_at"): continue
        first=max(0,minute(booking["start_at"],0));last=minute(booking["end_at"],0)
        if last<=first: continue
        fixed=model.new_fixed_size_interval_var(first,last-first,f"booked_{booking_index}")
        intervals_by_device.setdefault(str(booking["equipment_id"]),[]).append(fixed)
        team=booking.get("staff_ids") or [booking.get("staff_id")]
        for identifier in team:
            if str(identifier) in intervals_by_staff: intervals_by_staff[str(identifier)].append((fixed,1,last-first))
        capacity_intervals.append(fixed);capacity_demands.append(len(team))
    for index,item in enumerate(selected):
        equipment=str(item["equipment_id"])
        duration=max(1,int(math.ceil(_num(item.get("hours"),1)*60)))
        skill=str(item.get("required_skill") or "机修")
        needed=max(1,int(_num(item.get("people"),1)))
        eligible=[p for p in staff if skill_set(skill).issubset(skill_set(p.get("skills"))) and _num(p.get("available_hours"),0)*60>=duration]
        if len(eligible)<needed:
            conflicts.append({"equipment_id":equipment,"reason":f"需要 {needed} 名具备 {skill} 技能的人员，当前仅 {len(eligible)} 名","suggestion":"补充技能人员或调整班次后重算"});continue
        if any(_num(part.get("quantity"),1)>_num(part.get("available_quantity"),0) for part in item.get("spare_parts",[])):
            conflicts.append({"equipment_id":equipment,"reason":"备件库存不足","suggestion":"补充备件后重算"});continue
        lower=max(0,minute(item.get("window_start"),0)); upper=minute(item.get("window_end"),24*60)
        if upper-lower<duration:
            conflicts.append({"equipment_id":equipment,"reason":"设备停机窗口不足","suggestion":"延长停机窗口或调整维修任务"});continue
        if allow_subset:
            if budget is not None and _num(item.get("cost"))>budget:
                conflicts.append({"equipment_id":equipment,"reason":"单项维修费用已超过本轮预算","suggestion":"核对费用或提高预算后重新计算"});continue
            if max_hours is not None and duration>max_hours*60:
                conflicts.append({"equipment_id":equipment,"reason":"单项维修工时已超过累计停机上限","suggestion":"核对工时或调整本轮累计工时上限"});continue
            eligible=[person for person in eligible if min(upper,minute(person.get("shift_end"),int(_num(person.get("available_hours"),8)*60)))-max(lower,max(0,minute(person.get("shift_start"),0)))>=duration]
            if len(eligible)<needed:
                conflicts.append({"equipment_id":equipment,"reason":"具备技能的人员班次与设备窗口交集不足","suggestion":"调整班次或设备停机窗口，保证所需人员可以同时参与"});continue
        end_limits[equipment]=max(0,upper)
        start=model.new_int_var(lower,upper-duration,f"start_{index}")
        end=model.new_int_var(lower+duration,upper,f"end_{index}")
        model.add(end==start+duration)
        present=model.new_bool_var(f"selected_{index}") if allow_subset else 1
        presence[equipment]=present
        interval=model.new_optional_interval_var(start,duration,end,present,f"device_{index}") if allow_subset else model.new_interval_var(start,duration,end,f"device_{index}")
        capacity_intervals.append(interval);capacity_demands.append(needed)
        intervals_by_device.setdefault(equipment,[]).append(interval)
        assignments=[]
        for person in eligible:
            person_id=str(person["staff_id"])
            assigned=model.new_bool_var(f"assign_{index}_{person_id}")
            shift_start=max(0,minute(person.get("shift_start"),0))
            shift_end=minute(person.get("shift_end"),int(_num(person.get("available_hours"),8)*60))
            model.add(start>=shift_start).only_enforce_if(assigned)
            model.add(end<=shift_end).only_enforce_if(assigned)
            staff_interval=model.new_optional_interval_var(start,duration,end,assigned,f"staff_{index}_{person_id}")
            intervals_by_staff[person_id].append((staff_interval,assigned,duration))
            assignments.append((person,assigned))
        model.add(sum(flag for _,flag in assignments)==needed*present)
        affected=[o for o in orders if str(o.get("equipment_id"))==equipment]
        for oi,order in enumerate(affected):
            if order.get("start_at") and order.get("end_at"):
                os=minute(order["start_at"],0); oe=minute(order["end_at"],0)
                if oe<=os: raise ValueError("生产订单结束时间必须晚于开始时间")
                before=model.new_bool_var(f"before_{index}_{oi}")
                model.add(end<=os).only_enforce_if([before,present] if allow_subset else [before])
                model.add(start>=oe).only_enforce_if([before.Not(),present] if allow_subset else [before.Not()])
        tasks.append((item,start,end,assignments,affected))
    for parts in intervals_by_staff.values():
        model.add_no_overlap([interval for interval,_,_ in parts])
    for person in staff:
        parts=intervals_by_staff[str(person["staff_id"])]
        model.add(sum(flag*duration for _,flag,duration in parts)<=int(_num(person.get("available_hours"),8)*60))
    for intervals in intervals_by_device.values(): model.add_no_overlap(intervals)
    model.add_cumulative(capacity_intervals,capacity_demands,staff_limit if staff_limit is not None else max(1,len(staff)))
    if (shared_conflicts and not allow_subset) or not tasks: return [],conflicts+([] if allow_subset else shared_conflicts)
    if allow_subset:
        if budget is not None:model.add(sum(int(round(_num(item.get("cost"))*100))*presence[str(item["equipment_id"])] for item,_,_,_,_ in tasks)<=int(math.floor(budget*100+.00001)))
        if max_hours is not None:model.add(sum(int(math.ceil(_num(item.get("hours"))*60))*presence[str(item["equipment_id"])] for item,_,_,_,_ in tasks)<=int(math.floor(max_hours*60+.00001)))
        for name,available in stock.items():
            model.add(sum(sum(int(_num(part.get("quantity"))) for part in item.get("spare_parts",[]) if str(part.get("part_name",""))==name)*presence[str(item["equipment_id"])] for item,_,_,_,_ in tasks)<=available)
        completion_bound=sum(end_limits.values())+1
        model.maximize(completion_bound*sum(max(1,int(round(_num(item.get("priority_score"),_num(item.get("risk")))*10000)))*presence[str(item["equipment_id"])] for item,_,_,_,_ in tasks)-sum(end for _,_,end,_,_ in tasks))
    else:model.minimize(sum(end for _,_,end,_,_ in tasks))
    solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=10.;solver.parameters.num_search_workers=1
    status=solver.solve(model)
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        reason="求解超时，尚未找到可行安排" if status==cp_model.UNKNOWN else ("排程配置无法建立有效模型" if status==cp_model.MODEL_INVALID else "人员班次、设备窗口或生产订单占用存在冲突")
        suggestion="缩小任务范围或稍后重新计算，超时不代表一定无解" if status==cp_model.UNKNOWN else "调整班次、停机窗口或生产订单后重算"
        return [],conflicts+[{"equipment_id":item["equipment_id"],"reason":reason,"suggestion":suggestion} for item,_,_,_,_ in tasks]
    scheduled=[]
    for item,start,end,assignments,affected in tasks:
        if allow_subset and not solver.value(presence[str(item["equipment_id"])]):
            conflicts.append({"equipment_id":item["equipment_id"],"reason":"本轮联合约束下未选中，需同时满足预算、库存、人员和时间条件","suggestion":"调整预算、备件、班次或停机窗口后重算；未选中不表示设备无维护需求"})
            continue
        team=[p for p,flag in assignments if solver.value(flag)]
        assumptions=[]
        if not item.get("window_start") or not item.get("window_end"): assumptions.append("设备停机窗口采用起算后24小时的情景假设")
        if any(not p.get("shift_start") or not p.get("shift_end") for p in team): assumptions.append("缺少真实班次，使用可用工时推导情景班次")
        if any(not o.get("start_at") or not o.get("end_at") for o in affected): assumptions.append("订单缺少生产时间窗，无法验证真实订单冲突")
        scheduled.append({**item,"staff_id":team[0]["staff_id"],"staff_ids":[p["staff_id"] for p in team],"staff_name":"、".join(str(p.get("staff_name",p["staff_id"])) for p in team),"start_at":(base+timedelta(minutes=solver.value(start))).isoformat(sep=" "),"end_at":(base+timedelta(minutes=solver.value(end))).isoformat(sep=" "),"required_skill":item.get("required_skill") or "机修","affected_orders":[str(o.get("order_id")) for o in affected],"order_impact":"；".join(assumptions) if assumptions else "已检查生产时间窗，无占用冲突","assumptions":assumptions,"constraint_status":"scenario_only" if assumptions else "validated","approval_status":"待审批","optimizer_status":"optimal" if status==cp_model.OPTIMAL else "feasible"})
    return scheduled,conflicts
