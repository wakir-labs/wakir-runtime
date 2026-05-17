# Phase-3c Welle-1 Validation Runbook — v907_verify

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead) |
| ADR | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) |
| Workflow | [`.github/workflows/phase-3c-welle-1-validation.yml`](../../.github/workflows/phase-3c-welle-1-validation.yml) |
| Tests | [`tests/workflows/test_phase_3c_welle_1_validation.py`](../../tests/workflows/test_phase_3c_welle_1_validation.py) |
| Cadence | Wednesday 06:00 UTC (≈08:00 CEST in May) + workflow_dispatch |
| Welle-1 component | `v907_verify` (KW 24-25) |

## Purpose

This runbook explains the **Welle-1 Validation Workflow**, the wired-
substrate readiness check that the Phase-3c Welle-1 cutover decision
rests on. ADR-0065 §Verifikations-Plan demands a Monday-morning Pilot-
VM Live-Smoke before the Welle-1 cutover-PR flips the production
default of `WAKIR_V907_VERIFY_BACKEND` from `python` to `rust`. The
Live-Smoke is **operator-hand-territory**. This workflow is the
**hermetic readiness check** that runs three days *before* the
Monday smoke and emits the canonical `cutover-acceptance-decision`
JSON envelope.

Sibling artifacts:

* [`phase-3c-cutover-runbook.md`](phase-3c-cutover-runbook.md) — Dry-
  run usage walkthrough for ad-hoc operator rehearsal. Same Substrate
  scripts; different framing (CLI invocation vs. CI workflow).
* [`phase-3c-trigger-gates.md`](phase-3c-trigger-gates.md) — Per-gate
  evidence reference for the five Phase-3c trigger-gates.

## Trigger surface

```text
schedule:        Wed 06:00 UTC (= 08:00 CEST in May)
workflow_dispatch: target-binary-count, boots, score-band-floor
```

The wednesday-cron cadence is deliberate: three days before the
ADR-0065 §Mo Live-Smoke target gives Selin, Reza, and Tomás time to
investigate any red signal without sliding the Welle-1 timeline. The
dispatch inputs let operators tighten the readiness floor for a
focused investigation (e.g. `score-band-floor=AMBER` to capture a
slightly-degraded run without failing the decision).

## Five-step decision flow

| Step | Substrate | Failure semantics |
|------|-----------|-------------------|
| 1. Trigger-gate aggregator | `scripts/phase-3c-trigger-gate-aggregator.py --json` | Exit 0 = green; exit 1 = yellow (tolerated iff Gate-4 sole yellow); exit 2 = red (hard fail) |
| 2. Cutover-dry-run | `scripts/phase-3c-cutover-dry-run.py --component v907_verify --boots 12` | Exit non-zero fails the decision; envelope written to `out/dry-run-envelope.json` |
| 3. Test-persona-boot (rust) | `pytest wirelang/tests/persona_engine/test_rust_backend_switch.py -k v907_verify` with `WAKIR_V907_VERIFY_BACKEND=rust` | Pytest exit non-zero fails the decision |
| 4. Bridge-audit-roundtrip | `pytest tests/integration/test_bridge_audit_roundtrip_e2e.py` | Pytest exit 0 (pass or all-skipped) = OK; exit 5 (no tests collected) tolerated for forward-compat |
| 5. Render cutover-acceptance-decision | Inline python | Writes `out/cutover-acceptance-decision.json`; job exits 0 iff `ready_for_live_smoke == true` |

### Decision policy (Step 5)

`ready_for_live_smoke == true` requires **all** of:

* Step 1: `gate-aggregator-rc in {0, 1-tolerated}`. The yellow-tolerance
  applies only when Gate-4 (observability baseline) is the **sole**
  yellow gate — the operator-hand-staged baseline file is not present
  on the GitHub-hosted runner, which is the documented and expected
  posture per ADR-0065 §Trigger-Bedingung-4.
* Step 2: dry-run exited 0 AND the feasibility-band meets or exceeds
  the configured floor (default `GREEN`).
* Step 3: persona-boot pytest exited 0 (v907_verify backend-switch
  resolver passes with `WAKIR_V907_VERIFY_BACKEND=rust`).
