"""Exercise the real loopback website against dedicated Cloudflare databases."""
import argparse,csv,io,json,secrets,sys,time,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import quote
import httpx
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/full-acceptance';OUT.mkdir(exist_ok=True)
PRIVATE=Path(json.loads((ROOT/'.secrets/acceptance-current.json').read_text())['directory'])
CREDS=json.loads((PRIVATE/'credentials.json').read_text())
REPORT=OUT/'api-report.json';STATE=OUT/'state.json'
report=json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else {'scope':'isolated_cloudflare_d1_real_api','checks':[],'limitations':['未连接外部付费 AI 模型；验证离线查询、权限与配置错误处理','软件模拟验收，不代表真实设备预测效果']}
state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
subset_path=OUT/'subset.json'
subset=json.loads(subset_path.read_text(encoding='utf-8')) if subset_path.exists() else None
expected_devices=subset['counts']['equipment'] if subset else 24
expected_readings=subset['counts']['readings'] if subset else 34560
base='http://127.0.0.1:8001'

def save():
    report['updated_at']=datetime.now(timezone.utc).isoformat()
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')

def client():return httpx.Client(base_url=base,headers={'Origin':base},timeout=600)

def call(c,name,method,path,body=None,expected=200,**kwargs):
    started=time.perf_counter();r=c.request(method,path,json=body,**kwargs) if body is not None else c.request(method,path,**kwargs)
    item={'name':name,'method':method,'path':path,'status':r.status_code,'seconds':round(time.perf_counter()-started,3),'passed':r.status_code==expected}
    if not item['passed']:item['detail']=r.text[:600]
    report['checks'].append(item);save()
    print(name+': '+str(r.status_code)+' '+str(item['seconds'])+'s',flush=True)
    if not item['passed']:raise RuntimeError(name+': '+r.text[:500])
    if r.headers.get('content-type','').startswith('application/json'):return r.json()
    return r

