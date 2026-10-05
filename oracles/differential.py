#!/usr/bin/env python3
"""N-way differential oracle: deflate-core (Rust) vs the Lean model vs zlib.

Modelled on maked's benchmarks/fuzzer/fuzz_runner.py. Agreement here is
*test evidence over a finite corpus*, not proof. It says nothing about
streams the corpus never produces. See docs/verification-boundary.md.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from corpus import PAYLOADS, handmade, mutations, zlib_streams
import leanzip

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUST = ROOT / "target" / "release" / "vdeflate"
LEAN = ROOT / ".lake" / "build" / "bin" / "deflate_spec"
LIMIT = 1 << 26
MIN_STREAMS = 20000  # the floor docs/correspondence.md quotes


class Outcome:
    def __init__(self, ok, data=None, err=None):
        self.ok, self.data, self.err = ok, data, err

    @staticmethod
    def ok_(d):
        return Outcome(True, data=d)

    @staticmethod
    def err_(e):
        return Outcome(False, err=e)

    def key(self):
        # Error *kinds* are compared across our two implementations, but zlib
        # has its own error vocabulary, so comparison against zlib is on
        # success/failure and the bytes, not on which error.
        return ("ok", self.data) if self.ok else ("err", self.err)

    def coarse(self):
        return ("ok", self.data) if self.ok else ("err",)

    def __repr__(self):
        return f"OK({len(self.data)}B)" if self.ok else f"ERR({self.err})"


Outcome.ok = Outcome.ok_
Outcome.err = Outcome.err_


class Disagreement:
    def __init__(self, parties, stream, outcomes):
        self.parties, self.stream, self.outcomes = parties, stream, outcomes

    def as_dict(self):
        return {
            "parties": sorted(self.parties),
            "stream": self.stream.hex(),
            "outcomes": {k: repr(v) for k, v in self.outcomes.items()},
        }


def make_stored_stream(payload: bytes) -> bytes:
    n = len(payload)
    return bytes([0x01]) + n.to_bytes(2, "little") + (n ^ 0xFFFF).to_bytes(2, "little") + payload


def run_oracle(cmd, streams=(), requests=None):
    """Feed every stream/request to one oracle process and read back one line each."""
    if requests is not None:
        lines = [f"LIMIT {LIMIT}"] + requests
        expected_len = len(requests)
    else:
        lines = [f"LIMIT {LIMIT}"] + [f"DECODE {s.hex()}" for s in streams]
        expected_len = len(streams)
    p = subprocess.run(
        cmd, input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=600
    )
    if p.returncode != 0:
        raise SystemExit(f"oracle {cmd!r} exited {p.returncode}: {p.stderr[:400]}")
    out = [ln for ln in p.stdout.splitlines() if ln]
    if len(out) != expected_len:
        raise SystemExit(f"oracle {cmd!r} gave {len(out)} answers for {expected_len} requests")
    res = []
    for ln in out:
        tag, _, rest = ln.partition(" ")
        res.append(Outcome.ok(bytes.fromhex(rest)) if tag == "OK" else Outcome.err(rest))
    return res


def run_zlib(streams):
    res = []
    for s in streams:
        try:
            res.append(Outcome.ok(zlib.decompress(s, -15)))
        except zlib.error as e:
            res.append(Outcome.err(str(e)))
    return res


def encode_phase(payloads):
    """Spec §18.9: a minimal encoder emits valid DEFLATE and round-trips.

    Three checks per payload, in increasing strength:
      1. our decoder accepts our encoder  — necessary, and weak (spec §2)
      2. the Lean model's decoder accepts our encoder — Rust encoder vs the
         definition the theorems are about
      3. zlib accepts our encoder — an independent decoder, which is what
         makes this an RFC-conformance signal rather than a shared
         misunderstanding
    """
    rust_enc = run_oracle([str(RUST), "--oracle"],
                          requests=[f"ENCODE {p.hex()}" for p in payloads])
    findings = []
    streams = []
    valid_payloads = []
    for p, e in zip(payloads, rust_enc):
        if not e.ok:
            findings.append({"parties": ["rust-encode"], "payload": p.hex(), "err": e.err})
        else:
            streams.append(e.data)
            valid_payloads.append(p)
    if not streams:
        return findings

    rust_dec = run_oracle([str(RUST), "--oracle"], streams)
    lean_dec = run_oracle([str(LEAN)], streams)
    zlib_dec = run_zlib(streams)

    for p, s, r, l, z in zip(valid_payloads, streams, rust_dec, lean_dec, zlib_dec):
        for name, o in (("rust", r), ("lean", l), ("zlib", z)):
            if not o.ok or o.data != p:
                findings.append({
                    "parties": [f"encode->{name}"],
                    "payload": p.hex()[:64],
                    "stream": s.hex()[:64],
                    "outcome": repr(o),
                })
    return findings


def greedy_tokens(data: bytes):
    """Greedy LZ77 over a small window. Valid by construction: every match
    has 3 <= len <= 258 and 1 <= dist <= position, overlap allowed."""
    toks, i, n = [], 0, len(data)
    table = {}
    while i < n:
        best_l, best_d = 0, 0
        if i + 3 <= n:
            for j in reversed(table.get(data[i:i + 3], [])[-8:]):
                if i - j > 32768:
                    break
                l = 0
                while l < 258 and i + l < n and data[j + l] == data[i + l]:
                    l += 1
                if l > best_l:
                    best_l, best_d = l, i - j
        step = best_l if best_l >= 3 else 1
        if best_l >= 3:
            toks.append(f"m:{best_l}:{best_d}")
        else:
            toks.append(f"l:{data[i]:02x}")
        for k in range(i, min(i + step, n - 2)):
            table.setdefault(data[k:k + 3], []).append(k)
        i += step
    return toks


def random_tokens(rng, max_toks=60):
    toks, size = [], 0
    for _ in range(rng.randrange(0, max_toks)):
        if size and rng.random() < 0.5:
            l = rng.choice([3, 4, 10, 257, 258, rng.randrange(3, 259)])
            d = rng.choice([1, size, rng.randrange(1, min(size, 32768) + 1)])
            d = min(d, size, 32768)
            toks.append(f"m:{l}:{d}")
            size += l
        else:
            toks.append(f"l:{rng.randrange(256):02x}")
            size += 1
    return toks


def expand(toks):
    out = bytearray()
    for t in toks:
        f = t.split(":")
        if f[0] == "l":
            out.append(int(f[1], 16))
        else:
            for _ in range(int(f[1])):
                out.append(out[-int(f[2])])
    return bytes(out)


def emit_phase(payloads, rust_emit_hook=None, count=300):
    """Rust EMIT and Lean EMIT must reply byte-identically, and the stream
    must expand (via zlib) to the tokens' own expansion."""
    import random
    rng = random.Random(11)
    lists = [greedy_tokens(p) for p in payloads]
    lists += [random_tokens(rng) for _ in range(count)]
    reqs = ["EMIT " + " ".join(t) for t in lists]
    rust = run_oracle([str(RUST), "--oracle"], requests=reqs)
    if rust_emit_hook:
        rust = rust_emit_hook(rust)
    lean = run_oracle([str(LEAN)], requests=reqs)
    findings = []
    for r_, a, b, t in zip(reqs, rust, lean, lists):
        if a.key() != b.key():
            findings.append({"parties": ["rust-emit", "lean-emit"], "request": r_[:120],
                             "outcomes": {"rust": repr(a), "lean": repr(b)}})
        elif a.ok:
            try:
                got = zlib.decompress(a.data, -15)
            except zlib.error as e:
                got = repr(e).encode()
            if got != expand(t):
                findings.append({"parties": ["emit->zlib"], "request": r_[:120],
                                 "outcomes": {"rust": repr(a)}})
    return findings, len(reqs)


