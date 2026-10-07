#!/usr/bin/env python3
"""Audit the published G1 receipts and regenerate synthetic bytes in isolation."""
import gzip
import json
from pathlib import Path
import tempfile

from encoder_corpus import ROOT, digest
from new_methods_corpus import INVENTORY, inventory_check
from new_methods_synthetic import build

REPORTS = ROOT / "scripts/reports"


def read(name):
    path = REPORTS / name
    body = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(body), digest(body)


def main():
    real, real_sha = read("new-methods-corpus.json.gz")
    synth, synth_sha = read("new-methods-synthetic.json.gz")
    index, index_sha = read("new-methods-regression-index.json.gz")
    audit, _ = read("new-methods-data-audit.json")
    inventory = json.loads(INVENTORY.read_text())
    coverage = inventory_check(inventory)
    assert real["inventory_sha256"] == digest(INVENTORY.read_bytes())
    assert real["tool_sha256"] == digest((ROOT / "scripts/new_methods_corpus.py").read_bytes())
    assert real["helper_sha256"] == digest((ROOT / "scripts/encoder_corpus.py").read_bytes())
    assert real["old_manifest_sha256"] == digest((REPORTS / "encoder-corpus.json").read_bytes())
    assert audit["regression"]["status"] == "passed"
    assert audit["regression"]["index_sha256"] == index_sha
    assert audit["regression"]["fresh_real_manifest_sha256"] == real_sha
    assert audit["regression"]["fresh_synthetic_manifest_sha256"] == synth_sha
    assert index["tool_sha256"] == audit["regression"]["tool_sha256"] == digest((ROOT / "scripts/new_methods_regressions.py").read_bytes())
    assert audit["real"]["coverage"] == coverage
    assert audit["real"]["fresh_source_groups"] == len(real["cases"]) == 36
    assert len(index["manifests"]) == audit["regression"]["old_manifests"] == 18
    assert len(index["cases"]) == audit["regression"]["old_case_records"]
    old_hashes = {c["sha256"] for c in index["cases"]}
    assert len(old_hashes) == index["unique_byte_hashes"] == audit["regression"]["old_unique_hashes"]
    for source, case in zip(inventory["sources"], real["cases"]):
        assert source["id"] == case["source_group"]
        for key in ("partition", "tracks", "class", "lineage", "license"):
            assert source[key] == case[key]
        assert case["provenance"]["source"] == source
        assert case["provenance"]["download"]["requested_url"] == source["url"]
        assert case["provenance"]["license_download"]["requested_url"] == source["license_url"]
        assert case["bytes"] <= 1048576 and case["extraction_range"] == [0, case["bytes"]]
        assert case["sha256"] not in old_hashes and "features" not in case
    for case in synth["cases"]:
        assert "features" not in case
        if case["partition"] != "stress":
            assert case["sha256"] not in old_hashes
    assert sum(c["scope"] == "long-stress" for c in synth["cases"]) == 6
    assert all(c["bytes"] == 8388608 for c in synth["cases"] if c["scope"] == "long-stress")
    with tempfile.TemporaryDirectory() as temporary:
        out = Path(temporary) / "synthetic"
        build(out)
        assert digest((out / "manifest.json").read_bytes()) == synth_sha
        assert json.loads((out / "manifest.json").read_text()) == synth
    print("G1 pinned data/lineage/hash receipts and all synthetic regeneration passed; no codec measurements")


if __name__ == "__main__":
    main()
