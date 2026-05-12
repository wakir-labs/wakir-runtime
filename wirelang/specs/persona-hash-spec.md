<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# V-907 Persona-Hash Spec (Phase-1b Sprint-1 Tag-2 skeleton)

| Field | Value |
|---|---|
| Spec ID | V-907 |
| Module | `wirelang/persona/persona_hash.py` |
| Schema | `wirelang/schemas/persona-v1.json` |
| Phase | 1b (Python bootstrap; Phase-1c Rust re-write follows ADR) |
| Format ratification | engine-default mock; HR-slot ratification pending (ADR-0029) |
| Cross-review zones | K (WAT-bridge, pending K-1+K-2 ack), L (identity-substrate, pending Z-L sync memo) |

## 1. Purpose

The persona-hash is the third audit-pin pillar of the WAT frame, alongside
the AIP-document hash and the capability-token hash. Its role is to make
a persona-definition file *byte-pinnable* in the audit trail: any
modification to the canonical subset of a persona's front-matter shifts
the hash, which surfaces as a frame-level drift in the WAT projection.

The hash deliberately covers only a **subset** of the persona-definition
file. The narrative markdown body (Werdegang, Arbeitsstil, Stärken,
Blind Spots) is *out-of-hash* by design: those sections may evolve
through HR-slot edits without forcing a re-pin sweep. The
front-matter and the `identity_pinned` block carry the audit-relevant
surface (authority bounds, cross-review obligations, hierarchy).

## 2. Canonical subset (engine-default mock format)

A persona definition is a UTF-8 markdown file that opens with a YAML
front-matter fence:

```
---
<yaml-mapping>
---

# <markdown body, OUT-OF-HASH>
...
```

The canonical-subset extractor projects the YAML mapping onto the
following keys, dropping anything else:

```yaml
name: <role-string>                  # required, slug pattern
description: <text>                  # required
tools: [<string>, ...]               # required, list-of-strings
schema_version: persona-v1           # required, exact match
identity_pinned:                     # required, mapping
  cross_review_zones:                # required, list of {zone, partner, trigger}
    - zone: <string>
      partner: <role-string>
      trigger: <string>
  authority:                         # required, mapping
    push_remote: <bool>
    budget_cap_eur_per_month: <int>
    sub_delegation: <bool>
  hierarchy:                         # required, mapping
    reports_to: <role-string>
    escalation: <role-string>
```

Unknown top-level keys are *ignored* (forward-compat). Unknown keys
inside `identity_pinned` raise a parser error (strict for the
audit-pinned surface). `tools` may also be supplied as a comma-
separated string in the source for ergonomics; the canonical form
is always a list.

## 3. Hash function

```
persona_hash = "sha256:" + sha256_hex( JCS( canonical_subset ) )
```

- **JCS**: RFC 8785 JSON Canonicalization Scheme.
- **sha256_hex**: lowercase hex, 64 chars.

The function is exposed as
`wirelang.persona.compute_persona_hash(path) -> str` and
`wirelang.persona.compute_persona_hash_from_canonical(dict) -> str`.
A caller-pin parameter (`expected_jcs_sha256`) is supported in both
forms; on drift, `PersonaHashMismatchError` is raised.

## 4. Schema rejection and self-migration

Only `schema_version: persona-v1` is accepted in Phase-1b. Older
schemas (e.g. `persona-v0`) raise `PersonaSchemaUnsupportedError`.
The self-migration converter (ADR-0036, owned by the persona-engine
slot) is responsible for upgrading older sources before they reach
this hash function.

Future schema revisions (`persona-v2`, ...) will live behind a
versioned dispatch in this module and will keep `persona-v1` callable
through a compatibility adapter; the test-vector pin pack is the
forcing function for byte-stability across revisions.

## 5. Empty-ref sentinel (V-908 federation)

A WAT frame that does not pin a persona reference uses the
empty-string sentinel `""` (exposed as
`PERSONA_EMPTY_REF_SENTINEL`). The bridge helper that reads
`persona_refs[0]` from a frame returns this sentinel byte-for-byte
identically to `extract_aip_document_hash_from_frame` and
`extract_capability_token_hash`. The sentinel is *never* a valid
hash output (real hashes always start with `"sha256:"`), so the two
cases are distinguishable at the byte level.

