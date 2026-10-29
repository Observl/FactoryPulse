"""Install bounded-read indexes into an existing ready V2 D1; no fact replacement."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.d1_business import configuration
from backend.d1_identity import D1Store
store=D1Store(configuration())
state=store.batch([{'sql':'SELECT version,migration_state FROM database_schema WHERE version=2'}])[0]['results']
if not state or state[0]['migration_state']!='ready':raise RuntimeError('V2 migration must be ready')
statements=[{'sql':part.strip()} for part in (ROOT/'deploy/d1-read-indexes.sql').read_text(encoding='utf-8').split(';') if part.strip()]
store.batch(statements)
print(json.dumps({'indexes_installed':len(statements),'business_facts_changed':False}))
