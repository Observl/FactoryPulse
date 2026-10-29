"""Deterministic adapters over SQL aggregates; never ask the model to count rows."""
import json

from pathlib import Path

QUALITY_QUERY = (Path(__file__).resolve().parents[1] / 'deploy' / 'd1-quality-report.sql').read_text(encoding='utf-8')


def data_quality(connection):
    packed=connection.execute(QUALITY_QUERY).fetchone()
    result=json.loads(packed['report'])
    fields=set()
    for profile in json.loads(packed['fields']):
        if profile:fields.update(json.loads(profile))
    result['quality_status']='没有可用采样，无法完成质量判断' if result['reading_count']==0 else ('基础校验通过，需核对现场适用性' if result['missing_rate'] is not None and result['missing_rate']<.05 and not any(result[key] for key in ('duplicate_readings','invalid_timestamps','abnormal_values','future_timestamps')) else '需补充或修复数据')
    result['freshness']='future_timestamp' if result['future_timestamps'] else ('historical' if result['data_age_hours'] is not None and result['data_age_hours']>24 else 'recent_or_unknown')
    result.update({key:json.loads(packed[key]) for key in ('equipment_quality','metric_statistics','sampling_baselines')})
    result.update(field_coverage=sorted(fields),field_labels=sorted(fields),
        sampling_gaps=json.loads(packed['gaps']),
        gap_method='SQL 按设备正采样间隔中位数推断，超过3倍标为待复核间断；不是采集SLA',
        missing_rate_scope='指标值缺失率；主键和时间有效性单独检查',computed_by='cloudflare_d1_sql')
    return result
