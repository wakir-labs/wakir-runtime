// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine NATS-KV Persona-State-Backing — Rust substrate
//! (Phase-3a Item 6).
//!
//! This is the **initial Rust scaffold** of the persona-engine
//! NATS-KV Persona-State backing module. The Python reference
//! implementation lives at `wirelang/persona_engine/state_backing.py`
//! (Selin Sprint-Pengine-8 PR #65, persona-engine-format-spec §3.7.5).
//! The Doppelbetrieb-Konsistenz contract (Selin PR #113 3-way-triangle)
//! requires this Rust substrate to produce schema-byte-parity with
//! the Python module at the JCS-canonical envelope boundary.
//!
//! # Scope of this scaffold
//!
//! This crate intentionally does **not** open a live NATS-KV socket.
//! The wire-level NATS-KV `connect()` / `put` / `get` operations stay
//! `TODO`-shaped behind the [`NatsKvStateBacking`] type-level surface;
//! the `async-nats` crate is pulled in as a compile-dep so the
//! Phase-3a-step "live-binding" follow-up can extend without re-
//! deciding the client. Smoke-tests do **not** touch async-nats —
//! they exclusively exercise [`InMemoryStateBacking`].
//!
//! # Schema parity with PR #65 (`state_backing.py`)
//!
//! | Python concept                              | Rust type/const                  |
//! |---------------------------------------------|----------------------------------|
//! | `PersonaStateSnapshot` (dataclass)          | [`PersonaStateSnapshot`]         |
//! | `PersonaStateBackingError`                  | [`StateBackingError`]            |
//! | `PersonaStateBackingAsync` (trait)          | [`StateBacking`] (async trait)   |
//! | `InMemoryPersonaStateBacking`               | [`InMemoryStateBacking`]         |
//! | `NatsKvPersonaStateBackingAsync`            | [`NatsKvStateBacking`]           |
//! | `snapshot_to_jcs_bytes(snap)`               | [`snapshot_to_jcs_bytes`]        |
//! | `snapshot_payload_sha256(snap)`             | [`snapshot_payload_sha256`]      |
//! | `snapshot_from_jcs_bytes(blob)`             | [`snapshot_from_jcs_bytes`]      |
//! | `STATE_PACK_KEY_PREFIX = "state-pack"`      | [`STATE_PACK_KEY_PREFIX`]        |
//! | `OFFSET_KEY_WIDTH = 20`                     | [`OFFSET_KEY_WIDTH`]             |
//! | `PINNED_KEY = ".../__pinned__"`             | [`PINNED_KEY`]                   |
//! | `NEXT_OFFSET_KEY = ".../__next_offset__"`   | [`NEXT_OFFSET_KEY`]              |
//! | `LATEST_KEY = ".../latest"`                 | [`LATEST_KEY`]                   |
//! | `offset_key(off)`                           | [`offset_key`]                   |
//! | `offset_from_key(k)`                        | [`offset_from_key`]              |
//!
//! # Watch-Revisions extension (Sprint-Auftrag surface)
//!
//! The Python trait declares four operations
//! (`snapshot / restore_latest / list_snapshots /
//! atomic_swap_pinned_offset`). The Sprint-Auftrag adds a fifth op
//! [`StateBacking::watch_revisions`] — a NATS-KV-native revision
//! stream emitting [`RevisionEvent`] items as new snapshots land.
//! The Python pendant is the `nats-py KeyValue.watch()` async
//! iterator (used today only by the v0.2.0-pilot WAT-anchor-pipeline
//! observer). The Rust trait declares the surface; the in-memory
//! binding implements it via a `tokio::sync::mpsc::Receiver`. The
//! NATS-KV-live binding implementation follows in the Phase-3a
//! live-binding step.
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 6 (this crate).
//! - Selin PR #65   (Sprint-Pengine-8) — Python schema authority.
//! - Selin PR #113  (3-way-triangle)   — Doppelbetrieb substrate.
//! - Selin PR #131  (bridge-diff-rust) — sibling crate.
//! - Reza  PR #132  (subscribe-loop-rust) — sibling crate (async-nats
//!   version precedent).
//! - Selin PR #135  (recovery-rust)    — sibling crate (Tokio version
//!   precedent).
//! - Selin PR #136  (v907-verify-rust) — sibling crate.
//! - persona-engine-format-spec §3.7.5  — state-backing trait contract.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::sync::{mpsc, Mutex};

// ---------------------------------------------------------------------------
// Spec §3.7.5.4 — state-pack KV key layout (byte-parity with Python).
// ---------------------------------------------------------------------------

