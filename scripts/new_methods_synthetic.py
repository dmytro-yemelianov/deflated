#!/usr/bin/env python3
"""Disjoint regimes 13--18, plus explicitly shared tiny/boundary witnesses."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import random

from encoder_corpus import ROOT, digest, write_json
from search_corpus import seed_for, validate
from search_extended_corpus import collision_keys, payload as extension_payload

REGIMES = {"train": [13, 14], "validation": [15, 16], "test": [17, 18]}
FAMILIES = ("hash_trigram", "hash_fourbyte", "tag24_fourth", "cache_eviction",
            "ring_owner", "lazy_pending", "cost_sensitive", "numeric_spellings",
            "escaped_raw", "schema_drift", "unique_keys", "chunk_lexemes")
STRUCTURED = {"numeric_spellings", "escaped_raw", "schema_drift", "unique_keys", "chunk_lexemes"}
HELPERS = ("scripts/search_corpus.py", "scripts/search_extended_corpus.py")


def repeat(pattern, n):
    return (pattern * ((n + len(pattern) - 1) // len(pattern)))[:n]


def payload(family, regime, seed, n=262144):
    rng = random.Random(seed)
    evidence = {"regime": regime, "raw_byte_domain": True}
    if family in ("hash_trigram", "hash_fourbyte", "cache_eviction"):
        kind = "fourbyte" if family == "hash_fourbyte" else "trigram"
        count = 33 + regime if family == "cache_eviction" else 2 * regime + 5
        keys, proof = collision_keys(kind, 15, count, rng)
        rows = [key + rng.randbytes(27 + regime) for key in keys]
        sequence = [rng.choice(rows) for _ in range(n // len(rows[0]) + 1)]
        if family == "cache_eviction":
            sequence = [rows[(i % (count + 1)) % count] for i in range(len(sequence))]
        return b"".join(sequence)[:n], {**evidence, **proof, "rows_exceed_maximum_eight_ways": count > 8}
    if family == "tag24_fourth":
        prefix = rng.randbytes(3)
        rows = [prefix + bytes([i]) + rng.randbytes(20 + regime) for i in range(2 * regime + 5)]
        raw = b"".join(rng.choice(rows) for _ in range(n // len(rows[0]) + 1))[:n]
        return raw, {**evidence, "shared_trigram_hex": prefix.hex(), "distinct_fourth_bytes": len(rows),
                     "required_match_length_three": True}
    if family == "ring_owner":
        raw = bytearray(rng.randbytes(n))
        injections = []
        for position in range(32768 + regime, n - 258, 4093 + regime):
            distance = (32767, 32768, 32769)[len(injections) % 3]
            raw[position:position + 258] = raw[position - distance:position - distance + 258]
            injections.append([position, distance, 258])
        return bytes(raw), {**evidence, "copy_injections": injections, "ring_wraps": n // 32768}
    if family == "lazy_pending":
        motif = rng.randbytes(257 + 2 * regime)
        raw = bytearray(repeat(motif, n))
        for position in range(255 + regime, n - 4, 1021 + regime):
            raw[position] ^= 1
            raw[position + 1:position + 4] = motif[:3]
        return bytes(raw), {**evidence, "period": len(motif), "pending_prefix_injections": True,
                           "scope": "stresses lookahead; exact pending-state witnesses live in matcher correctness tests"}
    if family == "cost_sensitive":
        bodies, proof = extension_payload(family, regime, seed, n)
        return bodies[0], {**evidence, **proof}
    if family == "numeric_spellings":
        values = [b"0", b"-0", b"00", b"0123", b"1.0", b"1e3", b"1E+03", b"-7", b"+2",
                  b"18446744073709551615", b"18446744073709551616", b"9223372036854775808"]
        raw = bytearray()
        index = 0
        while len(raw) < n:
            value = values[index % len(values)]
            raw.extend(b'{"counter":' + str((index * regime) % (1 << 64)).encode() +
                       b',"spelling":' + value + b',"quoted":"' + value + b'"}\n')
            index += 1
        return bytes(raw[:n]), {**evidence, "spellings": [v.decode() for v in values], "may_be_non_json": True}
    if family == "escaped_raw":
        rows = [b'{"dupe":1, "dupe":2,"quote":"a\\\"b\\\\c","raw":"\xff\xfe"}\r\n',
                b' { "ws" : "\\u0061", "same" : "a", "ctl":"\x00\x80" }\n',
                b'{"dangling":"x\\', b'not json: \xff value=0007\t\r\n']
        raw = b"".join(rng.choice(rows) for _ in range(n // min(map(len, rows)) + 1))[:n]
        return raw, {**evidence, "invalid_utf8": True, "escape_spellings_and_duplicate_keys": True}
    if family in ("schema_drift", "unique_keys"):
        raw = bytearray()
        index = 0
        segment_width = 4093 + regime * 13
        while len(raw) < n:
            schema = len(raw) // segment_width
            key = (f"unique_{regime}_{index}_{rng.getrandbits(32):08x}" if family == "unique_keys"
                   else f"schema_{regime}_{schema}_field_{index % 9}").encode()
            raw.extend(b'{"' + key + b'":' + str(index * regime).encode() + b',"payload":"' +
                       rng.randbytes(12).hex().encode() + b'"}\n')
            index += 1
        return bytes(raw[:n]), {**evidence, "record_count": index, "schema_segment_bytes": segment_width,
                               "keys_never_repeat": family == "unique_keys"}
    if family == "chunk_lexemes":
        raw = bytearray(repeat(b'{"k":"value","counter":123456789}\n', n))
        cuts = []
        for cut in range(65536, n + 1, 65536):
            spelling = b'"escaped\\\"quoted_' + str(regime).encode() + b'":18446744073709551615'
            start = cut - (3 + regime % 7)
            width = min(len(spelling), n - start)
            raw[start:start + width] = spelling[:width]
            cuts.append([cut, start, width])
        return bytes(raw), {**evidence, "lexemes_cross_chunk_cuts": cuts, "cuts_log2": [16, 18]}
    if family == "long_history":
        motif = rng.randbytes(262401 + regime)
        return repeat(motif, n), {**evidence, "period": len(motif), "copies_beyond_deflate_window": True}
    if family == "long_structured":
        raw = bytearray()
        index = 0
        while len(raw) < n:
            raw.extend(b'{"sequence":' + str(index * regime).encode() + b',"group":' +
                       str(index // 4096).encode() + b',"status":"ok","escaped":"x\\\"y"}\n')
            index += 1
        raw = raw[:n]
        for cut in range(65536, n, 65536):
            spelling = b'"long_boundary":18446744073709551616'
            raw[cut - 7:cut - 7 + len(spelling)] = spelling
        return bytes(raw), {**evidence, "record_count": index, "chunk_cuts_log2": [16, 18]}
    raise ValueError("unknown family: " + family)


def recipes():
    for partition, regimes in REGIMES.items():
        for family in FAMILIES:
            for regime in regimes:
                yield partition, family, regime, 262144, "synthetic"
        for family in ("long_history", "long_structured"):
            yield partition, family, regimes[0], 8388608, "long-stress"
    for length in (0, 1, 2, 3, 4, 15, 16, 17, 257, 258, 259, 32767, 32768, 32769,
                   65535, 65536, 65537, 262143, 262144, 262145):
        yield "stress", "shared_boundary", length, length, "tiny" if length <= 259 else "boundary"
    yield "stress", "shared_raw_spellings", 0, 0, "tiny"


def build(out, check=False):
    manifest = out / "manifest.json"
    if not check and out.exists():
        raise ValueError("synthetics require a fresh output directory; use --check")
    cases, bodies = [], {}
    for partition, family, regime, size, scope in recipes():
        params = {"version": 1, "regime": regime, "bytes": size}
        seed = seed_for(202610071, partition, "new-methods-" + family, params)
        if family == "shared_boundary":
            raw, evidence = random.Random(seed).randbytes(size), {"length": size, "shared_correctness_scope": True}
        elif family == "shared_raw_spellings":
            raw = b' {"dup":1,"dup":2,"esc":"\\u0061","raw":"\xff","zero":-0,"lead":001}\r\n'
            evidence = {"shared_correctness_scope": True, "arbitrary_byte_domain": True}
        else:
            raw, evidence = payload(family, regime, seed, size)
        path = f"{partition}/{family}-{regime}.raw"
        structured = family in STRUCTURED or family == "long_structured" or partition == "stress"
        cases.append({"path": path, "partition": partition, "family": family, "scope": scope,
                      "tracks": ["A", "B"] if structured else ["A"], "params": params, "seed": seed,
                      "regime": f"new-methods:{family}:{regime}", "pair_id": f"{partition}:{family}:{regime}",
                      "bytes": len(raw), "sha256": digest(raw), "construction": evidence})
        bodies[path] = raw
    meta = {"schema_version": 1, "study": "new-methods-v1", "generator_sha256": digest(Path(__file__).read_bytes()),
            "helper_sha256": {p: digest((ROOT / p).read_bytes()) for p in HELPERS}, "partition_regimes": REGIMES,
            "test_policy": "construct/regenerate/hash only before G5 freeze; no held codec measurement/features",
            "shared_policy": "stress partition is correctness/tiny/boundary only, never independent holdout",
            "long_policy": "two 8MiB source groups per split; separate scores, not primary aggregates", "cases": cases}
    if check:
        if json.loads(manifest.read_text()) != meta:
            raise ValueError("generator/provenance changed")
    else:
        out.mkdir(parents=True)
        for name, raw in bodies.items():
            file = out / name
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(raw)
        write_json(manifest, meta)
    validate(out, meta)
    for name, raw in bodies.items():
        if (out / name).read_bytes() != raw:
            raise ValueError("synthetic regeneration differs")
    print(json.dumps({"manifest_sha256": digest(manifest.read_bytes()), "cases": len(cases),
                      "partition_counts": dict(collections.Counter(c["partition"] for c in cases)),
                      "scope_counts": dict(collections.Counter(c["scope"] for c in cases))}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/new-methods/synthetic-v1")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    build(args.out, args.check)
