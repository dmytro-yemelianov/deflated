#!/usr/bin/env python3
"""Compare feature-enabled preset bytes with the frozen pre-adapter pilot.

Expected hashes come from the 232678d phase-zero evidence; this is a finite
regression witness, not a format-level promise to freeze output forever.
"""
import argparse
import json
import pathlib
import subprocess
import tempfile

from search_corpus import ROOT, validate
from search_cpu import validate_measurements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=pathlib.Path, default=ROOT / "target/search/corpus-smoke")
    args = parser.parse_args()
    corpus = args.corpus.resolve()
    meta = json.loads((corpus / "manifest.json").read_text())
    validate(corpus, meta)
    expected = {(r["partition"], r["input"], r["candidate"]): r["packed_sha256"]
                for line in (ROOT / "scripts/reports/search-measurements.jsonl").read_text().splitlines()
                if (r := json.loads(line))["candidate"] in ("fast", "balanced", "best", "stored")}
    subprocess.run(["cargo", "build", "--locked", "--release", "-p", "deflate-core", "--features", "research-tuning", "--example", "tune_config"], cwd=ROOT, check=True)
    binary = ROOT / "target/release/examples/tune_config"
    checked = 0
    with tempfile.TemporaryDirectory(dir=ROOT / "target", prefix="defaults-check-") as temp:
        for partition in ("train", "validation", "stress"):
            cases = [c for c in meta["cases"] if c["partition"] == partition]
            for preset in ("fast", "balanced", "best", "stored"):
                streams = pathlib.Path(temp) / partition / preset
                output = subprocess.check_output([str(binary), str(corpus / partition), str(streams), "3", "1", preset], text=True)
                rows = [json.loads(line) for line in output.splitlines()]
                validate_measurements(rows, cases, streams, 3, corpus)
                for row in rows:
                    key = partition, row["input"], preset
                    if row["packed_sha256"] != expected[key]:
                        raise SystemExit(f"preset bytes changed: {key}")
                    checked += 1
    print(f"{checked} feature-enabled preset streams match the pre-adapter hashes; all three decoders passed")


if __name__ == "__main__":
    main()
