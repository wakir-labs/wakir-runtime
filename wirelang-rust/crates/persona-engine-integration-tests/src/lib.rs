// SPDX-License-Identifier: Apache-2.0
//! Shared helpers for the persona-engine cross-crate integration test
//! suite (Phase-3a Item 16).
//!
//! This crate is a thin shim: the substantive work lives under
//! `tests/` where each scenario is a self-contained integration-test
//! file. The helpers exposed here exist so the five scenarios do not
//! re-implement the same envelope-builder / fake-transport / counting-
//! handler scaffolding.
//!
//! Public surface
//! --------------
//!
//! - [`build_task_assigned_envelope_bytes`] — JSON-encoded bytes of a
//!   well-formed `wakir.agent.task-assigned/1` envelope, the shape the
//!   subscribe-loop crate's `parse_inbound_envelope` accepts.
//! - [`build_anchor_input`] — minimum-viable [`AnchorEmitterInput`]
//!   with caller-controlled `event_id` / `persona_id` / payload bytes.
//! - [`FakeTransport`] — deterministic [`SubmitTransport`] impl with a
//!   pre-programmed outcome sequence (per envelope `event_id`); reused
//!   by Scenario-1 to drive the submit-worker FSM along a known path.
//! - [`FixedClock`] / [`SeqRng`] — deterministic clock/RNG for the
//!   submit-worker so retry-backoff timings are byte-stable across
//!   CI machines.
//! - [`CountingHandler`] — captures every [`ParsedEnvelope`] the
//!   subscribe-loop dispatches, for Scenario-1 dispatch-count
//!   assertions.
//!
//! The helpers are deliberately minimal — anything more elaborate
//! belongs in the scenario file that needs it.

#![forbid(unsafe_code)]
#![warn(missing_docs)]
#![warn(missing_debug_implementations)]

use std::sync::Arc;
use std::sync::Mutex as StdMutex;

use async_trait::async_trait;
use persona_engine_anchor_emitter::{AnchorEmitterInput, AnchorEnvelope};
use persona_engine_anchor_submit_worker::{
    Clock as SubmitClock, Rng as SubmitRng, SubmitTransport, TransportOutcome,
};
use persona_engine_subscribe_loop::{
    HandlerError, HandlerFuture, MessageHandler, ParsedEnvelope, ACCEPTED_INBOUND_SCHEMA,
};

// ---------------------------------------------------------------------
// Envelope builders
// ---------------------------------------------------------------------

/// Build a well-formed inbound `wakir.agent.task-assigned/1` envelope
/// as JSON-encoded UTF-8 bytes.
///
/// Schema-parity with the subscribe-loop crate's smoke-test fixture
/// (`build_inbound_envelope_bytes` in `subscribe_loop_smoke_test.rs`).
/// The shape is deliberately identical so a future cross-crate parity
/// drift fails THIS crate's tests too.
pub fn build_task_assigned_envelope_bytes(auftrag_id: &str, persona: &str) -> Vec<u8> {
    let payload = serde_json::json!({
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "wakir-labs",
        "persona_id": persona,
        "auftrag_id": auftrag_id,
        "ts_utc": "2026-05-17T09:00:00Z",
        "source": "mira-cli",
        "prompt_sha256":
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "prompt_payload": "integration-test",
        "metadata": {"sprint": "tag-15-integration-tests"}
    });
    serde_json::to_vec(&payload).expect("payload must serialise")
}

/// Build a minimum-viable [`AnchorEmitterInput`] for Scenario-1's
/// anchor-emitter step. Uses a fixed RFC-3339 timestamp so the
/// resulting envelope hash is deterministic across CI machines.
#[must_use]
pub fn build_anchor_input(event_id: &str, persona_id: &str, payload: &[u8]) -> AnchorEmitterInput {
    AnchorEmitterInput {
        event_id: event_id.to_string(),
        timestamp_utc: "2026-05-17T09:00:00Z".to_string(),
        persona_id: persona_id.to_string(),
        payload_jcs_bytes: payload.to_vec(),
    }
}

// ---------------------------------------------------------------------
// Subscribe-loop handler that records every dispatch
// ---------------------------------------------------------------------

/// Records the `(auftrag_id, persona_id)` pair of every envelope the
/// subscribe-loop dispatches. Used by Scenario-1 to assert the loop
/// processed exactly the envelopes it was fed.
#[derive(Debug, Clone)]
pub struct CountingHandler {
    seen: Arc<tokio::sync::Mutex<Vec<(String, String)>>>,
}

impl Default for CountingHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl CountingHandler {
    /// Construct a fresh handler with an empty seen-list.
    #[must_use]
    pub fn new() -> Self {
        Self {
            seen: Arc::new(tokio::sync::Mutex::new(Vec::new())),
        }
    }

