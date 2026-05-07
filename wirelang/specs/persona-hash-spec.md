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
