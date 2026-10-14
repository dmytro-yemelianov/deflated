#!/usr/bin/env python3
"""Library-v1 decode diagnostics. No claim of representative/held-out performance.

build: isolated pinned native workers (references acquired by new_methods_references.py).
measure: same packets through every decoder, rotated serial sessions, native gzip APIs.
"""
import argparse
import hashlib
import gzip
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def run(command):
    return subprocess.check_output([str(x) for x in command], text=True)


def build(args):
    args.out.mkdir(parents=True, exist_ok=False)
    values = []
    for byte in range(256):
        value = byte
        for _ in range(8):
            value = (value >> 1) ^ (0xEDB88320 if value & 1 else 0)
        values.append(f"0x{value:08x}u")
    table = args.out / "native_crc32_table.h"
    table.write_text("static const uint32_t crc_table[256] = {" + ",".join(values) + "};\n")
    receipts = []
    for codec, index, library in [("zlib-ng", 2, "z-ng"), ("libdeflate", 3, "deflate")]:
        reference = (args.references / codec).resolve()
        receipt = json.loads((reference / "build-receipt.json").read_text())
        for name, digest in receipt["libraries"].items():
            if sha(reference / name) != digest:
                raise ValueError("reference library hash changed")
        prefix = reference / "install"
        for direction, source in [("encode", "native_codec_worker.c"), ("decode", "library_decode_worker.c")]:
            binary = args.out.resolve() / f"{codec}-{direction}"
            command = ["clang", "-std=c11", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror",
                       "-Wno-unused-function", f"-DNATIVE_CODEC={index}", "-I", str(prefix / "include"),
                       "-I", str(args.out.resolve()), str(ROOT / "scripts" / source),
                       "-L", str(prefix / "lib"), f"-Wl,-rpath,{prefix / 'lib'}", "-l" + library,
                       "-o", str(binary)]
            subprocess.run(command, check=True)
            receipts.append({"codec": codec, "direction": direction, "command": command,
                             "binary_sha256": sha(binary), "version": json.loads(run([binary, "--version"])),
                             "reference": receipt})
    write(args.out / "build.json", {"workers": receipts, "sources": {
        name: sha(ROOT / "scripts" / name) for name in
        ["native_codec_worker.c", "library_decode_worker.c", "library_bench.py"]}})


def corpus():
    # Two unchanged repository documents/code files, plus labelled synthetic cases.
    for name, source in [("lean-source", "spec/Deflate/Properties.lean"), ("spec-text", "VERIFIED_DEFLATE_SPEC.md")]:
        yield name, "repository", (ROOT / source).read_bytes(), source
    rng = random.Random(1951)
    yield "random", "synthetic", rng.randbytes(262144), None
    yield "periodic", "synthetic", (b"abcdef0123456789" * 16384), None
    yield "zeros", "synthetic", bytes(262144), None
    yield "empty", "tiny", b"", None
    yield "hello", "tiny", b"hello world", None


def manifest_corpus(path):
    manifest = json.loads(path.read_text())
    seen = set()
    if not manifest["cases"]:
        raise ValueError("empty corpus")
    for case in manifest["cases"]:
        name = case["name"]
        if name in seen or not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
            raise ValueError("invalid or duplicate corpus name")
        seen.add(name)
        source = path.parent / case["path"]
        raw = source.read_bytes()
        if len(raw) > 64 << 20 or sha(source) != case["sha256"]:
            raise ValueError("corpus size/hash mismatch")
        yield name, case["scope"], raw, str(source)


def call(binary, codec, mode, frame, packet, output, minimum, expected, level=6):
    return [binary, mode, codec, "balanced" if codec == "core" else str(level), frame,
            packet, output, str(minimum), str(expected)]


def summarize(rows):
    if len({r.get("context", "fresh-decoder-only") for r in rows}) > 1:
        raise ValueError("cannot aggregate different decoder contexts")
    result = []
    for scope in sorted({r["scope"] for r in rows}):
        for frame in ["raw", "gzip"]:
            selected = [r for r in rows if r["scope"] == scope and r["frame"] == frame]
            keys = sorted({(r["case"], r["encoder"]) for r in selected})
            for method in sorted({r["method"] for r in selected}):
                medians = [statistics.median(r["decode_ns"] for r in selected
                           if (r["case"], r["encoder"]) == key and r["method"] == method) for key in keys]
                byte_count = sum(next(r["raw_bytes"] for r in selected
                                     if (r["case"], r["encoder"]) == key) for key in keys)
                result.append({"scope": scope, "frame": frame, "method": method,
                               "summed_median_ns": sum(medians),
                               "MB_per_s": byte_count * 1000 / sum(medians)})
    return result


def verify_freeze(freeze, sources, binary_sha256):
    if (freeze["binary_sha256"] != binary_sha256 or not freeze["sources"]
            or any(sources.get(path) != digest for path, digest in freeze["sources"].items())):
        raise ValueError("candidate differs from frozen source/binary")


