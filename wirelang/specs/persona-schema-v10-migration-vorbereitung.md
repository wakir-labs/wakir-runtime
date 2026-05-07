<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Persona-Schema V10-Migration Vorbereitung (Phase-1b Sprint-3 Tag-1 sketch)

| Field | Value |
|---|---|
| Spec ID | V-907 / ADR-0036 (next-major-step preparation) |
| Phase | 1b Sprint-3 Tag-1 (sketch); implementation pending ceo-slot sprint-3 trigger |
| Status | **sketch** — neither Default-Lock A-2 marker re-verification, nor HR-slot ratification of `persona-v2` content, nor `V1ToV2Step` implementation has happened. This file scopes the work, it does not authorise it. |
| Companion specs | `wirelang/specs/persona-hash-spec.md` (V-907 hash function), `wirelang/specs/self-migration-konverter-spec.md` (ADR-0036 converter) |
| Cross-review zones touched | K (WAT-bridge — pin-pack append), L (identity-substrate — only if v2 carries identity material), HR (A-2 marker re-verification + content ratification) |
| Default-Lock posture | A-1 (mock format input shape), A-2 (semver-major-only, additiv-only, linear chain), A-3 (frontmatter in-hash, body out-of-hash). T-B Default-Lock ratified by ceo-slot 2026-05-07 closeout-stamp. |

## 0. Naming convention disambiguation

This sketch uses two parallel numbering systems; both are stable and
intentional:

- **Pin-pack vector numbering** (`v1..v9`, future `v10`, `v11`, ...).
  These index test-fixture files under
  `wirelang/tests/fixtures/persona_definitions/v{N}-persona-*.md` and
  the corresponding `PERSONA_HASH_PIN_V{N}` constants in
  `wirelang/persona/_internal/pin_pack_constants.py`. Sprint-3 Tag-1
  is the first time we extend this set past `v9`. The ceo-slot
  sprint-3-tag-1 brief uses **"V9"** and **"V10"** in this sense
  (V9 = current pin baseline, V10 = first new pin in the v2 fixture
  band).
- **Schema-version naming** (`persona-v0`, `persona-v1`, future
  `persona-v2`). These are the YAML-front-matter `schema_version`
  string consts defined in `wirelang/schemas/persona-v_n.json` and
  enforced by `V0ToV1Step.target_version` (and the upcoming
  `V1ToV2Step.target_version`). Sprint-3 Tag-1 is the first time we
  scope a `persona-v2` shape.

The mapping for this sketch:

| Pin-pack vector | Schema-version | Sprint provenance |
|---|---|---|
| `v9` | `persona-v1` (current latest) | Sprint-1 Tag-2 baseline + Sprint-2 Tag-1 `V0ToV1Step` migration target |
| `v10` (planned) | `persona-v2` (next major) | this sketch |
| `v11` (planned) | `persona-v2` (mutation class fixture, e.g. M-1/M-2 in v2 shape) | follow-up |

The remainder of this document refers to **V9** and **V10** as
pin-pack vectors when discussing fixtures, and to **`persona-v1`**
and **`persona-v2`** as schema-version strings when discussing
shapes and step lifts. The frontend-slot audit-trail-browser
persona-inspector card already pins on the `PERSONA_HASH_PIN_V9`
constant name (frontend-slot Sprint-Frontend-1 Tag-4 outbox); this
sketch keeps that constant stable and adds new ones.

## 1. Purpose

The V0-to-V1 self-migration step (Sprint-2 Tag-1 `V0ToV1Step`) was a
schema-version-only lift: rename the `schema_version` const, pass
everything else through. Sprint-3 Tag-1 prepares the *next* major
step, V9-to-V10 (i.e. `persona-v1` to `persona-v2`), which is the
first migration step that may carry actual additive content.

The deliverable of this sketch is **scope**, not implementation:

- The diff between the current `persona-v1` canonical subset and the
  proposed `persona-v2` shape (fields added, fields kept optional,
  fields explicitly reserved).
