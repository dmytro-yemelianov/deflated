#!/usr/bin/env python3
"""Validate and archive the v13 x86-64 counter attribution once.

The binaries were built and run on a shared Linux host and then deleted with
the work directory; this script checks internal consistency of the copied
receipts (hashes across measure/counters/record files and current sources).
"""
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "target/library-v13"
OUTPUT = ROOT / "scripts/reports/library-decode-v13-x86-counters.json.gz"
CORE = "01d69c4cf0aa438510c338a895f3242567a18b4e0120dd74e482e048a91c7d83"
ACCEL = "54a1ed18067d067edf455fb60ac03728bf01f4bed2557b2f97acad599a9d358e"
LINES = "069bc5a8837fd749cfa8fec1e1b3acfa09a280cbc5b7df6ddebfbd98a3087d47"
V3 = "0d6821f7cf8b8dd850a84edef4345aed35207734781d75e32fb12d084299a0ad"
NATIVE = {"zlib-ng": "2ae8a2bc8401681538be00450ccad891ea66d7589faa690afabc6dec01671cd5",
          "libdeflate": "29561e4c029203bff718573218f7590b5e662e8f253e57322045e199ca0b1049"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(relative):
    return json.loads((RUN / relative).read_text())


measure = load("measure/report.json")
counters = load("counters/counters.json")
environment = load("environment.json")
build = load("workers/build.json")
references = {c: load(f"references/{c}/build-receipt.json") for c in NATIVE}
lock = json.loads((ROOT / "scripts/reports/new-methods-reference-sources.json").read_text())

assert measure["methods"]["baseline"]["sha256"] == CORE
assert measure["methods"]["candidate"]["sha256"] == ACCEL
for codec, digest in NATIVE.items():
    assert measure["methods"][codec]["sha256"] == digest
    assert counters["binaries"][codec]["sha256"] == digest
    assert references[codec]["archive_sha256"] == lock[codec]["archive_sha256"]
assert counters["binaries"]["core"]["sha256"] == CORE
assert counters["binaries"]["accel"]["sha256"] == ACCEL
assert counters["binaries"]["core-x86-64-v3"]["sha256"] == V3
assert counters["measure_run_sha256"] == sha(RUN / "measure/report.json")
assert min(r["min_pct_running"] for r in counters["rows"]) == 100.0
assert environment["revision"] == measure["revision"]
for name in ("block.rs", "decode_table.rs"):
    assert environment[f"{name.replace('.', '_')}_sha256"] == sha(ROOT / "crates/deflate-core/src" / name)

records = {}
for path in sorted(RUN.glob("record-*/record.json")):
    record = json.loads(path.read_text())
    expected = LINES if "library_decode_reuse" in record["binary"] else NATIVE["libdeflate"]
    assert record["binary_sha256"] == expected, path
    records[path.parent.name] = record

supplementary = {}
for path in sorted((RUN / "supplementary").glob("l1split-*.csv")):
    values = {}
    for line in path.read_text().splitlines():
        fields = line.split(",")
        if len(fields) > 4 and not line.startswith("#"):
            values[fields[2].removesuffix(":u")] = float(fields[0])
    supplementary[path.stem] = {"counts": values,
                                "worker": json.loads(path.with_suffix(".json").read_text())}
for path in sorted((RUN / "supplementary").glob("topdown-*.txt")):
    text = path.read_text()
    supplementary[path.stem] = {"metrics_pct": {m[1]: float(m[0]) for m in
                                                re.findall(r"#\s+([\d.]+) %\s+(tma_\w+)", text)},
                                "text": text}
asm = {path.stem: path.read_text() for path in sorted((RUN / "asm").glob("*.asm"))}

receipt = {
    "schema_version": 1,
    "study": "library decode v13: x86-64 hardware-counter attribution (diagnostic)",
    "controller_sha256": sha(Path(__file__)),
    "helper_sha256": sha(ROOT / "scripts/library_x86_counters.py"),
    "environment": environment,
    "binaries": {"core": CORE, "accel": ACCEL, "core_line_tables": LINES,
                 "core_x86_64_v3": V3, **NATIVE},
    "native_build": build,
    "references": references,
    "throughput": measure,
    "counters": counters,
    "records": records,
    "supplementary": supplementary,
    "decode_tokens_asm": asm,
}
with OUTPUT.open("xb") as stream:
    stream.write(gzip.compress((json.dumps(receipt, separators=(",", ":")) + "\n").encode(), mtime=0))
for line in measure["summary"]:
    print(f"{line['frame']:4} {line['method']:10} {line['MB_per_s']:7.1f} MB/s")
print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size} bytes)")
