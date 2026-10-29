"""Package the three explicitly selected offline diagnostic models for Workers."""
import hashlib,json,math
from pathlib import Path
import joblib,numpy as np
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'outputs/real-industrial-20261028/experiments'
TARGET=ROOT/'public/models';TARGET.mkdir(parents=True,exist_ok=True)
QA=ROOT/'outputs/diagnostic-release';QA.mkdir(parents=True,exist_ok=True)
NAMES={'aps_component_failure':'卡车气压系统诊断','hydraulic_valve':'液压阀诊断','hydraulic_accumulator':'蓄能器诊断'}
def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
manifest={'version':'industrial-diagnostics-20261028-v1','task':'current_equipment_state_diagnosis','automatic_equipment_scoring':False,'models':[]}
fixtures=[]
for name,title in NAMES.items():
    folder=SOURCE/name;r=json.loads((folder/'result.json').read_text(encoding='utf-8'));candidate=r['winner'];package=joblib.load(folder/(candidate+'.joblib'));model=package['model']
    baseline=r['test']['factorypulse_baseline']['f1'];score=r['test'][candidate]['f1']
    if score<=baseline:raise RuntimeError('Refusing a non-improving candidate: '+name)
    payload={'id':name,'feature_count':package['feature_count'],'threshold':package['threshold'],'classes':package['label_classes'].tolist()}
    if hasattr(model,'get_booster'):
        raw=json.loads(model.get_booster().save_raw(raw_format='json'));learner=raw['learner']
        base=json.loads(learner['learner_model_param']['base_score']);base=base[0] if isinstance(base,list) else base
        payload.update(kind='xgboost_binary',base_margin=math.log(float(base)/(1-float(base))),trees=[])
        for tree in learner['gradient_booster']['model']['trees']:
            if any(tree['split_type']):raise RuntimeError('Categorical trees are not supported')
            payload['trees'].append({k:tree[v] for k,v in [('left','left_children'),('right','right_children'),('feature','split_indices'),('value','split_conditions'),('missing_left','default_left')]})
    else:
        imputer,forest=model.steps[0][1],model.steps[-1][1]
        payload.update(kind='extra_trees',imputation=imputer.statistics_.tolist(),trees=[])
        for estimator in forest.estimators_:
            tree=estimator.tree_;values=[]
            for i in range(tree.node_count):
                if tree.children_left[i]<0:
                    v=tree.value[i,0];values.append((v/v.sum()).tolist())
                else:values.append(None)
            payload['trees'].append({'left':tree.children_left.tolist(),'right':tree.children_right.tolist(),'feature':tree.feature.tolist(),'threshold':tree.threshold.tolist(),'probabilities':values})
    sensors=['PS1','PS2','PS3','PS4','PS5','PS6','EPS1','FS1','FS2','TS1','TS2','TS3','TS4','VS1']
    fields=[sensor+'_'+stat for sensor in sensors for stat in ['mean','std','min','max','rms','q25','q75','delta']] if name.startswith('hydraulic') else ['csv_column_'+str(i+1).zfill(3) for i in range(170)]
    recipe='按原始 APS CSV 的170个传感器列顺序，去掉 class；na 以 null 表示。当前部署不接受其他字段顺序。' if name.startswith('aps') else '按列出的14路传感器顺序，每个完整采集周期提取 mean、总体 std、min、max、rms、q25、q75、末值减首值；不能传入单次瞬时读数。'
    contract=hashlib.sha256(json.dumps({'name':name,'fields':fields,'recipe':recipe,'split':package['split_sha256']},sort_keys=True).encode()).hexdigest()[:20]
    payload['input_contract']=contract
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode();digest=hashlib.sha256(encoded).hexdigest();filename=name+'-'+digest[:16]+'.json';(TARGET/filename).write_bytes(encoded)
    metadata={'id':name,'title':title,'algorithm':candidate,'artifact':'/models/'+filename,'artifact_sha256':digest,'input_contract':contract,'feature_count':payload['feature_count'],'fields':fields,'recipe':recipe,'classes':payload['classes'],'threshold':payload['threshold'],'baseline_f1':baseline,'test_f1':score,'test_rows':r['split_counts']['test'],'limitations':r['note'],'split_sha256':package['split_sha256'],'scope':'research_diagnosis','positive_label':'气压系统部件故障' if name.startswith('aps') else None}
    manifest['models'].append(metadata)
    # Conversion QA uses generated vectors, not deleted training/test records.
    rng=np.random.default_rng(20261028);n=payload['feature_count'];probes=[np.zeros(n),np.ones(n),np.full(n,10.),np.full(n,100.)]
    if payload['kind']=='extra_trees':probes.extend([np.array(payload['imputation'])+rng.normal(size=n)*scale for scale in [0.,.01,1.,10.] for _ in range(20)])
    else:probes.extend([rng.lognormal(mean=scale,sigma=2.,size=n) for scale in [0.,3.,6.,10.] for _ in range(20)])
    for _ in range(20):
        row=probes[int(rng.integers(len(probes)))].copy();row[rng.random(n)<.15]=np.nan;probes.append(row)
    rows=np.asarray(probes);expected=model.predict_proba(rows)
    fixtures.append({'id':name,'features':[[None if not np.isfinite(v) else float(v) for v in row] for row in rows],'probabilities':expected.tolist(),'input_contract':contract})
    print(json.dumps({'model':name,'bytes':len(encoded),'conversion_vectors':len(rows),'test_f1':score},ensure_ascii=False))
save(TARGET/'manifest.json',manifest);save(QA/'conversion-fixtures.json',fixtures)
save(QA/'release-manifest.json',manifest)
