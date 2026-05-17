// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Smoke and invariant tests for persona-engine-fsm.
//
// Test taxonomy
// -------------
// - WIRE-STRING PINS (T01..T03): pin every wire string on the Rust
//   side. The Python authority is `STATES` / `VALID_TRANSITIONS` in
//   `wirelang/persona_engine/lifecycle_state_machine.py` (PR #65).
//   Any rename on either side must fail at least one of these tests
//   (Rust-side directly; Python-side via the schema-parity test in
//   the cross-lang CI harness, which compares the JSON output of
//   `python -m wirelang.persona_engine.lifecycle_state_machine
//   --dump-spec` against the Rust pins below).
// - HAPPY-PATH STATE PATHS (T04..T06): walk each documented
//   transition chain end-to-end (spawn-run-despawn, recover, migrate).
// - INVALID TRANSITION (T07..T09): rejections leave an audit trace
//   and do not mutate the state.
// - REPLAY (T10..T11): rebuild a machine from a recorded log,
//   including rejection records.
// - JSON ROUND-TRIP (T12): serde round-trip preserves field set and
//   skips `null` reasons, matching the Python wire shape.

use persona_engine_fsm::{
    assert_spec_invariants, is_valid_transition, FsmError, FsmState, FsmTransition, PersonaFsm,
    TransitionRecord, STATES, VALID_TRANSITIONS,
};

/// Deterministic clock: returns a fixed sentinel timestamp. Allows
/// byte-for-byte JSON cross-checks without wall-clock noise.
fn fixed_clock() -> String {
    "2026-05-17T00:00:00Z".to_string()
}

fn fixed_clock_fn() -> persona_engine_fsm::ClockFn {
    fixed_clock as persona_engine_fsm::ClockFn
}

// ---------------------------------------------------------------------
// T01 — Wire-string pins for every state.
//
// Cross-lang authority: Python tuple
//   STATES = ("uninstantiated", "spawning", "running",
//             "despawning", "recovered", "migrated")
// Any rename of an FsmState variant or its as_wire_str arm fails here.
// ---------------------------------------------------------------------
#[test]
fn t01_state_wire_string_pins() {
    let pinned: Vec<&'static str> = STATES.iter().map(|s| s.as_wire_str()).collect();
    assert_eq!(
        pinned,
        vec![
            "uninstantiated",
            "spawning",
            "running",
            "despawning",
            "recovered",
            "migrated",
        ],
        "state wire-string drift vs Python STATES tuple (PR #65)"
    );
}

// ---------------------------------------------------------------------
// T02 — Wire-string pins for every valid transition.
//
// Cross-lang authority: Python tuple VALID_TRANSITIONS. Order matches
// the spec §3.3 valid_transitions array.
// ---------------------------------------------------------------------
#[test]
fn t02_transition_wire_string_pins() {
    let pinned: Vec<(&'static str, &'static str)> = VALID_TRANSITIONS
        .iter()
        .map(|t| (t.from.as_wire_str(), t.to.as_wire_str()))
        .collect();
    assert_eq!(
        pinned,
        vec![
            ("uninstantiated", "spawning"),
            ("spawning", "running"),
            ("spawning", "uninstantiated"),
            ("running", "despawning"),
            ("despawning", "uninstantiated"),
            ("uninstantiated", "recovered"),
            ("recovered", "running"),
            ("running", "migrated"),
            ("migrated", "uninstantiated"),
        ],
        "transition wire-string drift vs Python VALID_TRANSITIONS (PR #65)"
    );
    // Drift sentinel: exactly nine transitions per spec §3.3.
    assert_eq!(VALID_TRANSITIONS.len(), 9);
}

// ---------------------------------------------------------------------
// T03 — Round-trip every state through `from_wire_str` /
// `as_wire_str`.
// ---------------------------------------------------------------------
#[test]
fn t03_state_wire_string_roundtrip() {
    for s in STATES {
        let wire = s.as_wire_str();
        let parsed = FsmState::from_wire_str(wire).expect("known wire string must parse");
        assert_eq!(parsed, *s, "round-trip drift for state {}", wire);
    }
    // Unknown wire strings are rejected with FsmError::UnknownState.
    match FsmState::from_wire_str("zombie") {
        Err(FsmError::UnknownState(s)) => assert_eq!(s, "zombie"),
        other => panic!("expected UnknownState, got {:?}", other),
    }
}

