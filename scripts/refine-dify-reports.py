"""Refine the user-imported loop-scope package without editing roster packages."""
from pathlib import Path
import copy,hashlib,json,re,zipfile
import yaml
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'outputs/dify-deployed-optimized/FactoryPulseAgent.loop-scope-fixed.ifpkg'
OUT=ROOT/'outputs/dify-report-refined';OUT.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(SOURCE) as z:
    infos=z.infolist();files={name:z.read(name) for name in z.namelist()}
raw=files['app.yaml'].decode();original=yaml.safe_load(raw);app=copy.deepcopy(original)
nodes={n['id']:n['data'] for n in app['workflow']['graph']['nodes']}
Q='{{#1792985116196.text#}}'
BOUNDARY='仅基于实际工具回执及已传入证据，分清事实、推断和建议。查询未成功不等于设备不存在或无数据；结构存在不等于取得业务值。未查明不得宣称SQL正确、字段正确、全部设备已覆盖或没有冲突。风险分不等于概率，模拟数据不代表现场收益。不得输出思考、编造来源或执行未授权写入。'
def task(id,body):
    text='用户原始任务：'+Q+'\n'+BOUNDARY+'\n'+body
    nodes[id]['agent_task']=text;nodes[id]['agent_job']['workflow_prompt']=text

task('17928149159620','只规划一次，不查询或执行。沿用已有任务JSON，最多3项：收集必要证据、形成建议、核对交付。明确区分A检查优先级建议、B资源条件核对、C可执行排程：A有足够且可比证据即可给出待人工确认建议，不依赖求解器；B缺项只阻塞对应条件；C需完整约束及实际求解/校验结果。用户只要建议时不得强加C为整体完成条件。预算不足或工具缺失按受影响子任务说明，保留其他可完成项。建议300字以内。')
task('1792815085722','计划：{{#17928149159620.text#}}\n仅简短分派，不查数据，不重写计划。Research唯一负责本轮业务取证；Analysis复用证据形成A优先级建议与B条件核对；Execute仅判断用户是否确实要求C正式可执行排程及当前工具可用性。不因无求解器阻塞A。沿用现有输出契约，建议180字以内。')
task('1792725277937','分派：{{#1792815085722.text#}}\n你是本轮唯一业务取证者。优先使用当前指南和已有有效证据，不例行查询sqlite_master；结构确有不明时，只查询相关表/视图的定义，不全库枚举、不COUNT全库。\n先取目标设备及其风险来源/版本/采样时间的必要字段，只在设备和时间范围内查询。然后按需分组取：匹配技能的人员与班次、相关设备和时间段的占用/工单、所需备件库存/预留。没有查到技能或备件名称时不拉取全人员/全库存。不得为减少请求把多类一对多明细强行JOIN，避免结果膨胀；选择必要字段、聚合和有界分页，不SELECT *或拉取全量监测记录。\n先判断每次查询是否会影响用户决策。目标通常2至4次有界业务查询，加至多1次必要结构核对；这是提示词预算而非工具硬限制。不能保证少量SQL调用就减少rows_read，未经执行统计不得宣称读取优化达标。\n若返回明确配额阻断（如7500），本轮立即停止后续业务查询，不重试、不换SQL探测，不因尚余调用预算继续调用；报告“本次查询被配额阻断，SQL/字段正确性未完成验证”。429/网络错误不擅自解释成账号每日配额。\n输出紧凑证据包，按A优先级、B资源核对、C排程分别标明已取得和缺项；保留来源、数据时间、范围/覆盖及实际错误回执。无数据时不罗列几十项未取得字段，建议600字以内。')
task('1792725230780','分派：{{#1792815085722.text#}}\n不查业务库、不重建算法。本轮若用户只需优先级和安排建议，明确“无需调用排程求解，Analysis可基于证据给待确认建议”。只有用户要求经资源约束验证的人员/起止时间或正式排程时，才核对已注册计算工具可用性；没有实际调用成功回执则说“未取得求解结果”，不要断言系统绝无求解能力。不执行业务流转。输出100字以内。')
task('1792725290444','证据：{{#1792725277937.text#}}\n计算条件：{{#1792725230780.text#}}\n不查询、不重试，复用证据。A优先级：设备风险来源/版本/时间可比且证据足够时，可给待人工确认的先后建议，说明依据；分数缺失或不可比时暂不排序。无求解器本身不阻塞此项。B条件：只对取得的数据判断，未取得只能说未核对。C排程：仅在用户要求且约束完整、实际计算/校验成功时报告可执行安排；否则将所述时间或方案明确标为建议/待验证。不要把建议包装成可行解。按子任务列已完成及具体限制，不把部分数据缺失扩大为所有工作失败。避免根因绝对化，证据不够说“目前不能确认”。建议400字以内。')
task('1792725312027','证据：{{#1792725277937.text#}}\n计算条件：{{#1792725230780.text#}}\n分析：{{#1792725290444.text#}}\n审查一次，不补查。按用户实际要求验收A/B/C，不为建议任务强加求解器门槛；有部分可靠产物则partial，必要证据全无则blocked。错误回执只支持该次请求的阻断原因，不证明SQL/字段/全部环境均正确。检查覆盖、日期、来源和“未核对≠无冲突”。要求删除超证据结论；不清楚的保留限制，不通过再查询来返工。输出简短审查结论、需删改点及实际完成项，不输出推理。')
task('17928150494110','证据：{{#1792725277937.text#}}\n分析：{{#1792725290444.text#}}\n审查：{{#1792725312027.text#}}\n本轮必须交付结果或阻塞说明，不输出空值/null。遵守现有JSON契约时把用户正文放report_text，其余为内部字段。report_text目标200至350字，复杂结果确有必要可至500字；不得机械截断关键证据，用户明确要求详细时以用户要求为准。\n正文只保留4段：①结果：完成/部分完成/暂无法判断，一句说明。②依据：最多3条关键事实及来源/数据时间；失败时最多引用一次错误及其限制。③建议：只写证据支持的待确认优先级或下一步；区分需要求解的正式排程。④未完成：合并缺项及原因，最多3项。全文不重复陈述“未取得”。省略空段落，不展示T1/T3、decision、continue、JSON键、逐Agent发言或合规口号。\n配额失败例：“本次业务查询被配额限制阻断，尚无法比较两台设备或核对资源；SQL及字段正确性也未完成验证。恢复可用额度后先按目标设备查询风险与时间，再按需查询相关资源。当前不提供设备排序或可执行排程。”仅在本轮回执确实支持时采用此口径，不写固定重置时间、升级建议或无依据的根因。')

