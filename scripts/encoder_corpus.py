#!/usr/bin/env python3
"""Acquire content-locked real inputs; never encode or compute selector features."""
import argparse
import concurrent.futures
import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "target/encoder-performance/corpus-v1"
INVENTORY = ROOT / "scripts/encoder_sources.json"
DOWNLOAD_LIMIT = 64 << 20
PARTITIONS = ("train", "validation", "test")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def download(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("HTTPS sources required")
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "deflated-encoder-corpus/1"})
            with urllib.request.urlopen(request, timeout=25) as response:
                chunks, size = [], 0
                while chunk := response.read(1 << 20):
                    size += len(chunk)
                    if size > DOWNLOAD_LIMIT:
                        raise ValueError("download exceeds 64 MiB bound")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                return raw, {"requested_url": url, "resolved_url": response.url,
                             "etag": response.headers.get("ETag"),
                             "last_modified": response.headers.get("Last-Modified"),
                             "content_type": response.headers.get("Content-Type"),
                             "bytes": len(raw), "sha256": digest(raw)}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code in (400, 401, 403, 404):
                raise
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))


def resolve(source):
    if "repo" not in source:
        return source["url"], source["license_url"], None
    repo, ref = source["repo"], source["ref"]
    patterns = ["HEAD"] if ref == "HEAD" else ["refs/tags/" + ref, "refs/tags/" + ref + "^{}"]
    result = subprocess.check_output(["git", "ls-remote", "https://github.com/" + repo + ".git", *patterns],
                                     text=True, timeout=45)
    refs = dict((name, commit) for commit, name in (line.split() for line in result.splitlines()))
    commit = refs.get(patterns[-1]) or refs.get(patterns[0])
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("cannot resolve source ref: " + repo + ":" + ref)
    prefix = "https://raw.githubusercontent.com/" + repo + "/" + commit + "/"
    url = prefix + urllib.parse.quote(source["file"], safe="/")
    license_url = prefix + source["license_file"] if "license_file" in source else source["license_url"]
    return url, license_url, commit


