// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine Subscribe-Loop Latency Bench — Phase-3a Item 15 (LAST).
//!
//! End-to-end latency benchmark for the NATS Subscribe-Loop crate
//! (`persona-engine-subscribe-loop`, Phase-3a Item 4, PR #132).
//!
//! See the crate-level `Cargo.toml` comment for the rationale block,
//! the cross-lang JSON shape contract, and the hard-constraint list.
//!
//! Public surface
//! --------------
//!
//! - [`LoopLatencyBench`] — the bench harness. Construct with a seed +
//!   target rate + duration, then call [`LoopLatencyBench::run`] to
//!   drive the subscribe-loop and collect per-frame timings.
//! - [`LatencyReport`] — the cross-lang JSON-comparable result. Carries
//!   p50/p95/p99/max latency in **microseconds**, throughput-actual-Hz,
//!   and dropped-frames count.
//! - [`SyntheticFrameGen`] — the deterministic envelope-bytes generator
//!   the bench feeds the loop. Same `(seed, count)` -> same bytes.
//!
//! Determinism note
//! ----------------
//! The bench's *output bytes* (envelope payload) are deterministic; the
//! *timing numbers* are inherently non-deterministic (they depend on
//! the host's scheduler). Unit-tests therefore test the structural
//! properties (frame-count, dropped-frame-counter monotonicity,
//! percentile maths on a synthetic sample-vector) — not absolute
//! latency numbers.

use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;

use persona_engine_subscribe_loop::{
    run_subscribe_loop_with_timeout, HandlerError, HandlerFuture, MessageHandler,
    ParsedEnvelope, SubscribeLoopConfig, SubscribeMessage,
};

// ---------------------------------------------------------------------------
// Latency report (cross-lang JSON shape)
// ---------------------------------------------------------------------------

/// Microsecond-precision latency percentiles for a bench run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LatencyMicros {
    pub p50: u64,
    pub p95: u64,
    pub p99: u64,
    pub max: u64,
}

impl LatencyMicros {
    /// Compute percentiles from a sample-vector (microsecond
    /// durations). The vector is cloned + sorted before percentile
    /// extraction. An empty input yields all-zeros.
    pub fn from_samples_micros(samples: &[u64]) -> Self {
        if samples.is_empty() {
            return Self {
                p50: 0,
                p95: 0,
                p99: 0,
                max: 0,
            };
        }
        let mut sorted: Vec<u64> = samples.to_vec();
        sorted.sort_unstable();
        let n = sorted.len();
        let pick = |q: f64| -> u64 {
            // Nearest-rank percentile (inclusive). `q` is a fraction
            // 0..=1. Index = ceil(q * n) - 1, clamped to [0, n-1].
            let idx = ((q * n as f64).ceil() as usize).saturating_sub(1);
            sorted[idx.min(n - 1)]
        };
        Self {
            p50: pick(0.50),
            p95: pick(0.95),
            p99: pick(0.99),
            max: *sorted.last().expect("non-empty"),
        }
    }
}

/// The full bench report. Field order intentionally matches the
/// JSON contract documented in `Cargo.toml` so a future Python
/// pendant can byte-match.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LatencyReport {
    pub rate_hz_target: f64,
    pub duration_sec: u64,
    pub frames_planned: u64,
    pub frames_received: u64,
    pub frames_processed: u64,
    pub frames_dropped: u64,
    pub throughput_actual_hz: f64,
    pub latency_micros: LatencyMicros,
}

impl LatencyReport {
    /// Pretty JSON emission for operator-eyes / cross-lang diffs.
    /// `serde_json::to_string_pretty` is used directly — field order
    /// in the struct above already matches the contract.
    pub fn to_json_pretty(&self) -> String {
        serde_json::to_string_pretty(self).expect("LatencyReport is always Serialize")
    }

    /// Compact JSON emission (one-line, no whitespace), suitable for
    /// pipe-into-jq cases and CI log lines.
    pub fn to_json_compact(&self) -> String {
        serde_json::to_string(self).expect("LatencyReport is always Serialize")
    }
}

