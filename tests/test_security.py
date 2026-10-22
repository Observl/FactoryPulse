import json

from backend.main import connect,settings_get
from backend.security import COOKIE
from tests.test_api import client,workbook

PASSWORD="synthetic-test-password-12345"


def initialize():
    client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    result=client.post("/api/auth/bootstrap",json={"username":"admin","display_name":"设备管理员","password":PASSWORD})
    assert result.status_code==200,result.text
    return {"Cookie":f"{COOKIE}={result.cookies.get(COOKIE)}"}


def login(name,password=PASSWORD):
    response=client.post("/api/auth/login",json={"username":name,"password":password})
    assert response.status_code==200,response.text
    return {"Cookie":f"{COOKIE}={response.cookies.get(COOKIE)}"}


def create_user(admin,name,role,staff_id=None):
    response=client.post("/api/auth/users",headers=admin,json={"username":name,"password":PASSWORD,"display_name":name,"role":role,"staff_id":staff_id})
    assert response.status_code==200,response.text
    return response.json()["user_id"]


def test_initialization_protects_business_data_without_exposing_credentials():
    assert client.get("/api/auth/status").json()["mode"]=="local_single_operator"
    admin=initialize()
    assert client.get("/api/overview").status_code==401
    assert client.get("/api/overview",headers=admin).status_code==200
    assert client.post("/api/auth/bootstrap",json={"username":"other","display_name":"其他","password":PASSWORD}).status_code==409
    listing=client.get("/api/auth/users",headers=admin)
    assert PASSWORD not in listing.text and "password_hash" not in listing.text
    with connect() as connection:
        stored=connection.execute("SELECT password_hash FROM auth_users").fetchone()[0]
        assert PASSWORD not in stored and stored.startswith("pbkdf2_sha256$")
        token=admin["Cookie"].split("=",1)[1]
        assert not connection.execute("SELECT 1 FROM auth_sessions WHERE token_hash=?",(token,)).fetchone()


def test_viewer_can_read_but_cannot_import_schedule_or_approve():
    admin=initialize();create_user(admin,"viewer01","viewer");viewer=login("viewer01")
    assert client.get("/api/overview",headers=viewer).status_code==200
    assert client.post("/api/schedule/generate",headers=viewer,json={}).status_code==403
    assert client.post("/api/maintenance-requests",headers=viewer,json={"equipment_id":"CNC-001","action":"检查设备","request_id":"viewer-request"}).status_code==403
    assert client.get("/api/developer/settings",headers=viewer).status_code==403
    assert client.get("/api/auth/users",headers=viewer).status_code==403


def test_technician_can_only_execute_assigned_work_and_actor_is_verified():
    admin=initialize();identifier=create_user(admin,"tech001","technician","ST-1");tech=login("tech001")
    with connect() as connection:
        for work,staff in [("OWN","ST-1"),("OTHER","ST-2")]:
            content={"work_order_id":work,"equipment_id":"CNC-001","version":1,"staff_id":staff,"dataset_version":settings_get("last_sync_at"),"approval_business_revision":settings_get("business_revision","0"),"start_at":"2026-10-20 08:00:00" if work=="OWN" else "2026-10-20 10:00:00","end_at":"2026-10-20 10:00:00" if work=="OWN" else "2026-10-20 12:00:00"}
            connection.execute("INSERT INTO work_orders VALUES (?,?,?,?,?)",(work,"CNC-001",json.dumps(content),"已批准","2026-10-20"))
    payload={"action":"accept","actor":"伪造姓名","note":"已接单","version":1,"request_id":"assigned-work-request"}
    assert client.post("/api/work-orders/OTHER/transition",headers=tech,json=payload).status_code==403
    response=client.post("/api/work-orders/OWN/transition",headers=tech,json=payload)
    assert response.status_code==200,response.text
    with connect() as connection:
        event=json.loads(connection.execute("SELECT content FROM audit_events WHERE event_type='work_order_transition'").fetchone()[0])
    assert event["actor"]=="tech001" and event["actor_user_id"]==identifier
    assert client.post("/api/work-orders/OWN/transition",headers=tech,json={**payload,"action":"verify","version":2}).status_code==403


def test_last_admin_cannot_be_disabled_and_logout_revokes_session():
    admin=initialize();user=client.get("/api/auth/status",headers=admin).json()["user"]
    result=client.post(f"/api/auth/users/{user['user_id']}",headers=admin,json={"display_name":"管理员","role":"viewer","active":False,"version":1})
    assert result.status_code==409
    assert client.post("/api/auth/logout",headers=admin).status_code==200
    assert client.get("/api/overview",headers=admin).status_code==401


def test_wrong_password_is_rate_limited_and_untrusted_origin_cannot_mutate():
    admin=initialize()
    for _ in range(5): assert client.post("/api/auth/login",json={"username":"admin","password":"wrong-password"}).status_code==401
    assert client.post("/api/auth/login",json={"username":"admin","password":PASSWORD}).status_code==429
    assert client.post("/api/sync/cnc-demo",headers={**admin,"Origin":"https://untrusted.invalid"}).status_code==403


def test_validation_error_does_not_echo_submitted_password():
    response=client.post("/api/auth/bootstrap",json={"username":"admin","display_name":"","password":PASSWORD})
    assert response.status_code==422
    assert PASSWORD not in response.text and '"input"' not in response.text


def test_password_change_revokes_every_old_session_and_records_no_secrets():
    admin=initialize();second=login("admin")
    replacement="replacement-test-password-98765"
    rejected=client.post("/api/auth/password",headers=admin,json={"current_password":"incorrect","new_password":replacement})
    assert rejected.status_code==422
    assert client.get("/api/overview",headers=second).status_code==200
    result=client.post("/api/auth/password",headers=admin,json={"current_password":PASSWORD,"new_password":replacement})
    assert result.status_code==200,result.text
    assert client.get("/api/overview",headers=admin).status_code==401
    assert client.get("/api/overview",headers=second).status_code==401
    assert client.post("/api/auth/login",json={"username":"admin","password":PASSWORD}).status_code==401
    renewed=login("admin",replacement)
    assert client.get("/api/overview",headers=renewed).status_code==200
    with connect() as connection:
        event=connection.execute("SELECT content FROM audit_events WHERE event_type='auth_password_changed'").fetchone()[0]
        assert PASSWORD not in event and replacement not in event


def test_account_names_cannot_be_whitespace_and_viewer_can_change_own_password():
    admin=initialize()
    invalid=client.post("/api/auth/users",headers=admin,json={"username":"blankname","display_name":"   ","role":"viewer","password":PASSWORD})
    assert invalid.status_code==422
    create_user(admin,"readonlyuser","viewer")
    viewer=login("readonlyuser")
    changed=client.post("/api/auth/password",headers=viewer,json={"current_password":PASSWORD,"new_password":"viewer-new-password-12345"})
    assert changed.status_code==200,changed.text
    assert client.get("/api/overview",headers=viewer).status_code==401


def test_viewer_comparison_preview_never_writes_plans_or_stock():
    admin=initialize();create_user(admin,"readonlyreview","viewer");viewer=login("readonlyreview")
    def state():
        with connect() as c:
            return {table:[tuple(row) for row in c.execute("SELECT * FROM "+table)] for table in ("planning_runs","inventory_stock","inventory_movements","inventory_reservations")}
    before=state()
    response=client.get("/api/strategies/compare?scenario_id=S-1",headers=viewer)
    assert response.status_code==200,response.text
    assert state()==before
    assert client.post("/api/strategies/compare",headers=viewer,json={"scenario_id":"S-1"}).status_code==403
    assert state()==before
