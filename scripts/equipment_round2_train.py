"""New physical bearing/motor data only. Offline grouped holdouts and local models."""
import os
os.environ.setdefault('OMP_NUM_THREADS','4')
import json,hashlib,itertools,math,traceback,sys
from pathlib import Path
from fractions import Fraction
import numpy as np
from scipy.io import loadmat
from scipy.signal import resample_poly,hilbert,butter,sosfilt
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.ensemble import BaggingClassifier
from sklearn.model_selection import GroupShuffleSplit
import pandas as pd
import real_industrial_train as engine

ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028-round2'
engine.ROOT=ROOT;engine.SEED=20261028
ORIGINAL_CANDIDATES=engine.candidates
def candidates(d,y):
    svm=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),
        SVC(C=10,gamma='scale',class_weight='balanced',probability=True,random_state=engine.SEED))
    if d['source']=='skab':
        svm=BaggingClassifier(estimator=svm,n_estimators=1,max_samples=min(1.,8000/len(y)),bootstrap=False,random_state=engine.SEED,n_jobs=1)
        return ORIGINAL_CANDIDATES(d,y)+[('rbf_svm_8000',svm)]
    return ORIGINAL_CANDIDATES(d,y)+[('rbf_svm',svm)]
engine.candidates=candidates

def grouped_split(d):
    """Class-stratified whole-record/bearing split. Selection uses counts, not feature quality."""
    idx=np.arange(len(d['y']));groups=d['groups'];y=d['y']
    if d['source']=='cwru' and (ROOT/'cwru_fixed_recording_partitions.json').exists():
        fixed=json.loads((ROOT/'cwru_fixed_recording_partitions.json').read_text())
        test=idx[np.isin(groups,fixed['test'])];val=idx[np.isin(groups,fixed['validation'])]
        dev=idx[~np.isin(groups,fixed['test'])];train=idx[~np.isin(groups,fixed['test']+fixed['validation'])]
        return train,val,dev,test
    if d['split']=='experiment_grouped':
        def choose(indices,fraction,seed):
            options=[];gs,inv,counts=np.unique(groups[indices],return_inverse=True,return_counts=True)
            labels=np.array([np.bincount(y[indices][inv==i],minlength=2) for i in range(len(gs))]);total=labels.sum(axis=0)
            rng=np.random.default_rng(seed);center=round(len(gs)*fraction)
            for number in range(max(1,center-2),min(len(gs)-1,center+2)+1):
                for _ in range(256):
                    selected=np.sort(rng.choice(len(gs),size=number,replace=False));ys=labels[selected].sum(axis=0)
                    if np.any(ys==0) or np.any(total-ys==0):continue
                    tie=hashlib.sha256((str(seed)+'|'+','.join(gs[selected])).encode()).hexdigest()
                    options.append((abs(counts[selected].sum()-len(indices)*fraction),tie,selected))
            best=min(options,key=lambda r:r[:2]);mask=np.isin(groups[indices],gs[best[2]])
            return indices[~mask],indices[mask]
        dev,test=choose(idx,.2,engine.SEED);train,val=choose(dev,.25,engine.SEED+1)
        return train,val,dev,test
    def holdout(indices,fraction,seed):
        chosen=[]
        for label in np.unique(y[indices]):
            part=indices[y[indices]==label];gs=np.unique(groups[part]);n=len(gs)
            if n<2:raise ValueError('Need at least two independent source groups per class')
            counts={g:int(sum(groups[part]==g)) for g in gs};target=len(part)*fraction
            sizes=sorted(set([max(1,min(n-1,math.floor(n*fraction))),max(1,min(n-1,math.ceil(n*fraction)))]))
            options=[]
            for size in sizes:
                for combo in itertools.combinations(gs,size):
                    tie=hashlib.sha256((str(seed)+'|'+','.join(combo)).encode()).hexdigest()
                    options.append((abs(sum(counts[g] for g in combo)-target),tie,combo))
            chosen.extend(min(options)[2])
        mask=np.isin(groups[indices],chosen)
        return indices[~mask],indices[mask]
    dev,test=holdout(idx,.2,engine.SEED);train,val=holdout(dev,.25,engine.SEED+1)
    return train,val,dev,test
