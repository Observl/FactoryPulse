"""Keep roster schemas and resource bindings; revise reader policy and output mapping."""
from pathlib import Path
import copy, hashlib, json, re, zipfile
import yaml

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'outputs/dify-report-refined/FactoryPulseAgent.concise-evidence.ifpkg'
OUT=ROOT/'outputs/dify-query-output'; OUT.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(SOURCE) as z:
    infos=z.infolist(); files={n:z.read(n) for n in z.namelist()}
original=yaml.safe_load(files['app.yaml']); app=copy.deepcopy(original)
nodes={n['id']:n['data'] for n in app['workflow']['graph']['nodes']}
POLICY='''本轮数据库读取协议（替代旧指南中例行先查结构、默认检查全部设备/全部记录的要求）：
1. 当前部署按项目2026-10-27的V2指南选择查询模板；这是已知配置而非本轮在线验证。首个数据库调用必须是有设备范围的业务查询，不调用sqlite_master、不做全库版本/字段盘点、不验证Cloudflare token。只读查询自身回执足以判断该次请求是否成功。
2. 每次query仅一条只读SELECT（必要时WITH），禁止UNION/UNION ALL、按每字段生成一条SELECT再拼接、批量多语句、SELECT *、全库COUNT及拉取原始大JSON。使用必要列、目标设备IN筛选、适用的时间边界、明确LIMIT（默认20，资源明细最多50）。LIMIT只限制返回量，不保证视图底层扫描少，不宣称已节省rows_read，除非有实际统计。
3. 按当前任务串行取证并共享回执，不能为每个Agent重查。先查询设备风险、来源与时间；再按影响决策的缺项查询相关资源。读取足够就停。每轮最多4次query调用，包含报错及结构修复；这是Agent调用协议，非插件强制配额。不要为完成清单而扫描无关表。
4. 优先使用以下V2已知列，不臆造模型版本或SHAP字段：equipment(equipment_id,equipment_name,status,production_line,required_skill,data_origin)；v_current_model_scores(equipment_id,model_risk,trend_risk,priority_score,prediction_at)；v_equipment_latest_reading(equipment_id,timestamp)；v_equipment_rule_risk(equipment_id,rule_risk)；external_risk_inputs(equipment_id,risk_score,data_origin)；business_settings(key,value)。
5. 可选首查模板（仅替换为从用户任务提取并正确转义的设备编号；工具支持绑定时绑定参数，不直接执行用户提供的SQL）：SELECT e.equipment_id,e.status,e.required_skill,e.data_origin,m.model_risk,m.trend_risk,m.priority_score,m.prediction_at,l.timestamp AS latest_sample_at FROM equipment e LEFT JOIN v_current_model_scores m ON m.equipment_id=e.equipment_id LEFT JOIN v_equipment_latest_reading l ON l.equipment_id=e.equipment_id WHERE e.equipment_id IN ('目标编号1','目标编号2') LIMIT 20。视图可能有底层扫描成本，不保证索引下推。模型值为空时可按需再查目标设备的规则/外部来源，不混为同类模型分数；不能以规则参考冒充模型预测。
6. 资源按依赖查：maintenance_requirements/maintenance_required_parts按equipment_id筛选；maintenance_staff只取已知所需技能相关人员与班次；production_orders按设备及区间重叠筛选；工单用v_work_order_schedule按设备和时间筛选；库存用v_current_spare_part_availability按已知part_name筛选。不把人员、备件、订单和工单多类一对多数据拼成大JOIN。未知设备、技能、窗口或备件时保留缺项，不拉全库补猜。SHAP不是普通优先级建议的必需字段。
7. 仅当业务查询实际返回no such table/column等结构错误，允许一次针对该表的PRAGMA table_info或sqlite_master WHERE name='具体对象'查询（禁止IN批量枚举），修复后至多重试一次，并计入4次总预算。若预算不够，交付缺项。复用本轮取得的字段信息，禁止再次查相同结构。
8. 按错误正文分类，不能仅按7500分类：明确日读取配额耗尽/401无权限时停止后续全部数据库调用，不换SQL、不验证token；too many terms in compound SELECT属于SQL形态错误，只能拆成当前最必要的一条简单SELECT，不重复复合拼接；其他错误保留实际回执，不能宣称字段或SQL已经正确。无权限变化不要求用户重新授权。配额恢复后续跑沿用原授权范围。
9. 取证回执只保存关键行、来源、时间、覆盖与实际读取统计，不把全部原文/结构清单传下游。业务全无时写“结构检查完成/未执行，业务分析受阻”，不以结构成功冒充业务部分完成。'''

