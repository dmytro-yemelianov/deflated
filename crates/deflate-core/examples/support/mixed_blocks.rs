//! Exact type selection for a fixed token partition, including bit alignment.
use deflate_core::CompressionLevel;
use deflate_core::bitwriter::BitWriter;
use deflate_core::encode_dynamic::{Lengths, dynamic_bits, fixed_bits, lengths_for};
use deflate_core::tokens::Token;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Fixed,
    Dynamic,
    Stored,
}

pub fn stored_bits(raw: usize, offset: usize) -> usize {
    let chunks = raw.div_ceil(65535).max(1);
    3 + (8 - (offset + 3) % 8) % 8 + 32 + raw * 8 + (chunks - 1) * 40
}

pub fn plan(
    costs: &[(usize, Option<usize>, usize)],
    stored: bool,
    start: usize,
) -> (usize, Vec<Kind>) {
    assert!(start < 8);
    let mut suffix = [0; 8];
    for (offset, value) in suffix.iter_mut().enumerate() {
        *value = (8 - offset) % 8;
    }
    let mut choices = vec![[Kind::Fixed; 8]; costs.len()];
    for (index, &(fixed, dynamic, raw)) in costs.iter().enumerate().rev() {
        let mut next = [0; 8];
        for offset in 0..8 {
            let mut best = fixed + suffix[(offset + fixed) % 8];
            if let Some(bits) = dynamic {
                let candidate = bits + suffix[(offset + bits) % 8];
                if candidate < best {
                    best = candidate;
                    choices[index][offset] = Kind::Dynamic;
                }
            }
            if stored {
                let candidate = stored_bits(raw, offset) + suffix[0];
                if candidate < best {
                    best = candidate;
                    choices[index][offset] = Kind::Stored;
                }
            }
            next[offset] = best;
        }
        suffix = next;
    }
    let (mut offset, mut selected) = (start, Vec::new());
    for (index, &(fixed, dynamic, _)) in costs.iter().enumerate() {
        let kind = choices[index][offset];
        offset = match kind {
            Kind::Fixed => (offset + fixed) % 8,
            Kind::Dynamic => (offset + dynamic.unwrap()) % 8,
            Kind::Stored => 0,
        };
        selected.push(kind);
    }
    (suffix[start], selected)
}

pub struct Block {
    tokens: std::ops::Range<usize>,
    raw: std::ops::Range<usize>,
    lengths: Option<Lengths>,
    pub fixed_bits: usize,
    pub dynamic_bits: Option<usize>,
}

pub struct Evidence {
    pub packed: Vec<u8>,
    pub planned_bits: usize,
    pub emitted_bits: usize,
    pub fallback: bool,
    pub blocks: Vec<(usize, usize, Option<usize>, Kind, usize, usize)>,
}

fn emit_stored(writer: &mut BitWriter, final_: bool, raw: &[u8]) {
    let count = raw.len().div_ceil(65535).max(1);
    for index in 0..count {
        let part = &raw[index * 65535..raw.len().min((index + 1) * 65535)];
        writer.write_bits(u32::from(final_ && index + 1 == count), 1);
        writer.write_bits(0, 2);
        writer.write_bits(0, ((8 - writer.bit_len() % 8) % 8) as u32);
        let len = part.len() as u16;
        writer.write_bits(u32::from(len), 16);
        writer.write_bits(u32::from(!len), 16);
        for &byte in part {
            writer.write_bits(u32::from(byte), 8);
        }
    }
}

pub fn stored_probe(raw: &[u8], prefix_count: usize) -> (Vec<u8>, usize) {
    assert!(prefix_count < 8);
    let mut writer = BitWriter::new();
    deflate_core::encode_fixed::emit_fixed_block(
        &mut writer,
        false,
        (0..prefix_count).map(|_| Token::Literal(144)),
    );
    let before = writer.bit_len();
    emit_stored(&mut writer, true, raw);
    assert_eq!(
        writer.bit_len() - before,
        stored_bits(raw.len(), before % 8)
    );
    (writer.finish(), before % 8)
}

pub fn encode(raw: &[u8], level: CompressionLevel, token_limit: usize, stored: bool) -> Evidence {
    assert!([1024, 4096, 16384].contains(&token_limit));
    let tokens: Vec<_> = deflate_core::matcher::tokens_with_level(raw, level).collect();
    let (mut blocks, mut raw_start, mut token_start) = (Vec::new(), 0, 0);
    loop {
        let end = (token_start + token_limit).min(tokens.len());
        let ts = &tokens[token_start..end];
        let raw_end = raw_start
            + ts.iter()
                .map(|t| match *t {
                    Token::Literal(_) => 1,
                    Token::Match { len, .. } => usize::from(len),
                })
                .sum::<usize>();
        let lengths = lengths_for(ts);
        let dynamic = lengths.as_ref().map(|(l, d, c)| dynamic_bits(l, d, c, ts));
        blocks.push(Block {
            tokens: token_start..end,
            raw: raw_start..raw_end,
            lengths,
            fixed_bits: fixed_bits(ts),
            dynamic_bits: dynamic,
        });
        raw_start = raw_end;
        token_start = end;
        if end == tokens.len() {
            break;
        }
    }
    assert_eq!(raw_start, raw.len());
    let costs: Vec<_> = blocks
        .iter()
        .map(|b| (b.fixed_bits, b.dynamic_bits, b.raw.len()))
        .collect();
    let (planned_bits, selected) = plan(&costs, stored, 0);
    // A single whole-input stored encoding remains an outside option for both
    // policies. Avoid building a discarded stream or charging its allocation.
    let whole_stored = raw.len() + raw.len().div_ceil(65535).max(1) * 5;
    if whole_stored * 8 < planned_bits {
        return Evidence {
            packed: deflate_core::deflate_stored(raw),
            planned_bits,
            emitted_bits: whole_stored * 8,
            fallback: true,
            blocks: Vec::new(),
        };
    }
    let mut writer = BitWriter::new();
    let mut evidence = Vec::new();
    for (index, (block, &kind)) in blocks.iter().zip(&selected).enumerate() {
        let before = writer.bit_len();
        let final_ = index + 1 == blocks.len();
        match kind {
            Kind::Fixed => deflate_core::encode_fixed::emit_fixed_block(
                &mut writer,
                final_,
                tokens[block.tokens.clone()].iter().copied(),
            ),
            Kind::Dynamic => {
                let (l, d, c) = block.lengths.as_ref().unwrap();
                deflate_core::encode_dynamic::emit_dynamic_block(
                    &mut writer,
                    final_,
                    l,
                    d,
                    c,
                    &tokens[block.tokens.clone()],
                );
            }
            Kind::Stored => emit_stored(&mut writer, final_, &raw[block.raw.clone()]),
        }
        let actual = writer.bit_len() - before;
        let expected = match kind {
            Kind::Fixed => block.fixed_bits,
            Kind::Dynamic => block.dynamic_bits.unwrap(),
            Kind::Stored => stored_bits(block.raw.len(), before % 8),
        };
        assert_eq!(actual, expected);
        evidence.push((
            block.raw.len(),
            block.fixed_bits,
            block.dynamic_bits,
            kind,
            before % 8,
            actual,
        ));
    }
    let emitted_bits = writer.bit_len();
    let packed = writer.finish();
    assert_eq!(packed.len() * 8, planned_bits);
    assert_eq!(packed.len(), emitted_bits.div_ceil(8));
    Evidence {
        packed,
        planned_bits,
        emitted_bits,
        fallback: false,
        blocks: evidence,
    }
}
