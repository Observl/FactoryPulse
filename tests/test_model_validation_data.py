from datetime import datetime, timedelta
from collections import defaultdict
import importlib.util
from pathlib import Path
import pytest

from backend.model_validation_data import build_model_validation, ORIGIN, SENSOR_FIELDS
from backend.analytics import xgboost_with_shap, chronological_partitions

@pytest.fixture(scope="module")
def dataset():
    return build_model_validation(datetime(2026,10,21))[0]

@pytest.fixture(scope="module")
def model(dataset):
    return xgboost_with_shap(dataset["readings"])

def test_fixture_is_complete_deterministic_and_not_rule_labelled(dataset):
    assert len(dataset["equipment"])==24
    assert len(dataset["readings"])==34560
    assert len(dataset["maintenance_history"])==144
    assert dataset==build_model_validation(datetime(2026,10,21))[0]
    assert all(row["data_origin"]==ORIGIN for row in dataset["readings"])
    assert not set(SENSOR_FIELDS)&{"failure","future_failure","timestamp","equipment_id"}
    assert len({row["reading_id"] for row in dataset["readings"]})==34560

def test_labels_reconcile_to_observed_fault_times_and_censored_tail(dataset):
    events=defaultdict(list)
    for event in dataset["maintenance_history"]:
        events[event["equipment_id"]].append(datetime.fromisoformat(event["failure_at"]))
    end=max(datetime.fromisoformat(row["timestamp"]) for row in dataset["readings"])
    for row in dataset["readings"]:
        moment=datetime.fromisoformat(row["timestamp"])
        if row["failure"] or moment+timedelta(hours=168)>end:
            assert row["future_failure"] is None
        else:
            expected=any(moment<event<=moment+timedelta(hours=168) for event in events[row["equipment_id"]])
            assert row["future_failure"]==int(expected)

def test_all_time_partitions_have_both_classes_and_purge_horizon(dataset):
    usable=[r for r in dataset["readings"] if r["future_failure"] in (0,1) and not r["failure"]]
    train,validation,test=chronological_partitions(usable,168)
    for part in (train,validation,test):
        assert {r["future_failure"] for r in part}=={0,1}
        assert len({r["equipment_id"] for r in part})==24
    assert datetime.fromisoformat(train[-1]["timestamp"])+timedelta(hours=168)<datetime.fromisoformat(validation[0]["timestamp"])
    assert datetime.fromisoformat(validation[-1]["timestamp"])+timedelta(hours=168)<datetime.fromisoformat(test[0]["timestamp"])

def test_real_training_produces_all_scores_and_reproducible_metrics(dataset,model):
    assert model.status=="ready",model.message
    assert len(model.predictions)==len(model.explanations)==24
    assert model.evaluation["independent_test_events"]>=24
    assert model.evaluation["synthetic_validation_only"] is True
    assert model.evaluation["probability_calibrated"] is False
    for key in ("precision","recall","false_alarm_rate","f1"):
        assert 0<=model.evaluation[key]<=1
    assert 0<model.evaluation["average_lead_hours"]<=168
    path=Path(__file__).resolve().parents[1]/"scripts/build-model-validation-dataset.py"
    spec=importlib.util.spec_from_file_location("fixture_export",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.verify_metrics(model)["passed"] is True
    repeated=xgboost_with_shap(dataset["readings"])
    assert repeated.predictions==model.predictions
    assert repeated.evaluation==model.evaluation
    assert repeated.replay==model.replay

def test_independent_fault_count_is_not_window_count(dataset,model):
    test_times=defaultdict(list)
    for row in model.replay:
        test_times[row["equipment_id"]].append(datetime.fromisoformat(row["timestamp"]))
    expected=[]
    for event in dataset["maintenance_history"]:
        onset=datetime.fromisoformat(event["failure_at"])
        if any(onset-timedelta(hours=168)<=sample<onset for sample in test_times[event["equipment_id"]]):
            expected.append((event["equipment_id"],onset.isoformat()))
    assert set(expected)=={(e["equipment_id"],e["failure_at"]) for e in model.evaluation["events"]}
    assert model.evaluation["test_rows"]>model.evaluation["independent_test_events"]

def test_opt_in_load_api_exposes_metrics_without_deleting_existing_orders():
    from tests.test_api import client,workbook
    from backend.main import agent_dispatch
    client.post("/api/import",files={"file":("test.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    proposal=agent_dispatch("draft_work_order",{"equipment_id":"CNC-001","note":"保留旧数据工单"})["proposal"]
    assert client.post(f"/api/copilot/proposals/{proposal['proposal_id']}/confirm",json={"confirmed":True}).status_code==200
    original=client.get("/api/work-orders").json()["records"]
    response=client.post("/api/sync/model-validation")
    assert response.status_code==200,response.text
    assert response.json()["data_origin"]==ORIGIN
    assert response.json()["counts"]["readings"]==34560
    overview=client.get("/api/overview").json()
    assert len(overview["devices"])==24
    assert all(device["model_risk"] is not None for device in overview["devices"])
    evaluation=client.get("/api/model/evaluation").json()["evaluation"]
    assert evaluation["test_rows"]>0 and evaluation["independent_test_events"]>=24
    assert client.get("/api/work-orders").json()["records"]==original
    created=client.post("/api/maintenance-requests",json={"equipment_id":"VAL-CNC-001","action":"验证润滑与主轴状态","priority":"高","request_id":"model-validation-workflow-test"})
    assert created.status_code==200,created.text
    scheduled=client.post("/api/schedule/generate",json={"scenario_id":"VAL-BASE","request_id":"model-validation-schedule-test"})
    assert scheduled.status_code==200,scheduled.text
    assert any(item["equipment_id"]=="VAL-CNC-001" for item in scheduled.json()["scheduled"])
