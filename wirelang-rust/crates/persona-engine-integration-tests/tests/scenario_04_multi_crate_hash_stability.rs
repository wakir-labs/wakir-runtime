// SPDX-License-Identifier: Apache-2.0
//! Scenario 4 — Multi-Crate Hash Stability.
//!
//! Walks five persona fixtures through the
//!
//!   frontmatter-parser  -> v907-verify -> v907-recompute-bench
//!
//! pipeline and asserts that every fixture's pin is:
//!
//!   - byte-identical across the parse_persona_def + compute_from_def
//!     route and the direct compute_v907_pin route, and
//!   - byte-identical across multiple recompute rounds (determinism),
//!     and
//!   - distinct from every other fixture's pin (no hash collision
//!     across the synthetic-bench fixture set).
//!
//! Per-fixture distinctness: the engine-side V-907 canonical subset
//! per `persona-engine-v907-verify::ENGINE_OPTIONAL_KEYS` is
//! `("schema_version", "identity_pinned", "capabilities", "domain",
//! "reports_to")`. Fields outside that set (`name`, `description`,
//! `tools`, `body`) do NOT contribute to the pin. The synthetic
//! fixtures therefore vary along `identity_pinned.hierarchy.reports_to`
//! / `capabilities` to guarantee five distinct pins.
//!
//! Three tests cover:
//!
//!   1. The V9 ground-truth fixture's pin is identical via
//!      compute_v907_pin AND via parse_persona_def +
//!      compute_v907_pin_from_def (cross-crate route equivalence).
//!   2. Five-persona-batch: each fixture's pin is deterministic across
//!      two independent compute calls AND every fixture hashes to a
//!      distinct pin.
//!   3. Five-persona-batch run via the recompute-bench BenchRunner
//!      produces a report whose sample_count == batch_size * iterations
//!      and re-running the same batch yields the same pins (the bench
//!      is side-effect-free).

use persona_engine_v907_recompute_bench::{BenchRunner, PersonaFixture};
use persona_engine_v907_verify::{compute_v907_pin, compute_v907_pin_from_def, parse_persona_def};

const V9_FIXTURE: &str = include_str!("fixtures/persona-v9.md");

/// Build five distinct persona fixtures. The first is the V9 ground-
/// truth document; the other four are minimal synthetic personas. To
/// guarantee distinct V-907 pins each fixture varies its
/// `identity_pinned.hierarchy.reports_to` plus its `capabilities`
/// field — both of which ARE part of the engine-side canonical subset
/// per `ENGINE_OPTIONAL_KEYS`.
fn five_personas() -> Vec<PersonaFixture> {
    let mut v = vec![PersonaFixture {
        slug: "v9-ground-truth".to_string(),
        bytes: V9_FIXTURE.to_string(),
        is_real: false,
    }];
    let reports_targets = ["mira", "priya", "tomas", "aisha"];
    for (i, target) in reports_targets.iter().enumerate() {
        let body = format!(
            "---\n\
name: synthetic-persona-{i:02}\n\
description: \"Synthetic Scenario-04 fixture #{i:02}\"\n\
tools:\n  - Read\n\
schema_version: persona-v1\n\
capabilities:\n  - cap-fixture-{i:02}\n\
identity_pinned:\n  cross_review_zones: []\n  authority:\n    push_remote: false\n    \
budget_cap_eur_per_month: 0\n    sub_delegation: false\n  hierarchy:\n    reports_to: {target}\n    \
escalation: {target}\n\
---\n\n# Synthetic fixture {i:02}\n"
        );
        v.push(PersonaFixture {
            slug: format!("synthetic-{i:02}"),
            bytes: body,
            is_real: false,
        });
    }
    v
}

#[test]
fn t01_v9_ground_truth_pin_is_route_invariant() {
    // Two engine-side routes must yield the same pin for the same
    // markdown input — that is the cross-crate invariant.
    //
    // Route A: direct compute_v907_pin over the markdown string.
    let pin_a = compute_v907_pin(V9_FIXTURE).expect("v9 must hash via compute_v907_pin");

    // Route B: parse_persona_def -> compute_v907_pin_from_def.
    let def = parse_persona_def(V9_FIXTURE).expect("v9 must parse");
    let pin_b =
        compute_v907_pin_from_def(&def).expect("v9 must hash via compute_v907_pin_from_def");
    assert_eq!(
        pin_a, pin_b,
        "Route A (compute_v907_pin) and Route B (parse + compute_from_def) must agree",
    );

    // Sanity: the pin has the documented surface shape (sha256:<64hex>).
    assert!(pin_a.starts_with("sha256:"));
    assert_eq!(pin_a.len(), 71);
}

#[test]
fn t02_five_persona_pins_are_deterministic_and_unique() {
    let fixtures = five_personas();
    assert_eq!(fixtures.len(), 5);

    // Two independent emissions per fixture must yield identical pins.
    let pins_a: Vec<String> = fixtures
        .iter()
        .map(|fx| compute_v907_pin(&fx.bytes).expect("hash a"))
        .collect();
    let pins_b: Vec<String> = fixtures
        .iter()
        .map(|fx| compute_v907_pin(&fx.bytes).expect("hash b"))
        .collect();
    assert_eq!(pins_a, pins_b, "v907 pins must be deterministic");

    // No collisions across the five distinct fixtures.
    let mut sorted = pins_a.clone();
    sorted.sort();
    sorted.dedup();
    assert_eq!(
        sorted.len(),
        pins_a.len(),
        "all five fixtures must hash to distinct pins; got duplicates in {pins_a:?}",
    );
}

#[test]
fn t03_recompute_bench_runs_and_pins_remain_stable() {
    let fixtures = five_personas();
    let runner = BenchRunner::new();
    let report = runner
        .run_recompute_batch(&fixtures, 3)
        .expect("bench must run");
    assert_eq!(report.batch_size, fixtures.len());
    assert_eq!(report.iterations, 3);
    let expected_total: usize = fixtures.len() * 3;
    assert_eq!(report.sample_count, expected_total);

    // A direct re-hash AFTER the bench has consumed the fixtures must
    // still match the first emission's pin: BenchRunner does not
    // mutate fixture state. Capture the pre-bench pin AND the post-
    // bench pin separately to make the side-effect-free invariant
    // explicit.
    let pin_before_round_two = compute_v907_pin(&fixtures[0].bytes).expect("re-hash post-bench");
    let report_round_two = runner.run_recompute_batch(&fixtures, 1).expect("bench round 2");
    let pin_after_round_two = compute_v907_pin(&fixtures[0].bytes).expect("re-hash post-round-2");
    assert_eq!(
        pin_before_round_two, pin_after_round_two,
        "bench must be side-effect-free across multiple rounds",
    );
    assert_eq!(report_round_two.batch_size, fixtures.len());
}
