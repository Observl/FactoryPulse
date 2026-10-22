from datetime import datetime, timedelta

import numpy as np

from backend.analytics import chronological_partitions, event_evaluation, _feature_row
from backend.analytics import ewma_scores,xgboost_with_shap
from backend.metropt3 import label_observed_history


def test_unknown_tail_and_active_fault_are_not_negative_labels():
    readings = [{"timestamp": "2020-07-15 15:00:00"}, {"timestamp": "2020-08-01 00:00:00"}, {"timestamp": "2020-08-10 00:00:00"}]
    label_observed_history(readings)
    assert readings[0]["future_failure"] is None
    assert readings[1]["future_failure"] == 0
    assert readings[2]["future_failure"] is None


def test_partitions_purge_full_horizon_and_keep_validation_separate():
    start = datetime(2020, 1, 1)
    history = [{"timestamp": (start + timedelta(hours=i)).isoformat()} for i in range(3000)]
    train, validation, test = chronological_partitions(history, 168)
    assert datetime.fromisoformat(train[-1]["timestamp"]) + timedelta(hours=168) < datetime.fromisoformat(validation[0]["timestamp"])
    assert datetime.fromisoformat(validation[-1]["timestamp"]) + timedelta(hours=168) < datetime.fromisoformat(test[0]["timestamp"])


def test_actual_event_lead_and_missed_event():
    history = [{"equipment_id": "A", "timestamp": f"2020-01-01 {hour:02}:00:00", "failure": int(hour >= 10)} for hour in range(12)]
    test = history[5:10]
    metrics = event_evaluation(history, test, np.array([.1, .7, .8, .2, .9]), .5, 168)
    assert metrics["average_lead_hours"] == 4
    assert metrics["independent_test_events"] == 1
    missed = event_evaluation(history, test, np.zeros(5), .5, 168)
    assert missed["event_recall"] == 0
    assert missed["average_lead_hours"] is None


def test_missing_feature_is_not_fabricated_zero():
    assert np.isnan(_feature_row({}, ["motor_current_a"])[0])


def test_ewma_does_not_present_last_known_value_as_latest_measurement():
    start=datetime(2020,1,1)
    history=[{'equipment_id':'A','timestamp':(start+timedelta(hours=i)).isoformat(),'vibration_g':.1+i*.01} for i in range(20)]
    history[-1]['vibration_g']=None
    history[-1]['motor_current_a']=10
    result=ewma_scores(history)['A']
    assert result['score'] is None and result['status']=='missing_latest_reading'
    assert result['samples']==19 and result['feature']=='vibration_g'


def test_no_current_model_score_with_missing_features_or_existing_failure():
    start=datetime(2020,1,1)
    history=[]
    for i in range(3001):
        phase=i%300
        history.append({'equipment_id':'A','timestamp':(start+timedelta(hours=i)).isoformat(),
                        'failure':int(phase==299),'future_failure':int(131<=phase<299),
                        'prediction_horizon_hours':168,'vibration_g':phase/300})
    history[-1]['vibration_g']=None
    timestamp=history[-1]['timestamp']
    history.extend([{'equipment_id':'VALID','timestamp':timestamp,'vibration_g':.5},
                    {'equipment_id':'FAILED','timestamp':timestamp,'vibration_g':.8,'failure':1}])
    result=xgboost_with_shap(history)
    assert set(result.predictions)=={'VALID'}
    unscored={item['equipment_id']:item['reason'] for item in result.evaluation['unscored_latest_equipment']}
    assert unscored=={'A':'missing_latest_features','FAILED':'already_failed'}
    assert result.evaluation['excluded_sensorless_windows']['test']==1


def test_unknown_fault_state_does_not_create_a_proven_fault_onset():
    history=[{"equipment_id":"A","timestamp":f"2020-01-01T{hour:02}:00:00",**({"failure":failed} if failed is not None else {})} for hour,failed in [(0,0),(1,None),(2,1),(3,0),(4,1)]]
    result=event_evaluation(history,history[:4],np.ones(4),.5,168)
    assert result["independent_test_events"]==1
    assert result["events"][0]["failure_at"]=="2020-01-01T04:00:00"


def test_alarm_burden_merges_episodes_and_counts_false_reviews():
    from backend.analytics import alarm_burden
    rows=[{"equipment_id":"A","timestamp":f"2026-01-01T{h:02}:00:00","failure":int(h==6),"future_failure":int(h in (3,4,5))} for h in range(7)]
    result=alarm_burden(rows,rows[:6],[.8,.8,.1,.8,.8,.1],.5,3)
    assert result["alert_episodes"]==2
    assert result["false_alert_episodes"]==1
    assert result["alert_windows"]==4
    assert result["confirmed_events"][0]["confirmed_lead_hours"]==2
