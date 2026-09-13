<!--
SPDX-License-Identifier: BUSL-1.1
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Business Source License 1.1; see../../wirelang/persona_engine/LICENSE-BSL.md.
Change Date: 2030-05-15. Change License: Apache License 2.0.
-->

# Wakir Persona-Engine — Release Notes 0.5.3-rc1

**(2026-05-19, persona-engine engineering / Persona-Engine).** Final Pre-cutover
Release-Candidate before the cutover gate opens. `0.5.3-rc1`
is a **manifest-and-metadata-only** version-stamp bump that absorbs
the closeout chain (OPEN-K1, OPEN-K2, OPEN-J1 plus the
state_backing pre-boot emit-order pin) and consolidates the single
Python version-string source of truth at
`wirelang/persona_engine/__version__.py`.

This is **not a substrate change**. The ten-record BackendDecision
boot fan-out, the fifteen-crate cross-language pin set, the ENV-flag
schema, and the Quadlet `Exec=` line are all byte-stable vs.
`0.5.2-final-pre-cutover` (PR #335).

---

## 1. Scope

`0.5.3-rc1` covers exactly four surface-level changes:

1. **Version anchor factored out.** A new module
   `wirelang/persona_engine/__version__.py` becomes the single Python
   source of truth for the engine's version string. Both
   `wirelang/persona_engine/__init__.py` (`__version__`) and
   `wirelang/persona_engine/engine.py` (`ENGINE_VERSION`) now import
   from this anchor instead of carrying inline literals. The anchor
   additionally exports `MANIFEST_RELPATH` and `RELEASE_NOTES_RELPATH`
   so downstream tooling can read the four-file authority bundle
   without grep-heuristics.

2. **Manifest §0 Version-Header pinned.** The manifest
   (`wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md`)
   gains a new §0 section that records the active engine version
   (`0.5.3-rc1`), the four authority surfaces, the carry-forward
   closeout chain (PR #363, #366, #367), and the remaining
   open Operator-Hand item (OPEN-J2).

3. **Release-notes file.** This document, pinned at
   `docs/persona-engine/0-5-3-rc1-release-notes.md`, becomes the
   public-facing companion to the manifest §0 header.

4. **Hermetic version-consistency test.**
   `wirelang/tests/persona_engine/test_engine_0_5_3_rc1_release_notes_tag58.py`
   pins the four-file consistency relation: `__version__.py` ↔
   manifest §0 ↔ release-notes header ↔ `engine.py` `ENGINE_VERSION`.
   Any future bump that touches one surface but not the others fails
   a test with an unambiguous failure message.

**Out of scope** (explicit non-goals, per persona-engine engineering scope discipline):

* No persona-definition change (Domäne, ADR-0043).
* No WAT-core / V-907 logic change (Domäne, Zone-K).
* No identity-substrate design change (Domäne, Zone-L).
* No Containerfile-tag or compose-file change beyond what infrastructure engineering
  coordinates separately (Zone-J).
* No new ENV flag, no flag rename, no flag-default flip.
* No new BackendDecision record, no record renumbering.
* No Rust crate version bump in the fifteen-crate pin pack.

---

## 2. Carry-Forward from 0.5.2-final-pre-cutover

The 0.5.3-rc1 RC absorbs the following..substrates by
reference. Each line below is a contract that 0.5.3-rc1 inherits
unchanged.

| Tag | PR | Substrate | Status |
|---|---|---|---|
| 52 | #335 | Manifest 0.5.2-final consolidation marker | carry-forward |
| 53 | #340 | `migrate_version_canonical` 0.5.1→0.5.2 adapter | carry-forward |
| 54 | #347 | ADR-0036 self-migration corpus reconciliation | carry-forward |
| 55 | #357 | Cosign-Strict-Mode Gate-G3+G5 (Zone-J input) | carry-forward |
| 56 | #359 | Watch-day-practice-run CI-gate (SRE engineering input) | carry-forward |
| 56 | #360 | Cosign-Strict-Mode G1+G2 Operator-Hand guide (infrastructure engineering) | carry-forward |
| 56 | #361 | Phase-3 rollback workflow (dev engineering input) | carry-forward |
| 56 | #362 | 0.5.2-final production-readiness audit (persona-engine engineering) | carry-forward |
| 57 | #363 | `state_backing` pre-boot emit-order pin (persona-engine engineering) | carry-forward |
| 57 | #364 | ADR-Errata × Wirelang-spec mirror-drift audit (protocol engineering) | carry-forward |
| 57 | #365 | Pre-cutover Acceptance-Pyramide Run-Order (QA engineering) | carry-forward |
| 57 | #366 | OPEN-K1 + OPEN-K2 closeout (dev engineering, WAT/V-907 Zone-K) | carry-forward |
| 57 | #367 | OPEN-J1 Cross-Substrate-Parity-Gate (infrastructure engineering, Zone-J) | carry-forward |
| 57 | #368 | Watch-day cron-pre-fire probe (SRE engineering input) | carry-forward |

The boot fan-out byte-shape, the manifest §1 record numbering, and
the pin-pack `boot_wired_crates` ordering are byte-stable vs.
0.5.2-final. The PR #363 emit-order pin already locked the
`state_backing` pre-boot emission ahead of the in-`boot` cohort; the
0.5.3-rc1 RC inherits that pin without re-asserting it here.

---

## 3. OPEN-Items Status

The production-readiness audit (persona-engine engineering, PR #362) emitted a
verdict of **PRODUCTION-READY-WITH-2-OPEN-CROSS-REVIEW**. The two
Cross-Review items were both closed in; one Operator-Hand
item remains for the cutover window itself.

### Closed in

* **OPEN-K1 (Zone-K, dev engineering / WAT-core).** V-907 canonical-form
  Python ↔ Rust parity fingerprint pinned. Closed by PR #366
  (dev engineering). 0.5.3-rc1 inherits the closeout.
* **OPEN-K2 (Zone-K, dev engineering / WAT-core).** Persona-Hash build-step
  cross-language fixture matrix completed. Closed by PR #366
  (dev engineering). 0.5.3-rc1 inherits the closeout.
* **OPEN-J1 (Zone-J, infrastructure engineering / Container-Bridge).** Cross-Substrate-
  Parity-Gate green-on-PR for the 0.5.2-final manifest fingerprint.
  Closed by PR #367 (infrastructure engineering). 0.5.3-rc1 inherits the gate.

### Remaining open at 0.5.3-rc1

* **OPEN-J2 (Operator-Hand).** cutover-day live-VM smoke-bring-up.
  Not closable in the hermetic sandbox by design (per the Live-
  Bring-up-Sandbox-Gap memory item from 2026-05-13). The 0.5.3-rc1
  RC explicitly defers this to the cutover window itself,
  under Operator-Hand authority. This is a **known carry**, not a
  blocker for the rc1 cut.

The RC explicitly does **not** open any new Cross-Review
gates. Zones J/K/L remain in the consent state reached at
closeout.

---

## 4. Pre-cutover Gate-Map

The cutover window opens after the following gates report
green against the 0.5.3-rc1 fingerprint. Each row references the
exact Tag-X / PR-Y substrate that owns the gate.

| # | Gate | Owner | Substrate Reference | Status at 0.5.3-rc1 |
|---|---|---|---|---|
| G1 | Cosign-Strict-Mode signing | infrastructure engineering | PR #357, PR #360 | green (carry-forward) |
| G2 | Cosign-Strict-Mode verification | infrastructure engineering | PR #357 | green (carry-forward) |
| G3 | Cross-Substrate-Parity-Gate | infrastructure engineering | PR #367 (OPEN-J1 closeout) | green |
| G4 | V-907 canonical-form parity | dev engineering | PR #366 (OPEN-K1 closeout) | green |
| G5 | Persona-Hash cross-lang fixtures | dev engineering | PR #366 (OPEN-K2 closeout) | green |
| G6 | `state_backing` pre-boot emit-order pin | persona-engine engineering | PR #363 | green |
| G7 | Phase-3 rollback workflow | dev engineering | PR #361 | green (carry-forward) |
| G8 | Watch-day-practice-run CI gate | SRE engineering | PR #359 | green (carry-forward) |
| G9 | Watch-day cron-pre-fire probe | SRE engineering | PR #368 | green (carry-forward) |
| G10 | Acceptance-Pyramide Run-Order verdict-aggregator | QA engineering | PR #365 | green (carry-forward) |
| G11 | ADR-Errata × spec mirror-drift audit | protocol engineering | PR #364 | green (carry-forward) |
| G12 | Manifest §0 + `__version__.py` + release-notes consistency | persona-engine engineering | (this RC) | green |
| G13 | cutover-day live-VM smoke (Operator-Hand) | Operator | OPEN-J2 | deferred to |

Gates G1–G12 are green at the 0.5.3-rc1 cut. G13 is the only
explicit Operator-Hand item, and it is by design not closable from
the hermetic sandbox.

---

## 5. Operator-Hand Items

The following actions are reserved for the human Operator and are
NOT in scope for any spawn. They are listed here so the
cutover-day runbook has a single canonical reference.

1. **OPEN-J2 cutover-day live-VM smoke-bring-up.** Operator runs
   the live-VM bring-up sequence against the 0.5.3-rc1 image,
   verifies the ten BackendDecision records emit in canonical order
   on real-host substrate, and signs the cutover-day audit bundle.
   Sandbox-tests cannot substitute for this per the Live-Bring-up-
   Sandbox-Gap memory item.

2. **cutover-day push-approval.** Per the Continuous-Mode-keine-
   Push-Approval-Frage memory item, automated pushes proceed when
   conditions are literally met. The 0.5.3-rc1 self-merge is in
   that category. The cutover-day promote-to-stable push from
   `0.5.3-rc1` to the cutover-stable tag is **not** in that
   category — it is an Operator-Hand gate.

3. **Post-cutover monitor-window watch.** SRE engineering's watch-day gate
   armed at PR #359 plus the PR #368 cron-pre-fire
   probe expect a human in the loop during the cutover window
   itself. The 0.5.3-rc1 RC does not change that expectation.

4. **Rollback trigger.** dev engineering's PR #361 Phase-3 
   Rollback workflow is armed. The trigger remains an Operator-
   Hand pull-the-cord action.

The 0.5.3-rc1 RC closes no Operator-Hand items and opens none.

---

*Authored by persona-engine engineering, 2026-05-19.
Cross-Review Zones J/K/L unchanged from consent state.*