    /// Snapshot the seen-list (returns a clone so the handler can keep
    /// recording).
    pub async fn seen(&self) -> Vec<(String, String)> {
        self.seen.lock().await.clone()
    }
}

impl MessageHandler for CountingHandler {
    fn handle<'a>(&'a self, parsed: &'a ParsedEnvelope) -> HandlerFuture<'a> {
        let seen = self.seen.clone();
        let auftrag = parsed.auftrag_id.clone();
        let persona = parsed.persona_id.clone();
        Box::pin(async move {
            seen.lock().await.push((auftrag, persona));
            Ok::<(), HandlerError>(())
        })
    }
}

// ---------------------------------------------------------------------
// Submit-worker fakes
// ---------------------------------------------------------------------

/// Deterministic [`SubmitTransport`] that pops outcomes from a pre-
/// programmed queue (one per call). When the queue is exhausted the
/// transport returns `TransportOutcome::Accepted`.
#[derive(Debug)]
pub struct FakeTransport {
    outcomes: StdMutex<std::collections::VecDeque<TransportOutcome>>,
    calls: StdMutex<Vec<String>>,
}

impl FakeTransport {
    /// Construct a transport pre-programmed with `outcomes` (consumed
    /// in order). The first call returns `outcomes[0]`, the second
    /// returns `outcomes[1]`, and so on; calls past the end return
    /// `Accepted` to keep tests deterministic when the FSM happens to
    /// poll one extra time.
    #[must_use]
    pub fn new(outcomes: Vec<TransportOutcome>) -> Self {
        Self {
            outcomes: StdMutex::new(outcomes.into()),
            calls: StdMutex::new(Vec::new()),
        }
    }

    /// Snapshot of every `event_id` the transport was asked to submit
    /// (in call order).
    pub fn calls(&self) -> Vec<String> {
        self.calls.lock().expect("FakeTransport calls lock").clone()
    }
}

#[async_trait]
impl SubmitTransport for FakeTransport {
    async fn submit(&self, envelope: &AnchorEnvelope) -> TransportOutcome {
        self.calls
            .lock()
            .expect("FakeTransport calls lock")
            .push(envelope.event_id.clone());
        self.outcomes
            .lock()
            .expect("FakeTransport outcomes lock")
            .pop_front()
            .unwrap_or(TransportOutcome::Accepted)
    }
}

/// Deterministic [`SubmitClock`] that returns a fixed second-precision
/// epoch. Use [`FixedClock::advance`] to step the clock forward
/// between submit-worker `tick()` calls.
#[derive(Debug)]
pub struct FixedClock {
    now: StdMutex<u64>,
}

impl FixedClock {
    /// Build a clock pinned at `start` epoch-seconds.
    #[must_use]
    pub fn new(start: u64) -> Self {
        Self {
            now: StdMutex::new(start),
        }
    }

    /// Advance the clock by `secs` seconds. Tests call this between
    /// `worker.tick().await` invocations to step the retry-backoff
    /// schedule forward.
    pub fn advance(&self, secs: u64) {
        let mut n = self.now.lock().expect("FixedClock lock");
        *n = n.saturating_add(secs);
    }
}

impl SubmitClock for FixedClock {
    fn now_secs(&self) -> u64 {
        *self.now.lock().expect("FixedClock lock")
    }
}

/// Deterministic [`SubmitRng`] that walks a fixed sequence of u64s
/// (wrapping at end). Used so the submit-worker's full-jitter backoff
/// is byte-stable across CI machines.
#[derive(Debug)]
pub struct SeqRng {
    seq: Vec<u64>,
    idx: StdMutex<usize>,
}

impl SeqRng {
    /// Build a deterministic RNG from a non-empty u64 sequence.
    #[must_use]
    pub fn new(seq: Vec<u64>) -> Self {
        assert!(!seq.is_empty(), "SeqRng sequence must be non-empty");
        Self {
            seq,
            idx: StdMutex::new(0),
        }
    }
}

impl SubmitRng for SeqRng {
    fn gen_range_secs(&self, upper_inclusive: u64) -> u64 {
        if upper_inclusive == 0 {
            return 0;
        }
        let mut idx = self.idx.lock().expect("SeqRng lock");
        let v = self.seq[*idx % self.seq.len()];
        *idx = idx.wrapping_add(1);
        // Production-parity: clamp, do not modulo (see DeterministicRng
        // comment in persona-engine-anchor-submit-worker).
        v.min(upper_inclusive)
    }
}

// ---------------------------------------------------------------------
// Hash helpers
// ---------------------------------------------------------------------

/// Compute a lower-case-hex SHA-256 of `bytes`. Used by Scenario-2 /
/// Scenario-4 cross-crate hash-stability assertions.
#[must_use]
pub fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    hex::encode(h.finalize())
}