def lengths_hex(lens):
    return "".join(f"{x:x}" for x in lens)


def canonical_random_lengths(rng, n, max_len, used):
    """Complete length set over n symbols with every index in `used` nonzero,
    built by repeatedly splitting a leaf (Kraft sum stays 1)."""
    ls = [1, 1]
    while len(ls) < max(2, len(used)):
        cand = [i for i, l in enumerate(ls) if l < max_len]
        i = rng.choice(cand)
        ls[i] += 1
        ls.append(ls[i])
    for _ in range(rng.randrange(0, 20)):
        cand = [i for i, l in enumerate(ls) if l < max_len]
        if not cand or len(ls) >= n:
            break
        i = rng.choice(cand)
        ls[i] += 1
        ls.append(ls[i])
    ls.sort()
    pos = list(used) + [i for i in range(n) if i not in used]
    rng.shuffle(pos[len(used):])
    out = [0] * n
    # shorter codes to a random subset; used symbols first
    for sym, l in zip(pos, rng.sample(ls, len(ls))):
        out[sym] = l
    return out


def emitdyn_phase(payloads, rust_hook=None, count=200):
    """EMITDYN: Rust == Lean byte for byte on Rust-LENGTHS-derived lengths (Lean has no LENGTHS), random
    valid length sets, and invalid ones (both must fall back identically).
    Every OK stream must also decode under zlib to the tokens' expansion."""
    import random
    rng = random.Random(23)
    lists = [greedy_tokens(p) for p in payloads] + [random_tokens(rng) for _ in range(count)]
    # 1. lengths from LENGTHS (Rust's) for each list
    lreq = ["LENGTHS " + " ".join(t) for t in lists]
    raw = _raw_oracle([str(RUST), "--oracle"], lreq)
    findings = []
    reqs, toks_of = [], []
    for t, line in zip(lists, raw):
        args = line.partition(" ")[2]
        if args and args != "none":
            reqs.append(f"EMITDYN {args} " + " ".join(t))
            toks_of.append(t)
    # 2. random valid length sets for random token lists
    for _ in range(count):
        t = random_tokens(rng, 40)
        used_lit, used_dist = {256}, set()
        for x in t:
            f = x.split(":")
            if f[0] == "l":
                used_lit.add(int(f[1], 16))
            else:
                used_lit.add(_len_sym(int(f[1])))
                used_dist.add(_dist_sym(int(f[2])))
        nlit = rng.randrange(max(used_lit) + 1, 287) if max(used_lit) + 1 < 287 else 286
        nlit = max(nlit, 257)
        ndist = rng.randrange(max([1] + [d + 1 for d in used_dist]), 31)
        lit = canonical_random_lengths(rng, nlit, 15, used_lit)
        dist = canonical_random_lengths(rng, ndist, 15, used_dist) if used_dist else \
            ([1] + [0] * (ndist - 1) if rng.random() < 0.5 else [1, 1][:max(ndist, 1)] + [0] * max(0, ndist - 2))
        cl = canonical_random_lengths(rng, 19, 7, set(range(19)) if rng.random() < 0.6 else {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18})
        reqs.append(f"EMITDYN {lengths_hex(lit)} {lengths_hex(dist)} {lengths_hex(cl)} " + " ".join(t))
        toks_of.append(t)
        # 3. invalid variants: incomplete lit, oversubscribed cl, over-long lit
        bad = list(lit)
        bad[rng.randrange(nlit)] = 0
        reqs.append(f"EMITDYN {lengths_hex(bad)} {lengths_hex(dist)} {lengths_hex(cl)} " + " ".join(t))
        toks_of.append(t)
        reqs.append(f"EMITDYN {lengths_hex(lit)} {lengths_hex(dist)} {'7' * 19} " + " ".join(t))
        toks_of.append(t)
        reqs.append(f"EMITDYN {'f' * nlit} {lengths_hex(dist)} {lengths_hex(cl)} " + " ".join(t))
        toks_of.append(t)
    rust = run_oracle([str(RUST), "--oracle"], requests=reqs)
    if rust_hook:
        rust = rust_hook(rust)
    lean = run_oracle([str(LEAN)], requests=reqs)
    for r_, a, b, t in zip(reqs, rust, lean, toks_of):
        if a.key() != b.key():
            findings.append({"parties": ["rust-emitdyn", "lean-emitdyn"], "request": r_[:120],
                             "outcomes": {"rust": repr(a), "lean": repr(b)}})
        elif a.ok:
            try:
                got = zlib.decompress(a.data, -15)
            except zlib.error as e:
                got = repr(e).encode()
            if got != expand(t):
                findings.append({"parties": ["emitdyn->zlib"], "request": r_[:120],
                                 "outcomes": {"rust": repr(a)}})
    return findings, len(reqs)


