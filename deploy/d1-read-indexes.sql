-- Idempotent indexes for scoped reads. No business records are replaced.
CREATE INDEX IF NOT EXISTS model_run_history_dataset_created ON model_run_history(dataset_version,created_at DESC,run_id DESC);
CREATE INDEX IF NOT EXISTS business_audit_log_entity_event ON business_audit_log(entity_id,event_id);
CREATE INDEX IF NOT EXISTS maintenance_work_orders_updated ON maintenance_work_orders(updated_at DESC,work_order_id DESC);
CREATE INDEX IF NOT EXISTS maintenance_work_orders_dataset_updated ON maintenance_work_orders(json_extract(details,'$.dataset_version'),updated_at DESC,work_order_id DESC);
CREATE INDEX IF NOT EXISTS equipment_alert_reviews_dataset_updated ON equipment_alert_reviews(dataset_version,updated_at DESC,alert_id DESC);
CREATE INDEX IF NOT EXISTS production_orders_equipment_time ON production_orders(equipment_id,start_at,end_at);
CREATE INDEX IF NOT EXISTS maintenance_history_replay_range ON maintenance_history(equipment_id,julianday(COALESCE(strftime('%Y-%m-%d %H:%M:%S',maintenance_date,'+8 hours'),json_extract(attributes,'$.verified_at'))));
