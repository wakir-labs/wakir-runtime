// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Engine-version migration pre-flight decision canonical-trace.
//!
//! Rust pendant of [`wirelang.persona_engine.migrate_version_canonical`]
//! (Python). Tag-38 Phase-3a-Foundation 15. Modul — closes the
//! Phase-3a-Foundation sweep.
//!
//! The live Python workflow
//! [`wirelang.persona_engine.migrate_version.MigrateVersionWorkflow`]
//! is stateful: it talks to a `PersonaStateBacking`, lists snapshots,
//! reads / writes the pinned offset, stamps the engine-version
//! sentinel key. None of that is byte-paritätisch across Python and
//! Rust without a network of mocked backings.
//!
//! The **pre-flight decision** — "is this
//! `(from_version, to_version, allow_major_bump)` tuple acceptable,
//! and if not why?" — IS byte-paritätisch and is the cross-engine
//! determinism anchor called out by the Selin roadmap §1.3
//! ("state-pack envelope must be byte-stable across engines").
//!
//! This crate provides exactly that pre-flight surface: parse both
//! semver tags, check known-version membership, evaluate the
//! major-bump rule, produce a structured
//! [`MigrateVersionDecisionTrace`].
//!
//! Schema
//! ------
//!
//! The canonical-trace carries exactly eleven top-level fields
//! (alphabetically sorted in the canonical form):
//!
//! 1. `accepted_status` — `"ok"` or `"rejected"`.
//! 2. `allow_major_bump` — Boolean policy bit echoed.
//! 3. `failure_mode` — Wire-string of the failure mode on
//!    `rejected`; empty string `""` on `ok`.
//! 4. `from_major` — Semver major component of `from_version`.
//! 5. `from_minor` — Semver minor component.
//! 6. `from_version` — Input string echoed.
//! 7. `major_bump_required` — Boolean: `from_major != to_major`
//!    when both parse cleanly.
//! 8. `schema` — Constant schema id.
//! 9. `to_major` — Semver major component of `to_version`.
//! 10. `to_minor` — Semver minor component.
//! 11. `to_version` — Input string echoed.
//!
//! Serialisation
//! -------------
//!
//! The canonical bytes are produced by `serde_jcs::to_vec`. The
//! outer trace hash is `"sha256:" + hex(SHA-256(canonical_bytes))`.
//! Mirrors the Python `rfc8785.dumps` + `hashlib.sha256` discipline
//! byte-for-byte.
//!
//! Cross-lang anchor
//! -----------------
//!
//! Both Python and Rust suites consume the same fixture file
//! `tests/fixtures/migrate-version-cross-lang/fixtures.json` (repo
//! root, two levels above the workspace root). Any drift on either
//! side fails both suites simultaneously.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value as JsonValue};
use sha2::{Digest, Sha256};

// ---------------------------------------------------------------------
// Cross-lang anchor constants.
// ---------------------------------------------------------------------

/// JCS-canonical schema id. Cross-lang anchor — must match the
/// Python constant `MIGRATE_VERSION_DECISION_TRACE_SCHEMA`.
pub const MIGRATE_VERSION_DECISION_TRACE_SCHEMA: &str =
    "wakir.persona-engine.migrate-version-canonical/1";

/// Outer-hash prefix. Cross-lang anchor.
pub const HASH_PREFIX: &str = "sha256:";

/// Length of a SHA-256 hex digest (32 bytes = 64 hex chars).
pub const SHA256_HEX_LEN: usize = 64;

/// Accepted-status: successful pre-flight. Wire-string `"ok"`.
pub const STATUS_OK: &str = "ok";
/// Accepted-status: pre-flight rejection. Wire-string `"rejected"`.
pub const STATUS_REJECTED: &str = "rejected";

/// Failure mode: `from_version` not in
/// [`KNOWN_ENGINE_VERSIONS`].
pub const FAILURE_MODE_UNKNOWN_FROM_VERSION: &str = "UnknownFromVersion";
/// Failure mode: `to_version` not in [`KNOWN_ENGINE_VERSIONS`].
pub const FAILURE_MODE_UNKNOWN_TO_VERSION: &str = "UnknownToVersion";
/// Failure mode: cross-major bump without `allow_major_bump=true`.
/// Currently structurally unreachable from the closed
/// [`KNOWN_ENGINE_VERSIONS`] set (all entries share major `0`); the
/// wire-string is pinned for future-proofing per the live module's
/// posture.
pub const FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED: &str =
    "MajorVersionBumpDisallowed";

