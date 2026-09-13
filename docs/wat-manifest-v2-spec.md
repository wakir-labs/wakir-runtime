<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT Hour-Manifest v2 — Format Specification

Schema-Version: `wat-manifest/2.0`
Schema-`$id`: `https://wakir.dev/wirelang/schema/wat-manifest-v2/0.1.0`
Status: **draft** — schema and pin-tests landed in Phase-1b; the
aggregator code-touchpoint is scheduled.
Audience: implementers of independent verifiers and external auditors
who want to validate Wakir Audit Trail receipts produced by v2-aware
aggregators without depending on the reference runtime.

This document is the public, externally-stable companion to the
internal trigger memo at
`docs/wat-manifest-v2-multi-cap-stub.md`. Where the stub describes
**why** v2 is being introduced and what code-touchpoints land in
which sprint, this spec describes **what** a v2 manifest looks like
on disk and how a verifier MUST treat it.

For v1 semantics see `docs/wat-manifest-spec.md`. v1 remains the
canonical default; v2 is emitted only when the trigger condition
fires (§3 below). The two specs are intended to be read side-by-side
during a v1→v2 migration.

---

## 1. Relationship to v1

v2 is **strictly additive** over v1 at the schema layer. Every v1
field retains identical semantics, identical encoding, and identical
validation rules. v2 introduces two new top-level keys
(`multi_cap_events`, `multi_cap_summary`) and a new value
(`wat-manifest/2.0`) on the existing `version` discriminator.

There are **no removed fields**, **no renamed fields**, and **no
changed validation patterns** between v1 and v2. A v1-only verifier
reading a v2 manifest can ignore the two new top-level keys per the
forward-compatibility rule in `wat-manifest-spec.md` §"Forward
compatibility" and validate the inclusion proof and OTS receipt
correctly. The inclusion-proof and OTS-receipt validation paths are
unchanged by v2.

Multi-cap metadata is **never** an input to `merkle_root`. The root
is computed identically in v1 and v2; only the per-event metadata
exposed alongside it differs.

This relationship is the basis for the migration story in §7.

## 2. File layout

The on-disk layout matches v1 verbatim:

```
<archive>/<YYYY-MM-DDTHH>/
    manifest.json     # carries version: "wat-manifest/2.0" iff trigger fires
    root.bin          # 32-byte raw Merkle root
    root.bin.ots      # OpenTimestamps receipt
    bitcoin_block.txt # optional, written after upgrade finalises
```

Hour slots remain UTC. The aggregator-side trigger decision
(§3) happens before any file is written; once the trigger fires
the manifest is written as v2 atomically. v2 manifests never
overwrite v1 manifests for the same hour — the version is decided
at build time and pinned for the life of the hour.

## 3. Trigger condition

A v2 manifest is emitted **iff** at least one ingested frame in the
hour has `len(caprefs) > 1`. Hours where every frame has zero or one
`caprefs[]` entry continue to emit v1 manifests verbatim.

The trigger is **deterministic** and **strict**:

- Aggregators MUST NOT emit v2 when no frame in the hour has
  multiple caprefs. The schema enforces this through an
  `if/then/not-anyOf` clause: a `wat-manifest/1.0` manifest MUST NOT
  carry `multi_cap_events` or `multi_cap_summary`. Producers that
  find themselves about to emit a v1 manifest with multi-cap sidecar
  keys have a trigger-condition bug — fail closed.
- Aggregators MUST emit v2 when at least one frame has multiple
  caprefs. The schema enforces this through a parallel
  `if-then-required` clause: a `wat-manifest/2.0` manifest MUST
  carry both `multi_cap_events` and `multi_cap_summary`.
- The trigger is evaluated once per hour at aggregator build time.
  Subsequent re-runs of the aggregator over the same hour MUST yield
  the same trigger decision (deterministic given the spool input).

This split is intentional: the common case (single-cap-only hours)
keeps the v1 schema verbatim with no payload bloat, and the
multi-cap case gets the sidecar without conditional verifier logic
peering at every event.

