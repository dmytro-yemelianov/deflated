use std::io::Write;
use std::process::{Command, Output, Stdio};

fn run(args: &[&str], input: &[u8]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_vdeflate"))
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(input).unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn stored_gzip_uses_stored_blocks() {
    let input = vec![b'a'; 4096];
    let compressed = run(&["-zc", "--stored"], &input);
    assert!(compressed.status.success());
    assert_eq!((compressed.stdout[10] >> 1) & 3, 0);
    let decoded = run(&["-zd"], &compressed.stdout);
    assert!(decoded.status.success());
    assert_eq!(decoded.stdout, input);
}

#[test]
fn concatenated_gzip_cli_and_later_error() {
    let mut bytes = run(&["-zc"], b"first").stdout;
    bytes.extend(run(&["-zc"], b"second").stdout);
    let decoded = run(&["-zd"], &bytes);
    assert!(decoded.status.success());
    assert_eq!(decoded.stdout, b"firstsecond");
    let limited = run(&["-zd", "--limit", "10"], &bytes);
    assert!(!limited.status.success());
    assert!(limited.stdout.is_empty());
    bytes.pop();
    let bad = run(&["-zd"], &bytes);
    assert!(!bad.status.success());
    assert!(bad.stdout.is_empty());
}
