//! `vdeflate`. Outside the verification boundary (spec §6): file I/O,
//! argument parsing and process exit are not modeled or proved.
//!
//! `--oracle` speaks the differential line protocol on stdin/stdout. Task 23
//! adds the user-facing CLI.

use deflate_core::{Error, deflate_stored, inflate_with_limit};
use std::io::{self, BufRead, Write};

fn err_name(e: Error) -> &'static str {
    match e {
        Error::UnexpectedEof => "unexpectedEof",
        Error::InvalidBlockType => "invalidBlockType",
        Error::InvalidStoredLength => "invalidStoredLength",
        Error::InvalidHuffmanTree => "invalidHuffmanTree",
        Error::InvalidCode => "invalidCode",
        Error::InvalidDistance => "invalidDistance",
        Error::InvalidLength => "invalidLength",
        Error::OutputLimitExceeded => "outputLimitExceeded",
    }
}

fn from_hex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    (0..s.len() / 2)
        .map(|i| u8::from_str_radix(s.get(i * 2..i * 2 + 2)?, 16).ok())
        .collect()
}

fn to_hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn oracle() -> io::Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    let mut limit: usize = 1 << 26;
    for line in stdin.lock().lines() {
        let line = line?;
        let mut parts = line.trim().splitn(2, ' ');
        match (parts.next(), parts.next()) {
            (Some("LIMIT"), Some(n)) => limit = n.parse().unwrap_or(limit),
            (Some("DECODE"), hx) => match from_hex(hx.unwrap_or("")) {
                None => writeln!(stdout, "ERR badHex")?,
                Some(bytes) => match inflate_with_limit(&bytes, limit) {
                    Ok(out) => writeln!(stdout, "OK {}", to_hex(&out))?,
                    Err(e) => writeln!(stdout, "ERR {}", err_name(e))?,
                },
            },
            (Some("ENCODE"), hx) => match from_hex(hx.unwrap_or("")) {
                None => writeln!(stdout, "ERR badHex")?,
                Some(bytes) => {
                    let out = deflate_stored(&bytes);
                    writeln!(stdout, "OK {}", to_hex(&out))?;
                }
            },
            _ => {}
        }
        stdout.flush()?;
    }
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--oracle") {
        if let Err(e) = oracle() {
            eprintln!("vdeflate: {e}");
            std::process::exit(1);
        }
        return;
    }
    eprintln!("vdeflate: usage: vdeflate --oracle");
    std::process::exit(2);
}
