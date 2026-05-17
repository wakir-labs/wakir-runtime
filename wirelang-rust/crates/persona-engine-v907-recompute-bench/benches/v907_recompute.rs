// SPDX-License-Identifier: Apache-2.0
//! Criterion benchmark for the V-907 engine-side persona-hash
//! recompute path.
//!
//! Two scenarios are measured:
//!
//! 1. `recompute_single_synthetic` — a single synthetic persona
//!    pin-compute. Pure micro-bench; useful for tracking per-call
//!    regressions without batch overhead noise.
//! 2. `recompute_1000_synthetic` — the 1000-persona synthetic corpus
//!    sweep (one round). Matches the auftrag's "1000 fixture personas"
//!    measurement target. Criterion auto-tunes iteration counts.
//!
//! Cross-language compare
//! ----------------------
//! Criterion's default output goes to `target/criterion/<group>/`.
//! For the cross-lang Python-pendant compare (Phase-3a Modul 15), the
//! `BenchRunner::run_recompute_batch` API in this crate produces a
//! JSON [`BenchReport`] that the Python side will mirror. Criterion's
//! output is engineer-facing; the JSON report is the cross-lang
//! contract.
//!
//! CI policy
//! ---------
//! This bench binary is NOT executed in CI; the existing wakir-runtime
//! production CI workflow (`tests.yml`) compiles the workspace but does
//! not invoke `cargo bench`. Criterion-driven measurement runs locally
//! only. To run:
//!
//! ```bash
//! CARGO_TARGET_DIR=/var/home/fred/AI-Corp/.cargo-target-runtime-tomas-tag13 \
//!   cargo bench -p persona-engine-v907-recompute-bench
//! ```

use criterion::{black_box, criterion_group, criterion_main, Criterion};
use persona_engine_v907_recompute_bench::{
    fixtures::{synthetic_corpus, synthetic_persona},
    BenchRunner,
};
use persona_engine_v907_verify::compute_v907_pin;

fn bench_recompute_single_synthetic(c: &mut Criterion) {
    let fx = synthetic_persona(42);
    c.bench_function("recompute_single_synthetic", |b| {
        b.iter(|| {
            let pin = compute_v907_pin(black_box(&fx.bytes)).expect("synthetic must hash");
            black_box(pin);
        })
    });
}

fn bench_recompute_1000_synthetic(c: &mut Criterion) {
    let corpus = synthetic_corpus(1000);
    let runner = BenchRunner::new();
    c.bench_function("recompute_1000_synthetic_one_round", |b| {
        b.iter(|| {
            let report = runner
                .run_recompute_batch(black_box(&corpus), 1)
                .expect("1000-persona batch must hash");
            black_box(report);
        })
    });
}

criterion_group!(
    benches,
    bench_recompute_single_synthetic,
    bench_recompute_1000_synthetic
);
criterion_main!(benches);