## 6. Test-vector pin pack

The 9-vector pack lives under
`wirelang/tests/fixtures/persona_definitions/v{N}-*.md` with frozen
hex pins in `wirelang/persona/_internal/pin_pack_constants.py`.
Coverage map:

| # | Vector | Mutation class | Expected behaviour |
|---|---|---|---|
| v1 | ceo baseline | — | reproduces PIN_V1 |
| v2 | wat-eng baseline | — | reproduces PIN_V2 |
| v3 | identity-eng baseline | — | reproduces PIN_V3 |
| v4 | ceo + description edit | M-1 (front-matter) | PIN != PIN_V1 |
| v5 | ceo + body edit | M-3 (out-of-hash) | PIN_V5 == PIN_V1 |
| v6 | ceo + extra cross_review_zone | M-2 (identity_pinned) | PIN != PIN_V1 |
| v7 | empty-ref sentinel | — (no file) | sentinel == "" |
| v8 | schema_version=persona-v0 | — | rejected with PersonaSchemaUnsupportedError |
| v9 | schema_version=persona-v1 (migrated) | — | hashes cleanly |

Mutation class M-4 (hex-tail bit-flip) is exercised by the caller-pin
verifier rather than by a separate fixture file.

## 7. Cross-review surfaces

### 7.1 Zone K (WAT-bridge)

The WAT-side bridge helper `extract_persona_hash_from_frame` will
mirror the existing `extract_capability_token_hash` byte-for-byte
and live in `wat/ingestion/wirelang_bridge.py` (wat-eng-slot owner).
This module is the *engine-side* source of truth for the format.
K-1 and K-2 ack from the wat-eng counterpart are pending; the
engine-side build proceeds independently in pull-through mode.

### 7.2 Zone L (identity-substrate)

The identity-substrate AIP resolver may be extended with a
`_post_verify(uri, body)` hook that cross-validates a persona-hash
attached to an AIP document. The Z-L sync memo and identity-eng-slot
ack are pending; this module is hook-agnostic.

### 7.3 HR (format ratification)

The mock format documented in §2 is the engine-default. The HR-slot
format decision (ADR-0029) may refine field semantics or constrain
unknown-key handling. The public API does not change under any
plausible HR refinement; only the canonical-subset extractor and the
9-vector pin pack do, and the pin pack is the canary that catches
drift at byte granularity.

## 8. License

This spec is CC-BY-4.0; the implementation modules are Apache-2.0
(per the wakir-runtime license posture in `pyproject.toml`).

---

## Annex A — Hex-Pin Posture (Phase-1b Sprint-6 Tag-6)

### A.1 What is pinned, where, and why

The V-907 hash function is the audit anchor. *Hex-pin posture* names
the test-side discipline of freezing the **raw 64-character hex tail**
(i.e. the substring after the literal `sha256:` prefix) of each
canonical-subset hash in addition to the full `sha256:<64hex>` pin
string. Two different surfaces consume the two forms:

| Form | Surface | Rationale |
|---|---|---|
| `"sha256:<64hex>"` | Python `PERSONA_HASH_PIN_V*` constants in `pin_pack_constants.py`; Rust mirror constants in `persona-migration/src/lib.rs` | Operator-facing pin string. What `wakir-persona pin <file>` prints on stdout, what `--expect-hash` accepts. Cross-language byte-equal. |
| `<64hex>` only | Rust `*_HEX_RUST_ONLY` test constants in `persona-canonical-form` / `persona-migration` / `persona-migration-resolver` | Hard-freeze of the JCS-canonicalisation + SHA-256 boundary on the Rust side. Catches a regression that would shift the hex tail even before the `"sha256:"` prefix is applied. Rust-only because Python catches the same regression via its existing `PERSONA_HASH_PIN_V*` self-consistency tests. |

The two forms are tied together by self-consistency tests
(e.g. `PERSONA_HASH_PIN_V9.ends_with(V8_MIGRATED_TO_V1_HEX_RUST_ONLY)`):
any drift on one form trips a test on the other.

### A.2 Frozen pin-pack (Phase-1b Sprint-6 state)

Operator-facing `sha256:<64hex>` pins (cross-language, byte-equal):

