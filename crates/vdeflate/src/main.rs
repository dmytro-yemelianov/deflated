//! `vdeflate`. Outside the verification boundary (spec §6): file I/O,
//! argument parsing and process exit are not modeled or proved.
//!
//! `--oracle` speaks the differential line protocol on stdin/stdout. Task 23
//! adds the user-facing CLI.

use deflate_core::encode_fixed::emit_fixed;
use deflate_core::tokens::Token;
use deflate_core::{Error, deflate, deflate_stored, inflate_with_limit};
use std::io::{self, BufRead, Write};

const USAGE: &str = "\
usage: vdeflate -d [--limit N] < INPUT > OUTPUT   decompress raw DEFLATE
       vdeflate -c             < INPUT > OUTPUT   compress (LZ77 + fixed Huffman)
       vdeflate -c --stored    < INPUT > OUTPUT   compress (stored blocks only)

Raw RFC 1951 streams only: no gzip or zip framing.
--limit N bounds the decompressed size in bytes (default: 1073741824).

This program is NOT formally verified. The Lean theorems in spec/ are about
the model in spec/Deflate/, not about this binary, and file I/O, argument
parsing and startup are outside the verification boundary entirely.
See docs/verification-boundary.md.
";

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

fn is_digits(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit())
}

fn parse_token(s: &str) -> Option<Token> {
    let mut it = s.split(':');
    match (it.next()?, it.next()?, it.next(), it.next()) {
        ("l", h, None, None) => {
            if h.len() != 2 || !h.bytes().all(|c| c.is_ascii_hexdigit()) {
                return None;
            }
            Some(Token::Literal(u8::from_str_radix(h, 16).ok()?))
        }
        ("m", l, Some(d), None) if is_digits(l) && is_digits(d) => Some(Token::Match {
            len: l.parse().ok()?,
            dist: d.parse().ok()?,
        }),
        _ => None,
    }
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
            (Some("DEFLATE"), hx) => match from_hex(hx.unwrap_or("")) {
                None => writeln!(stdout, "ERR badHex")?,
                Some(bytes) => writeln!(stdout, "OK {}", to_hex(&deflate(&bytes)))?,
            },
            (Some("EMIT"), toks) => {
                let parsed: Option<Vec<Token>> = toks
                    .unwrap_or("")
                    .split_whitespace()
                    .map(parse_token)
                    .collect();
                match parsed {
                    None => writeln!(stdout, "ERR badToken")?,
                    Some(ts) => writeln!(stdout, "OK {}", to_hex(&emit_fixed(ts)))?,
                }
            }
            _ => {}
        }
        stdout.flush()?;
    }
    Ok(())
}

fn read_stdin() -> std::io::Result<Vec<u8>> {
    use std::io::Read;
    let mut v = Vec::new();
    std::io::stdin().lock().read_to_end(&mut v)?;
    Ok(v)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = args.first().map(String::as_str);

    if mode == Some("--oracle") {
        if let Err(e) = oracle() {
            eprintln!("vdeflate: {e}");
            std::process::exit(1);
        }
        return;
    }

    let mut limit = deflate_core::DEFAULT_LIMIT;
    let mut stored = false;
    let mut i = 1;
    while i < args.len() {
        match args.get(i).map(String::as_str) {
            Some("--limit") => match args.get(i + 1).and_then(|s| s.parse::<usize>().ok()) {
                Some(n) => {
                    limit = n;
                    i += 2;
                }
                None => {
                    eprintln!("vdeflate: --limit needs a number\n{USAGE}");
                    std::process::exit(2);
                }
            },
            Some("--stored") if mode == Some("-c") => {
                stored = true;
                i += 1;
            }
            _ => {
                eprintln!("vdeflate: unexpected argument\n{USAGE}");
                std::process::exit(2);
            }
        }
    }

    let input = match read_stdin() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("vdeflate: reading stdin: {e}");
            std::process::exit(1);
        }
    };

    let result = match mode {
        Some("-d") => inflate_with_limit(&input, limit).map_err(err_name),
        Some("-c") if stored => Ok(deflate_stored(&input)),
        Some("-c") => Ok(deflate(&input)),
        _ => {
            eprint!("{USAGE}");
            std::process::exit(2);
        }
    };

    match result {
        Ok(bytes) => {
            use std::io::Write;
            let mut out = std::io::stdout().lock();
            if let Err(e) = out.write_all(&bytes).and_then(|()| out.flush()) {
                eprintln!("vdeflate: writing stdout: {e}");
                std::process::exit(1);
            }
        }
        Err(name) => {
            eprintln!("vdeflate: {name}");
            std::process::exit(1);
        }
    }
}
