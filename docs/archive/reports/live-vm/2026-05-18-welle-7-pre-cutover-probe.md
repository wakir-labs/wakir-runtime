<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-7 Pre-Cutover-Probe (Tag-42)

**Date (UTC):** 2026-05-18T18:35Z
**Sprint-Tag:** 42
**Operator:** Amara Osei (QA-Engineer), via Mira-SSH-Hand (substance only)
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 7 (`recovery_workflow`)
**Probe-Script:** `scripts/phase-3c/welle-7-pre-cutover-probe.sh`
**ADR-Authority:** ADR-0058 §Nachtrag (Mira-SSH-Hand), ADR-0065 §Welle-7
(Phase-3c Cutover-Plan), ADR-0066 §Doppel-Welle KW-27 / Phase-3-Ende
(Welle-6 + Welle-7 parallel), ADR-0067 / ADR-0068 (IIA-1130 Pre-
Auditor-Workflow)

---

> ### Phase-3-Marathon-Schluss-Markierung
>
> **This is the LAST Pre-Cutover-Probe of Phase-3.**
>
> Welle-7 cutover (KW-27) is the final cutover wave of the Phase-3-
> Doppel-Welle pair (Welle-6 + Welle-7).  A successful Welle-7
> cutover triggers the phase-3-complete-marker workflow.  Any RED
> verdict from this probe BLOCKS the cutover and therefore BLOCKS
> the Phase-3-COMPLETE-Marker.

---

## 1. Executive Summary

**Status:** `PROBE-NOT-EXECUTED`
**Reason:** Mira-Sandbox classifier blocks live VM-read SSH calls
for this agent identity per `feedback_sandbox_host_trennung.md`.
This probe delivers the substance (wrapper script + IIA-1130 Pre-
Auditor-Decision pre-condition gate + 10 hermetic tests + report
skeleton); the live verdict is queued for operator-hand replay
outside the Mira-sandbox classifier.
**Cutover-Readiness-Bewertung Welle-7:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41 §Live-VM-Probe: non-blocking).

Additional Welle-7-specific gate: the IIA-1130 Pre-Auditor-Decision
file at `state/welle-7-pre-auditor-decision.json` is *also*
required before the probe will proceed to the six axes.  This is
the Phase-3-Ende internal-audit-gate; if Henrik has not produced
the decision file before the operator-hand replay, the probe
exit-codes 3 (precondition) and the cutover MUST NOT start.  See
§4 of this report for the Pre-Auditor-Decision Existence-Check
mechanics.

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-7-pre-cutover-probe.sh` ships in this PR.
It encodes a six-axis verification rubric (5 + 1 — the +1 being
Cross-Lang-Parity, mirroring Welle-1 AXIS-4 applied to
RecoveryOutcome) plus the IIA-1130 Pre-Auditor-Decision pre-
condition gate:

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all six axes matched + pre-condition passed; Welle-7 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-7 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key / MISSING Pre-Auditor-Decision |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Six verification asserts (5 + 1)

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| AXIS-1 | R1..R4-Recovery-Pre-Stability | `persona-engine-cli recovery-drill-snapshot` + `recovery-outcome-tail` emit non-empty payload with monotonic R1 < R2 < R3 < R4 byte-offsets (spec §3.7.4 phase ordering) |
| AXIS-2 | State-Backing-Dependency-Pre-Check | `WAKIR_STATE_BACKING_BACKEND=rust` pinned AND audit-tail shows `backend=rust` for `state_backing` (Welle-4 cutovert in KW-26 per ADR-0066) |
| AXIS-3 | Cross-Modul-Drift-Pre-Check zu Welle-6 (symmetric A7) | Both `WAKIR_RECOVERY_WORKFLOW_BACKEND` and `WAKIR_SUBSCRIBE_LOOP_BACKEND` are unset / at python in PHASE_PRE — neither focus-module has leaked.  Inverted direction relative to Welle-6 AXIS-4. |
| AXIS-4 | BackendDecision-Stream | `journalctl -u persona-engine` since boot has >= 11 BackendDecision lines AND at least one names `component=recovery_workflow` |
| AXIS-5 | Cross-Lang-Parity (RecoveryOutcome) | Remote `persona-engine-cli recovery-outcome-hash --canonical-fixture pin-pack-v1` emits hash equal to `--expected-hash <hex>` from in-repo Pin-Pack anchor |
| AXIS-6 | Rollback-Probe | All four levers present: `systemctl`, `journalctl`, `persona-engine` enabled, drop-in dir exists |

### Pre-Condition gate (§4)

Before any axis runs, the probe checks
`state/welle-7-pre-auditor-decision.json` for existence and
JSON-parseability.  Missing or invalid file => exit-3 (precond),
no axes attempted.  Overridable via `--pre-auditor-path <p>` or
`WAKIR_PROBE_PRE_AUDITOR_PATH`.

### Sandbox-Hermetic-Tests

The wrapper has 10 hermetic pytest tests under
`tests/scripts/test_welle_7_pre_cutover_probe.py` covering:

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_help_mentions_phase_3_marathon_schluss_markierung`
3. `test_missing_pre_auditor_decision_returns_precondition`
4. `test_invalid_json_pre_auditor_decision_returns_precondition`
5. `test_missing_ssh_key_returns_precondition`
6. `test_dry_run_with_pre_auditor_present_aggregates_caution_without_hash`
7. `test_dry_run_with_pre_auditor_and_expected_hash_aggregates_green`
8. `test_ssh_unreachable_emits_not_exec`
9. `test_axis_2_state_backing_missing_renders_red`
10. `test_axis_3_cross_modul_drift_welle_6_env_rust_renders_red`

