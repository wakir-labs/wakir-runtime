// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Persona-engine anchor-submit-worker — Tag-13 Mini-Welle, Phase-3a Modul 12.
//
// Design summary
// --------------
// The submit-worker is the production-loop substrate on top of the
// anchor-emitter (PR #141, merged). It accepts in-flight
// `AnchorEnvelope` records, submits them to an OpenTimestamps
// calendar (modelled by the injected `SubmitTransport` trait), and
// drives a deterministic retry / dead-letter / writeback FSM.
//
// The FSM is stepped one *event* at a time by `tick().await`. A
// single `tick()` call advances exactly one envelope through one
// state transition, then returns. This single-step posture mirrors
// the persona-engine-fsm precedent (PR #137) and is what makes
// smoke-tests deterministic — no embedded sleeps, no background
// pollers, no time-dependent assertions.
//
// FSM states (per envelope)
// -------------------------
//
//   Pending    -- queued, never attempted, ready when `next_eligible_at
//                 <= clock.now()`.
//   Throttled  -- the token-bucket refused the attempt for this
//                 endpoint; the envelope is *requeued without
//                 incrementing the retry counter*. (A throttle is not
//                 a failure; it is a back-pressure signal.)
//   Retrying   -- the last submit attempt returned a retriable error;
//                 `retry_count` is incremented and
//                 `next_eligible_at = now + backoff(retry_count)`.
//   Dead       -- `retry_count` reached `max_retry`; the envelope is
//                 moved to the `DeadLetterStore`.
//   Done       -- submit succeeded; the writeback sink has been
//                 invoked; the envelope is removed from the queue.
//
// Throttling semantics
// --------------------
// `SubmitResult::Throttled` returns *without invoking the transport*
// — this is the "throttle-no-side-effects" invariant the
// Sprint-Auftrag calls out explicitly. The token-bucket check
// happens first; only after a token is consumed do we call
// `SubmitTransport::submit`.
//
// Retry-backoff with full jitter
// ------------------------------
// We use Marc Brooker's full-jitter formulation:
//
//   delay(n) = jitter ∈ [0, min(cap, base * 2^n)]
//
// where `n` is the (zero-based) retry attempt index, `base` is
// `SubmitWorkerConfig.retry_base_delay`, and `cap` is
// `SubmitWorkerConfig.retry_max_delay`. The jitter source is the
// injected `Rng` trait so smoke-tests can pin it to a deterministic
// stub.
//
// The "monotonic backoff" smoke test does not assert that delays grow
// strictly monotonically (the jitter would break that). It asserts
// that the *upper bound* doubles per attempt; the lower bound stays
// at zero. This is the contract the Sprint-Auftrag's "monotonic"
// wording maps to in the full-jitter formulation.
//
// Dead-letter store
// -----------------
// `DeadLetterStore::record` is the audit-hop. The default
// `InMemoryDeadLetterStore` is the smoke-test backing; production
// callers would inject a backing that writes to the WAT spool's
// dead-letter file. A `DeadLetterRecord` carries the
// `AnchorEnvelope`, the terminal-error string, the final retry-count,
// and the RFC-3339 timestamp of dead-letter-time.

#![forbid(unsafe_code)]
#![warn(missing_docs)]
#![warn(missing_debug_implementations)]

//! Persona-engine anchor-submit-worker — production-loop substrate.
//!
//! See the crate-level `Cargo.toml` comment for the schema-parity
//! authority, ADR anchors and version-pin rationale. Public surface:
//! [`SubmitWorker`], [`SubmitWorkerConfig`], [`SubmitResult`],
//! [`SubmitTransport`], [`TransportOutcome`], [`DeadLetterStore`],
//! [`InMemoryDeadLetterStore`], [`DeadLetterRecord`], [`WriteBackSink`],
//! [`NoopWriteBackSink`], [`Clock`], [`SystemClock`], [`Rng`],
//! [`DeterministicRng`].

use std::collections::VecDeque;
use std::env;
use std::fmt;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;

pub use persona_engine_anchor_emitter::AnchorEnvelope;

