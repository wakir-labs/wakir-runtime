<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-4 Pre-Cutover-Probe (Tag-42)

**Date (UTC):** 2026-05-18T18:35Z
**Sprint-Tag:** 42
**Operator:** Kai Hoffmann (DevOps-3), via Mira-SSH-Hand
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 4 (`state_backing`)
**Pair-Welle:** 5 (`lifecycle_state_machine`) — KW-26 Doppel-Welle
**Probe-Script:** `scripts/phase-3c/welle-4-pre-cutover-probe.sh`
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
**Cutover-Readiness-Bewertung Welle-4:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41: non-blocking — wrapper queued for
operator-hand replay).

This follows the AR-Direktive Tag-41 PROBE-NOT-EXECUTED clause:
the substance (probe wrapper + hermetic tests + report skeleton)
ships in this PR; live execution against the pilot is queued for
the next operator-hand window, well ahead of the KW-26 Doppel-
Welle cutover.

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-4-pre-cutover-probe.sh` encodes the six-
axis verification rubric for Welle-4 state_backing:

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all six axes matched; Welle-4 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-4 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Six verification axes

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| AXIS-1 | State-Read-Compatibility-Stub | Remote `state-backing-cli snapshot --json --canonical` emits non-empty JCS-bytes payload |
| AXIS-2 | Welle-4 Cutover-Smoke dry-run (PR #245) | Remote `welle-4-state-backing-cutover-smoke.py --dry-run` exits with `RC=0` |
| AXIS-3 | BackendDecision-Stream-Health | `>= 11` BackendDecision audit entries since boot (Tag-38 PR #250 baseline) AND state_backing component-tail shows `backend=python` |
| AXIS-4 | Cross-Lang-Parity (Pin-Pack PR #224) | Remote `state-backing-cli snapshot-hash --canonical-fixture pin-pack-v1` matches `--expected-hash` |
| AXIS-5 | Cross-Modul-Drift-Pre-Check zu Welle-5 | Pair overlay `welle-5-lifecycle-state-machine-rust.conf` ABSENT AND pair audit-tail not `backend=rust` |
| AXIS-6 | Rollback-Surface-Capability | All four levers present: `systemctl`, `journalctl`, `persona-engine` enabled, `persona-engine.service.d/` dir exists |

### Sandbox-Hermetic-Tests

`tests/scripts/test_welle_4_pre_cutover_probe.py` carries 8 hermetic
pytest tests:

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_missing_ssh_key_returns_precondition_without_dry_run`
3. `test_dry_run_aggregates_green_with_expected_hash`
4. `test_dry_run_aggregates_caution_without_expected_hash`
5. `test_ssh_unreachable_emits_not_exec_verdict`
6. `test_all_axes_green_renders_green_aggregate`
7. `test_axis_5_pair_overlay_present_renders_block`
8. `test_axis_2_smoke_dry_run_failure_renders_block`

All `ssh` calls stubbed via `$WAKIR_SSH_BIN` so CI never touches
the live VM (per Memory `feedback_sandbox_host_trennung.md`).

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked)

Limited to what is visible without SSH-to-VM:

- **Probe-host clock (UTC):** captured by wrapper at run-time
  (`PROBE_TS` field).
- **Probe-host repo head:** `64b1c170` (Tag-41 baseline, per
  Tag-42-Spawn-Anker).
- **PR #224 Pin-Pack anchor for state_backing:** to be supplied at
  operator-hand replay via `--expected-hash` flag.

## 4. Probe-Run-Log

```
$ bash scripts/phase-3c/welle-4-pre-cutover-probe.sh \
      --expected-hash <PR-224-state-backing-pin-pack-anchor> \
      --quiet
ERROR: Permission for this action was denied by the Claude Code
auto mode classifier. Reason: Reading inside a running pilot VM
via SSH (systemctl/podman/service enumeration) is a Production
Reads action that pulls live service state into the transcript
without explicit user approval for this exact remote read.
```

