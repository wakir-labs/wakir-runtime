# Phase-3-Marathon-Rollback Workflow Runbook (Tomás Tag-56)

| Field | Value |
|---|---|
| Owner | Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065 §Rollback-Strategie](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066 §Rollback](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) |
| Workflow | [`.github/workflows/phase-3-marathon-rollback.yml`](../../.github/workflows/phase-3-marathon-rollback.yml) |
| Aggregator | [`tooling/ci/aggregate_marathon_rollback_manifest.py`](../../tooling/ci/aggregate_marathon_rollback_manifest.py) |
| Helpers | [`emit_marathon_rollback_audit_marker.py`](../../tooling/ci/emit_marathon_rollback_audit_marker.py), [`emit_marathon_rollback_welle_envelope.py`](../../tooling/ci/emit_marathon_rollback_welle_envelope.py), [`build_marathon_rollback_ar_notify.py`](../../tooling/ci/build_marathon_rollback_ar_notify.py) |
| Tests | [`tests/ci/test_phase_3_marathon_rollback_workflow.py`](../../tests/ci/test_phase_3_marathon_rollback_workflow.py) |
| Drill-Suite | [`tests/acceptance/phase_3c/rollback_drill/`](../../tests/acceptance/phase_3c/rollback_drill/) |

## Purpose

Operator-Hand-triggered rollback orchestration that walks the
Phase-3-Marathon back to the pre-Cutover-Day-N0 substrate state in a
deterministic, per-Welle sequence. The workflow is the CI-side
companion to the per-Komponente Rollback-Drill suite — it stitches the
per-Welle envelopes into a single rollback-run manifest the AR-Hand can
ratify.

Rollback during a live Phase-3-Marathon is the worst possible moment to
be hand-rolling shell-pipelines. This workflow encodes the ADR-0065
§Rollback-Strategie step-order once, exposes the four knobs an operator
can legitimately tune, and refuses to run if the audit-trail-marker
would land in the wrong place.

## When to fire

- **Welle-N RD-3 cross-modul-drift failed.** A per-Welle Rollback-Drill
  test (`test_rd_3_cross_modul_konsistenz_post_rollback`) failed mid-
  marathon. Fire with `start_at_welle=<wN>` to roll back from that Welle
  downward.
- **Cutover-Day-Practice-Run abort.** The Tag-55 watch-day-practice-run
  simulator emitted a RED verdict; the AR decides to abort the live
  cutover for the day. Fire with `start_at_welle=all`.
- **AR-Hand cancel.** Aufsichtsrat decides the marathon must abort
  irrespective of CI status. Fire with `start_at_welle=all`.
- **Welle-4 state_backing drift.** The state_backing snapshot-restore
  flagged drift post-cutover. Fire with `start_at_welle=w4` (rolls back
  Welle-4 through Welle-1; Welle-5..7 stay on the rust backend).

## Trigger surface

`workflow_dispatch` only. No `schedule:`, no `push:`. Rollback is, by
definition, AR-Hand or operator-hand. Auto-fire would be a
category-error.

## Inputs

| Input | Type | Default | Notes |
|-------|------|---------|-------|
| `rollback_reason` | string | "AR-Hand initiated rollback" | Free-form audit text logged in J0 preamble. |
| `start_at_welle` | choice | `all` | One of `all|w7|w6|w5|w4|w3|w2|w1`. Rollback walks reverse-cutover-order (W7 first). |
| `mode` | choice | `stub` | `stub` = CI hermetic; `live` = Pilot-VM operator-hand only (J1 guard refuses non-self-hosted). |
| `dry_run` | boolean | `true` | Stub-mode dry-run is the CI-validate path; set `false` only for live-mode Pilot-VM fires. |
| `allow_partial_rollback` | boolean | `false` | When `false` (default), per-Welle failure halts the orchestration (fail-fast). When `true`, downstream Wellen still execute. |

## Job graph

```
J0 preamble (cycle-id mint)
   |
J1 audit-emit (audit-marker JSON; live-mode guard)
   |
J2 W7 recovery_workflow rust->python  (reverse-cutover order)
   |
J3 W6 subscribe_loop rust->python
   |
J4 W5 lifecycle_state_machine rust->python
   |
J5 W4 state_backing rust->python  + snapshot-restore-planned
   |
J6 W3 bridge_audit_writer rust->python
   |
J7 W2 svid_workload_identity rust->python
   |
J8 W1 v907_verify rust->python
   |
J10 aggregator (rollback-run manifest: READY/PARTIAL/FAILED)
   |
J11 AR-Hand notify-payload (ntfy.sh JSON artifact)
```

Each per-Welle job (J2..J8) ``needs:`` the previous Welle job AND the
J1 audit-emit. The `if:` expressions filter on `start_at_welle` so
specific Wellen execute only when in-scope. When `allow_partial_rollback
= false`, a per-Welle failure short-circuits downstream Wellen via
`needs.<previous>.result != 'failure'`.

## Verdict semantics

The J10 aggregator collects per-Welle status (`green|yellow|red|skipped`)
and emits a top-level verdict:

- **READY** — every executed Welle green; zero red, zero yellow.
  Rollback orchestration completed cleanly. AR-Hand may ratify.
- **PARTIAL** — any yellow OR only-skipped run. The system is mid-state;
  operator-hand intervention required to drive it to either fully-rolled-
  back or fully-cutover. AR-Hand notify priority 4.