* Step 4: bridge-audit-roundtrip pytest exited 0 (pass or all-SKIP
  on a runner without the Rust `replay_cli` binary).

Any other state surfaces as `ready_for_live_smoke == false` and the
workflow job exits 1. The artifact still ships (always-upload), so
the operator can inspect the decision JSON post-hoc.

## Artifact: `cutover-acceptance-decision`

Each run uploads a single artifact bundle (`retention: 30 days`):

```text
cutover-acceptance-decision.json   # canonical decision envelope
trigger-gate-report.json           # raw Step 1 output (5 gates)
dry-run-envelope.json              # raw Step 2 output (feasibility)
persona-boot.log                   # Step 3 pytest stdout
persona-boot-junit.xml             # Step 3 junit
bridge-audit.log                   # Step 4 pytest stdout
bridge-audit-junit.xml             # Step 4 junit
```

### `cutover-acceptance-decision.json` shape

```json
{
  "schema": "wakir.phase-3c.welle-1-validation/1",
  "welle": 1,
  "component": "v907_verify",
  "env_var": "WAKIR_V907_VERIFY_BACKEND",
  "ready_for_live_smoke": true,
  "score_band_floor": "GREEN",
  "observed_band": "GREEN",
  "steps": {
    "step_1_trigger_gates": {"exit_code": 1, "status": "yellow_tolerated"},
    "step_2_cutover_dry_run": {"exit_code": 0, "ok": true},
    "step_3_persona_boot_rust": {"exit_code": 0, "ok": true},
    "step_4_bridge_audit_roundtrip": {"exit_code": 0, "ok": true}
  },
  "inputs": {"target_binary_count": 7, "boots": 12},
  "trigger_report_summary": {"all_green": false, "ready_for_phase_3c": false, "gate_count": 5},
  "dry_run_summary": {"feasibility_score": 1.0, "band": "GREEN", "boots": 12},
  "anchors": {
    "adr": "decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md",
    "runbook": "docs/operations/phase-3c-welle-1-runbook.md"
  }
}
```

Field stability: the `schema` field is versioned (`/1`). A future
breaking change to the envelope shape bumps to `/2`; consumers
(Welle-1-Cutover-PR review checklist) read the schema field before
parsing.

## Operator walkthrough — wednesday morning

