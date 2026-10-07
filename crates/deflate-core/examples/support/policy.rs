//! Research-only integer features and a bounded serialized selector.
use super::BaseMethod;

pub const FEATURE_COUNT: usize = 13;
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
}

impl Policy {
    pub fn load(path: &str) -> Result<Self, String> {
        if std::fs::metadata(path).map_err(|e| e.to_string())?.len() > 65536 {
            return Err("policy file too large".into());
        }
        let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let mut lines = text.lines();
        if lines.next() != Some("policy-v1 features-13 short-balanced-32768") {
            return Err("unsupported policy schema".into());
        }
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
                    if feature >= FEATURE_COUNT
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
        Ok(Self { nodes })
    }

    pub fn choose(&self, raw: &[u8]) -> BaseMethod {
        if raw.len() < 32768 {
            return BaseMethod::Preset(deflate_core::CompressionLevel::Balanced);
        }
        if let Node::Leaf(method) = self.nodes[0] {
            return method;
        }
        let values = features(raw);
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
}
