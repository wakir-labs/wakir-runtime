// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine Federation-Resolver -- Tag-24 Mini-Welle (9. Modul).
//!
//! Rust authority for the [`FederationResolver`] trait and the
//! [`InMemoryFederationResolver`] reference implementation. The
//! resolver maps a tuple `(org_id, cluster_id)` to the operator-org's
//! Ed25519 public key that signs federation frames coming from that
//! org/cluster pair, accounting for key-rotation history and
//! overlapping validity windows.
//!
//! # Cross-language posture
//!
//! Byte-identical Python sibling at
//! `wirelang/identity/federation_resolver_canonical.py` (Apache-2.0,
//! same Tag-24 bundle). Both modules emit identical JCS-canonical
//! bytes for the cross-lang fixture file
//! `tests/fixtures/federation-resolver-cross-lang/fixtures.json`.
//!
//! # Schema-parity table (Rust <-> Python)
//!
//! | Python concept                              | Rust type/const                       |
//! |---------------------------------------------|---------------------------------------|
//! | `FederationResolver` (Protocol)             | [`FederationResolver`] (trait)        |
//! | `InMemoryFederationResolver`                | [`InMemoryFederationResolver`]        |
//! | `OperatorOrgKeyEntry` (dataclass)           | [`OperatorOrgKeyEntry`]               |
//! | `FederationResolverSnapshot` (dataclass)    | [`FederationResolverSnapshot`]        |
//! | `serialize_resolver_snapshot(snap)`         | [`serialize_resolver_snapshot`]       |
//! | `resolver_snapshot_sha256_hex(snap)`        | [`resolver_snapshot_sha256_hex`]      |
//! | `resolver_snapshot_hash_prefixed(snap)`     | [`resolver_snapshot_hash_prefixed`]   |
//! | `serialize_and_hash(snap)`                  | [`serialize_and_hash`]                |
//! | `FederationResolverError`                   | [`FederationResolverError`]           |
//! | `FEDERATION_RESOLVER_SCHEMA`                | [`FEDERATION_RESOLVER_SCHEMA`]        |
//! | `HASH_PREFIX`                               | [`HASH_PREFIX`]                       |
//! | `SHA256_HEX_LEN`                            | [`SHA256_HEX_LEN`]                    |
//! | `PUBLIC_KEY_HEX_LEN`                        | [`PUBLIC_KEY_HEX_LEN`]                |
//! | `DEFAULT_ALG`                               | [`DEFAULT_ALG`]                       |
//!
//! # Wire-shape contract (two top-level alphabetical keys)
//!
//! - `entries`: ordered array of entry objects (sorted by
//!   `(org_id, cluster_id, valid_from)`).
//! - `schema`: constant [`FEDERATION_RESOLVER_SCHEMA`].
//!
//! Per-entry wire-shape (six alphabetical keys):
//!
//! - `alg`            : algorithm wire-string (Phase-3a: `"Ed25519"`).
//! - `cluster_id`     : cluster identifier.
//! - `org_id`         : operator-org identifier.
//! - `public_key_hex` : 64-char lower-case hex Ed25519 public key.
//! - `valid_from`     : RFC-3339 second-precision UTC, inclusive start.
//! - `valid_until`    : RFC-3339 second-precision UTC, exclusive end.
//!
//! Note: this module deliberately uses [`WireEntry`] (a wire
//! projection) instead of [`OperatorOrgKeyEntry`] for serialisation
//! to pin the field-order explicitly. `serde_jcs` would re-sort
//! regardless, but pinning the wire struct keeps the source-level
//! layout matching the JCS-canonical key order and the explicit
//! dict construction on the Python side.
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 9 (federation-frame
//!   parser; downstream consumer).
//! - Reza PR #148 / #157 -- federation-frame-parser Rust / Python.
//! - Reza PR #176 (Tag-20) -- recovery-workflow canonical-projection.
//! - Reza PR #177 (Tag-21) -- lifecycle-FSM canonical-trace pattern.
//! - Reza PR #183 (Tag-23) -- state-backing cross-lang parity pattern.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

// ---------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------

/// Schema identifier emitted on every federation-resolver canonical
/// snapshot. Byte-for-byte equal to the Python constant
/// `FEDERATION_RESOLVER_SCHEMA`. Bump only when a wire-shape change
/// is intentional.
pub const FEDERATION_RESOLVER_SCHEMA: &str = "wakir.federation.resolver-snapshot/1";

/// Hash prefix string for the prefixed-form snapshot hash.
pub const HASH_PREFIX: &str = "sha256:";

/// Length of a bare-hex SHA-256 digest (no prefix).
pub const SHA256_HEX_LEN: usize = 64;

/// Length of a bare-hex Ed25519 public key (32 bytes -> 64 hex chars).
pub const PUBLIC_KEY_HEX_LEN: usize = 64;

/// Default algorithm. Phase-3a frame signing is Ed25519-only; the
/// `alg` field is carried explicitly on every entry to keep the
/// wire-shape extensible without re-versioning the schema.
pub const DEFAULT_ALG: &str = "Ed25519";

// ---------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------

/// Error surface for caller-supplied input that fails Tag-24 shape
/// pre-conditions. Mirrors `FederationResolverError` on the Python side.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FederationResolverError {
    /// `alg` was not equal to [`DEFAULT_ALG`].
    UnsupportedAlg(String),
    /// `org_id` was empty.
    EmptyOrgId,
    /// `cluster_id` was empty.
    EmptyClusterId,
    /// `public_key_hex` was not [`PUBLIC_KEY_HEX_LEN`] lower-case hex
    /// characters.
    InvalidPublicKeyHex(String),
    /// `valid_from` or `valid_until` was empty, or `valid_from >=
    /// valid_until` (lexical compare on RFC-3339 second-precision UTC).
    InvalidValidityWindow {
        valid_from: String,
        valid_until: String,
    },
    /// A duplicate `(org_id, cluster_id, valid_from)` triple was
    /// presented on registration.
    DuplicateTriple {
        org_id: String,
        cluster_id: String,
        valid_from: String,
    },
}

