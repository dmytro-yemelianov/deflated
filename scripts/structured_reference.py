#!/usr/bin/env python3
"""Independent DSC1 wire decoder and hand-built normative vectors.

Python/zlib is an oracle, not the timed codec. This module intentionally has no
Rust imports, scanner, dictionary selector or compression tuning policy.
"""

import argparse
import json
from pathlib import Path
import struct
import zlib

MAX_U64 = (1 << 64) - 1
DEFAULT_LIMIT = 64 << 20


class DecodeError(ValueError):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def require(condition, category):
    if not condition:
        raise DecodeError(category)


class Cursor:
    def __init__(self, data):
        self.data = memoryview(data)
        self.pos = 0

    def take(self, n):
        require(0 <= n <= len(self.data) - self.pos, "unexpectedEof")
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return bytes(result)

    def remaining(self):
        return len(self.data) - self.pos

    def varint(self):
        value = 0
        for i in range(10):
            byte = self.take(1)[0]
            bits = byte & 127
            require(i != 9 or bits <= 1, "integerOverflow")
            require(i != 9 or byte < 128, "integerOverflow")
            value |= bits << (7 * i)
            if byte < 128:
                require(i == 0 or bits != 0, "noncanonicalVarint")
                return value
        raise DecodeError("integerOverflow")


def varint(n):
    if not 0 <= n <= MAX_U64:
        raise ValueError("u64 required")
    result = bytearray()
    while n >= 128:
        result.append((n & 127) | 128)
        n >>= 7
    result.append(n)
    return bytes(result)


def strict_inflate(packet, expected):
    decoder = zlib.decompressobj(-15)
    try:
        raw = decoder.decompress(packet, expected + 1)
    except zlib.error as error:
        raise DecodeError("deflateError") from error
    require(len(raw) <= expected, "invalidLength")
    require(decoder.eof, "deflateError")
    require(not decoder.unused_data and not decoder.unconsumed_tail, "trailingData")
    require(len(raw) == expected, "invalidLength")
    return raw


def dictionary(data):
    cursor = Cursor(data)
    count = cursor.varint()
    require(count <= 256, "invalidLength")
    entries = []
    seen = set()
    for _ in range(count):
        length = cursor.varint()
        require(1 <= length <= 256, "invalidLength")
        entry = cursor.take(length)
        require(entry not in seen, "duplicateDictionary")
        seen.add(entry)
        entries.append(entry)
    require(cursor.remaining() == 0, "unusedSubstream")
    return entries


def expand(streams, expected):
    entries = dictionary(streams[0])
    ops, literals, numbers = (Cursor(data) for data in streams[1:])
    result = bytearray()
    previous = None
    while ops.remaining():
        opcode = ops.take(1)[0]
        if opcode == 0:
            length = ops.varint()
            require(1 <= length <= expected - len(result), "invalidLength")
            piece = literals.take(length)
        elif opcode == 1:
            entry_id = ops.varint()
            require(entry_id < len(entries), "badDictionaryId")
            piece = entries[entry_id]
        elif opcode in (2, 3):
            if opcode == 3:
                require(previous is not None, "missingNumericBase")
            value = numbers.varint()
            if opcode == 3:
                delta = value // 2 if value % 2 == 0 else -(value // 2) - 1
                value = previous + delta
                require(0 <= value <= MAX_U64, "integerOverflow")
            previous = value
            piece = str(value).encode("ascii")
        else:
            raise DecodeError("badOpcode")
        require(len(piece) <= expected - len(result), "invalidLength")
        result.extend(piece)
    require(len(result) == expected, "invalidLength")
    require(literals.remaining() == numbers.remaining() == 0, "unusedSubstream")
    return bytes(result)


def split_decode(payload, expected):
    cursor = Cursor(payload)
    descriptors = []
    for cap in (65536, 4 * expected, 4 * expected, 4 * expected):
        raw, stored, storage, reserved = struct.unpack("<IIB3s", cursor.take(12))
        require(reserved == b"\0\0\0", "badFlags")
        require(storage in (0, 1), "badStorage")
        require(raw <= cap and stored <= cap + 64, "invalidLength")
        require(raw != 0 or (storage == stored == 0), "badStorage")
        require(storage != 0 or raw == stored, "invalidLength")
        descriptors.append((raw, stored, storage))
    require(sum(d[0] for d in descriptors) <= 8 * expected + 65536, "invalidLength")
    require(sum(d[1] for d in descriptors) == cursor.remaining(), "invalidLength")
    streams = []
    for raw, stored, storage in descriptors:
        data = cursor.take(stored)
        streams.append(data if storage == 0 else strict_inflate(data, raw))
    return expand(streams, expected)


