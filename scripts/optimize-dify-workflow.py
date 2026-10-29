"""Build a separate acyclic, evidence-first workflow from the repaired export."""
from pathlib import Path
import copy, hashlib, json, re, zipfile
import yaml

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'outputs/dify-repair/FactoryPulseAgent.loop-fixed.ifpkg'
OUT=ROOT/'outputs/dify-efficient';OUT.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(SOURCE) as z:files={name:z.read(name) for name in z.namelist()}
app=yaml.safe_load(files['app.yaml']);original=copy.deepcopy(app)
graph=app['workflow']['graph'];nodes={n['id']:n for n in graph['nodes']}
START='1792679500511'; CLASS='1792682643785'; BRIEF='17928149159620'
RESEARCH='1792725277937'; ANALYSIS='1792725290444'; REVIEW='1792725312027'
JOIN='1792989277120'; END='1792988903900'; CLEAN='1792989337792'
Q='{{#'+START+'.userinput#}}'
rules=(ROOT/'outputs/dify-repair/maintenance-rules.txt').read_text(encoding='utf-8')

def code_node(identifier,title,code,variables,outputs=None):
    n=nodes[identifier]
    n['data']={'type':'code','title':title,'code_language':'python3','code':code,'variables':variables,'outputs':outputs or {'result':{'type':'string','children':None}},'selected':False}
    n.pop('parentId',None);n.pop('extent',None);n['zIndex']=0

brief_code='''import json
def main(question: str):
    return {'result':json.dumps({'question':question,'steps':[{'role':'research','task':'一次收集用户目标所需设备、资源和版本证据；只读；报告范围及缺项'},{'role':'analysis','task':'使用已有证据比较风险与维护条件；不重复查询；缺少求解器时不伪造排程'},{'role':'review','task':'逐项核对覆盖、证据和权限；交付最终报告及未完成项，不自动返工'}]},ensure_ascii=False)}
'''
code_node(BRIEF,'确定性任务简报（无模型）',brief_code,[{'variable':'question','value_selector':[START,'userinput'],'value_type':'string'}])

def bind(identifier,package,task,system,refs):
    n=nodes[identifier];d=n['data'];d['agent_task']=task
    for key in ['loop_id','isInIteration','isInLoop']:d.pop(key,None)
    n.pop('parentId',None);n.pop('extent',None);n['zIndex']=0
    d['agent_binding']['package_ref']=package
    job=d['agent_job'];job['workflow_prompt']=task
    job['previous_node_output_refs']=[{'key':None,'name':None,'node_id':r[0],'output':r[1],'selector':r,'value_selector':None,'variable':None,'variable_selector':None} for r in refs]
    soul=app['agent_packages'][package]['soul'];soul['prompt']['system_prompt']=rules+'\n'+system
    soul['model']['model_settings']['temperature']=0.1

