"""Local-only measured-industrial-data experiment. No database/cloud imports.

Frozen outer holdout, model/threshold selection exclusively on inner validation.
Run after real_industrial_download.py. Artifacts remain under ignored outputs/.
"""
import os
os.environ.setdefault('OMP_NUM_THREADS', '4')
import json, time, hashlib, re, traceback, warnings,itertools,math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.io import loadmat
from sklearn.model_selection import train_test_split, GroupShuffleSplit
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (f1_score, precision_score, recall_score, accuracy_score,
    balanced_accuracy_score, confusion_matrix, average_precision_score, roc_auc_score,
    mean_absolute_error, mean_squared_error, r2_score)
from xgboost import XGBClassifier, XGBRegressor
import joblib

ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028'
RAW=ROOT/'raw'; SEED=20261028
warnings.filterwarnings('ignore', category=UserWarning)

def save(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda o:o.item() if isinstance(o,np.generic) else str(o),allow_nan=False),encoding='utf-8')

def stats(a):
    a=np.asarray(a,dtype=np.float64)
    if a.ndim==1:a=a[None,:]
    return np.column_stack([np.mean(a,axis=1),np.std(a,axis=1),np.min(a,axis=1),np.max(a,axis=1),
        np.sqrt(np.mean(a*a,axis=1)),np.quantile(a,.25,axis=1),np.quantile(a,.75,axis=1),
        a[:,-1]-a[:,0]])

