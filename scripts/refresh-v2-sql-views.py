"""Refresh optimized V2 SQL projections only; does not modify business facts."""
import json,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.database_v2 import schema_statements
from backend.d1_identity import D1Store
p=ROOT/'.secrets/business.json';c=json.loads(p.read_text(encoding='utf-8'));c['token_file']=str(p.parent/c['token_file'])
store=D1Store(c)
assert store.batch([{'sql':'SELECT version,migration_state FROM database_schema'}])[0]['results']==[{'version':2,'migration_state':'ready'}]
names={'v_equipment_latest_reading','v_reading_metrics','fp_v_record_counts','v_dashboard_devices'}
batch=[]
for sql in schema_statements():
    match=re.search(r'CREATE VIEW (\w+)',sql)
    if match and match[1] in names:batch.extend([{'sql':'DROP VIEW '+match[1]},{'sql':sql}])
assert len(batch)==len(names)*2
store.batch(batch)
print(json.dumps({'updated_views':sorted(names),'business_facts_changed':False}))