- The migration path V9-to-V10 as a `V1ToV2Step` registry entry
  consistent with the Default-Lock A-2 / M-1 / M-2 / M-4 markers.
- A test-plan extension that grows the cross-version round-trip pack
  to cover the new V8-via-V0V1V2-chain shape (multi-step linear
  chain, anchored against the same v8/v9 fixture pair).
- A cross-reference back to the frontend-slot Persona-Inspector and
  Audit-Trail consumption surface (V9-Pin sample is the public
  substance the frontend-slot ships; V10-pin is the next public
  substance lobe).

This sketch is the artefact that lets a future implementation box
(possibly Sprint-3 Tag-2 or later) start coding without re-deriving
scope. It does **not** authorise schema content (HR-slot decision)
or pin-bytes (those follow once the v10 fixture is authored and the
pack is regenerated).

## 2. V9-to-V10 schema diff (proposed)

The diff is split into three classes per the engine-default Default-
Lock A-2 (semver-major-only, additiv-only, linear chain):

- **Additive fields** — new top-level or nested keys, **always
  optional** in `persona-v2`. The migration step writes their default
  explicitly when a v9 input is lifted.
- **Optional / forward-compat fields** — keys that may be present in
  v2 but are not required; lifted v9 inputs have them absent.
- **Reserved fields** — keys carved out in the schema with
  `additionalProperties: false` boundary widened to admit them, but
  no semantics yet defined. Reserved fields are an intentional anti-
  collision device: a future v10 reader knows the keyspace is taken
  even though Sprint-3 Tag-1 leaves their meaning open.

### 2.1 Candidate field set (HR-slot ratification pending)

The following candidates are **proposals only**. HR-slot owns the
ratification of `persona-v2` content (ADR-0029-Annex). This sketch
proposes them so that the engineering scope is bounded; HR may
refine or reject.

#### 2.1.1 Additive at top level

| Field | Type | Default in V1ToV2Step | Rationale |
|---|---|---|---|
| `model_pin` | object (optional) | absent | Carries an explicit model-version pin so a persona's behaviour is reproducible across model upgrades. Phase-2 alignment item; Phase-1c Sprint-3 records the hash-input shape so v2-inputs that supply it are byte-stable. |
| `spawn_constraints` | object (optional) | absent | Captures spawn-time validations (e.g. parent-supervisor allow-list, max-concurrent-instances). Currently lives implicitly in supervisor code; v2 makes it persona-pinnable. |

#### 2.1.2 Additive inside `identity_pinned`

| Field | Type | Default in V1ToV2Step | Rationale |
|---|---|---|---|
| `identity_pinned.identity_doc_ref` | string (optional, URI) | absent | Forward-link to a Z-L identity-substrate document hash (identity-eng-slot domain). Optional in v2 because Z-L identity-document schema is still pending; lifted v9 inputs have no such ref. |
| `identity_pinned.persona_owner_role` | string (optional, role-string) | absent | Captures HR-side ownership role (separate from `hierarchy.reports_to`, which is reporting/escalation only). hr-slot domain ratification. |
| `identity_pinned.governance_revision` | integer >= 1 (optional) | absent | Allows persona-definition governance revisions to be pinned without forcing a schema-version shift. Distinct from `schema_version` (engine-side) and from the file-level git history (operator-side). |

#### 2.1.3 Reserved at top level (no semantics)

The following keys are widened into `additionalProperties: false`'s
allow-list with type `object` or `string` so that future Sprint-3
follow-up boxes can claim them without breaking byte-pin stability.
A reserved field present in a v9 input is a parser error today (v1
schema is strict); a reserved field present in a v10 input that is
not yet meaningful is **ignored** but **not pin-affecting** — by
construction, an absent reserved field hashes the same as one
present-but-empty, because the canonical-subset extractor drops empty
values to get there. (See §6 for a tighter argument.)

