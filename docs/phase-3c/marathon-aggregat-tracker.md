# Phase-3 Marathon-Aggregat-Tracker (Tag-40)

SPDX-License-Identifier: Apache-2.0

## Purpose

The Phase-3c cutover sequence (ADR-0065 + ADR-0066) flips the
persona-engine default backend from Python to Rust across seven
"Wellen" in KW 24..27. Each Welle traverses a discrete lifecycle
from pre-flight checks through cutover-execution to post-cutover
soak and operator-hand sign-off. The
`scripts/phase-3c/marathon-aggregat-tracker.py` substrate is the
single source of truth for "where in the marathon is each Welle
right now?" + the cross-Welle aggregate view.

The Tag-30 `phase-3c-welle-status-emitter.py` covers the coarse
5-state view for the Grafana dashboard. The Tag-40 tracker is the
**finer 9-state operator-hand lifecycle** that drives the
Cutover-Marathon-discipline and emits the `phase_3_complete` event
once all seven Welles are signed-off.

## Welle-Lifecycle (per Welle, ADR-0066)

```
    pending
        |
        v
    pre-flight-running
        |
        v
    pre-flight-green
        |
        v
    cutover-running     -------+
        |                      |
        v                      |
    cutover-green              |
        |                      |
        v                      |
    soak-running               |
        |                      |
        v                      |
    soak-green                 |
        |                      |
        v                      |
    sign-off-pending           |
        |                      |
        v                      |
    signed-off                 |
                               |
    Rollback path              |
    (from cutover-running      |
    onwards):                  |
    rollback-running   <-------+
        |
        v
    rolled-back
```

### Invariants

| ID  | Invariant |
|-----|-----------|
| I1  | Every Welle starts in `pending`. |
| I2  | Forward transitions follow the exact 8-step sequence; skipping is rejected. |
| I3  | Rollback is only legal from `cutover-running` onwards. Earlier rollback must use operator-hand reset (CLI: `--force`, not implemented for Tag-40 - operator-hand edit only). |
| I4  | Terminal states (`signed-off`, `rolled-back`) have no outbound transitions. |
| I5  | Every state change records a UTC timestamp; the full history is preserved. |
| I6  | When all seven Welles reach `signed-off`, the tracker emits a single `phase_3_complete` event (idempotent). |

## CLI

### Show the marathon-aggregate (ASCII table)

```sh
python scripts/phase-3c/marathon-aggregat-tracker.py --show-marathon
```

Sample output:

```
Welle | Domain                  | KW    | Pre | Cut  | Post | State              | Coupling      | Last-Update
--------------------------------------------------------------------------------------------------------------
    1 | v907_verify             | KW 24 | -   | -    | -    | pending            | <-w2:sync     | 2026-05-18T17:27:05Z
    2 | svid_workload_identity  | KW 24 | -   | -    | -    | pending            | <-w1:sync     | 2026-05-18T17:27:05Z
    3 | bridge_audit_writer     | KW 25 | -   | -    | -    | pending            | solo          | 2026-05-18T17:27:05Z
    4 | state_backing           | KW 26 | -   | -    | -    | pending            | <-w5:sync     | 2026-05-18T17:27:05Z
    5 | lifecycle_state_machine | KW 26 | -   | -    | -    | pending            | <-w4:sync     | 2026-05-18T17:27:05Z
    6 | subscribe_loop          | KW 27 | -   | -    | -    | pending            | <-w7:sync     | 2026-05-18T17:27:05Z
    7 | recovery_workflow       | KW 27 | -   | -    | -    | pending            | <-w6:sync     | 2026-05-18T17:27:05Z
--------------------------------------------------------------------------------------------------------------
Marathon: signed-off=0/7 (0.0%), in-flight=0, rolled-back=0, pending=7
```

Column legend for the Pre / Cut / Post tri-columns:

| Symbol  | Meaning |
|---------|---------|
| `-`     | not started |
| `RUN`   | running |
| `OK`    | green / done |
| `PEND`  | sign-off pending (post-column only) |
| `ROLL`  | rolled-back affects this column |

### Show a single Welle's detailed history

```sh
python scripts/phase-3c/marathon-aggregat-tracker.py --show-welle 3
```

### Show aggregate counters only (JSON)

```sh
python scripts/phase-3c/marathon-aggregat-tracker.py --show-aggregat
```

### Update a Welle's state (operator-hand transition)

```sh
python scripts/phase-3c/marathon-aggregat-tracker.py \
    --update-welle 1 --state pre-flight-running

python scripts/phase-3c/marathon-aggregat-tracker.py \
    --update-welle 1 --state pre-flight-green --note "PR #190 merged"
```

### JSON output for all commands

Append `--json`:

```sh
python scripts/phase-3c/marathon-aggregat-tracker.py --show-marathon --json
```

## Persisted state file

Default path: `state/phase-3-marathon-state.json`. Schema-version 1.
Canonical formatting (sorted keys, 2-space indent, trailing newline)
so `git diff` is meaningful.

Top-level fields:

| Field                  | Type        | Description |
|------------------------|-------------|-------------|
| `schema_version`       | int         | Currently `1`. Mismatch causes `StateFileError`. |
| `created_utc`          | str (ISO-8601 Z) | First-creation timestamp. |
| `updated_utc`          | str (ISO-8601 Z) | Last-update timestamp. |
| `phase_3_complete`     | bool        | `true` iff all 7 Welles are `signed-off`. |
| `phase_3_complete_utc` | str or null | Timestamp of the all-signed-off transition (set once). |
| `welles`               | object      | Map `"1".."7"` -> WelleEntry. |

Each WelleEntry has `welle`, `domain`, `kw`, `pair`, `state`,
`first_seen_utc`, `last_updated_utc`, `history[]`. History rows are
`{"state": <name>, "utc": <iso>, "note": <str or null>}`.

## Phase-3-COMPLETE trigger

When the final `--update-welle N --state signed-off` transition
flips the 7th Welle to `signed-off`:

1. `state.phase_3_complete` becomes `true`;
2. `state.phase_3_complete_utc` is set to the same timestamp;
3. An event-file is written to `state/events/phase_3_complete.json`
   (idempotent: re-emit is a no-op).

The event-file is the substrate the post-Phase-3 closeout
Cross-Agent workflow consumes (Tomás validation aggregator, Henrik
audit-trail evidence, Mira AR briefing).

## Posture

This tracker is **operator-hand-driven**: it never reaches out to
CI, GitHub, podman, or a live VM. It is the discipline-substrate
the Mira-Hand uses to record "where in the marathon are we" - the
actual evidence for each transition is gathered by sibling
substrates:

* `scripts/phase-3c/welle-{N}-cutover-smoke.{py,sh}` - pre-flight smoke;
* `.github/workflows/phase-3c-welle-{N}-validation.yml` - cutover validation;
* `scripts/phase-3c-welle-status-emitter.py` - coarse 5-state live view;
* `scripts/observability/*` - SRE telemetry.

## Cross-references

* ADR-0065 - Phase-3c cutover sequence definition.
* ADR-0066 - KW-24..27 parallel-execution schedule (Option A+).
* `scripts/phase-3c-welle-status-emitter.py` - coarse 5-state Grafana emitter.
* `scripts/phase-3c-trigger-gate-aggregator.py` - pre-Phase-3c readiness gate.
* `docs/operations/live-vm-acceptance-phase-3b.md` - operator-hand acceptance contract.

## Stdlib-only contract

Python 3.13+, stdlib only. No third-party dependencies. The tracker
is pinnable to a single git-blob hash and survives Phase-3c
substrate-changes without dependency-pin churn.

-- Selin (Persona-Engine-Ingenieurin)
