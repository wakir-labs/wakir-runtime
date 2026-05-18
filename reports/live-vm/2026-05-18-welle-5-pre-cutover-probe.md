<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-5 Pre-Cutover-Probe (Tag-42)

**Date (UTC):** 2026-05-18T18:35Z
**Sprint-Tag:** 42
**Operator:** Kai Hoffmann (DevOps-3), via Mira-SSH-Hand
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 5 (`lifecycle_state_machine` / fsm)
**Pair-Welle:** 4 (`state_backing`) — KW-26 Doppel-Welle
**Probe-Script:** `scripts/phase-3c/welle-5-pre-cutover-probe.sh`
**ADR-Authority:** ADR-0058 §Nachtrag (Mira-SSH-Hand), ADR-0066
(Phase-3c Doppel-Welle order, KW-26)

---

## 1. Executive Summary

**Status:** `PROBE-NOT-EXECUTED`
**Reason:** Mira-sandbox classifier blocks live VM-read SSH calls
(systemctl / podman / journalctl enumeration) per
`feedback_sandbox_host_trennung.md`. Wrapper-substance, hermetic
tests and §10 Doppel-Welle coordination contract delivered;
live verdict requires operator-hand replay outside the sandbox.
**Cutover-Readiness-Bewertung Welle-5:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41: non-blocking).

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-5-pre-cutover-probe.sh` encodes the 5+1
axis verification rubric for Welle-5 lifecycle_state_machine
(7 axes counted for aggregate; the FSM-Transition-Integrity-Pre-
Check carries the Phantom-Transition-Scan as one combined axis,
plus the +1 Rollback-Probe — total 7 numbered axes):

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all axes matched; Welle-5 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-5 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Seven verification axes (5+1 rubric per Auftrag)

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| AXIS-1 | FSM-State-Persistence-Pre-Verification | Remote `lifecycle-state-machine-cli state-snapshot --canonical --json` emits non-empty payload |
| AXIS-2 | Welle-5 Cutover-Smoke dry-run (PR #249) | Remote `welle-5-lifecycle-state-machine-cutover-smoke.py --dry-run` exits with `RC=0` |
| AXIS-3 | FSM-Transition-Integrity + Phantom-Transition-Scan | `trace-validate` returns `{"valid":true}` AND `phantom-transitions` returns empty list / `phantom_count:0` |
| AXIS-4 | BackendDecision-Stream-Health | `>= 11` BackendDecision audit entries since boot (PR #250 baseline) AND lifecycle_state_machine component-tail shows `backend=python` |
| AXIS-5 | Cross-Modul-Drift-Pre-Check zu Welle-4 (symmetric A7) | Pair overlay `welle-4-state-backing-rust.conf` ABSENT AND pair audit-tail not `backend=rust` |
| AXIS-6 | Cross-Lang-Parity (Pin-Pack PR #224) | Remote `lifecycle-state-machine-cli state-hash --canonical-fixture pin-pack-v1` matches `--expected-hash` |
| AXIS-7 | Rollback-Surface-Capability | All four levers present on VM |

### Sandbox-Hermetic-Tests

`tests/scripts/test_welle_5_pre_cutover_probe.py` carries 8 hermetic
pytest tests:

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_missing_ssh_key_returns_precondition_without_dry_run`
3. `test_dry_run_aggregates_green_with_expected_hash`
4. `test_dry_run_aggregates_caution_without_expected_hash`
5. `test_ssh_unreachable_emits_not_exec_verdict`
6. `test_all_axes_green_renders_green_aggregate`
7. `test_axis_5_pair_overlay_present_renders_block_symmetric`
8. `test_axis_3_phantom_transitions_detected_renders_block`

All `ssh` calls stubbed via `$WAKIR_SSH_BIN` so CI never touches
the live VM (per Memory `feedback_sandbox_host_trennung.md`).

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked).

- **Probe-host clock (UTC):** captured by wrapper at run-time.
- **Probe-host repo head:** `64b1c170` (Tag-41 baseline).
- **PR #224 Pin-Pack anchor for lifecycle_state_machine:** to be
  supplied at operator-hand replay via `--expected-hash`.

## 4. Probe-Run-Log

