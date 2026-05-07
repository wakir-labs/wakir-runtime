<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT Hour-Manifest v2 — Format Specification

Schema-Version: `wat-manifest/2.0`
Schema-`$id`: `https://wakir.dev/wirelang/schema/wat-manifest-v2/0.1.0`
Status: **draft / Sprint-2 prep** — schema and pin-tests landed
Phase-1b Tag-26 / Tag-27, aggregator code-touchpoint scheduled
Sprint-2 Tag-1.
Audience: implementers of independent verifiers and external auditors
who want to validate Wakir Audit Trail receipts produced by v2-aware
aggregators without depending on the reference runtime.

This document is the public, externally-stable companion to the
internal Sprint-2 trigger memo at
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
     proposal; locked by Zone-2 sign-off in Sprint-2).
   - Compare against the `caprefs_root` claimed in the manifest.
     Mismatch → exit code `1` with reason `multi_cap_root_mismatch`.
   - In human-mode output append a line `multi_cap: <count>
     capabilities (root=<8 hex>...)`.
   - In `--output json` mode (Sprint-1 Tag-25 pickup, frontend-engineering
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
| `4`  | chain-mismatch (`prev_hour_root` does not match prev hour) | v1, Tag-8 |

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
equivalent — TBD pending file walk in Sprint-2 Tag-1) is the only
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

## 9. Open questions (must resolve before Sprint-2 implementation)

These mirror the open questions in the stub spec
(`docs/wat-manifest-v2-multi-cap-stub.md` §8) but are restated here
because they directly affect external-verifier interop.

**OQ-1: Ordered vs sorted Merkle for `caprefs_root`.**
Current proposal: ordered Merkle (preserves producer intent per
WAT-Phase-1a-Spec §3.4.1). Sign-off pending wirelang-engineering
Zone-2 review (open as of Tag-27, expected Sprint-2 Tag-1). External verifier authors MUST NOT independently choose an
ordering; the canonical decision will be locked in §4 of this spec
once Zone-2 signs off.

**OQ-2: Empty `multi_cap_events: {}` on a forced v2 manifest.**
Current proposal: never. Trigger condition is strict — v2 manifests
always have at least one entry in `multi_cap_events`. The schema
enforces this via the closed `version` enum and the `if-then-
required` clause; aggregators that generate empty `multi_cap_events`
on v2 are buggy.

**OQ-3: Verifier `--manifest-version` strict-mode override flag.**
Current proposal: defer to Sprint-3 unless an audit-query test plan
demands it earlier. External verifiers do not need this flag for
correct v1/v2 handling — version-detection from the manifest itself
is sufficient.

**OQ-4: Test-vector for multi-cap hour.**
Current proposal: TV-4 (multi-cap-hour Bitcoin-anchor live-stamp).
Coordinated with qa-engineering at the QA-handover slot. External
verifier conformance suites will pin against TV-4 once it lands
(Sprint-2 Tag-7+).

When OQ-1 resolves, this spec gets a §4.1.1 sub-section pinning
the canonical Merkle ordering and a normative reference to the
implementation. Until then, external verifiers in strict mode
should treat the multi-cap-root check as **provisional** and may
emit a warning indicating the ordering is not yet locked.

## 10. Reference artefacts

- Schema: `wirelang/schemas/wat-manifest-v2.json` (Draft 2020-12).
- Pin tests: `tests/wat/test_manifest_v2_schema_smoke.py` (22 tests,
  pinning every schema-level invariant called out in §3 / §4).
- Stub spec / sprint trigger: `docs/wat-manifest-v2-multi-cap-stub.md`.
- v1 spec (companion document): `docs/wat-manifest-spec.md`.
- Aggregator implementation: `wat/aggregator.py` (Sprint-2 Tag-1
  code-touchpoint, not yet landed).
- Verifier implementation: `wat.verify.cli` (Sprint-2 Tag-4-5 code-
  touchpoint, not yet landed).

The schema file is the contract; this document describes the
contract in prose. If the two ever disagree, the schema is
authoritative for structural validation and this document is
authoritative for semantic and behavioural rules (§3 trigger,
§5 verifier behaviour, §7 migration). The reference implementation
is informative only.

## 11. Change log

- **2026-05-07 (Tag-27.5):** Initial draft of this consolidated
  external-verifier spec. Schema-File and 22 pin-tests already
  landed in Tag-26 / Tag-27. OQ-1 still open pending Zone-2.
- **2026-05-06 (Tag-26):** Schema file `wat-manifest-v2.json` and
  inline smoke tests (4) landed.
- **2026-05-07 (Tag-27):** Pin-test suite expanded to 22 tests in
  `tests/wat/test_manifest_v2_schema_smoke.py`.

---

— Tomás
