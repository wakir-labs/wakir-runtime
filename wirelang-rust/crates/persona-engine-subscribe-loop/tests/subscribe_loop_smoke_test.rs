// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Smoke-tests for the persona-engine subscribe-loop Rust substrate.
//!
//! These tests use an in-memory `tokio::sync::mpsc` channel as the
//! NATS-mock — no real NATS server is contacted. The tests assert
//! the substrate contract:
//!
//! 1. Envelope parsing schema-parity with the Python reference.
//! 2. Subject-builder validation parity.
//! 3. Config construction with explicit + default fields.
//! 4. Loop dispatches every well-formed message to the handler.
//! 5. Malformed envelopes are dropped without incrementing the
//!    processed-count.
//! 6. The final state snapshot reflects the last-seen lag and the
//!    monotonic processed counter.
//! 7. Timeout-driver path returns a default state on deadline expiry.
//! 8. The HandlerError path leaves `messages_processed` unchanged.

use std::sync::Arc;

use persona_engine_subscribe_loop::{
    build_subscribe_subject, compute_subscribe_lag_seconds, parse_inbound_envelope,
    run_subscribe_loop, run_subscribe_loop_with_timeout, utc_now_rfc3339, EnvelopeError,
    HandlerError, HandlerFuture, MessageHandler, ParsedEnvelope, SubscribeLoopConfig,
    SubscribeMessage, ACCEPTED_INBOUND_SCHEMA, OUTBOUND_OUTPUT_SCHEMA,
    SUBSCRIBE_SUBJECT_TEMPLATE,
};

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/// Build a well-formed inbound envelope as JSON-encoded UTF-8 bytes.
/// Mirrors the Python `bridge-forward` payload shape.
fn build_inbound_envelope_bytes(auftrag_id: &str, persona: &str) -> Vec<u8> {
    let payload = serde_json::json!({
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "wakir-labs",
        "persona_id": persona,
        "auftrag_id": auftrag_id,
        "ts_utc": "2026-05-16T21:00:00Z",
        "source": "mira-cli",
        "prompt_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "prompt_payload": "hello",
        "metadata": {"sprint": "rust-subscribe-loop-crate-mini"}
    });
    serde_json::to_vec(&payload).expect("payload must serialise")
}

/// Counting handler: records every envelope passed in.
struct CountingHandler {
    seen: Arc<tokio::sync::Mutex<Vec<String>>>,
}

impl CountingHandler {
    fn new() -> (Self, Arc<tokio::sync::Mutex<Vec<String>>>) {
        let seen = Arc::new(tokio::sync::Mutex::new(Vec::new()));
        (
            Self {
                seen: seen.clone(),
            },
            seen,
        )
    }
}

impl MessageHandler for CountingHandler {
    fn handle<'a>(&'a self, parsed: &'a ParsedEnvelope) -> HandlerFuture<'a> {
        let seen = self.seen.clone();
        let auftrag = parsed.auftrag_id.clone();
        Box::pin(async move {
            seen.lock().await.push(auftrag);
            Ok(())
        })
    }
}

/// Rejecting handler: always returns Err. Used to assert the
/// state-counter contract on handler failure.
struct RejectingHandler;