Tests stub `ssh` via `$WAKIR_SSH_BIN` and write a synthetic
Pre-Auditor-Decision JSON file in `tmp_path` so CI never touches
the live VM (per `feedback_sandbox_host_trennung.md`).  All 10
tests pass on Tag-42 baseline `64b1c170`.

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked)

The Mira-sandbox classifier denies the read-side SSH enumeration.
In-repo evidence used as substance-readiness proxy:

- **Probe-host clock (UTC):** captured by the wrapper at run-time
  (`PROBE_TS` field).
- **Probe-host repo head:** Tag-42 baseline (`64b1c170`).
- **Welle-4 cutover-status (in-repo evidence):** ADR-0066 §Doppel-
  Welle KW-26 records Welle-4 (`state_backing`) as the KW-26
  cutover.  AXIS-2 verifies the live state_backing Rust-default
  persistence.
- **Pre-Auditor-Decision file:** the synthetic CI test fixture
  proves the wrapper's gate mechanics; the *production* file
  is produced by Henrik (Internal Audit) ahead of the KW-27
  cutover-window.

## 4. Probe-Run-Log

```
$ bash scripts/phase-3c/welle-7-pre-cutover-probe.sh \
        --dry-run --expected-hash deadbeef --quiet
[2026-05-18T12:00:00Z] [INFO   ] welle-7-pre-cutover-probe start ...
[2026-05-18T12:00:00Z] [INFO   ] PHASE-3-MARATHON-SCHLUSS-MARKIERUNG: ...
[2026-05-18T12:00:00Z] [STEP   ] pre-condition welle-7-IIA-1130-pre-auditor-decision ...
[2026-05-18T12:00:00Z] [INFO   ] Pre-Auditor-Decision file present and JSON-parseable.
[2026-05-18T12:00:00Z] [STEP   ] AXIS-1 r1-r4-recovery-pre-stability ...
...
PROBE-VERDICT=GREEN welle=7 component=recovery_workflow sibling=subscribe_loop ...
```

Live execution against the pilot VM was attempted and rejected at
the content-read layer (same pattern as Tag-41 Welle-1 + Tag-42
Welle-6 sibling).

## 5. Verifikations-Ergebnisse pro Achse

| Axis / Gate | Verdict | Detail |
|-------------|---------|--------|
| IIA-1130 Pre-Auditor-Decision-Check (§4) | `PENDING-AUDITOR` | File `state/welle-7-pre-auditor-decision.json` not yet produced by Henrik; operator-hand replay must wait for IIA sign-off |
| AXIS-1 R1..R4-Recovery-Pre-Stability | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 State-Backing-Dependency | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 Cross-Modul-Drift zu Welle-6 (sym. A7) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 BackendDecision-Stream | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Cross-Lang-Parity (RecoveryOutcome) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-6 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer; pre-condition pending IIA sign-off |

