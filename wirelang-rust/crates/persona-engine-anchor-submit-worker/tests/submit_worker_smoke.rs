// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// persona-engine-anchor-submit-worker smoke tests — Tag-13 Mini-Welle.
//
// Test inventory (mapped to Sprint-Auftrag-named tests + FSM corners)
// -------------------------------------------------------------------
//
//   Sprint-Auftrag-named:
//     1. rate_limit_honored
//     2. retry_monotonic_backoff
//     3. dead_letter_after_max
//     4. success_fast_path
//     5. throttle_no_side_effects
//
//   FSM corners (additional discipline):
//     6.  idle_when_queue_empty
//     7.  permanent_error_dead_letters_immediately
//     8.  permanent_error_does_not_consume_retry_budget
//     9.  retry_count_increments_per_attempt
//     10. dead_letter_record_carries_terminal_error
//     11. dead_letter_record_carries_persona_id
//     12. writeback_invoked_on_success_only
//     13. throttle_re_enters_queue_at_front
//     14. config_default_matches_sprint_auftrag
//     15. token_bucket_refills_between_ticks
//     16. backoff_upper_bound_doubles_per_attempt
//     17. multi_envelope_round_robin_through_ticks

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use async_trait::async_trait;
use persona_engine_anchor_emitter::{build_anchor_envelope, AnchorEmitterInput, AnchorEnvelope};
use persona_engine_anchor_submit_worker::{
    AnchorEnvelope as ReexportedAnchorEnvelope, Clock, DeadLetterStore, DeterministicRng,
    InMemoryDeadLetterStore, NoopWriteBackSink, Rng, SubmitResult, SubmitTransport, SubmitWorker,
    SubmitWorkerConfig, SystemClock, TransportOutcome, WriteBackSink, DEFAULT_MAX_RETRY,
    DEFAULT_RATE_REQUESTS, DEFAULT_RATE_WINDOW_SECS, DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_MAX_DELAY,
};

// ---------------------------------------------------------------------
// Helpers — test fakes.
// ---------------------------------------------------------------------

#[derive(Debug)]
struct ManualClock {
    now: AtomicU64,
}
impl ManualClock {
    fn new(start: u64) -> Self {
        Self {
            now: AtomicU64::new(start),
        }
    }
    fn advance(&self, by_secs: u64) {
        self.now.fetch_add(by_secs, Ordering::SeqCst);
    }
}
impl Clock for ManualClock {
    fn now_secs(&self) -> u64 {
        self.now.load(Ordering::SeqCst)
    }
}

#[derive(Debug)]
struct FakeTransport {
    /// Outcomes are popped from the front each `submit()` call. After
    /// the script is exhausted, the transport panics — making any
    /// "unintended extra submit" smoke-test failure loud.
    script: StdMutex<Vec<TransportOutcome>>,
    /// Count of `submit()` calls actually made (side-effect counter
    /// for throttle assertions).
    calls: AtomicU64,
    /// Captured event-ids in submit order (for cross-tick assertions).
    seen: StdMutex<Vec<String>>,
}
impl FakeTransport {
    fn new(script: Vec<TransportOutcome>) -> Self {
        Self {
            script: StdMutex::new(script),
            calls: AtomicU64::new(0),
            seen: StdMutex::new(Vec::new()),
        }
    }
    fn calls(&self) -> u64 {
        self.calls.load(Ordering::SeqCst)
    }
    fn seen(&self) -> Vec<String> {
        self.seen.lock().unwrap().clone()
    }
}
#[async_trait]
impl SubmitTransport for FakeTransport {
    async fn submit(&self, envelope: &AnchorEnvelope) -> TransportOutcome {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.seen.lock().unwrap().push(envelope.event_id.clone());
        let mut s = self.script.lock().unwrap();
        if s.is_empty() {
            panic!(
                "FakeTransport script exhausted but submit() was called \
                 for event_id={:?} — this signals an unintended extra \
                 transport call (likely a throttle/idle invariant violation)",
                envelope.event_id
            );
        }
        s.remove(0)
    }
}