def _raw_oracle(cmd, requests):
    p = subprocess.run(cmd, input="\n".join([f"LIMIT {LIMIT}"] + requests) + "\n",
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise SystemExit(f"oracle {cmd!r} exited {p.returncode}: {p.stderr[:400]}")
    out = [ln for ln in p.stdout.splitlines() if ln]
    if len(out) != len(requests):
        raise SystemExit(f"oracle {cmd!r} gave {len(out)} answers for {len(requests)} requests")
    return out


_LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83,
             99, 115, 131, 163, 195, 227, 258]
_DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769,
              1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]


def _len_sym(n):
    if n == 258:
        return 285
    return 257 + max(i for i, b in enumerate(_LEN_BASE[:28]) if b <= n)


def _dist_sym(d):
    return max(i for i, b in enumerate(_DIST_BASE) if b <= d)


def emitblocks_phase(rust_hook=None):
    """EMITBLOCKS (fixed blocks, chunks of 16384): Rust == Lean byte for byte
    around the chunk boundary, and zlib expands to the tokens' expansion."""
    import random
    rng = random.Random(41)
    reqs, lists = [], []
    for n in (0, 16383, 16384, 16385, 40000):
        t = random_tokens(rng, 1)
        t = []
        size = 0
        while len(t) < n:
            if size and rng.random() < 0.3:
                l = rng.randrange(3, 259)
                d = rng.randrange(1, min(size, 32768) + 1)
                t.append(f"m:{l}:{d}")
                size += l
            else:
                t.append(f"l:{rng.randrange(256):02x}")
                size += 1
        reqs.append("EMITBLOCKS " + " ".join(t))
        lists.append(t)
    rust = run_oracle([str(RUST), "--oracle"], requests=reqs)
    if rust_hook:
        rust = rust_hook(rust)
    lean = run_oracle([str(LEAN)], requests=reqs)
    findings = []
    for r_, a, b, t in zip(reqs, rust, lean, lists):
        if a.key() != b.key():
            findings.append({"parties": ["rust-emitblocks", "lean-emitblocks"], "request": r_[:60],
                             "outcomes": {"rust": repr(a), "lean": repr(b)}})
        elif a.ok:
            try:
                got = zlib.decompress(a.data, -15)
            except zlib.error as e:
                got = repr(e).encode()
            if got != expand(t):
                findings.append({"parties": ["emitblocks->zlib"], "request": r_[:60],
                                 "outcomes": {"rust": repr(a)}})
    return findings, len(reqs)


