#!/usr/bin/env python3
"""Acquire and audit the new source-grouped corpus; never encode held bytes."""
import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import time

from encoder_corpus import ROOT, PARTITIONS, DOWNLOAD_LIMIT, acquire, digest, download, write_json

INVENTORY = ROOT / "scripts/new_methods_sources.json"
DEFAULT_OUT = ROOT / "target/new-methods/corpus-v1"
OLD_MANIFEST = ROOT / "scripts/reports/encoder-corpus.json"
OLD_ROOT = ROOT / "target/encoder-performance/corpus-v1"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def chunks(raw):
    """Content-defined integrity fingerprints, independent of slice alignment.

    Gear boundaries average 1 KiB, with 256/4096-byte bounds. These hashes are
    used only to reject reused data, never exported as optimizer features.
    """
    gear = [int.from_bytes(hashlib.sha256(bytes([b])).digest()[:8], "little") for b in range(256)]
    start, rolling, result = 0, 0, {}
    for end, byte in enumerate(raw, 1):
        rolling = ((rolling << 1) + gear[byte]) & ((1 << 64) - 1)
        width = end - start
        if width >= 256 and ((rolling & 1023) == 0 or width == 4096):
            result[digest(raw[start:end])] = width
            start, rolling = end, 0
    if start < len(raw):
        result[digest(raw[start:])] = len(raw) - start
    return result


def copied(left, right, left_chunks, right_chunks):
    if left == right or (min(len(left), len(right)) >= 4096 and
                         (left in right or right in left)):
        return True
    if min(len(left), len(right)) < 8192:
        return False
    shared = sum(min(left_chunks[k], right_chunks[k]) for k in left_chunks.keys() & right_chunks.keys())
    denominator = min(sum(left_chunks.values()), sum(right_chunks.values()))
    return denominator > 0 and shared / denominator >= .8


def inventory_check(inventory):
    sources = inventory["sources"]
    if len(sources) > 48 or len({s["id"] for s in sources}) != len(sources):
        raise ValueError("invalid source group count")
    old_cases = json.loads(OLD_MANIFEST.read_text())["cases"]
    old_ids = {case["source_group"] for case in old_cases}
    if set(inventory["excluded_old_lineages"]) != old_ids:
        raise ValueError("old lineage exclusions differ")
    old_repos = {case["provenance"]["source"]["repo"].lower() for case in old_cases
                 if "repo" in case["provenance"]["source"]}
    lineages = {}
    for source in sources:
        if not re.fullmatch(r"[a-z0-9-]+", source["id"]):
            raise ValueError("invalid source id")
        if source["partition"] not in PARTITIONS or not set(source["tracks"]) <= {"A", "B"}:
            raise ValueError("invalid split/track")
        if not re.fullmatch(r"[a-f0-9]{40}", source["pinned_commit"]):
            raise ValueError("unversioned source")
        if source["lineage"] in lineages:
            raise ValueError("repeated lineage; collapse related groups before acquisition")
        if source["lineage"] in old_repos or source["id"] in old_ids:
            raise ValueError("previously measured source lineage")
        lineages[source["lineage"]] = source["partition"]
    coverage = {}
    for partition in PARTITIONS:
        coverage[partition] = {}
        for track in ("A", "B"):
            selected = [s for s in sources if s["partition"] == partition and track in s["tracks"]]
            classes = sorted({s["class"] for s in selected})
            if len(selected) != 8 or len(classes) < (6 if track == "A" else 2):
                raise ValueError("source/class coverage: " + partition + "/" + track)
            coverage[partition][track] = {"source_groups": len(selected), "classes": classes}
    return coverage


def extract(source, blob):
    if source.get("extraction", "identity") == "identity":
        return blob
    if source["extraction"] != "gzip":
        raise ValueError("unsupported extraction recipe")
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
        raw = stream.read(DOWNLOAD_LIMIT + 1)
        if len(raw) > DOWNLOAD_LIMIT:
            raise ValueError("decompressed source exceeds 64 MiB")
        return raw


