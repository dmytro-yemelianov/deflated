#!/usr/bin/env python3
"""Sample the exact frozen v5 reuse workers serially (macOS /usr/bin/sample).

Profile-run timings include profiler interference and must not be benchmarks.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def leaves(text):
    section = text.split("Sort by top of stack, same collapsed", 1)[1].split("Binary Images:", 1)[0]
    found = []
    for line in section.splitlines():
        match = re.match(r"\s+(.+?)\s+([0-9]+)\s*$", line)
        if match:
            found.append({"symbol": match[1].strip(), "samples": int(match[2])})
    totals = re.findall(r"^\s+(\d+) Thread_", text, re.MULTILINE)
    if len(totals) != 1:
        raise ValueError("expected one sampled worker thread")
    total = int(totals[0])
    if not total:
        raise ValueError("no sampled leaf stacks")
    return total, found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=Path("scripts/reports/library-decode-v5-reuse-real.json.gz"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    receipt = json.loads(gzip.decompress(args.receipt.read_bytes()))
    for method in receipt["methods"].values():
        assert sha(Path(method["binary"])) == method["sha256"], "frozen worker changed"
    records = []
    for case in ["go", "inter", "otel"]:
        for frame in ["raw", "gzip"]:
            packet = next(r for r in receipt["rows"] if r["case"] == case and r["frame"] == frame and r["encoder"] == "zlib-6")
            assert sha(Path(packet["path"])) == packet["packet_sha256"]
            for method, codec in [("candidate", "core"), ("zlib-ng", "zlib-ng"), ("libdeflate", "libdeflate")]:
                name = f"{case}-{frame}-{method}"
                output = args.out / (name + ".output")
                sample = args.out / (name + ".sample.txt")
                command = [receipt["methods"][method]["binary"], "context-warm", codec, "balanced" if codec == "core" else "6", frame, packet["path"], str(output), "4000000000", str(packet["raw_bytes"])]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                sampler = subprocess.run(["/usr/bin/sample", str(process.pid), "2", "1", "-file", str(sample)], capture_output=True, text=True)
                stdout, stderr = process.communicate(timeout=15)
                if sampler.returncode or process.returncode:
                    raise RuntimeError((sampler.stderr, stderr))
                assert sha(output) == packet["raw_sha256"], "profiled output mismatch"
                text = sample.read_text()
                count, symbols = leaves(text)
                records.append({"case": case, "frame": frame, "method": method, "command": command,
                                "worker_sha256": receipt["methods"][method]["sha256"],
                                "packet_sha256": packet["packet_sha256"], "raw_sha256": packet["raw_sha256"],
                                "sample_path": str(sample), "sample_sha256": sha(sample), "sample_count": count,
                                "leaf_samples": symbols, "omitted_leaf_samples": count - sum(s["samples"] for s in symbols), "interfered_worker_result": json.loads(stdout)})
                print(name, count, "samples", flush=True)
    report = {"source_receipt_sha256": sha(args.receipt), "method": "2-second sample at 1 ms during a 4-second reused-state/output loop; serial, one packet per process",
              "limitations": "Leaf symbols include inlined code; sample hides leaf totals below 5. Denominator is all main-thread samples. Profiler changes timing; no performance ratios from these runs.", "profiles": records}
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
