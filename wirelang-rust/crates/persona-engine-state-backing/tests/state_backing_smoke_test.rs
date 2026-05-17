// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Smoke tests for `persona-engine-state-backing` (Phase-3a Item 6).
//!
//! These tests exercise the [`InMemoryStateBacking`] binding only;
//! [`NatsKvStateBacking`] is a scaffold stub and its trait methods
//! return `StateBackingError::NatsKv` (asserted in tests 11 and 12
//! as the documented-today behaviour).
//!
//! Test inventory (>=10):
//!
//!  1. `test_01_snapshot_assigns_monotonic_offsets`
//!  2. `test_02_snapshot_is_idempotent_for_byte_equal_state`
//!  3. `test_03_restore_latest_returns_most_recent`
//!  4. `test_04_restore_latest_returns_none_on_cold_start`
//!  5. `test_05_list_snapshots_returns_oldest_first`
//!  6. `test_06_atomic_swap_pinned_offset_happy_path`
//!  7. `test_07_atomic_swap_pinned_offset_cas_failure`
//!  8. `test_08_atomic_swap_pinned_offset_unknown_offset`
//!  9. `test_09_per_persona_isolation`
//! 10. `test_10_jcs_canonical_bytes_are_byte_stable`
//! 11. `test_11_snapshot_payload_sha256_byte_stable`
//! 12. `test_12_snapshot_from_jcs_bytes_round_trip`
//! 13. `test_13_offset_key_round_trip_smoke`
//! 14. `test_14_watch_revisions_emits_snapshot_event`
//! 15. `test_15_watch_revisions_emits_pinned_event`
//! 16. `test_16_natskv_stub_returns_nats_kv_error`
//! 17. `test_17_natskv_bucket_name_shape`
//! 18. `test_18_snapshot_from_jcs_bytes_missing_key_rejected`
//! 19. `test_19_snapshot_from_jcs_bytes_corrupt_json_rejected`
//! 20. `test_20_keys_ordering_matches_offset_ordering`

use persona_engine_state_backing::{
    offset_from_key, offset_key, snapshot_from_jcs_bytes, snapshot_payload_sha256,
    snapshot_to_jcs_bytes, InMemoryStateBacking, NatsKvStateBacking, PersonaStateSnapshot,
    RevisionEvent, StateBacking, StateBackingError, LATEST_KEY, NEXT_OFFSET_KEY,
    OFFSET_KEY_WIDTH, PINNED_KEY, STATE_PACK_KEY_PREFIX,
};

// ---------------------------------------------------------------------------
// Test fixtures.
// ---------------------------------------------------------------------------

fn fixture_snapshot(offset_hint: u64, tokens: &[&str]) -> PersonaStateSnapshot {
    PersonaStateSnapshot {
        persona_hash: "sha256:1111111111111111111111111111111111111111111111111111111111111111".into(),
        audit_trace_offset: offset_hint,
        capability_token_ids: tokens.iter().map(|s| s.to_string()).collect(),
        snapshot_at_utc: "2026-05-17T00:00:00Z".into(),
        workspace_state_hash: "sha256:2222222222222222222222222222222222222222222222222222222222222222".into(),
    }
}

fn fixture_distinct_snapshot(persona_hash_suffix: u8) -> PersonaStateSnapshot {
    let hex_byte = format!("{:02x}", persona_hash_suffix);
    PersonaStateSnapshot {
        persona_hash: format!("sha256:{}{}", hex_byte, "1".repeat(62)),
        audit_trace_offset: 0,
        capability_token_ids: vec![format!("token-{}", persona_hash_suffix)],
        snapshot_at_utc: "2026-05-17T00:00:00Z".into(),
        workspace_state_hash: "sha256:3333333333333333333333333333333333333333333333333333333333333333".into(),
    }
}

// ---------------------------------------------------------------------------
// Test 01 — monotonic offset assignment.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_01_snapshot_assigns_monotonic_offsets() {
    let backing = InMemoryStateBacking::new();
    let s1 = fixture_distinct_snapshot(1);
    let s2 = fixture_distinct_snapshot(2);
    let s3 = fixture_distinct_snapshot(3);

    let off1 = backing.snapshot("persona-A", s1).await.unwrap();
    let off2 = backing.snapshot("persona-A", s2).await.unwrap();
    let off3 = backing.snapshot("persona-A", s3).await.unwrap();

    assert_eq!(off1, 1, "first snapshot should land at offset 1");
    assert_eq!(off2, 2, "second snapshot should land at offset 2");
    assert_eq!(off3, 3, "third snapshot should land at offset 3");
}

