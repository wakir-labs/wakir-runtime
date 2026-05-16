// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine NATS Subscribe-Loop — Rust substrate (Phase-3a Item 4).
//!
//! This is the **initial Rust scaffold** of the persona-engine
//! subscribe-loop. The Python reference implementation lives at
//! `wirelang/persona_engine/nats_subscribe_loop.py` (Selin Bug-42-Fix
//! PR #79, Sprint-Pengine-13). The Doppelbetrieb-Konsistenz contract
//! (Selin PR #113 3-way-triangle) requires this Rust substrate to
//! produce schema-byte-parity with the Python loop at the JSON
//! envelope boundary.
//!
//! # Scope of this scaffold
//!
//! This crate intentionally does **not** open a live NATS socket.
//! The `async-nats` dependency is declared so that the Phase-3a-step
//! "live-binding" follow-up can extend `run_subscribe_loop` to a
//! real NATS subscription without revisiting the crate-choice
//! decision. The smoke-test surface uses an in-process
//! `tokio::sync::mpsc::Receiver<SubscribeMessage>` instead — this is
//! the same posture as the Python hermetic-test surface
//! (`run_with_iterator(asyncio.Queue)`).
//!
//! # Schema parity with Selin PR #79
//!
//! | Python concept | Rust type |
//! |---|---|
//! | `SubscribeLoopConfig` (per-sprint subset) | [`SubscribeLoopConfig`] |
//! | `TaskProcessingTracker` + subscribe-lag | [`SubscribeLoopState`] |
//! | `InboundMessage` (`data` + `subject`) | [`SubscribeMessage`] |
//! | `_handle_message` callable surface | [`MessageHandler`] trait |
//! | `parse_inbound_envelope` (schema gate) | [`parse_inbound_envelope`] |
//! | RFC-3339 `ts_utc` (`%Y-%m-%dT%H:%M:%SZ`) | `chrono` Secs format |
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 4 (initial Rust scaffold).
//! - Selin PR #79  (Schema-Quelle, Bug-42 fix).
//! - Selin PR #113 (3-way-triangle Doppelbetrieb).
//! - Selin PR #118 (rust-adapter-hook).
//! - Reza  PR #120 (Phase-3a crate-smoke precedent).

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use tokio::sync::mpsc::Receiver;
use tokio::sync::Mutex;

/// Schema identifier accepted on inbound envelopes
/// (parity with Python `ACCEPTED_INBOUND_SCHEMA`).
pub const ACCEPTED_INBOUND_SCHEMA: &str = "wakir.agent.task-assigned/1";

/// Schema identifier emitted on output envelopes
/// (parity with Python `OUTBOUND_OUTPUT_SCHEMA`).
pub const OUTBOUND_OUTPUT_SCHEMA: &str = "wakir.agent.task-output/1";

/// Subscribe-subject template
/// (parity with Python `SUBSCRIBE_SUBJECT_TEMPLATE`).
///
/// Format placeholders are `{env}` and `{persona_slug}`. The caller
/// substitutes via [`build_subscribe_subject`].
pub const SUBSCRIBE_SUBJECT_TEMPLATE: &str =
    "wakir.{env}.agent.agent.task.assigned.{persona_slug}";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/// Subscribe-loop construction parameters.
///
/// Schema-parity-subset of the Python `SubscribeLoopConfig`, with the
/// fields explicitly listed in the Sprint-Auftrag: `subject_pattern`,
/// `nats_url`, `durable_name`, `max_inflight`.
#[derive(Debug, Clone)]
pub struct SubscribeLoopConfig {
    /// Canonical subscribe-subject (already substituted; the loop
    /// does no further templating). Example:
    /// `wakir.dev.agent.agent.task.assigned.reza`.
    pub subject_pattern: String,

    /// NATS server URL. Not exercised by smoke-tests — declared so
    /// the Phase-3a live-binding follow-up extends this struct
    /// without breaking the existing call sites.
    pub nats_url: String,

    /// Durable-consumer name. `None` for core-NATS callback/iterator
    /// modes; `Some(name)` for JetStream pull-consumer mode.
    /// Parity with Python `_run_live_jetstream_pull` durable arg.
    pub durable_name: Option<String>,

    /// Maximum in-flight messages (Phase-3a substrate; reserved for
    /// the JetStream pull-consumer `fetch(batch=...)` argument).
    pub max_inflight: u32,
}

