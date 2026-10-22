import json,os,subprocess,sys,uuid
from concurrent.futures import ThreadPoolExecutor
from backend.main import connect
from tests.test_api import client
from tests.test_workflow_board import prepare,current,manage

def payload(order,**changes):
    return {'decision':'approve','approver':'主管','note':'已核对计划','version':order['version'],'request_id':uuid.uuid4().hex,**changes}

def approve(order,body): return client.post(f"/api/work-orders/{order['work_order_id']}/approval",json=body)

def test_repeat_approval_recovers_original_result_without_duplicate_audit_or_stock():
    order,_=prepare();body=payload(order);first=approve(order,body)
    assert first.status_code==200,first.text
    assert approve(order,body).json()==first.json()
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='work_order_approval'").fetchone()[0]==1
        assert connection.execute("SELECT COUNT(*) FROM operation_requests WHERE request_id=?",(body['request_id'],)).fetchone()[0]==1
    assert current(order['work_order_id'])['version']==order['version']+1
    assert client.get('/api/resources/inventory').json()['records'][0]['reserved_quantity']==1

def test_changed_payload_or_stale_new_intent_cannot_reuse_approval():
    order,_=prepare();body=payload(order);assert approve(order,body).status_code==200
    for patch in ({'note':'修改后的意见'},{'decision':'reject'},{'approver':'另一名主管'}):
        assert approve(order,{**body,**patch}).status_code==409
    assert approve(order,{**body,'request_id':uuid.uuid4().hex}).status_code==409
    no_version={key:value for key,value in body.items() if key!='version'}
    assert approve(order,no_version).status_code==422

def test_blank_local_approver_and_blank_operation_id_leave_no_side_effects():
    order,_=prepare()
    assert approve(order,payload(order,approver='   ')).status_code==422
    assert approve(order,payload(order,request_id='        ')).status_code==422
    assert current(order['work_order_id'])['status']=='待审批'
    with connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='work_order_approval'").fetchone()[0]==0

def test_concurrent_identical_approval_has_one_persisted_outcome():
    order,_=prepare();body=payload(order)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:approve(order,body),range(2)))
    assert [r.status_code for r in responses]==[200,200]
    assert responses[0].json()==responses[1].json()
    assert len([row for row in current(order['work_order_id'])['execution_history'] if row.get('action')=='approve'])==1

def test_old_receipt_does_not_restore_approval_after_withdrawal():
    order,_=prepare();body=payload(order);original=approve(order,body).json()
    wid=order['work_order_id'];assert manage(current(wid),'withdraw').status_code==200
    version=current(wid)['version']
    assert approve(order,body).json()==original
    assert current(wid)['status']=='草稿·待排程' and current(wid)['version']==version
    assert not current(wid).get('last_approval_request_id')
    assert client.get('/api/resources/inventory').json()['records'][0]['reserved_quantity']==0

def test_reject_receipt_does_not_claim_an_approval_timestamp():
    order,_=prepare();body=payload(order,decision='reject',note='先调整停机窗口')
    first=approve(order,body)
    assert first.status_code==200 and approve(order,body).json()==first.json()
    saved=current(order['work_order_id'])
    assert saved['approval_decision_at'] and 'approved_at' not in saved
    assert 'approval_business_revision' not in saved

def test_legacy_client_with_version_gets_a_stable_server_receipt():
    order,_=prepare();body=payload(order);body.pop('request_id')
    first=approve(order,body)
    assert first.status_code==200 and first.json()['request_id'].startswith('approval-')
    assert approve(order,body).json()==first.json()

def test_approval_receipt_survives_fresh_application_process():
    order,_=prepare();body=payload(order);first=approve(order,body)
    assert first.status_code==200,first.text
    code='''import asyncio,json,sys,httpx
from backend.main import app
async def run():
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
  response=await client.post("/api/work-orders/"+sys.argv[1]+"/approval",json=json.loads(sys.argv[2]))
  print(json.dumps({"status":response.status_code,"body":response.json()}))
asyncio.run(run())
'''
    result=subprocess.run([sys.executable,'-c',code,order['work_order_id'],json.dumps(body)],env=os.environ.copy(),capture_output=True,text=True,timeout=30,check=True)
    persisted=json.loads(result.stdout)
    assert persisted=={'status':200,'body':first.json()}
    assert current(order['work_order_id'])['version']==order['version']+1

def test_receipt_is_bound_to_authenticated_approver():
    from tests.test_security import PASSWORD,login,create_user
    order,_=prepare();body=payload(order)
    bootstrap=client.post('/api/auth/bootstrap',json={'username':'developer','display_name':'设备管理员','password':PASSWORD})
    assert bootstrap.status_code==200,bootstrap.text
    admin=login('developer');create_user(admin,'manager02','admin');other=login('manager02')
    path=f"/api/work-orders/{order['work_order_id']}/approval"
    assert client.post(path,json=body,headers=admin).status_code==200
    assert client.post(path,json=body,headers=other).status_code==409
