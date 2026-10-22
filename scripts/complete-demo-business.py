"""Complete only simulated business resources in a named local dataset, with backup."""
import argparse,hashlib,json,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.demo_business import complete_demo_business
from backend.resources import StaffInput,OrderInput,ScenarioInput,RequirementInput
parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True);args=parser.parse_args()
p=args.database.resolve()
if not p.is_file():raise SystemExit('Database does not exist')
c=sqlite3.connect(p);c.row_factory=sqlite3.Row
origin=c.execute("SELECT value FROM settings WHERE key='data_origin'").fetchone()[0]
if origin not in {'SYNTHETIC_CNC_DEMO','UCI_METROPT3_REAL_OPERATIONAL'}:raise SystemExit('Refusing to replace business inputs of a user-imported dataset')
data={name:[json.loads(row[0]) for row in c.execute('SELECT content FROM records WHERE table_name=? ORDER BY row_index',(name,))] for name in ['equipment','readings','maintenance_rules','maintenance_history','staff','orders','scenarios']}
if not data['equipment'] or not data['scenarios']:raise SystemExit('Dataset is incomplete; cannot infer its base scenario')
complete_demo_business(data)
for r in data['maintenance_rules']:RequirementInput(**r)
for r in data['staff']:StaffInput(**{**r,'skills':r['skills'].split(',')})
for r in data['orders']:OrderInput(**r)
for r in data['scenarios']:ScenarioInput(**r)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out=Path('outputs')/('dataset-completion-'+stamp);out.mkdir(parents=True,exist_ok=False)
backup=out/'before.sqlite3'
with sqlite3.connect(backup) as dest:c.backup(dest)
def fingerprint(tables):
 h=hashlib.sha256()
 for table in tables:
  for row in c.execute('SELECT content FROM records WHERE table_name=? ORDER BY row_index',(table,)):h.update(row[0].encode())
 return h.hexdigest()
before=fingerprint(['readings','maintenance_history'])
c.execute('BEGIN IMMEDIATE')
try:
 for table in ['maintenance_rules','staff','orders','scenarios']:
  c.execute('DELETE FROM records WHERE table_name=?',(table,))
  c.executemany('INSERT INTO records VALUES (?,?,?)',[(table,i,json.dumps(row,ensure_ascii=False)) for i,row in enumerate(data[table])])
 scope_row=c.execute("SELECT value FROM settings WHERE key='inventory_scope'").fetchone() or c.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
 scope=scope_row[0] if scope_row else 'uninitialized'
 parts={part['part_name']:part['available_quantity'] for rule in data['maintenance_rules'] for part in rule.get('spare_parts',[])}
 for name,count in parts.items():
  existing=c.execute('SELECT on_hand,version,source FROM inventory_stock WHERE scope=? AND part_name=?',(scope,name)).fetchone()
  if existing and existing['source'] not in {'legacy_unverified','simulated_count'}:continue
  previous=existing['on_hand'] if existing else 0
  c.execute('INSERT OR REPLACE INTO inventory_stock VALUES (?,?,?,?,?,?)',(scope,name,count,(existing['version'] if existing else 0)+1,datetime.now(timezone.utc).isoformat(),'simulated_count'))
  c.execute('INSERT INTO inventory_movements VALUES (?,?,?,?,?,?,?,?)',('demo-'+stamp+'-'+str(len(name)),scope,name,None,'simulated_count',count-previous,'模拟初始库存，用于程序流程演练；非企业实盘',datetime.now(timezone.utc).isoformat()))
 revision=c.execute("SELECT value FROM settings WHERE key='business_revision'").fetchone()
 c.execute("INSERT OR REPLACE INTO settings VALUES ('business_revision',?)",(str(int(revision[0] if revision else '0')+1),))
 c.execute("INSERT OR REPLACE INTO settings VALUES ('demo_business_profile',?)",(stamp,))
 c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",('demo_business_completed',origin,json.dumps({'data_origin':'SIMULATED_BUSINESS_DATA','backup':str(backup.resolve()),'monitoring_unchanged':True},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
 assert fingerprint(['readings','maintenance_history'])==before
 c.commit()
except BaseException:c.rollback();raise
manifest={'database':str(p),'origin':origin,'monitoring_fingerprint':before,'monitoring_unchanged':True,'backup':str(backup.resolve()),'business_origin':'SIMULATED_BUSINESS_DATA','resources':{name:data[name] for name in ['maintenance_rules','staff','orders','scenarios']}}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'output':str(out.resolve()),'origin':origin,'equipment':len(data['equipment']),'staff':len(data['staff']),'monitoring_unchanged':True},ensure_ascii=False))
