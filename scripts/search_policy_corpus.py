#!/usr/bin/env python3
"""S5 training/regression, unseen Calgary validation, reserved final sources."""
import argparse
import collections
import copy
import hashlib
import json
import pathlib
import random
import shutil
import subprocess
import tarfile

from search_corpus import ROOT, validate
from search_policy import features
from search_poc import sha

URL = 'https://corpus.canterbury.ac.nz/resources/calgary.tar.gz'
FINAL = {'book2', 'geo', 'obj2', 'paper2', 'progl', 'trans'}
CALGARY = {'bib', 'book1', 'book2', 'geo', 'news', 'obj1', 'obj2', 'paper1',
           'paper2', 'pic', 'progc', 'progl', 'progp', 'trans'}


def generated(family, parameter, seed, n=262144):
    rng = random.Random(seed)
    if family == 'zipf_bursts':
        symbols = list(range(parameter))
        weights = [1 / (i + 1) ** 1.2 for i in symbols]
        out = bytearray(rng.choices(symbols, weights, k=n))
        for start in range(0, n, 8192):
            out[start:start + 128] = bytes([rng.choice(symbols)]) * 128
        return bytes(out)
    if family == 'markov':
        out = bytearray()
        value = rng.randrange(256)
        for _ in range(n):
            if rng.randrange(100) >= parameter:
                value = rng.randrange(256)
            out.append(value)
        return bytes(out)
    if family == 'template_edits':
        template = bytearray(rng.randbytes(parameter))
        out = bytearray()
        while len(out) < n:
            row = bytearray(template)
            for _ in range(3):
                pos = rng.randrange(len(row))
                if rng.randrange(2):
                    row[pos:pos] = rng.randbytes(1)
                else:
                    del row[pos]
            out.extend(row)
        return bytes(out[:n])
    raise ValueError('unsupported family')


def build(previous, real, archive):
    old = json.loads((previous / 'manifest.json').read_text())
    records = []
    for original in old['cases']:
        if original['partition'] == 'stress':
            continue
        case = copy.deepcopy(original)
        data = (previous / case['path']).read_bytes()
        if sha(previous / case['path']) != case['sha256']:
            raise ValueError('prior source changed')
        case['dataset'] = 'previous-regression' if case['partition'] == 'validation' else 'previous-' + case['partition']
        case['policy_features'] = features(data)
        records.append((case, data))
    original_real = json.loads((real / 'manifest.json').read_text())
    known = {c['sha256'] for c in original_real}
    # Sampled 64-byte shingles detect obvious near copies without using labels.
    def shingles(data):
        if len(data) < 64:
            return {hashlib.sha256(data).digest()}
        step = max(1, (len(data) - 64) // 1023)
        return {hashlib.sha256(data[i:i + 64]).digest() for i in range(0, len(data) - 63, step)}
    old_shingles = []
    for case in original_real:
        data = (real / case['partition'] / case['input']).read_bytes()
        if hashlib.sha256(data).hexdigest() != case['sha256']:
            raise ValueError('original lineage changed')
        old_shingles.append(shingles(data))
    excluded = []
    found = set()
    with tarfile.open(archive, 'r:gz') as tf:
        for member in tf.getmembers():
            name = pathlib.PurePosixPath(member.name).name
            if not member.isfile() or name not in CALGARY:
                continue
            if name in found:
                raise ValueError('duplicate Calgary member')
            found.add(name)
            data = tf.extractfile(member).read()
            digest = hashlib.sha256(data).hexdigest()
            sketch = shingles(data)
            if digest in known or any(len(sketch & s) / len(sketch | s) >= .8 for s in old_shingles):
                excluded.append(name)
                continue
            partition = 'test' if name in FINAL else 'validation'
            path = f'{partition}/calgary-{name}.raw'
            case = {'path': path, 'partition': partition, 'family': 'real',
                    'dataset': 'fresh-calgary', 'source': URL, 'source_file': 'calgary-' + name,
                    'regime': 'real-source:' + digest, 'params': {'source_sha256': digest},
                    'bytes': len(data), 'sha256': digest, 'policy_features': features(data)}
            records.append((case, data))
    if found != CALGARY:
        raise ValueError('incomplete Calgary archive')
    for index, partition in enumerate(('train', 'validation', 'test')):
        for family, levels in [('zipf_bursts', ((12, 96), (24, 160), (48, 240))),
                               ('markov', ((40, 85), (60, 92), (70, 97))),
                               ('template_edits', ((31, 251), (67, 509), (127, 1021)))]:
            for parameter in levels[index]:
                key = json.dumps([195113, partition, family, parameter])
                seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'little')
                data = generated(family, parameter, seed)
                case = {'path': f'{partition}/new-{family}-{parameter}.raw', 'partition': partition,
                        'family': family, 'dataset': 'fresh-synthetic', 'seed': seed,
                        'regime': f'{family}:{parameter}', 'params': {'parameter': parameter},
                        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                        'policy_features': features(data)}
                records.append((case, data))
    meta = {'schema_version': 1, 'study': 'S5', 'generator_sha256': sha(pathlib.Path(__file__)),
            'feature_source_sha256': sha(ROOT / 'scripts/search_policy.py'),
            'previous_manifest_sha256': sha(previous / 'manifest.json'),
            'calgary_archive_sha256': sha(archive), 'source': URL,
            'excluded_lineages': excluded, 'reserved_calgary_names': sorted(FINAL),
            'split_policy': 'declared source names before measurements; original synthetic tests reserved',
            'near_duplicate_policy': 'full SHA plus sampled 64-byte shingle Jaccard >=0.8; approximate, not exhaustive deduplication',
            'cases': [c for c, _ in records]}
    return meta, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=pathlib.Path, default=ROOT / 'target/search/corpus-policy-s5')
    parser.add_argument('--previous', type=pathlib.Path, default=ROOT / 'target/search/corpus-mixed-s2')
    parser.add_argument('--real', type=pathlib.Path, default=ROOT / 'target/tuning-corpus')
    args = parser.parse_args()
    archive = ROOT / 'target/search/calgary.tar.gz'
    if not archive.exists():
        temp = archive.with_suffix('.download')
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '2',
                        '--max-time', '120', URL, '--output', str(temp)], check=True)
        temp.replace(archive)
    meta, records = build(args.previous, args.real, archive)
    manifest = args.out / 'manifest.json'
    if manifest.exists():
        if json.loads(manifest.read_text()) != meta:
            raise ValueError('corpus revision changed; choose a new directory')
    else:
        args.out.mkdir(parents=True, exist_ok=False)
        for case, data in records:
            path = args.out / case['path']
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        manifest.write_text(json.dumps(meta, indent=2) + '\n')
    validate(args.out, meta)
    for case, data in records:
        if (args.out / case['path']).read_bytes() != data:
            raise ValueError('corpus regeneration changed')
    print(json.dumps({'cases': dict(collections.Counter(c['partition'] for c, _ in records)),
                      'excluded': meta['excluded_lineages'], 'manifest': str(manifest)}))


if __name__ == '__main__':
    main()
