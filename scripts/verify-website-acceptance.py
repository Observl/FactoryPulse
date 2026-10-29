"""Read-only postconditions for the explicitly authorized website acceptance run."""
import json
import sys
from pathlib import Path
from datetime import datetime,timezone
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.d1_identity import D1Store

base='https://factorypulse.griffonage2077.workers.dev'
folder=ROOT/'outputs/website-acceptance-20261028'
folder.mkdir(parents=True,exist_ok=True)
path=ROOT/'.secrets/business.json'
config=json.loads(path.read_text(encoding='utf-8'))
config['token_file']=str(path.parent/config['token_file'])
statements=[
 {'sql':"SELECT work_order_id,equipment_id,status,json_extract(details,'$.deleted_at') AS archived_at,json_extract(details,'$.actual_start_at') AS actual_start_at FROM maintenance_work_orders WHERE work_order_id=?",'params':['WO-DRAFT-9E1BEEED0F4D']},
 {'sql':'SELECT equipment_id,status,version FROM equipment_alert_reviews WHERE equipment_id=?','params':['VAL-CNC-009']},
 {'sql':'SELECT part_name,on_hand,version FROM spare_part_stock'},
 {'sql':"SELECT COUNT(*) AS active_reservations FROM spare_part_reservations WHERE state='reserved'"},
 {'sql':"SELECT COUNT(*) AS active_work_orders FROM maintenance_work_orders WHERE json_extract(details,'$.deleted_at') IS NULL"},
 {'sql':'SELECT version,migration_state FROM database_schema'},
]
results=[r['results'] for r in D1Store(config).batch(statements)]
assert results[0][0]['archived_at'] and results[0][0]['actual_start_at'] is None
assert results[1][0]['status']=='待确认'
assert len(results[2])==1 and results[2][0]['on_hand']==48 and results[2][0]['version']==1
assert results[3][0]['active_reservations']==0
assert results[4][0]['active_work_orders']==0
checks=[]
with httpx.Client(base_url=base,timeout=30) as client:
 for endpoint,expected in [('/',200),('/api/health',200),('/api/auth/status',200),('/api/overview',401),('/api/work-orders',401),('/api/resources/inventory',401)]:
  response=client.get(endpoint)
  assert response.status_code==expected,(endpoint,response.status_code)
  checks.append({'path':endpoint,'status':response.status_code,'expected':expected})
 response=client.post('/api/work-orders',headers={'Origin':'https://untrusted.invalid'},json={})
 assert response.status_code==403
 checks.append({'path':'POST /api/work-orders with untrusted origin','status':403,'expected':403})
report={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'authorized live acceptance postconditions; no database backup',
 'test_work_order':results[0][0],'alert':results[1][0],'inventory':results[2],
 'active_reservations':0,'active_work_orders':0,'schema':results[5][0],'http_checks':checks,
 'release':'eb94c72a-8d4d-404d-b453-534b49ee95b6'}
(folder/'postconditions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
