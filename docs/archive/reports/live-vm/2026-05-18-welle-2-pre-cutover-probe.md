<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Live-VM-Acceptance-Report — Welle-2 Pre-Cutover-Probe (Tag-42)

**Date (UTC):** 2026-05-18T18:35Z
**Sprint-Tag:** 42
**Operator:** Selin Çelik (Persona-Engine), via Mira-SSH-Hand
**Target VM:** `wakir-pilot` (192.168.178.116)
**Welle:** 2 (`svid_workload_identity`)
**Probe-Script:** `scripts/phase-3c/welle-2-pre-cutover-probe.sh`
**ADR-Authority:** ADR-0058 §Nachtrag (Mira-SSH-Hand), ADR-0065
§Option-B (Phase-3c Cutover-Plan Welle-2), ADR-0066 (Doppel-Welle order)

---

## 1. Executive Summary

**Status:** `PROBE-NOT-EXECUTED`
**Reason:** Mira-Sandbox classifier blocks live VM-read SSH calls
("Reading inside a running pilot VM via SSH (systemctl/podman/service
enumeration) is a Production Reads action that pulls live service state
into the transcript without explicit user approval for this exact
remote read.") — identical classifier behaviour as documented in
Kai's Tag-41 Welle-1 Pre-Cutover-Probe report
(`reports/live-vm/2026-05-18-welle-1-pre-cutover-probe.md` §4).
**Cutover-Readiness-Bewertung Welle-2:** `BLOCKED-ON-OPERATOR-HAND`
(per AR-Direktive Tag-41 carried forward to Tag-42: non-blocking —
operator-hand re-execution of the wrapper script outside the sandbox
classifier produces the live verdict).

This report follows the same AR-Direktive Kai's PR #267 followed:
*"Wenn wakir-pilot VM nicht erreichbar ist (SSH-timeout, Service-down),
dann reports/live-vm-Datei mit 'PROBE-NOT-EXECUTED' Status + Reason
erstellen, statt Auftrag zu blockieren."*

The substantial work — the reproducible probe-wrapper-CLI + hermetic
test bed + documented five-axis verification rubric pointed at
`svid_workload_identity` — is delivered and ready for operator-hand
replay. The wrapper is verified hermetically in this PR (10/10 tests
green); live execution against the pilot is queued for the next
operator-hand window.

## 2. Probe-Wrapper-CLI (Substanz)

`scripts/phase-3c/welle-2-pre-cutover-probe.sh` ships in this PR.
Five-axis verification rubric, exit-code-disciplined, mirrors Kai's
PR #267 shape with SVID-Workload-Identity-specific axis content.

| Exit | Meaning |
|------|---------|
| 0 | GREEN — all five axes matched; Welle-2 cutover GREEN |
| 1 | CAUTION — >= 1 axis YELLOW, none RED; Operator-Hand-Decision |
| 2 | BLOCK — >= 1 axis RED; Welle-2 cutover BLOCKED |
| 3 | PRECOND — bad args / missing SSH key |
| 4 | NOT-EXEC — VM unreachable / SSH failure |

### Five verification axes (SVID-Workload-Identity)