SSH connectivity itself is confirmed-reachable (Tag-41 probe-1 ran
the initial `echo CONNECTED` succession). The block is at the
content-read layer of the Mira-sandbox classifier, not at the
network or auth layer.

## 5. Verifikations-Ergebnisse pro Achse

| Axis | Verdict | Detail |
|------|---------|--------|
| AXIS-1 State-Read-Compatibility-Stub | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 Welle-4 Smoke dry-run | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 BackendDecision-Stream-Health | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 Cross-Lang-Parity (PR #224) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Cross-Modul-Drift zu Welle-5 | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-6 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer |

Hermetic dry-run of the wrapper (exit-code 0, AGGREGATE=GREEN with
`--expected-hash deadbeef`) confirms the *script* mechanics; the
*live verdict* requires operator-hand replay.

## 6. Bug-Findings

None — probe did not execute against the substrate.

**Tooling-Finding:** None new beyond Tag-41 Welle-1 probe report;
the sandbox-vs-operator-hand boundary holds.

## 7. Cutover-Readiness-Bewertung Welle-4

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators:**

- Welle-4 Cutover-Smoke (PR #245) merged. -- verified (PR baseline)
- state_backing canonical JCS encoder (Phase-3a) merged. -- verified
- Welle-4 Operator-Cutover-Runbook (Tag-36 Welle-3 successor pattern). -- in-place
- Welle-4 Pre-Cutover-Probe-Wrapper (this PR, Tag-42). -- substance
- KW-26 cutover window start ~23. Juni — sufficient slack for
  operator-hand replay before window-start.

**Recommendation:** Operator-hand replay of
`scripts/phase-3c/welle-4-pre-cutover-probe.sh` outside the Mira-
sandbox, with the PR #224 Pin-Pack state_backing anchor hash via
`--expected-hash`, before the KW-26 Welle-4 cutover step. Run
**before or jointly with** Welle-5 Pre-Cutover-Probe per §10
Doppel-Welle Coordination Note.

## 8. Doppel-Welle KW-26 Coordination

Welle-4 and Welle-5 run in parallel during the KW-26 cutover window
(ADR-0066). Both pre-cutover probes share a symmetric AXIS-5
Cross-Modul-Drift-Pre-Check:

| Probe | AXIS-5 verifies |
|-------|------------------|
| welle-4-pre-cutover-probe.sh | Welle-5 overlay `welle-5-lifecycle-state-machine-rust.conf` ABSENT in Default-State |
| welle-5-pre-cutover-probe.sh | Welle-4 overlay `welle-4-state-backing-rust.conf` ABSENT in Default-State |

These two AXIS-5 GREEN verdicts together form the *precondition* for
entering the KW-26 Doppel-Welle window. Both must be GREEN before
either cutover step starts. See §10 in the wrapper script for the
full operator-hand workflow.

## 9. Mira-Hand-Folge-Items

1. Operator-hand replay this probe with `--expected-hash
   <PR-224-state-backing-pin-pack-anchor>` and paste verdict into
   §5 of this report.
2. Operator-hand replay matching `welle-5-pre-cutover-probe.sh` in
   the same window (§8 Doppel-Welle precondition).
3. If either probe yields `BLOCK` or `CAUTION`: route to Reza
   (Welle-4 state_backing) / Tomás (Welle-5 fsm) for source-fix per
   `feedback_live_bringup_sandbox_gap.md` BEFORE KW-26 cutover
   window-start.

## 10. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0065 (Phase-3c Cutover-Plan)
- ADR-0066 (Phase-3c Doppel-Welle order; KW-26 Welle-4 + Welle-5)
- PR #224 (Pin-Pack Cross-Lang Anchor — provides AXIS-4 expected-hash)
- PR #245 (Welle-4 state_backing End-to-End Cutover-Smoke)
- PR #250 (Tag-38 migrate-version — 11 BackendDecision baseline)
- PR #267 (Welle-1 Pre-Cutover-Probe template — Tag-41)
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Kai Hoffmann (DevOps-3), 2026-05-18, Sprint-Tag-42.*

— Kai
