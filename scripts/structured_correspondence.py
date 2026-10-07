#!/usr/bin/env python3
"""Compare the Rust DSC1 prototype with the independent wire oracle.

Shared correctness witnesses do not constitute held performance data.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess
import tempfile

from structured_reference import decode

ROOT = Path(__file__).resolve().parents[1]


def witnesses():
    rng = random.Random(0x44534331)
    raw = b'{ "k":-0,"k":0007,"x":1.0,"y":1e3,"n":18446744073709551616,"raw":"\xff","q":"\\u0061\\\"" }\n'
    repeated = b"".join(b'{"timestamp":' + str(1000000000 + i).encode() +
                        b',"message":"quote\\\" and escape\\u0061","timestamp":0}\n'
                        for i in range(1000))
    return [("empty", b""), ("one", b"x"), ("byte-domain", bytes(range(256))),
            ("lexical", raw), ("repeated-keys-numbers", repeated),
            ("long-digit-overflow", b"9" * 5000),
            ("unterminated-quote", b'"123\\'),
            ("absolute-extrema", b"[0,18446744073709551615,9223372036854775807,9223372036854775808]"),
            ("chunk65535", rng.randbytes(65535)), ("chunk65536", b"z" * 65536),
            ("chunk65537", (b'\\"-0,1e3,\xff' * 8193)[:65537]),
            ("chunk262143", rng.randbytes(262143)), ("chunk262144", (repeated * 4)[:262144]),
            ("chunk262145", (b'"ab\\\"cd":123,\n' * 20000)[:262145])]


def run(binary, args):
    return subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/structured-tool")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    rows = []
    vectors = json.loads((ROOT / "tests/structured/vectors.json").read_text())["vectors"]
    with tempfile.TemporaryDirectory(prefix="dsc1-correspondence-") as temporary:
        directory = Path(temporary)
        packet_path, raw_path, decoded_path = (directory / n for n in ("packet", "raw", "decoded"))
        for vector in vectors:
            packet_path.write_bytes(bytes.fromhex(vector["packet_hex"]))
            result = run(args.binary, ["decode", packet_path, decoded_path, vector["limit"]])
            if "error" in vector:
                assert result.returncode == 2 and result.stderr.strip() == vector["error"], (vector["name"], result)
            else:
                assert result.returncode == 0, (vector["name"], result.stderr)
                assert decoded_path.read_bytes() == bytes.fromhex(vector["raw_hex"]), vector["name"]
        for name, raw in witnesses():
            raw_path.write_bytes(raw)
            for log2, dictionary, numbers in itertools.product((16, 18), ("off", "keys", "all-quoted"), ("off", "checked-delta")):
                options = [log2, dictionary, numbers]
                result = run(args.binary, ["encode", raw_path, packet_path, *options])
                assert result.returncode == 0, (name, options, result.stderr)
                packet = packet_path.read_bytes()
                assert decode(packet) == raw, (name, options, "reference")
                result = run(args.binary, ["decode", packet_path, decoded_path, len(raw)])
                assert result.returncode == 0 and decoded_path.read_bytes() == raw, (name, options, result.stderr)
                result = run(args.binary, ["plain", raw_path, packet_path, *options])
                assert result.returncode == 0, result.stderr
                plain = packet_path.read_bytes()
                assert decode(plain) == raw
                assert len(packet) <= len(plain), (name, options, "selection")
                rows.append({"case": name, "settings": options, "raw_bytes": len(raw),
                             "raw_sha256": hashlib.sha256(raw).hexdigest(),
                             "packed_bytes": len(packet), "plain_bytes": len(plain),
                             "packet_sha256": hashlib.sha256(packet).hexdigest()})
    receipt = {"schema_version": 1, "status": "passed", "scope": "finite shared correctness; not holdout performance or model proof",
               "normative_vectors": len(vectors), "encoded_cases": len(rows),
               "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
               "oracle_zlib_version": __import__("zlib").ZLIB_RUNTIME_VERSION, "rows": rows}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