// ---------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------

/// Default token-bucket refill rate: 1 request per 30 seconds. Matches
/// the Sprint-Auftrag default and the OpenTimestamps public-calendar
/// civility cap.
pub const DEFAULT_RATE_REQUESTS: u32 = 1;

/// Default token-bucket refill window in seconds.
pub const DEFAULT_RATE_WINDOW_SECS: u64 = 30;

/// Default max retry attempts before dead-lettering.
pub const DEFAULT_MAX_RETRY: u32 = 5;

/// Default base delay for exponential backoff (1 second).
pub const DEFAULT_RETRY_BASE_DELAY: Duration = Duration::from_secs(1);

/// Default cap on the upper bound of the full-jitter delay (5 minutes).
pub const DEFAULT_RETRY_MAX_DELAY: Duration = Duration::from_secs(300);

/// Environment variable name controlling the token-bucket rate.
/// Format: `"<requests>/<seconds>"`, e.g. `"1/30"` for 1 req per 30s.
pub const ENV_SUBMIT_RATE: &str = "WAKIR_ANCHOR_SUBMIT_RATE";

/// Environment variable name controlling the max retry budget.
/// Format: a non-negative `u32`.
pub const ENV_MAX_RETRY: &str = "WAKIR_ANCHOR_MAX_RETRY";

// ---------------------------------------------------------------------
// Public result enum.
// ---------------------------------------------------------------------

/// Outcome of a single [`SubmitWorker::tick`] step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SubmitResult {
    /// The envelope submitted successfully; writeback was invoked; the
    /// envelope has been removed from the queue.
    Success {
        /// Identifier of the envelope that just succeeded.
        event_id: String,
    },
    /// The token-bucket refused the attempt; no transport call was made;
    /// the envelope remains in the queue with its retry-count unchanged.
    Throttled {
        /// Identifier of the envelope that was throttled.
        event_id: String,
    },
    /// The transport returned a retriable error; the envelope is
    /// requeued with `retry_count + 1` and `next_eligible_at` updated
    /// via the full-jitter backoff schedule.
    Retrying {
        /// Identifier of the envelope being retried.
        event_id: String,
        /// One-based retry attempt that *just* happened.
        attempt: u32,
        /// The backoff delay drawn for the *next* attempt.
        next_delay: Duration,
    },
    /// `retry_count` reached `max_retry`; the envelope has been moved
    /// to the dead-letter store and removed from the queue.
    Dead {
        /// Identifier of the envelope that was dead-lettered.
        event_id: String,
        /// Terminal error string captured at dead-letter time.
        terminal_error: String,
    },
    /// No envelope was eligible (queue empty, or every queued envelope
    /// has `next_eligible_at > now`). No side-effects.
    Idle,
}

// ---------------------------------------------------------------------
// Transport trait + outcome.
// ---------------------------------------------------------------------

/// Outcome of a single transport submission attempt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransportOutcome {
    /// Submission succeeded.
    Accepted,
    /// Submission failed with a retriable error (e.g. calendar 5xx,
    /// network timeout). The string is captured into the eventual
    /// dead-letter record if the retry budget runs out.
    Retriable(String),
    /// Submission failed with a permanent error (e.g. malformed
    /// envelope, calendar 4xx). The worker dead-letters immediately
    /// without consuming the remaining retry budget.
    Permanent(String),
}

/// Pluggable OTS-calendar transport. The smoke-test surface uses
/// `FakeTransport`; the Phase-3c follow-up wires in a real HTTPS
/// client.
#[async_trait]
pub trait SubmitTransport: Send + Sync + fmt::Debug {
    /// Submit one envelope to the OTS calendar. Implementations MUST
    /// be cancellation-safe but need not be reentrant — the worker
    /// serialises calls per `tick()`.
    async fn submit(&self, envelope: &AnchorEnvelope) -> TransportOutcome;
}

// ---------------------------------------------------------------------
// Dead-letter store.
// ---------------------------------------------------------------------

