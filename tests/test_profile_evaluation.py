import pytest
from backend import analytics


def counts(tp,fp,fn,tn):
    return dict(true_positives=tp,false_positives=fp,false_negatives=fn,true_negatives=tn)


def evaluations():
    return {
        'hydraulic':{**counts(1,9,1,89),'test_rows':100,'positive_windows':2,'independent_test_events':1,'detected_events':1,
                     'test_start':'2020-05-01','test_end':'2020-05-30','feature_names':['pressure_bar'],
                     'events':[{'equipment_id':'P','failure_at':'2020-05-20','detected':True,'lead_hours':100}],
                     'excluded_sensorless_windows':{'train':2,'validation':1,'test':3},
                     'unscored_latest_equipment':[{'equipment_id':'P','reason':'missing_latest_features'}],
                     'baseline':{**counts(2,0,0,98),'evaluated_rows':100,'unavailable_rows':0,'matched_model':counts(1,9,1,89)}},
        'electrical':{**counts(8,2,0,0),'test_rows':10,'positive_windows':8,'independent_test_events':1,'detected_events':1,
                      'test_start':'2020-06-01','test_end':'2020-06-15','feature_names':['voltage_v'],
                      'events':[{'equipment_id':'E','failure_at':'2020-06-10','detected':True,'lead_hours':10}],
                      'excluded_sensorless_windows':{'train':3,'validation':0,'test':2},
                      'baseline':{**counts(3,1,1,0),'evaluated_rows':5,'unavailable_rows':5,'matched_model':counts(4,1,0,0)}}}


def run(monkeypatch,data):
    def fake(history):
        group=history[0]['_equipment_profile']
        return analytics.ModelOutput({}, {},'ready' if data[group] else 'insufficient_labels','group result',30,5,'observed',data[group])
    monkeypatch.setattr(analytics,'_xgboost_single',fake)
    return analytics.xgboost_with_shap([{'equipment_id':'P','_equipment_profile':'hydraulic','_feature_fields':['pressure_bar']},
                                      {'equipment_id':'E','_equipment_profile':'electrical','_feature_fields':['voltage_v']}])


def test_unequal_groups_pool_counts_instead_of_averaging_percentages(monkeypatch):
    result=run(monkeypatch,evaluations());metrics=result.evaluation
    assert metrics['test_rows']==110 and metrics['precision']==.45 and metrics['recall']==.9
    assert metrics['false_alarm_rate']==.11 and metrics['f1']==.6
    assert metrics['average_lead_hours']==55 and metrics['independent_test_events']==2
    assert metrics['event_recall']==1 and metrics['test_failures']==10
    assert metrics['excluded_sensorless_windows']=={'train':5,'validation':1,'test':5}
    assert metrics['unscored_latest_equipment'][0]['equipment_id']=='P'


def test_baseline_and_matched_model_pool_only_common_windows(monkeypatch):
    base=run(monkeypatch,evaluations()).evaluation['baseline']
    assert base['evaluated_rows']==105 and base['unavailable_rows']==5
    assert base['coverage']==pytest.approx(105/110)
    assert base['precision']==.8333 and base['f1']==.8333
    assert base['matched_model']['precision']==.3333
    assert sum(base[key] for key in counts(0,0,0,0))==105
    assert sum(base['matched_model'][key] for key in counts(0,0,0,0))==105


def test_historical_validation_remains_ready_when_latest_samples_unscorable(monkeypatch):
    result=run(monkeypatch,evaluations())
    assert not result.predictions and result.status=='ready'
    assert result.evaluation['validated_profiles']==2 and result.evaluation['available_current_predictions']==0


def test_partial_validation_does_not_claim_all_profiles_passed(monkeypatch):
    data=evaluations();data['electrical']={}
    result=run(monkeypatch,data)
    assert result.status=='partially_ready'
    assert result.evaluation['validated_profiles']==1 and result.evaluation['total_profiles']==2
    assert result.evaluation['test_rows']==100 and result.evaluation['baseline']['coverage']==1


def test_no_baseline_data_never_becomes_zero_error_rate():
    result=analytics.pool_window_metrics([{}, {'precision':None,'recall':None}])
    assert all(result[key] is None for key in ('precision','recall','f1','false_alarm_rate'))
