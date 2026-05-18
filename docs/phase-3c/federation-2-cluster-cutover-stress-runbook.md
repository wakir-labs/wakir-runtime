<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Phase-3c — 2-Cluster Federation Cutover-Stress-Runbook (Tag-44)

**Status:** Living operator companion.
**Scope:** Operator-Hand-companion for
`scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh`
(Tag-44, Kai-DevEng-3).
**Predecessors:**
* `scripts/phase-3c/live-vm-cutover-drill.sh` (Tag-40 single-org).
* `scripts/phase-3c/welle-{1..7}-pre-cutover-probe.sh` (Tag-41).
* `scripts/federation-live-vm-acceptance.sh` (Sprint-10 Tag-6,
  M-3 Federation Live-Trial).
**Anchors:** ADR-0058 §Nachtrag, ADR-0065, ADR-0066,
`docs/decisions/topology-bilateral-federation.md`.

---

## 1. Why a separate 2-cluster-stress drill exists

The Tag-40 `live-vm-cutover-drill.sh` exercises the per-Welle Phase-3c
cutover on the **single-org topology** that ships on `wakir-pilot`
(192.168.178.116). It enacts the overlay drop-in + service-restart +
boot-audit sequence per ADR-0065 §3.3..§3.5 and is the canonical
day-of marathon driver for the KW-24 cutover window.

Phase-4 production-rollout (KW-12+, ADR-0066 §"Production-Setup")
operates the substrate as a **2-cluster federation**:
`wakir-pilot` + `wakir-orbit` (192.168.178.191) both in
federation-mode (Option A "Pilot-Symmetric" from
`docs/decisions/topology-bilateral-federation.md`). The M-3
Federation Live-Trial established that federation-mode itself works
end-to-end at Sprint-10 Tag-5..Tag-8 (Bug-30..33 fixed). What it
did NOT exercise was the **cutover-window under federation-mode** —
i.e. whether per-Welle backend-flips on the pilot side disturb the
orbit-side engine or the federation bundle-sync path.

That gap is the substance behind Tag-44. The drill simulates a
Welle-N cutover on `wakir-pilot` while `wakir-orbit` participates
as a passive federation peer, and verifies three isolation /
durability properties:

1. **Pilot-side cutover semantics** — per-Welle BackendDecision audit
   emits the expected backend on the pilot side (mirrors
   live-vm-cutover-drill semantics).
2. **Cross-cluster engine isolation** — orbit-engine backend remains
   the documented Default-Backend (`python`) regardless of the
   pilot-side Welle-N cutover.
3. **Federation trust-bundle durability** — SPIFFE/SPIRE
   trust-bundle refresh across the pilot ↔ orbit link stays
   intact throughout the cutover window.

## 2. Stress-phase model

The drill walks four phases per invoked Welle. Each phase emits a
verdict (`green` / `yellow` / `red`); the overall Welle verdict is
the highest severity observed.

| Phase | Name | Side | Mutating | Verdict-criterion |
|------:|:-----|:----:|:--------:|:------------------|
| A | pre-stress-setup | both | no  | Both VMs reachable, both in federation-mode, both on Default-Backend (`python`). |
| B | stress (Welle-N cutover) | pilot | YES | Pilot-side overlay applied + service restart + BackendDecision boot-audit ≥ `--min-hits` (default 5). |
| C | drift-check | orbit | no  | Orbit emits ≥ 1 BackendDecision for `component=<welle.component>` with `backend=python` AND zero entries with `backend=<welle.env_value>` (no cross-cluster drift). |
| D | trust-stress | both | yes (refresh only) | Bundle-refresh succeeds on both sides; each side observes the partner bundle within `--trust-timeout` (default 30 s). |

### Verdict matrix

The overall Welle verdict is the maximum exit-code observed across
the four phases:

| Verdict | Exit-code | Meaning |
|:--------|:---------:|:--------|
| `GREEN` | 0 | All four phases green. Welle is safe for the federation cutover in Phase-4. |
| `CAUTION` | 1 | At least one phase yellow, none red. Operator-Hand-Decision required before promoting. |
| `BLOCK` | 2 | At least one phase red. Federation-cutover BLOCKED for this Welle. Investigate before Phase-4 KW-12+ rollout. |
| `PROBE-NOT-EXECUTED` | 4 | Phase A could not reach at least one VM. Non-blocking per Tag-41 AR-direktive; surface in the Acceptance-Report. |

### Welle-Matrix

Mirrors `scripts/phase-3c/live-vm-cutover-drill.sh` §Welle-Matrix.
Changes here MUST be reflected there and in
`docs/phase-3c/welle-{1..7}-*-runbook.md`.