def datasets():
    p=RAW/'steel_faults/extracted/Faults.NNA'
    a=np.loadtxt(p)
    yield dict(name='steel_defect_type',source='steel_faults',X=a[:,:27],y=a[:,27:].argmax(axis=1),
        mode='classification',split='stratified',note='Seven defect types; no healthy class; auxiliary inspection task.')
    p=RAW/'robot_failures/extracted'
    for f in sorted(p.glob('lp*.data')):
        rows=[];labels=[];current=[];label=None
        for line in f.read_text().splitlines()+['END']:
            line=line.strip()
            if not line:continue
            fields=line.split()
            try:
                nums=[float(v) for v in fields]
                if len(nums)!=6:raise ValueError()
                current.append(nums)
            except ValueError:
                if current:
                    if len(current)!=15:raise ValueError(f'{f}: event length {len(current)}')
                    rows.append(np.asarray(current).reshape(-1));labels.append(0 if label in ('normal','ok') else 1)
                label=line;current=[]
        yield dict(name=f'robot_{f.stem}',source='robot_failures',X=np.array(rows),y=np.array(labels),
            mode='classification',split='stratified',note='Whole 15-sample event kept together; data begin after failure detection, not early warning.')
    p=RAW/'secom/extracted'
    X=np.loadtxt(p/'secom.data');lines=(p/'secom_labels.data').read_text().splitlines()
    y=np.array([int(s.split()[0])==1 for s in lines],dtype=int)
    ts=pd.to_datetime([s.split(' ',1)[1].strip().strip('"') for s in lines],dayfirst=True)
    order=np.argsort(ts)
    yield dict(name='secom_quality',source='secom',X=X[order],y=y[order],mode='classification',
        split='chronological',note='Same-process pass/fail classification; timestamps sorted; no fault horizon.')
    p=RAW/'aps_scania/extracted'
    frames=[]
    for f in sorted(p.glob('*.csv')):
        lines=f.read_text(encoding='utf-8',errors='replace').splitlines()
        start=next(i for i,s in enumerate(lines) if s.startswith('class,'))
        frames.append(pd.read_csv(f,skiprows=start,na_values='na'))
    a=pd.concat(frames,ignore_index=True)
    yield dict(name='aps_component_failure',source='aps_scania',X=a.drop(columns='class').to_numpy(float),
        y=(a['class']=='pos').to_numpy(int),mode='classification',split='stratified',
        note='Original train/test pooled and re-split 80/20; not comparable to official challenge split. Negatives are other-component failures. No truck IDs/timestamps for stronger grouping.')
    p=RAW/'hydraulic/extracted';features=[];names=[]
    # Exclude CE/CP/SE: virtual efficiency signals can directly proxy target setup.
    for sensor in ['PS1','PS2','PS3','PS4','PS5','PS6','EPS1','FS1','FS2','TS1','TS2','TS3','TS4','VS1']:
        a=np.loadtxt(p/(sensor+'.txt'),dtype=np.float32)
        features.append(stats(a));names.extend([sensor+'_'+s for s in ['mean','std','min','max','rms','q25','q75','delta']])
        del a
    X=np.column_stack(features);profile=np.loadtxt(p/'profile.txt')
    for col,name in enumerate(['cooler','valve','pump_leakage','accumulator']):
        yield dict(name='hydraulic_'+name,source='hydraulic',X=X,y=profile[:,col],mode='classification',
            split='stratified',features=names,note='Complete cycle is unit; single rig with controlled fault settings; random-cycle result is not unseen-machine generalization. Other profile columns excluded.')
    p=RAW/'nasa_milling/extracted/mill.mat'
    records=loadmat(p,simplify_cells=True)['mill'];X=[];y=[];groups=[];excluded=0
    for r in records:
        target=float(r['VB'])
        if not np.isfinite(target):excluded+=1;continue
        row=[]
        for sensor in ['smcAC','smcDC','vib_table','vib_spindle','AE_table','AE_spindle']:row.extend(stats(r[sensor])[0])
        row.extend([r['DOC'],r['feed'],r['material']]);X.append(row);y.append(target);groups.append(r['case'])
    yield dict(name='milling_flank_wear',source='nasa_milling',X=np.array(X),y=np.array(y),groups=np.array(groups),
        mode='regression',split='grouped',note=f'Flank wear VB in mm; whole case/tool kept together; {excluded} missing VB cuts excluded without interpolation; case/run/time omitted from predictors. Group sizes make exact row 80/20 impossible.')
    files=list((RAW/'metropt3/extracted').rglob('*.csv'))
    if files:
        raw=pd.read_csv(files[0]);tc=next(c for c in raw if c.lower()=='timestamp')
        raw[tc]=pd.to_datetime(raw[tc]);raw=raw.sort_values(tc).set_index(tc)
        cols=[c for c in raw.select_dtypes('number') if not c.lower().startswith('unnamed')]
        # Right-edge bins ensure no future sample enters predictors.
        a=raw[cols].resample('10min',closed='right',label='right').agg(['mean','std','min','max']).dropna(how='all')
        a.columns=['_'.join(c) for c in a.columns]
        a=a.replace([np.inf,-np.inf],np.nan)
        events=[('2020-04-18','2020-04-19'),('2020-05-29 23:30','2020-05-30 06:00'),('2020-06-05 10:00','2020-06-07 14:30'),('2020-07-15 14:30','2020-07-15 19:00')]
        horizon=pd.Timedelta(days=7);y=np.zeros(len(a),dtype=int);inside=np.zeros(len(a),dtype=bool)
        for start,end in events:
            start,end=pd.Timestamp(start),pd.Timestamp(end)
            y|=((a.index<start)&(a.index+horizon>=start)).astype(int)
            inside|=(a.index>=start)&(a.index<end)
        valid=(~inside)&(a.index+horizon<=raw.index.max())
        a=a.loc[valid];y=y[valid]
        yield dict(name='metropt_7day_failure',source='metropt3',X=a.to_numpy(float),y=y,mode='classification',
            split='purged_time',times=a.index.as_unit('ns').asi8,raw_rows=len(raw),events=events,
            note='Real metro compressor; causal 10-minute bins; predicts documented failure onset within 7 days; excludes in-failure and censored terminal windows; 7-day purge at each split. Few independent failure events; no calibrated probability claim.')

