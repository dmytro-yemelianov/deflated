#!/usr/bin/env python3
"""Shared decoder-only timing/consumption contracts; no study data accessed."""
import argparse
import itertools
import json
from pathlib import Path
import subprocess
import tempfile

from encoder_corpus import ROOT, digest, write_json
from structured_correspondence import witnesses
from structured_reference import decode as structured_decode
from test_native_codec_workers import LEVELS, independent


def roster():
    for codec, levels in LEVELS.items():
        for frame in (["raw", "gzip", "zip"] if codec in ("zlib", "zlib-ng", "libdeflate") else ["frame"]):
            for level in levels:
                yield codec, str(level), frame, codec, codec
    for codec, levels, name in (("core", ("fast", "balanced", "best"), "core"),
                                ("miniz", (1, 6, 9), "miniz")):
        for level, frame in itertools.product(levels, ("raw", "gzip", "zip")):
            yield codec, str(level), frame, name + "_worker", name + "_decode"
    for log2, dictionary, numbers in itertools.product((16, 18), ("off", "keys", "all-quoted"), ("off", "checked-delta")):
        yield "dsc1", f"{log2}/{dictionary}/{numbers}", "frame", "structured_worker", "structured_decode"
    for log2 in (16, 18):
        yield "dsc1", f"{log2}/off/off", "plain", "structured_worker", "structured_decode"


def call(binary, mode, codec, level, frame, source, out, minimum, expected):
    return subprocess.run([str(binary), mode, codec, level, frame, str(source), str(out),
                           str(minimum), str(expected)], capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=Path, default=ROOT / "target/new-methods/decode-workers-v1")
    parser.add_argument("--rust-only", action="store_true", help="CI: verify only the three Rust decoder binaries")
    parser.add_argument("--encoders", type=Path, help="CI Rust worker directory")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if not args.rust_only:
        build = json.loads((args.workers / "build.json").read_text())
        for relative, expected in build["inputs_sha256"].items():
            assert digest((ROOT / relative).read_bytes()) == expected
    selected = [(name, raw) for name, raw in witnesses() if name in ("one", "chunk65537")]
    assert len(selected) == 2
    rows, rejected = [], 0
    with tempfile.TemporaryDirectory(prefix="decode-only-contracts-") as temporary:
        directory = Path(temporary)
        raw_path, packet_path, output_path = (directory / name for name in ("raw", "packet", "decoded"))
        for codec, level, frame, encoder_name, decoder_name in roster():
            if args.rust_only and codec in LEVELS:
                continue
            encoder_root = "native-workers-v1" if codec in LEVELS else "rust-workers-v1"
            encoder = ((args.encoders / encoder_name) if args.encoders else
                       ROOT / "target/new-methods" / encoder_root / encoder_name)
            decoder = args.workers / decoder_name
            for name, raw in selected:
                raw_path.write_bytes(raw)
                result = call(encoder, "encode", codec, level, frame, raw_path, packet_path, 0, 0)
                assert result.returncode == 0, result.stderr
                packet = packet_path.read_bytes()
                assert (structured_decode(packet) if codec == "dsc1" else independent(codec, frame, packet)) == raw
                for mode in ("cold", "warm"):
                    result = call(decoder, mode, codec, level, frame, packet_path, output_path, 2000000, len(raw))
                    assert result.returncode == 0, (codec, level, frame, name, result.stderr)
                    sample = json.loads(result.stdout)
                    assert output_path.read_bytes() == raw
                    assert sample["context"] == "fresh-decoder-only" and sample["encoder_calls"] == 0
                    assert sample["decode_init_ns"] == 0 and sample["raw_bytes"] == len(raw)
                    assert sample["packed_bytes"] == len(packet)
                    assert sample["decode_ns"] > 0 and sample["first_decode_ns"] > 0
                    count = sample["decode_iterations"]
                    assert count >= 1
                    if mode == "cold":
                        assert count == 1 and sample["decode_ns"] == sample["first_decode_ns"]
                    else:
                        assert sample["decode_ns"] * count >= 1999990
                    rows.append({"codec": codec, "level": level, "framing": frame, "case": name,
                                 "mode": mode, "raw_sha256": digest(raw), "packet_sha256": digest(packet),
                                 "binary_sha256": digest(decoder.read_bytes())})
                for bad in (packet[:-1], packet + b"x", packet + packet):
                    packet_path.write_bytes(bad)
                    result = call(decoder, "cold", codec, level, frame, packet_path, output_path, 0, len(raw))
                    assert result.returncode == 2, (codec, level, frame, name, "consumption", result.stderr)
                    rejected += 1
                packet_path.write_bytes(packet)
                result = call(decoder, "cold", codec, level, frame, packet_path, output_path, 0, len(raw) + 1)
                assert result.returncode == 2, (codec, level, frame, name, "output size", result.stderr)
                rejected += 1
    receipt = {"schema_version": 1, "status": "passed", "scope": "two shared correctness witnesses, all preregistered levels/frames; not performance screening",
               "tool_sha256": digest(Path(__file__).read_bytes()),
               "build_sha256": None if args.rust_only else digest((args.workers / "build.json").read_bytes()),
               "timer_contracts": len(rows), "rejected_cases": rejected, "rows": rows,
               "no_encoder_evidence": "decoder-only entrypoint source path inspection; Rust timer unit witness panics if encode is called; each new process supplies only its packet"}
    if args.receipt:
        write_json(args.receipt, receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != "rows"}))


if __name__ == "__main__":
    main()
