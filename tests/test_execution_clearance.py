import json,uuid
from backend.main import connect
from tests.test_api import client,workbook
from tests.test_workflow_board import prepare,post,current,manage


def approve(order):
    post(f"/api/work-orders/{order['work_order_id']}/approval",{'decision':'approve','approver':'主管','version':order['version']})
    return current(order['work_order_id'])

def transition(order,action,request_id=None):
    return client.post(f"/api/work-orders/{order['work_order_id']}/transition",json={'action':action,'actor':'维修人员','note':'执行前核对','version':order['version'],'request_id':request_id or uuid.uuid4().hex})


def test_resource_change_blocks_accept_until_withdraw_replan_and_reapprove():
    order,at=prepare();order=approve(order);wid=order['work_order_id']
    post('/api/resources/staff/ST-1',{'staff_name':'修改班次资料','skills':['机修'],'available_hours':8,'shift_start':at(0),'shift_end':at(10)})
    rejected=transition(order,'accept')
    assert rejected.status_code==409 and '资源已变化' in rejected.text
    assert current(wid)['status']=='已批准' and current(wid)['version']==order['version']
    assert manage(order,'withdraw').status_code==200
    assert not current(wid).get('approval_business_revision')
    post('/api/schedule/generate',{'scenario_id':'S-1','request_id':uuid.uuid4().hex,'start_at':at(0)})
    approved=approve(current(wid))
    request_id=uuid.uuid4().hex
    result=transition(approved,'accept',request_id)
    assert result.status_code==200,result.text
    assert transition(approved,'accept',request_id).json()==result.json()
    assert current(wid)['execution_check']['checks']
    assert current(wid)['execution_history'][-1]['execution_check']['action']=='accept'
    assert manage(current(wid),'withdraw').status_code==200
    withdrawn=current(wid)
    assert not withdrawn.get('execution_check')
    assert any(item.get('execution_check',{}).get('action')=='accept' for item in withdrawn['execution_history'])


def test_production_change_after_accept_blocks_first_start():
    order,at=prepare();order=approve(order);wid=order['work_order_id']
    assert transition(order,'accept').status_code==200
    order=current(wid)
    post('/api/resources/orders/O-1',{'order_name':'新增生产占用','equipment_id':order['equipment_id'],'start_at':order['start_at'],'end_at':order['end_at'],'due_at':at(10)})
    result=transition(order,'start')
    assert result.status_code==409 and current(wid)['status']=='已接单'
    assert not current(wid).get('actual_start_at')


def test_dataset_replacement_cannot_start_old_unstarted_order():
    order,at=prepare();order=approve(order)
    assert transition(order,'accept').status_code==200
    order=current(order['work_order_id'])
    assert client.post('/api/import',files={'file':('new.xlsx',workbook(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}).status_code==200
    response=transition(order,'start')
    assert response.status_code==409 and '数据版本已变化' in response.text


def test_waiting_verification_still_blocks_conflicting_approval():
    order,at=prepare();wid=order['work_order_id']
    with connect() as connection:
        other={**order,'work_order_id':'WAIT-VERIFY','version':1}
        connection.execute('INSERT INTO work_orders VALUES (?,?,?,?,?)',('WAIT-VERIFY',order['equipment_id'],json.dumps(other),'待验收',at(0)))
    reserved_before=client.get('/api/resources/inventory').json()['records'][0]['reserved_quantity']
    response=client.post(f'/api/work-orders/{wid}/approval',json={'decision':'approve','approver':'主管','version':order['version']})
    assert response.status_code==409 and 'WAIT-VERIFY' in response.text
    assert current(wid)['status']=='待审批'
    assert client.get('/api/resources/inventory').json()['records'][0]['reserved_quantity']==reserved_before
    with connect() as connection:
        assert not connection.execute("SELECT 1 FROM inventory_reservations WHERE work_order_id=? AND state='reserved'",(wid,)).fetchone()


def test_legacy_approved_order_needs_explicit_reapproval():
    order,at=prepare();wid=order['work_order_id']
    with connect() as connection:
        connection.execute("UPDATE work_orders SET status='已批准' WHERE work_order_id=?",(wid,))
    result=transition(current(wid),'accept')
    assert result.status_code==409 and '旧工单缺少审批资源版本' in result.text


def test_stock_shortage_blocks_start_without_consuming_retry_identifier():
    order,at=prepare();order=approve(order);wid=order['work_order_id']
    assert transition(order,'accept').status_code==200
    order=current(wid);request_id=uuid.uuid4().hex
    with connect() as connection: connection.execute('UPDATE inventory_stock SET on_hand=0')
    result=transition(order,'start',request_id)
    assert result.status_code==409 and '备件' in result.text
    assert current(wid)['version']==order['version'] and not current(wid).get('actual_start_at')
    with connect() as connection: connection.execute('UPDATE inventory_stock SET on_hand=5')
    retry=transition(order,'start',request_id)
    assert retry.status_code==200,retry.text
    assert transition(order,'start',request_id).json()==retry.json()