## 4. Schema delta vs v1

v2 adds two top-level keys side-by-side with `events`:

### 4.1 `multi_cap_events`

Per-event sidecar. Keys are `event_id` strings matching the
corresponding entry in `events[]`. Each value is an object with two
required fields:

| field          | type            | constraints                                                                                  |
|----------------|-----------------|----------------------------------------------------------------------------------------------|
| `caprefs_full` | array of string | `minItems: 2`, each item matches `^sha256:[0-9a-f]{64}$`                                     |
| `caprefs_root` | string          | matches `^[0-9a-f]{64}$` (lowercase hex)                                                     |

`additionalProperties` on each entry is `false`.

`caprefs_full` is the verbatim ordered list of capability-token
references as the producer emitted them. The `sha256:` prefix is
explicit so the hash algorithm cannot drift without a schema bump.
The `minItems: 2` constraint is a hard floor: by the trigger
condition only events with >1 capref appear here.

`caprefs_root` is a single SHA-256 hex over the canonical Merkle of
`caprefs_full`. The intended use is for audit queries to compare two
events without iterating the full list, and for verifiers to detect
tampering with `caprefs_full`. The Merkle ordering semantics
(ordered vs sorted) are tracked as **open question OQ-1** (§9).

Events with `len(caprefs) <= 1` are NOT included here even on v2
manifests. The sidecar is strictly the multi-cap subset.

`additionalProperties` at the `multi_cap_events` level is `false`;
all keys must match the `event_id` pattern `^[A-Za-z0-9_.:-]+$`.

### 4.2 `multi_cap_summary`

Hour-level roll-up. Three required integer fields:

| field                                     | constraint    | meaning                                                                                                       |
|-------------------------------------------|---------------|---------------------------------------------------------------------------------------------------------------|
| `events_with_multi_cap`                   | `minimum: 1`  | count of events with `len(caprefs) > 1`                                                                       |
| `max_caprefs_in_any_event`                | `minimum: 2`  | largest `len(caprefs)` observed in the hour                                                                   |
| `distinct_capability_token_hashes_in_hour`| `minimum: 1`  | count of distinct hashes across the union of `caprefs[]` from all events (v2 frames + v1-equivalent caprefs[0])|

`additionalProperties` is `false`.

The summary is a pure roll-up — brand pages and ops dashboards can
render it without scanning `multi_cap_events`. Aggregators MUST
keep `multi_cap_summary` consistent with `multi_cap_events`;
mismatch is a producer bug, not a schema-allowed degree of freedom.

### 4.3 `version` discriminator

The `version` field gains one additional valid value:

| value                   | semantics                                                                |
|-------------------------|--------------------------------------------------------------------------|
| `wat-manifest/1.0`      | v1 — must NOT carry `multi_cap_events` or `multi_cap_summary`            |
| `wat-manifest/2.0`      | v2 — MUST carry both sidecar keys, trigger condition fired               |

The `version` enum is closed; schema-validators reject any other
value. Adding a future `wat-manifest/3.0` requires a new schema
file with a new `$id`.

### 4.4 `signature` slot (schema 0.2.0, Phase-2)

Schema 0.2.0 adds an additive **optional** top-level `signature`
slot. Absence is permitted on both `wat-manifest/1.0` and
`wat-manifest/2.0` envelopes — legacy unsigned manifests continue
to validate. When present, the slot is a detached Ed25519
signature block with the following shape:

| field       | type   | constraints                                                            |
|-------------|--------|------------------------------------------------------------------------|
| `alg`       | string | enum `["Ed25519"]` (closed; future algorithms require additive bump)   |
| `kid`       | string | `minLength: 1` (non-empty key identifier)                              |
| `signature` | string | `^[0-9a-f]{128}$` (64-byte Ed25519 signature as 128 lowercase hex)     |

`additionalProperties` on the slot is `false`. The pre-image is
SHA-256 of the RFC-8785 JCS canonicalisation of the manifest
payload with the `signature` slot stripped (byte-identical to the
AIP-document and schema-registry-entry signing conventions). The
signing primitive that emits exactly this shape is
`wat.identity.manifest_signing.sign_manifest`.

