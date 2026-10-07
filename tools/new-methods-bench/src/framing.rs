//! Matched raw, gzip and one-entry ZIP fields shared with the C adapter.
use crate::Result;
use deflate_core::crc32::Crc32;

const GZIP: [u8; 10] = [31, 139, 8, 0, 0, 0, 0, 0, 0, 255];

fn put16(out: &mut [u8], offset: usize, value: u16) {
    out[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}
fn put32(out: &mut [u8], offset: usize, value: u32) {
    out[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}
fn get32(input: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(
        input[offset..offset + 4]
            .try_into()
            .expect("checked framing"),
    )
}
fn zip_headers(crc: u32, packed: u32, raw: u32) -> ([u8; 38], [u8; 54], [u8; 22]) {
    let (mut local, mut central, mut end) = ([0; 38], [0; 54], [0; 22]);
    put32(&mut local, 0, 0x04034b50);
    put16(&mut local, 4, 20);
    put16(&mut local, 8, 8);
    put16(&mut local, 12, 0x21);
    put32(&mut local, 14, crc);
    put32(&mut local, 18, packed);
    put32(&mut local, 22, raw);
    put16(&mut local, 26, 8);
    local[30..].copy_from_slice(b"data.bin");
    put32(&mut central, 0, 0x02014b50);
    put16(&mut central, 4, 20);
    put16(&mut central, 6, 20);
    put16(&mut central, 10, 8);
    put16(&mut central, 14, 0x21);
    put32(&mut central, 16, crc);
    put32(&mut central, 20, packed);
    put32(&mut central, 24, raw);
    put16(&mut central, 28, 8);
    central[46..].copy_from_slice(b"data.bin");
    put32(&mut end, 0, 0x06054b50);
    put16(&mut end, 8, 1);
    put16(&mut end, 10, 1);
    put32(&mut end, 12, 54);
    put32(&mut end, 16, 38 + packed);
    (local, central, end)
}

pub fn check(framing: &str) -> Result<()> {
    if matches!(framing, "raw" | "gzip" | "zip") {
        Ok(())
    } else {
        Err("invalid DEFLATE framing".into())
    }
}
pub fn wrap(packet: Vec<u8>, raw: &[u8], framing: &str) -> Result<Vec<u8>> {
    check(framing)?;
    if framing == "raw" {
        return Ok(packet);
    }
    let crc = Crc32::compute(raw);
    let raw_size = u32::try_from(raw.len()).map_err(|_| "raw size")?;
    let packed = u32::try_from(packet.len()).map_err(|_| "packet size")?;
    let mut out = Vec::with_capacity(packet.len() + if framing == "gzip" { 18 } else { 114 });
    if framing == "gzip" {
        out.extend_from_slice(&GZIP);
        out.extend_from_slice(&packet);
        out.extend_from_slice(&crc.to_le_bytes());
        out.extend_from_slice(&raw_size.to_le_bytes());
    } else {
        let (local, central, end) = zip_headers(crc, packed, raw_size);
        out.extend_from_slice(&local);
        out.extend_from_slice(&packet);
        out.extend_from_slice(&central);
        out.extend_from_slice(&end);
    }
    Ok(out)
}
pub fn unwrap<F>(packet: &[u8], expected: usize, framing: &str, decode: F) -> Result<Vec<u8>>
where
    F: FnOnce(&[u8], usize) -> Result<Vec<u8>>,
{
    check(framing)?;
    if framing == "raw" {
        return decode(packet, expected);
    }
    let (body, crc) = if framing == "gzip" {
        if packet.len() < 18
            || packet[..10] != GZIP
            || get32(packet, packet.len() - 4) as usize != expected
        {
            return Err("gzip fields or size".into());
        }
        (
            &packet[10..packet.len() - 8],
            get32(packet, packet.len() - 8),
        )
    } else {
        if packet.len() < 114 {
            return Err("short ZIP".into());
        }
        let packed = get32(packet, 18) as usize;
        let crc = get32(packet, 14);
        if packed != packet.len() - 114 || get32(packet, 22) as usize != expected {
            return Err("ZIP sizes".into());
        }
        let (local, central, end) = zip_headers(crc, packed as u32, expected as u32);
        if packet[..38] != local
            || packet[38 + packed..92 + packed] != central
            || packet[92 + packed..] != end
        {
            return Err("ZIP fields".into());
        }
        (&packet[38..38 + packed], crc)
    };
    let raw = decode(body, expected)?;
    if raw.len() != expected || Crc32::compute(&raw) != crc {
        return Err("frame checksum or size".into());
    }
    Ok(raw)
}
