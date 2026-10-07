#!/usr/bin/env python3
"""Seeded cost, collision, drift, sampling and paired-transform extensions."""
import argparse
import collections
import hashlib
import json
import pathlib
import random

from search_corpus import ROOT, features, seed_for, validate
from search_poc import sha


def collision_keys(kind, bits, count, rng):
    multiplier, width, endian = {
        'trigram': (0x9e3779b1, 3, 'big'),
        'fourbyte': (0x1e35a7bd, 4, 'little'),
        'cost_trigram': (0x1e35a7bd, 3, 'little')}[kind]
    bucket = rng.randrange(1 << bits)
    inverse = pow(multiplier, -1, 1 << 32)
    keys = []
    for low in range(1 << (32 - bits)):
        value = ((bucket << (32 - bits) | low) * inverse) & 0xffffffff
        if value < 1 << (width * 8):
            keys.append(value.to_bytes(width, endian))
            if len(keys) == count:
                break
    if len(keys) != count or any(((int.from_bytes(k, endian) * multiplier) & 0xffffffff) >> (32 - bits) != bucket for k in keys):
        raise ValueError('candidate-hash collision construction failed')
    return keys, {'kind': kind, 'hash_bits': bits, 'bucket': bucket, 'key_count': count,
                  'keys_sha256': hashlib.sha256(b''.join(keys)).hexdigest(), 'scope': 'aligned keys only; intervening suffix/unaligned prefixes need not collide'}