```
$ bash scripts/phase-3c/welle-5-pre-cutover-probe.sh \
      --expected-hash <PR-224-lifecycle-state-machine-pin-pack-anchor> \
      --quiet
ERROR: Permission for this action was denied by the Claude Code
auto mode classifier. Reason: Reading inside a running pilot VM
via SSH (systemctl/podman/service enumeration) is a Production
Reads action that pulls live service state into the transcript
without explicit user approval for this exact remote read.
```

SSH-Layer reachable (Tag-41 baseline). Block is at the content-read
classifier layer, not network/auth.

## 5. Verifikations-Ergebnisse pro Achse

| Axis | Verdict | Detail |
|------|---------|--------|
| AXIS-1 FSM-State-Persistence | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 Welle-5 Smoke dry-run | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 FSM-Transition-Integrity + Phantom-Scan | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 BackendDecision-Stream-Health | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Cross-Modul-Drift zu Welle-4 | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-6 Cross-Lang-Parity (PR #224) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-7 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer |

Hermetic dry-run of the wrapper (exit-code 0, AGGREGATE=GREEN with
`--expected-hash deadbeef`) confirms the *script* mechanics.

## 6. Bug-Findings

None — probe did not execute against the substrate.

## 7. Cutover-Readiness-Bewertung Welle-5

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators:**

- Welle-5 Cutover-Smoke (PR #249) merged. -- verified (PR baseline)
- lifecycle_state_machine canonical serializer + spec §3.3
  VALID_TRANSITIONS (Phase-3a) merged. -- verified
- Welle-5 Operator-Cutover-Runbook (Tag-36 successor pattern). -- in-place
- Welle-5 Pre-Cutover-Probe-Wrapper (this PR, Tag-42). -- substance
- KW-26 cutover window start ~23. Juni — sufficient slack for
  operator-hand replay before window-start.

**Recommendation:** Operator-hand replay of
`scripts/phase-3c/welle-5-pre-cutover-probe.sh` outside the Mira-
sandbox, with the PR #224 Pin-Pack lifecycle_state_machine anchor
hash via `--expected-hash`, before the KW-26 Welle-5 cutover step.
Run **before or jointly with** Welle-4 Pre-Cutover-Probe per §8
Doppel-Welle Coordination Note.

## 8. Doppel-Welle KW-26 Coordination

Welle-4 and Welle-5 run in parallel during the KW-26 cutover window
(ADR-0066). Both pre-cutover probes share a symmetric AXIS-5
Cross-Modul-Drift-Pre-Check:

| Probe | AXIS-5 verifies |
|-------|------------------|
| welle-5-pre-cutover-probe.sh | Welle-4 overlay `welle-4-state-backing-rust.conf` ABSENT in Default-State |
| welle-4-pre-cutover-probe.sh | Welle-5 overlay `welle-5-lifecycle-state-machine-rust.conf` ABSENT in Default-State |

Both AXIS-5 GREEN is the precondition for entering the KW-26
Doppel-Welle window. See §10 in the wrapper script for the
operator-hand workflow.

## 9. Mira-Hand-Folge-Items

1. Operator-hand replay this probe with `--expected-hash
   <PR-224-lifecycle-state-machine-pin-pack-anchor>` and paste
   verdict into §5.
2. Operator-hand replay matching `welle-4-pre-cutover-probe.sh` in
   the same window (§8 Doppel-Welle precondition).
3. If either probe yields `BLOCK` or `CAUTION`: route to Tomás
   (Welle-5 fsm) / Reza (Welle-4 state_backing) for source-fix per
   `feedback_live_bringup_sandbox_gap.md` BEFORE KW-26 cutover
   window-start.

## 10. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0065 (Phase-3c Cutover-Plan)
- ADR-0066 (Phase-3c Doppel-Welle order; KW-26 Welle-4 + Welle-5)
- PR #224 (Pin-Pack Cross-Lang Anchor — provides AXIS-6 expected-hash)
- PR #249 (Welle-5 lifecycle_state_machine End-to-End Cutover-Smoke)
- PR #250 (Tag-38 migrate-version — 11 BackendDecision baseline)
- PR #267 (Welle-1 Pre-Cutover-Probe template — Tag-41)
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Kai Hoffmann (DevOps-3), 2026-05-18, Sprint-Tag-42.*

— Kai
