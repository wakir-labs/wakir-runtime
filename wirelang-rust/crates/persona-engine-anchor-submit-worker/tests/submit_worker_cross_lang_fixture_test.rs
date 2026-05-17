// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-anchor-submit-worker.
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/anchor-submit-worker-cross-lang/fixtures.json` at
// the repo root) that the Python sibling test
// (`tests/wat/test_anchor_submit_worker_cross_lang_parity.py`)
// consumes. Both sides drive identical scripted scenarios through
// the deterministic FSM (manual clock + deterministic RNG +
// scripted transport) and pin the same decision-record byte
// strings + canonical hashes. Any drift on either side breaks both
// test suites — that is the intended boundary detector.
//
// Test taxonomy
// -------------
// - F01 — Fixture file loads, schema_version matches the
//   `DECISION_RECORD_SCHEMA` constant, exactly five vectors
//   present with the expected names.
// - F02..F06 — Per-fixture byte-level pin: replay the tick-program
//   against a freshly-constructed Rust `SubmitWorker`, emit a
//   decision-record JSON object per tick that is byte-identical to
//   the Python sibling's `serialize_decision_record(result)` output,
//   then compare against the fixture's pinned `decision_jcs_b64` and
//   `decision_hash_prefixed` fields.
//
// Decision-record wire-shape (cross-lang pin with Python)
// -------------------------------------------------------
// Top-level keys (lex-ordered for JCS):
//
//   attempt          (u32, 0 for Success/Throttled/Idle/permanent-Dead)
//   event_id         (String, "" for Idle)
//   kind             (one of "success", "throttled", "retrying",
//                     "dead", "idle")
//   next_delay_secs  (u64, 0 for non-Retrying outcomes)
//   terminal_error   (String, "" for non-Dead)
//
// JCS serialiser: this test rolls a minimal canonical JSON encoder
// (lex-sorted top-level keys, no whitespace, ASCII-safe). The Python
// sibling uses Python's `json.dumps(..., separators=(',',':'),
// sort_keys=True, ensure_ascii=False)` which produces the same bytes
// for the shape we emit here (no Unicode in any decision-record
// field; the event_id and terminal_error strings in the fixture set
// are ASCII).

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use async_trait::async_trait;
use persona_engine_anchor_emitter::{build_anchor_envelope, AnchorEmitterInput, AnchorEnvelope};
use persona_engine_anchor_submit_worker::{
    Clock, DeadLetterRecord, DeadLetterStore, DeterministicRng, InMemoryDeadLetterStore, Rng,
    SubmitResult, SubmitTransport, SubmitWorker, SubmitWorkerConfig, TransportOutcome,
    WriteBackSink,
};
use serde_json::Value;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet).
// ---------------------------------------------------------------------

fn b64_decode(input: &str) -> Vec<u8> {
    fn val(c: u8) -> Option<u8> {
        match c {
            b'A'..=b'Z' => Some(c - b'A'),
            b'a'..=b'z' => Some(c - b'a' + 26),
            b'0'..=b'9' => Some(c - b'0' + 52),
            b'+' => Some(62),
            b'/' => Some(63),
            _ => None,
        }
    }
    let bytes: Vec<u8> = input.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len() * 3 / 4 + 3);
    let mut buf: u32 = 0;
    let mut bits: u8 = 0;
    for &c in &bytes {
        if c == b'=' {
            break;
        }
        let v = val(c).unwrap_or_else(|| panic!("invalid b64 char: {:?}", c as char));
        buf = (buf << 6) | v as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((buf >> bits) & 0xff) as u8);
        }
    }
    out
}

// ---------------------------------------------------------------------
// SHA-256 helper (re-uses `sha2` via the emitter's transitive dep).
// ---------------------------------------------------------------------

fn sha256_hex(bytes: &[u8]) -> String {
    // Re-use the SHA-256 helper exposed by the emitter crate so we
    // don't add an extra `sha2` dev-dep here.
    persona_engine_anchor_emitter::sha256_hex(bytes)
}

// ---------------------------------------------------------------------
// Fixture file path resolution.
// ---------------------------------------------------------------------

fn fixture_path() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("could not resolve repo root from CARGO_MANIFEST_DIR");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("anchor-submit-worker-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let bytes = std::fs::read(fixture_path()).expect("fixtures.json must exist at repo-root path");
    serde_json::from_slice(&bytes).expect("fixtures.json must parse as JSON")
}

