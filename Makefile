# Top-level driver for verified-deflate. Mirrors maked's Makefile.
.PHONY: all build-rust build-lean test test-rust test-lean test-differential \
        fmt lint fuzz size clean

all: build-rust build-lean

build-rust:
	@echo "==> cargo build --release"
	@cargo build --release --workspace

build-lean:
	@echo "==> lake build (Lean model + theorems)"
	@lake build

test: test-rust test-lean test-differential

test-rust:
	@cargo test --workspace

test-lean: build-lean
	@echo "==> no sorry/admit"
	@! grep -rnwE 'sorry|admit' spec/ --include='*.lean'
	@echo "==> headline theorems rest on standard axioms only"
	@lake env lean spec/scripts/axioms.lean | tee /tmp/axioms.log
	@! grep -q sorryAx /tmp/axioms.log

test-differential: build-rust build-lean
	@if [ -f oracles/differential.py ]; then python3 oracles/differential.py; else echo "==> oracles/differential.py not yet present (deferred to Task 8)"; fi

fmt:
	@cargo fmt --all --check

lint:
	@cargo clippy --workspace --all-targets -- -D warnings

fuzz:
	@cargo +nightly fuzz run inflate -- -max_total_time=60

size: build-rust
	@bash scripts/size_report.sh

clean:
	@cargo clean
	@lake clean