| Reserved key | Anticipated owner | Reservation rationale |
|---|---|---|
| `recovery_drill` | reza | `recovery-drill-leaf-projection.md` may want a persona-pin slot for drill membership. |
| `wat_bridge_overrides` | tomas (wat-eng) | If a persona's WAT-frame ingestion needs persona-specific overrides, the slot exists ahead of time. |
| `container_bridge_spec` | kai | Zone-J persona-container-bridge override; Sprint-3 likely consumes it. |

Reservations are a low-cost forward-compat device: the schema
allows the key (so a v10 file with it is parseable), but Sprint-3
Tag-1 does not write semantics for them. Default-Lock A-2 is upheld
because a v10 reader sees a v9 input as a strict subset.

### 2.2 Anti-changes (what V10 does NOT do)

To keep A-2 (additiv-only) clean, the following changes are
**explicitly excluded** from the V9-to-V10 step:

- **No field removal.** No top-level or nested key in `persona-v1` is
  removed in `persona-v2`. M-2 in the M-Konsens-Marker aggregate
  (Sprint-2 Tag-5 companion memo) is the load-bearing assumption.
- **No type narrowing.** A `persona-v1` field of type `string` is
  not narrowed to `string` with a stricter regex in `persona-v2`. A
  v9 input that is currently valid is also valid as a `persona-v2`
  value once `schema_version` is lifted.
- **No required-set extension.** New fields enter as optional. A v9
  input does not gain a missing-field error after the lift.
- **No body changes.** A-3 (front-matter in-hash, body out-of-hash)
  is unchanged. The markdown body remains untouched.
- **No JCS-norm change.** RFC 8785 JCS is the canonicalisation; this
  is a substrate-level invariant unrelated to schema-major. The
  Phase-1c Rust crate continues to consume the same canonical-subset
  bytes (Cross-Lang-Parity-Anker from Sprint-2 Tag-5 stays valid).
- **No hash-function change.** SHA-256 stays. A `sha256:`-prefix is
  the V-907 sentinel discriminator; no second hash family is
  introduced in v2.

The discipline is: V10 adds *capacity*, never *constraint*.

## 3. V9-to-V10 migration path (linear chain via converter)

The `V1ToV2Step` follows the same Protocol-shape as `V0ToV1Step`:

```python
class V1ToV2Step:
    source_version: Final[str] = "persona-v1"
    target_version: Final[str] = "persona-v2"

    def apply(self, definition_dict: dict[str, Any]) -> dict[str, Any]:
        # source-version-strict (rule 4)
        if definition_dict.get("schema_version") != self.source_version:
            raise ValueError(...)
        out = copy.deepcopy(definition_dict)  # rule 2 (non-mutating)
        out["schema_version"] = self.target_version  # rule 5 (explicit default)
        # Additive fields are NOT injected; they default to absent
        # because canonical-subset extractor drops absent-or-empty
        # values to maintain pin-stability for lifted v9 inputs
        # (see §6).
        return out
```

`REGISTERED_STEPS` extends to:

```python
REGISTERED_STEPS: Final[tuple[MigrationStep, ...]] = (
    V0ToV1Step(),
    V1ToV2Step(),
)
```

A v0 input from the legacy era resolves through the chain
`V0ToV1Step()` then `V1ToV2Step()` automatically because
`migrate_persona`'s linear-walk resolver looks up by
`source_version` and walks forward. The Sprint-2 Tag-2 cycle-guard
(32) is sufficient.

The converter's behaviour for a fresh v9 input:

```
input  = { "schema_version": "persona-v1", ...same v1 keys... }
                                ↓ V1ToV2Step
output = { "schema_version": "persona-v2", ...same v1 keys... }
```

i.e. byte-identical to the input *except* for the `schema_version`
const, mirroring the V0-to-V1 pattern exactly. The
`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` aliasing constant (companion to
`PERSONA_HASH_PIN_V8_MIGRATED_TO_V1`) will **not** alias to
`PERSONA_HASH_PIN_V10` because the canonical-subset *includes*
`schema_version` in the JCS bytes; lifting `persona-v1` to
`persona-v2` changes the JCS bytes and therefore the pin.

