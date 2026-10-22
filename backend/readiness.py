"""Read-only validity checks; never substitute for joint scheduling."""
from datetime import datetime

def resource_time_readiness(requirements,staff,now=None):
    clock=now or datetime.now()
    if clock.tzinfo:clock=clock.astimezone().replace(tzinfo=None)
    def parse(value):
        try:
            moment=datetime.fromisoformat(str(value))
            if moment.tzinfo:moment=moment.astimezone().replace(tzinfo=None)
            return moment
        except (ValueError,TypeError):return None
    groups=[]
    for kind,rows,identifier,start_key,end_key,title in [('requirements',requirements,'equipment_id','window_start','window_end','设备停机窗口'),('staff',staff,'staff_id','shift_start','shift_end','人员班次')]:
        issues=[] if rows else [{"id":"尚未录入","reason":"请先配置时间条件"}]
        for row in rows:
            start=parse(row.get(start_key));end=parse(row.get(end_key))
            reason='时间缺失或无法识别' if start is None or end is None else '结束时间不晚于开始' if end<=start else '时间已过期' if end<=clock else None
            if not reason and kind=='requirements':
                try:hours=float(row.get('maintenance_hours',float(row.get('inspection_duration_h',0))+float(row.get('repair_duration_h',0))))
                except (TypeError,ValueError):hours=0
                if hours>0 and (end-max(clock,start)).total_seconds()/3600<hours:reason='剩余窗口不足以完成检修'
            if reason:issues.append({'id':str(row.get(identifier) or '未提供编号'),'reason':reason})
        groups.append({'kind':kind,'title':title,'records':len(rows),'issues':issues})
    return {'checked_at':clock.isoformat(sep=' '),'issue_count':sum(len(group['issues']) for group in groups),'groups':groups,'scope':'仅检查已录入时间条件，不代表技能、库存、订单和联合排程已通过'}