/// One row in the dead-letter store. Serde-derived so a production
/// backing can append it to the WAT spool's dead-letter file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeadLetterRecord {
    /// Identifier of the dead-lettered envelope.
    pub event_id: String,
    /// Persona the envelope was attributed to.
    pub persona_id: String,
    /// RFC-3339-shaped timestamp of dead-letter time (UTC).
    pub dead_letter_at: String,
    /// Terminal-error string captured from the last transport call.
    pub terminal_error: String,
    /// Number of retry attempts actually performed (excludes the
    /// initial attempt; matches `SubmitWorkerConfig.max_retry` when
    /// the budget is exhausted on a retriable error).
    pub retry_count: u32,
}

/// Pluggable backing for dead-lettered envelopes.
#[async_trait]
pub trait DeadLetterStore: Send + Sync + fmt::Debug {
    /// Record one dead-lettered envelope. Implementations MUST be
    /// append-only and tolerate duplicate event_ids (the worker
    /// guarantees uniqueness per envelope, but a retry of a
    /// previously-dead-lettered envelope after process restart is a
    /// supported scenario for the production backing).
    async fn record(&self, record: DeadLetterRecord);

    /// Test-only readback for smoke-tests. Production backings return
    /// `vec![]` (the canonical persistent dead-letter file is the
    /// audit substrate, not this in-memory mirror).
    async fn snapshot(&self) -> Vec<DeadLetterRecord>;
}

/// In-memory dead-letter store used by smoke-tests and as the default
/// when the caller does not inject a backing.
#[derive(Debug, Default)]
pub struct InMemoryDeadLetterStore {
    inner: Mutex<Vec<DeadLetterRecord>>,
}

impl InMemoryDeadLetterStore {
    /// Build an empty in-memory dead-letter store.
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl DeadLetterStore for InMemoryDeadLetterStore {
    async fn record(&self, record: DeadLetterRecord) {
        self.inner.lock().await.push(record);
    }
    async fn snapshot(&self) -> Vec<DeadLetterRecord> {
        self.inner.lock().await.clone()
    }
}

// ---------------------------------------------------------------------
// Writeback sink.
// ---------------------------------------------------------------------

/// Hook invoked on successful submission so the WAT row can be marked
/// as anchored. Default impl is a no-op (`NoopWriteBackSink`).
#[async_trait]
pub trait WriteBackSink: Send + Sync + fmt::Debug {
    /// Write the success-record back to the audit substrate.
    /// Implementations should be idempotent on `event_id`.
    async fn write_success(&self, envelope: &AnchorEnvelope);
}

/// Default no-op writeback sink. Used when the caller has no audit
/// substrate to feed; smoke-tests use `RecordingWriteBackSink`.
#[derive(Debug, Default)]
pub struct NoopWriteBackSink;

#[async_trait]
impl WriteBackSink for NoopWriteBackSink {
    async fn write_success(&self, _envelope: &AnchorEnvelope) {}
}

// ---------------------------------------------------------------------
// Clock + RNG (deterministic-substrate traits).
// ---------------------------------------------------------------------

/// Pluggable clock. The production impl is `SystemClock`; smoke-tests
/// use a manual clock so the FSM transitions can be observed step by
/// step without real time elapsing.
pub trait Clock: Send + Sync + fmt::Debug {
    /// Return the current monotonic instant as seconds-since-epoch.
    /// Smoke-tests use a `Cell<u64>` backing; production uses
    /// `SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()`.
    fn now_secs(&self) -> u64;
}

/// Real-wall-clock implementation. Suitable for production.
#[derive(Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now_secs(&self) -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    }
}

/// Pluggable bounded-integer RNG. The full-jitter backoff calls
/// `gen_range_secs(upper_inclusive)` to draw the jittered delay.
pub trait Rng: Send + Sync + fmt::Debug {
    /// Return a `u64` in the inclusive range `[0, upper_inclusive]`.
    /// Implementations MUST handle `upper_inclusive == 0` by
    /// returning `0`.
    fn gen_range_secs(&self, upper_inclusive: u64) -> u64;
}