def decode(packet, limit=DEFAULT_LIMIT):
    if not 0 <= limit <= MAX_U64:
        raise ValueError("nonnegative u64 output limit required")
    cursor = Cursor(packet)
    magic, version, log2, reserved, total, count, checksum = struct.unpack(
        "<4sBBHQII", cursor.take(24))
    require(magic == b"DSC1", "badMagic")
    require(version == 1, "unsupportedVersion")
    require(reserved == 0, "badFlags")
    require(log2 in (16, 18), "invalidLength")
    require(total <= limit, "outputLimit")
    chunk_size = 1 << log2
    require(count == (total + chunk_size - 1) // chunk_size, "badChunkCount")
    result = bytearray()
    for index in range(count):
        mode, flags, reserved, raw, stored, chunk_crc = struct.unpack(
            "<BBHIII", cursor.take(16))
        require(flags == reserved == 0, "badFlags")
        require(mode in (0, 1, 2), "badStorage")
        require(raw == min(chunk_size, total - index * chunk_size), "invalidLength")
        require(stored <= 8 * raw + 65536 + 304, "invalidLength")
        require(mode != 0 or stored == raw, "invalidLength")
        payload = cursor.take(stored)
        chunk = payload if mode == 0 else (strict_inflate(payload, raw) if mode == 1
                                           else split_decode(payload, raw))
        require(zlib.crc32(chunk) == chunk_crc, "checksumMismatch")
        result.extend(chunk)
    require(cursor.remaining() == 0, "trailingData")
    require(zlib.crc32(result) == checksum, "checksumMismatch")
    return bytes(result)


def frame(raw, mode=0, payload=None, log2=16):
    """Hand-build one chunk for normative vectors, independent of the scanner."""
    if len(raw) > 1 << log2:
        raise ValueError("single-chunk vector only")
    header = struct.pack("<4sBBHQII", b"DSC1", 1, log2, 0, len(raw), bool(raw), zlib.crc32(raw))
    if not raw:
        return header
    payload = raw if payload is None else payload
    return header + struct.pack("<BBHIII", mode, 0, 0, len(raw), len(payload), zlib.crc32(raw)) + payload


def split_payload(streams, compressed=()):
    descriptors, stored = [], []
    for index, stream in enumerate(streams):
        storage = int(bool(stream) and index in compressed)
        if storage:
            encoder = zlib.compressobj(6, zlib.DEFLATED, -15)
            data = encoder.compress(stream) + encoder.flush()
        else:
            data = stream
        descriptors.append(struct.pack("<IIB3s", len(stream), len(data), storage, b"\0\0\0"))
        stored.append(data)
    return b"".join(descriptors + stored)


def normative_vectors():
    vectors = []

    def good(name, raw, packet, limit=DEFAULT_LIMIT):
        vectors.append({"name": name, "packet_hex": packet.hex(), "raw_hex": raw.hex(), "limit": limit})

    def bad(name, packet, error, limit=DEFAULT_LIMIT):
        vectors.append({"name": name, "packet_hex": packet.hex(), "error": error, "limit": limit})

    good("empty", b"", frame(b""))
    lexical = b'{ "k":-0,"k":0007,"x":1.0,"y":1e3,"big":18446744073709551616,"q":"\\u0061\\\"", "raw":"\xff" }\n'
    good("raw-lexical-invalid-utf8", lexical, frame(lexical))
    # Literal split vectors are deliberately longer than raw: exercise wire
    # validity independently of the Rust encoder's smallest-payload policy.
    streams = [b"\x00", b"\x00" + varint(len(lexical)), lexical, b""]
    good("split-literal", lexical, frame(lexical, 2, split_payload(streams)))
    good("split-compressed-streams", lexical, frame(lexical, 2, split_payload(streams, (1, 2))))
    quoted = b'"escaped\\\"key"'
    keys = b"\x01" + varint(len(quoted)) + quoted
    streams = [keys, b"\x01\x00\x00\x01\x01\x00", b":", b""]
    good("split-dictionary", quoted + b":" + quoted,
         frame(quoted + b":" + quoted, 2, split_payload(streams)))
    # Absolute MAX, i64::MIN delta, then +1: Python wide arithmetic is the
    # independent expected-value oracle for Rust checked arithmetic.
    values = [MAX_U64, (1 << 63) - 1, 1 << 63]
    raw = b",".join(str(v).encode() for v in values)
    streams = [b"\0", b"\x02\x00\x01\x03\x00\x01\x03", b",,",
               varint(MAX_U64) + varint(MAX_U64) + varint(2)]
    good("numeric-delta-extrema", raw, frame(raw, 2, split_payload(streams)))
    encoder = zlib.compressobj(6, zlib.DEFLATED, -15)
    compressed = encoder.compress(lexical) + encoder.flush()
    good("whole-deflate", lexical, frame(lexical, 1, compressed))
    bad("deflate-suffix", frame(lexical, 1, compressed + b"x"), "trailingData")
    bad("deflate-truncated", frame(lexical, 1, compressed[:-1]), "deflateError")
    bad("deflate-overproduces", frame(b"x", 1, compressed), "invalidLength")
    bad("frame-suffix", frame(b"x") + b"x", "trailingData")
    bad("concatenated-frames", frame(b"") + frame(b""), "trailingData")
    bad("declared-output-limit", frame(b"xx"), "outputLimit", 1)
    packet = bytearray(frame(b"x"))
    packet[20] ^= 1
    bad("whole-crc", bytes(packet), "checksumMismatch")
    packet = bytearray(frame(b"x"))
    packet[36] ^= 1
    bad("chunk-crc", bytes(packet), "checksumMismatch")
    packet = bytearray(frame(b"x"))
    packet[24] = 3
    bad("unknown-mode", bytes(packet), "badStorage")
    packet = bytearray(frame(b"x"))
    packet[5] = 17
    bad("unsupported-chunk-size", bytes(packet), "invalidLength")
    packet = bytearray(frame(b"x"))
    packet[16] = 2
    bad("chunk-count", bytes(packet), "badChunkCount")
    packet = bytearray(frame(b"x"))
    packet[6] = 1
    bad("header-flags", bytes(packet), "badFlags")
    bad("bad-magic", b"X" + frame(b"")[1:], "badMagic")
    bad("bad-version", frame(b"")[:4] + b"\x02" + frame(b"")[5:], "unsupportedVersion")
    for name, ops, literals, numbers, entries, category in [
        ("zero-literal", b"\0\0", b"", b"", b"\0", "invalidLength"),
        ("bad-opcode", b"\x04", b"", b"", b"\0", "badOpcode"),
        ("bad-id", b"\x01\0", b"", b"", b"\0", "badDictionaryId"),
        ("missing-base", b"\x03", b"", b"\0", b"\0", "missingNumericBase"),
        ("overlong-varint", b"\0\x81\0", b"x", b"", b"\0", "noncanonicalVarint"),
        ("overflow-varint", b"\x02", b"", b"\xff" * 9 + b"\x02", b"\0", "integerOverflow"),
        ("unterminated-varint", b"\x02", b"", b"\x80", b"\0", "unexpectedEof"),
        ("unused-literals", b"\x02", b"x", b"\x01", b"\0", "unusedSubstream"),
        ("unused-numbers", b"\0\x01", b"x", b"\0", b"\0", "unusedSubstream"),
        ("dictionary-duplicate", b"\x01\0", b"", b"", b"\x02\x01x\x01x", "duplicateDictionary"),
        ("dictionary-empty-entry", b"\x01\0", b"", b"", b"\x01\0", "invalidLength"),
        ("numeric-underflow", b"\x02\x03", b"", b"\0\x01", b"\0", "integerOverflow"),
    ]:
        witness = b"xxx" if name == "overflow-varint" else b"x"
        bad(name, frame(witness, 2, split_payload([entries, ops, literals, numbers])), category)
    bad("numeric-overflow", frame(b"x" * 21, 2, split_payload(
        [b"\0", b"\x02\x03", b"", varint(MAX_U64) + b"\x02"])), "integerOverflow")
    # Declarations must be rejected before reading/inflating attacker-selected
    # stream sizes, even when no corresponding payload bytes are present.
    valid_split = bytearray(split_payload([b"\0", b"\0\x01", b"x", b""]))
    for name, offset, changed, category in [
        ("descriptor-flags", 9, b"\x01", "badFlags"),
        ("descriptor-storage", 8, b"\x02", "badStorage"),
        ("dictionary-size-cap", 0, struct.pack("<I", 65537), "invalidLength"),
        ("ops-size-cap", 12, struct.pack("<I", 5), "invalidLength"),
        ("literal-stored-cap", 28, struct.pack("<I", 69), "invalidLength"),
        ("empty-compressed-stream", 44, b"\x01", "badStorage"),
        ("stored-raw-mismatch", 4, struct.pack("<I", 2), "invalidLength"),
    ]:
        payload = valid_split.copy()
        payload[offset:offset + len(changed)] = changed
        bad(name, frame(b"x", 2, payload), category)
    for index in (0, 1, 4, 23, 24, 39, 40):
        bad(f"truncated-{index}", frame(b"xy")[:index], "unexpectedEof")
    return {"schema_version": 1, "format": "DSC1", "oracle": "independent Python/zlib; hand-built operations",
            "vectors": vectors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    decoder = sub.add_parser("decode")
    decoder.add_argument("input", type=Path)
    decoder.add_argument("output", type=Path)
    decoder.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    vectors = sub.add_parser("vectors")
    vectors.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "decode":
        args.output.write_bytes(decode(args.input.read_bytes(), args.limit))
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(normative_vectors(), indent=2) + "\n")


if __name__ == "__main__":
    main()
