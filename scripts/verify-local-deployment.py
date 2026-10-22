"""Exercise Windows single-service scripts on a copy, with Python egress blocked.
Only API routes are requested. No browser, page rendering or layout inspection.
"""
import argparse,json,os,socket,sqlite3,subprocess,sys,time,uuid
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.build_artifact import validate_build

GUARD='''import socket,ipaddress,os
def local(host):
 if isinstance(host,bytes):host=host.decode()
 if host is None or host=='localhost':return True
 try:return ipaddress.ip_address(str(host).split('%')[0]).is_loopback
 except ValueError:return False
def blocked(kind):
 try:
  with open(os.environ['FACTORYPULSE_PROBE_NETWORK_LOG'],'a') as log:log.write(kind+'\\n')
 except OSError:pass
old_dns=socket.getaddrinfo
def dns(host,*args,**kwargs):
 if not local(host):
  blocked('dns');raise socket.gaierror(socket.EAI_NONAME,'isolated deployment probe blocks non-loopback DNS')
 return old_dns(host,*args,**kwargs)
socket.getaddrinfo=dns
for name in ('connect','connect_ex','sendto'):
 original=getattr(socket.socket,name)
 def guarded(self,*args,_original=original,_name=name,**kwargs):
  address=args[-1] if _name=='sendto' else args[0]
  if self.family in (socket.AF_INET,socket.AF_INET6) and isinstance(address,tuple) and not local(address[0]):
   blocked(_name);raise PermissionError('isolated deployment probe blocks non-loopback sockets')
  return _original(self,*args,**kwargs)
 setattr(socket.socket,name,guarded)
socket._factorypulse_probe_guard=True
'''

