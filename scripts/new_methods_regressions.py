#!/usr/bin/env python3
"""Index prior input scopes and audit fresh data against historical bytes."""
import argparse
import json
from pathlib import Path

from encoder_corpus import ROOT, digest, write_json
from new_methods_corpus import checked_member, chunks, copied

OLD_ROOTS = (
    "target/tuning-corpus", "target/encoder-performance/corpus-v1", "target/encoder-performance/synthetic-v1",
    "target/search/corpus-mixed-s2", "target/search/corpus-policy-s5", "target/search/corpus-smoke",
    "target/search/corpus-extended-s7-checked", "target/search/cost-s7-safety-v2/corpus",
    "target/search/corpus-policy-s5-final", "target/search/corpus-full", "target/search/final-s9-full/corpus",
    "target/search/cost-s7-full/corpus", "target/search/corpus-extended-s7-final",
    "target/search/corpus-policy-s5-safety", "target/search/corpus-extended-s7",
    "target/search/corpus-smoke-initial", "target/search/final-s9-rotated/corpus",
    "target/search/campaign-smoke-corpus",
)


def run(out):
    if out.exists():
        raise ValueError("regression audit requires a fresh directory")
    out.mkdir(parents=True)
    manifests, records, real = [], [], {}
    for relative in OLD_ROOTS:
        root = ROOT / relative
        manifest = root / "manifest.json"
        meta = json.loads(manifest.read_text())
        cases = meta if isinstance(meta, list) else meta["cases"]
        manifests.append({"path": relative + "/manifest.json", "sha256": digest(manifest.read_bytes()), "cases": len(cases)})
        for case in cases:
            path = case.get("path") or case["partition"] + "/" + case["input"]
            raw = checked_member(root, path, case["sha256"])
            if len(raw) != case["bytes"]:
                raise ValueError("historical size changed")
            records.append({"path": relative + "/" + path, "bytes": len(raw), "sha256": case["sha256"],
                            "scope": "regression-only", "source_group": case.get("source_group", case.get("input", case["family"] if "family" in case else "unknown"))})
            is_real = relative.endswith("corpus-v1") or (relative == "target/tuning-corpus" and case["partition"] != "stress")
            if is_real and case["sha256"] not in real:
                real[case["sha256"]] = (records[-1]["path"], raw)
        print("indexed", relative, len(cases), flush=True)
    index = {"schema_version": 1, "scope": "all prior study inputs are regression only", "tool_sha256": digest(Path(__file__).read_bytes()),
             "manifests": manifests, "cases": records, "unique_byte_hashes": len({c["sha256"] for c in records})}
    write_json(out / "index.json", index)
    fresh_root = ROOT / "target/new-methods/corpus-v1"
    synth_root = ROOT / "target/new-methods/synthetic-v1"
    fresh_manifest = fresh_root / "manifest.json"
    synth_manifest = synth_root / "manifest.json"
    fresh = json.loads(fresh_manifest.read_text())["cases"]
    synth = json.loads(synth_manifest.read_text())["cases"]
    hashes = {c["sha256"] for c in records}
    for case in fresh + [c for c in synth if c["partition"] != "stress"]:
        if case["sha256"] in hashes:
            raise ValueError("fresh input duplicates old bytes: " + case["path"])
    fresh_bodies = [(c["source_group"], checked_member(fresh_root, c["path"], c["sha256"])) for c in fresh]
    fresh_chunks = {name: chunks(raw) for name, raw in fresh_bodies}
    comparisons = 0
    for name, old in real.values():
        old_chunks = chunks(old)
        for source, raw in fresh_bodies:
            comparisons += 1
            if copied(raw, old, fresh_chunks[source], old_chunks):
                raise ValueError("fresh/old real copy: " + source + "/" + name)
        print("dedup audited", name, flush=True)
    receipt = {"schema_version": 1, "status": "passed", "tool_sha256": index["tool_sha256"],
               "index_sha256": digest((out / "index.json").read_bytes()), "old_manifests": len(manifests),
               "old_case_records": len(records), "old_unique_hashes": index["unique_byte_hashes"],
               "old_real_unique_inputs": len(real), "real_pair_comparisons": comparisons,
               "fresh_real_manifest_sha256": digest(fresh_manifest.read_bytes()),
               "fresh_synthetic_manifest_sha256": digest(synth_manifest.read_bytes()),
               "fresh_nonshared_cases_checked_for_old_hashes": len(fresh) + sum(c["partition"] != "stress" for c in synth),
               "scope_limit": "Exact historical bytes plus real-data content-defined/contained copies; not a semantic/schema independence proof. Synthetic families intentionally share recipes with disjoint regimes."}
    write_json(out / "audit.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/regression-audit-v1")
    args = parser.parse_args()
    run(args.out)
