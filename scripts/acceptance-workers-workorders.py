"""Real native Workers/D1 workflow acceptance, isolated databases only."""
import json,sys,uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.d1_identity import D1Store
private=Path(json.loads((ROOT/'.secrets/acceptance-current.json').read_text())['directory'])
manifest=json.loads((private/'manifest.json').read_text());assert manifest['scope']=='isolated_cloudflare_acceptance'
cfg=json.loads((private/'business.json').read_text());assert cfg['database_id']==manifest['databases']['business']['id'];assert cfg['database_id']!='abc7cb74-5be4-49a2-827a-3bd8b639f257'
creds=json.loads((private/'credentials.json').read_text());out=ROOT/'outputs/full-acceptance/workers-workorders.json'
checks=[]
def save():out.write_text(json.dumps({'scope':'isolated_native_workers_real_d1','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
base='https://factorypulse-workorders-qa.griffonage2077.workers.dev';c=httpx.Client(base_url=base,headers={'Origin':base},timeout=45,trust_env=False)
if '--browser' in sys.argv:
 bridge=httpx.Client(trust_env=False,timeout=30)
 target=bridge.post('http://127.0.0.1:3456/new',content=base+'/api/health').json()['targetId']
 (ROOT/'outputs/full-acceptance/workers-browser-target.json').write_text(json.dumps({'targetId':target}))
 class BrowserSession:
  def request(self,method,path,payload=None):
   options={'method':method,'credentials':'include','headers':{'Content-Type':'application/json'}}
   if payload is not None:options['body']=json.dumps(payload,ensure_ascii=False)
   js='(async()=>{const r=await fetch('+json.dumps(path)+',{...'+json.dumps(options)+',signal:AbortSignal.timeout(20000)});return {status:r.status,body:await r.text()}})()'
   result=bridge.post('http://127.0.0.1:3456/eval?target='+target,content=js).json()
   if 'value' not in result:raise RuntimeError('Browser request did not complete')
   return httpx.Response(result['value']['status'],text=result['value']['body'])
  def get(self,path):return self.request('GET',path)
  def post(self,path,**kwargs):return self.request('POST',path,kwargs['json'])
 c=BrowserSession()
def call(name,path,p=None,status=200):
 r=c.post('/api'+path,json=p) if p is not None else c.get('/api'+path)
 try:b=r.json()
 except ValueError:b={'detail':'Non-JSON server response'}
 checks.append({'name':name,'path':path,'status':r.status_code,'passed':r.status_code==status});save();print(name+': '+str(r.status_code),flush=True)
 if r.status_code!=status:raise RuntimeError(name+': '+str(b.get('detail','Unexpected response'))[:350])
 return b
key=lambda:{'request_id':'workers-qa-'+uuid.uuid4().hex}
if len(sys.argv)>1 and sys.argv[1]=='prepare':
 local=httpx.Client(base_url='http://127.0.0.1:8001',headers={'Origin':'http://127.0.0.1:8001'},timeout=100,trust_env=False)
 assert local.post('/api/auth/login',json={'username':creds['user_id'],'password':creds['password']}).status_code==200
 response=local.get('/api/overview');assert response.status_code==200
 overview=response.json();version=overview['sync']['last_sync_at'];store=D1Store(cfg)
 assert overview['metrics']['total']==2
 store.batch([{'sql':'CREATE TABLE IF NOT EXISTS fp_computed_views(dataset_id TEXT NOT NULL,view_key TEXT NOT NULL,content TEXT NOT NULL,PRIMARY KEY(dataset_id,view_key))'},{'sql':'INSERT OR REPLACE INTO fp_computed_views VALUES(?,?,?)','params':[version,'overview',json.dumps(overview,ensure_ascii=False,separators=(',',':'))]}])
 print('Two-device real Python model evidence published only to isolated D1.',flush=True);sys.exit()
call('Workers 真实账号登录','/auth/login',{'username':creds['user_id'],'password':creds['password']})
overview=call('Workers D1 概览','/overview');assert len(overview['devices'])==2
timeline=call('Workers 人员设备时间轴','/maintenance/timeline');version=timeline['dataset_version'];device=next(x for x in overview['devices'] if x['equipment_id']=='VAL-CNC-009')
assert not any(x['equipment_id']=='VAL-CNC-009' and x['status'] not in ['已完成','已取消'] and not x.get('deleted_at') for x in timeline['work_orders']),'Existing QA order; inspect before another run'
start=(datetime.now(timezone.utc)+timedelta(hours=1)).replace(second=0,microsecond=0);end=start+timedelta(hours=12)
at=lambda d:d.isoformat()
requirements=call('读取检修条件','/resources/requirements')['records'];rule=next(x for x in requirements if x['equipment_id']=='VAL-CNC-009')
rule={k:rule[k] for k in ['maintenance_hours','maintenance_cost_cny','required_skill','spare_parts']};rule.update(required_staff_count=1,window_start=at(start),window_end=at(end))
call('保存独立设备停机窗口','/resources/requirements/VAL-CNC-009',rule)
person=timeline['staff'][0];skills=person['skills'].split(',')
call('保存独立维修班次','/resources/staff/'+str(person['staff_id']),{'staff_name':person['staff_name'],'skills':skills,'available_hours':12,'shift_start':at(start),'shift_end':at(end)})
for order in timeline['orders']:
 if order['equipment_id']=='VAL-CNC-009':call('设置独立生产占用','/resources/orders/'+order['order_id'],{'equipment_id':order['equipment_id'],'order_name':order.get('order_name',order['order_id']),'start_at':at(start),'end_at':at(start+timedelta(hours=1)),'due_at':at(start+timedelta(hours=1)),'delay_cost_cny_per_hour':0})
alert=call('当前预警','/alerts')['records'];old=next((x for x in alert if x['equipment_id']==device['equipment_id'] and x['dataset_version']==version and x['prediction_at']==device['prediction_at']),None)
guard={'expected_dataset_version':version,'prediction_at':device['prediction_at'],'version':old['version'] if old else 0}
confirmed=call('Workers 确认预警','/alerts/VAL-CNC-009/action',{**guard,'action':'confirm','note':'独立 Workers 验收',**key()})
draft=call('Workers 预警转工单','/alerts/VAL-CNC-009/action',{**guard,'version':confirmed['version'],'action':'work_order','note':'独立 Workers 验收',**key()});id=draft['work_order_id']
plan={'scenario_id':timeline['scenarios'][0]['scenario_id'],**key()};scheduled=call('Workers 生成维修安排','/schedule/generate',plan);assert any(x['work_order_id']==id for x in scheduled['scheduled'])
assert call('Workers 排程幂等','/schedule/generate',plan)==scheduled
record=call('Workers 工单流转证据','/work-orders/'+id+'/flow')['record'];assert datetime.fromisoformat(record['start_at']).replace(tzinfo=timezone(timedelta(hours=8)))>=start+timedelta(hours=1)
approve={'decision':'approve','version':record['version'],'note':'独立原生 Workers 验收',**key()};call('Workers 审批','/work-orders/'+id+'/approval',approve)
assert call('Workers 审批幂等','/work-orders/'+id+'/approval',approve)['status']=='已批准'
stock_before=call('Workers 执行前库存','/resources/inventory')['records']
for action in ['accept','start','pause','resume','finish','verify']:
 record=call('读取'+action+'前工单','/work-orders/'+id+'/flow')['record']
 p={'action':action,'version':record['version'],'actor':'client value','note':'独立原生 Workers 闭环验收',**key()}
 if action=='finish':p.update(actual_hours=record['hours'],actual_cost_cny=record['cost'])
 if action=='verify':p['actual_parts']=[{'part_name':x['part_name'],'quantity':x['quantity']} for x in record.get('spare_parts',[])]
 result=call('Workers '+action,'/work-orders/'+id+'/transition',p);assert call('Workers '+action+'幂等','/work-orders/'+id+'/transition',p)==result
final=call('Workers 完成工单回读','/work-orders/'+id+'/flow')['record'];assert final['status']=='已完成'
stock_after=call('Workers 实际库存回读','/resources/inventory')['records']
for part in final.get('spare_parts',[]):assert next(x['on_hand'] for x in stock_after if x['part_name']==part['part_name'])==next(x['on_hand'] for x in stock_before if x['part_name']==part['part_name'])-part['quantity']
for action in ['archive','restore']:
 record=call('读取管理前工单','/work-orders/'+id+'/flow')['record'];call('Workers '+action,'/work-orders/'+id+'/manage',{'action':action,'version':record['version'],'note':'独立 Workers 回收站验收',**key()})
call('Workers 退出','/auth/logout',{})
call('Workers 未登录拦截','/work-orders',status=401)
print('Native Workers real D1 workflow passed; production data untouched.',flush=True)
