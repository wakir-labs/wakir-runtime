<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Phase-3c Trigger-Gate Aggregator

Operator-hand readiness check for the Phase-3c cutover (persona-engine
default-backend flip from Python to Rust). Defined by **ADR-0065**,
approved 2026-05-17.

## What this is

`scripts/phase-3c-trigger-gate-aggregator.py` is a stdlib + PyYAML
Python script that evaluates the **five declarative trigger-gates**
that ADR-0065 says must be green before the cutover starts. It does
**not** execute any live verification (no cosign, no podman, no
systemctl invocation) — that stays operator-hand per the
sandbox-host-trennung discipline. The aggregator validates that the
substrate the cutover decision rests on is in place.

Output is a go/no-go JSON report plus an exit-code that CI can
consume:

| Exit | Meaning |
|------|---------|
| `0`  | All five gates green — `ready_for_phase_3c=true`. |
| `1`  | At least one gate yellow (warning), none red. |
| `2`  | At least one gate red. |

## The five trigger-gates

### Gate 1 — Phase-3b 7/7 backend-resolvers

Checks that all seven backend-resolver functions are defined in
`wirelang/persona_engine/rust_backend_switch.py`:

| Resolver | Landed |
|----------|--------|
| `resolve_recovery_backend`        | Tag-17 Mini-Welle |
| `resolve_state_backing_backend`   | Tag-17 Mini-Welle |
| `resolve_fsm_backend`             | Tag-18 Mini-Welle |
| `resolve_v907_verify_backend`     | Tag-19 Mini-Welle |
| `resolve_bridge_diff_backend`     | Tag-20 Mini-Welle |
| `resolve_subscribe_loop_backend`  | Tag-22 Mini-Welle |
| `resolve_anchor_emitter_backend`  | Tag-23 Mini-Welle |

Any missing resolver flips the gate **red** — the gate cannot ride
on a partial Phase-3b.

### Gate 2 — Cosign-Policy binary inventory

Checks that `policies/cosign-policy-phase-3b.yaml` lists the expected
number of Rust-CLI binaries (default `--target-binary-count 7`). The
keyless Sigstore verification only covers what the policy declares;
any binary the persona-engine subprocess-bridges to that is not in
this inventory is an attack-surface gap.

Status mapping:

- `green` — `found_count == target_count` (exact match).
- `yellow` — `found_count < target_count` (work-in-progress, expected
  during the Tag-23 → Tag-24 inventory-extension window).
- `red` — `found_count > target_count` (drift; investigate before
  cutover).

### Gate 3 — Quadlet-Installer binary inventory

Same target-count contract as Gate 2, applied to
`quadlet/wakir-rust-cli.container`. The Quadlet oneshot installer
copies the binaries from the carrier image into the host-side
`/opt/wakir/bin/` named volume; the inventory must match the
Cosign-Policy inventory byte-for-byte at cutover-time.

The check counts distinct `wakir-persona-engine-*` tokens in the
file — repeated mentions (for-loop body + comment-block) collapse
via `set()`.

### Gate 4 — Backend-Decision-Observability baseline

Two sub-conditions:

1.  **Aggregator script presence**:
    `scripts/backend-decision-observability.py` must exist.
    Missing aggregator ⇒ **red** (we cannot evaluate the cutover
    fallback-rate floor without it).

2.  **Baseline JSONL evidence**: ≥7 distinct UTC days of
    `backend-decision` records must be present in the JSONL file
    pointed at by `WAKIR_PHASE_3C_OBS_BASELINE_PATH`. The script
    counts distinct days (not records) because the cutover-confidence
    floor in ADR-0065 is about *operational duration*, not boot
    frequency.

The baseline file is operator-hand-staged. The expected workflow
before the cutover-review:

```bash
# On the Pilot-VM (operator-hand):
scp pilot-vm:/var/log/wakir/backend-decisions.jsonl \
    ./obs-baseline.jsonl

# On the cutover-review host:
WAKIR_PHASE_3C_OBS_BASELINE_PATH=./obs-baseline.jsonl \
  python scripts/phase-3c-trigger-gate-aggregator.py
```

Status mapping:

- `green` — aggregator present + baseline file exists + ≥7 distinct
  days.
- `yellow` — aggregator present, but baseline ENV unset / file
  missing / fewer than the threshold days. The evidence record
  carries a `reason` field (one of `env-not-set`, `file-not-found`,
  `baseline-too-short`).
- `red` — aggregator missing.

### Gate 5 — Live-VM-Acceptance Driver existence

Checks that `scripts/ci-live-vm-phase-3b-driver.sh` exists and is
executable. The Tag-19 deliverable is the substrate the
`.github/workflows/live-vm-acceptance.yml` matrix shells out to;
without it the Phase-3b acceptance lane silently falls through to a
workflow-side stub-emit path.

Status mapping:

- `green` — file present + executable bit set.
- `yellow` — present but non-executable (would fall through to the
  workflow stub).
- `red` — file missing.

## CLI reference

```text
usage: phase-3c-trigger-gate-aggregator [-h] [--repo-root REPO_ROOT]
                                        [--target-binary-count N]
                                        [--min-baseline-days N]
                                        [--json]
```

| Flag | Default | Effect |
|------|---------|--------|
| `--repo-root` | parent of `scripts/` | Repo root for path resolution. |
| `--target-binary-count` | `7` | Expected inventory size for gates 2+3. |
| `--min-baseline-days` | `7` | Distinct-day floor for gate-4. |
| `--json` | off | Emit machine-readable JSON instead of the human summary. |

### JSON schema

```json
{
  "schema": "wakir.phase-3c.trigger-gate-report/1",
  "gates": [
    {
      "id": "gate-1",
      "name": "phase-3b-7-resolvers",
      "status": "green|yellow|red",
      "evidence": { "...": "..." }
    }
  ],
  "all_green": true,
  "ready_for_phase_3c": true
}
```

`ready_for_phase_3c` is `true` if and only if every gate is `green`.

## When to run

- **Pre-cutover-review**: operator runs it once with the JSONL
  baseline staged, to produce the go/no-go report for the AR
  decision packet.
- **CI nightly**: a workflow can invoke the script with
  `--target-binary-count 7` and treat exit-code 0 as the
  ready-signal that gates further Phase-3c-prep automation. (Such
  a workflow is **not** wired in by this PR; the substrate ships
  first, the wiring follows in a Tag-25+ step.)
- **Local sanity-check**: developers running it against `main`
  should see the live-state report (Tag-23 baseline: gates 2+3
  yellow at 5/7, gate-4 yellow at env-not-set, gates 1+5 green).

## Sandbox boundary

This aggregator is **hermetic**. It reads five repo files plus an
optional operator-hand-staged JSONL. It calls no network, no
container runtime, no signing tooling. The Phase-3c cutover decision
itself remains operator-hand per ADR-0065 §6 and the wider
sandbox-host-trennung discipline.

## Cross-references

- ADR-0065 — Phase-3c cutover (Python-default → Rust-default).
- `docs/operations/cosign-policy-phase-3b.md` — Operator-hand Sigstore
  verification recipe (Gate 2's substrate).
- `docs/operations/quadlets-phase-3b-rust-cli.md` — Installer
  bring-up notes (Gate 3's substrate).
- `docs/operations/live-vm-acceptance-phase-3b.md` — Live-VM
  acceptance lane (Gate 5's substrate).
- `scripts/backend-decision-observability.py` — Per-component
  fallback-rate aggregator (Gate 4's substrate).
