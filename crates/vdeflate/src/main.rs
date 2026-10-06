//! `vdeflate`. Outside the verification boundary (spec §6): file I/O,
//! argument parsing and process exit are not modeled or proved.
//!
//! `--oracle` speaks the differential line protocol on stdin/stdout. Task 23
//! adds the user-facing CLI.

use deflate_core::bitwriter::BitWriter;
use deflate_core::encode_dynamic::{BLOCK_TOKENS, emit_dynamic_block, lengths_for};
use deflate_core::encode_fixed::{emit_fixed, emit_fixed_block};
use deflate_core::gzip::{gunzip, gzip, gzip_stored};
use deflate_core::huffman_build::{UsedSymbols, valid_lengths};
use deflate_core::tokens::Token;
use deflate_core::{Error, deflate, deflate_stored, inflate_with_limit};
use std::io::{self, BufRead, Write};

const USAGE: &str = "\
usage: vdeflate -d [--limit N] < INPUT > OUTPUT   decompress raw DEFLATE
       vdeflate -c             < INPUT > OUTPUT   compress (LZ77 + fixed Huffman)
       vdeflate -c --stored    < INPUT > OUTPUT   compress (stored blocks only)
       vdeflate -zd [--limit N] < INPUT > OUTPUT  decompress gzip (RFC 1952)
       vdeflate -zc [--stored] < INPUT > OUTPUT   compress gzip (RFC 1952)

Raw RFC 1951 streams only: no gzip or zip framing (without -z).
With -z: gzip (RFC 1952) framing.
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

/// One hex digit per length; `None` on any non-hex character.
fn parse_lengths(s: &str, sizes: std::ops::RangeInclusive<usize>) -> Option<Vec<u8>> {
    if !sizes.contains(&s.len()) {
        return None;
    }
    s.bytes()
        .map(|c| char::from(c).to_digit(16).map(|d| d as u8))
        .collect()
}

fn hex_lengths(l: &[u8]) -> String {
    l.iter().map(|&d| format!("{d:x}")).collect()
}

/// `EMITDYN <lit> <dist> <cl> <tok>*`: one final block, dynamic iff valid.
fn emit_dyn_reply(args: &str) -> String {
    let mut it = args.split_ascii_whitespace();
    let lens = (|| {
        let lit = parse_lengths(it.next()?, 257..=286)?;
        let dist = parse_lengths(it.next()?, 1..=30)?;
        let cl = parse_lengths(it.next()?, 19..=19)?;
        Some((lit, dist, cl))
    })();
    let Some((lit, dist, cl)) = lens else {
        return "ERR badLengths".to_string();
    };
    let parsed: Option<Vec<Token>> = it.map(parse_token).collect();
    let Some(ts) = parsed else {
        return "ERR badToken".to_string();
    };
    let mut w = BitWriter::new();
    if valid_lengths(&lit, &dist, &cl, &UsedSymbols::from_tokens(&ts)) {
        emit_dynamic_block(&mut w, true, &lit, &dist, &cl, &ts);
    } else {
        emit_fixed_block(&mut w, true, ts.iter().copied());
    }
    format!("OK {}", to_hex(&w.finish()))
}

/// `LENGTHS <tok>*`: the lengths `deflate` would use for that block.
fn lengths_reply(toks: &str) -> String {
    let parsed: Option<Vec<Token>> = toks.split_ascii_whitespace().map(parse_token).collect();
    match parsed {
        None => "ERR badToken".to_string(),
        Some(ts) => match lengths_for(&ts) {
            None => "OK none".to_string(),
            Some((l, d, c)) => format!(
                "OK {} {} {}",
                hex_lengths(&l),
                hex_lengths(&d),
                hex_lengths(&c)
            ),
        },
    }
}

