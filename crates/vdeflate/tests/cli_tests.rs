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
