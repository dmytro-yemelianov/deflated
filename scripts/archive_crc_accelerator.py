#!/usr/bin/env python3
"""Validate and archive the v11 CRC accelerator measurements once."""
import csv
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "target/library-v11/real-reuse-current-core/report.json"
PROBE = ROOT / "target/library-v11/crc32-probe.csv"
OUTPUT = ROOT / "scripts/reports/library-decode-v11-crc-accelerator.json.gz"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


report = json.loads(REPORT.read_text())
for relative, digest in report["source_sha256"].items():
    assert sha(ROOT / relative) == digest, relative
for method in report["methods"].values():
    assert sha(Path(method["binary"])) == method["sha256"], method["binary"]

probe_rows = list(csv.DictReader(PROBE.open()))
assert len(probe_rows) == 98
probe = ROOT / "crates/deflate-accel/examples/crc32_probe.rs"
checks = {}
for row in probe_rows:
    checks.setdefault(row["size"], set()).add(row["checksum"])
assert len(checks) == 7 and all(len(values) == 1 for values in checks.values())

receipt = {
    "schema_version": 1,
    "study": "deflate-accel CRC32 backend v11",
    "controller_sha256": sha(Path(__file__)),
    "reused_decode_report": report,
    "crc_microbenchmark": {
        "source": str(probe.relative_to(ROOT)),
        "source_sha256": sha(probe),
        "csv_sha256": sha(PROBE),
        "rows": probe_rows,
        "checksums_match_for_every_size": True,
        "command": "cargo run --release -p deflate-accel --example crc32_probe",
    },
}
with OUTPUT.open("xb") as stream:
    stream.write(
        gzip.compress((json.dumps(receipt, separators=(",", ":")) + "\n").encode(), mtime=0)
    )
print(f"Archived {len(report['rows'])} timed decoder rows and {len(probe_rows)} CRC samples")