// ---------------------------------------------------------------------------
// Synthetic frame generator (deterministic from seed)
// ---------------------------------------------------------------------------

/// Deterministic envelope-bytes generator.
///
/// Uses a small splitmix64-style PRNG so the bench has zero external
/// dependencies beyond what the subscribe-loop crate already pulls
/// in. The same `(seed, frame_count)` always produces the same bytes.
#[derive(Debug, Clone)]
pub struct SyntheticFrameGen {
    state: u64,
}

impl SyntheticFrameGen {
    /// Construct from a 64-bit seed. A seed of `0` is implicitly
    /// nudged to `0xDEAD_BEEF_CAFE_BABE` so the PRNG starts in a
    /// non-trivial state (splitmix degenerates on seed 0 to a
    /// constant-zero stream).
    pub fn new(seed: u64) -> Self {
        let state = if seed == 0 { 0xDEAD_BEEF_CAFE_BABE } else { seed };
        Self { state }
    }

    /// Step the PRNG one position. Splitmix64 (Stafford's mix 13).
    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Emit the next synthetic [`SubscribeMessage`] in the stream.
    ///
    /// The envelope shape matches `ACCEPTED_INBOUND_SCHEMA`
    /// (`wakir.agent.task-assigned/1`) so the subscribe-loop's
    /// `parse_inbound_envelope` accepts it.
    pub fn next_message(&mut self, env: &str, persona_slug: &str) -> SubscribeMessage {
        let n = self.next_u64();
        let auftrag_id = format!("synth-{:016x}", n);
        let prompt_payload = format!("bench-payload-{:016x}", self.next_u64());
        let prompt_sha256 = format!("{:064x}", self.next_u64() as u128);
        // Use a fixed-shape RFC-3339 ts_utc so the subscribe-loop's
        // `compute_subscribe_lag_seconds` parser accepts it. The
        // actual lag the bench measures is from the receiver side,
        // not from this ts; the ts is just schema-compliance.
        let ts_utc = chrono::Utc::now()
            .to_rfc3339_opts(chrono::SecondsFormat::Secs, true);

        let envelope = serde_json::json!({
            "schema":         "wakir.agent.task-assigned/1",
            "event_kind":     "agent.task.assigned",
            "org_id":         "bench-org",
            "persona_id":     persona_slug,
            "auftrag_id":     auftrag_id,
            "ts_utc":         ts_utc,
            "source":         "loop-latency-bench",
            "prompt_sha256":  prompt_sha256,
            "prompt_payload": prompt_payload,
            "metadata":       {},
        });

        let bytes = serde_json::to_vec(&envelope)
            .expect("synthetic envelope is always Serialize");
        let subject = format!(
            "wakir.{}.agent.agent.task.assigned.{}",
            env, persona_slug,
        );
        SubscribeMessage::new(subject, bytes)
    }
}

// ---------------------------------------------------------------------------
// Bench harness
// ---------------------------------------------------------------------------

/// End-to-end loop-latency bench harness.
///
/// One bench-run feeds `rate_hz * duration_sec` envelopes through a
/// real `run_subscribe_loop_with_timeout` invocation, timing the
/// receive -> handler-dispatch delta for each frame. The dropped-frames
/// counter captures frames that the channel **could not enqueue
/// within their per-frame deadline** (i.e., the loop fell behind the
/// requested rate).
///
/// Construction is via [`LoopLatencyBench::new`]. Execution is via
/// [`LoopLatencyBench::run`] (async) or [`LoopLatencyBench::run_blocking`]
/// (spins up a private Tokio runtime — useful for `criterion` benches
/// that are sync-callable).
#[derive(Debug, Clone)]
pub struct LoopLatencyBench {
    /// PRNG seed for the synthetic-frame generator. Fully determines
    /// the envelope bytes the loop processes.
    pub seed: u64,
    /// NATS environment string the bench advertises in subjects (the
    /// loop does no wire-level routing in this bench — the value is
    /// schema-compliance only). Must be `dev`/`staging`/`prod`.
    pub env: String,
    /// Persona-slug component for the subscribe-subject template.
    /// Must match the subscribe-loop's `[a-z][a-z0-9_-]*` rule.
    pub persona_slug: String,
    /// Channel-buffer depth. Frames the producer cannot enqueue
    /// within their per-frame deadline get counted as `frames_dropped`.
    /// Default for [`LoopLatencyBench::new`] is 256.
    pub channel_capacity: usize,
}

