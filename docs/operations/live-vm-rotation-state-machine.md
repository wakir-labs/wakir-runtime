# Live-VM Rotation State-Machine (OPEN-J2 Sandbox-Stub)

**Status:** Tag-60 (2026-05-19). Stub-only — no live VM is touched
from this lane. The Operator-Hand rotation recipe is validated
hermetically as a deterministic state-machine.

**Scope:** rotation plan `0.5.1 -> 0.5.2 -> 0.5.3-rc1`. The two
intermediate stops (`0.5.2`, `0.5.3-rc1`) are visited explicitly;
the operator companion can hold at `STABILIZED_AT_0_5_2` for any
duration before electing to advance.

**Out of scope:** any actual VM lifecycle invocation
(snapshot / image swap / quadlet reload / acceptance probe).
Those steps are Operator-Hand by construction per
`feedback_sandbox_host_trennung.md` and remain so.

---

## §1 Why a stub, not the real thing

OPEN-J2 was marked "kein CI-Substrat moeglich" on Tag-56 because
the rotation drives an actual VM lifecycle: snapshot create,
image swap, systemd quadlet reload, post-rotation acceptance
probe against a `192.168.178.*` LAN host. The hermetic claude-dev
Sandbox cannot reach that LAN by design — and we do not relax that
boundary just to fit a CI lane around it.

What we **can** validate without touching the VM is the *plan*
the operator companion will execute: which states exist, which
transitions are legal, which recovery paths exist from each
failure state, and which decision-points the operator must
resolve manually.

That plan is a deterministic graph. The simulator at
`tooling/ci/simulate_live_vm_rotation_state_machine.py` encodes
that graph as a transition-table and exercises it exhaustively
in pure Python (stdlib only). The probe asserts the graph is
internally consistent and recoverable — it does **not** assert
the live rotation will succeed.

The Sandbox-Boundary is hard and stays hard. The probe verdict
`ROTATION-STATE-MACHINE-INTACT` means: the plan is shape-ready.
It does not mean: the rotation will succeed. The operator still
performs the live rotation by hand, with the recipe at
`docs/operations/live-vm-acceptance-phase-3b.md` and the AR
authorisation pathway described in §6.

---

## §2 States and the transition table

The state-machine carries **12 states** total (10 non-terminal,
2 terminal-healthy). The full list is enumerated in
`STATES` in `tooling/ci/simulate_live_vm_rotation_state_machine.py`
and reproduced here for the operator companion.

### Non-terminal states (10)

| State | Meaning |
| --- | --- |
| `PRE_FLIGHT_CHECKS` | Operator runs the pre-rotation acceptance checks against the VM at 0.5.1. |
| `SNAPSHOT_CREATED` | Pre-rotation snapshot captured (rollback anchor). |
| `IMAGE_SWAP_0_5_2` | Container image swap to 0.5.2 in progress. |
| `QUADLET_RELOAD_0_5_2` | Systemd quadlet reload after the 0.5.2 swap. |
| `ACCEPTANCE_PROBE_0_5_2` | Post-swap acceptance probe against 0.5.2. |
| `STABILIZED_AT_0_5_2` | VM is stable at 0.5.2. Operator decides whether to advance to 0.5.3-rc1 or hold. |
| `IMAGE_SWAP_0_5_3_rc1` | Container image swap to 0.5.3-rc1 in progress. |
| `QUADLET_RELOAD_0_5_3_rc1` | Systemd quadlet reload after the 0.5.3-rc1 swap. |
| `ACCEPTANCE_PROBE_0_5_3_rc1` | Post-swap acceptance probe against 0.5.3-rc1. |
| `ROLLBACK_IN_PROGRESS` | Operator triggered rollback to the snapshot anchor. Only legal next state: `DRAINED`. |

### Terminal-healthy states (2)

| State | Meaning |
| --- | --- |
| `ROTATION_COMMITTED_v0_5_3_rc1` | Full rotation `0.5.1 -> 0.5.3-rc1` complete. Both acceptance probes passed. |
| `DRAINED` | Rotation aborted cleanly. The VM is back on 0.5.1, no in-flight requests dropped, operator chose not to retry. |