This is a deliberate design choice: in V0-to-V1, the v8 fixture and
the v9 fixture share *every* canonical-subset key including
`schema_version` (because the v9 fixture was authored as the v1-
shape native target), so the migrated output of v8 hashes to v9's
pin. In V9-to-V10, the v9 fixture is `persona-v1`-shape and the
V10 pin must be a *new* pin, computed on the migrated output. There
is no native `persona-v2` fixture before Sprint-3 Tag-N (where the
v10 fixture is authored).

### 3.1 Pin-pack expansion plan

Sprint-3 Tag-N (when implementation lands) extends
`pin_pack_constants.py`:

```python
# New native v2-shape fixture, pin-pack vector v10:
PERSONA_HASH_PIN_V10: Final[str] = "sha256:<TBD>"

# Migration target pin: hash of the canonical subset produced by
# V1ToV2Step.apply on the v9 fixture (Sprint-3 Tag-N S3-T?-?).
# By construction, NOT equal to PERSONA_HASH_PIN_V10 unless the
# v10 native fixture is authored to be byte-identical to the
# migrated v9 fixture. Treat as its own constant.
PERSONA_HASH_PIN_V9_MIGRATED_TO_V2: Final[str] = "sha256:<TBD>"

# (Optional, follow-up): mutation-class fixture in v2 shape, e.g.
# v11 = ceo + new model_pin field, exercising M-1 in v2.
PERSONA_HASH_PIN_V11: Final[str] = "sha256:<TBD>"
```

Pin-bytes are computed at fixture-author time in a Sprint-3 box;
this sketch leaves them as `<TBD>`.

### 3.2 V8-via-V0V1V2-chain (multi-step linear chain anchor)

A v8-shape input (legacy `persona-v0` schema_version) lifted through
the full chain produces a v2-shape output. The migrated dict's hash
will be a *new* pin:

```python
PERSONA_HASH_PIN_V8_MIGRATED_TO_V2: Final[str] = "sha256:<TBD>"
# Equal to PERSONA_HASH_PIN_V9_MIGRATED_TO_V2 by construction:
# v8 and v9 fixtures share every canonical-subset key except
# schema_version, and the chain V0->V1->V2 ends at schema_version
# = persona-v2 either way. So:
PERSONA_HASH_PIN_V8_MIGRATED_TO_V2 = PERSONA_HASH_PIN_V9_MIGRATED_TO_V2
```

This **is** the M-1 (linear-chain) direct-anchor that the Sprint-2
M-Konsens-Marker companion memo flagged as currently *indirect*. A
multi-step chain whose endpoints differ in two `schema_version`
lifts is the test-vector that exercises the resolver's linear-walk
algorithm beyond a single-step path.

## 4. Test plan extension (cross-version roundtrip pack)

The Sprint-2 Tag-2 roundtrip pack (`test_persona_migration_roundtrip.py`,
9 tests) extends in Sprint-3 with the following test classes. The
extension is additive: existing tests stay unchanged.

### 4.1 Single-step V1-to-V2 tests (~6 tests)

| Test | Purpose | Default-Lock anchor |
|---|---|---|
| `test_v1_to_v2_idempotence` | `migrate_persona(v9_dict, target=persona-v2)` called twice yields byte-identical output. | D-1 / D-2 |
| `test_v1_to_v2_target_already_met` | `migrate_persona(v10_native_dict, target=persona-v2)` is a no-op (returns deep-copy at v2). | resolver short-circuit |
| `test_v1_to_v2_pin_match` | Migrated dict matches `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`. | byte-determinism (V-907) |
| `test_v1_to_v2_input_unchanged` | Input dict is not mutated by the call. | step rule 2 |
| `test_v1_to_v2_source_version_strict` | A v9 dict with `schema_version` already at `persona-v2` (corrupted v9 input) does **not** route through `V1ToV2Step`; resolver short-circuits as already-target. | resolver |
| `test_v1_to_v2_native_v10_distinct_from_migrated_v9` | The native v10 fixture's pin differs from the migrated-v9 pin (so they are distinct test vectors, not accidental duplicates). | fixture-design discipline |