impl LoopLatencyBench {
    /// Construct with default channel capacity (256).
    pub fn new(seed: u64, env: impl Into<String>, persona_slug: impl Into<String>) -> Self {
        Self {
            seed,
            env: env.into(),
            persona_slug: persona_slug.into(),
            channel_capacity: 256,
        }
    }

    /// Override channel capacity (chain-style).
    pub fn with_channel_capacity(mut self, cap: usize) -> Self {
        self.channel_capacity = cap;
        self
    }

    /// Drive the loop at `rate_hz` for `duration_sec` seconds and
    /// return the latency report.
    ///
    /// The producer task issues `rate_hz * duration_sec` frames at
    /// a strict per-frame interval (`1.0 / rate_hz` seconds). If the
    /// loop falls behind and the channel's `try_send` is full at the
    /// scheduled instant, that frame is recorded as dropped and the
    /// producer moves on to the next slot (no catch-up bursts —
    /// realistic backpressure semantics).
    ///
    /// At the end, the producer drops its sender; the loop exits on
    /// the next `rx.recv() -> None`, the timeout backs up the exit
    /// in pathological cases.
    pub async fn run(&self, rate_hz: f64, duration_sec: u64) -> LatencyReport {
        let frames_planned = (rate_hz * duration_sec as f64).round() as u64;
        let per_frame_interval =
            Duration::from_secs_f64(if rate_hz <= 0.0 { 1.0 } else { 1.0 / rate_hz });

        let (tx, rx) = mpsc::channel::<SubscribeMessage>(self.channel_capacity);

        // Shared sample-vector populated by the handler. Per-frame
        // dispatch-arrival timestamps are stamped INTO the prompt_payload
        // at producer time (encoded as the producer's monotonic micros)
        // so the handler can compute the wall-clock delta without
        // needing a side-channel.
        let samples = Arc::new(tokio::sync::Mutex::new(Vec::<u64>::with_capacity(
            frames_planned as usize,
        )));

        let handler: Arc<dyn MessageHandler> = Arc::new(LatencyRecordingHandler {
            samples: samples.clone(),
            bench_start: Instant::now(),
        });

        // Producer task: emits synthetic frames at the requested rate,
        // counts drops on try_send failure.
        let producer = {
            let env = self.env.clone();
            let persona_slug = self.persona_slug.clone();
            let seed = self.seed;
            tokio::spawn(async move {
                let mut gen = SyntheticFrameGen::new(seed);
                let mut sent: u64 = 0;
                let mut dropped: u64 = 0;
                let started = Instant::now();
                for i in 0..frames_planned {
                    // The producer encodes its send-monotonic-micros
                    // into the prompt_payload so the handler can
                    // recover it for the latency calc. The encoded
                    // value is `(Instant::now() - bench_start).as_micros()`.
                    let mut msg = gen.next_message(&env, &persona_slug);
                    let send_micros = started.elapsed().as_micros() as u64;
                    // Splice the send-micros into the envelope:
                    // re-parse, set `prompt_payload`, re-serialise.
                    if let Ok(mut v) =
                        serde_json::from_slice::<serde_json::Value>(&msg.data)
                    {
                        if let Some(obj) = v.as_object_mut() {
                            obj.insert(
                                "prompt_payload".into(),
                                serde_json::Value::String(format!(
                                    "bench-send-micros:{}",
                                    send_micros
                                )),
                            );
                        }
                        if let Ok(re_bytes) = serde_json::to_vec(&v) {
                            msg.data = re_bytes;
                        }
                    }

                    match tx.try_send(msg) {
                        Ok(()) => sent += 1,
                        Err(mpsc::error::TrySendError::Full(_)) => dropped += 1,
                        Err(mpsc::error::TrySendError::Closed(_)) => {
                            // Receiver gone — stop early; remaining
                            // frames count as dropped (the loop is
                            // not going to process them).
                            dropped += frames_planned.saturating_sub(i);
                            break;
                        }
                    }

                    // Schedule the next slot at strict per-frame
                    // interval boundaries (no catch-up bursts).
                    let target_next = started + per_frame_interval * (i as u32 + 1);
                    let now = Instant::now();
                    if target_next > now {
                        tokio::time::sleep(target_next - now).await;
                    }
                }
                drop(tx);
                (sent, dropped)
            })
        };

        // Total timeout = the bench's own duration plus a 250 ms grace
        // window so the loop has time to drain the last few channel
        // entries after the producer drops its sender.
        let timeout =
            Duration::from_secs(duration_sec) + Duration::from_millis(250);
        let config = SubscribeLoopConfig::new(
            format!(
                "wakir.{}.agent.agent.task.assigned.{}",
                self.env, self.persona_slug
            ),
            "nats://bench-not-used:4222",
        );
        let state = run_subscribe_loop_with_timeout(config, rx, handler, timeout).await;

        let (_sent, dropped) =
            producer.await.unwrap_or((0u64, frames_planned));

        let samples_locked = samples.lock().await;
        let frames_received = samples_locked.len() as u64;
        let frames_processed = state.messages_processed;

        // Bench wall-clock duration is the *planned* duration; the
        // throughput-actual-Hz is computed against the planned
        // duration so the user can see the rate the substrate
        // actually sustained.
        let throughput_actual_hz =
            frames_processed as f64 / duration_sec as f64;

        let latency_micros = LatencyMicros::from_samples_micros(&samples_locked);

        LatencyReport {
            rate_hz_target: rate_hz,
            duration_sec,
            frames_planned,
            frames_received,
            frames_processed,
            frames_dropped: dropped,
            throughput_actual_hz,
            latency_micros,
        }
    }

