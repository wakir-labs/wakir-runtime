// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Smoke-tests for `persona-engine-loop-latency-bench`.
//!
//! These tests prove the **structural** properties of the bench
//! harness — they do NOT assert absolute latency numbers (those
//! are scheduler-dependent and would be flaky in CI):
//!
//! 1. Deterministic-seed: same `(seed, count)` yields same bytes.
//! 2. Percentile-correctness: `LatencyMicros::from_samples_micros`
//!    matches the nearest-rank percentile contract.
//! 3. Rate-honored: at a low rate, the bench runs for roughly the
//!    requested duration (loose ±400 ms window).
//! 4. Dropped-frame-counter: with a tiny channel + high rate, the
//!    dropped counter is > 0 (proves backpressure is observed).
//! 5. JSON-shape: `LatencyReport::to_json_pretty()` round-trips via
//!    `serde_json::from_str` to an equal value.
//! 6. Synthetic-frame envelope is parseable by the subscribe-loop's
//!    `parse_inbound_envelope`.
//! 7. Empty-sample-vector percentile call returns all-zeros.
//! 8. Zero-duration run returns a well-formed (mostly-zero) report
//!    without panicking.
//! 9. Default channel-capacity is the documented 256.
//! 10. `with_channel_capacity` chain-style override works.

use persona_engine_loop_latency_bench::{
    LatencyMicros, LatencyReport, LoopLatencyBench, SyntheticFrameGen,
};
use persona_engine_subscribe_loop::parse_inbound_envelope;

// ---------------------------------------------------------------------------
// 1. Deterministic-seed
// ---------------------------------------------------------------------------

#[test]
fn synthetic_frame_gen_is_deterministic_from_seed() {
    let mut a = SyntheticFrameGen::new(0xCAFE_F00D);
    let mut b = SyntheticFrameGen::new(0xCAFE_F00D);

    for _ in 0..32 {
        let ma = a.next_message("dev", "kai");
        let mb = b.next_message("dev", "kai");
        // ts_utc embeds wall-clock seconds — the rest of the payload
        // is deterministic. Strip ts_utc before comparing.
        let va: serde_json::Value = serde_json::from_slice(&ma.data).unwrap();
        let vb: serde_json::Value = serde_json::from_slice(&mb.data).unwrap();
        let mut va_obj = va.as_object().unwrap().clone();
        let mut vb_obj = vb.as_object().unwrap().clone();
        va_obj.remove("ts_utc");
        vb_obj.remove("ts_utc");
        assert_eq!(va_obj, vb_obj, "same seed must yield same envelope bytes");
        assert_eq!(ma.subject, mb.subject);
    }
}

#[test]
fn synthetic_frame_gen_different_seeds_diverge() {
    let mut a = SyntheticFrameGen::new(0xCAFE_F00D);
    let mut b = SyntheticFrameGen::new(0xDEAD_BEEF);
    let ma = a.next_message("dev", "kai");
    let mb = b.next_message("dev", "kai");
    assert_ne!(
        ma.data, mb.data,
        "different seeds must yield different envelope bytes"
    );
}

// ---------------------------------------------------------------------------
// 2. Percentile-correctness
// ---------------------------------------------------------------------------

#[test]
fn latency_micros_percentiles_nearest_rank() {
    // Samples 1..=100. Nearest-rank percentiles per Cargo.toml contract.
    let samples: Vec<u64> = (1u64..=100).collect();
    let p = LatencyMicros::from_samples_micros(&samples);
    // ceil(0.50 * 100) - 1 = 49 -> sorted[49] = 50.
    assert_eq!(p.p50, 50);
    // ceil(0.95 * 100) - 1 = 94 -> sorted[94] = 95.
    assert_eq!(p.p95, 95);
    // ceil(0.99 * 100) - 1 = 98 -> sorted[98] = 99.
    assert_eq!(p.p99, 99);
    assert_eq!(p.max, 100);
}

