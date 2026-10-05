use std::io::Write;
use std::process::{Command, Stdio};

fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_vdeflate")
}

fn run(args: &[&str], stdin: &[u8]) -> (bool, Vec<u8>, String) {
    let mut c = Command::new(bin())
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    c.stdin.as_mut().unwrap().write_all(stdin).unwrap();
    let o = c.wait_with_output().unwrap();
    (
        o.status.success(),
        o.stdout,
        String::from_utf8_lossy(&o.stderr).into_owned(),
    )
}

#[test]
fn compress_then_decompress_through_stdin() {
    let raw = b"the quick brown fox";
    let (ok, packed, _) = run(&["-c"], raw);
    assert!(ok);
    let (ok, back, _) = run(&["-d"], &packed);
    assert!(ok);
    assert_eq!(back, raw);
}

#[test]
fn decompress_rejects_garbage_with_a_nonzero_exit_and_a_message() {
    let (ok, out, err) = run(&["-d"], b"\xff\xff\xff\xff");
    assert!(!ok, "garbage must not exit 0");
    assert!(out.is_empty(), "no partial output on failure");
    assert!(!err.is_empty(), "a failure must say why");
}

#[test]
fn limit_is_honored_and_reported() {
    let raw = vec![b'z'; 100_000];
    let (ok, packed, _) = run(&["-c"], &raw);
    assert!(ok);
    let (ok, _, err) = run(&["-d", "--limit", "10"], &packed);
    assert!(!ok);
    assert!(err.to_lowercase().contains("limit"), "stderr was: {err}");
}

#[test]
fn no_arguments_prints_usage_and_exits_nonzero() {
    let (ok, _, err) = run(&[], b"");
    assert!(!ok);
    assert!(err.contains("usage"), "stderr was: {err}");
}

#[test]
fn empty_input_compresses_and_decompresses() {
    let (ok, packed, _) = run(&["-c"], b"");
    assert!(ok);
    let (ok, back, _) = run(&["-d"], &packed);
    assert!(ok);
    assert!(back.is_empty());
}

#[test]
fn compress_default_round_trips_and_shrinks_repeats() {
    let raw = vec![b'a'; 5000];
    let (ok, packed, _) = run(&["-c"], &raw);
    assert!(ok);
    assert!(packed.len() < 100);
    let (ok, back, _) = run(&["-d"], &packed);
    assert!(ok);
    assert_eq!(back, raw);
}

#[test]
fn compress_stored_flag_gives_stored_blocks() {
    let raw = b"abcabcabc";
    let (ok, packed, _) = run(&["-c", "--stored"], raw);
    assert!(ok);
    let mut want = vec![1, 9, 0, !9, 0xff];
    want.extend_from_slice(raw);
    assert_eq!(packed, want);
}

fn oracle(input: &str) -> String {
    let (ok, out, _) = run(&["--oracle"], input.as_bytes());
    assert!(ok);
    String::from_utf8(out).unwrap()
}

#[test]
fn oracle_emit_decodes_to_aaaa() {
    let reply = oracle("EMIT l:41 m:3:1\n");
    let hx = reply.trim().strip_prefix("OK ").expect(&reply);
    let bytes: Vec<u8> = (0..hx.len() / 2)
        .map(|i| u8::from_str_radix(&hx[i * 2..i * 2 + 2], 16).unwrap())
        .collect();
    let (ok, back, _) = run(&["-d"], &bytes);
    assert!(ok);
    assert_eq!(back, b"AAAA");
}

#[test]
fn oracle_emit_bad_token_and_deflate() {
    assert_eq!(oracle("EMIT l:4\n"), "ERR badToken\n");
    assert_eq!(oracle("EMIT x:1\n"), "ERR badToken\n");
    assert_eq!(oracle("EMIT m:3\n"), "ERR badToken\n");
    assert_eq!(oracle("EMIT l:+f\n"), "ERR badToken\n");
    assert_eq!(oracle("EMIT m:+3:1\n"), "ERR badToken\n");
    assert_eq!(oracle("EMIT l:41\u{a0}l:42\n"), "ERR badToken\n");
    assert!(oracle("DEFLATE 616161\n").starts_with("OK "));
    assert_eq!(oracle("DEFLATE zz\n"), "ERR badHex\n");
}