### Transition table

Each row is `(state, event) -> next_state`. Every failure state
routes into `ROLLBACK_IN_PROGRESS` via a `*_fail` or `hold`
event; `ROLLBACK_IN_PROGRESS` routes to `DRAINED` via
`drain_ok`. This is the graph-property the probe Stage-2 check
asserts.

| From | Event | To |
| --- | --- | --- |
| `PRE_FLIGHT_CHECKS` | `checks_pass` | `SNAPSHOT_CREATED` |
| `PRE_FLIGHT_CHECKS` | `checks_fail` | `ROLLBACK_IN_PROGRESS` |
| `SNAPSHOT_CREATED` | `snapshot_ok` | `IMAGE_SWAP_0_5_2` |
| `SNAPSHOT_CREATED` | `snapshot_fail` | `ROLLBACK_IN_PROGRESS` |
| `IMAGE_SWAP_0_5_2` | `swap_ok` | `QUADLET_RELOAD_0_5_2` |
| `IMAGE_SWAP_0_5_2` | `swap_fail` | `ROLLBACK_IN_PROGRESS` |
| `QUADLET_RELOAD_0_5_2` | `reload_ok` | `ACCEPTANCE_PROBE_0_5_2` |
| `QUADLET_RELOAD_0_5_2` | `reload_fail` | `ROLLBACK_IN_PROGRESS` |
| `ACCEPTANCE_PROBE_0_5_2` | `probe_ok` | `STABILIZED_AT_0_5_2` |
| `ACCEPTANCE_PROBE_0_5_2` | `probe_fail` | `ROLLBACK_IN_PROGRESS` |
| `STABILIZED_AT_0_5_2` | `advance` | `IMAGE_SWAP_0_5_3_rc1` |
| `STABILIZED_AT_0_5_2` | `hold` | `ROLLBACK_IN_PROGRESS` |
| `IMAGE_SWAP_0_5_3_rc1` | `swap_ok` | `QUADLET_RELOAD_0_5_3_rc1` |
| `IMAGE_SWAP_0_5_3_rc1` | `swap_fail` | `ROLLBACK_IN_PROGRESS` |
| `QUADLET_RELOAD_0_5_3_rc1` | `reload_ok` | `ACCEPTANCE_PROBE_0_5_3_rc1` |
| `QUADLET_RELOAD_0_5_3_rc1` | `reload_fail` | `ROLLBACK_IN_PROGRESS` |
| `ACCEPTANCE_PROBE_0_5_3_rc1` | `probe_ok` | `ROTATION_COMMITTED_v0_5_3_rc1` |
| `ACCEPTANCE_PROBE_0_5_3_rc1` | `probe_fail` | `ROLLBACK_IN_PROGRESS` |
| `ROLLBACK_IN_PROGRESS` | `drain_ok` | `DRAINED` |

19 transitions total. Every non-terminal state has exactly
**one** healthy event (advancing the rotation) and **one**
rollback event, except `ROLLBACK_IN_PROGRESS` which has only
`drain_ok`. `STABILIZED_AT_0_5_2` carries the only true
operator decision-point (`advance` vs `hold` — see §4).

---

## §3 Recovery paths

A **recovery path** is the trace from a failure state back to a
terminal-healthy state. The probe Stage-2 check enumerates every
failure state and runs the simulator with the `recovery`
strategy; the run must terminate at `DRAINED` within
`MAX_TRANSITIONS = 32` steps without revisiting a state.

In the current table every recovery path is two transitions:

    <failure_state> --(*_fail|hold)--> ROLLBACK_IN_PROGRESS --(drain_ok)--> DRAINED

This means: from any failure state, the operator can always
fall back to the snapshot anchor and drain cleanly. No failure
state is a dead-end. No recovery path cycles.

If a future change to the transition table breaks this property
— for example, by adding a transition out of `DRAINED` back into
a non-terminal state — the probe Stage-2 check fails with
verdict `DRIFT` and the workflow refuses to merge.

---

