// SPDX-License-Identifier: Apache-2.0
//! Fixture loaders for the V-907 recompute benchmark.
//!
//! Two corpora are supported:
//!
//! 1. **Synthetic** — deterministically generated persona-definition
//!    markdown. The generator is seeded by an integer index; identical
//!    indices produce identical markdown bytes byte-for-byte across
//!    runs and machines. Used for the bulk of the bench corpus (1000
//!    personas in the canonical bench setup).
//! 2. **Real** — hand-curated persona-definition markdown checked into
//!    the crate under `tests/fixtures/v907_pin_pack/*.md`. These are
//!    representative of operator-supplied personas (Mira, Tomás,
//!    Priya, Kai, Aisha) and exercise the canonical-subset lift over
//!    the four optional keys.
//!
//! Determinism contract
//! --------------------
//! - `synthetic_corpus(n)` produces the same `Vec<PersonaFixture>`
//!   byte-for-byte every call, for any `n`. The slugs are
//!   `"synthetic-{i:05}"` (5-digit zero-padded).
//! - `real_corpus()` returns the 5 hand-curated personas in the order
//!   `["mira", "tomas", "priya", "kai", "aisha"]`.
//! - `default_corpus()` is the canonical bench setup: 50 synthetic +
//!   5 real personas = 55 fixtures total. The 50/5 split keeps the
//!   bench loop fast enough to run under `cargo bench` in a few seconds
//!   while still exercising both fixture shapes.
//!
//! The 1000-persona corpus mentioned in the auftrag is reached by
//! calling `synthetic_corpus(1000)` directly; the bench harness in
//! `benches/v907_recompute.rs` does exactly that for the full sweep.

use crate::PersonaFixture;

/// Number of synthetic fixtures in [`default_corpus`].
pub const DEFAULT_SYNTHETIC_COUNT: usize = 50;

/// Number of real (curated) fixtures in [`default_corpus`].
pub const DEFAULT_REAL_COUNT: usize = 5;

/// Build a deterministic synthetic persona-definition fixture from an
/// integer index.
///
/// The output is a valid axis-A persona-definition markdown with
/// front-matter populated for `name`, `description`, `schema_version`,
/// `identity_pinned.email`, `domain`, and (every 3rd persona)
/// `capabilities` + (every 5th persona) `reports_to`. The variation
/// across the index space gives the JCS canonicaliser a non-trivial
/// shape to chew on (otherwise the bench would only measure the
/// trivial-shape fast path).
///
/// The output is fully deterministic given the index — no clock, no
/// PRNG, no hashing. Two calls with the same `idx` return byte-
/// identical strings.
#[must_use]
pub fn synthetic_persona(idx: usize) -> PersonaFixture {
    let slug = format!("synthetic-{idx:05}");
    let mut fm = String::with_capacity(512);
    fm.push_str("---\n");
    fm.push_str(&format!("name: synth-persona-{idx:05}\n"));
    fm.push_str(&format!(
        "description: synthetic persona {idx:05} for V-907 recompute bench\n"
    ));
    fm.push_str("schema_version: persona-v1\n");
    fm.push_str("identity_pinned:\n");
    fm.push_str(&format!("  email: synth-{idx:05}@bench.local\n"));
    let domain = SYNTH_DOMAINS[idx % SYNTH_DOMAINS.len()];
    fm.push_str(&format!("domain: {domain}\n"));
    if idx % 3 == 0 {
        fm.push_str("capabilities:\n");
        for cap in &SYNTH_CAPS[..1 + idx % SYNTH_CAPS.len()] {
            fm.push_str(&format!("  - {cap}\n"));
        }
    }
    if idx % 5 == 0 {
        let reports_to = SYNTH_REPORTS_TO[idx % SYNTH_REPORTS_TO.len()];
        fm.push_str(&format!("reports_to: {reports_to}\n"));
    }
    fm.push_str("---\n\n");
    fm.push_str(&format!(
        "Body for synthetic persona {idx:05}.\n\
         Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n\
         Body content does NOT reach the V-907 hash; it is included\n\
         to make the synthetic markdown shape representative of real\n\
         persona-definition files.\n"
    ));
    PersonaFixture {
        slug,
        bytes: fm,
        is_real: false,
    }
}

/// Deterministic domain values used by the synthetic generator. Six
/// values give enough variation that the canonical subset is not the
/// same string for every odd index without exploding the search-space.
const SYNTH_DOMAINS: &[&str] = &[
    "dev-engineering",
    "hr",
    "cfo",
    "cto",
    "sre",
    "internal-audit",
];

/// Deterministic capabilities used by the synthetic generator.
const SYNTH_CAPS: &[&str] = &["read", "write", "execute", "audit", "ratify"];

/// Deterministic reports-to slugs used by the synthetic generator.
const SYNTH_REPORTS_TO: &[&str] = &["aufsichtsrat", "ceo", "cto", "ceo", "ceo"];

/// Build a `n`-fixture synthetic corpus. Indices are `0..n`.
///
/// # Panics
///
/// Panics only if `n` overflows `usize` allocation — practically never.
#[must_use]
pub fn synthetic_corpus(n: usize) -> Vec<PersonaFixture> {
    (0..n).map(synthetic_persona).collect()
}

