# Top-level driver for verified-deflate. Mirrors maked's Makefile.
.PHONY: all build-rust build-lean test test-axiom-gate test-rust test-lean test-differential test-framing \
        fmt lint fuzz size perf profile tune research-check research-poc research-search research-defaults research-campaign clean

all: build-rust build-lean

build-rust:
	@echo "==> cargo build --release"
	@cargo build --release --workspace

build-lean:
	@echo "==> lake build (Lean model + theorems)"
	@lake build

test: test-axiom-gate test-rust test-lean test-differential test-framing

test-axiom-gate:
	@sh scripts/test_axiom_gate.sh

test-rust:
	@cargo test --workspace

test-lean: build-lean
	@echo "==> no sorry/admit/native_decide"
	@! grep -rnwE 'sorry|admit|native_decide' spec/ --include='*.lean'
	@echo "==> headline theorems rest on standard axioms only"
	@sh scripts/axiom_gate.sh

test-differential: build-rust build-lean
	@python3 oracles/differential.py --self-test
	@python3 oracles/differential.py

test-framing: build-rust build-lean
	@python3 oracles/framing.py

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
	@python3 scripts/tuning_report.py --check

tune:
	@python3 scripts/tuning_corpus.py
	@python3 scripts/tuning_report.py

research-check:
	@python3 scripts/test_search_tools.py
	@python3 scripts/test_search_cpu.py
	@python3 scripts/test_search_campaign.py
	@python3 scripts/test_search_campaign_artifacts.py

research-poc:
	@python3 scripts/search_corpus.py --profile smoke
	@python3 scripts/search_poc.py --partition train

research-search:
	@python3 scripts/search_corpus.py --profile smoke
	@python3 scripts/search_cpu.py --strategy random

research-defaults:
	@python3 scripts/search_corpus.py --profile smoke
	@python3 scripts/check_research_defaults.py

research-campaign:
	@python3 -m venv target/search/optimizer-venv
	@target/search/optimizer-venv/bin/python -m pip install -r scripts/optimizer-requirements.txt
	@python3 scripts/tuning_corpus.py
	@python3 scripts/search_workloads.py
	@target/search/optimizer-venv/bin/python scripts/search_campaign.py

profile: perf
	@bash scripts/profile_report.sh
	@bash scripts/check_perf_report.sh

clean:
	@cargo clean
	@lake clean
