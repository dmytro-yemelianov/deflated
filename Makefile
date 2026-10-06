# Top-level driver for verified-deflate. Mirrors maked's Makefile.
.PHONY: all build-rust build-lean test test-rust test-lean test-differential \
        fmt lint fuzz size perf profile clean

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
	@echo "==> no sorry/admit/native_decide"
	@! grep -rnwE 'sorry|admit|native_decide' spec/ --include='*.lean'
	@echo "==> headline theorems rest on standard axioms only"
	@lake env lean spec/scripts/axioms.lean | tee /tmp/axioms.log
	@! grep -qE 'sorryAx|ofReduceBool' /tmp/axioms.log

test-differential: build-rust build-lean
	@python3 oracles/differential.py --self-test
	@python3 oracles/differential.py

fmt:
	@cargo fmt --all --check

lint:
	@cargo clippy --workspace --all-targets -- -D warnings

fuzz:
	@cargo +nightly fuzz run inflate        -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run dynamic_header -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run differential   -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run roundtrip      -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run dynamic_lengths -- -max_total_time=60 -rss_limit_mb=4096

size: build-rust
	@bash scripts/size_report.sh

perf:
	@bash scripts/perf_report.sh
	@bash scripts/check_perf_report.sh

profile: perf
	@bash scripts/profile_report.sh
	@bash scripts/check_perf_report.sh

clean:
	@cargo clean
	@lake clean
