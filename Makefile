# Top-level driver for verified-deflate. Mirrors maked's Makefile.
.PHONY: all build-rust build-lean test test-axiom-gate test-rust test-lean test-differential test-framing \
        fmt lint fuzz size perf profile tune research-check research-poc research-search research-defaults research-campaign research-policy-check research-policy research-cost-check research-mixed-check research-final-check clean

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
	@python3 scripts/structured_fuzz_seeds.py
	@cargo +nightly fuzz run structured_decode -- -max_total_time=60 -rss_limit_mb=4096
	@cargo +nightly fuzz run structured_roundtrip -- -max_total_time=60 -max_len=70000 -rss_limit_mb=4096

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
	@python3 scripts/test_search_policy.py
	@python3 scripts/test_search_policy_artifacts.py
	@python3 scripts/test_search_surrogate.py
	@python3 scripts/test_search_surrogate_artifacts.py
	@python3 scripts/test_search_bayesian.py
	@python3 scripts/test_search_bayesian_artifacts.py
	@python3 scripts/test_search_cost_oracle.py
	@python3 scripts/test_search_extended_corpus.py
	@python3 scripts/test_search_cost_artifacts.py
	@python3 scripts/test_search_mixed.py
	@python3 scripts/test_search_mixed_artifacts.py
	@python3 scripts/test_search_final.py
	@python3 scripts/test_search_final_artifacts.py

research-final-check:
	@cargo build --locked -p deflate-core --example default_bench --release
	@python3 scripts/test_encoder_final.py --binary target/release/examples/default_bench
	@cargo test --locked -p deflate-core --example final_bench --features research-tuning
	@cargo build --locked -p deflate-core --example final_bench --features research-tuning --release
	@python3 scripts/test_search_final.py --binary target/release/examples/final_bench

research-mixed-check:
	@cargo build --locked -p deflate-core --example mixed_blocks --release
	@python3 scripts/test_search_mixed.py --binary target/release/examples/mixed_blocks

research-cost-check:
	@cargo build --locked -p deflate-core --example cost_parse --release
	@python3 scripts/test_search_cost_oracle.py --binary target/release/examples/cost_parse

research-policy-check:
	@cargo build -p deflate-core --example tune_config --features research-tuning --release
	@python3 scripts/test_search_policy.py --binary target/release/examples/tune_config

research-policy:
	@python3 scripts/search_policy_corpus.py --out target/search/corpus-policy-s5-final
	@python3 scripts/search_policy_campaign.py --corpus target/search/corpus-policy-s5-final

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
