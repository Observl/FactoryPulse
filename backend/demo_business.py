"""Explicit simulated business overlay; monitoring samples and fault labels stay untouched."""
from datetime import datetime,timedelta
ORIGIN="SIMULATED_BUSINESS_DATA"

def complete_demo_business(data,now=None):
    day=((now or datetime.now())+timedelta(days=1)).replace(hour=8,minute=0,second=0,microsecond=0)
    end=day+timedelta(hours=12)
    stamp=lambda value:value.isoformat(sep=" ")
    rules=data['maintenance_rules'];metro=any('METROPT' in str(row['equipment_id']) for row in data['equipment'])
    skills=sorted({row.get('required_skill') or ('空气压缩机' if metro else '机修') for row in rules})
    bearing=all(str(row['equipment_id']).startswith('IMS-') for row in data['equipment'])
    part='压缩机密封维护包（模拟）' if metro else ('轴承更换维护包（模拟）' if bearing else '机床润滑维护包（模拟）')
    for row in rules:
        row.update(maintenance_hours=row.get('maintenance_hours',row.get('inspection_duration_h',2)+row.get('repair_duration_h',6)),maintenance_cost_cny=row.get('maintenance_cost_cny',row.get('inspection_cost_cny',800)+row.get('repair_cost_cny',5500)),required_skill=row.get('required_skill') or skills[0],window_start=stamp(day),window_end=stamp(end),configuration_status='configured',spare_parts=[{'part_name':part,'quantity':1,'available_quantity':max(24,len(rules)*2)}],data_origin=ORIGIN)
    count=2 if metro else max(2,(len(rules)+1)//2)
    staff=data['staff']
    while len(staff)<count: staff.append({'staff_id':f'DEMO-TECH-{len(staff)+1:02d}','staff_name':f'演示维修员{len(staff)+1:02d}（模拟）'})
    for row in staff:
        row.update(skills=','.join(skills),available_hours=8 if metro else 10,shift_start=stamp(day),shift_end=stamp(end),data_origin=ORIGIN)
        if '模拟' not in row['staff_name']:row['staff_name']+='（模拟）'
    for row in data['orders']:
        row.update(start_at=stamp(day),end_at=stamp(day+timedelta(hours=2)),due_at=stamp(day+timedelta(hours=2)),delay_cost_cny_per_hour=500,data_origin=ORIGIN)
        row.pop('production_start',None)
        if '模拟' not in row.get('order_name',''):row['order_name']=row.get('order_name',row['order_id'])+'（模拟）'
    total_cost=sum(row['maintenance_cost_cny'] for row in rules);total_hours=sum(row['maintenance_hours'] for row in rules)
    base=data['scenarios'][0]
    base.update(scenario_name='全流程维护演示（模拟经营条件）',maintenance_budget_cny=max(10000,round(total_cost*1.2)),available_staff_count=count,max_downtime_h=max(8,total_hours),risk_threshold=.15,data_origin=ORIGIN,assumed_failure_probability=.1)
    return data


def initialize_demo_stock(connection,data,scope):
    """Only called for built-in demo profiles, never for enterprise imports."""
    import uuid
    from datetime import timezone
    now=datetime.now(timezone.utc).isoformat()
    counts={}
    for rule in data.get('maintenance_rules',[]):
        if rule.get('data_origin')!=ORIGIN:continue
        for part in rule.get('spare_parts',[]):
            if '模拟' not in part['part_name']:continue
            counts[part['part_name']]=min(counts.get(part['part_name'],part['available_quantity']),part['available_quantity'])
    for name,count in counts.items():
        existing=connection.execute('SELECT on_hand,version,source FROM inventory_stock WHERE scope=? AND part_name=?',(scope,name)).fetchone()
        if existing and existing['source']!='legacy_unverified':continue
        previous=existing['on_hand'] if existing else 0
        connection.execute('INSERT OR REPLACE INTO inventory_stock VALUES (?,?,?,?,?,?)',(scope,name,count,(existing['version'] if existing else 0)+1,now,'simulated_count'))
        connection.execute('INSERT INTO inventory_movements VALUES (?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,scope,name,None,'simulated_count',count-previous,'内置演示包的模拟初始库存，非企业实盘',now))