/// Closed set of engine semver tags this canonical-trace knows
/// about. Mirrors Python `KNOWN_ENGINE_VERSIONS` byte-for-byte —
/// any addition requires a coordinated three-place edit (Python
/// live module + Python canonical sibling + this crate) and a
/// fixture re-derivation.
pub const KNOWN_ENGINE_VERSIONS: &[&str] = &[
    "0.2.0-pilot",
    "0.3.0-pilot",
    "0.4.0-pilot",
];

// ---------------------------------------------------------------------
// Trace dataclass.
// ---------------------------------------------------------------------

/// Canonical-trace projection of a migrate-version pre-flight
/// decision.
///
/// Fields are NOT in alphabetical order at the struct level (the
/// JCS canonicalisation re-sorts them lexicographically anyway).
/// The ten fields plus the constant `schema` field appear on the
/// wire in alphabetical order:
///
/// 1. `accepted_status`
/// 2. `allow_major_bump`
/// 3. `failure_mode`
/// 4. `from_major`
/// 5. `from_minor`
/// 6. `from_version`
/// 7. `major_bump_required`
/// 8. `schema`              (constant: [`MIGRATE_VERSION_DECISION_TRACE_SCHEMA`])
/// 9. `to_major`
/// 10. `to_minor`
/// 11. `to_version`
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MigrateVersionDecisionTrace {
    /// Status discriminant. One of [`STATUS_OK`], [`STATUS_REJECTED`].
    pub accepted_status: String,
    /// Boolean policy bit echoed for trace reproducibility.
    pub allow_major_bump: bool,
    /// Wire-string failure mode on `rejected`; empty on `ok`.
    pub failure_mode: String,
    /// Semver-parsed major component of `from_version`. Zero on
    /// parse-failure.
    pub from_major: u64,
    /// Semver-parsed minor component. Zero on parse-failure.
    pub from_minor: u64,
    /// `from_version` input string echoed verbatim.
    pub from_version: String,
    /// `true` iff `from_major != to_major` after both parse
    /// cleanly. `false` on any parse-fail (schema-symmetric default).
    pub major_bump_required: bool,
    /// Semver-parsed major component of `to_version`. Zero on
    /// parse-failure.
    pub to_major: u64,
    /// Semver-parsed minor component. Zero on parse-failure.
    pub to_minor: u64,
    /// `to_version` input string echoed verbatim.
    pub to_version: String,
}

// ---------------------------------------------------------------------
// Semver helpers (hand-rolled to avoid a new workspace dep on `regex`).
// ---------------------------------------------------------------------

/// Parse a relaxed-semver tag `M.m.p[-prerelease]`. Returns
/// `(major, minor, true)` on success, `(0, 0, false)` on failure.
///
/// The grammar mirrors the Python `_SEMVER_RE` regex byte-for-byte:
///
/// - Three dot-separated unsigned integers.
/// - Optional `-prerelease` suffix of `[A-Za-z0-9-]+`.
/// - The patch component is parsed but not echoed on the wire (the
///   wire schema carries only major / minor; patch is not part of
///   the determinism anchor).
fn parse_semver_strict(tag: &str) -> (u64, u64, bool) {
    // Split on `-` once for the optional prerelease tail.
    let (core, prerelease) = match tag.split_once('-') {
        Some((core, rest)) => (core, Some(rest)),
        None => (tag, None),
    };

    // Validate prerelease character set if present.
    if let Some(pre) = prerelease {
        if pre.is_empty() {
            return (0, 0, false);
        }
        for c in pre.chars() {
            if !(c.is_ascii_alphanumeric() || c == '-') {
                return (0, 0, false);
            }
        }
    }

    let parts: Vec<&str> = core.split('.').collect();
    if parts.len() != 3 {
        return (0, 0, false);
    }

    // Each of the three parts must be a non-empty ASCII digit string.
    for part in &parts {
        if part.is_empty() {
            return (0, 0, false);
        }
        for c in part.chars() {
            if !c.is_ascii_digit() {
                return (0, 0, false);
            }
        }
    }

    let major = match parts[0].parse::<u64>() {
        Ok(v) => v,
        Err(_) => return (0, 0, false),
    };
    let minor = match parts[1].parse::<u64>() {
        Ok(v) => v,
        Err(_) => return (0, 0, false),
    };
    // Patch parsed for grammar validation only; not echoed.
    if parts[2].parse::<u64>().is_err() {
        return (0, 0, false);
    }

    (major, minor, true)
}

