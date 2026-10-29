"""Create local experiment inventory, report and a standalone comparison figure."""
import json,hashlib,platform,sys,os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028/matplotlib-cache'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from real_industrial_download import SOURCES
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028'
LABELS={'steel_defect_type':'钢板缺陷类型','robot_lp1':'机器人 LP1','robot_lp2':'机器人 LP2','robot_lp3':'机器人 LP3',
 'robot_lp4':'机器人 LP4','robot_lp5':'机器人 LP5','secom_quality':'半导体制程质量','aps_component_failure':'卡车 APS 部件故障',
 'hydraulic_cooler':'液压冷却器','hydraulic_valve':'液压阀','hydraulic_pump_leakage':'液压泵泄漏',
 'hydraulic_accumulator':'液压蓄能器','milling_flank_wear':'铣削刀具磨损','metropt_7day_failure':'地铁压缩机七天故障预警',
 'ims_remaining_life':'IMS 轴承剩余试验寿命','femto_remaining_life':'FEMTO 轴承剩余试验寿命'}
def main():
    summary=json.loads((ROOT/'training_summary.json').read_text());results=sorted(summary['results'],key=lambda r:list(LABELS).index(r['name']) if r['name'] in LABELS else 100)
    inventory=[]
    for name,url,page,kind,license in SOURCES:
        folder=ROOT/'raw'/name
        f=next((x for x in [folder/'source.zip',folder/'source.ranged.zip'] if x.exists()),None)
        item={'name':name,'source_page':page,'download_url':url,'provenance':kind,'license':license,'status':'downloaded' if f else 'not_complete'}
        if f:item.update(archive=str(f),bytes=f.stat().st_size,sha256=hashlib.file_digest(f.open('rb'),'sha256').hexdigest())
        inventory.append(item)
    (ROOT/'source_inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    registry=[]
    for r in results:
        status='offline_research_only'
        if r['name']=='milling_flank_wear':status='rejected_corrupt_sensor_values_and_unstable_extrapolation'
        if r['name']=='metropt_7day_failure':status='rejected_no_test_failure_events_and_excessive_false_alarms'
        if r['name']=='secom_quality':status='rejected_low_precision_and_no_heldout_f1_improvement'
        registry.append({'task':r['name'],'validation_selected_model':r['winner'],'use_status':status,
            'artifact':str(ROOT/'experiments'/r['name']/(r['winner']+'.joblib')),
            'feature_extractor':'scripts/real_industrial_train.py::datasets; bearing extension uses real_industrial_rul.py',
            'production_integration':False})
    (ROOT/'model_registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')
    done=[x for x in inventory if x['status']=='downloaded'];total=sum(x.get('bytes',0) for x in done)
    lines=['# FactoryPulse 真实工业数据本地算法实验报告','',
        '> 本地实验；数据、模型和预测没有上传，未修改线上数据库、生产算法或网页。日期：2026-10-28。','',
        '## 结论','',
        f'已完整下载并校验 **{len(done)} 套**公开真实测量数据，压缩原始包合计 **{total/1e9:.3f} GB**；完成 **{len(results)} 项**独立建模评估。数据来源包括实际运行和实机实验，不能全部称为真实生产现场数据。这是已核验公开来源清单，不是全球工业数据的穷尽集合。','',
        '- **卡车 APS 诊断有改善**：测试 F1 从 75.65% 到 84.83%，精确率从 68.33% 到 85.29%；误报 108 → 40，漏报 42 → 43。按原挑战的 10×误报+500×漏报口径，成本 22,080 → 21,900，仅减少 0.82%。本轮按 F1 筛选，未宣称成本最优。',
        '- **液压诊断整体表现较好**：四个任务分别评估；单试验台的随机循环划分不证明可泛化到其他工厂和设备。',
        '- **故障提前预警尚未通过**：地铁数据按时间划分后，最终测试段没有已报告故障起点；模型误报过高。不能用诊断分类的高分替代未来故障预测证据。',
        '- **保留失败结果**：SECOM 未稳定超过基线；NASA 铣削文件存在极端传感器数值，验证集选出的 Ridge 在测试时失控，拒绝用于实际决策。没有删除不利测试记录或根据测试结果重调参数。','',
        '## 数据来源与适用范围','',
        '| 数据 | 来源性质 | 原始包 MB | 使用范围 |','|---|---|---:|---|']
    uses={'metropt3':'压缩机未来七天故障窗口；4 个官方报告事件','hydraulic':'冷却器、阀、泵、蓄能器当次循环状态诊断',
        'aps_scania':'APS 指定部件故障 vs 其他部件故障，负类并非健康卡车','secom':'当次半导体制程合格/不合格分类',
        'steel_faults':'七类钢板缺陷；没有正常钢板样本','robot_failures':'机器人故障检测后的力/扭矩诊断，不是事前预警',
        'nasa_milling':'切削后测得的刀具后刀面磨损 VB；缺失标签不插补',
        'nasa_ims':'加速寿命试验；核对完整失效轨迹后使用','femto':'加速寿命试验；部分轨迹未运行到失效，不伪造其终点标签'}
    for s in inventory:lines.append(f"| [{s['name']}]({s['source_page']}) | {s['provenance']} | {s.get('bytes',0)/1e6:.2f} | {uses[s['name']]}；{s['status']} |")
    lines+=['','原始包和嵌套包均保留；`source_inventory.json` 记录下载地址、许可证说明、大小和 SHA-256。UCI 按其页面的 CC BY 4.0 说明记录；APS 包内另有 Scania GPLv3 声明，两者均保留，未重新分发原始包。NASA 按其资料库及提供者说明署名。',
        '','排除 AI4I、C-MAPSS、船舶推进系统仿真等合成/仿真数据；没有生成替代故障、业务工单、人员、库存、价格或计划标签。公开测量数据不包含维护排程可执行性和业务审批效果的真实标签，本轮不报告这些业务效果。','',
        '## 实验方法与 80%/20% 划分','',
        '随机种子 20261028。普通分类按事件/完整循环分层划分：约 80% 开发集、20% 最终测试集；开发集再按 75%/25% 分为内部训练和验证，即总体约 60%/20%/20%。超参数、算法族和二分类阈值只由内部验证集选择，最后用开发集重训，再评估已经冻结的测试集。',
        '',
        '- SECOM 按真实时间顺序划分；MetroPT 按时间划分，在两道边界剔除会跨越边界的七天标签窗口，并剔除正在故障和末端不足七天观察期的记录。',
        '- 铣削按整把刀具/试验 case 隔离；16 个组使用约 20% 组数的 GroupShuffleSplit，实际开发 103、测试 43 条有标签切削记录，即 **70.55%/29.45% 行数**，并非严格的行级 80%/20%。这是保持组完整性的偏离，不能隐藏或说成精确 80/20。',
        '- APS 原来的 60,000/16,000 官方文件合并后重分为 60,800/15,200，满足本轮 80/20，但不能与官方挑战榜单直接比较。数据没有唯一车辆标识和时间，无法进一步核查同一车辆是否跨集。',
        '- 完全相同的有标签记录去重；重复预测向量保留第一次，数量记录在各任务结果。所有机器人事件的 15 个采样点作为整体，未拆到不同集合。',
        '- 不同任务分别建模，不混合特征单位和标签。液压排除虚拟效率信号 CE/CP/SE 及其他故障标签，磨损模型排除 case/run/time 编号及磨损目标。缺失值插补和标准化只在训练侧拟合。',
        '',
        '比较五个预先确定候选：FactoryPulse 同类 XGBoost 参数基线（140 棵树、深度 4、学习率 0.05）、较强正则 XGBoost、交互 XGBoost、ExtraTrees、分类 LogisticRegression/回归 Ridge。**基线与候选使用相同特征**，不是线上完整预警与排程流程的回放。二分类选择验证集 F1 最大的阈值，多分类按 macro-F1，回归按 MAE。各任务的候选验证分数和冻结选择见 `selection_frozen.json`。',
        '','## 最终测试结果','',
        'F1 是精确率与召回率的调和平均；多分类使用各类别等权的 macro-F1。下表逐任务比较，不计算跨任务“总准确率”。','',
        '| 任务 | 测试条数 | 指标 | 参数基线 | 验证集选出模型 | 选出模型测试结果 |','|---|---:|---|---:|---|---:|']
    for r in results:
        b=r['test']['factorypulse_baseline'];w=r['test'][r['winner']]
        if r['mode']=='regression':metric='MAE，越小越好';bv=f"{b['mae']:.5g}";wv=f"{w['mae']:.5g}"
        elif r['name']=='metropt_7day_failure':metric='负窗口误报率';bv=f"{b['false_positive_rate']:.2%}";wv=f"{w['false_positive_rate']:.2%}（未通过）"
        else:metric='F1' if 'tp' in w else 'macro-F1';bv=f"{b['f1']:.2%}";wv=f"{w['f1']:.2%}"
        lines.append(f"| {LABELS.get(r['name'],r['name'])} | {r['split_counts']['test']} | {metric} | {bv} | {r['winner']} | {wv} |")
    lines+=['','![测试集分类表现对比](classification-comparison.png)','',
        '机器人子任务只有 10–33 个测试事件；LP5 的 100% 仅代表 33 个事件全对，不是工业可靠性保证。LP3 正常标签写作 `ok`，已按实际标签映射；它仍有较高误报。液压相邻循环可能相关，随机循环划分的高分可能偏乐观；缺乏独立设备/试验标识，不能把这些循环当作大量独立工厂。没有重复改变随机种子寻找高分，也没有计算假定采样独立的时间序列置信区间。','',
        '### 没通过的关键任务','',
        '- **MetroPT**：原始 CSV 实际 1,516,948 行（官方说明 PDF 另写 15,169,480，不能照搬）；处理后 23,247 个有效十分钟窗口。名义 80/20 后，开发侧七天隔离使最终开发 17,865、测试 4,650；测试区间 2020-07-17 07:00 至 2020-08-25 03:50，没有官方报告的新故障。选出模型把 4,648/4,650 个负窗口报成阳性。召回率、PR-AUC 和故障事件提前量在该测试段不可可靠估计，不能把零阳性时软件计算出的 F1=0 解释为完整预测能力评估。',
        '- **铣削**：167 次原始切削，146 次有 VB；21 次缺失标签直接排除。case 2/run 1 原始信号含约 10^34 的值，case 12/run 1 还出现约 2771 的读数。未修饰数据的 Ridge 测试 MAE 约 2.687×10^31 mm，是输入质量和数值鲁棒性失败；XGBoost 参数基线 MAE 约 0.1010 mm。原始失败保留，模型注册表将该选出模型标为拒绝。',
        '- **SECOM**：最终 314 条中只有 17 条不合格。选出模型召回 10/17，但误报 146/297，精确率 6.41%；F1 11.56%，低于基线 12.07%。不能用总体准确率掩盖少数类失效。','',
        '## 每项实际数据规模','',
        '| 任务 | 去重后行数 | 特征数 | 开发 | 内部验证 | 最终测试 | 测试占比 | 缺失比例 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in results:
        c=r['split_counts'];lines.append(f"| {r['name']} | {r['rows']} | {r['features']} | {c['development']} | {c['validation']} | {c['test']} | {r['actual_test_fraction']:.2%} | {r['missing_fraction']:.2%} |")
    if summary['errors']:lines+=['','未评分项目：']+[f"- {x['task']}：{x['error']}" for x in summary['errors']]
    bearing=ROOT/'bearing_evidence.json'
    if bearing.exists():
        evidence=json.loads(bearing.read_text());lines+=['','## 轴承轨迹与标签审查','',evidence.get('report_text','')]
    per_bearing=ROOT/'experiments/femto_remaining_life/per_bearing_test_metrics.json'
    if per_bearing.exists():
        values=json.loads(per_bearing.read_text())
        lines+=['','FEMTO 本轮没有候选超过验证集上的 XGBoost 参数基线，因此保留基线。最终测试 MAE 409.94 个快照、RMSE 503.51、R² 0.596；开发/测试为 19,913/4,976 个快照，即 80.007%/19.993%。完整轴承组为 13/4，未按原挑战的 6/11 分组，结果不能对照官方榜单。',
            '',f"按轴承等权的平均 MAE 为 {np.mean([v['mae_remaining_snapshots'] for v in values]):.2f}，高于按快照加权的 409.94；短寿命轴承明显较差，不能因大轨迹占比较高而忽略。仅有四条独立测试轨迹，没有做出可靠现场寿命预测的结论。",'',
            '| 测试轴承 | 快照数 | MAE（剩余快照数） |','|---|---:|---:|']
        lines += [f"| {v['bearing']} | {v['n']} | {v['mae_remaining_snapshots']:.2f} |" for v in values]
    lines+=['','## 本地产物与复核','',
        '- `raw/`：下载原始包、原始说明、来源与校验值。',
        '- `experiments/<任务>/`：冻结划分、处理后特征、所有验证分数、两组最终预测、模型及完整指标。',
        '- `model_registry.json`：标记仅限离线研究和拒绝模型；没有自动替换线上算法。',
        '- `audit.json`：独立检查开发/测试不相交、内部训练/验证不相交、划分哈希、验证选模一致，并从保存预测重新计算 F1/MAE/混淆计数。这个复核不等于工业可用性认证。',
        '- `python-environment.txt`：实际本地依赖版本。报告由本地实验文件自动生成。','',
        '复现（在项目目录执行；下载步骤需要网络，训练和复核不需要网络）：','',
        '```powershell',
        '.venv\\Scripts\\python.exe scripts/real_industrial_download.py',
        '.venv\\Scripts\\python.exe scripts/real_industrial_train.py',
        '.venv\\Scripts\\python.exe scripts/real_industrial_bearings.py femto',
        '.venv\\Scripts\\python.exe scripts/real_industrial_rul.py',
        '.venv\\Scripts\\python.exe scripts/real_industrial_audit.py',
        '.venv\\Scripts\\python.exe scripts/real_industrial_report.py',
        '```','',
        '本轮没有把测试结果用于第二轮超参数搜索。需要继续优化的失败项必须先处理数据质量和任务定义，并另设新的独立评估资料；当前测试结果已经公开观察，不能继续当作全新盲测。']
    (ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Separate units: classification only; RUL and wear MAE are intentionally excluded.
    rows=[r for r in results if r['mode']=='classification' and r['name']!='metropt_7day_failure']
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
    fig,ax=plt.subplots(figsize=(11,7.5));fig.subplots_adjust(left=.27,right=.91,bottom=.16,top=.88)
    y=np.arange(len(rows));b=[r['test']['factorypulse_baseline']['f1'] for r in rows];w=[r['test'][r['winner']]['f1'] for r in rows]
    ax.barh(y-.18,b,.34,label='XGBoost parameter baseline',color='#426e9b')
    ax.barh(y+.18,w,.34,label='Validation-selected model',color='#cf8b2f')
    names=[r['name'].replace('hydraulic_','Hydraulic: ').replace('robot_','Robot: ').replace('_',' ')+f"  (n={r['split_counts']['test']})" for r in rows]
    ax.set_yticks(y,names);ax.invert_yaxis();ax.set_xlim(0,1.12);ax.set_xticks(np.arange(0,1.01,.2));ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.set_xlabel('Held-out F1 (macro-F1 for multiclass tasks)');ax.spines[['top','right']].set_visible(False);ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True)
    for i,(v0,v1) in enumerate(zip(b,w)):ax.text(max(v0,v1)+.015,i,f'{v0:.1%} / {v1:.1%}',va='center',fontsize=8)
    fig.suptitle('Local real-data classification experiments',x=.27,ha='left',fontsize=17,fontweight='bold')
    ax.legend(loc='upper left',bbox_to_anchor=(0,-.09),frameon=False,ncol=2)
    fig.text(.27,.015,'One frozen split per task; small robot tests and single-rig hydraulic data limit generalization.\nDiagnostic/quality scores do not validate future equipment-failure forecasting.',fontsize=9,color='#444444')
    fig.savefig(ROOT/'classification-comparison.png',dpi=160);plt.close(fig)
    print(json.dumps({'report':str(ROOT/'REPORT.md'),'complete_sources':len(done),'tasks':len(results),'raw_bytes':total}))
if __name__=='__main__':main()
