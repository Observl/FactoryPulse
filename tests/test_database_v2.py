"""Verify loss accounting and live-derived views in an isolated SQLite fixture."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from backend.database_v2 import build_migration, migrate_input, schema_statements

ROOT = Path(__file__).resolve().parents[1]


def migration_module():
    spec = importlib.util.spec_from_file_location('migration_v2', ROOT/'scripts/migrate-d1-business-v2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    with sqlite3.connect(':memory:') as connection:
        connection.row_factory = sqlite3.Row
        for statement in schema_statements():
            connection.execute(statement)
        yield connection


def test_raw_updates_change_views_without_refresh_and_keep_missing_data(db):
    db.execute("INSERT INTO equipment(equipment_id) VALUES('E1')")
    db.execute("INSERT INTO equipment(equipment_id) VALUES('E2')")
    db.execute("INSERT INTO sensor_readings(reading_id,equipment_id,timestamp,torque_nm) VALUES('R1','E1','2026-01-01T00:00:00.000000Z',20)")
    db.execute("INSERT INTO sensor_readings(reading_id,equipment_id,timestamp,torque_nm) VALUES('R2','E1','2026-01-01T01:00:00.000000Z',30)")
    assert db.execute("SELECT torque_nm FROM v_equipment_summary WHERE equipment_id='E1'").fetchone()[0] == 30
    assert db.execute("SELECT latest_sample_at FROM v_equipment_summary WHERE equipment_id='E2'").fetchone()[0] is None
    assert db.execute("SELECT gap_seconds FROM v_reading_gaps WHERE reading_id='R2'").fetchone()[0] == pytest.approx(3600, abs=.001)
    db.execute("UPDATE sensor_readings SET torque_nm=41 WHERE reading_id='R2'")
    assert db.execute("SELECT torque_nm FROM v_equipment_summary WHERE equipment_id='E1'").fetchone()[0] == 41


def test_inventory_reservations_are_scoped_and_shortage_not_hidden(db):
    db.execute("INSERT INTO business_settings VALUES('inventory_scope','S1')")
    db.execute("INSERT INTO spare_part_stock(scope,part_name,on_hand) VALUES('S1','P',3)")
    db.execute("INSERT INTO spare_part_stock(scope,part_name,on_hand) VALUES('S2','P',100)")
    db.execute("INSERT INTO spare_part_reservations(work_order_id,scope,part_name,quantity,state) VALUES('W1','S1','P',4,'reserved')")
    row = db.execute('SELECT * FROM v_current_spare_part_availability').fetchone()
    assert row['available_to_allocate'] == 0 and row['reservation_shortage'] == 1 and row['balance_after_reservations'] == -1
    db.execute("UPDATE spare_part_reservations SET state='released'")
    assert db.execute('SELECT available_to_allocate FROM v_current_spare_part_availability').fetchone()[0] == 3


def test_only_redundant_totals_removed_manual_override_preserved():
    original = dict(equipment_id='E1', inspection_duration_h=1, repair_duration_h=2, maintenance_hours=5,
                    inspection_cost_cny=100, repair_cost_cny=200, maintenance_cost_cny=300, custom_safety_note='preserve')
    _, row, removed = migrate_input('maintenance_rules', original)
    assert row['duration_override_h'] == 5
    assert row['cost_override_cny'] is None and 'maintenance_cost_cny' in removed
    assert json.loads(row['attributes'])['custom_safety_note'] == 'preserve'
    assert original['maintenance_hours'] == 5


def test_future_labels_removed_and_time_normalized_but_observed_failure_retained():
    _, row, removed = migrate_input('readings', dict(reading_id='R',equipment_id='E',timestamp='2026-01-01 08:00:00',
                                                   failure=1,future_failure=1,prediction_horizon_hours=168))
    assert row['timestamp'] == '2026-01-01T00:00:00.000000Z'
    assert row['failure'] == 1 and 'future_failure' in removed
    assert 'future_failure' not in row and 'future_failure' not in json.loads(row['attributes'])


def test_history_actual_downtime_override_is_not_erased():
    _, row, removed = migrate_input('maintenance_history', dict(maintenance_id='M',equipment_id='E',
        failure_at='2026-01-01 00:00:00',failure_end='2026-01-01 08:00:00',downtime_hours=5))
    assert row['observed_downtime_h'] == 5 and 'downtime_hours' not in removed


def test_invalid_or_unknown_active_data_blocks_migration():
    with pytest.raises(ValueError, match='Unmapped'):
        build_migration({'records':[{'table_name':'unknown','content':'{}'}], 'settings':[{'key':'last_sync_at','value':'v'}]})
    with pytest.raises(ValueError, match='missing reading_id'):
        migrate_input('readings', {'equipment_id':'E'})


def test_full_frozen_fixture_migrates_and_views_match_original(db):
    migration = migration_module()
    source = migration.fixture_source()
    statements, report = build_migration(source)
    db.execute('PRAGMA defer_foreign_keys=ON')
    for statement in statements:
        db.execute(statement['sql'], statement['params'])
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert db.execute('SELECT COUNT(*) FROM equipment').fetchone()[0] == 24
    assert db.execute('SELECT COUNT(*) FROM sensor_readings').fetchone()[0] == 34560
    assert report['removed_recomputable_fields']['readings.future_failure'] == 34560
    assert db.execute('SELECT duplicate_group_count FROM v_data_quality_summary').fetchone()[0] == 0
    for record in source['records']:
        old = json.loads(record['content'])
        if record['table_name'] == 'maintenance_rules':
            row = db.execute('SELECT * FROM v_maintenance_requirements WHERE equipment_id=?', [old['equipment_id']]).fetchone()
            assert row['maintenance_hours'] == old['maintenance_hours']
            assert row['maintenance_cost_cny'] == old['maintenance_cost_cny']
        elif record['table_name'] == 'maintenance_history':
            value = db.execute('SELECT downtime_hours FROM v_maintenance_history WHERE maintenance_id=?', [old['maintenance_id']]).fetchone()[0]
            assert value == pytest.approx(old['downtime_hours'], abs=1e-6)
    assert not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('fp_computed_views','records','demo_risks')").fetchall()


def test_work_order_history_and_receipts_retained_and_archive_not_counted(db):
    source = {'records':[{'table_name':'equipment','content':'{"equipment_id":"E"}'}],
              'settings':[{'key':'last_sync_at','value':'v'}],
              'work_orders':[{'work_order_id':'W','equipment_id':'E','status':'待验收','updated_at':'2026-01-01T00:00:00Z',
                              'content':'{"work_order_id":"W","actual_cost_cny":9,"start_at":"2026-01-01 08:00:00","end_at":"2026-01-01 10:00:00"}'}],
              'prediction_runs':[{'run_id':'P','dataset_version':'v','model_version':'m','created_at':'2026-01-01T00:00:00Z','content':'{"risk":0.6}'}]}
    statements, _ = build_migration(source)
    for statement in statements:
        db.execute(statement['sql'], statement['params'])
    assert json.loads(db.execute('SELECT details FROM maintenance_work_orders').fetchone()[0])['actual_cost_cny'] == 9
    assert json.loads(db.execute('SELECT evidence FROM model_run_history').fetchone()[0])['risk'] == .6
    assert db.execute('SELECT planned_duration_h FROM v_work_order_schedule').fetchone()[0] == pytest.approx(2)
    db.execute("UPDATE maintenance_work_orders SET details=json_set(details,'$.deleted_at','2026-01-02')")
    assert db.execute('SELECT * FROM v_work_order_counts').fetchall() == []


class IsolatedD1:
    """Exercise request batches and read-back checks without a cloud connection."""
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row

    def batch(self, statements):
        result = []
        with self.db:
            for item in statements:
                cursor = self.db.execute(item['sql'], item.get('params', []))
                result.append({'results': [dict(row) for row in cursor.fetchall()]})
        return result


def test_target_apply_refuses_nonempty_database():
    target = IsolatedD1()
    try:
        target.db.execute('CREATE TABLE valuable(id INTEGER PRIMARY KEY)')
        target.db.execute('INSERT INTO valuable VALUES(1)')
        target.db.commit()
        with pytest.raises(ValueError, match='empty'):
            migration_module().apply_target(target, [], {})
        assert target.db.execute('SELECT id FROM valuable').fetchone()[0] == 1
        assert not target.db.execute("SELECT name FROM sqlite_master WHERE name='database_schema'").fetchall()
    finally:
        target.db.close()


def test_target_ready_only_after_full_readback_verification():
    source = {'records':[{'table_name':'equipment','content':'{"equipment_id":"E","equipment_name":"Original"}'}],
              'settings':[{'key':'last_sync_at','value':'v'}]}
    migration = migration_module()
    statements, _ = build_migration(source)
    expected, _ = migration.rehearse(source, statements)
    target = IsolatedD1()
    broken = IsolatedD1()
    try:
        migration.apply_target(target, statements, expected)
        assert target.db.execute('SELECT migration_state FROM database_schema').fetchone()[0] == 'ready'
        expected['equipment'][0]['equipment_name'] = 'Unexpected'
        with pytest.raises(ValueError, match='read-back'):
            migration.apply_target(broken, statements, expected)
        assert broken.db.execute('SELECT migration_state FROM database_schema').fetchone()[0] == 'building'
    finally:
        target.db.close()
        broken.db.close()


def test_quality_returns_reusable_json_in_one_statement(db):
    from backend.sql_reports import data_quality
    db.execute("INSERT INTO equipment(equipment_id) VALUES('E1')")
    db.execute("INSERT INTO sensor_readings(reading_id,equipment_id,timestamp,motor_current_a,attributes) VALUES('R1','E1','2026-01-01T00:00:00Z',9,?)", (json.dumps({'_feature_fields':['motor_current_a']}),))
    class Tracked:
        statements=[]
        def execute(self,sql):
            self.statements.append(sql)
            return db.execute(sql)
    tracked=Tracked()
    result=data_quality(tracked)
    assert len(tracked.statements)==1
    assert result['reading_count']==1
    assert result['missing_rate']==0
    assert result['field_coverage']==['motor_current_a']
    assert result['equipment_quality'][0]['equipment_id']=='E1'
    assert result['metric_statistics'][0]['average']==9
    assert result['sampling_baselines']==[]
