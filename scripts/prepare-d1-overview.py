"""Compute frozen acceptance evidence with the real Python model and publish to D1.
The calculations use RAM; all persistent state is remote D1.
"""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import sqlite3
sqlite3.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Local database access forbidden'))
from backend.d1_business import configuration
from backend.d1_identity import D1Store

store=D1Store(configuration())
selected=store.batch([{'sql':"SELECT value FROM fp_app_settings WHERE key='default_dataset'"}])[0]['results']
if not selected:raise RuntimeError('Dataset has not finished verification')
version=selected[0]['value']
metadata=store.batch([{'sql':'SELECT * FROM fp_datasets WHERE dataset_id=? AND ready=1','params':[version]}])[0]['results'][0]
tables={}
for item in store.batch([{'sql':'SELECT table_name,COUNT(*) AS n FROM fp_dataset_records WHERE dataset_id=? GROUP BY table_name','params':[version]}])[0]['results']:
    name=item['table_name'];tables[name]=[]
    for start in range(0,item['n'],2000):
        batches=store.batch([{'sql':'SELECT content FROM fp_dataset_records WHERE dataset_id=? AND table_name=? ORDER BY row_index LIMIT 500 OFFSET ?','params':[version,name,offset]} for offset in range(start,min(start+2000,item['n']),500)])
        for batch in batches:tables[name].extend(json.loads(row['content']) for row in batch['results'])
    print('Read from D1:',name,len(tables[name]),flush=True)

import backend.main as app
settings={'sync_status':'synced','last_sync_at':version,'source_date':metadata['source_date'],'source_name':'CNC 多故障模型验证集（模拟）','source_url':'','record_count':str(len(tables['readings'])),'device_count':str(len(tables['equipment'])),'sync_error':'','import_filename':'','data_origin':'SYNTHETIC_CNC_MODEL_VALIDATION_V1','data_lineage':'[]','inventory_scope':version}
with app.connect() as connection:
    if connection.execute('SELECT COUNT(*) FROM records').fetchone()[0]:
        existing=connection.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
        if not existing or existing[0]!=version:raise RuntimeError('Business database already contains another dataset; refusing to replace it')
    else:
        connection.execute('INSERT INTO records SELECT table_name,row_index,content FROM fp_dataset_records WHERE dataset_id=?',[version])
        app.settings_set_many(connection,settings)
        app.initialize_demo_stock(connection,tables,version)
print('Business records activated',flush=True)
# Pure computations use these already-read D1 inputs, avoiding repeated network transfer.
app.rows=lambda name,limit=None:tables.get(name,[])[:limit]
app.settings_get=lambda name,default='':settings.get(name,default)
overview=app.overview()
quality=app.data_quality()
store.batch([{'sql':'CREATE TABLE IF NOT EXISTS fp_computed_views(dataset_id TEXT NOT NULL,view_key TEXT NOT NULL,content TEXT NOT NULL,PRIMARY KEY(dataset_id,view_key))'}])
views={'overview':overview,'data-quality':quality}
for device in tables['equipment']:
    identifier=device['equipment_id']
    views['history/'+identifier]=app.equipment_history(identifier,360)
for key,value in views.items():
    store.batch([{'sql':'INSERT INTO fp_computed_views VALUES(?,?,?) ON CONFLICT(dataset_id,view_key) DO UPDATE SET content=excluded.content','params':[version,key,json.dumps(value,ensure_ascii=False,default=str,separators=(',',':'))]}])
print(json.dumps({'published_views':len(views),'devices':overview['metrics']['total'],'model_status':overview['analytics']['xgboost'],'counts':overview['counts']},ensure_ascii=False),flush=True)
