"""Causal feature engineering and bounded validation-only model selection."""
from collections import deque
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from pydantic import BaseModel, ConfigDict, Field

class CandidateParameters(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True,allow_inf_nan=False)
    n_estimators: int | None = Field(default=None,ge=50,le=600)
    max_depth: int | None = Field(default=None,ge=2,le=8)
    learning_rate: float | None = Field(default=None,ge=.01,le=.3)
    min_child_weight: float | None = Field(default=None,ge=0,le=100)
    reg_lambda: float | None = Field(default=None,ge=0,le=100)
    subsample: float | None = Field(default=None,gt=0,le=1)
    colsample_bytree: float | None = Field(default=None,gt=0,le=1)
    scale_pos_weight: float | None = Field(default=None,gt=0,le=1000)

class TrainingConfig(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    enabled: bool = True
    temporal_features: bool = True
    max_candidates: int = Field(default=8,ge=1,le=8)
    max_selected_features: int = Field(default=24,ge=4,le=128)
    minimum_validation_gain: float = Field(default=.01,ge=0,le=.2)
    max_validation_alert_fraction: float = Field(default=.25,gt=0,le=1)
    excluded_features: list[str] = Field(default_factory=list,max_length=128)
    custom_candidates: list[CandidateParameters] = Field(default_factory=list,max_length=4)

def load_training_config():
    path=Path(__file__).resolve().parents[1]/"config/model-training.json"
    return TrainingConfig.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else TrainingConfig()

def finite(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (ValueError,TypeError): return None

def causal_features(readings,features):
    """A row's rolling features use observations strictly before its own timestamp."""
    prepared=[dict(row) for row in readings]
    engineered=[f"temporal__{name}__{kind}" for name in features for kind in ("mean24h","delta24h","mean72h")]
    histories={}
    for index in sorted(range(len(prepared)),key=lambda i:str(prepared[i].get("timestamp",""))):
        row=prepared[index]
        if not row.get("equipment_id") or not row.get("timestamp"): continue
        moment=datetime.fromisoformat(row["timestamp"])
        device=histories.setdefault(str(row["equipment_id"]),{})
        for name in features:
            queues=device.setdefault(name,{24:deque(),72:deque()})
            value=finite(row.get(name))
            for hours,queue in queues.items():
                while queue and queue[0][0]<moment-timedelta(hours=hours): queue.popleft()
                past=[number for stamp,number in queue if stamp<moment]
                mean=sum(past)/len(past) if len(past)>=3 else None
                row[f"temporal__{name}__mean{hours}h"]=mean
                if hours==24:row[f"temporal__{name}__delta24h"]=value-mean if value is not None and mean is not None else None
                if value is not None: queue.append((moment,value))
    return prepared,engineered

def context_residuals(readings,train,features):
    """Fit normal-operation context corrections on training data only."""
    import numpy as np
    context=[name for name in ("spindle_load_pct","rotational_speed_rpm","air_temperature_k") if name in features]
    normal=[row for row in train if row["future_failure"]==0]
    if not context or len(normal)<30:return [],{}
    columns=[];medians=[];scales=[]
    for name in context:
        values=[finite(row.get(name)) for row in normal]
        valid=[v for v in values if v is not None]
        if not valid:continue
        median=float(np.median(valid));scale=max(float(np.std(valid)),1.)
        columns.append(name);medians.append(median);scales.append(scale)
    if not columns:return [],{}
    def design(rows):
        return np.asarray([[1.]+[(value-median)/scale if (value:=finite(row.get(name))) is not None else 0.
                                for name,median,scale in zip(columns,medians,scales)] for row in rows])
    x=design(normal);all_x=design(readings);metadata={};added=[]
    for target in features:
        if target in columns:continue
        valid=[i for i,row in enumerate(normal) if finite(row.get(target)) is not None]
        if len(valid)<30:continue
        coefficients=np.linalg.lstsq(x[valid],np.asarray([float(normal[i][target]) for i in valid]),rcond=None)[0]
        expected=all_x@coefficients
        name="residual__"+target
        for index,row in enumerate(readings):
            value=finite(row.get(target));row[name]=float(value-expected[index]) if value is not None else None
        metadata[name]={"context":columns,"medians":medians,"scales":scales,"coefficients":coefficients.tolist()}
        added.append(name)
    return added,metadata

def choose_model(train,validation,raw_features,engineered_features,config):
    """The test partition is intentionally absent from this interface."""
    import numpy as np
    from xgboost import XGBClassifier
    def matrix(rows,fields):
        return np.asarray([[finite(row.get(name)) if finite(row.get(name)) is not None else np.nan for name in fields] for row in rows],dtype=float)
    y=np.asarray([int(row["future_failure"]) for row in train])
    # Reserve a later validation segment for a stability report; it never picks candidates or thresholds.
    original_validation=validation
    boundary=datetime.fromisoformat(validation[int(len(validation)*.65)]["timestamp"])
    horizon=max(int(row.get("prediction_horizon_hours",168)) for row in validation)
    selection=[row for row in validation if datetime.fromisoformat(row["timestamp"])+timedelta(hours=horizon)<boundary]
    holdout=[row for row in validation if datetime.fromisoformat(row["timestamp"])>=boundary]
    stable=all(len(part)>=20 and len({row["future_failure"] for row in part})==2 for part in (selection,holdout))
    if stable:validation=selection
    else:holdout=[]
    validation_y=np.asarray([int(row["future_failure"]) for row in validation])
    weight=max(1.,(len(y)-int(y.sum()))/max(1,int(y.sum())))
    def metrics(scores,threshold):
        predicted=scores>=threshold
        tp=int(((predicted==1)&(validation_y==1)).sum());fp=int(((predicted==1)&(validation_y==0)).sum())
        fn=int(((predicted==0)&(validation_y==1)).sum());tn=int(((predicted==0)&(validation_y==0)).sum())
        return {"f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,"precision":tp/(tp+fp) if tp+fp else 0.,
                "recall":tp/(tp+fn) if tp+fn else 0.,"false_alarm_rate":fp/(fp+tn) if fp+tn else 0.}
    baseline={"n_estimators":140,"max_depth":4,"learning_rate":.05,"subsample":.85,"colsample_bytree":.9,"min_child_weight":3,"reg_lambda":2,"scale_pos_weight":weight}
    varying={name for name in raw_features+engineered_features if len({finite(r.get(name)) for r in train if finite(r.get(name)) is not None})>1}
    all_features=[name for name in raw_features+engineered_features if name in varying]
    if not all_features:all_features=list(raw_features)
    trials=[];best=None;ranked=[]
    candidates=[("original",raw_features,baseline)]
    if config.enabled:
        candidates.extend((f"custom_{index+1}",all_features,{**baseline,**parameters.model_dump(exclude_none=True)}) for index,parameters in enumerate(config.custom_candidates))
    if config.enabled:
        candidates.extend([
            ("raw_regularized",raw_features,{**baseline,"n_estimators":420,"max_depth":3,"learning_rate":.035,"min_child_weight":6,"reg_lambda":5,"scale_pos_weight":math.sqrt(weight)}),
            ("raw_interactions",raw_features,{**baseline,"n_estimators":300,"max_depth":5,"learning_rate":.035,"min_child_weight":8,"scale_pos_weight":math.sqrt(weight)}),
            ("context_corrected",raw_features+[f for f in engineered_features if f.startswith("residual__")],baseline),
            ("temporal_balanced",all_features,{**baseline,"n_estimators":220,"max_depth":3,"min_child_weight":6,"scale_pos_weight":math.sqrt(weight)}),
            ("temporal_conservative",all_features,{**baseline,"n_estimators":300,"learning_rate":.04,"min_child_weight":10,"scale_pos_weight":1.}),
            ("selected_compact",None,{**baseline,"n_estimators":260,"max_depth":3,"min_child_weight":6,"scale_pos_weight":math.sqrt(weight)}),
            ("selected_regularized",None,{**baseline,"n_estimators":220,"max_depth":4,"min_child_weight":8,"reg_lambda":5,"scale_pos_weight":math.sqrt(weight)}),
        ])
    for name,fields,parameters in candidates[:config.max_candidates]:
        if fields is None:
            fields=ranked[:config.max_selected_features] or all_features
        classifier=XGBClassifier(**parameters,objective="binary:logistic",eval_metric="logloss",n_jobs=2,random_state=42)
        classifier.fit(matrix(train,fields),y)
        scores=classifier.predict_proba(matrix(validation,fields))[:,1]
        feasible=[value for value in [i/100 for i in range(5,101,5)]+[1.000001] if float((scores>=value).mean())<=config.max_validation_alert_fraction]
        threshold=max(feasible,key=lambda value:(metrics(scores,value)["f1"],value))
        result=metrics(scores,threshold)
        trials.append({"candidate":name,"parameters":parameters,"feature_count":len(fields),"threshold":threshold,"validation":result,"validation_alert_fraction":float((scores>=threshold).mean())})
        if name=="temporal_balanced":
            ranked=[field for _,field in sorted(zip(classifier.feature_importances_,fields),reverse=True)]
        # Prefer the original on ties; no test feedback participates in selection.
        if best is None or (result["f1"]>=trials[0]["validation"]["f1"]+config.minimum_validation_gain and result["f1"]>best[4]["f1"]+1e-9):
            best=(classifier,list(fields),threshold,name,result,parameters)
    classifier,fields,threshold,name,result,parameters=best
    artifact=json.loads(classifier.get_booster().save_raw(raw_format="json").decode())
    digest=hashlib.sha256(json.dumps(artifact,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    report={"selection_basis":"validation_f1_under_alert_capacity","validation_alert_fraction_limit":config.max_validation_alert_fraction,"capacity_basis":"情景约束，现场复核容量待人员试用确认","test_used_for_selection":False,"selected_candidate":name,
            "parameters":parameters,"features":fields,"added_features":[f for f in fields if f not in raw_features],
            "removed_features":[f for f in raw_features if f not in fields],"trials":trials,
            "validation_f1_gain":result["f1"]-trials[0]["validation"]["f1"],"weights_sha256":digest}
    report["validation_selection_rows"]=len(validation)
    report["validation_stability"]={"status":"unavailable_insufficient_classes_or_time"}
    if holdout:
        holdout_scores=classifier.predict_proba(matrix(holdout,fields))[:,1]
        old_labels=validation_y;validation_y=np.asarray([int(row["future_failure"]) for row in holdout])
        report["validation_stability"]={"status":"reserved_not_used_for_selection","rows":len(holdout),"start":holdout[0]["timestamp"],"end":holdout[-1]["timestamp"],"purge_hours":horizon,"metrics":metrics(holdout_scores,threshold),"alert_fraction":float((holdout_scores>=threshold).mean())}
        validation_y=old_labels
    return classifier,fields,threshold,report,{"booster":artifact,"features":fields,"raw_features":raw_features,"threshold":threshold,"training":report}
