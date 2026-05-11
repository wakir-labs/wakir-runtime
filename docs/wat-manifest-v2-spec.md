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

**OQ-1 — RATIFIED 2026-05-07: Ordered Merkle for `caprefs_root`.**
Decision: **ordered Merkle** (Variante A) — preserves producer /
issuance intent per WAT-Phase-1a-Spec §3.4.1. Sign-off:
wirelang-engineering Cross-Review-Zone-2, 2026-05-07T11:48:09Z.
External verifier authors MUST adopt
the ordered convention; the reference verifier
(`wat.verify.manifest_v2`) ships with strict-mode default ON
since Sprint-2 Tag-4 (2026-05-07). Lenient mode
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
Current proposal: defer to Sprint-3 unless an audit-query test plan
demands it earlier. External verifiers do not need this flag for
correct v1/v2 handling — version-detection from the manifest itself
is sufficient.

**OQ-4: Test-vector for multi-cap hour.**
Current proposal: TV-4 (multi-cap-hour Bitcoin-anchor live-stamp).
Coordinated with qa-engineering at the QA-handover slot. External
verifier conformance suites will pin against TV-4 once it lands
(Sprint-2 Tag-7+).

**OQ-1 implementation pin (post-ratification, Sprint-2 Tag-4):**
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
- Aggregator implementation: `wat/aggregator.py` (Sprint-2 Tag-1
  code-touchpoint, not yet landed).
- Event-centric verifier: `wat.verify.cli` (Sprint-2 Tag-4-5
  code-touchpoint for the multi-cap-root recompute branch, not yet
  landed).
- **Manifest verifier-stub:** `wat.verify.manifest_v2` (Sprint-2
  Tag-1 code-touchpoint, **landed**) — single-file cross-module
  integrity checker complementing the schema-only smoke tests.
  Reference fixture at
  `tests/fixtures/wat-manifest-v2/sample-multi-cap-hour.json`;
  hermetic test suite in
  `tests/wat/test_manifest_v2_verifier_stub.py`.

### Verifier-stub JSON-output schema