# Also apply read discipline to the non-loop read-only branch, retaining its
# own original upstream refs and scope. No account/tool/package fields change.
d=nodes['1792937331505'];suffix='\n读取控制：先限定设备与时间，按需取必要字段和聚合结果，不例行全库结构检查、不SELECT *、不一次JOIN全部一对多资源。明确配额错误后停止本轮查询，不重试或换SQL探测。查询失败不证明SQL/字段正确或错误；按回执说明当前限制。优先级建议不强制依赖排程求解器；可执行排程另需完整约束及计算/校验证据。'
d['agent_task']+=suffix;d['agent_job']['workflow_prompt']=d['agent_task']

assert app['agent_packages']==original['agent_packages']
assert app['workflow']['graph']['edges']==original['workflow']['graph']['edges']
prefix=raw.split('\napp:',1)[0]
files['app.yaml']=(prefix+'\n'+yaml.safe_dump({k:v for k,v in app.items() if k!='agent_packages'},allow_unicode=True,sort_keys=False,width=110)).encode()
assert yaml.safe_load(files['app.yaml'])==app
manifest=yaml.safe_load(files['manifest.yaml'])
for item in manifest['apps']:
    content=files[item['path']];item['size']=len(content);item['sha256']=hashlib.sha256(content).hexdigest()
files['manifest.yaml']=yaml.safe_dump(manifest,allow_unicode=True,sort_keys=False).encode()

incoming={id:set() for id in nodes}
for e in app['workflow']['graph']['edges']:incoming[e['target']].add(e['source'])
def upstream(id,seen=None):
    seen=set() if seen is None else seen
    for parent in incoming[id]:
        if parent not in seen:seen.add(parent);upstream(parent,seen)
    return seen
for id,d in nodes.items():
    if d.get('type')!='agent':continue
    assert d['agent_task']==d['agent_job']['workflow_prompt']
    if d.get('isInLoop'):
        refs=set(re.findall(r'\{\{#(\d+)\.([^#]+)#\}\}',d['agent_task']))
        declared={(r['node_id'],r['output']) for r in d['agent_job']['previous_node_output_refs']}
        assert refs==declared,(id,refs-declared,declared-refs)
        for target,field in refs:
            assert target in upstream(id) and nodes[target].get('loop_id')==d['loop_id'],(id,target)
assert '7500' in nodes['1792725277937']['agent_task']
assert '不证明SQL' in nodes['1792725312027']['agent_task']
assert '无求解器本身不阻塞' in nodes['1792725290444']['agent_task']
out=OUT/'FactoryPulseAgent.concise-evidence.ifpkg'
with zipfile.ZipFile(out,'w') as z:
    for info in infos:z.writestr(info,files[info.filename])
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    assert z.read('app.yaml').decode().split('\napp:',1)[0]==prefix
    for item in manifest['apps']+sum([r.get('files',[]) for r in manifest['agent_resources'].values()],[]):
        content=z.read(item['path']);assert len(content)==item['size'];assert hashlib.sha256(content).hexdigest()==item['sha256']
report={'baseline':SOURCE.name,'baseline_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'agent_packages_raw_unchanged':True,'graph_edges_unchanged':True,'loop_scope_and_upstream_refs':'passed','manifest_hashes':'passed','task_contracts':'passed','live_import_tested':False,'live_model_tested':False,'query_budget_enforced_by_runtime':False,'report_length_enforced_by_runtime':False}
(OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
for id in ['1792725277937','1792725290444','17928150494110']:(OUT/(nodes[id]['title'].replace(' ','_')+'.txt')).write_text(nodes[id]['agent_task'],encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
