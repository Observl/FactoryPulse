"""Build/verify the fact-only schema in an empty target. Never alters the source.

Default is an offline rehearsal using the frozen fixture. Remote writes require
--apply, an explicit target config and a different D1 UUID from the source.
No secrets or business row contents are printed.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.database_v2 import build_migration, schema_statements, encoded


def fixture_source():
    raw = (ROOT/'data/model-validation/dataset.json').read_bytes()
    manifest = json.loads((ROOT/'data/model-validation/manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('Frozen fixture checksum mismatch')
    fixture = json.loads(raw)
    return {
        'records': [{'table_name': name, 'row_index': index, 'content': encoded(row)} for name, rows in fixture['tables'].items() for index, row in enumerate(rows)],
        'settings': [{'key': 'last_sync_at', 'value': manifest['dataset_id']}, {'key': 'data_origin', 'value': 'SYNTHETIC_CNC_MODEL_VALIDATION_V1'}],
    }


def config(path):
    result = json.loads(path.read_text(encoding='utf-8'))
    token = Path(result['token_file'])
    result['token_file'] = str(token if token.is_absolute() else path.resolve().parent/token)
    return result


def remote_export(store):
    def read(sql, params=()):
        return store.batch([{'sql': sql, 'params': list(params)}])[0]['results']
    before = read('SELECT revision FROM fp_business_revision WHERE id=1')
    if len(before) != 1:
        raise ValueError('Missing revision guard; consistent export cannot be established')
    tables = read("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    result = {}
    for entry in tables:
        name = entry['name']
        # Business source only. Internal workspaces and auth secrets are excluded.
        if name.startswith(('auth_', '_fp_tx_', '_fp_import_')):
            continue
        quoted = '"'+name.replace('"', '""')+'"'
        info = read(f'PRAGMA table_info({quoted})')
        keys = [r['name'] for r in sorted(info, key=lambda r:r['pk']) if r['pk']]
        order = ','.join('"'+key.replace('"','""')+'"' for key in keys) or 'rowid'
        rows = []
        while True:
            page = read(f'SELECT * FROM {quoted} ORDER BY {order} LIMIT 500 OFFSET ?', [len(rows)])
            rows.extend(page)
            if len(page) < 500:
                break
        result[name] = rows
    if read('SELECT revision FROM fp_business_revision WHERE id=1') != before:
        raise ValueError('Source changed during export; retry in a maintenance window')
    return result


def rehearse(source, statements):
    # Explicit isolated SQL validation only, never application persistence.
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        for sql in schema_statements():
            db.execute(sql)
        # Resource inputs can have any source export ordering.
        db.execute('PRAGMA defer_foreign_keys=ON')
        for item in statements:
            db.execute(item['sql'], item['params'])
        errors = db.execute('PRAGMA foreign_key_check').fetchall()
        if errors:
            raise ValueError('Foreign-key verification failed')
        expected = {}
        for item in statements:
            table = item['sql'].split('"')[1]
            expected.setdefault(table, [])
        for table in expected:
            expected[table] = [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]
        summaries = {
            'counts': [dict(row) for row in db.execute('SELECT * FROM v_business_counts')],
            'data_quality': dict(db.execute('SELECT * FROM v_data_quality_summary').fetchone()),
            'views': [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")],
        }
    return expected, summaries


def apply_target(store, statements, expected):
    existing = store.batch([{'sql': "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'_cf_METADATA'"}])[0]['results']
    if existing:
        raise ValueError('Target must be empty; no overwrite/drop operation is supported')
    for sql in schema_statements():
        store.batch([{'sql': sql}])
    # Load parent tables first. D1 enforces FKs within each request.
    parent_order = {'equipment': 0, 'maintenance_requirements': 1, 'maintenance_required_parts': 2}
    ordered = sorted(statements, key=lambda item: parent_order.get(item['sql'].split('"')[1], 3))
    for offset in range(0, len(ordered), 40):
        store.batch(ordered[offset:offset+40])
    # Verify full field contents, not merely row counts, before marking ready.
    for table, rows in expected.items():
        actual = []
        info = store.batch([{'sql': f'PRAGMA table_info("{table}")'}])[0]['results']
        keys = [r['name'] for r in sorted(info, key=lambda r:r['pk']) if r['pk']]
        order = ','.join('"'+key+'"' for key in keys)
        while True:
            page = store.batch([{'sql': f'SELECT * FROM "{table}" ORDER BY {order} LIMIT 500 OFFSET ?', 'params': [len(actual)]}])[0]['results']
            actual.extend(page)
            if len(page) < 500:
                break
        canonical = lambda values: sorted(values, key=lambda row: encoded([row[key] for key in keys]))
        if canonical(actual) != canonical(rows):
            raise ValueError('Target read-back verification failed: '+table)
    store.batch([{'sql': "UPDATE database_schema SET migration_state='ready' WHERE version=2"}])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-config', type=Path, help='Explicit source D1 connection; absent uses synthetic fixture')
    parser.add_argument('--target-config', type=Path, help='Separate, empty D1 target connection')
    parser.add_argument('--apply', action='store_true', help='Actually write target only; source remains unchanged')
    parser.add_argument('--report', type=Path, default=ROOT/'outputs/database-v2/report.json')
    args = parser.parse_args()
    if args.apply and not args.target_config:
        parser.error('--apply requires --target-config')
    if args.target_config and not args.source_config:
        parser.error('Remote target requires --source-config; synthetic fixture is rehearsal-only')
    from backend.d1_identity import D1Store
    source_config = config(args.source_config) if args.source_config else None
    target_config = config(args.target_config) if args.target_config else None
    if target_config and target_config['database_id'] == source_config['database_id']:
        parser.error('Source and target must be different databases')
    source = remote_export(D1Store(source_config)) if source_config else fixture_source()
    statements, report = build_migration(source)
    expected, summaries = rehearse(source, statements)
    report.update({'validation': summaries, 'remote_applied': False, 'source': 'remote_business_export' if source_config else 'frozen_synthetic_fixture'})
    # Source backups are deliberately disabled by the user's migration policy.
    report['source_backup_created'] = False
    if args.apply:
        apply_target(D1Store(target_config), statements, expected)
        report['remote_applied'] = True
        report['target_database_id'] = target_config['database_id']
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(args.report), 'remote_applied': report['remote_applied'], 'production_switched': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
