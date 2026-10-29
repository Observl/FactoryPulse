-- Fact-only target schema. Install into an EMPTY database, never over v1.
PRAGMA foreign_keys=ON;
CREATE TABLE database_schema(version INTEGER PRIMARY KEY, installed_at TEXT NOT NULL,
 migration_state TEXT NOT NULL CHECK(migration_state IN ('building','ready')));
INSERT INTO database_schema VALUES(2,strftime('%Y-%m-%dT%H:%M:%fZ','now'),'building');
CREATE TABLE equipment(
 equipment_id TEXT PRIMARY KEY, equipment_name TEXT, equipment_type TEXT,
 status TEXT, production_line TEXT, required_skill TEXT, data_origin TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE sensor_readings(
 reading_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
 timestamp TEXT NOT NULL, air_temperature_k REAL, process_temperature_k REAL,
 rotational_speed_rpm REAL, torque_nm REAL, tool_wear_min REAL, vibration_mm_s REAL,
 spindle_load_pct REAL, motor_current_a REAL, oil_temperature_c REAL,
 failure INTEGER CHECK(failure IN (0,1)), label_status TEXT, data_origin TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE INDEX sensor_readings_equipment_time ON sensor_readings(equipment_id,timestamp,reading_id);
CREATE TABLE maintenance_requirements(
 equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id),
 inspection_cost_cny REAL, repair_cost_cny REAL, inspection_duration_h REAL,
 repair_duration_h REAL, duration_override_h REAL, cost_override_cny REAL,
 required_staff_count INTEGER, required_skill TEXT, assumed_failure_loss_cny REAL,
 window_start TEXT, window_end TEXT, configuration_status TEXT, data_origin TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE maintenance_required_parts(
 equipment_id TEXT NOT NULL REFERENCES maintenance_requirements(equipment_id),
 part_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
 PRIMARY KEY(equipment_id,part_name)
);
CREATE TABLE maintenance_history(
 maintenance_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
 maintenance_type TEXT, failure_at TEXT, failure_end TEXT, maintenance_date TEXT,
 observed_downtime_h REAL, data_origin TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE maintenance_staff(
 staff_id TEXT PRIMARY KEY, staff_name TEXT, skills TEXT, available_hours REAL,
 shift_start TEXT, shift_end TEXT, data_origin TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE production_orders(
 order_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
 order_name TEXT, start_at TEXT, end_at TEXT, due_at TEXT, delay_cost_cny_per_hour REAL,
 data_origin TEXT, attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE maintenance_scenarios(
 scenario_id TEXT PRIMARY KEY, scenario_name TEXT, maintenance_budget_cny REAL,
 available_staff_count INTEGER, max_downtime_h REAL, risk_threshold REAL,
 assumed_failure_probability REAL, data_origin TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE maintenance_work_orders(
 work_order_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL, status TEXT NOT NULL,
 updated_at TEXT NOT NULL, details TEXT NOT NULL CHECK(json_valid(details)),
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE INDEX maintenance_work_orders_equipment_status ON maintenance_work_orders(equipment_id,status);
CREATE TABLE equipment_alert_reviews(
 alert_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL, status TEXT, note TEXT,
 updated_at TEXT, dataset_version TEXT, prediction_at TEXT, defer_until TEXT, version INTEGER,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE maintenance_acceptance_records(
 work_order_id TEXT PRIMARY KEY, dataset_version TEXT, equipment_id TEXT NOT NULL,
 verified_at TEXT, details TEXT NOT NULL CHECK(json_valid(details)),
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE schedule_decision_history(
 plan_id TEXT PRIMARY KEY, dataset_version TEXT, business_revision TEXT, created_at TEXT,
 evidence TEXT NOT NULL CHECK(json_valid(evidence)),
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE model_run_history(
 run_id TEXT PRIMARY KEY, dataset_version TEXT, model_version TEXT, created_at TEXT,
 evidence TEXT NOT NULL CHECK(json_valid(evidence)),
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE business_audit_log(
 event_id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, entity_id TEXT, created_at TEXT,
 details TEXT NOT NULL CHECK(json_valid(details)),
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE operation_receipts(
 request_id TEXT PRIMARY KEY, request_content TEXT NOT NULL, response TEXT NOT NULL,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE spare_part_stock(
 scope TEXT NOT NULL, part_name TEXT NOT NULL, on_hand INTEGER NOT NULL CHECK(on_hand>=0),
 version INTEGER, counted_at TEXT, source TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes)), PRIMARY KEY(scope,part_name)
);
CREATE TABLE spare_part_reservations(
 work_order_id TEXT NOT NULL, scope TEXT NOT NULL, part_name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>=0), state TEXT NOT NULL,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes)), PRIMARY KEY(work_order_id,part_name)
);
CREATE INDEX spare_part_reservations_lookup ON spare_part_reservations(scope,part_name,state);
CREATE TABLE spare_part_movements(
 movement_id TEXT PRIMARY KEY, scope TEXT NOT NULL, part_name TEXT NOT NULL,
 work_order_id TEXT, movement_type TEXT, quantity INTEGER NOT NULL, note TEXT, created_at TEXT,
 attributes TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes))
);
CREATE TABLE business_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);

-- Readable views contain no persisted counters, totals or current-state caches.
CREATE VIEW v_equipment_latest_reading AS
 SELECT s.*,1 AS reading_rank FROM equipment e JOIN sensor_readings s ON s.reading_id=(
  SELECT t.reading_id FROM sensor_readings t WHERE t.equipment_id=e.equipment_id
  ORDER BY t.timestamp DESC,t.reading_id DESC LIMIT 1
 );
CREATE VIEW v_equipment_summary AS
 SELECT e.*,r.reading_id,r.timestamp AS latest_sample_at,r.rotational_speed_rpm,
 r.torque_nm,r.vibration_mm_s,r.spindle_load_pct,r.motor_current_a,r.oil_temperature_c,
 (SELECT COUNT(*) FROM sensor_readings s WHERE s.equipment_id=e.equipment_id) AS reading_count
 FROM equipment e LEFT JOIN v_equipment_latest_reading r USING(equipment_id);
CREATE VIEW v_maintenance_requirements AS
 SELECT m.*,
 COALESCE(duration_override_h,inspection_duration_h+repair_duration_h) AS maintenance_hours,
 COALESCE(cost_override_cny,inspection_cost_cny+repair_cost_cny) AS maintenance_cost_cny
 FROM maintenance_requirements m;
CREATE VIEW v_maintenance_history AS
 SELECT m.*,COALESCE(observed_downtime_h,
 (julianday(failure_end)-julianday(failure_at))*24.0) AS downtime_hours
 FROM maintenance_history m;
CREATE VIEW v_spare_part_availability AS
 SELECT s.*,COALESCE(r.reserved_quantity,0) AS reserved_quantity,
 s.on_hand-COALESCE(r.reserved_quantity,0) AS balance_after_reservations,
 MAX(0,s.on_hand-COALESCE(r.reserved_quantity,0)) AS available_to_allocate,
 CASE WHEN COALESCE(r.reserved_quantity,0)>s.on_hand THEN 1 ELSE 0 END AS reservation_shortage
 FROM spare_part_stock s LEFT JOIN (
 SELECT scope,part_name,SUM(quantity) AS reserved_quantity
 FROM spare_part_reservations WHERE state='reserved' GROUP BY scope,part_name
 ) r USING(scope,part_name);
CREATE VIEW v_current_spare_part_availability AS
 SELECT * FROM v_spare_part_availability WHERE scope=COALESCE(
 (SELECT NULLIF(value,'') FROM business_settings WHERE key='inventory_scope'),
 (SELECT NULLIF(value,'') FROM business_settings WHERE key='last_sync_at'),'uninitialized');
CREATE VIEW v_work_order_schedule AS
 SELECT work_order_id,equipment_id,status,updated_at,
 json_extract(details,'$.dataset_version') AS dataset_version,
 json_extract(details,'$.start_at') AS planned_start_at,
 json_extract(details,'$.end_at') AS planned_end_at,
 json_extract(details,'$.actual_start_at') AS actual_start_at,
 json_extract(details,'$.actual_finish_at') AS actual_finish_at,
 json_extract(details,'$.staff_ids') AS staff_ids,
 json_extract(details,'$.deleted_at') AS deleted_at,
 (julianday(json_extract(details,'$.end_at'))-julianday(json_extract(details,'$.start_at')))*24.0 AS planned_duration_h
 FROM maintenance_work_orders;
CREATE VIEW v_work_order_counts AS
 SELECT status,COUNT(*) AS work_order_count FROM v_work_order_schedule
 WHERE deleted_at IS NULL GROUP BY status;
CREATE VIEW v_reading_duplicates AS
 SELECT equipment_id,timestamp,COUNT(*) AS duplicate_count
 FROM sensor_readings GROUP BY equipment_id,timestamp HAVING COUNT(*)>1;
CREATE VIEW v_reading_gaps AS
 SELECT equipment_id,reading_id,timestamp,previous_sample_at,
 (julianday(timestamp)-julianday(previous_sample_at))*86400.0 AS gap_seconds
 FROM (
 SELECT equipment_id,reading_id,timestamp,
 LAG(timestamp) OVER(PARTITION BY equipment_id ORDER BY timestamp,reading_id) AS previous_sample_at
 FROM sensor_readings
 );
CREATE VIEW v_data_quality_summary AS
 SELECT COUNT(*) AS reading_count,COUNT(DISTINCT equipment_id) AS equipment_count,
 MIN(timestamp) AS first_sample_at,MAX(timestamp) AS last_sample_at,
 COALESCE(SUM(CASE WHEN julianday(timestamp) IS NULL THEN 1 ELSE 0 END),0) AS invalid_timestamp_count,
 (SELECT COUNT(*) FROM v_reading_duplicates) AS duplicate_group_count,
 (SELECT COUNT(*) FROM sensor_readings s LEFT JOIN equipment e USING(equipment_id) WHERE e.equipment_id IS NULL) AS unknown_equipment_count
 FROM sensor_readings;
CREATE VIEW v_business_counts AS
 SELECT 'equipment' AS entity,COUNT(*) AS record_count FROM equipment
 UNION ALL SELECT 'sensor_readings',COUNT(*) FROM sensor_readings
 UNION ALL SELECT 'maintenance_staff',COUNT(*) FROM maintenance_staff
 UNION ALL SELECT 'production_orders',COUNT(*) FROM production_orders
 UNION ALL SELECT 'maintenance_work_orders',COUNT(*) FROM maintenance_work_orders;