The CLI `python -m wat.verify.manifest_v2 --output json` emits a
single-line JSON object per run. Schema is **manifest-centric**
(single-file outcome) and is intentionally distinct from the
event-centric `wakir verify --output json` schema (Tag-25 pickup,
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
| `multi_cap_root_status` | string enum: `"verified" \| "deferred" \| "mismatch" \| ""` | Empty string for v1 manifests. `"verified"` is the strict-mode default since Sprint-2 Tag-4 (OQ-1 ratified ordered-Merkle 2026-05-07); `"deferred"` is emitted only under explicit `--no-strict-multi-cap-root` lenient mode. |
| `failure_reason` | string | `"<phase>: <message>"` on failure where `<phase>` is one of `schema`, `integrity`, `multi_cap_root`. Empty on success. |

JSON keys are sorted (`json.dumps(..., sort_keys=True)`) so the
byte-output is stable for downstream diffing / snapshot-tests.
Exit codes are unchanged from human-mode (0 ok, 1 fail).

### Audit-trail-entry export contract

The CLI `python -m wat.verify.manifest_v2 --output audit-trail-entry`
emits a single-line JSON object that matches the **paired-update
contract** with the frontend `AuditTrailEntry` consumer
(`infra/repos-skeleton/site/src/data/wakir-audit-trail-sample.ts`,
published in Sprint-Frontend-1 Tag-3 outbox memo). It is shape-
distinct from the manifest-centric `--output json` schema above —
this format is for the audit-trail-browser timeline, that one is
for single-file verifier-result snapshots.

Pinned eleven keys, additive-only across `schema_version`
`wakir-verify-manifest-v2/0`:

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
| `branches` | list | Exactly one entry: `{label: "manifest-validity", verdict: "verified" \| "rejected" \| "pending", detail: <human string>}`. `verified` is the strict-mode default for clean v2 manifests since Sprint-2 Tag-4 (OQ-1 ratified). `pending` is emitted only under explicit `--no-strict-multi-cap-root` lenient mode (escape hatch for downstream verifiers that have not yet adopted the locked ordering). |
| `ok` | bool | Mirror of `--output json` `ok`. Allows short-circuit without parsing `branches`. |
| `failure_reason` | string | `"<phase>: <message>"` on failure, empty on success. Mirrors `--output json`. |

**Determinism guarantees:**

- Key set is exactly the eleven keys above. No optional / conditional
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

- **2026-05-11 (Sprint-4 Tag-4):** Brand-Demo-Verifier Cross-Module
  byte-coordination pinned. A hypothetical Brand-Demo-Snapshot emitter
  (per `docs/wat-brand-asset-snapshot-spec.md` §3.5, §4) spans three
  layers: the WAT-Identity-Layer verifier (`wat.verify.manifest_v2`),
  the v1+v2 schema-files (`wirelang/schemas/wakir-wat-manifest-v1.json`
  and `wat-manifest-v2.json`), and real OTS receipts (e.g. the TV-3
  T17 fixture). Existing tests cover each layer in isolation. Tag-4
  adds six Cross-Module tests that pin byte-coordination across layer
  boundaries: (1) `manifest.merkle_root` hex equals `root.bin.hex()`
  and `len(root.bin) == 32`; (2) `verify_real_manifest_file(...,
  use_schema_file=True)` passes the TV-3 wire-form against the v1
  schema-file end-to-end (schema + in-code fields + integrity rebuild
  + OTS side-files); (3) feeding the v1 wire-form through
  `verify_manifest_v2_file` correctly rejects at the schema layer
  (`additionalProperties: false` on `prev_hour_root`, version enum
  mismatch), pinning the intentional v1-vs-v2 wire-form divergence as
  a test invariant; (4) the v2 sample-multi-cap-hour fixture passes
  full v2 pipeline with `multi_cap_root_status == "verified"` under
  strict mode; (5) the four Brand-Snapshot anchor fields (`hour_slot`,
  `merkle_root`, `prev_hour_root`, `event_count`) are byte-pluckable
  from the TV-3 manifest, satisfy v1-schema regex constraints
  (`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}$` for `hour_slot`,
  `^[0-9a-f]{64}$` for `merkle_root`), and are byte-consistent with
  `root.bin`; (6) end-to-end pipeline against a hermetic `tmp_path`
  copy of TV-3 T17 with independent byte-pin of the OpenTimestamps
  magic-header bytes (`\x00OpenTimestamps\x00`, 16 bytes) before the
  verifier touches the file, asserting every `OtsAnchorCheck`
  discriminator (`root_bin_present`, `root_bin_matches_manifest`,
  `ots_present`, `ots_magic_ok`). All six tests are hermetic; tests
  using the schema-file path use `pytest.importorskip("jsonschema")`
  so they skip cleanly when the optional dependency is absent. New
  module `tests/wat/test_brand_demo_cross_module_anchor_pins.py`
  (6 tests). Test-suite delta +6 (304 -> 310 passed; 25 skipped
  unchanged). Acceptance-belege Phase-1b -> 1c: this is the first
  test module that asserts Cross-Module byte-coordination across all
  three Brand-Demo-relevant layers in one place, replacing implicit
  per-layer assumptions with explicit assertions.
- **2026-05-11 (Sprint-4 Tag-2):** hermetic live-path coverage for the
  off-default `ots verify`-Voll-Integration (Sprint-3 Tag-4). The
  existing Tag-4 hermetic suite (`test_ots_full_verify.py`) monkey-
  patches `wat.anchor.ots_anchor.verify_receipt` at the wrapper
  surface; that pins the manifest-v2 verifier-contract but leaves
  `verify_receipt` itself covered only by the live-gated
  `OTS_INTEGRATION_TEST=1` smokes (real `ots` CLI on `$PATH`, real
  network round-trip to Esplora). Tag-2 adds five hermetic tests that
  mock the two boundaries below `verify_receipt` instead: the
  `subprocess.run` call into the `ots` CLI (intercepted by patching
  `ots_anchor.subprocess.run` plus `ots_anchor._resolve_ots_binary`)
  and `wat.anchor.esplora.lookup_block_with_cache`. The five shapes
  are (1) local-node `ots verify` returns `Success!`; (2) local-node
  pending plus `ots info` yields one `BitcoinBlockHeaderAttestation`
  height and Esplora confirms; (3) `ots info` yields zero heights,
  truly unfinalised, hard reject; (4) heights present but Esplora
  raises `EsploraError`, hard reject (no soft skip); (5) `ots verify`
  raises `subprocess.TimeoutExpired`, translated to `AnchorError`,
  surfaced as `full_verify_skipped_reason`, `ok` stays True at the
  magic-header pin. Each test pins the
  (`full_verify_attempted`, `full_verify_ok`, `full_verify_skipped_reason`)
  discriminator triple, not just `ok`, so a future refactor that
  silently re-classifies a hard reject as a soft skip breaks a test.
  New module `tests/wat/test_ots_full_verify_live_path_hermetic.py`
  (5 tests). Test-suite delta +5 (299 -> 304 passed; 25 skipped
  unchanged).
- **2026-05-11 (Sprint-4 Tag-1):** TV-3 receipt-persistence edge-case
  coverage extended by six hermetic shapes against the on-disk side-
  files: empty `root.bin` (0 bytes); `root.bin` removed entirely;
  `root.bin.ots` removed entirely; `root.bin.ots` with the wrong magic
  header at the correct length (16 bytes of `\xff`); `root.bin` padded
  to 64 bytes; `root.bin` with all-bits-cleared permissions. Each test
  pins the specific `OtsAnchorCheck` discriminator (`root_bin_present`,
  `root_bin_matches_manifest`, `ots_present`, `ots_magic_ok`) so a
  future verifier refactor that silently re-classifies a branch will
  break a test. Tied to a small verifier hardening:
  `_check_ots_anchor_side_files` now wraps both sidecar `read_bytes()`
  calls in `try/except OSError` and surfaces a structured rejection
  (`failure_reason` populated, `ots_anchor.ok` False) rather than
  leaking `PermissionError`/`OSError` up the stack. This is additive
  to the Tag-3 edge cluster (three shapes: truncated `root.bin`,
  truncated `root.bin.ots`, `root.bin` flipped vs `merkle_root`) in
  `tests/wat/test_tv3_real_manifest_live_run.py`; the Tag-3 module is
  unchanged. New module `tests/wat/test_tv3_receipt_persistence_edges.py`
  (6 tests). Test-suite delta +6 (293 -> 299 passed; 25 skipped
  unchanged).
- **2026-05-07 (Sprint-3 Tag-4):** off-default `ots verify`-Voll-
  Integration landed. The pin-anchor side-file check (Sprint-2 Tag-5)
  stops at the OpenTimestamps magic header for hermeticity reasons —
  enough to assert that `root.bin.ots` is a well-formed proof file but
  silent on whether the receipt is actually finalised on Bitcoin. The
  new `--ots-full-verify` CLI flag, the `WAKIR_OTS_FULL_VERIFY=1` env
  var, and the `ots_full_verify` keyword on
  `verify_real_manifest_file` opt callers into invoking
  `wat.anchor.ots_anchor.verify_receipt`, which shells out to the
  `ots` CLI and consults the Esplora HTTP fallback for cross-
  validation when no local Bitcoin node is reachable. Three new
  fields land on `OtsAnchorCheck` and the JSON output schema:
  `full_verify_attempted`, `full_verify_ok`, and
  `full_verify_skipped_reason`. Soft-failure semantics are explicit:
  a soft skip (`ots` CLI missing, receipt still pending) does not
  flip `ok` because the magic-header pin still holds; a hard reject
  (verifier returned False against a real receipt) does flip `ok`
  with a populated `failure_reason`. The Bitcoin-RPC dependency is
  thereby gated to a single off-default code path; the default
  invocation surface stays hermetic. Test module
  `tests/wat/test_ots_full_verify.py` lands six hermetic tests
  (default magic-header path unchanged, kwarg-green, kwarg-hard-
  reject, AnchorError-soft-skipped, env-flag-flips-on, CLI-flag-
  flows-through-with-JSON-keys) and three live-gated tests under
  `OTS_INTEGRATION_TEST=1` (TV-2 + TV-3 fixture full-verify contract,
  CLI smoke). Test-suite delta +6 (290 -> 296).
- **2026-05-07 (Sprint-3 Tag-3):** TV-3 real-manifest cohort + receipt-
  persistence edge-case hardening landed. The single-hour TV-3
  close-out run hour-receipt (run 2026-05-07T07:25:38Z, hour-slot
  `2026-05-26T17`, run-genesis with `prev_hour_root: null`) is
  committed under `tests/fixtures/wat-tv3-real/` as a second
  Bitcoin-anchored reference cohort alongside TV-2. New test module
  `tests/wat/test_tv3_real_manifest_live_run.py` (12 tests) covers
  the same per-hour pipeline the TV-2 module asserts plus three new
  receipt-persistence edge-case rejects: a `root.bin` truncated to
  16 bytes; a one-byte-truncated `root.bin.ots`; and a `root.bin`
  whose first byte is flipped relative to `merkle_root` (a side-file
  that lies about the stamped root). The shape pair (TV-2 four-hour
  multi-hop chain + TV-3 single-hour run-genesis) is what proves the
  verifier path is not coincidentally tuned to TV-2 specifics; the
  edge-case cluster is hardening substance proving the OTS-anchor
  side-file check rejects realistic on-disk corruptions, not only
  schema-side and integrity-rebuild errors. Driver
  `scripts/external_verifier_validation.py` gains a parallel
  `--real-tv3` mode plus a generic
  `run_real_manifest_pipeline_for(fixture_root, hour_slots, tag, ...)`
  helper; the legacy `--real-tv2` and `run_real_manifest_pipeline()`
  surfaces are preserved as backward-compat wrappers. Test-suite
  delta +12 (278 -> 290).
- **2026-05-07 (Sprint-3 Tag-2):** Real-manifest live-run validation
  cohort landed. The four hour-receipts produced by the TV-2
  multi-hour audit-trail run (2026-05-06; submit
  2026-05-06T17:37:26Z, close-out 2026-05-07T06:44:13Z, four
  hour-slots `2026-05-27T00..T03`, all four OpenTimestamps calendar
  branches finalised on each receipt within ~13 h) are committed
  under `tests/fixtures/wat-tv2-real/` as the canonical
  Bitcoin-anchored reference cohort. Each hour-receipt directory
  carries the production triple `manifest.json` + `root.bin` (32
  bytes equal to `bytes.fromhex(merkle_root)`) + `root.bin.ots`.
  New test module `tests/wat/test_tv2_real_manifest_live_run.py`
  (17 tests) asserts: per-hour `verify_real_manifest_file
  (use_schema_file=True, check_ots_anchor=True)` returns fully
  green; the formal v1 JSON-Schema accepts each hour-manifest
  directly; `root.bin` matches the `merkle_root` field;
  cross-hour `prev_hour_root` chain is contiguous (T00 is genesis
  with `prev_hour_root: null`, T01..T03 each chain back); two
  negative-path tests against mutated copies of the T00 fixture
  exercise the integrity-rebuild and schema-enum reject paths.
  Driver `scripts/external_verifier_validation.py` gains
  `--real-tv2` mode that wraps the four real manifests as
  accept-vectors, runs them through both schema-side validators
  AND the `verify_real_manifest_file` pipeline (with
  OTS-side-file smoke), and asserts cross-tool parity plus
  pipeline-green. This is the acceptance evidence for the
  Phase-1b→1c criterion that the v1 schema-file plumbing accepts
  artefacts produced by the production aggregator against real
  Bitcoin-anchored side-files, not only hand-authored synthetic
  vectors. Test-suite delta +17 (261 → 278). Cross-tool parity on
  the four real hour-receipts: clean.
- **2026-05-07 (Sprint-3 Tag-1):** External-verifier validation
  substrate landed. The formal v1 schema file
  `wirelang/schemas/wakir-wat-manifest-v1.json` is now exercised by
  two independent JSON-Schema validators against a shared test-vector
  set: the Python `jsonschema` Draft-2020-12 reference (already in
  use) and a Node.js `ajv` implementation under
  `tooling/external-verifier-ajv/`. The shared vectors file
  `tooling/external-verifier-ajv/test-vectors.json` carries 17
  vectors (5 accept + 12 reject) covering required-field coverage,
  pattern pins (hour_slot, merkle_root, prev_hour_root), enum
  closure (version), additionalProperties closure, anchor_height
  domain, and both leaves shapes (hex strings + full-event objects).
  Driver `scripts/external_verifier_validation.py` runs every
  vector through both validators and asserts identical per-vector
  verdicts; cross-tool parity is the schema-correctness contract.
  Pytest wrapper `tests/wat/test_external_verifier_parity.py` gates
  on the same contract (Node.js side `pytest.mark.skipif` when
  `node` or `node_modules` unavailable; Python side always runs).
  Net new: 1 schema-smoke-test module
  (`tests/wat/test_manifest_v1_schema_smoke.py`, 26 tests covering
  the v1 schema directly), 1 parity test module (5 tests, 4 of
  which require Node.js), 1 reference driver script, 1 Node.js
  tooling package, 1 cross-validator vectors file. Test-suite delta
  +31 (230 → 261) when Node.js + ajv are installed; +27 (230 → 257)
  Python-only. The Node.js side remains substrate (not a hard CI
  gate) for Sprint-3; promoting it to `--require-node` is a
  follow-up Open-Item once a CI step pins the node toolchain.
- **2026-05-07 (Sprint-2 Tag-6):** Formal v1 JSON-Schema file
  `wirelang/schemas/wakir-wat-manifest-v1.json` landed as the sibling
  of `wat-manifest-v2.json`. Pins the eight mandatory fields
  (`version`, `hour_slot`, `merkle_root`, `event_count`, `events`,
  `leaves`, `tree_levels`, `build_time`) plus the optional
  `anchor_height` (positive integer when present) and `prev_hour_root`
  (null or 64-lower-hex). The `version` enum reserves both
  `wakir-wat-manifest/v1` and `wakir-wat-manifest/v2`; the v2 producer
  will not require a schema-file edit when it lands. The schema file
  faithfully describes the v1 wire-form including the `leaf_hash`
  field on each event and the leaves-as-objects shape (one-of:
  64-lower-hex string OR object with `leaf_hash` and arbitrary
  additional B1-tuple fields). Verifier-stub gains a
  `use_schema_file` parameter and `--use-schema-file` CLI flag (both
  off-default); when set, the schema-file validator runs *before* the
  in-code field-by-field validator. The in-code path remains the
  redundant hermetic-no-deps fallback so a missing `jsonschema`
  install does not block real-manifest verification. New
  `DEFAULT_REAL_SCHEMA_PATH` module constant; new `--real-schema`
  CLI flag for path override. Cross-reference: `docs/verifier-cli-
  schema-sync.md` will pin the schema-file path for the frontend-side
  TypeScript-interface generator (Tag-7+ hook). 10 additional
  hermetic tests (57 total in the stub suite, 230 / 19 across the
  full repo).
- **2026-05-07 (Sprint-2 Tag-5):** Verifier-stub gains real-manifest
  mode for the on-disk wire-form emitted by today's aggregator
  (`wakir-wat-manifest/v1`). New `verify_real_manifest_file()` API
  and `--real-manifest` CLI flag. Real-manifest mode performs
  field-by-field validation (mandatory fields,
  `version` ∈ {`wakir-wat-manifest/v1`, `wakir-wat-manifest/v2`},
  `merkle_root` 64-lower-hex pattern, `event_count` non-negative int,
  optional `anchor_height` positive int when present), handles the
  `leaf_hash`-vs-`leaf` field-name divergence and the
  leaves-as-objects shape, and re-runs the same Merkle-rebuild
  + multi-cap consistency check (strict default ON since Tag-4) when
  `multi_cap_events` is present. New OTS-pin-anchor side-file check
  (`--check-ots-anchor`, default ON) verifies `root.bin` (32 raw
  bytes equal to `merkle_root`) and `root.bin.ots` (OpenTimestamps
  magic header `\x00OpenTimestamps\x00`) exist next to `manifest.json`;
  full Bitcoin-attestation completeness is delegated to `ots verify`
  (not in-scope for the hermetic stub). New `RealManifestResult` +
  `OtsAnchorCheck` dataclasses; `--output json` and
  `--output audit-trail-entry` work in real-manifest mode and emit
  the same `wakir-verify-manifest-v2/0` schema-version (audit-trail-
  entry bridges via the existing eleven-field paired-update
  contract). 15 additional hermetic tests (47 total in the stub
  suite, 220 / 19 across the full repo). New fixture at
  `tests/fixtures/wat-real-manifest/` (manifest.json + root.bin +
  root.bin.ots, verbatim copy of a real TV-3 archive hour).
- **2026-05-07 (Sprint-2 Tag-4):** OQ-1 ratified
  (wirelang-engineering Cross-Review-Zone-2, sign-off
  2026-05-07T11:48:09Z): canonical Merkle for `caprefs_root` is
  **ordered Merkle** (Variante A — preserves producer / issuance
  intent). Reference verifier `wat.verify.manifest_v2`
  default-flips strict-mode ON (`strict_multi_cap_root=True` is
  the new default in `verify_manifest_v2_file`; CLI flag now
  `argparse.BooleanOptionalAction` — `--strict-multi-cap-root`
  default ON, `--no-strict-multi-cap-root` lenient escape
  hatch). Zero-line implementation patch on the recompute
  itself: `_caprefs_canonical_root_ordered` was already the
  ratified algorithm. Spec §9 OQ-1 status moves from "open" to
  "RATIFIED"; §10 verifier-stub-schema and audit-trail-entry
  status descriptions updated; 3 additional hermetic tests
  (32 total in the stub suite, 205 / 19 across the full repo).
  Frontend audit-trail-entry consumer gets `verdict="verified"`
  for clean v2 manifests by default; lenient `verdict="pending"`
  remains available under explicit `--no-strict-multi-cap-root`.
- **2026-05-07 (Sprint-2 Tag-3):** Verifier-stub gains
  `--output audit-trail-entry` CLI mode and
  `ManifestV2Result.as_audit_trail_entry()`. Eleven-field
  paired-update contract pinned in §10 sub-section "Audit-trail-
  entry export contract" (`kind: "wat-tv-pin-pack"`,
  `schema_version: "wakir-verify-manifest-v2/0"`). 13 additional
  hermetic tests (29 total in the stub suite); field-by-field-
  determinism + dump-roundtrip-byte-stability covered. Frontend
  Sprint-Frontend-1 Tag-3 paired-update unblocked — `AuditTrailEntry`
  TypeScript interface for `wat-tv-pin-pack` kind can converge on
  this shape without schema invention.