def acquire(source, cache):
    key = digest(json.dumps(source, sort_keys=True).encode())[:24]
    location = cache / key
    receipt = location / "receipt.json"
    if receipt.exists():
        meta = json.loads(receipt.read_text())
        for file, field in (("download.bin", "download"), ("license.txt", "license_download")):
            if digest((location / file).read_bytes()) != meta[field]["sha256"]:
                raise ValueError("cached source changed: " + source["id"])
        return source, location, meta
    location.mkdir(parents=True, exist_ok=True)
    url, license_url, commit = resolve(source)
    raw, provenance = download(url)
    license_raw, license_provenance = download(license_url)
    if not raw or not license_raw:
        raise ValueError("empty source or license")
    (location / "download.bin").write_bytes(raw)
    (location / "license.txt").write_bytes(license_raw)
    meta = {"source": source, "commit": commit, "download": provenance,
            "license_download": license_provenance,
            "acquired_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write_json(receipt, meta)
    return source, location, meta


def extract(source, blob):
    suffix = source.get("member_suffix")
    if not suffix:
        return blob, None
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as archive:
        members = [m for m in archive.getmembers() if m.isfile() and m.name.endswith(suffix)]
        if len(members) != 1:
            raise ValueError("expected one archive member: " + source["id"])
        member = members[0]
        if member.size > DOWNLOAD_LIMIT:
            raise ValueError("archive member exceeds bound")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("unreadable archive member")
        return stream.read(), member.name


def check_signature(source, raw):
    if source["class"] == "executable" and not raw.startswith(b"\x7fELF"):
        raise ValueError("expected ELF data: " + source["id"])
    if source["id"] == "chinook" and not raw.startswith(b"SQLite format 3\x00"):
        raise ValueError("expected SQLite database")
    if source["id"] in ("noto-sans", "dejavu", "liberation") and raw[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
        raise ValueError("expected TrueType/OpenType data")
    if source["id"] == "lshort" and not raw.startswith(b"%PDF-"):
        raise ValueError("expected PDF data")
    if source["id"] == "nyc-tlc" and not (raw.startswith(b"PAR1") and raw.endswith(b"PAR1")):
        raise ValueError("expected complete Parquet source")


def validate(root, meta):
    cases = meta["cases"]
    if len(cases) != 24:
        raise ValueError("expected 24 independent real cases")
    seen_ids, seen_hashes, by_partition = set(), set(), {p: [] for p in PARTITIONS}
    chunk_sets = []
    for case in cases:
        partition = case["partition"]
        if partition not in by_partition:
            raise ValueError("invalid partition")
        path = PurePosixPath(case["path"])
        if path.parts != (partition, case["source_group"] + ".raw"):
            raise ValueError("invalid raw path")
        if case["source_group"] in seen_ids or case["sha256"] in seen_hashes:
            raise ValueError("source-group or byte duplicate")
        if "features" in case:
            raise ValueError("selector features are not corpus-acquisition metadata")
        raw = (root / path).read_bytes()
        if len(raw) != case["bytes"] or digest(raw) != case["sha256"]:
            raise ValueError("raw input changed")
        license_path = PurePosixPath(case["license_path"])
        if license_path.parts != ("licenses", case["source_group"] + ".txt"):
            raise ValueError("invalid license path")
        if digest((root / license_path).read_bytes()) != case["provenance"]["license_download"]["sha256"]:
            raise ValueError("license snapshot changed")
        start, end = case["extraction_range"]
        if start != 0 or end != len(raw) or end > meta["cap_bytes"] or end > case["extracted_source_bytes"]:
            raise ValueError("invalid extraction range")
        chunks = {digest(raw[i:i + 4096]) for i in range(0, len(raw) - 4095, 4096)}
        # Integrity-only chunk hashes: never exposed to a selector or optimizer.
        for other_id, other_chunks in chunk_sets:
            if len(chunks) >= 8 and len(other_chunks) >= 8 and len(chunks & other_chunks) / min(len(chunks), len(other_chunks)) >= 0.8:
                raise ValueError("near-copy across source groups: " + case["source_group"] + "/" + other_id)
        chunk_sets.append((case["source_group"], chunks))
        seen_ids.add(case["source_group"])
        seen_hashes.add(case["sha256"])
        by_partition[partition].append(case)
    for partition, selected in by_partition.items():
        if len(selected) != 8 or len({c["class"] for c in selected}) < 4:
            raise ValueError("insufficient source/class coverage: " + partition)
        actual = {str(p.relative_to(root)) for p in (root / partition).iterdir() if p.is_file()}
        if actual != {c["path"] for c in selected}:
            raise ValueError("unrecorded/missing corpus member")
    return {p: {"sources": len(c), "classes": sorted({x["class"] for x in c}),
                "bytes": sum(x["bytes"] for x in c)} for p, c in by_partition.items()}


def run(out, inventory_path, cache):
    if (out / "manifest.json").exists():
        raise ValueError("corpus is frozen; use --check or a new output directory")
    inventory = json.loads(inventory_path.read_text())
    sources = inventory["sources"]
    ids = [s["id"] for s in sources]
    if len(sources) != 24 or len(set(ids)) != 24 or any(not re.fullmatch(r"[a-z0-9-]+", x) for x in ids):
        raise ValueError("invalid source inventory")
    out.mkdir(parents=True, exist_ok=True)
    for directory in (*PARTITIONS, "licenses"):
        (out / directory).mkdir(exist_ok=True)
    records, errors = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(acquire, s, cache): s for s in sources}
        for job in concurrent.futures.as_completed(jobs):
            source = jobs[job]
            try:
                _, location, provenance = job.result()
                extracted, member = extract(source, (location / "download.bin").read_bytes())
                check_signature(source, extracted)
                raw = extracted[:inventory["cap_bytes"]]
                path = source["partition"] + "/" + source["id"] + ".raw"
                license_path = "licenses/" + source["id"] + ".txt"
                (out / path).write_bytes(raw)
                (out / license_path).write_bytes((location / "license.txt").read_bytes())
                records[source["id"]] = {"path": path, "partition": source["partition"],
                    "family": "real", "class": source["class"], "source_group": source["id"],
                    "bytes": len(raw), "sha256": digest(raw), "license": source["license"],
                    "license_path": license_path, "provenance": provenance,
                    "archive_member": member, "extracted_source_bytes": len(extracted),
                    "extracted_source_sha256": digest(extracted), "extraction_range": [0, len(raw)]}
                print("acquired", source["id"], len(raw), flush=True)
            except Exception as error:
                errors.append({"source": source, "error": str(error), "url": getattr(error, "url", None)})
                print("failed", source["id"], str(error), flush=True)
    if errors:
        attempt = {"inventory_sha256": digest(inventory_path.read_bytes()), "successful": sorted(records), "errors": errors}
        name = "acquisition-failed-" + str(time.time_ns()) + ".json"
        write_json(out / name, attempt)
        raise ValueError("acquisition incomplete; cached successes can be resumed")
    meta = {"schema_version": 1, "inventory_sha256": digest(inventory_path.read_bytes()),
            "tool_sha256": digest(Path(__file__).read_bytes()), "cap_bytes": inventory["cap_bytes"],
            "cases": [records[s["id"]] for s in sources],
            "test_policy": "reserved; integrity hashes only; no selector features or encoder measurements",
            "dedup_policy": "distinct declared lineage, exact hash, >=80% shared aligned 4KiB chunks rejected",
            "sampling_policy": "complete files <=1MiB; otherwise first 1MiB recorded as a bounded real-file slice"}
    summary = validate(out, meta)
    write_json(out / "manifest.json", meta)
    print(json.dumps({"manifest_sha256": digest((out / "manifest.json").read_bytes()), "coverage": summary}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--cache", type=Path, default=ROOT / "target/encoder-performance/download-cache")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        meta = json.loads((args.out / "manifest.json").read_text())
        print(json.dumps(validate(args.out, meta)))
    else:
        run(args.out, args.inventory, args.cache)