/// Top-level prefix for all persona-state-bucket keys.
///
/// Parity with Python `STATE_PACK_KEY_PREFIX = "state-pack"`.
pub const STATE_PACK_KEY_PREFIX: &str = "state-pack";

/// Width of the zero-padded offset segment. 20 decimal digits gives
/// 10^20 snapshots per persona — well above any plausible single-
/// persona lifetime — and makes the natural NATS-KV listing order
/// match numeric offset order.
///
/// Parity with Python `OFFSET_KEY_WIDTH = 20`.
pub const OFFSET_KEY_WIDTH: usize = 20;

/// Sentinel key: pointer to the currently-pinned snapshot offset.
/// Used by spec §3.7.3 migrate-version mechanic.
///
/// Parity with Python `PINNED_KEY = f"{STATE_PACK_KEY_PREFIX}/__pinned__"`.
pub const PINNED_KEY: &str = "state-pack/__pinned__";

/// Sentinel key: monotonic counter for new snapshots; compare-and-swap
/// on write in the NATS-KV binding.
///
/// Parity with Python
/// `NEXT_OFFSET_KEY = f"{STATE_PACK_KEY_PREFIX}/__next_offset__"`.
pub const NEXT_OFFSET_KEY: &str = "state-pack/__next_offset__";

/// Sentinel key: pointer to the highest-offset snapshot key.
///
/// Parity with Python `LATEST_KEY = f"{STATE_PACK_KEY_PREFIX}/latest"`.
pub const LATEST_KEY: &str = "state-pack/latest";

/// Render a per-offset snapshot key. Zero-padded to
/// [`OFFSET_KEY_WIDTH`] digits so NATS-KV `keys()` listing order
/// matches numeric offset order.
///
/// Parity with Python
/// `f"{STATE_PACK_KEY_PREFIX}/{offset:0{OFFSET_KEY_WIDTH}d}"`.
///
/// # Errors
///
/// Returns [`StateBackingError::InvalidOffset`] for negative
/// offsets. (The Rust type system narrows the input to `u64` so
/// the error path is structurally unreachable from typed callers,
/// but the function exists as a parity surface for the Python
/// `ValueError` raised by `offset_key(-1)`.)
pub fn offset_key(offset: u64) -> String {
    // u64 cannot be negative; the format-with-padding is the parity-
    // relevant operation. Width 20 covers up to u64::MAX (~1.8e19,
    // 20 decimal digits).
    format!("{}/{:0width$}", STATE_PACK_KEY_PREFIX, offset, width = OFFSET_KEY_WIDTH)
}

/// Inverse of [`offset_key`]. Returns `Err` for malformed input
/// (sentinel keys, foreign prefixes, non-numeric suffixes).
///
/// Parity with Python `offset_from_key(k)` raising `ValueError`.
pub fn offset_from_key(key: &str) -> Result<u64, StateBackingError> {
    let prefix = format!("{}/", STATE_PACK_KEY_PREFIX);
    let suffix = key.strip_prefix(&prefix).ok_or_else(|| {
        StateBackingError::InvalidKey(format!("not a state-pack key: {key:?}"))
    })?;
    if !suffix.chars().all(|c| c.is_ascii_digit()) {
        return Err(StateBackingError::InvalidKey(format!(
            "sentinel key, not an offset: {key:?}"
        )));
    }
    suffix.parse::<u64>().map_err(|e| {
        StateBackingError::InvalidKey(format!("offset parse failed for {key:?}: {e}"))
    })
}

// ---------------------------------------------------------------------------
// Spec §3.7.5.2 — snapshot envelope (byte-parity with Python dataclass).
// ---------------------------------------------------------------------------

/// Spec §3.7.5.2 snapshot envelope. Five fields, byte-stable under
/// JCS canonicalisation (alphabetical key order, no insignificant
/// whitespace, RFC 3339 UTC second-precision timestamp).
///
/// Parity with Python `@dataclass(frozen=True)
/// class PersonaStateSnapshot`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PersonaStateSnapshot {
    /// Persona-Hash identifier in `"sha256:<64hex>"` form.
    pub persona_hash: String,

    /// Monotonic audit-trace offset (per-persona). Zero-based; the
    /// first snapshot returns offset `1` from `snapshot()`.
    pub audit_trace_offset: u64,

    /// Ordered list of capability-token IDs active in this snapshot.
    /// Order is the canonical capability-token creation order; the
    /// JCS canonicaliser MUST NOT re-sort.
    pub capability_token_ids: Vec<String>,

    /// Snapshot wall-clock timestamp, RFC 3339 UTC second-precision,
    /// e.g. `"2026-05-15T14:30:00Z"`.
    pub snapshot_at_utc: String,

    /// SHA-256 of the workspace-state bytes in `"sha256:<64hex>"` form.
    pub workspace_state_hash: String,
}