def split_indices(d):
    n=len(d['y']);idx=np.arange(n);kind=d['split'];y=d['y']
    if kind=='balanced_group_rows':
        def closest(indices,fraction,seed,minimum_remaining=1):
            groups=np.unique(d['groups'][indices]);number=max(1,math.ceil(len(groups)*fraction))
            counts={g:int(sum(d['groups'][indices]==g)) for g in groups};target=len(indices)*fraction
            available_conditions={str(g).split('_')[0] for g in groups}
            options=[]
            for combo in itertools.combinations(groups,number):
                remaining=set(groups)-set(combo)
                if {str(g).split('_')[0] for g in combo}!=available_conditions:continue
                if {str(g).split('_')[0] for g in remaining}!=available_conditions:continue
                if any(sum(str(g).split('_')[0]==c for g in remaining)<minimum_remaining for c in available_conditions):continue
                tie=hashlib.sha256((str(seed)+'|'+','.join(combo)).encode()).hexdigest()
                options.append((abs(sum(counts[g] for g in combo)-target),tie,combo))
            chosen=set(min(options)[2]);mask=np.isin(d['groups'][indices],list(chosen))
            return indices[~mask],indices[mask]
        dev,test=closest(idx,.2,SEED,2);train,val=closest(dev,.25,SEED+1)
    elif kind=='grouped':
        dev,test=next(GroupShuffleSplit(n_splits=1,test_size=.2,random_state=SEED).split(idx,groups=d['groups']))
        it,iv=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=SEED+1).split(dev,groups=d['groups'][dev]))
        train,val=dev[it],dev[iv]
    elif kind in ('chronological','purged_time'):
        cut=int(n*.8);dev=idx[:cut];test=idx[cut:]
        if kind=='purged_time':dev=dev[d['times'][dev]+7*86400*10**9<d['times'][test[0]]]
        inner=int(len(dev)*.75);train=dev[:inner];val=dev[inner:]
        if kind=='purged_time':train=train[d['times'][train]+7*86400*10**9<d['times'][val[0]]]
    else:
        dev,test=train_test_split(idx,test_size=.2,random_state=SEED,stratify=y)
        train,val=train_test_split(dev,test_size=.25,random_state=SEED+1,stratify=y[dev])
    return train,val,dev,test

def candidates(d,y):
    regression=d['mode']=='regression';binary=len(np.unique(y))==2
    common=dict(n_jobs=4,random_state=SEED,tree_method='hist',verbosity=0)
    base=dict(n_estimators=140,max_depth=4,learning_rate=.05,subsample=.85,colsample_bytree=.9,min_child_weight=3,reg_lambda=2)
    def xgb(params):
        if regression:return XGBRegressor(**common,**params,objective='reg:squarederror')
        if binary:params={**params,'scale_pos_weight':float(sum(y==0)/max(1,sum(y==1)))}
        return XGBClassifier(**common,**params,eval_metric='logloss' if binary else 'mlogloss')
    models=[('factorypulse_baseline',xgb(base)),
        ('regularized',xgb({**base,'n_estimators':350,'max_depth':3,'learning_rate':.035,'min_child_weight':8,'reg_lambda':8})),
        ('interactions',xgb({**base,'n_estimators':300,'max_depth':5,'min_child_weight':5,'reg_lambda':5}))]
    if regression:
        models.extend([('extra_trees',make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),ExtraTreesRegressor(n_estimators=250,min_samples_leaf=2,n_jobs=4,random_state=SEED))),
            ('ridge',make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),Ridge(alpha=10)))])
    else:
        models.extend([('extra_trees',make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),ExtraTreesClassifier(n_estimators=250,min_samples_leaf=2,class_weight='balanced',max_features=.8,n_jobs=4,random_state=SEED))),
            ('linear',make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),LogisticRegression(C=.1,class_weight='balanced',max_iter=1500)))])
    return models

def threshold(y,p):
    # Entirely validation-derived. Fixed grid is committed before any test evaluation.
    grid=np.linspace(.01,.99,99);scores=[f1_score(y,p>=t,zero_division=0) for t in grid]
    return float(grid[int(np.argmax(scores))])

