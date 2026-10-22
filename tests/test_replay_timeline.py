from backend.replay import event_timeline


def test_events_remain_separate_from_model_scores_and_missing_outcomes():
    series=[{"equipment_id":"A","timestamp":f"2020-01-01T{hour:02}:00:00","alert":alert,"score":.7 if alert else .1,"observed_future_failure":outcome} for hour,alert,outcome in [(1,True,0),(2,True,0),(3,False,None),(4,True,None)]]
    faults=[{"equipment_id":"A","failure_at":"2020-01-01T05:00:00","detected":False,"lead_hours":None}]
    history=[{"equipment_id":"A","maintenance_date":"2020-01-01T03:00:00","maintenance_type":"人工检查"},{"equipment_id":"B","maintenance_date":"2020-01-01T03:00:00"}]
    timeline=event_timeline(series,faults,history)
    assert len(timeline)==4
    assert [event["kind"] for event in timeline]==["alert","maintenance","alert","failure"]
    assert "误报" in timeline[0]["detail"]
    assert "无法核验" in timeline[2]["detail"]
    assert "漏报" in timeline[3]["detail"]
    assert series[0]["score"]==.7
    assert all(event["equipment_id"]=="A" for event in timeline)
