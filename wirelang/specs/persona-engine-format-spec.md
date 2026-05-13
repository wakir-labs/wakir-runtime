<!-- SPDX-License-Identifier: CC-BY-4.0 -->

---
spec: persona-engine-format
version: 1.2.0
status: draft
date: 2026-05-13
audience: pengine-eng, persona-authors, hr-slot, container-ops-slot
license: CC-BY-4.0
---

# Persona-Engine-Format Specification (v1.2)

| Field | Value |
|---|---|
| Spec ID | PEF-1 |
| Owner | pengine-eng (ADR-0043) |
| Phase | 1b Sprint-Pengine-7 Tag-3 (2026-05-13) |
| Self-Migration anchor | ADR-0036 (Self-Migration-Konverter) — Sprint-Pengine-7 Tag-2 converter consumes this spec; Tag-3 adds §3.7.3 migrate-version mechanic |
| Companion specs | `persona-hash-spec.md` (V-907), `self-migration-konverter-spec.md`, `persona-schema-v10-migration-vorbereitung.md`, `schema-registry-spec.md` v0.32.0 §10, `recovery-drill-leaf-projection.md` (WAT bridge) |
| Cross-review zones | J (container-bridge spec, container-ops-slot), K (WAT-bridge / V-907 hash integration, wat-eng-slot), L (identity-substrate forward-link, identity-eng-slot), B (NATS-KV × Wirelang, drain protocol), HR (governance-revision, hr-slot) |
| Status of ratification | v1.2: additive-only minor bump on top of v1.1 (HR-slot bedingt-ack 2026-05-13 carries; no governance gate re-opened). §3.7 lifecycle protocols are operator-facing protocols layered over the byte-unchanged JSON envelope. Cross-Review-Zone-B/J/K/L are touched in spec-form only (no impl change, no schema change). |