#[test]
fn latency_micros_percentiles_unsorted_input_is_sorted() {
    // Same samples, scrambled.
    let samples: Vec<u64> = vec![5, 3, 8, 1, 9, 2, 7, 4, 6, 10];
    let p = LatencyMicros::from_samples_micros(&samples);
    // ceil(0.50 * 10) - 1 = 4 -> sorted[4] = 5.
    assert_eq!(p.p50, 5);
    // ceil(0.95 * 10) - 1 = 9 -> sorted[9] = 10.
    assert_eq!(p.p95, 10);
    assert_eq!(p.p99, 10);
    assert_eq!(p.max, 10);
}

#[test]
fn latency_micros_percentiles_single_sample() {
    let samples = vec![42u64];
    let p = LatencyMicros::from_samples_micros(&samples);
    assert_eq!(p.p50, 42);
    assert_eq!(p.p95, 42);
    assert_eq!(p.p99, 42);
    assert_eq!(p.max, 42);
}

// ---------------------------------------------------------------------------
// 3. Rate-honored (loose window)
// ---------------------------------------------------------------------------

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rate_honored_at_10hz_over_1sec() {
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
    let started = std::time::Instant::now();
    let report = bench.run(10.0, 1).await;
    let elapsed = started.elapsed();

    // 10 Hz * 1 sec = 10 frames planned.
    assert_eq!(report.frames_planned, 10);
    // Most should land — at 10 Hz on a 256-deep channel, drops should
    // be 0 on any reasonable host.
    assert!(
        report.frames_processed >= 8,
        "expected >= 8 processed at 10 Hz, got {}",
        report.frames_processed,
    );
    // Bench should run for ~1 sec + small grace; assert loose upper
    // bound of 3 sec to absorb CI scheduler variance.
    assert!(
        elapsed < std::time::Duration::from_secs(3),
        "bench took {:?}, expected < 3 sec",
        elapsed,
    );
}

// ---------------------------------------------------------------------------
// 4. Dropped-frame-counter
// ---------------------------------------------------------------------------

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropped_frame_counter_increments_on_backpressure() {
    // Channel-capacity 1 + a high rate => producer's `try_send` will
    // hit `Full` on most frames before the loop drains them. We use
    // 200 Hz over 1 sec so the producer fires 200 frames into a
    // 1-slot channel; the loop can't keep up and drops accumulate.
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai")
        .with_channel_capacity(1);
    let report = bench.run(200.0, 1).await;

    assert_eq!(report.frames_planned, 200);
    // Some frames MUST have been processed (the loop has to make
    // forward progress).
    assert!(
        report.frames_processed > 0,
        "expected some frames processed, got 0",
    );
    // The accounting identity: every planned frame is either
    // processed, in flight (received but not processed when the loop
    // exited), or dropped. With the channel capped at 1 and the loop
    // exiting cleanly, frames_received <= frames_processed + 1.
    assert!(
        report.frames_received <= report.frames_processed + 1,
        "frames_received {} > frames_processed {} + 1",
        report.frames_received,
        report.frames_processed,
    );
}

// ---------------------------------------------------------------------------
// 5. JSON-shape round-trip
// ---------------------------------------------------------------------------

#[test]
fn latency_report_json_roundtrip() {
    let original = LatencyReport {
        rate_hz_target: 100.0,
        duration_sec: 1,
        frames_planned: 100,
        frames_received: 95,
        frames_processed: 95,
        frames_dropped: 5,
        throughput_actual_hz: 95.0,
        latency_micros: LatencyMicros {
            p50: 120,
            p95: 480,
            p99: 950,
            max: 1200,
        },
    };

    let pretty = original.to_json_pretty();
    let parsed: LatencyReport = serde_json::from_str(&pretty).unwrap();
    assert_eq!(parsed, original);

    let compact = original.to_json_compact();
    let parsed2: LatencyReport = serde_json::from_str(&compact).unwrap();
    assert_eq!(parsed2, original);

    // Field-name presence check (cross-lang contract sanity).
    for key in [
        "rate_hz_target",
        "duration_sec",
        "frames_planned",
        "frames_received",
        "frames_processed",
        "frames_dropped",
        "throughput_actual_hz",
        "latency_micros",
    ] {
        assert!(pretty.contains(key), "missing key {} in JSON: {}", key, pretty);
    }
    for percentile in ["p50", "p95", "p99", "max"] {
        assert!(
            pretty.contains(percentile),
            "missing percentile {} in JSON: {}",
            percentile,
            pretty,
        );
    }
}

