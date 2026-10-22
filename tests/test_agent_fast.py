from backend.agent_fast import quick_tool,evidence_answer
from tests.test_api import client

def test_exact_shortcuts_do_not_capture_complex_requests():
    assert quick_tool('模型评估结果可靠吗？')=='evaluation'
    assert quick_tool('本周哪些设备需要优先复核？')=='equipment'
    assert quick_tool('查询CNC-001的风险并起草检查需求') is None
    assert quick_tool('模型评估可靠吗？并且比较方案') is None

def test_direct_evaluation_preserves_missing_values_and_limits():
    result=evidence_answer('evaluation',{'source':'SQLite','data_time':'2020-07-01','evaluation':{'precision':.064,'recall':.251,'false_alarm_rate':.476,'independent_test_events':1}})
    assert all(text in result['answer'] for text in ['6.4%','25.1%','47.6%','1次','不是故障概率','2020-07-01'])
    assert result['mode']=='evidence_direct' and result['proposals']==[]
    assert '无法判断' in evidence_answer('evaluation',{})['answer']

def test_fast_endpoint_uses_no_language_model(monkeypatch):
    from backend import main
    async def forbidden(*args,**kwargs): raise AssertionError('常见事实查询不应等待模型')
    monkeypatch.setattr(main,'run_agent',forbidden)
    monkeypatch.setattr(main,'agent_dispatch',lambda *args:{'source':'SQLite','data_time':'2020-07-01','evaluation':{'independent_test_events':1}})
    result=client.post('/api/copilot/chat',json={'question':'模型评估结果可靠吗？'})
    assert result.status_code==200
    assert result.json()['mode']=='evidence_direct'

def test_device_answer_orders_real_scores_and_does_not_treat_missing_as_zero():
    result=evidence_answer('equipment',{'devices':[{'equipment_id':'unknown','risk_score':None},{'equipment_id':'E1','risk_score':.2},{'equipment_id':'E2','risk_score':.8}]})
    assert result['answer'].index('E2')<result['answer'].index('E1')
    assert 'unknown' not in result['answer']


def test_agent_reuses_identical_reads_and_reports_cost(monkeypatch):
    import asyncio
    from backend.agent import run_agent
    responses=[{'tool_calls':[{'id':'read1','function':{'name':'equipment','arguments':'{}'}},{'id':'read2','function':{'name':'equipment','arguments':'{}'}}]}, {'content':'当前证据不足，请复核设备。'}]
    class Response:
        status_code=200
        def __init__(self,message): self.message=message
        def json(self): return {'choices':[{'message':self.message}]}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return Response(responses.pop(0))
    monkeypatch.setattr('backend.agent.httpx.AsyncClient',Client)
    calls=[]
    def dispatch(*args): calls.append(args);return {'source':'SQLite','devices':[]}
    result=asyncio.run(run_agent('https://example.org','test','fake','查看设备风险',dispatch))
    assert len(calls)==1
    assert result['timing']['read_cache_hits']==1 and result['timing']['model_calls']==2
    assert result['timing']['total_ms']>=result['timing']['model_ms']
    assert result['trace'][0]['cached'] is False and result['trace'][1]['cached'] is True


def test_evaluation_dispatch_avoids_redundant_device_snapshot(monkeypatch):
    from backend import main
    def forbidden(): raise AssertionError('评估工具不能额外构建设备快照')
    monkeypatch.setattr(main,'snapshot',forbidden)
    monkeypatch.setattr(main,'model_evaluation',lambda:{'model_version':'m1','evaluation':{'test_end':'2020-08-25','precision':.064}})
    result=main.agent_dispatch('evaluation',{})
    assert result['model_version']=='m1' and result['data_time']=='2020-08-25'
    assert result['evaluation']['precision']==.064


def test_fast_comparison_preserves_costs_and_planning_limits():
    assert quick_tool('比较当前维护排程方案')=='compare_plans'
    evidence={'source':'SQLite','strategies':[{'strategy':'optimized','scenario':'演示情景','summary':{'task_count':2,'maintenance_cost':2400,'maintenance_hours':6}}]}
    result=evidence_answer('compare_plans',evidence)
    assert '2,400.0元' in result['answer'] and '6.0小时' in result['answer']
    assert '演示情景' in result['answer'] and '不能证明' in result['answer']
    assert result['proposals']==[]


