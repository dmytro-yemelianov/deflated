"""Corpus generation for the differential harness.

Three sources, and the distinction matters:

  * `zlib_streams`   — what a mature encoder actually emits. Agreement here
                       is interoperability.
  * `handmade`       — streams we construct bit by bit to hit boundaries no
                       encoder emits: empty blocks, dist == len(out),
                       under-subscribed trees.
  * `mutations`      — bit flips and truncations of the above. Every one of
                       these must produce an error, never a crash or a hang.
"""
import random
import zlib

PAYLOADS = [
    b"", b"a", b"ab", b"\x00", b"\xff" * 300,
    b"hello world " * 40,
    bytes(range(256)),
    b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",      # long run: max-length matches
    b"abcabcabcabcabcabcabcabcabcabcabcabc",  # short period: overlapping copies
    b"the quick brown fox jumps over the lazy dog " * 20,
    b"a" * 300,
    b"abc" * 200,
    b"ab" * 5000,
    bytes(range(32)) * 100,
]


def zlib_streams(seed: int = 0):
    """Raw DEFLATE from zlib at every level. Level 0 is stored blocks;
    higher levels are fixed and dynamic Huffman."""
    rng = random.Random(seed)
    payloads = list(PAYLOADS)
    for n in (1, 7, 64, 1024, 65536, 65537):
        payloads.append(bytes(rng.getrandbits(8) for _ in range(n)))        # incompressible
        payloads.append(bytes(rng.choice(b"ab") for _ in range(n)))         # very compressible
    for p in payloads:
        for level in range(0, 10):
            c = zlib.compressobj(level, zlib.DEFLATED, -15)
            yield p, c.compress(p) + c.flush()


def mutations(stream: bytes, seed: int = 0, count: int = 8):
    """Truncations at every power-of-two boundary, plus random bit flips."""
    rng = random.Random(seed)
    n = len(stream)
    cuts = {0, 1, n // 2, n - 1, n}
    k = 1
    while k < n:
        cuts.add(k)
        k *= 2
    for c in sorted(x for x in cuts if 0 <= x <= n):
        yield stream[:c]
    for _ in range(count):
        if n == 0:
            return
        b = bytearray(stream)
        i = rng.randrange(n)
        b[i] ^= 1 << rng.randrange(8)
        yield bytes(b)


def handmade(seed: int = 0):
    """Streams built bit by bit, to reach shapes no encoder produces.

    zlib agreement proves interoperability; it cannot prove conformance,
    because zlib is the de facto definition. These are the cases where the
    RFC and the dominant implementation are the only two authorities, and
    they are where our two implementations must agree with each other.
    """
    rng = random.Random(seed)

    def pack(bits):
        out = bytearray((len(bits) + 7) // 8)
        for i, b in enumerate(bits):
            out[i // 8] |= b << (i % 8)
        return bytes(out)

    def lsb(value, n):
        return [(value >> i) & 1 for i in range(n)]

    # Every stored LEN at and around the 16-bit boundary.
    for n in (0, 1, 2, 65534, 65535):
        yield bytes([0x01]) + n.to_bytes(2, "little") + (n ^ 0xFFFF).to_bytes(2, "little") + bytes(n)

    # Every block-type/BFINAL combination, including the reserved one.
    for final in (0, 1):
        for btype in range(4):
            yield pack(lsb(final, 1) + lsb(btype, 2) + [0] * 40)

    # Empty fixed block: BFINAL=1, BTYPE=01, then the 7-bit end-of-block code.
    yield pack([1, 1, 0] + [0] * 7 + [0] * 4)

    # Dynamic headers with every HLIT and HDIST at and beyond the RFC caps.
    for hlit in (0, 28, 29, 30, 31):
        for hdist in (0, 28, 29, 30, 31):
            yield pack(lsb(1, 1) + lsb(2, 2) + lsb(hlit, 5) + lsb(hdist, 5)
                       + lsb(15, 4) + [0] * 200)

    # Random bit soup: short, so a large fraction reaches the decoder's
    # interesting paths rather than failing on the first header.
    for _ in range(19000):
        n = rng.randrange(1, 40)
        yield bytes(rng.getrandbits(8) for _ in range(n))