// ---------------------------------------------------------------------------
// Test 02 — idempotent byte-equal snapshots.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_02_snapshot_is_idempotent_for_byte_equal_state() {
    let backing = InMemoryStateBacking::new();
    let s1 = fixture_snapshot(0, &["tok-a"]);
    let off1 = backing.snapshot("persona-A", s1.clone()).await.unwrap();
    // Same byte-content -> same offset, no new write.
    let off1_again = backing.snapshot("persona-A", s1).await.unwrap();
    assert_eq!(off1, off1_again, "byte-equal snapshot must return existing offset");

    let offsets = backing.list_snapshots("persona-A").await.unwrap();
    assert_eq!(offsets.len(), 1, "no new offset entry should be appended");
}

// ---------------------------------------------------------------------------
// Test 03 — restore_latest returns most recent.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_03_restore_latest_returns_most_recent() {
    let backing = InMemoryStateBacking::new();
    let s1 = fixture_distinct_snapshot(1);
    let s2 = fixture_distinct_snapshot(2);
    backing.snapshot("persona-A", s1).await.unwrap();
    backing.snapshot("persona-A", s2.clone()).await.unwrap();

    let restored = backing.restore_latest("persona-A").await.unwrap();
    assert_eq!(restored, Some(s2), "restore_latest must return the most recent");
}

// ---------------------------------------------------------------------------
// Test 04 — cold-start returns None.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_04_restore_latest_returns_none_on_cold_start() {
    let backing = InMemoryStateBacking::new();
    let restored = backing.restore_latest("persona-never-seen").await.unwrap();
    assert_eq!(restored, None, "cold-start must return None");
}

// ---------------------------------------------------------------------------
// Test 05 — list_snapshots returns oldest first.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_05_list_snapshots_returns_oldest_first() {
    let backing = InMemoryStateBacking::new();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(1))
        .await
        .unwrap();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(2))
        .await
        .unwrap();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(3))
        .await
        .unwrap();
    let offsets = backing.list_snapshots("persona-A").await.unwrap();
    assert_eq!(offsets, vec![1, 2, 3], "oldest offset must come first");
}

// ---------------------------------------------------------------------------
// Test 06 — atomic_swap_pinned_offset happy path.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_06_atomic_swap_pinned_offset_happy_path() {
    let backing = InMemoryStateBacking::new();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(1))
        .await
        .unwrap();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(2))
        .await
        .unwrap();

    // First pin: from_offset is ignored when current is None.
    backing
        .atomic_swap_pinned_offset("persona-A", 0, 1)
        .await
        .unwrap();
    assert_eq!(backing.get_pinned("persona-A").await, Some(1));

    // Swap pin from 1 to 2.
    backing
        .atomic_swap_pinned_offset("persona-A", 1, 2)
        .await
        .unwrap();
    assert_eq!(backing.get_pinned("persona-A").await, Some(2));
}

// ---------------------------------------------------------------------------
// Test 07 — CAS failure: from_offset mismatch.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_07_atomic_swap_pinned_offset_cas_failure() {
    let backing = InMemoryStateBacking::new();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(1))
        .await
        .unwrap();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(2))
        .await
        .unwrap();

    // Pin to 1, then attempt CAS with wrong from_offset.
    backing
        .atomic_swap_pinned_offset("persona-A", 0, 1)
        .await
        .unwrap();
    let err = backing
        .atomic_swap_pinned_offset("persona-A", 99, 2)
        .await
        .unwrap_err();
    match err {
        StateBackingError::CasFailed(msg) => {
            assert!(msg.contains("expected from_offset=99"), "CAS-failure message must cite from_offset: {msg}");
            assert!(msg.contains("current pinned offset=1"), "CAS-failure message must cite current pin: {msg}");
        }
        other => panic!("expected CasFailed, got {other:?}"),
    }
    // Pin must remain at 1.
    assert_eq!(backing.get_pinned("persona-A").await, Some(1));
}