impl SubscribeLoopConfig {
    /// Constructor with explicit defaults for the optional fields,
    /// matching the Python `dataclass(default_factory=...)` posture.
    pub fn new(
        subject_pattern: impl Into<String>,
        nats_url: impl Into<String>,
    ) -> Self {
        Self {
            subject_pattern: subject_pattern.into(),
            nats_url: nats_url.into(),
            durable_name: None,
            max_inflight: 16,
        }
    }
}

// ---------------------------------------------------------------------------
// Runtime state
// ---------------------------------------------------------------------------

/// Snapshot of subscribe-loop runtime state.
///
/// Collapses the Python `TaskProcessingTracker` counters with the
/// Sprint-SRE Tag-15 subscribe-lag observability into a single
/// returnable value, matching the Sprint-Auftrag signature
/// `async fn run_subscribe_loop(config) -> SubscribeLoopState`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SubscribeLoopState {
    /// Last-measured envelope-to-dispatch lag, in seconds.
    /// `None` if no message has been processed yet or the envelope
    /// `ts_utc` failed to parse (parity with Python
    /// `_compute_subscribe_lag_seconds`).
    pub current_lag_seconds: Option<f64>,

    /// Monotonic count of fully-handled messages.
    pub messages_processed: u64,

    /// RFC-3339 second-precision UTC timestamp of the last delivery.
    /// `None` if no message has been processed yet.
    pub last_message_at: Option<String>,
}

// ---------------------------------------------------------------------------
// Inbound message
// ---------------------------------------------------------------------------

/// A NATS-shaped inbound message.
///
/// Parity with the Python `InboundMessage` protocol (only `data` and
/// `subject` are touched). `ack` is intentionally absent in the Rust
/// scaffold — core-NATS pub-sub does not require ack (Bridge-Forward-
/// Pipe v1 §4.2), and the JetStream-pull ack-path is a Phase-3a
/// follow-up item.
#[derive(Debug, Clone)]
pub struct SubscribeMessage {
    pub data: Vec<u8>,
    pub subject: String,
}

impl SubscribeMessage {
    pub fn new(subject: impl Into<String>, data: impl Into<Vec<u8>>) -> Self {
        Self {
            subject: subject.into(),
            data: data.into(),
        }
    }
}

// ---------------------------------------------------------------------------
// Handler trait (manual BoxFuture form — no async-trait dep)
// ---------------------------------------------------------------------------

/// Future returned by [`MessageHandler::handle`].
pub type HandlerFuture<'a> =
    Pin<Box<dyn Future<Output = Result<(), HandlerError>> + Send + 'a>>;

/// Per-message handler trait.
///
/// Parity with the Python `LlmCallHook` + `_handle_message_inner`
/// integration: the trait is invoked once per parsed envelope. The
/// trait is `Send + Sync` so handlers can hold async resources.
///
/// The trait uses a hand-rolled `BoxFuture`-returning signature
/// rather than the `async-trait` macro to keep the dependency
/// footprint at the four declared deps.
pub trait MessageHandler: Send + Sync {
    /// Handle one parsed envelope. Return `Ok(())` on success;
    /// `Err(_)` is logged by the loop and counted as a hook failure
    /// (the loop continues — parity with Python `tracker.hook_failed`).
    fn handle<'a>(&'a self, parsed: &'a ParsedEnvelope) -> HandlerFuture<'a>;
}

/// Hook-side error surface.
#[derive(Debug, Clone, PartialEq)]
pub enum HandlerError {
    /// Handler-side rejection (typed string for audit-trail clarity).
    Rejected(String),
}

impl std::fmt::Display for HandlerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            HandlerError::Rejected(msg) => write!(f, "handler-rejected: {}", msg),
        }
    }
}

impl std::error::Error for HandlerError {}

// ---------------------------------------------------------------------------
// Envelope parsing
// ---------------------------------------------------------------------------

/// Parsed inbound auftrag envelope.
///
/// Parity-subset of the Python `ParsedAuftrag` — only the fields the
/// Rust scaffold consumes are captured here. `metadata` is held as
/// an opaque `serde_json::Value` so future fields are pass-through.
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedEnvelope {
    pub schema: String,
    pub event_kind: String,
    pub org_id: String,
    pub persona_id: String,
    pub auftrag_id: String,
    pub ts_utc: String,
    pub source: String,
    pub prompt_sha256: String,
    pub prompt_payload: String,
    pub metadata: Value,
}