impl std::fmt::Display for FederationResolverError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnsupportedAlg(a) => write!(
                f,
                "alg must equal {:?}; got {:?}",
                DEFAULT_ALG, a
            ),
            Self::EmptyOrgId => write!(f, "org_id must be a non-empty string"),
            Self::EmptyClusterId => write!(f, "cluster_id must be a non-empty string"),
            Self::InvalidPublicKeyHex(s) => write!(
                f,
                "public_key_hex must be {} lower-case hex chars; got {:?}",
                PUBLIC_KEY_HEX_LEN, s
            ),
            Self::InvalidValidityWindow { valid_from, valid_until } => write!(
                f,
                "valid_from {:?} must be lexically less than valid_until {:?}",
                valid_from, valid_until
            ),
            Self::DuplicateTriple { org_id, cluster_id, valid_from } => write!(
                f,
                "duplicate (org_id, cluster_id, valid_from) triple: ({:?}, {:?}, {:?})",
                org_id, cluster_id, valid_from
            ),
        }
    }
}

impl std::error::Error for FederationResolverError {}

// ---------------------------------------------------------------------
// OperatorOrgKeyEntry -- typed struct + wire projection
// ---------------------------------------------------------------------

/// One operator-org public-key registration. Six fields, mirroring
/// the Python `@dataclass(frozen=True) class OperatorOrgKeyEntry`.
///
/// Construct via [`OperatorOrgKeyEntry::new`] or via
/// [`InMemoryFederationResolver::register`].
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct OperatorOrgKeyEntry {
    /// Algorithm wire-string. Phase-3a accepts `"Ed25519"`.
    pub alg: String,
    /// Cluster identifier within the operator-org. Wire-string;
    /// e.g. `"primary"`, `"backup-eu"`.
    pub cluster_id: String,
    /// Operator-org identifier. Wire-string.
    pub org_id: String,
    /// 64-char lower-case hex of the Ed25519 public key (32 bytes).
    pub public_key_hex: String,
    /// RFC-3339 second-precision UTC start of the key-validity
    /// window (inclusive).
    pub valid_from: String,
    /// RFC-3339 second-precision UTC end of the key-validity window
    /// (exclusive). MUST be lexically greater than `valid_from`.
    pub valid_until: String,
}

impl OperatorOrgKeyEntry {
    /// Construct an entry with the default algorithm pin
    /// ([`DEFAULT_ALG`]). Validation is deferred to
    /// [`InMemoryFederationResolver::register`]; the constructor
    /// itself never fails.
    pub fn new(
        org_id: impl Into<String>,
        cluster_id: impl Into<String>,
        public_key_hex: impl Into<String>,
        valid_from: impl Into<String>,
        valid_until: impl Into<String>,
    ) -> Self {
        Self {
            alg: DEFAULT_ALG.to_string(),
            cluster_id: cluster_id.into(),
            org_id: org_id.into(),
            public_key_hex: public_key_hex.into(),
            valid_from: valid_from.into(),
            valid_until: valid_until.into(),
        }
    }

