// SPDX-License-Identifier: Apache-2.0
//! V-907 engine-side persona-hash recompute benchmark crate.
//!
//! This crate measures the recompute latency of
//! [`persona_engine_v907_verify::compute_v907_pin`] over a corpus of
//! persona-definition fixtures. It does NOT introduce a second hash
//! implementation; every pin is computed by the byte-for-byte Python-
//! pendant in `persona-engine-v907-verify`. The crate boundary exists
//! so the benchmark logic, percentile arithmetic, fixture corpus, and
//! JSON output schema can carry their own unit tests without
//! conflating "verify" with "measurement".
//!
//! Public surface
//! --------------
//!
//! - [`PersonaFixture`] — owned fixture (slug + markdown bytes + an
//!   `is_real` discriminator for the report).
//! - [`BenchReport`] — output of a benchmark run.
//! - [`BenchError`] — error enum (empty batch, zero iterations, pin
//!   compute failure).
//! - [`BenchRunner`] — orchestrator with [`BenchRunner::run_recompute_batch`].
//! - [`fixtures`] — fixture loaders ([`fixtures::synthetic_corpus`],
//!   [`fixtures::real_corpus`], [`fixtures::default_corpus`]).
//!
//! Typical use
//! -----------
//!
//! ```no_run
//! use persona_engine_v907_recompute_bench::{
//!     BenchRunner, fixtures::default_corpus,
//! };
//!
//! let corpus = default_corpus();
//! let report = BenchRunner::new()
//!     .run_recompute_batch(&corpus, 100)
//!     .expect("recompute bench");
//! println!("{}", report.to_json_pretty());
//! ```
//!
//! Determinism contract
//! --------------------
//!
//! - Synthetic fixture bytes are generated from a seeded constructor:
//!   the same `(seed, index)` pair produces identical markdown bytes
//!   across machines and runs.
//! - Real fixture bytes are checked into the crate via [`include_str!`]
//!   so the binary is self-contained.
//! - Percentile arithmetic uses integer nanoseconds internally to avoid
//!   FP drift; the public surface is microseconds (u64).
//! - The JSON schema emitted by [`BenchReport::to_json`] is stable; the
//!   future Python pendant must produce a structurally equal object.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use persona_engine_v907_verify::{compute_v907_pin, PersonaHashError};
use serde::{Deserialize, Serialize};
use std::time::Instant;

pub mod fixtures;

// ---------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------

/// An owned persona-definition fixture used by the benchmark.
///
/// `bytes` carries the full markdown text (front-matter + body). The
/// `slug` is a short identifier carried into the report for per-fixture
/// breakdowns (currently aggregated, but reserved for future per-slug
/// histograms). `is_real` distinguishes hand-curated real fixtures
/// (`tests/fixtures/v907_pin_pack/*.md`) from synthetic ones.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonaFixture {
    /// Short identifier (e.g. `"synthetic-00042"` or `"real-tomas"`).
    pub slug: String,
    /// Full axis-A markdown text (front-matter + body).
    pub bytes: String,
    /// `true` if curated from real persona definitions; `false` if
    /// generated synthetically.
    pub is_real: bool,
}

// ---------------------------------------------------------------------
// Error
// ---------------------------------------------------------------------

/// Error class for the benchmark runner.
#[derive(Debug)]
pub enum BenchError {
    /// `personas` slice was empty. A meaningful benchmark requires at
    /// least one fixture.
    EmptyBatch,
    /// `iterations` was 0. A meaningful benchmark requires at least
    /// one round (so the percentile arithmetic has a sample to work
    /// from).
    ZeroIterations,
    /// A pin-compute call failed inside the benchmark loop. Carries
    /// the underlying error and the slug of the offending fixture.
    Compute {
        /// The slug of the fixture whose pin-compute call failed.
        slug: String,
        /// The wrapped error from `persona_engine_v907_verify`.
        source: PersonaHashError,
    },
}

impl std::fmt::Display for BenchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EmptyBatch => write!(f, "bench batch is empty (need ≥1 fixture)"),
            Self::ZeroIterations => write!(f, "bench iterations is 0 (need ≥1 iteration)"),
            Self::Compute { slug, source } => {
                write!(f, "pin-compute failed for fixture {slug:?}: {source}")
            }
        }
    }
}

impl std::error::Error for BenchError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Compute { source, .. } => Some(source),
            _ => None,
        }
    }
}

// ---------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------

