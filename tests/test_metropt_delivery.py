import json
import pytest
from backend import metropt3

def test_packaged_metropt_cache_loads_without_original_csv(tmp_path,monkeypatch):
    cache=tmp_path/'factorypulse_records.json';raw=tmp_path/'missing.csv'
    records=[{'equipment_id':metropt3.EQUIPMENT_ID,'timestamp':'2020-03-01 00:00:00','prediction_horizon_hours':168,'failure':0,'tp3_bar':9.3,'reservoirs_bar':9.2,'oil_temperature_c':60}]
    cache.write_text(json.dumps(records),'utf-8')
    before=cache.read_bytes()
    monkeypatch.setattr(metropt3,'CACHE_FILE',cache);monkeypatch.setattr(metropt3,'RAW_FILE',raw)
    data,date=metropt3.build_metropt3()
    assert date=='2020-03-01' and data['equipment'][0]['equipment_id']==metropt3.EQUIPMENT_ID
    assert len(data['readings'])==1 and data['readings'][0]['future_failure'] is None
    assert cache.read_bytes()==before and not raw.exists()

def test_missing_or_obsolete_delivery_cache_has_actionable_error(tmp_path,monkeypatch):
    cache=tmp_path/'cache.json';monkeypatch.setattr(metropt3,'CACHE_FILE',cache);monkeypatch.setattr(metropt3,'RAW_FILE',tmp_path/'missing.csv')
    with pytest.raises(ValueError,match='重新准备'):metropt3.build_metropt3()
    cache.write_text(json.dumps([{'prediction_horizon_hours':24}]),'utf-8')
    with pytest.raises(ValueError,match='七天任务缓存'):metropt3.build_metropt3()
