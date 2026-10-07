#!/usr/bin/env python3
"""One serial paid DSC1 training screen; never read/encode held input bodies."""
import argparse
import collections
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import time

from encoder_corpus import ROOT, digest, write_json
from structured_reference import decode as structured_decode
from test_native_codec_workers import independent, LEVELS
from test_new_methods_decoder_workers import roster

REPORTS = ROOT / "scripts/reports"
REAL_ROOT = ROOT / "target/new-methods/corpus-v1"
SYNTH_ROOT = ROOT / "target/new-methods/synthetic-v1"


def methods():
    result = []
    for codec, level, frame, enc_name, dec_name in roster():
        enc_root = "native-workers-v1" if codec in LEVELS else "rust-workers-v1"
        enc = ROOT / "target/new-methods" / enc_root / enc_name
        dec = ROOT / "target/new-methods/decode-workers-v1" / dec_name
        result.append({"id": f"{codec}:{level}:{frame}", "codec": codec, "level": level, "frame": frame,
                       "encoder": str(enc.relative_to(ROOT)), "decoder": str(dec.relative_to(ROOT)),
                       "encoder_sha256": digest(enc.read_bytes()), "decoder_sha256": digest(dec.read_bytes()),
                       "role": "candidate" if codec == "dsc1" and frame == "frame" else "control"})
    assert len(result) == 73 and sum(m["role"] == "candidate" for m in result) == 12
    return result


def cases():
    result = []
    for root, label in ((REAL_ROOT, "real"), (SYNTH_ROOT, "synthetic")):
        manifest = json.loads((root / "manifest.json").read_text())
        for case in manifest["cases"]:
            if "B" not in case["tracks"] or case["partition"] not in ("train", "stress"):
                continue
            path = root / case["path"]
            raw = path.read_bytes()
            assert digest(raw) == case["sha256"] and len(raw) == case["bytes"]
            result.append({"id": label + ":" + case["path"], "path": str(path.relative_to(ROOT)),
                           "sha256": case["sha256"], "bytes": case["bytes"], "family": case["family"],
                           "scope": "primary" if label == "real" else case["scope"],
                           "source_group": case.get("source_group", case["pair_id"] if "pair_id" in case else case["family"])})
    assert collections.Counter(c["scope"] for c in result) == {"primary": 8, "synthetic": 10, "long-stress": 1, "tiny": 12, "boundary": 9}
    return result


def guard_summary(rows, method):
    by_method = collections.defaultdict(dict)
    for row in rows:
        by_method[row["method"]][row["case"]] = row
    candidate = by_method[method]
    zstd = by_method["zstd:3:frame"]
    log2 = method.split(":")[1].split("/")[0]
    plain = by_method[f"dsc1:{log2}/off/off:plain"]
    primary = [key for key, row in candidate.items() if row["scope"] == "primary"]
    assert len(primary) == 8
    totals = lambda mapping, field: sum(mapping[key][field] for key in primary)
    packed_ratio = totals(candidate, "packed_bytes") / totals(zstd, "packed_bytes")
    plain_ratio = totals(candidate, "packed_bytes") / totals(plain, "packed_bytes")
    metrics = {"id": method, "primary_packed_bytes": totals(candidate, "packed_bytes"),
               "packed_ratio_vs_zstd3": packed_ratio, "packed_ratio_vs_plain": plain_ratio,
               "each_primary_packed_ratio_max": max(candidate[k]["packed_bytes"] / zstd[k]["packed_bytes"] for k in primary)}
    for timing in ("warm", "first"):
        metrics[timing + "_encode_speed_ratio"] = totals(zstd, timing + "_encode_ns") / totals(candidate, timing + "_encode_ns")
        metrics[timing + "_decode_time_ratio"] = totals(candidate, timing + "_decode_ns") / totals(zstd, timing + "_decode_ns")
    tiny = [key for key, row in candidate.items() if row["scope"] == "tiny"]
    metrics["each_tiny_time_ratio_max"] = max(candidate[k][timing + "_" + direction + "_ns"] / zstd[k][timing + "_" + direction + "_ns"]
                                              for k in tiny for timing in ("warm", "first") for direction in ("encode", "decode"))
    metrics["size_role_training_point_guards"] = (
        packed_ratio <= .95 and plain_ratio <= .98 and metrics["each_primary_packed_ratio_max"] <= 1.10
        and min(metrics[t + "_encode_speed_ratio"] for t in ("warm", "first")) >= .25
        and max(metrics[t + "_decode_time_ratio"] for t in ("warm", "first")) <= 3
        and metrics["each_tiny_time_ratio_max"] <= 2)
    metrics["compromise_stretch_training_point"] = packed_ratio <= 1.01 and min(metrics[t + "_encode_speed_ratio"] for t in ("warm", "first")) >= 1.10
    return metrics


