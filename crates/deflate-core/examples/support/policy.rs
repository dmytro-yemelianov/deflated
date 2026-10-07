//! Research-only integer features and a bounded serialized selector.
use super::BaseMethod;

pub const FEATURE_COUNT: usize = 13;
pub const ENHANCED_FEATURE_COUNT: usize = 15;
const MAX_SAMPLES: usize = 4096;

pub fn features(raw: &[u8]) -> [u64; FEATURE_COUNT] {
    let count = raw.len().min(MAX_SAMPLES);
    let stride = (raw.len() / MAX_SAMPLES).max(1);
    let mut histogram = [0_u64; 256];
    let mut result = [0_u64; FEATURE_COUNT];
    result[0] = u64::from(usize::BITS - raw.len().max(1).leading_zeros() - 1);
    result[4] = count as u64;
    for j in 0..count {
        let pos = j * stride + ((j as u64 * 0x9e37_79b1) % stride as u64) as usize;
        let byte = raw[pos];
        histogram[usize::from(byte)] += 1;
        for (k, distance) in [1, 3, 4, 16, 64, 256].into_iter().enumerate() {
            if pos >= distance && raw[pos - distance] == byte {
                result[5 + k] += 1;
            }
        }
        result[11] += u64::from((32..=126).contains(&byte));
        result[12] += u64::from(byte == 0);
    }
    result[1] = histogram.iter().filter(|&&n| n > 0).count() as u64;
    result[2] = histogram.iter().copied().max().unwrap_or(0);
    result[3] = histogram.iter().map(|n| n * n).sum();
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selector_modes_charge_fallback_and_preserve_accepted_packets() {
        let raw: Vec<_> = (0..65537).map(|i| b"abcabdefxyz"[i % 11]).collect();
        let config = BaseMethod::parse("config:16:1:0:trigram:16384").unwrap();
        let regional = Policy {
            nodes: vec![Node::Leaf(config)],
            enhanced: true,
        };
        assert_eq!(
            regional.encode(&raw, Execution::Feature),
            config.encode(&raw)
        );
        assert_eq!(
            regional.encode(&raw, Execution::Regional),
            super::super::adaptive::encode(
                &raw,
                super::super::adaptive::Settings::parse("adaptive:16:16:dual:0:0:16").unwrap()
            )
        );
        let stored = Policy {
            nodes: vec![Node::Leaf(BaseMethod::Stored)],
            enhanced: true,
        };
        let baseline = deflate_core::deflate(&raw);
        assert!(stored.encode(&raw, Execution::Feature).len() > baseline.len());
        assert_eq!(stored.encode(&raw, Execution::Exact), baseline);
        for packet in [
            regional.encode(&raw, Execution::Regional),
            stored.encode(&raw, Execution::Exact),
        ] {
            assert_eq!(deflate_core::inflate(&packet).unwrap(), raw);
            assert_eq!(
                miniz_oxide::inflate::decompress_to_vec(&packet).unwrap(),
                raw
            );
        }
        for mode in [Execution::Feature, Execution::Regional, Execution::Exact] {
            assert_eq!(
                stored.encode(&raw[..259], mode),
                deflate_core::deflate(&raw[..259])
            );
        }
    }
    #[test]
    fn enhanced_selector_rejects_small_alphabet_stored_false_positive() {
        let mut s = 43_u32;
        let random: Vec<_> = (0..131072)
            .map(|_| {
                s = s.wrapping_mul(1664525).wrapping_add(1013904223);
                (s >> 24) as u8
            })
            .collect();
        let low: Vec<_> = random.iter().map(|b| b % 16).collect();
        let policy = Policy {
            nodes: vec![
                Node::Branch {
                    feature: 14,
                    threshold: 0.5,
                    left: 1,
                    right: 2,
                },
                Node::Leaf(BaseMethod::Preset(deflate_core::CompressionLevel::Balanced)),
                Node::Leaf(BaseMethod::Stored),
            ],
            enhanced: true,
        };
        assert_eq!(
            policy.encode(&random, Execution::Feature),
            deflate_core::deflate_stored(&random)
        );
        assert_eq!(
            policy.encode(&low, Execution::Feature),
            deflate_core::deflate(&low)
        );
    }
}