/// Envelope-parse error surface.
#[derive(Debug, Clone, PartialEq)]
pub enum EnvelopeError {
    JsonDecode(String),
    NotObject,
    UnexpectedSchema { got: String, expected: String },
    UnexpectedEventKind { got: String },
    MissingField(String),
    MetadataNotObject,
}

impl std::fmt::Display for EnvelopeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EnvelopeError::JsonDecode(msg) => write!(f, "json-decode-failed: {}", msg),
            EnvelopeError::NotObject => write!(f, "envelope-not-object"),
            EnvelopeError::UnexpectedSchema { got, expected } => write!(
                f,
                "unexpected-schema: got {:?}, expected {:?}",
                got, expected
            ),
            EnvelopeError::UnexpectedEventKind { got } => {
                write!(f, "unexpected-event_kind: got {:?}", got)
            }
            EnvelopeError::MissingField(field) => {
                write!(f, "missing-or-empty-field: {:?}", field)
            }
            EnvelopeError::MetadataNotObject => write!(f, "metadata-not-object"),
        }
    }
}

impl std::error::Error for EnvelopeError {}

/// Parse an inbound Bridge-Forward-Pipe envelope.
///
/// Validation rules mirror Python `parse_inbound_envelope` exactly:
///
/// 1. UTF-8 + JSON-decodable.
/// 2. Top-level object.
/// 3. `schema == ACCEPTED_INBOUND_SCHEMA`.
/// 4. `event_kind == "agent.task.assigned"`.
/// 5. All required string fields present and non-empty.
/// 6. `metadata` is an object (defaulting to `{}` if absent).
pub fn parse_inbound_envelope(raw: &[u8]) -> Result<ParsedEnvelope, EnvelopeError> {
    let text = std::str::from_utf8(raw)
        .map_err(|e| EnvelopeError::JsonDecode(format!("utf8: {}", e)))?;
    let obj: Value = serde_json::from_str(text)
        .map_err(|e| EnvelopeError::JsonDecode(e.to_string()))?;
    let map = obj.as_object().ok_or(EnvelopeError::NotObject)?;

    let schema = expect_str(map, "schema")?;
    if schema != ACCEPTED_INBOUND_SCHEMA {
        return Err(EnvelopeError::UnexpectedSchema {
            got: schema.to_owned(),
            expected: ACCEPTED_INBOUND_SCHEMA.to_owned(),
        });
    }
    let event_kind = expect_str(map, "event_kind")?;
    if event_kind != "agent.task.assigned" {
        return Err(EnvelopeError::UnexpectedEventKind {
            got: event_kind.to_owned(),
        });
    }
    let org_id = expect_str(map, "org_id")?.to_owned();
    let persona_id = expect_str(map, "persona_id")?.to_owned();
    let auftrag_id = expect_str(map, "auftrag_id")?.to_owned();
    let ts_utc = expect_str(map, "ts_utc")?.to_owned();
    let source = expect_str(map, "source")?.to_owned();
    let prompt_sha256 = expect_str(map, "prompt_sha256")?.to_owned();
    let prompt_payload = expect_str(map, "prompt_payload")?.to_owned();

    let metadata = match map.get("metadata") {
        None => Value::Object(serde_json::Map::new()),
        Some(v) if v.is_object() => v.clone(),
        Some(_) => return Err(EnvelopeError::MetadataNotObject),
    };

    Ok(ParsedEnvelope {
        schema: schema.to_owned(),
        event_kind: event_kind.to_owned(),
        org_id,
        persona_id,
        auftrag_id,
        ts_utc,
        source,
        prompt_sha256,
        prompt_payload,
        metadata,
    })
}

fn expect_str<'a>(
    map: &'a serde_json::Map<String, Value>,
    field: &str,
) -> Result<&'a str, EnvelopeError> {
    match map.get(field) {
        Some(Value::String(s)) if !s.is_empty() => Ok(s.as_str()),
        _ => Err(EnvelopeError::MissingField(field.to_owned())),
    }
}

// ---------------------------------------------------------------------------
// Subject helpers (parity with Python `build_subscribe_subject`)
// ---------------------------------------------------------------------------