    /// Validate the entry against the Tag-24 shape pre-conditions.
    /// Returns `Ok(())` on success or [`FederationResolverError`]
    /// describing the first detected violation.
    pub fn validate(&self) -> Result<(), FederationResolverError> {
        if self.alg != DEFAULT_ALG {
            return Err(FederationResolverError::UnsupportedAlg(self.alg.clone()));
        }
        if self.org_id.is_empty() {
            return Err(FederationResolverError::EmptyOrgId);
        }
        if self.cluster_id.is_empty() {
            return Err(FederationResolverError::EmptyClusterId);
        }
        if !is_lower_hex(&self.public_key_hex, PUBLIC_KEY_HEX_LEN) {
            return Err(FederationResolverError::InvalidPublicKeyHex(
                self.public_key_hex.clone(),
            ));
        }
        if self.valid_from.is_empty()
            || self.valid_until.is_empty()
            || self.valid_from >= self.valid_until
        {
            return Err(FederationResolverError::InvalidValidityWindow {
                valid_from: self.valid_from.clone(),
                valid_until: self.valid_until.clone(),
            });
        }
        Ok(())
    }

    /// Return the wire-projection of this entry. The result is a
    /// shallow clone with the canonical field order (alphabetical;
    /// matched by `serde_jcs` regardless, but pinned at the struct
    /// level for readability).
    pub fn to_wire(&self) -> WireEntry {
        WireEntry {
            alg: self.alg.clone(),
            cluster_id: self.cluster_id.clone(),
            org_id: self.org_id.clone(),
            public_key_hex: self.public_key_hex.clone(),
            valid_from: self.valid_from.clone(),
            valid_until: self.valid_until.clone(),
        }
    }
}

fn is_lower_hex(s: &str, expected_len: usize) -> bool {
    if s.len() != expected_len {
        return false;
    }
    s.chars()
        .all(|c| matches!(c, '0'..='9' | 'a'..='f'))
}

// ---------------------------------------------------------------------
// Wire structs (alphabetical field order; serde_jcs re-sorts anyway)
// ---------------------------------------------------------------------

/// Wire-projection of an [`OperatorOrgKeyEntry`]. Mirrors the Python
/// `_entry_to_wire_dict` output exactly. Field order is alphabetical.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireEntry {
    /// Algorithm wire-string.
    pub alg: String,
    /// Cluster identifier within the operator-org.
    pub cluster_id: String,
    /// Operator-org identifier.
    pub org_id: String,
    /// 64-char lower-case hex Ed25519 public key.
    pub public_key_hex: String,
    /// RFC-3339 second-precision UTC inclusive start.
    pub valid_from: String,
    /// RFC-3339 second-precision UTC exclusive end.
    pub valid_until: String,
}

/// The Tag-24 canonical snapshot wire-shape. Two alphabetically-
/// ordered top-level fields. Entries are sorted lexicographically by
/// `(org_id, cluster_id, valid_from)`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FederationResolverSnapshot {
    /// Sorted ordered list of entry wire-projections.
    pub entries: Vec<WireEntry>,
    /// Schema identifier; constant [`FEDERATION_RESOLVER_SCHEMA`].
    pub schema: String,
}

impl FederationResolverSnapshot {
    /// Construct an empty snapshot (no entries).
    pub fn empty() -> Self {
        Self {
            entries: Vec::new(),
            schema: FEDERATION_RESOLVER_SCHEMA.to_string(),
        }
    }

    /// Build a sorted snapshot from a flat slice of entries. The
    /// entries are sorted lexicographically by
    /// `(org_id, cluster_id, valid_from)` so the canonical bytes are
    /// stable regardless of input order. Validation is the caller's
    /// responsibility (use [`OperatorOrgKeyEntry::validate`]).
    pub fn from_entries(entries: &[OperatorOrgKeyEntry]) -> Self {
        let mut wire: Vec<WireEntry> = entries.iter().map(|e| e.to_wire()).collect();
        wire.sort_by(|a, b| {
            (a.org_id.as_str(), a.cluster_id.as_str(), a.valid_from.as_str())
                .cmp(&(b.org_id.as_str(), b.cluster_id.as_str(), b.valid_from.as_str()))
        });
        Self {
            entries: wire,
            schema: FEDERATION_RESOLVER_SCHEMA.to_string(),
        }
    }
}