/// JCS-canonicalise a snapshot to a byte-stable form. Mirrors the
/// Python stdlib-only implementation in `snapshot_to_jcs_bytes`:
/// alphabetical key order (via [`BTreeMap`]), no extra whitespace,
/// UTF-8 output. Capability-token-id list rendered as a JSON array
/// preserving insertion order.
///
/// Byte-equality with Python is asserted at the 3-way-triangle
/// boundary (Selin PR #113); the smoke-tests in this crate include
/// a golden-vector regression test against the byte string emitted
/// by the Python reference.
pub fn snapshot_to_jcs_bytes(snap: &PersonaStateSnapshot) -> Vec<u8> {
    // Use serde_json with sorted keys via BTreeMap construction.
    // Python uses `json.dumps(..., sort_keys=True, separators=(",", ":"))`;
    // the equivalent in serde_json is the default compact format with
    // the keys placed in lexicographic order via BTreeMap.
    let mut canonical: BTreeMap<&str, serde_json::Value> = BTreeMap::new();
    canonical.insert(
        "audit_trace_offset",
        serde_json::Value::Number(snap.audit_trace_offset.into()),
    );
    canonical.insert(
        "capability_token_ids",
        serde_json::Value::Array(
            snap.capability_token_ids
                .iter()
                .map(|s| serde_json::Value::String(s.clone()))
                .collect(),
        ),
    );
    canonical.insert(
        "persona_hash",
        serde_json::Value::String(snap.persona_hash.clone()),
    );
    canonical.insert(
        "snapshot_at_utc",
        serde_json::Value::String(snap.snapshot_at_utc.clone()),
    );
    canonical.insert(
        "workspace_state_hash",
        serde_json::Value::String(snap.workspace_state_hash.clone()),
    );
    // serde_json::to_vec on a BTreeMap emits keys in iteration order
    // (which BTreeMap provides as lexicographic). Compact format
    // (no whitespace) matches Python `separators=(",", ":")`.
    serde_json::to_vec(&canonical)
        .expect("snapshot_to_jcs_bytes: BTreeMap<&str, Value> always serialises")
}

/// SHA-256 of the JCS-canonical bytes, prefixed with `"sha256:"`
/// and rendered as lower-case hex (matching Python
/// `hashlib.sha256().hexdigest()` shape).
///
/// Parity with Python `snapshot_payload_sha256`.
pub fn snapshot_payload_sha256(snap: &PersonaStateSnapshot) -> String {
    let bytes = snapshot_to_jcs_bytes(snap);
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    format!("sha256:{}", hex::encode(digest))
}

/// Inverse of [`snapshot_to_jcs_bytes`]. Returns
/// [`StateBackingError::CorruptSnapshot`] on malformed input
/// (missing keys, wrong types, invalid UTF-8).
///
/// Parity with Python `snapshot_from_jcs_bytes` raising `ValueError`.
pub fn snapshot_from_jcs_bytes(blob: &[u8]) -> Result<PersonaStateSnapshot, StateBackingError> {
    let obj: serde_json::Value = serde_json::from_slice(blob)
        .map_err(|e| StateBackingError::CorruptSnapshot(format!("JSON parse failed: {e}")))?;
    let map = obj
        .as_object()
        .ok_or_else(|| StateBackingError::CorruptSnapshot("snapshot is not a JSON object".into()))?;
    // Required-keys check (parity with Python `required - set(obj.keys())`).
    for required in [
        "audit_trace_offset",
        "capability_token_ids",
        "persona_hash",
        "snapshot_at_utc",
        "workspace_state_hash",
    ] {
        if !map.contains_key(required) {
            return Err(StateBackingError::CorruptSnapshot(format!(
                "snapshot JCS payload missing key: {required:?}"
            )));
        }
    }
    let persona_hash = map["persona_hash"]
        .as_str()
        .ok_or_else(|| StateBackingError::CorruptSnapshot("persona_hash not string".into()))?
        .to_string();
    let audit_trace_offset = map["audit_trace_offset"]
        .as_u64()
        .ok_or_else(|| StateBackingError::CorruptSnapshot("audit_trace_offset not u64".into()))?;
    let capability_token_ids = map["capability_token_ids"]
        .as_array()
        .ok_or_else(|| {
            StateBackingError::CorruptSnapshot("capability_token_ids not array".into())
        })?
        .iter()
        .map(|v| {
            v.as_str()
                .map(|s| s.to_string())
                .ok_or_else(|| {
                    StateBackingError::CorruptSnapshot(
                        "capability_token_ids element not string".into(),
                    )
                })
        })
        .collect::<Result<Vec<_>, _>>()?;
    let snapshot_at_utc = map["snapshot_at_utc"]
        .as_str()
        .ok_or_else(|| StateBackingError::CorruptSnapshot("snapshot_at_utc not string".into()))?
        .to_string();
    let workspace_state_hash = map["workspace_state_hash"]
        .as_str()
        .ok_or_else(|| {
            StateBackingError::CorruptSnapshot("workspace_state_hash not string".into())
        })?
        .to_string();
    Ok(PersonaStateSnapshot {
        persona_hash,
        audit_trace_offset,
        capability_token_ids,
        snapshot_at_utc,
        workspace_state_hash,
    })
}

