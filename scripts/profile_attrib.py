#!/usr/bin/env python3
"""Attribute samply samples to deflate-core functions, inlining included.

Everything in deflate-core inlines into `decode_huff_block`, so a
function-level profile says only "99% decode_huff_block". This resolves each
sampled address with `atos -i`, which reports the whole inline chain, and
counts a sample once for every core function on that chain: inclusive time.
Names are FILE::FUNCTION, since atos prints inlined frames unqualified.

usage: profile_attrib.py PROFILE.json.gz BINARY  (macOS: needs atos)
"""
import collections
import gzip
import json
import re
import subprocess
import sys

CORE = (
    "huffman.rs", "bitstream.rs", "lz77.rs", "block.rs", "inflate.rs",
    "matcher.rs", "matcher_flat.rs", "tokens.rs", "compress.rs", "encode_dynamic.rs",
    "encode_fixed.rs", "huffman_build.rs", "bitwriter.rs", "deflate.rs",
)
BASE = 0x100000000  # Mach-O __TEXT load address; samply addresses are relative


def col(table, key):
    if "schema" in table:
        return [row[table["schema"][key]] for row in table["data"]]
    return table[key]


def main(profile, binary):
    p = json.load(gzip.open(profile))
    exe = binary.rsplit("/", 1)[-1]
    by_addr = collections.Counter()
    for t in p["threads"]:
        sframe = col(t["stackTable"], "frame")
        faddr = col(t["frameTable"], "address")
        ffunc = col(t["frameTable"], "func")
        fres = t["funcTable"]["resource"]
        rlib = t["resourceTable"]["lib"]
        for sk in col(t["samples"], "stack"):
            if sk is None:
                continue
            f = sframe[sk]
            r = fres[ffunc[f]]
            lib = p["libs"][rlib[r]]["name"] if r is not None and r >= 0 else "?"
            by_addr[(lib, faddr[f])] += 1

    total = sum(by_addr.values())
    inclusive = collections.Counter()
    outside = collections.Counter()
    for (lib, addr), n in by_addr.items():
        if lib != exe:
            outside[lib] += n
            continue
        chain = subprocess.run(
            ["atos", "-i", "-o", binary, "-l", hex(BASE), hex(BASE + addr)],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        core = set()
        for line in chain:
            m = re.search(r"\((\w+\.rs):\d+\)", line)
            if m and m.group(1) in CORE:
                name = re.sub(r"::h[0-9a-f]{16}", "", line.split(" (in")[0])
                core.add(m.group(1)[:-3] + "::" + name.split("::")[-1])
        for fn in core:
            inclusive[fn] += n
        if not core:
            outside[f"{exe} (outside deflate-core)"] += n

    pct = lambda n: round(100 * n / total, 1)
    return {
        "samples": total,
        "inclusive_pct": {k: pct(v) for k, v in inclusive.most_common() if pct(v) >= 0.5},
        "outside_core_pct": {k: pct(v) for k, v in outside.most_common() if pct(v) >= 0.5},
    }


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:3])))