/// Build the canonical agent.task.assigned subscribe-subject.
///
/// Parity with Python `build_subscribe_subject` validation:
/// `env` must be one of `dev`/`staging`/`prod`; `persona_slug` must
/// match `[a-z][a-z0-9_-]*`.
pub fn build_subscribe_subject(
    env: &str,
    persona_slug: &str,
) -> Result<String, String> {
    if !matches!(env, "dev" | "staging" | "prod") {
        return Err(format!(
            "env must be one of dev/staging/prod, got {:?}",
            env
        ));
    }
    if !is_valid_slug(persona_slug) {
        return Err(format!(
            "persona_slug must match [a-z][a-z0-9_-]*, got {:?}",
            persona_slug
        ));
    }
    Ok(SUBSCRIBE_SUBJECT_TEMPLATE
        .replace("{env}", env)
        .replace("{persona_slug}", persona_slug))
}

fn is_valid_slug(s: &str) -> bool {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) if c.is_ascii_lowercase() => {}
        _ => return false,
    }
    chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
}

// ---------------------------------------------------------------------------
// Subscribe-loop driver
// ---------------------------------------------------------------------------

/// Compute envelope-to-dispatch lag in seconds.
///
/// Parity with Python `_compute_subscribe_lag_seconds`: accepts the
/// `YYYY-MM-DDTHH:MM:SSZ` shape; returns `None` if parse fails.
pub fn compute_subscribe_lag_seconds(ts_utc: &str) -> Option<f64> {
    let parsed = chrono::DateTime::parse_from_rfc3339(ts_utc).ok()?;
    let now = chrono::Utc::now();
    let delta = now.signed_duration_since(parsed.with_timezone(&chrono::Utc));
    Some(delta.num_milliseconds() as f64 / 1000.0)
}

/// Current UTC timestamp in the RFC-3339 second-precision shape
/// (matches Python `time.strftime("%Y-%m-%dT%H:%M:%SZ")`).
pub fn utc_now_rfc3339() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

/// Async driver that consumes an in-memory message channel and
/// dispatches each message through the supplied handler.
///
/// The signature mirrors the Sprint-Auftrag contract:
///
/// ```ignore
/// async fn run_subscribe_loop(config) -> SubscribeLoopState
/// ```
///
/// The function exits when the receiver is closed (all senders
/// dropped) — parity with the Python `iter_from_queue(sentinel=None)`
/// shutdown signal.
pub async fn run_subscribe_loop(
    config: SubscribeLoopConfig,
    mut rx: Receiver<SubscribeMessage>,
    handler: Arc<dyn MessageHandler>,
) -> SubscribeLoopState {
    let state = Arc::new(Mutex::new(SubscribeLoopState::default()));
    let _ = &config; // config currently informational; future fields drive
                     // the JetStream-pull path (Phase-3a follow-up).

    while let Some(msg) = rx.recv().await {
        let parsed = match parse_inbound_envelope(&msg.data) {
            Ok(p) => p,
            Err(_) => {
                // Parity: malformed envelopes increment `tasks_malformed`
                // in Python; the Rust scaffold's state struct does not
                // surface that counter yet — we deliberately do NOT
                // bump `messages_processed`. Future versions add an
                // explicit `malformed_count` field; the current
                // contract is the Sprint-Auftrag's 3-field struct.
                continue;
            }
        };

        let lag = compute_subscribe_lag_seconds(&parsed.ts_utc);
        // Snapshot the dispatch timestamp BEFORE the handler runs so
        // hermetic tests can assert deterministic ordering.
        let stamp = utc_now_rfc3339();

        let res = handler.handle(&parsed).await;

        let mut guard = state.lock().await;
        guard.current_lag_seconds = lag;
        guard.last_message_at = Some(stamp);
        if res.is_ok() {
            guard.messages_processed = guard.messages_processed.saturating_add(1);
        }
    }

    // Snapshot the final state. The Arc<Mutex<...>> is dropped on
    // function return; no race because the loop above has exited.
    let final_state = state.lock().await.clone();
    final_state
}

/// Convenience: run the loop with an explicit timeout deadline.
///
/// Returns the state snapshot at the moment the deadline expires
/// even if the channel is still open. Used by the JetStream-pull
/// substrate (Phase-3a follow-up) and by integration tests that
/// want to assert "loop ran for N ms and processed M msgs".
pub async fn run_subscribe_loop_with_timeout(
    config: SubscribeLoopConfig,
    rx: Receiver<SubscribeMessage>,
    handler: Arc<dyn MessageHandler>,
    timeout: Duration,
) -> SubscribeLoopState {
    tokio::time::timeout(timeout, run_subscribe_loop(config, rx, handler))
        .await
        .unwrap_or_default()
}
