# Phase-3c Cutover Runbook — Welle-1 v907_verify, Welle-2 svid_workload_identity

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065](../../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) (§Option-B per-Welle plan, lists `svid_workload_identity` as Welle-2), [0066](../../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) (Option-A+ Verkürzte-Sequenz, 4-Wochen-Marathon) |
| Substrate | [scripts/phase-3c-cutover-dry-run.py](../../scripts/phase-3c-cutover-dry-run.py) |
| Tests | [tests/scripts/test_phase_3c_cutover_dry_run.py](../../tests/scripts/test_phase_3c_cutover_dry_run.py) |
| Welle-1 component | `v907_verify` (KW 24-25 per ADR-0065 §Option-B) |
| Welle-2 component | `svid_workload_identity` (KW 25-26 per ADR-0065 §Option-B; ADR-0066 §Option-A+ may compress timing) |

## Purpose

ADR-0065 §Verifikations-Plan demands a Monday-morning Pilot-VM
acceptance-lane Live-Smoke before any per-component Cutover-PR
flips the production default backend from Python to Rust. That
live run is **Operator-Hand-territory**; it touches the Pilot-VM,
the real NATS bus, and the WAT anchor pipeline.

This runbook covers the **local dry-run** that operators run
*before* the live smoke. The dry-run never invokes the real Rust
binary, never connects to NATS, and never calls the Anthropic API.
Its purpose is to:

1. Rehearse the env-var flip (`WAKIR_<COMPONENT>_BACKEND=rust`) in
   a hermetic env-map and verify the resolver produces the
   expected `BackendDecision` records.
2. Surface a single `cutover_feasibility_score` in `[0.0, 1.0]`
   with a colour band (GREEN/AMBER/RED) that gates the decision to
   proceed to the live Pilot-VM smoke.
3. Optionally consult the real binary-probe (`--probe-real`) to
   verify the Rust CLI binary is deployed at
   `WAKIR_RUST_<COMPONENT>_BIN` — when the binary is missing, the
   dry-run renders `dry_run="blocked"` with an explicit error
   message rather than producing a misleading GREEN score.

## ADR-0065 §Option-B vs. in-repo substrate — naming drift

ADR-0065 §Option-B enumerates the eight cutover components
(Welle-1..7 plus `svid_workload_identity` at Welle-2; the §Option-B
table in ADR-0065 lists svid as the second row). ADR-0066 §Option-A+
keeps the same ordering but compresses the timeline. The eight
components in cutover order:

| Week | ADR long-form | In-repo short form | Resolver | Welle-Status |
|------|---------------|--------------------|----------|--------------|
| 1 | `v907_verify` | `v907_verify` | `resolve_v907_verify_backend` | shipped (PR #194 image, Welle-1 active) |
| 2 | `svid_workload_identity` | `svid_workload_identity` | `resolve_svid_workload_identity_backend` | shipped (PR #191 resolver, PR #201 image — `ready-pending-binary` until image-tag lands on Pilot-VM) |
| 3 | `bridge_audit_writer` | `anchor_emitter` | `resolve_anchor_emitter_backend` | shipped (PR #170/#175) |
| 4 | `state_backing` | `state_backing` | `resolve_state_backing_backend` | shipped |
| 5 | `lifecycle_state_machine` | `fsm` | `resolve_fsm_backend` | shipped |
| 6 | `subscribe_loop` | `subscribe_loop` | `resolve_subscribe_loop_backend` | shipped |
| 7 | `recovery_workflow` | `recovery` | `resolve_recovery_backend` | shipped |

Four observations:

- The dry-run script accepts **both** spellings for all aliased
  components. Operators may pass `--component lifecycle_state_machine`
  or `--component fsm`; the alias is resolved in `validate_component()`.
- `svid_workload_identity` uses the **same name** in the ADR long-form
  and the in-repo short form, so no alias entry is registered for it.
  Operators pass the name unchanged in both contexts. A regression
  test (`test_svid_workload_identity_has_no_alias_entry`) pins this.
- `svid_workload_identity` is `ready-pending-binary`: the Python-side
  resolver landed in PR #191 (Tag-25 Mini-Welle) and the Rust-CLI
  container-image-build-pipeline landed in PR #201 (Tag-29 Mini-Welle).
  Operationally this means the dry-run runs GREEN under the stub
  probe, but the live cutover-Mo `--probe-real` invocation will block
  with `dry_run="blocked"` until the operator has pulled the
  `wakir-persona-engine-svid-workload-identity:<tag>` image onto the
  Pilot-VM and the `WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN` env-var
  points at the installed binary. See the FAQ for the recovery flow.
- `bridge_audit_writer` is the ADR-0065 operator-facing name; in the
  substrate the resolver is `resolve_anchor_emitter_backend` because
  that crate writes the outer WAT-anchor envelope (PR #170, Tag-23).
  The dry-run accepts the alias.

## Acceptance criteria (per ADR-0065 §Verifikations-Plan)

The dry-run is the **Monday pre-check** for the cutover-PR. It
does not replace the live acceptance criteria AC-1..AC-5, which
are measured against actual Pilot-VM evidence over the
Beobachtungs-Woche.

The dry-run scores against three sub-signals that mirror the
production AC-1..AC-3 in shape:

| Dry-run sub-score | Production AC | Threshold |
|-------------------|---------------|-----------|
| `backend_purity` (weight 0.5) | AC-3 (Bug-Rate 0 in window) — if any boot falls back to Python, that's a substance signal | 1.0 for GREEN |
| `latency_score` (weight 0.3) | AC-2 (P95 ≤ Python baseline + 20%) — dry-run uses a 50 ms sanity ceiling, not the production tight bound | 1.0 at p95 ≤ budget; 0.0 at 4× budget |
| `fallback_score` (weight 0.2) | AC-3 (fallback events are S0/S1 in spirit) | 1.0 at zero fallbacks |

**Score bands:**

- `>= 0.95` → **GREEN**: proceed to ADR-0065 §Mo Live-Smoke.
- `>= 0.80` → **AMBER**: investigate before proceeding. Most
  common cause is a non-deterministic latency tail in a noisy
  sandbox — re-run with `--boots 24` to widen the sample.
- `< 0.80` → **RED**: do not proceed. Escalate to Tomás (Matrix-
  Lead). The two most likely root causes are: (a) the resolver is
  returning fallback-to-Python decisions for an unexpected reason,
  (b) ADR-0065 long-form-vs-short-form aliasing broke after a
  substrate change.

## How to run the dry-run

### Welle-1: `v907_verify` (default)

The simplest invocation — the dry-run defaults to Welle-1:

```bash
python scripts/phase-3c-cutover-dry-run.py
```

This produces a JSON envelope on stdout with `dry_run="completed"`,
12 boots' worth of decision records, and a feasibility score.

### Per-component dry-run

```bash
# ADR-0065 long-form name (accepted):
python scripts/phase-3c-cutover-dry-run.py --component lifecycle_state_machine

# Equivalent in-repo short-form name:
python scripts/phase-3c-cutover-dry-run.py --component fsm

# state_backing rust_natskv variant (still hermetic — no real NATS):
python scripts/phase-3c-cutover-dry-run.py \
  --component state_backing \
  --state-backing-variant rust_natskv
```

### Real binary-probe (optional, opt-in)

By default the dry-run uses a stub binary-probe that always
returns `available=True`. When the operator wants to verify the
Rust CLI binary is actually deployed on the local host:

```bash
python scripts/phase-3c-cutover-dry-run.py \
  --component v907_verify \
  --probe-real
```

If the binary is missing or not executable, the envelope is
rendered with `dry_run="blocked"`, `band="BLOCKED"`, and an
explicit `error` field. This is the dry-run's hard gate for
"the cutover cannot proceed because the substrate is not
deployed".

### Output options

```bash
# Write to file instead of stdout:
python scripts/phase-3c-cutover-dry-run.py \
  --component v907_verify \
  --output /tmp/phase-3c-v907-dry-run.json

# Widen the boot sample (default 12, useful for latency-tail debug):
python scripts/phase-3c-cutover-dry-run.py \
  --component v907_verify \
  --boots 48

# Tighten the p95 latency budget (default 50000 us = 50 ms):
python scripts/phase-3c-cutover-dry-run.py \
  --component v907_verify \
  --p95-latency-budget-us 10000
```

## Interpreting the JSON envelope

The envelope shape is stable per the script's `__all__` contract.
The cutover-PR Mo-status-report consumes the following fields:

```json
{
  "schema": "wakir.phase-3c.dry-run/1",
  "timestamp_utc": 1747487472,
  "component": "v907_verify",
  "env_var": "WAKIR_V907_VERIFY_BACKEND",
  "requested_backend": "rust",
  "boots": 12,
  "probe_mode": "stub",
  "dry_run": "completed",
  "decisions": [ ... 12 BackendDecision records ... ],
  "latency": {"avg": 87, "p50": 80, "p95": 140, "p99": 180, "count": 12},
  "chosen_backend_counts": {"rust": 12},
  "fallback_reason_counts": {"null": 12},
  "feasibility": {
    "cutover_feasibility_score": 1.0,
    "band": "GREEN",
    "subscores": {
      "backend_purity": 1.0,
      "latency_score": 1.0,
      "fallback_score": 1.0
    },
    "weights": {
      "backend_purity": 0.5,
      "latency_score": 0.3,
      "fallback_score": 0.2
    },
    "p95_latency_budget_us": 50000
  }
}
```

When `dry_run == "blocked"`:

```json
{
  "schema": "wakir.phase-3c.dry-run/1",
  "component": "v907_verify",
  "dry_run": "blocked",
  "probe_mode": "real",
  "decisions": [],
  "feasibility": {
    "cutover_feasibility_score": 0.0,
    "band": "BLOCKED",
    "p95_latency_budget_us": 50000
  },
  "error": "rust binary unavailable at '/opt/wakir/bin/wakir-persona-engine-v907-verify': binary_missing"
}
```

## Welle-1 to Welle-7 sequence

ADR-0065 §Verifikations-Plan defines a Mo-Fr cadence per component.
The dry-run slots into Mo Vormittag, **before** the Cutover-Welle-PR
review:

| Day | Activity | Owner | Substrate |
|-----|----------|-------|-----------|
| Mo | Dry-run for the week's component | Selin / Reza | `phase-3c-cutover-dry-run.py` (this script) |
| Mo | Cutover-Welle-PR (Quadlet-Default-Flip + Container-Image-Tag-Bump) | Reza, Tomás-Matrix-Lead-Phase-Gate-Verify | Cutover-PR |
| Mo-Abend | Pilot-VM-Acceptance-Lane-Run (Live-Smoke per ADR-0060) | Noa, Operator-Hand | `ci-live-vm-phase-3b-driver.sh` |
| Di | Bridge-Audit-Writer-Konsistenz-Report (24h-Fenster) | Selin | `backend-decision-observability.py` |
| Di-Fr | Beobachtungs-Fenster (Bug-Rate, Performance-Gauges, WAT-Anchor-Diff) | Noa, Amara | Grafana dashboards |
| Do | Cross-Review-Session | Tomás-Matrix-Lead-Moderation | — |
| Fr | Wochen-Cutover-Status-Report an Priya CTO | Tomás | — |
| Fr-Abend | Go/No-Go-Decision für nächste Komponente | Priya CTO + Tomás | — |

The dry-run does not replace any of these activities — it is the
local sandbox-side rehearsal that lets the Mo-cutover-PR be opened
with confidence. A RED dry-run is a signal that the cutover-PR
should not be opened that week.

## Operator FAQ

**Q: Why does the dry-run never invoke the real Rust binary by
default?**

A: Hermeticity. The script must be runnable from any sandbox —
the claude-dev toolbox, a CI runner, an operator's laptop — without
requiring `/opt/wakir/bin/wakir-persona-engine-*` to be installed.
`--probe-real` is opt-in for operators who specifically want the
binary-availability check.

**Q: Why does the dry-run never connect to NATS even with
`--state-backing-variant rust_natskv`?**

A: Same reason. The resolver returns a `BackendDecision` record
that documents the operator's intent (`requested_backend ==
"rust_natskv"`); it does not actually open a NATS connection.
The real NATS-bound boot happens during the Mo-Abend Pilot-VM
Live-Smoke.

**Q: How do I dry-run the Welle-2 component `svid_workload_identity`?**

A: Same as Welle-1, just with the explicit `--component` flag. The
resolver landed in PR #191 (Tag-25 Mini-Welle) and the dry-run-side
wire-in landed in PR #196 (Tag-29 Welle-2 Validation Workflow):

```bash
python scripts/phase-3c-cutover-dry-run.py \
  --component svid_workload_identity
```

Under the default stub binary-probe the envelope returns
`dry_run="completed"` with a GREEN-band feasibility score, mirroring
the Welle-1 v907_verify behaviour. The `env_var` field carries
`WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` and the `requested_backend`
field carries `rust`.

**Q: What is `ready-pending-binary` for `svid_workload_identity`?**

A: `ready-pending-binary` is the operational status the runbook
uses when the Python-side resolver and Rust-CLI container-image are
both built (PR #191 + PR #201) but the image has not yet been
pulled onto the Pilot-VM. In this state:

- The hermetic dry-run (stub probe, no `--probe-real`) renders
  `dry_run="completed"` and a GREEN feasibility score, because
  the script does not touch the filesystem.
- The `--probe-real` dry-run renders `dry_run="blocked"`,
  `band="BLOCKED"`, and `error` set to
  `"rust binary unavailable at '/opt/wakir/bin/wakir-persona-engine-svid-workload-identity': binary_missing"`
  until the operator deploys the
  `wakir-persona-engine-svid-workload-identity:<tag>` image and the
  `WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN` env-var points at the
  installed binary.

Recovery flow for `ready-pending-binary` → `ready`:

1. Operator pulls the image-tag on the Pilot-VM (Kai-Container-Bridge
   substrate, see `docs/operations/container-image-deployment.md`).
2. Operator sets `WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN` to the
   absolute path of the installed binary.
3. Operator re-runs the dry-run with `--probe-real`; the envelope
   must now return `dry_run="completed"` with a GREEN feasibility
   score before the Welle-2 cutover-PR is opened.

The dry-run script does not perform step 1 or 2 — both are
Operator-Hand territory per the Sandbox/Host-Operations Trennung
(no podman-socket access from claude-dev). The script's role is
to render the `ready-pending-binary` vs. `ready` distinction
visibly in its JSON envelope so the Mo-pre-check produces an
unambiguous gate signal.

**Q: Where is the Welle-2 substrate documented in detail?**

A: PR #191 (svid_workload_identity Python-side resolver), PR #196
(dry-run wire-in + Welle-2 Validation Workflow), PR #201 (Rust-CLI
container-image-build-pipeline), and ADR-0065 §Option-B (which
pins `svid_workload_identity` as the second cutover Welle).
ADR-0066 §Option-A+ governs the timeline compression but not the
component ordering. The duplicate PR #202 was closed in favour of
#191 and is not part of the substrate; the Tag-31 reconciliation
PR (this revision) was opened to bring the dry-run script header,
the runbook component table, and this FAQ in sync with the
already-shipped substrate.

**Q: Why is the default `--boots` value 12?**

A: It mirrors the Phase-3b live-smoke boot-count baseline from
ADR-0061..0063. Twelve boots yields a non-trivial latency
percentile sample (p95 = 12th-percentile-position nearest-rank
= sample index 12) while still being fast enough to fit a
sub-second Mo-pre-check workflow.

**Q: How does this interact with the
`backend-decision-observability.py` aggregator (Tag-22, Noa)?**

A: The aggregator consumes BackendDecision records from the
**production** engine's `log_sink` JSONL — what actually happened
on the Pilot-VM. The dry-run produces BackendDecision records
**in-memory** for a hermetic simulation — what *would* happen if
the operator flipped the env-var. The two are complementary: the
dry-run is Mo-pre-check, the aggregator is the Di-onwards
production-evidence pipeline.

## Cross-references

- ADR-0065 — Phase-3c Cutover-Plan.
- ADR-0063 — Persona-Engine-Sprach-Revision (Phase-3a/3b/3c
  scoping ADR).
- ADR-0060 — Live-FCOS-VM-CI-Gate (Live-Smoke substrate).
- ADR-0058 — Pilot-Persona-Migrations-Plan (Beobachtungs-Fenster-
  Disziplin pattern).
- [scripts/backend-decision-observability.py](../../scripts/backend-decision-observability.py)
  — Production-side BackendDecision aggregator (Tag-22, Noa).
- [wirelang/persona_engine/rust_backend_switch.py](../../wirelang/persona_engine/rust_backend_switch.py)
  — Per-component switch substrate (the resolvers this dry-run
  exercises).