/// Deterministic-RNG stub used by smoke-tests. Cycles through a
/// caller-supplied sequence of `u64` values, wrapping at the end.
/// When the underlying value exceeds `upper_inclusive`, it is clamped
/// (not modulo'd — clamping matches the expected production behaviour
/// where a real RNG returns a uniform draw within the bound).
#[derive(Debug)]
pub struct DeterministicRng {
    sequence: Vec<u64>,
    cursor: Mutex<usize>,
}

impl DeterministicRng {
    /// Build a deterministic RNG seeded with the given sequence.
    /// Panics if `sequence` is empty (smoke-test contract; a deterministic
    /// RNG with no values is a programming error).
    pub fn new(sequence: Vec<u64>) -> Self {
        assert!(
            !sequence.is_empty(),
            "DeterministicRng requires a non-empty sequence"
        );
        Self {
            sequence,
            cursor: Mutex::new(0),
        }
    }
}

impl Rng for DeterministicRng {
    fn gen_range_secs(&self, upper_inclusive: u64) -> u64 {
        if upper_inclusive == 0 {
            return 0;
        }
        // We block on the mutex synchronously because `Rng::gen_range_secs`
        // is intentionally a sync surface — the FSM step needs a jittered
        // draw without crossing an await point inside the critical
        // section. The lock is uncontended (one tick at a time).
        let mut cursor = self
            .cursor
            .try_lock()
            .expect("DeterministicRng cursor lock is uncontended by construction");
        let raw = self.sequence[*cursor % self.sequence.len()];
        *cursor = (*cursor + 1) % self.sequence.len();
        if raw > upper_inclusive {
            upper_inclusive
        } else {
            raw
        }
    }
}

// ---------------------------------------------------------------------
// Config.
// ---------------------------------------------------------------------

/// Construction parameters for [`SubmitWorker`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SubmitWorkerConfig {
    /// Token-bucket refill rate: `rate_requests` tokens per
    /// `rate_window`. Default `1 / 30s`.
    pub rate_requests: u32,
    /// Window over which `rate_requests` tokens are issued.
    #[serde(with = "duration_secs")]
    pub rate_window: Duration,
    /// Max retry attempts before dead-lettering (default 5).
    pub max_retry: u32,
    /// Base delay for full-jitter backoff (default 1s).
    #[serde(with = "duration_secs")]
    pub retry_base_delay: Duration,
    /// Cap on the upper bound of the full-jitter draw (default 5min).
    #[serde(with = "duration_secs")]
    pub retry_max_delay: Duration,
}

impl Default for SubmitWorkerConfig {
    fn default() -> Self {
        Self {
            rate_requests: DEFAULT_RATE_REQUESTS,
            rate_window: Duration::from_secs(DEFAULT_RATE_WINDOW_SECS),
            max_retry: DEFAULT_MAX_RETRY,
            retry_base_delay: DEFAULT_RETRY_BASE_DELAY,
            retry_max_delay: DEFAULT_RETRY_MAX_DELAY,
        }
    }
}

impl SubmitWorkerConfig {
    /// Build a config from environment variables, falling back to
    /// defaults for any unset/malformed key. Pure function over an
    /// explicit `getenv` closure so smoke-tests can drive it without
    /// mutating the real process environment.
    pub fn from_env_with<F: Fn(&str) -> Option<String>>(getenv: F) -> Self {
        let mut cfg = Self::default();
        if let Some(raw) = getenv(ENV_SUBMIT_RATE) {
            if let Some((reqs, secs)) = parse_rate_spec(&raw) {
                cfg.rate_requests = reqs;
                cfg.rate_window = Duration::from_secs(secs);
            }
        }
        if let Some(raw) = getenv(ENV_MAX_RETRY) {
            if let Ok(n) = raw.trim().parse::<u32>() {
                cfg.max_retry = n;
            }
        }
        cfg
    }

    /// Production convenience: read from the real process environment.
    pub fn from_env() -> Self {
        Self::from_env_with(|key| env::var(key).ok())
    }
}

