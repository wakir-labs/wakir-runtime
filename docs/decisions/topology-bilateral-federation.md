# Topology Decision — Bilateral-Federation vs. Asymmetric-Pilot

<!--
SPDX-License-Identifier: BUSL-1.1
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

**Status:** OPEN — maintainer decision pending. The repository ships
substrate for both variants; the runtime selector
`WAKIR_BILATERAL_PRECHECK` chooses between them.

**Context — Bug-39:** The Cross-VM-Federation smoke (8/8 with
`WAKIR_FEDERATION_MODE=enabled` + `--peer-side`) requires BOTH peer
VMs to be in federation-mode. The current Pilot topology is
asymmetric:

- **wakir-pilot** runs in `single-org-mode` (one persona
  container, V2-Anchor, no federation peer). This is the
  ADR-0058 Doppelbetrieb-shadow host.
- **wakir-orbit** runs in `federation-mode` against wakir-pilot.

The asymmetric topology runs the federation-smoke with both
gates SKIPped on the pilot-side. The Pilot-Phase has tolerated
this so far; the question is whether we close the gap inside
the Pilot-Phase (Option A) or park it for the Phase-3
Production-rollout (Option B).

## Option A — Pilot-Symmetric (in-Pilot-Phase fix)

Bring wakir-pilot into federation-mode as well. Both VMs are then
in symmetric federation-mode and the 8/8 smoke runs without
SKIPs on either side.

**Pros:**

- Closes Bug-39 inside the Pilot-Phase. The federation gate runs
  on both sides; observability of the federation-bundle-sync path
  improves.
- The migration-pilot acceptance criteria of ADR-0058 can be
  exercised end-to-end before the production switchover.

**Cons:**

- The running persona container on wakir-pilot needs a
  re-spawn after the mode-flip. The SPIRE-server-federation-${side}
  unit is a different systemd unit name; the SPIFFE-ID changes
  from
  `spiffe://wakir.test/spire/agent/wakir-pilot/...` to
  `spiffe://wakir.test/spire/agent/${side}/...`; the workload-API
  socket re-binds; the persona-engine inside the container must
  re-authenticate.
- Operator-Hand window required for the re-spawn — not automatable
  in the Pilot-Phase because the persona-engine state-pack is
  involved.

**Substrate in the repository:**

- `WAKIR_BILATERAL_PRECHECK=1` enables `step_15_bilateral_precheck`
  in `infra/spire/federation/wakir-pilot-bootstrap.sh`. The precheck:
  - verifies this side is already in federation-mode,
  - verifies the peer-side bundle-endpoint is reachable on TCP 8443
    (peer is in federation-mode too),
  - verifies the operator declared a persona re-spawn-window via
    `WAKIR_PERSONA_RESPAWN_WINDOW`,
  - produces a PASS/FAIL summary the Operator-Hand uses as the
    go/no-go gate. **Does NOT mutate the running VM.**
- The actual mode-flip (`WAKIR_PILOT_MODE=federation` on
  wakir-pilot) is the regular bootstrap path; the persona re-spawn
  stays Operator-Hand because it touches the state-pack.

## Option B — production-setup item (park to the rollout phase)

Park the asymmetry as a production-rollout item. The asymmetric
topology stays in place for the remainder of the Pilot-Phase; both
VMs flip to federation-mode in a single coordinated Operator-Hand
window during Phase-3 cutover.

**Pros:**

- Zero Pilot-Phase Operator-Hand cost. The Doppelbetrieb-shadow
  keeps running on the topology that has been live since 2026-05-13.
- The mode-flip + persona re-spawn lands in the production
  switchover window, which is already an operator-coordinated event
  per ADR-0058. No additional re-spawn window needs to be
  scheduled.

**Cons:**

- The 8/8 federation-smoke does not exercise the bundle-sync gate
  on the pilot-side until Phase-3. A bug in the bundle-sync path
  may surface late.
- The Pilot-Phase acceptance criteria (ADR-0058) cannot be checked
  end-to-end in symmetric federation-mode before the switchover.

**Substrate in the repository:**

- Default behaviour. `WAKIR_BILATERAL_PRECHECK` unset or `0`;
  `step_15_bilateral_precheck` is a no-op.
- The asymmetric topology continues to run.
- This decision-note captures the topology rationale for review.

<!-- The "Decision-points" / "AR" literals in the next heading are
     pinned verbatim by tests/infra/test_pilot_bootstrap_bug_39_bilateral.py
     (test_decision_note_content); archaeology-lint allowlist entry. -->

## Decision-points for the maintainer and the AR

1. **Severity of the bundle-sync gate gap.** Is the Doppelbetrieb-
   shadow value sufficient to defer federation-bundle-sync
   verification on the pilot-side to Phase-3 cutover? Or do we want
   to exercise it in the Pilot-Phase to de-risk the cutover?

2. **Operator-Hand cost.** Option A adds a re-spawn-window inside
   the Pilot-Phase. Option B folds it into the Phase-3 cutover
   window. Which is preferable from an operational-rhythm
   perspective?

3. **Risk of late-discovery.** If a bundle-sync bug surfaces during
   Phase-3 cutover (Option B), the rollback path is more expensive
   than if it had surfaced during the Pilot-Phase (Option A).
   How is this risk weighted against the Option-A Operator-Hand
   cost?

## Implementation status

- **Option A substrate:** `step_15_bilateral_precheck` in
  `infra/spire/federation/wakir-pilot-bootstrap.sh`. Gated on
  `WAKIR_BILATERAL_PRECHECK=1`. Hermetic-tested in
  `tests/infra/test_pilot_bootstrap_bug_39_bilateral.py`.
- **Option B substrate:** this decision-note. The asymmetric
  topology runs unchanged (default).
- **Runtime selector:** `WAKIR_BILATERAL_PRECHECK` env-var
  documented in the bootstrap header.

Either option can be activated without a source-patch — the
decision is purely runtime-selectable. Both substrates ship
together so the variant can be picked without engineering rework.
