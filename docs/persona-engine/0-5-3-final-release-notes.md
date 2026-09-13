<!--
SPDX-License-Identifier: BUSL-1.1
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Business Source License 1.1; see../../wirelang/persona_engine/LICENSE-BSL.md.
Change Date: 2030-05-15. Change License: Apache License 2.0.
-->

# Wakir Persona-Engine — Release Notes 0.5.3 (Final)

**(2026-05-19, persona-engine engineering / Persona-Engine).** Final-Bump
Pre-cutover-Sealing. `0.5.3` is the **rc1-suffix-drop** of
`0.5.3-rc1` (PR #372). It is a strict superset of the rc1
substrate and a strict superset of `0.5.2-final-pre-cutover`
(PR #335). The G5-PRE-CUTOVER-READY compositum
verdict (PR #391) is the substrate authority that authorised this
promotion to the final release-tag before the cutover-T0
window opens (2026-06-08/09).

This is **not a substrate change**. The ten-record BackendDecision
boot fan-out, the fifteen-crate cross-language pin set, the
ENV-flag schema, the Quadlet `Exec=` line, and the
V-907-composite-hash seal at `v907-hash-baseline.json` are all
byte-stable vs. `0.5.3-rc1` and vs. `0.5.2-final-pre-cutover`.

---

## 1. Scope

`0.5.3` covers exactly four surface-level changes vs. `0.5.3-rc1`:

1. **Canonical version literal.**
   `wirelang/persona_engine/__version__.py` line 46 drops the
   `-rc1` suffix: `__version__ = "0.5.3"`. The downstream re-exports
   (`__init__.__version__`, `engine.ENGINE_VERSION`) inherit the
   new literal through the single import. `RELEASE_NOTES_RELPATH`
   bumps to `docs/persona-engine/0-5-3-final-release-notes.md`
   (this file). The `MANIFEST_RELPATH` carry-forward stays at the
   manifest filename — the manifest body is byte-stable and
   only its §0 version-header was rewritten.

2. **hot-fix-surface mirroring.** The three surfaces the
   sweep PR #381 had to clean — `engine_async.py:96`
   (`ASYNC_ENGINE_VERSION`), `cli.py:3` (module docstring), and
   `engine.py:84` (canonical-anchor import comment) — are mirrored
   to `0.5.3`. These are the surfaces the drift-scanner
   (`tooling/ci/scan_engine_version_drift.py`) is wired to catch
   if they drift again.

3. **Manifest §0 Version-Header rewrite.** The manifest
   (`wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md`)
   §0 section is updated to record `0.5.3` as the active engine
   version. The old `0.5.3-rc1` §0 substance is preserved verbatim
   in a new §0.1 history sub-section so the auditability of the
   rc1 → final transition is intact.

4. **Drift-scanner allowlist + STALE_VERSIONS extension.**
   `tooling/ci/scan_engine_version_drift.py` now hunts
   `0.5.3-rc1` as a stale literal. The
   `tooling/ci/engine-version-drift-allowlist.json` is extended
   with the legitimate stale-literal contexts (v907-hash-baseline,
   tag58/59/60/61 hermetic test fixtures, the rc1 release-notes
   file under `docs/persona-engine/`).

**Out of scope** (explicit non-goals, per persona-engine engineering scope discipline):

* No persona-definition change (Domäne, ADR-0043).
* No WAT-core / V-907 logic change (Domäne, Zone-K). The
  V-907-composite-hash baseline at `v907-hash-baseline.json`
  remains sealed — the §0 version-header is outside the V-907
  byte-bounded slice (manifest §1 + pin-pack `boot_wired_crates` +
  engine.py resolver-block). The baseline file still carries
  `0.5.3-rc1` in its `engine_version` and `note` fields by design;
  refreshing it requires an operator-hand refresh plus Zone-K cross-review
  per the seal contract.
* No identity-substrate design change (Domäne, Zone-L).
* No Containerfile-tag or compose-file change beyond what infrastructure engineering
  coordinates separately (Zone-J).
* No new ENV flag, no flag rename, no flag-default flip.
* No new BackendDecision record, no record renumbering.
* No Rust crate version bump in the fifteen-crate pin pack.
* No pin-pack YAML refresh (`pin-pack-0.5.2-final-pre-cutover.yaml`
  is carry-forward).
* No live-VM rotation chain extension. The Tag-N rotation
  state-machine substrate (`tooling/ci/simulate_live_vm_rotation_
  state_machine.py`) narrates the `0.5.1 → 0.5.2 → 0.5.3-rc1`
  chain and is preserved as historical record; the `→ 0.5.3` final
  promotion is a metadata-only seal, not a rotation event, and
  the Operator-Hand cutover-day live-VM bring-up (OPEN-J2) covers
  the final-tag substrate verification at T0.

---

## 2. Carry-Forward from 0.5.3-rc1 (and from 0.5.2-final)

The 0.5.3 final tag absorbs the..substrates by
reference. Each line below is a contract that 0.5.3 inherits
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
| 58 | #372 | Engine 0.5.3-rc1 manifest-and-metadata bump (persona-engine engineering) | carry-forward |
| 59 | #381 | Engine version-literal hot-fix sweep + V-907 seal (persona-engine engineering/the CEO) | carry-forward |
| 60 | #382 | Drift-scanner + 15-test version-drift-full-coverage pin (persona-engine engineering) | carry-forward |
| 61 | #391 | Engine-Final-Acceptance compositum, G5-PRE-CUTOVER-READY (persona-engine engineering) | carry-forward |

The boot fan-out byte-shape, the manifest §1 record numbering, the
pin-pack `boot_wired_crates` ordering, and the V-907-composite-hash
seal are byte-stable vs. 0.5.3-rc1. The PR #363 emit-order
pin remains in force. The compositum verdict is the
upstream gate that authorised this promotion.

---

## 3. G5-PRE-CUTOVER-READY Compositum Verdict Achievement

The Engine-Final-Acceptance compositum aggregator
(`tooling/ci/aggregate_persona_engine_pre_cutover_final.py`,
PR #391) is the authority that authorised the rc1 → final
promotion. It reports a single composite verdict by aggregating
the per-component verdicts of every Phase-3-substrate gate the
0.5.3-rc1 substrate accumulated.

### G5 verdict at (input authority for)

* **Verdict:** `PRE-CUTOVER-READY` (green).
* **Aggregated gates:** G1 (Cosign-Strict-Mode signing, infrastructure engineering), G2
  (Cosign-Strict-Mode verification, infrastructure engineering), G3 (Cross-Substrate-
  Parity-Gate, infrastructure engineering #367), G4 (V-907 canonical-form parity,
  dev engineering #366), G5 (Persona-Hash cross-lang fixtures, dev engineering
  PR #366), G6 (state_backing pre-boot emit-order pin, persona-engine engineering
  PR #363), G7 (Phase-3 rollback workflow, dev engineering
  PR #361), G8 (Watch-day-practice-run CI gate, SRE engineering #359), G9
  (Watch-day cron-pre-fire probe, SRE engineering #368), G10 (Acceptance-
  Pyramide Run-Order verdict-aggregator, QA engineering #365), G11
  (ADR-Errata × spec mirror-drift audit, protocol engineering #364), G12
  (Manifest §0 + `__version__.py` + release-notes consistency,
  persona-engine engineering), G13 (drift-scanner full coverage, persona-engine engineering).
* **G13 (drift scanner) at:** green — the scanner's
  `ACTIVE_VERSION` is bumped to `0.5.3` in lockstep with the
  `__version__.py` literal; the rc1 stale literal joins the
  hunted `STALE_VERSIONS` set; the allowlist registers the
  legitimate rc1-surviving artefacts.

### Operator-Hand item carry-forward

* **OPEN-J2 cutover-day live-VM smoke (Operator-Hand).** Deferred
  to the cutover-T0 window (2026-06-08/09). Not closable
  from the hermetic sandbox by design (per Live-Bring-up-Sandbox-
  Gap memory item 2026-05-13). The 0.5.3 final tag explicitly
  inherits this carry-forward; the cutover-day push from the
  `0.5.3` final-tag image to the cutover-stable tag is an
  Operator-Hand authorisation gate per the Continuous-Mode-keine-
  Push-Approval-Frage memory item.

The 0.5.3 final tag opens no new Cross-Review gates. Zones J/K/L
remain in the consent state reached at closeout, reinforced
by the V-907 seal and the compositum verdict.

---

## 4. Pre-cutover Gate-Map (sealed at)

The cutover-T0 window opens after the following gates report
green against the 0.5.3 final fingerprint. Each row references the
exact Tag-X / PR-Y substrate that owns the gate.

| # | Gate | Owner | Substrate Reference | Status at 0.5.3 |
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
| G12 | Manifest §0 + `__version__.py` + release-notes consistency | persona-engine engineering | PR #372 (this bump) | green |
| G13 | Engine-version-drift-scanner full coverage | persona-engine engineering | extension | green |
| G14 | V-907 hash-pin baseline seal | persona-engine engineering/dev engineering | PR #381 | green (carry-forward, sealed) |
| G15 | Engine-Final-Acceptance compositum (G5-PRE-CUTOVER-READY) | persona-engine engineering | PR #391 | green (carry-forward) |
| G16 | cutover-day live-VM smoke (Operator-Hand) | Operator | OPEN-J2 | deferred to T0 |

Gates G1–G15 are green at the 0.5.3 final cut. G16 is the only
explicit Operator-Hand item, and it is by design not closable from
the hermetic sandbox.

---

## 5. Operator-Hand Items

The following actions are reserved for the human Operator and are
NOT in scope for any spawn. They are listed here so the
cutover-day runbook has a single canonical reference.

1. **OPEN-J2 cutover-day live-VM smoke-bring-up.** Operator runs
   the live-VM bring-up sequence against the 0.5.3 final image,
   verifies the ten BackendDecision records emit in canonical order
   on real-host substrate, and signs the cutover-day audit bundle.
   Sandbox-tests cannot substitute for this per the Live-Bring-up-
   Sandbox-Gap memory item.

2. **cutover-day push-approval (final-tag promote).** Per the
   Continuous-Mode-keine-Push-Approval-Frage memory item, automated
   pushes proceed when conditions are literally met. The 0.5.3
   final self-merge is in that category. The cutover-day promote-
   to-stable push from `0.5.3` to the cutover-stable tag is **not**
   in that category — it is an Operator-Hand gate.

3. **Post-cutover monitor-window watch.** SRE engineering's watch-day gate
   armed at PR #359 plus the PR #368 cron-pre-fire
   probe expect a human in the loop during the cutover window
   itself. The 0.5.3 final tag does not change that expectation.

4. **Rollback trigger.** dev engineering's PR #361 Phase-3 
   Rollback workflow is armed. The trigger remains an Operator-
   Hand pull-the-cord action.

5. **V-907-baseline refresh (Zone-K seal).** The
   `wirelang/persona_engine/v907-hash-baseline.json` seal
   continues to record `engine_version: "0.5.3-rc1"` because the
   composite-hash slice is byte-bounded and unchanged. Any future
   refresh that bumps the `engine_version` metadata literal there
   requires engineering-hand + dev engineering Zone-K cross-review per the
   seal contract; the final-bump explicitly does not
   exercise that authority.

The 0.5.3 final tag closes no Operator-Hand items and opens none.

---

*Authored by persona-engine engineering, 2026-05-19.
Cross-Review Zones J/K/L unchanged from consent state,
reinforced by V-907 seal and G5-PRE-CUTOVER-READY
compositum verdict.*