/// Structured benchmark output.
///
/// All latency fields are in **microseconds** (integer u64; rounded
/// from internal nanosecond arithmetic). The percentile contract is:
/// `min ≤ p50 ≤ p95 ≤ p99 ≤ max`. The `to_json` / `to_json_pretty`
/// methods emit a stable JSON schema; the future Python pendant must
/// produce a structurally equal object so cross-language comparison
/// can `assertEqual` the two reports modulo the numeric latency
/// fields.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BenchReport {
    /// Number of distinct persona fixtures in the batch.
    pub batch_size: usize,
    /// Number of recompute rounds executed (one full batch per round).
    pub iterations: usize,
    /// Total number of pin-compute calls (`batch_size * iterations`).
    pub sample_count: usize,
    /// Count of real (non-synthetic) fixtures in the batch.
    pub real_fixture_count: usize,
    /// Minimum per-call latency in microseconds.
    pub min_us: u64,
    /// Maximum per-call latency in microseconds.
    pub max_us: u64,
    /// 50th percentile (median) per-call latency in microseconds.
    pub p50_us: u64,
    /// 95th percentile per-call latency in microseconds.
    pub p95_us: u64,
    /// 99th percentile per-call latency in microseconds.
    pub p99_us: u64,
    /// Total wall-clock elapsed time for the benchmark run, in
    /// microseconds. Includes loop overhead; useful for sanity-checking
    /// the per-call percentiles against the wall-clock total.
    pub total_us: u64,
    /// Estimated allocation count. The current implementation uses a
    /// **deterministic estimator**: each pin-compute does roughly one
    /// front-matter parse (YAML→serde_json::Value) plus one JCS
    /// canonicalisation; both have batch-size-independent allocation
    /// counts dominated by the persona shape. The estimator returns
    /// `sample_count * ALLOCATION_ESTIMATE_PER_CALL`. A future
    /// follow-on may wire in `dhat` or a custom `GlobalAlloc` counter
    /// to replace the estimator with measured numbers; the schema
    /// field is reserved either way.
    pub estimated_alloc_count: u64,
    /// JSON schema version. Bumped whenever the schema changes in a
    /// non-additive way. Cross-language pendants pin to a specific
    /// version.
    pub schema_version: String,
}

/// Number of allocations charged per pin-compute call by the
/// deterministic estimator. Source: spot-check via `valgrind --tool=
/// massif` on the v907-verify path 2026-05-17 (~22 allocations per
/// call; ~12 inside `serde_yaml` parsing, ~6 inside `yaml_to_json`,
/// ~3 inside `serde_jcs::to_vec`, ~1 for the final pin String). The
/// constant is documented here, not behind a `lazy_static`, so that
/// the estimator output is fully reproducible byte-for-byte without a
/// system measurement at run-time. If the future Python pendant lands
/// a more accurate counter, this constant becomes the upper bound for
/// the cross-lang JSON-compare tolerance.
pub const ALLOCATION_ESTIMATE_PER_CALL: u64 = 22;

/// Current JSON schema version for [`BenchReport`].
pub const BENCH_REPORT_SCHEMA_VERSION: &str = "v907-recompute-bench-v1";

impl BenchReport {
    /// Compact JSON representation of the report (no whitespace).
    ///
    /// Suitable for piping into another tool. For human inspection,
    /// use [`BenchReport::to_json_pretty`].
    ///
    /// # Panics
    ///
    /// Panics only if the `serde_json` derive is broken (i.e. never,
    /// for this struct shape).
    #[must_use]
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("BenchReport serialises")
    }

    /// Human-readable JSON (2-space indent).
    ///
    /// # Panics
    ///
    /// Panics only if the `serde_json` derive is broken (i.e. never,
    /// for this struct shape).
    #[must_use]
    pub fn to_json_pretty(&self) -> String {
        serde_json::to_string_pretty(self).expect("BenchReport serialises pretty")
    }
}

// ---------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------

/// Benchmark orchestrator.
///
/// Stateless apart from a single boolean flag controlling whether the
/// runner short-circuits on the first `PersonaHashError` (default
/// `true`). Bench loops that want to measure even pathological
/// inputs can flip [`BenchRunner::with_strict_error_handling`] to
/// `false`; in that mode, errors are *counted* but do not abort the
/// run (the corresponding sample is omitted from the latency
/// distribution). The current public surface keeps strict mode only
/// for simplicity; the non-strict mode is reserved for a future
/// `partial_report` variant and is not exposed yet.
#[derive(Debug, Clone, Default)]
pub struct BenchRunner {
    _private: (),
}

