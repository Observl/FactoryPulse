from backend.main import snapshot,settings_get
from tests.test_api import client,workbook

def test_old_deferred_alert_can_be_reviewed_without_rebinding_to_new_prediction(monkeypatch):
    from backend import main
    from datetime import datetime,timedelta,timezone
    guard=prepare();path='/api/alerts/CNC-001/action'
    deferred=client.post(path,json={**guard,'action':'defer','defer_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'request_id':'old-defer-review'}).json()
    current=[{**item,'prediction_at':'2099-01-01 00:00:00'} for item in snapshot()]
    monkeypatch.setattr(main,'snapshot',lambda:current)
    body={**guard,'alert_id':deferred['alert_id'],'version':deferred['version'],'action':'confirm','note':'核对当前工况后完成原延期复核','request_id':'old-review-confirm'}
    result=client.post(path,json=body)
    assert result.status_code==200,result.text
    assert client.post(path,json=body).json()==result.json()
    assert client.post(path,json={**body,'request_id':'old-review-stale'}).status_code==409
    assert client.post(path,json={**body,'version':result.json()['version'],'action':'work_order','request_id':'old-review-no-work'}).status_code==409
    records=client.get('/api/alerts').json()['records']
    assert len(records)==1 and records[0]['prediction_at']==guard['prediction_at'] and records[0]['status']=='已确认'
    assert client.get('/api/work-orders').json()['records']==[]


def prepare():
    response=client.post("/api/import",files={"file":("business.xlsx",workbook(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code==200,response.text
    device=snapshot()[0]
    return {"expected_dataset_version":settings_get("last_sync_at"),"prediction_at":device.get("prediction_at") or "","version":0}


def test_alert_versions_reject_stale_updates_and_retries_do_not_duplicate_work():
    guard=prepare();path="/api/alerts/CNC-001/action"
    confirmed=client.post(path,json={**guard,"action":"confirm","request_id":"alert-confirm-request"})
    assert confirmed.status_code==200,confirmed.text
    assert client.post(path,json={**guard,"action":"reject","note":"过期意见","request_id":"alert-stale-request"}).status_code==409
    payload={**guard,"version":confirmed.json()["version"],"alert_id":confirmed.json()["alert_id"],"action":"work_order","request_id":"alert-work-request"}
    result=client.post(path,json=payload)
    assert result.status_code==200,result.text
    assert client.post(path,json=payload).json()==result.json()
    assert result.json()["work_order_id"]
    repeated=client.post(path,json={**payload,"version":result.json()["version"],"request_id":"alert-work-second-intent"})
    assert repeated.status_code==200,repeated.text
    assert repeated.json()["work_order_id"]==result.json()["work_order_id"]
    assert len(client.get("/api/work-orders").json()["records"])==1


def test_changed_dataset_or_prediction_cannot_be_reviewed_from_old_page():
    guard=prepare();path="/api/alerts/CNC-001/action"
    for changes in ({"expected_dataset_version":"stale"},{"prediction_at":"1900-01-01"},{"alert_id":"wrong-alert"}):
        result=client.post(path,json={**guard,**changes,"action":"confirm"})
        assert result.status_code==409,result.text
    assert client.get("/api/alerts").json()["records"]==[]


def test_alert_reuses_existing_manual_draft_without_losing_request():
    guard=prepare()
    manual=client.post('/api/maintenance-requests',json={'equipment_id':'CNC-001','action':'人工登记的轴承检查','request_id':'manual-before-alert'}).json()
    reply=client.post('/api/alerts/CNC-001/action',json={**guard,'action':'work_order','request_id':'alert-link-manual-draft'})
    assert reply.status_code==200,reply.text
    assert reply.json()['work_order_id']==manual['work_order_id']
    orders=client.get('/api/work-orders').json()['records']
    assert len(orders)==1
    assert orders[0]['maintenance_action']=='人工登记的轴承检查'
    assert orders[0]['source_alert_id']==reply.json()['alert_id'] and orders[0]['version']==2
    assert orders[0]['execution_history'][-1]['action']=='link_alert'


def test_existing_formal_order_rejects_duplicate_and_rolls_back_alert():
    import json
    from backend.main import connect
    guard=prepare()
    with connect() as connection:
        content={'work_order_id':'EXISTING','equipment_id':'CNC-001','dataset_version':settings_get('last_sync_at'),'version':1}
        connection.execute('INSERT INTO work_orders VALUES (?,?,?,?,?)',('EXISTING','CNC-001',json.dumps(content),'已批准','2026-10-21'))
    reply=client.post('/api/alerts/CNC-001/action',json={**guard,'action':'work_order','request_id':'must-not-duplicate-formal'})
    assert reply.status_code==409 and 'EXISTING' in reply.text
    assert client.get('/api/alerts').json()['records']==[]
    assert len(client.get('/api/work-orders').json()['records'])==1