#[derive(Debug, Default)]
struct RecordingWriteBackSink {
    calls: StdMutex<Vec<String>>,
}
impl RecordingWriteBackSink {
    fn new() -> Self {
        Self::default()
    }
    fn calls(&self) -> Vec<String> {
        self.calls.lock().unwrap().clone()
    }
}
#[async_trait]
impl WriteBackSink for RecordingWriteBackSink {
    async fn write_success(&self, envelope: &AnchorEnvelope) {
        self.calls.lock().unwrap().push(envelope.event_id.clone());
    }
}

fn fixture_envelope(event_id: &str) -> AnchorEnvelope {
    build_anchor_envelope(AnchorEmitterInput {
        event_id: event_id.to_string(),
        timestamp_utc: "2026-05-17T00:00:00Z".to_string(),
        persona_id: "reza".to_string(),
        payload_jcs_bytes: b"{}".to_vec(),
    })
    .expect("fixture envelope must build cleanly")
}

// Build a worker with manual clock + deterministic RNG. The default
// RNG always returns "max" so the backoff smoke tests can pin the
// next_delay exactly to the upper-bound formula.
fn make_worker(
    config: SubmitWorkerConfig,
    transport: Arc<FakeTransport>,
    clock: Arc<ManualClock>,
    rng_sequence: Vec<u64>,
) -> (
    SubmitWorker,
    Arc<InMemoryDeadLetterStore>,
    Arc<RecordingWriteBackSink>,
) {
    let dead_letter = Arc::new(InMemoryDeadLetterStore::new());
    let writeback = Arc::new(RecordingWriteBackSink::new());
    let rng = Arc::new(DeterministicRng::new(rng_sequence));
    let worker = SubmitWorker::new(
        config,
        transport.clone() as Arc<dyn SubmitTransport>,
        dead_letter.clone() as Arc<dyn DeadLetterStore>,
        writeback.clone() as Arc<dyn WriteBackSink>,
        clock as Arc<dyn Clock>,
        rng as Arc<dyn Rng>,
    );
    (worker, dead_letter, writeback)
}

// ---------------------------------------------------------------------
// Test 1 — rate_limit_honored.
// ---------------------------------------------------------------------

#[tokio::test]
async fn rate_limit_honored() {
    // Bucket: 1 req / 30s. Three envelopes queued, all eligible at
    // t=0. tick #1 succeeds; tick #2 is throttled; advance clock 30s;
    // tick #3 succeeds; tick #4 throttled again; advance another 30s;
    // tick #5 succeeds.
    let cfg = SubmitWorkerConfig {
        rate_requests: 1,
        rate_window: Duration::from_secs(30),
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("e1")).await;
    worker.enqueue(fixture_envelope("e2")).await;
    worker.enqueue(fixture_envelope("e3")).await;

    assert!(matches!(
        worker.tick().await,
        SubmitResult::Success { event_id } if event_id == "e1"
    ));
    assert!(matches!(
        worker.tick().await,
        SubmitResult::Throttled { event_id } if event_id == "e2"
    ));
    assert_eq!(transport.calls(), 1, "throttle must not call transport");

    clock.advance(30);
    assert!(matches!(
        worker.tick().await,
        SubmitResult::Success { event_id } if event_id == "e2"
    ));
    assert!(matches!(
        worker.tick().await,
        SubmitResult::Throttled { event_id } if event_id == "e3"
    ));

    clock.advance(30);
    assert!(matches!(
        worker.tick().await,
        SubmitResult::Success { event_id } if event_id == "e3"
    ));
    assert_eq!(worker.queue_len().await, 0);
}

// ---------------------------------------------------------------------
// Test 2 — retry_monotonic_backoff.
//
// The "monotonic" smoke contract for full-jitter is upper-bound
// doubling. We pin the RNG to always return the upper bound and
// assert the sequence 1s -> 2s -> 4s -> 8s -> 16s for base=1s,
// max=300s, max_retry=5.
// ---------------------------------------------------------------------