def deflate_phase(payloads):
    """Rust DEFLATE must decode to the payload under Rust, Lean, zlib and lean-zip."""
    rust_enc = run_oracle([str(RUST), "--oracle"],
                          requests=[f"DEFLATE {p.hex()}" for p in payloads])
    findings, streams, pl = [], [], []
    for p, e in zip(payloads, rust_enc):
        if not e.ok:
            findings.append({"parties": ["rust-deflate"], "payload": p.hex()[:64], "err": e.err})
        else:
            streams.append(e.data)
            pl.append(p)
    decs = {"rust": run_oracle([str(RUST), "--oracle"], streams),
            "lean": run_oracle([str(LEAN)], streams),
            "zlib": run_zlib(streams)}
    if leanzip.available():
        lz = leanzip.decode_all(streams, run_oracle)
        if lz is not None:
            decs["leanzip"] = lz
    for name, outs in decs.items():
        for p, s, o in zip(pl, streams, outs):
            if not o.ok or o.data != p:
                findings.append({"parties": [f"deflate->{name}"], "payload": p.hex()[:64],
                                 "stream": s.hex()[:64], "outcome": repr(o)})
    return findings, len(streams)


def flip_bit(replies):
    """Self-test wrapper: corrupt one bit of the first OK reply."""
    out = list(replies)
    for i, o in enumerate(out):
        if o.ok and o.data:
            b = bytearray(o.data)
            b[0] ^= 1
            out[i] = Outcome.ok(bytes(b))
            break
    return out


def compare(outcomes, stream):
    """Rust and Lean must agree exactly, errors included. zlib is compared
    only on success/failure and bytes, since its error names are its own."""
    r, l = outcomes["rust"], outcomes["lean"]
    if r.key() != l.key():
        return Disagreement({"rust", "lean"}, stream, outcomes)
    if "zlib" in outcomes and outcomes["zlib"].coarse() != r.coarse():
        return Disagreement({"rust", "zlib"}, stream, outcomes)
    return None