// ---------------------------------------------------------------------
// T04 — Happy-path state walk: uninstantiated -> spawning -> running
// -> despawning -> uninstantiated. Covers the four core transitions.
// ---------------------------------------------------------------------
#[test]
fn t04_happy_path_spawn_run_despawn() {
    let mut m = PersonaFsm::new("mira", "wakir-labs").with_clock(fixed_clock_fn());
    assert_eq!(m.state(), FsmState::Uninstantiated);
    m.transition(FsmState::Spawning).expect("uninstantiated -> spawning");
    m.transition(FsmState::Running).expect("spawning -> running");
    m.transition(FsmState::Despawning).expect("running -> despawning");
    m.transition(FsmState::Uninstantiated)
        .expect("despawning -> uninstantiated");
    assert_eq!(m.state(), FsmState::Uninstantiated);
    assert_eq!(m.history_ref().len(), 4);
    assert!(m.history_ref().iter().all(|r| r.accepted));
    assert!(m.history_ref().iter().all(|r| r.reason.is_none()));
    // Pinned timestamps stay deterministic.
    assert!(m.history_ref().iter().all(|r| r.ts_utc == fixed_clock()));
}

// ---------------------------------------------------------------------
// T05 — Recovery path: uninstantiated -> recovered -> running.
// Covers the §3.7.4 R2 "Reload" surface.
// ---------------------------------------------------------------------
#[test]
fn t05_recovery_path() {
    let mut m = PersonaFsm::new("priya", "wakir-labs").with_clock(fixed_clock_fn());
    m.transition(FsmState::Recovered).expect("uninstantiated -> recovered");
    m.transition(FsmState::Running).expect("recovered -> running");
    assert_eq!(m.state(), FsmState::Running);
    assert_eq!(m.history_ref().len(), 2);
}

// ---------------------------------------------------------------------
// T06 — Migration path: spawn -> run -> migrate -> uninstantiated.
// ---------------------------------------------------------------------
#[test]
fn t06_migration_path() {
    let mut m = PersonaFsm::new("aisha", "wakir-labs").with_clock(fixed_clock_fn());
    m.transition(FsmState::Spawning).unwrap();
    m.transition(FsmState::Running).unwrap();
    m.transition(FsmState::Migrated).expect("running -> migrated");
    m.transition(FsmState::Uninstantiated)
        .expect("migrated -> uninstantiated");
    assert_eq!(m.state(), FsmState::Uninstantiated);
}

// ---------------------------------------------------------------------
// T07 — Spawn cancel path: uninstantiated -> spawning ->
// uninstantiated. Covers the "spawn aborted before run" surface.
// ---------------------------------------------------------------------
#[test]
fn t07_spawn_cancel_path() {
    let mut m = PersonaFsm::new("noa", "wakir-labs").with_clock(fixed_clock_fn());
    m.transition(FsmState::Spawning).unwrap();
    m.transition(FsmState::Uninstantiated)
        .expect("spawning -> uninstantiated");
    assert_eq!(m.state(), FsmState::Uninstantiated);
    // can_transition_to negative case from terminal-ish state.
    assert!(!m.can_transition_to(FsmState::Despawning));
}

// ---------------------------------------------------------------------
// T08 — Invalid transition from uninstantiated to running (no direct
// edge per spec §3.3). Must return InvalidTransition and leave the
// state unchanged but with an audit record.
// ---------------------------------------------------------------------
#[test]
fn t08_invalid_transition_records_attempt() {
    let mut m = PersonaFsm::new("tomas", "wakir-labs").with_clock(fixed_clock_fn());
    let err = m
        .transition(FsmState::Running)
        .expect_err("uninstantiated -> running is not in spec §3.3");
    match err {
        FsmError::InvalidTransition { from, to } => {
            assert_eq!(from, FsmState::Uninstantiated);
            assert_eq!(to, FsmState::Running);
        }
        other => panic!("expected InvalidTransition, got {:?}", other),
    }
    // State stays put.
    assert_eq!(m.state(), FsmState::Uninstantiated);
    // Audit log records the rejection with the canonical reason
    // string (cross-lang pin: same wire string as Python).
    assert_eq!(m.history_ref().len(), 1);
    let rec = &m.history_ref()[0];
    assert!(!rec.accepted);
    assert_eq!(rec.reason.as_deref(), Some("not_in_valid_transitions"));
    assert_eq!(rec.from_state, FsmState::Uninstantiated);
    assert_eq!(rec.to_state, FsmState::Running);
}

