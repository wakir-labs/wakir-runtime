// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Criterion bench harness for `persona-engine-loop-latency-bench`.
//!
//! Three benches at the documented rates (10 Hz / 100 Hz / 1000 Hz),
//! each over a 1-second window. The bench-body invokes
//! [`LoopLatencyBench::run_blocking`] and consumes the returned
//! `LatencyReport` via `criterion::black_box` so the optimiser does
//! not elide the work.
//!
//! Execution model
//! ---------------
//! CI does NOT run `cargo bench` — it only verifies that the bench
//! file COMPILES (`cargo build --benches`). Bench execution is
//! operator-hand (`cargo bench -p persona-engine-loop-latency-bench`).
//! This matches the Sprint-Auftrag hard-constraint that criterion
//! benches must not run in CI (they're inherently scheduler-sensitive
//! and would be flaky).
//!
//! Why `sample_size = 10`
//! ----------------------
//! Each bench iteration runs a 1-second subscribe-loop driver. With
//! criterion's default sample-size of 100, a single bench would take
//! 100+ seconds. 10 samples per rate keeps the full three-rate run
//! at ~30 sec total — fast enough for an operator dev-loop, still
//! enough samples for criterion's confidence-interval maths to be
//! useful.

use std::hint::black_box;
use std::time::Duration;

use criterion::{criterion_group, criterion_main, Criterion};

use persona_engine_loop_latency_bench::LoopLatencyBench;

fn bench_at_rate(c: &mut Criterion, label: &str, rate_hz: f64) {
    let mut group = c.benchmark_group("loop_latency");
    group.sample_size(10);
    group.measurement_time(Duration::from_secs(15));
    group.bench_function(label, |b| {
        b.iter(|| {
            let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
            let report = bench.run_blocking(black_box(rate_hz), black_box(1));
            black_box(report)
        });
    });
    group.finish();
}

fn bench_10hz(c: &mut Criterion) {
    bench_at_rate(c, "10hz_1sec", 10.0);
}

fn bench_100hz(c: &mut Criterion) {
    bench_at_rate(c, "100hz_1sec", 100.0);
}

fn bench_1000hz(c: &mut Criterion) {
    bench_at_rate(c, "1000hz_1sec", 1000.0);
}

criterion_group!(benches, bench_10hz, bench_100hz, bench_1000hz);
criterion_main!(benches);
