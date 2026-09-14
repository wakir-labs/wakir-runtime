<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Test-lane assignment

Which gate runs which test module — and, for every module no gate runs,
why, who owns that, and by when it gets decided.

The machine-readable source of truth is
[`tests/lanes/lane_assignment.json`](../../tests/lanes/lane_assignment.json).
This page is the readable half; the two cannot drift, because
`tests/lanes/test_lane_assignment.py` derives the assignment from
`.github/workflows/` on every run of the required production lane.

## The finding this exists because of

Measured at commit `2193ed88`, 2026-09-14:

| | modules |
|---|---:|
| test modules in the tree | 419 |
| targeted by a **required** status context | 190 |
| targeted by a non-required workflow | 30 |
| reachable only by `workflow_dispatch` | 2 |
| guarded by a skip-by-default marker | 20 |
| **targeted by nothing at all** | **177** |

Two properties of the 190 matter more than the number:

* **175 of them are one directory.** `wirelang/` is the only tree any
  lane collects wholesale (`pytest wirelang/`). Out of `tests/` — 230
  modules — 15 are named individually in a required lane, by filename.
* **`tests/` was the declared test root and had no lane.** `testpaths`
  read `["tests"]` while the main lane ran `wirelang/`. A bare `pytest`
  collected the one tree CI does not run. That is now fixed in the
  honest direction: `testpaths` names every root that holds tests, and
  says in a comment that it is a statement about where tests *are*, not
  about what CI executes. What CI executes is this file.

And the part that is not a number: **the whole tree is hermetically
green.** `pytest tests wirelang infra` at the baseline is 7187 passed,
328 skipped, 0 failed, 84 seconds — no podman, no VM, no network, no
cargo. The 177 unrun modules are not unrunnable. Nobody wired them up.

## Profiles

| profile | meaning | needs a justification? |
|---|---|---|
| `required` | a required status context points a runner at it | no |
| `optional-ci` | a non-required workflow runs it on PR/push/schedule | no |
| `operator-hand` | reachable only via `workflow_dispatch` | yes — standing exception |
| `opt-in-marker` | no lane; skip-by-default marker | yes — standing exception |
| `unassigned` | no lane, no marker: nothing runs it, ever | yes — **plus an owner and a review date** |

The distinction that does the work: a standing exception (`deliberate:
true`) is a decision and gets no review date, because a review date on a
permanent decision is theatre. An `unassigned` module is the absence of a
decision and gets one.

## Contracts currently checked by no gate

Named, because "48 % of modules are unrun" is a statistic and these are
the specific things it costs:

* **Required contexts cannot fail open.**
  `tests/workflows/test_required_context_error_propagation.py` asserts
  that a required context using `needs:` cannot disappear by being
  *skipped* when a dependency fails — GitHub does not block a merge on a
  skipped required check. The guard for every other gate in this
  repository runs in no lane. It was added in the same commit this
  assignment was measured at.
* **The WAT proof path.** 46 modules under `tests/wat` run nowhere:
  Merkle-root construction and proof verification (`test_merkle.py`),
  manifest v1/v2 signature and schema admission, the OTS full-verify
  path, cross-module anchor pin consistency. Exactly one WAT module is
  in a required lane. This is the path Phase 4 exists to seal.
* **The proof-path driver's own fault handling.** The required
  `proof-path` context executes `scripts/demo-proof.sh` end to end;
  `tests/scripts/test_demo_proof.py` (33 tests, fault injection via
  `DEMO_PROOF_FAIL_STEP`, `wakir_verify`-absent path) runs nowhere. A
  refactor that breaks failure reporting is caught only if it also
  breaks the happy path.
* **Required-check names match job display-names.**
  `tests/ci/test_branch_protection_check_names_audit.py` pins exactly
  the PR #102 failure class — a renamed job leaving pull requests
  pending forever. Unrun. (The lane-assignment guard now re-checks this
  property from the other direction, in a required lane.)
