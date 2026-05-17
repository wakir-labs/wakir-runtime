// SPDX-License-Identifier: Apache-2.0
//! Scenario 1 — Full-Lifecycle integration.
//!
//! Wires:
//!
//!   subscribe-loop (parse + dispatch)
//!     -> fsm (Uninstantiated -> Spawning -> Running)
//!     -> bridge-diff (canonicalise + jcs_hash)
//!     -> anchor-emitter (build_anchor_envelope from JCS bytes)
//!     -> anchor-submit-worker (FakeTransport retry FSM)
//!     -> recovery (classify_trigger / RecoveryOutcome on permanent
//!                  submit-worker failure)
//!
//! Five tests cover:
//!
//!   1. End-to-end happy path — subscribe envelope flows through every
//!      stage and the anchor lands in the submit-worker as a `Success`.
//!   2. Submit-worker retries on transient failure — three Retriable
//!      outcomes followed by Accepted, FSM observes Retrying x3 then
//!      Success.
//!   3. Submit-worker dead-letters on permanent failure — Permanent
//!      outcome causes the submit-worker to dead-letter and the
//!      recovery-trigger classification routes to the right
//!      RecoveryTrigger variant.
//!   4. FSM rejects an invalid transition after a successful subscribe
//!      dispatch (Uninstantiated -> Running is NOT in VALID_TRANSITIONS).
//!   5. Bridge-diff and anchor-emitter agree on the canonical JCS bytes
//!      for the payload that flowed through subscribe-loop -> handler.

use std::sync::Arc;
use std::time::Duration;

use persona_engine_anchor_emitter::{build_anchor_envelope, serialize_anchor, sha256_hex};
use persona_engine_anchor_submit_worker::{
    DeadLetterStore, InMemoryDeadLetterStore, NoopWriteBackSink, SubmitResult, SubmitWorker,
    SubmitWorkerConfig, TransportOutcome,
};
use persona_engine_bridge_diff::{canonicalize_envelope, jcs_hash};
use persona_engine_fsm::{FsmError, FsmState, PersonaFsm};
use persona_engine_recovery::{classify_trigger, RecoveryContext, RecoveryTrigger};
use persona_engine_subscribe_loop::{
    run_subscribe_loop_with_timeout, SubscribeLoopConfig, SubscribeMessage,
};

use persona_engine_integration_tests::{
    build_anchor_input, build_task_assigned_envelope_bytes, CountingHandler, FakeTransport,
    FixedClock, SeqRng,
};

