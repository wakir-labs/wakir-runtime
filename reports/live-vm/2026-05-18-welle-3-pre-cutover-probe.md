<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-3 Pre-Cutover-Probe (Tag-42)

**Date (UTC):** 2026-05-18T18:35Z
**Sprint-Tag:** 42
**Operator:** Selin Çelik (Persona-Engine), via Mira-SSH-Hand
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 3 (`bridge_audit_writer`)
**Probe-Script:** `scripts/phase-3c/welle-3-pre-cutover-probe.sh`
**ADR-Authority:** ADR-0058 §Nachtrag (Mira-SSH-Hand), ADR-0066
§Welle-3 (Phase-3c KW-25 solo wave, bridge_audit_writer)

---

## 1. Executive Summary

**Status:** `PROBE-NOT-EXECUTED`
**Reason:** Mira-Sandbox classifier blocks live VM-read SSH calls
(same classifier behaviour as documented in Kai's PR #267
§4 and the Welle-2 Tag-42 probe sibling-report).
**Cutover-Readiness-Bewertung Welle-3:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41 carried forward to Tag-42: non-blocking).

This report follows the same AR-Direktive Kai's PR #267 followed:
*"Wenn wakir-pilot VM nicht erreichbar ist (SSH-timeout, Service-down),
dann reports/live-vm-Datei mit 'PROBE-NOT-EXECUTED' Status + Reason
erstellen, statt Auftrag zu blockieren."*

The substantial work — the reproducible probe-wrapper-CLI + hermetic
test bed + documented **six-axis** verification rubric (one more
than Welle-1/2 because of the Welle-3 Self-Reference-Trap-Pre-Check
requirement from ADR-0066 §Welle-3-Risiken) — is delivered and
ready for operator-hand replay. The wrapper is verified hermetically
in this PR (10/10 tests green); live execution against the pilot is
queued for the next operator-hand window.

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-3-pre-cutover-probe.sh` ships in this PR.
Six-axis verification rubric, exit-code-disciplined, mirrors Kai's
PR #267 shape with `bridge_audit_writer`-specific axis content plus
the Self-Reference-Trap-Pre-Check (AXIS-0).

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all six axes matched; Welle-3 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-3 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Six verification axes (bridge_audit_writer)

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| **AXIS-0** Self-Reference-Trap-Pre-Check | In-engine vs. independent-oracle head | `persona-engine-cli bridge-audit-head --json` `head_seq` matches `tail -1 /var/log/persona-engine/bridge-audit.jsonl` `seq`. 1-row drift -> YELLOW; >=2 drift -> RED. *Mitigates ADR-0066 §Welle-3-Risiken Consistency-Oracle-Selbst-Cutover-Risiko* |
| AXIS-1 Audit-Stream-Continuity | head advance since boot | `head_seq - start_seq >= --min-head-delta` (default 5) |
| AXIS-2 Independent-Oracle-Probe | `audit-replay --tail N` vs. on-disk tail | matching seq count `>= --replay-tail-n` for GREEN; `>= --replay-match-min` for YELLOW |
| AXIS-3 BackendDecision-Stream | journalctl + component row | `>= --min-decisions` BackendDecisions *and* `component=bridge_audit_writer backend=python` row present |
| AXIS-4 Cross-Lang-Hash-Parity (PR #224, bridge-audit fixture) | Hash equality | Remote `persona-engine-cli bridge-audit-writer-hash --canonical-fixture pin-pack-bridge-audit-v1` emits hash equal to `--expected-hash <hex>` |
| AXIS-5 Rollback-Surface-Capability | levers + overlay absent | All four rollback levers present *and* `welle-3-bridge-audit-writer-rust.conf` overlay file is absent in Default-State |

### Sandbox-Hermetic-Tests

The wrapper has 10 hermetic pytest tests under
`tests/scripts/test_welle_3_pre_cutover_probe.py` (exceeds the
Auftrag-Tag-42 minimum of 8):

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_missing_ssh_key_returns_precondition_without_dry_run`
3. `test_dry_run_aggregates_green_with_expected_hash`
4. `test_dry_run_aggregates_caution_without_expected_hash`
5. `test_ssh_unreachable_emits_not_exec_verdict`
6. `test_all_axes_green_renders_green`
7. `test_axis_0_self_reference_trap_drift_renders_block`
8. `test_axis_0_self_reference_one_row_drift_renders_caution`
9. `test_axis_1_no_head_advance_renders_block`
10. `test_axis_2_independent_oracle_partial_match_renders_caution`

Tests stub `ssh` via `$WAKIR_SSH_BIN` so CI never touches the live VM
(per Memory `feedback_sandbox_host_trennung.md`). Local run on
Tag-42: `10 passed in 0.87s`.

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked)

- **Probe-host clock (UTC):** captured by the wrapper at run-time
  (`PROBE_TS` field).
- **Probe-host repo head:** `64b1c170` (Tag-41 Cutover-Day
  Live-Stream-Aggregator baseline, per Tag-42 spawn-anker).