- **FAILED** — any executed Welle red. The rollback orchestration broke
  (e.g. welle<->modul binding drift, snapshot-restore missing for
  Welle-4). AR-Hand notify priority 5 (max).

## Per-Welle status mapping

The per-Welle envelope-emitter (`emit_marathon_rollback_welle_envelope.py`)
produces:

| Condition | Welle Status |
|-----------|--------------|
| Welle<->modul binding correct, mode=stub, dry_run any | `green` |
| Welle-4 without `--with-snapshot-restore=true` | `yellow` |
| `--with-snapshot-restore=true` set for non-Welle-4 (silently ignored) | `yellow` |
| mode=live (envelope still recorded; execution blocked by J1 guard) | `yellow` |
| Welle<->modul binding drift (e.g. welle=3 modul=state_backing) | `red` |

## Audit-trail marker

The J1 audit-emit job writes
`out/rollback/audit-marker-<cycle-id>.json` BEFORE any per-Welle
backend-switch. Even if the workflow itself crashes mid-run (e.g. J5
state_backing snapshot-restore throws), the audit trail still records
the rollback attempt. Henrik (Internal Audit) counts attempted vs.
completed rollbacks against the ADR-0065 §Rollback-Strategie SLA budget
without scraping run-logs.

The marker is uploaded as artifact `marathon-rollback-audit-marker`.

## AR-Hand notify

The J11 job builds a ntfy-shaped JSON envelope at
`out/rollback/ar-hand-notify-payload.json`. The workflow does NOT POST
to ntfy.sh by design — the operator-hand curl-POSTs the artifact after
ratifying:

```bash
gh run download <run-id> --name marathon-rollback-ar-hand-notify-payload
curl -fsSL -X POST -H "Content-Type: application/json" \
  -d @ar-hand-notify-payload.json \
  https://ntfy.sh
```

Separation: CI prepares the payload deterministically, operator fires
the notification. Matches the audit-trail-first pattern.

## Stub-mode vs. live-mode

**Stub-mode** (default, runs on `ubuntu-latest`):

- No podman, no NATS, no Pilot-VM, no Anthropic API.
- Per-Welle jobs run a Python stub-emitter that writes a per-Welle
  envelope-JSON.
- Aggregator stitches the seven envelopes into a single rollback-run
  manifest.
- Hermetic test-suite enforces shape parity.

**Live-mode** (reserved for operator-hand on Pilot-VM):

- The J1 audit-emit job carries a guard-step that refuses to run if
  `mode=live` AND runner is not self-hosted. CI cannot execute a live-
  mode rollback.
- The actual ENV-Flag-Switch (rust→python in the Quadlet unit-file)
  happens via the operator-hand procedure documented in
  `docs/phase-3c/cutover-operator-cheat-sheet.md`. This workflow only
  prepares the manifest and audit-record envelope.

## Operator procedure (stub-mode dry-run, CI sanity)

1. Open Actions UI → workflow `phase-3-marathon-rollback`.
2. Fire `Run workflow` with defaults (mode=stub, dry_run=true,
   start_at_welle=all, allow_partial_rollback=false).
3. Wait for J10 aggregator green.
4. Download the rollback manifest artifact `marathon-rollback-
   manifest` and verify `verdict=READY` and `counts.green=7`.
5. The dry-run is complete — no Pilot-VM state changed.

## Operator procedure (live-mode, Pilot-VM)

1. **Do NOT fire from this workflow.** Live-mode is a category-error
   on the GitHub-hosted runner.
2. Follow `docs/phase-3c/cutover-operator-cheat-sheet.md` §Rollback for
   the per-Welle ENV-Flag-Switch via SSH+Quadlet on the Pilot-VM.
3. After the live ENV-Flag-Switch is complete, fire this workflow with
   `mode=stub`, `dry_run=false` to record the audit-trail marker and
   per-Welle envelope retroactively for Henrik's audit sample.

## Hermetic test-suite

The test-suite (`tests/ci/test_phase_3_marathon_rollback_workflow.py`)
asserts:

- Workflow YAML shape (`workflow_dispatch` only; no schedule/push).
- Job graph topology (J0→J1→J2..J8→J10→J11).
- Per-Welle `needs:` and `if:` filters honour `start_at_welle`.
- Concurrency-group is distinct from cutover-day-auto-scheduler.
- Audit-marker schema (v1) is well-formed.
- Per-Welle envelope schema (v1) emits the right status for the right
  inputs (green/yellow/red branches).
- Aggregator verdict-rule (READY/PARTIAL/FAILED matrix).
- AR-Hand notify-payload priority mapping (3/4/5).
- All four helper scripts are stdlib-only (no third-party imports).

Run locally:

```bash
pytest -q tests/ci/test_phase_3_marathon_rollback_workflow.py
```

## Cross-references

- `tests/acceptance/phase_3c/rollback_drill/` — per-Komponente RD-1..RD-4
  drill-suite. The drill-suite validates the *backend* rollback
  semantics; this workflow orchestrates the *CI* rollback envelope.
- `.github/workflows/phase-3-cutover-day-auto-scheduler.yml` — the
  Cutover-Day forward-direction counterpart. Distinct concurrency-group.
- `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md`
  §Rollback-Strategie — ENV-Flag-Switch ≤10min SLA per Welle.
- `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` §Rollback —
  Doppel-Welle-Rollback-Kompatibilität.

— Tomás
