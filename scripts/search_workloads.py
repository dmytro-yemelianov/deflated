#!/usr/bin/env python3
"""Frozen mixed training and full-file regression validation for S2/S3.

Real data remains under target/. Original train/holdout assignments are
preserved by source file; the old holdout is regression evidence, not a fresh
final test. The 14 reserved synthetic test cases are retained and not encoded.
"""
import argparse
import copy
import hashlib
import json
import pathlib

from search_corpus import ROOT, features, manifest, payload, validate


def build(real_root, chunk_bytes):
    originals = json.loads((real_root / "manifest.json").read_text())
    synthetic, generated = manifest("full", 195107)
    records = []
    for case, full in generated:
        case = copy.deepcopy(case)
        data = (payload(case["family"], case["params"], case["seed"], chunk_bytes)
                if case["partition"] in ("train", "validation") else full)
        case["path"] = case["partition"] + "/syn-" + pathlib.PurePosixPath(case["path"]).name
        case.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), features=features(data))
        records.append((case, data))
    for original in originals:
        if original["partition"] == "stress":
            continue
        raw = (real_root / original["partition"] / original["input"]).read_bytes()
        if len(raw) != original["bytes"] or hashlib.sha256(raw).hexdigest() != original["sha256"]:
            raise ValueError("real source hash/size mismatch")
        partition = "train" if original["partition"] == "train" else "validation"
        width = min(len(raw), chunk_bytes) if partition == "train" else len(raw)
        offset = (len(raw) - width) // 2 if partition == "train" else 0
        data = raw[offset:offset + width]
        case = {"partition": partition, "path": partition + "/real-" + original["input"],
                "family": "real", "regime": "real-source:" + original["sha256"],
                "params": {"source_sha256": original["sha256"], "offset": offset, "length": width},
                "source": original["source"], "source_file": original["input"],
                "source_partition": original["partition"], "source_bytes": len(raw),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "features": features(data)}
        records.append((case, data))
    meta = {"schema_version": 1, "profile": "mixed-s2", "chunk_bytes": chunk_bytes,
            "generator_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
            "synthetic_generator_sha256": synthetic["generator_sha256"],
            "real_manifest_sha256": hashlib.sha256((real_root / "manifest.json").read_bytes()).hexdigest(),
            "test_policy": "14 original full synthetic cases reserved; no real final test in this study",
            "validation_policy": "previously visible full real holdout plus larger synthetic validation; regression only",
            "cases": [c for c, _ in records]}
    return meta, records


def validate_groups(root, meta):
    validate(root, meta)
    sources = {}
    for case in meta["cases"]:
        if case["family"] != "real":
            continue
        expected = "train" if case["source_partition"] == "train" else "validation"
        if case["partition"] != expected:
            raise ValueError("real source split changed")
        digest = case["params"]["source_sha256"]
        if sources.setdefault(digest, expected) != expected:
            raise ValueError("real source file crosses partitions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", type=pathlib.Path, default=ROOT / "target/tuning-corpus")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "target/search/corpus-mixed-s2")
    parser.add_argument("--chunk-bytes", type=int, default=262144)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.chunk_bytes < 32768:
        parser.error("chunks must span at least one DEFLATE window")
    meta, records = build(args.real, args.chunk_bytes)
    path = args.out / "manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != meta:
            raise ValueError("existing corpus differs; use a new directory")
    elif args.check:
        raise ValueError("generate the corpus before checking")
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        if any(args.out.iterdir()):
            raise ValueError("output must be empty")
        for case, data in records:
            file = args.out / case["path"]
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(data)
        path.write_text(json.dumps(meta, indent=2) + "\n")
    validate_groups(args.out, meta)
    for case, data in records:
        if (args.out / case["path"]).read_bytes() != data:
            raise ValueError("regeneration mismatch")
    print(json.dumps({"manifest": str(path), "partitions": {
        p: {"cases": sum(c["partition"] == p for c, _ in records),
            "bytes": sum(c["bytes"] for c, _ in records if c["partition"] == p)}
        for p in ("train", "validation", "test", "stress")}}))


if __name__ == "__main__":
    main()
