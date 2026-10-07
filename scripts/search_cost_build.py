"""Source/compiler/flags/layout keyed builds for the isolated research parser."""
import hashlib
import json
import os
import subprocess
import time

from search_corpus import ROOT
from search_poc import sha


def sources():
    names = ['Cargo.toml', 'Cargo.lock', 'crates/deflate-core/Cargo.toml',
             'crates/deflate-core/examples/cost_parse.rs', 'crates/deflate-core/examples/support/cost_parse.rs',
             'scripts/search_cost_build.py']
    return {name: sha(ROOT / name) for name in names + [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'crates/deflate-core/src').rglob('*.rs'))]}


def build(layout):
    if set(layout) != {'hash_bits', 'window_bytes'} or type(layout['hash_bits']) is not int or type(layout['window_bytes']) is not int:
        raise ValueError('unknown, inactive or mistyped layout fields')
    bits, window = layout['hash_bits'], layout['window_bytes']
    if not 12 <= bits <= 18 or not 1024 <= window <= 32768 or window & (window - 1):
        raise ValueError('layout outside checked bounds')
    overrides = {name: value for name, value in os.environ.items() if name.startswith('CARGO_PROFILE_RELEASE_') or name in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS')}
    compiler = subprocess.check_output(['rustc', '--version'], text=True).strip()
    frozen = sources()
    key = hashlib.sha256(json.dumps([frozen, compiler, overrides, layout], sort_keys=True).encode()).hexdigest()[:20]
    target = ROOT / 'target/search/cost-builds' / key
    begun = time.perf_counter()
    subprocess.run(['cargo', 'build', '--locked', '--release', '-p', 'deflate-core', '--example', 'cost_parse', '--target-dir', str(target)],
                   cwd=ROOT, env={**os.environ, 'DEFLATED_RESEARCH_HASH_BITS': str(bits), 'DEFLATED_RESEARCH_WINDOW': str(window)}, check=True)
    binary = target / 'release/examples/cost_parse'
    native = json.loads(subprocess.check_output([str(binary), '--layout'], text=True))
    if native['hash_bits'] != bits or native['window_bytes'] != window or frozen != sources():
        raise ValueError('compiled layout or measured sources changed')
    return binary, {'layout': native, 'source_sha256': frozen, 'rustc': compiler, 'build_overrides': overrides,
                    'binary_path': str(binary.relative_to(ROOT)), 'binary_sha256': sha(binary), 'build_seconds': time.perf_counter() - begun}
