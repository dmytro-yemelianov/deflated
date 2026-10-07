#!/usr/bin/env python3
"""Serial frozen S2/S3 campaign, regression validation and process memory.

Run with the optional pinned Optuna research environment. Corpus downloads
are separate; real payloads and packed streams remain under ignored target/.
"""
import argparse
import collections
import copy
import datetime
import hashlib
import itertools
import json
import math
import pathlib
import platform
import random
import re
import statistics
import subprocess
import sys
import time
import uuid

from search_cpu import (CONTROLS, aggregate, identity, measure_rows, select_finalists,
                        source_files, worker_method, write_json)
from search_corpus import ROOT
from search_poc import decode_exact, sha
from search_workloads import validate_groups


def factorial_configs(axes, seed):
    configs = [dict(zip(axes, values)) for values in itertools.product(*axes.values())]
    if len({identity(c) for c in configs}) != len(configs):
        raise ValueError("duplicate factorial configurations")
    random.Random(seed).shuffle(configs)
    return configs


def hypervolume(points, reference):
    xref, yref = reference
    if not all(math.isfinite(v) and v > 0 for v in reference):
        raise ValueError("invalid hypervolume reference")
    usable = []
    for x, y in points:
        if not (math.isfinite(x) and math.isfinite(y) and x > 0 and y > 0):
            raise ValueError("invalid objective")
        if x < xref and y < yref:
            usable.append((x, y))
    previous = yref
    area = 0.0
    for x, y in sorted(usable):
        if y < previous:
            area += (xref - x) * (previous - y)
            previous = y
    return area


def confidence(rows, cases, resamples, seed):
    """Resample source/family groups and paired round indices within files."""
    if not rows or resamples < 2:
        raise ValueError("bootstrap needs measurements and resamples")
    meta = {pathlib.PurePosixPath(c["path"]).name: c for c in cases}
    groups = collections.defaultdict(list)
    for row in rows:
        case = meta[row["input"]]
        group = case.get("source_file", "synthetic:" + case["family"])
        groups[group].append(row)
    blocks = list(groups.values())
    rng = random.Random(seed)
    speeds, sizes = [], []
    for _ in range(resamples):
        candidate_ns = baseline_ns = packed = baseline_packed = 0
        for _ in blocks:
            for row in rng.choice(blocks):
                rounds = len(row["samples_ns"])
                indices = [rng.randrange(rounds) for _ in range(rounds)]
                candidate_ns += statistics.median(row["samples_ns"][i] for i in indices)
                baseline_ns += statistics.median(row["baseline_samples_ns"][i] for i in indices)
                packed += row["packed_bytes"]
                baseline_packed += row["baseline_bytes"]
        speeds.append(baseline_ns / candidate_ns)
        sizes.append(100 * (packed / baseline_packed - 1))
    def interval(values):
        values.sort()
        return [values[int(.025 * len(values))], values[min(len(values) - 1, int(.975 * len(values)))]]
    return {"groups": len(blocks), "resamples": resamples,
            "speed_multiple_95pct": interval(speeds), "size_delta_pct_95pct": interval(sizes)}


def freeze_finalists(studies, previous, protocol):
    configs, origins = {}, collections.defaultdict(list)
    def add(config, origin):
        key = identity(config)
        configs[key] = config
        origins[key].append(origin)
    for study in studies:
        for role, key in study["finalists"]["roles"].items():
            add(study["finalists"]["configs"][key], f"{study['strategy']}:{study['seed']}:{role}")
    for config in CONTROLS:
        add(config, "production control")
    for name in protocol["reference_controls"]:
        add({"reference": name}, "reference control")
    for study in previous["studies"]:
        for config in study["finalists"]["configs"].values():
            add(config, "prior synthetic sentinel")
    # Choose representatives using training only. Repeated measurements of a
    # config contribute median normalized time; exact compressed sizes agree.
    measurements = collections.defaultdict(list)
    for study in studies:
        for trial in study["training"]:
            measurements[trial["id"]].append(trial)
    candidates = []
    for key, trials in measurements.items():
        agg = copy.deepcopy(trials[0]["aggregate"])
        if len({t["aggregate"]["packed_bytes"] for t in trials}) != 1:
            raise ValueError("same config produced different training size")
        agg["time_vs_paired_balanced"] = statistics.median(t["aggregate"]["time_vs_paired_balanced"] for t in trials)
        candidates.append({"id": key, "config": trials[0]["config"], "aggregate": agg})
    roles = select_finalists(candidates, protocol["balanced_training_size_tolerance"])
    by_id = {t["id"]: t for t in candidates}
    for role, key in roles.items():
        add(by_id[key]["config"], "global training representative:" + role)
    return {"selection": "training only; no validation feedback or production promotion",
            "configs": configs, "origins": dict(origins), "representatives": roles}


