"""Exercise actual API transitions on an isolated database copy."""
import argparse,asyncio,json,os,sqlite3,sys,uuid
from pathlib import Path
from datetime import datetime,timezone
parser=argparse.ArgumentParser()
parser.add_argument('--database',type=Path,required=True)
parser.add_argument('--all-equipment',action='store_true')
parser.add_argument('--dataset',choices=['current','metropt3','cnc-demo','nasa-ims'],default='current')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
out=root/'outputs'/('workflow-proof-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:4]);out.mkdir()
copy=out/'factorypulse.sqlite3'
with sqlite3.connect(args.database.resolve()) as source,sqlite3.connect(copy) as target:source.backup(target)
os.environ['FACTORYPULSE_DATA_DIR']=str(out);os.environ['FACTORYPULSE_AUTH_REQUIRED']='0';os.environ['FACTORYPULSE_AUTO_BACKUP']='0'
from backend.main import app
import httpx
async def run():
 steps=[];targets=[]
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
  async def call(method,path,body=None):
   response=await client.request(method,path,json=body) if body is not None else await client.request(method,path)
   if response.status_code!=200:raise RuntimeError(f'{path}: {response.status_code} {response.text[:600]}')
   return response.json()
  if args.dataset!='current':await call('POST','/api/sync/'+args.dataset)
  sync=await call('GET','/api/sync/status');version=sync['last_sync_at']
  devices=(await call('GET','/api/overview'))['devices']
  selected=devices if args.all_equipment else [max((d for d in devices if d.get('risk_available',True)),key=lambda d:d['risk_score'])]
  alerts=(await call('GET','/api/alerts'))['records']
  for device in selected:
   eid=device['equipment_id']
   prior=next((a for a in alerts if a['dataset_version']==version and a['equipment_id']==eid and a['prediction_at']==device['prediction_at']),None)
   guard={'expected_dataset_version':version,'prediction_at':device['prediction_at'],'version':prior['version'] if prior else 0,'request_id':uuid.uuid4().hex,'note':'副本全流程演练：模拟检查需求，非实际故障或现场维修'}
   confirmed=await call('POST',f'/api/alerts/{eid}/action',{**guard,'action':'confirm'})
   created=await call('POST',f'/api/alerts/{eid}/action',{**guard,'version':confirmed['version'],'request_id':uuid.uuid4().hex,'action':'work_order'})
   targets.append({'equipment_id':eid,'work_order_id':created['work_order_id']})
   steps.extend([{'step':'复核预警','equipment_id':eid,'status':confirmed['status']},{'step':'维护需求',**targets[-1]}])
  scenario=(await call('GET','/api/records/scenarios'))['records'][0];sid=scenario['scenario_id']
  compared=await call('GET',f'/api/strategies/compare?scenario_id={sid}');steps.append({'step':'方案比较','strategies':len(compared['strategies'])})
  plan=await call('POST','/api/schedule/generate',{'scenario_id':sid,'request_id':uuid.uuid4().hex})
  planned={item['work_order_id'] for item in plan['scheduled']}
  assert all(target['work_order_id'] in planned for target in targets),plan
  assert not plan['conflicts'],plan['conflicts']
  assert sum(item['cost'] for item in plan['scheduled'])<=scenario['maintenance_budget_cny']
  assert sum(item['hours'] for item in plan['scheduled'])<=scenario['max_downtime_h']
  steps.append({'step':'排程','scheduled':plan['scheduled'],'conflicts':plan['conflicts']})
  async def order(wid):return next(r for r in (await call('GET','/api/work-orders'))['records'] if r['work_order_id']==wid)
  # Approve all before executing any, so cross-order resource/stock checks remain active.
  for target in targets:
   wid=target['work_order_id'];current=await order(wid)
   assert not current.get('assumptions'),current.get('assumptions')
   await call('POST',f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'副本演练设备总管','note':'模拟经营条件已核对','version':current['version']})
   steps.append({'step':'人工审批','work_order_id':wid,'status':'已批准'})
  for target in targets:
   wid=target['work_order_id']
   for action in ['accept','start','pause','resume','finish','verify']:
    current=await order(wid)
    body={'action':action,'version':current['version'],'actor':'副本演练人员','note':'模拟全流程演练，非真实维修','request_id':uuid.uuid4().hex}
    if action=='finish':body.update(actual_hours=current['hours'],actual_cost_cny=current['cost'])
    if action=='verify':body['actual_parts']=[{'part_name':part['part_name'],'quantity':part['quantity']} for part in current.get('spare_parts',[])]
    result=await call('POST',f'/api/work-orders/{wid}/transition',body)
    steps.append({'step':action,'work_order_id':wid,'status':result['status']})
   assert (await order(wid))['status']=='已完成'
   with sqlite3.connect(copy) as c:
    event=c.execute('SELECT content FROM maintenance_events WHERE work_order_id=?',(wid,)).fetchone();assert event
    target['maintenance_event']=json.loads(event[0])
  report={'result':'passed','source_database':str(args.database.resolve()),'copy_database':str(copy),'targets':targets,'steps':steps,'simulation_only':True,'all_equipment':args.all_equipment,'dataset':args.dataset,'data_origin':sync.get('data_origin'),'sampling_records':sync.get('record_count'),'scheduled_cost':sum(item['cost'] for item in plan['scheduled']),'scheduled_hours':sum(item['hours'] for item in plan['scheduled'])}
  (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
  print(json.dumps({'result':'passed','report':str(out/'report.json'),'equipment_count':len(targets),'scheduled_cost':report['scheduled_cost'],'scheduled_hours':report['scheduled_hours'],'stages':len(steps),'operator_database_not_executed':True},ensure_ascii=False))
asyncio.run(run())