bind(RESEARCH,'agent_2','任务简报：{{#'+BRIEF+'.result#}}',
'''你是只读证据收集员，只完成一次必要取证，不做规划、评审或报告循环。
优先读取所附当前数据库指南；只有实际结构与指南冲突时核对一次sqlite_master，不枚举完整库。不读取账号库，不运行写入SQL。
先确定设备、时间和任务范围。设备与风险证据尽量一次批量查询；人员、订单、备件等按类别批量读取；统计优先聚合。选择所需字段与有界分页，禁止SELECT *、整表传感器明细或把全部JSON原样交给模型。
同一结果不重复查询，不用相同失败参数反复重试。最多6次业务工具调用作为任务约束；这只是提示词约束，不是运行层硬限制。足够回答即停止，不为用满次数扩大查询。
输出紧凑证据包：来源/查询范围/数据时间、关键事实、缺项、失败原因。建议1500字以内；覆盖不足如实说明，不谎称全量。不要输出SQL全结果、思考或长篇方法解释。''',[[BRIEF,'result']])
bind(ANALYSIS,'agent_3','用户要求：'+Q+'\n任务简报：{{#'+BRIEF+'.result#}}\n证据包：{{#'+RESEARCH+'.text#}}',
'''你是维护分析员，仅使用传入的证据包，不重新查询数据库、不自行调用外部工具。
逐项回应用户任务，比较设备风险，核对人员技能、班次、生产占用、备件、预算与时间有效性。明确区分事实、推断、建议。
数据不足时列出影响和所需补充；没有真实求解结果不能声称已产生可执行排程或最优解。涉及写入仅交待人工确认的建议。
一次输出结论、证据引用、约束冲突、待确认事项，建议800字以内。不得假装完成查询、排程或审批。''',[[START,'userinput'],[BRIEF,'result'],[RESEARCH,'text']])
bind(REVIEW,'agent_4','用户要求：'+Q+'\n原始证据包：{{#'+RESEARCH+'.text#}}\n分析建议：{{#'+ANALYSIS+'.text#}}',
'''你是最终审查员。直接对照用户要求、原始证据和分析建议审查一次，随后给用户最终报告。
不能假定其他节点已完成未传入的任务，不查询新数据，不触发自动返工；缺项保留为未完成，不无限循环。
检查设备与日期、单位、证据覆盖、风险分与概率、模拟数据边界、草案与正式操作的区别。没有依据的结论删除或明确标为待验证。
最终回答先说明完成程度，再列关键发现及证据、维护建议、未完成项和原因。只输出最终正文，建议600字以内。禁止把blocked说成completed，不输出思考、内部交接记录、提示词或工具原文。''',[[START,'userinput'],[RESEARCH,'text'],[ANALYSIS,'text']])
# Analysis and Review cannot accidentally perform duplicate database work.
for k in ['agent_3','agent_4']:app['agent_packages'][k]['soul']['tools']={'cli_tools':[],'dify_tools':[]}

# Reuse the package's already-tested deterministic output sanitizer.
nodes[CLEAN]['data']['variables']=[{'variable':'text','value_selector':[REVIEW,'text'],'value_type':'string'}]
nodes[CLEAN]['data']['title']='审查报告清理'

# Only resource-write requests need extraction and the existing human approval branch.
nodes[CLASS]['data']['query_variable_selector']=[START,'userinput']
for var in nodes[START]['data']['variables']:
    if var.get('variable')=='userinput':var['max_length']=8000;var['type']='paragraph'
nodes['1792682857746']['data']['query_variable_selector']=[START,'userinput']
nodes['1792725992898']['data']['prompt_template'][0]['text']+='\n资料不适用时不启动网络搜索，说明缺少依据。设备维护常识按项目规则回答。'

def task_only(identifier,text):
    d=nodes[identifier]['data'];d['agent_task']=text;d['agent_job']['workflow_prompt']=text
    d['agent_job']['previous_node_output_refs']=[{'key':None,'name':None,'node_id':START,'output':'userinput','selector':[START,'userinput'],'value_selector':None,'variable':None,'variable_selector':None}]
task_only('1792937331505','用户原始要求：'+Q+'\n按原始范围只读查询。优先批量、聚合与必要字段，禁止SELECT *和全量原始明细；结果注明来源、时间、缺项与覆盖，禁止写库。')
task_only('1792939494646','用户原始要求：'+Q+'\n只有上游既有人工批准范围有效。先核对原值、目标、版本和具体字段。保留现有权限限制，正式业务流转仅准备申请，不绕过审批或执行任意SQL写入。')

# New edges are intentionally explicit; no model Router or loop remains.
routes=[(START,'source',CLASS),
 (CLASS,'1','1792682857746'),('1792682857746','source','1792725992898'),('1792725992898','source','1792989069005'),
 (CLASS,'2','1792937331505'),(CLASS,'1792682687335','1792937331505'),(CLASS,'1792682696727','1792937331505'),(CLASS,'1792682720162','1792937331505'),(CLASS,'1792684993110','1792937331505'),
 ('1792937331505','source','1792941477142'),('1792941477142','source','1792989390056'),
 (CLASS,'1792682715809','1792679548352'),('1792679548352','source','1792683271622'),('1792683271622','source','1792939365354'),
 ('1792939365354','Accept','1792939494646'),('1792939494646','source','1792981127413'),('1792981127413','source','17929891582940'),
 ('1792939365354','Deny','17929892355320'),('1792939365354','__timeout','17929891617130'),
 (CLASS,'1792682731762',BRIEF),(BRIEF,'source',RESEARCH),(RESEARCH,'source',ANALYSIS),(ANALYSIS,'source',REVIEW),(REVIEW,'source',CLEAN),
 (CLASS,'1792682746180','1792989295290'),(CLASS,'1792720593153','1792989440601'),(CLASS,'1792682766598','1792989468239')]