// ---------------------------------------------------------------------------
// Error surface — parity with Python PersonaStateBackingError.
// ---------------------------------------------------------------------------

/// Errors raised by any [`StateBacking`] implementation.
///
/// Parity with Python `PersonaStateBackingError(RuntimeError)`. The
/// Rust variant taxonomy is finer-grained than the Python single-
/// type surface (which is `RuntimeError`-derived with a string
/// message); the Python message string maps onto the matching Rust
/// variant's `String` payload.
#[derive(Debug)]
pub enum StateBackingError {
    /// Atomic-swap pre-condition failed: the current pinned offset
    /// does not equal the caller-supplied `from_offset`. Mirrors the
    /// Python message `"atomic_swap_pinned_offset(...): expected
    /// from_offset=X, current pinned offset=Y"`.
    CasFailed(String),

    /// Atomic-swap referenced an offset not present in this persona's
    /// snapshot list. Mirrors the Python message
    /// `"atomic_swap_pinned_offset(...): to_offset=X not in known
    /// snapshots [...]"`.
    UnknownOffset(String),

    /// Malformed key (sentinel, foreign prefix, non-numeric suffix).
    InvalidKey(String),

    /// `offset_key()` called with a value the parity-surface flagged
    /// as invalid. Structurally unreachable from typed Rust callers
    /// (the input is `u64`); preserved as a parity surface for the
    /// Python `ValueError`.
    InvalidOffset(String),

    /// `snapshot_from_jcs_bytes()` received a malformed payload
    /// (missing keys, wrong types, invalid UTF-8/JSON).
    CorruptSnapshot(String),

    /// NATS-KV wire-level error. Used by [`NatsKvStateBacking`] when
    /// the Phase-3a live-binding step is wired up. Smoke-tests do
    /// not produce this variant.
    NatsKv(String),

    /// Watch-revisions stream was dropped or never started.
    WatchStream(String),
}

impl std::fmt::Display for StateBackingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StateBackingError::CasFailed(msg) => write!(f, "compare-and-swap failed: {msg}"),
            StateBackingError::UnknownOffset(msg) => write!(f, "offset not known: {msg}"),
            StateBackingError::InvalidKey(msg) => write!(f, "invalid key: {msg}"),
            StateBackingError::InvalidOffset(msg) => write!(f, "invalid offset: {msg}"),
            StateBackingError::CorruptSnapshot(msg) => write!(f, "corrupt snapshot: {msg}"),
            StateBackingError::NatsKv(msg) => write!(f, "nats-kv error: {msg}"),
            StateBackingError::WatchStream(msg) => write!(f, "watch stream error: {msg}"),
        }
    }
}

impl std::error::Error for StateBackingError {}

// ---------------------------------------------------------------------------
// Watch-Revisions surface (Sprint-Auftrag fifth op).
// ---------------------------------------------------------------------------

