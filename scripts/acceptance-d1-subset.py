"""Activate two frozen devices only in the pre-existing isolated acceptance D1."""
import json,os,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
private=Path(json.loads((ROOT/'.secrets/acceptance-current.json').read_text())['directory'])
manifest=json.loads((private/'manifest.json').read_text())
assert manifest['scope']=='isolated_cloudflare_acceptance'
os.environ['FACTORYPULSE_BUSINESS_CONFIG']=str(private/'business.json')
from backend.d1_business import configuration,Connection
from backend.d1_identity import D1Store
from backend.demo_business import complete_demo_business,initialize_demo_stock
from backend.inventory import current_scope
from backend.model_validation_data import ORIGIN
cfg=configuration();assert cfg['database_id']==manifest['databases']['business']['id']
assert cfg['database_id'] not in {'abc7cb74-5be4-49a2-827a-3bd8b639f257','af5776ef-c7f8-48c7-8f21-1bb36f98061c'}
store=D1Store(cfg)
assert store.batch([{'sql':'SELECT COUNT(*) AS n FROM records'}])[0]['results'][0]['n']==0,'Subset already activated; do not replace it'
meta=store.batch([{'sql':"SELECT d.* FROM fp_datasets d JOIN fp_app_settings s ON s.value=d.dataset_id WHERE s.key='default_dataset' AND d.ready=1"}])[0]['results'][0]
data={}
for name in ['equipment','maintenance_rules','maintenance_history','orders','demo_risks','readings','staff','scenarios']:
    found=[];offset=0
    predicate=" AND json_extract(content,'$.equipment_id') IN ('VAL-CNC-001','VAL-CNC-009')" if name not in {'staff','scenarios'} else ''
    while True:
        rows=store.batch([{'sql':'SELECT content FROM fp_dataset_records WHERE dataset_id=? AND table_name=?'+predicate+' ORDER BY row_index LIMIT 300 OFFSET ?','params':[meta['dataset_id'],name,offset]}])[0]['results']
        found.extend(json.loads(r['content']) for r in rows)
        if len(rows)<300:break
        offset+=300
    data[name]=found
assert {r['equipment_id'] for r in data['equipment']}=={'VAL-CNC-001','VAL-CNC-009'}
complete_demo_business(data)
stamp=datetime.now(timezone.utc).isoformat()
with Connection(store) as c:
    for name,rows in data.items():
        c.executemany('INSERT INTO records(table_name,row_index,content) VALUES(?,?,?)',[(name,i,json.dumps(r,ensure_ascii=False,separators=(',',':'))) for i,r in enumerate(rows)])
    values={'sync_status':'synced','last_sync_at':stamp,'source_date':meta['source_date'],'source_name':'独立验收子集：VAL-CNC-001 / VAL-CNC-009（仅流程测试）','record_count':str(len(data['readings'])),'device_count':'2','data_origin':ORIGIN,'acceptance_scope':'isolated_two_device_workflow_subset','sync_error':'','import_filename':''}
    c.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',list(values.items()))
    initialize_demo_stock(c,data,current_scope(c))
report={'scope':'isolated_two_device_workflow_subset','frozen_dataset_unchanged':meta['dataset_id'],'counts':{k:len(v) for k,v in data.items()},'activated_at':stamp}
(ROOT/'outputs/full-acceptance/subset.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
