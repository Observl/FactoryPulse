"""Synthetic, seeded multi-failure fixture for end-to-end metric verification.

Fault times are sampled independently of alarm thresholds. This is a software
validation dataset, never evidence of field accuracy or calibrated probability.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta
import math
import random
from .demo_business import complete_demo_business

ORIGIN = "SYNTHETIC_CNC_MODEL_VALIDATION_V1"
SEED = 20261021
DAYS = 240
INTERVAL_HOURS = 4
HORIZON_HOURS = 168
DEVICE_COUNT = 24
SENSOR_FIELDS = ["air_temperature_k", "process_temperature_k", "rotational_speed_rpm",
                 "torque_nm", "tool_wear_min", "vibration_mm_s", "spindle_load_pct",
                 "motor_current_a", "oil_temperature_c"]


def build_model_validation(anchor: datetime | None = None):
    anchor = (anchor or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    start = anchor - timedelta(days=DAYS)
    end_hour = DAYS * 24 - INTERVAL_HOURS
    tables = {name: [] for name in ("equipment", "readings", "maintenance_rules",
              "maintenance_history", "staff", "orders", "scenarios", "demo_risks")}
    for index in range(DEVICE_COUNT):
        rng = random.Random(SEED + index)
        identifier = f"VAL-CNC-{index+1:03d}"
        # Random exogenous onsets span train, validation and held-out test periods.
        faults = [(day + rng.randint(-4, 4)) * 24 + rng.randrange(6) * 4
                  for day in (36, 72, 108, 144, 180, 220)]
        durations = [rng.choice((8, 12, 16)) for _ in faults]
        modes = [(index + event) % 3 for event in range(len(faults))]
        abrupt = [(index * 3 + event) % 11 == 0 for event in range(len(faults))]
        precursor = [rng.choice((96, 120, 144, 168)) for _ in faults]
        offset = rng.uniform(-.18, .18)
        state = 0.0
        last_row = None
        for hour in range(0, DAYS * 24, INTERVAL_HOURS):
            moment = start + timedelta(hours=hour)
            position = bisect_right(faults, hour)
            failed = position > 0 and hour < faults[position-1] + durations[position-1]
            next_event = position if position < len(faults) else None
            progress = 0.0
            mode = modes[next_event] if next_event is not None else 0
            if next_event is not None and not abrupt[next_event]:
                remaining = faults[next_event] - hour
                progress = max(0.0, 1.0 - remaining / precursor[next_event])
            # Benign production changes overlap fault symptoms: high readings are
            # deliberately not equivalent to positive outcome labels.
            phase = (hour + index * 37) % (24 * 23)
            overload = max(0.0, 1.0 - abs(phase - 130) / 28)
            transient = .65 * overload
            if index % 8 == 0 and hour > end_hour - 84:
                transient += .6 * (hour - end_hour + 84) / 84
            state = .68 * state + rng.gauss(0, .16)
            load = 53 + 9 * math.sin(hour / 19 + index) + 6 * state + 22 * overload
            mechanical = progress if mode == 0 else .3 * progress
            electrical = progress if mode == 1 else .25 * progress
            thermal = progress if mode == 2 else .4 * progress
            failure_state = int(failed)
            future = None if failed or hour + HORIZON_HOURS > end_hour else int(
                next_event is not None and 0 < faults[next_event] - hour <= HORIZON_HOURS)
            row = {
                "reading_id": f"{identifier}-{hour:05d}", "equipment_id": identifier,
                "timestamp": moment.isoformat(sep=" "),
                "air_temperature_k": round(297 + 3 * math.sin(hour / 168) + rng.gauss(0, .35), 3),
                "process_temperature_k": round(309 + .1 * (load - 53) + 19 * thermal + 9 * transient + rng.gauss(0, 1.3), 3),
                "rotational_speed_rpm": round(max(0, 1480 + 100 * math.sin(hour / 29 + index) - 140 * electrical + rng.gauss(0, 35)) if not failed else 0, 2),
                "torque_nm": round(max(0, 30 + .18 * (load - 53) + 10 * mechanical + rng.gauss(0, 2.2)), 3),
                "tool_wear_min": round((hour * .2 + index * 7) % 240, 2),
                "vibration_mm_s": round(max(.1, 1.4 + offset + state + 4.6 * mechanical + 2.3 * transient + rng.gauss(0, .22)), 3),
                "spindle_load_pct": round(min(100, max(0, load + 20 * electrical + rng.gauss(0, 2))), 2),
                "motor_current_a": round(max(.1, 7.5 + .06 * (load - 53) + 5.4 * electrical + 1.8 * transient + rng.gauss(0, .3)), 3),
                "oil_temperature_c": round(42 + 1.8 * state + 17 * thermal + 5 * transient + rng.gauss(0, 1), 3),
                "failure": failure_state, "future_failure": future,
                "prediction_horizon_hours": HORIZON_HOURS,
                "label_status": "observed" if future is not None else "already_failed_or_right_censored",
                "data_origin": ORIGIN, "_equipment_profile": "cnc",
                "_feature_fields": SENSOR_FIELDS,
            }
            # Sparse missing sensors exercise native missing-value handling while
            # keeping the latest sample complete and every window usable.
            if hour < end_hour and rng.random() < .012:
                row[rng.choice(SENSOR_FIELDS)] = None
            tables["readings"].append(row)
            last_row = row
        tables["equipment"].append({"equipment_id": identifier,
            "equipment_name": f"验证加工中心 {index+1:02d}（模拟）", "equipment_type": "数控机床",
            "status": "待现场复核", "production_line": f"模拟产线{index%4+1}",
            "required_skill": "机修", "data_origin": ORIGIN})
        for event, onset in enumerate(faults):
            begin = start + timedelta(hours=onset)
            finish = begin + timedelta(hours=durations[event])
            tables["maintenance_history"].append({"maintenance_id": f"VAL-FAULT-{index+1:03d}-{event+1}",
                "equipment_id": identifier, "maintenance_type": ("机械振动故障", "电气负载故障", "润滑热异常故障")[modes[event]] + "修复（模拟）",
                "failure_at": begin.isoformat(sep=" "), "failure_end": finish.isoformat(sep=" "),
                "maintenance_date": begin.isoformat(sep=" "), "downtime_hours": durations[event],
                "data_origin": ORIGIN})
        tables["maintenance_rules"].append({"equipment_id": identifier,
            "inspection_cost_cny": 300, "repair_cost_cny": 1500 + 200 * (index % 4),
            "inspection_duration_h": 1, "repair_duration_h": 2 + index % 3,
            "required_staff_count": 1, "required_skill": "机修", "assumed_failure_loss_cny": 20000,
            "data_origin": "SIMULATED_BUSINESS_DATA"})
        rule = min(.98, .04 + max(0, last_row["vibration_mm_s"] - 2.2) * .12
                   + max(0, last_row["motor_current_a"] - 9) * .05)
        tables["demo_risks"].append({"equipment_id": identifier, "risk_score": round(rule, 4),
                                    "data_origin": "SYNTHETIC_SENSOR_THRESHOLD_BASELINE"})
        tables["orders"].append({"order_id": f"VAL-PO-{index+1:03d}", "equipment_id": identifier,
                                "order_name": f"验证生产批次{index+1:02d}（模拟）"})
    tables["scenarios"] = [{"scenario_id": "VAL-BASE", "scenario_name": "多故障模型验证维护窗口（模拟）"},
                            {"scenario_id": "VAL-TIGHT", "scenario_name": "预算收紧对照（模拟）",
                             "maintenance_budget_cny": 6000, "risk_threshold": .35,
                             "available_staff_count": 2, "max_downtime_h": 8,
                             "data_origin": "SIMULATED_BUSINESS_DATA"}]
    tables = complete_demo_business(tables, now=anchor)
    return tables, (start + timedelta(hours=end_hour)).date().isoformat()


def load_acceptance_dataset(refresh_business=True):
    """Load the single frozen acceptance input and verify its identity before use."""
    import hashlib,json
    from pathlib import Path
    folder=Path(__file__).resolve().parents[1]/"data/model-validation"
    manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    raw=(folder/"dataset.json").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest["sha256"]:
        raise ValueError("最终验收数据摘要不一致，禁止载入")
    payload=json.loads(raw)
    data=payload["tables"]
    if refresh_business: complete_demo_business(data)
    return data,payload["source_date"]