/// Event emitted by [`StateBacking::watch_revisions`] when a new
/// snapshot lands in the per-persona bucket. The Rust trait surface
/// extends the Python four-op trait with this fifth op; the Python
/// pendant is the `nats-py KeyValue.watch()` async iterator.
///
/// Two variants:
///
/// - [`RevisionEvent::Snapshot`] — a new per-offset key was written.
///   The payload carries the new offset and the decoded snapshot
///   envelope.
/// - [`RevisionEvent::Pinned`] — the `state-pack/__pinned__` sentinel
///   changed (typically via [`StateBacking::atomic_swap_pinned_offset`]).
///
/// Other sentinel-key writes (`__next_offset__`, `latest`) are
/// internal bookkeeping and do not surface as revision events —
/// the consumer reasons about offsets via the [`Snapshot`] variant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RevisionEvent {
    /// A new per-offset snapshot was written.
    Snapshot {
        /// The audit-trace offset of the new snapshot.
        offset: u64,
        /// The decoded snapshot envelope.
        snapshot: PersonaStateSnapshot,
    },
    /// The pinned offset was updated.
    Pinned {
        /// The new pinned offset.
        offset: u64,
    },
}

// ---------------------------------------------------------------------------
// Async trait surface — parity with Python PersonaStateBackingAsync.
// ---------------------------------------------------------------------------

/// Type alias for the boxed async future returned by trait methods.
/// We avoid `async fn` in trait position so the crate stays on
/// stable Rust 1.85 without the `async-trait` macro (the Python
/// reference has no analogous mechanism; this is purely a Rust-
/// language ergonomics choice).
pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Abstract persona-state-backing trait. Async (mirrors Python
/// `PersonaStateBackingAsync`). Concrete bindings: [`InMemoryStateBacking`]
/// for hermetic tests + pre-NATS-init engine boot, and
/// [`NatsKvStateBacking`] for production.
///
/// Five operations:
///
/// 1. [`snapshot`](StateBacking::snapshot) — persist a snapshot,
///    return its assigned offset. Idempotent: byte-equal latest
///    snapshot returns the existing offset (no new write).
/// 2. [`restore_latest`](StateBacking::restore_latest) — return the
///    latest snapshot or `None` on cold start.
/// 3. [`list_snapshots`](StateBacking::list_snapshots) — return all
///    snapshot offsets, oldest first.
/// 4. [`atomic_swap_pinned_offset`](StateBacking::atomic_swap_pinned_offset)
///    — CAS-update the pinned offset. Used by spec §3.7.3
///    migrate-version mechanic.
/// 5. [`watch_revisions`](StateBacking::watch_revisions) — open a
///    revision-event stream for the persona's bucket. Sprint-Auftrag
///    fifth op; Python pendant is `nats-py KeyValue.watch()`.
pub trait StateBacking: Send + Sync {
    /// Persist `state` and return its new `audit_trace_offset`.
    ///
    /// Idempotent: re-snapshotting a byte-equal state returns the
    /// existing offset (no new write).
    fn snapshot<'a>(
        &'a self,
        persona_id: &'a str,
        state: PersonaStateSnapshot,
    ) -> BoxFuture<'a, Result<u64, StateBackingError>>;

    /// Return the latest snapshot for `persona_id` or `None` (cold
    /// start). Parity with Python `restore_latest`.
    fn restore_latest<'a>(
        &'a self,
        persona_id: &'a str,
    ) -> BoxFuture<'a, Result<Option<PersonaStateSnapshot>, StateBackingError>>;

    /// Return all snapshot offsets for `persona_id`, oldest first.
    /// Parity with Python `list_snapshots`.
    fn list_snapshots<'a>(
        &'a self,
        persona_id: &'a str,
    ) -> BoxFuture<'a, Result<Vec<u64>, StateBackingError>>;

    /// Atomically swap the pinned offset. Pre-condition: the current
    /// pinned offset must equal `from_offset` (or be unset, in which
    /// case `from_offset` is ignored — matching Python's
    /// `current is not None and current != from_offset` guard).
    ///
    /// Parity with Python `atomic_swap_pinned_offset`.
    fn atomic_swap_pinned_offset<'a>(
        &'a self,
        persona_id: &'a str,
        from_offset: u64,
        to_offset: u64,
    ) -> BoxFuture<'a, Result<(), StateBackingError>>;

    /// Open a revision-event stream for `persona_id`. Returns a
    /// `tokio::sync::mpsc::Receiver` that emits [`RevisionEvent`]
    /// items as new snapshots / pinned-offset updates land.
    ///
    /// The receiver buffer-size is `buffer` (8 is a safe default
    /// for low-volume operator-facing observers; tune up for the
    /// WAT-anchor-pipeline observer).
    ///
    /// Sprint-Auftrag fifth op. Python pendant: `nats-py
    /// KeyValue.watch()` async iterator.
    fn watch_revisions<'a>(
        &'a self,
        persona_id: &'a str,
        buffer: usize,
    ) -> BoxFuture<'a, Result<mpsc::Receiver<RevisionEvent>, StateBackingError>>;
}

