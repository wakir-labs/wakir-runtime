// SPDX-License-Identifier: Apache-2.0
//
// Cross-Lang-Pin-Tests für persona-engine-nats-subjects.
//
// Diese Tests sichern die Rust-canonical Pin-Pack-Strings als
// byte-stabile Fixtures. Python-Pendant
// `wirelang/persona_engine/nats_subjects.py` ist Sync-Folge-Item
// (Tag-N+1) und MUSS die hier hardcoded Strings byte-identisch
// reproduzieren.

use persona_engine_nats_subjects as subjects;
use subjects::pins;

#[test]
fn cross_lang_pin_strings_are_byte_stable() {
    // Hardcoded reference snapshot (Rust-canonical).
    // Wenn dieser Test rot wird, hat jemand die Pin-Strings geändert
    // → Python-Side, Operator-Docs, Stream-Configs alle betroffen.
    let expected: &[&str] = &[
        "persona.lifecycle.reza-2026-05-17.spawned",
        "persona.lifecycle.reza-2026-05-17.despawned",
        "persona.federation.cluster-eu-1.reza-2026-05-17.frame",
        "persona.audit.identity-rotate.run-0001",
        "persona.audit.policy-violation.run-0002",
        "persona.anchor.batch-2026-05-17.submitted",
        "persona.recovery.replay.run-0003",
        "persona.recovery.verify.run-0003",
    ];

    assert_eq!(
        pins::ALL_FIXTURES.len(),
        expected.len(),
        "Pin-Pack length drift"
    );

    for (i, (got, want)) in pins::ALL_FIXTURES.iter().zip(expected.iter()).enumerate() {
        assert_eq!(
            got, want,
            "Pin-Fixture index {} drifted: got={:?} want={:?}",
            i, got, want
        );
    }
}

#[test]
fn cross_lang_pin_joined_string_is_stable() {
    // Stable join under `\n` — this is what Python MUST reproduce
    // byte-for-byte when emitting its own pin pack.
    let joined = pins::ALL_FIXTURES.join("\n");
    let expected = "persona.lifecycle.reza-2026-05-17.spawned\n\
                    persona.lifecycle.reza-2026-05-17.despawned\n\
                    persona.federation.cluster-eu-1.reza-2026-05-17.frame\n\
                    persona.audit.identity-rotate.run-0001\n\
                    persona.audit.policy-violation.run-0002\n\
                    persona.anchor.batch-2026-05-17.submitted\n\
                    persona.recovery.replay.run-0003\n\
                    persona.recovery.verify.run-0003";
    assert_eq!(joined, expected);

    // Sanity: total byte-length is also a stable property.
    assert_eq!(joined.len(), expected.len());
}

#[test]
fn cross_lang_pin_each_round_trips_through_builders() {
    // Jede Pin-Fixture wird sowohl als String-Konstante als auch via
    // typed Builder erzeugt; beide Pfade müssen byte-identisch sein.
    // Dieser Test ist die Garantie, dass die Pin-Strings nicht von
    // Hand "korrigiert" werden können, ohne dass die Builder-Logik
    // mitwandert.
    let pairs: &[(&str, String)] = &[
        (
            pins::FIXTURE_LIFECYCLE_SPAWNED,
            subjects::lifecycle_subject("reza-2026-05-17", "spawned").unwrap(),
        ),
        (
            pins::FIXTURE_LIFECYCLE_DESPAWNED,
            subjects::lifecycle_subject("reza-2026-05-17", "despawned").unwrap(),
        ),
        (
            pins::FIXTURE_FEDERATION_FRAME,
            subjects::federation_subject("cluster-eu-1", "reza-2026-05-17").unwrap(),
        ),
        (
            pins::FIXTURE_AUDIT_IDENTITY_ROTATE,
            subjects::audit_subject("identity-rotate", "run-0001").unwrap(),
        ),
        (
            pins::FIXTURE_AUDIT_POLICY_VIOLATION,
            subjects::audit_subject("policy-violation", "run-0002").unwrap(),
        ),
        (
            pins::FIXTURE_ANCHOR_SUBMITTED,
            subjects::anchor_subject("batch-2026-05-17").unwrap(),
        ),
        (
            pins::FIXTURE_RECOVERY_REPLAY,
            subjects::recovery_subject("replay", "run-0003").unwrap(),
        ),
        (
            pins::FIXTURE_RECOVERY_VERIFY,
            subjects::recovery_subject("verify", "run-0003").unwrap(),
        ),
    ];

    for (pin, built) in pairs {
        assert_eq!(
            *pin, built,
            "Pin-vs-Builder drift on fixture: pin={:?} built={:?}",
            pin, built
        );
    }
}
