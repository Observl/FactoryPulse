import json,uuid
from datetime import datetime,timedelta
from tests.test_api import client,workbook
from backend.main import connect,settings_get

def post(path,body):
    response=client.post(path,json=body)
    assert response.status_code==200,response.text
    return response.json()

def prepare():
    assert client.post('/api/import',files={'file':('test.xlsx',workbook(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}).status_code==200
    base=(datetime.now()+timedelta(days=2)).replace(hour=8,minute=0,second=0,microsecond=0)
    at=lambda hour:(base+timedelta(hours=hour)).isoformat(sep=' ')
    for sid in ['1','2']:
        post('/api/resources/staff/'+sid,{'staff_name':sid,'skills':['机修'],'available_hours':8,'shift_start':at(0),'shift_end':at(10)})
    post('/api/resources/orders/O-1',{'order_name':'生产占用','equipment_id':'CNC-001','start_at':at(0),'end_at':at(2),'due_at':at(2)})
    post('/api/resources/requirements/CNC-001',{'maintenance_hours':2,'maintenance_cost_cny':500,'required_skill':'机修','required_staff_count':1,'window_start':at(0),'window_end':at(10),'spare_parts':[{'part_name':'轴承','quantity':1,'available_quantity':5}]})
    post('/api/resources/scenarios/S-1',{'scenario_name':'联合安排','maintenance_budget_cny':2000,'available_staff_count':2,'max_downtime_h':8,'risk_threshold':.35})
    draft=post('/api/maintenance-requests',{'equipment_id':'CNC-001','action':'检查轴承','priority':'高','request_id':uuid.uuid4().hex})
    post('/api/schedule/generate',{'scenario_id':'S-1','request_id':uuid.uuid4().hex,'start_at':at(0)})
    order=next(r for r in client.get('/api/work-orders').json()['records'] if r['work_order_id']==draft['work_order_id'])
    return order,at

def manage(order,action,request_id=None):
    return client.post(f"/api/work-orders/{order['work_order_id']}/manage",json={'action':action,'version':order['version'],'request_id':request_id or uuid.uuid4().hex,'note':'用户修改需求'})

def current(wid):return next(o for o in client.get('/api/work-orders?include_deleted=true').json()['records'] if o['work_order_id']==wid)

def test_withdraw_approved_releases_stock_keeps_history_and_receipt():
    order,at=prepare();wid=order['work_order_id']
    post(f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'主管','version':order['version']})
    order=current(wid);request_id=uuid.uuid4().hex
    response=manage(order,'withdraw',request_id);assert response.status_code==200,response.text
    assert response.json()['status']=='草稿·待排程'
    assert manage(order,'withdraw',request_id).json()==response.json()
    value=current(wid);assert not value.get('staff_ids') and not value.get('start_at')
    assert value['execution_history'][-1]['action']=='withdraw'
    stock=client.get('/api/resources/inventory').json()['records'][0]
    assert stock['reserved_quantity']==0 and stock['on_hand']==5

def test_archive_is_recoverable_and_hidden_from_queue():
    order,at=prepare();wid=order['work_order_id'];assert manage(order,'withdraw').status_code==200
    order=current(wid);assert manage(order,'archive').status_code==200
    assert not client.get('/api/work-orders').json()['records']
    deleted=current(wid);assert deleted['deleted_at']
    assert manage(deleted,'restore').status_code==200
    assert current(wid)['status']=='草稿·待排程'
    assert not current(wid).get('deleted_at')

def test_restore_cannot_create_duplicate_live_request():
    order,at=prepare();wid=order['work_order_id'];assert manage(order,'withdraw').status_code==200
    assert manage(current(wid),'archive').status_code==200
    post('/api/maintenance-requests',{'equipment_id':'CNC-001','action':'新的检查需求','request_id':uuid.uuid4().hex})
    assert manage(current(wid),'restore').status_code==409

def test_dataset_timeline_never_mixes_orders_or_staff():
    order,at=prepare();old=order['dataset_version']
    assert client.post('/api/import',files={'file':('next.xlsx',workbook(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}).status_code==200
    now=client.get('/api/maintenance/timeline').json()
    assert now['current'] and now['work_orders']==[]
    past=client.get('/api/maintenance/timeline',params={'dataset_version':old}).json()
    assert not past['current'] and len(past['work_orders'])==1
    assert {p['staff_id'] for p in past['staff']}=={'1','2'}
    assert client.get('/api/work-orders',params={'dataset_version':old}).json()['records'][0]['work_order_id']==order['work_order_id']

def edit_payload(order,at,**extra):
    return {'version':order['version'],'staff_ids':['2'],'start_at':at(4),'end_at':at(6),'scenario_id':'S-1','note':'拖动任务调整','request_id':uuid.uuid4().hex,**extra}

def test_timeline_preview_then_save_invalidates_approval_and_is_idempotent():
    order,at=prepare();wid=order['work_order_id']
    post(f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'主管','version':order['version']})
    order=current(wid);payload=edit_payload(order,at)
    preview=post(f'/api/work-orders/{wid}/timeline',payload)
    assert current(wid)['status']=='已批准'
    payload.update(apply=True,state_fingerprint=preview['state_fingerprint'])
    saved=post(f'/api/work-orders/{wid}/timeline',payload)
    assert saved['status']=='待审批'
    assert post(f'/api/work-orders/{wid}/timeline',payload)==saved
    item=current(wid);assert item['staff_ids']==['2'] and item['start_at']==at(4)
    assert item['execution_history'][-1]['before']['staff_ids']!=['2'] or item['execution_history'][-1]['before']['start_at']!=at(4)
    assert client.get('/api/resources/inventory').json()['records'][0]['reserved_quantity']==0

def test_timeline_rejects_order_overlap_short_duration_and_missing_skill():
    order,at=prepare();path=f"/api/work-orders/{order['work_order_id']}/timeline"
    assert client.post(path,json=edit_payload(order,at,start_at=at(0),end_at=at(2))).status_code==422
    assert client.post(path,json=edit_payload(order,at,end_at=at(5))).status_code==422
    post('/api/resources/staff/2',{'staff_name':'电工','skills':['电气'],'available_hours':8,'shift_start':at(0),'shift_end':at(10)})
    assert client.post(path,json=edit_payload(order,at)).status_code==422

def test_stale_timeline_preview_cannot_overwrite_resource_change():
    order,at=prepare();payload=edit_payload(order,at);path=f"/api/work-orders/{order['work_order_id']}/timeline"
    preview=post(path,payload)
    post('/api/resources/scenarios/S-1',{'scenario_name':'修改预算','maintenance_budget_cny':1500,'available_staff_count':2,'max_downtime_h':8,'risk_threshold':.35})
    assert client.post(path,json={**payload,'apply':True,'state_fingerprint':preview['state_fingerprint']}).status_code==409

def test_started_order_cannot_be_erased_or_withdrawn():
    order,at=prepare();wid=order['work_order_id']
    post(f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'主管','version':order['version']})
    for action in ['accept','start']:
        item=current(wid);post(f'/api/work-orders/{wid}/transition',{'action':action,'actor':'维修员','version':item['version'],'request_id':uuid.uuid4().hex})
    assert manage(current(wid),'withdraw').status_code==409
    assert manage(current(wid),'archive').status_code==409


def test_finished_submission_can_be_withdrawn_without_erasing_execution():
    order,at=prepare();wid=order['work_order_id']
    post(f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'主管','version':order['version']})
    for action in ['accept','start','finish']:
        post(f'/api/work-orders/{wid}/transition',{'action':action,'actor':'维修员','note':'实际处理说明','version':current(wid)['version'],'request_id':uuid.uuid4().hex,'actual_hours':2,'actual_cost_cny':500})
    assert current(wid)['status']=='待验收'
    assert manage(current(wid),'withdraw').status_code==200
    value=current(wid)
    assert value['status']=='执行中' and value['actual_start_at']
    assert not value.get('actual_finish_at')


def test_timeline_rejects_outside_shift_and_insufficient_budget():
    order,at=prepare();path=f"/api/work-orders/{order['work_order_id']}/timeline"
    assert client.post(path,json=edit_payload(order,at,start_at=at(9),end_at=at(11))).status_code==422
    post('/api/resources/scenarios/S-1',{'scenario_name':'预算不足','maintenance_budget_cny':100,'available_staff_count':2,'max_downtime_h':8,'risk_threshold':.35})
    assert client.post(path,json=edit_payload(order,at)).status_code==422
