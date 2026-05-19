---
title: "OPEN-K3 V-907 Baseline-Metadata Carry-Forward (Tag-64)"
status: "active"
owner: "tomas"
audience: "operator,ar,engineering,audit"
created: "2026-05-19"
tag: "tag-64"
predecessor: "reports/audit/persona-engine-0-5-3-production-readiness-2026-05-19.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
  - "ADR-0043"
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/persona-engine/0-5-3-final-release-notes.md"
  - "wirelang/persona_engine/v907-hash-baseline.json"
  - "tooling/ci/engine-version-drift-allowlist.json"
related_prs:
  - "#372"
  - "#381"
  - "#394"
  - "#399"
  - "#405"
related_memory:
  - "feedback_anti_eskalations_drift.md"
  - "feedback_adr_substanz_prüfung_pflicht.md"
related_zones:
  - "Zone-K (Tomás, WAT-V-907)"
---

# OPEN-K3 V-907 Baseline-Metadata Carry-Forward (Tag-64)

This document is the **carry-forward record** for Tag-63 audit
finding OPEN-K3 (Selin, `reports/audit/persona-engine-0-5-3-
production-readiness-2026-05-19.md` §3.5 + §Open-Item-Tracker).
The audit reported OPEN-K3 as **intentional-by-design, non-
blocking-documentation**; this document is the operational pin
for that posture.

This is **doc-form-only**. No code mutation, no JSON metadata
edit, no drift-allowlist change. The Tag-59 seal contract is
the operational gate, and refreshing the baseline file in-place
would itself be a bypass of the seal contract.

The doc is the analog of `OPEN-J3` posture for Zone-J (Kai,
Containerfile OCI `image.version` label `0.5.2-final-pre-cutover`
carry-forward, deferred until the cutover-image-build pipeline
phase). Both items are **intentional carry-forwards** routed
through the appropriate cross-review surface, not defects.

---

## §1 - Subject and posture

### §1.1 - Substrate

The file `wirelang/persona_engine/v907-hash-baseline.json` is the
Tag-59 V-907 composite-hash seal (PR #381, Selin sweep + Tomás
Zone-K cross-review). It declares:

```json
{
  "engine_version": "0.5.3-rc1",
  "note": "V-907 persona-hash-pin baseline for engine 0.5.3-rc1
           (Tag-58 PR #372). Sealed Tag-59. Refresh requires
           Selin-Hand + Tomas Zone-K cross-review.",
  "composite_hash": "a529d7d1b85ee33c61755cef7cb21793ff0ecf87d2efc5b9267f58526c818857",
  ...
}
```