#[tokio::test]
async fn retry_monotonic_backoff() {
    let cfg = SubmitWorkerConfig {
        // Generous rate so the bucket never blocks the retry sequence.
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        max_retry: 5,
        retry_base_delay: Duration::from_secs(1),
        retry_max_delay: Duration::from_secs(300),
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("first".into()),
        TransportOutcome::Retriable("second".into()),
        TransportOutcome::Retriable("third".into()),
        TransportOutcome::Retriable("fourth".into()),
        TransportOutcome::Retriable("fifth".into()),
        TransportOutcome::Accepted,
    ]));
    let clock = Arc::new(ManualClock::new(0));
    // RNG always returns 999_999 -> clamps to upper bound.
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![999_999]);

    worker.enqueue(fixture_envelope("ev")).await;

    let mut delays: Vec<Duration> = Vec::new();
    for _ in 0..5 {
        let res = worker.tick().await;
        if let SubmitResult::Retrying { next_delay, .. } = res {
            delays.push(next_delay);
            // Advance clock past the backoff so the envelope is
            // eligible again on the next tick.
            clock.advance(next_delay.as_secs() + 1);
        } else {
            panic!("expected Retrying, got {:?}", res);
        }
    }

    assert_eq!(
        delays,
        vec![
            Duration::from_secs(1),
            Duration::from_secs(2),
            Duration::from_secs(4),
            Duration::from_secs(8),
            Duration::from_secs(16),
        ],
        "upper-bound backoff must double per attempt"
    );

    // Sixth attempt succeeds.
    assert!(matches!(
        worker.tick().await,
        SubmitResult::Success { event_id } if event_id == "ev"
    ));
}

// ---------------------------------------------------------------------
// Test 3 — dead_letter_after_max.
// ---------------------------------------------------------------------

#[tokio::test]
async fn dead_letter_after_max() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        max_retry: 3,
        retry_base_delay: Duration::from_secs(1),
        retry_max_delay: Duration::from_secs(300),
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("e-1".into()),
        TransportOutcome::Retriable("e-2".into()),
        TransportOutcome::Retriable("e-3".into()),
        TransportOutcome::Retriable("terminal-fail".into()),
    ]));
    let clock = Arc::new(ManualClock::new(0));
    // RNG: 0 -> all backoffs are zero so we don't need to advance clock.
    let (worker, dead_letter, writeback) =
        make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("dead-one")).await;

    // 3 retries within budget.
    for attempt in 1..=3u32 {
        let res = worker.tick().await;
        match res {
            SubmitResult::Retrying { attempt: a, .. } => assert_eq!(a, attempt),
            _ => panic!("expected Retrying #{}, got {:?}", attempt, res),
        }
    }
    // 4th attempt: retry-count would become 4 (> 3) -> dead-letter.
    let res = worker.tick().await;
    match res {
        SubmitResult::Dead {
            event_id,
            terminal_error,
        } => {
            assert_eq!(event_id, "dead-one");
            assert_eq!(terminal_error, "terminal-fail");
        }
        _ => panic!("expected Dead, got {:?}", res),
    }

    let snap = dead_letter.snapshot().await;
    assert_eq!(snap.len(), 1);
    assert_eq!(snap[0].event_id, "dead-one");
    assert_eq!(snap[0].retry_count, 4);
    assert_eq!(snap[0].terminal_error, "terminal-fail");

    assert_eq!(writeback.calls().len(), 0, "no success -> no writeback");
    assert_eq!(worker.queue_len().await, 0);
}

// ---------------------------------------------------------------------
// Test 4 — success_fast_path.
// ---------------------------------------------------------------------

#[tokio::test]
async fn success_fast_path() {
    let cfg = SubmitWorkerConfig::default();
    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Accepted]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, dead_letter, writeback) =
        make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("happy")).await;

    let res = worker.tick().await;
    assert!(
        matches!(res, SubmitResult::Success { ref event_id } if event_id == "happy"),
        "fast path must produce Success, got {:?}",
        res
    );

    assert_eq!(writeback.calls(), vec!["happy".to_string()]);
    assert!(dead_letter.snapshot().await.is_empty());
    assert_eq!(worker.queue_len().await, 0);
    assert_eq!(transport.calls(), 1);
}

// ---------------------------------------------------------------------
// Test 5 — throttle_no_side_effects.
// ---------------------------------------------------------------------

