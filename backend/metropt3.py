"""MetroPT-3 real operational compressor data adapter.

The 1.5M raw samples remain on disk.  FactoryPulse stores ten-minute aggregates
so six months of history can be queried and modelled without inflating SQLite.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from .demo_business import complete_demo_business

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = ROOT / "data" / "metropt3" / "raw" / "MetroPT3(AirCompressor).csv"
CACHE_FILE = ROOT / "data" / "metropt3" / "factorypulse_records.json"
ORIGIN = "UCI_METROPT3_REAL_OPERATIONAL"
EQUIPMENT_ID = "METROPT3-APU-01"
ANALOG = ("TP2", "TP3", "H1", "DV_pressure", "Reservoirs", "Oil_temperature", "Motor_current")
DIGITAL = ("COMP", "DV_eletric", "Towers", "MPG", "LPS", "Pressure_switch", "Oil_level", "Caudal_impulses")
FAILURES = (
    (datetime(2020, 4, 18), datetime(2020, 4, 19)),
    (datetime(2020, 5, 29, 23, 30), datetime(2020, 5, 30, 6)),
    (datetime(2020, 6, 5, 10), datetime(2020, 6, 7, 14, 30)),
    (datetime(2020, 7, 15, 14, 30), datetime(2020, 7, 15, 19)),
)


def _in_failure(moment: datetime) -> bool:
    return any(start <= moment < end for start, end in FAILURES)


def _future_failure(moment: datetime) -> bool:
    horizon = moment + timedelta(days=7)
    return any(moment < start <= horizon for start, _ in FAILURES)


def label_observed_history(readings: list[dict]) -> list[dict]:
    """Only label healthy observations with a fully observed future window."""
    if not readings:
        return readings
    observed_end = max(datetime.fromisoformat(row["timestamp"]) for row in readings)
    for row in readings:
        moment = datetime.fromisoformat(row["timestamp"])
        row["prediction_horizon_hours"] = 168
        row["future_failure"] = None if _in_failure(moment) or moment + timedelta(days=7) > observed_end else int(_future_failure(moment))
        row["label_status"] = "observed" if row["future_failure"] is not None else "unknown_or_already_failed"
    return readings


def _aggregate() -> list[dict]:
    if not RAW_FILE.exists():
        raise FileNotFoundError(f"MetroPT-3 CSV not found: {RAW_FILE}")
    readings: list[dict] = []
    bucket = None
    sums: dict[str, float] = {}
    count = 0

    def flush() -> None:
        nonlocal count
        if bucket is None or not count:
            return
        values = {name: round(sums[name] / count, 5) for name in ANALOG + DIGITAL}
        reading = {
            "reading_id": f"METROPT3-{bucket:%Y%m%d%H%M}",
            "equipment_id": EQUIPMENT_ID,
            "timestamp": bucket.strftime("%Y-%m-%d %H:%M:%S"),
            "tp2_bar": values["TP2"], "tp3_bar": values["TP3"], "h1_bar": values["H1"],
            "dv_pressure_bar": values["DV_pressure"], "reservoirs_bar": values["Reservoirs"],
            "oil_temperature_c": values["Oil_temperature"],
            "process_temperature_k": round(values["Oil_temperature"] + 273.15, 3),
            "motor_current_a": values["Motor_current"],
            "failure": int(_in_failure(bucket)), "future_failure": int(_future_failure(bucket)),
            "prediction_horizon_hours": 168,
            "failure_type": "air_leak" if _in_failure(bucket) else "",
            "evaluation_split": "test" if bucket >= datetime(2020, 7, 1) else "train",
            "sample_count": count, "aggregation_window": "10min", "data_origin": ORIGIN,
        }
        reading.update({name.lower(): values[name] for name in DIGITAL})
        readings.append(reading)

    with RAW_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            moment = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            current = moment.replace(minute=(moment.minute // 10) * 10, second=0)
            if bucket is not None and current != bucket:
                flush(); sums = {}; count = 0
            bucket = current
            for name in ANALOG + DIGITAL:
                sums[name] = sums.get(name, 0.0) + float(row[name])
            count += 1
    flush()
    return readings


def build_metropt3() -> tuple[dict[str, list[dict]], str]:
    cache_current=CACHE_FILE.is_file() and (not RAW_FILE.is_file() or CACHE_FILE.stat().st_mtime>=RAW_FILE.stat().st_mtime)
    readings = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if cache_current else []
    if not readings or readings[0].get("prediction_horizon_hours") != 168:
        if not RAW_FILE.is_file():raise ValueError("MetroPT-3 缺少可用的七天任务缓存及原始数据，请重新准备演示数据包")
        readings = _aggregate()
        CACHE_FILE.write_text(json.dumps(readings, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if not readings:
        raise ValueError("MetroPT-3 contains no readings")
    label_observed_history(readings)
    latest = readings[-1]
    pressure_gap = abs(float(latest["tp3_bar"]) - float(latest["reservoirs_bar"]))
    risk = min(.95, .03 + pressure_gap * .12 + max(float(latest["oil_temperature_c"]) - 75, 0) * .012)
    data = {
        "equipment": [{"equipment_id": EQUIPMENT_ID, "equipment_name": "MetroPT-3 空气生产单元", "equipment_type": "列车空气压缩机 APU", "status": "运行中", "production_line": "Metro do Porto", "data_origin": ORIGIN}],
        "readings": readings,
        "maintenance_rules": [{"equipment_id": EQUIPMENT_ID, "inspection_cost_cny": 800, "repair_cost_cny": 5500, "inspection_duration_h": 2, "assumed_failure_loss_cny": 20000, "repair_duration_h": 6, "required_staff_count": 2, "required_skill": "空气压缩机", "data_origin": "SIMULATED_BUSINESS_DATA"}],
        "maintenance_history": [{"maintenance_id": f"METROPT3-LEAK-{i}", "equipment_id": EQUIPMENT_ID, "maintenance_type": "空气泄漏故障区间", "maintenance_date": start.strftime("%Y-%m-%d %H:%M:%S"), "failure_end": end.strftime("%Y-%m-%d %H:%M:%S"), "data_origin": ORIGIN} for i, (start, end) in enumerate(FAILURES, 1)],
        "staff": [{"staff_id": "TECH-AIR-01", "staff_name": "压缩机维修员（模拟）", "available_hours": 8, "skills": "空气压缩机", "data_origin": "SIMULATED_BUSINESS_DATA"}, {"staff_id": "TECH-AIR-02", "staff_name": "机电维修员（模拟）", "available_hours": 8, "skills": "机电", "data_origin": "SIMULATED_BUSINESS_DATA"}],
        "orders": [{"order_id": "METRO-SERVICE-01", "equipment_id": EQUIPMENT_ID, "order_name": "列车供气保障任务（模拟）", "priority": "高", "data_origin": "SIMULATED_BUSINESS_DATA"}],
        "scenarios": [{"scenario_id": "METROPT3-BASE", "scenario_name": "MetroPT-3 长期运行维护情景", "maintenance_budget_cny": 10000, "risk_threshold": .25, "available_staff_count": 2, "max_downtime_h": 8, "data_origin": "SIMULATED_BUSINESS_DATA"}],
        "demo_risks": [{"equipment_id": EQUIPMENT_ID, "risk_score": round(risk, 4), "data_origin": "METROPT3_TRANSPARENT_RULE_BASELINE"}],
    }
    return complete_demo_business(data), readings[-1]["timestamp"][:10]
