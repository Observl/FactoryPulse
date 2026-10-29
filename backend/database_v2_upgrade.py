"""Atomic in-place V1 -> V2 SQL plan; database UUID and existing API names survive."""
import re
from .database_v2 import INPUTS, OPERATIONS, schema_statements
from .database_v2_runtime import AUXILIARY


def quote(name):
    return '"'+name.replace('"','""')+'"'


def upgrade_statements(objects, source_revision):
    existing={row['name']:row for row in objects}
    if 'database_schema' in existing:
        raise ValueError('Database already has a versioned schema; refusing to overwrite')
    if existing.get('records',{}).get('type')!='table':
        raise ValueError('Not a V1 business database')
    if any(name.startswith('_v1_backup_') for name in existing):
        raise ValueError('Existing migration backup found; audit before continuing')
    plan=[
        {'sql':'CREATE TABLE schema_upgrade_guard(id INTEGER PRIMARY KEY CHECK(id=1))'},
        {'sql':'INSERT INTO schema_upgrade_guard(id) SELECT 0 WHERE (SELECT revision FROM fp_business_revision WHERE id=1)<>?','params':[source_revision]},
    ]
    # Drop V1 cache triggers only inside the same transaction; no interval exists
    # in which a public write can escape both old and new revision protection.
    for row in objects:
        if row['type']=='trigger':plan.append({'sql':'DROP TRIGGER '+quote(row['name'])})
    reused={old:target for old,(target,_,_) in AUXILIARY.items() if old in existing}
    reused.update({old:target for old,(target,_,_) in OPERATIONS.items() if old in existing})
    reused_targets=set(reused.values())
    all_sql=schema_statements()
    aliases=set(AUXILIARY)|set(OPERATIONS)|{'records','fp_computed_views','fp_computed_freshness','fp_v_data_source','fp_v_record_counts','fp_v_processed_results'}
    deferred=[]
    loaders=[]
    for sql in all_sql:
        stripped=re.sub(r'(?m)^\s*--[^\n]*','',sql).strip()
        table=re.match(r'CREATE TABLE (\w+)',stripped,re.I)
        if table and table[1] in reused_targets:continue
        init=re.match(r'INSERT INTO (\w+)',stripped,re.I)
        if init and init[1] in reused_targets:continue
        view=re.match(r'CREATE VIEW (\w+)',stripped,re.I)
        trigger=re.match(r'CREATE TRIGGER (\w+).*?INSTEAD OF (INSERT|UPDATE|DELETE) ON (\w+)',stripped,re.I|re.S)
        index=re.match(r'CREATE (?:UNIQUE )?INDEX (?:IF NOT EXISTS )?\w+ ON (\w+)',stripped,re.I)
        if index and index[1] in reused_targets:
            if 'IF NOT EXISTS' in stripped.upper():deferred.append(sql)
            continue
        if view:
            deferred.append(sql);continue
        if trigger:
            deferred.append(sql)
            if trigger[2].upper()=='INSERT' and trigger[3]=='records' and trigger[1].startswith('records_insert_'):
                loaders.append(sql.replace('CREATE TRIGGER '+trigger[1],'CREATE TRIGGER load_'+trigger[1],1).replace(' ON records ', ' ON v2_load_records ',1))
            continue
        if re.match(r'CREATE TRIGGER\b',stripped,re.I):
            deferred.append(sql);continue
        plan.append({'sql':sql})
    # Build normalized current inputs directly inside D1, without sending the
    # 34,560 samples to an AI or back through one network request per sample.
    plan.append({'sql':'CREATE VIEW v2_load_records AS SELECT table_name,row_index,content FROM records WHERE 0'})
    plan.extend({'sql':sql} for sql in loaders)
    for logical in INPUTS:
        plan.append({'sql':'INSERT INTO v2_load_records SELECT table_name,row_index,content FROM records WHERE table_name=?','params':[logical]})
    plan.append({'sql':"INSERT INTO v2_load_records SELECT table_name,row_index,content FROM records WHERE table_name='demo_risks'"})
    plan.append({'sql':'DROP VIEW v2_load_records'})
    # Check exact entity counts before any legacy name is released.
    for logical,(table,_,_) in INPUTS.items():
        plan.append({'sql':f'INSERT INTO schema_upgrade_guard(id) SELECT 0 WHERE (SELECT COUNT(*) FROM records WHERE table_name=?)<>(SELECT COUNT(*) FROM {table})','params':[logical]})
    if 'fp_computed_views' in existing:
        freshness='LEFT JOIN fp_computed_freshness f USING(dataset_id,view_key)' if 'fp_computed_freshness' in existing else ''
        from .data_sync import DATA_INPUTS
        old_inputs=','.join("'"+name+"'" for name in DATA_INPUTS)
        old_stamp=f'(SELECT COALESCE(SUM(revision),0) FROM fp_resource_revisions WHERE resource IN ({old_inputs}))'
        new_stamp="(SELECT COALESCE(SUM(revision),0) FROM fp_resource_revisions WHERE resource IN ('records/readings','settings/dataset'))"
        stamp=f'CASE WHEN f.input_revision={old_stamp} THEN {new_stamp} ELSE -1 END' if freshness else '-1'
        plan.append({'sql':f'INSERT INTO calculation_history(dataset_id,result_type,input_revision,evidence) SELECT c.dataset_id,c.view_key,{stamp},c.content FROM fp_computed_views c {freshness}'})
    for row in objects:
        if row['type']=='view':plan.append({'sql':'DROP VIEW '+quote(row['name'])})
    for old,target in reused.items():
        plan.append({'sql':f'ALTER TABLE {quote(old)} RENAME TO {quote(target)}'})
        if old in OPERATIONS:
            payload=OPERATIONS[old][2]
            if payload:plan.append({'sql':f'ALTER TABLE {quote(target)} RENAME COLUMN content TO {payload}'})
            plan.append({'sql':f'ALTER TABLE {quote(target)} ADD COLUMN attributes TEXT NOT NULL DEFAULT \'{{}}\''})
    # Derived settings are supplied by the settings view, not stored counters.
    plan.append({'sql':"DELETE FROM business_settings WHERE key IN ('record_count','device_count')"})
    # Free compatibility names without copying or retaining the old database.
    # These transient tables are dropped before this atomic batch commits.
    obsolete=['records']
    plan.append({'sql':'ALTER TABLE records RENAME TO _v2_obsolete_records'})
    for name in ('fp_computed_views','fp_computed_freshness'):
        if name in existing:
            obsolete.append(name)
            plan.append({'sql':'ALTER TABLE '+quote(name)+' RENAME TO '+quote('_v2_obsolete_'+name)})
    # Historical run and approved plan evidence is retained; current caches are
    # replaced by input-revision-filtered projections over calculation_history.
    plan.extend({'sql':sql} for sql in deferred)
    plan.extend({'sql':'DROP TABLE '+quote('_v2_obsolete_'+name)} for name in obsolete)
    plan.append({'sql':"UPDATE database_schema SET migration_state='ready' WHERE version=2"})
    plan.append({'sql':'DROP TABLE schema_upgrade_guard'})
    return plan


