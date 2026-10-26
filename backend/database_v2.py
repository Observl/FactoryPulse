"""Fact-only D1 schema and loss-accounted migration into an EMPTY target database.

No production connection or import-time migration. SQL views are evaluated on read.
Unknown business fields are preserved as attributes, never silently discarded.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'deploy/d1-business-v2.sql'

# Logical input name -> readable physical table, business key, original fields.
INPUTS = {
    'equipment': ('equipment', 'equipment_id', ['equipment_id', 'equipment_name', 'equipment_type', 'status', 'production_line', 'required_skill', 'data_origin']),
    'readings': ('sensor_readings', 'reading_id', ['reading_id', 'equipment_id', 'timestamp', 'air_temperature_k', 'process_temperature_k', 'rotational_speed_rpm', 'torque_nm', 'tool_wear_min', 'vibration_mm_s', 'spindle_load_pct', 'motor_current_a', 'oil_temperature_c', 'failure', 'label_status', 'data_origin']),
    'maintenance_rules': ('maintenance_requirements', 'equipment_id', ['equipment_id', 'inspection_cost_cny', 'repair_cost_cny', 'inspection_duration_h', 'repair_duration_h', 'required_staff_count', 'required_skill', 'assumed_failure_loss_cny', 'window_start', 'window_end', 'configuration_status', 'data_origin']),
    'maintenance_history': ('maintenance_history', 'maintenance_id', ['maintenance_id', 'equipment_id', 'maintenance_type', 'failure_at', 'failure_end', 'maintenance_date', 'data_origin']),
    'staff': ('maintenance_staff', 'staff_id', ['staff_id', 'staff_name', 'skills', 'available_hours', 'shift_start', 'shift_end', 'data_origin']),
    'orders': ('production_orders', 'order_id', ['order_id', 'equipment_id', 'order_name', 'start_at', 'end_at', 'due_at', 'delay_cost_cny_per_hour', 'data_origin']),
    'scenarios': ('maintenance_scenarios', 'scenario_id', ['scenario_id', 'scenario_name', 'maintenance_budget_cny', 'available_staff_count', 'max_downtime_h', 'risk_threshold', 'assumed_failure_probability', 'data_origin']),
}

# Immutable decisions/observations are retained even if their content has numbers.
OPERATIONS = {
    'work_orders': ('maintenance_work_orders', ['work_order_id', 'equipment_id', 'status', 'updated_at'], 'details'),
    'alerts': ('equipment_alert_reviews', ['alert_id', 'equipment_id', 'status', 'note', 'updated_at', 'dataset_version', 'prediction_at', 'defer_until', 'version'], None),
    'maintenance_events': ('maintenance_acceptance_records', ['work_order_id', 'dataset_version', 'equipment_id', 'verified_at'], 'details'),
    'planning_runs': ('schedule_decision_history', ['plan_id', 'dataset_version', 'business_revision', 'created_at'], 'evidence'),
    'prediction_runs': ('model_run_history', ['run_id', 'dataset_version', 'model_version', 'created_at'], 'evidence'),
    'audit_events': ('business_audit_log', ['event_id', 'event_type', 'entity_id', 'created_at'], 'details'),
    'operation_requests': ('operation_receipts', ['request_id', 'request_content', 'response'], None),
    'inventory_stock': ('spare_part_stock', ['scope', 'part_name', 'on_hand', 'version', 'counted_at', 'source'], None),
    'inventory_reservations': ('spare_part_reservations', ['work_order_id', 'scope', 'part_name', 'quantity', 'state'], None),
    'inventory_movements': ('spare_part_movements', ['movement_id', 'scope', 'part_name', 'work_order_id', 'movement_type', 'quantity', 'note', 'created_at'], None),
}
PUBLIC_SETTINGS = {'last_sync_at', 'inventory_scope', 'source_name', 'source_date', 'data_origin', 'source_url', 'sensor_catalog', 'field_profile_config', 'data_lineage'}
CACHE_TABLES = {'fp_computed_views', 'fp_computed_freshness'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def schema_statements():
    # Schema deliberately has no triggers or procedural bodies; each delimiter is SQL.
    from .database_v2_runtime import runtime_statements
    return [part.strip() for part in SCHEMA_PATH.read_text(encoding='utf-8').split(';') if part.strip()] + runtime_statements()


def normalized_time(value):
    if value in (None, ''):
        return None
    instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone(timedelta(hours=8)))
    return instant.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def statement(table, data):
    return {'sql': f'INSERT INTO "{table}" ({",".join(data)}) VALUES ({",".join("?" for _ in data)})', 'params': list(data.values())}


def migrate_input(name, original):
    table, key, fields = INPUTS[name]
    row = dict(original)
    if row.get(key) in (None, ''):
        raise ValueError(f'{name}: missing {key}; migration stopped, no synthetic ID assigned')
    result = {field: row.pop(field, None) for field in fields}
    if name == 'staff' and isinstance(result['skills'], list):
        result['skills'] = encoded(result['skills'])
    removed = []
    if name == 'readings':
        # Future labels must be regenerated against an explicitly chosen horizon.
        for field in ('future_failure',):
            if field in row:
                removed.append(field)
                row.pop(field)
    elif name == 'maintenance_rules':
        # A user-entered total may differ from the original component sum. Preserve
        # it as an INPUT override; delete only demonstrably redundant totals.
        for total, a, b, override in (
            ('maintenance_hours', 'inspection_duration_h', 'repair_duration_h', 'duration_override_h'),
            ('maintenance_cost_cny', 'inspection_cost_cny', 'repair_cost_cny', 'cost_override_cny'),
        ):
            value = row.pop(total, None)
            same = value is not None and result[a] is not None and result[b] is not None and math.isclose(float(value), float(result[a]) + float(result[b]), rel_tol=1e-10, abs_tol=1e-8)
            result[override] = None if same else value
            if same:
                removed.append(total)
        parts = row.pop('spare_parts', [])
        # Do not duplicate normalized part quantities. Retain only extra source
        # inputs (e.g. legacy availability) for operator reconciliation.
        extra_parts = [{key: value for key, value in part.items() if key != 'quantity'}
                       for part in parts if set(part)-{'part_name','quantity'}]
        if extra_parts:
            row['legacy_part_inputs'] = extra_parts
    elif name == 'maintenance_history':
        value = row.pop('downtime_hours', None)
        start, end = normalized_time(result['failure_at']), normalized_time(result['failure_end'])
        same = value is not None and start is not None and end is not None and math.isclose(float(value), (datetime.fromisoformat(end.replace('Z', '+00:00'))-datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds()/3600, abs_tol=1e-8)
        result['observed_downtime_h'] = None if same else value
        if same:
            removed.append('downtime_hours')
    for field in result:
        if field in {'timestamp', 'window_start', 'window_end', 'failure_at', 'failure_end', 'maintenance_date', 'shift_start', 'shift_end', 'start_at', 'end_at', 'due_at'}:
            result[field] = normalized_time(result[field])
    result['attributes'] = encoded(row)
    return table, result, removed


def build_migration(source):
    """Source is a complete business-table export; return statements and accounting.

    Export is mandatory for rollback. Non-active archives/control data remain in
    that export, not copied into the current facts schema as redundant snapshots.
    """
    if not isinstance(source.get('records'), list) or not source['records']:
        raise ValueError('Source has no active records')
    settings = {r['key']: r['value'] for r in source.get('settings', [])}
    if not settings.get('last_sync_at'):
        raise ValueError('Missing current dataset identity')
    statements = []
    counts, removals = {}, {}
    ordinals = {}
    for record in source['records']:
        name = record['table_name']
        if name == 'demo_risks':
            removals['demo_risks rows'] = removals.get('demo_risks rows', 0) + 1
            continue
        if name not in INPUTS:
            raise ValueError(f'Unmapped active logical table: {name}')
        table, row, dropped = migrate_input(name, json.loads(record['content']))
        row['record_index'] = record.get('row_index', ordinals.get(name, 0))
        ordinals[name] = ordinals.get(name, 0) + 1
        statements.append(statement(table, row))
        counts[table] = counts.get(table, 0) + 1
        for field in dropped:
            label = name + '.' + field
            removals[label] = removals.get(label, 0) + 1
        if name == 'maintenance_rules':
            parts = json.loads(record['content']).get('spare_parts', [])
            seen = set()
            for part in parts:
                if part['part_name'] in seen:
                    raise ValueError('Duplicate spare part requirement; reconcile before migration')
                seen.add(part['part_name'])
                statements.append(statement('maintenance_required_parts', {'equipment_id': row['equipment_id'], 'part_name': part['part_name'], 'quantity': part['quantity']}))
                counts['maintenance_required_parts'] = counts.get('maintenance_required_parts', 0) + 1
    for old, (table, fields, payload) in OPERATIONS.items():
        for original in source.get(old, []):
            rest = dict(original)
            data = {field: rest.pop(field, None) for field in fields}
            if payload:
                content = json.loads(rest.pop('content', '{}'))
                for field in fields:
                    content.pop(field, None)
                for field in ('start_at', 'end_at', 'actual_start_at', 'actual_finish_at', 'deleted_at'):
                    if content.get(field):
                        content[field] = normalized_time(content[field])
                data[payload] = encoded(content)
            # Retain unknown columns instead of silently dropping business facts.
            data['attributes'] = encoded(rest)
            for field in ('updated_at', 'verified_at', 'created_at', 'prediction_at', 'defer_until', 'counted_at'):
                if field in data:
                    data[field] = normalized_time(data[field])
            statements.append(statement(table, data))
            counts[table] = counts.get(table, 0) + 1
    excluded = {'record_count','device_count','api_key','token','password','credential_key'}
    for key in sorted(settings.keys()-excluded):
        statements.append(statement('business_settings', {'key': key, 'value': settings[key]}))
    from .database_v2_runtime import AUXILIARY
    migrated = {'records','settings',*OPERATIONS}
    for old,(table,columns,keys) in AUXILIARY.items():
        if old=='settings':continue
        migrated.add(old)
        for original in source.get(old,[]):
            row={key:original[key] for key in columns}
            item=statement(table,row)
            updates=[key for key in columns if key not in keys]
            item['sql'] += ' ON CONFLICT('+','.join(keys)+') '+('DO UPDATE SET '+','.join(f'{key}=excluded.{key}' for key in updates) if updates else 'DO NOTHING')
            statements.append(item)
            counts[table]=counts.get(table,0)+1
    from .data_sync import DATA_INPUTS
    revision=sum(int(r['revision']) for r in source.get('fp_resource_revisions',[]) if r['resource'] in DATA_INPUTS)
    model_revision=sum(int(r['revision']) for r in source.get('fp_resource_revisions',[]) if r['resource'] in ('records/readings','settings/dataset'))
    freshness={(r['dataset_id'],r['view_key']):r['input_revision'] for r in source.get('fp_computed_freshness',[])}
    for row in source.get('fp_computed_views',[]):
        stamp=model_revision if freshness.get((row['dataset_id'],row['view_key']),-1)==revision else -1
        statements.append(statement('calculation_history',{'dataset_id':row['dataset_id'],'result_type':row['view_key'],'input_revision':stamp,'evidence':row['content'],'created_at':datetime.now(timezone.utc).isoformat()}))
        counts['calculation_history']=counts.get('calculation_history',0)+1
    migrated.update({'fp_computed_views','fp_computed_freshness'})
    retained_only_in_backup = {name: len(rows) for name, rows in source.items() if name not in migrated and rows}
    return statements, {'schema_version': 2, 'table_counts': counts, 'removed_recomputable_fields': removals, 'backup_only_tables': retained_only_in_backup, 'excluded_setting_keys': sorted(settings.keys() & excluded), 'source_input_revision':revision,'production_switched': False}