`kid` references an AIP-document `public_keys` entry under
`PURPOSE_WAT_ANCHOR`; the resolver bridge is
`wat.identity.anchor_kid.resolve_wat_anchor_kid`.
Schema-validation does NOT require the kid to resolve — that is a
verifier-side concern (resolver wire-up).

**Schema-version bump rationale (additive minor).** 0.1.0 → 0.2.0
is additive only: `signature` is added to the top-level
`properties` map, NOT to the top-level `required` array. Existing
0.1.0-conformant manifests (with or without multi-cap sidecars,
signed or unsigned) validate identically against 0.2.0. The `$id`
URL changes from `…/wat-manifest-v2/0.1.0` to `…/wat-manifest-v2/0.2.0`;
consumers that pin the URL must update their pin. Consumers that
fetch by stem (`wat-manifest-v2`) and rely on schema-discovery
need no change.

**Interaction with the v1-`not.anyOf` clause.** The existing
conditional that forbids `multi_cap_events` / `multi_cap_summary`
on v1 manifests is unchanged: `signature` is not in that
forbid-list, so v1 + `signature` is a valid combination
(unsigned-aware verifiers reading a signed v1 manifest can ignore
the slot just like they ignore the v2 sidecar keys when version
is v1, but here on v1 manifests this slot is permitted).

## 5. Verifier behaviour

A v2-aware verifier processing `wakir-verify <event_id>`:

1. Parse the manifest, validate top-level structure against the
   schema. Reject on schema-validation failure.
2. Run all v1 checks unchanged: leaf-hash recompute from the
   four-tuple, inclusion proof through `tree_levels`, OTS-receipt
   chain to a Bitcoin attestation (or report `pending` if not yet
   anchored).
3. **If** the manifest version is `wat-manifest/2.0` **and** the
   event_id appears as a key in `multi_cap_events`:
   - Re-derive `caprefs_root` over `caprefs_full` using the
     project-canonical Merkle (ordered semantics per OQ-1
     proposal; locked by Zone-2 sign-off).
   - Compare against the `caprefs_root` claimed in the manifest.
     Mismatch → exit code `1` with reason `multi_cap_root_mismatch`.
   - In human-mode output append a line `multi_cap: <count>
     capabilities (root=<8 hex>...)`.
   - In `--output json` mode (frontend-engineering
     deliverable): include `caprefs_full[]` and `caprefs_root` in
     the result object.
4. **Otherwise** (v1 manifest, or v2 manifest without the event in
   `multi_cap_events`): behaviour identical to v1.

`--chain-check` semantics are unchanged. The multi-cap layer is
purely metadata and never affects the Bitcoin-anchor validation
path or the chain-walk through `prev_hour_root`.

### 5.1 Exit codes

| code | meaning                                               | introduced |
|------|-------------------------------------------------------|------------|
| `0`  | verified                                              | v1         |
| `1`  | failed (leaf-hash, inclusion proof, OTS, or new: `multi_cap_root_mismatch`) | v1 (semantics extended in v2) |
| `3`  | pending (OTS not yet finalised on Bitcoin)            | v1         |
| `4`  | chain-mismatch (`prev_hour_root` does not match prev hour) | v1 |

Exit codes are stable contract. v2 does not introduce a new exit
code; multi-cap-root mismatch is a sub-case of generic verification
failure (`1`) and is distinguished only by the human-readable
reason string and the JSON-mode `failure_reason` field.

### 5.2 v1-only verifier reading a v2 manifest

A v1-only verifier reads a v2 manifest and:

- Recognises `version` as outside its built-in enum but does not
  fail (forward-compatibility rule).
- Ignores the two unknown top-level keys
  (`multi_cap_events`, `multi_cap_summary`).
- Validates leaf-hash, inclusion proof, OTS receipt as in v1.
- Reports the v1 result.

