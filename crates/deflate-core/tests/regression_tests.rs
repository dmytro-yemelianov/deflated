//! Every minimized fuzz finding lives in `tests/malformed/` and is replayed
//! here forever (spec §19.11). The contract is narrow on purpose: these
//! inputs must *return*. Which error they return is not pinned, because a
//! later fix may legitimately change the error while keeping the behavior
//! safe.

use deflate_core::inflate_with_limit;
use std::fs;
use std::path::Path;

#[test]
fn every_malformed_corpus_entry_returns() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/malformed");
    let mut n = 0;
    for entry in fs::read_dir(&dir).expect("tests/malformed must exist") {
        let p = entry.unwrap().path();
        if p.extension().and_then(|e| e.to_str()) != Some("deflate") {
            continue;
        }
        let data = fs::read(&p).unwrap();
        // No panic, no hang, no unbounded allocation.
        let _ = inflate_with_limit(&data, 1 << 20);
        n += 1;
    }
    assert!(n > 0, "the malformed corpus is empty; seed it from Step 4");
}
