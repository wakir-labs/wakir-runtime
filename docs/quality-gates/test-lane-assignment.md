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

Measured at commit `2193ed88`, 2026-09-14 (ADR-0074 removed 8 modules from one
optional-ci directory shortly after; the unassigned count is unaffected):

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
| `operator-hand` | reachable only via `workflow_dispatch` | yes — plus execution evidence |
| `opt-in-marker` | no lane; skip-by-default marker | yes — plus execution evidence |
| `unassigned` | no lane, no marker: nothing runs it, ever | yes — **plus an owner and a review date** |

## Why "runs by operator hand" is not a reason on its own

The first draft of this page said a standing exception (`deliberate:
true`) needs no review date, because a date on a permanent decision is
theatre. That was wrong in a specific and checkable way, and the numbers
say so:

| standing exception | mechanism | enabled by | runs |
|---|---|---|---:|
| `live-vm-operator` | `workflow_dispatch` + `--run-live-vm` | `live-vm-acceptance.yml` | **0, ever** |
| `sbom-baseline-operator` | `workflow_dispatch` | `sbom-baseline-refresh.yml` | **0, ever** |
| `phase-3c-opt-in` | `WAKIR_PHASE_3C_*` / `--phase-3c-*` | **no workflow sets these** | **0, ever** → 1, on 2026-09-20 ([below](#the-first-date-that-bit)) |
| `phase-3-skeleton-opt-in` | `WAKIR_PHASE_3_SKELETON=1` | **no workflow sets this** | **0, ever** |

All 22 modules classified as deliberate standing exceptions had never
executed. `live-vm-acceptance.yml` had not been dispatched once since it
was added on 2026-05-16. No workflow in this repository sets any of the
Phase-3c opt-in variables, so 207 tests documented as "skip-by-default,
opt-in" are in practice skip-always — the acceptance criteria for a
cutover, written down and unexecuted.

**What has happened to the first row since.** The live-VM acceptance ran
on 2026-09-21/22 — three times, by operator hand on the substrate node,
and it failed there, which is the useful kind of failing. The workflow
half never ran and, on a closer reading, never could have: a hosted
runner has no route to a private-network target and the repository holds
no Actions secrets. It was withdrawn on 2026-09-22 under ADR-0077, along
with the companion real-VM job whose runner label no runner carries. So
the row's `enabled by` column now reads *operator hand on the node*, and
the exemption's own `execution_evidence` says so. The mechanism column
is unchanged in one respect that matters: `--run-live-vm` is still the
switch, and nothing in CI passes it.

So the rule is now: every standing exception states the mechanism that
would run it, what enables that mechanism, and when it last actually ran
(`execution_evidence`). And a standing exception whose evidence says
`never` does not get to be standing: it carries a review date like any
other accident. `test_standing_exceptions_must_have_actually_run`
enforces exactly that.

The evidence is a pinned reading (GitHub Actions API, 2026-09-14), not a
live query — a hermetic test cannot call the API, and pretending
otherwise would be the same class of unfalsifiable claim. What the test
enforces is that the claim is stated, dated and sourced.

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
* **The WAT proof path.** 46 of the 47 modules under `tests/wat` run nowhere:
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
| ~~`phase-3c-opt-in`~~ | 19 | *retired 2026-09-20* | selin | — |
| `spire-federation-substrate` | 14 | unassigned | kai | 2026-10-31 |
| `spec-audit-evidence` | 9 | unassigned | reza | 2026-10-31 |
| `ci-meta` | 9 | unassigned | kai | 2026-10-31 |
| `cross-lang-parity` | 6 | unassigned | selin | 2026-09-30 |
| `script-driver` | 6 | unassigned | kai | 2026-10-31 |
| `workflow-shape` | 5 | unassigned | kai | 2026-09-30 |
| `spec-freeze` | 4 | unassigned | reza | 2026-09-30 |
| `integration-regression` | 1 | unassigned | kai | 2026-10-31 |
| `proof-path-driver` | 1 | unassigned | tomas | 2026-09-30 |
| `phase-3-skeleton-opt-in` | 1 | opt-in-marker | tomas | 2026-10-31 |
| `live-vm-operator` | 1 | operator-hand | kai | 2026-09-30 |
| `sbom-baseline-operator` | 1 | operator-hand | kai | 2026-10-31 |

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

Both allow-lists are **empty** at this baseline, and staying empty is the
goal. Every module-level guard in the tree now names something
`pyproject.toml` declares or a package that lives here.
`test_allow_lists_have_no_stale_entries` stops dead exceptions from
accumulating — an allow-list entry whose subject was deleted still reads
like a live one.

### The same pattern in three repositories

This is not a local quirk. In one week: `wakir-protocol` had 19 modules
and 309 of 1132 node IDs (27 %) behind import-time guards on *declared*
dependencies; `wakir-verify` ran its python-bitcoinlib drift matrix —
the one check that compares against an independent third-party library,
which is what the whole cross-library argument rests on — behind an
`importorskip` that no lane ever satisfied; and here, 177 modules that
no workflow runs at all. Three repositories, three shapes, one class: a
test that is present, green-adjacent, and not executed. The gate above
is the runtime-side answer; the assignment file is the bookkeeping-side
one.

## The first date that bit

`phase-3c-opt-in` is the first exemption to reach its review date with
the ADR-0075 §3 mechanism live, and the point of the mechanism is what
happened next rather than that a date passed.

The group's reason was that the opt-in had never been taken: 19 modules,
207 tests, the written acceptance criteria for the Phase-3c cutover of
**2026-05-20**, behind `WAKIR_PHASE_3C_E2E` / `WAKIR_PHASE_3C_DOPPEL_E2E`
/ `WAKIR_PHASE_3C_ROLLBACK_DRILL`, and no workflow setting any of them.
On **2026-09-20**, at commit `979f3f98`, they were run:

```
175 passed, 15 failed, 17 skipped      0.6 s, no podman, no NATS, no network
```

All 15 failures were one defect. The archaeology rename of 2026-09-14
(PR #533) replaced `Welle` with `wave` inside 21 f-string *placeholders*
in `tests/acceptance/phase_3c/_ac_assertions.py` while the surrounding
parameter stayed `welle`. Every one sits in an assertion's failure
message, so the happy path stayed silent and the failure path raised
`NameError` instead of `AssertionError`. The 15 tests that broke are the
negative controls — the half of the acceptance criteria that asserts a
violation is *caught*. That half was inoperative for six days, and it
merged green because this group ran nowhere. After the fix: **190 passed,
0 failed, 17 skipped**.

Two things follow, and both are now in place:

* The group is retired. The 19 modules are `required` through
  `runtime-acceptance-gates.yml:lane-phase-3c-acceptance`. The earlier
  objection was drill character; the measurement was 0.6 s and no
  infrastructure, so there was no cost to weigh against the six days.
* A lane over a skip-by-default marker can be green and empty, because
  `pytest` exits 0 when everything skips. `tooling/ci/skip_gate.py` reads
  the JUnit report and refuses a run in which any test was skipped for
  the opt-in reason. It is the skip-side counterpart of the collect-gate
  above, and it exists because renaming a flag in a `conftest.py` would
  otherwise turn this lane back into decoration without turning it red.

What the lane does **not** establish: that the cutover met its criteria.
The fixtures are hermetic placeholder oracles with hard-coded numbers,
and 17 of the 207 carry a second, inner skip pending real perf gauges, a
real SPIRE agent and operator-hand runbooks. Green here means the
acceptance assertions hold their shape, including their failure paths.
Reading more into it would repeat the error this page is about.

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