engine.split_indices=grouped_split

def physical_features(signal,fs):
    a=np.asarray(signal,dtype=np.float64).reshape(-1)
    if not np.isfinite(a).all():raise ValueError('Nonfinite raw vibration/current values')
    ratio=Fraction(12000/float(fs)).limit_denominator(10000)
    if ratio.numerator!=ratio.denominator:a=resample_poly(a,ratio.numerator,ratio.denominator)
    return a

def feature_vector(a):
    """Time moments + frequency and envelope bands; a single causal physical recording."""
    a=np.asarray(a,float);center=a-a.mean();sd=center.std();rms=np.sqrt(np.mean(a*a));ab=np.abs(a).mean();peak=np.max(np.abs(a))
    base=engine.stats(a)[0].tolist()+[float(np.mean(center**3)/max(sd**3,1e-15)),float(np.mean(center**4)/max(sd**4,1e-15)),
        float(ab),float(peak/max(rms,1e-12)),float(peak/max(ab,1e-12))]
    p=np.abs(np.fft.rfft(center))**2;freq=np.fft.rfftfreq(len(center),1/12000);total=max(p.sum(),1e-20)
    for lo,hi in [(0,250),(250,500),(500,1000),(1000,2000),(2000,4000),(4000,6001)]:base.append(float(p[(freq>=lo)&(freq<hi)].sum()/total))
    base.append(float(np.sum(freq*p)/total/6000))
    filtered=sosfilt(butter(3,[500,5500],btype='bandpass',fs=12000,output='sos'),center)
    env=np.abs(hilbert(filtered));env-=env.mean();power=np.abs(np.fft.rfft(env))**2;den=max(power.sum(),1e-20)
    for lo,hi in [(0,100),(100,200),(200,400),(400,800),(800,2000)]:base.append(float(power[(freq>=lo)&(freq<hi)].sum()/den))
    return np.asarray(base,dtype=np.float32)

def cwru():
    catalog=json.loads((ROOT/'cwru_file_catalog.json').read_text());X=[];y=[];groups=[];records=[]
    for item in catalog:
        f=ROOT/'raw/cwru'/Path(item['url']).name
        if not f.exists():raise FileNotFoundError(f)
        data=loadmat(f,simplify_cells=True);keys=[k for k in data if k.endswith('DE_time')]
        expected='X'+str(int(f.stem)).zfill(3)+'_DE_time'
        if expected in keys:key=expected
        elif len(keys)==1:key=keys[0]
        else:raise ValueError('Ambiguous drive-end channel '+f.name+str(keys))
        label=item['label'];normal=label.startswith('Normal');target=0 if normal else 1 if label.startswith('IR') else 2 if label.startswith('B') else 3
        fs=48000 if normal else 12000
        a=physical_features(data[key],fs);windows=len(a)//2048
        for i in range(windows):X.append(feature_vector(a[i*2048:(i+1)*2048]));y.append(target);groups.append(f.stem)
        records.append({'file':f.name,'mat_variable':key,'label':label,'class':target,'raw_samples':len(data[key]),'assumed_source_sampling_hz':fs,'common_sampling_hz':12000,'complete_nonoverlap_windows':windows})
    engine.save(ROOT/'cwru_feature_manifest.json',{'recordings':records,'classes':['healthy','inner_ring','rolling_element','outer_ring'],
        'normal_sampling_note':'Normal baseline drive-end recordings resampled 48 kHz to 12 kHz before windowing; original files do not carry explicit sampling-rate fields.',
        'features':'25 physical signal statistics / band-energy and envelope features; no filename, RPM, load, defect size or label predictors.'})
    return dict(name='cwru_bearing_fault',source='cwru',mode='classification',split='recording_stratified',X=np.array(X),y=np.array(y),groups=np.array(groups),
        preserve_repeated_measurements=True,note='Physical motor bearing rig with EDM seeded defects. Complete source recordings grouped; nonoverlap 2048-sample windows. Four classes. Different load recordings can still share specimen. Loader correction selects X099 rather than embedded X098 in 99.mat; original test/validation recordings remain frozen. Quality-repair retest, not a fresh blind result.')