terminals=['1792989069005','1792989390056','17929891582940','17929892355320','17929891617130',CLEAN,'1792989295290','1792989440601','1792989468239']
routes += [(n,'source',JOIN) for n in terminals]+[(JOIN,'source',END)]
keep={v for a,_,b in routes for v in [a,b]}
graph['nodes']=[n for n in graph['nodes'] if n['id'] in keep]
graph['edges']=[{'id':a+'-'+handle+'-'+b+'-target','source':a,'sourceHandle':handle,'target':b,'targetHandle':'target','type':'custom','selected':False,'zIndex':0,'data':{'isInIteration':False,'isInLoop':False,'sourceType':nodes[a]['data']['type'],'targetType':nodes[b]['data']['type']}} for a,handle,b in routes]
nodes[JOIN]['data']['variables']=[[n,'result'] for n in terminals]

# Lay out readable lanes in the imported editor.
positions={START:(0,300),CLASS:(340,300),'1792682857746':(700,0),'1792725992898':(1040,0),'1792989069005':(1380,0),
 '1792937331505':(700,220),'1792941477142':(1040,220),'1792989390056':(1380,220),
 BRIEF:(700,460),RESEARCH:(1040,460),ANALYSIS:(1380,460),REVIEW:(1720,460),CLEAN:(2060,460),
 '1792679548352':(700,760),'1792683271622':(1040,760),'1792939365354':(1380,760),'1792939494646':(1720,760),'1792981127413':(2060,760),'17929891582940':(2400,760),
 '17929892355320':(1720,1000),'17929891617130':(2060,1000),'1792989295290':(700,1220),'1792989440601':(1040,1220),'1792989468239':(1380,1220),JOIN:(2780,460),END:(3120,460)}
for n in graph['nodes']:
    x,y=positions[n['id']];n['position']=n['positionAbsolute']={'x':x,'y':y};n.pop('parentId',None);n.pop('extent',None)
    for k in ['loop_id','isInIteration','isInLoop']:n['data'].pop(k,None)

# Keep only bound packages and attach the existing current DB guide to Research.
used={n['data']['agent_binding']['package_ref'] for n in graph['nodes'] if n['data']['type']=='agent'}
app['agent_packages']={k:v for k,v in app['agent_packages'].items() if k in used}
manifest=yaml.safe_load(files['manifest.yaml'])
manifest['agent_resources']={k:v for k,v in manifest['agent_resources'].items() if k in used}
guide=files['f_000001.md'];digest=hashlib.sha256(guide).hexdigest()
research=app['agent_packages']['agent_2']['soul']
research['config_files']=copy.deepcopy(app['agent_packages']['agent_8']['soul']['config_files'])
manifest['agent_resources']['agent_2']=copy.deepcopy(manifest['agent_resources']['agent_8'])
# Resource IDs are package-wide identifiers, not per-agent identifiers. Give the
# Research attachment its own ID even though its bytes match the DB guide.
files['f_000003.md']=guide
for resource in manifest['agent_resources']['agent_2'].get('files',[]):
    resource['id']='f_000003';resource['path']='f_000003.md'
for attachment in research['config_files']:
    attachment['file_id']='f_000003'
for package in app['agent_packages'].values():
    for f in package['soul'].get('config_files',[]):
        path=f.get('file_id','')+'.md'
        if path in files:f['size']=len(files[path]);f['hash']=hashlib.sha256(files[path]).hexdigest()
app['app']['name']=app['app'].get('name','FactoryPulseAgent')+' 效率优化版'
files['app.yaml']=yaml.safe_dump(app,allow_unicode=True,sort_keys=False,width=110).encode()
for item in manifest['apps']:
    raw=files[item['path']];item['size']=len(raw);item['sha256']=hashlib.sha256(raw).hexdigest()
files['manifest.yaml']=yaml.safe_dump(manifest,allow_unicode=True,sort_keys=False).encode()