### 4.2 Multi-step V0-to-V2 chain tests (~5 tests)

| Test | Purpose | M-anchor |
|---|---|---|
| `test_v0_to_v2_full_chain` | `migrate_persona(v8_dict, target=persona-v2)` resolves via `[V0ToV1Step(), V1ToV2Step()]` and produces v2 output. | **M-1 direct** (linear-chain anchor) |
| `test_v0_to_v2_pin_match` | Migrated dict matches `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`. | byte-determinism |
| `test_v0_to_v2_intermediate_inspection` | The resolver does not expose intermediate dicts (no public V1 hook); only endpoint is observable. | API hygiene |
| `test_v0_to_v2_chain_equals_pairwise` | Migrating v8 to v1 then v1 to v2 by two separate calls produces a dict byte-identical to the single-call v8-to-v2 chain. | resolver associativity |
| `test_v0_to_v2_cycle_guard_unchanged` | The 32-step cycle guard is not exhausted by a 2-step chain. | resolver guard |

### 4.3 Reserved-field round-trip tests (~3 tests)

| Test | Purpose |
|---|---|
| `test_reserved_field_present_does_not_break_v2_parse` | A v10 fixture with a reserved key (e.g. `recovery_drill: {}`) parses cleanly. |
| `test_reserved_field_present_pin_matches_native_v10_without` | A v10 fixture with `recovery_drill: {}` produces the same pin as the v10 fixture without the field — *only* if the canonical-subset extractor drops empty mappings. (See §6 for the discipline argument; this test is the canary.) |
| `test_reserved_field_with_non_empty_value_changes_pin` | A v10 fixture with `recovery_drill: {"id": "drill-001"}` produces a *different* pin from the bare v10. (Confirms the canonical-subset extractor includes non-empty reserved-field content.) |

### 4.4 Negative tests (~2 tests)

| Test | Purpose |
|---|---|
| `test_v2_to_v1_inverse_not_supported` | `migrate_persona(v10_dict, target=persona-v1)` raises `PersonaMigrationError` (no inverse step; M-3 non-invertible anchor still holds in v2). |
| `test_v1_to_unknown_v3_raises` | `migrate_persona(v9_dict, target=persona-v3)` raises `PersonaMigrationError` (unknown target; resolver does not walk past the registered max). |

### 4.5 Total test delta

Sprint-3 Tag-1 (V10-Migration-Vorbereitung) is a **sketch only**, no
new tests authored. The implementation box (Sprint-3 Tag-N) adds
~16 tests:

| Class | Count |
|---|---|
| Single-step V1-to-V2 | 6 |
| Multi-step V0-to-V2 | 5 |
| Reserved-field roundtrip | 3 |
| Negative | 2 |
| **Total Sprint-3 Tag-N delta** | **~16** |

Persona-cluster suite would move from 95 (Sprint-2 Tag-5 closeout)
to ~111. Full `wirelang` suite from 357 to ~373. (Numbers are
projection; Sprint-2-Tag-5 baseline is verified, Sprint-3-projection
is sketch.)

## 5. Default-Lock A-2 re-verification (M-Konsens-Marker handover)

The Sprint-2 Tag-5 M-Konsens-Marker aggregate (companion memo)
classified the four Default-Lock markers as:

| Marker | Statement | Sprint-2 status |
|---|---|---|
| **M-1** | Linear chain, no branching DAG | indirect (single-step Sprint-2 chain) |
| **M-2** | Additiv-only (no field removal) | direct (Sprint-2 V0-to-V1 step) |
| **M-3** | Migration is intentionally non-invertible | direct (Tag-2 roundtrip pack §"M-3-direkt") |
| **M-4** | Multi-version-aware (resolver supports n-step chains) | indirect (resolver code path exercised but not by a multi-step fixture) |

