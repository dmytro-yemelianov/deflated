#!/usr/bin/env python3
"""Seeded autotuning workloads; production benchmarks remain unchanged.

python3 scripts/search_corpus.py --profile smoke
python3 scripts/search_corpus.py --profile smoke --check
"""
import argparse
import collections
import hashlib
import json
import math
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = 1
PARTITIONS = ("train", "validation", "test")
HASH_BITS = 15
HASH_MULTIPLIER = 0x1E35A7BD


def seed_for(master, partition, family, params):
    key = json.dumps([VERSION, master, partition, family, params], sort_keys=True)
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little")


def repeat(pattern, n):
    return (pattern * ((n + len(pattern) - 1) // len(pattern)))[:n]


def payload(family, params, seed, n):
    rng = random.Random(seed)
    if family == "alphabet":
        alphabet = rng.sample(range(256), params["symbols"])
        return bytes(rng.choice(alphabet) for _ in range(n))
    if family == "periodic":
        out = bytearray(repeat(rng.randbytes(params["period"]), n))
        for i in range(params["mutation_stride"] - 1, n, params["mutation_stride"]):
            out[i] ^= 1
        return bytes(out)
    if family == "distance":
        # Inject a 258-byte copy at an exact distance, including 32769 (illegal
        # as one DEFLATE reference, but legal input with shorter alternatives).
        distance = params["distance"]
        out = bytearray(rng.randbytes(max(n, distance * 2 + 258)))
        out[distance:distance + 258] = out[:258]
        return bytes(out)
    if family == "hash_collision":
        # Invert the current four-byte multiply hash: every aligned key maps
        # to one chosen 15-bit bucket. Other alignments need not collide.
        inverse = pow(HASH_MULTIPLIER, -1, 1 << 32)
        bucket = rng.randrange(1 << HASH_BITS)
        lows = rng.sample(range(1 << (32 - HASH_BITS)), params["keys"])
        keys = [(((bucket << (32 - HASH_BITS)) | low) * inverse & 0xFFFFFFFF)
                .to_bytes(4, "little") for low in lows]
        return b"".join(rng.choice(keys) for _ in range((n + 3) // 4))[:n]
    if family == "prefix_collision":
        prefix = rng.randbytes(3)
        words = [prefix + rng.randbytes(5) for _ in range(params["keys"])]
        return b"".join(rng.choice(words) for _ in range((n + 7) // 8))[:n]
    if family == "records":
        keys = [rng.randbytes(6).hex().encode() for _ in range(params["keys"])]
        rows = []
        size = 0
        while size < n:
            row = (b'{"key":"' + rng.choice(keys) + b'","value":' +
                   str(rng.randrange(params["values"])).encode() + b'}\n')
            rows.append(row)
            size += len(row)
        return b"".join(rows)[:n]
    if family == "mixed":
        segment = params["segment_bytes"]
        n = max(n, segment * 3)
        out = bytearray()
        modes = ["random", "run", "records"]
        rng.shuffle(modes)
        while len(out) < n:
            mode = modes[(len(out) // segment) % len(modes)]
            if mode == "random":
                out.extend(rng.randbytes(segment))
            elif mode == "run":
                out.extend(repeat(rng.randbytes(7), segment))
            else:
                out.extend(payload("records", {"keys": 16, "values": 32},
                                   rng.getrandbits(64), segment))
        return bytes(out[:n])
    if family == "sample_trap":
        # Deliberately make the eight current classifier samples disagree
        # with most of the input. This is an adversarial classifier workload,
        # not a claim that flat frequencies imply incompressibility.
        n = max(n, 8192)
        flat = params["flat_samples"]
        out = bytearray(repeat(rng.randbytes(3), n) if flat else rng.randbytes(n))
        step = (n - 512) // 7
        motif = rng.randbytes(params["period"])
        for sample in range(8):
            patch = (repeat(bytes(rng.sample(range(256), 256)), 512) if flat
                     else repeat(motif, 512))
            out[sample * step:sample * step + 512] = patch
        return bytes(out)
    if family == "boundary":
        return rng.randbytes(params["length"])
    if family == "run_boundary":
        return bytes([params["byte"]]) * params["length"]
    raise ValueError(f"unknown family: {family}")


def recipes():
    domains = {
        "alphabet": ("symbols", [(4, 16, 128), (8, 64), (2, 32, 256)]),
        "periodic": ("period", [(1, 3, 16, 64), (2, 9, 257), (7, 17, 258)]),
        "distance": ("distance", [(1024, 8191, 16384), (8192, 32767), (32768, 32769)]),
        "hash_collision": ("keys", [(32, 128), (64,), (256,)]),
        "prefix_collision": ("keys", [(32, 128), (64,), (256,)]),
        "records": ("keys", [(8, 64), (16,), (128,)]),
        "mixed": ("segment_bytes", [(1024, 16384), (4096,), (32768,)]),
    }
    for index, partition in enumerate(PARTITIONS):
        for family, (axis, splits) in domains.items():
            for value in splits[index]:
                params = {axis: value}
                if family == "periodic":
                    params["mutation_stride"] = [4093, 2053, 1031][index]
                if family == "records":
                    params["values"] = [32, 128, 512][index]
                yield partition, family, params
        for flat in [False, True]:
            yield partition, "sample_trap", {"flat_samples": flat,
                                            "period": [3, 7, 13][index]}
    lengths = [0, 1, 2, 3, 4, 15, 16, 17, 257, 258, 259,
               32767, 32768, 32769, 65535, 65536, 65537]
    for length in lengths:
        yield "stress", "boundary", {"length": length}
    for length in [257, 258, 259, 32768, 32769, 65535, 65536, 65537]:
        yield "stress", "run_boundary", {"length": length, "byte": 0}


def features(data):
    # Cheap, explicit features for the first surrogate spike; no learned
    # embedding or target-derived feature is smuggled into the corpus.
    sample = data[::max(1, len(data) // 4096)][:4096]
    counts = collections.Counter(sample)
    size = len(sample)
    return {"log2_bytes": math.log2(max(1, len(data))),
            "sample_entropy": -sum((c / size) * math.log2(c / size) for c in counts.values()),
            "distinct_bytes": len(counts),
            "adjacent_equal_fraction": (sum(a == b for a, b in zip(sample, sample[1:])) /
                                        max(1, size - 1))}


def manifest(profile, master):
    n = {"smoke": 32768, "full": 1 << 20}[profile]
    cases = []
    for index, (partition, family, params) in enumerate(recipes()):
        seed = seed_for(master, partition, family, params)
        data = payload(family, params, seed, n)
        name = f"{index:03d}-{family}.raw"
        cases.append(({"path": f"{partition}/{name}", "partition": partition,
                       "family": family, "params": params, "seed": seed,
                       "regime": family + ":" + json.dumps(params, sort_keys=True),
                       "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                       "features": features(data)}, data))
    meta = {"schema_version": VERSION, "profile": profile, "master_seed": master,
            "generator_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
            "test_policy": "reserved; search_poc does not measure the test partition",
            "cases": [case for case, _ in cases]}
    return meta, cases


def validate(root, meta):
    by_hash = {}
    by_regime = {}
    paths = set()
    for case in meta["cases"]:
        relative = pathlib.PurePosixPath(case["path"])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
            raise ValueError("invalid corpus path")
        if relative.parts[0] != case["partition"] or case["path"] in paths:
            raise ValueError("duplicate path or partition mismatch")
        paths.add(case["path"])
        data = (root / relative).read_bytes()
        if len(data) != case["bytes"] or hashlib.sha256(data).hexdigest() != case["sha256"]:
            raise ValueError(f"corpus hash/size mismatch: {relative}")
        if case["partition"] not in PARTITIONS + ("stress",):
            raise ValueError("unknown partition")
        if case["partition"] == "stress":
            continue
        for registry, key in [(by_hash, case["sha256"]), (by_regime, case["regime"])]:
            previous = registry.setdefault(key, case["partition"])
            if previous != case["partition"]:
                raise ValueError("data or parameter regime overlaps partitions")
    actual = {str(p.relative_to(root)) for p in root.glob("*/*.raw")}
    if actual != paths:
        raise ValueError("corpus membership differs from manifest")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--seed", type=int, default=195107)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    out = args.out or ROOT / "target/search" / ("corpus-" + args.profile)
    expected, cases = manifest(args.profile, args.seed)
    path = out / "manifest.json"
    if path.exists():
        if json.loads(path.read_text()) != expected:
            raise SystemExit("existing manifest differs; use a new --out directory")
    elif args.check:
        raise SystemExit("generate the corpus before checking it")
    else:
        if out.exists() and any(out.iterdir()):
            raise SystemExit("--out must be empty for a new corpus")
        out.mkdir(parents=True, exist_ok=True)
        for case, data in cases:
            file = out / case["path"]
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(data)
        path.write_text(json.dumps(expected, indent=2) + "\n")
    validate(out, expected)
    for case, data in cases:
        if (out / case["path"]).read_bytes() != data:
            raise SystemExit("regeneration differs")
    print(json.dumps({"manifest": str(path), "cases": len(cases),
                      "partitions": dict(collections.Counter(c["partition"] for c, _ in cases)),
                      "bytes": sum(c["bytes"] for c, _ in cases)}))


if __name__ == "__main__":
    main()