/// Parse a rate spec of the form `"<reqs>/<secs>"`. Returns
/// `None` if either component is missing, non-numeric, or zero.
fn parse_rate_spec(s: &str) -> Option<(u32, u64)> {
    let (reqs, secs) = s.trim().split_once('/')?;
    let reqs: u32 = reqs.trim().parse().ok()?;
    let secs: u64 = secs.trim().parse().ok()?;
    if reqs == 0 || secs == 0 {
        return None;
    }
    Some((reqs, secs))
}

// ---------------------------------------------------------------------
// Serde helper for Duration <-> seconds.
// ---------------------------------------------------------------------

mod duration_secs {
    use serde::{Deserialize, Deserializer, Serializer};
    use std::time::Duration;

    pub fn serialize<S: Serializer>(d: &Duration, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_u64(d.as_secs())
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Duration, D::Error> {
        let secs = u64::deserialize(d)?;
        Ok(Duration::from_secs(secs))
    }
}

// ---------------------------------------------------------------------
// Per-envelope FSM state (internal).
// ---------------------------------------------------------------------

/// Internal queue entry — one envelope plus its retry-FSM state.
#[derive(Debug, Clone)]
struct QueuedEnvelope {
    envelope: AnchorEnvelope,
    /// One-based count of retry attempts already performed (excludes
    /// the initial attempt). `0` means "never attempted" OR "first
    /// attempt completed but throttle pushed it back".
    retry_count: u32,
    /// Earliest `now_secs()` value at which a `tick()` should
    /// re-attempt this envelope. Updated by both throttle and retry.
    next_eligible_at: u64,
    /// Terminal error string from the most recent retriable failure
    /// (used to populate the dead-letter record if the budget runs
    /// out on the next attempt).
    last_error: Option<String>,
}

// ---------------------------------------------------------------------
// Token-bucket (internal).
// ---------------------------------------------------------------------

/// Single-endpoint token bucket. Per Sprint-Auftrag "per submit
/// endpoint", multi-endpoint support is the Phase-3c follow-up;
/// for the Phase-3a substrate we model a single bucket.
#[derive(Debug)]
struct TokenBucket {
    capacity: u32,
    window_secs: u64,
    tokens: u32,
    last_refill_at: u64,
}

impl TokenBucket {
    fn new(capacity: u32, window_secs: u64) -> Self {
        Self {
            capacity,
            window_secs,
            tokens: capacity,
            last_refill_at: 0,
        }
    }

    /// Try to consume one token at the given clock time. Returns
    /// `true` iff a token was available (refill first, then consume).
    fn try_consume(&mut self, now: u64) -> bool {
        self.refill(now);
        if self.tokens > 0 {
            self.tokens -= 1;
            true
        } else {
            false
        }
    }

    fn refill(&mut self, now: u64) {
        if self.window_secs == 0 || self.capacity == 0 {
            return;
        }
        if now < self.last_refill_at {
            // Clock went backwards (test stub edge case): treat as
            // "no time has passed".
            return;
        }
        let elapsed = now - self.last_refill_at;
        if elapsed >= self.window_secs {
            // Refill to capacity once per full window. Sub-window
            // elapsed time accrues to the next refill check.
            let windows = elapsed / self.window_secs;
            // Saturating add to capacity ceiling.
            let add = (self.capacity as u64).saturating_mul(windows);
            let new_tokens = (self.tokens as u64).saturating_add(add);
            self.tokens = new_tokens.min(self.capacity as u64) as u32;
            self.last_refill_at += windows * self.window_secs;
        }
    }
}

// ---------------------------------------------------------------------
// Submit-worker.
// ---------------------------------------------------------------------

/// Production-loop substrate. See module-level docs for the FSM
/// contract. The worker is `tick`-driven (one envelope per `tick()`
/// call) and deterministic when constructed with a manual `Clock`
/// and `DeterministicRng`.
#[derive(Debug)]
pub struct SubmitWorker {
    config: SubmitWorkerConfig,
    queue: Mutex<VecDeque<QueuedEnvelope>>,
    bucket: Mutex<TokenBucket>,
    transport: Arc<dyn SubmitTransport>,
    dead_letter: Arc<dyn DeadLetterStore>,
    writeback: Arc<dyn WriteBackSink>,
    clock: Arc<dyn Clock>,
    rng: Arc<dyn Rng>,
}

impl SubmitWorker {
    /// Build a new submit-worker.
    pub fn new(
        config: SubmitWorkerConfig,
        transport: Arc<dyn SubmitTransport>,
        dead_letter: Arc<dyn DeadLetterStore>,
        writeback: Arc<dyn WriteBackSink>,
        clock: Arc<dyn Clock>,
        rng: Arc<dyn Rng>,
    ) -> Self {
        let bucket = TokenBucket::new(config.rate_requests, config.rate_window.as_secs());
        Self {
            config,
            queue: Mutex::new(VecDeque::new()),
            bucket: Mutex::new(bucket),
            transport,
            dead_letter,
            writeback,
            clock,
            rng,
        }
    }