V9-to-V10 / V0-V1-V2 implementation in Sprint-3 Tag-N would convert:

| Marker | Sprint-3 Tag-N status |
|---|---|
| **M-1** | direct (V8-via-V0V1V2-chain test class anchors it explicitly) |
| **M-2** | direct (V1ToV2Step is additive on the v-next side; reserved fields are forward-compat) |
| **M-3** | direct (test_v2_to_v1_inverse_not_supported confirms it stays direct in v2) |
| **M-4** | direct (multi-step chain with two distinct steps exercised by 5 dedicated tests) |

This is a substantial M-Konsens-Marker hardening: three of four
markers move from indirect to direct in Sprint-3 Tag-N. The ceo-
slot-ratified T-B Default-Lock posture (closeout-stamp) does not
require this hardening to hold — Default-Lock is the silent-
acceptance fallback — but it adds substance to the hr-slot HR /
governance pickup if T-A Owner-Acks materialise later.

This sketch does **not** modify the M-Konsens-Marker protocol file.
That edit is hr-slot domain. Sprint-3 Tag-N implementation, when it
ships, would file an hr-slot-side trigger memo for the indirect-to-
direct upgrade.

## 6. Pin-stability discipline for reserved fields (subtlety note)

Reserved fields (§2.1.3) are admitted by the v2 schema but carry no
semantics in Sprint-3 Tag-1. For pin-stability, the canonical-subset
extractor must drop **empty** mappings or arrays so that an absent
reserved field and a present-but-empty reserved field hash
identically:

```
canonical_subset({..., "recovery_drill": {}}) == canonical_subset({...})
```

The current `persona_canonical_form` extractor does **not** do this
projection automatically; v1 schema is strict (`additionalProperties:
false`) and the dropped-key set is the unknown-top-level-keys set.
Reserved fields are *known* keys with *no semantics*; they need an
explicit drop rule.

There are two discipline options Sprint-3 Tag-N may take:

**Option D-A (drop empty reserved):** The canonical-subset extractor
projects `recovery_drill: {}` as if absent. Authors of v10 files
with bare reservations get pin-stability for free; the test
`test_reserved_field_present_pin_matches_native_v10_without`
passes.

**Option D-B (require absence):** Reserved fields **must be absent**
in v10 files until they have semantics. The extractor raises a
`PersonaCanonicalFormError` on a present reserved field. Stricter,
but requires a v10-author-disclipline that is hard to enforce at
the engineering boundary.

This sketch leans toward D-A (lower author-side friction, stricter
drop rule in the extractor), but the decision is parked for the
Sprint-3 Tag-N implementation box. Either way, the test-class
in §4.3 is the canary.

## 7. Cross-reference to frontend-slot consumption (V9-Pin sample)

The frontend-slot Sprint-Frontend-1 Tag-3 audit-trail-browser
(`agents-workspaces/frontend/outbox/2026-05-07-sprint-frontend-1-
tag-3-audit-trail-browser.md`) and Sprint-Frontend-1 Tag-4 persona-
inspector (`...-tag-4-persona-inspector.md`) consume the V9-pin from
`PERSONA_HASH_PIN_V9` as the per-persona hash anchor displayed on
the persona-inspector card. The constant name `PERSONA_HASH_PIN_V9`
is therefore **public substance** at the Wakir-runtime / frontend-
slot TypeScript-bridge boundary.

V10 implementation impact on frontend-slot:

- **Constant-naming stability.** `PERSONA_HASH_PIN_V9` keeps its
  semantics ("hash of the v9 fixture, current `persona-v1` shape").
  No rename. New constants (`PERSONA_HASH_PIN_V10`, etc.) are added
  alongside.
