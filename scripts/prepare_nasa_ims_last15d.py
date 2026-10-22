"""Extract the chronologically latest 15 days from the official NASA IMS archive."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "nasa_ims"
ARCHIVE_DIR = DATA_DIR / "archives"
OUTPUT_DIR = DATA_DIR / "last_15_days"
SOURCE_URL = "https://phm-datasets.s3.amazonaws.com/NASA/4.+Bearings.zip"
STAMP = re.compile(r"(\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2})$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_members(path: Path) -> list[tuple[str, datetime]]:
    result = subprocess.run(
        ["tar", "-tf", str(path)], check=True, capture_output=True, text=True
    )
    members: list[tuple[str, datetime]] = []
    for name in result.stdout.splitlines():
        match = STAMP.search(name.strip())
        if match:
            members.append((name.strip(), datetime.strptime(match.group(1), "%Y.%m.%d.%H.%M.%S")))
    return members


def main() -> None:
    archives = sorted(ARCHIVE_DIR.glob("*_test.rar"))
    if not archives:
        raise SystemExit("No IMS experiment archives found")

    indexed = [(archive, *item) for archive in archives for item in archive_members(archive)]
    latest = max(timestamp for _, _, timestamp in indexed)
    cutoff = latest - timedelta(days=15)
    selected = [(archive, name, timestamp) for archive, name, timestamp in indexed if timestamp >= cutoff]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    experiments: dict[str, list[str]] = {}
    for archive, name, _ in selected:
        experiments.setdefault(archive.name, []).append(name)

    for archive_name, members in experiments.items():
        archive = ARCHIVE_DIR / archive_name
        include_file = DATA_DIR / f"{archive.stem}_last15d_files.txt"
        include_file.write_text("\n".join(members) + "\n", encoding="utf-8")
        subprocess.run(
            ["tar", "-xf", str(archive), "-C", str(OUTPUT_DIR), "-T", str(include_file)],
            check=True,
        )

    manifest = {
        "dataset": "NASA IMS Bearing Data Set",
        "source_url": SOURCE_URL,
        "source_archive": "NASA_IMS_Bearings.zip",
        "source_sha256": sha256(DATA_DIR / "NASA_IMS_Bearings.zip"),
        "selection_rule": "timestamp >= global maximum timestamp minus 15 days",
        "cutoff_inclusive": cutoff.isoformat(),
        "maximum_timestamp": latest.isoformat(),
        "selected_file_count": len(selected),
        "selected_experiments": sorted(experiments),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": "Experimental run-to-failure vibration data; not factory production data.",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