- **2026-05-07 (Sprint-2 Tag-2):** Verifier-stub gains
  `--output {human,json}` CLI mode and `ManifestV2Result.as_dict()`.
  JSON schema pinned in §10 sub-section "Verifier-stub JSON-output
  schema" (`schema_version: "wakir-verify-manifest-v2/0"`,
  manifest-centric). 5 additional hermetic tests (16 total in the
  stub suite). Frontend cross-review-sync handover unblocked
  (manifest-centric vs event-centric distinction documented).
- **2026-05-07 (Sprint-2 Tag-1):** Verifier-stub
  `wat.verify.manifest_v2` landed. Implements schema-validation +
  cross-module integrity (events/leaves/tree_levels/merkle_root
  rebuild + multi-cap sidecar consistency) with a
  `--strict-multi-cap-root` flag for the OQ-1-provisional ordered-
  Merkle recompute. 11 hermetic tests added; reference fixture at
  `tests/fixtures/wat-manifest-v2/sample-multi-cap-hour.json`. OQ-1
  still open; lenient mode is the default until Zone-2 sign-off.
- **2026-05-07 (Tag-27.5):** Initial draft of this consolidated
  external-verifier spec. Schema-File and 22 pin-tests already
  landed in Tag-26 / Tag-27. OQ-1 still open pending Zone-2.
- **2026-05-06 (Tag-26):** Schema file `wat-manifest-v2.json` and
  inline smoke tests (4) landed.
- **2026-05-07 (Tag-27):** Pin-test suite expanded to 22 tests in
  `tests/wat/test_manifest_v2_schema_smoke.py`.

---

— Tomás