def measure(args):
    if args.candidate is None:
        args.candidate = ROOT / "target/release/examples" / ("library_decode_reuse" if args.reuse else "library_decode")
    cold_mode = "context-cold" if args.reuse else "cold"
    warm_mode = "context-warm" if args.reuse else "warm"
    context = "reuse-state-output" if args.reuse else "fresh-decoder-only"
    if len(args.levels) != len(set(args.levels)):
        raise ValueError("duplicate compression levels")
    if args.sessions < 1 or args.minimum_ns < 1:
        raise ValueError("sessions and minimum-ns must be positive")
    args.out.mkdir(parents=True, exist_ok=False)
    methods = [("candidate", args.candidate.resolve(), "core")]
    if args.baseline:
        methods.append(("baseline", args.baseline.resolve(), "core"))
    methods += [(codec, (args.workers / f"{codec}-decode").resolve(), codec)
                for codec in ["zlib-ng", "libdeflate"]]
    tracked = run(["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard",
                   "crates/deflate-core/src", "crates/deflate-accel/src",
                   "crates/deflate-accel/examples"]).splitlines()
    tracked += ["crates/deflate-core/examples/library_decode.rs", "crates/deflate-core/examples/library_decode_reuse.rs", "scripts/library_bench.py",
                "crates/deflate-core/Cargo.toml", "crates/deflate-accel/Cargo.toml",
                "Cargo.toml", "Cargo.lock", "rust-toolchain.toml"]
    sources = {p: sha(ROOT / p) for p in tracked}
    binaries = {name: {"binary": str(path), "sha256": sha(path), "bytes": path.stat().st_size} for name, path, _ in methods}
    candidate_freeze = None
    if args.candidate_freeze:
        candidate_freeze = json.loads(args.candidate_freeze.read_text())
        verify_freeze(candidate_freeze, sources, binaries["candidate"]["sha256"])
    manifest = None if not args.corpus_manifest else json.loads(args.corpus_manifest.read_text())
    manifest_sha256 = None if not args.corpus_manifest else sha(args.corpus_manifest)
    native_build = json.loads((args.workers / "build.json").read_text())
    for worker in native_build["workers"]:
        binary = args.workers / f"{worker['codec']}-{worker['direction']}"
        if sha(binary) != worker["binary_sha256"]:
            raise ValueError("native worker changed since build receipt")
        # The original build command carries the actual reference prefix even
        # when callers choose unrelated --references and --out directories.
        command = worker["command"]
        prefix = Path(command[command.index("-L") + 1]).parent.parent
        for relative, digest in worker["reference"]["libraries"].items():
            if sha(prefix / relative) != digest:
                raise ValueError("native library changed since build receipt")
    baseline_receipt = None
    if args.baseline_receipt:
        blob = args.baseline_receipt.read_bytes()
        previous = json.loads(gzip.decompress(blob) if args.baseline_receipt.suffix == ".gz" else blob)
        if not args.baseline or sha(args.baseline) != previous["methods"]["candidate"]["sha256"]:
            raise ValueError("baseline does not match the prior candidate receipt")
        baseline_receipt = {"path": str(args.baseline_receipt), "sha256": sha(args.baseline_receipt)}
    packets, contracts = [], 0
    cases = manifest_corpus(args.corpus_manifest) if args.corpus_manifest else corpus()
    for name, scope, raw, source in cases:
        raw_path = args.out / (name + ".raw")
        raw_path.write_bytes(raw)
        for frame in ["raw", "gzip"]:
            roster = [(encoder, level) for encoder in ["zlib", "zlib-ng", "libdeflate"] for level in args.levels]
            for encoder, level in roster:
                encoder_label = encoder if args.levels == [6] else f"{encoder}-{level}"
                packet = args.out / f"{name}.{encoder_label}.{frame}"
                if encoder == "zlib":
                    compressor = zlib.compressobj(level, wbits=-15 if frame == "raw" else 31)
                    encoded = bytearray(compressor.compress(raw) + compressor.flush())
                    if frame == "gzip":
                        encoded[9] = 255  # Match the historical baseline's canonical OS field.
                    packet.write_bytes(encoded)
                else:
                    run(call((args.workers / f"{encoder}-encode").resolve(), encoder, "encode",
                             frame, raw_path, packet, 0, len(raw), level))
                # Independent Python/zlib decoder: complete frame and exact bytes.
                decoder = zlib.decompressobj(-15 if frame == "raw" else 31)
                if decoder.decompress(packet.read_bytes()) + decoder.flush() != raw or not decoder.eof or decoder.unused_data:
                    raise ValueError("encoder cross-decode failed")
                item = {"case": name, "scope": scope, "frame": frame, "encoder": encoder_label, "level": level,
                        "raw_bytes": len(raw), "raw_sha256": sha(raw_path), "packet_sha256": sha(packet),
                        "source": source, "path": str(packet)}
                packets.append(item)
                # Every decoder: valid bytes, truncation and wrong expected size.
                for _, binary, codec in methods:
                    output = args.out / "decoded"
                    run(call(binary, codec, cold_mode, frame, packet, output, 0, len(raw)))
                    if output.read_bytes() != raw:
                        raise ValueError("decoder cross-check failed")
                    invalid = [(packet.read_bytes()[:-1], len(raw)),
                               (packet.read_bytes(), len(raw) + 1),
                               (packet.read_bytes() + b"x", len(raw))]
                    if frame == "gzip":
                        bad_crc = bytearray(packet.read_bytes())
                        bad_crc[-8] ^= 1
                        invalid.append((bad_crc, len(raw)))
                    for data, expected in invalid:
                        bad = args.out / "bad"
                        bad.write_bytes(data)
                        check = subprocess.run([str(x) for x in call(binary, codec, cold_mode, frame, bad, output, 0, expected)],
                                               capture_output=True)
                        if check.returncode != 2:
                            raise ValueError("decoder accepted truncation/wrong size or crashed")
                        contracts += 1
    rows = []
    for session in range(args.sessions):
        ordered = packets[session:] + packets[:session]
        for index, packet in enumerate(ordered):
            offset = (session + index) % len(methods)
            for method, binary, codec in methods[offset:] + methods[:offset]:
                output = args.out / "decoded"
                sample = json.loads(run(call(binary, codec, warm_mode, packet["frame"], packet["path"], output,
                                             args.minimum_ns, packet["raw_bytes"])))
                if (sha(output) != packet["raw_sha256"] or sample["decode_ns"] <= 0
                        or sample["encoder_calls"] != 0 or sample["context"] != context
                        or sample["raw_bytes"] != packet["raw_bytes"]
                        or sample["packed_bytes"] != Path(packet["path"]).stat().st_size
                        or sample["decode_iterations"] < 1
                        or sample["decode_ns"] * sample["decode_iterations"] < args.minimum_ns * 0.999):
                    raise ValueError("timed decode failed validation")
                rows.append({**packet, **sample, "method": method, "session": session})
        print(f"session {session + 1}/{args.sessions}: {len(rows)} rows", flush=True)
    if sources != {p: sha(ROOT / p) for p in tracked}:
        raise ValueError("source changed during measurement")
    if args.corpus_manifest and sha(args.corpus_manifest) != manifest_sha256:
        raise ValueError("corpus manifest changed during measurement")
    for name, path, _ in methods:
        if sha(path) != binaries[name]["sha256"]:
            raise ValueError("decoder binary changed during measurement")
    report = {"schema_version": 1, "study": args.study,
              "baseline_receipt": baseline_receipt,
              "candidate_freeze": candidate_freeze,
              "corpus_manifest": manifest, "corpus_manifest_sha256": manifest_sha256, "host": platform.platform(),
              "rustc": run(["rustc", "-vV"]), "revision": run(["git", "-C", ROOT, "rev-parse", "HEAD"]).strip(),
              "source_sha256": sources,
              "driver_sha256": sha(ROOT / "crates/deflate-core/examples" /
                                   ("library_decode_reuse.rs" if args.reuse else "library_decode.rs")),
              "controller_sha256": sha(Path(__file__)), "python_zlib": zlib.ZLIB_RUNTIME_VERSION,
              "native_build": native_build,
              "methods": binaries,
              "sessions": args.sessions, "minimum_ns": args.minimum_ns, "rejection_contracts": contracts,
              "scope": manifest.get("scope", "custom diagnostic corpus") if manifest else
                       "diagnostic repository/synthetic/tiny corpus; no holdout or universal performance claim",
              "context": context,
              "timing": "same packet per decoder; " +
                        ("reused state/output, initialization excluded from warm timer" if args.reuse else "fresh state/output per call") +
                        "; resident input, native gzip checksums; IO excluded",
              "summary": summarize(rows), "rows": rows}
    write(args.out / "report.json", report)
    for row in report["summary"]:
        print(f"{row['scope']:12} {row['frame']:4} {row['method']:12} {row['MB_per_s']:9.1f} MB/s")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--references", type=Path, required=True)
    builder.add_argument("--out", type=Path, required=True)
    bench = commands.add_parser("measure")
    bench.add_argument("--workers", type=Path, required=True)
    bench.add_argument("--candidate", type=Path, help="defaults to library_decode or library_decode_reuse according to --reuse")
    bench.add_argument("--baseline", type=Path)
    bench.add_argument("--reuse", action="store_true", help="reuse state AND output for every decoder")
    bench.add_argument("--out", type=Path, required=True)
    bench.add_argument("--baseline-receipt", type=Path)
    bench.add_argument("--candidate-freeze", type=Path)
    bench.add_argument("--study", default="library-decode-v1-diagnostic")
    bench.add_argument("--corpus-manifest", type=Path)
    bench.add_argument("--levels", type=int, choices=[1, 6, 9], nargs="+", default=[6])
    bench.add_argument("--sessions", type=int, default=3)
    bench.add_argument("--minimum-ns", type=int, default=20_000_000)
    args = parser.parse_args()
    (build if args.command == "build" else measure)(args)


if __name__ == "__main__":
    main()