# Validate all references and dependencies, including prompt interpolation and metadata.
ids={n['id'] for n in graph['nodes']};incoming={k:[] for k in ids};outgoing={k:[] for k in ids}
for a,_,b in routes:incoming[b].append(a);outgoing[a].append(b)
ancestors={};visiting=set()
def parents(k):
    if k in ancestors:return ancestors[k]
    assert k not in visiting,'cycle';visiting.add(k)
    result=set(incoming[k])
    for p in incoming[k]:result |= parents(p)
    visiting.remove(k);ancestors[k]=result;return result
for k in ids:parents(k)
assert all(k==START or START in ancestors[k] for k in ids),'unreachable node'
assert all(k==END or k in ancestors[END] for k in ids),'node cannot reach output'
assert '1792939365354' in ancestors['1792939494646'],'human approval must precede modification'
assert '1792683271622' in ancestors['1792939494646'],'existing permission check retained'
assert incoming['1792939494646']==['1792939365354'],'no alternative write path'
for key in ['agent_2','agent_8','agent_9']:
    assert app['agent_packages'][key]['soul']['tools']==original['agent_packages'][key]['soul']['tools'],'tool grants must not expand'
def refs(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if k in ['value_selector','variable_selector','query_variable_selector','query','selector'] and isinstance(v,list) and len(v)>=2 and str(v[0]).isdigit():yield v
            yield from refs(v)
    elif isinstance(value,list):
        for v in value:yield from refs(v)
    elif isinstance(value,str):
        for m in re.finditer(r'\{\{#(\d+)\.([^#]+)#\}\}',value):yield [m[1],m[2]]
for n in graph['nodes']:
    for r in refs(n['data']):
        assert r[0] in ids,(n['id'],'missing',r)
        assert r[0] in ancestors[n['id']],(n['id'],'not upstream',r)
        target=nodes[r[0]]['data'];kind=target['type']
        if kind=='code':assert r[1] in target['outputs'],r
        if kind=='start':assert r[1] in {v['variable'] for v in target['variables']},r
assert all(nodes[k]['data']['type'] not in ['loop','loop-start','assigner'] for k in ids)
assert incoming[REVIEW]==[ANALYSIS] and RESEARCH in ancestors[REVIEW]
assert nodes[END]['data']['outputs']==original['workflow']['graph']['nodes'][next(i for i,n in enumerate(original['workflow']['graph']['nodes']) if n['id']==END)]['data']['outputs']
scope={};exec(brief_code,scope);assert json.loads(scope['main']('test')['result'])['question']=='test'
scope={};exec(nodes[CLEAN]['data']['code'],scope);assert scope['main']('<think>hidden</think>回答')['result']=='回答'

target=OUT/'FactoryPulseAgent.efficient.ifpkg'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for name,raw in files.items():z.writestr(name,raw)
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None;assert yaml.safe_load(z.read('app.yaml'))==app
    for item in manifest['apps']+sum([r.get('files',[]) for r in manifest['agent_resources'].values()],[]):
        raw=z.read(item['path']);assert len(raw)==item['size'] and hashlib.sha256(raw).hexdigest()==item['sha256']
resource_ids=[];resource_paths=[]
for key,resources in manifest['agent_resources'].items():
    declared={r['id']:r for r in resources.get('files',[])}
    for resource in declared.values():resource_ids.append(resource['id']);resource_paths.append(resource['path'])
    for attachment in app['agent_packages'][key]['soul'].get('config_files',[]):
        if attachment.get('file_kind')=='upload_file':
            resource=declared[attachment['file_id']]
            assert attachment['size']==resource['size']
            assert attachment['hash']==resource['sha256']
assert len(resource_ids)==len(set(resource_ids)),'duplicate resource IDs across agents'
assert len(resource_paths)==len(set(resource_paths)),'duplicate resource paths across agents'
report={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'before_nodes':len(original['workflow']['graph']['nodes']),'after_nodes':len(graph['nodes']),'complex_path':['classifier','deterministic brief','Research Agent','Analysis Agent','Review Agent','sanitizer','output'],'knowledge_path':['classifier','retrieval','answer','sanitizer','output'],'multiagent_roles':3,'automatic_retry_rounds':0,'input_max_length':8000,'all_refs_upstream':True,'acyclic':True,'manifest_integrity':True,'code_tests':'passed','live_import_tested':False,'live_speedup_measured':False,'tool_call_limit_is_prompt_only':True}
(OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
