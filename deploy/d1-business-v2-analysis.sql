-- Database-side analytics. No AI computation, stored counters or normal-limit claims.
CREATE VIEW v_reading_metrics AS
 SELECT s.reading_id,s.equipment_id,s.timestamp,f.value AS metric,
 CASE f.value WHEN 'air_temperature_k' THEN s.air_temperature_k WHEN 'process_temperature_k' THEN s.process_temperature_k
 WHEN 'rotational_speed_rpm' THEN s.rotational_speed_rpm WHEN 'torque_nm' THEN s.torque_nm WHEN 'tool_wear_min' THEN s.tool_wear_min
 WHEN 'vibration_mm_s' THEN s.vibration_mm_s WHEN 'spindle_load_pct' THEN s.spindle_load_pct
 WHEN 'motor_current_a' THEN s.motor_current_a WHEN 'oil_temperature_c' THEN s.oil_temperature_c
 ELSE json_extract(s.attributes,'$.'||f.value) END AS value
 FROM sensor_readings s,json_each(COALESCE(json_extract(s.attributes,'$._feature_fields'),
 '["air_temperature_k","process_temperature_k","rotational_speed_rpm","torque_nm","tool_wear_min","vibration_mm_s","spindle_load_pct","motor_current_a","oil_temperature_c"]')) f;
CREATE VIEW v_equipment_metric_statistics AS
 SELECT equipment_id,metric,COUNT(*) AS sample_count,
 SUM(CASE WHEN value IS NULL OR value='' THEN 1 ELSE 0 END) AS missing_count,
 SUM(CASE WHEN value IS NOT NULL AND value<>'' AND typeof(value) NOT IN ('integer','real') THEN 1 ELSE 0 END) AS invalid_number_count,
 MIN(CASE WHEN typeof(value) IN ('integer','real') THEN value END) AS minimum,
 MAX(CASE WHEN typeof(value) IN ('integer','real') THEN value END) AS maximum,
 AVG(CASE WHEN typeof(value) IN ('integer','real') THEN value END) AS average
 FROM v_reading_metrics GROUP BY equipment_id,metric;
CREATE VIEW v_equipment_sampling_baseline AS
 SELECT equipment_id,AVG(gap_seconds) AS median_interval_seconds FROM (
 SELECT equipment_id,gap_seconds,ROW_NUMBER() OVER(PARTITION BY equipment_id ORDER BY gap_seconds) AS position,
 COUNT(*) OVER(PARTITION BY equipment_id) AS interval_count FROM v_reading_gaps WHERE gap_seconds>0
 ) WHERE position IN ((interval_count+1)/2,(interval_count+2)/2) GROUP BY equipment_id;
CREATE VIEW v_sampling_interruptions AS
 SELECT g.equipment_id,g.previous_sample_at AS start_at,g.timestamp AS end_at,g.gap_seconds AS duration_seconds,
 b.median_interval_seconds AS inferred_interval_seconds
 FROM v_reading_gaps g JOIN v_equipment_sampling_baseline b USING(equipment_id)
 WHERE g.gap_seconds>b.median_interval_seconds*3.0;
CREATE VIEW v_equipment_data_quality AS
 SELECT e.equipment_id,e.equipment_name,
 COALESCE(r.reading_count,0) AS reading_count,r.first_sample_at,r.latest_sample_at,
 r.invalid_timestamp_count,r.future_timestamp_count,
 COALESCE(m.expected_value_count,0) AS expected_value_count,COALESCE(m.missing_count,0) AS missing_count,
 COALESCE(m.invalid_number_count,0) AS invalid_number_count,
 CASE WHEN m.expected_value_count>0 THEN m.missing_count*1.0/m.expected_value_count END AS missing_rate,
 COALESCE(d.duplicate_readings,0) AS duplicate_readings,COALESCE(g.sampling_gap_count,0) AS sampling_gap_count,
 CASE WHEN r.latest_sample_at IS NOT NULL THEN MAX(0,(julianday('now')-julianday(r.latest_sample_at))*24.0) END AS data_age_hours
 FROM equipment e LEFT JOIN (
 SELECT equipment_id,COUNT(*) AS reading_count,MIN(timestamp) AS first_sample_at,MAX(timestamp) AS latest_sample_at,
 SUM(julianday(timestamp) IS NULL) AS invalid_timestamp_count,
 SUM(julianday(timestamp)>julianday('now')+300.0/86400.0) AS future_timestamp_count
 FROM sensor_readings GROUP BY equipment_id) r USING(equipment_id)
 LEFT JOIN (SELECT equipment_id,SUM(sample_count) AS expected_value_count,SUM(missing_count) AS missing_count,
 SUM(invalid_number_count) AS invalid_number_count FROM v_equipment_metric_statistics GROUP BY equipment_id) m USING(equipment_id)
 LEFT JOIN (SELECT equipment_id,SUM(duplicate_count-1) AS duplicate_readings FROM v_reading_duplicates GROUP BY equipment_id) d USING(equipment_id)
 LEFT JOIN (SELECT equipment_id,COUNT(*) AS sampling_gap_count FROM v_sampling_interruptions GROUP BY equipment_id) g USING(equipment_id);