def payload(family, parameter, seed, n=262144):
    rng = random.Random(seed)
    evidence = {}
    if family == 'cost_sensitive':
        raw = bytearray(rng.randbytes(n))
        lengths = [3, 4, 5, 10, 11, 12, 31, 32, 33, 63, 64, 127, 128, 129, 255, 256, 258]
        distances = [1, 4, 16, 32, 33, 64, 65, 256, 257, 1024, 4096, 32767, 32768, 32769]
        injections = []
        for index, pos in enumerate(range(33000 + parameter, n - 258, 1021 + parameter)):
            length, distance = lengths[(index + parameter) % len(lengths)], distances[(index * 3 + parameter) % len(distances)]
            for k in range(length):
                raw[pos + k] = raw[pos + k - distance]
            injections.append([pos, length, distance])
        evidence['injections'] = injections
    elif family.startswith('collision_'):
        kind = family.removeprefix('collision_')
        keys, evidence = collision_keys(kind, 12 + parameter, 16 + parameter * 3, rng)
        # Divergent tails exercise expensive collision chains and short matches.
        rows = [k + rng.randbytes(9 + parameter) for k in keys]
        raw = bytearray()
        while len(raw) < n:
            raw.extend(rng.choice(rows))
        raw = raw[:n]
    elif family in ('change_points', 'drift'):
        raw = bytearray()
        changes = []
        widths = [511, 512, 513, 4095, 4096, 4097, 16383, 16384, 16385, 32767, 32768, 32769, 65535, 65536, 65537]
        while len(raw) < n:
            width = widths[(len(changes) + parameter) % len(widths)]
            kind = (len(changes) + parameter) % 3
            changes.append([len(raw), width, kind])
            if family == 'drift':
                symbols = min(256, 4 + len(changes) * (parameter + 1))
                segment = bytes(rng.randrange(symbols) for _ in range(width))
            elif kind == 0:
                segment = rng.randbytes(width)
            else:
                template = rng.randbytes(7 + parameter * 5) if kind == 1 else b'{key:value,number:12345}\n'
                segment = (template * (width // len(template) + 1))[:width]
            raw.extend(segment)
        raw, evidence = raw[:n], {'regime_changes': changes}
    elif family == 'feature_sampling_trap':
        if parameter % 2:
            template = rng.randbytes(31 + parameter)
            raw = bytearray((template * (n // len(template) + 1))[:n])
        else:
            raw = bytearray(rng.randbytes(n))
        stride = max(len(raw) // 4096, 1)
        positions = [j * stride + j * 0x9e3779b1 % stride for j in range(min(4096, len(raw)))]
        for pos in positions:
            raw[pos] = rng.randrange(256) if parameter % 2 else 0
        evidence = {'sample_positions': len(positions), 'poison': 'flat samples / periodic background' if parameter % 2 else 'zero samples / random background'}
    elif family == 'paired_transforms':
        template = rng.randbytes(257 + parameter * 2)
        raw = bytearray((template * (n // (2 * len(template)) + 1))[:n // 2])
        for pos in range(1000 + parameter, len(raw), 4093 + parameter):
            raw[pos] ^= 1
        transform = ['prepend', 'append', 'concatenate', 'duplicate', 'mutate', 'change_point', 'prepend'][parameter]
        extra = rng.randbytes(511 + parameter)
        if transform == 'prepend':
            changed = extra + raw
        elif transform == 'append':
            changed = raw + extra
        elif transform == 'concatenate':
            changed = raw + rng.randbytes(len(raw))
        elif transform == 'duplicate':
            changed = raw + raw
        else:
            changed = bytearray(raw)
            if transform == 'mutate':
                for pos in range(parameter, len(changed), 67):
                    changed[pos] ^= rng.randrange(1, 256)
            else:
                changed[len(changed) // 2:] = rng.randbytes(len(changed) - len(changed) // 2)
        evidence = {'transform': transform, 'window_wraps_base': len(raw) // 32768,
                    'base_sha256': hashlib.sha256(raw).hexdigest()}
        return [bytes(raw), bytes(changed)], evidence
    else:
        raise ValueError('unsupported extension')
    return [bytes(raw)], evidence


def build(out):
    source_hash = sha(pathlib.Path(__file__))
    cases, data = [], {}
    families = ['cost_sensitive', 'collision_trigram', 'collision_fourbyte', 'collision_cost_trigram',
                'change_points', 'drift', 'feature_sampling_trap', 'paired_transforms']
    for partition, parameters in [('train', [0, 2, 4]), ('validation', [1, 3]), ('test', [5, 6])]:
        for family in families:
            for parameter in parameters:
                params = {'regime': parameter}
                seed = seed_for(195115, partition, family, params)
                variants, evidence = payload(family, parameter, seed)
                pair_id = f'{partition}:{family}:{parameter}'
                for variant, raw in enumerate(variants):
                    path = f'{partition}/{family}-{parameter}-{variant}.raw'
                    case = {'path': path, 'partition': partition, 'family': family, 'params': {**params, 'variant': variant},
                            'seed': seed, 'regime': f'{family}:{parameter}:{variant}', 'bytes': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest(), 'features': features(raw),
                            'pair_id': pair_id, 'construction': evidence}
                    cases.append(case)
                    data[path] = raw
    meta = {'schema_version': 1, 'generator_sha256': source_hash, 'profile': 'extended-256k',
            'helper_sha256': {'scripts/search_corpus.py': sha(ROOT / 'scripts/search_corpus.py'),
                              'crates/deflate-core/src/matcher.rs': sha(ROOT / 'crates/deflate-core/src/matcher.rs'),
                              'crates/deflate-core/examples/support/cost_parse.rs': sha(ROOT / 'crates/deflate-core/examples/support/cost_parse.rs')},
            'test_policy': 'reserved; construct/hash only until all S9 methods and criteria are frozen', 'cases': cases}
    path = out / 'manifest.json'
    if path.exists():
        if json.loads(path.read_text()) != meta:
            raise ValueError('generator/provenance changed; use a new corpus directory')
    else:
        out.mkdir(parents=True, exist_ok=False)
        for name, raw in data.items():
            target = out / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(raw)
        path.write_text(json.dumps(meta, indent=2) + '\n')
    validate(out, meta)
    if any((out / name).read_bytes() != raw for name, raw in data.items()):
        raise ValueError('extension regeneration differs')
    print(json.dumps({'manifest': str(path), 'counts': dict(collections.Counter(c['partition'] for c in cases))}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    build(parser.parse_args().out.resolve())
