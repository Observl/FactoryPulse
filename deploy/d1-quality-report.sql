WITH sensor_readings AS MATERIALIZED (SELECT * FROM main.sensor_readings),
v_reading_duplicates AS MATERIALIZED (SELECT equipment_id,timestamp,COUNT(*) AS duplicate_count
 FROM sensor_readings GROUP BY equipment_id,timestamp HAVING COUNT(*)>1),
v_reading_gaps AS MATERIALIZED (SELECT equipment_id,reading_id,timestamp,previous_sample_at,
 (julianday(timestamp)-julianday(previous_sample_at))*86400.0 AS gap_seconds
 FROM (
 SELECT equipment_id,reading_id,timestamp,
 LAG(timestamp) OVER(PARTITION BY equipment_id ORDER BY timestamp,reading_id) AS previous_sample_at
 FROM sensor_readings
 )),
v_reading_metrics AS MATERIALIZED (SELECT s.reading_id,s.equipment_id,s.timestamp,f.value AS metric,
 CASE f.value WHEN 'air_temperature_k' THEN s.air_temperature_k WHEN 'process_temperature_k' THEN s.process_temperature_k
 WHEN 'rotational_speed_rpm' THEN s.rotational_speed_rpm WHEN 'torque_nm' THEN s.torque_nm WHEN 'tool_wear_min' THEN s.tool_wear_min
 WHEN 'vibration_mm_s' THEN s.vibration_mm_s WHEN 'spindle_load_pct' THEN s.spindle_load_pct
 WHEN 'motor_current_a' THEN s.motor_current_a WHEN 'oil_temperature_c' THEN s.oil_temperature_c
 ELSE json_extract(s.attributes,'$.'||f.value) END AS value
 FROM sensor_readings s,json_each(COALESCE(json_extract(s.attributes,'$._feature_fields'),
 '["air_temperature_k","process_temperature_k","rotational_speed_rpm","torque_nm","tool_wear_min","vibration_mm_s","spindle_load_pct","motor_current_a","oil_temperature_c"]')) f),
v_equipment_metric_statistics AS MATERIALIZED (SELECT equipment_id,metric,COUNT(*) AS sample_count,
 SUM(CASE WHEN value IS NULL OR value='' THEN 1 ELSE 0 END) AS missing_count,
 SUM(CASE WHEN value IS NOT NULL AND value<>'' AND typeof(value) NOT IN ('integer','real') THEN 1 ELSE 0 END) AS invalid_number_count,
 MIN(CASE WHEN typeof(value) IN ('integer','real') THEN value END) AS minimum,
 MAX(CASE WHEN typeof(value) IN ('integer','real') THEN value END) AS maximum,
 AVG(CASE WHEN typeof(value) IN ('integer','real') THEN value END) AS average
 FROM v_reading_metrics GROUP BY equipment_id,metric),
v_equipment_sampling_baseline AS MATERIALIZED (SELECT equipment_id,AVG(gap_seconds) AS median_interval_seconds FROM (
 SELECT equipment_id,gap_seconds,ROW_NUMBER() OVER(PARTITION BY equipment_id ORDER BY gap_seconds) AS position,
 COUNT(*) OVER(PARTITION BY equipment_id) AS interval_count FROM v_reading_gaps WHERE gap_seconds>0
 ) WHERE position IN ((interval_count+1)/2,(interval_count+2)/2) GROUP BY equipment_id),
v_sampling_interruptions AS MATERIALIZED (SELECT g.equipment_id,g.previous_sample_at AS start_at,g.timestamp AS end_at,g.gap_seconds AS duration_seconds,
 b.median_interval_seconds AS inferred_interval_seconds
 FROM v_reading_gaps g JOIN v_equipment_sampling_baseline b USING(equipment_id)
 WHERE g.gap_seconds>b.median_interval_seconds*3.0),
v_equipment_data_quality AS MATERIALIZED (SELECT e.equipment_id,e.equipment_name,
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
 LEFT JOIN (SELECT equipment_id,COUNT(*) AS sampling_gap_count FROM v_sampling_interruptions GROUP BY equipment_id) g USING(equipment_id)),
v_quality_report AS MATERIALIZED (SELECT (SELECT COUNT(*) FROM equipment) AS device_count,
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
 FROM v_equipment_data_quality)
SELECT json_object('device_count',device_count,'reading_count',reading_count,'missing_count',missing_count,'expected_value_count',expected_value_count,'missing_rate',missing_rate,'invalid_timestamps',invalid_timestamps,'future_timestamps',future_timestamps,'abnormal_values',abnormal_values,'duplicate_readings',duplicate_readings,'sampling_gap_count',sampling_gap_count,'latest_timestamp',latest_timestamp,'data_age_hours',data_age_hours,'data_origin',data_origin) AS report, (SELECT json_group_array(fields) FROM (SELECT DISTINCT json_extract(attributes,'$._feature_fields') AS fields FROM sensor_readings)) AS fields, (SELECT json_group_array(json_object('equipment_id',equipment_id,'start_at',start_at,'end_at',end_at,'duration_seconds',duration_seconds,'inferred_interval_seconds',inferred_interval_seconds)) FROM (SELECT * FROM v_sampling_interruptions ORDER BY equipment_id,start_at LIMIT 100)) AS gaps, (SELECT json_group_array(json_object('equipment_id',equipment_id,'equipment_name',equipment_name,'reading_count',reading_count,'first_sample_at',first_sample_at,'latest_sample_at',latest_sample_at,'invalid_timestamp_count',invalid_timestamp_count,'future_timestamp_count',future_timestamp_count,'expected_value_count',expected_value_count,'missing_count',missing_count,'invalid_number_count',invalid_number_count,'missing_rate',missing_rate,'duplicate_readings',duplicate_readings,'sampling_gap_count',sampling_gap_count,'data_age_hours',data_age_hours)) FROM v_equipment_data_quality) AS equipment_quality, (SELECT json_group_array(json_object('equipment_id',equipment_id,'metric',metric,'sample_count',sample_count,'missing_count',missing_count,'invalid_number_count',invalid_number_count,'minimum',minimum,'maximum',maximum,'average',average)) FROM v_equipment_metric_statistics) AS metric_statistics, (SELECT json_group_array(json_object('equipment_id',equipment_id,'median_interval_seconds',median_interval_seconds)) FROM v_equipment_sampling_baseline) AS sampling_baselines FROM v_quality_report;