| Constant | Vector / chain | Lives in (Python) | Lives in (Rust) |
|---|---|---|---|
| `PERSONA_HASH_PIN_V1` | v1 baseline | `pin_pack_constants.py` | (test fixture only) |
| `PERSONA_HASH_PIN_V2` | v2 baseline | `pin_pack_constants.py` | (test fixture only) |
| `PERSONA_HASH_PIN_V3` | v3 baseline | `pin_pack_constants.py` | (test fixture only) |
| `PERSONA_HASH_PIN_V4` | v4 frontmatter edit | `pin_pack_constants.py` | (test fixture only) |
| `PERSONA_HASH_PIN_V5` | v5 body edit (== V1) | `pin_pack_constants.py` (alias) | (test fixture only) |
| `PERSONA_HASH_PIN_V6` | v6 cross-review edit | `pin_pack_constants.py` | (test fixture only) |
| `PERSONA_HASH_PIN_V9` | v9 self-migration target | `pin_pack_constants.py` | `persona-migration/src/lib.rs` |
| `PERSONA_HASH_PIN_V8_MIGRATED_TO_V1` | v8 -> v1 (alias of V9) | `pin_pack_constants.py` | `persona-migration/src/lib.rs` |
| `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` | v9 -> v2 single step | `pin_pack_constants.py` | `persona-migration/src/lib.rs` |
| `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2` | v8 -> chain -> v2 | `pin_pack_constants.py` (alias) | `persona-migration/src/lib.rs` (alias) |

Rust-only hex-tail hard-freeze constants:

| Constant | Asserts the hex tail of | Lives in |
|---|---|---|
| `V8_PIN_HEX_RUST_ONLY` | the JCS-SHA-256 of the v8 canonical subset (no migration) — promoted from `None` in Sprint-5 Tag-4 | `persona-canonical-form/src/lib.rs` |
| `V8_MIGRATED_TO_V1_HEX_RUST_ONLY` | `V0ToV1Step` output hex (== tail of `PERSONA_HASH_PIN_V9`) | `persona-migration/src/lib.rs` |
| `V9_MIGRATED_TO_V2_HEX_RUST_ONLY` | `V1ToV2Step` output hex (== tail of `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`) | `persona-migration/src/lib.rs` |
| `V8_CHAIN_TO_V2_HEX_RUST_ONLY` | `migrate_persona(... target=persona-v2)` dispatcher output on V8 Markdown input (== tail of `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`) | `persona-migration-resolver/src/lib.rs` |

### A.3 Re-derivation pattern via `registered_steps()`

The migration registry is the single source of truth for chain order.
Test code that walks the chain re-derives every intermediate hash from
the registered steps rather than from hard-coded step references, so a
new step accidentally not wired into `registered_steps()` is caught by
a regression test (`t15_re_derivation_via_registered_steps_iteration`
in `persona-migration` and the dispatcher pendants in
`persona-migration-resolver`).

```rust
// Re-derivation skeleton (pseudo-code):
let mut current = load_v8_canonical_subset();
let mut current_pin = compute_pin(&current);
for step in registered_steps() {
    if let Some(next) = step.apply_if_source_matches(&current) {
        current = next;
        current_pin = compute_pin(&current);
    }
}
assert_eq!(current_pin, expected_chain_terminus_pin);
```

The Python sister is structurally identical and uses
`wirelang.persona._internal.migration_steps.registered_steps()`.

### A.4 Maintenance triggers for pin updates

A pin update is required *only* when one of the following changes
land. None of these is a routine refactor.

1. **A canonical-subset fixture front-matter is edited.** Bumps the
   per-fixture pin (`PERSONA_HASH_PIN_Vn`) and any chain-terminus pin
   downstream.
2. **The canonical-subset extractor adds or drops a required key, or
   reorders the schema.** Affects every fixture; the entire pin pack
   plus the Rust hex-tail constants re-anchor in a single box.
3. **A migration step's projection changes (gain/lose a key, change a
   default value).** Bumps the chain-terminus pin for every chain that
   passes through the affected step.
4. **JCS canonicaliser or SHA-256 backend swap.** Affects every pin
   (operator-facing and Rust-only hex). Cross-language byte-stability
   must be re-verified end-to-end before the new backend is accepted.

The pin-pack is **not** updated for:

- Code-comment / doc-string edits.
- Body-only Markdown edits to a fixture (the body is OUT-of-hash by
  construction; `PERSONA_HASH_PIN_V5 == PERSONA_HASH_PIN_V1` is the
  M-3 anchor for this).
- Test-only refactors (helper extraction, parametrisation).
- Renames that don't touch the canonical-subset wire bytes.

### A.5 Cross-Reference test-anchors

Each pin is exercised by at least one byte-equal test on each side.
The Phase-1b Sprint-6 anchor matrix:

| Pin | Python anchor | Rust anchor (crate) |
|---|---|---|
| `PERSONA_HASH_PIN_V1..V6` | `test_persona_hash.py::test_pin_pack_constants_match_fixtures` | `persona-canonical-form` `cf6..cf11` |
| `PERSONA_HASH_PIN_V9` | `test_persona_hash.py::test_v9_pin_matches_python_constant` | `persona-migration` `t1`, `persona-canonical-form` `cf1..cf5` |
| `PERSONA_HASH_PIN_V8_MIGRATED_TO_V1` | `test_persona_migration.py::test_v8_to_v1_pin_match` | `persona-migration` `t1`, `t11` (10-iter stress) |
| `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` | `test_persona_migration_v1_to_v2.py::test_v9_to_v2_pin_match` | `persona-migration` `t2`, `t12` (10-iter stress) |
| `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2` | `test_persona_migration.py::test_v8_chain_to_v2_pin_match` | `persona-migration` `t3` (chain), `persona-migration-resolver` `t6..t8`, `t13`, `t14`, `t15` |
| `V8_PIN_HEX_RUST_ONLY` | (none; Rust-only) | `persona-canonical-form` `cf12` (`t12_v8_hex_pin_hard_freeze`) |
| `V8_MIGRATED_TO_V1_HEX_RUST_ONLY` | (none; Rust-only) | `persona-migration` `t13` |
| `V9_MIGRATED_TO_V2_HEX_RUST_ONLY` | (none; Rust-only) | `persona-migration` `t14` |
| `V8_CHAIN_TO_V2_HEX_RUST_ONLY` | (none; Rust-only) | `persona-migration-resolver` `t15` |
| Re-derivation roundtrip (registry-iteration) | (none; Rust-only — Python equivalent runs via `migrate_persona` end-to-end tests) | `persona-migration` `t15`, `persona-migration-resolver` `t16` |

### A.6 CLI-side cross-reference (Sprint-6 Tag-1 .. Tag-5)

The operator-facing CLI (`wakir-persona`) re-uses the same pins:

- `wakir-persona migrate --expect-hash <pin>` — accepts only the
  `"sha256:<64hex>"` form; mismatched pins fire
  `PersonaMigrationDeterminismError` and emit the
  `"wakir-persona: hash drift: ..."` stderr marker (exit 2).
- `wakir-persona inspect --emit-hash` — emits the V-907 pin on
  stderr for the read-only canonical-subset projection.
- `wakir-persona pin <file>` — emits *only* the pin on stdout
  (`sha256:<64hex>\n`), so shell scripts can capture without
  `2>&1` redirect gymnastics.

The cross-language V-907-CLI-invariant (`pin` stdout ==
`inspect --emit-hash --quiet` stderr-pin == `migrate --emit-hash`
stderr-last-line on a v9 no-op-chain input) holds against
`PERSONA_HASH_PIN_V9` in both Python and Rust CLIs. The
Tag-4 test pack pins all three forms simultaneously
(`test_persona_pin_cli::test_pin_v9_matches_inspect_and_migrate`
plus the Rust `pin_tests` mod's cross-form anchor).

### A.7 stderr-Wording-Byte-Parität (Sprint-6 Tag-6 — Item 1)

The error-path stderr surface carries a Cross-Lang-Diff-Pin on the
six per-subcommand markers. See `wirelang/tests/test_persona_cli_stderr_parity.py`
(Python) and `wirelang-rust/crates/persona-cli/src/lib.rs`
`mod stderr_parity_tests` (Rust) for the pinned constants. The
prefixes are byte-equal across languages; the bodies follow runtime-
formatter semantics (Python `__str__` vs. Rust `Display`) and are
intentionally soft-match only.