def exercise(database,output,username=None):
    if os.name!='nt':raise RuntimeError('本演练针对Windows启动和停止脚本')
    build=validate_build(ROOT/'dist')
    folder=output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    data=folder/'data';data.mkdir();database=database.resolve(strict=True);copied=data/'factorypulse.sqlite3'
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(copied)) as target:source.backup(target)
    with closing(sqlite3.connect(copied)) as connection:
        with connection:
            connection.execute('DELETE FROM auth_sessions')
            connection.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)',[('ai_base_url','https://factorypulse-probe.invalid/v1'),('ai_model','offline-probe')])
    control=folder/'control';control.mkdir();(control/'sitecustomize.py').write_text(GUARD,'utf-8')
    network_log=control/'blocked-network.log'
    env={**os.environ,'FACTORYPULSE_DATA_DIR':str(data),'FACTORYPULSE_AUTO_BACKUP':'0','FACTORYPULSE_AI_API_KEY':'synthetic-offline-probe-not-a-key',
         'FACTORYPULSE_PROBE_NETWORK_LOG':str(network_log),'PYTHONPATH':str(control)+os.pathsep+str(ROOT)}
    # Assert the guard is loaded before asking it to resolve even a synthetic name.
    proof=subprocess.run([sys.executable,'-c',"import socket;assert getattr(socket,'_factorypulse_probe_guard',False);\ntry:socket.getaddrinfo('factorypulse-probe.invalid',443)\nexcept socket.gaierror:print('blocked')\nelse:raise RuntimeError('network guard inactive')"],env=env,cwd=ROOT,capture_output=True,timeout=15)
    if proof.returncode or proof.stdout.strip()!=b'blocked':raise RuntimeError('网络隔离探针未启用，未启动服务')
    with socket.socket() as allocated:allocated.bind(('127.0.0.1',0));port=allocated.getsockname()[1]
    api=httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=30,trust_env=False)
    running=False;steps=[];result={'status':'failed','operator_database_not_executed':True,'copy_database':str(copied),'port':port,'build':build,
                                 'network_isolation':'Python DNS/TCP/UDP入口屏蔽非回环连接；非操作系统防火墙或物理断网验收','browser_or_layout_checked':False}
    def script(name):
        # Detached descendants can keep captured Windows pipes alive after PowerShell exits.
        with (folder/'launcher.log').open('ab') as log:
            response=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts'/name),'-Port',str(port)],env=env,cwd=ROOT,stdout=log,stderr=log,timeout=30)
        if response.returncode:raise RuntimeError(name+'失败，请查看隔离目录launcher.log')
    def request(method,path,body=None):
        if not path.startswith('/api/'):raise RuntimeError('探针禁止请求网页')
        response=api.request(method,path,json=body) if body is not None else api.request(method,path)
        if response.status_code!=200:raise RuntimeError(f'{path} 返回 {response.status_code}，请查看隔离服务日志')
        return response.json()
    def start():
        nonlocal running
        script('start-local.ps1');running=True
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                if api.get('/api/health').status_code==200:return
            except httpx.RequestError:pass
            time.sleep(.2)
        raise RuntimeError('隔离服务未按时就绪；未自动重启，请检查日志')
    def stop():
        nonlocal running
        if not running:return
        script('stop-local.ps1')
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:api.get('/api/health',timeout=.3)
            except httpx.RequestError:running=False;return
            time.sleep(.2)
        raise RuntimeError('停止脚本返回后隔离服务仍在运行，未启动第二个实例')
    try:
        start();steps.append('Windows单服务启动')
        if request('GET','/api/auth/status').get('required'):
            password=os.environ.get('FACTORYPULSE_VERIFY_PASSWORD')
            if not username or not password:raise RuntimeError('副本启用账号；请设置验证账号与FACTORYPULSE_VERIFY_PASSWORD后重新演练')
            request('POST','/api/auth/login',{'username':username,'password':password})
        request('GET','/api/health/ready');steps.append('数据库读写就绪')
        board=request('GET','/api/maintenance/timeline');version=board['dataset_version']
        active={item['equipment_id'] for item in board['work_orders'] if not item.get('deleted_at') and item['status'] not in {'已完成','已取消'}}
        target=next((item['equipment_id'] for item in board['equipment'] if item['equipment_id'] not in active),None)
        if not target or not board['scenarios']:raise RuntimeError('演练副本需有可创建需求的设备与完整排程条件')
        fast=request('POST','/api/copilot/chat',{'question':'本周哪些设备需要优先复核？'})
        if fast.get('mode')!='evidence_direct':raise RuntimeError('离线常用查询未使用本地证据')
        before=len(network_log.read_text().splitlines())
        unavailable=request('POST','/api/copilot/chat',{'question':f'请查询设备{target}的运行历史并解释维修风险'})
        if unavailable.get('mode')!='unavailable' or unavailable.get('proposals') or len(network_log.read_text().splitlines())<=before:raise RuntimeError('AI断网降级验证失败')
        if request('GET','/api/maintenance/timeline')['work_orders']!=board['work_orders']:raise RuntimeError('AI断网检查意外改变工单')
        steps.append('AI公网连接屏蔽、常用查询可用、复杂请求安全降级')
        draft=request('POST','/api/maintenance-requests',{'equipment_id':target,'action':'隔离离线演练，非真实维修','request_id':uuid.uuid4().hex})
        wid=draft['work_order_id'];sid=board['scenarios'][0]['scenario_id']
        request('GET','/api/strategies/compare?scenario_id='+sid)
        plan=request('POST','/api/schedule/generate',{'scenario_id':sid,'request_id':uuid.uuid4().hex})
        if not any(item['work_order_id']==wid for item in plan['scheduled']):raise RuntimeError('演练条件无法排程，未绕过约束')
        def order():return request('GET',f'/api/work-orders/{wid}/flow')['record']
        approval={'decision':'approve','approver':'离线隔离演练','note':'仅验证软件流程，非真实现场审批','accept_assumptions':True,'version':order()['version'],'request_id':uuid.uuid4().hex}
        receipt=request('POST',f'/api/work-orders/{wid}/approval',approval);steps.append('离线创建需求、比较、排程与审批')
        stop();start();steps.append('通过正式脚本停止并重新启动')
        if request('POST',f'/api/work-orders/{wid}/approval',approval)!=receipt:raise RuntimeError('重启后审批回执不一致')
        if order()['status']!='已批准':raise RuntimeError('重启后工单状态丢失')
        steps.append('重启后状态及审批回执恢复')
        for action in ['accept','start','pause','resume','finish','verify']:
            current=order();body={'action':action,'actor':'隔离演练人员','note':'隔离软件演练，非现场维修','version':current['version'],'request_id':uuid.uuid4().hex}
            if action=='finish':body.update(actual_hours=current['hours'],actual_cost_cny=current['cost'])
            if action=='verify':body['actual_parts']=[{'part_name':part['part_name'],'quantity':part['quantity']} for part in current.get('spare_parts',[])]
            request('POST',f'/api/work-orders/{wid}/transition',body);steps.append(action)
        if order()['status']!='已完成':raise RuntimeError('离线工单未完成')
        history=request('GET',f'/api/equipment/{target}/history')
        if not any(item.get('work_order_id')==wid for item in history['maintenance']):raise RuntimeError('维修履历未保存')
        steps.append('维修履历与库存落库');stop();steps.append('隔离服务已停止')
        result.update(status='isolated_local_deployment_passed',dataset_version=version,equipment_id=target,work_order_id=wid,steps=steps,
                      scope='本机现有运行环境下的Windows脚本、软件网络屏蔽、API闭环及重启持久化；不是干净电脑安装、网页、排版或真实人员验收')
    finally:
        try:stop()
        finally:
            api.close();result['steps']=steps;(folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return folder,result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True);parser.add_argument('--output',type=Path,default=ROOT/'outputs/local-deployment');parser.add_argument('--username');args=parser.parse_args()
    folder,result=exercise(args.database,args.output,args.username)
    print(json.dumps({'report':str(folder/'report.json'),'status':result['status'],'steps':len(result['steps'])},ensure_ascii=False))