CREATE VIEW v_quality_report AS
 SELECT (SELECT COUNT(*) FROM equipment) AS device_count,
 COALESCE(SUM(reading_count),0) AS reading_count,SUM(missing_count) AS missing_count,
 SUM(expected_value_count) AS expected_value_count,
 CASE WHEN SUM(expected_value_count)>0 THEN SUM(missing_count)*1.0/SUM(expected_value_count) END AS missing_rate,
 COALESCE(SUM(invalid_timestamp_count),0) AS invalid_timestamps,
 COALESCE(SUM(future_timestamp_count),0) AS future_timestamps,
 COALESCE(SUM(invalid_number_count),0) AS abnormal_values,
 COALESCE(SUM(duplicate_readings),0) AS duplicate_readings,
 COALESCE(SUM(sampling_gap_count),0) AS sampling_gap_count,
 MAX(latest_sample_at) AS latest_timestamp,
 MIN(data_age_hours) AS data_age_hours,
 (SELECT value FROM business_settings WHERE key='data_origin') AS data_origin
 FROM v_equipment_data_quality;
CREATE VIEW v_sensor_reference_ranges AS
 WITH ranked AS (
 SELECT m.equipment_id,m.metric,m.value,
 ROW_NUMBER() OVER(PARTITION BY m.equipment_id,m.metric ORDER BY m.value)-1 AS position,
 COUNT(*) OVER(PARTITION BY m.equipment_id,m.metric) AS samples
 FROM v_reading_metrics m JOIN sensor_readings s USING(reading_id)
 WHERE s.failure=0 AND typeof(m.value) IN ('integer','real')
 ), bounds AS (
 SELECT *, (samples-1)*0.05 AS low_position,(samples-1)*0.95 AS high_position FROM ranked
 ) SELECT equipment_id,metric,MAX(samples) AS samples,
 SUM(CASE WHEN position=CAST(low_position AS INTEGER) THEN value*(1-(low_position-CAST(low_position AS INTEGER))) ELSE 0 END)
 +SUM(CASE WHEN position=CAST(low_position AS INTEGER)+1 THEN value*(low_position-CAST(low_position AS INTEGER)) ELSE 0 END) AS low,
 SUM(CASE WHEN position=CAST(high_position AS INTEGER) THEN value*(1-(high_position-CAST(high_position AS INTEGER))) ELSE 0 END)
 +SUM(CASE WHEN position=CAST(high_position AS INTEGER)+1 THEN value*(high_position-CAST(high_position AS INTEGER)) ELSE 0 END) AS high
 FROM bounds WHERE samples>=20 GROUP BY equipment_id,metric;
CREATE VIEW v_work_order_assignments AS
 SELECT w.work_order_id,CAST(p.value AS TEXT) AS staff_id
 FROM maintenance_work_orders w,json_each(COALESCE(json_extract(w.details,'$.staff_ids'),json_array(json_extract(w.details,'$.staff_id')))) p
 WHERE p.value IS NOT NULL;
CREATE VIEW v_work_order_conflicts AS
 SELECT a.work_order_id,b.work_order_id AS conflicting_work_order_id,a.equipment_id,
 CASE WHEN a.equipment_id=b.equipment_id THEN 1 ELSE 0 END AS equipment_conflict,
 CASE WHEN EXISTS(SELECT 1 FROM v_work_order_assignments x JOIN v_work_order_assignments y USING(staff_id)
 WHERE x.work_order_id=a.work_order_id AND y.work_order_id=b.work_order_id) THEN 1 ELSE 0 END AS staff_conflict
 FROM v_work_order_schedule a JOIN v_work_order_schedule b ON a.work_order_id<b.work_order_id
 WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
 AND a.status IN ('已批准','已接单','执行中','已暂停','待验收') AND b.status IN ('已批准','已接单','执行中','已暂停','待验收')
 AND julianday(a.planned_start_at)<julianday(b.planned_end_at) AND julianday(b.planned_start_at)<julianday(a.planned_end_at)
 AND (a.equipment_id=b.equipment_id OR EXISTS(SELECT 1 FROM v_work_order_assignments x JOIN v_work_order_assignments y USING(staff_id)
 WHERE x.work_order_id=a.work_order_id AND y.work_order_id=b.work_order_id));
CREATE VIEW v_production_maintenance_conflicts AS
 SELECT w.work_order_id,p.order_id,w.equipment_id,w.planned_start_at,w.planned_end_at,p.start_at AS production_start_at,p.end_at AS production_end_at
 FROM v_work_order_schedule w JOIN production_orders p USING(equipment_id)
 WHERE w.deleted_at IS NULL AND w.status IN ('已批准','已接单','执行中','已暂停','待验收')
 AND julianday(w.planned_start_at)<julianday(p.end_at) AND julianday(p.start_at)<julianday(w.planned_end_at);
