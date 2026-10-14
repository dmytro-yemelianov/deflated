#!/usr/bin/env python3
"""Paired gzip-header development diagnostic; valid packets, no holdout claim."""
import argparse
import gzip
import json
import statistics
import struct
import subprocess
import zlib
from pathlib import Path

from library_bench import ROOT, call, run, sha, verify_freeze, write


def packet(raw, flags, size):
    header = bytearray([31, 139, 8, flags, 0, 0, 0, 0, 0, 255])
    if flags & 4:
        header += struct.pack('<H', size) + bytes(i % 256 for i in range(size))
    if flags & 8:
        header += b'n' * size + b'\0'
    if flags & 16:
        header += b'c' * size + b'\0'
    if flags & 2:
        header += struct.pack('<H', zlib.crc32(header) & 65535)
    encoder = zlib.compressobj(6, wbits=-15)
    return bytes(header) + encoder.compress(raw) + encoder.flush() + struct.pack('<II', zlib.crc32(raw), len(raw))


def measure(args):
    receipt_blob = args.receipt.read_bytes()
    receipt = json.loads(gzip.decompress(receipt_blob) if args.receipt.suffix == '.gz' else receipt_blob)
    reuse = receipt['context'] == 'reuse-state-output'
    mode = 'context-warm' if reuse else 'warm'
    methods = [(name, Path(value['binary']), 'core' if name in ['candidate', 'baseline'] else name)
               for name, value in receipt['methods'].items()]

    def check_freeze():
        sources = {p: sha(ROOT / p) for p in receipt['source_sha256']}
        verify_freeze(receipt['candidate_freeze'], sources, sha(Path(receipt['methods']['candidate']['binary'])))
        for name, binary, _ in methods:
            if sha(binary) != receipt['methods'][name]['sha256']:
                raise ValueError('worker changed')
        for worker in receipt['native_build']['workers']:
            command = worker['command']
            prefix = Path(command[command.index('-L') + 1]).parent.parent
            for relative, digest in worker['reference']['libraries'].items():
                if sha(prefix / relative) != digest:
                    raise ValueError('native library changed')

    check_freeze()
    args.out.mkdir(parents=True, exist_ok=False)
    packets = []
    for length in [0, 11, 257, 4096]:
        raw = (b'hello world ' * ((length + 11) // 12))[:length]
        for name, flags, size in [('minimal', 0, 0), ('text', 1, 0), ('extra', 4, 64),
                                  ('strings', 24, 64), ('all-crc', 31, 64), ('large-crc', 31, 8192)]:
            data = packet(raw, flags, size)
            assert zlib.decompress(data, 31) == raw
            path = args.out / f'{length}-{name}.gz'
            path.write_bytes(data)
            packets.append({'case': f'{length}-{name}', 'raw_bytes': length, 'header': name,
                            'packet_sha256': sha(path), 'packet_hex': data.hex(), 'raw_hex': raw.hex(),
                            'path': str(path), 'packed_bytes': len(data)})
    header_contracts = []
    for item in packets:
        if item['header'] not in ['all-crc', 'large-crc']:
            continue
        size = 64 if item['header'] == 'all-crc' else 8192
        invalid = bytearray.fromhex(item['packet_hex'])
        invalid[10 + 2 + size + (size + 1) * 2] ^= 1
        bad_path = args.out / 'bad-header-crc.gz'
        bad_path.write_bytes(invalid)
        for name, binary, codec in methods:
            result = subprocess.run([str(x) for x in call(binary, codec,
                'context-cold' if reuse else 'cold', 'gzip', bad_path,
                args.out / 'decoded', 0, item['raw_bytes'])], capture_output=True)
            expected = 0 if name == 'libdeflate' else 2
            if result.returncode != expected:
                raise ValueError('unexpected native/core FHCRC contract')
            header_contracts.append({'case': item['case'], 'method': name,
                                     'exit_code': result.returncode})
    rows = []
    for session in range(args.sessions):
        for i, item in enumerate(packets[session:] + packets[:session]):
            rotation = (i + session) % len(methods)
            for name, binary, codec in methods[rotation:] + methods[:rotation]:
                output = args.out / 'decoded'
                sample = json.loads(run(call(binary, codec, mode, 'gzip', Path(item['path']),
                                             output, args.minimum_ns, item['raw_bytes'])))
                if (output.read_bytes().hex() != item['raw_hex'] or sample['context'] != receipt['context']
                        or sample['encoder_calls'] != 0 or sample['raw_bytes'] != item['raw_bytes']
                        or sample['packed_bytes'] != item['packed_bytes'] or sample['decode_ns'] <= 0
                        or sample['decode_iterations'] < 1
                        or sample['decode_ns'] * sample['decode_iterations'] < args.minimum_ns * .999):
                    raise ValueError('timed output or timing contract mismatch')
                rows.append({'case': item['case'], 'method': name, 'session': session, **sample})
        print(f'session {session + 1}/{args.sessions}', flush=True)
    check_freeze()
    summary = [{'case': item['case'], 'ns': {name: statistics.median(
        row['decode_ns'] for row in rows if row['case'] == item['case'] and row['method'] == name)
        for name, _, _ in methods}} for item in packets]
    write(args.out / 'report.json', {
        'schema_version': 1, 'scope': 'gzip header development diagnostic; valid packets only',
        'source_receipt': str(args.receipt), 'source_receipt_sha256': sha(args.receipt),
        'source_sha256': receipt['source_sha256'], 'candidate_freeze': receipt['candidate_freeze'],
        'native_build': receipt['native_build'], 'methods': receipt['methods'], 'host': receipt['host'],
        'context': receipt['context'], 'sessions': args.sessions, 'minimum_ns': args.minimum_ns,
        'controller_sha256': sha(Path(__file__)), 'controller_source': Path(__file__).read_text(),
        'python_zlib': zlib.ZLIB_RUNTIME_VERSION, 'header_contracts': header_contracts, 'packets': packets, 'summary': summary, 'rows': rows,
        'notes': 'Same valid packets, serial rotated workers, output checked each batch. Header CRC validation differs: libdeflate skips FHCRC; core and zlib-ng validate it. Deliberately corrupted FHCRC packets verify this difference separately before timing. No allocation/peak-memory measurement is claimed.'})
    for row in summary:
        print(row, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sessions', type=int, default=5)
    parser.add_argument('--minimum-ns', type=int, default=20000000)
    args = parser.parse_args()
    if args.sessions < 1 or args.minimum_ns < 1:
        parser.error('sessions and minimum-ns must be positive')
    measure(args)
