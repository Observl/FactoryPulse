"""Upgrade the live business D1 atomically in place, without exports or backups."""
import argparse
import json
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.database_v2_upgrade import upgrade_statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'.secrets/business.json')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if config['database_id'] != 'abc7cb74-5be4-49a2-827a-3bd8b639f257':
        raise ValueError('Expected the authorized business database, not identity')
    token = Path(config['token_file'])
    if not token.is_absolute(): token = args.config.resolve().parent/token
    url = f"https://api.cloudflare.com/client/v4/accounts/{config['account_id']}/d1/database/{config['database_id']}/query"
    with httpx.Client(timeout=120) as client:
        def batch(statements):
            response = client.post(url, headers={'Authorization':'Bearer '+token.read_text(encoding='utf-8').strip()}, json={'batch':statements})
            body = response.json()
            if not response.is_success or not body.get('success') or any(not x.get('success') for x in body.get('result', [])):
                raise RuntimeError('D1 refused the operation: '+json.dumps(body.get('errors', []),ensure_ascii=False))
            return body['result']
        def read(sql): return batch([{'sql':sql}])[0]['results']
        objects = read("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
        if any(x['name']=='database_schema' for x in objects):
            print(json.dumps({'already_versioned':read('SELECT * FROM database_schema'),'backup_created':False},ensure_ascii=False));return
        revision = read('SELECT revision FROM fp_business_revision WHERE id=1')[0]['revision']
        names = {x['name'] for x in objects}
        if any(n.startswith(('_fp_tx_', '_fp_import_')) for n in names):
            raise RuntimeError('An active transaction/import workspace requires completion first')
        unknown = read("SELECT DISTINCT table_name FROM records WHERE table_name NOT IN ('equipment','readings','maintenance_rules','maintenance_history','staff','orders','scenarios','demo_risks')")
        if unknown: raise RuntimeError('Unknown logical record categories; refusing to discard them')
        counts = read('SELECT table_name,COUNT(*) AS record_count FROM records GROUP BY table_name')
        plan = upgrade_statements(objects,revision)
        print(json.dumps({'database_id':config['database_id'],'source_revision':revision,'counts':counts,'statements':len(plan),'backup_created':False,'applying':args.apply},ensure_ascii=False),flush=True)
        if not args.apply:return
        # One request, one atomic D1 batch. Never automatically retry a mutation.
        batch(plan)
        result = {'schema':read('SELECT * FROM database_schema'), 'counts':read('SELECT * FROM fp_v_record_counts'),
                  'foreign_key_errors':read('PRAGMA foreign_key_check'),
                  'retained_old_tables':read("SELECT name FROM sqlite_master WHERE name GLOB '_v1_backup_*' OR name GLOB '_v2_obsolete_*'"),
                  'backup_created':False,'database_id':config['database_id']}
        if result['foreign_key_errors'] or result['retained_old_tables']: raise RuntimeError('Post-migration integrity validation failed')
        report = ROOT/'outputs/database-v2/live-upgrade.json'
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