#[tokio::test]
async fn throttle_no_side_effects() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 1,
        rate_window: Duration::from_secs(60),
        ..SubmitWorkerConfig::default()
    };
    // Only ONE outcome scripted — the second submit() call would panic
    // (transport script-exhausted guard). If throttle accidentally
    // calls the transport, the test fails loud.
    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Accepted]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, dead_letter, writeback) =
        make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("a")).await;
    worker.enqueue(fixture_envelope("b")).await;

    let _ = worker.tick().await; // consumes token, "a" succeeds.
    let r2 = worker.tick().await; // throttled — MUST NOT call transport.
    assert!(matches!(r2, SubmitResult::Throttled { .. }));

    assert_eq!(
        transport.calls(),
        1,
        "throttle path must not invoke transport"
    );
    assert_eq!(
        writeback.calls(),
        vec!["a".to_string()],
        "throttle must not invoke writeback"
    );
    assert!(
        dead_letter.snapshot().await.is_empty(),
        "throttle must not dead-letter"
    );
    assert_eq!(
        worker.queue_len().await,
        1,
        "throttled envelope must remain in the queue"
    );
}

// ---------------------------------------------------------------------
// Test 6 — idle_when_queue_empty.
// ---------------------------------------------------------------------

#[tokio::test]
async fn idle_when_queue_empty() {
    let cfg = SubmitWorkerConfig::default();
    let transport = Arc::new(FakeTransport::new(vec![]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    let res = worker.tick().await;
    assert_eq!(res, SubmitResult::Idle);
    assert_eq!(transport.calls(), 0);
}

// ---------------------------------------------------------------------
// Test 7 — permanent_error_dead_letters_immediately.
// ---------------------------------------------------------------------

#[tokio::test]
async fn permanent_error_dead_letters_immediately() {
    let cfg = SubmitWorkerConfig::default();
    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Permanent(
        "malformed-envelope".into(),
    )]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, dead_letter, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("perm-fail")).await;

    let res = worker.tick().await;
    match res {
        SubmitResult::Dead {
            event_id,
            terminal_error,
        } => {
            assert_eq!(event_id, "perm-fail");
            assert_eq!(terminal_error, "malformed-envelope");
        }
        _ => panic!("expected Dead, got {:?}", res),
    }
    assert_eq!(dead_letter.snapshot().await.len(), 1);
}

// ---------------------------------------------------------------------
// Test 8 — permanent_error_does_not_consume_retry_budget.
// ---------------------------------------------------------------------

#[tokio::test]
async fn permanent_error_does_not_consume_retry_budget() {
    let cfg = SubmitWorkerConfig {
        max_retry: 5,
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Permanent(
        "schema".into(),
    )]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, dead_letter, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("perm")).await;
    let _ = worker.tick().await;

    let snap = dead_letter.snapshot().await;
    assert_eq!(snap.len(), 1);
    // Permanent error -> retry_count stays 0 (no retry was attempted).
    assert_eq!(snap[0].retry_count, 0);
}

// ---------------------------------------------------------------------
// Test 9 — retry_count_increments_per_attempt.
// ---------------------------------------------------------------------

#[tokio::test]
async fn retry_count_increments_per_attempt() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        max_retry: 5,
        retry_base_delay: Duration::from_secs(1),
        retry_max_delay: Duration::from_secs(300),
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("r1".into()),
        TransportOutcome::Retriable("r2".into()),
        TransportOutcome::Retriable("r3".into()),
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("rc")).await;

    let mut attempts: Vec<u32> = Vec::new();
    for _ in 0..3 {
        match worker.tick().await {
            SubmitResult::Retrying { attempt, .. } => attempts.push(attempt),
            other => panic!("expected Retrying, got {:?}", other),
        }
    }
    assert_eq!(attempts, vec![1, 2, 3]);
}

// ---------------------------------------------------------------------
// Test 10 — dead_letter_record_carries_terminal_error.
// ---------------------------------------------------------------------

#[tokio::test]
async fn dead_letter_record_carries_terminal_error() {
    let cfg = SubmitWorkerConfig {
        max_retry: 1,
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("first-error".into()),
        TransportOutcome::Retriable("LAST-ERROR-PIN".into()),
    ]));
    let clock = Arc::new(ManualClock::new(100));
    let (worker, dead_letter, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("ev-err")).await;
    let _ = worker.tick().await; // retry 1
    let _ = worker.tick().await; // dead-letter (retry would be 2 > 1)

    let snap = dead_letter.snapshot().await;
    assert_eq!(snap.len(), 1);
    assert_eq!(
        snap[0].terminal_error, "LAST-ERROR-PIN",
        "dead-letter must carry the LAST retriable error string"
    );
}

