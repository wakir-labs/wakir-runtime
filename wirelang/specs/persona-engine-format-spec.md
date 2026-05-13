<!-- SPDX-License-Identifier: CC-BY-4.0 -->

---
spec: persona-engine-format
version: 1.1.0
status: draft
date: 2026-05-13
audience: pengine-eng, persona-authors, hr-slot, container-ops-slot
license: CC-BY-4.0
---

# Persona-Engine-Format Specification (v1.1)

| Field | Value |
|---|---|
| Spec ID | PEF-1 |
| Owner | pengine-eng (ADR-0043) |
| Phase | 1b Sprint-Pengine-7 Tag-2 (2026-05-13) |
| Self-Migration anchor | ADR-0036 (Self-Migration-Konverter) — Sprint-Pengine-7 Tag-2 converter consumes this spec |
| Companion specs | `persona-hash-spec.md` (V-907), `self-migration-konverter-spec.md`, `persona-schema-v10-migration-vorbereitung.md`, `schema-registry-spec.md` v0.32.0 §10 |
| Cross-review zones | J (container-bridge spec, container-ops-slot), K (WAT-bridge / V-907 hash integration, wat-eng-slot), L (identity-substrate forward-link, identity-eng-slot), HR (governance-revision, hr-slot) |
| Status of ratification | v1.1: HR-slot bedingt-ack 2026-05-13 (Aisha-Cross-Review Counter-Vorschlag 1 eingearbeitet als `synthesis_default_exceptions` §4.3); Counter-Vorschläge 2-3 als Future-Items OI-PEF-7/8 registriert |

## Revision history

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-05-13 (AM) | Initial Sprint-Pengine-7 Tag-1 spec (PR #22, `86c9acc`). |
| 1.1.0 | 2026-05-13 (PM) | Tag-2 cut-over: Aisha-HR-Counter-Vorschlag 1 eingearbeitet als `synthesis_default_exceptions` table in §4.3 (cfo + internal-audit `reports_to`/`escalation` → `aufsichtsrat`). Counter-Vorschläge 2 (per-transaction budget cap) and 3 (`identity_pinned_policy_version`) recorded as OI-PEF-7 / OI-PEF-8 (future items, not Tag-2 blockers). |

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

### 3.7 JSON-Schema for output validation

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

## 7. Cross-review zones (Sprint-Pengine-7 Tag-1)

| Zone | Partner | Trigger | Tag-1 touch | Tag-1 ack required? |
|---|---|---|---|---|
| **J** | container-ops-slot | container-bridge spec change | yes — §3.5 specifies image template, labels, env vars | yes, before Sprint-Pengine-7 Tag-4 (container backend implementation) |
| **K** | wat-eng-slot | WAT-frame format / V-907 hash function change | **no functional change** — §5 confirms hash function unchanged, only operator-side pin-pack added | yes, confirmation that no WAT-frame change is needed |
| **L** | identity-eng-slot | identity_doc_ref forward-link | reserved in §4.3 (synthesised default with safe fallback); §3.x carries no identity-document URI yet | not until Sprint-Pengine-7 Tag-3+; Tag-1 records the reservation |
| **HR** | hr-slot | persona-definition governance | v1.0: §4.3 synthesis defaults HR-slot-ratification-pending; v1.1: bedingt-ack 2026-05-13 (Counter-Vorschlag 1 eingearbeitet als §4.3.1 `synthesis_default_exceptions`; Counter-Vorschläge 2-3 als OI-PEF-7/8 registriert) | v1.1: yes (bedingt-ack received, full ratification gated on Tag-3 body-parser landing) |

## 8. Open items (Sprint-Pengine-7 Tag-1 follow-up)

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

## 10. License

This specification is licensed under the Creative Commons
Attribution 4.0 International License
(<https://creativecommons.org/licenses/by/4.0/>).

— pengine-eng, Sprint-Pengine-7 Tag-1