def metrics(y,p,regression=False,threshold_value=.5):
    if regression:return {'mae':float(mean_absolute_error(y,p)),'rmse':float(np.sqrt(mean_squared_error(y,p))),'r2':float(r2_score(y,p))}
    binary=p.ndim==1;pred=(p>=threshold_value).astype(int) if binary else p.argmax(axis=1)
    out={'accuracy':float(accuracy_score(y,pred)),'balanced_accuracy':float(balanced_accuracy_score(y,pred)),
        'f1':float(f1_score(y,pred,average='binary' if binary else 'macro',zero_division=0)),
        'precision':float(precision_score(y,pred,average='binary' if binary else 'macro',zero_division=0)),
        'recall':float(recall_score(y,pred,average='binary' if binary else 'macro',zero_division=0)),
        'confusion_matrix':confusion_matrix(y,pred).tolist()}
    if binary:
        tn,fp,fn,tp=confusion_matrix(y,pred,labels=[0,1]).ravel()
        out.update(tn=int(tn),fp=int(fp),fn=int(fn),tp=int(tp),false_positive_rate=float(fp/max(1,tn+fp)))
        if len(np.unique(y))>1:out.update(pr_auc=float(average_precision_score(y,p)),roc_auc=float(roc_auc_score(y,p)))
    return out

def predictions(model,X,regression,binary):
    if regression:return model.predict(X)
    p=model.predict_proba(X)
    return p[:,1] if binary else p

