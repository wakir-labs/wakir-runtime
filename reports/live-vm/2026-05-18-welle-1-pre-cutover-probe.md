<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-1 Pre-Cutover-Probe (Tag-41)

**Date (UTC):** 2026-05-18T17:48Z
**Sprint-Tag:** 41
**Operator:** Kai Hoffmann (DevOps-3), via Mira-SSH-Hand
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 1 (`v907_verify`)
**Probe-Script:** `scripts/phase-3c/welle-1-pre-cutover-probe.sh`
**ADR-Authority:** ADR-0058 §Nachtrag (Mira-SSH-Hand), ADR-0065 (Phase-3c
Cutover-Plan), ADR-0066 (Doppel-Welle order)

---

## 1. Executive Summary

**Status:** `PROBE-NOT-EXECUTED`
**Reason:** Mira-Sandbox classifier blocked the live VM-read SSH calls
("Reading inside a running pilot VM via SSH (systemctl/podman/service
enumeration) is a Production Reads action that pulls live service state
into the transcript without explicit user approval for this exact
remote read.") — see §4 for full classifier response.
**Cutover-Readiness-Bewertung Welle-1:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41: non-blocking — operator-hand re-execution of
the wrapper script outside the sandbox classifier produces the live
verdict).

This report follows the AR-Direktive Tag-41 explicit instruction:
*"Wenn wakir-pilot VM nicht erreichbar ist (SSH-timeout, Service-down),
dann reports/live-vm-Datei mit 'PROBE-NOT-EXECUTED' Status + Reason
erstellen, statt Auftrag zu blockieren."*

The substantial work — the reproducible probe-wrapper-CLI + hermetic
test bed + documented five-axis verification rubric — is delivered and
ready for operator-hand replay. The wrapper is verified hermetically in
this PR; live execution against the pilot is queued for the next
operator-hand window.

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-1-pre-cutover-probe.sh` ships in this PR. It
encodes the five-axis verification rubric as a single, reproducible,
exit-code-disciplined script:

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all five axes matched; Welle-1 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-1 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Five verification axes

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| AXIS-1 | Engine-State-Snapshot reachable | `persona-engine-cli state-pack` + `audit-stream-snapshot` emit non-empty payload via SSH |
| AXIS-2 | BackendDecision count >= 11 | `journalctl -u persona-engine` since boot has >= `WAKIR_PROBE_MIN_BACKEND_DECISIONS` BackendDecision lines (Tag-38 PR #250 baseline) |
| AXIS-3 | Default-State backend=python | No `welle-1-v907-verify-rust.conf` overlay present *and* audit-tail shows `backend=python` for `v907_verify` |
| AXIS-4 | Cross-Lang-Hash-Parity (PR #224) | Remote `persona-engine-cli v907-verify-hash --canonical-fixture pin-pack-v1` emits hash equal to `--expected-hash <hex>` from in-repo Pin-Pack anchor |
| AXIS-5 | Rollback-Surface-Capability | All four levers present on VM: `systemctl`, `journalctl`, `persona-engine` enabled, `persona-engine.service.d/` drop-in dir exists |

### Sandbox-Hermetic-Tests

The wrapper has 8 hermetic pytest tests under
`tests/scripts/test_welle_1_pre_cutover_probe.py` covering:

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_missing_ssh_key_returns_precondition_without_dry_run`
3. `test_dry_run_aggregates_green_with_expected_hash`
4. `test_dry_run_aggregates_caution_without_expected_hash`
5. `test_ssh_unreachable_emits_not_exec_verdict`
6. `test_axis_2_observed_above_min_renders_green`
7. `test_axis_2_observed_below_min_above_zero_renders_yellow`
8. `test_axis_3_overlay_present_renders_red`

Tests stub `ssh` via `$WAKIR_SSH_BIN` so CI never touches the live VM
(per Memory `feedback_sandbox_host_trennung.md`).

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked)

The Mira-sandbox classifier denied the read-side SSH `systemctl
list-units` + `podman ps` enumeration that would normally populate
this section. Captured pre-probe data is therefore limited to what is
visible without SSH-to-VM:

- **Probe-host clock (UTC):** captured by the wrapper at run-time
  (`PROBE_TS` field).
- **Probe-host repo head:** `4ce08c2` (Tag-40 Phase-3-Final-Regression
  baseline, per Tag-41-Spawn-Anker).
