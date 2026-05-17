# Phase-3c Welle-3 Validation Runbook — bridge_audit_writer (Henrik-Caution)

| Field | Value |
|---|---|
| Owner | Reza Lotfi (Persona-Engine anchor_emitter resolver), Tomas Reinhart (Matrix-Lead), Henrik Voss (Internal Audit, Henrik-Caution sign-off) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) (Cutover-Plan), [0066](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) (Acceleration + Welle-3 solo) |
| Workflow | [`.github/workflows/phase-3c-welle-3-validation.yml`](../../.github/workflows/phase-3c-welle-3-validation.yml) |
| Tests | [`tests/workflows/test_phase_3c_welle_3_validation.py`](../../tests/workflows/test_phase_3c_welle_3_validation.py) |
| Cadence | Wednesday 06:00 UTC (~08:00 CEST in May) + workflow_dispatch |
| Welle-3 component | `bridge_audit_writer` (KW 25, solo per ADR-0066) |
| Component alias | `anchor_emitter` (in-repo short-form, resolver-actual name) |
| Welle-3 env-var (long) | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` (ADR-0065 vocabulary) |
| Welle-3 env-var (resolver) | `WAKIR_ANCHOR_EMITTER_BACKEND` (read by `resolve_anchor_emitter_backend`) |

## Purpose

This runbook explains the **Welle-3 Validation Workflow**, the
wired-substrate readiness check that the Phase-3c Welle-3 cutover
decision rests on. ADR-0065 + ADR-0066 (Acceleration Option-A+,
§Welle-Sequenz) demand a Monday-morning Pilot-VM Live-Smoke before
the Welle-3 cutover-PR flips the production default of
`WAKIR_ANCHOR_EMITTER_BACKEND` from `python` to `rust`. The
Live-Smoke is **operator-hand-territory**. This workflow is the
**hermetic readiness check** that runs three days *before* the
Monday smoke and emits the canonical
`cutover-acceptance-decision-welle-3` JSON envelope.

Welle-3 runs **solo** in KW 25 per the ADR-0066 §Welle-Sequenz —
unlike Welle-1+2 (KW 24, parallel) and Welle-4+5 (KW 26, parallel),
the bridge_audit_writer cutover does not share its wednesday-cron
slot with another welle.

## Henrik-Caution (ADR-0066 §"Bridge-Audit-Welle bleibt strikt solo")

Welle-3 IS the bridge-audit cutover. The component being flipped
(`bridge_audit_writer`, in-repo alias `anchor_emitter`) is itself
the substrate behind the canonical cross-lang consistency oracle
`tests/integration/test_bridge_audit_roundtrip_e2e.py`. The Welle-1
(PR #190) and Welle-2 (PR #196) workflows use that oracle at Step 4
to verify cross-lang consistency. Using the same oracle to validate
its own cutover would mean asking the subject under test to certify
itself — Henrik (Internal Audit) flagged this as a self-Oracle risk
in the ADR-0066 verification plan and demanded an **independent**
consistency source for Welle-3.

### Welle-3 Step 4 — independent oracle

Welle-3 swaps the Step-4 oracle: instead of
`pytest tests/integration/test_bridge_audit_roundtrip_e2e.py`, it
runs:

```bash
scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress --threshold 3
```

That aggregator's three Cross-Modul axes (PR #197) are:

* `cross-lang-pin-coverage` (federation_frame, state_backing,
  lifecycle_state_machine, subscribe_loop, recovery_workflow)
* `cross-modul-fixture-stability`
* `cross-modul-rollup-integrity`

None of these axes use the `bridge_audit_writer` /
`anchor_emitter` substrate as the source-of-truth oracle, so the
signal is **structurally independent** from the subject under
cutover. This satisfies the Henrik-Caution requirement.

The decision JSON envelope carries an explicit
`henrik_caution_applied: true` marker and documents the
independent-oracle source under `step_4_oracle`. Henrik consumes the
marker via the audit-trail when signing off Welle-3 per ADR-0066
§Henrik-Sign-off.

## Component aliasing — long-form vs. short-form

ADR-0065 §Welle-Sequenz lists `bridge_audit_writer` as the Welle-3
component name; the in-repo dry-run + resolver substrate normalises
this to the short form `anchor_emitter`:

```text
ADR-0065 long-form:        bridge_audit_writer
In-repo short-form:        anchor_emitter
ADR-0065 env-var (long):   WAKIR_BRIDGE_AUDIT_WRITER_BACKEND
Resolver env-var (short):  WAKIR_ANCHOR_EMITTER_BACKEND
```

Source of truth for the alias: `scripts/phase-3c-cutover-dry-run.py`
`PHASE_3C_COMPONENT_ALIASES`.

The workflow's Step 3 sets **both** env-var spellings on the
persona-boot step so:

* the ADR-0065-named env-var carries the Welle-3 vocabulary the
  operator reads in the run-tab,
* the resolver's actual env-var (`WAKIR_ANCHOR_EMITTER_BACKEND`) is
  what `resolve_anchor_emitter_backend` reads at boot time.

The pytest filter uses `-k anchor_emitter` because the
rust_backend_switch test functions follow the in-repo short-form
convention (`test_anchor_emitter_*`, AE1..AE12+, see
`wirelang/tests/persona_engine/test_rust_backend_switch.py` L2849+).

Sibling artifacts:

* [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md) —
  Welle-1 readiness check for `v907_verify`. Same 5-step pattern;
  different component. Read first if you have not seen the Welle-1
  workflow.
* [`phase-3c-welle-2-runbook.md`](phase-3c-welle-2-runbook.md) —
  Welle-2 readiness check for `svid_workload_identity`. Same 5-step
  pattern; parallel to Welle-1 per ADR-0066.
* [`phase-3c-cutover-runbook.md`](phase-3c-cutover-runbook.md) —
  Dry-run usage walkthrough for ad-hoc operator rehearsal.
* [`phase-3c-trigger-gates.md`](phase-3c-trigger-gates.md) — Per-gate
  evidence reference for the five Phase-3c trigger-gates.

## Trigger surface

```text
schedule:        Wed 06:00 UTC (= 08:00 CEST in May)
workflow_dispatch: target-binary-count, boots, score-band-floor
```

The wednesday-cron cadence is deliberate: three days before the
ADR-0065 §Mo Live-Smoke target gives Reza, Tomas, and Henrik time to
investigate any red signal without sliding the Welle-3 timeline. The
dispatch inputs let operators tighten the readiness floor for a
focused investigation.

## Five-step decision flow

| Step | Substrate | Failure semantics |
|------|-----------|-------------------|
| 1. Trigger-gate aggregator | `scripts/phase-3c-trigger-gate-aggregator.py --json` | Exit 0 = green; exit 1 = yellow (tolerated iff Gate-4 sole yellow); exit 2 = red (hard fail) |
| 2. Cutover-dry-run | `scripts/phase-3c-cutover-dry-run.py --component bridge_audit_writer --boots 12` | Exit non-zero fails the decision; envelope written to `out/dry-run-envelope.json` |
| 3. Test-persona-boot (rust) | `pytest wirelang/tests/persona_engine/test_rust_backend_switch.py -k anchor_emitter` with `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust` AND `WAKIR_ANCHOR_EMITTER_BACKEND=rust` | Pytest exit non-zero fails the decision |
| 4. Cross-modul-stress (Henrik-Caution) | `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress --threshold 3` | Exit 0 = independent oracle threshold-pass; exit non-zero fails the decision |
| 5. Render cutover-acceptance-decision | Inline python | Writes `out/cutover-acceptance-decision.json`; job exits 0 iff `ready_for_live_smoke == true` |

### Decision policy (Step 5)

`ready_for_live_smoke == true` requires **all** of:

* Step 1: `gate-aggregator-rc in {0, 1-tolerated}`. The yellow-tolerance
  applies only when Gate-4 (observability baseline) is the **sole**
  yellow gate.
* Step 2: dry-run exited 0 AND the feasibility-band meets or exceeds
  the configured floor (default `GREEN`).
* Step 3: persona-boot pytest exited 0 (anchor_emitter
  backend-switch resolver passes with both env-vars set to `rust`).
* Step 4: cross-modul-stress aggregator exited 0 (Henrik-Caution
  independent oracle threshold-pass on 3-of-3 Cross-Modul axes).

Any other state surfaces as `ready_for_live_smoke == false` and the
workflow job exits 1. The artifact still ships (always-upload), so
the operator can inspect the decision JSON post-hoc.

## Artifact: `cutover-acceptance-decision-welle-3`

Each run uploads a single artifact bundle (`retention: 30 days`):

```text
cutover-acceptance-decision.json   # canonical decision envelope
trigger-gate-report.json           # raw Step 1 output (5 gates)
dry-run-envelope.json              # raw Step 2 output (feasibility)
persona-boot.log                   # Step 3 pytest stdout
persona-boot-junit.xml             # Step 3 junit
cross-modul-stress.log             # Step 4 aggregator stdout
cross-modul-stress-rollup.json     # Step 4 rollup (3 axes)
```

The artifact bundle name carries the `-welle-3` suffix so it does not
collide with the Welle-1 / Welle-2 artifacts on the GitHub Actions
artifact namespace.

### `cutover-acceptance-decision.json` shape

```json
{
  "schema": "wakir.phase-3c.welle-3-validation/1",
  "welle": 3,
  "component": "bridge_audit_writer",
  "component_resolver_alias": "anchor_emitter",
  "env_var": "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
  "env_var_resolver_alias": "WAKIR_ANCHOR_EMITTER_BACKEND",
  "henrik_caution_applied": true,
  "step_4_oracle": "doppelbetrieb-score-aggregator --mode=cross-modul-stress",
  "ready_for_live_smoke": true,
  "score_band_floor": "GREEN",
  "observed_band": "GREEN",
  "steps": {
    "step_1_trigger_gates": {"exit_code": 1, "status": "yellow_tolerated"},
    "step_2_cutover_dry_run": {"exit_code": 0, "ok": true},
    "step_3_persona_boot_rust": {"exit_code": 0, "ok": true},
    "step_4_cross_modul_stress": {
      "exit_code": 0,
      "ok": true,
      "henrik_caution": "independent_oracle"
    }
  },
  "inputs": {"target_binary_count": 7, "boots": 12},
  "trigger_report_summary": {"all_green": false, "ready_for_phase_3c": false, "gate_count": 5},
  "dry_run_summary": {"feasibility_score": 1.0, "band": "GREEN", "boots": 12},
  "cross_modul_stress_summary": {
    "total_score": 3,
    "threshold": 3,
    "threshold_pass": true,
    "mode": "cross-modul-stress"
  },
  "anchors": {
    "adr_cutover": "decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md",
    "adr_acceleration": "decisions/0066-phase-3c-beschleunigung-option-a-plus.md",
    "runbook": "docs/operations/phase-3c-welle-3-runbook.md",
    "welle_1_sibling": ".github/workflows/phase-3c-welle-1-validation.yml",
    "welle_2_sibling": ".github/workflows/phase-3c-welle-2-validation.yml",
    "independent_oracle": ".github/workflows/phase-2-acceptance-gate.yml"
  }
}
```

Field stability: the `schema` field is versioned (`/1`). A future
breaking change to the envelope shape bumps to `/2`; consumers
(Welle-3-Cutover-PR review checklist, Henrik audit-trail tooling)
read the schema field before parsing.

## Substrate wire-in note (Tag-31)

The Welle-1 and Welle-2 workflows shipped before Welle-3's
Henrik-Caution oracle swap was specified. Tag-31 (this PR) adds the
Welle-3 workflow without modifying the existing substrate:

* `scripts/phase-3c-cutover-dry-run.py` — unchanged.
  `PHASE_3C_COMPONENT_ALIASES["bridge_audit_writer"] = "anchor_emitter"`
  already shipped in earlier sprints; the workflow consumes the
  existing alias.
* `scripts/doppelbetrieb-score-aggregator.py` — unchanged. The
  `--mode=cross-modul-stress` path shipped in PR #197 (Tomás Tag-29);
  the workflow consumes the existing CLI surface.
* No new in-repo substrate is added; Welle-3 is a *consumer* of the
  existing aggregator + dry-run + score-aggregator triple.

## Operator walkthrough — wednesday morning (KW 25)

1. Open the [Actions tab](https://github.com/wakir-labs/wakir-runtime/actions/workflows/phase-3c-welle-3-validation.yml)
   and find the most recent scheduled run.
2. Inspect the **run-tab summary**: a markdown table renders the four
   step-exit-codes and the cutover-decision verdict. The table is
   enough to triage 90 percent of cases without downloading the
   artifact. The Henrik-Caution banner is rendered above the table.
3. If the verdict is `YES` and Gate-4 is the only yellow signal:
   proceed with the Welle-3 cutover-PR planning per ADR-0066 §Mo
   Live-Smoke. Notify Henrik (Internal Audit) — he countersigns the
   Welle-3 cutover.
4. If the verdict is `NO`: download the
   `cutover-acceptance-decision-welle-3` artifact and read the four
   sub-bundles (trigger-gate-report, dry-run-envelope, persona-boot.log,
   cross-modul-stress.log) to find the failing step. Escalate per the
   routing table below.

### Failure routing

| Failing step | Owner | First diagnostic |
|--------------|-------|------------------|
| 1 (trigger-gates RED) | Kai (Cosign + Quadlet inventories), Reza (rust_backend_switch resolvers) | Inspect `trigger-gate-report.json` for the offending gate `evidence` block |
| 2 (dry-run RED) | Reza (anchor_emitter resolver substance) | Inspect `dry-run-envelope.json`; `chosen_backend_counts` + `fallback_reason_counts` show the deviation |
| 3 (persona-boot RED) | Reza | `persona-boot-junit.xml` lists failing AE1..AE12+ test cases; `persona-boot.log` carries the full pytest output |
| 4 (cross-modul-stress RED) | Selin (cross-modul substrate), Henrik (audit-trail review) | `cross-modul-stress-rollup.json` shows the failing Cross-Modul axis; `cross-modul-stress.log` has the aggregator's per-axis breakdown |

Tomas (Matrix-Lead) is the cross-step moderator if two or more steps
fail in the same run. Henrik (Internal Audit) is the named contact
for any Step-4-Henrik-Caution red signal — the independent-oracle
substrate is part of his audit-trail jurisdiction.

## Manual dispatch — ad-hoc readiness check

```bash
# From the Actions tab, click "Run workflow" and tune the inputs:
target-binary-count: 7        # default Welle-7 substrate target
boots: 12                     # default Phase-3b live-smoke cadence
score-band-floor: GREEN       # tighten to GREEN, loosen to AMBER
```

Or via `gh`:

```bash
gh workflow run phase-3c-welle-3-validation.yml \
    -f target-binary-count=7 \
    -f boots=24 \
    -f score-band-floor=GREEN