This is the **explicit fallback path** for legacy verifiers in the
field. The audit query layer loses access to multi-cap metadata
under this fallback, but the inclusion proof remains valid. Audit
operators who need multi-cap data must upgrade their verifier; they
do not need to re-anchor or re-emit any manifest.

### 5.3 Optional manifest-signature wire-up (Phase-2)

Since Phase-2 the reference verifier
(`wat/verify/manifest_v2.py`) carries an **opt-in** consumer for the
optional `signature` slot landed in (schema 0.2.0,
§4.4). The wire-up is OFF by default to preserve backward
compatibility for the earlier test cohort and for external
verifiers that have not yet adopted the optional slot. Opt-in is
the only path; the verifier never auto-detects slot presence to
flip into signature-checking mode, because doing so would couple
the integrity verdict to the absence of a caller-supplied public
key.

Surface:

- Python API: `verify_manifest_v2_file(..., verify_signature=True,
  verify_signature_public_key=<32 raw bytes>, verify_signature_mode=
  VerifyMode.PERMISSIVE | VerifyMode.STRICT)`.
- CLI: `--verify-signature` + `--verify-signature-public-key-hex
  <64-hex>` + `--verify-signature-strict` (flag → STRICT mode,
  default PERMISSIVE).
- Env-var: `WAKIR_VERIFY_MANIFEST_SIGNATURE=1` flips opt-in without
  changing call sites — mirrors `WAKIR_OTS_FULL_VERIFY=1`.

The `signature_status` field on `ManifestV2Result` (mirrored in
`as_dict()['signature_status']`) reports one of:

| value | meaning |
|---|---|
| `""` | verification not requested (default opt-in surface). |
| `"verified"` | slot present, signature verified cryptographically. |
| `"unsigned-permissive"` | no slot, PERMISSIVE mode accepted. |
| `"unsigned-strict"` | no slot, STRICT mode rejected (forces `integrity_ok=False`). |
| `"mismatch"` | slot present, well-formed, did NOT verify (forces `integrity_ok=False`). |
| `"structural-error"` | slot malformed OR public-key missing under a signed-manifest path (forces `integrity_ok=False`). |

Phase ordering inside `verify_manifest_v2_file`: schema →
trigger-discipline → event-count → leaves-match → merkle-root →
multi-cap-root (v2 only) → signature (when opted in). The
signature phase is the *last* verdict because cryptographic
checking is only meaningful against a structurally consistent
manifest; a tampered-body manifest that broke merkle-root upstream
never reaches the signature phase.

The signing primitive itself
(`wat.identity.manifest_signing.verify_manifest_signature`) is the
canonical implementation; this wire-up is a thin consumer that
maps the primitive's return values into the verifier's failure-
reason taxonomy. The `kid` field inside a signature slot is
captured for downstream auditing; the kid → public-key resolver
bridge (`wat.identity.anchor_kid.resolve_wat_anchor_kid`) is not
yet wired into the verifier — callers supply the raw public key
directly. Resolver wire-up is a follow-up item gated on the
Cross-Review-Zone-1 boundary with Identity-Substrate-engineering.

The `--real-manifest` path **does** honour the signature kwargs
since Phase-2: `verify_real_manifest_file` accepts
the same three kwargs (`verify_signature`,
`verify_signature_public_key`, `verify_signature_mode`) and
`RealManifestResult` carries the same `signature_status` field
with the same six pinned values. Phase-ordering is the same
(signature is the LAST gate, after fields, integrity,
multi-cap-root, and OTS-anchor). The wire-up is OFF by default,
so every earlier caller of `verify_real_manifest_file` sees
identical behaviour and `signature_status` left empty.

The schema-file `wakir-wat-manifest-v1.json` was bumped
`0.1.0 → 0.2.0` on to add the optional `signature`
top-level slot byte-for-byte identical to the v2-schema 0.2.0 slot
(§4.4). Stock TV-2 real-manifest fixtures stay unsigned (the
Production aggregator does not emit signed envelopes today); the
hermetic tests hand-sign deep-copies in `tmp_path` and feed
them through the full `verify_real_manifest_file` pipeline. When
the signing-aggregator branch lands in Phase-2+, the verifier
already accepts its output without further change. The CLI driver
`scripts/external_verifier_validation.py --real-tv2` does NOT yet
expose `--verify-signature`: the cohort is unsigned, so there is
no signed real-manifest to drive — the driver-side wire-up is a
follow-up gated on the signing-aggregator branch
landing.

