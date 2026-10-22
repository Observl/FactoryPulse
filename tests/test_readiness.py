from datetime import datetime
from backend.readiness import resource_time_readiness
from tests.test_api import client


def test_time_readiness_detects_expired_missing_and_too_short_windows():
    rules=[{'equipment_id':'expired','window_start':'2026-10-20 08:00:00','window_end':'2026-10-20 18:00:00'},{'equipment_id':'missing'},{'equipment_id':'short','window_start':'2026-10-21 08:00:00','window_end':'2026-10-21 18:00:00','maintenance_hours':5}]
    result=resource_time_readiness(rules,[{'staff_id':'P1','shift_start':'2026-10-21 08:00:00','shift_end':'2026-10-21 12:00:00'}],datetime(2026,10,21,15))
    assert result['issue_count']==4
    assert {item['reason'] for item in result['groups'][0]['issues']}=={'时间已过期','时间缺失或无法识别','剩余窗口不足以完成检修'}


def test_time_readiness_valid_future_is_not_a_full_scheduling_guarantee():
    result=resource_time_readiness([{'equipment_id':'E1','window_start':'2026-10-22 08:00:00','window_end':'2026-10-22 18:00:00','maintenance_hours':5}],[{'staff_id':'P1','shift_start':'2026-10-22 08:00:00','shift_end':'2026-10-22 18:00:00'}],datetime(2026,10,21,15))
    assert result['issue_count']==0
    assert '不代表' in result['scope']


def test_empty_resources_need_configuration_and_endpoint_is_read_only():
    result=client.get('/api/maintenance/time-readiness')
    assert result.status_code==200 and result.json()['issue_count']==2
    assert client.get('/api/work-orders').json()['records']==[]