// ---------------------------------------------------------------------
// Trace-build helper.
// ---------------------------------------------------------------------

/// Build a canonical migrate-version pre-flight decision trace.
///
/// Infallible at the trace-build layer: every decision outcome
/// (success, unknown-from, unknown-to, major-bump-disallowed) is
/// captured as a structured trace with the appropriate
/// `accepted_status` and `failure_mode` populated.
///
/// Decision order
/// --------------
///
/// 1. `from_version` not in [`KNOWN_ENGINE_VERSIONS`] ->
///    `rejected` / [`FAILURE_MODE_UNKNOWN_FROM_VERSION`].
/// 2. `to_version` not in [`KNOWN_ENGINE_VERSIONS`] ->
///    `rejected` / [`FAILURE_MODE_UNKNOWN_TO_VERSION`].
/// 3. `from_major != to_major` AND not `allow_major_bump` ->
///    `rejected` / [`FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED`].
/// 4. Otherwise -> `ok`.
///
/// The order of evaluation is part of the cross-lang contract.
/// Re-ordering between (1) and (2) would change the
/// `failure_mode` on a `(unknown, unknown)` pair and is forbidden.
pub fn build_migrate_version_decision_trace(
    from_version: &str,
    to_version: &str,
    allow_major_bump: bool,
) -> MigrateVersionDecisionTrace {
    let (from_major, from_minor, from_parsed) =
        parse_semver_strict(from_version);
    let (to_major, to_minor, to_parsed) =
        parse_semver_strict(to_version);

    let from_known = KNOWN_ENGINE_VERSIONS.iter().any(|v| *v == from_version);
    let to_known = KNOWN_ENGINE_VERSIONS.iter().any(|v| *v == to_version);

    // major_bump_required is meaningful only when BOTH parse
    // cleanly. When either tag is unparseable the field is `false`
    // (schema-symmetric default).
    let major_bump_required =
        if from_parsed && to_parsed { from_major != to_major } else { false };

    if !from_known {
        return MigrateVersionDecisionTrace {
            accepted_status: STATUS_REJECTED.to_string(),
            allow_major_bump,
            failure_mode: FAILURE_MODE_UNKNOWN_FROM_VERSION.to_string(),
            from_major,
            from_minor,
            from_version: from_version.to_string(),
            major_bump_required,
            to_major,
            to_minor,
            to_version: to_version.to_string(),
        };
    }

    if !to_known {
        return MigrateVersionDecisionTrace {
            accepted_status: STATUS_REJECTED.to_string(),
            allow_major_bump,
            failure_mode: FAILURE_MODE_UNKNOWN_TO_VERSION.to_string(),
            from_major,
            from_minor,
            from_version: from_version.to_string(),
            major_bump_required,
            to_major,
            to_minor,
            to_version: to_version.to_string(),
        };
    }

    if major_bump_required && !allow_major_bump {
        return MigrateVersionDecisionTrace {
            accepted_status: STATUS_REJECTED.to_string(),
            allow_major_bump,
            failure_mode: FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED
                .to_string(),
            from_major,
            from_minor,
            from_version: from_version.to_string(),
            major_bump_required: true,
            to_major,
            to_minor,
            to_version: to_version.to_string(),
        };
    }

    MigrateVersionDecisionTrace {
        accepted_status: STATUS_OK.to_string(),
        allow_major_bump,
        failure_mode: String::new(),
        from_major,
        from_minor,
        from_version: from_version.to_string(),
        major_bump_required,
        to_major,
        to_minor,
        to_version: to_version.to_string(),
    }
}