* **The v0.4.3 spec freeze is a strict superset.** The required
  freeze-seal probe verifies the seal envelope
  (`tests/audit/test_wirelang_spec_freeze_seal_probe.py`, via
  `python -m unittest`); the strict-superset property
  (`tests/specs/test_wirelang_spec_v0_4_3_pre_cutover_freeze.py`,
  12 tests) is verified nowhere.
* **Python/Rust wire parity for six persona-engine surfaces.** The
  parity suites that happen to live under `tests/` instead of
  `wirelang/tests/` fall outside the one directory the required suite
  collects. Their siblings inside `wirelang/` are required.

## The exemption groups

Reasons and owners live in `exemption_groups` in the JSON. Summary:

| group | modules | profile | owner | review by |
|---|---:|---|---|---|
| `wat-core` | 46 | unassigned | tomas | 2026-09-30 |
| `infra-substrate` | 29 | unassigned | kai | 2026-10-31 |
| `orchestrator-substrate` | 27 | unassigned | kai | 2026-10-31 |
| `observability-routing` | 20 | unassigned | noa | 2026-10-31 |
| `phase-3c-opt-in` | 19 | opt-in-marker | selin | standing |
| `spire-federation-substrate` | 14 | unassigned | kai | 2026-10-31 |
| `spec-audit-evidence` | 9 | unassigned | reza | 2026-10-31 |
| `ci-meta` | 9 | unassigned | kai | 2026-10-31 |
| `cross-lang-parity` | 6 | unassigned | selin | 2026-09-30 |
| `script-driver` | 6 | unassigned | kai | 2026-10-31 |
| `workflow-shape` | 5 | unassigned | kai | 2026-09-30 |
| `spec-freeze` | 4 | unassigned | reza | 2026-09-30 |
| `integration-regression` | 1 | unassigned | kai | 2026-10-31 |
| `proof-path-driver` | 1 | unassigned | tomas | 2026-09-30 |
| `phase-3-skeleton-opt-in` | 1 | opt-in-marker | tomas | standing |
| `live-vm-operator` | 1 | operator-hand | kai | standing |
| `sbom-baseline-operator` | 1 | operator-hand | kai | standing |

Owners are QA's proposal from component ownership, not an assignment.
Confirming or moving them is the CTO's call; the file is the place to
record the answer.

## The collection gate

`tooling/ci/collect_gate.py` runs in both `tests.yml` jobs and closes
the half of `--collect-only` that counting never covered:

* a **collection error** is red, named, in both profiles;
* in the **production** profile, a module that yields zero node IDs is
  red — that is the silent case, where a module-level
  `pytest.importorskip` fires on something the lane is supposed to have
  and pytest still exits 0 with a smaller count;
* in the **production** profile, an import guard naming something
  `pyproject.toml` never declared is red;
* in the **sandbox** profile, zero collection is *expected* and stays
  green. The production/sandbox split is deliberate, the existing hard
  guards ("verify rfc8785 + jsonschema are present / absent") remain the
  authority, and the drift envelope consumes the same integer as before.

A third step collects `tests/ wirelang/ infra/` as a whole. Collection,
not execution: the 177 unrun modules cannot rot into unimportable code
unnoticed, and nothing is asserted about their contents. Turning any of
them into an executed lane is a separate, owned decision.

Each failure class has a negative control in
`tests/lanes/test_collect_gate.py`, including the premise itself: that a
module-level `importorskip` really does exit 0 and vanish.

## Working with this file

```sh
python tooling/ci/lane_inventory.py          # summary
python tooling/ci/lane_inventory.py --json   # derived facts per module
python tooling/ci/lane_inventory.py --sync   # after adding/moving tests
python -m pytest tests/lanes/                # the guard itself
```

`--sync` refreshes modules, profiles and counts. It never invents a
justification: a newly exempt module lands without a group and the guard
stays red until somebody writes the reason.