def self_test() -> int:
    """A harness that cannot fail is worthless. Feed it a deliberately wrong
    oracle and confirm it reports the disagreement."""
    stream = make_stored_stream(b"abc")
    good, bad = Outcome.ok(b"abc"), Outcome.ok(b"abd")
    d = compare({"rust": good, "lean": bad, "zlib": good}, stream)
    assert d is not None, "self-test: a disagreeing oracle was not detected"
    assert "lean" in d.parties, f"self-test: wrong party blamed: {d.parties}"
    assert compare({"rust": good, "lean": good, "zlib": good}, stream) is None, \
        "self-test: agreement was reported as a disagreement"
    err, oth = Outcome.err("invalidStoredLength"), Outcome.err("unexpectedEof")
    assert compare({"rust": err, "lean": oth, "zlib": err}, stream) is not None, \
        "self-test: differing error kinds were not detected"
    toks = greedy_tokens(b"abcabcabcabc")
    assert expand(toks) == b"abcabcabcabc", "self-test: tokenizer is not lossless"
    if RUST.exists() and LEAN.exists():
        f, _ = emit_phase([b"hello hello hello"], rust_emit_hook=flip_bit, count=0)
        assert f, "self-test: a corrupted Rust EMIT was not reported"
        f, _ = emit_phase([b"hello hello hello"], count=0)
        assert not f, f"self-test: clean EMIT reported a finding: {f}"
        f, _ = emitdyn_phase([b"hello hello hello"], rust_hook=flip_bit, count=3)
        assert f, "self-test: a corrupted Rust EMITDYN was not reported"
        f, _ = emitdyn_phase([b"hello hello hello"], count=3)
        assert not f, f"self-test: clean EMITDYN reported a finding: {f}"
        f, _ = emitblocks_phase(rust_hook=flip_bit)
        assert f, "self-test: a corrupted Rust EMITBLOCKS was not reported"
        print("self-test: 9/9")
    else:
        print("self-test: 4/4 (emit checks skipped, binaries missing)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--count", type=int, default=0, help="0 = the whole corpus")
    ap.add_argument("--no-zlib", action="store_true")
    ap.add_argument("--report", default=str(ROOT / "oracles" / "reports" / "differential.json"))
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    for binary in (RUST, LEAN):
        if not binary.exists():
            raise SystemExit(f"missing {binary}; run `make all` first")

    streams, expected = [], {}
    for raw, s in zlib_streams():
        streams.append(s)
        expected[s] = raw
        streams.extend(mutations(s))
    for s in handmade():
        streams.append(s)
    if a.count:
        streams = streams[: a.count]
    streams = list(dict.fromkeys(streams))

    results = {
        "rust": run_oracle([str(RUST), "--oracle"], streams),
        "lean": run_oracle([str(LEAN)], streams),
    }
    if not a.no_zlib:
        results["zlib"] = run_zlib(streams)
    if leanzip.available():
        lz_outcomes = leanzip.decode_all(streams, run_oracle)
        if lz_outcomes is not None:
            results["leanzip"] = lz_outcomes

    findings = []
    advisories = []
    for i, s in enumerate(streams):
        o = {k: v[i] for k, v in results.items()}
        d = compare(o, s)
        if d is not None:
            findings.append(d.as_dict())
        if "leanzip" in o and o["rust"].coarse() != o["leanzip"].coarse():
            advisories.append({
                "parties": ["rust", "leanzip"],
                "stream": s.hex(),
                "outcomes": {"rust": repr(o["rust"]), "leanzip": repr(o["leanzip"])},
            })
        # Stronger than agreement: on a stream zlib produced from known bytes,
        # the answer must be those bytes.
        if s in expected and o["rust"].ok and o["rust"].data != expected[s]:
            findings.append({
                "parties": ["rust", "ground-truth"],
                "stream": s.hex(),
                "outcomes": {"rust": repr(o["rust"]), "expected": expected[s][:64].hex()},
            })

    findings.extend(encode_phase(PAYLOADS))
    ef, n_emit = emit_phase(PAYLOADS)
    dyf, n_dyn = emitdyn_phase(PAYLOADS)
    bf, n_blk = emitblocks_phase()
    df, n_defl = deflate_phase(PAYLOADS)
    findings.extend(dyf)
    findings.extend(bf)
    findings.extend(ef)
    findings.extend(df)
    print(f"emitdyn: {n_dyn} requests, {len(dyf)} findings; emitblocks: {n_blk} requests, {len(bf)} findings")
    print(f"emit: {n_emit} requests, {len(ef)} findings; deflate: {n_defl} payloads, {len(df)} findings")

    report = {"streams": len(streams), "parties": sorted(results), "findings": findings}
    if "leanzip" in results:
        report["advisories"] = advisories
    pathlib.Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.report).write_text(json.dumps(report, indent=2))
    extra = f", {len(advisories)} advisories" if "leanzip" in results else ""
    print(f"{len(streams)} streams, {len(results)} oracles, {len(findings)} findings{extra}")
    for f in findings[:10]:
        print("  ", f["parties"], f["outcomes"])
    if not a.count and report["streams"] < MIN_STREAMS:
        print(f"corpus too small: {report['streams']} < {MIN_STREAMS}")
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
