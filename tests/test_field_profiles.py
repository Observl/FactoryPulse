import json
import time
import pytest
from datetime import datetime,timedelta
from backend import analytics
from backend.field_profiles import custom_key
from backend.main import rows,settings_get
from backend.smart_import import infer_mapping,normalize_rows
from tests.test_api import client


def stage(content,mapping,**options):
    analysis=client.post('/api/import/intelligent/analyze',files={'file':('mixed.csv',content.encode('utf-8-sig'),'text/csv')})
    assert analysis.status_code==200,analysis.text
    reply=client.post('/api/import/intelligent/preview',json={'upload_id':analysis.json()['upload_id'],'mapping':mapping,**options})
    if reply.status_code!=200:return reply,None
    identifier=reply.json()['job_id']
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        job=client.get('/api/import/jobs/'+identifier).json()
        if job['status'] not in {'queued','validating'}:return reply,job
        time.sleep(.02)
    raise AssertionError('import timeout')


def mapping():
    return [{'source_column':'机台编号','target_field':'equipment_id'},{'source_column':'时间','target_field':'timestamp'},
            {'source_column':'供油压力','target_field':'pressure_bar','source_unit':'MPa'},
            {'source_column':'测点X','target_field':custom_key('测点X'),'custom_unit':'mV'},
            {'source_column':'故障','target_field':'failure','use_for_prediction':False}]


def test_custom_numeric_fields_only_use_second_row_and_preserve_multiple_sensors():
    inferred=infer_mapping([{'设备编号':'M1','timestamp':'2020-01-01','测点X':1.2,'轴承温度A':30,'轴承温度B':40,'future_failure':0}, {'测点X':'must not leak'}])
    x=next(item for item in inferred if item['source_column']=='测点X')
    assert x['target_field']==custom_key('测点X') and x['samples']==[1.2]
    assert next(item for item in inferred if item['source_column']=='轴承温度B')['target_field'].startswith('sensor_')
    assert not next(item for item in inferred if item['source_column']=='future_failure')['target_field']

@pytest.mark.parametrize('column',['future_failure','未来7天故障','remaining_life','predicted_fault','故障概率'])
def test_future_results_cannot_be_overridden_as_observed_failure(column):
    content=f'机台编号,时间,{column}\nP-1,2020-01-01,0\n'
    choices=[{'source_column':'机台编号','target_field':'equipment_id'},{'source_column':'时间','target_field':'timestamp'},{'source_column':column,'target_field':'failure','use_for_prediction':False}]
    response,job=stage(content,choices)
    assert response.status_code==422 and job is None
    with pytest.raises(ValueError,match='不能映射'):
        normalize_rows([{'机台编号':'P-1','时间':'2020-01-01',column:0}],{item['source_column']:item['target_field'] for item in choices},'')
    assert infer_mapping([{column:0}])[0]['target_field']==''


def test_import_mixed_profiles_preserves_custom_values_units_and_configuration():
    _,job=stage('机台编号;时间;供油压力;测点X;故障\nP-1;2020/01/01 00:00;0.5;12;正常\nE-1;2020/01/01 00:00;0.6;18;故障\n',mapping(),profile_id='hydraulic',device_profiles=[{'equipment_id':'E-1','profile_id':'electrical','feature_fields':[custom_key('测点X')]}])
    assert job['status']=='ready',job
    result=client.post(f"/api/import/jobs/{job['job_id']}/commit",json={'replace_existing':True,'expected_dataset_version':job['expected_dataset_version']})
    assert result.status_code==200,result.text
    imported={row['equipment_id']:row for row in rows('readings')}
    assert imported['P-1']['pressure_bar']==5 and imported['P-1'][custom_key('测点X')]==12
    assert imported['E-1']['_feature_fields']==[custom_key('测点X')]
    assert imported['E-1']['_equipment_profile']=='electrical' and imported['E-1']['failure']==1
    catalog=json.loads(settings_get('sensor_catalog'))
    assert catalog[custom_key('测点X')]['unit']=='mV'
    assert client.get('/api/data-quality').json()['missing_rate']==0
    detail=client.get('/api/equipment/E-1/history').json()
    assert detail['series'][0]['signal']==18


def test_bad_device_profile_and_result_leakage_are_rejected():
    content='机台编号,时间,供油压力,测点X,故障\nP-1,2020-01-01,0.5,12,0\n'
    response,_=stage(content,mapping(),profile_id='nonexistent')
    assert response.status_code==422
    response,_=stage(content,mapping(),device_profiles=[{'equipment_id':'P-1','feature_fields':['failure']}])
    assert response.status_code==422
    _,job=stage(content,mapping(),device_profiles=[{'equipment_id':'not-in-file','profile_id':'cnc'}])
    assert job['status']=='invalid'
    response,_=stage(content,[*mapping(),{'source_column':'未来故障概率','target_field':custom_key('未来故障概率')}])
    assert response.status_code==422


def test_unix_timestamp_and_nonfinite_custom_sensor_validation():
    response,job=stage('机台编号,时间,供油压力,测点X,故障\nP-1,1577836800000,0.5,12,0\n',[{**item,**({'source_unit':'unix_ms'} if item['target_field']=='timestamp' else {})} for item in mapping()])
    assert job['status']=='ready' and job['preview'][0]['timestamp']=='2020-01-01 00:00:00'
    _,job=stage('机台编号,时间,供油压力,测点X,故障\nP-1,2020-01-01,0.5,NaN,0\n',mapping())
    assert job['status']=='invalid'


def test_models_are_isolated_by_device_profile_and_selected_fields(monkeypatch):
    calls=[]
    def fake(history):
        calls.append(history)
        return analytics.ModelOutput({}, {},'insufficient_labels','not enough',len(history),0,'observed',{})
    monkeypatch.setattr(analytics,'_xgboost_single',fake)
    output=analytics.xgboost_with_shap([
        {'equipment_id':'P','_equipment_profile':'hydraulic','_feature_fields':['pressure_bar']},
        {'equipment_id':'E','_equipment_profile':'electrical','_feature_fields':['voltage_v']},
        {'equipment_id':'P2','_equipment_profile':'hydraulic','_feature_fields':['pressure_bar']}])
    assert len(calls)==2 and sorted(map(len,calls))==[1,2]
    assert len(output.evaluation['profile_results'])==2 and not output.predictions


def test_custom_sensor_can_reach_time_split_model_without_using_labels_as_features():
    key=custom_key('测点X');base=datetime(2020,1,1)
    history=[]
    for i in range(3001):
        phase=i%300
        history.append({'equipment_id':'P','timestamp':(base+timedelta(hours=i)).isoformat(sep=' '),'failure':int(phase==299),
                        'future_failure':int(131<=phase<299),'prediction_horizon_hours':168,'_equipment_profile':'hydraulic','_feature_fields':[key],key:phase/300})
    result=analytics.xgboost_with_shap(history)
    assert result.predictions and result.evaluation['feature_names']==[key]
    assert result.evaluation['split_method']=='purged_train_validation_test'
    assert 'failure' not in result.evaluation['feature_names']
