"""Deterministic CNC demonstration dataset.

All records are visibly marked as synthetic.  They model the same entities used
in a manufacturing pilot, so the UI and workflow never mix disk-drive data with
CNC maintenance decisions.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import math
from .demo_business import complete_demo_business

ORIGIN = "SYNTHETIC_CNC_DEMO_FOR_WORKFLOW_VALIDATION"

def build_cnc_demo() -> tuple[dict[str, list[dict]], str]:
    start = datetime(2026, 7, 1, 8)
    ids = [f"CNC-{index:03d}" for index in range(1, 13)]
    # Three historical failures support time-split validation; CNC-003 is an
    # active pre-failure case 20 hours beyond the final sample for the demo flow.
    failing = {"CNC-003": 1450, "CNC-005": 820, "CNC-007": 1040, "CNC-011": 1290}
    equipment=[]; readings=[]; rules=[]; history=[]; risks=[]
    for index,eid in enumerate(ids):
        equipment.append({"equipment_id":eid,"equipment_name":f"立式加工中心 {index+1:02d}","equipment_type":"数控机床","status":"预警" if eid in failing else "运行中","production_line":f"机加工{chr(65+index%3)}线","required_skill":"机修","data_origin":ORIGIN})
        device_rows=[]
        for hour in range(1440):
            timestamp=start+timedelta(hours=hour); fault_hour=failing.get(eid); hours_to_fault=(fault_hour-hour) if fault_hour is not None else 9999
            degrading=fault_hour is not None and 96>=hours_to_fault>=0
            severity=max(0,(96-hours_to_fault)/96) if degrading else 0
            vibration=1.15+.09*math.sin(hour/11+index)+severity*5.6
            process_temp=309+1.8*math.sin(hour/18)+severity*18
            spindle_load=51+6*math.sin(hour/9+index)+severity*37
            wear=(hour*0.45+index*9)%260 + severity*70
            future_failure=None if hour+168>1439 or hours_to_fault==0 else int(fault_hour is not None and 0<hours_to_fault<=168)
            failure=int(fault_hour is not None and hour==fault_hour)
            row={"reading_id":f"{eid}-{hour:04d}","equipment_id":eid,"timestamp":timestamp.isoformat(sep=" "),"air_temperature_k":298+math.sin(hour/24),"process_temperature_k":round(process_temp,3),"rotational_speed_rpm":round(1480+80*math.sin(hour/7+index),2),"torque_nm":round(32+5*math.sin(hour/13)+severity*14,2),"tool_wear_min":round(wear,2),"vibration_mm_s":round(vibration,3),"spindle_load_pct":round(spindle_load,2),"future_failure":future_failure,"prediction_horizon_hours":168,"failure":failure,"data_origin":ORIGIN}
            readings.append(row); device_rows.append(row)
            if failure: history.append({"maintenance_id":f"FAIL-{eid}-{hour}","equipment_id":eid,"maintenance_type":"主轴异常停机","maintenance_date":timestamp.isoformat(sep=" "),"downtime_hours":6,"data_origin":ORIGIN})
        latest=device_rows[-1]; rule=min(.98,.02+max(0,float(latest["vibration_mm_s"])-2.5)*.12+max(0,float(latest["process_temperature_k"])-315)*.025+max(0,float(latest["spindle_load_pct"])-70)*.012)
        risks.append({"equipment_id":eid,"risk_score":round(rule,4),"data_origin":"CNC_THRESHOLD_BASELINE"})
        maintenance_cost=2200 if eid=="CNC-003" else 4650
        rules.append({"equipment_id":eid,"inspection_cost_cny":450,"repair_cost_cny":maintenance_cost-450,"inspection_duration_h":1,"repair_duration_h":4,"maintenance_cost_cny":maintenance_cost,"maintenance_hours":5,"required_staff_count":1,"required_skill":"机修","assumed_failure_loss_cny":28000,"scenario_risk_reduction_low":.25,"scenario_risk_reduction_high":.65,"data_origin":"SYNTHETIC_BUSINESS_ASSUMPTION"})
    staff=[
        {"staff_id":"TECH-01","staff_name":"王工","skills":"机修,主轴","available_hours":8,"shift_start":"2026-08-30 08:00:00","shift_end":"2026-08-30 16:00:00","data_origin":ORIGIN},
        {"staff_id":"TECH-02","staff_name":"李工","skills":"机修,电气","available_hours":8,"shift_start":"2026-08-30 08:00:00","shift_end":"2026-08-30 16:00:00","data_origin":ORIGIN},
        {"staff_id":"TECH-03","staff_name":"陈工","skills":"电气","available_hours":8,"shift_start":"2026-08-30 08:00:00","shift_end":"2026-08-30 16:00:00","data_origin":ORIGIN},
    ]
    orders=[]
    for index,eid in enumerate(ids):
        orders.append({"order_id":f"PO-2026-{index+1:03d}","equipment_id":eid,"order_name":f"精密壳体批次{index+1:02d}","production_start":"2026-08-30 08:00:00","due_at":"2026-09-01 18:00:00","priority":"高" if index%4==0 else "普通","delay_cost_cny_per_hour":1200 if index%4==0 else 500,"data_origin":ORIGIN})
    scenarios=[{"scenario_id":"CNC-BASE","scenario_name":"周末维护窗口","maintenance_budget_cny":30000,"risk_threshold":.35,"available_staff_count":2,"max_downtime_h":16,"scenario_risk_reduction_low":.25,"scenario_risk_reduction_high":.65},{"scenario_id":"CNC-TIGHT","scenario_name":"预算收紧情景","maintenance_budget_cny":12000,"risk_threshold":.55,"available_staff_count":1,"max_downtime_h":8,"scenario_risk_reduction_low":.2,"scenario_risk_reduction_high":.5}]
    data={"equipment":equipment,"readings":readings,"maintenance_rules":rules,"maintenance_history":history,"staff":staff,"orders":orders,"scenarios":scenarios,"demo_risks":risks}
    return complete_demo_business(data), readings[-1]["timestamp"][:10]