// ---------------------------------------------------------------------
// T09 — Cross-product: every non-VALID edge is rejected; every VALID
// edge is accepted from the matching source state. Exhaustive
// 6x6 = 36 cell sweep, the 9 valid cells must succeed and the other
// 27 must fail (also implicitly pins set membership).
// ---------------------------------------------------------------------
#[test]
fn t09_invalid_transition_matrix() {
    for from in STATES {
        for to in STATES {
            let expected = VALID_TRANSITIONS
                .iter()
                .any(|t| t.from == *from && t.to == *to);
            assert_eq!(
                is_valid_transition(*from, *to),
                expected,
                "matrix drift for ({}, {})",
                from,
                to
            );
            // Drive a fresh FSM seeded at `from` and verify behaviour.
            let mut m = PersonaFsm::with_initial_state("x", "wakir-labs", *from)
                .with_clock(fixed_clock_fn());
            let r = m.transition(*to);
            match (expected, r) {
                (true, Ok(_)) => {
                    assert_eq!(m.state(), *to, "valid edge must update state");
                }
                (false, Err(FsmError::InvalidTransition { from: f2, to: t2 })) => {
                    assert_eq!(f2, *from);
                    assert_eq!(t2, *to);
                    assert_eq!(m.state(), *from, "invalid edge must preserve state");
                }
                (exp, got) => panic!(
                    "matrix drift for ({}, {}): expected={} got={:?}",
                    from, to, exp, got
                ),
            }
        }
    }
    // Total valid count must equal the table length.
    let valid_count: usize = STATES
        .iter()
        .flat_map(|f| STATES.iter().map(move |t| (f, t)))
        .filter(|(f, t)| is_valid_transition(**f, **t))
        .count();
    assert_eq!(valid_count, VALID_TRANSITIONS.len());
}

// ---------------------------------------------------------------------
// T10 — Replay reproduces state from an accepted-only history.
// ---------------------------------------------------------------------
#[test]
fn t10_replay_reproduces_state() {
    let mut original = PersonaFsm::new("kai", "wakir-labs").with_clock(fixed_clock_fn());
    original.transition(FsmState::Spawning).unwrap();
    original.transition(FsmState::Running).unwrap();
    original.transition(FsmState::Migrated).unwrap();
    let history = original.history();

    let rebuilt = PersonaFsm::replay("kai", "wakir-labs", history.clone())
        .expect("clean history must replay");
    assert_eq!(rebuilt.state(), original.state());
    assert_eq!(rebuilt.history(), history);
}

