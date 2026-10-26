"""Add revision triggers and read views to the configured D1; never open SQLite."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.d1_business import configuration
from backend.d1_identity import D1Store
from backend.data_sync import schema_statements

def main():
    store=D1Store(configuration())
    names=store.batch([{'sql':"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_fp_tx_%'"}])[0]['results']
    tables={}
    for row in names:
        name=row['name']
        if name=='database_schema':tables[name]=['version','installed_at','migration_state'];continue
        if name not in {'records','settings','alerts','work_orders','dataset_versions','maintenance_events','audit_events','fp_computed_views','inventory_stock','inventory_reservations','prediction_runs'}:continue
        tables[name]=[field['name'] for field in store.batch([{'sql':f'PRAGMA table_info("{name}")'}])[0]['results']]
    statements=schema_statements(tables)
    # One atomic D1 batch: source writes cannot fall between revision-trigger installation and the baseline.
    store.batch([{'sql':sql} for sql in statements])
    check=store.batch([{'sql':"SELECT name,type FROM sqlite_master WHERE name IN ('fp_v_record_counts','fp_v_data_source','fp_v_processed_results','fp_resource_revisions') ORDER BY name"},{'sql':'SELECT * FROM fp_v_data_source'}])
    print(json.dumps({'installed':len(statements),'objects':check[0]['results'],'summary':check[1]['results']},ensure_ascii=False))

if __name__=='__main__':main()