The `engine_version` and `note` fields carry the literal
`0.5.3-rc1`. The Tag-62 final-bump (`0.5.3-rc1` -> `0.5.3`,
PR #399, Selin) did **not** rewrite these literals.

### §1.2 - Posture

**Intentional-by-design carry-forward, non-blocking-documentation.**

- The Tag-62 final-bump is, by self-description, a "manifest-and-
  metadata-only rc1-suffix-drop" (release-notes `docs/persona-
  engine/0-5-3-final-release-notes.md` §1).
- The V-907 composite-hash seal at `v907-hash-baseline.json` is
  outside the V-907-bounded byte-range. The hashed input is
  exactly `manifest §1 ∥ pin-pack boot_wired_crates ∥ engine.py
  resolvers`. The `engine_version` and `note` JSON fields are
  documentation, not part of the hashed input.
- Refreshing the metadata literal in-place from `0.5.3-rc1` to
  `0.5.3` would itself bypass the seal contract (the baseline
  file is *itself* the Zone-K cross-review artefact; editing its
  documentation metadata in-place would be an edit of the
  cross-review artefact without a fresh cross-review).

### §1.3 - Verdict

The Tag-63 audit (Selin, PR #405) reports the posture
**MATCH-WITH-1-INTENTIONAL-DEFERRAL** for Dimension 5 (V-907
Pin-Stability Substrate). The deferral is not a defect.

---

## §2 - Why not cleanup

This section enumerates the three reasons we do **not** edit
`v907-hash-baseline.json` in this Tag-64 PR or any later PR that
is not explicitly a seal-contract refresh.

### §2.1 - Reason 1: the seal contract requires Selin-Hand + Tomás-Zone-K cross-review

The Tag-59 seal contract (PR #381 commit message + `v907-hash-
baseline.json:10` `note` field) explicitly states refreshing
the baseline requires a **dual-hand cross-review**:

- Selin (Persona-Engine owner) authors the new baseline.
- Tomás (Zone-K WAT-V-907 owner) cross-reviews and signs off.

An in-place metadata edit by either hand alone would defeat the
two-hand-on-the-baseline invariant. The two-hand invariant is the
seal contract.

### §2.2 - Reason 2: the metadata is not part of the hashed input

The composite hash at line 6 of `v907-hash-baseline.json`
(`a529d7d1...`) is computed over exactly three byte segments:

| Segment | Source | Byte length |
|---|---|---|
| `manifest_section_1` | `MANIFEST-0.5.2-final-pre-cutover.md` §1 | 2322 |
| `pin_pack_boot_wired_crates` | `pin-pack-0.5.2-final-pre-cutover.yaml` `boot_wired_crates` block | 3183 |
| `engine_py_resolvers` | `wirelang/persona_engine/engine.py` resolver block | 16710 |

The `engine_version` and `note` JSON fields are not part of the
input. The Tag-62 final-bump touched none of the three segments
(manifest §1 substance byte-stable, pin-pack carry-forward, engine.py
resolver block carry-forward). Therefore the hash is mathematically
unaffected by the rc1-suffix-drop, and the metadata refresh is
**purely cosmetic** from the seal's perspective.

Refreshing a metadata literal that does not affect the seal would
introduce churn without changing the seal's invariant. The Tag-59
sealer (Selin) intentionally declined this churn at the Tag-62
final-bump for this reason.

### §2.3 - Reason 3: the carry-forward is already documented in three places

The intentional carry-forward is documented in:

1. `wirelang/persona_engine/v907-hash-baseline.json:10` (the
   `note` field itself: "Refresh requires Selin-Hand + Tomas
   Zone-K cross-review").
2. `docs/persona-engine/0-5-3-final-release-notes.md` §1 line
   3-4 ("No persona-definition change ... refreshing it
   requires Selin-Hand + Tomas-Zone-K cross-review per the
   Tag-59 seal contract").
3. `reports/audit/persona-engine-0-5-3-production-readiness-
   2026-05-19.md` §3.5 line 446-453 (Selin Tag-63 audit
   verdict).

This Tag-64 doc is the **fourth surface** (operations-doc layer)
and the canonical operator-facing carry-forward record.

---

## §3 - Refresh trigger conditions

The baseline metadata refresh is **not** scheduled. It is
triggered by either of two events, whichever comes first.

### §3.1 - Trigger A: substrate change to a hashed segment

If a future PR mutates any of the three hashed segments (manifest
§1, pin-pack `boot_wired_crates`, or `engine.py` resolver block)
in a way that legitimately changes the composite hash, the
**refresh is mandatory in that same PR or the immediately
following cross-review PR**:

- The PR author MUST recompute the composite hash.
- The PR author MUST refresh the `engine_version` literal to the
  active engine version at the time of the segment change.
- The PR author MUST update the `note` field to reflect the
  triggering PR.
- The refresh PR MUST carry both Selin-Hand and Tomás-Zone-K
  approval before merge (the two-hand invariant).

### §3.2 - Trigger B: KW-24 cutover-T0 window opens

When the cutover-window opens (KW-24, target 2026-06-08/09 per
ADR-0066 + Mira manifest §6 Cutover-Window-Open-Signal), the
operator-hand cutover plan may schedule a baseline metadata
refresh as a cosmetic clean-up step **after** the cutover-image
is built and signed. This is a low-priority housekeeping item
and is not on the cutover critical path.

The cutover-day refresh is optional. If the substrate has not
mutated since Tag-59, the seal is intact and the metadata
carries no operational signal. The cosmetic refresh would only
serve to align the `engine_version` literal with the rest of
the engine's surface metadata for tidiness.

### §3.3 - Trigger C: explicit cross-review request

If either Selin or Tomás decides the metadata churn is
warranted independent of triggers A and B (for example, if the
metadata literal becomes a source of operator confusion in the
operator-hand cutover-day runbook), the dual-hand can convene
ad-hoc and refresh the baseline. This is the explicit
cross-review path and is the only path that does not require
either a substrate change or the cutover window.

---

## §4 - Tooling guard

The drift-scanner `tooling/ci/scan_engine_version_drift.py` is
configured to **expect** the stale literal `0.5.3-rc1` at
`v907-hash-baseline.json`. The allowlist entry has category
`v907-baseline-pin` and exists in
`tooling/ci/engine-version-drift-allowlist.json` (Tag-62
extension, PR #399).

This Tag-64 doc does **not** modify the allowlist. The allowlist
entry is correct by construction: the file is a pin file for a
historical hash input. Removing the entry would trip the drift
scanner on a legitimate carry-forward.

---

## §5 - Cross-Anchors

### §5.1 - Tag-58 Engine 0.5.3-rc1 bump (PR #372, Selin)

The literal `0.5.3-rc1` was introduced in
`wirelang/persona_engine/__version__.py` by PR #372 and was
captured in the V-907 baseline at the time of the Tag-59 seal.

### §5.2 - Tag-59 V-907 hash-pin baseline seal (PR #381, Selin sweep)

PR #381 created `v907-hash-baseline.json` with the dual-hand
seal contract in the `note` field. This is the foundational
artefact for OPEN-K3.

### §5.3 - Tag-62 Engine 0.5.3 final-bump (PR #399, Selin)

PR #399 dropped the `-rc1` suffix from `__version__.py` and
mirrored the change across three downstream surfaces
(`engine_async.py:96`, `cli.py:3`, `engine.py:84`). The release
notes explicitly state the baseline metadata refresh is not part
of the final-bump scope.

### §5.4 - Tag-63 Production-Readiness Audit (PR #405, Selin)

PR #405 §3.5 reported V-907 Pin-Stability Substrate as MATCH-
WITH-1-INTENTIONAL-DEFERRAL and named OPEN-K3 explicitly. This
Tag-64 doc is the operational record that closes the audit
loop for OPEN-K3.

### §5.5 - Zone-K cross-review anchors

The Zone-K cross-review surface is anchored at:

- Reza Tag-25 V-907-verify smoke test (`tests/v907_verify_smoke_
  test.rs`, sample axis-A digest pin).
- Tomás-Tag-25 SAMPLE_AXIS_A digest authoring (the digest
  literal `sha256:cf66fbc5e02e...` in `persona-engine-v907-
  verify/src/lib.rs`).
- Tag-59 seal contract (PR #381) - the foundational dual-hand
  invariant.

The Zone-K surface is **read-only from outside** by design.
Refresh PRs require explicit Zone-K cross-review.

---

## §6 - Sandbox boundary

This doc and its companion test suite (`tests/ci/test_k3_and_
bulk_subsumption_tag64.py` §K3 group) are pure documentation
and pure read-only assertions. No JSON-mutation, no settings
mutation, no `gh api` call, no `gh variable set` call, no
GitHub-side write.

- The test suite reads `v907-hash-baseline.json` and the
  drift-allowlist and asserts the carry-forward posture.
- The test suite does **not** edit the baseline or the
  allowlist.
- The Mira-Sandbox-vs-Host-Operations rule (Memory `feedback_
  sandbox_host_trennung`) is preserved: any future seal refresh
  is operator-hand, not sandbox-hand.

---

*Tomás Reinhart, Dev-Engineering-Agent, Zone-K cross-review hand.*
*Tag-64 carry-forward record for OPEN-K3.*
*2026-05-19.*
