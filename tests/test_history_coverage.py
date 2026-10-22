import json
from datetime import datetime,timedelta

from backend.main import connect
from tests.test_api import client


def test_aggregation_keeps_endpoints_and_faults_from_unsampled_rows():
    start=datetime(2020,1,1)
    readings=[]
    for index in range(100):
        readings.append({"equipment_id":"LONG","timestamp":(start+timedelta(hours=index)).isoformat(),"motor_current_a":100 if index%4==0 else 1,"failure":int(index in (37,38))})
    with connect() as connection:
        connection.executemany("INSERT INTO records VALUES ('readings',?,?)",[(index,json.dumps(row)) for index,row in enumerate(readings)])
    response=client.get("/api/equipment/LONG/history?points=24")
    assert response.status_code==200,response.text
    data=response.json()
    assert len(data["series"])==24
    assert data["series"][0]["timestamp"]==readings[0]["timestamp"]
    assert data["series"][-1]["timestamp"]==readings[-1]["timestamp"]
    assert data["fault_intervals"]==[{"start_at":readings[37]["timestamp"],"end_at":readings[38]["timestamp"],"source":"原始故障标记"}]
    assert "不是模型预测" in data["risk_basis"]


def test_unknown_measurements_do_not_become_normal_values_or_fault_labels():
    with connect() as connection:
        connection.execute("INSERT INTO records VALUES ('readings',0,?)",(json.dumps({"equipment_id":"EMPTY","timestamp":"2020-01-01"}),))
    data=client.get("/api/equipment/EMPTY/history").json()
    assert data["series"][0]["signal"] is None
    assert data["series"][0]["risk"] is None
    assert data["series"][0]["failure"] is None
    assert data["fault_intervals"]==[]