def rss_bytes(output, system):
    if system == "Darwin":
        found = re.findall(r"^\s*(\d+)\s+maximum resident set size\s*$", output, re.MULTILINE)
        scale = 1  # current local getrusage(2) documents bytes
    elif system == "Linux":
        found = re.findall(r"^rss_kib=(\d+)\s*$", output, re.MULTILINE)
        scale = 1024  # GNU time %M is KiB
    else:
        raise ValueError("memory measurement supports Darwin and GNU time on Linux")
    if len(found) != 1 or int(found[0]) <= 0:
        raise ValueError("missing, duplicate or invalid maximum RSS")
    return int(found[0]) * scale


def relative_summary(rows, baseline):
    result = aggregate(rows)
    if baseline != "balanced":
        for old, new in (("speed_vs_paired_balanced", "speed_vs_reference"),
                         ("time_vs_paired_balanced", "time_vs_reference"),
                         ("size_vs_balanced", "size_vs_reference")):
            result[new] = result.pop(old)
    return result


def measure_memory(binary, corpus, cases, frozen, out, repetitions, expected_rows):
    system = platform.system()
    selected = [max([c for c in cases if (c["family"] == "real") == real], key=lambda c: (c["bytes"], c["path"]))
                for real in (True, False)]
    result = []
    for case in selected:
        name = pathlib.PurePosixPath(case["path"]).name
        for index, (key, config) in enumerate(sorted(frozen["configs"].items())):
            samples = []
            trial = out / key / name
            trial.mkdir(parents=True)
            for repeat in range(repetitions):
                packed = trial / f"{repeat}.deflate"
                cmd = (["/usr/bin/time", "-l"] if system == "Darwin" else ["/usr/bin/time", "-f", "rss_kib=%M"])
                command = cmd + [str(binary), "--memory", str(corpus / case["path"]), str(packed), worker_method(config)]
                measured = subprocess.run(command, text=True, capture_output=True, timeout=600, check=True)
                (trial / f"{repeat}.stderr").write_text(measured.stderr)
                native = json.loads(measured.stdout)
                raw = (corpus / case["path"]).read_bytes()
                stream = packed.read_bytes()
                decode_exact(stream, raw)  # outside the measured native process
                witness = expected_rows[key][name]
                if native["raw_bytes"] != len(raw) or native["packed_bytes"] != len(stream) or hashlib.sha256(stream).hexdigest() != witness["packed_sha256"]:
                    raise ValueError("memory worker stream differs from validated timing worker")
                samples.append(rss_bytes(measured.stderr, system))
            result.append({"id": key, "input": name, "raw_bytes": case["bytes"], "samples_rss_bytes": samples,
                           "median_rss_bytes": statistics.median(samples), "peak_rss_bytes": max(samples)})
    return {"system": system, "scope": "single native encode process, includes runtime/input/output and file I/O; no decoder or timing loop",
            "tool": "/usr/bin/time -l" if system == "Darwin" else "GNU time %M, KiB converted to bytes",
            "cases": [c["path"] for c in selected], "repetitions": repetitions, "measurements": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=pathlib.Path, default=ROOT / "scripts/search_protocol.json")
    parser.add_argument("--corpus", type=pathlib.Path, default=ROOT / "target/search/corpus-mixed-s2")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    corpus = args.corpus.resolve()
    manifest_path = corpus / "manifest.json"
    meta = json.loads(manifest_path.read_text())
    validate_groups(corpus, meta)
    if meta["chunk_bytes"] != protocol["training_chunk_bytes"]:
        raise ValueError("corpus and protocol chunk sizes differ")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = (args.out or ROOT / "target/search/campaigns" / stamp).resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    sources = {p: sha(ROOT / p) for p in source_files()}
    protocol_hash = sha(args.protocol)
    manifest_hash = sha(manifest_path)
    write_json(out / "protocol.json", protocol)
    write_json(out / "provenance.json", {"source_sha256": sources, "protocol_sha256": protocol_hash,
               "manifest_sha256": manifest_hash, "python": platform.python_version(),
               "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()})
    factorial = factorial_configs(protocol["factorial"], protocol["factorial_seed"])
    write_json(out / "factorial-configs.json", factorial)
    schedule = [(strategy, seed) for i, seed in enumerate(protocol["seeds"])
                for strategy in protocol["strategies"][i:] + protocol["strategies"][:i]]
    schedule.append(("fixed", protocol["factorial_seed"]))
    write_json(out / "schedule.json", schedule)
    studies = []
    def guard():
        if sources != {p: sha(ROOT / p) for p in sources} or protocol_hash != sha(args.protocol) or manifest_hash != sha(manifest_path):
            raise ValueError("campaign sources/protocol/manifest changed")
        validate_groups(corpus, meta)
    for index, (strategy, seed) in enumerate(schedule):
        trial_out = out / f"{index:02}-{strategy}-{seed}"
        command = [sys.executable, str(ROOT / "scripts/search_cpu.py"), "--strategy", strategy,
                   "--seed", str(seed), "--trials", str(len(factorial) if strategy == "fixed" else protocol["configured_trials_per_strategy_seed"]),
                   "--rounds", str(protocol["training_rounds"]), "--min-ms", str(protocol["training_minimum_batch_ms"]),
                   "--trial-timeout", str(protocol["trial_timeout_seconds"]), "--size-tolerance", str(protocol["balanced_training_size_tolerance"]),
                   "--training-only", "--corpus", str(corpus), "--out", str(trial_out)]
        if strategy == "fixed":
            command += ["--fixed-configs", str(out / "factorial-configs.json")]
        print("study", index, strategy, seed, flush=True)
        with (out / f"{index:02}-study.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, check=True)
        study = json.loads((trial_out / "result.json").read_text())
        study["directory"] = str(trial_out.relative_to(ROOT))
        studies.append(study)
        guard()
    previous = json.loads((ROOT / "scripts/reports/search-cpu-spike.json").read_text())
    frozen = freeze_finalists(studies, previous, protocol)
    write_json(out / "finalists.json", frozen)
    frozen_hash = sha(out / "finalists.json")
    binary = ROOT / studies[0]["binary_path"]
    binary_hash = sha(binary)
    if any(s["binary_sha256"] != binary_hash for s in studies):
        raise ValueError("study binary hashes differ")
    validation_cases = [c for c in meta["cases"] if c["partition"] == "validation"]
    validation = []
    expected_rows = {}
    def validate_config(key, config, label, baseline="balanced"):
        trial = out / label / key
        trial.mkdir(parents=True)
        print(label, key[:8], config, "vs", baseline, flush=True)
        rows = measure_rows(binary, config, corpus, "validation", validation_cases, trial,
                            protocol["validation_rounds"], protocol["validation_minimum_batch_ms"], protocol["trial_timeout_seconds"], baseline)
        guard()
        if sha(binary) != binary_hash or sha(out / "finalists.json") != frozen_hash:
            raise ValueError("binary or finalists changed during validation")
        result = {"id": key, "config": config, "baseline": baseline, "rows": rows, "aggregate": relative_summary(rows, baseline)}
        for scope, cases in (("real", [c for c in validation_cases if c["family"] == "real"]),
                             ("synthetic", [c for c in validation_cases if c["family"] != "real"])):
            names = {pathlib.PurePosixPath(c["path"]).name for c in cases}
            subset = [r for r in rows if r["input"] in names]
            result[scope] = {"aggregate": relative_summary(subset, baseline), "confidence": confidence(subset, cases,
                            protocol["bootstrap"]["resamples"], protocol["bootstrap"]["seed"])}
        write_json(trial / "result.json", result)
        return result
    for key, config in sorted(frozen["configs"].items()):
        result = validate_config(key, config, "validation")
        expected_rows[key] = {r["input"]: r for r in result["rows"]}
        validation.append(result)
    comparisons = []
    for role, baseline in protocol["direct_comparisons"].items():
        key = frozen["representatives"][role]
        result = validate_config(key, frozen["configs"][key], "direct-" + role, baseline)
        result["role"] = role
        comparisons.append(result)
    memory = measure_memory(binary, corpus, validation_cases, frozen, out / "memory",
                            protocol["memory_process_repetitions"], expected_rows)
    guard()
    if sha(binary) != binary_hash or sha(out / "finalists.json") != frozen_hash:
        raise ValueError("binary or finalists changed during memory measurements")
    write_json(out / "memory.json", memory)
    result = {"schema_version": 1, "source_sha256": sources, "protocol": protocol,
              "protocol_sha256": protocol_hash, "manifest_sha256": manifest_hash, "binary_sha256": binary_hash,
              "studies": studies, "finalists": frozen, "finalists_sha256": frozen_hash,
              "validation": validation, "direct_comparisons": comparisons, "memory": memory,
              "total_seconds": time.perf_counter() - started, "test_partition_measured": False, "promotion": "none"}
    write_json(out / "result.json", result)
    print("completed", out / "result.json", flush=True)


if __name__ == "__main__":
    main()