/// The 5 curated real-persona fixtures. Loaded via `include_str!` so
/// the binary is self-contained.
#[must_use]
pub fn real_corpus() -> Vec<PersonaFixture> {
    vec![
        PersonaFixture {
            slug: "real-mira".to_string(),
            bytes: include_str!("../tests/fixtures/v907_pin_pack/mira.md").to_string(),
            is_real: true,
        },
        PersonaFixture {
            slug: "real-tomas".to_string(),
            bytes: include_str!("../tests/fixtures/v907_pin_pack/tomas.md").to_string(),
            is_real: true,
        },
        PersonaFixture {
            slug: "real-priya".to_string(),
            bytes: include_str!("../tests/fixtures/v907_pin_pack/priya.md").to_string(),
            is_real: true,
        },
        PersonaFixture {
            slug: "real-kai".to_string(),
            bytes: include_str!("../tests/fixtures/v907_pin_pack/kai.md").to_string(),
            is_real: true,
        },
        PersonaFixture {
            slug: "real-aisha".to_string(),
            bytes: include_str!("../tests/fixtures/v907_pin_pack/aisha.md").to_string(),
            is_real: true,
        },
    ]
}

/// Canonical bench corpus: 50 synthetic + 5 real = 55 fixtures.
///
/// The 50/5 split keeps the unit-test loop fast (~50ms on dev
/// hardware) while still exercising both shapes. The bench harness in
/// `benches/v907_recompute.rs` calls `synthetic_corpus(1000)` directly
/// for the full 1000-persona sweep.
#[must_use]
pub fn default_corpus() -> Vec<PersonaFixture> {
    let mut out = synthetic_corpus(DEFAULT_SYNTHETIC_COUNT);
    out.extend(real_corpus());
    out
}

#[cfg(test)]
mod fixture_tests {
    use super::*;
    use persona_engine_v907_verify::compute_v907_pin;

    /// Synthetic generator is deterministic: same idx → byte-identical
    /// markdown across two calls. Locks the no-clock / no-PRNG
    /// invariant.
    #[test]
    fn synthetic_persona_is_byte_deterministic() {
        for idx in [0_usize, 1, 7, 42, 999] {
            let a = synthetic_persona(idx);
            let b = synthetic_persona(idx);
            assert_eq!(a, b, "synthetic_persona({idx}) must be byte-deterministic");
        }
    }

    /// Synthetic corpus has the expected length and slug ordering.
    #[test]
    fn synthetic_corpus_length_and_slug_order() {
        let c = synthetic_corpus(10);
        assert_eq!(c.len(), 10);
        assert_eq!(c[0].slug, "synthetic-00000");
        assert_eq!(c[9].slug, "synthetic-00009");
        assert!(c.iter().all(|f| !f.is_real));
    }

    /// Real corpus has the expected slugs in the expected order.
    #[test]
    fn real_corpus_slugs_in_documented_order() {
        let c = real_corpus();
        let slugs: Vec<_> = c.iter().map(|f| f.slug.as_str()).collect();
        assert_eq!(
            slugs,
            vec![
                "real-mira",
                "real-tomas",
                "real-priya",
                "real-kai",
                "real-aisha"
            ]
        );
        assert!(c.iter().all(|f| f.is_real));
    }

    /// Default corpus is 50 synthetic + 5 real = 55.
    #[test]
    fn default_corpus_has_50_synthetic_5_real() {
        let c = default_corpus();
        assert_eq!(c.len(), DEFAULT_SYNTHETIC_COUNT + DEFAULT_REAL_COUNT);
        let real = c.iter().filter(|f| f.is_real).count();
        assert_eq!(real, DEFAULT_REAL_COUNT);
        let synth = c.iter().filter(|f| !f.is_real).count();
        assert_eq!(synth, DEFAULT_SYNTHETIC_COUNT);
    }

    /// Every fixture in the default corpus must be hashable by the
    /// v907-verify code path. This catches the case where the
    /// synthetic generator emits malformed YAML (e.g. a colon-bearing
    /// value that needs quoting) before that bug reaches the bench loop.
    #[test]
    fn every_default_corpus_fixture_hashes_cleanly() {
        let c = default_corpus();
        for fx in &c {
            let pin = compute_v907_pin(&fx.bytes)
                .unwrap_or_else(|e| panic!("fixture {} failed to hash: {e}", fx.slug));
            assert!(
                pin.starts_with("sha256:"),
                "fixture {} produced malformed pin {pin}",
                fx.slug
            );
        }
    }

    /// Synthetic-persona variation: at least two different domain
    /// strings appear in a 10-fixture sweep. Guards against a
    /// regression where the generator accidentally collapses to a
    /// single domain (which would defeat the bench's purpose of
    /// exercising a non-trivial canonical-subset shape).
    #[test]
    fn synthetic_corpus_varies_in_domain_value() {
        let c = synthetic_corpus(10);
        let mut seen = std::collections::HashSet::new();
        for fx in &c {
            for line in fx.bytes.lines() {
                if let Some(rest) = line.strip_prefix("domain: ") {
                    seen.insert(rest.to_string());
                }
            }
        }
        assert!(
            seen.len() >= 2,
            "expected ≥2 distinct domain values in 10-fixture sweep, got {seen:?}"
        );
    }
}