// ---------------------------------------------------------------------
// FederationResolver trait
// ---------------------------------------------------------------------

/// Minimal trait every federation-resolver implementation honours.
/// Mirrors the Python `FederationResolver` Protocol. A future
/// production binding (NATS-KV, SQL, remote registry) MAY substitute
/// as long as the byte-shape contract holds.
pub trait FederationResolver {
    /// Return the entry currently valid at `now` for the given
    /// `(org_id, cluster_id)` pair, or `None` if no entry is
    /// currently valid.
    ///
    /// "Currently valid" means `valid_from <= now < valid_until`
    /// (lexical compare on RFC-3339 second-precision UTC strings).
    /// When multiple entries overlap, the implementation SHOULD
    /// return the entry with the lexicographically-latest
    /// `valid_from` to prefer newer keys.
    fn resolve(
        &self,
        org_id: &str,
        cluster_id: &str,
        now: &str,
    ) -> Option<OperatorOrgKeyEntry>;

    /// Return all registered entries (any state), sorted
    /// lexicographically by `(org_id, cluster_id, valid_from)`.
    /// Implementations MUST return a defensive copy: the returned
    /// `Vec` is owned by the caller and mutating it MUST NOT affect
    /// the resolver state.
    fn list_entries(&self) -> Vec<OperatorOrgKeyEntry>;

    /// Return a [`FederationResolverSnapshot`] of the current entry
    /// set. The snapshot's `entries` vector MUST be sorted
    /// lexicographically by `(org_id, cluster_id, valid_from)`.
    fn snapshot(&self) -> FederationResolverSnapshot;
}

// ---------------------------------------------------------------------
// InMemoryFederationResolver -- reference implementation
// ---------------------------------------------------------------------

/// In-memory reference implementation of [`FederationResolver`].
///
/// Stores entries in insertion order in a flat `Vec`; resolution
/// walks the vec to gather all entries matching `(org_id,
/// cluster_id)` whose validity window contains `now` and picks the
/// one with the latest `valid_from`.
///
/// Duplicate triples `(org_id, cluster_id, valid_from)` are rejected
/// on registration with
/// [`FederationResolverError::DuplicateTriple`]. Overlapping windows
/// for the same `(org_id, cluster_id)` pair are explicitly allowed
/// (Phase-3a key-rotation use-case).
///
/// The type is intentionally **NOT** thread-safe. The Phase-3a
/// consumer (frame-signature verifier) runs single-threaded.
#[derive(Debug, Default, Clone)]
pub struct InMemoryFederationResolver {
    entries: Vec<OperatorOrgKeyEntry>,
}

impl InMemoryFederationResolver {
    /// Construct an empty resolver.
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a new entry. Validates the entry shape and rejects
    /// duplicate `(org_id, cluster_id, valid_from)` triples.
    pub fn register(
        &mut self,
        entry: OperatorOrgKeyEntry,
    ) -> Result<(), FederationResolverError> {
        entry.validate()?;
        for existing in &self.entries {
            if existing.org_id == entry.org_id
                && existing.cluster_id == entry.cluster_id
                && existing.valid_from == entry.valid_from
            {
                return Err(FederationResolverError::DuplicateTriple {
                    org_id: entry.org_id.clone(),
                    cluster_id: entry.cluster_id.clone(),
                    valid_from: entry.valid_from.clone(),
                });
            }
        }
        self.entries.push(entry);
        Ok(())
    }

    /// Construct a resolver from an iterable of entries; convenience
    /// wrapper that registers each entry in order, short-circuiting
    /// on the first error.
    pub fn from_entries(
        entries: impl IntoIterator<Item = OperatorOrgKeyEntry>,
    ) -> Result<Self, FederationResolverError> {
        let mut r = Self::new();
        for e in entries {
            r.register(e)?;
        }
        Ok(r)
    }
}

impl FederationResolver for InMemoryFederationResolver {
    fn resolve(
        &self,
        org_id: &str,
        cluster_id: &str,
        now: &str,
    ) -> Option<OperatorOrgKeyEntry> {
        let mut best: Option<&OperatorOrgKeyEntry> = None;
        for e in &self.entries {
            if e.org_id != org_id || e.cluster_id != cluster_id {
                continue;
            }
            if e.valid_from.as_str() <= now && now < e.valid_until.as_str() {
                best = match best {
                    None => Some(e),
                    Some(prev) if e.valid_from > prev.valid_from => Some(e),
                    Some(prev) => Some(prev),
                };
            }
        }
        best.cloned()
    }

