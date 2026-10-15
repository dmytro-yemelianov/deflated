#!/usr/bin/env python3
"""Acquire the v16 library holdout corpus from the pinned VALIDATION partition.

Bodies come from scripts/new_methods_sources.json, partition "validation",
identity extraction, each pinned by its Git blob SHA-1. None of these sources
was used by library work v1-v15 (which drew only on six TRAINING sources and
synthetic/witness cases). The TEST partition is deliberately not touched; it
stays reserved for a final release evaluation. Bodies stay under target/ and
are not redistributed; only the manifest (names, sizes, hashes) is reported.

Derived cases are fixed here, before any timing: a 600-byte prefix of every
body (tiny band) and the concatenation of all bodies in inventory order
(large band).
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts/new_methods_sources.json"
MAX_DOWNLOAD = 8 << 20
TINY_PREFIX = 600


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def download(url, blob_sha1):
    with urlopen(url, timeout=120) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if len(data) > MAX_DOWNLOAD or digest != blob_sha1:
        raise ValueError(f"pinned Git blob mismatch for {url}")
    return data


def band(size):
    if size < 1024:
        return "tiny"
    if size < 64 << 10:
        return "small"
    if size < 1 << 20:
        return "medium"
    return "large"


def holdout_sources():
    sources = json.loads(INVENTORY.read_text())["sources"]
    # Sources without a Git blob pin (repository archives) are excluded: they
    # cannot be verified byte-exactly and are already compressed.
    return [s for s in sources if s["partition"] == "validation"
            and s.get("extraction", "identity") == "identity" and s.get("download_git_blob_sha1")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    cases, bodies = [], []

    def add(name, data, origin):
        path = args.out / f"{name}.raw"
        path.write_bytes(data)
        cases.append({"name": name, "path": path.name, "scope": band(len(data)), "bytes": len(data),
                      "sha256": sha256(data), "origin": origin})

    for source in holdout_sources():
        data = download(source["url"], source["download_git_blob_sha1"])
        if len(data) != source["declared_download_bytes"]:
            raise ValueError("declared source size differs")
        download(source["license_url"], source["license_git_blob_sha1"])
        bodies.append(data)
        add(source["id"], data, {"source_id": source["id"], "url": source["url"],
                                 "git_blob_sha1": source["download_git_blob_sha1"],
                                 "license": source["license"], "class": source.get("class")})
    for source, data in zip(holdout_sources(), bodies):
        add(f"{source['id']}-prefix{TINY_PREFIX}", data[:TINY_PREFIX],
            {"derived": f"first {TINY_PREFIX} bytes of {source['id']}"})
    add("concat-all", b"".join(bodies), {"derived": "all validation bodies concatenated in inventory order"})
    manifest = {"schema_version": 1,
                "scope": "v16 holdout: pinned validation partition, never used by library tuning",
                "inventory_sha256": sha256(INVENTORY.read_bytes()), "cases": cases}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for case in cases:
        print(case["scope"], case["bytes"], case["name"])


if __name__ == "__main__":
    main()