## §4 Decision-points

The operator companion encounters exactly one true decision-point
during a happy-path rotation: at `STABILIZED_AT_0_5_2`, the
operator must choose between `advance` (continue to 0.5.3-rc1)
and `hold` (stop here and drain back to 0.5.1).

All other states have a deterministic event the operator either
observes (e.g. `swap_ok` vs `swap_fail` from the underlying
podman/systemd return code) or triggers (`drain_ok` after the
rollback completes). The operator is not picking between two
equally legal advances at those states.

### Recommended hold criteria at `STABILIZED_AT_0_5_2`

The operator should pick `hold` (and accept a partial rotation
to 0.5.2 only, with rollback to 0.5.1) when any of the
following is true:

* The 0.5.2 acceptance probe passed but with a single failure
  vector flagged as a known-pending fix.
* The pre-cutover AR-authorisation window has elapsed
  mid-rotation (see §6).
* External observability (Noa SRE dashboards) shows latency or
  error-rate drift that the post-0.5.2 acceptance probe did
  not catch.

Otherwise: pick `advance`. The state-machine does not encode
these criteria — they are operator judgement on top of the
deterministic graph.

---

## §5 Running the probe locally

The probe is stdlib-only and runs in well under a second.

### Happy-path single run

    python3 tooling/ci/simulate_live_vm_rotation_state_machine.py \
        --entry-state PRE_FLIGHT_CHECKS \
        --strategy happy_path \
        --out /tmp/sm-happy.json

Expected: exit 0, final state `ROTATION_COMMITTED_v0_5_3_rc1`,
verdict `ROTATION-STATE-MACHINE-INTACT`.

### Recovery-path completeness

    python3 tooling/ci/simulate_live_vm_rotation_state_machine.py \
        --verify-recovery-paths \
        --out /tmp/sm-recovery.json

Expected: exit 0, every failure state in `FAILURE_STATES`
terminates at `DRAINED`.

### All entry states sweep

    python3 tooling/ci/simulate_live_vm_rotation_state_machine.py \
        --all-entry-states \
        --strategy happy_path \
        --out /tmp/sm-sweep.json

Expected: exit 0, every entry-state in `ENTRY_STATES` terminates
at a healthy terminal under the happy-path strategy.

### CI lane

The probe is wired as a CI lane at
`.github/workflows/live-vm-rotation-state-machine-probe.yml`
and triggered on push to main, on PR touching the probe
artifacts, and on `workflow_dispatch`. The lane is a required
status-check candidate once the Operator-Hand rotation is
scheduled.

---

## §6 AR-Authorisation pathway

The probe is the green-light tripwire. It does **not** authorise
the live rotation — the Aufsichtsrat does, on the strength of the
probe verdict plus the wider Phase-3c pre-cutover bundle (Tag-59
OTS pre-anchor probe, Tag-57 K2 audit-only emit, Welle-3..7
hot-spot probes).

Pathway:

1. **Probe green.** `live-vm-rotation-state-machine-probe`
   reports `ROTATION-STATE-MACHINE-INTACT` on main.
2. **Bundle assembled.** Internal Audit (Henrik Voss) folds the
   probe verdict into the pre-cutover bundle.
3. **AR sights.** Aufsichtsrat reviews the bundle in the
   pre-cutover gate (KW-24 window pinned by Tag-58 Wirelang-Spec
   seal).
4. **AR authorises.** Explicit go/no-go decision recorded in
   `activity-log.md` plus the relevant ADR closeout.
5. **Operator schedules.** Operator (Fred / Mira-Hand) picks the
   rotation window and runs the actual VM rotation off the
   recipe at `docs/operations/live-vm-acceptance-phase-3b.md`.
   The Sandbox is never in this loop.
6. **Post-rotation acceptance.** Operator captures the
   post-rotation acceptance probe (real VM, real SSH, real
   `192.168.178.*` host) and files it as the rotation-closeout
   artifact.

If the probe reports `DRIFT` at step 1 the rotation does not
proceed — the table change is reverted or the gap is closed
before the bundle is resubmitted.

— Tomás
