#!/usr/bin/env python3
"""Acquire pinned real-file diagnostics from historical TRAINING sources only.

These are previously used lineages, not an independent or held-out release set.
Source/license bytes stay under target; only provenance and hashes are reported.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / 'scripts/new_methods_sources.json'
# Chosen by file type and size before candidate evaluation, not by codec speed.
SOURCE_IDS = ('go', 'commonmark', 'inter', 'otel', 'kubernetes', 'vega-weather')
MAX_DOWNLOAD = 2 << 20


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_blob(data, expected):
    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if len(data) > MAX_DOWNLOAD or digest != expected:
        raise ValueError('download size or pinned Git blob mismatch')
    return data


def download(url, expected):
    with urlopen(url, timeout=60) as response:
        return checked_blob(response.read(MAX_DOWNLOAD + 1), expected)


def selected_sources():
    sources = {s['id']: s for s in json.loads(INVENTORY.read_text())['sources']}
    result = [sources[name] for name in SOURCE_IDS]
    for source in result:
        if source['partition'] != 'train' or source.get('extraction', 'identity') != 'identity':
            raise ValueError('only untransformed historical training sources are permitted')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sources = selected_sources()
    args.out.mkdir(parents=True, exist_ok=False)
    cases = []
    for source in sources:
        raw = download(source['url'], source['download_git_blob_sha1'])
        if len(raw) != source['declared_download_bytes']:
            raise ValueError('declared source size differs')
        license_data = download(source['license_url'], source['license_git_blob_sha1'])
        name = source['id']
        path = name + '.raw'
        license_path = name + '.license'
        (args.out / path).write_bytes(raw)
        (args.out / license_path).write_bytes(license_data)
        cases.append({'name': name, 'path': path, 'scope': 'real', 'bytes': len(raw),
                      'sha256': sha(raw), 'source': source, 'license_path': license_path,
                      'license_sha256': sha(license_data)})
        print(f'{name}: {len(raw)} bytes, source and license pins verified', flush=True)
    manifest = {'schema_version': 1,
                'scope': 'real-file diagnostic; reused historical training lineages, not holdout',
                'acquisition_sha256': sha(Path(__file__).read_bytes()),
                'inventory_sha256': sha(INVENTORY.read_bytes()), 'cases': cases}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