// ---------------------------------------------------------------------
// Wire-dict projection + serialisation.
// ---------------------------------------------------------------------

/// Project a trace into its alphabetical wire-dict.  Keys appear in
/// alphabetical order at the wire level after JCS canonicalisation.
pub fn trace_to_wire_dict(trace: &MigrateVersionDecisionTrace) -> JsonValue {
    let mut m = Map::with_capacity(11);
    m.insert(
        "accepted_status".to_string(),
        JsonValue::String(trace.accepted_status.clone()),
    );
    m.insert(
        "allow_major_bump".to_string(),
        JsonValue::Bool(trace.allow_major_bump),
    );
    m.insert(
        "failure_mode".to_string(),
        JsonValue::String(trace.failure_mode.clone()),
    );
    m.insert(
        "from_major".to_string(),
        JsonValue::Number(trace.from_major.into()),
    );
    m.insert(
        "from_minor".to_string(),
        JsonValue::Number(trace.from_minor.into()),
    );
    m.insert(
        "from_version".to_string(),
        JsonValue::String(trace.from_version.clone()),
    );
    m.insert(
        "major_bump_required".to_string(),
        JsonValue::Bool(trace.major_bump_required),
    );
    m.insert(
        "schema".to_string(),
        JsonValue::String(MIGRATE_VERSION_DECISION_TRACE_SCHEMA.to_string()),
    );
    m.insert(
        "to_major".to_string(),
        JsonValue::Number(trace.to_major.into()),
    );
    m.insert(
        "to_minor".to_string(),
        JsonValue::Number(trace.to_minor.into()),
    );
    m.insert(
        "to_version".to_string(),
        JsonValue::String(trace.to_version.clone()),
    );
    JsonValue::Object(m)
}

/// Serialise a trace to its JCS-canonical UTF-8 bytes.
pub fn serialize_trace(trace: &MigrateVersionDecisionTrace) -> Vec<u8> {
    // `unwrap` is justified: the wire-dict is a pure `Map<String,
    // JsonValue>` of strings + bools + small u64 numbers — JCS
    // canonicalisation is total over this domain.
    serde_jcs::to_vec(&trace_to_wire_dict(trace))
        .expect("trace wire-dict is always JCS-canonicalisable")
}

/// SHA-256 hex of the JCS bytes of `trace`.
pub fn trace_sha256_hex(trace: &MigrateVersionDecisionTrace) -> String {
    sha256_hex(&serialize_trace(trace))
}

/// Prefixed outer hash: `"sha256:" + trace_sha256_hex`.
pub fn trace_hash_prefixed(trace: &MigrateVersionDecisionTrace) -> String {
    let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    out.push_str(HASH_PREFIX);
    out.push_str(&trace_sha256_hex(trace));
    out
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut s = String::with_capacity(SHA256_HEX_LEN);
    for b in digest.iter() {
        use std::fmt::Write as _;
        let _ = write!(&mut s, "{:02x}", b);
    }
    s
}