def test_missing_comparison_resources_returns_actionable_reason(monkeypatch):
    from fastapi import HTTPException
    from backend import main
    def missing(*args): raise HTTPException(422,'请先配置真实维护工时和费用')
    monkeypatch.setattr(main,'agent_dispatch',missing)
    result=client.post('/api/copilot/chat',json={'question':'比较当前维护排程方案'})
    assert result.status_code==200
    assert '请先配置' in result.json()['answer']
    assert result.json()['proposals']==[]


def test_fast_comparison_passes_selected_scenario(monkeypatch):
    from backend import main
    calls=[]
    def read(name,arguments): calls.append((name,arguments));return {'strategies':[]}
    monkeypatch.setattr(main,'agent_dispatch',read)
    response=client.post('/api/copilot/chat',json={'question':'比较当前维护排程方案','scenario_id':'S-SELECTED'})
    assert response.status_code==200
    assert calls==[('compare_plans',{'scenario_id':'S-SELECTED'})]


def test_real_fast_queries_do_not_create_work_orders_or_agent_drafts():
    from tests.test_api import workbook
    from backend.main import connect
    imported=client.post('/api/import',files={'file':('test.xlsx',workbook(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert imported.status_code==200
    before=client.get('/api/work-orders').json()['records']
    with connect() as connection:
        before_drafts=connection.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'agent_proposal:%'").fetchone()[0]
    for question in ['本周哪些设备需要优先复核？','模型评估结果可靠吗？','比较当前维护排程方案']:
        response=client.post('/api/copilot/chat',json={'question':question,'scenario_id':'S-1'})
        assert response.status_code==200
        result=response.json()
        assert result['mode']=='evidence_direct',result
        assert result['proposals']==[] and result['trace'][0]['status']=='success'
    assert client.get('/api/work-orders').json()['records']==before
    with connect() as connection:
        after_drafts=connection.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'agent_proposal:%'").fetchone()[0]
    assert before_drafts==after_drafts


def test_model_timeout_keeps_successful_equipment_evidence(monkeypatch):
    import asyncio
    import httpx
    from backend.agent import run_agent
    calls=[]
    class Response:
        status_code=200
        def json(self): return {'choices':[{'message':{'tool_calls':[{'id':'read1','function':{'name':'equipment','arguments':'{}'}}]}}]}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs):
            calls.append(True)
            if len(calls)>1: raise httpx.ReadTimeout('模拟模型解释超时')
            return Response()
    monkeypatch.setattr('backend.agent.httpx.AsyncClient',Client)
    evidence={'source':'SQLite','data_time':'2020-07-01','devices':[{'equipment_id':'E1','risk_score':.2,'prediction_at':'2020-07-01'}]}
    result=asyncio.run(run_agent('https://example.org','test','fake','查询设备风险',lambda *args:evidence))
    assert result['completion_status']=='incomplete' and '超时' in result['answer']
    assert result['evidence']==evidence
    assert result['trace'][0]['status']=='success'
    assert result['proposals']==[]


def test_initial_model_timeout_has_no_invented_evidence(monkeypatch):
    import asyncio
    import httpx
    from backend.agent import run_agent
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): raise httpx.ReadTimeout('模拟超时')
    monkeypatch.setattr('backend.agent.httpx.AsyncClient',Client)
    def forbidden(*args): raise AssertionError('无模型工具请求时不能执行工具')
    result=asyncio.run(run_agent('https://example.org','test','fake','查询设备风险',forbidden))
    assert result['completion_status']=='incomplete'
    assert result['evidence'] is None and result['trace']==[] and result['proposals']==[]


def test_equipment_shortcut_uses_model_review_flag_not_display_bands():
    response=evidence_answer("equipment",{"devices":[{"equipment_id":"SUPPRESSED","risk_score":.8,"review_required":False},{"equipment_id":"REVIEW","risk_score":.1,"review_required":True}]})
    assert "REVIEW" in response["answer"] and "SUPPRESSED" not in response["answer"]