def summarize(rows, method_list):
    candidates = [guard_summary(rows, m["id"]) for m in method_list if m["role"] == "candidate"]
    feasible = [m for m in candidates if m["size_role_training_point_guards"]]
    sentinel = min(feasible, key=lambda m: (m["primary_packed_bytes"], -m["warm_encode_speed_ratio"], m["id"]))["id"] if feasible else None
    return {"schema_version": 1, "phase": "one training session, point estimates only", "sentinel": sentinel,
            "decision": "confirm one B sentinel in three validation sessions" if sentinel else "early reject initial B family: no training point passes the preregistered role/common point guards",
            "selection_rule": "all primary size/plain/each-file/aggregate warm+first encode+decode and each-tiny point guards; smallest primary bytes, then warm encode speed, then ID",
            "inference_limit": "no confidence interval, independent holdout, RSS gate or frame-model proof follows from training",
            "candidates": sorted(candidates, key=lambda m: (m["primary_packed_bytes"], m["id"]))}


def sample(binary, mode, method, source, output, minimum, expected):
    start = time.perf_counter_ns()
    result = subprocess.run([str(binary), mode, method["codec"], method["level"], method["frame"],
                             str(source), str(output), str(minimum), str(expected)], capture_output=True, text=True)
    elapsed = time.perf_counter_ns() - start
    if result.returncode:
        raise RuntimeError(f"{method['id']} {mode}: {result.stderr}")
    return json.loads(result.stdout), elapsed