| Welle | Component | Env-Var(s) | Env-Value | Overlay Basename |
|------:|:----------|:-----------|:----------|:------------------|
| 1 | `v907_verify` | `WAKIR_V907_VERIFY_BACKEND` | `rust` | `welle-1-v907-verify-rust.conf` |
| 2 | `svid_workload_identity` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` | `rust` | `welle-2-svid-workload-identity-rust.conf` |
| 3 | `bridge_audit_writer` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND, WAKIR_ANCHOR_EMITTER_BACKEND` | `rust` | `welle-3-bridge-audit-writer-rust.conf` |
| 4 | `state_backing` | `WAKIR_STATE_BACKING_BACKEND` | `rust_inmemory` | `welle-4-state-backing-rust.conf` |
| 5 | `lifecycle_state_machine` | `WAKIR_FSM_BACKEND` | `rust` | `welle-5-lifecycle-state-machine-rust.conf` |
| 6 | `subscribe_loop` | `WAKIR_SUBSCRIBE_LOOP_BACKEND` | `rust` | `welle-6-subscribe-loop-rust.conf` |
| 7 | `recovery_workflow` | `WAKIR_RECOVERY_BACKEND` | `rust` | `welle-7-recovery-workflow-rust.conf` |

## 3. Pre-flight checklist

Before running the drill against live VMs:

1. **Operator-Hand-Authority confirmed** — Mira-SSH-Hand per
   ADR-0058 §Nachtrag (KW-20). No AR escalation required for the
   read-only phases A, C, D. Phase B is mutating (overlay + restart)
   and follows ADR-0066 Doppel-Welle Order; if Welle-N is sequenced
   after a parent that is not yet on the rust backend in Phase-4,
   defer the drill for Welle-N.
2. **SSH keys present and readable**:
   * `$HOME/.ssh/wakir-pilot-vm-diagnose` (or via
     `--pilot-ssh-key PATH`).
   * `$HOME/.ssh/wakir-orbit-vm-diagnose` (or via
     `--orbit-ssh-key PATH`).
3. **Both VMs in federation-mode** — `WAKIR_PILOT_MODE=federation`
   active on each. Confirm via the bilateral-precheck step:
   `WAKIR_BILATERAL_PRECHECK=1 bash infra/spire/federation/wakir-pilot-bootstrap.sh`
   on each VM (Sprint-10 Tag-8 substrate).
4. **Both engines on Default-Backend** — no overlay drop-ins present
   in `/etc/systemd/system/wakir-persona-engine.service.d/` on
   either side. Phase A verifies this; deviations surface as
   `caution` (exit 1).
5. **Stress-log directory writable** — defaults to
   `/tmp/wakir-fed-2-cluster-stress`; override via
   `WAKIR_STRESS_LOG_DIR` or `--log-dir`.

## 4. Invocation patterns

### 4.1 Single Welle, all four phases

The default `--action stress` walks A → B → C → D and returns the
highest exit-code.

```bash
scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh \
  --welle 1
```

### 4.2 Full marathon (all 7 Wellen, numeric order)

Walks Welle 1..7 sequentially; stops on first non-zero verdict.
Numeric order is deliberate — parallel Doppel-Welle order from
ADR-0066 would muddy the drift-check signal.

```bash
scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh \
  --full-marathon
```

### 4.3 Single phase only (for incident-replay)

```bash
# Re-run phase C alone for Welle-3 after a manual orbit-side fix.
scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh \
  --welle 3 --action drift-check
```

Single-phase actions: `pre-stress-setup`, `stress-only`,
`drift-check`, `trust-stress`.

### 4.4 Sandbox-stub mode (CI / hermetic test)

Short-circuits every remote SSH call to a deterministic stub keyed
by env-vars. This is what the hermetic test suite consumes — it
never opens a real SSH connection.

```bash
WAKIR_STUB_PILOT_REACH="PILOT_REACH_OK" \
WAKIR_STUB_ORBIT_REACH="ORBIT_REACH_OK" \
WAKIR_STUB_PILOT_FEDERATION_MODE="enabled" \
WAKIR_STUB_ORBIT_FEDERATION_MODE="enabled" \
WAKIR_STUB_PILOT_BACKEND_DEFAULT="BACKEND=python" \
WAKIR_STUB_ORBIT_BACKEND_DEFAULT="BACKEND=python" \
WAKIR_STUB_PILOT_BOOT_AUDIT="5" \
WAKIR_STUB_ORBIT_DRIFT_PYTHON="3" \
WAKIR_STUB_ORBIT_DRIFT_OTHER="0" \
WAKIR_STUB_PILOT_TRUST_OBSERVE="1" \
WAKIR_STUB_ORBIT_TRUST_OBSERVE="1" \
  scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh \
    --welle 1 --sandbox-stub-mode
```

