<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# Pre-Cutover-Final-Sanity-Gate Operator Runbook (Tomas Tag-53)

This runbook covers the Tag-53 `pre-cutover-final-sanity-gate` workflow
(`.github/workflows/pre-cutover-final-sanity-gate.yml`). It is the
pre-KW-24 final readiness probe across all seven Phase-3-Marathon
substrates. Companion to the Tag-41 `phase-3c-pre-cutover-sanity`
runbook and the Tag-44 `phase-3-cutover-day-auto-scheduler` runbook.

## Scheduling

| Time (UTC) | Workflow | Verdict file |
|---|---|---|
| Mon 05:00 | Tag-53 `pre-cutover-final-sanity-gate` (this one) | `pre-cutover-final-sanity-gate-verdict.json` |
| Mon 06:00 | Tag-41 `phase-3c-pre-cutover-sanity` | `pre-cutover-sanity-verdict.json` |
| Mon 07:00 | Tag-44 `phase-3-cutover-day-auto-scheduler` | reads both above |

Tag-53 runs **first** so that the auto-scheduler reads the freshest
seven-substrate verdict.

## Seven substrates probed (S1..S7)

| ID | Substrate | Owning persona / PR |
|---|---|---|
| S1 | engine_manifest (0.5.2-final + pin-pack parity) | Selin PR #336 (Tag-52) |
| S2 | spec_freeze (v0.4.3-freeze marker) | Reza PR #338 (Tag-53) |
| S3 | 15-binary SBOM substrate | Kai PR #311 (Tag-48) |
| S4 | build-reproducibility-daily | Noa (Tag-46) |
| S5 | cosign-OIDC drift + verify-images | Kai PR #307 (Tag-47) |
| S6 | welle-probes (7 pre-cutover + 5 hot-spot) | Reza / Selin (Tag-40..Tag-45) |
| S7 | marathon-tracker + tracker-gate | Selin PR #261 (Tag-40) |

## Decision rule

* `READY`   - all seven substrates green.
* `CAUTION` - 1..2 substrates yellow, zero red.
* `BLOCK`   - any substrate red, OR three or more yellow.

The threshold `yellows>=3 -> BLOCK` is **tighter** than the four-
substrate Tag-41 gate (`yellows>=2 -> BLOCK` there). Seven substrates
carry more redundancy.

## Operator playbook (when verdict != READY)

When the Monday 05:00 UTC scheduled run lands as `BLOCK` or `CAUTION`
and the auto-scheduler at 07:00 UTC is two hours away:

1. **Download the verdict artifact.**
   `gh run download <run-id> -n pre-cutover-final-sanity-gate-verdict`

2. **Inspect `failed_steps` and `substrate_notes`.** Each substrate
   note is `<substrate-key>:<human-readable-reason>`.

3. **Remediation by substrate:**

   * **S1 engine_manifest** - missing manifest doc / pin-pack mismatch.
     Coordinate with Selin (PR #336). Manifest is at
     `wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md`,
     pin-pack at
     `infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml`.

   * **S2 spec_freeze** - spec file present without freeze-marker
     means a regression on PR #338. Spec is at
     `wirelang/specs/wirelang-spec-v0-4-3.md`. The probe accepts
     any `status:` value containing the literal `freeze` token
     (so `freeze`, `pre-cutover-freeze`, `cutover-freeze` all
     qualify). Yellow with note "spec v0.4.3 not yet on HEAD
     (pre-freeze)" is the expected pre-freeze posture and clears
     to green once the spec lands.

   * **S3 sbom** - 15-binary SBOM workflow missing means a
     `.github/workflows/15-binary-sbom-daily.yml` regression
     (Kai PR #311). Workflow is required - any missing workflow
     in the supply-chain triad triggers a Tag-53 BLOCK by itself.

   * **S4 build_reproducibility** - same shape as S3. Workflow at
     `.github/workflows/build-reproducibility-daily.yml`.

   * **S5 cosign_oidc** - partial substrate (one of two workflows
     missing) emits yellow, both missing emits red. Workflows at
     `.github/workflows/cosign-keyless-oidc-drift-probe.yml` and
     `.github/workflows/cosign-verify-images.yml`.

   * **S6 welle_probes** - the seven per-Welle pre-cutover-probe
     shell scripts + five hot-spot probe workflows. Up to two
     missing emits yellow; three or more emits red. Reza/Selin
     own these substrates collectively (Tag-40..Tag-45).

   * **S7 marathon_tracker** - tracker-script at
     `scripts/phase-3c/marathon-aggregat-tracker.py`, tracker-
     gate workflow at
     `.github/workflows/phase-3c-marathon-tracker-gate.yml`.
     Partial substrate emits yellow, both missing emits red.
     Selin PR #261 substrate.

4. **AR-Hand ratification:** a `CAUTION` verdict does NOT block
   Cutover-Execution by itself - AR-Hand decides via the
   `state/ar-hand-cutover-day-flag.json` substrate that the
   Tag-44 auto-scheduler reads. A `BLOCK` verdict by itself does
   NOT cancel the cutover - operator-hand + AR-Hand decide
   together, with both Tag-41 + Tag-53 verdict-JSONs attached
   to the decision.

5. **Cross-reference Tag-41 verdict.** If both Tag-41 and Tag-53
   land BLOCK, the auto-scheduler at 07:00 UTC will degrade to
   DRY_RUN_ONLY automatically. If only one of the two lands
   BLOCK, the AR-Hand-Ratification flag is what tips the
   balance.

## Hermetic posture

Strict hermetic: filesystem + pyyaml + stdlib only. No podman,
no NATS, no live-VM, no Cosign-OIDC handshake. The supply-chain
triad (S3 SBOM, S4 repro, S5 cosign) is probed at the workflow-
discovery level; their own hermetic suites cover the dynamics.

## Not a required status check

Per `feedback_branch_protection_check_names.md` this workflow is
NOT listed as a required status check on PRs - it gates a calendar-
window (KW-24 marathon-start), not individual PRs. The 28 hermetic
tests in `tests/ci/test_pre_cutover_final_sanity_gate.py` are the
gating unit on PRs that touch the gate substrate itself.

## Cross-substrate links

* Tag-41 sanity workflow: `.github/workflows/phase-3c-pre-cutover-sanity.yml`
* Tag-44 auto-scheduler: `.github/workflows/phase-3-cutover-day-auto-scheduler.yml`
* Decision aggregator: `tooling/ci/aggregate_pre_cutover_final_sanity_gate_verdict.py`
* Tag-53 hermetic tests: `tests/ci/test_pre_cutover_final_sanity_gate.py`
