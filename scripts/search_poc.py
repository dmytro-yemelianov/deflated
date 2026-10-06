#!/usr/bin/env python3
"""Measure existing encoder methods on a manifest-checked synthetic split.

This is an exhaustive finite pilot, not Bayesian optimization. The test split
is deliberately unavailable here. Streams, timings and provenance go to target/.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import pathlib
import platform
import statistics
import subprocess
import uuid
import zlib

from search_corpus import ROOT, validate

CANDIDATES = ("stored", "fast", "balanced", "best", "split256", "split1024",
              "split4096", "split16384", "miniz1", "miniz6", "miniz9")
SOURCES = ["Cargo.toml", "Cargo.lock", "crates/deflate-core/examples/search.rs",
           "scripts/search_corpus.py", "scripts/search_poc.py"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_exact(packed, raw):
    decoder = zlib.decompressobj(-15)
    decoded = decoder.decompress(packed, len(raw) + 1)
    if (decoded != raw or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
        raise ValueError("zlib round trip, EOF or exact byte consumption failed")


def pareto(points):
    """Minimize bytes and measured ns; tied points both remain on the frontier."""
    axes = ("packed_bytes", "encode_ns")
    return [p["candidate"] for p in points if not any(
        all(q[a] <= p[a] for a in axes) and any(q[a] < p[a] for a in axes)
        for q in points)]


def check_rows(rows, cases, streams, rounds):
    expected = {pathlib.PurePosixPath(c["path"]).name: c for c in cases}
    found = set()
    for row in rows:
        key = row["input"], row["candidate"]
        if row["input"] not in expected or row["candidate"] not in CANDIDATES or key in found:
            raise ValueError("unknown or duplicate measurement")
        found.add(key)
        case = expected[row["input"]]
        if row["raw_bytes"] != case["bytes"]:
            raise ValueError("raw size mismatch")
        samples = row["samples_ns"]
        if len(samples) != rounds or any(not math.isfinite(v) or v <= 0 for v in samples):
            raise ValueError("invalid timing samples")
        packed = streams / row["candidate"] / (row["input"] + ".deflate")
        if packed.stat().st_size != row["packed_bytes"]:
            raise ValueError("packed size mismatch")
    if found != {(name, candidate) for name in expected for candidate in CANDIDATES}:
        raise ValueError("incomplete measurement matrix")


def summarize(rows):
    points = []
    for candidate in CANDIDATES:
        selected = [r for r in rows if r["candidate"] == candidate]
        raw = sum(r["raw_bytes"] for r in selected)
        ns = sum(statistics.median(r["samples_ns"]) for r in selected)
        size = sum(r["packed_bytes"] for r in selected)
        points.append({"candidate": candidate, "raw_bytes": raw,
                       "packed_bytes": size, "encode_ns": ns,
                       "mb_s": raw / ns * 1e3,
                       "size_fraction": size / max(1, raw)})
    eligible = [p for p in points if p["candidate"] != "split16384"]
    ours = [p for p in eligible if not p["candidate"].startswith("miniz")]
    return {"aggregate": points, "provisional_frontier": pareto(ours),
            "frontier_with_references": pareto(eligible)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=pathlib.Path, default=ROOT / "target/search/corpus-smoke")
    parser.add_argument("--partition", choices=["train", "validation", "stress"], default="train")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--min-ms", type=int, default=10)
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    if args.rounds < 3 or args.min_ms < 1:
        parser.error("use at least three rounds and a positive batch duration")
    corpus = args.corpus.resolve()
    manifest_path = corpus / "manifest.json"
    meta = json.loads(manifest_path.read_text())
    validate(corpus, meta)
    cases = [c for c in meta["cases"] if c["partition"] == args.partition]
    if not cases:
        parser.error("empty partition")
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = (args.out or ROOT / "target/search/runs" / run_id).resolve()
    if out.exists():
        parser.error("--out already exists; keep runs separate")
    out.mkdir(parents=True)
    sources = SOURCES + [str(p.relative_to(ROOT)) for p in sorted((ROOT / "crates/deflate-core/src").rglob("*.rs"))]
    cpu = platform.processor()
    if platform.system() == "Darwin":
        cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    provenance = {"schema_version": 1, "run_id": run_id, "partition": args.partition,
                  "manifest_sha256": sha(manifest_path), "corpus": meta,
                  "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "git_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
                  "source_sha256": {p: sha(ROOT / p) for p in sources},
                  "platform": platform.platform(), "cpu": cpu, "python": platform.python_version(),
                  "zlib": zlib.ZLIB_RUNTIME_VERSION,
                  "rustc": subprocess.check_output(["rustc", "--version"], cwd=ROOT, text=True).strip(),
                  "rounds": args.rounds, "minimum_batch_ms": args.min_ms,
                  "build_overrides": {k: v for k, v in os.environ.items() if k.startswith("CARGO_PROFILE_RELEASE_") or k == "RUSTFLAGS"},
                  "measurement": "serial CPU runs; order rotates by file and round; timing includes allocation and encoding, excludes input I/O and decoding",
                  "memory": "not measured; frontier has only time and size axes",
                  "candidate_space": {"presets": ["fast", "balanced", "best"],
                                      "method": ["stored", "matched"],
                                      "custom_splits": {"level": "balanced", "block_tokens": [256, 1024, 4096, 16384]},
                                      "reference": "miniz_oxide 0.8.9 levels 1, 6, 9"},
                  "purpose": "tooling pilot; no encoder promotion or universal performance claim"}
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    # A dedicated Cargo target prevents ordinary dev builds replacing the
    # measured binary. GPU scoring is a separate command, outside CPU timings.
    target = ROOT / "target/search/build"
    subprocess.run(["cargo", "build", "--locked", "--release", "-p", "deflate-core", "--example", "search"],
                   cwd=ROOT, env={**os.environ, "CARGO_TARGET_DIR": str(target)}, check=True)
    binary = target / "release/examples/search"
    provenance["binary_sha256"] = sha(binary)
    streams = out / "streams"
    with (out / "measurements.jsonl").open("w") as output:
        subprocess.run([str(binary), str(corpus / args.partition), str(streams),
                        str(args.rounds), str(args.min_ms)], stdout=output, check=True)
    rows = [json.loads(line) for line in (out / "measurements.jsonl").read_text().splitlines()]
    check_rows(rows, cases, streams, args.rounds)
    for row in rows:
        raw = (corpus / args.partition / row["input"]).read_bytes()
        packed_path = streams / row["candidate"] / (row["input"] + ".deflate")
        packed = packed_path.read_bytes()
        decode_exact(packed, raw)
        row["packed_sha256"] = hashlib.sha256(packed).hexdigest()
    hashes = {(r["input"], r["candidate"]): r["packed_sha256"] for r in rows}
    for case in cases:
        name = pathlib.PurePosixPath(case["path"]).name
        if hashes[name, "balanced"] != hashes[name, "split16384"]:
            raise SystemExit("default-equivalent split changed output")
    # Fail if a source or corpus changed while the process was running.
    if provenance["source_sha256"] != {p: sha(ROOT / p) for p in sources} or sha(manifest_path) != provenance["manifest_sha256"]:
        raise SystemExit("sources/manifest changed during measurement")
    validate(corpus, meta)
    result = {**provenance, "verification": {"streams": len(rows), "decoders": ["deflate-core", "miniz_oxide", "zlib"],
                                            "zlib_exact_consumption": True,
                                            "balanced_split16384_byte_equality": True},
              "control": "split16384 is byte-equivalent to balanced and excluded from selection; timing differences may reflect API/compiler overhead or noise, not different policy settings",
              "rows": rows, **summarize(rows), "families": {}}
    family_for = {pathlib.PurePosixPath(c["path"]).name: c["family"] for c in cases}
    for family in sorted(set(family_for.values())):
        result["families"][family] = summarize([r for r in rows if family_for[r["input"]] == family])
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": str(out / "result.json"), "verified_streams": len(rows),
                      "provisional_frontier": result["provisional_frontier"]}))


if __name__ == "__main__":
    main()