## 6. Aggregator behaviour (informational)

This section is informational for verifier authors who want to
understand what the producer side does. The contract is the schema
plus §3 trigger condition — verifiers MUST NOT depend on
implementation details below.

```python
def build_manifest(events, hour_slot, ...):
    multi_cap_events = {
        evt.event_id: {
            "caprefs_full": evt.caprefs,
            "caprefs_root": _caprefs_merkle_root(evt.caprefs),
        }
        for evt in events
        if len(evt.caprefs) > 1
    }
    if not multi_cap_events:
        return _build_v1(events, hour_slot, ...)  # version: wat-manifest/1.0
    v1 = _build_v1(events, hour_slot, ...)
    v1["version"] = "wat-manifest/2.0"
    v1["multi_cap_events"] = multi_cap_events
    v1["multi_cap_summary"] = _summary(events, multi_cap_events)
    return v1
```

This shape preserves the v1 build path as the canonical default and
adds v2 only when triggered. No regression risk for the common case.

The aggregator code-touchpoint (`wat/aggregator.py` or current
equivalent — TBD pending a file walk) is the only
place the trigger decision is taken.

## 7. v1 → v2 migration

The v1 → v2 transition is **additive at the writer side and
default-flip at the reader side**, mirroring the chain-check
migration documented in `wat-manifest-spec.md`.

### 7.1 Writer-side migration (aggregator)

- Bump emitted `version` to `wat-manifest/2.0` only when the trigger
  condition fires. No mass rewrite of existing v1 manifests.
- v1 manifests already on disk remain v1 forever — they were emitted
  for hours that genuinely had no multi-cap frames, and the v1
  schema describes them correctly.
- The writer-side change is a single `if multi_cap_events: emit v2`
  branch in the aggregator build path. No schema migrations on
  historical archives. No re-anchoring of receipts.

### 7.2 Reader-side migration (verifier)

- Existing v1 verifiers continue to work against v1 manifests
  unchanged.
- Existing v1 verifiers read v2 manifests as forward-compatible
  unknown-version-with-extra-fields — they validate the inclusion
  proof and OTS receipt correctly and silently drop the multi-cap
  metadata. This is the explicit graceful-fallback path.
- v2-aware verifiers handle both versions: v1 with v1 semantics,
  v2 with the additional multi-cap-root recompute step (§5).
- There is no reader-side flag to flip on the migration to v2 —
  v2-awareness is built in once the verifier ships with the v2
  schema bundled.

### 7.3 Audit-query-layer migration

Audit queries of the form "did agent X exercise capability Y in
hour H?" gain richer answers under v2:

- v1 manifests: query inspects `events[].capability_token_hash`,
  which is `caprefs[0]` for multi-cap frames (lossy projection).
- v2 manifests: query inspects `multi_cap_events[event_id]
.caprefs_full[]` for full capability set, plus the v1-projected
  `caprefs[0]` in `events[].capability_token_hash` for backwards-
  compatible single-cap queries.

The v2 audit-query semantics are a **strict superset** of v1 — no
query that worked on v1 will fail on v2, but new queries (multi-cap
intersection, capability-set-equality across events) only return
useful results on v2 manifests.

### 7.4 No breaking changes

Summary of guarantees across the v1→v2 transition:

- v1 manifests never need to be rewritten.
- v1 OTS receipts never need to be re-anchored.
- v1 verifiers never need to be upgraded (they keep reading what
  they already read; new metadata is invisible to them).
- v1 audit queries never break (v2 keeps `events[].capability_token
  _hash` populated for every frame, including multi-cap ones, with
  the v1-projected `caprefs[0]` value).

## 8. Backward compatibility (verifier perspective)

