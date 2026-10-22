"""Produce a JSON fixture bundle and independently reconcile its evaluation."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.model_validation_data import load_acceptance_dataset, build_model_validation, SEED, ORIGIN, SENSOR_FIELDS
from backend.analytics import xgboost_with_shap, chronological_partitions


def verify_metrics(model):
    evaluation = model.evaluation
    counts = Counter((int(row["observed_future_failure"]), bool(row["alert"])) for row in model.replay)
    tp, fp, fn, tn = (counts[key] for key in ((1, True), (0, True), (1, False), (0, False)))
    expected = {"true_positives": tp, "false_positives": fp, "false_negatives": fn, "true_negatives": tn,
                "test_rows": tp + fp + fn + tn, "positive_windows": tp + fn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else 0,
                "recall": round(tp / (tp + fn), 4) if tp + fn else 0,
                "false_alarm_rate": round(fp / (fp + tn), 4) if fp + tn else 0,
                "f1": round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else 0}
    for key, value in expected.items():
        if evaluation.get(key) != value:
            raise ValueError(f"逐窗口复算不一致：{key}")
    # Reconstruct independent event lead directly from timestamped alert records.
    leads = []
    for event in evaluation["events"]:
        onset = datetime.fromisoformat(event["failure_at"])
        hits = [datetime.fromisoformat(row["timestamp"]) for row in model.replay
                if row["equipment_id"] == event["equipment_id"] and row["alert"]
                and 0 < (onset - datetime.fromisoformat(row["timestamp"])).total_seconds() <= 168 * 3600]
        lead = (onset - min(hits)).total_seconds() / 3600 if hits else None
        if event["detected"] != bool(hits) or event["lead_hours"] != lead:
            raise ValueError("事件检出或提前量复算不一致")
        if lead is not None:
            leads.append(lead)
    average = round(sum(leads) / len(leads), 2) if leads else None
    if evaluation["average_lead_hours"] != average:
        raise ValueError("平均提前量复算不一致")
    return {"window_metrics": expected, "average_lead_hours": average,
            "detected_events": len(leads), "checked_events": len(evaluation["events"]), "passed": True}


def build(destination, anchor):
    if anchor != datetime(2026,10,21): raise ValueError("验收输入已冻结，请勿更换日期重新生成测试集")
    tables, source_date = load_acceptance_dataset(refresh_business=False)
    model = xgboost_with_shap(tables["readings"])
    if model.status != "ready" or len(model.predictions) != len(tables["equipment"]):
        raise ValueError("模型未完整生成设备评分：" + model.message)
    reconciliation = verify_metrics(model)
    usable = [r for r in tables["readings"] if r["future_failure"] in (0, 1) and not r["failure"]]
    partitions = chronological_partitions(usable, 168)
    split_counts = {name: {"rows": len(rows), "positive": sum(r["future_failure"] == 1 for r in rows),
                           "negative": sum(r["future_failure"] == 0 for r in rows),
                           "start": min(r["timestamp"] for r in rows), "end": max(r["timestamp"] for r in rows)}
                    for name, rows in zip(("train", "validation", "test"), partitions)}
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {"dataset.json": {"format": "factorypulse-record-tables-v1", "source_date": source_date, "tables": tables},
                 "evaluation.json": {"origin": ORIGIN, "status": model.status, "model_version": model.model_version,
                                     "predictions": model.predictions, "explanations": model.explanations,
                                     "evaluation": model.evaluation, "split_counts": split_counts,
                                     "reconciliation": reconciliation},
                 "test-replay.json": model.replay,
                 "fault-events.json": tables["maintenance_history"]}
    manifest = {"origin": ORIGIN, "seed": SEED, "anchor": anchor.isoformat(), "sensor_fields": SENSOR_FIELDS,
                "counts": {key: len(value) for key, value in tables.items()},
                "purpose": "仅用于程序全流程、时间切分、模型评分与指标计算验证；不是实际工业数据或现场准确性证据",
                "files": {}}
    for name, content in artifacts.items():
        raw = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        (destination / name).write_bytes(raw)
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    target = destination / "FactoryPulse-model-validation-v1.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in (*artifacts, "manifest.json"):
            archive.write(destination / name, name)
    return model, manifest, target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/model-validation-v1")
    parser.add_argument("--anchor", default="2026-10-21")
    args = parser.parse_args()
    model, manifest, archive = build(args.output, datetime.fromisoformat(args.anchor))
    print(json.dumps({"archive": str(archive), "counts": manifest["counts"], "metrics": model.evaluation}, ensure_ascii=False))