pub fn enhanced_features(raw: &[u8]) -> [u64; ENHANCED_FEATURE_COUNT] {
    let mut result = [0; ENHANCED_FEATURE_COUNT];
    result[..FEATURE_COUNT].copy_from_slice(&features(raw));
    let hint = super::adaptive::hint(raw, 4096, true);
    result[13] = if hint.samples == 0 {
        0
    } else {
        (hint.repeats * 4096 / hint.samples) as u64
    };
    result[14] = u64::from(hint.stored);
    result
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Execution {
    Feature,
    Regional,
    Exact,
}

enum Node {
    Leaf(BaseMethod),
    Branch {
        feature: usize,
        threshold: f64,
        left: usize,
        right: usize,
    },
}

pub struct Policy {
    nodes: Vec<Node>,
    enhanced: bool,
}

impl Policy {
    pub fn load(path: &str) -> Result<Self, String> {
        if std::fs::metadata(path).map_err(|e| e.to_string())?.len() > 65536 {
            return Err("policy file too large".into());
        }
        let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let mut lines = text.lines();
        let enhanced = match lines.next() {
            Some("policy-v1 features-13 short-balanced-32768") => false,
            Some("policy-v2 features-15 short-balanced-32768") => true,
            _ => return Err("unsupported policy schema".into()),
        };
        let feature_count = if enhanced {
            ENHANCED_FEATURE_COUNT
        } else {
            FEATURE_COUNT
        };
        let mut nodes = Vec::new();
        for line in lines {
            if nodes.len() >= 511 {
                return Err("policy tree too large".into());
            }
            let fields: Vec<_> = line.split_whitespace().collect();
            let node = match fields.as_slice() {
                ["L", method] => Node::Leaf(BaseMethod::parse(method)?),
                ["B", f, t, l, r] => {
                    let feature: usize = f.parse().map_err(|_| "invalid feature")?;
                    let threshold: f64 = t.parse().map_err(|_| "invalid threshold")?;
                    let left: usize = l.parse().map_err(|_| "invalid left child")?;
                    let right: usize = r.parse().map_err(|_| "invalid right child")?;
                    if feature >= feature_count
                        || !threshold.is_finite()
                        || left <= nodes.len()
                        || right <= nodes.len()
                    {
                        return Err("invalid policy branch".into());
                    }
                    Node::Branch {
                        feature,
                        threshold,
                        left,
                        right,
                    }
                }
                _ => return Err("invalid policy node".into()),
            };
            nodes.push(node);
        }
        if nodes.is_empty() || nodes.len() > 511 {
            return Err("invalid policy size".into());
        }
        let mut seen = vec![false; nodes.len()];
        let mut pending = vec![(0, 0)];
        while let Some((index, depth)) = pending.pop() {
            if index >= nodes.len() || depth > 8 || seen[index] {
                return Err("policy must be a bounded tree".into());
            }
            seen[index] = true;
            if let Node::Branch { left, right, .. } = nodes[index] {
                pending.push((left, depth + 1));
                pending.push((right, depth + 1));
            }
        }
        if seen.iter().any(|&visited| !visited) {
            return Err("unreachable policy nodes".into());
        }
        Ok(Self { nodes, enhanced })
    }

    pub fn choose(&self, raw: &[u8]) -> BaseMethod {
        if raw.len() < 32768 {
            return BaseMethod::Preset(deflate_core::CompressionLevel::Balanced);
        }
        if let Node::Leaf(method) = self.nodes[0] {
            return method;
        }
        let values = if self.enhanced {
            enhanced_features(raw)
        } else {
            let mut values = [0; ENHANCED_FEATURE_COUNT];
            values[..FEATURE_COUNT].copy_from_slice(&features(raw));
            values
        };
        let mut index = 0;
        loop {
            match self.nodes[index] {
                Node::Leaf(method) => return method,
                Node::Branch {
                    feature,
                    threshold,
                    left,
                    right,
                } => {
                    index = if (values[feature] as f64) <= threshold {
                        left
                    } else {
                        right
                    };
                }
            }
        }
    }

    pub fn encode(&self, raw: &[u8], execution: Execution) -> Vec<u8> {
        let selected = self.choose(raw);
        let candidate = match (execution, selected) {
            (Execution::Regional, BaseMethod::Configured(config))
                if config.probes() == 16 && config.lazy() =>
            {
                let settings =
                    super::adaptive::Settings::parse("adaptive:16:16:dual:0:0:16").unwrap();
                super::adaptive::encode(raw, settings)
            }
            _ => selected.encode(raw),
        };
        if execution != Execution::Exact || raw.len() < 32768 {
            return candidate;
        }
        let baseline = deflate_core::deflate(raw);
        if (candidate.len() as u128) * 100 <= (baseline.len() as u128) * 101 {
            candidate
        } else {
            baseline
        }
    }
}