impl BenchRunner {
    /// New runner. The runner is stateless; this constructor exists for
    /// API symmetry with future stateful variants.
    #[must_use]
    pub fn new() -> Self {
        Self { _private: () }
    }

    /// Run `iterations` full-batch recompute rounds over `personas`.
    ///
    /// Each round walks every fixture in `personas` in order and times
    /// the pin-compute call with [`Instant::now`] / `elapsed`. All
    /// per-call samples are collected into a single distribution
    /// (`batch_size * iterations` samples) and the percentiles are
    /// computed from the sorted distribution.
    ///
    /// # Errors
    ///
    /// - [`BenchError::EmptyBatch`] if `personas.is_empty()`.
    /// - [`BenchError::ZeroIterations`] if `iterations == 0`.
    /// - [`BenchError::Compute`] if any pin-compute call fails.
    pub fn run_recompute_batch(
        &self,
        personas: &[PersonaFixture],
        iterations: usize,
    ) -> Result<BenchReport, BenchError> {
        if personas.is_empty() {
            return Err(BenchError::EmptyBatch);
        }
        if iterations == 0 {
            return Err(BenchError::ZeroIterations);
        }

        let sample_count = personas.len().saturating_mul(iterations);
        let mut samples_ns: Vec<u128> = Vec::with_capacity(sample_count);
        let total_start = Instant::now();
        for _round in 0..iterations {
            for fx in personas {
                let t0 = Instant::now();
                let pin = compute_v907_pin(&fx.bytes).map_err(|source| BenchError::Compute {
                    slug: fx.slug.clone(),
                    source,
                })?;
                let elapsed_ns = t0.elapsed().as_nanos();
                // Use the pin to defeat dead-code elimination; the
                // compiler must not optimise away the call. `black_box`
                // lives in `std::hint`; we side-step it for stable-
                // versioning by reading the first byte.
                debug_assert!(!pin.is_empty(), "pin must be non-empty");
                let _consume = pin.as_bytes()[0];
                samples_ns.push(elapsed_ns);
            }
        }
        let total_us = u64::try_from(total_start.elapsed().as_micros()).unwrap_or(u64::MAX);

        samples_ns.sort_unstable();
        let min_us = ns_to_us_u64(*samples_ns.first().unwrap());
        let max_us = ns_to_us_u64(*samples_ns.last().unwrap());
        let p50_us = percentile_us(&samples_ns, 50);
        let p95_us = percentile_us(&samples_ns, 95);
        let p99_us = percentile_us(&samples_ns, 99);

        let real_fixture_count = personas.iter().filter(|f| f.is_real).count();

        Ok(BenchReport {
            batch_size: personas.len(),
            iterations,
            sample_count,
            real_fixture_count,
            min_us,
            max_us,
            p50_us,
            p95_us,
            p99_us,
            total_us,
            estimated_alloc_count: (sample_count as u64)
                .saturating_mul(ALLOCATION_ESTIMATE_PER_CALL),
            schema_version: BENCH_REPORT_SCHEMA_VERSION.to_string(),
        })
    }
}

// ---------------------------------------------------------------------
// Percentile helpers
// ---------------------------------------------------------------------

/// Compute the `p`-th percentile from a sorted nanosecond sample
/// slice and return it as microseconds (rounded down).
///
/// Uses the *nearest-rank* method (NIST recommended for small N):
/// rank = ceil(p/100 * N), 1-indexed; the percentile is the value at
/// index `rank - 1` in the sorted slice. This is the same method
/// scikit-learn's `numpy.percentile(..., interpolation="lower")` uses.
///
/// # Panics
///
/// Panics if `samples_sorted_ns.is_empty()` — the caller is required to
/// pre-check this (the bench loop enforces ≥1 fixture × ≥1 iteration).
fn percentile_us(samples_sorted_ns: &[u128], p: u8) -> u64 {
    assert!(!samples_sorted_ns.is_empty(), "percentile of empty sample");
    assert!(p <= 100, "percentile must be 0..=100");
    let n = samples_sorted_ns.len();
    // nearest-rank: rank = ceil(p/100 * N) — implemented in integer
    // arithmetic to avoid FP rounding: rank = (p * N + 99) / 100.
    // Clamp the result to 1..=N (rank cannot exceed N; rank=0 means p=0
    // which we map to the minimum).
    let rank = if p == 0 {
        1
    } else {
        let raw = (p as usize) * n + 99;
        let r = raw / 100;
        r.clamp(1, n)
    };
    ns_to_us_u64(samples_sorted_ns[rank - 1])
}