for node_id,pkg in [('1792725277937','agent_2'),('1792937331505','agent_8')]:
    d=nodes[node_id]
    # Keep scope, refs and fields untouched; policy first prevents old defaults winning.
    d['agent_task']=POLICY+'\n\n'+d['agent_task']
    d['agent_job']['workflow_prompt']=d['agent_task']
    soul=app['agent_packages'][pkg]['soul']
    soul['prompt']['system_prompt']+='\n\n'+POLICY
    for t in soul['tools']['dify_tools']:
        if t.get('tool_name')=='cloudflare_verify': t['enabled']=False
        if t.get('tool_name')=='query':
            t['description']='业务只读查询：单条有界SELECT，禁UNION、SELECT *、多语句及全库结构扫描；遵守本轮数据库读取协议。错误正文明确配额耗尽或权限不足即停止。'

REPORT_RULE='\n最终交付补充：没有任何业务行值时，开头写“业务分析受阻”，不能以结构检查成功标为业务部分完成。不展示served_by、token检查、UTC配额重置时间、重复缺字段或合规口号。不要求重新授权，除非实际权限缺失。SHAP仅在用户要求解释模型时按需获取。输出JSON时只需简短status及report_text，其他内部键非必需，不扩写内部清单。'
for id in ['17928150494110','1792725312027']:
    nodes[id]['agent_task']+=REPORT_RULE
    nodes[id]['agent_job']['workflow_prompt']=nodes[id]['agent_task']

# Deterministic parser after each branch. Fail closed for structured reports
# missing report_text; do not dump status/evidence/internal fields to users.
CODE=r'''import json,re
FALLBACK='未取得有效的报告正文，请检查报告节点的report_text输出。'
def strip_thinking(text):
    depth=0; cursor=0; parts=[]
    for m in re.finditer(r'</?(?:think|thinking|analysis|reasoning)\b[^>]*>',text,re.I):
        if depth==0: parts.append(text[cursor:m.start()])
        if m.group().startswith('</'):
            if depth==0: return ''
            depth-=1
        else: depth+=1
        cursor=m.end()
    if depth==0: parts.append(text[cursor:])
    return ''.join(parts).strip()
def extract(value,depth=0):
    if depth>6: return None
    if isinstance(value,dict):
        report=value.get('report_text')
        return extract(report,depth+1) if isinstance(report,str) and report.strip() else None
    if not isinstance(value,str): return None
    clean=strip_thinking(value).strip()
    if not clean or clean in ('init','_NO_PLAN_','null'): return None
    fence=re.fullmatch(r'```(?:json|text|markdown)?\s*\n?([\s\S]*?)\n?```',clean,re.I)
    if fence: clean=fence.group(1).strip()
    try:
        parsed=json.loads(clean)
    except (ValueError,TypeError): parsed=None
    else:
        if isinstance(parsed,(dict,str)): return extract(parsed,depth+1)
        return None
    # Accept valid JSON objects surrounded by a short model preamble/fence.
    decoder=json.JSONDecoder()
    for m in re.finditer(r'\{',clean):
        try: obj,_=decoder.raw_decode(clean[m.start():])
        except ValueError: continue
        if isinstance(obj,dict) and 'report_text' in obj: return extract(obj,depth+1)
    # Broken structured output is not allowed to leak as user prose.
    if clean.startswith(('{','[')) or re.search(r'["\'](?:report_text|review_decision|task_progress)["\']\s*:',clean): return None
    return clean
def main(text: str):
    return {'result':extract(text) or FALLBACK}
'''
changed_code=[]
for id,d in nodes.items():
    # Branch sanitation nodes have exactly text input and result output.
    if d.get('type')=='code' and set(d.get('outputs',{}))=={'result'} and [v.get('variable') for v in d.get('variables',[])]==['text']:
        d['code']=CODE; changed_code.append(id)
assert '1792989337792' in changed_code
assert nodes['1792988903900']['outputs'][0]['value_selector']==['1792989277120','output']