// ---------------------------------------------------------------------
// T11 — Replay preserves rejection records as audit annotations
// without advancing state (mirrors Python `replay` semantics).
// ---------------------------------------------------------------------
#[test]
fn t11_replay_preserves_rejections() {
    // Mixed history with one rejection in the middle.
    let records = vec![
        TransitionRecord {
            from_state: FsmState::Uninstantiated,
            to_state: FsmState::Spawning,
            ts_utc: fixed_clock(),
            accepted: true,
            reason: None,
        },
        TransitionRecord {
            from_state: FsmState::Spawning,
            to_state: FsmState::Migrated, // not a valid edge -> rejected
            ts_utc: fixed_clock(),
            accepted: false,
            reason: Some("not_in_valid_transitions".to_string()),
        },
        TransitionRecord {
            from_state: FsmState::Spawning,
            to_state: FsmState::Running,
            ts_utc: fixed_clock(),
            accepted: true,
            reason: None,
        },
    ];
    let rebuilt = PersonaFsm::replay("henrik", "wakir-labs", records.clone())
        .expect("mixed history must replay cleanly");
    assert_eq!(rebuilt.state(), FsmState::Running);
    assert_eq!(rebuilt.history(), records);

    // Replay drift: an accepted record whose from-state mismatches
    // the running replay state must surface a ReplayDrift error.
    let corrupted = vec![TransitionRecord {
        from_state: FsmState::Running, // wrong — fresh FSM is uninstantiated
        to_state: FsmState::Despawning,
        ts_utc: fixed_clock(),
        accepted: true,
        reason: None,
    }];
    match PersonaFsm::replay("henrik", "wakir-labs", corrupted) {
        Err(FsmError::ReplayDrift {
            expected_from,
            recorded_from,
            recorded_to,
        }) => {
            assert_eq!(expected_from, FsmState::Uninstantiated);
            assert_eq!(recorded_from, FsmState::Running);
            assert_eq!(recorded_to, FsmState::Despawning);
        }
        other => panic!("expected ReplayDrift, got {:?}", other),
    }
}

// ---------------------------------------------------------------------
// T12 — Cross-lang JSON shape pin for TransitionRecord. Pins the
// field names (`from_state`, `to_state`, `ts_utc`, `accepted`,
// `reason`) and the lowercase wire-string encoding for FsmState. A
// `null` reason is omitted from the serialised form (matches the
// Python `Optional[str] = None` default-omit semantics on the wire).
// ---------------------------------------------------------------------
#[test]
fn t12_transition_record_json_pin() {
    let rec = TransitionRecord {
        from_state: FsmState::Spawning,
        to_state: FsmState::Running,
        ts_utc: "2026-05-17T00:00:00Z".to_string(),
        accepted: true,
        reason: None,
    };
    let json = serde_json::to_string(&rec).expect("serde must encode TransitionRecord");
    assert_eq!(
        json,
        r#"{"from_state":"spawning","to_state":"running","ts_utc":"2026-05-17T00:00:00Z","accepted":true}"#
    );

    let rejected = TransitionRecord {
        from_state: FsmState::Uninstantiated,
        to_state: FsmState::Running,
        ts_utc: "2026-05-17T00:00:00Z".to_string(),
        accepted: false,
        reason: Some("not_in_valid_transitions".to_string()),
    };
    let rejected_json = serde_json::to_string(&rejected).expect("serde must encode rejected rec");
    assert_eq!(
        rejected_json,
        r#"{"from_state":"uninstantiated","to_state":"running","ts_utc":"2026-05-17T00:00:00Z","accepted":false,"reason":"not_in_valid_transitions"}"#
    );

    // Round-trip parity.
    let parsed: TransitionRecord = serde_json::from_str(&rejected_json).unwrap();
    assert_eq!(parsed, rejected);
}

// ---------------------------------------------------------------------
// T13 — apply_transition rejects an FsmTransition whose from does
// not match the current state, even if the destination would be
// valid from the actual state.
// ---------------------------------------------------------------------
#[test]
fn t13_apply_transition_guards_from_state() {
    let mut m = PersonaFsm::new("amara", "wakir-labs").with_clock(fixed_clock_fn());
    // Machine is in Uninstantiated, but we hand it a Running->Despawning record.
    let wrong = FsmTransition::new(FsmState::Running, FsmState::Despawning);
    let err = m
        .apply_transition(wrong)
        .expect_err("apply_transition must reject from-state mismatch");
    match err {
        FsmError::InvalidTransition { from, to } => {
            assert_eq!(from, FsmState::Uninstantiated);
            assert_eq!(to, FsmState::Despawning);
        }
        other => panic!("expected InvalidTransition, got {:?}", other),
    }
    assert_eq!(m.state(), FsmState::Uninstantiated);
}

// ---------------------------------------------------------------------
// T14 — Spec-invariant guard (mirrors the Python import-time
// `_assert_spec_invariants` call): no duplicate edges, no
// out-of-bounds states.
// ---------------------------------------------------------------------
#[test]
fn t14_spec_invariants_hold() {
    assert_spec_invariants().expect("spec invariants must hold");
}
