from datetime import datetime,timedelta
from backend.analytics import schedule_selected,ewma_scores
from backend.score_explanation import rule_details
from backend import main
from tests.test_api import workbook,client


def test_first_feasible_slot_is_used_before_or_after_production():
    person={'staff_id':'P','skills':'机修','available_hours':8,'shift_start':'2026-10-22 08:00:00','shift_end':'2026-10-22 18:00:00'}
    task={'equipment_id':'E','hours':1,'people':1,'priority_score':.8,'cost':10,'window_start':'2026-10-22 08:00:00','window_end':'2026-10-22 18:00:00'}
    for end,expected in [('09:00:00','08:00:00'),('08:30:00','12:00:00')]:
        orders=[{'equipment_id':'E','start_at':'2026-10-22 '+end,'end_at':'2026-10-22 12:00:00'}]
        result,conflicts=schedule_selected([task],[person],orders,'2026-10-22 08:00:00',allow_subset=True,budget=10,max_hours=1)
        assert not conflicts
        assert result[0]['start_at']=='2026-10-22 '+expected


def test_rule_and_trend_arithmetic_is_reconstructible():
    rule=rule_details({'data_origin':'SYNTHETIC_SENSOR_THRESHOLD_BASELINE','risk_score':.186},{'vibration_mm_s':3,'motor_current_a':10})
    assert rule['matches_stored']
    history=[{'equipment_id':'E','timestamp':f'2026-10-01 {index:02d}:00:00','vibration_mm_s':1+index*.1} for index in range(20)]
    result=ewma_scores(history)['E']
    assert result['score']==round(min(result['deviation']/result['baseline']/6,1),4)
    external=rule_details({'data_origin':'EXTERNAL','risk_score':.5},{})
    assert external['formula_available'] is False


def test_comparison_reads_snapshot_once_and_skips_unused_preselection(monkeypatch):
    client.post('/api/import',files={'file':('business.xlsx',workbook(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    original=main.snapshot;calls=[]
    def snapshot():calls.append(1);return original()
    monkeypatch.setattr(main,'snapshot',snapshot)
    def forbidden(*args,**kwargs):raise AssertionError('Budget-only solver must not run before joint executable selection')
    monkeypatch.setattr(main,'cp_sat_select',forbidden)
    schedule=main.schedule_selected;origins=[]
    def checked_schedule(*args,**kwargs):
        origins.append(kwargs.get('start_at'))
        return schedule(*args,**kwargs)
    monkeypatch.setattr(main,'schedule_selected',checked_schedule)
    result=main._compare_strategies_consistent(None,executable=True)
    assert len(calls)==1
    assert origins and origins[0] and len(set(origins))==1
    assert len(result['strategies'])==3
    assert all(item['comparison_scope']=='joint_staff_time_resources' for item in result['strategies'])


def test_second_precision_windows_are_never_rounded_into_production():
    person={'staff_id':'P','skills':'机修','available_hours':8,'shift_start':'2026-10-22 08:00:20','shift_end':'2026-10-22 18:00:00'}
    task={'equipment_id':'E','hours':1,'people':1,'priority_score':.8,'cost':10,'window_start':'2026-10-22 08:00:10','window_end':'2026-10-22 18:00:00'}
    result,_=schedule_selected([task],[person],[],'2026-10-22 08:00:00')
    assert result[0]['start_at']=='2026-10-22 08:01:00'
    orders=[{'equipment_id':'E','start_at':'2026-10-22 08:00:00','end_at':'2026-10-22 09:00:20'}]
    result,_=schedule_selected([task],[person],orders,'2026-10-22 08:00:00')
    assert result[0]['start_at']=='2026-10-22 09:01:00'