/// `EMITBLOCKS <tok>*`: fixed blocks only (lengths forced to `None`), chunks
/// of `BLOCK_TOKENS`, the last (or only, possibly empty) chunk final.
fn emit_blocks_fixed_reply(toks: &str) -> String {
    let parsed: Option<Vec<Token>> = toks.split_ascii_whitespace().map(parse_token).collect();
    let Some(ts) = parsed else {
        return "ERR badToken".to_string();
    };
    let mut w = BitWriter::new();
    let mut chunks = ts.chunks(BLOCK_TOKENS).peekable();
    if chunks.peek().is_none() {
        emit_fixed_block(&mut w, true, std::iter::empty());
    }
    while let Some(c) = chunks.next() {
        emit_fixed_block(&mut w, chunks.peek().is_none(), c.iter().copied());
    }
    format!("OK {}", to_hex(&w.finish()))
}

// Framing commands use '-' for an empty byte argument (including ZIP names).
fn framing_reply(command: &str, args: &str, limit: usize) -> String {
    use deflate_core::crc32::Crc32;
    use deflate_core::zip::{CompressionMethod, unzip_single, zip_single};
    let fields: Vec<_> = args.split_ascii_whitespace().collect();
    let parse = |s: &str| from_hex(if s == "-" { "" } else { s });
    if command == "ZIPSTORE" {
        if fields.len() != 2 {
            return "ERR arguments".into();
        }
        let (Some(name), Some(data)) = (parse(fields[0]), parse(fields[1])) else {
            return "ERR badHex".into();
        };
        return match zip_single(&name, &data, CompressionMethod::Stored) {
            Ok(wire) => format!("OK {}", to_hex(&wire)),
            Err(e) => format!("ERR {}", err_name(e)),
        };
    }
    if fields.len() > 1 {
        return "ERR arguments".into();
    }
    let Some(bytes) = parse(fields.first().copied().unwrap_or("-")) else {
        return "ERR badHex".into();
    };
    if command == "CRC32" {
        return format!("OK {}", Crc32::compute(&bytes));
    }
    if command == "UNZIPSTORE" {
        return match unzip_single(&bytes, limit) {
            Ok((data, name)) => format!("OK {} {}", to_hex(&name), to_hex(&data)),
            Err(e) => format!("ERR {}", err_name(e)),
        };
    }
    let result = if command == "GZIP" {
        gzip(&bytes, limit)
    } else {
        gunzip(&bytes, limit)
    };
    match result {
        Ok(out) => format!("OK {}", to_hex(&out)),
        Err(e) => format!("ERR {}", err_name(e)),
    }
}

fn oracle() -> io::Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    let mut limit: usize = 1 << 26;
    for line in stdin.lock().lines() {
        let line = line?;
        let mut parts = line.trim_ascii().splitn(2, ' ');
        match (parts.next(), parts.next()) {
            (Some("LIMIT"), Some(n)) => limit = n.parse().unwrap_or(limit),
            (Some(cmd @ ("CRC32" | "GZIP" | "GUNZIP" | "ZIPSTORE" | "UNZIPSTORE")), args) => {
                writeln!(stdout, "{}", framing_reply(cmd, args.unwrap_or(""), limit))?
            }
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
                    .split_ascii_whitespace()
                    .map(parse_token)
                    .collect();
                match parsed {
                    None => writeln!(stdout, "ERR badToken")?,
                    Some(ts) => writeln!(stdout, "OK {}", to_hex(&emit_fixed(ts)))?,
                }
            }
            (Some("EMITDYN"), args) => writeln!(stdout, "{}", emit_dyn_reply(args.unwrap_or("")))?,
            (Some("EMITBLOCKS"), toks) => {
                writeln!(stdout, "{}", emit_blocks_fixed_reply(toks.unwrap_or("")))?
            }
            (Some("LENGTHS"), toks) => writeln!(stdout, "{}", lengths_reply(toks.unwrap_or("")))?,
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
            Some("--stored") if mode == Some("-c") || mode == Some("-zc") => {
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
        Some("-zd") => gunzip(&input, limit).map_err(err_name),
        Some("-zc") if stored => gzip_stored(&input, limit).map_err(err_name),
        Some("-zc") => gzip(&input, limit).map_err(err_name),
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
