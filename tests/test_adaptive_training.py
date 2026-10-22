from datetime import datetime,timedelta
import pytest
from backend.adaptive_training import causal_features,TrainingConfig

def test_temporal_features_never_read_current_or_future_observations():
    start=datetime(2026,1,1)
    rows=[{"equipment_id":"A","timestamp":(start+timedelta(hours=i)).isoformat(),"signal":float(i)} for i in range(12)]
    prepared,names=causal_features(rows,["signal"])
    assert prepared[3]["temporal__signal__mean24h"]==1
    assert prepared[3]["temporal__signal__delta24h"]==2
    changed=[{**row,"signal":99999.} if i>=7 else row for i,row in enumerate(rows)]
    repeated,_=causal_features(changed,["signal"])
    for i in range(7):
        for name in names: assert prepared[i][name]==repeated[i][name]
    assert rows[3].keys()=={"equipment_id","timestamp","signal"}

def test_temporal_features_respect_device_and_real_time_boundaries():
    rows=[{"equipment_id":"A","timestamp":f"2026-01-01 0{i}:00:00","signal":1} for i in range(4)]
    rows.extend([{"equipment_id":"B","timestamp":"2026-01-01 04:00:00","signal":999},
                 {"equipment_id":"A","timestamp":"2026-01-03 04:00:00","signal":10}])
    prepared,_=causal_features(rows,["signal"])
    assert prepared[4]["temporal__signal__mean24h"] is None
    assert prepared[5]["temporal__signal__mean24h"] is None
    assert prepared[5]["temporal__signal__mean72h"]==1

@pytest.mark.parametrize("config",[{"max_candidates":999},{"enabled":"yes"},{"arbitrary_code":"exec"},{"max_selected_features":0}])
def test_training_configuration_is_bounded(config):
    with pytest.raises(ValueError):TrainingConfig(**config)

def test_same_length_measurement_edits_invalidate_training_cache(monkeypatch):
    from backend import main
    from backend.analytics import ModelOutput
    calls=[]
    def train(rows):
        calls.append(rows[0]["signal"])
        return ModelOutput({}, {}, "insufficient_labels", "test", 0, 0, "test", {})
    monkeypatch.setattr(main,"xgboost_with_shap",train)
    monkeypatch.setattr(main,"_analytics_cache",{"key":None,"devices":{},"summary":{}})
    monkeypatch.setattr(main,"settings_get",lambda name,default="": "test" if name=="last_sync_at" else default)
    rows=[{"equipment_id":"A","timestamp":"2026-01-01 00:00:00","signal":1.}]
    main._compute_analytics_snapshot(rows,{})
    main._compute_analytics_snapshot(rows,{})
    rows[0]["signal"]=2.
    main._compute_analytics_snapshot(rows,{})
    assert calls==[1.,2.]


def test_persisted_analysis_reused_only_for_matching_input_and_config(monkeypatch):
    from backend import main
    from backend.analytics import ModelOutput
    calls=[]
    monkeypatch.setattr(main,"xgboost_with_shap",lambda rows:(calls.append(1) or ModelOutput({}, {}, "insufficient_labels", "test", 0, 0, "test", {})))
    monkeypatch.setattr(main,"settings_get",lambda name,default="":"persisted-test" if name=="last_sync_at" else default)
    rows=[{"equipment_id":"A","timestamp":"2026-01-01 00:00:00","signal":1}]
    main._compute_analytics_snapshot(rows,{})
    main._analytics_cache.update(key=None,devices={},summary={})
    main._compute_analytics_snapshot(rows,{})
    assert len(calls)==1
    main._analytics_cache.update(key=None,devices={},summary={})
    main._compute_analytics_snapshot([{**rows[0],"signal":2}],{})
    assert len(calls)==2