- **Per-persona V9/V10-Cohabitation.** A given persona-definition
  file at the operator side may be in `persona-v1` or `persona-v2`
  shape during a roll-out window. The frontend-slot persona-
  inspector card needs to either (a) display the schema-version on
  the card and pin the appropriate constant, or (b) display the
  post-migration pin (i.e. always-current-target). Sprint-Frontend-
  2 Auftakt-Hook (frontend-slot Sprint-Frontend-2 Tag-N) carries
  this decision.
- **TypeScript-Interface-Generator Pipeline (O3 from Sprint-2
  Tag-6).** When the Persona-V9-Pin-Sample is exposed via the TS-
  generator pipeline (parallel to wat-eng-slot Tag-6 TS-interface-
  hint for `wakir-wat-manifest-v1.json`), the same pipeline supports
  V10. The sample-file pengine-side bears
  `wirelang/schemas/persona-v2.json` and a sample fixture
  `tests/fixtures/persona_definitions/v10-...md` exposes a V10-pin.
- **Audit-trail-browser cross-version display.** A WAT frame may
  pin a persona-hash that was computed on a v9 OR a v10 input,
  during the cohabitation window. The audit-trail-browser does not
  need to know which: the hash is opaque. The persona-inspector
  card does (to display the schema-version line); the data flows
  through the same pin-pack constant pipeline.

This cross-reference is **status-only**. No frontend-slot change is
triggered by this sketch; Sprint-Frontend-2 Auftakt is frontend-slot
domain.

## 8. Push-Bedingung mapping (this sketch)

Per Sprint-3 Tag-1 brief: "Skizze + §9 clean → β-Push (Stack auf
Sprint-2-Tag-5 oder neuer Branch)."

This sketch is one new file (`persona-schema-v10-migration-
vorbereitung.md`) under `wirelang/specs/`. CC-BY-4.0. No code
patches, no schema-file edits, no `pin_pack_constants.py` edits, no
`migration_steps.py` edits. The entire substance is in this file.

§9-sweep (this file): no clear personal names. Persona-slugs only
(`pengine`, `ceo-slot`, `hr-slot`, `wat-eng-slot`, `identity-eng-
slot`, `container-ops-slot`, `frontend-slot`). All persona-vorname
references in earlier draft passes (audit-trail and persona-inspector
attribution lines, M-Konsens-Marker hand-off lines, identity-doc-ref
attribution) were replaced with their corresponding slug forms in
the editing pass.

Verification of §9 cleanness is at the bottom (§10).

## 9. Open items for Sprint-3 Tag-N (implementation)

1. **HR-slot ratification of `persona-v2` content.** This sketch
   proposes additive fields (§2.1.1, §2.1.2) and reserved fields
   (§2.1.3). HR-slot ratification (ADR-0029-Annex follow-up) is
   pending. Implementation cannot land without it, or proceeds with
   a Default-Lock A-2-marker-aware engine-default mock content
   (Sprint-2 Tag-5 M-Konsens-Marker T-B trigger pattern).
2. **`V1ToV2Step` implementation + `REGISTERED_STEPS` extension.**
   ~30 LoC + step rule 4 strict source-version check.
3. **`persona-v2.json` JSON-Schema authoring.** ~120 LoC, mirroring
   `persona-v1.json` with additive optional fields and reserved-
   field allow-list. `additionalProperties: false` retained at
   `identity_pinned` boundary.
   **Status (Sprint-3 Tag-2):** done — schema-file landed at
   `wirelang/schemas/persona-v2.json` with 6 schema-validation
   tests under `wirelang/tests/test_persona_v2_schema.py` (3
   positive + 3 negative). Field-spec mirrors §2.1.1 + §2.1.2 +
   §2.1.3 of this sketch. HR-slot content ratification still
   pending; the schema-file is structure-only.
4. **v10 native fixture + v11 mutation-class fixture.** Two new
   markdown files under `wirelang/tests/fixtures/persona_definitions/`.