// ---------------------------------------------------------------------
// Test substrates — manual clock, scripted transport, recording sinks.
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
struct ScriptedTransport {
    script: StdMutex<Vec<TransportOutcome>>,
    calls: AtomicU64,
    seen: StdMutex<Vec<String>>,
}
impl ScriptedTransport {
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
impl SubmitTransport for ScriptedTransport {
    async fn submit(&self, envelope: &AnchorEnvelope) -> TransportOutcome {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.seen.lock().unwrap().push(envelope.event_id.clone());
        let mut s = self.script.lock().unwrap();
        if s.is_empty() {
            panic!(
                "ScriptedTransport script exhausted but submit() was called for {:?}",
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

// ---------------------------------------------------------------------
// Decision-record builder — canonical JSON (lex keys, no whitespace).
// ---------------------------------------------------------------------

fn decision_record_json(result: &SubmitResult) -> String {
    let (kind, event_id, attempt, next_delay_secs, terminal_error): (
        &str,
        String,
        u32,
        u64,
        String,
    ) = match result {
        SubmitResult::Success { event_id } => ("success", event_id.clone(), 0, 0, String::new()),
        SubmitResult::Throttled { event_id } => {
            ("throttled", event_id.clone(), 0, 0, String::new())
        }
        SubmitResult::Retrying {
            event_id,
            attempt,
            next_delay,
        } => (
            "retrying",
            event_id.clone(),
            *attempt,
            next_delay.as_secs(),
            String::new(),
        ),
        SubmitResult::Dead {
            event_id,
            terminal_error,
        } => ("dead", event_id.clone(), 0, 0, terminal_error.clone()),
        SubmitResult::Idle => ("idle", String::new(), 0, 0, String::new()),
    };
    // Build JCS-style canonical JSON: lex-ordered keys, no whitespace.
    // The Python sibling uses `json.dumps(sort_keys=True,
    // separators=(',',':'), ensure_ascii=False)`. For ASCII-only
    // values this matches `serde_json::to_string` of a BTreeMap with
    // String keys + careful escape rules. The Python `dead` variant
    // emits `attempt=4` for the retry-exhausted case but the Rust
    // crate's `SubmitResult::Dead` does not carry `attempt` — we look
    // up the dead-letter snapshot from the worker to recover it. To
    // keep this test self-contained, we apply a special override
    // below: the caller passes the dead-letter retry_count for the
    // Dead branch.
    use serde_json::json;
    let v = json!({
        "attempt": attempt,
        "event_id": event_id,
        "kind": kind,
        "next_delay_secs": next_delay_secs,
        "terminal_error": terminal_error,
    });
    serde_json::to_string(&v).expect("decision record must serialise")
}

/// Decision record with an explicit attempt override (used for the
/// Dead variant where the Rust enum doesn't carry the retry counter
/// but the cross-lang wire-shape does).
fn decision_record_json_with_attempt(result: &SubmitResult, attempt_override: u32) -> String {
    use serde_json::json;
    let (kind, event_id, attempt, next_delay_secs, terminal_error): (
        &str,
        String,
        u32,
        u64,
        String,
    ) = match result {
        SubmitResult::Success { event_id } => ("success", event_id.clone(), 0, 0, String::new()),
        SubmitResult::Throttled { event_id } => {
            ("throttled", event_id.clone(), 0, 0, String::new())
        }
        SubmitResult::Retrying {
            event_id,
            attempt,
            next_delay,
        } => (
            "retrying",
            event_id.clone(),
            *attempt,
            next_delay.as_secs(),
            String::new(),
        ),
        SubmitResult::Dead {
            event_id,
            terminal_error,
        } => (
            "dead",
            event_id.clone(),
            attempt_override,
            0,
            terminal_error.clone(),
        ),
        SubmitResult::Idle => ("idle", String::new(), 0, 0, String::new()),
    };
    let v = json!({
        "attempt": attempt,
        "event_id": event_id,
        "kind": kind,
        "next_delay_secs": next_delay_secs,
        "terminal_error": terminal_error,
    });
    serde_json::to_string(&v).expect("decision record must serialise")
}

// ---------------------------------------------------------------------
// Fixture-driven replay.
// ---------------------------------------------------------------------

fn outcome_from_json(v: &Value) -> TransportOutcome {
    let kind = v["kind"].as_str().expect("transport_script.kind missing");
    let err = v["error"].as_str().unwrap_or("").to_string();
    match kind {
        "accepted" => TransportOutcome::Accepted,
        "retriable" => TransportOutcome::Retriable(err),
        "permanent" => TransportOutcome::Permanent(err),
        other => panic!("unknown transport outcome kind: {}", other),
    }
}

fn envelope_from_json(v: &Value) -> AnchorEnvelope {
    let event_id = v["event_id"].as_str().expect("event_id missing").to_string();
    let persona_id = v["persona_id"]
        .as_str()
        .expect("persona_id missing")
        .to_string();
    build_anchor_envelope(AnchorEmitterInput {
        event_id,
        timestamp_utc: "2026-05-17T00:00:00Z".to_string(),
        persona_id,
        payload_jcs_bytes: b"{}".to_vec(),
    })
    .expect("fixture envelope must build cleanly")
}

#[tokio::test]
async fn f01_fixture_file_loads_and_schema_matches() {
    let doc = load_fixtures();
    assert_eq!(
        doc["schema_version"].as_str().unwrap(),
        "wakir.wat.anchor-submit-decision/1"
    );
    let fixtures = doc["fixtures"].as_array().expect("fixtures must be array");
    assert_eq!(fixtures.len(), 5, "expected exactly five fixture vectors");
    let names: Vec<&str> = fixtures
        .iter()
        .map(|f| f["name"].as_str().unwrap())
        .collect();
    assert_eq!(
        names,
        vec![
            "f01-success-fast-path",
            "f02-throttled-rate-limit",
            "f03-retry-backoff-success",
            "f04-retry-exhausted-dead-letter",
            "f05-idle-empty-queue",
        ]
    );
}

/// Replay one fixture and return (ledger_json_strings, transport_calls,
/// transport_seen, writeback_calls, dead_letter_snapshot_json,
/// queue_len_final).
async fn replay_fixture(fx: &Value) -> ReplayDerived {
    let inp = &fx["input"];
    let cfg_in = &inp["config"];
    let cfg = SubmitWorkerConfig {
        rate_requests: cfg_in["rate_requests"].as_u64().unwrap() as u32,
        rate_window: Duration::from_secs(cfg_in["rate_window_secs"].as_u64().unwrap()),
        max_retry: cfg_in["max_retry"].as_u64().unwrap() as u32,
        retry_base_delay: Duration::from_secs(cfg_in["retry_base_delay_secs"].as_u64().unwrap()),
        retry_max_delay: Duration::from_secs(cfg_in["retry_max_delay_secs"].as_u64().unwrap()),
    };
    let transport_script: Vec<TransportOutcome> = inp["transport_script"]
        .as_array()
        .unwrap()
        .iter()
        .map(outcome_from_json)
        .collect();
    let rng_sequence: Vec<u64> = inp["rng_sequence"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().expect("rng entry must be u64"))
        .collect();
    let clock_start = inp["clock_start_secs"].as_u64().unwrap();

    let clock = Arc::new(ManualClock::new(clock_start));
    let transport = Arc::new(ScriptedTransport::new(transport_script));
    let dead_letter = Arc::new(InMemoryDeadLetterStore::new());
    let writeback = Arc::new(RecordingWriteBackSink::new());
    let rng = Arc::new(DeterministicRng::new(rng_sequence));

    let worker = SubmitWorker::new(
        cfg,
        transport.clone() as Arc<dyn SubmitTransport>,
        dead_letter.clone() as Arc<dyn DeadLetterStore>,
        writeback.clone() as Arc<dyn WriteBackSink>,
        clock.clone() as Arc<dyn Clock>,
        rng as Arc<dyn Rng>,
    );

    for env in inp["enqueues"].as_array().unwrap() {
        worker.enqueue(envelope_from_json(env)).await;
    }

    // The Dead variant in the Rust crate doesn't carry retry_count
    // directly; we track the dead-letter snapshot inline so we can
    // look up the matching record by event_id and recover the
    // counter for the decision-record `attempt` field.
    let mut ledger: Vec<LedgerEntry> = Vec::new();
    for step in inp["tick_program"].as_array().unwrap() {
        let op = step["op"].as_str().unwrap();
        match op {
            "tick" => {
                let r = worker.tick().await;
                let json_str = match &r {
                    SubmitResult::Dead { event_id, .. } => {
                        // Look up retry_count from the dead-letter
                        // snapshot for this event_id.
                        let snap = dead_letter.snapshot().await;
                        let rc = snap
                            .iter()
                            .find(|rec| &rec.event_id == event_id)
                            .map(|rec| rec.retry_count)
                            .unwrap_or(0);
                        decision_record_json_with_attempt(&r, rc)
                    }
                    _ => decision_record_json(&r),
                };
                let canonical = json_str.into_bytes();
                let hash = format!("sha256:{}", sha256_hex(&canonical));
                ledger.push(LedgerEntry {
                    decision_jcs_bytes: canonical,
                    decision_hash_prefixed: hash,
                });
            }
            "advance_clock" => {
                clock.advance(step["by_secs"].as_u64().unwrap());
            }
            "enqueue" => {
                worker.enqueue(envelope_from_json(&step["envelope"])).await;
            }
            other => panic!("unknown op: {}", other),
        }
    }

    let dl_snapshot = dead_letter.snapshot().await;

    ReplayDerived {
        ledger,
        transport_calls: transport.calls(),
        transport_seen: transport.seen(),
        writeback_calls: writeback.calls(),
        dead_letter_snapshot: dl_snapshot,
        queue_len_final: worker.queue_len().await,
    }
}

struct LedgerEntry {
    decision_jcs_bytes: Vec<u8>,
    decision_hash_prefixed: String,
}

struct ReplayDerived {
    ledger: Vec<LedgerEntry>,
    transport_calls: u64,
    transport_seen: Vec<String>,
    writeback_calls: Vec<String>,
    dead_letter_snapshot: Vec<DeadLetterRecord>,
    queue_len_final: usize,
}

async fn assert_fixture_parity(fixture_name: &str) {
    let doc = load_fixtures();
    let fx = doc["fixtures"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"].as_str() == Some(fixture_name))
        .unwrap_or_else(|| panic!("fixture {} not found", fixture_name));

    let derived = replay_fixture(fx).await;

    let expected_ledger = fx["expected"]["ledger"].as_array().unwrap();
    assert_eq!(
        derived.ledger.len(),
        expected_ledger.len(),
        "ledger length mismatch for {}",
        fixture_name
    );
    for (i, (got, want)) in derived.ledger.iter().zip(expected_ledger.iter()).enumerate() {
        let want_bytes = b64_decode(want["decision_jcs_b64"].as_str().unwrap());
        let want_hash = want["decision_hash_prefixed"].as_str().unwrap();
        assert_eq!(
            got.decision_jcs_bytes,
            want_bytes,
            "{} entry #{} decision JCS bytes mismatch\n  got=  {}\n  want= {}",
            fixture_name,
            i,
            String::from_utf8_lossy(&got.decision_jcs_bytes),
            String::from_utf8_lossy(&want_bytes),
        );
        assert_eq!(
            got.decision_hash_prefixed, want_hash,
            "{} entry #{} decision hash mismatch",
            fixture_name, i
        );
    }

    let exp = &fx["expected"];
    assert_eq!(
        derived.transport_calls,
        exp["transport_calls"].as_u64().unwrap(),
        "{} transport_calls drift",
        fixture_name
    );
    let exp_seen: Vec<String> = exp["transport_seen"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    assert_eq!(
        derived.transport_seen, exp_seen,
        "{} transport_seen drift",
        fixture_name
    );
    let exp_wb: Vec<String> = exp["writeback_calls"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();
    assert_eq!(
        derived.writeback_calls, exp_wb,
        "{} writeback_calls drift",
        fixture_name
    );
    let exp_dl_arr = exp["dead_letter_snapshot"].as_array().unwrap();
    assert_eq!(
        derived.dead_letter_snapshot.len(),
        exp_dl_arr.len(),
        "{} dead_letter length drift",
        fixture_name
    );
    for (rec, want) in derived.dead_letter_snapshot.iter().zip(exp_dl_arr.iter()) {
        assert_eq!(
            rec.event_id,
            want["event_id"].as_str().unwrap(),
            "{} dl.event_id drift",
            fixture_name
        );
        assert_eq!(
            rec.persona_id,
            want["persona_id"].as_str().unwrap(),
            "{} dl.persona_id drift",
            fixture_name
        );
        assert_eq!(
            rec.dead_letter_at,
            want["dead_letter_at"].as_str().unwrap(),
            "{} dl.dead_letter_at drift",
            fixture_name
        );
        assert_eq!(
            rec.terminal_error,
            want["terminal_error"].as_str().unwrap(),
            "{} dl.terminal_error drift",
            fixture_name
        );
        assert_eq!(
            rec.retry_count as u64,
            want["retry_count"].as_u64().unwrap(),
            "{} dl.retry_count drift",
            fixture_name
        );
    }
    assert_eq!(
        derived.queue_len_final as u64,
        exp["queue_len_final"].as_u64().unwrap(),
        "{} queue_len_final drift",
        fixture_name
    );
}

#[tokio::test]
async fn f02_success_fast_path_byte_parity() {
    assert_fixture_parity("f01-success-fast-path").await;
}

#[tokio::test]
async fn f03_throttled_rate_limit_byte_parity() {
    assert_fixture_parity("f02-throttled-rate-limit").await;
}

#[tokio::test]
async fn f04_retry_backoff_success_byte_parity() {
    assert_fixture_parity("f03-retry-backoff-success").await;
}

#[tokio::test]
async fn f05_retry_exhausted_dead_letter_byte_parity() {
    assert_fixture_parity("f04-retry-exhausted-dead-letter").await;
}

#[tokio::test]
async fn f06_idle_empty_queue_byte_parity() {
    assert_fixture_parity("f05-idle-empty-queue").await;
}