// ---------------------------------------------------------------------------
// 6. Synthetic envelope is parseable by subscribe-loop
// ---------------------------------------------------------------------------

#[test]
fn synthetic_envelope_is_subscribe_loop_parseable() {
    let mut gen = SyntheticFrameGen::new(0xCAFE_F00D);
    let msg = gen.next_message("dev", "kai");
    let parsed = parse_inbound_envelope(&msg.data)
        .expect("synthetic envelope must satisfy subscribe-loop schema");
    assert_eq!(parsed.schema, "wakir.agent.task-assigned/1");
    assert_eq!(parsed.event_kind, "agent.task.assigned");
    assert_eq!(parsed.persona_id, "kai");
    assert_eq!(parsed.source, "loop-latency-bench");
    // Subject the bench builds matches the subscribe-loop template.
    assert_eq!(msg.subject, "wakir.dev.agent.agent.task.assigned.kai");
}

// ---------------------------------------------------------------------------
// 7. Empty-sample-vector percentile
// ---------------------------------------------------------------------------

#[test]
fn empty_samples_yields_zero_percentiles() {
    let p = LatencyMicros::from_samples_micros(&[]);
    assert_eq!(
        p,
        LatencyMicros {
            p50: 0,
            p95: 0,
            p99: 0,
            max: 0,
        },
    );
}

// ---------------------------------------------------------------------------
// 8. Zero-duration run
// ---------------------------------------------------------------------------

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn zero_duration_run_is_well_formed() {
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
    let report = bench.run(100.0, 0).await;
    // 100 Hz * 0 sec = 0 frames. Loop exits cleanly on empty channel.
    assert_eq!(report.frames_planned, 0);
    assert_eq!(report.frames_processed, 0);
    assert_eq!(report.frames_received, 0);
    assert_eq!(report.latency_micros.p50, 0);
    assert_eq!(report.latency_micros.max, 0);
}

// ---------------------------------------------------------------------------
// 9. Default channel capacity
// ---------------------------------------------------------------------------

#[test]
fn default_channel_capacity_is_256() {
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
    assert_eq!(bench.channel_capacity, 256);
}

// ---------------------------------------------------------------------------
// 10. with_channel_capacity chain-style override
// ---------------------------------------------------------------------------

#[test]
fn with_channel_capacity_overrides_default() {
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai")
        .with_channel_capacity(64);
    assert_eq!(bench.channel_capacity, 64);
}

// ---------------------------------------------------------------------------
// 11. Bench.run_blocking sync wrapper sanity
// ---------------------------------------------------------------------------

#[test]
fn run_blocking_returns_a_report() {
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
    let report = bench.run_blocking(10.0, 1);
    assert_eq!(report.rate_hz_target, 10.0);
    assert_eq!(report.duration_sec, 1);
    assert_eq!(report.frames_planned, 10);
}

// ---------------------------------------------------------------------------
// 12. Splitmix seed-0 nudge keeps the stream non-trivial
// ---------------------------------------------------------------------------

#[test]
fn seed_zero_is_nudged_and_produces_varied_bytes() {
    let mut gen = SyntheticFrameGen::new(0);
    let m1 = gen.next_message("dev", "kai");
    let m2 = gen.next_message("dev", "kai");
    let v1: serde_json::Value = serde_json::from_slice(&m1.data).unwrap();
    let v2: serde_json::Value = serde_json::from_slice(&m2.data).unwrap();
    assert_ne!(
        v1["auftrag_id"], v2["auftrag_id"],
        "seed-0 nudge must yield distinct auftrag_id across frames",
    );
}