impl MessageHandler for RejectingHandler {
    fn handle<'a>(&'a self, _parsed: &'a ParsedEnvelope) -> HandlerFuture<'a> {
        Box::pin(async move { Err(HandlerError::Rejected("smoke-test".into())) })
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn t1_constants_match_python_reference() {
    // Parity-snapshot: constants must not drift from the Python
    // module without an explicit cross-review checkpoint.
    assert_eq!(ACCEPTED_INBOUND_SCHEMA, "wakir.agent.task-assigned/1");
    assert_eq!(OUTBOUND_OUTPUT_SCHEMA, "wakir.agent.task-output/1");
    assert_eq!(
        SUBSCRIBE_SUBJECT_TEMPLATE,
        "wakir.{env}.agent.agent.task.assigned.{persona_slug}"
    );
}

#[test]
fn t2_parse_inbound_envelope_happy_path() {
    let raw = build_inbound_envelope_bytes("auftrag-001", "reza");
    let parsed = parse_inbound_envelope(&raw).expect("envelope must parse");
    assert_eq!(parsed.schema, ACCEPTED_INBOUND_SCHEMA);
    assert_eq!(parsed.event_kind, "agent.task.assigned");
    assert_eq!(parsed.persona_id, "reza");
    assert_eq!(parsed.auftrag_id, "auftrag-001");
    assert_eq!(parsed.org_id, "wakir-labs");
    assert_eq!(parsed.source, "mira-cli");
    assert_eq!(parsed.prompt_payload, "hello");
    // metadata is pass-through
    assert!(parsed.metadata.is_object());
}

#[test]
fn t3_parse_inbound_envelope_error_surface() {
    // Wrong schema -> UnexpectedSchema.
    let bad_schema = serde_json::json!({
        "schema": "evil/1",
        "event_kind": "agent.task.assigned",
        "org_id": "wakir-labs",
        "persona_id": "reza",
        "auftrag_id": "x",
        "ts_utc": "2026-05-16T21:00:00Z",
        "source": "s",
        "prompt_sha256": "sha256:f",
        "prompt_payload": "p",
    });
    let raw = serde_json::to_vec(&bad_schema).unwrap();
    let err = parse_inbound_envelope(&raw).unwrap_err();
    matches!(err, EnvelopeError::UnexpectedSchema { .. });

    // Missing field -> MissingField.
    let missing = serde_json::json!({
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "wakir-labs",
        // persona_id missing
        "auftrag_id": "x",
        "ts_utc": "2026-05-16T21:00:00Z",
        "source": "s",
        "prompt_sha256": "sha256:f",
        "prompt_payload": "p",
    });
    let raw = serde_json::to_vec(&missing).unwrap();
    let err = parse_inbound_envelope(&raw).unwrap_err();
    assert_eq!(err, EnvelopeError::MissingField("persona_id".to_owned()));

    // Non-object envelope -> NotObject.
    let raw = b"[]";
    let err = parse_inbound_envelope(raw).unwrap_err();
    assert_eq!(err, EnvelopeError::NotObject);

    // Bad JSON -> JsonDecode.
    let raw = b"{not-json";
    let err = parse_inbound_envelope(raw).unwrap_err();
    matches!(err, EnvelopeError::JsonDecode(_));
}

#[test]
fn t4_build_subscribe_subject_parity() {
    let s = build_subscribe_subject("dev", "reza").expect("must build");
    assert_eq!(s, "wakir.dev.agent.agent.task.assigned.reza");

    // Bad env rejected.
    assert!(build_subscribe_subject("evil", "reza").is_err());

    // Bad slug rejected.
    assert!(build_subscribe_subject("prod", "Reza").is_err()); // uppercase
    assert!(build_subscribe_subject("prod", "1reza").is_err()); // leading digit
    assert!(build_subscribe_subject("prod", "").is_err()); // empty
    assert!(build_subscribe_subject("prod", "re.za").is_err()); // dot
}

#[test]
fn t5_config_defaults_match_sprint_contract() {
    let cfg = SubscribeLoopConfig::new(
        "wakir.dev.agent.agent.task.assigned.reza",
        "nats://localhost:4222",
    );
    assert_eq!(cfg.subject_pattern, "wakir.dev.agent.agent.task.assigned.reza");
    assert_eq!(cfg.nats_url, "nats://localhost:4222");
    assert_eq!(cfg.durable_name, None);
    assert_eq!(cfg.max_inflight, 16);

    // Explicit override.
    let cfg2 = SubscribeLoopConfig {
        subject_pattern: "a".into(),
        nats_url: "b".into(),
        durable_name: Some("wakir-persona-reza-dev".into()),
        max_inflight: 4,
    };
    assert_eq!(cfg2.durable_name.as_deref(), Some("wakir-persona-reza-dev"));
    assert_eq!(cfg2.max_inflight, 4);
}

#[tokio::test]
async fn t6_run_subscribe_loop_dispatches_well_formed_messages() {
    let cfg = SubscribeLoopConfig::new(
        "wakir.dev.agent.agent.task.assigned.reza",
        "nats://mock",
    );
    let (handler, seen) = CountingHandler::new();
    let handler: Arc<dyn MessageHandler> = Arc::new(handler);

    let (tx, rx) = tokio::sync::mpsc::channel::<SubscribeMessage>(8);

    // Drive three well-formed envelopes through the channel, then
    // close the sender to trigger graceful loop exit.
    let subject = build_subscribe_subject("dev", "reza").unwrap();
    for i in 0..3 {
        let raw = build_inbound_envelope_bytes(&format!("auftrag-{:03}", i), "reza");
        tx.send(SubscribeMessage::new(subject.clone(), raw))
            .await
            .expect("channel must accept");
    }
    drop(tx); // closes the receiver path

    let state = run_subscribe_loop(cfg, rx, handler).await;

    assert_eq!(state.messages_processed, 3);
    assert!(state.last_message_at.is_some());
    let recorded = seen.lock().await;
    assert_eq!(recorded.len(), 3);
    assert_eq!(recorded[0], "auftrag-000");
    assert_eq!(recorded[2], "auftrag-002");
}

#[tokio::test]
async fn t7_run_subscribe_loop_drops_malformed_envelopes() {
    let cfg = SubscribeLoopConfig::new("wakir.dev.agent.agent.task.assigned.reza", "nats://mock");
    let (handler, seen) = CountingHandler::new();
    let handler: Arc<dyn MessageHandler> = Arc::new(handler);

    let (tx, rx) = tokio::sync::mpsc::channel::<SubscribeMessage>(8);
    let subject = build_subscribe_subject("dev", "reza").unwrap();

    // One malformed, one well-formed, one malformed, one well-formed.
    tx.send(SubscribeMessage::new(subject.clone(), b"{garbage".to_vec()))
        .await
        .unwrap();
    tx.send(SubscribeMessage::new(
        subject.clone(),
        build_inbound_envelope_bytes("good-1", "reza"),
    ))
    .await
    .unwrap();
    tx.send(SubscribeMessage::new(subject.clone(), b"[]".to_vec()))
        .await
        .unwrap();
    tx.send(SubscribeMessage::new(
        subject.clone(),
        build_inbound_envelope_bytes("good-2", "reza"),
    ))
    .await
    .unwrap();
    drop(tx);

    let state = run_subscribe_loop(cfg, rx, handler).await;

    assert_eq!(state.messages_processed, 2);
    let recorded = seen.lock().await;
    assert_eq!(recorded.len(), 2);
    assert_eq!(recorded[0], "good-1");
    assert_eq!(recorded[1], "good-2");
}

#[tokio::test]
async fn t8_handler_error_leaves_processed_count_unchanged() {
    let cfg = SubscribeLoopConfig::new("wakir.dev.agent.agent.task.assigned.reza", "nats://mock");
    let handler: Arc<dyn MessageHandler> = Arc::new(RejectingHandler);

    let (tx, rx) = tokio::sync::mpsc::channel::<SubscribeMessage>(4);
    let subject = build_subscribe_subject("dev", "reza").unwrap();
    for i in 0..2 {
        let raw = build_inbound_envelope_bytes(&format!("rej-{}", i), "reza");
        tx.send(SubscribeMessage::new(subject.clone(), raw))
            .await
            .unwrap();
    }
    drop(tx);

    let state = run_subscribe_loop(cfg, rx, handler).await;

    // No successful dispatches -> count stays zero.
    assert_eq!(state.messages_processed, 0);
    // But last_message_at must still be set: the loop saw the
    // envelope (parity with Python: malformed-vs-handler-failed are
    // distinct paths; this test pins the contract for the handler-
    // failed path).
    assert!(state.last_message_at.is_some());
}

#[tokio::test]
async fn t9_run_subscribe_loop_with_timeout_returns_on_deadline() {
    let cfg = SubscribeLoopConfig::new("wakir.dev.agent.agent.task.assigned.reza", "nats://mock");
    let (handler, _seen) = CountingHandler::new();
    let handler: Arc<dyn MessageHandler> = Arc::new(handler);

    // Channel that is never closed and never sends — forces the
    // timeout path to fire.
    let (_tx, rx) = tokio::sync::mpsc::channel::<SubscribeMessage>(1);

    let start = std::time::Instant::now();
    let state = run_subscribe_loop_with_timeout(
        cfg,
        rx,
        handler,
        std::time::Duration::from_millis(50),
    )
    .await;
    let elapsed = start.elapsed();

    // Deadline expired -> default state returned.
    assert_eq!(state.messages_processed, 0);
    assert_eq!(state.last_message_at, None);
    // And the elapsed time is bounded (loose upper bound for CI noise).
    assert!(
        elapsed < std::time::Duration::from_secs(2),
        "timeout-driver must not block past deadline; elapsed={:?}",
        elapsed
    );
}

#[test]
fn t10_lag_and_timestamp_helpers_round_trip() {
    // utc_now_rfc3339 must produce a string parseable by chrono.
    let now = utc_now_rfc3339();
    assert!(
        chrono::DateTime::parse_from_rfc3339(&now).is_ok(),
        "utc_now_rfc3339 must emit RFC-3339: got {:?}",
        now
    );

    // compute_subscribe_lag_seconds: a far-past ts must produce a
    // large positive lag; a far-future ts must produce a negative.
    let past = "2020-01-01T00:00:00Z";
    let lag_past = compute_subscribe_lag_seconds(past).expect("past parses");
    assert!(lag_past > 0.0, "past ts must produce positive lag");

    // Malformed ts -> None (parity with Python).
    let bad = "not-a-timestamp";
    assert!(compute_subscribe_lag_seconds(bad).is_none());
}
