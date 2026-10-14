#!/usr/bin/env python3
"""Resolve inline PCs, retaining qualified core symbols even at std/mod.rs:0.

Inclusive categories overlap. Unknown inline ancestry is left unknown; a PC at
an instruction is not proof that the instruction caused its sampled cost.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
from profile_attrib import col

CORE = {"block", "lz77", "bitstream", "huffman", "inflate", "crc32", "gzip", "decode_table"}


def attribute(path, binary):
    profile = json.loads(gzip.decompress(path.read_bytes()))
    counts = Counter()
    for thread in profile["threads"]:
        sframe = col(thread["stackTable"], "frame")
        faddr = col(thread["frameTable"], "address")
        ffunc = col(thread["frameTable"], "func")
        fres = thread["funcTable"]["resource"]
        rlib = thread["resourceTable"]["lib"]
        for stack in col(thread["samples"], "stack"):
            if stack is None:
                continue
            frame = sframe[stack]
            resource = fres[ffunc[frame]]
            library = profile["libs"][rlib[resource]]["name"] if resource is not None and resource >= 0 else "?"
            counts[library, faddr[frame]] += 1
    inclusive = Counter()
    external = Counter()
    pcs = []
    for (library, address), count in counts.most_common():
        if library != binary.name:
            external[library] += count
            continue
        chain = subprocess.check_output(["atos", "-i", "-o", str(binary), "-l", "0x100000000", hex(0x100000000 + address)], text=True).splitlines()
        categories = set()
        for line in chain:
            source = re.search(r"\((\w+)\.rs:\d+\)", line)
            if source and source[1] in CORE:
                symbol = re.sub(r"::h[0-9a-f]{16}", "", line.split(" (in")[0])
                # Ignore path separators inside generic type arguments.
                # Trait-qualified methods start with <...>::method instead.
                head = symbol.rsplit(">::", 1)[-1] if symbol.startswith("<") else symbol
                function = head.split("<", 1)[0].rsplit("::", 1)[-1]
                categories.add(source[1] + "::" + function)
            # Rust may attach std/mod.rs:0 to an instruction that is physically
            # inside a core function and omit its inline ancestry. Do not label
            # that PC outside the core merely because the line table is sparse.
            qualified = re.match(r"deflate_core::(\w+)::(\w+)::h[0-9a-f]+", line)
            if qualified:
                categories.add(qualified[1] + "::" + qualified[2])
        for category in categories:
            inclusive[category] += count
        if not categories:
            external["application PCs without resolved core ancestry"] += count
        pcs.append({"relative_address": hex(address), "samples": count, "inline_chain": chain, "categories": sorted(categories)})
    total = sum(counts.values())
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "samples": total,
            "inclusive_pct": {k: round(100*v/total, 2) for k,v in inclusive.most_common()},
            "outside_pct": {k: round(100*v/total, 2) for k,v in external.most_common()}, "pcs": pcs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("profiles", type=Path, nargs="+")
    args = parser.parse_args()
    report = {"binary": str(args.binary), "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              "note": "Separate line-tables-only build. Inclusive categories overlap; sampled PCs are not hardware stall counters.",
              "profiles": [attribute(p, args.binary) for p in args.profiles]}
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
