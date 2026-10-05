#!/usr/bin/env python3
"""Deterministic decode-throughput corpus (scripts/perf_report.sh).

Each payload is 8 MiB and seeded, so every run measures the same bytes.
NAME.raw is the expected output; NAME.KIND.deflate is a raw RFC 1951 stream
from zlib with dynamic (`dyn`), fixed-only (`fixed`) or stored-only (`stored`)
blocks. Random data gets only the stored form: zlib emits stored blocks for
it whatever strategy is asked for, so a "dyn" file would mislabel itself.
"""
import os
import random
import sys
import zlib

N = 8 << 20


def raw(data, level, strategy=zlib.Z_DEFAULT_STRATEGY):
    c = zlib.compressobj(level, zlib.DEFLATED, -15, 9, strategy)
    return c.compress(data) + c.flush()


def main(out):
    os.makedirs(out, exist_ok=True)
    rng = random.Random(1951)
    words = [
        "".join(rng.choice("etaoinshrdlucmfwyp") for _ in range(rng.randint(2, 9)))
        for _ in range(2000)
    ]
    payloads = {
        "text": " ".join(rng.choice(words) for _ in range(N // 5)).encode()[:N],
        "random": rng.randbytes(N),
        "repetitive": (b"abcabcabd" * (N // 9 + 1))[:N],
        "zeros": bytes(N),
    }
    for name, data in payloads.items():
        with open(f"{out}/{name}.raw", "wb") as f:
            f.write(data)
        kinds = {"stored": raw(data, 0)}
        if name != "random":
            kinds["dyn"] = raw(data, 6)
            kinds["fixed"] = raw(data, 6, zlib.Z_FIXED)
        for kind, stream in kinds.items():
            with open(f"{out}/{name}.{kind}.deflate", "wb") as f:
                f.write(stream)


if __name__ == "__main__":
    main(sys.argv[1])
