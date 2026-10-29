"""Independent audit of saved splits and held-out predictions (no model training)."""
import json,hashlib
from pathlib import Path
import numpy as np
from sklearn.metrics import f1_score,accuracy_score,mean_absolute_error,mean_squared_error
ROOT=Path(__file__).resolve().parents[1]/'outputs/real-industrial-20261028'
def audit():
    checks=[]
    for folder in sorted((ROOT/'experiments').iterdir()):
        if not (folder/'result.json').exists():continue
        r=json.loads((folder/'result.json').read_text());s=np.load(folder/'frozen_split.npz');a=np.load(folder/'prepared.npz')
        assert not set(s['development'])&set(s['test']),folder
        assert not set(s['train'])&set(s['validation']),folder
        assert set(s['train'])<=set(s['development']) and set(s['validation'])<=set(s['development']),folder
        assert hashlib.sha256((folder/'frozen_split.npz').read_bytes()).hexdigest()==r['split_sha256'],folder
        if r['split']=='purged_time':
            times=a['times'];gap=7*86400*10**9
            assert times[s['development']].max()+gap<times[s['test']].min(),folder
            assert times[s['train']].max()+gap<times[s['validation']].min(),folder
        if 'groups' in a.files:
            assert not set(a['groups'][s['development']])&set(a['groups'][s['test']]),folder
            assert not set(a['groups'][s['train']])&set(a['groups'][s['validation']]),folder
        frozen=json.loads((folder/'selection_frozen.json').read_text())
        expected=max(frozen['trials'],key=lambda q:q['score'])['name']
        assert expected==r['winner']==frozen['winner'],folder
        if 'group_sets' in r:
            groups=r['group_sets']
            assert not set(groups['development'])&set(groups['test']),folder
            if 'train' in groups:assert not set(groups['train'])&set(groups['validation']),folder
        for name,m in r['test'].items():
            p=np.load(folder/(name+'_test_predictions.npz'));y=p['y_true'];v=p['prediction']
            assert np.array_equal(y,a['y'][s['test']]),folder
            assert np.isfinite(v).all(),folder
            if r['mode']=='regression':
                assert np.isclose(mean_absolute_error(y,v),m['mae'])
                assert np.isclose(np.sqrt(mean_squared_error(y,v)),m['rmse'])
            else:
                pred=(v>=p['threshold']).astype(int) if v.ndim==1 else v.argmax(axis=1)
                assert np.isclose(f1_score(y,pred,average='binary' if v.ndim==1 else 'macro',zero_division=0),m['f1'])
                assert np.isclose(accuracy_score(y,pred),m['accuracy'])
                if v.ndim==1:
                    assert int(((y==1)&(pred==0)).sum())==m['fn']
                    assert int(((y==0)&(pred==1)).sum())==m['fp']
        checks.append({'task':r['name'],'split_disjoint':True,'split_hash_verified':True,'selection_matches_validation':True,
            'predictions_match_test_labels':True,'metrics_independently_recomputed':True})
    result={'status':'passed','tasks_checked':len(checks),'checks':checks,
        'limits':'Verifies recorded artifacts and code-selected validation winner, not industrial deployment validity or future generalization.'}
    (ROOT/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':audit()
