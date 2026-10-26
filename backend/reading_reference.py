"""Historical reference intervals, never manufacturer safety limits."""
import math
from collections import defaultdict

FIELDS=('motor_current_a','vibration_g','vibration_mm_s','oil_temperature_c','process_temperature_k','tp3_bar','spindle_load_pct','torque_nm','tool_wear_min')
def ranges(readings):
    grouped=defaultdict(lambda:defaultdict(list))
    for row in readings:
        if row.get('failure') not in (0,'0'):continue
        for field in FIELDS:
            raw=row.get(field)
            if raw is None or isinstance(raw,bool):continue
            try:value=float(raw)
            except (TypeError,ValueError):continue
            if math.isfinite(value):grouped[str(row['equipment_id'])][field].append(value)
    def quantile(values,p):
        i=(len(values)-1)*p;low=int(i);return values[low]+(values[min(low+1,len(values)-1)]-values[low])*(i-low)
    result={}
    for identifier,fields in grouped.items():
        result[identifier]={}
        for field,values in fields.items():
            if len(values)<20:continue
            values.sort();low,high=quantile(values,.05),quantile(values,.95)
            if field=='process_temperature_k':field='process_temperature_c';low-=273.15;high-=273.15
            result[identifier][field]={'low':round(low,4),'high':round(high,4),'samples':len(values),'basis':'本设备同版本无故障标记样本 P5–P95；不是厂家正常／安全限值'}
    return result

