"""Local results and provenance for industrial-equipment-only round two."""
import os,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028-round2'
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'matplotlib-cache'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from equipment_round2_download import sources
LABELS={'cwru_bearing_fault':'CWRU 电机轴承四类诊断','mfpt_bearing_fault':'MFPT 轴承三类诊断',
 'paderborn_motor_bearing_fault':'Paderborn 电机与轴承三类诊断','skab_water_pump_anomaly':'SKAB 水泵回路异常识别'}
def main():
    summary=json.loads((ROOT/'training_summary.json').read_text());results=sorted(summary['results'],key=lambda r:list(LABELS).index(r['name']))
    manifests=[]
    for item in sources():
        p=ROOT/'raw'/item['name']/(item['filename']+'.manifest.json')
        manifests.append(json.loads(p.read_text()) if p.exists() else {**item,'status':'not_complete'})
    inventory=[]
    for name in ['cwru','mfpt','paderborn','skab']:
        records=[r for r in manifests if r['name']==name];done=[r for r in records if r['status']=='downloaded']
        inventory.append({'name':name,'completed_files':len(done),'requested_files':len(records),
            'bytes':sum(r['bytes'] for r in done),'complete':len(done)==len(records),
            'source_page':records[0]['source_page'],'license':records[0]['license'],'provenance':records[0]['provenance']})
    (ROOT/'source_inventory.json').write_text(json.dumps({'datasets':inventory,'files':manifests},ensure_ascii=False,indent=2),encoding='utf-8')
    total=sum(r['bytes'] for r in inventory);trials=sum(len(r['trials']) for r in results)
    registry=[]
    for r in results:
        b=r['test']['factorypulse_baseline'];w=r['test'][r['winner']]
        state='baseline_retained' if r['winner']=='factorypulse_baseline' else 'candidate_rejected_test_degradation' if w['f1']<b['f1'] else 'offline_candidate_only'
        registry.append({'task':r['name'],'validation_selected':r['winner'],'status':state,
            'model':str(ROOT/'experiments'/r['name']/(r['winner']+'.joblib')),
            'evaluation_type':'quality_repair_retest_not_new_blind_test' if r['source'] in ['cwru','skab'] else 'frozen_group_holdout',
            'online_integration':False,'data_scope':'industrial equipment measurements only'})
    (ROOT/'model_registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# FactoryPulse 工业设备数据：第二轮本地算法报告','',
        '> 日期：2026-10-28。仅工业设备运行、故障和异常数据；全部本地训练，无线上数据库、网页或生产算法修改。','',
        f'本轮完成 **{len(inventory)} 套**新数据的获取（{sum(r["completed_files"] for r in inventory)} 个原始下载文件，**{total/1e9:.3f} GB**），完成 **{len(results)} 项任务、{trials} 组候选比较**。上一轮下载及处理后的训练数据已删除约 **19.00 GB**；旧数据和旧模型权重均未参与本轮训练。旧报告、来源元数据和评估证据保留。',
        '',
        '## 当前结果','',
        '多分类按 macro-F1（各类别等权）评估，水泵二分类按异常类 F1。F1 越高越好。基线与候选使用相同特征，基线为 FactoryPulse 同类 XGBoost 参数方案，不是线上全业务流程的回放。','',
        '| 设备任务 | 测试观测 / 独立分组 | 指标 | XGBoost 参数基线 | 验证集选出候选 | 候选测试结果 | 结果性质 |',
        '|---|---:|---|---:|---|---:|---|']
    for r in results:
        b=r['test']['factorypulse_baseline'];w=r['test'][r['winner']];c=r['split_counts'];n=len(r['group_sets']['test'])
        kind='数据质量修复后复测' if r['source'] in ['cwru','skab'] else '冻结分组测试'
        metric='F1' if r['source']=='skab' else 'macro-F1'
        lines.append(f"| {LABELS[r['name']]} | {c['test']} / {n} | {metric} | {b['f1']:.2%} | {r['winner']} | {w['f1']:.2%} | {kind} |")
    lines+=['','![本轮设备诊断测试结果](equipment-results.png)','',
        '**不能把所有任务都称为优化成功。** 选模只看内部验证集，测试结果较差的候选会如实保留，不改随机种子重新寻找高分，也不将测试集作为调参集。没有把这些分数平均成一个“全厂准确率”。','',
        '## 数据直接来自哪些设备','',
        '| 数据源 | 实际设备与测量 | 本轮范围 |','|---|---|---|']
    desc={'cwru':('2 hp 电机轴承试验台；驱动端加速度','64 个原始 MAT；正常、内圈、滚动体、外圈四类。故障为电火花加工植入，属于实机试验，不是自然现场故障。'),
        'mfpt':('轴承试验台；径向振动信号','20 个原始记录；正常、内圈、外圈三类。来源为数据持有者授权 MathWorks 发布的副本。'),
        'paderborn':('电机驱动系统；两路相电流及一路轴承振动','原作者论文表 10 的 15 个物理轴承：5 个健康、5 个真实外圈损伤、5 个真实内圈损伤；损伤来自加速寿命试验。每个轴承 4 种工况、各 20 条约 4 秒记录，共 1,200 条 MAT。未下载其余人工损伤和混合损伤轴承。'),
        'skab':('水泵循环回路；振动、电流、压力、温度、热电偶、电压、流量','35 个原始 CSV，46,806 行。标注为当前异常状态，包含回路/阀门工况异常，不能都解释为泵机械损坏。')}
    for s in inventory:
        a,b=desc[s['name']];lines.append(f"| [{s['name']}]({s['source_page']}) | {a} | {b} |")
    lines+=['',
        '本轮没有使用钢厂总能耗、电厂综合输出、气体成分识别、钢板质量、半导体制程等数据，也没有使用 AI4I、C-MAPSS 等合成/仿真数据。四套数据都是实机采集，**不等于四套真实生产现场运行数据**。本轮任务是现有状态诊断，没有真实的未来失效时间标签，因此没有编造故障提前量、剩余寿命、维护收益或计划优化结果。','',
        '## 分割和训练方法','',
        '目标为开发集约 80%、最终测试集约 20%。开发集内再保留约 25% 作验证（总体约 60%/20%/20%）。随机种子固定为 20261028。分组只使用来源身份、样本数和类别覆盖，不使用模型测试表现。为了不拆同一个轴承/记录，实际行数比例会有偏离：','',
        '| 任务 | 开发观测 | 内部训练 | 内部验证 | 测试观测 | 实际开发 / 测试占比 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in results:
        c=r['split_counts'];lines.append(f"| {r['name']} | {c['development']} | {c['inner_train']} | {c['validation']} | {c['test']} | {1-r['actual_test_fraction']:.3%} / {r['actual_test_fraction']:.3%} |")
    lines+=['',
        '- **Paderborn**：按物理轴承隔离，整只轴承的全部工况只进入一个集合。每类 5 个轴承中约 4 个开发、1 个测试；内部验证再从开发轴承中取整组。测试只有 3 只独立轴承，不能把数百条重复测量当作数百只设备。',
        '- **CWRU/MFPT**：完整原始文件分组，再将文件内部的振动切为不重叠的 2,048 点窗口；相邻窗口不会跨集。同一损伤轴承可能在多个载荷文件中重复使用，原始材料缺少可证明独立的完整物理样本标识，因此只能声称跨记录评估，不能声称未知设备泛化。MFPT 只有 3 个正常记录，不能精确做到行级 80/20，同时保持整记录隔离；如表所示如实披露偏离。',
        '- **SKAB**：重复内容关联的原始文件先合并为同一连通分组，再隔离开发和测试；滚动特征只使用该原始文件的当前及过去记录，不跨文件计算。',
        '- 所有轴承信号抗混叠重采样到 12 kHz；提取时域统计、频带能量和包络频带特征。Paderborn 每条通道先根据实际记录的时间轴对齐到标称 64 kHz，避免固定假设采样点数。CWRU 正常数据采用常用的 48 kHz 源采样率约定，原始 MAT 本身没有显式采样率字段，此项来源元数据限制保留。',
        '- 插补、标准化和模型拟合都只发生在训练侧。轴承文件名、损伤编号、载荷标签、分组身份、泵的 anomaly/changepoint 标注不作为模型输入。',
        '',
        '预先固定的六种候选：XGBoost 参数基线（140 棵树、深度 4、学习率 0.05）、正则 XGBoost、交互 XGBoost、ExtraTrees、逻辑回归、RBF SVM。水泵 RBF SVM 为控制计算量，只在固定随机种子的最多 8,000 条训练侧记录上拟合；其他候选使用全部内部训练记录。验证集确定算法和二分类阈值后，用开发侧重新拟合，随后评估测试侧。','',
        '## 原始数据问题与复测边界','',
        '1. **CWRU 99.mat 的多信号读取问题**：文件同时含 X098_DE_time 和 X099_DE_time。最初按“第一路 DE”读取会把 X098 当成 99 号文件。已改为优先按文件编号选择 X099；3001–3008 号文件的内部信号编号与文件名不同，仅在内部唯一时接受。纠正后没有发现跨文件的相同驱动端完整信号。原始测试与验证文件名单保持不变；候选网格也不变。',
        '2. **水泵跨文件重复和标签冲突**：发现 1,290 个相同“时间戳+八路传感器”键出现在多个文件中，其中 235 个键的异常标注相互冲突。隔离这些键对应的 470 行，并去掉其余 1,055 行重复观测，保留 45,281 行；35 个文件合并为 30 个重叠连通组。修正前有 349 个重复键跨过分割边界，修正前分数不能作为有效的独立分组证据。',
        '3. **两项修正后的结果不是新的盲测**：最初测试已经运行过，质量问题发现后进行了固定规则修复和复测，未按测试效果选择超参数。CWRU 和 SKAB 的当前分数标记为“修复后复测”，不声称从未接触过测试资料。水泵分组变化，前后分数不能直接解释为算法提升。最初分割和指标保存在 initial-quality-review，修正依据在 QUALITY-REVISIONS.json。',
        '4. **Paderborn 重复记录**：1,200 个原始文件中，检测到 KA04 轴承的 4 条记录与其他记录有完全相同的三路原始信号。去重后使用 1,196 条记录，全部重复都属于同一物理轴承；具体文件名保存在 paderborn_feature_manifest.json。',
        '',
        '## 各任务如何解释','']
    for r in results:
        b=r['test']['factorypulse_baseline'];w=r['test'][r['winner']]
        lines.append(f"### {LABELS[r['name']]}")
        lines.append('')
        if r['winner']=='factorypulse_baseline':lines.append(f"候选在验证集未超过基线，保留基线；当前测试 F1 为 {w['f1']:.2%}。")
        elif w['f1']<b['f1']:lines.append(f"候选在验证集胜出，但测试 F1 从基线 {b['f1']:.2%} 降为 {w['f1']:.2%}，**拒绝晋升此候选**。这说明本轮筛选没有获得稳定改善，不能将训练完成写成优化成功。")
        else:lines.append(f"候选测试 F1 为 {w['f1']:.2%}，基线为 {b['f1']:.2%}；这是当前有限分组下的结果，没有提供跨工厂可靠性保证。")
        lines.append('')
        if r['source']=='mfpt':lines.append('104 个测试窗口来自 4 个原始文件，全部判对也只代表这 4 段记录，不是 104 只独立轴承。')
        if r['source']=='cwru':lines.append('应同时检查正常类的误报，不能只看总体准确率。各类别混淆矩阵和原始预测已保留；分组中的正常测试数据仅来自一个原始记录。')
        if r['source']=='skab':lines.append(f"正常状态误报 {w['fp']}/{w['tn']+w['fp']}，异常漏报 {w['fn']}/{w['tp']+w['fn']}；精确率 {w['precision']:.2%}、召回率 {w['recall']:.2%}。这是有监督分类，不与原 SKAB 无监督榜单直接比较。")
        if r['source']=='paderborn':lines.append('测试内圈轴承 KI04 的 80 条记录均被判为外圈，内圈召回率为 0；本轮特征与模型方案对未见轴承的损伤类别识别失败。它是本轮最严格的物理轴承隔离评估，但仍然只有三只测试轴承，且全来自同一类实验装置；这不说明设备故障无法建模，也不说明其他算法无效。')
        lines.append('')
    if summary['errors']:lines+=['## 未完成项','']+[f"- {v['task']}：{v['error']}" for v in summary['errors']]+['']
    lines+=['## 本地产物与复核','',
        '- raw/：本轮四套设备数据的原始文件、来源和 SHA-256，未上传到任何外部系统。',
        '- experiments/：处理后特征、冻结分组、全部验证比较、最终预测及模型文件。',
        '- model_registry.json：各任务候选的保留/拒绝状态；所有模型仍只限离线研究，没有替换线上算法。',
        '- audit.json 与 equipment_quality_audit.json：独立复算指标、检查分割与分组不相交、来源校验、泵重叠组隔离以及旧训练数据确已删除。',
        '- initial-quality-review/ 与 QUALITY-REVISIONS.json：保留修正前证据和数据质量修复过程，不能把已观察过的测试重新包装成全新盲测。','',
        'MFPT 保留 CC BY-NC-SA 4.0 声明，Paderborn 保留 CC BY-NC 4.0 声明，SKAB 保留仓库 GPL-3.0 声明；CWRU 未据此推断额外商业授权。本轮仅本地离线研究，不代替这些数据的商业使用许可。','',
        '复现命令（下载需要网络，训练和复核在本地运行）：','',
        '```powershell',
        '.venv\\Scripts\\python.exe scripts/equipment_round2_download.py',
        '.venv\\Scripts\\python.exe scripts/equipment_round2_extract.py',
        '.venv\\Scripts\\python.exe scripts/equipment_round2_train.py cwru mfpt skab paderborn',
        '.venv\\Scripts\\python.exe scripts/equipment_round2_audit.py',
        '.venv\\Scripts\\python.exe scripts/equipment_round2_report.py',
        '```','',
        '本轮没有维护工单、人员、备件或生产排程的真实标签，因此未生成这些业务数据，也未报告业务执行效果。']
    (ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11})
    fig,ax=plt.subplots(figsize=(11,5));fig.subplots_adjust(left=.29,right=.94,top=.82,bottom=.28)
    pos=np.arange(len(results));baseline=[r['test']['factorypulse_baseline']['f1'] for r in results];selected=[r['test'][r['winner']]['f1'] for r in results]
    ax.barh(pos-.18,baseline,.34,color='#426e9b',label='XGBoost parameter baseline')
    ax.barh(pos+.18,selected,.34,color='#cf8b2f',label='Validation-selected candidate')
    labels=[r['source'].upper()+f"  (n={r['split_counts']['test']}, groups={len(r['group_sets']['test'])})" for r in results]
    ax.set_yticks(pos,labels);ax.invert_yaxis();ax.set_xlim(0,1.22);ax.set_xticks(np.arange(0,1.01,.2));ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.set_xlabel('Held-out F1 (macro-F1 for bearing classes)');ax.spines[['top','right']].set_visible(False);ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
    for i,(b,w) in enumerate(zip(baseline,selected)):ax.text(max(b,w)+.014,i,f'{b:.1%} / {w:.1%}',va='center',fontsize=10)
    fig.suptitle('Industrial equipment condition diagnosis',x=.29,ha='left',fontsize=17,fontweight='bold')
    ax.legend(loc='upper left',bbox_to_anchor=(0,-.24),frameon=False,fontsize=9)
    fig.text(.29,.02,'CWRU / SKAB: quality-repair retests, not fresh blind tests.\nFile-based windows are correlated; these results do not validate future failure forecasts.',fontsize=9,color='#444444')
    fig.savefig(ROOT/'equipment-results.png',dpi=160);plt.close(fig)
    print(json.dumps({'report':str(ROOT/'REPORT.md'),'datasets':len(inventory),'tasks':len(results),'candidate_comparisons':trials,'source_bytes':total}))
if __name__=='__main__':main()