def run(d):
    started=time.monotonic();folder=ROOT/'experiments'/d['name'];folder.mkdir(parents=True,exist_ok=True)
    X=np.asarray(d['X'],dtype=np.float32);X[~np.isfinite(X)]=np.nan;y=np.asarray(d['y'])
    regression=d['mode']=='regression';encoder=None
    if not regression:encoder=LabelEncoder();y=encoder.fit_transform(y)
    d['y']=y
    # Remove exact labeled duplicates globally before freeze; never learn a transform on heldout data.
    hashes=pd.util.hash_pandas_object(pd.DataFrame(X),index=False).to_numpy()
    labeled=pd.DataFrame({'hash':hashes,'y':y});keep=~labeled.duplicated().to_numpy()
    duplicate_count=int((~keep).sum())
    # Keep identical predictor vectors in a single set: remove later repetitions, even conflicting labels.
    unique_features=~pd.Series(hashes[keep]).duplicated().to_numpy()
    positions=np.flatnonzero(keep)[unique_features]
    conflict_count=int(keep.sum()-len(positions))
    if d.get('preserve_repeated_measurements',False):
        positions=np.arange(len(y));duplicate_count=0;conflict_count=0
    X=X[positions];y=y[positions];d['y']=y
    for key in ('groups','times'):
        if key in d:d[key]=d[key][positions]
    train,val,dev,test=split_indices(d)
    if not regression and (len(np.unique(y[train]))!=len(np.unique(y)) or len(np.unique(y[val]))<2):
        raise ValueError('Insufficient class coverage in inner split; not safe to tune')
    np.savez_compressed(folder/'frozen_split.npz',train=train,validation=val,development=dev,test=test,source_positions=positions)
    metadata={key:d[key] for key in ('groups','times') if key in d}
    np.savez_compressed(folder/'prepared.npz',X=X,y=y,**metadata)
    sha=hashlib.sha256((folder/'frozen_split.npz').read_bytes()).hexdigest()
    save(folder/'protocol.json',{'seed':SEED,'outer_test_fraction':.2,'inner_validation_fraction_of_development':.25,
        'split_strategy':d['split'],'split_sha256':sha,'selection':'validation minimum MAE' if regression else 'validation maximum F1 (binary) / macro-F1 (multiclass)',
        'test_use':'evaluate baseline and selected model only after model and threshold frozen','note':d['note']})
    binary=not regression and len(np.unique(y))==2
    trials=[];models=candidates(d,y[train])
    for name,model in models:
        t=time.monotonic();model.fit(X[train],y[train]);p=predictions(model,X[val],regression,binary)
        cut=threshold(y[val],p) if binary else .5
        m=metrics(y[val],p,regression,cut)
        score=-m['mae'] if regression else m['f1']
        trials.append({'name':name,'score':score,'threshold':cut,'validation':m,'seconds':round(time.monotonic()-t,2)})
        print(json.dumps({'task':d['name'],'candidate':name,'validation_score':score}),flush=True)
    winner=max(trials,key=lambda a:a['score']);save(folder/'selection_frozen.json',{'winner':winner['name'],'trials':trials,'test_not_consulted':True})
    evaluations={};chosen_names={'factorypulse_baseline',winner['name']}
    # Rebuild and refit after selection; thresholds remain from inner validation.
    for name,model in candidates(d,y[dev]):
        if name not in chosen_names:continue
        model.fit(X[dev],y[dev]);p=predictions(model,X[test],regression,binary)
        cut=next(t['threshold'] for t in trials if t['name']==name)
        evaluations[name]=metrics(y[test],p,regression,cut)
        np.savez_compressed(folder/(name+'_test_predictions.npz'),y_true=y[test],prediction=p,threshold=cut)
        joblib.dump({'model':model,'threshold':cut,'label_classes':None if encoder is None else encoder.classes_,
            'split_sha256':sha,'task':d['name'],'feature_count':X.shape[1]},folder/(name+'.joblib'))
    result={'name':d['name'],'source':d['source'],'mode':d['mode'],'split':d['split'],'note':d['note'],
        'raw_rows':d.get('raw_rows',len(keep)),'rows_before_dedup':len(keep),'rows':len(y),'features':X.shape[1],
        'exact_labeled_duplicates_removed':duplicate_count,'repeated_predictors_removed':conflict_count,
        'missing_fraction':float(np.isnan(X).mean()),'split_counts':{k:len(v) for k,v in [('inner_train',train),('validation',val),('development',dev),('test',test)]},
        'actual_test_fraction':len(test)/len(y),'winner':winner['name'],'test':evaluations,'trials':trials,
        'seconds':round(time.monotonic()-started,2),'split_sha256':sha}
    if not regression:result['class_counts']={k:dict(zip(*[v.tolist() for v in np.unique(y[ix],return_counts=True)])) for k,ix in [('development',dev),('test',test)]}
    if d['split']=='grouped':result['group_sets']={k:np.unique(d['groups'][ix]).tolist() for k,ix in [('development',dev),('test',test)]}
    if d['split']=='purged_time':
        ts=pd.DatetimeIndex(d['times'][test]);result['test_time_range']=[str(ts.min()),str(ts.max())]
        result['independent_test_onsets']=[start for start,end in d['events'] if ts.min()<pd.Timestamp(start)<=ts.max()+pd.Timedelta(days=7)]
    save(folder/'result.json',result);print(json.dumps({'completed':d['name'],'winner':winner['name'],'test':evaluations}),flush=True)
    return result

if __name__=='__main__':
    save(ROOT/'EXPERIMENT_PROTOCOL.json',{'seed':SEED,'local_only':True,'test_fraction':.2,
        'tuning_within_development_only':True,'candidate_families':['FactoryPulse-like XGBoost baseline','regularized XGBoost','interaction XGBoost','ExtraTrees','linear model'],
        'excluded':'Synthetic/ simulated sources, target-derived predictor columns, unlabeled partial run-to-failure endpoints.'})
    results=[];errors=[]
    try:
        for d in datasets():
            try:results.append(run(d))
            except Exception as e:
                errors.append({'task':d['name'],'error':str(e),'traceback':traceback.format_exc()});print(traceback.format_exc(),flush=True)
            save(ROOT/'training_summary.json',{'results':results,'errors':errors})
    except Exception as e:
        errors.append({'task':'data_preparation','error':str(e),'traceback':traceback.format_exc()})
        save(ROOT/'training_summary.json',{'results':results,'errors':errors});raise