CREATE VIEW v_current_model_scores AS
 SELECT json_extract(d.value,'$.equipment_id') AS equipment_id,
 json_extract(d.value,'$.model_risk') AS model_risk,
 json_extract(d.value,'$.ewma_risk') AS trend_risk,
 json_extract(d.value,'$.combined_risk') AS priority_score,
 json_extract(d.value,'$.prediction_at') AS prediction_at
 FROM fp_v_processed_results v,json_each(v.content,'$.devices') d WHERE v.view_key='overview';
CREATE VIEW v_dashboard_devices AS
 WITH artifacts AS (
 SELECT d.value AS content,json_extract(d.value,'$.equipment_id') AS equipment_id
 FROM fp_v_processed_results v,json_each(v.content,'$.devices') d WHERE v.view_key='overview'
 ), latest_alert AS (
 SELECT * FROM (SELECT a.*,ROW_NUMBER() OVER(PARTITION BY equipment_id ORDER BY updated_at DESC,alert_id DESC) AS position
 FROM equipment_alert_reviews a WHERE dataset_version=(SELECT value FROM business_settings WHERE key='last_sync_at')) WHERE position=1
 ), current AS (
 SELECT e.*,l.timestamp,l.air_temperature_k,l.process_temperature_k,l.rotational_speed_rpm,l.torque_nm,l.tool_wear_min,
 l.vibration_mm_s,l.spindle_load_pct,l.motor_current_a,l.oil_temperature_c,l.attributes AS reading_attributes,
 a.content AS artifact_content,m.model_risk,m.trend_risk,
 COALESCE(m.model_risk,m.trend_risk,z.risk_score,r.rule_risk) AS score,
 x.status AS alert_status,x.note AS alert_note
 FROM equipment e LEFT JOIN v_equipment_latest_reading l USING(equipment_id)
 LEFT JOIN artifacts a USING(equipment_id) LEFT JOIN v_current_model_scores m USING(equipment_id)
 LEFT JOIN v_equipment_rule_risk r USING(equipment_id) LEFT JOIN external_risk_inputs z USING(equipment_id) LEFT JOIN latest_alert x USING(equipment_id)
 ) SELECT equipment_id,score,
 json_patch(COALESCE(artifact_content,'{}'),json_object(
 'equipment_id',equipment_id,'equipment_name',equipment_name,'equipment_type',equipment_type,
 'production_line',production_line,'status',status,'required_skill',required_skill,'data_origin',data_origin,
 'risk_score',score,'combined_risk',score,'model_risk',model_risk,'ewma_risk',trend_risk,
 'risk_available',json(CASE WHEN score IS NULL THEN 'false' ELSE 'true' END),
 'risk_level',CASE WHEN score IS NULL THEN '待评估' WHEN score>0.35 THEN '高' WHEN score>=0.15 THEN '中' ELSE '低' END,
 'review_required',json(CASE WHEN score>=COALESCE(json_extract(artifact_content,'$.model_alert_threshold'),0.15) THEN 'true' ELSE 'false' END),
 'prediction_at',COALESCE(json_extract(artifact_content,'$.prediction_at'),timestamp),'prediction_window',CASE WHEN model_risk IS NULL THEN '当前工况参考' ELSE COALESCE(json_extract(artifact_content,'$.prediction_window'),'模型历史证据') END,
 'risk_semantics',CASE WHEN model_risk IS NOT NULL THEN '模型分数用于检查排序，不是故障概率' WHEN score IS NOT NULL THEN '规则或趋势参考，不继承模型验证成绩' ELSE '没有足够证据评估，不能解读为低风险' END,
 'recommended_action',COALESCE(json_extract(artifact_content,'$.recommended_action'),'复核监测、历史记录与设备手册，再确认检修动作'),
 'primary_evidence',json(COALESCE(json_extract(artifact_content,'$.primary_evidence'),'[]')),
 'latest_reading',json_patch(COALESCE(reading_attributes,'{}'),json_object('equipment_id',equipment_id,'timestamp',timestamp,
 'air_temperature_k',air_temperature_k,'process_temperature_k',process_temperature_k,'rotational_speed_rpm',rotational_speed_rpm,
 'torque_nm',torque_nm,'tool_wear_min',tool_wear_min,'vibration_mm_s',vibration_mm_s,'spindle_load_pct',spindle_load_pct,
 'motor_current_a',motor_current_a,'oil_temperature_c',oil_temperature_c)),
 'affected_orders',json((SELECT json_group_array(order_id) FROM production_orders p WHERE p.equipment_id=current.equipment_id)),
 'alert_status',COALESCE(alert_status,CASE WHEN score>=0.15 THEN '待确认' ELSE '观察' END),'alert_note',COALESCE(alert_note,''))) AS content
 FROM current;