1. Open the [Actions tab](https://github.com/wakir-labs/wakir-runtime/actions/workflows/phase-3c-welle-1-validation.yml)
   and find the most recent scheduled run.
2. Inspect the **run-tab summary**: a markdown table renders the four
   step-exit-codes and the cutover-decision verdict. The table is
   enough to triage 90 % of cases without downloading the artifact.
3. If the verdict is `YES` and Gate-4 is the only yellow signal:
   proceed with the Welle-1 cutover-PR planning per ADR-0065 §Mo.
4. If the verdict is `NO`: download the `cutover-acceptance-decision`
   artifact and read the four sub-bundles (trigger-gate-report,
   dry-run-envelope, persona-boot.log, bridge-audit.log) to find the
   failing step. Escalate per the routing table below.

### Failure routing

| Failing step | Owner | First diagnostic |
|--------------|-------|------------------|
| 1 (trigger-gates RED) | Kai (Cosign + Quadlet inventories), Reza (rust_backend_switch resolvers) | Inspect `trigger-gate-report.json` for the offending gate `evidence` block |
| 2 (dry-run RED) | Reza (resolver substance) | Inspect `dry-run-envelope.json`; `chosen_backend_counts` + `fallback_reason_counts` show the deviation |
| 3 (persona-boot RED) | Reza | `persona-boot-junit.xml` lists failing test cases; `persona-boot.log` carries the full pytest output |
| 4 (bridge-audit RED, not all-SKIP) | Selin (cross-lang substrate) | `bridge-audit.log`; the test asserts Python emit ↔ Rust replay hash parity |

Tomás (Matrix-Lead) is the cross-step moderator if two or more steps
fail in the same run.

## Manual dispatch — ad-hoc readiness check

```bash
# From the Actions tab, click "Run workflow" and tune the inputs:
target-binary-count: 7        # default Welle-7 substrate target
boots: 12                     # default Phase-3b live-smoke cadence
score-band-floor: GREEN       # tighten to GREEN, loosen to AMBER
```

Or via `gh`:

```bash
gh workflow run phase-3c-welle-1-validation.yml \
    -f target-binary-count=7 \
    -f boots=24 \
    -f score-band-floor=GREEN
```

A `boots` count higher than 12 gives the latency-percentile sub-score
a wider sample; 24 is a useful diagnostic value when the GREEN-band
verdict is borderline.

## Relationship to other Phase-3c artifacts

```text
+------------------------------------+
| ADR-0065 (Cutover-Plan)            |
+--------------+---------------------+
               |
   +-----------+------------+
   |                        |
   v                        v
phase-3c-cutover-       phase-3c-welle-1-
runbook.md              validation.yml  (THIS workflow)
(dry-run CLI usage)     (wednesday CI gate)
   |                        |
   |                        v
   |               cutover-acceptance-decision.json
   v                        |
phase-3c-trigger-           |
gates.md                    |
(per-gate evidence)         |
                            v
                  ADR-0065 §Mo Live-Smoke
                  (Operator-Hand, real Pilot-VM)
```

The validation workflow does **not** replace the Live-Smoke; it is
the readiness check that the Live-Smoke decision rests on. The
Live-Smoke remains operator-hand-territory per the
[sandbox-host-trennung](../../agents-workspaces/mira/memory/feedback_sandbox_host_trennung.md)
discipline.

## Bandwidth notes

* Wednesday-cron run completes in ≈4-6 minutes on the GitHub-hosted
  runner (checkout 15 s, install 60 s, Step 1 ≈3 s, Step 2 ≈3 s,
  Step 3 ≈30 s, Step 4 ≈10 s with all-skip, Step 5 ≈5 s, upload 5 s).
* The hermetic envelope means a `workflow_dispatch` ad-hoc run is
  cheap; operators do not need to schedule a Mira-Hand window.

## Drift sentinels — tests/workflows/test_phase_3c_welle_1_validation.py

The hermetic test file asserts the workflow contract so a future
edit that drops a step, breaks the env-var on Step 3, or omits a
canonical artifact path regresses with a clear hermetic-test failure.

Test coverage:

1. `test_workflow_yaml_format_and_top_level` — YAML parses, name +
   least-privilege permissions intact.
2. `test_trigger_surface_schedule_and_dispatch` — wed 06:00 UTC cron
   + three dispatch inputs with defaults.
3. `test_five_validation_steps_in_order` — five Mira-Hand-defined
   step-ids in chronological order.
4. `test_step_invocation_contracts` — each step references a real
   in-repo script / test file with the documented CLI flags;
   Step 3 sets `WAKIR_V907_VERIFY_BACKEND=rust` on the step env.
5. `test_gate_aggregation_against_live_repo` — aggregator composes
   end-to-end against the live repo and yields five gates.
6. `test_dry_run_success_criteria_v907_verify` — dry-run with stub
   resolver produces GREEN band, score ≥ 0.95.
7. `test_decision_policy_*` (three tests) — Step-5 decision policy:
   ready-path, Gate-4-yellow tolerance, red-step blocks ready,
   band-floor enforcement.
8. `test_artifact_upload_bundles_canonical_paths` — upload step
   collects the five canonical output paths with `retention-days: 30`
   and `always()` guard.

## Anchors

* ADR-0065 — Phase-3c Cutover-Plan (Python-Default → Rust-Default).
* ADR-0058 — Pilot-Persona-Migrations-Plan (Phase-2 4-week observation
  pattern; this workflow mirrors the discipline for Phase-3c).
* ADR-0060 — Live-FCOS-VM-CI-Gate (acceptance-lane substrate; Step 4
  bridge-audit-roundtrip-e2e is the cross-lang oracle).
* `feedback_sandbox_host_trennung.md` — Sandbox vs. operator-hand
  boundary; this workflow lives strictly on the sandbox side.
* `feedback_branch_protection_check_names.md` — this workflow is
  deliberately NOT wired as a required status check.

— Tomás Reinhart (Matrix-Lead), Sprint-Tag-25 Mini-Welle, 2026-05-17.