    fn list_entries(&self) -> Vec<OperatorOrgKeyEntry> {
        let mut out = self.entries.clone();
        out.sort_by(|a, b| {
            (a.org_id.as_str(), a.cluster_id.as_str(), a.valid_from.as_str())
                .cmp(&(b.org_id.as_str(), b.cluster_id.as_str(), b.valid_from.as_str()))
        });
        out
    }

    fn snapshot(&self) -> FederationResolverSnapshot {
        FederationResolverSnapshot::from_entries(&self.entries)
    }
}

// ---------------------------------------------------------------------
// Serialisation + hashing
// ---------------------------------------------------------------------

/// Serialise a [`FederationResolverSnapshot`] to RFC 8785 JCS-
/// canonical bytes. Byte-for-byte equal to the Python
/// `serialize_resolver_snapshot` output for the same logical input.
pub fn serialize_resolver_snapshot(snap: &FederationResolverSnapshot) -> Vec<u8> {
    serde_jcs::to_vec(snap).expect(
        "FederationResolverSnapshot is a flat owned-string struct; \
         serde_jcs::to_vec cannot fail here",
    )
}

/// Lower-case hex SHA-256 digest of `payload`.
pub fn sha256_hex(payload: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(payload);
    hex::encode(hasher.finalize())
}

/// Bare lower-case hex SHA-256 of the JCS-canonical bytes of a snapshot.
pub fn resolver_snapshot_sha256_hex(snap: &FederationResolverSnapshot) -> String {
    sha256_hex(&serialize_resolver_snapshot(snap))
}

/// Prefixed-form SHA-256 (`"sha256:" + bare_hex`) of the JCS-
/// canonical bytes of a snapshot.
pub fn resolver_snapshot_hash_prefixed(snap: &FederationResolverSnapshot) -> String {
    let bare = resolver_snapshot_sha256_hex(snap);
    let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    out.push_str(HASH_PREFIX);
    out.push_str(&bare);
    out
}

/// One-shot helper: return `(canonical_bytes, prefixed_hash)` in a
/// single canonicalisation pass.
pub fn serialize_and_hash(snap: &FederationResolverSnapshot) -> (Vec<u8>, String) {
    let bytes = serialize_resolver_snapshot(snap);
    let mut prefixed = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    prefixed.push_str(HASH_PREFIX);
    prefixed.push_str(&sha256_hex(&bytes));
    (bytes, prefixed)
}