| verifier ↓ \ manifest →     | v1                            | v2                                           |
|-----------------------------|-------------------------------|----------------------------------------------|
| v1-only                     | full validation               | inclusion + OTS validation; multi-cap silently dropped |
| v2-aware                    | full validation, multi-cap path skipped | full validation including multi-cap-root recompute |

A verifier MUST NOT fail a manifest solely because its `version` is
unknown. v2-aware verifiers MUST recognise both
`wat-manifest/1.0` and `wat-manifest/2.0`; future-version verifiers
MUST tolerate values they do not recognise per the forward-
compatibility rule.

A verifier that finds itself unable to recompute `caprefs_root` (for
example because the canonical Merkle ordering is locked to a
project-side decision the verifier author has not yet adopted) MUST
either:

- Skip the multi-cap-root check and emit a warning (lenient mode), or
- Refuse to validate the manifest and emit a clear error (strict
  mode).

The reference verifier ships in strict mode; downstream verifiers
choose their own posture.

## 9. Open questions (must resolve before implementation)

These mirror the open questions in the stub spec
(`docs/wat-manifest-v2-multi-cap-stub.md` §8) but are restated here
because they directly affect external-verifier interop.

**OQ-1 — RATIFIED 2026-05-07: Ordered Merkle for `caprefs_root`.**
Decision: **ordered Merkle** (Variante A) — preserves producer /
issuance intent per WAT-Phase-1a-Spec §3.4.1. Sign-off:
wirelang-engineering Cross-Review-Zone-2, 2026-05-07T11:48:09Z.
External verifier authors MUST adopt
the ordered convention; the reference verifier
(`wat.verify.manifest_v2`) ships with strict-mode default ON
since (2026-05-07). Lenient mode
(`--no-strict-multi-cap-root`) remains available as an escape
hatch for downstream verifiers that have not yet adopted the
locked ordering.

**OQ-2: Empty `multi_cap_events: {}` on a forced v2 manifest.**
Current proposal: never. Trigger condition is strict — v2 manifests
always have at least one entry in `multi_cap_events`. The schema
enforces this via the closed `version` enum and the `if-then-
required` clause; aggregators that generate empty `multi_cap_events`
on v2 are buggy.

**OQ-3: Verifier `--manifest-version` strict-mode override flag.**
Current proposal: defer to unless an audit-query test plan
demands it earlier. External verifiers do not need this flag for
correct v1/v2 handling — version-detection from the manifest itself
is sufficient.

**OQ-4: Test-vector for multi-cap hour.**
Current proposal: TV-4 (multi-cap-hour Bitcoin-anchor live-stamp).
Coordinated with qa-engineering at the QA-handover slot. External
verifier conformance suites will pin against TV-4 once it lands
.

**OQ-1 implementation pin (post-ratification):**
the canonical Merkle ordering is the ordered-Merkle convention
implemented in
`wat.verify.manifest_v2._caprefs_canonical_root_ordered`
(`caprefs_full[i]` is hashed left-to-right in producer / issuance
order; SHA-256 leaves; standard pair-hash internal nodes;
duplicate-last-on-odd-count pad). External verifiers that adopt
this convention can run in strict mode and validate
`caprefs_root` against the recompute. Verifiers that have not
yet adopted it MUST use lenient mode and emit a
`multi_cap_root_status="deferred"` warning.

## 10. Reference artefacts

- Schema: `wirelang/schemas/wat-manifest-v2.json` (Draft 2020-12).
- Pin tests: `tests/wat/test_manifest_v2_schema_smoke.py` (22 tests,
  pinning every schema-level invariant called out in §3 / §4).
- Stub spec / sprint trigger: `docs/wat-manifest-v2-multi-cap-stub.md`.
- v1 spec (companion document): `docs/wat-manifest-spec.md`.
- Aggregator implementation: `wat/aggregator.py` (
  code-touchpoint, not yet landed).
- Event-centric verifier: `wat.verify.cli` (
  code-touchpoint for the multi-cap-root recompute branch, not yet
  landed).
