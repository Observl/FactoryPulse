"""Deterministic adapters over SQL aggregates; never ask the model to count rows."""
import json

QUALITY_SQL = """SELECT *,
 CASE WHEN reading_count=0 THEN '没有可用采样，无法完成质量判断'
 WHEN missing_rate<0.05 AND duplicate_readings=0 AND invalid_timestamps=0 AND abnormal_values=0 AND future_timestamps=0
 THEN '基础校验通过，需核对现场适用性' ELSE '需补充或修复数据' END AS quality_status,
 CASE WHEN future_timestamps>0 THEN 'future_timestamp' WHEN data_age_hours>24 THEN 'historical' ELSE 'recent_or_unknown' END AS freshness
 FROM v_quality_report"""


def data_quality(connection):
    row=connection.execute(QUALITY_SQL).fetchone()
    result=dict(row)
    profiles=connection.execute("SELECT DISTINCT json_extract(attributes,'$._feature_fields') AS fields FROM sensor_readings").fetchall()
    fields=set()
    for profile in profiles:
        if profile['fields']:
            fields.update(json.loads(profile['fields']))
    result.update(field_coverage=sorted(fields),field_labels=sorted(fields),
        sampling_gaps=[dict(r) for r in connection.execute('SELECT * FROM v_sampling_interruptions ORDER BY equipment_id,start_at LIMIT 100')],
        gap_method='SQL 按设备正采样间隔中位数推断，超过3倍标为待复核间断；不是采集SLA',
        missing_rate_scope='指标值缺失率；主键和时间有效性单独检查',computed_by='cloudflare_d1_sql')
    return result
