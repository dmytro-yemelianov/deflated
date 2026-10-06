#!/usr/bin/env python3
"""Bounded CPU search over validated research-only encoder parameters.

Random search is the baseline; pareto-mutation is a simple exploration
heuristic, not NSGA-II or Bayesian optimization. No third-party Python deps.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import pathlib
import platform
import random
import statistics
import subprocess
import time
import uuid

from search_corpus import ROOT, validate
from search_poc import decode_exact, sha

AXES = {"probes": [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024],
        "lazy": [False, True], "insert_tail": [0, 4, 8, 16, 32],
        "index": ["dual", "trigram"], "block_tokens": [256, 1024, 4096, 16384]}
CONTROLS = [{"preset": name} for name in ("balanced", "fast", "best", "stored")]


def canonical(config):
    if set(config) == {"preset"}:
        if config["preset"] not in ("balanced", "fast", "best", "stored"):
            raise ValueError("unknown preset")
    elif set(config) == set(AXES):
        if (type(config["probes"]) is not int or not 1 <= config["probes"] <= 1024
                or type(config["insert_tail"]) is not int or not 0 <= config["insert_tail"] <= 32
                or type(config["block_tokens"]) is not int or config["block_tokens"] not in AXES["block_tokens"]
                or type(config["lazy"]) is not bool or config["index"] not in AXES["index"]):
            raise ValueError("invalid bounded configuration")
    else:
        raise ValueError("unknown, missing or inactive fields")
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def identity(config):
    return hashlib.sha256(canonical(config).encode()).hexdigest()


def worker_method(config):
    canonical(config)
    if "preset" in config:
        return config["preset"]
    return f"config:{config['probes']}:{int(config['lazy'])}:{config['insert_tail']}:{config['index']}:{config['block_tokens']}"


def frontier(trials):
    axes = ("packed_bytes", "time_vs_paired_balanced")
    return [trial for trial in trials if not any(
        all(other["aggregate"][a] <= trial["aggregate"][a] for a in axes)
        and any(other["aggregate"][a] < trial["aggregate"][a] for a in axes)
        for other in trials)]


def propose(rng, strategy, trials, seen):
    parents = [t for t in frontier(trials) if "preset" not in t["config"]]
    for _ in range(10000):
        if strategy == "pareto-mutation" and parents and rng.random() < 0.7:
            config = dict(rng.choice(parents)["config"])
            axis = rng.choice(list(AXES))
            config[axis] = rng.choice([v for v in AXES[axis] if v != config[axis]])
        else:
            config = {axis: rng.choice(values) for axis, values in AXES.items()}
        if identity(config) not in seen:
            return config
    raise ValueError("proposal space exhausted or duplicate proposal limit reached")


def aggregate(rows):
    raw = sum(r["raw_bytes"] for r in rows)
    ns = sum(statistics.median(r["samples_ns"]) for r in rows)
    base_ns = sum(statistics.median(r["baseline_samples_ns"]) for r in rows)
    size = sum(r["packed_bytes"] for r in rows)
    base_size = sum(r["baseline_bytes"] for r in rows)
    return {"raw_bytes": raw, "packed_bytes": size, "encode_ns": ns,
            "baseline_encode_ns": base_ns, "baseline_bytes": base_size,
            "mb_s": raw / ns * 1e3, "speed_vs_paired_balanced": base_ns / ns,
            "time_vs_paired_balanced": ns / base_ns,
            "size_vs_balanced": size / base_size}


def validate_measurements(rows, cases, streams, rounds, corpus):
    expected = {pathlib.PurePosixPath(c["path"]).name: c for c in cases}
    seen = set()
    for row in rows:
        name = row["input"]
        if name not in expected or name in seen or row["raw_bytes"] != expected[name]["bytes"]:
            raise ValueError("unknown, duplicate or wrong-size measurement")
        seen.add(name)
        for key in ("samples_ns", "baseline_samples_ns"):
            samples = row[key]
            if len(samples) != rounds or any(not math.isfinite(v) or v <= 0 for v in samples):
                raise ValueError("invalid paired timing samples")
        packed = (streams / (name + ".deflate")).read_bytes()
        if len(packed) != row["packed_bytes"] or row["baseline_bytes"] <= 0:
            raise ValueError("invalid encoded size")
        raw = (corpus / expected[name]["path"]).read_bytes()
        decode_exact(packed, raw)
        row["packed_sha256"] = hashlib.sha256(packed).hexdigest()
    if seen != set(expected):
        raise ValueError("incomplete measurement matrix")


def select_finalists(trials, size_tolerance):
    useful = [t for t in trials if t["config"].get("preset") != "stored"]
    feasible = [t for t in useful if t["aggregate"]["size_vs_balanced"] <= 1 + size_tolerance]
    if not useful or not feasible:
        raise ValueError("no valid finalist under the declared size constraint")
    return {"speed": min(useful, key=lambda t: t["aggregate"]["time_vs_paired_balanced"])["id"],
            "size": min(useful, key=lambda t: (t["aggregate"]["packed_bytes"], t["aggregate"]["time_vs_paired_balanced"]))["id"],
            "balanced": min(feasible, key=lambda t: t["aggregate"]["time_vs_paired_balanced"])["id"]}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def source_files():
    fixed = ["Cargo.toml", "Cargo.lock", "crates/deflate-core/Cargo.toml",
             "crates/deflate-core/examples/tune_config.rs", "scripts/search_cpu.py",
             "scripts/search_corpus.py", "scripts/search_poc.py"]
    return fixed + [str(p.relative_to(ROOT)) for p in sorted((ROOT / "crates/deflate-core/src").rglob("*.rs"))]


def run_study(args):
    corpus = args.corpus.resolve()
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    validate(corpus, manifest)
    training = [c for c in manifest["cases"] if c["partition"] == "train"]
    validation = [c for c in manifest["cases"] if c["partition"] == "validation"]
    if not training or not validation:
        raise ValueError("training and validation partitions required")
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = (args.out or ROOT / "target/search/cpu-studies" / run_id).resolve()
    if out.exists():
        raise ValueError("output exists; use a new directory (resume is not implemented)")
    out.mkdir(parents=True)
    sources = source_files()
    hashes = {p: sha(ROOT / p) for p in sources}
    rustc = subprocess.check_output(["rustc", "--version"], cwd=ROOT, text=True).strip()
    cpu = platform.processor()
    if platform.system() == "Darwin":
        cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    provenance = {"schema_version": 1, "run_id": run_id, "strategy": args.strategy,
                  "seed": args.seed, "configured_trial_budget": args.trials, "controls": CONTROLS,
                  "axes": AXES, "rounds": args.rounds, "minimum_batch_ms": args.min_ms,
                  "trial_timeout_seconds": args.trial_timeout, "balanced_size_tolerance": args.size_tolerance,
                  "source_sha256": hashes, "manifest_sha256": sha(manifest_path),
                  "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "rustc": rustc, "cpu": cpu, "platform": platform.platform(),
                  "python": platform.python_version(), "features": ["research-tuning"],
                  "build_overrides": {k: v for k, v in os.environ.items() if k.startswith("CARGO_PROFILE_RELEASE_") or k == "RUSTFLAGS"},
                  "objectives": ["time_vs_paired_balanced", "packed_bytes"],
                  "memory": "configured table capacities reported; peak memory unmeasured and not optimized",
                  "test_partition_measured": False, "promotion": "none"}
    write_json(out / "provenance.json", provenance)
    started = time.perf_counter()
    build_key = hashlib.sha256(json.dumps([hashes, rustc, provenance["build_overrides"]], sort_keys=True).encode()).hexdigest()[:16]
    target = ROOT / "target/search/config-builds" / build_key
    subprocess.run(["cargo", "build", "--locked", "--release", "-p", "deflate-core", "--features", "research-tuning", "--example", "tune_config"],
                   cwd=ROOT, env={**os.environ, "CARGO_TARGET_DIR": str(target)}, check=True)
    binary = target / "release/examples/tune_config"
    provenance["binary_sha256"] = sha(binary)
    provenance["build_seconds"] = time.perf_counter() - started
    write_json(out / "provenance.json", provenance)
    ledger_path = out / "trials.jsonl"

    def measure(config, partition, cases):
        trial_id = identity(config)
        trial = out / partition / trial_id
        trial.mkdir(parents=True)
        write_json(trial / "config.json", config)
        begun = time.perf_counter()
        event = {"id": trial_id, "partition": partition, "config": config, "status": "scheduled"}
        with ledger_path.open("a") as ledger:
            ledger.write(json.dumps(event) + "\n")
        try:
            streams = trial / "streams"
            with (trial / "measurements.jsonl").open("w") as output, (trial / "stderr.log").open("w") as errors:
                subprocess.run([str(binary), str(corpus / partition), str(streams), str(args.rounds),
                                str(args.min_ms), worker_method(config)], stdout=output,
                               stderr=errors, timeout=args.trial_timeout, check=True)
            rows = [json.loads(line) for line in (trial / "measurements.jsonl").read_text().splitlines()]
            validate_measurements(rows, cases, streams, args.rounds, corpus)
            if hashes != {p: sha(ROOT / p) for p in sources} or provenance["manifest_sha256"] != sha(manifest_path) or provenance["binary_sha256"] != sha(binary):
                raise ValueError("sources, binary or corpus manifest changed during study")
            validate(corpus, manifest)
            result = {"id": trial_id, "config": config, "partition": partition,
                      "status": "complete", "aggregate": aggregate(rows), "rows": rows,
                      "elapsed_seconds": time.perf_counter() - begun,
                      "verified_streams": len(rows), "decoders": ["deflate-core", "miniz_oxide", "zlib"],
                      "matcher_table_bytes": None if "preset" in config else (192 << 10) * (2 if config["index"] == "dual" else 1)}
            write_json(trial / "result.json", result)
            with ledger_path.open("a") as ledger:
                ledger.write(json.dumps({k: v for k, v in result.items() if k != "rows"}, allow_nan=False) + "\n")
            print(f"{partition} {trial_id[:8]} {config} {result['aggregate']['mb_s']:.1f} MB/s", flush=True)
            return result
        except BaseException as error:
            failure = {**event, "status": "failed", "error": str(error), "elapsed_seconds": time.perf_counter() - begun}
            write_json(trial / "failure.json", failure)
            with ledger_path.open("a") as ledger:
                ledger.write(json.dumps(failure) + "\n")
            raise

    trials = [measure(config, "train", training) for config in CONTROLS]
    rng = random.Random(args.seed)
    seen = {t["id"] for t in trials}
    for _ in range(args.trials):
        config = propose(rng, args.strategy, trials, seen)
        result = measure(config, "train", training)
        seen.add(result["id"])
        trials.append(result)
    roles = select_finalists(trials, args.size_tolerance)
    frozen = {"criteria": {"speed": "minimum ratio of summed median ns to paired Balanced, excluding stored",
                           "size": "minimum summed compressed bytes, excluding stored; paired time breaks ties",
                           "balanced": f"minimum paired time ratio with training size <= balanced * {1 + args.size_tolerance}"},
              "roles": roles, "configs": {t["id"]: t["config"] for t in trials if t["id"] in roles.values()}}
    write_json(out / "finalists.json", frozen)
    frozen_hash = sha(out / "finalists.json")
    by_id = {t["id"]: t for t in trials}
    checked = [measure(by_id[trial_id]["config"], "validation", validation) for trial_id in sorted(set(roles.values()))]
    if sha(out / "finalists.json") != frozen_hash:
        raise ValueError("finalists changed during validation")
    result = {**provenance, "training": [{k: v for k, v in t.items() if k != "rows"} for t in trials],
              "provisional_frontier": [t["id"] for t in frontier(trials)],
              "finalists": frozen, "finalists_sha256": frozen_hash,
              "validation": [{k: v for k, v in t.items() if k != "rows"} for t in checked],
              "total_verified_streams": sum(t["verified_streams"] for t in trials + checked),
              "total_seconds": time.perf_counter() - started}
    write_json(out / "result.json", result)
    print(json.dumps({"result": str(out / "result.json"), "verified_streams": result["total_verified_streams"], "finalists": roles}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=pathlib.Path, default=ROOT / "target/search/corpus-smoke")
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--strategy", choices=["random", "pareto-mutation"], default="random")
    parser.add_argument("--seed", type=int, default=195108)
    parser.add_argument("--trials", type=int, default=32)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--min-ms", type=int, default=2)
    parser.add_argument("--trial-timeout", type=int, default=60)
    parser.add_argument("--size-tolerance", type=float, default=0.01)
    args = parser.parse_args()
    if not 1 <= args.trials <= 384 or args.rounds < 3 or args.min_ms < 1 or args.trial_timeout < 1 or not math.isfinite(args.size_tolerance) or not 0 <= args.size_tolerance <= 1:
        parser.error("invalid trial/timing budget or size tolerance")
    run_study(args)


if __name__ == "__main__":
    main()
