#!/usr/bin/env python3
"""Finite canonical framing correspondence evidence; not a refinement proof.

Build the existing differential binaries first: cargo build --release -p vdeflate
and lake build deflate_spec. Gzip bytes need not match (different finders).
Only canonical minimal gzip and single-entry STORED ZIP are compared.
"""
import gzip
import io
import pathlib
import selectors
import subprocess
import sys
import zipfile
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIMIT = 1 << 26


def hx(data):
    return data.hex() or "-"


class Oracle:
    def __init__(self, command):
        self.p = subprocess.Popen(command, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.p.stdout, selectors.EVENT_READ)
        self.count = 0

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def ask(self, line):
        self.send(line)
        if not self.selector.select(60):
            raise AssertionError(f"oracle timeout: {line[:50]}")
        reply = self.p.stdout.readline().rstrip("\r\n")
        self.count += 1
        if not reply:
            raise AssertionError(f"oracle exited: {self.p.poll()}")
        return reply

    def close(self):
        self.p.stdin.close()
        try:
            code = self.p.wait(timeout=5)
            if code:
                raise AssertionError(f"oracle exit {code}")
        finally:
            if self.p.poll() is None:
                self.p.kill()
                self.p.wait()
            self.p.stdout.close()
            self.selector.close()


def wire(oracle, request):
    reply = oracle.ask(request)
    assert reply.startswith("OK "), (request[:40], reply[:100])
    return bytes.fromhex(reply[3:])


def expect(oracle, request, answer):
    actual = oracle.ask(request)
    assert actual == answer, (request[:50], actual[:100], answer[:100])


def reject(oracle, request):
    actual = oracle.ask(request)
    assert actual.startswith("ERR"), (request[:50], actual[:100])


def flip(data, offset):
    out = bytearray(data)
    out[offset] ^= 1
    return bytes(out)


def exercise(oracles):
    payloads = [b"", b"123456789", bytes(range(256)), b"hello\x00world"]
    payloads += [bytes((i * 73 + i // 251) % 256 for i in range(n))
                 for n in (16383, 16384, 16385, 65534, 65535, 65536)]
    cases = 0
    for index, data in enumerate(payloads):
        name = [b"", b"entry.bin", b"nested/raw.bin"][index % 3]
        archives, gzips = [], []
        for oracle in oracles:
            expect(oracle, f"CRC32 {hx(data)}", f"OK {zlib.crc32(data)}")
            archives.append(wire(oracle, f"ZIPSTORE {hx(name)} {hx(data)}"))
            gzips.append(wire(oracle, f"GZIP {hx(data)}"))
        assert archives[0] == archives[1], f"ZIP bytes differ: payload {index}"
        for archive in archives:
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                entries = z.infolist()
                assert len(entries) == 1
                assert entries[0].filename.encode("ascii") == name
                assert z.read(entries[0]) == data
            for oracle in oracles:
                expect(oracle, f"UNZIPSTORE {hx(archive)}", f"OK {name.hex()} {data.hex()}")
        for stream in gzips:
            assert gzip.decompress(stream) == data
            for oracle in oracles:
                expect(oracle, f"GUNZIP {hx(stream)}", f"OK {data.hex()}")
        for oracle in oracles:
            oracle.send(f"LIMIT {len(data)}")
            expect(oracle, f"GUNZIP {hx(gzips[0])}", f"OK {data.hex()}")
            expect(oracle, f"UNZIPSTORE {hx(archives[0])}", f"OK {name.hex()} {data.hex()}")
            if data:
                oracle.send(f"LIMIT {len(data) - 1}")
                reject(oracle, f"GUNZIP {hx(gzips[1])}")
                reject(oracle, f"UNZIPSTORE {hx(archives[1])}")
            oracle.send(f"LIMIT {LIMIT}")
        # Every producer's CRC and ISIZE mutations must fail in both decoders.
        for stream in gzips:
            for pos in (0, 1, 2, -8, -4):
                for oracle in oracles:
                    reject(oracle, f"GUNZIP {hx(flip(stream, pos))}")
        archive = archives[0]
        cd = 30 + len(name) + len(data)
        # Shared rejected subset: CRC, sizes, method, flags, signatures, disks/counts.
        for pos in (0, 6, 8, 14, 18, 22, cd, cd + 16, cd + 24,
                    len(archive) - 22, len(archive) - 18, len(archive) - 14):
            for oracle in oracles:
                reject(oracle, f"UNZIPSTORE {hx(flip(archive, pos))}")
        # Exhaustive truncation on small members; boundary cuts on large ones.
        for cmd, stream in [("GUNZIP", gzips[0]), ("UNZIPSTORE", archive)]:
            cuts = range(len(stream)) if len(data) < 20 else (0, 1, 9, 18, 29, len(stream) - 1)
            for cut in cuts:
                for oracle in oracles:
                    reject(oracle, f"{cmd} {hx(stream[:cut])}")
        cases += 1
    # The canonical ZIP encoder must check the 16-bit filename boundary.
    name = b"n" * 65535
    archives = [wire(o, f"ZIPSTORE {hx(name)} -") for o in oracles]
    assert archives[0] == archives[1], "ZIP bytes differ at maximum filename length"
    for oracle in oracles:
        expect(oracle, f"UNZIPSTORE {hx(archives[0])}", f"OK {name.hex()} ")
        reject(oracle, f"ZIPSTORE {hx(name + b'n')} -")
    return cases


def main():
    oracles = []
    try:
        for command in ([str(ROOT / "target/release/vdeflate"), "--oracle"],
                        [str(ROOT / ".lake/build/bin/deflate_spec")]):
            oracles.append(Oracle(command))
        cases = exercise(oracles)
        print(f"framing: {cases} payloads, {sum(o.count for o in oracles)} oracle checks passed")
    finally:
        for oracle in oracles:
            oracle.close()


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, ValueError, EOFError) as error:
        print(f"framing: FAIL: {error}", file=sys.stderr)
        sys.exit(1)