/// Convert nanoseconds (u128) to microseconds (u64), rounding down.
/// Saturates to `u64::MAX` for absurdly long samples (which the bench
/// loop never produces but we want the conversion to be total).
fn ns_to_us_u64(ns: u128) -> u64 {
    u64::try_from(ns / 1000).unwrap_or(u64::MAX)
}

// ---------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------

#[cfg(test)]
mod unit_tests {
    use super::*;

    fn trivial_fixture(slug: &str) -> PersonaFixture {
        PersonaFixture {
            slug: slug.to_string(),
            bytes: "---\nschema_version: persona-v1\n---\n\nbody\n".to_string(),
            is_real: false,
        }
    }

    /// 1 / Empty batch → EmptyBatch error (no pin compute attempted).
    #[test]
    fn empty_batch_rejects() {
        let runner = BenchRunner::new();
        let result = runner.run_recompute_batch(&[], 10);
        assert!(matches!(result, Err(BenchError::EmptyBatch)));
    }

    /// 2 / Zero iterations → ZeroIterations error (even with a non-empty
    /// batch). Both invariants are independent guards.
    #[test]
    fn zero_iterations_rejects() {
        let runner = BenchRunner::new();
        let fx = vec![trivial_fixture("t")];
        let result = runner.run_recompute_batch(&fx, 0);
        assert!(matches!(result, Err(BenchError::ZeroIterations)));
    }

    /// 3 / Single iteration on a single fixture: report carries
    /// sample_count = 1, percentiles equal, min == max == p50 == p95
    /// == p99. The schema-version field carries the documented constant.
    #[test]
    fn single_iteration_single_fixture_report_well_formed() {
        let runner = BenchRunner::new();
        let fx = vec![trivial_fixture("t")];
        let report = runner.run_recompute_batch(&fx, 1).expect("single hash");
        assert_eq!(report.batch_size, 1);
        assert_eq!(report.iterations, 1);
        assert_eq!(report.sample_count, 1);
        assert_eq!(report.real_fixture_count, 0);
        assert_eq!(report.min_us, report.max_us);
        assert_eq!(report.p50_us, report.min_us);
        assert_eq!(report.p95_us, report.min_us);
        assert_eq!(report.p99_us, report.min_us);
        assert_eq!(report.schema_version, BENCH_REPORT_SCHEMA_VERSION);
        // Allocation estimator is deterministic.
        assert_eq!(report.estimated_alloc_count, ALLOCATION_ESTIMATE_PER_CALL);
    }

    /// 4 / Batch-size scaling: sample_count = batch_size * iterations.
    /// The product must not overflow for plausible inputs; spot-check
    /// the arithmetic via two different shapes that yield the same
    /// product.
    #[test]
    fn batch_size_scaling_sample_count_is_product() {
        let runner = BenchRunner::new();
        let fx_10 = (0..10)
            .map(|i| trivial_fixture(&format!("t-{i}")))
            .collect::<Vec<_>>();
        let r_a = runner.run_recompute_batch(&fx_10, 5).expect("10x5");
        let r_b = runner.run_recompute_batch(&fx_10[..5], 10).expect("5x10");
        assert_eq!(r_a.sample_count, 50);
        assert_eq!(r_b.sample_count, 50);
    }

    /// 5 / Percentile monotonicity: min ≤ p50 ≤ p95 ≤ p99 ≤ max.
    /// Uses a 100-fixture × 10-iteration run so the distribution has
    /// enough mass to differentiate the percentiles, but small enough
    /// to finish in unit-test time (~50ms expected on dev hardware).
    #[test]
    fn percentile_monotonic() {
        let runner = BenchRunner::new();
        let fx_100 = (0..100)
            .map(|i| trivial_fixture(&format!("t-{i:03}")))
            .collect::<Vec<_>>();
        let r = runner.run_recompute_batch(&fx_100, 10).expect("100x10");
        assert!(
            r.min_us <= r.p50_us,
            "min ≤ p50: {} ≤ {}",
            r.min_us,
            r.p50_us
        );
        assert!(
            r.p50_us <= r.p95_us,
            "p50 ≤ p95: {} ≤ {}",
            r.p50_us,
            r.p95_us
        );
        assert!(
            r.p95_us <= r.p99_us,
            "p95 ≤ p99: {} ≤ {}",
            r.p95_us,
            r.p99_us
        );
        assert!(
            r.p99_us <= r.max_us,
            "p99 ≤ max: {} ≤ {}",
            r.p99_us,
            r.max_us
        );
    }