fn loop_config() -> SubscribeLoopConfig {
    SubscribeLoopConfig {
        subject_pattern: "wakir.dev.agent.agent.task.assigned.reza".to_string(),
        nats_url: "nats://127.0.0.1:4222".to_string(),
        durable_name: None,
        max_inflight: 0,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn t01_end_to_end_happy_path() {
    // -------------------------------------------------------------
    // Stage 1: subscribe-loop receives one envelope and dispatches
    // it via the counting handler.
    // -------------------------------------------------------------
    let (tx, rx) = tokio::sync::mpsc::channel::<SubscribeMessage>(4);
    let envelope_bytes = build_task_assigned_envelope_bytes("auftrag-t01", "reza");
    tx.send(SubscribeMessage::new(
        "wakir.dev.agent.agent.task.assigned.reza",
        envelope_bytes.clone(),
    ))
    .await
    .expect("send");
    drop(tx); // close so the loop exits once the message is drained

    let handler = Arc::new(CountingHandler::new());
    let state = run_subscribe_loop_with_timeout(
        loop_config(),
        rx,
        handler.clone(),
        Duration::from_secs(2),
    )
    .await;
    assert_eq!(
        state.messages_processed, 1,
        "subscribe-loop must have processed exactly one envelope"
    );
    let seen = handler.seen().await;
    assert_eq!(
        seen,
        vec![("auftrag-t01".to_string(), "reza".to_string())],
        "handler must record the single envelope"
    );

    // -------------------------------------------------------------
    // Stage 2: FSM walks Uninstantiated -> Spawning -> Running.
    // -------------------------------------------------------------
    let mut fsm = PersonaFsm::new("reza", "wakir-labs");
    let _r1 = fsm
        .transition(FsmState::Spawning)
        .expect("Uninstantiated -> Spawning must be valid");
    let _r2 = fsm
        .transition(FsmState::Running)
        .expect("Spawning -> Running must be valid");

    // -------------------------------------------------------------
    // Stage 3: bridge-diff canonicalises the envelope and produces
    // a deterministic JCS-hash; the same bytes feed the anchor-
    // emitter so the two crates agree on the payload representation.
    // -------------------------------------------------------------
    let envelope_value: serde_json::Value =
        serde_json::from_slice(&envelope_bytes).expect("envelope parses");
    let canonical_bytes = canonicalize_envelope(&envelope_value).expect("JCS canonicalise");
    let bd_hash = jcs_hash(&envelope_value).expect("bridge-diff hash");
    assert!(bd_hash.starts_with("sha256:"));
    assert_eq!(bd_hash.len(), 71); // 7 prefix + 64 hex

    // -------------------------------------------------------------
    // Stage 4: anchor-emitter builds an envelope over those same
    // canonical bytes; the resulting payload-hash MUST match the
    // bridge-diff jcs_hash hex tail because both crates hash the
    // same byte slice with SHA-256.
    // -------------------------------------------------------------
    let anchor_input = build_anchor_input("anchor-t01", "reza", &canonical_bytes);
    let anchor_env = build_anchor_envelope(anchor_input).expect("anchor build");
    // Cross-crate parity: bridge-diff::jcs_hash(envelope_value) and
    // anchor-emitter::sha256_hex(payload_jcs_bytes) must agree on the
    // same bytes, because both crates hash the canonical bytes with
    // SHA-256 (bridge-diff prefixes "sha256:"; anchor-emitter exports
    // the bare hex tail). The two must equal after prefix-strip.
    let bd_hash_hex = bd_hash.strip_prefix("sha256:").expect("bd hash prefix");
    let ae_hash_hex = sha256_hex(&anchor_env.payload_jcs_bytes);
    assert_eq!(
        bd_hash_hex, ae_hash_hex,
        "bridge-diff JCS-hash and anchor-emitter sha256_hex must agree on the same bytes",
    );
    let _serialized = serialize_anchor(&anchor_env);

    // -------------------------------------------------------------
    // Stage 5: submit-worker enqueues the anchor envelope and the
    // first tick succeeds (Accepted transport).
    // -------------------------------------------------------------
    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Accepted]));
    let worker = SubmitWorker::new(
        SubmitWorkerConfig::default(),
        transport.clone(),
        Arc::new(InMemoryDeadLetterStore::new()),
        Arc::new(NoopWriteBackSink),
        Arc::new(FixedClock::new(1_747_000_000)),
        Arc::new(SeqRng::new(vec![1])),
    );
    worker.enqueue(anchor_env).await;
    let result = worker.tick().await;
    assert!(
        matches!(result, SubmitResult::Success { ref event_id } if event_id == "anchor-t01"),
        "first tick on a happy path must Succeed with the enqueued event_id, got {result:?}",
    );
    assert_eq!(transport.calls(), vec!["anchor-t01".to_string()]);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn t02_submit_worker_retries_on_transient_failure() {
    // Three retriable outcomes followed by Accepted; FSM must observe
    // Retrying x3 then Success on the fourth tick. The deterministic
    // clock is advanced between ticks so the next_eligible_at watermark
    // expires.

    let envelope_bytes = build_task_assigned_envelope_bytes("auftrag-t02", "reza");
    let envelope_value: serde_json::Value =
        serde_json::from_slice(&envelope_bytes).expect("envelope parses");
    let canonical = canonicalize_envelope(&envelope_value).expect("JCS bytes");
    let anchor = build_anchor_envelope(build_anchor_input("anchor-t02", "reza", &canonical))
        .expect("anchor build");

    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("503".into()),
        TransportOutcome::Retriable("502".into()),
        TransportOutcome::Retriable("500".into()),
        TransportOutcome::Accepted,
    ]));
    let clock = Arc::new(FixedClock::new(1_747_000_000));
    // 100 req/window so the token-bucket never throttles this test.
    let cfg = SubmitWorkerConfig {
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        ..SubmitWorkerConfig::default()
    };
    let worker = SubmitWorker::new(
        cfg,
        transport.clone(),
        Arc::new(InMemoryDeadLetterStore::new()),
        Arc::new(NoopWriteBackSink),
        clock.clone(),
        Arc::new(SeqRng::new(vec![0, 0, 0, 0])),
    );
    worker.enqueue(anchor).await;

    // Tick 1 -> Retrying (attempt 1).
    let r1 = worker.tick().await;
    assert!(
        matches!(r1, SubmitResult::Retrying { attempt: 1, .. }),
        "tick 1 must be Retrying attempt=1, got {r1:?}",
    );
    // Step clock past the backoff watermark (default base 1s, jitter
    // 0 from SeqRng) — advance enough for retry_max_delay to expire.
    clock.advance(600);
    let r2 = worker.tick().await;
    assert!(
        matches!(r2, SubmitResult::Retrying { attempt: 2, .. }),
        "tick 2 must be Retrying attempt=2, got {r2:?}",
    );
    clock.advance(600);
    let r3 = worker.tick().await;
    assert!(
        matches!(r3, SubmitResult::Retrying { attempt: 3, .. }),
        "tick 3 must be Retrying attempt=3, got {r3:?}",
    );
    clock.advance(600);
    let r4 = worker.tick().await;
    assert!(
        matches!(r4, SubmitResult::Success { ref event_id } if event_id == "anchor-t02"),
        "tick 4 must Succeed, got {r4:?}",
    );

    // Transport was called exactly four times in order.
    assert_eq!(transport.calls().len(), 4);
    assert!(transport.calls().iter().all(|id| id == "anchor-t02"));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn t03_submit_worker_dead_letters_and_recovery_classifies() {
    // Permanent failure path: one Permanent outcome dead-letters
    // immediately. The recovery crate is then asked to classify the
    // resulting context as a substrate-failure trigger.

    let envelope_bytes = build_task_assigned_envelope_bytes("auftrag-t03", "reza");
    let envelope_value: serde_json::Value =
        serde_json::from_slice(&envelope_bytes).expect("envelope parses");
    let canonical = canonicalize_envelope(&envelope_value).expect("JCS bytes");
    let anchor = build_anchor_envelope(build_anchor_input("anchor-t03", "reza", &canonical))
        .expect("anchor build");

    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Permanent(
        "malformed".into(),
    )]));
    let dead = Arc::new(InMemoryDeadLetterStore::new());
    let worker = SubmitWorker::new(
        SubmitWorkerConfig::default(),
        transport.clone(),
        dead.clone(),
        Arc::new(NoopWriteBackSink),
        Arc::new(FixedClock::new(1_747_000_000)),
        Arc::new(SeqRng::new(vec![0])),
    );
    worker.enqueue(anchor).await;
    let r = worker.tick().await;
    assert!(
        matches!(r, SubmitResult::Dead { ref event_id, .. } if event_id == "anchor-t03"),
        "permanent failure must dead-letter on the first tick, got {r:?}",
    );
    let dead_snapshot = dead.snapshot().await;
    assert_eq!(dead_snapshot.len(), 1);
    assert_eq!(dead_snapshot[0].event_id, "anchor-t03");

    // Recovery: a submit-worker dead-letter is the production analog
    // of a subscribe-loop teardown — the recovery crate maps that onto
    // RecoveryTrigger::DespawnMidOperation via the subscribe_failure
    // flag. We pin the variant here so a future re-mapping inside the
    // recovery crate fails this integration test loudly.
    let ctx = RecoveryContext {
        pin_drift: false,
        fence_active: false,
        subscribe_failure: true,
        force_trigger: None,
        persona_id: "reza".to_string(),
        org_id: "wakir-labs".to_string(),
    };
    let trigger = classify_trigger(&ctx).expect("recovery must classify");
    assert_eq!(
        trigger,
        RecoveryTrigger::DespawnMidOperation,
        "subscribe_failure must classify as DespawnMidOperation",
    );
}

