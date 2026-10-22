import json

from backend.main import connect
from tests.test_api import client


def test_audit_filters_are_applied_before_pagination_and_do_not_interpret_sql():
    with connect() as connection:
        for number in range(5):
            connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("work_order_transition",f"WORK-{number}",json.dumps({"equipment_id":"DEVICE-A","status":"执行中"}),"2026-10-20"))
        connection.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("alert_action","DEVICE-B","{}","2026-10-20"))
    first=client.get("/api/audit?event_type=work_order_transition&entity=DEVICE-A&limit=2").json()
    second=client.get(f"/api/audit?event_type=work_order_transition&entity=DEVICE-A&limit=2&before_id={first['next_cursor']}").json()
    assert len(first["records"])==len(second["records"])==2
    assert not {row["event_id"] for row in first["records"]}&{row["event_id"] for row in second["records"]}
    assert all(row["content"]["equipment_id"]=="DEVICE-A" for row in first["records"]+second["records"])
    assert client.get("/api/audit?entity=%27%20OR%201=1--").json()["records"]==[]