    /// Enqueue an envelope for submission. The envelope becomes
    /// immediately eligible (`next_eligible_at = 0`).
    pub async fn enqueue(&self, envelope: AnchorEnvelope) {
        let entry = QueuedEnvelope {
            envelope,
            retry_count: 0,
            next_eligible_at: 0,
            last_error: None,
        };
        self.queue.lock().await.push_back(entry);
    }

    /// Test-only readback for the queue length. Production code does
    /// not need this; the smoke-tests use it to assert side-effects.
    pub async fn queue_len(&self) -> usize {
        self.queue.lock().await.len()
    }

    /// Drive one step of the FSM. Pops the first *eligible* envelope
    /// (or returns `Idle` if none), attempts submission honouring the
    /// token-bucket, and applies the resulting state transition.
    ///
    /// Eligibility uses `now_secs()` from the injected `Clock`.
    /// Order of evaluation per envelope:
    /// 1. Token-bucket check -> `Throttled` on refusal (no transport
    ///    call, no retry-count change, envelope requeued at the
    ///    front so it gets retried on the next eligible tick).
    /// 2. Transport submission.
    /// 3. Outcome dispatch:
    ///    - `Accepted`  -> writeback + `Success`.
    ///    - `Retriable` -> retry-count + 1; if budget exhausted,
    ///      dead-letter + `Dead`; else requeue with full-jitter
    ///      backoff + `Retrying`.
    ///    - `Permanent` -> dead-letter + `Dead` (no retry budget
    ///      consumed).
    pub async fn tick(&self) -> SubmitResult {
        let now = self.clock.now_secs();

        let mut entry = {
            let mut queue = self.queue.lock().await;
            // Find first eligible (next_eligible_at <= now).
            let idx = queue.iter().position(|e| e.next_eligible_at <= now);
            match idx {
                Some(i) => queue.remove(i).expect("position returned a valid index"),
                None => return SubmitResult::Idle,
            }
        };

        // Token-bucket gate. No side-effects on refusal.
        let allowed = {
            let mut bucket = self.bucket.lock().await;
            bucket.try_consume(now)
        };
        if !allowed {
            let event_id = entry.envelope.event_id.clone();
            // Requeue at front, eligibility unchanged. Retry-count
            // unchanged (throttle is back-pressure, not a failure).
            self.queue.lock().await.push_front(entry);
            return SubmitResult::Throttled { event_id };
        }

        // Submit. No lock held across this await.
        let outcome = self.transport.submit(&entry.envelope).await;
        let event_id = entry.envelope.event_id.clone();

        match outcome {
            TransportOutcome::Accepted => {
                self.writeback.write_success(&entry.envelope).await;
                SubmitResult::Success { event_id }
            }
            TransportOutcome::Retriable(err) => {
                entry.retry_count += 1;
                entry.last_error = Some(err.clone());
                if entry.retry_count > self.config.max_retry {
                    // Budget exhausted.
                    let record = self.build_dead_letter_record(&entry, err);
                    self.dead_letter.record(record.clone()).await;
                    SubmitResult::Dead {
                        event_id,
                        terminal_error: record.terminal_error,
                    }
                } else {
                    let delay = self.backoff_for_attempt(entry.retry_count);
                    entry.next_eligible_at = now.saturating_add(delay.as_secs());
                    let attempt = entry.retry_count;
                    self.queue.lock().await.push_back(entry);
                    SubmitResult::Retrying {
                        event_id,
                        attempt,
                        next_delay: delay,
                    }
                }
            }
            TransportOutcome::Permanent(err) => {
                let record = self.build_dead_letter_record(&entry, err);
                let terminal_error = record.terminal_error.clone();
                self.dead_letter.record(record).await;
                SubmitResult::Dead {
                    event_id,
                    terminal_error,
                }
            }
        }
    }