```

A `boots` count higher than 12 gives the latency-percentile sub-score
a wider sample; 24 is a useful diagnostic value when the GREEN-band
verdict is borderline.

## Relationship to Welle-1 + Welle-2 + other Phase-3c artifacts

```text
+----------------------------------------+
| ADR-0065 (Cutover-Plan) +              |
| ADR-0066 (Acceleration Option-A+)      |
+--+-----------------------+-----------+-+
   |                       |           |
   v                       v           v
phase-3c-welle-1-     phase-3c-welle-2-  phase-3c-welle-3-
validation.yml        validation.yml     validation.yml   (THIS workflow)
(v907_verify)         (svid_workload_   (bridge_audit_writer
                       identity)         a.k.a. anchor_emitter)
   |                       |                  |
   |                       |    Step 4: independent
   |                       |    oracle (Henrik-Caution)
   |                       |                  |
   v                       v                  v
cutover-acceptance-   cutover-acceptance-  cutover-acceptance-
decision               decision-welle-2     decision-welle-3
   |                       |                  |
   +-----------+-----------+------------------+
               v
       ADR-0065 + ADR-0066 §Mo Live-Smoke
       (Operator-Hand, real Pilot-VM,
        Welle-3 solo in KW 25 per ADR-0066)
```

The validation workflow does **not** replace the Live-Smoke; it is
the readiness check that the Live-Smoke decision rests on. The
Live-Smoke remains operator-hand-territory per the
[sandbox-host-trennung](../../agents-workspaces/mira/memory/feedback_sandbox_host_trennung.md)
discipline.

## Bandwidth notes

* Wednesday-cron run completes in ~4-7 minutes on the GitHub-hosted
  runner (checkout 15 s, install 60 s, Step 1 ~3 s, Step 2 ~3 s,
  Step 3 ~30 s, Step 4 ~60-90 s (the cross-modul-stress aggregator
  runs three subprocess pytest invocations, one per axis), Step 5
  ~5 s, upload 5 s).
* Welle-3 runs solo in KW 25; ~5-7 minutes of GH-Actions runtime per
  week (single welle, no parallel partner).
* The hermetic envelope means a `workflow_dispatch` ad-hoc run is
  cheap; operators do not need to schedule a Mira-Hand window.

## Drift sentinels — tests/workflows/test_phase_3c_welle_3_validation.py

The hermetic test file asserts the workflow contract so a future
edit that drops a step, breaks the env-var on Step 3, omits the
Henrik-Caution marker, or reverts the Step-4 oracle to the bridge-
audit-roundtrip-e2e (self-Oracle risk) regresses with a clear
hermetic-test failure.

Test coverage (12 tests, 9 explicit + 3 decision-policy variants):

1. `test_workflow_yaml_format_and_top_level` — YAML parses, name +
   least-privilege permissions intact.
2. `test_trigger_surface_schedule_and_dispatch` — wed 06:00 UTC cron
   + three dispatch inputs with defaults.
3. `test_five_validation_steps_in_order` — five Mira-Hand-defined
   step-ids in chronological order; Welle-3-specific Step 4 id is
   `cross-modul-stress` and the step name surfaces Henrik-Caution.
4. `test_step_invocation_contracts` — each step references a real
   in-repo script / test file with the documented CLI flags; Step 3
   sets BOTH `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust` and
   `WAKIR_ANCHOR_EMITTER_BACKEND=rust`; Step 4 uses
   `--mode=cross-modul-stress` and explicitly does NOT reference
   bridge_audit_roundtrip_e2e.
5. `test_job_level_env_pins_bridge_audit_writer_component` — the
   job-level env block pins `WELLE_COMPONENT` to
   `bridge_audit_writer`, `WELLE_ENV_VAR` to the long-form env-var,
   and `WELLE_RESOLVER_ENV_VAR` to the short-form resolver env-var.
6. `test_dry_run_accepts_bridge_audit_writer_alias` — dry-run script
   accepts the ADR-0065 long-form name and normalises to
   `anchor_emitter` (alias-bridge regression guard).
7. `test_dry_run_success_criteria_bridge_audit_writer` — dry-run
   with stub resolver produces GREEN band, score >= 0.95.
8. `test_decision_policy_ready_path` — all-green ready-path.
9. `test_decision_policy_henrik_caution_red_blocks_ready` — Welle-3-
   specific: cross-modul-stress RED blocks ready even when all other
   steps are green.
10. `test_decision_policy_gate4_yellow_tolerated` — Gate-4 yellow
    alone tolerated.
11. `test_decision_policy_red_blocks_ready` — gate / persona-boot
    red blocks ready.
12. `test_decision_policy_band_floor_enforced` — band-floor
    enforced.
13. `test_artifact_upload_bundles_canonical_paths` — upload step
    collects the canonical output paths under the
    `cutover-acceptance-decision-welle-3` bundle name; the
    `cross-modul-stress.log` + rollup are present and the
    `bridge-audit.log` is explicitly absent.
14. `test_decision_render_carries_henrik_caution_marker` — the
    decision JSON envelope literal contains
    `henrik_caution_applied: True` plus the independent-oracle
    source string and the Welle-3 schema version.

## Anchors

* ADR-0065 — Phase-3c Cutover-Plan (Python-Default -> Rust-Default).
* ADR-0066 — Phase-3c Acceleration Option-A+ (4W statt 7W; Welle-3
  solo in KW 25 with Henrik-Caution).
* ADR-0058 — Pilot-Persona-Migrations-Plan (Phase-2 4-week observation
  pattern; this workflow mirrors the discipline for Phase-3c).
* ADR-0060 — Live-FCOS-VM-CI-Gate (acceptance-lane substrate).
* PR #190 — Welle-1 validation workflow (sibling, uses
  bridge_audit_roundtrip_e2e as Step 4 — Welle-3 cannot).
* PR #196 — Welle-2 validation workflow (sibling, same Step-4
  oracle as Welle-1).
* PR #197 — Phase-2-Acceptance-Gate cross-modul-stress mode (Welle-3
  Step-4 independent oracle).
* `feedback_sandbox_host_trennung.md` — Sandbox vs. operator-hand
  boundary; this workflow lives strictly on the sandbox side.
* `feedback_branch_protection_check_names.md` — this workflow is
  deliberately NOT wired as a required status check.

— Tomas Reinhart (Matrix-Lead), Sprint-Tag-31 Mini-Welle, 2026-05-17.
