"""Independent local metrics, raw-source identity, grouping and deletion audit."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from scipy.io import loadmat
import real_industrial_audit as metrics_audit
from equipment_round2_download import sources
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028-round2'
def main():
    metrics_audit.ROOT=ROOT;metrics_audit.audit()
    old=ROOT.parent/'real-industrial-20261028';deletion=json.loads((old/'data-deletion-manifest.json').read_text())
    assert all(not Path(v['path']).exists() for v in deletion['items']),'Previous training data still exists'
    hashes=0
    for item in sources():
        f=ROOT/'raw'/item['name']/item['filename'];m=json.loads((f.parent/(f.name+'.manifest.json')).read_text())
        assert f.stat().st_size==m['bytes'],f
        assert hashlib.file_digest(f.open('rb'),'sha256').hexdigest()==m['sha256'],f
        hashes+=1
    # Correct source channel selection; entire DE signals are not copied between files.
    seen={};cwru=[]
    for f in sorted((ROOT/'raw/cwru').glob('*.mat')):
        d=loadmat(f,simplify_cells=True);ks=[k for k in d if k.endswith('DE_time')];expected='X'+str(int(f.stem)).zfill(3)+'_DE_time'
        assert expected in ks or len(ks)==1,f
        k=expected if expected in ks else ks[0];digest=hashlib.sha256(np.asarray(d[k]).tobytes()).hexdigest()
        assert digest not in seen,(f,seen.get(digest));seen[digest]=f.name;cwru.append((f.name,k))
    cr=json.loads((ROOT/'experiments/cwru_bearing_fault/result.json').read_text());fixed=json.loads((ROOT/'cwru_fixed_recording_partitions.json').read_text())
    assert cr['group_sets']['test']==fixed['test'] and cr['group_sets']['validation']==fixed['validation']
    # Reconstruct pump physical observations directly from source CSVs, independently of the training features.
    sensors=['Accelerometer1RMS','Accelerometer2RMS','Current','Pressure','Temperature','Thermocouple','Voltage','RateRMS'];frames=[]
    base=ROOT/'raw/skab/extracted'
    for f in sorted(base.rglob('*.csv')):
        a=pd.read_csv(f,sep=';').rename(columns={'Volume Flow RateRMS':'RateRMS'});a['datetime']=pd.to_datetime(a['datetime'])
        a=a.sort_values('datetime').reset_index(drop=True);a['file']=str(f.relative_to(base)).replace('\\','/')
        a['anomaly']=a['anomaly'].astype(int) if 'anomaly' in a else 0
        a['key']=pd.util.hash_pandas_object(a[['datetime']+sensors],index=False).to_numpy();frames.append(a)
    raw=pd.concat(frames,ignore_index=True);bad=raw.groupby('key')['anomaly'].nunique();bad=set(bad[bad>1].index)
    clean=raw.loc[~raw['key'].isin(bad)].drop_duplicates('key',keep='first')
    manifest=json.loads((ROOT/'skab_feature_manifest.json').read_text());component={v['file']:v['overlap_component'] for v in manifest['experiments']}
    groups=clean['file'].map(component).to_numpy();p=ROOT/'experiments/skab_water_pump_anomaly';a=np.load(p/'prepared.npz')
    assert np.array_equal(clean[sensors].to_numpy(np.float32),a['X'][:,:8],equal_nan=True),'Pump source observations differ from prepared features'
    assert np.array_equal(clean['anomaly'].to_numpy(),a['y']),'Pump labels differ'
    assert np.array_equal(groups,a['groups']),'Pump source grouping differs'
    r=json.loads((p/'result.json').read_text());part={g:k for k in ['train','validation','test'] for g in r['group_sets'][k]}
    raw['partition']=raw['file'].map(component).map(part)
    assert raw['partition'].notna().all()
    crossings=int((raw.groupby('key')['partition'].nunique()>1).sum());assert crossings==0,'Raw pump observations cross partitions'
    assert len(clean)==45281 and len(bad)==235 and len(raw)==46806
    # Independent source-record counts for unseen-physical-bearing evaluation.
    pm=json.loads((ROOT/'paderborn_feature_manifest.json').read_text());p=ROOT/'experiments/paderborn_motor_bearing_fault';a=np.load(p/'prepared.npz')
    assert len(pm['recordings'])==len(a['y'])
    assert len(set(a['groups']))==15
    assert len(pm['recordings'])+len(pm['exact_signal_duplicates_removed'])==1200
    result={'status':'passed','metric_tasks':4,'source_files_sha256_verified':hashes,'previous_data_targets_absent':len(deletion['items']),
        'previous_deleted_bytes':sum(v['bytes'] for v in deletion['items']),
        'cwru_source_channels_verified':len(cwru),'cwru_original_test_and_validation_recordings_preserved':True,
        'pump_raw_rows':len(raw),'pump_unique_conflicting_keys_excluded':len(bad),'pump_clean_observations':len(clean),
        'pump_raw_keys_crossing_corrected_partitions':crossings,'pump_feature_labels_and_components_match_raw_sources':True,
        'paderborn_physical_bearings':15,'paderborn_raw_recordings':1200,'paderborn_retained_recordings':len(a['y']),
        'limitations':'CWRU and SKAB are disclosed source-quality repair retests, not new blind tests. Passing artifact checks does not certify industrial deployment or future-failure prediction.'}
    (ROOT/'equipment_quality_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
