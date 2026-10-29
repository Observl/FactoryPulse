"""FEMTO full-trajectory RUL proxy; never label truncated test endpoints as failure."""
import json,io,zipfile,concurrent.futures
from collections import Counter
from pathlib import Path
import numpy as np
import real_industrial_train as t
ROOT=t.ROOT;P=ROOT/'raw/femto/nested'
def prepare():
    cache=ROOT/'femto_full_trajectory_features.npz'
    if cache.exists():
        a=np.load(cache);return {k:a[k] for k in a.files}
    X=[];y=[];groups=[];source_names=[];counts={};skipped=[]
    for fn in ['Training_set.zip','Validation_Set.zip']:
        with zipfile.ZipFile(P/fn) as z:
            members=[n for n in z.namelist() if '/acc_' in n and n.endswith('.csv')]
            bearings=sorted({n.split('/')[1] for n in members})
            for bearing in bearings:
                names=sorted(n for n in members if n.split('/')[1]==bearing)
                indices=[int(Path(n).stem.split('_')[1]) for n in names]
                if indices!=list(range(1,len(names)+1)):raise ValueError('Non-contiguous trajectory '+bearing)
                condition=int(bearing[7:8]);counts[bearing]=len(names)
                def extract(name):
                    content=z.read(name)
                    delimiter=';' if b';' in content.splitlines()[0] else ','
                    a=np.loadtxt(io.BytesIO(content),delimiter=delimiter)
                    if a.shape!=(2560,6):raise ValueError('Unexpected shape '+name+str(a.shape))
                    sensors=a[:,4:6].T
                    if not np.isfinite(sensors).all():raise ValueError('Nonfinite physical signal '+name)
                    basic=t.stats(sensors).reshape(-1)
                    centered=sensors-sensors.mean(axis=1,keepdims=True);sd=sensors.std(axis=1)
                    kurt=np.mean(centered**4,axis=1)/np.maximum(sd**4,1e-16)
                    crest=np.max(np.abs(sensors),axis=1)/np.maximum(np.sqrt(np.mean(sensors*sensors,axis=1)),1e-12)
                    power=np.abs(np.fft.rfft(centered,axis=1))**2
                    bands=np.column_stack([power[:,lo:hi].sum(axis=1)/np.maximum(power.sum(axis=1),1e-12) for lo,hi in [(1,128),(128,512),(512,1281)]]).reshape(-1)
                    # Operating-condition identity is known; bearing identity and current index are excluded.
                    return np.r_[basic,kurt,crest,bands,[int(condition==c) for c in [1,2,3]]]
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:features=list(pool.map(extract,names))
                X.extend(features);y.extend(np.arange(len(names)-1,-1,-1));groups.extend([bearing]*len(names));source_names.extend(names)
                print(json.dumps({'prepared_bearing':bearing,'snapshots':len(names)}),flush=True)
    a={'X':np.asarray(X,np.float32),'y':np.asarray(y,float),'groups':np.array(groups),'source_names':np.array(source_names)}
    np.savez_compressed(cache,**a)
    t.save(ROOT/'femto_feature_manifest.json',{'complete_bearing_counts':counts,'features':
        'Two vibration channels: mean/std/min/max/rms/q25/q75/delta, kurtosis, crest, three normalized frequency bands; three known operating-condition indicators.',
        'target':'Number of snapshots remaining until end of full run-to-failure record; endpoint 0. Not calendar days or calibrated failure probability.',
        'no_target_features':['bearing ID','snapshot index','timestamp','total lifetime','RUL','future samples'],
        'excluded_archive':'Test_set.zip contains truncated duplicates of the 11 Full_Test_Set runs; not treated as new independent bearings or labeled as failed at truncated end.'})
    return a
if __name__=='__main__':
    if not (P/'Training_set.zip').exists() or not (P/'Validation_Set.zip').exists():
        from real_industrial_bearings import inspect
        inspect('femto')
    # Freeze protocol before fitting or looking at any held-out response.
    t.save(ROOT/'FEMTO_PROTOCOL.json',{'outer':'.20 of rows, whole bearing groups, closest possible count; cover all three known operating conditions on both sides',
        'inner':'.25 of development rows, same whole-group rule','tie':'SHA256 of fixed seed and group names',
        'selection_uses_only':'trajectory row counts and group/operating-condition identities, no sensor values or response quality; reserve at least two development bearings per condition for inner split',
        'label':'remaining full-run snapshots; no truncated endpoint labels','candidate_models':'same five predeclared regression candidates as other tasks'})
    a=prepare();d=dict(name='femto_remaining_life',source='femto',mode='regression',split='balanced_group_rows',
        note='17 full physical accelerated-life bearing trajectories; full runs grouped, row-balanced near 80/20, all three operating conditions represented. Target is remaining snapshots to experimental endpoint, not field-calendar RUL. Excludes truncated Test_set duplicates.',**a)
    r=t.run(d)
    # Keep group membership in audit evidence despite training helper receiving arrays by reference.
    split=np.load(ROOT/'experiments/femto_remaining_life/frozen_split.npz')
    r['group_sets']={k:np.unique(d['groups'][split[k]]).tolist() for k in ['train','validation','development','test']}
    t.save(ROOT/'experiments/femto_remaining_life/result.json',r)
    p=ROOT/'training_summary.json';s=json.loads(p.read_text());s['results']=[x for x in s['results'] if x['name']!=r['name']]+[r];t.save(p,s)
