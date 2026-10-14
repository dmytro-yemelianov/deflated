#!/usr/bin/env python3
"""Untimed token census and separately timed CRC-only comparisons for v5 packets."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--references", type=Path, default=ROOT / "target/library-v1/references")
    parser.add_argument("--receipt", type=Path, default=ROOT / "scripts/reports/library-decode-v5-reuse-real.json.gz")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    receipt = json.loads(gzip.decompress(args.receipt.read_bytes()))
    for path, digest in receipt["source_sha256"].items():
        assert sha(ROOT / path) == digest, "v5 source changed"
    binaries = {"candidate": ROOT / "target/release/examples/crc_bench"}
    builds = []
    for codec, index, library in [("zlib-ng", 2, "z-ng"), ("libdeflate", 3, "deflate")]:
        reference = args.references.resolve() / codec
        build = json.loads((reference / "build-receipt.json").read_text())
        for path, digest in build["libraries"].items():
            assert sha(reference / path) == digest, "native library changed"
        prefix = reference / "install"
        binary = args.out.resolve() / (codec + "-crc")
        command = ["clang", "-std=c11", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror", f"-DNATIVE_CODEC={index}",
                   "-I", str(prefix / "include"), str(ROOT / "scripts/native_crc_bench.c"), "-L", str(prefix / "lib"),
                   f"-Wl,-rpath,{prefix / 'lib'}", "-l" + library, "-o", str(binary)]
        subprocess.run(command, check=True)
        binaries[codec] = binary
        builds.append({"codec": codec, "command": command, "reference": build})
    census = []
    packets = {}
    raw_files = {}
    for row in receipt["rows"]:
        if row["frame"] != "raw":
            continue
        packets.setdefault((row["case"], row["encoder"]), row)
    for (case, encoder), row in sorted(packets.items()):
        packet = Path(row["path"])
        assert sha(packet) == row["packet_sha256"]
        shape = json.loads(subprocess.check_output([str(ROOT / "target/release/examples/decode_shape"), str(packet), str(row["raw_bytes"])], text=True))
        raw = zlib.decompress(packet.read_bytes(), wbits=-15)
        assert hashlib.sha256(raw).hexdigest() == row["raw_sha256"]
        source = args.out / (case + ".raw")
        source.write_bytes(raw)
        raw_files[case] = source
        census.append({"case": case, "encoder": encoder, "packet_sha256": row["packet_sha256"], **shape})
    print("census:", len(census), "raw packets validated", flush=True)
    rows = []
    methods = list(binaries)
    for session in range(5):
        for index, (case, source) in enumerate(sorted(raw_files.items())):
            offset = (session + index) % len(methods)
            for method in methods[offset:] + methods[:offset]:
                sample = json.loads(subprocess.check_output([str(binaries[method]), str(source), "100000000"], text=True))
                assert sample["crc32"] == zlib.crc32(source.read_bytes())
                assert sample["ns"] * sample["iterations"] >= 100000000 * .999
                rows.append({"session": session, "case": case, "method": method,
                             "bytes": source.stat().st_size, "raw_sha256": sha(source), **sample})
        print("CRC session", session + 1, flush=True)
    summary = []
    for method in methods:
        total_ns = sum(statistics.median(r["ns"] for r in rows if r["case"] == case and r["method"] == method) for case in raw_files)
        summary.append({"method": method, "MB_per_s": sum(p.stat().st_size for p in raw_files.values()) * 1000 / total_ns})
    sources = ["scripts/native_crc_bench.c", "scripts/native_decode_diagnostics.py", "crates/deflate-core/examples/crc_bench.rs", "crates/deflate-core/examples/decode_shape.rs"]
    report = {"receipt_sha256": sha(args.receipt), "core_sources": receipt["source_sha256"],
              "source_sha256": {p: sha(ROOT / p) for p in sources}, "native_builds": builds,
              "binaries": {m: {"path": str(p), "sha256": sha(p)} for m, p in binaries.items()},
              "census_binary_sha256": sha(ROOT / "target/release/examples/decode_shape"),
              "timing": "CRC only, resident raw input; warm dispatch; serial rotated order; 5 sessions, 100ms batches; no sampling/census/build running during timers",
              "census": census, "crc_rows": rows, "crc_summary": summary}
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
