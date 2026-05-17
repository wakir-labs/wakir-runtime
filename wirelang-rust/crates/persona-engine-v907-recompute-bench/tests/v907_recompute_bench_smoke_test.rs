// SPDX-License-Identifier: Apache-2.0
//! Smoke + integration tests for the V-907 recompute bench crate.
//!
//! These tests complement the in-module unit tests in `src/lib.rs` and
//! `src/fixtures.rs`. They focus on end-to-end shape — running the
//! bench on representative inputs and asserting the report's
//! cross-field invariants — rather than on individual helpers.

use persona_engine_v907_recompute_bench::{
    fixtures::{default_corpus, real_corpus, synthetic_corpus},
    BenchRunner, BENCH_REPORT_SCHEMA_VERSION,
};

/// I-1 / End-to-end: default corpus (50 synth + 5 real) over 5
/// iterations runs cleanly and produces a well-formed report.
#[test]
fn i1_default_corpus_five_iterations_runs_cleanly() {
    let corpus = default_corpus();
    let runner = BenchRunner::new();
    let report = runner
        .run_recompute_batch(&corpus, 5)
        .expect("default corpus must run");
    assert_eq!(report.batch_size, 55);
    assert_eq!(report.iterations, 5);
    assert_eq!(report.sample_count, 55 * 5);
    assert_eq!(report.real_fixture_count, 5);
    assert!(report.min_us <= report.p50_us);
    assert!(report.p50_us <= report.p95_us);
    assert!(report.p95_us <= report.p99_us);
    assert!(report.p99_us <= report.max_us);
    assert_eq!(report.schema_version, BENCH_REPORT_SCHEMA_VERSION);
}

/// I-2 / 1000-persona sweep: confirms the corpus size in the auftrag
/// is reachable without overflow or OOM. Uses a SINGLE iteration so
/// the test stays under ~1s on dev hardware (the full criterion
/// bench is what wants many iterations).
#[test]
fn i2_thousand_persona_sweep_completes() {
    let corpus = synthetic_corpus(1000);
    let runner = BenchRunner::new();
    let report = runner
        .run_recompute_batch(&corpus, 1)
        .expect("1000-persona sweep must run");
    assert_eq!(report.batch_size, 1000);
    assert_eq!(report.sample_count, 1000);
    assert_eq!(report.real_fixture_count, 0);
    // p99 must be finite-microseconds for plausible hardware.
    assert!(
        report.p99_us < 100_000,
        "p99 looks pathological: {}us",
        report.p99_us
    );
}

/// I-3 / JSON output schema: serialise the report and assert the
/// presence of every documented field. Locks the cross-lang contract
/// — the Python pendant must produce a JSON object with the SAME
/// keys (latency values may differ; the field set must not).
#[test]
fn i3_json_output_has_all_documented_fields() {
    let runner = BenchRunner::new();
    let report = runner
        .run_recompute_batch(&real_corpus(), 2)
        .expect("real corpus must run");
    let json = report.to_json();
    for key in [
        "batch_size",
        "iterations",
        "sample_count",
        "real_fixture_count",
        "min_us",
        "max_us",
        "p50_us",
        "p95_us",
        "p99_us",
        "total_us",
        "estimated_alloc_count",
        "schema_version",
    ] {
        assert!(
            json.contains(&format!("\"{key}\"")),
            "JSON output missing field {key}: {json}"
        );
    }
}

/// I-4 / Real corpus alone exercises every optional canonical-subset
/// key path. Every real fixture has `capabilities`, `domain`,
/// `reports_to`, and `identity_pinned`; running the bench on the real
/// corpus is a quick smoke that the optional-key lift in v907-verify
/// is not regressing.
#[test]
fn i4_real_corpus_each_fixture_hashes_to_distinct_pin() {
    use persona_engine_v907_verify::compute_v907_pin;
    use std::collections::HashSet;
    let real = real_corpus();
    let pins: HashSet<String> = real
        .iter()
        .map(|fx| {
            compute_v907_pin(&fx.bytes).unwrap_or_else(|e| panic!("hash {} failed: {e}", fx.slug))
        })
        .collect();
    assert_eq!(
        pins.len(),
        real.len(),
        "every real fixture must produce a distinct pin (no accidental dup-content)"
    );
}

/// I-5 / Total wall-clock total_us is at least as large as the sum of
/// per-call percentiles' mass — sanity check that the wall-clock timer
/// is not running backwards. Specifically: total_us >= p50_us
/// (always; the bench runs at least one call, the median call took
/// at most p50_us of the total).
#[test]
fn i5_total_wall_clock_consistent_with_per_call_percentiles() {
    let corpus = default_corpus();
    let runner = BenchRunner::new();
    let report = runner
        .run_recompute_batch(&corpus, 3)
        .expect("default corpus 3x");
    assert!(
        report.total_us >= report.p50_us,
        "total_us {} < p50_us {} — wall clock inconsistency",
        report.total_us,
        report.p50_us
    );
}