| Axis | Check | GREEN Criterion |
|------|-------|------------------|
| AXIS-1 | SPIFFE-ID-Resolution-Sanity | Remote `persona-engine-cli svid-workload-identity-resolve --json` emits a SPIFFE-ID matching `--trust-domain-regex` (default `^spiffe://[a-zA-Z0-9._-]+/.+$`) |
| AXIS-2 | SVID-Cert-Validity-Window | Cert `not_before <= now <= not_after` with TTL `>= --warn-cert-ttl` (default 3600 s); YELLOW between `--min-cert-ttl` and `--warn-cert-ttl`; RED below min or outside window |
| AXIS-3 | BackendDecision-Stream | `journalctl -u persona-engine --since=boot` shows `>= --min-decisions` BackendDecision lines (default 11; Tag-38 PR #250 baseline) *and* at least one row for `component=svid_workload_identity` with `backend=python` |
| AXIS-4 | Cross-Lang-Hash-Parity (PR #224, SVID fixture set) | Remote `persona-engine-cli svid-workload-identity-hash --canonical-fixture pin-pack-svid-v1` emits hash equal to `--expected-hash <hex>` from the in-repo Pin-Pack anchor |
| AXIS-5 | Rollback-Surface-Capability | All four levers present (`systemctl`, `journalctl`, `persona-engine` enabled, `persona-engine.service.d/` drop-in dir exists) *and* the Welle-2 overlay file (`welle-2-svid-workload-identity-rust.conf`) is *absent* in Default-State |

### Sandbox-Hermetic-Tests

The wrapper has 10 hermetic pytest tests under
`tests/scripts/test_welle_2_pre_cutover_probe.py` (exceeds the
Auftrag-Tag-42 minimum of 8):

1. `test_help_flag_prints_usage_and_exits_zero`
2. `test_missing_ssh_key_returns_precondition_without_dry_run`
3. `test_dry_run_aggregates_green_with_expected_hash`
4. `test_dry_run_aggregates_caution_without_expected_hash`
5. `test_ssh_unreachable_emits_not_exec_verdict`
6. `test_all_axes_green_renders_green`
7. `test_axis_1_invalid_spiffe_id_renders_caution`
8. `test_axis_2_cert_expired_renders_block`
9. `test_axis_2_cert_ttl_below_warn_renders_caution`
10. `test_axis_5_overlay_present_renders_block`

Tests stub `ssh` via `$WAKIR_SSH_BIN` so CI never touches the live VM
(per Memory `feedback_sandbox_host_trennung.md`). Local run on
Tag-42: `10 passed in 0.77s`.

## 3. Pre-Probe-Engine-State

**Status:** NOT-CAPTURED (sandbox-blocked)

The Mira-sandbox classifier denies the read-side SSH `systemctl
list-units` + `podman ps` enumeration that would normally populate
this section.

- **Probe-host clock (UTC):** captured by the wrapper at run-time
  (`PROBE_TS` field).
- **Probe-host repo head:** `64b1c170` (Tag-41 Cutover-Day
  Live-Stream-Aggregator baseline, per Tag-42 spawn-anker).
- **In-repo Pin-Pack SVID anchor (PR #224):** to be confirmed during
  operator-hand live-execution by passing `--expected-hash` via
  `WAKIR_PROBE_EXPECTED_HASH` env or `--expected-hash` flag.

## 4. Probe-Run-Log

```
$ timeout 8 ssh -i /home/fred/.ssh/wakir-pilot-vm-diagnose \
    -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    root@192.168.178.116 "echo CONNECTED"
[Tag-41 attempt log per PR #267 §4: classifier denies the deeper
read — same boundary applies for Welle-2 SVID-Workload-Identity
content reads. Operator-hand replay outside the classifier is the
established workflow.]
```

The block is at the *content-read* layer of the Mira-sandbox
classifier, not at the network or auth layer. The probe script's
NOT-EXEC verdict (exit code 4) is the correct, non-blocking
classifier-equivalent of this state — operators can replay outside
the sandbox and paste verdict into §5.

## 5. Verifikations-Ergebnisse pro Achse

| Axis | Verdict | Detail |
|------|---------|--------|
| AXIS-1 SPIFFE-ID-Resolution | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-2 SVID-Cert-Validity-Window | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-3 BackendDecision-Stream | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-4 Cross-Lang-Hash-Parity (PR #224 SVID) | `NOT-EXEC` | Sandbox-blocked SSH read |
| AXIS-5 Rollback-Surface | `NOT-EXEC` | Sandbox-blocked SSH read |
| **AGGREGATE** | **`NOT-EXEC`** | All axes blocked at content-read layer |

Hermetic dry-run of the wrapper (exit-code 0, AGGREGATE=GREEN with
`--expected-hash svidhash123 --dry-run`) confirms the *script*
mechanics; the *live verdict* requires operator-hand replay.

## 6. Bug-Findings

No live VM-side bugs surfaced in this probe (probe did not execute
against the substrate).

**Substrate-Design-Note (SVID-cert-TTL bucket):**

The Welle-2 probe adds a two-band TTL bucket
(`--min-cert-ttl` / `--warn-cert-ttl`) on top of the Welle-1
binary-axis rubric. This reflects the operational reality that SVID
certs rotate on a shorter cadence than v907 verify hashes — the warn
band gives operators a runway to renew the cert before the cutover
window opens. Default 600 s / 3600 s bands are conservative; operators
can tighten to 60 s / 600 s for short-rotation deployments by passing
the CLI flags.

## 7. Cutover-Readiness-Bewertung Welle-2

**Probe-Verdict:** `PROBE-NOT-EXECUTED`
**Substance-Readiness-Indicators (from prior Tag-N work):**

- Welle-2 SVID Cutover-Smoke (PR #234) merged Tag-35.
- SVID `resolve_svid_workload_identity_backend` (PR #191) merged.
- Welle-2 Operator-Cutover-Runbook (PR #232) merged.
- PR #224 Pin-Pack Cross-Lang Anchor (SVID fixture set) merged.
- Welle-2 Pre-Cutover-Probe-Wrapper (this PR, Tag-42).
- KW-24 cutover-window start ~9. Juni — sufficient slack for
  operator-hand replay of this probe before window-start.

**Recommendation:** Operator-hand replay of
`scripts/phase-3c/welle-2-pre-cutover-probe.sh` outside the
Mira-sandbox classifier, with the PR #224 Pin-Pack SVID anchor hash
provided via `--expected-hash`, before the KW-24 Welle-2 cutover step.
Result paste-back into §5 of this report converts
`PROBE-NOT-EXECUTED` into a hard verdict.

## 8. Mira-Hand-Folge-Items

1. Operator-hand replay this probe against pilot VM with
   `--expected-hash <PR-224-SVID-pin-pack-anchor>` and paste verdict
   into §5.
2. If `BLOCK` or `CAUTION`: route as Welle-2-Substanz-Issue to Reza
   (Identity-Substrate) / Tomás (cross-lang hash) for source-fix per
   `feedback_live_bringup_sandbox_gap.md`.
3. Pair this probe with Kai's Welle-1 probe (PR #267) for the
   KW-24 doppel-cutover (ADR-0066): both must report GREEN
   independently before the doppel-window opens.

## 9. Anchors

- ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
- ADR-0065 §Option-B (Phase-3c Cutover-Plan: Welle-2 svid_workload_identity)
- ADR-0066 (Phase-3c Doppel-Welle order: KW-24 W-1+W-2)
- PR #224 (Pin-Pack Cross-Lang Anchor — SVID fixture set: AXIS-4 expected-hash)
- PR #232 (Welle-2 Operator-Cutover-Runbook)
- PR #234 (Welle-2 SVID-Workload-Identity End-to-End Cutover-Smoke)
- PR #250 (Tag-38 migrate-version — 11 BackendDecision baseline)
- PR #267 (Welle-1 Pre-Cutover-Probe template, Kai Tag-41)
- Memory `feedback_sandbox_host_trennung.md`
- Memory `feedback_live_bringup_sandbox_gap.md`

---

*Authored by Selin Çelik (Persona-Engine), 2026-05-18, Sprint-Tag-42.*

— Selin