The stub var name is `WAKIR_STUB_<SIDE>_<DESC>` where `<SIDE>` is
`PILOT` / `ORBIT` and `<DESC>` is the `desc` argument passed into
`remote_exec`. Dashes in the desc are converted to underscores.

### 4.5 Dry-run (plan-without-execute on live infra)

```bash
scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh \
  --welle 1 --dry-run
```

Logs every SSH-command that would have been sent. No remote
mutation. Useful before a cutover-window to sanity-check the
overlay payloads.

## 5. Interpreting the output

The drill writes a per-invocation log file under
`${WAKIR_STRESS_LOG_DIR}/welle-N-ACTION-TIMESTAMP.log` (or
`marathon-TIMESTAMP.log` for `--full-marathon`). Every log line is
also emitted to stderr (suppress non-error chatter with `--quiet`).

Look for the trailing `[VERDICT]` lines:

```
[2026-05-18T19:38:26Z] [VERDICT] phase A green: both sides in federation-mode + default-backend
[2026-05-18T19:38:26Z] [VERDICT] phase B green: pilot cutover boot-audit met min-hits
[2026-05-18T19:38:26Z] [VERDICT] phase C green: orbit on backend=python, no drift from pilot cutover
[2026-05-18T19:38:26Z] [VERDICT] phase D green: trust-bundle roundtrip observed on both sides
[2026-05-18T19:38:26Z] [VERDICT] welle=1 STRESS-VERDICT=GREEN (A=0 B=0 C=0 D=0)
```

The final `STRESS-VERDICT=` line is the canonical artefact for the
Acceptance-Report; the per-phase rc values record the precise
exit-code observed per phase (helps when triaging a `CAUTION`).

## 6. Rollback considerations

Phase B writes an overlay drop-in and restarts the pilot-side
`wakir-persona-engine.service`. **The drill does not rollback
automatically.** When the post-drill verdict is anything other than
`GREEN`, follow the per-Welle runbook §6 rollback path
(`docs/phase-3c/welle-N-*-runbook.md`):

1. SSH to `wakir-pilot`.
2. `rm /etc/systemd/system/wakir-persona-engine.service.d/welle-N-*.conf`.
3. `systemctl daemon-reload && systemctl restart wakir-persona-engine.service`.
4. Verify backend reverted to `python` via journalctl BackendDecision
   stream.

The orbit side is read-only in phase C; no rollback there. Phase D's
trust-refresh is idempotent — re-running with `--action trust-stress`
is the rollback for any transient bundle-sync hiccup.

## 7. CI integration

The drill ships with hermetic tests under
`tests/scripts/test_federation_2_cluster_cutover_stress.py` (12+
vectors) which exercise every code path through
`--sandbox-stub-mode`. The tests run as part of the existing
`tests` workflow (`production-suite` + `sandbox-suite-shadow`
lanes; ADR-0035 drift-envelope intact because every new test
collects in both lanes).

No new required-status-check is introduced; the existing six checks
cover this drill:

* `License-Hygiene Gate (ADR-0061)`
* `wirelang suite with rfc8785 + jsonschema`
* `wirelang suite without rfc8785 / jsonschema (shadow)`
* `production-vs-sandbox drift envelope`
* `cross-repo drift (wakir-runtime ↔ wakir-protocol)`
* `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)`

## 8. Authority + sandbox boundary

This drill is **operator-hand**. It is NOT run from the Mira-sandbox
against live VMs; the sandbox cannot reach 192.168.178.* per
`feedback_sandbox_host_trennung.md`. The substance + tests of the
drill are landed via the regular PR workflow (sandbox-CI lane); the
live-VM execution is done by Mira-Hand inside an
operator-authorised window per ADR-0058 §Nachtrag.

When the AR (or Mira) wants a live-VM run, request an SSH-Hand
authorisation; that lifts the sandbox-boundary for one drill-invocation.

## 9. Open follow-ups

* **Federation-bundle-sync metrics** — phase D currently checks
  presence of the partner bundle. A future tag should add a
  freshness probe (`bundle.created_at` within X seconds of refresh)
  as an additional yellow/red boundary.
* **N-cluster generalisation** — the drill assumes 2 clusters. The
  ADR-0066 production-setup is explicitly 2-cluster but post-Phase-4
  may grow to N=3 (DR-cluster). When that happens, the
  `pilot_exec` / `orbit_exec` split should generalise to a
  `peer_exec <side>` indirection.

— Kai (DevEng-3 / DevOps), Tag-44, 2026-05-18.
