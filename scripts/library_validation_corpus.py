#!/usr/bin/env python3
"""Deterministic broader decoder diagnostics, not a representative real corpus.

Freeze the candidate before running this generator; do not tune on its results
while calling them independent validation. These synthetic families exercise
literal-heavy input, structured records, overlap and 32 KiB window boundaries.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random


def generate():
    rng = random.Random(0x20261014)
    logs = [json.dumps({"id": i, "route": f"/api/{rng.randrange(200)}",
                        "status": rng.choice([200, 200, 200, 404, 500]),
                        "duration": rng.randrange(100000), "message": "request completed"},
                       separators=(",", ":")).encode() for i in range(3500)]
    yield "json-records", b"\n".join(logs), "synthetic"
    csv = b"timestamp,sensor,value,quality\n" + b"".join(
        f"{1700000000 + i},{rng.randrange(50)},{rng.randrange(100000) / 100:.2f},{rng.randrange(4)}\n".encode()
        for i in range(13000))
    yield "numeric-csv", csv, "synthetic"
    words = ["розпакування", "дані", "перевірка", "γειά", "世界", "données", "buffer", "🗂️"]
    yield "utf8-text", " ".join(f"{rng.choice(words)}:{rng.randrange(2000)}" for _ in range(20000)).encode(), "synthetic"
    history = rng.randbytes(32768)
    yield "window-boundaries", b"".join(history[:n] + history[-n:] for n in [1, 7, 31, 257, 4095, 16384, 32767, 32768]), "synthetic"
    yield "literal-biased", bytes(rng.randrange(32, 128) for _ in range(262144)), "synthetic"
    yield "alternating-blocks", b"".join(rng.randbytes(16384) + b"ab\x00cd" * 3277 for _ in range(8)), "synthetic"
    yield "tiny-random-31", rng.randbytes(31), "tiny"
    yield "tiny-structured-257", (b'{"id":17,"ok":true}\n' * 20)[:257], "tiny"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    cases = []
    for name, raw, scope in generate():
        path = args.out / (name + ".raw")
        path.write_bytes(raw)
        cases.append({"name": name, "path": path.name, "scope": scope,
                      "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    manifest = {"schema_version": 1, "scope": "synthetic validation diagnostic; no real-corpus claim",
                "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "cases": cases}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"generated {len(cases)} validation cases")


if __name__ == "__main__":
    main()