def run(out):
    if out.exists():
        raise ValueError("study attempt exists; preserve partial rows/live process, do not restart")
    subprocess.run(["python3", "scripts/new_methods_decoder_lock.py", "--check", "--local"], cwd=ROOT, check=True)
    proposal_start = time.perf_counter_ns()
    method_list, case_list = methods(), cases()
    proposal_ns = time.perf_counter_ns() - proposal_start
    protocol = json.loads((ROOT / "scripts/new_methods_protocol.json").read_text())
    intent = {"schema_version": 1, "phase": "B training", "sessions": 1, "seed": 2026100719,
              "tool_sha256": digest(Path(__file__).read_bytes()), "protocol_sha256": digest((ROOT / "scripts/new_methods_protocol.json").read_bytes()),
              "reference_lock_sha256": digest((REPORTS / "new-methods-reference-lock.json").read_bytes()),
              "decoder_lock_sha256": digest((REPORTS / "new-methods-decoder-lock.json").read_bytes()),
              "real_manifest_sha256": digest((REAL_ROOT / "manifest.json").read_bytes()),
              "synthetic_manifest_sha256": digest((SYNTH_ROOT / "manifest.json").read_bytes()),
              "methods": method_list, "cases": case_list, "host": platform.platform(), "python": sys.version,
              "selection_rule": "require all primary size/plain/each-file/aggregate encode+decode and each-tiny point guards; choose smallest primary bytes, then warm encode speed, then ID; otherwise early reject",
              "held_body_access": "none", "minimum_ns": {"ordinary": protocol["measurement"]["warm_minimum_ns"], "tiny": protocol["measurement"]["tiny_minimum_ns"]},
              "independent_decoder_binaries": {name: {"path": shutil.which(name), "sha256": digest(Path(shutil.which(name)).read_bytes())} for name in ("zstd", "lz4", "brotli")}}
    out.mkdir(parents=True)
    write_json(out / "intent.json", intent)
    write_json(out / "status.json", {"state": "running", "completed_rows": 0})
    pairs = [(c, m) for c in case_list for m in method_list]
    random.Random(intent["seed"]).shuffle(pairs)
    rows, process_ns, oracle_ns = [], 0, 0
    loop_start = time.perf_counter_ns()
    with (out / "rows.jsonl").open("x") as ledger:
        for index, (case, method) in enumerate(pairs):
            minimum = intent["minimum_ns"]["tiny" if case["scope"] == "tiny" else "ordinary"]
            raw_path = ROOT / case["path"]
            directory = out / "packets" / digest(case["id"].encode())[:16]
            directory.mkdir(parents=True, exist_ok=True)
            packet_path = directory / (digest(method["id"].encode())[:16] + ".packet")
            decoded_path = out / "decoded.raw"
            try:
                cold, elapsed = sample(ROOT / method["encoder"], "cold", method, raw_path, packet_path, 0, 0)
                process_ns += elapsed
                packet_sha = digest(packet_path.read_bytes())
                warm, elapsed = sample(ROOT / method["encoder"], "warm", method, raw_path, packet_path, minimum, 0)
                process_ns += elapsed
                packet = packet_path.read_bytes()
                assert digest(packet) == packet_sha, "first/warm packet drift"
                raw = raw_path.read_bytes()
                verify_start = time.perf_counter_ns()
                assert (structured_decode(packet) if method["codec"] == "dsc1" else independent(method["codec"], method["frame"], packet)) == raw
                oracle_ns += time.perf_counter_ns() - verify_start
                dec_cold, elapsed = sample(ROOT / method["decoder"], "cold", method, packet_path, decoded_path, 0, case["bytes"])
                process_ns += elapsed
                assert decoded_path.read_bytes() == raw
                dec_warm, elapsed = sample(ROOT / method["decoder"], "warm", method, packet_path, decoded_path, minimum, case["bytes"])
                process_ns += elapsed
                assert decoded_path.read_bytes() == raw
                decoded_path.unlink()
                assert cold["raw_bytes"] == warm["raw_bytes"] == dec_cold["raw_bytes"] == dec_warm["raw_bytes"] == case["bytes"]
                assert cold["packed_bytes"] == warm["packed_bytes"] == dec_cold["packed_bytes"] == dec_warm["packed_bytes"] == len(packet)
                assert cold["context"] == warm["context"] == "fresh"
                assert dec_cold["context"] == dec_warm["context"] == "fresh-decoder-only"
                assert dec_cold["encoder_calls"] == dec_warm["encoder_calls"] == 0
                assert cold["encode_iterations"] == dec_cold["decode_iterations"] == 1
                assert warm["encode_ns"] * warm["encode_iterations"] >= minimum - 10
                assert dec_warm["decode_ns"] * dec_warm["decode_iterations"] >= minimum - 10
                row = {"session": 0, "case": case["id"], "scope": case["scope"], "family": case["family"], "method": method["id"],
                       "raw_bytes": case["bytes"], "raw_sha256": case["sha256"], "packed_bytes": len(packet), "packet_sha256": packet_sha,
                       "packet_path": str(packet_path.relative_to(out)), "warm_encode_ns": warm["encode_ns"], "first_encode_ns": cold["first_encode_ns"],
                       "warm_decode_ns": dec_warm["decode_ns"], "first_decode_ns": dec_cold["first_decode_ns"],
                       "samples": {"cold_paired": cold, "warm_paired": warm, "cold_decoder_only": dec_cold, "warm_decoder_only": dec_warm}}
                rows.append(row)
                ledger.write(json.dumps(row, sort_keys=True) + "\n")
                ledger.flush()
                if (index + 1) % 25 == 0:
                    print("training rows", index + 1, "/", len(pairs), flush=True)
            except Exception as error:
                write_json(out / "status.json", {"state": "failed", "completed_rows": len(rows), "case": case["id"], "method": method["id"], "error": str(error)})
                raise
    selection_start = time.perf_counter_ns()
    summary = summarize(rows, method_list)
    selection_ns = time.perf_counter_ns() - selection_start
    wall = time.perf_counter_ns() - loop_start + proposal_ns
    summary["accounting"] = {"whole_loop_wall_ns": wall, "codec_process_wall_ns": process_ns, "independent_verification_wall_ns": oracle_ns,
                             "proposal_planning_wall_ns": proposal_ns, "selection_wall_ns": selection_ns,
                             "proposal_and_selection_share": (proposal_ns + selection_ns) / wall,
                             "scope": "CPU grid proposal/selection only; includes input integrity planning. No surrogate fitting or GPU use."}
    write_json(out / "summary.json", summary)
    write_json(out / "status.json", {"state": "complete", "completed_rows": len(rows), "intent_sha256": digest((out / "intent.json").read_bytes()),
                                    "rows_sha256": digest((out / "rows.jsonl").read_bytes()), "summary_sha256": digest((out / "summary.json").read_bytes())})
    print(json.dumps({"rows": len(rows), "sentinel": summary["sentinel"], "decision": summary["decision"], "top_candidates": summary["candidates"][:3]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/b-training-v1")
    args = parser.parse_args()
    run(args.out)