def mfpt():
    files=sorted((ROOT/'raw/mfpt/extracted').rglob('*.mat'));X=[];y=[];groups=[];records=[]
    if not files:raise FileNotFoundError('MFPT not yet extracted')
    for f in files:
        d=loadmat(f,simplify_cells=True);b=d['bearing']
        fault=str(b.get('fault',''));filename=f.stem.lower()
        target=0 if 'baseline' in filename or 'normal' in filename else 1 if 'inner' in filename else 2 if 'outer' in filename else None
        if target is None:raise ValueError('Unverified MFPT target '+f.name+' '+fault)
        fs=float(b['sr']);a=physical_features(b['gs'],fs);n=len(a)//2048
        for i in range(n):X.append(feature_vector(a[i*2048:(i+1)*2048]));y.append(target);groups.append(f.stem)
        records.append({'file':f.name,'fault_field':fault,'class':target,'sampling_hz':fs,'windows':n})
    engine.save(ROOT/'mfpt_feature_manifest.json',{'recordings':records,'classes':['healthy','inner_ring','outer_ring'],
        'license':'CC BY-NC-SA 4.0, retained local for research; MathWorks commercial permission does not extend to this project',
        'no_predictors':['filename','fault','load','sampling rate','shaft speed','target']})
    return dict(name='mfpt_bearing_fault',source='mfpt',mode='classification',split='recording_stratified',X=np.array(X),y=np.array(y),groups=np.array(groups),
        preserve_repeated_measurements=True,note='Actual bearing rig; three classes. Resample each recorded sampling rate to 12 kHz. Source recordings grouped, no neighboring window leaks; original specimen identifiers are not available, so no unseen-specimen claim. Original vendor train/test pooled and regrouped, not official benchmark split.')

def skab():
    files=sorted((ROOT/'raw/skab/extracted').rglob('*.csv'));X=[];ys=[];groups=[];records=[];frames=[]
    sensors=['Accelerometer1RMS','Accelerometer2RMS','Current','Pressure','Temperature','Thermocouple','Voltage','RateRMS']
    for f in files:
        a=pd.read_csv(f,sep=';')
        a=a.rename(columns={'Volume Flow RateRMS':'RateRMS'})
        if not set(sensors)<=set(a):raise ValueError('Unexpected pump schema '+str(f))
        a['datetime']=pd.to_datetime(a['datetime']);a=a.sort_values('datetime').reset_index(drop=True)
        if 'anomaly' in a:pass
        elif 'anomaly-free' in str(f):a['anomaly']=0
        else:raise ValueError('No authoritative anomaly label '+str(f))
        a['anomaly']=a['anomaly'].astype(int)
        group=str(f.relative_to(ROOT/'raw/skab/extracted')).replace('\\','/')
        a['_file']=group;a['_key']=pd.util.hash_pandas_object(a[['datetime']+sensors],index=False).to_numpy()
        frames.append(a)
    combined=pd.concat(frames,ignore_index=True);label_counts=combined.groupby('_key')['anomaly'].nunique();bad=set(label_counts[label_counts>1].index)
    parent={f['_file'].iloc[0]:f['_file'].iloc[0] for f in frames}
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    shared=combined.groupby('_key')['_file'].agg(lambda s:sorted(set(s)))
    for names in shared[shared.map(len)>1]:
        for name in names[1:]:parent[find(name)]=find(names[0])
    seen=set();quarantined=0;deduplicated=0
    for a in frames:
        target=a['anomaly'].to_numpy(int)
        if not set(target)<={0,1}:raise ValueError('Unexpected anomaly label')
        values=a[sensors].astype(float)
        # Each row diagnoses its current state; rolling features use only this experiment's past/current values.
        features=pd.concat([values,values.rolling(10,min_periods=1).mean(),values.rolling(10,min_periods=2).std(),
            values.rolling(60,min_periods=1).mean(),values.diff(1)],axis=1)
        group=a['_file'].iloc[0];keep=[]
        for key in a['_key']:
            if key in bad:keep.append(False);quarantined+=1
            elif key in seen:keep.append(False);deduplicated+=1
            else:keep.append(True);seen.add(key)
        keep=np.array(keep);X.append(features.to_numpy()[keep]);ys.append(target[keep]);groups.extend([find(group)]*int(keep.sum()))
        records.append({'file':group,'overlap_component':find(group),'original_rows':len(a),'retained_rows':int(keep.sum()),'anomalies_retained':int(target[keep].sum()),'start':str(a['datetime'].min()),'end':str(a['datetime'].max())})
    if len(files)!=35:raise ValueError('Expected 35 pump experiment files, got '+str(len(files)))
    engine.save(ROOT/'skab_feature_manifest.json',{'experiments':records,'raw_sensors':sensors,'label_conflict_keys_quarantined':len(bad),'quarantined_rows':quarantined,'duplicate_observations_removed':deduplicated,'independent_overlap_components':len(set(groups)),
        'features':'8 sensors, current values plus causal 10-row mean/std, 60-row mean and first differences; 40 columns.',
        'target':'Author-labeled current abnormal state; normal-only file explicitly documented by anomaly-free filename',
        'excluded':['changepoint','datetime','filename','experiment ID','future measurements','anomaly target as predictor'],
        'comparison_note':'Supervised grouped classification, not directly comparable to original unsupervised SKAB leaderboard.'})
    return dict(name='skab_water_pump_anomaly',source='skab',mode='classification',split='experiment_grouped',
        X=np.vstack(X),y=np.concatenate(ys),groups=np.array(groups),raw_rows=len(combined),preserve_repeated_measurements=True,
        note='Actual water-pump circulation-loop rig. Merge overlapping files into connected experiment components; remove repeated physical observations and quarantine conflicting labels before grouped split. Quality-repair exploratory retest after source overlap discovered; not fresh blind evidence. Current-state supervised diagnosis, not future failure prediction or original unsupervised leaderboard protocol.')