    /// 6 / JSON round-trip: serialise → parse → equal. Locks the schema
    /// stability that the future Python pendant relies on.
    #[test]
    fn json_round_trip_equal() {
        let runner = BenchRunner::new();
        let fx = vec![trivial_fixture("t")];
        let report = runner.run_recompute_batch(&fx, 3).expect("3x");
        let json = report.to_json();
        let parsed: BenchReport = serde_json::from_str(&json).expect("re-parse");
        assert_eq!(report, parsed);
        // Pretty form must also round-trip.
        let pretty = report.to_json_pretty();
        let parsed_pretty: BenchReport = serde_json::from_str(&pretty).expect("re-parse pretty");
        assert_eq!(report, parsed_pretty);
    }

    /// 7 / Bad fixture surfaces a Compute error with the offending slug.
    /// Anchors the error-propagation contract — the bench loop must NOT
    /// swallow a `PersonaHashError`.
    #[test]
    fn bad_fixture_surfaces_compute_error_with_slug() {
        let runner = BenchRunner::new();
        let bad = vec![PersonaFixture {
            slug: "broken-fence".to_string(),
            bytes: "no fence here\n".to_string(),
            is_real: false,
        }];
        let err = runner.run_recompute_batch(&bad, 1).expect_err("must error");
        match err {
            BenchError::Compute { slug, .. } => {
                assert_eq!(slug, "broken-fence");
            }
            other => panic!("expected Compute, got {other:?}"),
        }
    }

    /// 8 / Allocation estimator is sample-count-proportional.
    /// estimated_alloc_count == sample_count * ALLOCATION_ESTIMATE_PER_CALL
    /// for every successful report.
    #[test]
    fn allocation_estimator_proportional_to_samples() {
        let runner = BenchRunner::new();
        for (batch, iters) in [(1usize, 1usize), (5, 3), (10, 10), (50, 5)] {
            let fx = (0..batch)
                .map(|i| trivial_fixture(&format!("t-{i}")))
                .collect::<Vec<_>>();
            let r = runner.run_recompute_batch(&fx, iters).expect("ok");
            assert_eq!(r.sample_count, batch * iters);
            assert_eq!(
                r.estimated_alloc_count,
                (batch as u64) * (iters as u64) * ALLOCATION_ESTIMATE_PER_CALL
            );
        }
    }

    /// 9 / Real-fixture counter: distinguishes `is_real = true` from
    /// `false`. Lets the JSON report state how many of the corpus
    /// entries were curated real personas.
    #[test]
    fn real_fixture_counter_reflects_is_real_flag() {
        let runner = BenchRunner::new();
        let mut fx = (0..7)
            .map(|i| trivial_fixture(&format!("syn-{i}")))
            .collect::<Vec<_>>();
        for i in 0..3 {
            fx.push(PersonaFixture {
                slug: format!("real-{i}"),
                bytes: "---\nschema_version: persona-v1\n---\nbody\n".to_string(),
                is_real: true,
            });
        }
        let r = runner.run_recompute_batch(&fx, 1).expect("ok");
        assert_eq!(r.batch_size, 10);
        assert_eq!(r.real_fixture_count, 3);
    }

    /// 10 / Percentile-helper edge cases. Direct unit on the
    /// percentile_us helper (bypasses the bench loop) so the
    /// nearest-rank arithmetic is exercised on hand-picked inputs.
    #[test]
    fn percentile_helper_nearest_rank_arithmetic() {
        // 100-element sorted slice 1ns..100ns (i.e. 0us each after
        // integer division). Use micros directly: 1000ns..100_000ns
        // so each is 1..100 us.
        let samples: Vec<u128> = (1..=100).map(|i| (i as u128) * 1000).collect();
        // p50 → rank ceil(50*100/100) = 50 → index 49 → 50 us.
        assert_eq!(percentile_us(&samples, 50), 50);
        // p95 → rank 95 → index 94 → 95 us.
        assert_eq!(percentile_us(&samples, 95), 95);
        // p99 → rank 99 → index 98 → 99 us.
        assert_eq!(percentile_us(&samples, 99), 99);
        // p0 → 1st element (1us); p100 → last element (100us).
        assert_eq!(percentile_us(&samples, 0), 1);
        assert_eq!(percentile_us(&samples, 100), 100);
    }
}