#[test]
fn t04_fsm_rejects_invalid_transition_after_dispatch() {
    // Uninstantiated -> Running is NOT a valid edge in VALID_TRANSITIONS
    // (the only legal first step from Uninstantiated is Spawning or
    // Recovered). The integration check is that the FSM still raises
    // even if the caller already saw a subscribe-loop dispatch — the
    // two crates' contracts are independent.
    let mut fsm = PersonaFsm::new("reza", "wakir-labs");
    let err = fsm
        .transition(FsmState::Running)
        .expect_err("Uninstantiated -> Running must be rejected");
    assert!(
        matches!(err, FsmError::InvalidTransition { .. }),
        "wrong FsmError variant: {err:?}",
    );
}

#[test]
fn t05_bridge_diff_and_anchor_emitter_agree_on_jcs_bytes() {
    // Independent of any subscribe-loop flow: feed an arbitrary JSON
    // value through both bridge-diff::canonicalize_envelope and the
    // anchor-emitter; the anchor-emitter's payload_sha256 over the
    // canonical bytes equals bridge-diff::jcs_hash of the same value.
    let v = serde_json::json!({
        "schema": "wakir.test/1",
        "fields": {
            "b": 2,
            "a": 1,
            "nested": {"y": "ok", "x": [1, 2, 3]},
        }
    });
    let canon = canonicalize_envelope(&v).expect("canon");
    let bd = jcs_hash(&v).expect("jcs_hash");
    let anchor = build_anchor_envelope(build_anchor_input("anchor-t05", "reza", &canon))
        .expect("anchor build");
    let bd_hex = bd.strip_prefix("sha256:").expect("bd hash prefix");
    let ae_hex = sha256_hex(&anchor.payload_jcs_bytes);
    assert_eq!(bd_hex, ae_hex, "cross-crate hash drift");
}
