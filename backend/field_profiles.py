"""Industrial sensor catalogue and explicit, device-specific feature contracts."""
import hashlib
import re

EXTRA_FIELDS = {
    "equipment_type":"设备类型", "air_temperature_k":"环境温度（K）",
    "pressure_bar":"工作压力（bar）", "flow_m3_h":"流量（m³/h）",
    "voltage_v":"电压（V）", "power_kw":"功率（kW）", "frequency_hz":"频率（Hz）",
    "humidity_pct":"相对湿度（%）", "operating_hours":"累计运行时长（h）",
    "cycle_count":"累计循环次数", "displacement_mm":"位移（mm）",
    "oil_level_pct":"油位（%）", "particle_count":"颗粒计数",
}
EXTRA_UNITS={"air_temperature_k":"K","pressure_bar":"bar","flow_m3_h":"m³/h","voltage_v":"V","power_kw":"kW","frequency_hz":"Hz","humidity_pct":"%","operating_hours":"h","cycle_count":"次","displacement_mm":"mm","oil_level_pct":"%"}
COMMON=["equipment_id","timestamp","failure","status","production_line","equipment_type"]
PROFILES={
    "generic":{"label":"通用工业设备","fields":[]},
    "cnc":{"label":"数控机床 / 加工中心","fields":["process_temperature_k","vibration_mm_s","vibration_g","rotational_speed_rpm","torque_nm","tool_wear_min","spindle_load_pct","motor_current_a"]},
    "rotating":{"label":"电机 / 泵 / 风机 / 轴承","fields":["vibration_g","vibration_mm_s","vibration_peak_g","vibration_kurtosis","process_temperature_k","rotational_speed_rpm","motor_current_a","pressure_bar","flow_m3_h"]},
    "compressor":{"label":"压缩机 / 气动系统","fields":["pressure_bar","tp2_bar","tp3_bar","reservoirs_bar","flow_m3_h","oil_temperature_c","motor_current_a","power_kw"]},
    "hydraulic":{"label":"液压 / 注塑 / 压机","fields":["pressure_bar","flow_m3_h","oil_temperature_c","oil_level_pct","particle_count","displacement_mm","cycle_count","motor_current_a"]},
    "thermal":{"label":"锅炉 / 换热 / 制冷","fields":["process_temperature_k","air_temperature_k","pressure_bar","flow_m3_h","power_kw","humidity_pct"]},
    "electrical":{"label":"电气 / 供配电","fields":["voltage_v","motor_current_a","power_kw","frequency_hz","process_temperature_k","humidity_pct"]},
}
CUSTOM_PATTERN=r"sensor_[0-9a-f]{16}"
def custom_key(column): return "sensor_"+hashlib.sha256(column.encode("utf-8")).hexdigest()[:16]
def is_custom(field): return bool(re.fullmatch(CUSTOM_PATTERN,field))
def is_sensor(field, standard): return field not in COMMON and (field in standard or is_custom(field))
def leakage_column(column):
    return bool(re.search(r"future|failure|fault|label|target|remaining.?life|\brul\b|故障|失效|标签|剩余寿命|预测|风险评分",column,re.I))

def future_outcome_column(column):
    return bool(re.search(r"future.?failure|future.?fault|未来.*(?:故障|失效)|剩余寿命|remaining.?life|\brul\b|predicted.*(?:failure|fault)|(?:故障|失效).*(?:概率|预测)",column,re.I))

def feature_candidates(readings, standard_features):
    explicit=any("_feature_fields" in row for row in readings)
    if not explicit: return list(standard_features)
    return sorted({name for row in readings for name in row.get("_feature_fields",[]) if name in standard_features or is_custom(name)})