- **In-repo Pin-Pack bridge-audit anchor (PR #224):** to be confirmed
  during operator-hand live-execution by passing `--expected-hash`
  via `WAKIR_PROBE_EXPECTED_HASH` env or `--expected-hash` flag.

## 4. Probe-Run-Log

```
$ timeout 8 ssh -i /home/fred/.ssh/wakir-pilot-vm-diagnose \
    -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    root@192.168.178.116 "echo CONNECTED"
[Tag-41 attempt log per PR #267 §4: classifier denies the deeper
read — same boundary applies for Welle-3 bridge_audit_writer
content reads. Operator-hand replay outside the classifier is the
established workflow.]
```

The block is at the *content-read* layer of the Mira-sandbox
classifier, not at the network or auth layer. The probe script's
NOT-EXEC verdict (exit code 4) is the correct, non-blocking
classifier-equivalent of this state.

## 5. Verifikations-Ergebnisse pro Achse

| Axis | Verdict | Detail |
|------|---------|--------|
| AXIS-0 Self-Reference-Trap-Pre-Check | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-1 Audit-Stream-Continuity | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 Independent-Oracle-Probe | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 BackendDecision-Stream | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 Cross-Lang-Hash-Parity (PR #224 bridge-audit) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer |

Hermetic dry-run of the wrapper (exit-code 0, AGGREGATE=GREEN with
`--expected-hash bridgehash321 --dry-run`) confirms the *script*
mechanics; the *live verdict* requires operator-hand replay.

## 6. Bug-Findings

No live VM-side bugs surfaced in this probe (probe did not execute
against the substrate).

**Substrate-Design-Note (Self-Reference-Trap-Pre-Check, AXIS-0):**

AXIS-0 is the Welle-3-specific axis Henrik flagged in ADR-0066
§Welle-3-Risiken. The bridge_audit_writer is the system under test;
using its own audit-replay CLI to verify its head pointer would be
the consistency-oracle-self-cutover trap. The probe therefore reads
the head from *two* independent sources:

1. **In-engine view:** `persona-engine-cli bridge-audit-head --json`
   reports the writer's current head sequence number.
2. **Independent-oracle view:** `tail -1 <audit-log-path>` reads the
   on-disk JSONL emitted by the writer's kernel-side flush — a
   second, decoupled source.

The two views must agree on `seq` (0-row drift) for GREEN; 1-row
drift is the in-flight-flush tolerance window for YELLOW; >=2-row
drift is RED (the oracles have actually diverged — the writer
either lost an entry or is hallucinating one). This is the
*pre-cutover* analog of the PR #240 Welle-3 smoke A7 assert (which
captures the audit-stream baseline *before* the focus-component
flips). Both anchors enforce the same invariant against different
parts of the system lifecycle.

## 7. Cutover-Readiness-Bewertung Welle-3

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators (from prior Tag-N work):**

- Welle-3 bridge_audit_writer Cutover-Smoke (PR #240, with A7
  self-reference-trap-mitigation-control assert) merged Tag-36.
- Welle-3 Operator-Cutover-Runbook (PR #239) merged.
- Reza-Tag-36 `resolve_bridge_audit_writer_backend` wire-in landed.
- PR #224 Pin-Pack Cross-Lang Anchor (bridge-audit fixture set)
  merged.
- Welle-3 Pre-Cutover-Probe-Wrapper (this PR, Tag-42).
- KW-25 cutover-window start ~16. Juni — sufficient slack for
  operator-hand replay of this probe before window-start.

**Recommendation:** Operator-hand replay of
`scripts/phase-3c/welle-3-pre-cutover-probe.sh` outside the
Mira-sandbox classifier, with the PR #224 Pin-Pack bridge-audit
anchor hash provided via `--expected-hash`, before the KW-25
Welle-3 cutover step. Result paste-back into §5 of this report
converts `PROBE-NOT-EXECUTED` into a hard verdict.

## 8. Mira-Hand-Folge-Items

1. Operator-hand replay this probe against pilot VM with
   `--expected-hash <PR-224-bridge-audit-pin-pack-anchor>` and paste
   verdict into §5.
2. If `BLOCK` or `CAUTION` on AXIS-0: route as Welle-3-Substanz-Issue
   to Reza (Identity-Substrate is adjacent) / Tomás (cross-lang
   hash) — but first verify the on-disk audit-log path
   (`/var/log/persona-engine/bridge-audit.jsonl` default) actually
   exists on the pilot; mis-path is the most likely false-positive.
3. If `BLOCK` on AXIS-4: PR #224 Pin-Pack drift — route to Tomás
   for the cross-lang fixture refresh.
4. KW-25 is the *solo* Welle-3 window — Welle-3 cutover does not
   pair with another welle for parallel cutover, but it must
   respect the Welle-1/2 KW-24 doppel-cutover predecessor by
   verifying the BackendDecision-Stream count (`--min-decisions 11`)
   reflects post-doppel state.

## 9. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0066 §Welle-3 (Phase-3c KW-25 solo wave, bridge_audit_writer
  + Welle-3-Risiken / Consistency-Oracle-Selbst-Cutover-Mitigation)
- PR #224 (Pin-Pack Cross-Lang Anchor — bridge-audit fixture set: AXIS-4 expected-hash)
- PR #239 (Welle-3 Operator-Cutover-Runbook)
- PR #240 (Welle-3 bridge_audit_writer End-to-End Cutover-Smoke + A7 assert)
- PR #250 (Tag-38 migrate-version — 11 BackendDecision baseline)
- PR #267 (Welle-1 Pre-Cutover-Probe template, Kai Tag-41)
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Selin Çelik (Persona-Engine), 2026-05-18, Sprint-Tag-42.*

— Selin
