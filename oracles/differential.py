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
from corpus import mutations, zlib_streams

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUST = ROOT / "target" / "release" / "vdeflate"
LEAN = ROOT / ".lake" / "build" / "bin" / "deflate_spec"
LIMIT = 1 << 26


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


def run_oracle(cmd, streams):
    """Feed every stream to one oracle process and read back one line each."""
    lines = [f"LIMIT {LIMIT}"] + [f"DECODE {s.hex()}" for s in streams]
    p = subprocess.run(
        cmd, input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=600
    )
    if p.returncode != 0:
        raise SystemExit(f"oracle {cmd!r} exited {p.returncode}: {p.stderr[:400]}")
    out = [ln for ln in p.stdout.splitlines() if ln]
    if len(out) != len(streams):
        raise SystemExit(f"oracle {cmd!r} gave {len(out)} answers for {len(streams)} streams")
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
    print("self-test: 3/3")
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
    if a.count:
        streams = streams[: a.count]
    streams = list(dict.fromkeys(streams))

    results = {
        "rust": run_oracle([str(RUST), "--oracle"], streams),
        "lean": run_oracle([str(LEAN)], streams),
    }
    if not a.no_zlib:
        results["zlib"] = run_zlib(streams)

    findings = []
    for i, s in enumerate(streams):
        o = {k: v[i] for k, v in results.items()}
        d = compare(o, s)
        if d is not None:
            findings.append(d.as_dict())
        # Stronger than agreement: on a stream zlib produced from known bytes,
        # the answer must be those bytes.
        if s in expected and o["rust"].ok and o["rust"].data != expected[s]:
            findings.append({
                "parties": ["rust", "ground-truth"],
                "stream": s.hex(),
                "outcomes": {"rust": repr(o["rust"]), "expected": expected[s][:64].hex()},
            })

    report = {"streams": len(streams), "parties": sorted(results), "findings": findings}
    pathlib.Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.report).write_text(json.dumps(report, indent=2))
    print(f"{len(streams)} streams, {len(results)} oracles, {len(findings)} findings")
    for f in findings[:10]:
        print("  ", f["parties"], f["outcomes"])
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