def checked_member(root, path, expected):
    parts = PurePosixPath(path).parts
    if not parts or any(p in ("..", ".") for p in parts) or PurePosixPath(path).is_absolute():
        raise ValueError("invalid corpus path")
    raw = (root / path).read_bytes()
    if digest(raw) != expected:
        raise ValueError("corpus member changed: " + path)
    return raw


def validate(root, meta, old_root=OLD_ROOT):
    inventory = json.loads(INVENTORY.read_text())
    if meta["inventory_sha256"] != digest(INVENTORY.read_bytes()):
        raise ValueError("inventory changed")
    coverage = inventory_check(inventory)
    if meta["tool_sha256"] != digest(Path(__file__).read_bytes()):
        raise ValueError("acquisition tool changed")
    if meta["helper_sha256"] != digest((ROOT / "scripts/encoder_corpus.py").read_bytes()):
        raise ValueError("acquisition helper changed")
    cases = meta["cases"]
    sources = inventory["sources"]
    if [c["source_group"] for c in cases] != [s["id"] for s in sources]:
        raise ValueError("source roster differs")
    peers, pair_checks = [], 0
    old_meta = json.loads(OLD_MANIFEST.read_text())
    if meta["old_manifest_sha256"] != digest(OLD_MANIFEST.read_bytes()):
        raise ValueError("old regression manifest changed")
    for case in old_meta["cases"]:
        raw = checked_member(old_root, case["path"], case["sha256"])
        peers.append(("regression:" + case["source_group"], raw, chunks(raw)))
    for source, case in zip(sources, cases):
        if "features" in case:
            raise ValueError("held features prohibited")
        expected_path = source["partition"] + "/" + source["id"] + ".raw"
        if case["path"] != expected_path or case["partition"] != source["partition"] or case["tracks"] != source["tracks"]:
            raise ValueError("source metadata differs")
        raw = checked_member(root, case["path"], case["sha256"])
        if len(raw) != case["bytes"] or not raw or len(raw) > inventory["cap_bytes"]:
            raise ValueError("invalid source size")
        if case["extraction_range"] != [0, len(raw)] or len(raw) > case["extracted_source_bytes"]:
            raise ValueError("invalid extraction range")
        license_raw = checked_member(root, case["license_path"], case["provenance"]["license_download"]["sha256"])
        if git_blob(license_raw) != source["license_git_blob_sha1"]:
            raise ValueError("license does not match pinned git tree")
        for extra in case["additional_provenance"]:
            checked_member(root, extra["path"], extra["download"]["sha256"])
        own_chunks = chunks(raw)
        for name, other, other_chunks in peers:
            pair_checks += 1
            if copied(raw, other, own_chunks, other_chunks):
                raise ValueError("copy/near-copy: " + source["id"] + "/" + name)
        peers.append((source["id"], raw, own_chunks))
    actual = {str(p.relative_to(root)) for partition in PARTITIONS for p in (root / partition).iterdir() if p.is_file()}
    if actual != {c["path"] for c in cases}:
        raise ValueError("unrecorded corpus members")
    return {"coverage": coverage, "fresh_source_groups": len(cases), "old_regression_groups": len(old_meta["cases"]),
            "dedup_pair_checks": pair_checks, "bytes": sum(c["bytes"] for c in cases)}


