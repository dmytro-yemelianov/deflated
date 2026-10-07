#!/usr/bin/env python3
"""Publish/audit the complete one-session B negative; no study rescreening."""
import argparse
import collections
import gzip
import json
import math
from pathlib import Path

from encoder_corpus import ROOT, digest, write_json
from new_methods_b_screen import summarize

REPORTS = ROOT / "scripts/reports"
PREFIX = "new-methods-b-training"


def read(name):
    path = REPORTS / name
    return gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()


def scope_scores(rows):
    groups = collections.defaultdict(list)
    for row in rows:
        groups[(row["scope"], row["method"])].append(row)
    scores = []
    for (scope, method), selected in sorted(groups.items()):
        scores.append({"scope": scope, "method": method, "cases": len(selected),
                       **{field: sum(row[field] for row in selected) for field in
                          ("raw_bytes", "packed_bytes", "warm_encode_ns", "first_encode_ns", "warm_decode_ns", "first_decode_ns")}})
    return {"schema_version": 1, "scope": "training/shared stress only; complete per-scope sums, no confidence intervals", "scores": scores}


def assert_recomputed(stored, calculated, path):
    """Allow four float ULPs across Python versions; keep decisions/counts exact."""
    assert type(stored) is type(calculated), path
    if isinstance(stored, float):
        assert math.isfinite(stored) and math.isfinite(calculated), path
        tolerance = 4 * max(math.ulp(stored), math.ulp(calculated))
        assert abs(stored - calculated) <= tolerance, path
    elif isinstance(stored, dict):
        assert stored.keys() == calculated.keys(), path
        for key in stored:
            assert_recomputed(stored[key], calculated[key], f"{path}.{key}")
    elif isinstance(stored, list):
        assert len(stored) == len(calculated), path
        for index, (left, right) in enumerate(zip(stored, calculated)):
            assert_recomputed(left, right, f"{path}[{index}]")
    else:
        assert stored == calculated, path


def audit(local=None):
    intent_body = read(PREFIX + "-intent.json.gz")
    row_body = read(PREFIX + "-rows.jsonl.gz")
    summary_body = read(PREFIX + "-summary.json")
    status = json.loads(read(PREFIX + "-status.json"))
    intent = json.loads(intent_body)
    rows = [json.loads(line) for line in row_body.splitlines()]
    summary = json.loads(summary_body)
    assert status["state"] == "complete" and status["completed_rows"] == len(rows) == 2920
    assert status["intent_sha256"] == digest(intent_body)
    assert status["rows_sha256"] == digest(row_body)
    assert status["summary_sha256"] == digest(summary_body)
    assert intent["sessions"] == 1 and intent["held_body_access"] == "none"
    assert intent["tool_sha256"] == digest((ROOT / "scripts/new_methods_b_screen.py").read_bytes())
    assert intent["protocol_sha256"] == digest((ROOT / "scripts/new_methods_protocol.json").read_bytes())
    for key, name in (("reference_lock_sha256", "new-methods-reference-lock.json"),
                      ("decoder_lock_sha256", "new-methods-decoder-lock.json"),
                      ("real_manifest_sha256", "new-methods-corpus.json.gz"),
                      ("synthetic_manifest_sha256", "new-methods-synthetic.json.gz")):
        assert intent[key] == digest(read(name)), key
    method_map = {m["id"]: m for m in intent["methods"]}
    case_map = {c["id"]: c for c in intent["cases"]}
    assert len(method_map) == 73 and len(case_map) == 40
    assert collections.Counter(c["scope"] for c in case_map.values()) == {"primary": 8, "synthetic": 10, "long-stress": 1, "tiny": 12, "boundary": 9}
    assert all("/train/" in c["path"] or "/stress/" in c["path"] for c in case_map.values())
    assert {(r["case"], r["method"]) for r in rows} == {(c, m) for c in case_map for m in method_map}
    for row in rows:
        case = case_map[row["case"]]
        assert row["session"] == 0 and row["scope"] == case["scope"]
        assert row["raw_bytes"] == case["bytes"] and row["raw_sha256"] == case["sha256"]
        sample = row["samples"]
        assert row["first_encode_ns"] == sample["cold_paired"]["first_encode_ns"]
        assert row["warm_encode_ns"] == sample["warm_paired"]["encode_ns"]
        assert row["first_decode_ns"] == sample["cold_decoder_only"]["first_decode_ns"]
        assert row["warm_decode_ns"] == sample["warm_decoder_only"]["decode_ns"]
        minimum = intent["minimum_ns"]["tiny" if case["scope"] == "tiny" else "ordinary"]
        assert sample["warm_paired"]["encode_ns"] * sample["warm_paired"]["encode_iterations"] >= minimum - 10
        assert sample["warm_decoder_only"]["decode_ns"] * sample["warm_decoder_only"]["decode_iterations"] >= minimum - 10
        assert sample["cold_paired"]["encode_iterations"] == sample["cold_decoder_only"]["decode_iterations"] == 1
        assert sample["cold_decoder_only"]["encoder_calls"] == sample["warm_decoder_only"]["encoder_calls"] == 0
        assert sample["cold_decoder_only"]["context"] == sample["warm_decoder_only"]["context"] == "fresh-decoder-only"
        if local:
            assert digest((local / row["packet_path"]).read_bytes()) == row["packet_sha256"]
            assert digest((ROOT / case["path"]).read_bytes()) == case["sha256"]
    calculated = summarize(rows, intent["methods"])
    assert_recomputed({key: summary[key] for key in calculated}, calculated, "summary")
    assert summary["sentinel"] is None and len(summary["candidates"]) == 12
    assert all(not c["size_role_training_point_guards"] for c in summary["candidates"])
    assert_recomputed(json.loads(read(PREFIX + "-scopes.json")), scope_scores(rows), "scopes")
    print("Published B one-session roster/timers/guard/negative audit passed" + ("; local packet/raw hashes checked" if local else ""))


def publish(source):
    files = [("intent.json", "-intent.json.gz"), ("rows.jsonl", "-rows.jsonl.gz"),
             ("summary.json", "-summary.json"), ("status.json", "-status.json")]
    if any((REPORTS / (PREFIX + suffix)).exists() for _, suffix in files):
        raise ValueError("published B evidence already exists; refusing replacement")
    assert json.loads((source / "status.json").read_text())["state"] == "complete"
    for filename, suffix in files:
        raw = (source / filename).read_bytes()
        (REPORTS / (PREFIX + suffix)).write_bytes(gzip.compress(raw, mtime=0) if suffix.endswith(".gz") else raw)
    rows = [json.loads(line) for line in (source / "rows.jsonl").read_text().splitlines()]
    write_json(REPORTS / (PREFIX + "-scopes.json"), scope_scores(rows))
    audit(local=source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "target/new-methods/b-training-v1")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    if args.check:
        audit(args.source if args.local else None)
    else:
        publish(args.source)