def paderborn():
    base=ROOT/'raw/paderborn/extracted';files=sorted(base.rglob('*.mat'));X=[];y=[];groups=[];records=[];duplicates=[];seen=set()
    if len(files)!=1200:raise ValueError('Paderborn extraction incomplete: expected 1200, got '+str(len(files)))
    for ix,f in enumerate(files):
        d=loadmat(f,simplify_cells=True);key=next(k for k in d if not k.startswith('_'));r=d[key]
        bearing=f.stem.split('_')[3];target=0 if bearing.startswith('K0') else 1 if bearing.startswith('KA') else 2 if bearing.startswith('KI') else None
        if target is None:raise ValueError('Unverified bearing category '+bearing)
        signals=r['Y'];signals=signals if isinstance(signals,list) else list(signals)
        selected=[];clocks=[];signal_names=[]
        for s in signals:
            name=str(s.get('Name','')).lower()
            if 'vibration' in name or 'phase_current' in name or 'current' in name:
                selected.append(np.asarray(s['Data']).reshape(-1));signal_names.append(name)
                clocks.append(np.asarray(r['X'][int(s['XIndex'])-1]['Data']).reshape(-1))
        if len(selected)!=3:raise ValueError('Expected two currents + one vibration, got '+str(signal_names))
        # Stable channel order by physical channel name; never by label.
        order=np.argsort(signal_names);selected=[selected[i] for i in order];clocks=[clocks[i] for i in order];signal_names=sorted(signal_names)
        fingerprint=hashlib.sha256(b''.join(a.tobytes() for a in selected)).hexdigest()
        if fingerprint in seen:duplicates.append(f.name);continue
        seen.add(fingerprint)
        features=[]
        for a,clock in zip(selected,clocks):
            if len(a)!=len(clock) or not np.isfinite(clock).all() or np.any(np.diff(clock)<=0):raise ValueError('Invalid recorded time axis '+f.name)
            # Files have slightly varying sample counts/timing. Regrid the recorded clock before antialias decimation.
            start=max(0,np.ceil(clock[0]*64000)/64000);stop=np.floor(clock[-1]*64000)/64000
            uniform_time=np.arange(start,stop,1/64000)
            uniform_signal=np.interp(uniform_time,clock,a)
            features.append(feature_vector(physical_features(uniform_signal,64000)))
        row=np.concatenate(features)
        X.append(row);y.append(target);groups.append(bearing);records.append({'file':f.name,'bearing':bearing,'class':target,'channels':signal_names,'samples':[len(a) for a in selected]})
        if ix%100==0:print(json.dumps({'paderborn_prepared':ix,'total_files':len(files)}),flush=True)
    engine.save(ROOT/'paderborn_feature_manifest.json',{'recordings':records,'exact_signal_duplicates_removed':duplicates,
        'classes':['healthy','outer_ring','inner_ring'],'nominal_sample_rate_hz':64000,'common_rate_hz':12000,
        'clock_handling':'Use each channel XIndex time axis; verify monotonicity; interpolate onto nominal 64 kHz clock, then anti-alias resample to 12 kHz. Do not assume each file has exactly 256000 samples.',
        'label_source':'Paderborn original paper Table 10: five healthy, five real outer-ring and five real inner-ring damage bearings',
        'no_predictors':['bearing ID','filename','fault type','damage extent','group membership']})
    return dict(name='paderborn_motor_bearing_fault',source='paderborn',mode='classification',split='bearing_stratified',X=np.array(X),y=np.array(y),groups=np.array(groups),
        raw_rows=len(files),preserve_repeated_measurements=True,note='15 physical bearing specimens: 5 healthy / 5 accelerated-lifetime outer-ring / 5 inner-ring. Whole specimens grouped, approximately 80/20. Two motor-current channels plus vibration; all four operating conditions retained. Diagnosis of existing damage, not RUL or future-failure prediction.')