- **Manifest verifier-stub:** `wat.verify.manifest_v2`
  (**landed**) — single-file cross-module
  integrity checker complementing the schema-only smoke tests.
  Reference fixture at
  `tests/fixtures/wat-manifest-v2/sample-multi-cap-hour.json`;
  hermetic test suite in
  `tests/wat/test_manifest_v2_verifier_stub.py`.

### Verifier-stub JSON-output schema

The CLI `python -m wat.verify.manifest_v2 --output json` emits a
single-line JSON object per run. Schema is **manifest-centric**
(single-file outcome) and is intentionally distinct from the
event-centric `wakir verify --output json` schema (follow-up,
per-event-id audit-result aggregated across an archive). Frontend
hour-aggregate / multi-receipt snapshots aggregate on top of the
manifest-centric record rather than expecting a 1:1 field map.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string literal `"wakir-verify-manifest-v2/0"` | Version-pin so consumers can branch on a future `/1` without probe-by-field heuristics. Additive-only changes within `/0`. |
| `manifest_path` | string | Echo of the input path (operators do not have to reconstruct from CLI invocation). |
| `manifest_version` | string | The `version` field as read from the manifest (e.g. `"wat-manifest/2.0"`); empty string when parsing did not reach that field. |
| `ok` | boolean | True iff `schema_ok` and `integrity_ok` both true. |
| `schema_ok` | boolean | JSON-Schema validation outcome. |
| `integrity_ok` | boolean | Cross-module integrity outcome (event-count / leaves / merkle_root / multi-cap sidecar consistency). |
| `multi_cap_root_status` | string enum: `"verified" \| "deferred" \| "mismatch" \| ""` | Empty string for v1 manifests. `"verified"` is the strict-mode default since (OQ-1 ratified ordered-Merkle 2026-05-07); `"deferred"` is emitted only under explicit `--no-strict-multi-cap-root` lenient mode. |
| `signature_status` | string enum: `"" \| "verified" \| "unsigned-permissive" \| "unsigned-strict" \| "mismatch" \| "structural-error"` | Phase-2 opt-in field. Empty when signature verification not requested (default). See §5.3 for the full decision matrix. Additive within `wakir-verify-manifest-v2/0` (existing `/0` consumers see a new optional key, never a removed one). |
| `failure_reason` | string | `"<phase>: <message>"` on failure where `<phase>` is one of `schema`, `integrity`, `multi_cap_root`, `signature`. Empty on success. |

JSON keys are sorted (`json.dumps(..., sort_keys=True)`) so the
byte-output is stable for downstream diffing / snapshot-tests.
Exit codes are unchanged from human-mode (0 ok, 1 fail).

### Audit-trail-entry export contract

The CLI `python -m wat.verify.manifest_v2 --output audit-trail-entry`
emits a single-line JSON object that matches the **paired-update
contract** with the frontend `AuditTrailEntry` consumer
(`infra/repos-skeleton/site/src/data/wakir-audit-trail-sample.ts`,
published in the frontend brand memo). It is shape-
distinct from the manifest-centric `--output json` schema above —
this format is for the audit-trail-browser timeline, that one is
for single-file verifier-result snapshots.

Pinned twelve keys, additive-only across `schema_version`
`wakir-verify-manifest-v2/0` (eleven → twelve bumped in
Phase-2; `signature_status` added additively):