5. **Pin-pack constant additions.** `PERSONA_HASH_PIN_V10`,
   `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`, `PERSONA_HASH_PIN_V11`,
   `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2` (alias to V9-migrated-V2 by
   construction).
6. **Test-pack extension.** ~16 tests across the four classes in §4.
7. **Spec doc paired update.** `self-migration-konverter-spec.md` §6
   "step registry contract" and §8 "test posture" paired-edited.
   `persona-hash-spec.md` §4 "schema rejection and self-migration"
   updated to mention `persona-v2` as a valid `target_schema_version`.
8. **Phase-1c Rust crate parity.** The `persona-hash` Rust crate
   (Sprint-2 Tag-4, currently gcc-blocked) consumes the same
   canonical-subset bytes; a `persona-v2` fixture's bytes are
   computed via the same JCS path. No Rust-side schema-file change
   needed (the crate consumes pre-extracted canonical-subset, not
   the JSON-Schema file). Once gcc-block clears, the v10 fixture is
   added to the cross-lang parity test pack.
9. **Frontend-slot Sprint-Frontend-2 paired hand-off.** §7 cross-
   reference; frontend-slot domain pickup.
10. **M-Konsens-Marker-Aggregat indirect-to-direct upgrade memo.**
    Once Sprint-3 Tag-N tests are green, file an hr-slot-side
    trigger memo upgrading M-1 and M-4 from indirect-anchor to
    direct-anchor. pengine-side drafts; hr-slot commits.

## 10. §9-sweep self-verification (this file)

```
$ grep -nE "Tomas|Reza|Kai|Lena|Noa|Selin|Amara|Priya|Aisha|Henrik|Julia|Callandor|Mira" \
    wirelang/specs/persona-schema-v10-migration-vorbereitung.md
```

Expected hits: zero in the body content. The body uses persona-slugs
(`pengine`, `ceo-slot`, `hr-slot`, `wat-eng-slot`, `identity-eng-
slot`, `container-ops-slot`, `frontend-slot`) consistently. The grep
pattern itself, plus this self-verification block, are the only
literal matches that may surface; both are §9 meta-references, not
content references.

Brand-Guide §9.1 governs public-output. `wirelang/specs/` is a
public-surface path under wakir-runtime; this sketch is therefore
held to the slug-only standard.

§9-sweep status: **clean**.

## 11. References

- `wirelang/specs/persona-hash-spec.md` — V-907 hash function,
  canonical-subset definition.
- `wirelang/specs/self-migration-konverter-spec.md` — ADR-0036
  converter spec (companion).
- `wirelang/persona/persona_migration.py` — converter implementation.
- `wirelang/persona/_internal/migration_steps.py` — step registry.
- `wirelang/persona/_internal/pin_pack_constants.py` — V-907 pin-
  pack constants.
- `wirelang/schemas/persona-v0.json` — legacy schema (registry-only).
- `wirelang/schemas/persona-v1.json` — current latest schema.
- `wirelang/schemas/persona-v2.json` — proposed (Sprint-3 Tag-N).
- ADR-0036 — Self-migration of the Wakir-Orga onto wakir-runtime.
- ADR-0029 (and pending Annex KW 23) — HR Persona-Definition format
  ratification.
- Sprint-2 Tag-5 M-Konsens-Marker companion memo — `agents-workspaces
  /pengine/outbox/2026-05-07-phase-1b-sprint-2-tag-5-m-konsens-
  marker-aggregat.md`.
- Sprint-2 Tag-6 Acceptance-Doku §"Open-Items" O5 — `agents-
  workspaces/pengine/outbox/2026-05-07-phase-1b-sprint-2-pengine-
  acceptance-doku.md` (Sprint-2 Tag-6 Acceptance-Doku scoped V10 as
  Phase-2 item; Sprint-3 Tag-1 brief explicitly pulls it forward to
  Sprint-3.)
- RFC 8785 — JSON Canonicalization Scheme (JCS).