if __name__=='__main__':
    engine.save(ROOT/'EXPERIMENT_PROTOCOL.json',{'local_only':True,'seed':engine.SEED,'new_sources_only':['CWRU','MFPT via authorized MathWorks mirror','Paderborn Table 10 subset','SKAB water-pump experiments'],
        'scope':'Industrial equipment bearing/motor condition only. No plant-wide energy, quality inspection, gas identification or synthetic records.',
        'outer_test_fraction':.2,'inner_validation_fraction_of_development':.25,'grouping':'Whole physical bearing specimens for Paderborn; whole original recording files for CWRU/MFPT.',
        'group_selection':'Bearing sources: per-class whole groups nearest requested row count, floor/ceil 20% group count and SHA256 seed tie. Pump: 256 fixed-seed candidates at each nearby group count (rounded desired +/-2), nearest requested row count with binary class coverage. No feature or model score used.',
        'selection':'Only internal validation macro-F1; test opened after candidate frozen','candidates':['baseline XGB','regularized XGB','interaction XGB','ExtraTrees','LogisticRegression','RBF SVM'],
        'preprocessing':'No raw signals or measurements from the prior round are reused. Nonoverlap bearing windows, common 12 kHz sampling, training-only imputation/scaling. Pump RBF SVM capped to a fixed-seed training-only sample of 8000 rows for runtime; other candidates use all training rows.'})
    summary_path=ROOT/'training_summary.json';summary=json.loads(summary_path.read_text()) if summary_path.exists() else {'results':[],'errors':[]}
    names=sys.argv[1:] or ['cwru','mfpt','paderborn']
    for name in names:
        try:
            d=globals()[name]();r=engine.run(d)
            split=np.load(ROOT/'experiments'/r['name']/'frozen_split.npz')
            r['group_sets']={k:np.unique(d['groups'][split[k]]).tolist() for k in ['train','validation','development','test']}
            engine.save(ROOT/'experiments'/r['name']/'result.json',r)
            summary['results']=[v for v in summary['results'] if v['name']!=r['name']]+[r]
            summary['errors']=[v for v in summary['errors'] if v['task']!=name]
        except Exception as e:
            summary['errors']=[v for v in summary['errors'] if v['task']!=name]+[{'task':name,'error':str(e),'traceback':traceback.format_exc()}]
            print(traceback.format_exc(),flush=True)
        engine.save(summary_path,summary)