// ---------------------------------------------------------------------
// Inline smoke tests (cross-lang fixture lives in tests/).
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_schema_constants_pin() {
        assert_eq!(
            MIGRATE_VERSION_DECISION_TRACE_SCHEMA,
            "wakir.persona-engine.migrate-version-canonical/1"
        );
        assert_eq!(HASH_PREFIX, "sha256:");
        assert_eq!(SHA256_HEX_LEN, 64);
    }

    #[test]
    fn test_known_engine_versions_pin() {
        assert_eq!(
            KNOWN_ENGINE_VERSIONS,
            &["0.2.0-pilot", "0.3.0-pilot", "0.4.0-pilot"]
        );
    }

    #[test]
    fn test_status_wire_strings() {
        assert_eq!(STATUS_OK, "ok");
        assert_eq!(STATUS_REJECTED, "rejected");
    }

    #[test]
    fn test_failure_mode_wire_strings() {
        assert_eq!(FAILURE_MODE_UNKNOWN_FROM_VERSION, "UnknownFromVersion");
        assert_eq!(FAILURE_MODE_UNKNOWN_TO_VERSION, "UnknownToVersion");
        assert_eq!(
            FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED,
            "MajorVersionBumpDisallowed"
        );
    }

    #[test]
    fn test_parse_semver_known_tags() {
        assert_eq!(parse_semver_strict("0.2.0-pilot"), (0, 2, true));
        assert_eq!(parse_semver_strict("0.3.0-pilot"), (0, 3, true));
        assert_eq!(parse_semver_strict("0.4.0-pilot"), (0, 4, true));
        assert_eq!(parse_semver_strict("1.2.3"), (1, 2, true));
        assert_eq!(parse_semver_strict("9.99.0-alpha-beta"), (9, 99, true));
    }

    #[test]
    fn test_parse_semver_rejects_garbage() {
        assert_eq!(parse_semver_strict(""), (0, 0, false));
        assert_eq!(parse_semver_strict("not-a-version"), (0, 0, false));
        assert_eq!(parse_semver_strict("0.3"), (0, 0, false));
        assert_eq!(parse_semver_strict("0.3.0."), (0, 0, false));
        assert_eq!(parse_semver_strict("a.b.c"), (0, 0, false));
        assert_eq!(parse_semver_strict("0.3.0-"), (0, 0, false));
        assert_eq!(parse_semver_strict("0.3.0-bad space"), (0, 0, false));
    }

    #[test]
    fn test_decision_ok_same_major() {
        let t = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "0.4.0-pilot",
            false,
        );
        assert_eq!(t.accepted_status, STATUS_OK);
        assert_eq!(t.failure_mode, "");
        assert!(!t.major_bump_required);
        assert_eq!(t.from_major, 0);
        assert_eq!(t.from_minor, 3);
        assert_eq!(t.to_major, 0);
        assert_eq!(t.to_minor, 4);
    }

    #[test]
    fn test_decision_unknown_from_version() {
        let t = build_migrate_version_decision_trace(
            "0.1.0-pilot",
            "0.4.0-pilot",
            false,
        );
        assert_eq!(t.accepted_status, STATUS_REJECTED);
        assert_eq!(t.failure_mode, FAILURE_MODE_UNKNOWN_FROM_VERSION);
    }

    #[test]
    fn test_decision_unknown_to_version() {
        let t = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "0.5.0-pilot",
            false,
        );
        assert_eq!(t.accepted_status, STATUS_REJECTED);
        assert_eq!(t.failure_mode, FAILURE_MODE_UNKNOWN_TO_VERSION);
    }

    #[test]
    fn test_decision_order_from_before_to() {
        // Both unknown — from-check fires first.
        let t = build_migrate_version_decision_trace(
            "0.99.0-pilot",
            "0.98.0-pilot",
            false,
        );
        assert_eq!(t.accepted_status, STATUS_REJECTED);
        assert_eq!(t.failure_mode, FAILURE_MODE_UNKNOWN_FROM_VERSION);
    }

    #[test]
    fn test_serialize_determinism() {
        let t1 = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "0.4.0-pilot",
            false,
        );
        let t2 = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "0.4.0-pilot",
            false,
        );
        assert_eq!(serialize_trace(&t1), serialize_trace(&t2));
        assert_eq!(trace_sha256_hex(&t1), trace_sha256_hex(&t2));
    }

    #[test]
    fn test_hash_shape() {
        let t = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "0.4.0-pilot",
            false,
        );
        let bare = trace_sha256_hex(&t);
        let prefixed = trace_hash_prefixed(&t);
        assert_eq!(bare.len(), SHA256_HEX_LEN);
        assert!(bare.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        assert_eq!(prefixed, format!("{}{}", HASH_PREFIX, bare));
    }

    #[test]
    fn test_infallibility_on_garbage_inputs() {
        // None of these should panic; all produce structured traces.
        let _ = build_migrate_version_decision_trace("", "", false);
        let _ = build_migrate_version_decision_trace(
            "not-a-version",
            "0.4.0-pilot",
            false,
        );
        let _ = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "not-a-version",
            false,
        );
        let _ = build_migrate_version_decision_trace(
            "0.3.0-pilot",
            "0.4.0-pilot",
            true,
        );
    }
}