fn unhex(reply: &str) -> Vec<u8> {
    let hx = reply.trim().strip_prefix("OK ").expect(reply);
    (0..hx.len() / 2)
        .map(|i| u8::from_str_radix(&hx[i * 2..i * 2 + 2], 16).unwrap())
        .collect()
}

const TOKS: &str = "l:61 l:62 l:61 l:62 l:61 l:62 m:6:2 m:4:2 l:63";

#[test]
fn oracle_lengths_feeds_emitdyn_and_decodes() {
    let reply = oracle(&format!("LENGTHS {TOKS}\n"));
    let args = reply.trim().strip_prefix("OK ").expect(&reply);
    assert_ne!(args, "none");
    let dynamic = oracle(&format!("EMITDYN {args} {TOKS}\n"));
    let (ok, back, _) = run(&["-d"], &unhex(&dynamic));
    assert!(ok);
    assert_eq!(back, b"ababababababababc");
    // Dynamic was chosen: first byte has BFINAL=1, BTYPE=10 (bits 1..3).
    assert_eq!(unhex(&dynamic)[0] & 7, 0b101);
}

#[test]
fn oracle_emitdyn_invalid_lengths_fall_back_to_fixed() {
    let lit = "8".repeat(257);
    let r = oracle(&format!("EMITDYN {lit} 1 {} l:41\n", "4".repeat(19)));
    assert_eq!(r, oracle("EMIT l:41\n"));
}

#[test]
fn oracle_emitdyn_and_lengths_errors() {
    let lit = "8".repeat(257);
    let cl = "4".repeat(19);
    assert_eq!(oracle("EMITDYN\n"), "ERR badLengths\n");
    assert_eq!(oracle(&format!("EMITDYN {lit} 1\n")), "ERR badLengths\n");
    assert_eq!(
        oracle(&format!("EMITDYN {lit} 1 {}\n", "4".repeat(18))),
        "ERR badLengths\n"
    );
    assert_eq!(
        oracle(&format!("EMITDYN {} 1 {cl}\n", "8".repeat(256))),
        "ERR badLengths\n"
    );
    assert_eq!(
        oracle(&format!("EMITDYN {lit} {} {cl}\n", "1".repeat(31))),
        "ERR badLengths\n"
    );
    assert_eq!(
        oracle(&format!("EMITDYN {lit} 1 {}g\n", "4".repeat(18))),
        "ERR badLengths\n"
    );
    assert_eq!(
        oracle(&format!("EMITDYN {lit} 1 {cl} l:4\n")),
        "ERR badToken\n"
    );
    assert_eq!(
        oracle(&format!("EMITDYN {lit} 1 {cl} l:+f\n")),
        "ERR badToken\n"
    );
    assert_eq!(oracle("LENGTHS x:1\n"), "ERR badToken\n");
    assert_eq!(oracle("LENGTHS l:+f\n"), "ERR badToken\n");
}

#[test]
fn oracle_emit_is_ascii_whitespace_only() {
    // Interior and edge Unicode whitespace are not separators: Rust and Lean agree.
    for cmd in ["EMIT", "EMITBLOCKS"] {
        assert_eq!(oracle(&format!("{cmd} l:41\u{a0}l:42\n")), "ERR badToken\n");
        assert_eq!(
            oracle(&format!("{cmd} l:41\u{2003}l:42\n")),
            "ERR badToken\n"
        );
        assert_eq!(
            oracle(&format!("{cmd} l:41\tl:42\n")),
            oracle(&format!("{cmd} l:41 l:42\n"))
        );
    }
    assert_eq!(oracle("EMIT l:41\u{a0}\n"), "ERR badToken\n");
}

#[test]
fn oracle_emitblocks_matches_emit_when_one_block() {
    assert_eq!(
        oracle("EMITBLOCKS l:41 m:3:1\n"),
        oracle("EMIT l:41 m:3:1\n")
    );
    assert_eq!(oracle("EMITBLOCKS\n"), oracle("EMIT\n"));
    assert_eq!(oracle("EMITBLOCKS l:4\n"), "ERR badToken\n");
    // Two blocks: the stream still decodes.
    let toks = vec!["l:61"; 16385].join(" ");
    let (ok, back, _) = run(&["-d"], &unhex(&oracle(&format!("EMITBLOCKS {toks}\n"))));
    assert!(ok);
    assert_eq!(back, vec![b'a'; 16385]);
}