## Revision history

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-05-13 (AM) | Initial Sprint-Pengine-7 Tag-1 spec (PR #22, `86c9acc`). |
| 1.1.0 | 2026-05-13 (PM) | Tag-2 cut-over: Aisha-HR-Counter-Vorschlag 1 eingearbeitet als `synthesis_default_exceptions` table in §4.3 (cfo + internal-audit `reports_to`/`escalation` → `aufsichtsrat`). Counter-Vorschläge 2 (per-transaction budget cap) and 3 (`identity_pinned_policy_version`) recorded as OI-PEF-7 / OI-PEF-8 (future items, not Tag-2 blockers). |
| 1.2.0 | 2026-05-13 (EVE) | Tag-3 spawn-lifecycle concretisation: new §3.7 lifecycle protocols layered on §3.3 state machine — §3.7.1 `despawn_clean` (four phase-sequential operations P1..P4: NATS-KV drain, capability-token revocation, final marker compose, container stop; idempotence + failure modes), §3.7.2 `recovery_drill` pattern (three failure classes: container crash, NATS bucket lost, SPIRE SVID expired; four acceptance criteria: hash pre/post, audit-trail gap = 0, capability continuity, 30s budget), §3.7.3 `migrate_version` mechanic (trigger conditions, backward-compat guarantees, hash-pin-drift detection, per-instance sequence with rollback window). Bisheriges §3.7 (JSON-Schema) → §3.8. JSON envelope (§3.3 `spawn_lifecycle`, §3.4 `state_persistence`, §3.5 `container_bridge`, §3.6 `migration_metadata`) **byte-unchanged** — Tag-3 adds spec-level operator protocols, not new JSON fields. |

## 0. Purpose and one-paragraph summary

Today the AI-Corp / Wakir Labs runs 13 active personae as
`.claude/agents/<slug>.md` files in the **Claude-Code-Native**
format: a YAML front-matter (`name`, `description`, plus an
optional `tools` or `model` field) followed by a Markdown body.
This format is constrained by the Claude-Code spawner contract
and is not the framework-native format. The Self-Migration
(ADR-0036) target is `wakir.persona/<slug>.json` — a single
JSON document carrying the persona-definition canonical subset,
the persona-engine lifecycle envelope (spawn / despawn / recovery
/ migrate-version), the state-persistence config (NATS-KV bucket
binding), the container-bridge spec, and the V-907 persona-hash
build-step metadata. This specification fixes that target shape
v1.0, fixes the byte-deterministic mapping from
`.claude/agents/*.md`, fixes the JSON-Schema, and fixes the test
vectors against the 13 personae we operate today.

## 1. Format inventory and version axes

The persona-format ecosystem has **three parallel axes**:

| Axis | Versions in flight (Phase-1b Sprint-Pengine-7) | Owner | Anchor |
|---|---|---|---|
| **A. Claude-Code-Native** (input axis, today) | `persona-claude-native` v0 | Claude-Code spawner contract | `.claude/agents/*.md` files |
| **B. V-907 mock canonical subset** (hash-input axis) | `persona-v0` (legacy), `persona-v1` (current), `persona-v2` (next) | pengine-eng (V-907) | `wirelang/schemas/persona-v{0,1,2}.json` |
| **C. Framework-native engine format** (target axis, this spec) | `wakir-persona-v1` (this spec) | pengine-eng (ADR-0043) | `wirelang/schemas/wakir-persona-v1.json` (new in Sprint-Pengine-7 Tag-1) |

Axis A is the **production input** the engine actually finds on
disk today. Axis B is what V-907 pins (the hash-pillar surface).
Axis C is the **wakir-runtime-native target shape** the engine
will spawn from after the Self-Migration cut-over.

Sprint-Pengine-7 Tag-1 ships:
- The `wakir-persona-v1` JSON-Schema (axis C target).
- The byte-deterministic mapping `A → C` (Claude-Native → wakir-persona-v1).
- The V-907 hash-integration: `wakir-persona-v1` documents
  embed the persona-v1 canonical-subset block verbatim, so the
  V-907 hash function is unchanged at the byte level. (This is
  the **load-bearing decision** of Sprint-Pengine-7 Tag-1: the
  framework-native format does not fork V-907; it embeds it.)

## 2. Axis A — Claude-Code-Native input format (`persona-claude-native`)

### 2.1 Shape

A `.claude/agents/<slug>.md` file is a UTF-8 text document with:

```
---
<yaml-frontmatter>
---

<markdown body, free-form, OUT-OF-HASH>
```

The front-matter is a YAML mapping with the following
recognised keys (Phase-1b Sprint-Pengine-7 Tag-1 inventory of
the 13 active personae):

| Key | Required | Type | Notes |
|---|---|---|---|
| `name` | yes | string, slug pattern `^[a-z0-9][a-z0-9-]*$` | Subagent slug (Brand-Guide §9 anonymity) |
| `description` | yes | string | Free-form dispatcher hint (multi-paragraph allowed) |
| `tools` | one of `tools` or `model` | string (comma-separated) OR array of strings | Claude-Code tool allow-list |
| `model` | one of `tools` or `model` | string | Claude-Code model override (e.g. `sonnet`); presence implies "use Claude-Code-default tool set" |

Unknown front-matter keys MUST be preserved through the
mapping (axis A→C is lossless on the front-matter surface).

### 2.2 The hr.md edge case

The `hr` persona (hr-slot) carries `model: sonnet` instead
of a `tools:` key, with the tools-list embedded in the
description text as `(Tools, Werkzeuge, Read, Glob, Grep, Edit,
Write, Bash, WebFetch, WebSearch)`. This shape is **valid
persona-claude-native** under the "one of tools or model" rule
(§2.1). The mapping pipeline (§4) explicitly handles this case:
when `tools` is absent and `model` is present, the resulting
`wakir-persona-v1` document carries `tools: null` (RESERVED) and
a `model_override` field populated from the `model` key.

### 2.3 JSON-Schema for input validation

`wirelang/schemas/persona-claude-native.json` (Sprint-Pengine-7
Tag-1, new). The schema validates the front-matter mapping only;
the Markdown body is not covered.

## 3. Axis C — Framework-native target format (`wakir-persona-v1`)

### 3.1 Top-level structure

A `wakir.persona/<slug>.json` document is a single JSON object
with the following top-level fields:

```json
{
  "schema_version": "wakir-persona-v1",
  "persona_id": "<slug>",
  "canonical_subset": { /* V-907 persona-v1 canonical-subset, verbatim */ },
  "claude_native_source": { /* axis-A surface for round-trip */ },
  "spawn_lifecycle": { /* §3.3 */ },
  "state_persistence": { /* §3.4 */ },
  "container_bridge": { /* §3.5 */ },
  "migration_metadata": { /* §3.6 */ },
  "model_override": null
}
```

### 3.2 `canonical_subset` — V-907 hash-input block (embedded)

The `canonical_subset` object MUST be a valid
`persona-v1` document under `wirelang/schemas/persona-v1.json`
(or `persona-v2` once Sprint-3 Tag-2 ratifies it). This is the
**single source of truth for the V-907 persona-hash**. The
hash of the `wakir-persona-v1` document is defined as:

```
wakir_persona_hash = compute_persona_hash_from_canonical(doc["canonical_subset"])
```

That is, the wakir-persona-v1 document **does not introduce a
new hash function**. The persona-hash pillar (V-907) is
unchanged at the byte level. The framework-native wrapper carries
additional lifecycle / persistence / bridge fields, but those
are **out-of-hash** by V-907 design (mirroring the Markdown body
posture).

### 3.3 `spawn_lifecycle` — engine state-machine envelope

```json
{
  "states": ["uninstantiated", "spawning", "running", "despawning", "recovered", "migrated"],
  "valid_transitions": [
    ["uninstantiated", "spawning"],
    ["spawning", "running"],
    ["spawning", "uninstantiated"],
    ["running", "despawning"],
    ["despawning", "uninstantiated"],
    ["uninstantiated", "recovered"],
    ["recovered", "running"],
    ["running", "migrated"],
    ["migrated", "uninstantiated"]
  ],
  "recovery_policy": {
    "kind": "event-replay",
    "source": "marker-stack-kv-bridge"
  },
  "max_concurrent_instances": 1
}
```

**State semantics** (pengine-eng type-state pattern):

- `uninstantiated`: no live persona instance; engine has only the definition.
- `spawning`: spawn request accepted; resource allocation in flight.
- `running`: instance live, accepting tool calls.
- `despawning`: shutdown initiated; in-flight work allowed to drain.
- `recovered`: replayed from event log post-failure; equivalent to `running` modulo the audit pin (recovery emits an explicit WAT frame).
- `migrated`: schema-version migration in progress; the v_n instance is frozen, the v_{n+1} instance will spawn separately.

The `recovery_policy.source` of `marker-stack-kv-bridge`
(Sprint-8 Tag-4 `wirelang.federation.marker_stack_kv` backend)
binds Recovery to event-replay on the Sprint-8 Tag-3 marker-
composition reducer.

### 3.4 `state_persistence` — NATS-KV bucket binding

```json
{
  "bucket_template": "wakir-persona-state-{persona_id}",
  "value_envelope_schema": "wakir.persona.state-event/1",
  "history": 10,
  "max_value_size_bytes": 65536,
  "storage": "file",
  "replicas": 1,
  "ttl_seconds": 0
}
```

Pattern source: Sprint-8 Tag-4 marker-stack-kv backend
(`wakir-marker-stack-{org_id}`). Sprint-Pengine-7 Tag-1 reserves
the bucket-name family; Sprint-Pengine-7 Tag-4 will land the
backend module (out of Tag-1 scope).

Cross-Review-Zone-B (NATS-KV × Wirelang) **TOUCH**: a new
bucket-name family `wakir-persona-state-{persona_id}` requires
a paired container-ops-slot-side bucket-initialiser update. Triggered as
Zone-K-J-Hybrid follow-up.

### 3.5 `container_bridge` — Zone-J persona-container spec

```json
{
  "image_template": "wakir-persona-{persona_id}:{persona_hash_short}",
  "metadata_labels": {
    "wakir.persona.id": "{persona_id}",
    "wakir.persona.hash": "{persona_hash}",
    "wakir.persona.schema_version": "wakir-persona-v1"
  },
  "env_injection": {
    "WAKIR_PERSONA_ID": "{persona_id}",
    "WAKIR_PERSONA_HASH": "{persona_hash}"
  },
  "cross_review_zone": "J"
}
```

Sprint-Pengine-7 Tag-1 records the **shape** of the Zone-J
contract. The implementation (container-ops-slot-side Quadlet
template) is gated on Zone-J cross-review with container-ops-slot
(mandated by `pengine.md`
§Cross-Review-Zonen).

### 3.6 `migration_metadata` — Self-Migration ADR-0036 surface

```json
{
  "source_axis": "persona-claude-native",
  "source_axis_version": "v0",
  "target_axis": "wakir-persona",
  "target_axis_version": "v1",
  "converter_module": "wirelang_rust::persona_engine_format::map_claude_native_to_wakir_v1",
  "converter_byte_determinism": "JCS-stable; same input bytes → same output bytes",
  "v907_hash_integration": "embedded canonical_subset; hash function unchanged"
}
```

This block tells the Self-Migration-Konverter (ADR-0036) which
chain step produced this document and how to walk it forward
when the engine reaches `wakir-persona-v2`.

### 3.7 Lifecycle protocols (Sprint-Pengine-7 Tag-3, v1.2)

The `spawn_lifecycle` envelope in §3.3 fixes the **state machine**
(six states, nine transitions). §3.7 concretises the three
production-grade operational protocols that drive transitions in
the running engine: clean despawn, recovery drill, and
migrate-version. These protocols are byte-stable surfaces over the
v1.1-byte-unchanged `spawn_lifecycle` block (no JSON shape change
required — the same envelope embeds richer operational meaning).

#### 3.7.1 `despawn_clean` protocol

A despawn is **clean** iff the engine completes all four
phase-ordered operations in the canonical order below, every
phase reaches its terminal status (`drained` / `revoked` /
`composed` / `stopped`), and the engine transitions
`running → despawning → uninstantiated` (§3.3 valid_transitions).
A failure in any phase aborts the protocol and surfaces a
`DespawnDirtyError` per §3.7.1.3.

**§3.7.1.1 Phase order (canonical, four phases).**

| Phase | Operation | Terminal status | Cross-review zone |
|---|---|---|---|
| `P1_drain_nats_kv` | NATS-KV bucket drain: stop accepting new state events on `wakir-persona-state-{persona_id}`; allow in-flight events to commit; close the put-stream; emit final `marker-stack-final-compose` event reducing the persona's marker stack to a terminal `DESPAWN_FINAL` verdict (Sprint-8 Tag-3 reducer surface). | `drained` | B (NATS-KV × Wirelang) |
| `P2_revoke_capability_tokens` | Capability-token revocation: iterate the persona's outstanding capability-token set; emit one `RevokeEvent` per token to the marker-stack with `revocation_reason="persona_despawn"`; await per-event acknowledgement (Sprint-8 Tag-4 NATS-KV-backed `put_marker_stack`). | `revoked` | L (Identity-Substrate) |
| `P3_final_marker_compose` | Marker-stack final compose: run `reduce_marker_stack` (Sprint-8 Tag-3) over the now-frozen event log; persist the resulting `CompositionVerdict` as the **canonical final audit record** at key `wakir-persona-state-{persona_id}/__final__/composition-verdict`; emit a WAT-frame referencing this verdict for the engine-side audit anchor (V-907 hash unchanged). | `composed` | K (WAT-bridge) |
| `P4_container_stop` | Container stop: signal the Quadlet supervisor to stop the persona container (`systemctl --user stop wakir-persona-{persona_id}.service`); await `inactive (dead)` unit state with `Result=success` (or `Result=exit-code` with rc=0 for `SIGTERM`-on-clean-exit semantics); remove the persona-state directory mount handle. | `stopped` | J (container-bridge) |

The protocol is **phase-sequential** (not transactional and not
eventual): the engine MUST NOT begin phase Pₙ₊₁ until phase Pₙ has
returned its terminal status. This serialises the audit trail —
the marker-stack compose at P3 can witness all P2 revoke events
exactly because P2 reaches `revoked` before P3 starts. A
two-phase commit across NATS-KV + WAT + container-supervisor is
deliberately rejected: the underlying systems do not share a
transaction coordinator, and an eventual-consistency window would
permit a despawned container with un-revoked capability tokens
still floating in NATS-KV — exactly the audit-trail-gap §3.7.2
recovery-drill is designed to forbid.

**§3.7.1.2 Idempotence.**

Each phase MUST be idempotent on retry: re-running `P1_drain_nats_kv`
on an already-drained bucket is a no-op returning `drained`; re-running
`P2_revoke_capability_tokens` on an already-revoked token-set raises no
error and returns `revoked` (Sprint-6 Tag-9 `UnrevokeAuditMarker`
extension does not apply at despawn — revocation at despawn is
**terminal**, not narrowable); `P3_final_marker_compose` returns the
same byte-identical `CompositionVerdict` on second-run (Sprint-8 Tag-3
reducer determinism, T-MC-determinism); `P4_container_stop` on an
already-stopped unit is a `systemctl stop` no-op returning `stopped`.

**§3.7.1.3 Failure modes and recovery path.**

| Phase | Failure mode | Engine state | Recovery path |
|---|---|---|---|
| P1 | NATS-KV unreachable | `despawning` (stuck) | Operator retry; do not transition to `uninstantiated`; the persona is in `dirty_despawning`. |
| P1 | Marker-stack-final-compose event rejected (envelope error) | `despawning` (stuck) | Diagnose envelope drift (schema-registry-spec §10); fix and retry P1. |
| P2 | Capability-token enumeration empty (token set lost) | `despawning` | Treat as no-op success (`revoked` terminal). Log `P2_NO_TOKENS` audit annotation. |
| P2 | Per-event acknowledgement timeout | `despawning` (stuck) | Retry once with exponential backoff (1s, 2s, 4s); on third failure raise `DespawnDirtyError{phase=P2, reason=ACK_TIMEOUT}` and require operator manual marker-stack append. |
| P3 | Reducer raises `MarkerCompositionConflictError` | `despawning` (stuck) | The marker stack is logically inconsistent. Do NOT despawn. Surface to operator; despawn is gated on manual marker-stack reconciliation. |
| P4 | Quadlet unit fails to stop within 30s | `despawning` (stuck) | Quadlet-side `SIGKILL` after 30s (Quadlet `TimeoutStopSec=30s`); engine waits for `inactive` regardless of `Result`; emit P4 audit annotation `SIGKILL_FALLBACK`. |

A `DespawnDirtyError` MUST be raised iff any phase fails to reach
its terminal status AND no operator override is in place. The
engine MUST NOT silently transition to `uninstantiated` on a
dirty despawn — the persona remains in `despawning` until the
operator clears the dirt or forces a recovery drill (§3.7.2).

#### 3.7.2 `recovery_drill` pattern

Recovery drills exercise the `uninstantiated → recovered → running`
transition (§3.3 valid_transitions) under controlled failure
injection. Drills are the engine's evidence that recovery is
truly event-replay-driven (per `recovery_policy.kind:
"event-replay"`, §3.3) rather than state-restore-driven.

**§3.7.2.1 What is drilled (three failure classes).**

| Drill ID | Failure injection | Recovery substrate | Frequency |
|---|---|---|---|
| `DRILL_CONTAINER_CRASH` | Quadlet unit `SIGKILL` mid-run (no `SIGTERM` grace period). | Marker-stack-kv replay from last commit; container restart from pinned image. | Weekly (every Mon 02:00 UTC). |
| `DRILL_NATS_BUCKET_LOST` | Per-persona bucket `wakir-persona-state-{persona_id}` deleted (simulates NATS-KV catastrophic loss). | Restore from WAT-anchored snapshot (§5.3 `pin-pack-operator-v1` anchor + last-known marker-stack-kv backup). | Monthly (first Mon 02:00 UTC). |
| `DRILL_SPIRE_SVID_EXPIRED` | SPIFFE workload-API returns expired SVID for the persona's identity-doc binding. | Identity-substrate re-attestation flow (§3.6 forward-link, Reza-Sprint-9 Tag-1 durable-ledger anchor); marker-stack continues unchanged. | Monthly (first Mon 02:30 UTC, 30 min after DRILL_NATS_BUCKET_LOST). |

The three drill classes form a stratified test: `CONTAINER_CRASH`
exercises the engine-runtime layer, `NATS_BUCKET_LOST` exercises
the storage-substrate layer, `SPIRE_SVID_EXPIRED` exercises the
identity layer. A persona that passes all three classes in the
same calendar month has demonstrated end-to-end recovery
across all three substrate layers.

**§3.7.2.2 Acceptance criteria.**

A drill is **passed** iff all four invariants hold post-recovery:

1. **Persona-hash pre/post identical.** The V-907 persona-hash
   (`sha256:<64hex>`) computed against the recovered persona's
   `canonical_subset` block MUST byte-equal the persona-hash
   recorded in the pre-drill operator pin-pack
   (`pin-pack-operator-v1` snapshot). Drift → drill FAILED.
2. **Audit-trail gap = 0.** The marker-stack-kv reducer over the
   post-recovery event log MUST produce a `CompositionVerdict`
   whose `audit_trace` length equals the pre-drill audit_trace
   length (no event lost) AND every entry's
   `wat_anchor_manifest_id` resolves through the WAT bridge
   (Zone K). Drift → drill FAILED.
3. **Capability-token continuity.** Every non-revoked
   capability-token from the pre-drill snapshot MUST verify
   against the post-recovery N3 chain walker (Sprint-2 Tag-5
   surface). Drift → drill FAILED.
4. **Container-state convergence within budget.** The
   `recovered → running` transition MUST complete within 30s of
   the failure injection (`recovery_budget_seconds: 30` in
   `spawn_lifecycle.recovery_policy`, §3.3 implicit; not yet on
   the JSON envelope but enforced operationally). Drift → drill
   FAILED.

A drill that FAILS in any criterion MUST surface a
`RecoveryDrillFailedError` audit annotation, and the persona
MUST NOT receive new live capability-token mints until the
operator manually clears the failure (operator-deliberate gate;
analogous to the Sprint-6 Tag-9 unrevoke flow).

**§3.7.2.3 Drill scheduling and observability.**

Drills are operator-scheduled (Quadlet `OnCalendar=` timers on
the persona-engine-side; the scheduler is out of Tag-3 scope and
is Tag-N+ slot). Each drill emits one structured audit record
to the persona's marker-stack with `event_kind=recovery_drill`
and `outcome ∈ {PASSED, FAILED}`. The Sprint-9 Tag-2 durable
ledger (Reza, in-flight) will anchor drill outcomes into the
WAT merkle tree for cross-org-auditable evidence.

#### 3.7.3 `migrate_version` mechanic

The `migrated` state in §3.3 covers schema-version migration of
the persona-engine format itself: `wakir-persona-v1` →
`wakir-persona-v2` and later. §3.7.3 fixes when migration is
triggered, what backward-compatibility guarantees hold, and how
the Self-Migration-Konverter (ADR-0036) drives the transition.

**§3.7.3.1 Migration trigger conditions.**

A `wakir-persona-vN` → `wakir-persona-v(N+1)` migration is
triggered exactly when **all three** of the following hold:

1. **Spec-bump is major.** `persona-engine-format-spec` minor
   bumps (v1.1 → v1.2) are **additive-only** and require **no
   re-conversion**; persona JSON documents under v1.x remain
   byte-stable across minor bumps. A major bump (v1.x → v2.0)
   indicates a breaking schema axis change.
2. **Hash-input shape changes.** If the `canonical_subset` block
   (§3.2, the V-907 hash-input) gains or loses a field, or the
   field-order or JCS canonicalisation differs, the V-907
   persona-hash drifts and re-conversion is mandatory. Pure-doc
   additions outside `canonical_subset` (e.g., a new
   `spawn_lifecycle` field) MUST NOT trigger re-conversion
   alone — only the operator-side audit-trail records the
   richer envelope.
3. **HR-slot governance ratification.** A migration requires
   explicit HR-slot ratification per Aisha-Cross-Review-Zone
   (HR). No migrate-version transition fires without a paired
   `.claude/agents/<slug>.md` audit annotation.

If conditions (1) AND (2) hold but (3) is missing, the engine
SHALL emit a `MigrateVersionGovernanceGateError` and refuse the
transition.

**§3.7.3.2 Backward-compatibility guarantees.**

For minor bumps (v1.x → v1.y, x < y):

- All v1.x persona JSON documents MUST validate cleanly against
  the v1.y JSON-Schema (`wirelang/schemas/wakir-persona-v1.json`
  remains additive — new optional fields only).
- The V-907 persona-hash function applied to a v1.x document MUST
  produce the same hex digest under v1.x and v1.y (the
  `canonical_subset` shape is byte-stable across minor bumps).
- The Self-Migration-Konverter (ADR-0036) is idempotent on v1.x
  documents under v1.y conversion: input bytes == output bytes
  (the §4.4 stability-under-re-conversion contract extends to
  minor bumps).

For major bumps (v1.x → v2.0):

- v1.x persona JSON documents are **NOT** valid against the v2.0
  JSON-Schema — a forced re-conversion via the
  `persona-migration` crate (V0→V1→V2 chain, Sprint-4 Tag-5
  resolver surface) is mandatory.
- The V-907 persona-hash WILL drift across v1.x → v2.0 (this is
  the documented pin-pack-drift signal for major bumps).
- Pin-pack-drift across a major bump MUST trigger a forced
  re-conversion of all 13+ active personae; the new pin-pack is
  the v2.0 baseline.

**§3.7.3.3 Migration trigger: hash-pin-drift detection.**

The engine detects the need for a re-conversion via the
operator-side `pin-pack-operator-v1` (§5.2):

1. On engine startup, the engine computes the V-907 persona-hash
   for each persona's `canonical_subset` block (`wakir_persona_hash`
   from this crate's public surface).
2. The computed hash is compared against the pinned hash in the
   operator pin-pack.
3. If the hashes match → no migration triggered (normal startup).
4. If the hashes differ AND the spec-version axis matches (same
   v1.x family) → drift is a **bug** (the canonical_subset
   block should be byte-stable across minor bumps); halt
   startup with a `PersonaHashDriftError` for operator
   forensics.
5. If the hashes differ AND the spec-version axis crossed a
   major bump (v1.x → v2.0) → drift is **expected**; trigger
   the Self-Migration-Konverter chain to produce a v2.0
   persona JSON, run all four `despawn_clean` phases (§3.7.1)
   on the v1 instance, then spawn the v2 instance from the
   new persona JSON.

**§3.7.3.4 Per-instance migration sequence.**

A per-persona migrate-version sequence under a major bump (v1 → v2):

```
running (v1)
  → migrated (v1 frozen; v1 instance held until v2 spawn ack)
  → uninstantiated (v1 despawned via §3.7.1 clean despawn)
  → spawning (v2 instance spawned from new persona JSON)
  → running (v2)
```

The `migrated → uninstantiated` transition (§3.3 valid_transitions)
fires only after the v2 instance successfully reaches `running`
— i.e., a **rollback window** is preserved: if the v2 spawn
fails, the engine can resurrect the v1 instance from the
held-frozen state. The rollback window closes at the moment
v2 reaches `running`; at that point the v1 instance is
authoritatively despawned and only v2 receives live traffic.

### 3.8 JSON-Schema for output validation

`wirelang/schemas/wakir-persona-v1.json` (Sprint-Pengine-7
Tag-1, new). Strict — `additionalProperties: false` at every
level.

## 4. Mapping `persona-claude-native` → `wakir-persona-v1`

### 4.1 Byte-determinism contract

The mapping is **byte-deterministic** in the following sense:

- Given the same input file bytes (UTF-8), the mapping produces
  the same `wakir-persona-v1` JSON bytes when serialised via
  JCS (RFC 8785).
- The mapping is **side-effect-free** (no clock, no random, no
  filesystem reads outside the input file).
- The mapping is **input-shape-stable**: front-matter key order
  and tools-list element order are preserved into
  `claude_native_source`; canonical-subset key order is
  CANONICAL_TOP_LEVEL_KEYS order (matches V-907 §2).

### 4.2 Pipeline

```
input bytes (.claude/agents/<slug>.md)
  → split_frontmatter (persona-canonical-form-yaml::split_frontmatter)
  → parse YAML mapping (persona-canonical-form-yaml::parse_frontmatter)
  → validate against persona-claude-native.json
  → extract claude_native_source (front-matter mapping, lossless)
  → derive canonical_subset (synthesise persona-v1 shape from claude-native):
      - name: as-is
      - description: as-is
      - tools: parsed to array (comma-split if string, identity if array, empty if absent)
      - schema_version: "persona-v1" (synthesised)
      - identity_pinned: synthesised defaults block (§4.3)
  → assemble wakir-persona-v1 document (sections 3.2 - 3.6)
  → JCS-canonicalise → output bytes
```

### 4.3 Synthesised identity_pinned block (Sprint-Pengine-7 Tag-1 default)

Because the 13 active personae do not carry an `identity_pinned`
block (axis A is pre-v0), the converter MUST synthesise one.
Sprint-Pengine-7 Tag-1 fixes the synthesis defaults:

```yaml
identity_pinned:
  cross_review_zones: []          # populated from .claude/agents body parse (out of Tag-1 scope; Tag-2 may extract)
  authority:
    push_remote: false             # safe default; persona-specific override via hr-slot ratification
    budget_cap_eur_per_month: 10   # ADR-0001 default cap
    sub_delegation: false          # safe default; only mira / cto / hr override true
  hierarchy:
    reports_to: "mira"             # safe default; CTO-reporting personae override to "cto"
    escalation: "mira"             # safe default
```

Sprint-Pengine-7 Tag-2 will extend the converter to **parse
the Markdown body** for `## Hierarchie` / `## Befugnis-Rahmen`
sections and populate the synthesised defaults with persona-
specific values. Tag-1 ships only the safe-default synthesis;
this is intentionally HR-slot-ratification-pending.

### 4.3.1 `synthesis_default_exceptions` (Aisha-HR Counter-Vorschlag 1, v1.1)

The Aisha-HR cross-review (2026-05-13, bedingt-ack on v1.0) identified
two personae for which the safe-default `reports_to: "mira"` /
`escalation: "mira"` is **inhaltlich incorrect** and must be overridden
in synthesis (before the Tag-2 Markdown-body parser is in place). Both
personae carry an explicit Aufsichtsrat-reporting line in their
`.claude/agents/<slug>.md` body that the engine must honour at Tag-2
cut-over rather than silently default away.

The Tag-2 converter MUST consult this hard-coded exceptions table
before falling back to the safe defaults of §4.3:

| `persona_slug` | `reports_to` | `escalation` | Rationale |
|---|---|---|---|
| `cfo` | `aufsichtsrat` | `aufsichtsrat` | Top-Management gleichrangig zur CEO (`cfo.md` §3 Hierarchie): "Berichtet direkt an Aufsichtsrat für Strategy-ADRs und Hard-Stop, an CEO für operative Bündelung." Daniel Mwangi ist nicht Mira-untergeordnet sondern ein peer; AR-direkt für Strategy + Hard-Stop. |
| `internal-audit` | `aufsichtsrat` | `aufsichtsrat` | Dotted-line zum Aufsichtsrat (`internal-audit.md` §2): "Berichtet direkt an den Aufsichtsrat (Fred). Nicht an die CEO." Henrik Voss ist independent-audit (klassisches Internal-Audit-Modell), nicht CEO-untergeordnet. |

**Semantik:** Diese Tabelle ist eine Hard-Coded Override-Liste im
Konverter (`persona_engine_format::SYNTHESIS_DEFAULT_EXCEPTIONS`). Sie
ist explizit pre-Tag-2-Markdown-body-parse — d.h. die Override gilt
auch wenn der Body-Parser (`OI-PEF-1`) noch nicht implementiert ist.
Sobald `OI-PEF-1` landet, kann diese Tabelle in Datenform aus dem
Body extrahiert werden; bis dahin ist sie die maßgebliche Quelle.

**Wartung:** Wenn eine neue Persona mit Aufsichtsrat-direktem Reporting
geschaffen wird (HR-Domäne, Aisha), MUSS die Tabelle im selben PR
aktualisiert werden (Cross-Review-Gate HR vor Konverter-Run).

### 4.3.2 Open Items (HR-Counter-Vorschläge 2-3, v1.1)

Two HR-counter-proposals are recorded as future-items, NOT Tag-2
blockers, per Aisha-bedingt-ack:

- **OI-PEF-7** — `budget_cap_eur_per_month` adressiert nur eine
  der zwei ADR-0001-Delegationsmatrix-Dimensionen (single-month
  rolling cap; missing: per-transaction cap, ≤ 20 EUR). Two-dimensional
  schema (`budget_cap_eur_per_month` + `budget_cap_eur_per_transaction`)
  to be added in `wakir-persona-v1` v2 (Sprint-Pengine-7 Tag-N+).
- **OI-PEF-8** — `identity_pinned_policy_version` field on the
  `migration_metadata` block (§3.6) to record which default-policy
  version was in effect at conversion time. Enables an HR-audit-sweep
  to recognise which persona-documents were synthesised under older
  defaults (Sprint-Pengine-7 Tag-N+).

### 4.4 Stability under re-conversion

Re-converting an already-converted persona MUST be idempotent
at the byte level on the second pass: if the input is a
`wakir-persona-v1` document, the mapping is the identity
function (returns input bytes unchanged after JCS).

## 5. V-907 persona-hash integration (build-step)

### 5.1 Build-step interface

```rust
pub fn wakir_persona_hash(doc: &WakirPersonaV1) -> String {
    // Delegate to V-907 hash function on the embedded canonical_subset.
    let canonical_bytes = canonical_jcs_bytes(&doc.canonical_subset);
    persona_hash::compute(&canonical_bytes)  // sha256:<64hex>
}
```

### 5.2 Pin-pack inheritance

The 13 active personae produce 13 framework-native documents.
Sprint-Pengine-7 Tag-1 records the **V-907 canonical-subset
pin** for each of the 13 (the `canonical_subset` block of each
wakir-persona-v1 document, hashed via the unchanged V-907
function). These 13 pins extend the V-907 pin-pack at the
operator-side (`pin-pack-operator-v1`); the engine-side pin-pack
(V1..V11 fixtures) is untouched.

### 5.3 Anchor — Zone K with wat-eng-slot (WAT-bridge)

This integration **does not introduce a new hash function**, so
the WAT-bridge frame format is unchanged. Zone K is touched only
in the operator-side pin-pack registry: the new `pin-pack-
operator-v1` is a fresh registry distinct from the engine-side
pin-pack. wat-eng-slot cross-review surfaces:

- Confirm WAT-frame schema is unchanged (no `wakir-persona`
  field in WAT envelopes).
- Acknowledge operator-side pin-pack registry as a new
  derivable artefact (V-907 spec §7.1 Zone K table extension).
- Confirm that operator-side pin re-derivation is a build-step
  function (`cargo run --bin wakir-persona-derive-pin`).

## 6. Test vectors — 13 active personae

### 6.1 Inventory

Sprint-Pengine-7 Tag-1 ships test vectors for the 13 active
personae under
`wirelang-rust/crates/persona-engine-format/tests/fixtures/claude-agents/`:

| Slug | Role | Notes |
|---|---|---|
| `mira` | ceo-slot | tools-list array form; has `Agent` tool |
| `cto` | cto-slot | tools-list array form; has `Agent` tool |
| `hr` | hr-slot | **edge case: no `tools:` key, `model: sonnet`** |
| `cfo` | cfo-slot | tools-list array form |
| `comms` | comms-slot | tools-list array form |
| `internal-audit` | audit-slot | tools-list array form (shorter set) |
| `dev-engineering` | dev-eng-slot (matrix-lead) | tools-list array form |
| `reza` | identity-eng-slot | tools-list array form |
| `kai` | container-ops-slot | tools-list array form |
| `pengine` | pengine-eng-slot | tools-list array form |
| `frontend` | frontend-eng-slot | tools-list array form |
| `qa` | qa-eng-slot | tools-list array form |
| `sre` | sre-slot | tools-list array form |

### 6.2 Validation surface

For each persona, Tag-1 tests assert:

1. **T-PEF-{slug}-A** — `.claude/agents/<slug>.md` parses as valid `persona-claude-native`.
2. **T-PEF-{slug}-B** — `map_claude_native_to_wakir_v1(input)` produces a JSON document that validates against `wakir-persona-v1.json`.
3. **T-PEF-{slug}-C** — re-mapping the output is the identity (idempotence under JCS).
4. **T-PEF-{slug}-D** — `wakir_persona_hash(output)` is byte-stable across two runs.

### 6.3 Aggregate determinism tests

- **T-PEF-DET-01** — JCS round-trip stability across all 13.
- **T-PEF-DET-02** — Hash-set cardinality = 13 (no collisions).
- **T-PEF-EDGE-01** — `hr.md` edge case (`model:` instead of `tools:`) produces a wakir-persona-v1 with `model_override: "sonnet"` and `tools: []`.
- **T-PEF-EDGE-02** — Missing `description` (synthetic fixture) is rejected by `persona-claude-native` schema with code `missing-top-level-key`.
- **T-PEF-EDGE-03** — Unknown front-matter keys (synthetic fixture) are preserved in `claude_native_source` and dropped from `canonical_subset`.

Total Tag-1 test floor: 13 × 4 + 5 = 57 (test-floor; the
implementation may add auxiliary probes).

## 7. Cross-review zones (Sprint-Pengine-7 Tag-1..Tag-3)

| Zone | Partner | Trigger | Tag-1/2 touch | v1.2 Tag-3 touch | Ack required? |
|---|---|---|---|---|---|
| **J** | container-ops-slot | container-bridge spec change | yes — §3.5 specifies image template, labels, env vars | yes — §3.7.1 P4 phase fixes Quadlet `TimeoutStopSec=30s` + `SIGKILL_FALLBACK` semantics for clean despawn | yes, before Sprint-Pengine-7 Tag-4 (container backend implementation) |
| **K** | wat-eng-slot | WAT-frame format / V-907 hash function change | **no functional change** — §5 confirms hash function unchanged, only operator-side pin-pack added | spec-only — §3.7.1 P3 phase emits a WAT-frame referencing the final `CompositionVerdict`; §3.7.2 invariant 1 anchors recovery-drill acceptance on V-907 hash byte-equality | yes, confirmation that no WAT-frame change is needed; §3.7.1 P3 frame is the existing engine-side audit frame, not a new schema |
| **L** | identity-eng-slot | identity_doc_ref forward-link | reserved in §4.3 (synthesised default with safe fallback); §3.x carries no identity-document URI yet | spec-only — §3.7.1 P2 phase consumes the identity-doc binding for capability-token-revocation surface; §3.7.2 DRILL_SPIRE_SVID_EXPIRED exercises the identity layer | not until Sprint-Pengine-7 Tag-3+; v1.2 records the touch as spec-level only (Reza Sprint-9 Tag-2 durable-ledger anchor pairs with §3.7.2.3 drill anchoring) |
| **B** | container-ops-slot (NATS-KV) | NATS-KV bucket-family touch | **TOUCH** in §3.4 (bucket-name family reserved) | **TOUCH** in §3.7.1 P1 phase (drain protocol on `wakir-persona-state-{persona_id}`) and §3.7.2 DRILL_NATS_BUCKET_LOST | yes, before Sprint-Pengine-7 Tag-4 (state-persistence backend module) |
| **HR** | hr-slot | persona-definition governance | v1.0: §4.3 synthesis defaults HR-slot-ratification-pending; v1.1: bedingt-ack 2026-05-13 (Counter-Vorschlag 1 eingearbeitet als §4.3.1 `synthesis_default_exceptions`; Counter-Vorschläge 2-3 als OI-PEF-7/8 registriert) | spec-only — §3.7.3.1 condition (3) makes HR-slot ratification a hard gate on migrate-version transitions | v1.2: no new governance gate opened (additive-only); v1.1 bedingt-ack carries |

## 8. Open items (Sprint-Pengine-7 Tag-1..Tag-3 follow-up)

Tag-3 (v1.2) CONSUMES: OI-PEF-5 (Zone L touch documented at §3.7.1 P2
and §3.7.2 DRILL_SPIRE_SVID_EXPIRED; impl-axis remains Reza-Sprint-9
Tag-2+ slot). Tag-3 (v1.2) ADDS: OI-PEF-9..OI-PEF-12 below.

- **OI-PEF-1** — Markdown-body section extractor for `## Hierarchie` /
  `## Befugnis-Rahmen` so the synthesised `identity_pinned` block
  reflects per-persona facts (Tag-2).
- **OI-PEF-2** — Container-bridge Quadlet template implementation
  (Tag-4, Zone J).
- **OI-PEF-3** — NATS-KV state-persistence backend module
  `wirelang.persona.state_kv` mirroring the Sprint-8 Tag-4
  marker-stack-kv pattern (Tag-4).
- **OI-PEF-4** — Persona-spec-converter CLI binary
  `wakir-persona convert-claude-native --in PATH --out PATH`
  (Tag-2, Sprint-Pengine-7).
- **OI-PEF-5** — Identity-document forward-link URI scheme
  (Zone L, Tag-3+).
- **OI-PEF-6** — `persona-claude-native` schema extension for
  the model-override field (currently inferred at conversion
  time; could be made an explicit schema field).
- **OI-PEF-7** — Two-dimensional budget-cap schema
  (`budget_cap_eur_per_month` + `budget_cap_eur_per_transaction`)
  to reflect both ADR-0001 Delegationsmatrix dimensions. v1.1
  records only the per-month dimension; per-transaction (≤ 20 EUR
  for CEO-Freigrenze) is unrepresented. Aisha-HR-Counter-Vorschlag 2,
  Sprint-Pengine-7 Tag-N+.
- **OI-PEF-8** — `identity_pinned_policy_version` field on the
  `migration_metadata` block (§3.6) to record which default-policy
  version was in effect at conversion time. Enables an HR-audit-sweep
  to recognise which persona-documents were synthesised under
  older defaults. Aisha-HR-Counter-Vorschlag 3, Sprint-Pengine-7
  Tag-N+.
- **OI-PEF-9** — Quadlet `OnCalendar=` timer schedule for the
  three recovery-drill classes (§3.7.2.3 operator-scheduled).
  Quadlet template lands on container-ops-slot-side; engine
  consumes the drill-trigger envelope only. Sprint-Pengine-7
  Tag-4+ (Zone J impl axis).
- **OI-PEF-10** — Operator-CLI surface `wakir-persona
  drill --persona <id> --class {CONTAINER_CRASH,NATS_BUCKET_LOST,
  SPIRE_SVID_EXPIRED}` for manual drill execution outside the
  scheduled cadence. Mirrors the §3.7.2 acceptance criteria as
  exit-code-encoded outcome. Sprint-Pengine-7 Tag-N+.
- **OI-PEF-11** — Persistent `recovery_drill_outcome` envelope
  schema-registry entry (`wakir.persona.recovery-drill-outcome/1`)
  so Reza Sprint-9 Tag-2 durable-ledger can anchor drill
  outcomes into the WAT merkle tree (Zone K cross-review).
  Sprint-Pengine-7 Tag-N+ (Reza-side Sprint-9 Tag-2+ paired axis).
- **OI-PEF-12** — `MigrateVersionGovernanceGateError` runtime
  surface in the persona-engine crate, surfaced as a structured
  error when §3.7.3.1 condition (3) is missing. The error MUST
  carry `(persona_id, source_version, target_version,
  missing_hr_audit_annotation_path)` for forensics. Sprint-Pengine-7
  Tag-N+ (paired with Aisha-HR-slot governance-revision flow).

## 9. Compatibility statement

Sprint-Pengine-7 Tag-1 is **purely additive** relative to
Phase-1b Sprint-6:

- All seven existing Rust crates (`persona-hash`,
  `persona-canonical-form`, `persona-canonical-form-yaml`,
  `persona-migration`, `persona-migration-resolver`,
  `persona-cli`, `persona-validator`) remain byte-unchanged.
- The Python `wirelang.persona.*` tree is untouched.
- The V-907 hash function is byte-unchanged.
- The V-907 pin-pack constants (engine-side V1..V11) are
  byte-unchanged.
- The persona-v1 / persona-v2 JSON-Schemas are byte-unchanged.
- The schema-registry-spec v0.31.0 bucket inventory is touched
  only by **reservation** of the `wakir-persona-state-{persona_id}`
  family (Sprint-Pengine-7 Tag-4 will implement; Tag-1 documents).

New artefacts (Sprint-Pengine-7 Tag-1):

- `wirelang/specs/persona-engine-format-spec.md` (this file).
- `wirelang/schemas/persona-claude-native.json` (input-axis JSON-Schema).
- `wirelang/schemas/wakir-persona-v1.json` (target-axis JSON-Schema).
- `wirelang-rust/crates/persona-engine-format/` (mapping crate).
- `wirelang-rust/crates/persona-engine-format/tests/fixtures/claude-agents/` (13 test vectors).

Sprint-Pengine-7 Tag-3 (v1.2) is **purely additive** relative to
v1.1:

- §3.7 lifecycle protocols are spec-level surfaces over the
  v1.1-byte-unchanged JSON envelope. No new JSON field is added
  to `spawn_lifecycle` / `state_persistence` / `container_bridge` /
  `migration_metadata`; the wakir-persona-v1.json schema remains
  byte-unchanged.
- All 22 existing tests (T-PEF-AXIS-A..D, T-PEF-DET-01..03,
  T-PEF-EDGE-01..03, T-PEF-V907-01, T-PCV-01..15 in the
  persona-converter crate) remain green; the V-907 persona-hash
  function and all 13 active personae's hash pins remain
  byte-unchanged.
- The `persona-engine-format` crate gains a Tag-3 lifecycle-protocols
  surface module (`lifecycle_protocols`) carrying pure-data
  constants and validator functions matching §3.7. The mapping
  entry-point `map_claude_native_to_wakir_v1` is byte-unchanged.

## 10. License

This specification is licensed under the Creative Commons
Attribution 4.0 International License
(<https://creativecommons.org/licenses/by/4.0/>).

— pengine-eng, Sprint-Pengine-7 Tag-3