def acquire_case(source, out, cache, cap):
    _, location, provenance = acquire(source, cache)
    blob = (location / "download.bin").read_bytes()
    if "download_git_blob_sha1" in source and git_blob(blob) != source["download_git_blob_sha1"]:
        raise ValueError("source does not match pinned git tree")
    license_raw = (location / "license.txt").read_bytes()
    if git_blob(license_raw) != source["license_git_blob_sha1"]:
        raise ValueError("license does not match pinned git tree")
    extracted = extract(source, blob)
    raw = extracted[:cap]
    if source["class"] == "font" and raw[:4] not in (b"\0\1\0\0", b"OTTO"):
        raise ValueError("not a TrueType/OpenType font")
    path = source["partition"] + "/" + source["id"] + ".raw"
    license_path = "licenses/" + source["id"] + ".txt"
    (out / path).write_bytes(raw)
    (out / license_path).write_bytes(license_raw)
    extra = []
    for index, url in enumerate(source.get("additional_provenance_urls", [])):
        body, receipt = download(url)
        extra_path = "licenses/" + source["id"] + "-provenance-" + str(index) + ".txt"
        (out / extra_path).write_bytes(body)
        extra.append({"path": extra_path, "download": receipt})
    return {"path": path, "source_group": source["id"], "partition": source["partition"],
            "tracks": source["tracks"], "class": source["class"], "family": "real", "lineage": source["lineage"],
            "bytes": len(raw), "sha256": digest(raw), "license": source["license"], "license_path": license_path,
            "provenance": provenance, "additional_provenance": extra,
            "extracted_source_bytes": len(extracted), "extracted_source_sha256": digest(extracted),
            "extraction_range": [0, len(raw)]}


def run(out, cache):
    manifest = out / "manifest.json"
    if manifest.exists():
        raise ValueError("corpus frozen; use --check or a fresh directory")
    inventory = json.loads(INVENTORY.read_text())
    inventory_check(inventory)
    out.mkdir(parents=True, exist_ok=True)
    for directory in (*PARTITIONS, "licenses"):
        (out / directory).mkdir(exist_ok=True)
    intent = {"inventory_sha256": digest(INVENTORY.read_bytes()), "tool_sha256": digest(Path(__file__).read_bytes())}
    intent_path = out / "acquisition-intent.json"
    if intent_path.exists() and json.loads(intent_path.read_text()) != intent:
        raise ValueError("acquisition intent changed; preserve attempt and use fresh output")
    if not intent_path.exists():
        write_json(intent_path, intent)
    records, errors = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(acquire_case, s, out, cache, inventory["cap_bytes"]): s for s in inventory["sources"]}
        for job in concurrent.futures.as_completed(jobs):
            source = jobs[job]
            try:
                records[source["id"]] = job.result()
                print("acquired", source["id"], records[source["id"]]["bytes"], flush=True)
            except Exception as error:
                errors.append({"source": source["id"], "error": str(error)})
                print("failed", source["id"], str(error), flush=True)
    if errors:
        write_json(out / ("acquisition-failed-" + str(time.time_ns()) + ".json"), {**intent, "successful": sorted(records), "errors": errors})
        raise ValueError("acquisition incomplete; resume cached successes with the identical intent")
    meta = {"schema_version": 1, **intent, "helper_sha256": digest((ROOT / "scripts/encoder_corpus.py").read_bytes()),
            "old_manifest_sha256": digest(OLD_MANIFEST.read_bytes()), "cap_bytes": inventory["cap_bytes"],
            "cases": [records[s["id"]] for s in inventory["sources"]],
            "test_policy": "reserved: acquisition, signature/hash validation and deduplication only before G5 freeze",
            "dedup_policy": "declared lineage exclusions; exact/contained copies >=4KiB; >=80% shared content-defined chunk weight rejected; not a semantic independence proof",
            "sampling_policy": "complete source if <=1MiB; otherwise first 1MiB with complete extracted-source hash"}
    summary = validate(out, meta)
    write_json(manifest, meta)
    write_json(out / "audit.json", summary)
    print(json.dumps({"manifest_sha256": digest(manifest.read_bytes()), **summary}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache", type=Path, default=ROOT / "target/new-methods/download-cache-v1")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(validate(args.out, json.loads((args.out / "manifest.json").read_text()))))
    else:
        run(args.out, args.cache)
