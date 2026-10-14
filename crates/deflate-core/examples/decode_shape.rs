//! Untimed token census using canonical symbol decoding, checked against inflate.
use deflate_core::{
    bitstream::BitReader,
    block::{BlockType, read_block_header, read_dynamic_tables, read_stored},
    huffman::{fixed_dist, fixed_litlen},
    lz77::{copy_back, read_distance, read_length},
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 {
        return Err("decode_shape RAW_PACKET EXPECTED_SIZE".into());
    }
    let limit: usize = args[2].parse()?;
    if limit > 64 << 20 {
        return Err("diagnostic size limit".into());
    }
    let packet = std::fs::read(&args[1])?;
    let mut reader = BitReader::new(&packet);
    let mut output = Vec::new();
    let (mut stored, mut fixed, mut dynamic) = (0, 0, 0);
    let (mut literals, mut matches, mut short_matches, mut short_bytes) = (0, 0, 0, 0);
    let (mut long_codes, mut code_count, mut overlap, mut dist1, mut header_bits) = (0, 0, 0, 0, 0);
    let (mut run, mut grouped_literals) = (0, 0);
    let mut lengths = [0usize; 259];
    let mut distances = [0usize; 5]; // 1, 2..7, 8..15, 16..32768, invalid
    loop {
        let header = read_block_header(&mut reader)?;
        if header.btype == BlockType::Stored {
            stored += 1;
            let remaining = limit.saturating_sub(output.len());
            read_stored(&mut reader, &mut output, remaining)?;
        } else {
            let (lit, dist) = if header.btype == BlockType::Fixed {
                fixed += 1;
                (fixed_litlen(), fixed_dist())
            } else {
                dynamic += 1;
                let start = reader.bit_pos();
                let tables = read_dynamic_tables(&mut reader)?;
                header_bits += reader.bit_pos() - start;
                tables
            };
            loop {
                let before = reader.bit_pos();
                let symbol = lit.decode(&mut reader)?;
                code_count += 1;
                long_codes += usize::from(reader.bit_pos() - before > 12);
                if symbol < 256 {
                    literals += 1;
                    run += 1;
                    if output.len() == limit {
                        return Err("output limit".into());
                    }
                    output.push(symbol as u8);
                } else {
                    if run >= 3 {
                        grouped_literals += run;
                    }
                    run = 0;
                    if symbol == 256 {
                        break;
                    }
                    let len = read_length(symbol, &mut reader)?;
                    let before = reader.bit_pos();
                    let symbol = dist.decode(&mut reader)?;
                    code_count += 1;
                    long_codes += usize::from(reader.bit_pos() - before > 12);
                    let distance = read_distance(symbol, &mut reader)?;
                    matches += 1;
                    lengths[len] += 1;
                    if len < 16 {
                        short_matches += 1;
                        short_bytes += len;
                    }
                    overlap += usize::from(len > distance);
                    dist1 += usize::from(distance == 1);
                    distances[match distance {
                        1 => 0,
                        2..=7 => 1,
                        8..=15 => 2,
                        16..=32768 => 3,
                        _ => 4,
                    }] += 1;
                    if output.len() + len > limit {
                        return Err("output limit".into());
                    }
                    copy_back(&mut output, distance, len)?;
                }
            }
        }
        if header.is_final {
            break;
        }
    }
    if output.len() != limit || reader.bit_pos().div_ceil(8) != packet.len() {
        return Err("size/consumption mismatch".into());
    }
    assert_eq!(output, deflate_core::inflate_with_limit(&packet, limit)?);
    println!(
        "{{\"raw_bytes\":{},\"stored_blocks\":{stored},\"fixed_blocks\":{fixed},\"dynamic_blocks\":{dynamic},\"dynamic_header_bits\":{header_bits},\"literals\":{literals},\"matches\":{matches},\"short_matches\":{short_matches},\"short_match_bytes\":{short_bytes},\"overlap_matches\":{overlap},\"distance_one\":{dist1},\"code_count\":{code_count},\"codes_over_12_bits\":{long_codes},\"literals_in_runs_at_least_3\":{grouped_literals},\"length_histogram\":{lengths:?},\"distance_histogram\":{distances:?}}}",
        output.len()
    );
    Ok(())
}