    /// Synchronous wrapper that spins up a private Tokio runtime.
    /// Useful for `criterion` benches that cannot be `async fn`.
    pub fn run_blocking(&self, rate_hz: f64, duration_sec: u64) -> LatencyReport {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .expect("tokio runtime build");
        rt.block_on(self.run(rate_hz, duration_sec))
    }
}

// ---------------------------------------------------------------------------
// Latency-recording handler
// ---------------------------------------------------------------------------

/// Handler that, for every envelope, recovers the producer-side
/// send-micros from `prompt_payload` and records the wall-clock
/// delta (in microseconds) into a shared sample-vector.
struct LatencyRecordingHandler {
    samples: Arc<tokio::sync::Mutex<Vec<u64>>>,
    bench_start: Instant,
}

impl MessageHandler for LatencyRecordingHandler {
    fn handle<'a>(&'a self, parsed: &'a ParsedEnvelope) -> HandlerFuture<'a> {
        Box::pin(async move {
            let recv_micros = self.bench_start.elapsed().as_micros() as u64;
            let send_micros = parsed
                .prompt_payload
                .strip_prefix("bench-send-micros:")
                .and_then(|s| s.parse::<u64>().ok());
            if let Some(s) = send_micros {
                let delta = recv_micros.saturating_sub(s);
                self.samples.lock().await.push(delta);
                Ok(())
            } else {
                // Envelope didn't carry the bench timestamp — count as
                // a handler-rejection (parity with subscribe-loop's
                // `tracker.hook_failed`). This case should not happen
                // in normal bench runs.
                Err(HandlerError::Rejected(
                    "missing-bench-send-micros".to_owned(),
                ))
            }
        })
    }
}
