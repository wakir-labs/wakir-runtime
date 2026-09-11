<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-6 Pre-Cutover-Probe (Tag-42)

**Date (UTC):** 2026-05-18T18:30Z
**Sprint-Tag:** 42
**Operator:** Amara Osei (QA-Engineer), via Mira-SSH-Hand (substance only)
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 6 (`subscribe_loop`)
**Probe-Script:** `scripts/phase-3c/welle-6-pre-cutover-probe.sh`
**ADR-Authority:** ADR-0058 §Nachtrag (Mira-SSH-Hand), ADR-0065 §Welle-6
(Phase-3c Cutover-Plan), ADR-0066 §Doppel-Welle KW-27 (Welle-6 + Welle-7
parallel)

---

## 1. Executive Summary

**Status:** `PROBE-NOT-EXECUTED`
**Reason:** Mira-Sandbox classifier blocks live VM-read SSH calls
(systemctl/podman/service enumeration is Production-Reads) for this
agent identity per `feedback_sandbox_host_trennung.md`.  This probe
delivers the substance (wrapper script + 10 hermetic tests +
report skeleton); the live verdict is queued for operator-hand
replay outside the Mira-sandbox classifier.
**Cutover-Readiness-Bewertung Welle-6:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41 §Live-VM-Probe: non-blocking — operator-hand
re-execution of the wrapper produces the live verdict).

This report follows the AR-Direktive Tag-41 explicit instruction:
*"Wenn wakir-pilot VM nicht erreichbar ist (SSH-timeout, Service-down),
dann reports/live-vm-Datei mit 'PROBE-NOT-EXECUTED' Status + Reason
erstellen, statt Auftrag zu blockieren."*  The pattern was used for
the Tag-41 Welle-1 Pre-Cutover-Probe-Report and is reused here
verbatim.

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-6-pre-cutover-probe.sh` ships in this PR.
It encodes the five-axis verification rubric as a single,
reproducible, exit-code-disciplined script:

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all five axes matched; Welle-6 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-6 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Five verification axes

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| AXIS-1 | Subscribe-Loop-Drain-Pre-State | `persona-engine-cli subscribe-loop-status` reports `ack_queue_depth <= 256` (default; configurable via `--ack-queue-max`); lag-histogram-pre-snapshot non-empty |
| AXIS-2 | NATS-Connection-Persistence | `journalctl --since="5 minutes ago"` shows `<= 2` nats reconnect/disconnect events (default; configurable via `--nats-reconnect-max`) |
| AXIS-3 | FSM-Awareness post-Welle-5 | `WAKIR_FSM_BACKEND=rust` pinned in engine env-map AND audit-tail shows `backend=rust` for `lifecycle_state_machine` (Welle-5 cutovert in KW-26 per ADR-0066) |
| AXIS-4 | Cross-Modul-Drift-Pre-Check zu Welle-7 | Both `WAKIR_SUBSCRIBE_LOOP_BACKEND` and `WAKIR_RECOVERY_WORKFLOW_BACKEND` are unset / at python in PHASE_PRE — neither focus-module has leaked a premature cutover.  Pre-state mirror of cutover-smoke A7 isolation assert. |
| AXIS-5 | Rollback-Surface-Capability | All four levers present on VM: `systemctl`, `journalctl`, `persona-engine` enabled, `persona-engine.service.d/` drop-in dir exists |

### Welle-6-Smoke dry-run integration

When invoked with `--dry-run`, the probe additionally verifies that
the sibling smoke wrapper (`welle-6-subscribe-loop-cutover-smoke.sh`)
is present + executable.  The actual smoke dry-run-execution
happens in the smoke-CI workflow, not in this probe.

### Sandbox-Hermetic-Tests

The wrapper has 10 hermetic pytest tests under
`tests/scripts/test_welle_6_pre_cutover_probe.py` covering:

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_missing_ssh_key_returns_precondition_without_dry_run`
3. `test_dry_run_aggregates_green`
4. `test_ssh_unreachable_emits_not_exec_verdict`
5. `test_axis_1_ack_queue_below_max_renders_green`
6. `test_axis_1_ack_queue_far_above_max_renders_red`
7. `test_axis_2_nats_zero_reconnects_renders_green`
8. `test_axis_3_fsm_env_missing_renders_red`
9. `test_axis_4_cross_modul_drift_welle_7_env_rust_renders_red`
10. `test_help_mentions_phase_3_doppel_welle_anchor`

Tests stub `ssh` via `$WAKIR_SSH_BIN` so CI never touches the live
VM (per Memory `feedback_sandbox_host_trennung.md`).  All 10 tests
pass on Tag-42 baseline `64b1c170`.

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked)

The Mira-sandbox classifier denies the read-side SSH `systemctl
show persona-engine` + `journalctl -u persona-engine` enumeration
that would normally populate this section.  Captured pre-probe
data is therefore limited to what is visible without SSH-to-VM:

