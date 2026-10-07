#!/usr/bin/env python3
"""Freeze the verified G0 control roster before any study screening.

--check audits published evidence; --local additionally rechecks actual worker,
library and baseline binaries. Creation refuses an existing lock and marks the
local worker directories frozen. OpenZL's bounded exclusion is explicit.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "scripts/reports"
LOCK = REPORTS / "new-methods-reference-lock.json"
NATIVE = ROOT / "target/new-methods/native-workers-v1"
RUST = ROOT / "target/new-methods/rust-workers-v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    path = REPORTS / name
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


SETTINGS = {
    "zlib": {"encoder": "deflateInit2/deflateBound/deflate(Z_FINISH)/deflateEnd", "decoder": "inflateInit2/inflate(Z_FINISH)/inflateEnd",
             "window_bits": -15, "memory_level": 8, "strategy": "Z_DEFAULT_STRATEGY", "reuse": "deflateReset/inflateReset"},
    "zlib-ng": {"encoder": "zng_deflateInit2/zng_deflateBound/zng_deflate(Z_FINISH)/zng_deflateEnd", "decoder": "zng_inflateInit2/zng_inflate(Z_FINISH)/zng_inflateEnd",
                "window_bits": -15, "memory_level": 8, "strategy": "Z_DEFAULT_STRATEGY", "reuse": "zng_deflateReset/zng_inflateReset"},
    "libdeflate": {"encoder": "libdeflate_alloc_compressor/deflate_compress_bound/deflate_compress/free_compressor",
                   "decoder": "libdeflate_alloc_decompressor/deflate_decompress_ex/free_decompressor", "reuse": "retained allocation; each call is an independent member"},
    "zstd": {"encoder": "ZSTD_createCCtx/setParameter/compress2/freeCCtx", "decoder": "ZSTD_findFrameCompressedSize/getFrameContentSize/createDCtx/decompressDCtx/freeDCtx",
             "content_size": True, "content_checksum": True, "nb_workers": 0, "reuse": "session_only reset; settings reapplied inside encode"},
    "lz4": {"encoder": "LZ4F_compressFrame", "decoder": "LZ4F_createDecompressionContext/getFrameInfo/decompress/freeDecompressionContext",
            "block_bytes": 65536, "content_checksum": True, "block_checksum": True, "content_size": "native API omits size for empty input",
            "block_mode": "independent <=65536 bytes; linked otherwise", "reuse": "compressBegin/Update/End; autoFlush=1, stableSrc=1; resetDecompressionContext"},
    "brotli": {"encoder": "BrotliEncoderMaxCompressedSize/BrotliEncoderCompress", "decoder": "BrotliDecoderCreateInstance/DecompressStream/DestroyInstance",
               "mode": "GENERIC", "window_log2": 22, "framing": "BRF1 + little-endian u64 original size + u32 CRC32 + native Brotli stream", "reuse": "fresh-no-reset-api"},
    "lzma2": {"encoder": "lzma_stream_buffer_bound/lzma_easy_buffer_encode", "decoder": "lzma_stream_buffer_decode",
              "container": "XZ", "check": "CRC32", "preset_flags": "ordinary preset; no EXTREME/BCJ", "reuse": "fresh-no-reset-api"},
}
FRAMING = {
    "raw": "one raw DEFLATE member; exact input consumption; expected decoded size supplied by test/controller",
    "gzip": {"overhead": 18, "mtime": 0, "os": 255, "xfl": 0, "optional_fields": False, "crc": "paid CRC32", "isize": "paid u32 size"},
    "zip": {"overhead": 114, "filename": "data.bin", "method": 8, "date": "1980-01-01 00:00:00", "version": 20,
            "extra_comment_descriptor": False, "crc": "paid CRC32", "central_directory_and_eocd": "paid; one entry"},
}


def miniz_source():
    cargo = tomllib.loads((ROOT / "Cargo.lock").read_text())
    package = next(p for p in cargo["package"] if p["name"] == "miniz_oxide" and p["version"] == "0.8.9")
    archives = list((Path.home() / ".cargo/registry/cache").glob("*/miniz_oxide-0.8.9.crate"))
    sources = list((Path.home() / ".cargo/registry/src").glob("*/miniz_oxide-0.8.9"))
    if len(archives) != 1 or len(sources) != 1 or sha(archives[0]) != package["checksum"]:
        raise RuntimeError("missing or mismatched pinned miniz crate archive")
    # Verify the local source consumed by Cargo against that exact archive.
    count = 0
    with tarfile.open(archives[0]) as bundle:
        for member in bundle.getmembers():
            parts = Path(member.name).parts
            if member.isfile() and (parts[1] == "src" or parts[-1] == "Cargo.toml"):
                content = bundle.extractfile(member).read()
                if (sources[0] / Path(*parts[1:])).read_bytes() != content:
                    raise RuntimeError("local miniz source differs from crate archive: " + member.name)
                count += 1
    return {"release": "0.8.9", "source_archive_sha256": package["checksum"], "verified_source_files": count,
            "source": "https://static.crates.io/crates/miniz_oxide/miniz_oxide-0.8.9.crate"}


def construct():
    native = read("new-methods-native-workers-build.json")
    rust = read("new-methods-rust-workers-build.json")
    nv = read("new-methods-native-worker-contracts.json.gz")
    rv = read("new-methods-rust-worker-contracts.json.gz")
    sources = read("new-methods-reference-sources.json")
    protocol = json.loads((ROOT / "scripts/new_methods_protocol.json").read_text())
    minisrc = miniz_source()
    refs = []
    for rule in protocol["references"]:
        codec = rule["codec"]
        entry = dict(rule, threads=1, external_dictionary=False)
        if codec in ("deflate-core-b7", "miniz_oxide"):
            key, name = ("core", "core_worker") if codec == "deflate-core-b7" else ("miniz", "miniz_worker")
            entry.update(worker_codec=key, worker_path=str((RUST / name).relative_to(ROOT)), binary=rust["binaries"][name],
                         compiler=rust["rustc"], flags="Rust 1.88.0 release opt-level=3; ordinary target; no research-tuning; recorded removed overrides",
                         adapter_inputs_sha256=rust["inputs_sha256"], ordinary_context="fresh per-call work state, allocations and framing; no data-history reuse",
                         reusable_context="fresh-no-reuse-adapter", frames=["raw", "gzip", "zip"],
                         validation_receipt="scripts/reports/new-methods-rust-worker-contracts.json.gz", validation_binary_sha256=rv["binary_sha256"][key])
            if codec == "deflate-core-b7":
                entry.update(release=protocol["baseline_revision"], source_sha256=rust["baseline_core_sha256"],
                             encoder_api="deflate_with_level", decoder_api="tooling copy of public block driver; exact consumption/size charged; public inflate suffix contract unchanged",
                             baseline_packet_identity_cases=42)
            else:
                entry.update(**minisrc, encoder_api="miniz_oxide::deflate::compress_to_vec",
                             decoder_api="miniz_oxide::inflate::core::decompress; same fresh Box state/geometric Vec growth as decompress_to_vec_with_limit; exact final consumption/size charged",
                             baseline_packet_identity_cases=42)
        else:
            worker = next(w for w in native["workers"] if w["codec"] == codec)
            entry.update(release=sources[codec]["release"], source_archive_sha256=sources[codec]["archive_sha256"],
                         source_url=sources[codec]["url"], compiler=sources[codec]["compiler"],
                         library_build_commands=sources[codec]["commands"], library_sha256=sources[codec]["libraries"],
                         library_compile_commands_sha256=sources[codec]["compile_commands_sha256"],
                         worker_codec=codec, worker_path=str((NATIVE / codec).relative_to(ROOT)),
                         binary={"sha256": worker["binary_sha256"], "bytes": worker["binary_bytes"]},
                         runtime_version=worker["version"], linkage=worker["linkage"], adapter_command=worker["command"],
                         adapter_sha256=native["source_sha256"], crc_table_sha256=native["table_sha256"],
                         settings=SETTINGS[codec], ordinary_context="fresh codec state + destroy + allocation + checksum/frame inside each call",
                         frames=["raw", "gzip", "zip"] if codec in ("zlib", "zlib-ng", "libdeflate") else ["frame"],
                         validation_receipt="scripts/reports/new-methods-native-worker-contracts.json.gz", validation_binary_sha256=nv["binary_sha256"][codec])
        refs.append(entry)
    evidence = ["new-methods-reference-sources.json", "new-methods-reference-cache.json", "new-methods-reference-compile-commands.json.gz",
                "new-methods-baseline-seal.json", "new-methods-native-workers-build.json", "new-methods-native-worker-contracts.json.gz",
                "new-methods-native-implementation-ledger.json", "new-methods-rust-workers-build.json", "new-methods-rust-worker-contracts.json.gz",
                "new-methods-openzl-setup.json", "new-methods-openzl-feasibility.json", "new-methods-openzl-second-setup-logs.json.gz"]
    return {"schema_version": 1, "study": protocol["study"], "status": "G0 control roster frozen before any study screening",
            "baseline_revision": protocol["baseline_revision"], "references": refs, "matched_deflate_framing": FRAMING,
            "evidence_sha256": {str((REPORTS / name).relative_to(ROOT)): sha(REPORTS / name) for name in evidence},
            "control_tooling_sha256": {p: sha(ROOT / p) for p in ["scripts/new_methods_reference_lock.py", "scripts/native_codec_worker.c",
                "scripts/new_methods_native_build.py", "scripts/new_methods_rust_build.py", "scripts/test_native_codec_workers.py", "scripts/test_rust_codec_workers.py"]},
            "clock": {"C": "mach_absolute_time on Apple; CLOCK_MONOTONIC otherwise", "Rust": "Instant", "measured_minimum_step_ns": 41, "overhead_subtracted": False},
            "measurements": "none on study data; evidence is shared correctness/timer contracts only",
            "optional_openzl": read("new-methods-openzl-feasibility.json"),
            "scope_limit": "nine verified reference implementations; no superiority claim about unmeasured OpenZL, typed/trained graphs, other versions/settings/platforms",
            "initial_structured_prototype": {"worker_path": str((RUST / "structured_worker").relative_to(ROOT)),
                "binary": rust["binaries"]["structured_worker"], "tool_binary": rust["binaries"]["structured-tool"],
                "status": "correctness prototype, not performance-qualified or frame-model-proved; all 12 configurations + 2 plain controls fixed by protocol"}}


def check(lock, local=False):
    for collection in ("evidence_sha256", "control_tooling_sha256"):
        for relative, expected in lock[collection].items():
            if sha(ROOT / relative) != expected:
                raise RuntimeError("locked evidence/tooling differs: " + relative)
    protocol = json.loads((ROOT / "scripts/new_methods_protocol.json").read_text())
    assert [r["codec"] for r in lock["references"]] == [r["codec"] for r in protocol["references"]]
    for ref, rule in zip(lock["references"], protocol["references"]):
        assert ref["levels"] == rule["levels"] and ref["threads"] == 1 and ref["external_dictionary"] is False
        assert ref["binary"]["sha256"] == ref["validation_binary_sha256"]
        if local:
            if sha(ROOT / ref["worker_path"]) != ref["binary"]["sha256"]:
                raise RuntimeError("locked worker differs: " + ref["codec"])
            for relative, expected in ref.get("library_sha256", {}).items():
                if sha(ROOT / "target/new-methods/references-v1" / ref["codec"] / relative) != expected:
                    raise RuntimeError("locked library differs: " + ref["codec"])
    assert lock["optional_openzl"]["retry_budget_used"] == lock["optional_openzl"]["retry_budget_cap"] == 2
    assert lock["optional_openzl"]["performance_measured"] is False
    if local:
        assert sha(ROOT / lock["initial_structured_prototype"]["worker_path"]) == lock["initial_structured_prototype"]["binary"]["sha256"]
        seal = read("new-methods-baseline-seal.json")
        for name, entry in seal["binaries"].items():
            assert sha(ROOT / "target/new-methods/baseline-b7" / entry["path"]) == entry["sha256"], name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    if args.check:
        check(json.loads(LOCK.read_text()), args.local)
        print("G0 reference lock validated" + (" including local binaries/libraries" if args.local else " (published receipts)"))
        return
    if LOCK.exists():
        raise RuntimeError("existing reference lock; refusing replacement")
    lock = construct()
    check(lock, local=True)
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    for directory in (NATIVE, RUST):
        marker = directory / ".frozen"
        if marker.exists():
            raise RuntimeError("existing frozen worker marker")
        marker.write_text(sha(LOCK) + "\n")
    print(json.dumps({"status": lock["status"], "references": len(lock["references"]), "sha256": sha(LOCK)}))


if __name__ == "__main__":
    main()