// ---------------------------------------------------------------------------
// Test 08 — atomic-swap to unknown offset is rejected.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_08_atomic_swap_pinned_offset_unknown_offset() {
    let backing = InMemoryStateBacking::new();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(1))
        .await
        .unwrap();
    let err = backing
        .atomic_swap_pinned_offset("persona-A", 0, 999)
        .await
        .unwrap_err();
    match err {
        StateBackingError::UnknownOffset(msg) => {
            assert!(msg.contains("to_offset=999"), "UnknownOffset must cite the missing offset: {msg}");
        }
        other => panic!("expected UnknownOffset, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Test 09 — per-persona isolation.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_09_per_persona_isolation() {
    let backing = InMemoryStateBacking::new();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(1))
        .await
        .unwrap();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(2))
        .await
        .unwrap();
    let off_b1 = backing
        .snapshot("persona-B", fixture_distinct_snapshot(10))
        .await
        .unwrap();
    let off_b2 = backing
        .snapshot("persona-B", fixture_distinct_snapshot(11))
        .await
        .unwrap();

    // persona-B's offsets are independent (start at 1, not at 3).
    assert_eq!(off_b1, 1);
    assert_eq!(off_b2, 2);
    assert_eq!(backing.list_snapshots("persona-A").await.unwrap(), vec![1, 2]);
    assert_eq!(backing.list_snapshots("persona-B").await.unwrap(), vec![1, 2]);
}

// ---------------------------------------------------------------------------
// Test 10 — JCS-canonical bytes are deterministic.
// ---------------------------------------------------------------------------

#[test]
fn test_10_jcs_canonical_bytes_are_byte_stable() {
    let snap = fixture_snapshot(42, &["alpha", "beta"]);
    let bytes_a = snapshot_to_jcs_bytes(&snap);
    let bytes_b = snapshot_to_jcs_bytes(&snap);
    assert_eq!(bytes_a, bytes_b, "JCS bytes must be deterministic");

    // Field ordering check: must be alphabetical.
    let as_str = std::str::from_utf8(&bytes_a).unwrap();
    let audit_pos = as_str.find("audit_trace_offset").unwrap();
    let cap_pos = as_str.find("capability_token_ids").unwrap();
    let persona_pos = as_str.find("persona_hash").unwrap();
    let snap_pos = as_str.find("snapshot_at_utc").unwrap();
    let work_pos = as_str.find("workspace_state_hash").unwrap();
    assert!(audit_pos < cap_pos, "audit < capability");
    assert!(cap_pos < persona_pos, "capability < persona");
    assert!(persona_pos < snap_pos, "persona < snapshot");
    assert!(snap_pos < work_pos, "snapshot < workspace");

    // No whitespace (Python separators=(",", ":")).
    assert!(
        !as_str.contains(": "),
        "JCS must not emit space after colons"
    );
    assert!(
        !as_str.contains(", "),
        "JCS must not emit space after commas"
    );
}

// ---------------------------------------------------------------------------
// Test 11 — snapshot_payload_sha256 byte-stable.
// ---------------------------------------------------------------------------

#[test]
fn test_11_snapshot_payload_sha256_byte_stable() {
    let snap = fixture_snapshot(7, &["tok-x"]);
    let h1 = snapshot_payload_sha256(&snap);
    let h2 = snapshot_payload_sha256(&snap);
    assert_eq!(h1, h2, "sha256 must be deterministic for byte-equal input");
    assert!(h1.starts_with("sha256:"), "must use sha256:<hex> prefix");
    assert_eq!(h1.len(), "sha256:".len() + 64, "hex tail must be 64 chars");
    // Hex tail must be lower-case (parity with Python hexdigest()).
    let tail = &h1["sha256:".len()..];
    assert!(
        tail.chars().all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c)),
        "hex tail must be lower-case ASCII hex: {tail}"
    );
}

// ---------------------------------------------------------------------------
// Test 12 — snapshot_from_jcs_bytes round-trip.
// ---------------------------------------------------------------------------

#[test]
fn test_12_snapshot_from_jcs_bytes_round_trip() {
    let snap = fixture_snapshot(99, &["a", "b", "c"]);
    let bytes = snapshot_to_jcs_bytes(&snap);
    let parsed = snapshot_from_jcs_bytes(&bytes).unwrap();
    assert_eq!(parsed, snap, "round-trip must preserve all five fields");
}

// ---------------------------------------------------------------------------
// Test 13 — offset_key round-trip (smoke-test-level).
// ---------------------------------------------------------------------------

#[test]
fn test_13_offset_key_round_trip_smoke() {
    for off in [0u64, 1, 42, 1_000_000, u64::MAX] {
        let key = offset_key(off);
        assert_eq!(offset_from_key(&key).unwrap(), off);
    }
    // Sentinel keys must use the documented constants.
    assert_eq!(PINNED_KEY, "state-pack/__pinned__");
    assert_eq!(NEXT_OFFSET_KEY, "state-pack/__next_offset__");
    assert_eq!(LATEST_KEY, "state-pack/latest");
    assert_eq!(STATE_PACK_KEY_PREFIX, "state-pack");
    assert_eq!(OFFSET_KEY_WIDTH, 20);
}

