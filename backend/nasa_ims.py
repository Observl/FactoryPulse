"""Adapter from NASA IMS vibration snapshots to FactoryPulse records."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from .demo_business import complete_demo_business

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "data" / "nasa_ims" / "last_15_days" / "4th_test" / "txt"
CACHE_FILE = ROOT / "data" / "nasa_ims" / "factorypulse_records.json"
ORIGIN = "NASA_IMS_BEARING_RUN_TO_FAILURE"


def _kurtosis(values: np.ndarray) -> float:
    centered = values - values.mean()
    variance = float(np.mean(centered * centered))
    return float(np.mean(centered**4) / (variance * variance)) if variance > 0 else 0.0


def build_nasa_ims() -> tuple[dict[str, list[dict]], str]:
    if CACHE_FILE.exists():
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return complete_demo_business(payload["tables"]), payload["source_date"]
    files = sorted(SOURCE_DIR.glob("20*"))
    if not files:
        raise FileNotFoundError(f"NASA IMS subset not found: {SOURCE_DIR}")
    last = datetime.strptime(files[-1].name, "%Y.%m.%d.%H.%M.%S")
    first = datetime.strptime(files[0].name, "%Y.%m.%d.%H.%M.%S")
    readings: list[dict] = []
    rms_by_channel: list[list[float]] = [[] for _ in range(4)]
    for path in files:
        timestamp = datetime.strptime(path.name, "%Y.%m.%d.%H.%M.%S")
        matrix = np.loadtxt(path, delimiter="\t", dtype=np.float32)
        for channel in range(4):
            values = matrix[:, channel]
            rms = float(np.sqrt(np.mean(values * values)))
            rms_by_channel[channel].append(rms)
            equipment_id = f"IMS-B{channel + 1}"
            is_failed_bearing = channel == 2
            hours_to_failure = (last - timestamp).total_seconds() / 3600
            readings.append({
                "reading_id": f"{equipment_id}-{path.name}", "equipment_id": equipment_id,
                "timestamp": timestamp.isoformat(sep=" "), "vibration_g": round(rms, 6),
                "vibration_peak_g": round(float(np.max(np.abs(values))), 6),
                "vibration_kurtosis": round(_kurtosis(values), 6), "sample_rate_hz": 20000,
                "sample_points": int(values.size),
                "future_failure": None if hours_to_failure < 168 else 0,
                "prediction_horizon_hours": 168,
                "failure": int(is_failed_bearing and timestamp == last), "data_origin": ORIGIN,
            })
    risks = []
    for channel, values in enumerate(rms_by_channel):
        baseline = max(float(np.median(values[: max(12, len(values)//5)])), 1e-6)
        ratio = values[-1] / baseline
        score = .98 if channel == 2 else min(max((ratio - 1) / 5, 0.02), .98)
        risks.append({"equipment_id": f"IMS-B{channel+1}", "risk_score": round(score, 4), "data_origin": "NASA_IMS_VIBRATION_HEURISTIC_BASELINE"})
    equipment = [{"equipment_id": f"IMS-B{i}", "equipment_name": f"主轴轴承测点 {i}", "equipment_type": "滚动轴承（NASA IMS实验台）", "status": "预警" if i == 3 else "运行中", "production_line": "NASA IMS Test 3", "data_origin": ORIGIN} for i in range(1, 5)]
    rules = [{"equipment_id": f"IMS-B{i}", "inspection_cost_cny": 300, "repair_cost_cny": 2400, "inspection_duration_h": 1, "repair_duration_h": 3, "assumed_failure_loss_cny": 18000, "required_staff_count": 1, "required_skill": "轴承", "data_origin": "SIMULATED_BUSINESS_DATA"} for i in range(1, 5)]
    tables = {
        "equipment": equipment, "readings": readings, "maintenance_rules": rules,
        "maintenance_history": [{"maintenance_id": "IMS-FAIL-B3", "equipment_id": "IMS-B3", "maintenance_type": "外圈故障实验终止", "maintenance_date": last.isoformat(sep=" "), "data_origin": ORIGIN}],
        "staff": [{"staff_id": "TECH-01", "staff_name": "轴承维修工程师", "skills": "轴承,机修", "available_hours": 8, "data_origin": "SIMULATED_BUSINESS_DATA"}],
        "orders": [{"order_id": f"IMS-ORDER-{i}", "equipment_id": f"IMS-B{i}", "priority": "高" if i == 3 else "普通", "data_origin": "SIMULATED_BUSINESS_DATA"} for i in range(1, 5)],
        "scenarios": [{"scenario_id": "NASA-IMS-BASE", "scenario_name": "NASA IMS轴承维护情景", "maintenance_budget_cny": 6000, "risk_threshold": .35, "available_staff_count": 1, "max_downtime_h": 8, "data_origin": "SIMULATED_BUSINESS_DATA"}],
        "demo_risks": risks,
    }
    CACHE_FILE.write_text(json.dumps({"source_date": last.date().isoformat(), "range_start": first.isoformat(), "range_end": last.isoformat(), "tables": tables}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return complete_demo_business(tables), last.date().isoformat()
