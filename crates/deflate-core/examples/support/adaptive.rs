//! P4 experimental predictor and regional search adapter. All predictor work
//! is inside encode; low sampled repetition is not a universal size guarantee.
use deflate_core::research::{AdaptiveConfig, Config, Index};

#[derive(Clone, Copy)]
pub struct Settings {
    pub regional: AdaptiveConfig,
    pub samples: usize,
    pub exact_cap_percent: usize,
}

impl Settings {
    pub fn parse(text: &str) -> Result<Self, String> {
        let fields: Vec<_> = text.split(':').collect();
        if fields.len() != 7 || fields[0] != "adaptive" {
            return Err("expected adaptive:LIGHT:STOP_LENGTH:INDEX:SAMPLE_BUDGET:EXACT_CAP_PERCENT:LAZY_LIMIT".into());
        }
        let integer = |n: usize| {
            fields[n]
                .parse::<usize>()
                .map_err(|_| "invalid adaptive integer".to_string())
        };
        let index = match fields[3] {
            "dual" => Index::Dual,
            "trigram" => Index::Trigram,
            _ => return Err("invalid index".into()),
        };
        let samples = integer(4)?;
        let exact_cap_percent = integer(5)?;
        if ![0, 4096, 16384, 65536].contains(&samples) || ![0, 1, 20].contains(&exact_cap_percent) {
            return Err("unsupported sampling budget or exact cap".into());
        }
        let base = Config::new(128, true, 0, index, 16384).map_err(|e| e.to_string())?;
        let regional = AdaptiveConfig::new(base, integer(1)?, integer(2)?, integer(6)?)
            .map_err(|e| format!("{e:?}"))?;
        Ok(Self {
            regional,
            samples,
            exact_cap_percent,
        })
    }
}

#[derive(Default, Debug)]
pub struct Hint {
    pub samples: usize,
    pub repeats: usize,
    pub stored: bool,
}

pub fn hint(raw: &[u8], budget: usize) -> Hint {
    if budget == 0 || raw.len() < 32768 || raw.len() >= u32::MAX as usize {
        return Hint::default();
    }
    let mut tags = vec![0u64; 1 << 15];
    let stride = (raw.len() / budget).max(1);
    let mut word = 0x19510401u32;
    let mut result = Hint::default();
    for start in (0..raw.len().saturating_sub(3)).step_by(stride) {
        word ^= word << 13;
        word ^= word >> 17;
        word ^= word << 5;
        let pos = start + (word as usize % stride);
        if pos > raw.len() - 4 {
            break;
        }
        let tag = u32::from_le_bytes(raw[pos..pos + 4].try_into().unwrap());
        let slot = (tag.wrapping_mul(0x1e35_a7bd) >> 17) as usize;
        let old = tags[slot];
        if old != 0 && old as u32 == tag {
            let previous = (old >> 32) as usize - 1;
            if pos - previous <= 32768 {
                result.repeats += 1;
            }
        }
        tags[slot] = u64::from(tag) | ((pos as u64 + 1) << 32);
        result.samples += 1;
    }
    result.stored = result.samples >= 2048 && result.repeats * 256 < result.samples;
    result
}

pub fn encode(raw: &[u8], settings: Settings) -> Vec<u8> {
    let prediction = hint(raw, settings.samples);
    let candidate = if prediction.stored {
        deflate_core::deflate_stored(raw)
    } else {
        deflate_core::research::deflate_adaptive(raw, settings.regional)
    };
    if settings.exact_cap_percent == 0 {
        return candidate;
    }
    // An always-computed baseline enforces the declared per-input size cap,
    // with integer rounding, at the cost of both complete encoder passes.
    let baseline = deflate_core::deflate(raw);
    if (candidate.len() as u128) * 100
        <= (baseline.len() as u128) * (100 + settings.exact_cap_percent as u128)
    {
        candidate
    } else {
        baseline
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sampling_recognizes_uniform_random_and_repetition_across_wraps() {
        let mut word = 43_u32;
        let random: Vec<u8> = (0..4 * 32768)
            .map(|_| {
                word = word.wrapping_mul(1664525).wrapping_add(1013904223);
                (word >> 24) as u8
            })
            .collect();
        let periodic: Vec<u8> = (0..4 * 32768).map(|i| random[i % 271]).collect();
        for budget in [4096, 16384, 65536] {
            assert!(hint(&random, budget).stored);
            assert!(!hint(&periodic, budget).stored);
        }
        assert!(!hint(&random[..259], 4096).stored);
    }
    #[test]
    fn exact_fallback_caps_actual_packets_and_keeps_decoder_agreement() {
        let raw: Vec<u8> = (0..32769).map(|i| b"abcabdef"[i % 8]).collect();
        for cap in [1, 20] {
            let settings = Settings::parse(&format!("adaptive:4:4:trigram:4096:{cap}:16")).unwrap();
            let packet = encode(&raw, settings);
            let baseline = deflate_core::deflate(&raw);
            assert!((packet.len() as u128) * 100 <= (baseline.len() as u128) * (100 + cap));
            assert_eq!(deflate_core::inflate(&packet).unwrap(), raw);
            assert_eq!(
                miniz_oxide::inflate::decompress_to_vec(&packet).unwrap(),
                raw
            );
        }
    }
}
