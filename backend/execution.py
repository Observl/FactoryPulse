"""Recheck an approved plan before acknowledging or first starting it."""
import json
from datetime import datetime,timezone
from fastapi import HTTPException
from . import inventory

FORMAL_STATES=('已批准','已接单','执行中','已暂停','待验收')

def moment(value):
    try:
        result=datetime.fromisoformat(str(value))
        return result.astimezone().replace(tzinfo=None) if result.tzinfo else result
    except (ValueError,TypeError): raise HTTPException(409,'工单时间无效，请撤回并重新排程')

def plan_interval(content):
    if not content.get('start_at') or not content.get('end_at'):
        raise HTTPException(409,'工单缺少完整排程，请撤回并重新安排人员与时间')
    start,end=moment(content['start_at']),moment(content['end_at'])
    if end<=start: raise HTTPException(409,'工单结束时间必须晚于开始时间，请重新排程')
    team=content.get('staff_ids') or [content.get('staff_id')]
    if not team or any(not item for item in team) or len(team)!=len(set(team)):
        raise HTTPException(409,'维修人员缺失或重复，请重新排程')
    return start,end,set(team)

def assert_no_formal_conflict(connection,content):
    start,end,team=plan_interval(content)
    marks=','.join('?' for _ in FORMAL_STATES)
    for row in connection.execute(f'SELECT * FROM work_orders WHERE work_order_id<>? AND status IN ({marks})',(content['work_order_id'],*FORMAL_STATES)):
        other=json.loads(row['content'])
        if other.get('deleted_at'): continue
        same=content['equipment_id']==row['equipment_id'] or bool(team&set(other.get('staff_ids') or [other.get('staff_id')]))
        if not same: continue
        if not other.get('start_at') or not other.get('end_at'):
            raise HTTPException(409,f"正式工单 {row['work_order_id']} 的占用时间不完整，请先核对")
        if start<moment(other['end_at']) and end>moment(other['start_at']):
            raise HTTPException(409,f"与正式工单 {row['work_order_id']} 的设备或人员时间冲突，请重新排程")

def recheck_execution(connection,content,current_dataset,current_revision,action):
    if content.get('dataset_version')!=current_dataset:
        raise HTTPException(409,'数据版本已变化，此工单不能接单或首次开工；请核对来源并重新排程审批')
    approved=content.get('approval_business_revision')
    if approved is None:
        raise HTTPException(409,'旧工单缺少审批资源版本，请设备总管撤回并重新排程审批后再执行')
    if str(approved)!=str(current_revision):
        raise HTTPException(409,'审批后维修资源已变化，请设备总管撤回到待排程，重新安排并审批后再执行')
    assert_no_formal_conflict(connection,content)
    if content.get('spare_parts'):
        inventory.import_legacy_reservations(connection)
        scope=content.get('inventory_scope') or content['dataset_version']
        inventory.reserve(connection,content['work_order_id'],scope,content['spare_parts'])
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'action':action,'dataset_version':current_dataset,
            'business_revision':str(current_revision),'checks':['数据版本','审批资源版本','正式设备及人员占用','备件库存'],
            'basis':'批准的计划时间；不替代现场开工许可或实际时点安全检查'}