| Field | Type | Meaning |
|---|---|---|
| `kind` | string literal `"wat-tv-pin-pack"` | Pinned kind discriminator. A future v3 producer would land as a separate kind, never re-purpose this one. |
| `schema_version` | string literal `"wakir-verify-manifest-v2/0"` | Same string as `--output json`. Consumers branch on a single field. |
| `identity` | string | Short display string. `"wat-hour <slot>"` if `hour_slot` known, else echo of `manifest_path`. Render-only; never load-bearing. |
| `manifest_version` | string | The manifest's `version` field (e.g. `"wat-manifest/2.0"`). Empty if parsing failed before that field. |
| `manifest_path` | string | Echo of input path. |
| `hour_slot` | string | The manifest's `hour_slot` if available, else empty string. |
| `event_count` | int | Number of events in the manifest, else `-1`. Never `null`. |
| `anchor_root_hex` | string | The manifest's `merkle_root` (64 lowercase hex, NO `"sha256:"` prefix), else empty string. The frontend re-prefixes at render-time when desired. |
| `branches` | list | Exactly one entry: `{label: "manifest-validity", verdict: "verified" \| "rejected" \| "pending", detail: <human string>}`. `verified` is the strict-mode default for clean v2 manifests since (OQ-1 ratified). `pending` is emitted only under explicit `--no-strict-multi-cap-root` lenient mode (escape hatch for downstream verifiers that have not yet adopted the locked ordering). |
| `ok` | bool | Mirror of `--output json` `ok`. Allows short-circuit without parsing `branches`. |
| `failure_reason` | string | `"<phase>: <message>"` on failure, empty on success. Mirrors `--output json`. |
| `signature_status` | string enum: `"" \| "verified" \| "unsigned-permissive" \| "unsigned-strict" \| "mismatch" \| "structural-error"` | Phase-2 additive key. Mirrors `--output json` `signature_status`. Empty string when signature verification was NOT requested by the caller — frontends MUST treat empty-string as "no signature verdict available" rather than "unsigned" (the unsigned states are explicit values, not empty). The `branches[]` field is unchanged — the signature phase does NOT add a branch entry; consumers that want to render the signature verdict read this top-level key directly. A future schema version may add a second `branches[]` entry for the signature phase, gated on Cross-Review with frontend-engineering. |

**Determinism guarantees:**

- Key set is exactly the twelve keys above. No optional / conditional
  keys appear. Missing data renders as empty string / `-1` / empty
  list — never as `null` or absent.
- `json.dumps(..., sort_keys=True, ensure_ascii=False)` over the dict
  yields a canonical wire-form suitable for snapshot tests, content-
  hashing, and re-import.
- Field types are stable across ok-paths and failure-paths
  (pinned in
  `tests/wat/test_manifest_v2_verifier_stub.py::test_as_audit_trail_entry_field_types_are_stable`).
- `anchor_root_hex` rejects non-canonical input (uppercase, wrong
  length, with `"sha256:"` prefix) — wire-format must match the
  `wat-manifest-v2.json` schema's bare-hex pattern.

**Schema-version evolution rule:** a future revision that adds a
field stays at `/0` if the addition is purely additive (e.g., a new
optional `caprefs_root_hex` field is additive). A breaking change
(rename, type change of an existing field) bumps to `/1`. Consumers
that need to handle both versions branch on `schema_version`.

The Python in-process API is `ManifestV2Result.as_audit_trail_entry(
*, anchor_root_hex="", hour_slot="", event_count=None)`. Callers
that already have the parsed manifest in hand should pass the three
optional fields explicitly; the CLI re-parses the manifest under
the hood for these fields, which is wasted I/O when caller-side data
is available.

The schema file is the contract; this document describes the
contract in prose. If the two ever disagree, the schema is
authoritative for structural validation and this document is
authoritative for semantic and behavioural rules (§3 trigger,
§5 verifier behaviour, §7 migration). The reference implementation
is informative only.

## 11. Change log

Schema-level history. Per-release engineering detail lives in the git
history (tag `archive/pre-phase-4`) and in the PRs referenced below.

| Schema | Change | Reference |
| --- | --- | --- |
| 0.1.0 | Initial formal v1 manifest schema: hour-root, leaf count, `prev_hour_root` chaining, OTS side-file contract. | §2, §3 |
| 0.2.0 | Additive optional `signature` slot (Ed25519 over the JCS-canonical manifest without the slot), `signature_status` on the verifier result, `--verify-signature` / `--verify-signature-strict` driver modes, multi-cap consistency check on by default. | §4.4, §5.3 |

Compatibility rule for every future entry: a schema bump that adds an
optional key is additive and MUST keep earlier manifests verifiable;
anything else is a new major schema id.