- **In-repo Pin-Pack anchor (PR #224):** to be confirmed during
  operator-hand live-execution by passing `--expected-hash` via
  `WAKIR_PROBE_EXPECTED_HASH` env or `--expected-hash` flag.

## 4. Probe-Run-Log

```
$ timeout 8 ssh -i /home/fred/.ssh/wakir-pilot-vm-diagnose \
    -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    root@192.168.178.116 "echo CONNECTED"
CONNECTED

$ timeout 15 ssh ... root@192.168.178.116 "hostname; date -u; ..."
ERROR: Permission for this action was denied by the Claude Code
auto mode classifier. Reason: Reading inside a running pilot VM
via SSH (systemctl/podman/service enumeration) is a Production
Reads action that pulls live service state into the transcript
without explicit user approval for this exact remote read.
```

SSH connectivity itself is confirmed-reachable (initial `echo
CONNECTED` succeeded). The block is at the *content-read* layer of the
Mira-sandbox classifier, not at the network or auth layer.

## 5. Verifikations-Ergebnisse pro Achse

| Axis | Verdict | Detail |
|------|---------|--------|
| AXIS-1 Engine-State-Snapshot | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 BackendDecision >= 11 | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 backend=python Default | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 Cross-Lang-Hash-Parity (PR #224) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer |

Hermetic dry-run of the wrapper (exit-code 0, AGGREGATE=GREEN with
`--expected-hash abc123`) confirms the *script* mechanics; the *live
verdict* requires operator-hand replay.

## 6. Bug-Findings

No live VM-side bugs surfaced in this probe (probe did not execute
against the substrate).

**Tooling-Finding (Mira-sandbox vs. operator-hand boundary):**

The Mira-sandbox classifier correctly enforces the
`feedback_sandbox_host_trennung.md` memory directive — live-VM-touch
is operator-hand-only. The Tag-41 AR-Direktive ("Live-Smoke =
Operator-Hand", "Live-VM-Probe via SSH-Hand") implies a workflow
where:

1. Kai (sandboxed agent) authors the probe wrapper + tests + report
   skeleton.
2. Operator hand (outside sandbox) replays
   `scripts/phase-3c/welle-1-pre-cutover-probe.sh` against the live
   VM with `--expected-hash <hex>`.
3. Operator pastes the resulting `[VERDICT] ...` log lines into the
   §5 table of this report, flipping the status from
   `PROBE-NOT-EXECUTED` to one of `GREEN` / `CAUTION` / `BLOCK`.

This is structurally the same pattern as Tag-40 live-vm-cutover-drill
(`scripts/phase-3c/live-vm-cutover-drill.sh`) — the substance lives
in the wrapper + hermetic test; the *live execution* is a separate
operator-hand step.

## 7. Cutover-Readiness-Bewertung Welle-1

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators (from prior Tag-N work):**

- Welle-1 Cutover-Smoke (PR #230) merged Tag-34. ✓
- v907_verify Python<->Rust parity (PR #229 / #233) merged. ✓
- Welle-1 Operator-Cutover-Runbook (PR #228) merged Tag-34. ✓
- Welle-1 Pre-Cutover-Probe-Wrapper (this PR, Tag-41). ✓ (substance)
- KW-24 cutover-window start ~9. Juni — sufficient slack for
  operator-hand replay of this probe before window-start. ✓

**Recommendation:** Operator-hand replay of
`scripts/phase-3c/welle-1-pre-cutover-probe.sh` outside the
Mira-sandbox classifier, with the PR #224 Pin-Pack anchor hash
provided via `--expected-hash`, before the KW-24 Welle-1 cutover step.
Result paste-back into §5 of this report converts
`PROBE-NOT-EXECUTED` into a hard verdict.

## 8. Mira-Hand-Folge-Items

1. Operator-hand replay this probe against pilot VM with
   `--expected-hash <PR-224-pin-pack-anchor>` and paste verdict
   into §5.
2. If `BLOCK` or `CAUTION`: route as Welle-1-Substanz-Issue to
   Reza / Tomás for source-fix per `feedback_live_bringup_sandbox_gap.md`.
3. Spawn equivalent probes for Welle-2..7 in subsequent Tag-N+ work
   (script template ready for parametric extension).

## 9. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0065 (Phase-3c Cutover-Plan: Welle-1 v907_verify)
- ADR-0066 (Phase-3c Doppel-Welle order)
- PR #224 (Pin-Pack Cross-Lang Anchor — provides AXIS-4 expected-hash)
- PR #228 (Welle-1 Operator-Cutover-Runbook)
- PR #230 (Welle-1 v907_verify End-to-End Cutover-Smoke)
- PR #250 (Tag-38 migrate-version — 11 BackendDecision baseline)
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Kai Hoffmann (DevOps-3), 2026-05-18, Sprint-Tag-41.*

— Kai
