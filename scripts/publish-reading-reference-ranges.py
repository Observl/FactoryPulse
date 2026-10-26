"""Attach clearly labelled historical P5/P95 ranges to existing D1 history views."""
import json,math,sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.d1_business import configuration
from backend.d1_identity import D1Store
from backend.data_sync import DATA_INPUTS

from backend.reading_reference import ranges

def main():
    store=D1Store(configuration());inputs=','.join("'"+key+"'" for key in DATA_INPUTS)
    stamp_sql=f'SELECT COALESCE(SUM(revision),0) AS revision FROM fp_resource_revisions WHERE resource IN ({inputs})'
    version=store.batch([{'sql':"SELECT value FROM settings WHERE key='last_sync_at'"}])[0]['results'][0]['value']
    stamp=store.batch([{'sql':stamp_sql}])[0]['results'][0]['revision']
    last=store.batch([{'sql':"SELECT MAX(row_index) AS n FROM records WHERE table_name='readings'"}])[0]['results'][0]['n']
    readings=[]
    for start in range(0,(last or 0)+1,2000):
        results=store.batch([{'sql':"SELECT content FROM records WHERE table_name='readings' AND row_index>=? AND row_index<? ORDER BY row_index",'params':[offset,offset+500]} for offset in range(start,min(start+2000,last+1),500)])
        for result in results:readings.extend(json.loads(row['content']) for row in result['results'])
        print('Read current D1 samples:',len(readings),flush=True)
    reference=ranges(readings)
    views=store.batch([{'sql':"SELECT view_key,content FROM fp_v_processed_results WHERE dataset_id=? AND view_key LIKE 'history/%'",'params':[version]}])[0]['results']
    writes=[]
    for view in views:
        body=json.loads(view['content']);body['reference_ranges']=reference.get(body['equipment_id'],{})
        body['reference_dataset_version']=version
        writes.append({'sql':f"UPDATE fp_computed_views SET content=? WHERE dataset_id=? AND view_key=? AND content=? AND ({stamp_sql})=? AND (SELECT value FROM settings WHERE key='last_sync_at')=?",'params':[json.dumps(body,ensure_ascii=False,separators=(',',':')),version,view['view_key'],view['content'],stamp,version]})
    store.batch(writes)
    # D1 meta.changes includes trigger writes; verify actual published values instead.
    checks=store.batch([{'sql':"SELECT COUNT(*) AS n FROM fp_v_processed_results WHERE dataset_id=? AND view_key=? AND json_extract(content,'$.reference_ranges')=json(?)",'params':[version,view['view_key'],json.dumps(reference.get(json.loads(view['content'])['equipment_id'],{}),ensure_ascii=False,separators=(',',':'))]} for view in views])
    if any(row['results'][0]['n']!=1 for row in checks):raise RuntimeError('Source changed during publication; refresh reference ranges before claiming completion')
    print(json.dumps({'published_histories':len(writes),'reference_devices':len(reference),'source_readings':len(readings),'dataset_version':version},ensure_ascii=False))
if __name__=='__main__':main()
