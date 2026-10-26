"""Read the isolated frozen D1 dataset and validate the full model in RAM only."""
import json,sys,sqlite3,time,math
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def forbidden(*args,**kwargs):raise RuntimeError('No local databases allowed during frozen model acceptance')
sqlite3.connect=forbidden
from backend.d1_identity import D1Store
from backend.analytics import xgboost_with_shap
p=Path(json.loads((ROOT/'.secrets/acceptance-current.json').read_text())['directory'])
m=json.loads((p/'manifest.json').read_text());assert m['scope']=='isolated_cloudflare_acceptance'
cfg=json.loads((p/'business.json').read_text());assert cfg['database_id']==m['databases']['business']['id'];assert cfg['database_id']!='abc7cb74-5be4-49a2-827a-3bd8b639f257'
db=D1Store(cfg);started=time.perf_counter()
version=db.batch([{'sql':"SELECT value FROM fp_app_settings WHERE key='default_dataset'"}])[0]['results'][0]['value']
count=db.batch([{'sql':"SELECT COUNT(*) AS n FROM fp_dataset_records WHERE dataset_id=? AND table_name='readings'",'params':[version]}])[0]['results'][0]['n'];assert count==34560
rows=[]
for start in range(0,count,2000):
 batches=db.batch([{'sql':"SELECT content FROM fp_dataset_records WHERE dataset_id=? AND table_name='readings' ORDER BY row_index LIMIT 500 OFFSET ?",'params':[version,offset]} for offset in range(start,min(count,start+2000),500)])
 for batch in batches:rows.extend(json.loads(r['content']) for r in batch['results'])
 print('Frozen rows read:',len(rows),flush=True)
assert len(rows)==count and len({x['equipment_id'] for x in rows})==24
result=xgboost_with_shap(rows);assert result.status=='ready',result.status
assert len(result.predictions)==24 and len(result.calculations)==24
errors=[]
for identifier,score in result.predictions.items():
 details=result.calculations[identifier];assert math.isfinite(score) and 0<=score<=1
 error=abs(details['reconstructed_score']-details['model_output']);assert error<.00001
 assert abs(details['model_output']-score)<.000051;errors.append(error)
report={'scope':'full_frozen_synthetic_dataset_memory_only','checked_at':datetime.now(timezone.utc).isoformat(),'dataset_id':version,'readings':len(rows),'devices':24,'status':result.status,'model_version':result.model_version,'current_scores_verified':len(errors),'max_shap_reconstruction_error':max(errors),'training_rows':result.training_rows,'test_rows':result.evaluation.get('test_rows'),'probability_calibrated':result.evaluation.get('probability_calibrated'),'seconds':round(time.perf_counter()-started,2),'cloud_writes':0,'local_database_connections':0,'limitation':'Synthetic software verification; not evidence of field prediction or economic benefit.'}
(ROOT/'outputs/full-acceptance/frozen-model-memory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
