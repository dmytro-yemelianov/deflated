#!/usr/bin/env python3
"""v16 holdout: malformed-input agreement with Python zlib, and peak RSS.

Malformed agreement: for every case, frame and the zlib level-6 packet, apply
fixed mutations (truncations, seeded single-bit flips, a one-byte suffix and,
for gzip, CRC/ISIZE flips). Python zlib is the reference verdict: a mutation is
"accepted" only if zlib reaches end of stream with no unused data. Every decoder
must agree: reject (exit status 2, no crash) when zlib rejects, and produce
exactly zlib's bytes when zlib accepts. Error kinds are not compared.

Peak RSS: one cold decode per decoder for every level-6 packet, measured as
the child's ru_maxrss through a fresh Python wrapper (bytes on macOS, KiB on
Linux; normalised to bytes). This is whole-process RSS including the packet
and output buffers, not decoder-only working memory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
FLIPS = 16
SEED = 0x16


def sha(data):
    return hashlib.sha256(data).hexdigest()


def zlib_verdict(data, frame):
    decoder = zlib.decompressobj(-15 if frame == "raw" else 31)
    try:
        out = decoder.decompress(data) + decoder.flush()
    except zlib.error:
        return None
    return out if decoder.eof and not decoder.unused_data else None


def encode(raw, frame):
    compressor = zlib.compressobj(6, wbits=-15 if frame == "raw" else 31)
    data = bytearray(compressor.compress(raw) + compressor.flush())
    if frame == "gzip":
        data[9] = 255  # Same canonical OS byte as library_bench.py.
    return bytes(data)


def mutations(packet, frame, rng):
    n = len(packet)
    for k in range(8):
        yield f"truncate-{k}/8", packet[: n * k // 8]
    yield "truncate-last", packet[:-1]
    for i in range(FLIPS):
        position = rng.randrange(n * 8)
        data = bytearray(packet)
        data[position // 8] ^= 1 << (position % 8)
        yield f"flip-{position}", bytes(data)
    yield "suffix", packet + b"x"
    if frame == "gzip":
        for name, offset in [("crc", n - 8), ("isize", n - 4)]:
            data = bytearray(packet)
            data[offset] ^= 1
            yield f"bad-{name}", bytes(data)


def worker_command(binary, codec, frame, packet, output, expected):
    level = "balanced" if codec == "core" else "6"
    return [str(binary), "cold", codec, level, frame, str(packet), str(output), "0", str(expected)]


def peak_rss(command):
    wrapper = ("import resource,subprocess,sys;"
               "r=subprocess.run(sys.argv[1:],capture_output=True);"
               "print(r.returncode, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)")
    status, rss = subprocess.check_output([sys.executable, "-c", wrapper, *command], text=True).split()
    scale = 1 if platform.system() == "Darwin" else 1024
    return int(status), int(rss) * scale


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="manifest.json from library_holdout_corpus.py")
    parser.add_argument("--core", type=Path, required=True, help="library_decode (fresh core worker)")
    parser.add_argument("--accel", type=Path, required=True, help="library_decode_accel")
    parser.add_argument("--workers", type=Path, required=True, help="native worker directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(args.corpus.read_text())
    decoders = [("core", args.core.resolve(), "core"), ("accel", args.accel.resolve(), "core"),
                ("zlib-ng", (args.workers / "zlib-ng-decode").resolve(), "zlib-ng"),
                ("libdeflate", (args.workers / "libdeflate-decode").resolve(), "libdeflate")]
    rng = random.Random(SEED)
    malformed, memory = [], []
    for case in manifest["cases"]:
        raw = (args.corpus.parent / case["path"]).read_bytes()
        if sha(raw) != case["sha256"]:
            raise ValueError("corpus hash mismatch")
        for frame in ["raw", "gzip"]:
            packet = encode(raw, frame)
            packet_path = args.out / "packet"
            packet_path.write_bytes(packet)
            for name, binary, codec in decoders:
                status, rss = peak_rss(worker_command(binary, codec, frame, packet_path, args.out / "decoded", len(raw)))
                if status != 0 or (args.out / "decoded").read_bytes() != raw:
                    raise ValueError(f"valid decode failed: {name} {case['name']} {frame}")
                memory.append({"case": case["name"], "frame": frame, "decoder": name, "raw_bytes": len(raw),
                               "packed_bytes": len(packet), "peak_rss_bytes": rss})
            for label, data in mutations(packet, frame, rng):
                expected = zlib_verdict(data, frame)
                bad = args.out / "bad"
                bad.write_bytes(data)
                row = {"case": case["name"], "frame": frame, "mutation": label,
                       "zlib": "accept" if expected is not None else "reject", "decoders": {}}
                for name, binary, codec in decoders:
                    output = args.out / "decoded"
                    output.unlink(missing_ok=True)
                    size = len(expected) if expected is not None else len(raw)
                    result = subprocess.run(worker_command(binary, codec, frame, bad, output, size), capture_output=True)
                    if expected is not None:
                        agree = result.returncode == 0 and output.read_bytes() == expected
                    else:
                        agree = result.returncode == 2
                    row["decoders"][name] = {"status": result.returncode, "agrees": agree}
                malformed.append(row)
    disagreements = [r for r in malformed if not all(d["agrees"] for d in r["decoders"].values())]
    result = {"host": platform.platform(), "machine": platform.machine(), "seed": SEED, "flips": FLIPS,
              "corpus_manifest_sha256": sha(args.corpus.read_bytes()),
              "decoders": {name: {"path": str(path), "sha256": sha(path.read_bytes())} for name, path, _ in decoders},
              "malformed_rows": len(malformed), "zlib_accepts": sum(r["zlib"] == "accept" for r in malformed),
              "disagreements": disagreements, "malformed": malformed, "memory": memory}
    (args.out / "checks.json").write_text(json.dumps(result) + "\n")
    print(f"malformed rows {len(malformed)}, zlib accepts {result['zlib_accepts']}, disagreements {len(disagreements)}")


if __name__ == "__main__":
    main()