// ---------------------------------------------------------------------
// Test 11 — dead_letter_record_carries_persona_id.
// ---------------------------------------------------------------------

#[tokio::test]
async fn dead_letter_record_carries_persona_id() {
    let cfg = SubmitWorkerConfig::default();
    let transport = Arc::new(FakeTransport::new(vec![TransportOutcome::Permanent(
        "perma".into(),
    )]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, dead_letter, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    let env = build_anchor_envelope(AnchorEmitterInput {
        event_id: "x1".into(),
        timestamp_utc: "2026-05-17T00:00:00Z".into(),
        persona_id: "selin".into(),
        payload_jcs_bytes: vec![],
    })
    .unwrap();
    worker.enqueue(env).await;
    let _ = worker.tick().await;

    let snap = dead_letter.snapshot().await;
    assert_eq!(snap.len(), 1);
    assert_eq!(snap[0].persona_id, "selin");
    // dead_letter_at must be RFC-3339 second-precision UTC shape.
    assert!(snap[0].dead_letter_at.ends_with('Z'));
    assert_eq!(snap[0].dead_letter_at.len(), 20);
}

// ---------------------------------------------------------------------
// Test 12 — writeback_invoked_on_success_only.
// ---------------------------------------------------------------------

#[tokio::test]
async fn writeback_invoked_on_success_only() {
    let cfg = SubmitWorkerConfig {
        max_retry: 1,
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("err".into()),
        TransportOutcome::Retriable("err".into()),
        TransportOutcome::Accepted,
        TransportOutcome::Permanent("perm".into()),
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, writeback) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("ok")).await;
    worker.enqueue(fixture_envelope("doomed")).await;

    // "ok": retry, dead-letter (because max_retry=1 would make this
    // retry_count=2 > 1)... actually let's tweak to exercise success.
    // We rebuild: just submit each one separately.
    let _ = worker.tick().await; // ok -> Retrying (count=1)
    let _ = worker.tick().await; // doomed -> Retrying (count=1)
    let _ = worker.tick().await; // ok -> Success
    assert_eq!(writeback.calls(), vec!["ok".to_string()]);
    let _ = worker.tick().await; // doomed -> Dead (perm)
    assert_eq!(
        writeback.calls(),
        vec!["ok".to_string()],
        "writeback must be invoked exactly once (on success)"
    );
}

// ---------------------------------------------------------------------
// Test 13 — throttle_re_enters_queue_at_front.
// ---------------------------------------------------------------------

#[tokio::test]
async fn throttle_re_enters_queue_at_front() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 1,
        rate_window: Duration::from_secs(60),
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("first")).await;
    worker.enqueue(fixture_envelope("second")).await;

    let _ = worker.tick().await; // first -> Success
    let r2 = worker.tick().await; // second -> Throttled
    assert!(matches!(r2, SubmitResult::Throttled { event_id } if event_id == "second"));

    clock.advance(60);
    let r3 = worker.tick().await;
    assert!(
        matches!(&r3, SubmitResult::Success { event_id } if event_id == "second"),
        "the throttled envelope must be served first on next eligible tick, got {:?}",
        r3
    );
}

// ---------------------------------------------------------------------
// Test 14 — config_default_matches_sprint_auftrag.
// ---------------------------------------------------------------------

#[tokio::test]
async fn config_default_matches_sprint_auftrag() {
    let cfg = SubmitWorkerConfig::default();
    assert_eq!(cfg.rate_requests, DEFAULT_RATE_REQUESTS);
    assert_eq!(cfg.rate_requests, 1);
    assert_eq!(cfg.rate_window.as_secs(), DEFAULT_RATE_WINDOW_SECS);
    assert_eq!(cfg.rate_window.as_secs(), 30);
    assert_eq!(cfg.max_retry, DEFAULT_MAX_RETRY);
    assert_eq!(cfg.max_retry, 5);
    assert_eq!(cfg.retry_base_delay, DEFAULT_RETRY_BASE_DELAY);
    assert_eq!(cfg.retry_max_delay, DEFAULT_RETRY_MAX_DELAY);
}