def login(c,credentials=CREDS):
    return call(c,'登录'+credentials['user_id'],'POST','/api/auth/login',{'username':credentials['user_id'],'password':credentials['password']})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['seed','workflow','agent','imports','restore','accounts']);args=parser.parse_args()
    for attempt in range(45):
        try:
            if httpx.get(base+'/api/health',timeout=5).status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(1)
    else:raise RuntimeError('Isolated acceptance server is not ready')
    c=client();login(c)
    if args.phase=='seed':
        call(c,'D1运行健康','GET','/api/health')
        call(c,'D1可读写','GET','/api/health/ready')
        call(c,'集中账号禁止网页初始化','POST','/api/auth/bootstrap',{'username':'blocked','display_name':'不得创建','password':'isolated-bootstrap-password-2026'},403)
        for step in range(1,6):call(c,'教程进度'+str(step),'POST','/api/auth/onboarding',{'step':step})
        if not subset:raise RuntimeError('先运行 acceptance-d1-subset.py；禁止全量重新激活以保护免费写入额度')
        overview=call(c,'全量设备和真实模型','GET','/api/overview')
        assert overview['metrics']['total']==expected_devices and overview['counts']['readings']==expected_readings
        assert overview['analytics']['xgboost']=='ready'
        for device in overview['devices']:
            model=device['scoring_details']['model']
            assert abs(model['reconstructed_score']-device['risk_score'])<.000051
        report['scoring_reconstruction_devices']=len(overview['devices'])
        state['dataset_version']=overview['sync']['last_sync_at'];save()
        call(c,'热读取','GET','/api/overview')
        quality=call(c,'数据质量实算','GET','/api/data-quality');assert quality['reading_count']==expected_readings
        for path in ['/api/model/evaluation','/api/model/replay','/api/equipment/VAL-CNC-001/history?points=360','/api/equipment/VAL-CNC-001/operations','/api/operations/resource-occupancy','/api/maintenance/time-readiness','/api/maintenance/timeline','/api/data/versions','/api/alerts','/api/work-orders','/api/audit','/api/developer/settings','/api/backups/status','/api/copilot/harness']:
            call(c,'读取'+path,'GET',path)
        call(c,'禁止本地数据库备份','POST','/api/backups/create',expected=409)
        call(c,'禁止本地SQLite导入','POST','/api/import/database/inspect',expected=422,files={'file':('isolated.sqlite3',b'SQLite format 3\0test')})
        for kind in ['staff','orders','scenarios','requirements','inventory']:call(c,'读取资源'+kind,'GET','/api/resources/'+kind)
    elif args.phase=='workflow':
        overview=call(c,'设备证据','GET','/api/overview');version=overview['sync']['last_sync_at']
        device=next(d for d in overview['devices'] if d['equipment_id']=='VAL-CNC-001')
        if 'work_order_id' not in state:
            guard={'expected_dataset_version':version,'prediction_at':device['prediction_at'],'version':0,'note':'独立D1全流程模拟验收，不是真实维修','request_id':'qa-confirm-001'}
            result=call(c,'确认预警','POST','/api/alerts/VAL-CNC-001/action',{**guard,'action':'confirm'})
            call(c,'拒绝过期预警版本','POST','/api/alerts/VAL-CNC-001/action',{**guard,'action':'confirm','request_id':'qa-stale-alert-001'},409)
            order=call(c,'预警转维修需求','POST','/api/alerts/VAL-CNC-001/action',{**guard,'version':result['version'],'action':'work_order','request_id':'qa-order-001'})
            state['work_order_id']=order['work_order_id'];save()
        wid=state['work_order_id']
        def order():return call(c,'读取工单状态','GET',f'/api/work-orders/{wid}/flow')['record']
        current=order()
        if current['status']=='草稿·待排程':
            comparison=call(c,'只读方案比较','GET','/api/strategies/compare?scenario_id=VAL-BASE');assert len(comparison['strategies'])==3
            comparison=call(c,'保存方案快照','POST','/api/strategies/compare',{'scenario_id':'VAL-BASE'})
            plan=next(p for p in comparison['strategies'] if p['strategy']=='optimized')
            call(c,'导出方案CSV','GET','/api/export/maintenance.csv?plan_id='+plan['plan_id'])
            scheduled=call(c,'联合约束排程','POST','/api/schedule/generate',{'scenario_id':'VAL-BASE','request_id':'qa-schedule-001'})
            assert any(item['work_order_id']==wid for item in scheduled['scheduled'])
            repeat=call(c,'重复排程不重复写入','POST','/api/schedule/generate',{'scenario_id':'VAL-BASE','request_id':'qa-schedule-001'});assert repeat==scheduled
            state['schedule']=scheduled;save()
        current=order()
        if current['status']=='待审批':
            preview={'version':current['version'],'staff_ids':current.get('staff_ids') or [current['staff_id']],'start_at':current['start_at'],'end_at':current['end_at'],'scenario_id':'VAL-BASE','note':'独立D1时间轴预览','request_id':'qa-timeline-preview-001','apply':False}
            call(c,'时间轴修改预览','POST',f'/api/work-orders/{wid}/timeline',preview)
            call(c,'审批批准','POST',f'/api/work-orders/{wid}/approval',{'decision':'approve','approver':'隔离验收','note':'模拟经营条件已核对','accept_assumptions':True,'version':current['version'],'request_id':'qa-approval-001'})
        stock=call(c,'执行前库存','GET','/api/resources/inventory')['records']
        state.setdefault('stock_before_execution',stock);save()
        target_actions={'已批准':['accept','start','pause','resume','finish','verify'],'已接单':['start','pause','resume','finish','verify'],'执行中':['pause','resume','finish','verify'],'已暂停':['resume','finish','verify'],'待验收':['verify'],'已完成':[]}
        for action in target_actions[order()['status']]:
            current=order();payload={'action':action,'actor':'隔离验收','note':'独立D1全流程模拟验收','version':current['version'],'request_id':'qa-transition-'+action+'-001'}
            if action=='finish':payload.update(actual_hours=current['hours'],actual_cost_cny=current['cost'])
            if action=='verify':payload['actual_parts']=[{'part_name':p['part_name'],'quantity':p['quantity']} for p in current.get('spare_parts',[])]
            result=call(c,'工单流转'+action,'POST',f'/api/work-orders/{wid}/transition',payload)
            if action=='accept':assert call(c,'接单幂等回读','POST',f'/api/work-orders/{wid}/transition',payload)==result
        assert order()['status']=='已完成'
        stock=call(c,'验收后库存','GET','/api/resources/inventory')['records']
        before={p['part_name']:p for p in state['stock_before_execution']}
        for part in order().get('spare_parts',[]):
            after=next(p for p in stock if p['part_name']==part['part_name']);assert after['on_hand']==before[part['part_name']]['on_hand']-part['quantity']
        history=call(c,'维修履历回写','GET','/api/equipment/VAL-CNC-001/history');assert any(p.get('work_order_id')==wid or p.get('maintenance_id')=='EXEC-'+wid for p in history['maintenance'])
        for action in ['archive','restore']:
            current=order();call(c,'工单'+action,'POST',f'/api/work-orders/{wid}/manage',{'action':action,'version':current['version'],'request_id':'qa-manage-'+action+'-001','note':'独立D1回收站验收'})
        report.setdefault('phases',{})['workflow_core']='passed';save()
    if args.phase in {'workflow','agent'}:
        harness=call(c,'助手会话创建','POST','/api/copilot/sessions',{'task':'查看高风险设备','success_criteria':'只读设备证据','tools':['equipment']});sid=harness['session_id']
        memory=call(c,'助手记忆保存','POST',f'/api/copilot/sessions/{sid}/memories',{'text':'这是临时隔离验收偏好','consent':True})
        call(c,'助手会话回读','GET',f'/api/copilot/sessions/{sid}')
        call(c,'助手记忆删除','POST',f'/api/copilot/sessions/{sid}/memories/{memory["memory_id"]}/forget')
        call(c,'助手无密钥查询降级','POST',f'/api/copilot/sessions/{sid}/chat',{'question':'查看高风险设备'})
        call(c,'助手范围约束','POST','/api/copilot/chat',{'question':'推荐一道晚餐菜谱'})
    elif args.phase=='accounts':
        names={'admin':-1,'user':1,'viewer':-1};credentials={}
        existing=call(c,'账号列表','GET','/api/auth/users')['records']
        for role,staff in names.items():
            filename=PRIVATE/(role+'-credentials.json')
            if filename.exists():account=json.loads(filename.read_text())
            else:
                password=secrets.token_urlsafe(30);name='隔离验收-'+role
                result=call(c,'创建'+role,'POST','/api/auth/users',{'display_name':name,'role':role,'staff_id':staff,'password':password})
                account={'user_id':result['user_id'],'password':password};filename.write_text(json.dumps(account),encoding='utf-8')
            credentials[role]=account
            other=client();login(other,account)
            call(other,role+'读取设备','GET','/api/overview')
            call(other,role+'禁止管理账号','GET','/api/auth/users',expected=403)
            if role in ['viewer','user']:
                call(other,role+'禁止创建需求','POST','/api/maintenance-requests',{'equipment_id':'VAL-CNC-002','action':'不得写入','priority':'中','request_id':'qa-denied-'+role},403)
                call(other,role+'禁止修改账号名称','POST','/api/auth/profile',{'username':account['user_id'],'display_name':'不得写入','version':1},403)
            if role=='admin':
                call(other,'管理员修改自身名称','POST','/api/auth/profile',{'username':account['user_id'],'display_name':'隔离验收管理员改名','version':1})
            call(other,role+'退出','POST','/api/auth/logout')
        viewer=client();login(viewer,credentials['viewer'])
        account=next(u for u in call(c,'最新账号版本','GET','/api/auth/users')['records'] if str(u['user_id'])==credentials['viewer']['user_id'])
        call(c,'停用临时只读账号','POST','/api/auth/users/'+str(account['user_id']),{'display_name':account['display_name'],'role':'viewer','staff_id':-1,'active':False,'version':account['version']})
        call(viewer,'停用立即撤销会话','GET','/api/overview',expected=401)
        account=next(u for u in call(c,'停用后账号版本','GET','/api/auth/users')['records'] if str(u['user_id'])==credentials['viewer']['user_id'])
        call(c,'恢复临时只读账号','POST','/api/auth/users/'+str(account['user_id']),{'display_name':account['display_name'],'role':'viewer','staff_id':-1,'active':True,'version':account['version']})
        normal=client();login(normal,credentials['user']);new_password=secrets.token_urlsafe(30)
        call(normal,'修改自身密码','POST','/api/auth/password',{'current_password':credentials['user']['password'],'new_password':new_password})
        credentials['user']['password']=new_password;(PRIVATE/'user-credentials.json').write_text(json.dumps(credentials['user']),encoding='utf-8')
        login(normal,credentials['user'])
    elif args.phase=='imports':
        old_version=call(c,'导入前版本','GET','/api/sync/status')['last_sync_at']
        state['import_restore_target']=old_version;save()
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=['equipment_id','timestamp','vibration_mm_s','motor_current_a','failure']);writer.writeheader()
        for index in range(100):writer.writerow({'equipment_id':'QA-IMPORT-001','timestamp':(datetime(2026,10,1)+timedelta(hours=index)).isoformat(sep=' '),'vibration_mm_s':1+index/100,'motor_current_a':8,'failure':int(70<=index<=72)})
        analyzed=call(c,'CSV分析','POST','/api/import/intelligent/analyze',files={'file':('isolated-acceptance.csv',output.getvalue().encode())})
        upload=analyzed.get('upload_id') or analyzed.get('session_id')
        assert upload,sorted(analyzed)
        preview=call(c,'D1导入预览','POST','/api/import/intelligent/preview',{'upload_id':upload,'mapping':[{'source_column':key,'target_field':key} for key in writer.fieldnames],'profile_id':'generic'})
        job=preview.get('job_id');assert job,preview
        for attempt in range(120):
            status=call(c,'导入任务轮询','GET','/api/import/jobs/'+job)
            if status['status'] not in ['queued','validating']:break
            time.sleep(1)
        assert status['status']=='ready',status
        call(c,'提交前原数据仍可用','GET','/api/data-quality')
        call(c,'提交D1导入','POST','/api/import/jobs/'+job+'/commit',{'replace_existing':True,'expected_dataset_version':old_version})
        quality=call(c,'导入后数据质量','GET','/api/data-quality');assert quality['reading_count']==100
        versions=call(c,'历史数据归档','GET','/api/data/versions');assert any(v['version']==old_version for v in versions['records'])
        call(c,'恢复原测试集','POST','/api/data/versions/'+quote(old_version,safe='')+'/restore',{'confirmed':True,'expected_dataset_version':versions['current_version']})
        quality=call(c,'恢复后完整性','GET','/api/data-quality');assert quality['reading_count']==expected_readings
    elif args.phase=='restore':
        old_version=state.get('import_restore_target') or subset['activated_at']
        versions=call(c,'恢复前刷新版本','GET','/api/data/versions')
        assert any(v['version']==old_version for v in versions['records'])
        call(c,'仅复验恢复原测试集','POST','/api/data/versions/'+quote(old_version,safe='')+'/restore',{'confirmed':True,'expected_dataset_version':versions['current_version']})
        quality=call(c,'恢复后完整性','GET','/api/data-quality');assert quality['reading_count']==expected_readings
    report.setdefault('phases',{})[args.phase]='passed';save()
    print('PHASE PASSED: '+args.phase,flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        report['last_failure']={'type':type(error).__name__,'detail':str(error)[:900]};save();raise
