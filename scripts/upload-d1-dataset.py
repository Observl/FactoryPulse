"""Publish the hash-verified frozen fixture to D1; no local database is opened."""
import hashlib
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.d1_identity import D1Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'.secrets/business.json')
    parser.add_argument('--batch-rows',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.batch_rows<=1000:parser.error('--batch-rows must be between 1 and 1000')
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    token = Path(config['token_file'])
    config['token_file'] = str(token if token.is_absolute() else config_path.parent / token)
    store = D1Store(config)
    if store.batch([{'sql':"SELECT name FROM sqlite_master WHERE name='database_schema'"}])[0]['results']:
        # Initialization and UPSERT target the physical source archive tables;
        # SQLite cannot apply ON CONFLICT to the legacy compatibility views.
        from backend.d1_business import identifiers
        from backend.database_v2_runtime import AUXILIARY
        original_batch=store.batch
        mapping={name:AUXILIARY[name][0] for name in ('fp_datasets','fp_dataset_records','fp_app_settings')}
        store.batch=lambda statements:original_batch([{**item,'sql':identifiers(item['sql'],mapping)} for item in statements])
    folder = ROOT / 'data/model-validation'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    raw = (folder / 'dataset.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256'], 'Frozen dataset hash mismatch'
    payload = json.loads(raw)
    version = manifest['dataset_id']
    store.batch([
        {'sql': 'CREATE TABLE IF NOT EXISTS fp_dataset_records(dataset_id TEXT NOT NULL,table_name TEXT NOT NULL,row_index INTEGER NOT NULL,equipment_id TEXT,content TEXT NOT NULL,PRIMARY KEY(dataset_id,table_name,row_index))'},
        {'sql': 'CREATE INDEX IF NOT EXISTS fp_dataset_equipment ON fp_dataset_records(dataset_id,table_name,equipment_id,row_index)'},
        {'sql': 'CREATE TABLE IF NOT EXISTS fp_datasets(dataset_id TEXT PRIMARY KEY,manifest TEXT NOT NULL,source_date TEXT NOT NULL,ready INTEGER NOT NULL DEFAULT 0)'},
        {'sql': 'CREATE TABLE IF NOT EXISTS fp_app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)'},
    ])
    existing = store.batch([{'sql': 'SELECT ready,manifest FROM fp_datasets WHERE dataset_id=?', 'params': [version]}])[0]['results']
    if existing and existing[0]['ready']:
        assert json.loads(existing[0]['manifest'])['sha256'] == manifest['sha256']
        print('Already published; verifying counts.', flush=True)
    else:
        store.batch([{'sql': 'INSERT INTO fp_datasets(dataset_id,manifest,source_date) VALUES(?,?,?) ON CONFLICT(dataset_id) DO UPDATE SET manifest=excluded.manifest,source_date=excluded.source_date', 'params': [version, json.dumps(manifest, ensure_ascii=False), payload['source_date']]}])
        for name, rows in payload['tables'].items():
            # Each request is atomic and idempotent. The version is invisible until ready=1.
            for start in range(0, len(rows), args.batch_rows):
                chunk = rows[start:start+args.batch_rows]
                statements=[]
                for offset in range(0,len(chunk),15):
                    part=chunk[offset:offset+15]
                    params=[]
                    for index,row in enumerate(part,start+offset):
                        params.extend([version,name,index,str(row.get('equipment_id','')),json.dumps(row,ensure_ascii=False,separators=(',',':'))])
                    statements.append({'sql':'INSERT INTO fp_dataset_records VALUES '+','.join('(?,?,?,?,?)' for _ in part)+' ON CONFLICT(dataset_id,table_name,row_index) DO UPDATE SET equipment_id=excluded.equipment_id,content=excluded.content','params':params})
                store.batch(statements)
                if start % 5000 == 0: print(f'{name}: {min(start+args.batch_rows,len(rows))}/{len(rows)}',flush=True)
    actual = store.batch([{'sql': 'SELECT table_name,COUNT(*) AS n FROM fp_dataset_records WHERE dataset_id=? GROUP BY table_name', 'params': [version]}])[0]['results']
    assert {r['table_name']:r['n'] for r in actual} == {k:len(v) for k,v in payload['tables'].items()}, 'Remote count mismatch'
    # Verify every uploaded row against the source, not only counts.
    for name, rows in payload['tables'].items():
        print('Verifying '+name,flush=True)
        for start in range(0,len(rows),500):
            result=store.batch([{'sql':'SELECT content FROM fp_dataset_records WHERE dataset_id=? AND table_name=? ORDER BY row_index LIMIT 500 OFFSET ?', 'params':[version,name,start]}])[0]['results']
            assert [json.loads(r['content']) for r in result] == rows[start:start+500], f'Remote content mismatch: {name}/{start}'
    store.batch([
        {'sql':'UPDATE fp_datasets SET ready=1 WHERE dataset_id=?','params':[version]},
        {'sql':"INSERT INTO fp_app_settings VALUES('default_dataset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",'params':[version]},
    ])
    print(json.dumps({'verified':True,'dataset_id':version,'database_id':config['database_id'],'counts':{r['table_name']:r['n'] for r in actual}},ensure_ascii=False),flush=True)


if __name__ == '__main__': main()