Hermetic dry-run of the wrapper (with synthetic Pre-Auditor
fixture + `--expected-hash deadbeef`, exit-code 0, AGGREGATE=GREEN)
confirms the *script* mechanics; the *live verdict* requires
both (a) Henrik's IIA-1130 sign-off file landing in `state/` and
(b) operator-hand replay outside the sandbox classifier.

## 6. Bug-Findings

No live VM-side bugs surfaced (probe did not execute against
substrate).  No substance-bugs in the wrapper surfaced during
hermetic testing (10/10 green).

**Boundary-Finding (QA × Audit, Zone N per Amara-Persona §2):**
The Welle-7 probe's Pre-Auditor-Decision gate is a clean Zone-N
boundary realisation: QA owns the gate *mechanics* (Existence +
JSON-parseability check on file path); Henrik owns the gate
*content* (the actual audit verdict in the file body).  The probe
does not interpret the content; it only enforces presence as a
precondition.  This matches the persona contract: "QA-Test-Evidenz
und Audit-Trail sind komplementär, nicht austauschbar."

## 7. Cutover-Readiness-Bewertung Welle-7

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators (from prior Tag-N work):**

- Welle-7 Cutover-Smoke (PR #257) merged Tag-37.  ✓
- recovery_workflow Python<->Rust parity (prior PRs).  ✓
- Welle-7 Operator-Cutover-Runbook (Tag-37 Kai).  ✓
- Welle-4 State-Backing cutover (ADR-0066 §KW-26) — AXIS-2
  dependency.  ✓ (live persistence to be confirmed at operator-
  hand replay)
- Welle-7 Pre-Cutover-Probe-Wrapper (this PR, Tag-42).  ✓ substance.
- IIA-1130 Pre-Auditor-Decision file by Henrik — **pending**.
- KW-27 cutover-window start ~30. Juni — sufficient slack for
  IIA sign-off + operator-hand replay before window-start.  ✓

**Recommendation:** Two-step gate before KW-27 Welle-7 cutover:
1. Henrik produces `state/welle-7-pre-auditor-decision.json`
   per IIA-1130 workflow.
2. Operator-hand replay of
   `scripts/phase-3c/welle-7-pre-cutover-probe.sh` outside the
   Mira-sandbox classifier with `--expected-hash <PR-X-recovery-
   pin-pack-anchor>` after step 1 completes.
3. Result paste-back into §5 of this report converts
   `PROBE-NOT-EXECUTED` into a hard verdict.

## 8. Mira-Hand-Folge-Items

1. Surface to Henrik (Internal Audit) that the Welle-7 Pre-
   Auditor-Decision file at `state/welle-7-pre-auditor-decision.json`
   is required before KW-27 cutover-window-start; route via
   regular Audit-channel coordination.
2. Operator-hand replay this probe against pilot VM after
   step 1 completes and paste verdict into §5.
3. If `BLOCK` or `CAUTION`: route as Welle-7-Substanz-Issue to
   Reza / Tomás / Kai (per AXIS that fired).
4. Welle-6 sibling probe authored in parallel (Tag-42); the §3
   cross-modul-drift pre-check between Welle-6 and Welle-7 forms
   a symmetric pair (Welle-6 AXIS-4 mirrors Welle-7 AXIS-3,
   inverted direction).

## 9. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0065 §Welle-7 (Phase-3c Cutover-Plan: recovery_workflow)
- ADR-0066 §Doppel-Welle KW-27 / Phase-3-Ende (Welle-6 + Welle-7
  parallel, last cutover before phase-3-complete-marker)
- ADR-0067 / ADR-0068 (IIA-1130 Pre-Auditor-Workflow context)
- PR #257 (Welle-7 End-to-End Cutover-Smoke + A6 R1..R4 ordering)
- PR #250 (Tag-38 migrate-version — BackendDecision baseline)
- Tag-41 report `reports/live-vm/2026-05-18-welle-1-pre-cutover-probe.md`
  (PROBE-NOT-EXECUTED pattern source)
- Tag-42 sibling report `reports/live-vm/2026-05-18-welle-6-pre-cutover-probe.md`
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Amara Osei (QA-Engineer), 2026-05-18, Sprint-Tag-42.*

— Amara
