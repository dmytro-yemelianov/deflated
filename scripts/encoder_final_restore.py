#!/usr/bin/env python3
"""Restore pinned P5 inputs and portable CLI artifacts without encoding data."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile

from encoder_baseline import DEFAULT_OUT as BASELINE, check, freeze
from encoder_corpus import DEFAULT_OUT as REAL, INVENTORY, ROOT, run as acquire, validate
from encoder_measure import OUTLIERS, sha
from encoder_synthetic import build as synthetic_build
from search_extended_corpus import payload as extended_payload
from search_policy_corpus import generated


def restore_inputs():
    published = ROOT / "scripts/reports/encoder-corpus.json"
    original = json.loads(published.read_text())
    if not (REAL / "manifest.json").exists():
        acquire(REAL, INVENTORY, ROOT / "target/encoder-performance/download-cache")
    # Reacquisition timestamps/headers are new receipts. Validate all original
    # raw/license hashes before restoring the historical measurement manifest.
    validate(REAL, original)
    manifest = REAL / "manifest.json"
    if manifest.read_bytes() != published.read_bytes():
        shutil.copy2(manifest, REAL / "reacquisition.json")
        shutil.copy2(published, manifest)
    synthetic = ROOT / "target/encoder-performance/synthetic-v1"
    synthetic_build(synthetic, check=(synthetic / "manifest.json").exists())
    if sha(synthetic / "manifest.json") != sha(ROOT / "scripts/reports/encoder-synthetic.json"):
        raise ValueError("synthetic manifest differs from frozen original")
    previous = json.loads((ROOT / "scripts/reports/search-final.json").read_text())
    for name in OUTLIERS:
        case = next(c for c in previous["corpus"]["cases"] if c["path"] == name)
        if case["family"] == "template_edits":
            raw = generated(case["family"], case["params"]["parameter"], case["seed"], case["bytes"])
        else:
            variants, _ = extended_payload(case["family"], case["params"]["regime"], case["seed"], case["bytes"])
            raw = variants[case["params"]["variant"]]
        if hashlib.sha256(raw).hexdigest() != case["sha256"]:
            raise ValueError("old regression regeneration differs: " + name)
        path = ROOT / "target/search/final-s9-rotated/corpus" / name
        if path.exists() and sha(path) != case["sha256"]:
            raise ValueError("preserve changed existing regression: " + name)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)


def run(inputs_only):
    from encoder_final_campaign import source_hashes
    frozen = json.loads((ROOT / "scripts/reports/encoder-p5-freeze.json").read_text())
    if source_hashes() != frozen["source_sha256"]:
        raise ValueError("use a revision with the exact frozen measured sources")
    restore_inputs()
    if inputs_only:
        return
    if BASELINE.exists():
        check(BASELINE)
    else:
        freeze(BASELINE, rebuild=True)
    size = json.loads((ROOT / "scripts/reports/encoder-p5-portable-size.json").read_text())
    old = ROOT / "target/encoder-performance/p5-original-cli"
    for original in (True, False):
        target = old / "build" if original else ROOT / "target/encoder-performance/p5-portable-cli"
        binary = target / "release/vdeflate"
        expected = size["original" if original else "candidate"]["binary_sha256"]
        if not binary.exists():
            source = ROOT
            if original:
                source = old / "source"
                source.mkdir(parents=True, exist_ok=False)
                with tarfile.open(BASELINE / "source.tar.gz") as archive:
                    archive.extractall(source, filter="data")
            subprocess.run(["cargo", "build", "--locked", "--release", "-p", "vdeflate", "--target-dir", str(target)], cwd=source, check=True)
        if sha(binary) != expected:
            raise ValueError("portable CLI differs from original-platform frozen build")
    print("P5 inputs/baseline/portable CLIs restored; no input encoded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-only", action="store_true")
    run(parser.parse_args().inputs_only)
