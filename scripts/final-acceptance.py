"""Final software acceptance uses one SHA-verified frozen dataset, in a disposable DB."""
import os,tempfile,json,hashlib,sys,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
runtime=tempfile.TemporaryDirectory(prefix='factorypulse-final-')
os.environ['FACTORYPULSE_DATA_DIR']=runtime.name
os.environ['FACTORYPULSE_AUTH_REQUIRED']='0'
os.environ.pop('FACTORYPULSE_ENABLE_LEGACY_FIXTURES',None)
from fastapi.testclient import TestClient
from backend import main
from backend.model_validation_data import load_acceptance_dataset
client=TestClient(main.app,client=('127.0.0.1',45678));checks=[]
bootstrap=client.post('/api/auth/bootstrap',json={'username':'acceptance-admin','display_name':'隔离验收管理员','password':'temporary-acceptance-password-2026'})
assert bootstrap.status_code==200,bootstrap.text
for step in range(1,6):assert client.post('/api/auth/onboarding',json={'step':step}).status_code==200
def call(method,path,body=None):
 r=client.request(method,path,json=body) if body is not None else client.request(method,path)
 if r.status_code!=200:raise RuntimeError(f'{method} {path}: {r.status_code} {r.text[:500]}')
 return r.json()
def check(name,detail):checks.append({'name':name,'passed':True,'detail':detail});print(name,flush=True)
manifest=json.loads((ROOT/'data/model-validation/manifest.json').read_text(encoding='utf-8'))
load_acceptance_dataset(False);check('冻结数据身份',manifest['sha256'])
assert client.post('/api/sync/metropt3').status_code==410
call('POST','/api/sync/model-validation');check('唯一数据加载','旧实验入口返回410；当前24台、34560条合成记录')
t=time.perf_counter();overview=call('GET','/api/overview');cold=time.perf_counter()-t
t=time.perf_counter();call('GET','/api/overview');warm=time.perf_counter()-t
quality=call('GET','/api/data-quality');evaluation=call('GET','/api/model/evaluation')
e=evaluation['evaluation'];assert e['synthetic_validation_only'] and e['test_rows']>0
assert all(d['risk_score']==d['model_risk'] for d in overview['devices'])
for device in overview['devices']:
 details=device['scoring_details'];model=details['model'];trend=details['trend']
 assert model and abs(model['reconstructed_score']-model['model_output'])<.000002
 assert abs(model['reconstructed_score']-device['model_risk'])<.000051
 assert details['rule']['matches_stored']
 if trend.get('score') is not None:assert round(min(trend['deviation']/trend['baseline']/6,1),4)==trend['score']
check('逐设备评分复算','全部设备的规则、EWMA与模型贡献转换均与显示分数核对一致')

assert e['adaptive_training']['validation_stability']['status']=='reserved_not_used_for_selection'
check('验证稳定性段','后段验证数据未参与候选或阈值选择，且与选择段隔离168小时')
check('评分评估一致','当前风险排序直接使用模型分数；规则与趋势不融合')
check('数据质量实算',f"缺失率 {quality['missing_rate']}，重复 {quality['duplicate_readings']}")
check('读取耗时',f'本机冷读取 {cold:.3f}s，热读取 {warm:.3f}s；不是负载认证')
with main.connect() as db:before=db.execute('SELECT COUNT(*) FROM planning_runs').fetchone()[0]
call('GET','/api/strategies/compare?scenario_id=VAL-BASE')
with main.connect() as db:assert db.execute('SELECT COUNT(*) FROM planning_runs').fetchone()[0]==before
check('只读预览不写方案','GET比较不产生planning_runs')
request=call('POST','/api/maintenance-requests',{'equipment_id':'VAL-CNC-001','action':'最终软件验收，非真实维修','priority':'高','request_id':'final-acceptance-request-001'})
comparison=call('POST','/api/strategies/compare',{'scenario_id':'VAL-BASE'})
plan=next(p for p in comparison['strategies'] if p['strategy']=='optimized')
assert client.get('/api/export/maintenance.csv?plan_id='+plan['plan_id']).status_code==200
scheduled=call('POST','/api/schedule/generate',{'scenario_id':'VAL-BASE','request_id':'final-acceptance-schedule-001'})
wid=request['work_order_id'];assert any(w['work_order_id']==wid for w in scheduled['scheduled'])
check('维护需求、快照与联合排程','使用同一冻结集及明确模拟经营条件；导出读取已保存快照')
def order():return call('GET',f'/api/work-orders/{wid}/flow')['record']
call('POST',f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'软件验收','note':'仅隔离程序验收','accept_assumptions':True,'version':order()['version'],'request_id':'final-acceptance-approval-001'})
for action in ['accept','start','pause','resume','finish','verify']:
 payload={'action':action,'actor':'软件验收','note':'隔离程序验收，非现场维修','version':order()['version'],'request_id':'final-acceptance-'+action+'-001'}
 if action=='verify':payload.update(actual_parts=[{'part_name':p['part_name'],'quantity':0} for p in order().get('spare_parts',[])])
 if action=='finish':payload.update(actual_hours=1,actual_cost_cny=100,actual_parts=[{'part_name':p['part_name'],'quantity':0} for p in order().get('spare_parts',[])])
 call('POST',f'/api/work-orders/{wid}/transition',payload)
check('审批至验收闭环','接单、开工、暂停、恢复、完工、验收均由后端状态与资源规则检查')
report={'dataset':manifest,'generated_at':datetime.now(timezone.utc).isoformat(),'model_version':evaluation['model_version'],'quality':quality,'evaluation':e,'devices':[{'equipment_id':d['equipment_id'],'score':d['model_risk']} for d in overview['devices']],'checks':checks,'unverified':['真实人员试用','现场泛化与经济收益','干净Windows电脑和物理断网'],'code_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((ROOT/'backend').glob('*.py'))+list((ROOT/'config').glob('*.json'))},'timing':{'cold_overview_seconds':cold,'warm_overview_seconds':warm}}
output=ROOT/'outputs/final-acceptance';output.mkdir(parents=True,exist_ok=True)
import sqlite3
from contextlib import closing
runtime_output=ROOT/'outputs/final-runtime';runtime_output.mkdir(exist_ok=True)
with main.connect() as source,closing(sqlite3.connect(runtime_output/'factorypulse.sqlite3')) as destination:source.backup(destination)
(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
public=ROOT/'public';public.mkdir(exist_ok=True)
(public/'acceptance-evidence.json').write_text(json.dumps(report,ensure_ascii=False,allow_nan=False),encoding='utf-8')
print(json.dumps({'passed':True,'checks':len(checks),'f1':e['f1'],'report':str(output/'report.json')},ensure_ascii=False),flush=True)