// ---------------------------------------------------------------------
// Library-internal unit tests
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn pk(c: char) -> String {
        std::iter::repeat(c).take(PUBLIC_KEY_HEX_LEN).collect()
    }

    fn entry(
        org_id: &str,
        cluster_id: &str,
        c: char,
        valid_from: &str,
        valid_until: &str,
    ) -> OperatorOrgKeyEntry {
        OperatorOrgKeyEntry::new(org_id, cluster_id, pk(c), valid_from, valid_until)
    }

    #[test]
    fn constants_pin() {
        assert_eq!(FEDERATION_RESOLVER_SCHEMA, "wakir.federation.resolver-snapshot/1");
        assert_eq!(HASH_PREFIX, "sha256:");
        assert_eq!(SHA256_HEX_LEN, 64);
        assert_eq!(PUBLIC_KEY_HEX_LEN, 64);
        assert_eq!(DEFAULT_ALG, "Ed25519");
    }

    #[test]
    fn empty_snapshot_bytes_pin() {
        let r = InMemoryFederationResolver::new();
        let snap = r.snapshot();
        let bytes = serialize_resolver_snapshot(&snap);
        assert_eq!(
            std::str::from_utf8(&bytes).unwrap(),
            r#"{"entries":[],"schema":"wakir.federation.resolver-snapshot/1"}"#
        );
    }

    #[test]
    fn register_validates_alg() {
        let mut r = InMemoryFederationResolver::new();
        let mut e = entry("wakir-labs", "primary", 'a', "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z");
        e.alg = "RSA-2048".to_string();
        let err = r.register(e).expect_err("alg must be Ed25519");
        assert!(matches!(err, FederationResolverError::UnsupportedAlg(_)));
    }

    #[test]
    fn register_validates_pubkey_hex() {
        let mut r = InMemoryFederationResolver::new();
        let mut e = entry("wakir-labs", "primary", 'a', "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z");
        e.public_key_hex = "A".repeat(64); // upper-case rejected
        let err = r.register(e).expect_err("upper-case hex must be rejected");
        assert!(matches!(err, FederationResolverError::InvalidPublicKeyHex(_)));
    }

    #[test]
    fn register_validates_window() {
        let mut r = InMemoryFederationResolver::new();
        let e = entry(
            "wakir-labs",
            "primary",
            'a',
            "2027-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        );
        let err = r.register(e).expect_err("inverted window must be rejected");
        assert!(matches!(err, FederationResolverError::InvalidValidityWindow { .. }));
    }

    #[test]
    fn register_rejects_duplicate_triple() {
        let mut r = InMemoryFederationResolver::new();
        r.register(entry(
            "wakir-labs",
            "primary",
            'a',
            "2026-01-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
        ))
        .unwrap();
        let err = r
            .register(entry(
                "wakir-labs",
                "primary",
                'b',
                "2026-01-01T00:00:00Z",
                "2027-06-01T00:00:00Z",
            ))
            .expect_err("duplicate (org, cluster, valid_from) must be rejected");
        assert!(matches!(err, FederationResolverError::DuplicateTriple { .. }));
    }

    #[test]
    fn resolve_returns_none_on_miss() {
        let mut r = InMemoryFederationResolver::new();
        r.register(entry(
            "wakir-labs",
            "primary",
            'a',
            "2026-01-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
        ))
        .unwrap();
        assert!(r.resolve("unknown", "primary", "2026-06-15T00:00:00Z").is_none());
        assert!(r
            .resolve("wakir-labs", "missing-cluster", "2026-06-15T00:00:00Z")
            .is_none());
        // valid_until is exclusive.
        assert!(r.resolve("wakir-labs", "primary", "2027-01-01T00:00:00Z").is_none());
        // Before window.
        assert!(r.resolve("wakir-labs", "primary", "2025-12-31T23:59:59Z").is_none());
    }

    #[test]
    fn resolve_returns_some_on_hit() {
        let mut r = InMemoryFederationResolver::new();
        r.register(entry(
            "wakir-labs",
            "primary",
            'a',
            "2026-01-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
        ))
        .unwrap();
        // valid_from is inclusive.
        let hit = r
            .resolve("wakir-labs", "primary", "2026-01-01T00:00:00Z")
            .expect("hit");
        assert_eq!(hit.public_key_hex, pk('a'));
    }

    #[test]
    fn resolve_picks_latest_valid_from_when_overlap() {
        let mut r = InMemoryFederationResolver::new();
        r.register(entry(
            "wakir-labs",
            "primary",
            'a',
            "2026-01-01T00:00:00Z",
            "2026-07-01T00:00:00Z",
        ))
        .unwrap();
        r.register(entry(
            "wakir-labs",
            "primary",
            'b',
            "2026-04-01T00:00:00Z",
            "2026-10-01T00:00:00Z",
        ))
        .unwrap();
        let hit = r
            .resolve("wakir-labs", "primary", "2026-04-15T00:00:00Z")
            .expect("overlap hit");
        assert_eq!(hit.public_key_hex, pk('b'));
        assert_eq!(hit.valid_from, "2026-04-01T00:00:00Z");
    }

    #[test]
    fn snapshot_independent_of_insertion_order() {
        let entries = vec![
            entry("org-z", "cluster-a", '1', "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
            entry("org-a", "cluster-z", '2', "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
            entry("org-a", "cluster-a", '3', "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            entry("org-a", "cluster-a", '4', "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
        ];
        let r1 = InMemoryFederationResolver::from_entries(entries.iter().cloned()).unwrap();
        let r2 = InMemoryFederationResolver::from_entries(entries.iter().rev().cloned()).unwrap();
        let b1 = serialize_resolver_snapshot(&r1.snapshot());
        let b2 = serialize_resolver_snapshot(&r2.snapshot());
        assert_eq!(b1, b2);
    }

    #[test]
    fn list_entries_returns_defensive_copy() {
        let mut r = InMemoryFederationResolver::new();
        r.register(entry(
            "wakir-labs",
            "primary",
            'a',
            "2026-01-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
        ))
        .unwrap();
        let mut list_1 = r.list_entries();
        list_1.clear();
        let list_2 = r.list_entries();
        assert_eq!(list_2.len(), 1, "mutation must not affect the resolver");
    }
}