// ---------------------------------------------------------------------------
// Test 14 — watch_revisions emits Snapshot event.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_14_watch_revisions_emits_snapshot_event() {
    let backing = InMemoryStateBacking::new();
    let mut rx = backing.watch_revisions("persona-A", 8).await.unwrap();
    let snap = fixture_distinct_snapshot(1);
    let off = backing
        .snapshot("persona-A", snap.clone())
        .await
        .unwrap();
    let event = tokio::time::timeout(std::time::Duration::from_secs(2), rx.recv())
        .await
        .expect("watch_revisions should emit within 2s")
        .expect("channel should not close");
    match event {
        RevisionEvent::Snapshot {
            offset,
            snapshot: emitted,
        } => {
            assert_eq!(offset, off);
            assert_eq!(emitted, snap);
        }
        other => panic!("expected Snapshot event, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Test 15 — watch_revisions emits Pinned event.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_15_watch_revisions_emits_pinned_event() {
    let backing = InMemoryStateBacking::new();
    backing
        .snapshot("persona-A", fixture_distinct_snapshot(1))
        .await
        .unwrap();
    let mut rx = backing.watch_revisions("persona-A", 8).await.unwrap();
    backing
        .atomic_swap_pinned_offset("persona-A", 0, 1)
        .await
        .unwrap();
    let event = tokio::time::timeout(std::time::Duration::from_secs(2), rx.recv())
        .await
        .expect("watch_revisions should emit within 2s")
        .expect("channel should not close");
    match event {
        RevisionEvent::Pinned { offset } => assert_eq!(offset, 1),
        other => panic!("expected Pinned event, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Test 16 — NatsKvStateBacking stub returns NatsKv error (Phase-3a pending).
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_16_natskv_stub_returns_nats_kv_error() {
    let backing = NatsKvStateBacking::new("nats://localhost:4222", "org-A");
    let snap = fixture_distinct_snapshot(1);
    let err = backing.snapshot("persona-A", snap).await.unwrap_err();
    match err {
        StateBackingError::NatsKv(msg) => {
            assert!(
                msg.contains("not bound yet"),
                "stub error should document Phase-3a pending: {msg}"
            );
        }
        other => panic!("expected NatsKv error, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Test 17 — NatsKvStateBacking bucket name shape.
// ---------------------------------------------------------------------------

#[test]
fn test_17_natskv_bucket_name_shape() {
    let backing = NatsKvStateBacking::new("nats://localhost:4222", "org-A");
    let bucket = backing.bucket_name("persona-XYZ");
    assert_eq!(
        bucket, "wakir-persona-state-org-A-persona-XYZ",
        "bucket name must match the documented Python shape \
         wakir-persona-state-<org_id>-<persona_id>"
    );
}

// ---------------------------------------------------------------------------
// Test 18 — snapshot_from_jcs_bytes rejects missing keys.
// ---------------------------------------------------------------------------

#[test]
fn test_18_snapshot_from_jcs_bytes_missing_key_rejected() {
    // Missing `workspace_state_hash`.
    let blob = br#"{"audit_trace_offset":1,"capability_token_ids":[],"persona_hash":"sha256:0","snapshot_at_utc":"2026-05-17T00:00:00Z"}"#;
    let err = snapshot_from_jcs_bytes(blob).unwrap_err();
    match err {
        StateBackingError::CorruptSnapshot(msg) => {
            assert!(
                msg.contains("workspace_state_hash"),
                "missing-key error must cite the field: {msg}"
            );
        }
        other => panic!("expected CorruptSnapshot, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Test 19 — snapshot_from_jcs_bytes rejects corrupt JSON.
// ---------------------------------------------------------------------------

#[test]
fn test_19_snapshot_from_jcs_bytes_corrupt_json_rejected() {
    let blob = b"not valid json";
    let err = snapshot_from_jcs_bytes(blob).unwrap_err();
    match err {
        StateBackingError::CorruptSnapshot(_) => {}
        other => panic!("expected CorruptSnapshot, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Test 20 — offset_key zero-padding sorts numerically.
// ---------------------------------------------------------------------------

#[test]
fn test_20_keys_ordering_matches_offset_ordering() {
    // The 20-digit zero-pad means lexicographic sort == numeric sort.
    let mut keys = vec![
        offset_key(1),
        offset_key(2),
        offset_key(10),
        offset_key(100),
        offset_key(1000),
    ];
    let original = keys.clone();
    keys.sort();
    assert_eq!(keys, original, "zero-padded keys must sort lexicographically == numerically");
}