    fn backoff_for_attempt(&self, attempt: u32) -> Duration {
        // Full jitter: delay = uniform[0, min(cap, base * 2^(attempt-1))].
        // `attempt` is one-based (the first retry is attempt=1).
        let base = self.config.retry_base_delay.as_secs().max(1);
        let cap = self.config.retry_max_delay.as_secs();
        let shift = (attempt.saturating_sub(1)).min(63);
        let exp = base.saturating_mul(1u64 << shift);
        let upper = exp.min(cap.max(1));
        let drawn = self.rng.gen_range_secs(upper);
        Duration::from_secs(drawn)
    }

    fn build_dead_letter_record(
        &self,
        entry: &QueuedEnvelope,
        last_error: String,
    ) -> DeadLetterRecord {
        let now = self.clock.now_secs();
        DeadLetterRecord {
            event_id: entry.envelope.event_id.clone(),
            persona_id: entry.envelope.persona_id.clone(),
            dead_letter_at: format_rfc3339_secs(now),
            terminal_error: last_error,
            retry_count: entry.retry_count,
        }
    }
}

// ---------------------------------------------------------------------
// RFC-3339 second-precision UTC formatter (no chrono dep).
// ---------------------------------------------------------------------

/// Format a `seconds-since-epoch` value as
/// `YYYY-MM-DDTHH:MM:SSZ`. Avoids a `chrono` dependency for this one
/// shape; the algorithm is the standard civil-from-days formulation
/// (Howard Hinnant's date library, public-domain pseudocode).
fn format_rfc3339_secs(secs: u64) -> String {
    // Howard Hinnant's `civil_from_days` algorithm, ported to u64.
    let days = (secs / 86_400) as i64;
    let secs_of_day = secs % 86_400;
    let hour = secs_of_day / 3600;
    let minute = (secs_of_day % 3600) / 60;
    let second = secs_of_day % 60;

    // Shift so day 0 is 0000-03-01 (Hinnant's algorithm convention),
    // unix epoch (1970-01-01) is +719_468 in that frame.
    let z = days + 719_468;
    let era = if z >= 0 {
        z / 146_097
    } else {
        (z - 146_096) / 146_097
    };
    let doe = (z - era * 146_097) as u64; // [0, 146097)
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365; // [0, 400)
    let y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 366)
    let mp = (5 * doy + 2) / 153; // [0, 11)
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let year = if m <= 2 { y + 1 } else { y };

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year, m, d, hour, minute, second
    )
}

// ---------------------------------------------------------------------
// Spec-invariant self-check.
// ---------------------------------------------------------------------

/// Module-internal invariant check used by unit tests. Mirrors the
/// posture of the FSM and anchor-emitter crates.
pub fn assert_spec_invariants() -> Result<(), &'static str> {
    if DEFAULT_RATE_REQUESTS == 0 {
        return Err("DEFAULT_RATE_REQUESTS must be > 0");
    }
    if DEFAULT_RATE_WINDOW_SECS == 0 {
        return Err("DEFAULT_RATE_WINDOW_SECS must be > 0");
    }
    if DEFAULT_MAX_RETRY == 0 {
        return Err("DEFAULT_MAX_RETRY must be > 0");
    }
    if DEFAULT_RETRY_BASE_DELAY.as_secs() == 0 {
        return Err("DEFAULT_RETRY_BASE_DELAY must be at least 1s");
    }
    if DEFAULT_RETRY_MAX_DELAY < DEFAULT_RETRY_BASE_DELAY {
        return Err("DEFAULT_RETRY_MAX_DELAY must be >= DEFAULT_RETRY_BASE_DELAY");
    }
    if ENV_SUBMIT_RATE != "WAKIR_ANCHOR_SUBMIT_RATE" {
        return Err("ENV_SUBMIT_RATE drifted from Sprint-Auftrag-pinned value");
    }
    if ENV_MAX_RETRY != "WAKIR_ANCHOR_MAX_RETRY" {
        return Err("ENV_MAX_RETRY drifted from Sprint-Auftrag-pinned value");
    }
    Ok(())
}