// ---------------------------------------------------------------------------
// InMemoryStateBacking — hermetic-test binding.
// ---------------------------------------------------------------------------

/// Per-persona state (HashMap-equivalent shape to Python
/// `InMemoryPersonaStateBacking`). Held under a single
/// `tokio::sync::Mutex` per backing instance.
#[derive(Debug, Default)]
struct InMemoryPersonaState {
    /// Ordered list of `(offset, snapshot)` pairs. Insertion order
    /// matches snapshot-creation order, which matches offset order.
    entries: Vec<(u64, PersonaStateSnapshot)>,
    /// Pinned offset (None until first pin).
    pinned: Option<u64>,
    /// Last offset assigned (monotonic per persona).
    next_offset: u64,
    /// Active watch-revision channels for this persona. Each
    /// `mpsc::Sender` is held weakly via clone; closed receivers
    /// are pruned on the next `snapshot()` call.
    watchers: Vec<mpsc::Sender<RevisionEvent>>,
}

/// In-memory persona-state-backing. Pure-stdlib + Tokio; suitable
/// for hermetic tests and for pre-NATS-init engine-boot fallback
/// (parity with Python `InMemoryPersonaStateBacking`).
///
/// Per-persona single-writer: callers MUST NOT spawn parallel
/// `snapshot` calls for the same `persona_id`. Cross-persona
/// operations are independent (different keys in the underlying
/// map). The per-persona offset counter is serialised under a
/// per-backing `Mutex` — sufficient for the single-writer-per-
/// persona contract.
#[derive(Debug, Default)]
pub struct InMemoryStateBacking {
    state: Mutex<BTreeMap<String, InMemoryPersonaState>>,
}

impl InMemoryStateBacking {
    /// Construct an empty in-memory backing.
    pub fn new() -> Self {
        Self {
            state: Mutex::new(BTreeMap::new()),
        }
    }

    /// Convenience read accessor used by smoke tests (no spec
    /// equivalent; parity with Python `get_pinned`).
    pub async fn get_pinned(&self, persona_id: &str) -> Option<u64> {
        let state = self.state.lock().await;
        state.get(persona_id).and_then(|p| p.pinned)
    }
}

impl StateBacking for InMemoryStateBacking {
    fn snapshot<'a>(
        &'a self,
        persona_id: &'a str,
        state: PersonaStateSnapshot,
    ) -> BoxFuture<'a, Result<u64, StateBackingError>> {
        Box::pin(async move {
            let mut guard = self.state.lock().await;
            let entry = guard.entry(persona_id.to_string()).or_default();
            // Idempotence: byte-equal latest snapshot -> return its offset.
            if let Some((latest_offset, latest_snap)) = entry.entries.last() {
                if snapshot_to_jcs_bytes(latest_snap) == snapshot_to_jcs_bytes(&state) {
                    return Ok(*latest_offset);
                }
            }
            entry.next_offset += 1;
            let new_offset = entry.next_offset;
            entry.entries.push((new_offset, state.clone()));
            // Fan-out to watchers; prune closed ones.
            let event = RevisionEvent::Snapshot {
                offset: new_offset,
                snapshot: state,
            };
            entry.watchers.retain(|tx| !tx.is_closed());
            for tx in &entry.watchers {
                // try_send: full buffer drops the event for this
                // watcher (consistent with NATS-KV slow-consumer
                // semantics). This is a smoke-test binding; the
                // production binding maps NATS-KV slow-consumer to
                // a `WatchStream` error.
                let _ = tx.try_send(event.clone());
            }
            Ok(new_offset)
        })
    }

    fn restore_latest<'a>(
        &'a self,
        persona_id: &'a str,
    ) -> BoxFuture<'a, Result<Option<PersonaStateSnapshot>, StateBackingError>> {
        Box::pin(async move {
            let guard = self.state.lock().await;
            Ok(guard
                .get(persona_id)
                .and_then(|p| p.entries.last())
                .map(|(_, snap)| snap.clone()))
        })
    }

    fn list_snapshots<'a>(
        &'a self,
        persona_id: &'a str,
    ) -> BoxFuture<'a, Result<Vec<u64>, StateBackingError>> {
        Box::pin(async move {
            let guard = self.state.lock().await;
            Ok(guard
                .get(persona_id)
                .map(|p| p.entries.iter().map(|(off, _)| *off).collect())
                .unwrap_or_default())
        })
    }

    fn atomic_swap_pinned_offset<'a>(
        &'a self,
        persona_id: &'a str,
        from_offset: u64,
        to_offset: u64,
    ) -> BoxFuture<'a, Result<(), StateBackingError>> {
        Box::pin(async move {
            let mut guard = self.state.lock().await;
            let entry = guard.entry(persona_id.to_string()).or_default();
            if let Some(current) = entry.pinned {
                if current != from_offset {
                    return Err(StateBackingError::CasFailed(format!(
                        "atomic_swap_pinned_offset({persona_id:?}): \
                         expected from_offset={from_offset}, current pinned offset={current}"
                    )));
                }
            }
            let offsets: Vec<u64> = entry.entries.iter().map(|(off, _)| *off).collect();
            if !offsets.contains(&to_offset) {
                return Err(StateBackingError::UnknownOffset(format!(
                    "atomic_swap_pinned_offset({persona_id:?}): \
                     to_offset={to_offset} not in known snapshots {offsets:?}"
                )));
            }
            entry.pinned = Some(to_offset);
            // Fan-out Pinned event to watchers.
            let event = RevisionEvent::Pinned { offset: to_offset };
            entry.watchers.retain(|tx| !tx.is_closed());
            for tx in &entry.watchers {
                let _ = tx.try_send(event.clone());
            }
            Ok(())
        })
    }

    fn watch_revisions<'a>(
        &'a self,
        persona_id: &'a str,
        buffer: usize,
    ) -> BoxFuture<'a, Result<mpsc::Receiver<RevisionEvent>, StateBackingError>> {
        Box::pin(async move {
            let mut guard = self.state.lock().await;
            let entry = guard.entry(persona_id.to_string()).or_default();
            let (tx, rx) = mpsc::channel(buffer.max(1));
            entry.watchers.push(tx);
            Ok(rx)
        })
    }
}