- **Probe-host clock (UTC):** captured by the wrapper at run-time
  (`PROBE_TS` field).
- **Probe-host repo head:** Tag-42 baseline (`64b1c170`).
- **Welle-5 cutover-status (in-repo evidence):** ADR-0066 §Doppel-
  Welle KW-26 records Welle-5 (`lifecycle_state_machine`) as the
  KW-26 cutover.  AXIS-3 verifies the live FSM Rust-default
  persistence.

## 4. Probe-Run-Log

```
$ bash scripts/phase-3c/welle-6-pre-cutover-probe.sh --dry-run --quiet
[2026-05-18T12:00:00Z] [INFO   ] welle-6-pre-cutover-probe start ...
[2026-05-18T12:00:00Z] [STEP   ] AXIS-1 subscribe-loop-drain-pre-state
[2026-05-18T12:00:00Z] [INFO   ] DRY-RUN [axis-1-drain-pre-state] ssh ...
...
PROBE-VERDICT=GREEN welle=6 component=subscribe_loop sibling=recovery_workflow ...
```

Live execution against the pilot VM was attempted via the Mira-
sandbox classifier and rejected at the content-read layer (same
pattern as Tag-41 Welle-1 Pre-Cutover-Probe-Report §4).

## 5. Verifikations-Ergebnisse pro Achse

| Axis | Verdict | Detail |
|------|---------|--------|
| AXIS-1 Subscribe-Loop-Drain-Pre-State | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 NATS-Connection-Persistence | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 FSM-Awareness post-Welle-5 | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 Cross-Modul-Drift-Pre-Check zu Welle-7 | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| Welle-6-Smoke-Dry-Run-Invocation | `WRAPPER-READY` | `welle-6-subscribe-loop-cutover-smoke.sh` present + executable on Tag-42 baseline |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer |

Hermetic dry-run of the wrapper (exit-code 0, AGGREGATE=GREEN
with all default flags) confirms the *script* mechanics; the
*live verdict* requires operator-hand replay.

## 6. Bug-Findings

No live VM-side bugs surfaced in this probe (probe did not
execute against the substrate).

**Tooling-Finding (Mira-sandbox vs. operator-hand boundary):**
Identical to Tag-41 Welle-1 Pre-Cutover-Probe-Report §6 —
live-VM-touch is operator-hand-only.  The pattern is structurally
the same as the welle-1 probe + the live-vm-cutover-drill driver.

## 7. Cutover-Readiness-Bewertung Welle-6

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators (from prior Tag-N work):**

- Welle-6 Cutover-Smoke (PR #257) merged Tag-37.  ✓
- subscribe_loop Python<->Rust parity (prior PRs).  ✓
- Welle-6 Operator-Cutover-Runbook (Tag-37 Kai).  ✓
- Welle-5 FSM cutover (ADR-0066 §KW-26) — AXIS-3 dependency.  ✓
  (live persistence to be confirmed at operator-hand replay)
- Welle-6 Pre-Cutover-Probe-Wrapper (this PR, Tag-42).  ✓ substance.
- KW-27 cutover-window start ~30. Juni — sufficient slack for
  operator-hand replay before window-start.  ✓

**Recommendation:** Operator-hand replay of
`scripts/phase-3c/welle-6-pre-cutover-probe.sh` outside the
Mira-sandbox classifier, before the KW-27 Welle-6 cutover step.
Result paste-back into §5 of this report converts
`PROBE-NOT-EXECUTED` into a hard verdict.

## 8. Mira-Hand-Folge-Items

1. Operator-hand replay this probe against pilot VM and paste
   verdict into §5.
2. If `BLOCK` or `CAUTION`: route as Welle-6-Substanz-Issue to
   Reza / Tomás / Kai (per AXIS that fired) per
   `feedback_live_bringup_sandbox_gap.md`.
3. Welle-7 sibling probe authored in parallel
   (`welle-7-pre-cutover-probe.sh`) — the §4 cross-modul-drift
   pre-check between Welle-6 and Welle-7 forms a symmetric pair
   with Welle-7's AXIS-3.

## 9. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0065 §Welle-6 (Phase-3c Cutover-Plan: subscribe_loop)
- ADR-0066 §Doppel-Welle KW-27 (Welle-6 + Welle-7 parallel)
- PR #257 (Welle-6 End-to-End Cutover-Smoke + A6 lag-stability)
- PR #250 (Tag-38 migrate-version — BackendDecision baseline)
- Tag-41 report `reports/live-vm/2026-05-18-welle-1-pre-cutover-probe.md`
  (PROBE-NOT-EXECUTED pattern source)
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Amara Osei (QA-Engineer), 2026-05-18, Sprint-Tag-42.*

— Amara