// ---------------------------------------------------------------------
// Test 15 — token_bucket_refills_between_ticks.
// ---------------------------------------------------------------------

#[tokio::test]
async fn token_bucket_refills_between_ticks() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 1,
        rate_window: Duration::from_secs(10),
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("a")).await;
    worker.enqueue(fixture_envelope("b")).await;
    worker.enqueue(fixture_envelope("c")).await;

    assert!(matches!(worker.tick().await, SubmitResult::Success { .. }));
    clock.advance(10);
    assert!(matches!(worker.tick().await, SubmitResult::Success { .. }));
    clock.advance(10);
    assert!(matches!(worker.tick().await, SubmitResult::Success { .. }));
    assert_eq!(worker.queue_len().await, 0);
}

// ---------------------------------------------------------------------
// Test 16 — backoff_upper_bound_doubles_per_attempt.
//
// Direct property test: pin the RNG to "always return upper bound",
// drive successive retries, and verify the upper bound doubles 1->2->4
// up to the cap.
// ---------------------------------------------------------------------

#[tokio::test]
async fn backoff_upper_bound_doubles_per_attempt() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        max_retry: 6,
        retry_base_delay: Duration::from_secs(1),
        retry_max_delay: Duration::from_secs(8), // cap caught at attempt 4 (8s).
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Retriable("r".into()),
        TransportOutcome::Retriable("r".into()),
        TransportOutcome::Retriable("r".into()),
        TransportOutcome::Retriable("r".into()),
        TransportOutcome::Retriable("r".into()),
        TransportOutcome::Retriable("r".into()),
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![999_999]);

    worker.enqueue(fixture_envelope("bo")).await;

    let mut delays = vec![];
    for _ in 0..6 {
        let r = worker.tick().await;
        if let SubmitResult::Retrying { next_delay, .. } = r {
            delays.push(next_delay.as_secs());
            clock.advance(next_delay.as_secs() + 1);
        }
    }
    // 1, 2, 4, 8, 8, 8 — capped at retry_max_delay=8.
    assert_eq!(delays, vec![1, 2, 4, 8, 8, 8]);
}

// ---------------------------------------------------------------------
// Test 17 — multi_envelope_round_robin_through_ticks.
// ---------------------------------------------------------------------

#[tokio::test]
async fn multi_envelope_round_robin_through_ticks() {
    let cfg = SubmitWorkerConfig {
        rate_requests: 100,
        rate_window: Duration::from_secs(1),
        ..SubmitWorkerConfig::default()
    };
    let transport = Arc::new(FakeTransport::new(vec![
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
        TransportOutcome::Accepted,
    ]));
    let clock = Arc::new(ManualClock::new(0));
    let (worker, _dl, _wb) = make_worker(cfg, transport.clone(), clock.clone(), vec![0]);

    worker.enqueue(fixture_envelope("first")).await;
    worker.enqueue(fixture_envelope("second")).await;
    worker.enqueue(fixture_envelope("third")).await;

    for _ in 0..3 {
        let r = worker.tick().await;
        assert!(matches!(r, SubmitResult::Success { .. }));
    }
    assert!(matches!(worker.tick().await, SubmitResult::Idle));
    assert_eq!(
        transport.seen(),
        vec![
            "first".to_string(),
            "second".to_string(),
            "third".to_string()
        ]
    );
}

// ---------------------------------------------------------------------
// Re-export smoke: the crate re-exports `AnchorEnvelope` from the
// emitter crate, so downstream callers don't need a second dep line.
// ---------------------------------------------------------------------

#[tokio::test]
async fn reexported_anchor_envelope_type_matches() {
    let env: ReexportedAnchorEnvelope = fixture_envelope("re-exp");
    assert_eq!(env.event_id, "re-exp");
    assert_eq!(env.persona_id, "reza");
}

// ---------------------------------------------------------------------
// NoopWriteBackSink + SystemClock smoke — exercise the default impls.
// ---------------------------------------------------------------------

#[tokio::test]
async fn noop_writeback_and_system_clock_compile_and_run() {
    let sink: Arc<NoopWriteBackSink> = Arc::new(NoopWriteBackSink);
    let env = fixture_envelope("ny");
    sink.write_success(&env).await;
    let clock = SystemClock;
    let _ = clock.now_secs();
}