// ---------------------------------------------------------------------------
// NatsKvStateBacking — production binding stub (Phase-3a live-binding TODO).
// ---------------------------------------------------------------------------

/// Production NATS-KV persona-state-backing.
///
/// **Scaffold stub** — this crate declares the type-level surface
/// and pulls in `async-nats =0.48.0` as a compile-dep so the
/// Phase-3a live-binding follow-up can extend without re-deciding
/// the client. The five [`StateBacking`] trait methods return
/// [`StateBackingError::NatsKv`] with a `not-yet-bound` message
/// today; smoke-tests do not exercise this binding.
///
/// Parity with Python `NatsKvPersonaStateBackingAsync` (the full
/// connect/CAS/`KeyValue.watch()` wire-level binding lives in the
/// Python module today; the Rust binding will follow the same
/// shape).
///
/// # Field semantics
///
/// - `nats_servers` — comma-separated NATS server URLs (e.g.
///   `"nats://localhost:4222"`). Same string format as the Python
///   `nats.connect()` argument.
/// - `org_id` — multi-tenant org identifier; combined with
///   `persona_id` to compute the bucket name via the Python
///   `wirelang.persona.persona_state_kv.bucket_name_for_pair(org_id,
///   persona_id)` (Rust port pending in the live-binding step).
/// - `connect_timeout` — NATS-connect timeout in seconds.
pub struct NatsKvStateBacking {
    /// Comma-separated NATS server URLs.
    pub nats_servers: String,
    /// Multi-tenant org identifier (for bucket-name computation).
    pub org_id: String,
    /// NATS-connect timeout, seconds.
    pub connect_timeout_sec: f64,
    /// Cached client handle (constructed lazily on first call in
    /// the live-binding step). `Arc<Mutex<>>` for the future
    /// connection-owning lifecycle; not exercised today.
    _client: Arc<Mutex<Option<async_nats::Client>>>,
}

impl std::fmt::Debug for NatsKvStateBacking {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NatsKvStateBacking")
            .field("nats_servers", &self.nats_servers)
            .field("org_id", &self.org_id)
            .field("connect_timeout_sec", &self.connect_timeout_sec)
            .field("_client", &"<async-nats client handle>")
            .finish()
    }
}

impl NatsKvStateBacking {
    /// Construct a new scaffold binding. Does not open a NATS
    /// connection; the live-binding step will add a `connect()`
    /// method following the Python pattern.
    pub fn new(nats_servers: impl Into<String>, org_id: impl Into<String>) -> Self {
        Self {
            nats_servers: nats_servers.into(),
            org_id: org_id.into(),
            connect_timeout_sec: 5.0,
            _client: Arc::new(Mutex::new(None)),
        }
    }