// ---------------------------------------------------------------------
// Library-internal smoke tests (module-import-time invariants).
// ---------------------------------------------------------------------

#[cfg(test)]
mod lib_tests {
    use super::*;

    #[test]
    fn spec_invariants_hold() {
        assert_spec_invariants().expect("spec invariants must hold at build time");
    }

    #[test]
    fn rate_spec_parser_accepts_canonical_shape() {
        assert_eq!(parse_rate_spec("1/30"), Some((1, 30)));
        assert_eq!(parse_rate_spec(" 4 / 60 "), Some((4, 60)));
    }

    #[test]
    fn rate_spec_parser_rejects_zero_or_garbage() {
        assert_eq!(parse_rate_spec(""), None);
        assert_eq!(parse_rate_spec("0/30"), None);
        assert_eq!(parse_rate_spec("1/0"), None);
        assert_eq!(parse_rate_spec("abc"), None);
        assert_eq!(parse_rate_spec("1/abc"), None);
        assert_eq!(parse_rate_spec("1"), None);
    }

    #[test]
    fn config_from_env_uses_defaults_when_unset() {
        let cfg = SubmitWorkerConfig::from_env_with(|_| None);
        assert_eq!(cfg, SubmitWorkerConfig::default());
    }

    #[test]
    fn config_from_env_picks_up_known_keys() {
        let cfg = SubmitWorkerConfig::from_env_with(|k| match k {
            ENV_SUBMIT_RATE => Some("3/15".to_string()),
            ENV_MAX_RETRY => Some("7".to_string()),
            _ => None,
        });
        assert_eq!(cfg.rate_requests, 3);
        assert_eq!(cfg.rate_window, Duration::from_secs(15));
        assert_eq!(cfg.max_retry, 7);
    }

    #[test]
    fn config_from_env_falls_back_on_malformed() {
        let cfg = SubmitWorkerConfig::from_env_with(|k| match k {
            ENV_SUBMIT_RATE => Some("not-a-rate".to_string()),
            ENV_MAX_RETRY => Some("negative".to_string()),
            _ => None,
        });
        assert_eq!(cfg, SubmitWorkerConfig::default());
    }

    #[test]
    fn rfc3339_format_pins_known_epoch() {
        // 0 -> 1970-01-01T00:00:00Z
        assert_eq!(format_rfc3339_secs(0), "1970-01-01T00:00:00Z");
        // 1_700_000_000 -> 2023-11-14T22:13:20Z (known reference)
        assert_eq!(format_rfc3339_secs(1_700_000_000), "2023-11-14T22:13:20Z");
    }

    #[test]
    fn token_bucket_consumes_then_refuses() {
        let mut b = TokenBucket::new(2, 30);
        assert!(b.try_consume(0));
        assert!(b.try_consume(0));
        assert!(!b.try_consume(0));
    }

    #[test]
    fn token_bucket_refills_after_window() {
        let mut b = TokenBucket::new(1, 30);
        assert!(b.try_consume(0));
        assert!(!b.try_consume(15));
        assert!(b.try_consume(30));
    }

    #[test]
    fn deterministic_rng_clamps_to_upper() {
        let r = DeterministicRng::new(vec![999]);
        assert_eq!(r.gen_range_secs(10), 10);
    }

    #[test]
    fn deterministic_rng_returns_zero_for_zero_upper() {
        let r = DeterministicRng::new(vec![42]);
        assert_eq!(r.gen_range_secs(0), 0);
    }
}
