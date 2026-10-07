#!/usr/bin/env python3
"""Independent format/framing and adversarial-input checks for G0 controls.

Shared correctness fixtures and clock calibration are not training/holdout
measurements. The reference lock must precede study screening.
"""

import argparse
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
LEVELS = {"zlib": [1, 6, 9], "zlib-ng": [1, 6, 9], "libdeflate": [1, 6, 9, 12],
          "zstd": [-1, 1, 3, 9], "lz4": [0, 9], "brotli": [1, 5, 9], "lzma2": [1, 6]}


def independent(codec, framing, packet):
    if framing == "raw":
        decoder = zlib.decompressobj(-15)
        result = decoder.decompress(packet)
        assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
        return result
    if framing == "gzip":
        assert packet[:10] == bytes([31, 139, 8, 0, 0, 0, 0, 0, 0, 255])
        return gzip.decompress(packet)
    if framing == "zip":
        with zipfile.ZipFile(io.BytesIO(packet)) as archive:
            assert archive.namelist() == ["data.bin"]
            info = archive.getinfo("data.bin")
            assert info.date_time == (1980, 1, 1, 0, 0, 0) and info.compress_type == 8
            assert not info.extra and not info.comment and not archive.comment
            return archive.read("data.bin")
    if codec == "lzma2":
        assert packet[:6] == b"\xfd7zXZ\0" and packet[6:8] == b"\0\x01"
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        result = decoder.decompress(packet)
        assert decoder.eof and not decoder.unused_data and decoder.check == lzma.CHECK_CRC32
        return result
    if codec == "brotli":
        assert packet[:4] == b"BRF1"
        declared, crc = struct.unpack("<QI", packet[4:16])
        result = subprocess.run([shutil.which("brotli"), "--decompress", "--stdout"],
                                input=packet[16:], capture_output=True, check=True).stdout
        assert len(result) == declared and zlib.crc32(result) == crc
        return result
    if codec == "zstd":
        assert packet[:4] == b"\x28\xb5\x2f\xfd" and packet[4] & 4
        command = [shutil.which("zstd"), "--decompress", "--stdout", "--quiet"]
    elif codec == "lz4":
        assert packet[:4] == b"\x04\x22\x4d\x18" and packet[4] & 0x14 == 0x14
        command = [shutil.which("lz4"), "--decompress", "--stdout", "--quiet"]
    else:
        raise AssertionError(codec)
    return subprocess.run(command, input=packet, capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=Path, default=ROOT / "target/new-methods/native-workers-v1")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    for executable in ("zstd", "lz4", "brotli"):
        assert shutil.which(executable), f"independent decoder missing: {executable}"
    rng = random.Random(0x4e4154495645)
    cases = [("empty", b""), ("tiny", b"abc0abc1"), ("byte-domain", bytes(range(256))),
             ("lexical", b'{"k":-0,"k":0007,"x":1.0,"y":1e3,"raw":"\xff\\u0061"}\n'),
             ("boundary65535", rng.randbytes(65535)), ("boundary65536", b"z" * 65536),
             ("boundary65537", b"abc" * 21845 + b"xy"),
             ("mixed-history", (rng.randbytes(32768) + b"\0" * 65536) * 2)]
    rows, rejected, clocks, versions, hashes = [], 0, {}, {}, {}
    reset_rows, reuse_samples = [], []
    with tempfile.TemporaryDirectory(prefix="native-framing-") as temporary:
        directory = Path(temporary)
        raw_path, packet_path, out_path, second_path = (directory / n for n in ("raw", "packet", "decoded", "second"))
        for codec, levels in LEVELS.items():
            binary = (args.workers / codec).resolve()
            hashes[codec] = hashlib.sha256(binary.read_bytes()).hexdigest()
            versions[codec] = json.loads(subprocess.check_output([str(binary), "--version"], text=True))
            clocks[codec] = json.loads(subprocess.check_output([str(binary), "--clock"], text=True))
            assert 0 < clocks[codec]["minimum_observed_clock_step_ns"] < 1000
            frames = ["raw", "gzip", "zip"] if codec in ("zlib", "zlib-ng", "libdeflate") else ["frame"]
            for framing in frames:
                for level in levels:
                    for name, raw in cases:
                        raw_path.write_bytes(raw)
                        prefix = [str(binary), "encode", codec, str(level), framing]
                        subprocess.run([*prefix, str(raw_path), str(packet_path), "0", "0"], check=True, capture_output=True)
                        packet = packet_path.read_bytes()
                        assert independent(codec, framing, packet) == raw, (codec, level, framing, name, "independent")
                        subprocess.run([str(binary), "decode", codec, str(level), framing, str(packet_path),
                                        str(out_path), "0", str(len(raw))], check=True, capture_output=True)
                        assert out_path.read_bytes() == raw
                        rows.append({"codec": codec, "level": level, "framing": framing, "case": name,
                                     "raw_bytes": len(raw), "packed_bytes": len(packet),
                                     "raw_sha256": hashlib.sha256(raw).hexdigest(),
                                     "packet_sha256": hashlib.sha256(packet).hexdigest()})
                        second = bytes(byte ^ 0x5a for byte in raw[::-1]) + b'\n{"different-shape":18446744073709551615}\n'
                        second_path.write_bytes(second)
                        reset = subprocess.run([str(binary), "reset-check", codec, str(level), framing,
                                                str(raw_path), str(packet_path), "0", "0", str(second_path)],
                                               check=True, capture_output=True, text=True)
                        assert independent(codec, framing, packet_path.read_bytes()) == second
                        reset_rows.append({"codec": codec, "level": level, "framing": framing,
                                           "case": name, **json.loads(reset.stdout)})
                        if name in ("tiny", "boundary65537"):
                            sample = subprocess.run([str(binary), "reuse-warm", codec, str(level), framing,
                                                     str(raw_path), str(packet_path), "2000000", "0"],
                                                    check=True, capture_output=True, text=True)
                            sample = json.loads(sample.stdout)
                            supported = codec not in ("brotli", "lzma2")
                            assert sample["context"] == ("reused-reset-paid" if supported else "fresh-no-reset-api")
                            for direction in ("encode", "decode"):
                                assert sample[direction + "_ns"] > 0
                                assert sample[direction + "_iterations"] >= 1
                                assert sample[direction + "_ns"] * sample[direction + "_iterations"] >= 1999999
                                if not supported:
                                    assert sample[direction + "_init_ns"] == 0
                            assert packet_path.read_bytes() == packet
                            reuse_samples.append({"codec": codec, "level": level, "framing": framing,
                                                  "case": name, "context": sample["context"]})
                        # All methods/levels must reject truncation, suffixes,
                        # concatenation and mismatched declared output size.
                        for changed in (packet[:-1], packet + b"x", packet + b"\0" * 8, packet + packet):
                            packet_path.write_bytes(changed)
                            result = subprocess.run([str(binary), "decode", codec, str(level), framing,
                                                     str(packet_path), str(out_path), "0", str(len(raw))], capture_output=True)
                            assert result.returncode == 2, (codec, level, framing, name, "consumption", result)
                            rejected += 1
                        packet_path.write_bytes(packet)
                        result = subprocess.run([str(binary), "decode", codec, str(level), framing,
                                                 str(packet_path), str(out_path), "0", str(len(raw) + 1)], capture_output=True)
                        assert result.returncode == 2
                        rejected += 1
                        if framing != "raw":
                            altered = bytearray(packet)
                            offset = {"gzip": -8, "zip": 14}.get(framing,
                                12 if codec == "brotli" else (8 if codec == "lzma2" else -1))
                            altered[offset] ^= 1
                            packet_path.write_bytes(altered)
                            result = subprocess.run([str(binary), "decode", codec, str(level), framing,
                                                     str(packet_path), str(out_path), "0", str(len(raw))], capture_output=True)
                            assert result.returncode == 2, (codec, framing, name, "checksum")
                            rejected += 1
    result = {"schema_version": 1, "status": "passed", "scope": "shared adapter correctness/calibration only; no study screening",
              "success_cases": len(rows), "rejected_cases": rejected, "clocks": clocks, "binary_sha256": hashes,
              "versions": versions, "independent_oracles": {
                  "zlib": zlib.ZLIB_RUNTIME_VERSION, "xz": "Python liblzma",
                  "zstd": subprocess.check_output(["zstd", "--version"], text=True).strip(),
                  "lz4": subprocess.check_output(["lz4", "--version"], text=True).strip(),
                  "brotli": subprocess.check_output(["brotli", "--version"], text=True).strip()}, "rows": rows,
              "reset_identity_cases": len(reset_rows), "reset_rows": reset_rows,
              "reuse_sample_contract_cases": len(reuse_samples), "reuse_samples": reuse_samples}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "reset_rows", "reuse_samples")}, indent=2))


if __name__ == "__main__":
    main()
