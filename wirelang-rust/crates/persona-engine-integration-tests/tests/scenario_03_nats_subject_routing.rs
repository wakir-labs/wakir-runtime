// SPDX-License-Identifier: Apache-2.0
//! Scenario 3 — NATS Subject Routing.
//!
//! The `persona-engine-nats-subjects` crate builds canonical subject
//! strings (`persona.lifecycle.<id>.<event>`, etc.) and wildcard forms
//! (`persona.lifecycle.<id>.*`, `persona.lifecycle.>`). The
//! `persona-engine-subscribe-loop` crate carries the agent-task-
//! assigned subject template (`wakir.{env}.agent.agent.task.assigned.
//! {persona_slug}`). The two crates intentionally cover DIFFERENT
//! subject families (NATS-level persona-engine traffic vs. the
//! agent-task-assigned bridge subject); this scenario verifies they
//! remain non-overlapping and that the wildcard forms from
//! `nats-subjects` correctly cover the concrete subjects built by
//! the same crate.
//!
//! Three tests cover:
//!
//!   1. Concrete subjects built via the documented builder API
//!      (lifecycle / federation / audit / anchor / recovery) all
//!      share the `persona.<family>.` prefix and the wildcard for
//!      that family is a prefix of the concrete subject.
//!   2. The subscribe-loop subject-template lives in a different
//!      family (`wakir.<env>.agent.agent.task.assigned.<slug>`) and
//!      does NOT collide with the `persona.>` namespace.
//!   3. Token validation rejects reserved-word inputs (`>`, `*`, "")
//!      across every subject builder.

use persona_engine_nats_subjects::{
    anchor_subject, anchor_wildcard_all, audit_subject, audit_wildcard_all,
    audit_wildcard_by_kind, federation_subject, federation_wildcard_all,
    federation_wildcard_by_cluster, lifecycle_subject, lifecycle_wildcard_all,
    lifecycle_wildcard_all_events, recovery_subject, recovery_wildcard_all,
    recovery_wildcard_by_step,
};
use persona_engine_subscribe_loop::SUBSCRIBE_SUBJECT_TEMPLATE;

#[test]
fn t01_concrete_subjects_are_covered_by_their_family_wildcards() {
    // --- Lifecycle family ---
    let lc = lifecycle_subject("reza", "spawned").expect("lifecycle subject");
    assert_eq!(lc, "persona.lifecycle.reza.spawned");
    let lc_id_wild = lifecycle_wildcard_all_events("reza").expect("lc wild id");
    assert_eq!(lc_id_wild, "persona.lifecycle.reza.*");
    let lc_all = lifecycle_wildcard_all().expect("lc wild all");
    assert!(
        lc.starts_with("persona.lifecycle.") && lc_all.starts_with("persona.lifecycle.")
    );

    // --- Federation family ---
    let fed = federation_subject("eu-west", "frame-001").expect("fed subject");
    assert_eq!(fed, "persona.federation.eu-west.frame-001.frame");
    let fed_cluster_wild = federation_wildcard_by_cluster("eu-west").expect("fed wild cluster");
    assert_eq!(fed_cluster_wild, "persona.federation.eu-west.>");
    let fed_all = federation_wildcard_all().expect("fed wild all");
    assert!(fed_all.starts_with("persona.federation."));
    // Cluster wildcard is a prefix of the concrete subject (modulo the
    // trailing `>` wildcard token).
    let fed_cluster_prefix = fed_cluster_wild.trim_end_matches('>');
    assert!(
        fed.starts_with(fed_cluster_prefix),
        "concrete fed subject {fed} must share prefix {fed_cluster_prefix}",
    );

    // --- Audit family ---
    let aud = audit_subject("policy", "policy-001").expect("audit subject");
    assert!(aud.starts_with("persona.audit.policy."));
    let aud_kind_wild = audit_wildcard_by_kind("policy").expect("audit kind wild");
    let aud_all = audit_wildcard_all().expect("audit all wild");
    assert!(aud_kind_wild.starts_with("persona.audit.policy"));
    assert!(aud_all.starts_with("persona.audit."));

    // --- Anchor family ---
    let anc = anchor_subject("batch-42").expect("anchor subject");
    assert!(anc.starts_with("persona.anchor."));
    let anc_all = anchor_wildcard_all().expect("anchor all wild");
    assert!(anc_all.starts_with("persona.anchor."));

    // --- Recovery family ---
    let rec = recovery_subject("R2", "session-001").expect("recovery subject");
    assert!(rec.starts_with("persona.recovery.R2."));
    let rec_step_wild = recovery_wildcard_by_step("R2").expect("rec step wild");
    let rec_all = recovery_wildcard_all().expect("rec all wild");
    assert!(rec_step_wild.starts_with("persona.recovery.R2"));
    assert!(rec_all.starts_with("persona.recovery."));
}

#[test]
fn t02_subscribe_loop_template_is_disjoint_from_persona_namespace() {
    // The agent-task-assigned subject lives under `wakir.<env>.agent.
    // agent.task.assigned.<slug>` — a deliberately different top
    // segment from the `persona.*` namespace owned by the
    // persona-engine-nats-subjects crate. The two must NOT overlap,
    // otherwise a wildcard subscriber on `persona.>` would shadow
    // bridge-forward traffic.
    assert!(
        SUBSCRIBE_SUBJECT_TEMPLATE.starts_with("wakir."),
        "subscribe-loop template top segment must be `wakir.`, got {SUBSCRIBE_SUBJECT_TEMPLATE}",
    );
    assert!(
        !SUBSCRIBE_SUBJECT_TEMPLATE.starts_with("persona."),
        "subscribe-loop template MUST NOT live under the persona.* namespace",
    );
    // Sanity-substitute the template and re-check.
    let concrete = SUBSCRIBE_SUBJECT_TEMPLATE
        .replace("{env}", "dev")
        .replace("{persona_slug}", "reza");
    assert_eq!(concrete, "wakir.dev.agent.agent.task.assigned.reza");
    let persona_wild = lifecycle_wildcard_all().expect("lc wild all");
    let persona_root = persona_wild.trim_end_matches('>');
    assert!(
        !concrete.starts_with(persona_root.trim_end_matches('.')),
        "concrete subscribe-loop subject must not fall under persona.lifecycle.>",
    );
}

#[test]
fn t03_subject_builders_reject_reserved_tokens() {
    // Reserved tokens in NATS subject grammar: ">", "*", "". The
    // builder API must reject all three (token validation lives in
    // `validate_token`; the per-builder reject path is covered here).
    for bad in &["", ">", "*"] {
        assert!(
            lifecycle_subject(bad, "spawned").is_err(),
            "lifecycle_subject must reject id={bad:?}",
        );
        assert!(
            federation_subject(bad, "frame-001").is_err(),
            "federation_subject must reject cluster={bad:?}",
        );
        assert!(
            audit_subject("policy", bad).is_err(),
            "audit_subject must reject id={bad:?}",
        );
        assert!(
            anchor_subject(bad).is_err(),
            "anchor_subject must reject batch={bad:?}",
        );
        assert!(
            recovery_subject("R1", bad).is_err(),
            "recovery_subject must reject id={bad:?}",
        );
    }
}
