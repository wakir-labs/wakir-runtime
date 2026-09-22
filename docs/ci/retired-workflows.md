---
title: "Retired workflows register (wakir-runtime)"
status: "active"
owner: "tomas"
audience: "maintainers,auditors"
updated: "2026-09-22"
related_adrs:
  - "ADR-0068"
  - "ADR-0072"
  - "ADR-0075"
  - "ADR-0077"
related_docs:
  - "STABILITY.md"
  - "docs/architecture/layers.md"
  - "docs/ci/branch-protection-required-checks.md"
---

<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Retired workflows

## Why this file exists

Our trust documents contain correct historical prose. `STABILITY.md`
line 82 names `external-verifier-drift.yml` in a sentence whose whole
point is that the workflow no longer exists; the branch-protection
inventory describes a Phase-4 W1 cleanup that deleted two workflows by
name. A lint that simply demanded "every workflow filename mentioned in
a document must exist under `.github/workflows/`" would paint those
three sentences red, and a lint that is wrong about careful prose gets
switched off or papered over with suppressions inside a fortnight.

So the rule is not "do not mention deleted workflows". The rule is:
**a mentioned workflow either exists, or it is registered here with the
change that removed it.** Historical prose stays legal and stays
checkable at the same time. The register is enforced by
`tests/ci/test_evidence_citations.py`.

This is not an amnesty list. An entry whose workflow file is present
again under `.github/workflows/` fails the same test — otherwise the
register would slowly become a way to stop checking live workflows.

## Register

| Workflow file | Removed by | Date | Why |
|---|---|---|---|
| `external-verifier-drift.yml` | `527508e` | 2026-09-11 | Phase-4 W1 workflow prune. The workflow never touched `tooling/external-verifier-*`; the maturity row that credited it as a divergence guard for those trees was wrong about it even while it existed. Successor evidence: `tests/wat/test_external_verifier_parity.py` in the `Lane — WAT core` job of `runtime-acceptance-gates.yml`. |
| `cross-repo-drift-audit.yml` | PR #526 | 2026-09-11 | Phase-4 W1 rebuild of the cross-repository drift surface. Folded into `cross-repo-compat.yml`, which carries the required context `cross-repo compatibility (protocol ↔ runtime ↔ verify)`. |
| `cross-repo-drift-allowlist-audit.yml` | PR #526 | 2026-09-11 | Same rebuild. The allowlist half now lives in `wakir-protocol` `tooling/compat/allowlist.py`, which fails the gate on an expired `until` instead of reporting drift after the fact. |
| `ci-aggregator.yml` | ADR-0075 §1 (this register's own PR) | 2026-09-15 | Cross-workflow aggregation over the Actions API, never a required context. Retired rather than completed — see below. |
| `live-vm-acceptance.yml` | ADR-0077 | 2026-09-22 | Dispatch-only lane that aimed a hosted runner at a LAN address. Zero Actions secrets in the repository, so the SSH step could never have authenticated; zero runs since it was added on 2026-05-16. Live bring-up evidence comes from the operator-hand run of `scripts/federation-live-vm-acceptance.sh` on the substrate node — see below. |

## `ci-aggregator.yml` — the long version

ADR-0068 (approved 2026-05-18) called for exactly one required status
check named `ci-aggregator`, replacing six brittle path-filtered names.
The workflow landed. The cutover never happened. What the measurement
of 2026-09-14 found, four months later:

- The workflow **ran 865 times, always green, and never blocked
  anything.** It was not one of the thirteen required contexts on
  `main`.
- It polled **6 of those 13 contexts** over the Actions API
  (`scripts/ci/ci_aggregator.py::SUB_WORKFLOWS`); `proof-path`,
  `secret-scan` and the cosign contexts were not among them.
- `docs/ci/aggregator-workflow.md` §6 stated *"the aggregator is **the**
  Required-Status"*. That sentence was never true.

Executing ADR-0068 today would have traded thirteen enforcement points
for one that had never been on the critical path — and finding R6 of
the external re-review is the empirical argument against the pattern
itself: a single collecting context over everything is the largest
possible fail-open surface, and an aggregator that *polls* results
instead of inheriting them via `needs:` makes it larger. The binding
pattern is now aggregation **inside** one workflow: a collecting job
with `if: always()` plus an explicit `needs.*.result` check, as
`runtime-acceptance-gates.yml` has carried since 2026-09-14.

Deleted with the workflow: `scripts/ci/ci_aggregator.py`,
`docs/ci/aggregator-workflow.md`, and its hermetic pin
`tests/ci/test_ci_aggregator_workflow.py` — the last one because a test
that pins a file into a mandatory lane has to leave with the file it
pins, not after it.

Still in the tree, deliberately, and reported rather than removed:
`scripts/ci/adr-0068-migration-step-3-cutover.py` and
`scripts/observability/aggregator-failure-rate-tracker.py` with their
test modules. Both are ADR-0068 satellites with no remaining purpose;
removing them means deleting tests, and this PR removes exactly one
test module, the one whose subject it deletes.

## `live-vm-acceptance.yml` — the long version

The lane was added on 2026-05-16 as the CI invocation surface for the
live virtual-machine acceptance path. It was `workflow_dispatch` only by
design, and deliberately so: a push must never fan out to a real machine.
What the measurement of 2026-09-21/22 found, four months later:

- **Zero runs. Ever.** Not "rarely dispatched" — never dispatched.
- It ran on a hosted runner and reached its target over SSH at a
  private-network address. A hosted runner has no route to that network.
- It read its SSH key and its target from **Actions secrets. The
  repository has none** — zero secrets at repository scope. Even given a
  route, the first step that needed a credential would have had nothing
  to read.

Two independent structural reasons why it could not have produced
evidence, on top of the empirical fact that it never tried. It was not a
lane that nobody got round to dispatching; it was a lane that would not
have worked if somebody had.

What exists instead, and what the withdrawal makes visible: the same
acceptance runs by operator hand on the substrate node itself
(`scripts/federation-live-vm-acceptance.sh`, with the side and peer
passed as environment variables). That path ran three times on
2026-09-21/22 and surfaced four defects that had looked green for four
months. It is terminated rather than enforced — the `live-vm-operator`
exemption in `tests/lanes/lane_assignment.json` carries a review date
that is checked against the calendar and turns the lane red when it
lapses. That is the whole of the guarantee, and stating it plainly is
the point of the withdrawal.

Deleted with the workflow: `tests/infra/test_live_vm_acceptance_phase_3b.py`,
whose subject was the workflow's own YAML surface — the matrix axes, the
per-cell `should_run` filter and the aggregate verdict state machine. A
test that pins a file has to leave with the file it pins.

Still in the tree, deliberately, and reported rather than removed:
`scripts/ci-live-vm-acceptance-wrapper.sh` and
`scripts/ci-live-vm-phase-3b-driver.sh` with their test modules and
`docs/operations/live-vm-acceptance-phase-3b.md`. Both scripts run over
SSH from an operator-controlled host and neither needs a workflow to be
invoked; the wrapper drives the very script that produced the
2026-09-21/22 evidence. Their headers and the companion document have
been rewritten to say that no CI lane calls them and that neither has
ever been executed. Whether an operator tool that has never been run
should stay is a real question — it is a question about a capability,
not about a gate, and it belongs to its own decision rather than to this
one.