# Test actual code used inside package, including the observed JSON report form.
env={}; exec(CODE,env); main=env['main']
cases=[('正常正文','正常正文'),(json.dumps({'status':'partial','report_text':'业务分析受阻。','continue':0},ensure_ascii=False),'业务分析受阻。'),('```json\n{"report_text":"仅显示正文"}\n```','仅显示正文'),('报告如下：\n{"report_text":"已提取"}','已提取'),(json.dumps(json.dumps({'report_text':'双重编码'},ensure_ascii=False),ensure_ascii=False),'双重编码'),('<think>内部思考</think>{"report_text":"答案"}','答案'),('{"report_text":"<analysis>内部</analysis>正文"}','正文'),('{"status":"blocked"}',env['FALLBACK']),('{"report_text":null}',env['FALLBACK']),('{"report_text":',env['FALLBACK']),('<think>未闭合',env['FALLBACK']),('{"report_text":""}',env['FALLBACK'])]
for value,expected in cases: assert main(value)['result']==expected,(value,main(value))

# Check roster shapes and protected settings remain compatible.
for pkg in original['agent_packages']:
    before=copy.deepcopy(original['agent_packages'][pkg]); after=copy.deepcopy(app['agent_packages'][pkg])
    if pkg in ('agent_2','agent_8'):
        after['soul']['prompt']=before['soul']['prompt']
        for old,new in zip(before['soul']['tools']['dify_tools'],after['soul']['tools']['dify_tools']):
            new['enabled']=old['enabled']; new['description']=old['description']
    assert before==after,pkg
assert app['workflow']['graph']['edges']==original['workflow']['graph']['edges']
incoming={id:set() for id in nodes}
for e in app['workflow']['graph']['edges']: incoming[e['target']].add(e['source'])
def ancestors(id,seen=None):
    seen=set() if seen is None else seen
    for parent in incoming[id]:
        if parent not in seen: seen.add(parent); ancestors(parent,seen)
    return seen
for id,d in nodes.items():
    if d.get('type')=='agent':
        assert d['agent_task']==d['agent_job']['workflow_prompt']
        if d.get('isInLoop'):
            refs=set(re.findall(r'\{\{#(\d+)\.([^#]+)#\}\}',d['agent_task']))
            assert refs=={(r['node_id'],r['output']) for r in d['agent_job']['previous_node_output_refs']}
            for target,_ in refs: assert target in ancestors(id) and nodes[target].get('loop_id')==d['loop_id']
files['app.yaml']=yaml.safe_dump(app,allow_unicode=True,sort_keys=False,width=110).encode()
assert yaml.safe_load(files['app.yaml'])==app
manifest=yaml.safe_load(files['manifest.yaml'])
for item in manifest['apps']:
    b=files[item['path']]; item['size']=len(b); item['sha256']=hashlib.sha256(b).hexdigest()
files['manifest.yaml']=yaml.safe_dump(manifest,allow_unicode=True,sort_keys=False).encode()
target=OUT/'FactoryPulseAgent.query-output-fixed.ifpkg'
with zipfile.ZipFile(target,'w') as z:
    for info in infos: z.writestr(info,files[info.filename])
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
    for item in manifest['apps']+sum([r.get('files',[]) for r in manifest['agent_resources'].values()],[]):
        b=z.read(item['path']); assert len(b)==item['size'] and hashlib.sha256(b).hexdigest()==item['sha256']
checks={'archive_manifest':'passed','roster_schema_and_bindings':'preserved','graph_and_loop_refs':'passed','output_parser_cases_passed':len(cases),'branch_parsers_updated':len(changed_code),'reader_token_verify_disabled':True,'database_runtime_hard_limits':False,'live_import_tested':False,'live_query_tested':False}
(OUT/'validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'report_text_parser.py').write_text(CODE,encoding='utf-8')
(OUT/'说明.txt').write_text('导入并发布 FactoryPulseAgent.query-output-fixed.ifpkg。保留原用户输入userinput和最终输出output；output现在由代码提取正文，正常结构化报告只透出report_text，解析失败显示简短提示。调试面板仍可见内部Agent原始JSON，这不等同于最终output。\n查询协议统一至Research与独立数据库读取Agent，禁复合UNION和例行结构查询，禁无关token验证；工具/模型/凭据绑定保持原配置。循环仍为单轮。结构错误时最多一次针对单对象核对，明确配额/权限失败即停止。\n查询次数、SQL范围是Agent策略约束，插件不在包内，不能硬性限制底层SQL扫描；LIMIT不等于低扫描量。本地完成包完整性、引用及12类输出提取测试，尚未在线导入或查库验证。\n',encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))
