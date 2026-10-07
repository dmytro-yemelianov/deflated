#!/usr/bin/env python3
"""Build isolated, byte-equivalent P2 implementations from the sealed source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

from encoder_baseline import DEFAULT_OUT as BASELINE_OUT, check as check_baseline
from encoder_corpus import ROOT, write_json
from encoder_measure import sha

OLD_REVERSE = '''        let mut rev = 0u32;
        for i in 0..len {
            rev |= ((code >> i) & 1) << (len - 1 - i);
        }
        self.write_bits(rev, len);'''
NEW_REVERSE = '''        // Reversing the whole word then shifting retains only the low len
        // input bits. Width zero avoids shifting a u32 by 32.
        let rev = if len == 0 { 0 } else { code.reverse_bits() >> (32 - len) };
        self.write_bits(rev, len);'''
OLD_ACCEPT = '''    if !(MIN_MATCH..=MAX_MATCH).contains(&len) || !(1..=WINDOW).contains(&dist) || dist > i {
        return false;
    }
    let end = match i.checked_add(len) {
        Some(e) if e <= input.len() => e,
        _ => return false,
    };
    // `dist <= i`, so the source starts at `i - dist` and never passes `i`.
    let src = i.saturating_sub(dist);
    match (
        input.get(i..end),
        input.get(src..end.min(src.saturating_add(len))),
    ) {
        (Some(a), Some(b)) => a == b,
        _ => false,
    }'''
NEW_ACCEPT = '''    if !(MIN_MATCH..=MAX_MATCH).contains(&len)
        || !(1..=WINDOW).contains(&dist)
        || dist > i
        || i > input.len()
        || len > input.len() - i
    {
        return false;
    }
    // These bounds imply i+len <= input.len() and src+len <= i+len.
    // Both additions and slices are valid, including overlapping matches.
    let src = i - dist;
    input[i..i + len] == input[src..src + len]'''
OLD_ITERATOR = '''        let mut candidate = (self.head[h] as usize).checked_sub(1);
        (0..probes).map_while(move |_| {
            let c = candidate?;
            if c >= i || i - c > WINDOW {
                return None;
            }
            let delta = self.prev[c % WINDOW] as usize;
            candidate = if delta == 0 {
                None
            } else {
                c.checked_sub(delta)
            };
            Some(c)
        })'''
NEW_ITERATOR = '''        // Keep the existing position-plus-one representation through the
        // traversal, avoiding an Option<usize> plus range-iterator state.
        let mut candidate = self.head[h] as usize;
        let mut remaining = probes;
        core::iter::from_fn(move || {
            if remaining == 0 || candidate == 0 {
                return None;
            }
            remaining -= 1;
            let c = candidate - 1;
            if c >= i || i - c > WINDOW {
                candidate = 0;
                return None;
            }
            let delta = self.prev[c % WINDOW] as usize;
            candidate = if delta != 0 && delta <= c { candidate - delta } else { 0 };
            Some(c)
        })'''
OLD_POSITION = '''        let i = self.i;
        let byte = *self.input.get(i)?;

        // Ensure the hash tables are populated up to current position
        self.insert_up_to(i);

        // Find best match at current position
        let current = self.find_best(i);

        // Lazy matching: check if next position has a better match
        if let Some((len, dist)) = current {
            if self.level.lazy() && self.better_next(len, dist) {
                // Emit literal instead, advance by 1
                self.i = i.saturating_add(1);
                self.pending = None;
                return Some(Token::Literal(byte));
            }
            // Emit the match
            self.i = i.saturating_add(len);
            self.pending = Some((i, self.i, dist));
            if let (Ok(l), Ok(d)) = (u16::try_from(len), u16::try_from(dist)) {
                return Some(Token::Match { len: l, dist: d });
            }
        }

        // No match or match not better than lookahead - emit literal
        self.i = i.saturating_add(1);
        self.pending = None;
        Some(Token::Literal(byte))'''
NEW_POSITION = OLD_POSITION.replace("i.saturating_add(1)", "i + 1").replace(
    "i.saturating_add(len)", "i + len").replace(
    '''            if let (Ok(l), Ok(d)) = (u16::try_from(len), u16::try_from(dist)) {
                return Some(Token::Match { len: l, dist: d });
            }''',
    '''            // find_best retains only accept-checked matches: len <= 258,
            // dist <= 32768 and i+len <= input.len(). No truncation or overflow.
            debug_assert!((MIN_MATCH..=MAX_MATCH).contains(&len));
            debug_assert!((1..=WINDOW).contains(&dist));
            return Some(Token::Match { len: len as u16, dist: dist as u16 });''')
PATCHES = {
    "reverse": ("crates/deflate-core/src/bitwriter.rs", OLD_REVERSE, NEW_REVERSE),
    "iterator": ("crates/deflate-core/src/matcher.rs", OLD_ITERATOR, NEW_ITERATOR),
    "accept": ("crates/deflate-core/src/matcher.rs", OLD_ACCEPT, NEW_ACCEPT),
    "position": ("crates/deflate-core/src/matcher.rs", OLD_POSITION, NEW_POSITION),
}
VARIANTS = {"control": [], "reverse": ["reverse"], "iterator": ["iterator"],
            "accept": ["accept"], "combined": ["reverse", "iterator", "accept"],
            "position": ["position"], "reverse-position": ["reverse", "position"]}

WRITER_TESTS = r'''
#[cfg(test)]
mod encoder_p2_writer_equivalence {
    use super::BitWriter;
    fn compare(code: u32, width: u32, offset: u32) {
        let mut actual = BitWriter::new();
        let mut expected = BitWriter::new();
        actual.write_bits(0b10101010, offset);
        expected.write_bits(0b10101010, offset);
        actual.write_code(code, width);
        for bit in (0..width.min(32)).rev() {
            expected.write_bits((code >> bit) & 1, 1);
        }
        actual.write_bits(0b1110011, 7);
        expected.write_bits(0b1110011, 7);
        assert_eq!(actual.bit_len(), expected.bit_len());
        assert_eq!(actual.finish(), expected.finish(), "code={code} width={width} offset={offset}");
    }
    #[test]
    fn every_16bit_code_and_width_with_wide_and_clamped_edges() {
        for code in 0..=u16::MAX as u32 {
            for width in 0..=16 { compare(code, width, code % 8); }
        }
        let mut word = 43_u32;
        for _ in 0..512 {
            word = word.wrapping_mul(1664525).wrapping_add(1013904223);
            for width in (0..=40).chain([u32::MAX]) {
                for offset in 0..8 { compare(word, width, offset); }
            }
        }
    }
}
'''
MATCHER_TESTS = r'''
#[cfg(test)]
mod encoder_p2_matcher_equivalence {
    use super::*;
    fn legacy_accept(input: &[u8], i: usize, len: usize, dist: usize) -> bool {
        if !(MIN_MATCH..=MAX_MATCH).contains(&len) || !(1..=WINDOW).contains(&dist) || dist > i { return false; }
        let end = match i.checked_add(len) { Some(e) if e <= input.len() => e, _ => return false };
        let src = i.saturating_sub(dist);
        match (input.get(i..end), input.get(src..end.min(src.saturating_add(len)))) {
            (Some(a), Some(b)) => a == b,
            _ => false,
        }
    }
    fn legacy_candidates(chain: &Chain, i: usize, h: usize, probes: usize) -> Vec<usize> {
        let mut candidate = (chain.head[h] as usize).checked_sub(1);
        (0..probes).map_while(|_| {
            let c = candidate?;
            if c >= i || i - c > WINDOW { return None; }
            let delta = chain.prev[c % WINDOW] as usize;
            candidate = if delta == 0 { None } else { c.checked_sub(delta) };
            Some(c)
        }).collect()
    }
    #[test]
    fn accepted_ranges_match_legacy_including_overflow_and_overlap() {
        let mut word = 43_u32;
        let random: Vec<u8> = (0..512).map(|_| { word = word.wrapping_mul(1664525).wrapping_add(1013904223); (word >> 24) as u8 }).collect();
        for input in [vec![], vec![0;512], (0..512).map(|i| b"abc"[i%3]).collect(), random] {
            for i in (0..=input.len()+2).chain([usize::MAX-1, usize::MAX]) {
                for len in [0,1,2,3,4,15,16,17,128,255,256,257,258,259,usize::MAX] {
                    for dist in [0,1,2,3,4,7,15,16,31,127,257,32768,32769,usize::MAX] {
                        assert_eq!(accept(&input,i,len,dist), legacy_accept(&input,i,len,dist), "i={i} len={len} dist={dist}");
                    }
                }
            }
        }
    }
    #[test]
    fn candidate_order_and_probe_limits_survive_ring_wrap_and_invalid_links() {
        let mut chain = Chain::new();
        for p in 0..=3*WINDOW+17 {
            let h = (p*17+p/127)%16;
            chain.insert(p,h);
            if p%4096==0 || [WINDOW-1,WINDOW,WINDOW+1,2*WINDOW-1,2*WINDOW,3*WINDOW+17].contains(&p) {
                for h in 0..16 {
                    for probes in [0,1,4,64,128,512,1024] {
                        assert_eq!(chain.candidates(p+1,h,probes).collect::<Vec<_>>(), legacy_candidates(&chain,p+1,h,probes));
                    }
                }
            }
        }
        for head in [0,1,2,3,32768,32769,u32::MAX] {
            chain.head[0] = head;
            for delta in [0,1,2,32768,u16::MAX] {
                chain.prev.fill(delta);
                for i in [0,1,2,32768,32769,u32::MAX as usize,usize::MAX] {
                    for probes in [0,1,4,1024,usize::MAX] {
                        assert_eq!(chain.candidates(i,0,probes).collect::<Vec<_>>(), legacy_candidates(&chain,i,0,probes));
                    }
                }
            }
        }
    }
}
'''

POSITION_TESTS = r'''
#[cfg(test)]
mod encoder_p2_progression_equivalence {
    use super::*;
    fn legacy_next<P: SearchPolicy>(m: &mut Matcher<'_, P>) -> Option<Token> {
LEGACY_BODY
    }
    fn compare<P: SearchPolicy>(mut actual: Matcher<'_, P>, mut expected: Matcher<'_, P>) {
        let mut position = 0;
        loop {
            let token = actual.next();
            assert_eq!(token, legacy_next(&mut expected), "position={position}");
            assert_eq!(actual.i, expected.i);
            assert_eq!(actual.pending, expected.pending);
            match token {
                Some(Token::Literal(byte)) => {
                    assert_eq!(actual.input[position], byte);
                    position += 1;
                }
                Some(Token::Match {len,dist}) => {
                    assert!(accept(actual.input,position,len as usize,dist as usize));
                    position += len as usize;
                }
                None => break,
            }
        }
        assert_eq!(position, actual.input.len());
        assert_eq!(actual.next(), None);
    }
    #[test]
    fn token_stream_state_and_accepted_ranges_match_legacy_progression() {
        let mut word = 43_u32;
        let random: Vec<u8> = (0..3*WINDOW+17).map(|_| {
            word = word.wrapping_mul(1664525).wrapping_add(1013904223);
            (word >> 24) as u8
        }).collect();
        let periodic: Vec<u8> = (0..3*WINDOW+17).map(|i| b"abcab"[i%5]).collect();
        for input in [&random[..], &periodic[..]] {
            for len in [0,1,2,3,15,16,17,257,258,259,WINDOW-1,WINDOW+1,input.len()] {
                let input = &input[..len];
                for level in [CompressionLevel::Fast,CompressionLevel::Balanced,CompressionLevel::Best] {
                    compare(Matcher::new(input,level), Matcher::new(input,level));
                }
                #[cfg(feature="research-tuning")]
                for config in [crate::research::Config::new(1,false,8,crate::research::Index::Trigram,16384).unwrap(),
                               crate::research::Config::new(32,false,16,crate::research::Index::Trigram,16384).unwrap()] {
                    compare(Matcher::configured(input,config), Matcher::configured(input,config));
                }
            }
        }
    }
}
'''.replace("LEGACY_BODY", OLD_POSITION.replace("self.", "m."))


def build(name, out, baseline):
    seal = check_baseline(baseline)
    compiler = subprocess.check_output(["rustc", "--version"], text=True).strip()
    flags = {k: v for k, v in os.environ.items() if k.startswith("CARGO_PROFILE_") or k in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")}
    if compiler != seal["rustc"] or flags != seal["build_overrides"]:
        raise ValueError("variant compiler/flags differ from sealed baseline")
    identity = {"variant": name, "patches": VARIANTS[name], "builder_sha256": sha(Path(__file__)),
                "source_archive_sha256": sha(baseline / "source.tar.gz"), "rustc": compiler, "flags": flags}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    folder = out / key
    receipt = folder / "build.json"
    if receipt.exists():
        existing = json.loads(receipt.read_text())
        if existing["identity"] != identity or sha(Path(existing["binary"])) != existing["binary_sha256"]:
            raise ValueError("cached variant changed")
        if sha(folder / "tests.log") != existing["test_log_sha256"] or any(
            sha(folder / "source" / relative) != digest for relative, digest in existing["source_sha256"].items()
        ):
            raise ValueError("cached source/test evidence changed")
        return existing
    source = folder / "source"
    source.mkdir(parents=True, exist_ok=False)
    with tarfile.open(baseline / "source.tar.gz", "r:gz") as archive:
        archive.extractall(source, filter="data")
    for file in ("crates/deflate-core/src/bitwriter.rs", "crates/deflate-core/src/matcher.rs"):
        if sha(source / file) != seal["source_sha256"][file]:
            raise ValueError("archived production source changed")
    for patch in VARIANTS[name]:
        relative, old, new = PATCHES[patch]
        path = source / relative
        text = path.read_text()
        if text.count(old) != 1:
            raise ValueError("patch anchor differs: " + patch)
        path.write_text(text.replace(old, new))
    for relative, tests in (("crates/deflate-core/src/bitwriter.rs", WRITER_TESTS),
                            ("crates/deflate-core/src/matcher.rs", MATCHER_TESTS + POSITION_TESTS)):
        path = source / relative
        path.write_text(path.read_text() + tests)
    manifest = source / "Cargo.toml"
    target = folder / "target"
    subprocess.run(["cargo", "fmt", "--all", "--manifest-path", str(manifest)], check=True, cwd=source)
    tests = subprocess.run(["cargo", "test", "--locked", "-p", "deflate-core", "--lib", "--features", "research-tuning",
                            "--manifest-path", str(manifest), "--target-dir", str(target)], capture_output=True, text=True, cwd=source)
    (folder / "tests.log").write_text(tests.stdout + tests.stderr)
    if tests.returncode != 0:
        raise ValueError("variant tests failed: " + str(folder / "tests.log"))
    subprocess.run(["cargo", "build", "--locked", "--release", "-p", "deflate-core", "--example", "final_bench", "--features", "research-tuning",
                    "--manifest-path", str(manifest), "--target-dir", str(target)], cwd=source, check=True)
    binary = target / "release/examples/final_bench"
    result = {"identity": identity, "binary": str(binary), "binary_sha256": sha(binary), "test_log_sha256": sha(folder / "tests.log"),
              "source_sha256": {str(p.relative_to(source)): sha(p) for p in sorted((source / "crates/deflate-core").rglob("*.rs"))},
              "promotion": "isolated research build only; current production core unchanged"}
    write_json(receipt, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target/encoder-performance/p2-builds")
    parser.add_argument("--baseline", type=Path, default=BASELINE_OUT)
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    args = parser.parse_args()
    results = {}
    for name in args.variants:
        print("build spike", name, flush=True)
        results[name] = build(name, args.out.resolve(), args.baseline.resolve())
    write_json(args.out / "builds.json", results)
    print(json.dumps({name: r["binary_sha256"] for name,r in results.items()}))