    /// Override the default connect timeout (parity with Python
    /// `connect_timeout_sec` kwarg).
    pub fn with_connect_timeout(mut self, sec: f64) -> Self {
        self.connect_timeout_sec = sec;
        self
    }

    /// Compute the per-persona bucket name. Today returns the
    /// canonical `wakir-persona-state-<org_id>-<persona_id>` shape
    /// matching the Python `bucket_name_for_pair(org_id, persona_id)`
    /// helper. The live-binding step will reconcile against the
    /// canonical Python implementation byte-for-byte.
    pub fn bucket_name(&self, persona_id: &str) -> String {
        format!("wakir-persona-state-{}-{}", self.org_id, persona_id)
    }
}

impl StateBacking for NatsKvStateBacking {
    fn snapshot<'a>(
        &'a self,
        _persona_id: &'a str,
        _state: PersonaStateSnapshot,
    ) -> BoxFuture<'a, Result<u64, StateBackingError>> {
        Box::pin(async move {
            Err(StateBackingError::NatsKv(
                "NatsKvStateBacking::snapshot: live NATS-KV binding not bound yet \
                 (Phase-3a live-binding step pending). Use InMemoryStateBacking \
                 for hermetic tests."
                    .into(),
            ))
        })
    }

    fn restore_latest<'a>(
        &'a self,
        _persona_id: &'a str,
    ) -> BoxFuture<'a, Result<Option<PersonaStateSnapshot>, StateBackingError>> {
        Box::pin(async move {
            Err(StateBackingError::NatsKv(
                "NatsKvStateBacking::restore_latest: live NATS-KV binding not bound yet \
                 (Phase-3a live-binding step pending)."
                    .into(),
            ))
        })
    }

    fn list_snapshots<'a>(
        &'a self,
        _persona_id: &'a str,
    ) -> BoxFuture<'a, Result<Vec<u64>, StateBackingError>> {
        Box::pin(async move {
            Err(StateBackingError::NatsKv(
                "NatsKvStateBacking::list_snapshots: live NATS-KV binding not bound yet \
                 (Phase-3a live-binding step pending)."
                    .into(),
            ))
        })
    }

    fn atomic_swap_pinned_offset<'a>(
        &'a self,
        _persona_id: &'a str,
        _from_offset: u64,
        _to_offset: u64,
    ) -> BoxFuture<'a, Result<(), StateBackingError>> {
        Box::pin(async move {
            Err(StateBackingError::NatsKv(
                "NatsKvStateBacking::atomic_swap_pinned_offset: live NATS-KV binding \
                 not bound yet (Phase-3a live-binding step pending)."
                    .into(),
            ))
        })
    }

    fn watch_revisions<'a>(
        &'a self,
        _persona_id: &'a str,
        _buffer: usize,
    ) -> BoxFuture<'a, Result<mpsc::Receiver<RevisionEvent>, StateBackingError>> {
        Box::pin(async move {
            Err(StateBackingError::NatsKv(
                "NatsKvStateBacking::watch_revisions: live NATS-KV binding not bound yet \
                 (Phase-3a live-binding step pending). Use InMemoryStateBacking::watch_revisions \
                 for hermetic tests."
                    .into(),
            ))
        })
    }
}

// ---------------------------------------------------------------------------
// Unit tests — pure-doc-helper-fn tests; smoke tests live in tests/.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod unit_tests {
    use super::*;

    #[test]
    fn offset_key_zero_padded_to_20_digits() {
        assert_eq!(offset_key(0), "state-pack/00000000000000000000");
        assert_eq!(offset_key(1), "state-pack/00000000000000000001");
        assert_eq!(offset_key(42), "state-pack/00000000000000000042");
    }

    #[test]
    fn offset_key_round_trip() {
        for off in [0u64, 1, 42, 999_999, u64::MAX] {
            let key = offset_key(off);
            assert_eq!(offset_from_key(&key).unwrap(), off);
        }
    }

    #[test]
    fn offset_from_key_rejects_sentinel_keys() {
        assert!(offset_from_key(PINNED_KEY).is_err());
        assert!(offset_from_key(NEXT_OFFSET_KEY).is_err());
        assert!(offset_from_key(LATEST_KEY).is_err());
    }

    #[test]
    fn offset_from_key_rejects_foreign_prefix() {
        assert!(offset_from_key("foreign/0").is_err());
        assert!(offset_from_key("state-pack").is_err());
    }
}
