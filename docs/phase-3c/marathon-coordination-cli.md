# Marathon-Coordination-CLI — Operator-Workflow

SPDX-License-Identifier: Apache-2.0

Tag-43 (Tomás Reinhart, Dev-Engineering / Matrix-Lead).

`scripts/phase-3c/marathon-coordination-cli.py` is the **top-level
operator CLI** for the Phase-3 Cutover-Marathon (ADR-0065 +
ADR-0066). It wraps the seven substrates produced during Tag-40..42
into one uniform sub-command surface so the operator-hand does not
have to remember per-substrate flag conventions on cutover day.

## Why a top-level CLI

Tag-40..42 produced seven separate substrates with seven separate
CLI surfaces:

| Substrate | Author | Path |
|---|---|---|
| Marathon-Aggregat-Tracker | Selin | `scripts/phase-3c/marathon-aggregat-tracker.py` |
| Cross-Welle-Generalprobe | Reza | `scripts/phase-3c/cross-welle-cutover-generalprobe.py` |
| Live-VM-Cutover-Drill | Kai | `scripts/phase-3c/live-vm-cutover-drill.sh` |
| Per-Welle Pre-Cutover-Probes | Selin/Kai/Amara | `scripts/phase-3c/welle-N-pre-cutover-probe.sh` |
| Phase-3-COMPLETE-Marker | Tomás | `.github/workflows/phase-3-complete-marker.yml` |
| Pre-Cutover-Sanity Workflow | Tomás | `.github/workflows/phase-3c-pre-cutover-sanity.yml` |
| Pre-Cutover-Marathon-Dashboard | Tomás | `.github/workflows/phase-3c-pre-cutover-marathon-dashboard.yml` |

On the operator-day-of the cutover those substrates need to be
fired in a specific order. The CLI exposes that order as named
sub-commands and adds two safety properties on top:

1. **Dry-run by default.** Every sub-command runs in non-mutating
   mode unless `--live` is supplied. `--live` further requires
   `--confirm I-CONFIRM-LIVE-CUTOVER` and refuses to dispatch when
   sandbox-stub-mode is active.
2. **Uniform envelope.** Every sub-command emits the same JSON or
   ASCII-table envelope so downstream tooling (Henrik audit,
   Marathon-Dashboard, AR-Sichtung) can consume a single schema.

## Sub-command reference

```text
marathon status
marathon probe --welle <N>             [--format json|table]
marathon probe --all                   [--format json|table]
marathon dryrun                        [--up-to-welle N]
marathon cutover --welle <N>           [--dry-run | --live]
marathon signoff --welle <N> --auditor <name>
marathon complete-check
marathon complete                      [--live --confirm <token>]
```

### `marathon status`

Renders the Marathon-Aggregat-Tracker state + a pointer to the
Pre-Cutover-Marathon-Dashboard workflow. Exit code = tracker exit
code (0/1/2/3).

### `marathon probe`

Runs the per-Welle Pre-Cutover-Sanity-Probe in sandbox-stub-mode.
With `--all` it iterates Welle 1..7 and emits a worst-of aggregate
verdict.

* `rc=0`: all probes green.
* `rc=1`: at least one probe yellow.
* `rc=2`: at least one probe red — Marathon BLOCKED.
* `rc=3`: probe script missing for at least one Welle.
* `rc=4` (probe-internal): VM unreachable, non-blocking by Tag-41
  AR-direktive.

### `marathon dryrun`

Invokes Reza's `cross-welle-cutover-generalprobe.py` with
`--dry-run`. Use `--up-to-welle N` to truncate the marathon at
Welle N (e.g. KW-24 has only Welle-1 + Welle-2 in scope).

### `marathon cutover --welle N`

Dispatches Kai's `live-vm-cutover-drill.sh` for one Welle. Without
`--live` the drill runs in dry-run mode (commands echoed, no SSH
mutation). With `--live` the top-level `--live --confirm` flags
must also be present **and** sandbox-stub-mode must NOT be active
(real SSH key required).

### `marathon signoff --welle N --auditor <name>`

Writes `state/welle-N-sign-off.json` with the supplied auditor
name. Idempotent: re-running on an existing marker returns yellow
without overwriting the original. This file is consumed by the
Phase-3-COMPLETE-Marker workflow's AC-1 check.

### `marathon complete-check`

Verifies the four readiness predicates before the
Phase-3-COMPLETE-Marker can be set:

* All seven `state/welle-N-sign-off.json` files present.
* `.github/workflows/phase-3-complete-marker.yml` present.
* `state/phase-3-complete-marker.json` not yet written.

Returns `ready / yellow / red` accordingly.

### `marathon complete`

In dry-run mode (default) this previews the complete-check verdict
without writing the marker. In `--live` mode it writes
`state/phase-3-complete-marker.json` — but only after all the
safety predicates pass and sandbox-stub-mode is inactive.

## Typical Cutover-Day Workflow

The operator-day-of workflow proceeds in seven phases. Each phase
runs first as a dry-run, then (on operator decision) as live.

```text
# ---- Phase 0: pre-flight ----------------------------------------
marathon status                          # is the marathon state sane?
marathon probe --all --format json       # are all seven Wellen READY?
marathon dryrun --up-to-welle 7          # does the generalprobe pass?

# ---- Phase 1: KW-24 Welle-1 v907_verify -------------------------
marathon cutover --welle 1               # dry-run (default)
# operator review of dry-run output, then:
marathon --live --confirm I-CONFIRM-LIVE-CUTOVER cutover --welle 1 --live
marathon signoff --welle 1 --auditor "Henrik Voss"

# ---- Phase 2: KW-24 Welle-2 svid_workload_identity --------------
marathon cutover --welle 2
marathon --live --confirm I-CONFIRM-LIVE-CUTOVER cutover --welle 2 --live
marathon signoff --welle 2 --auditor "Henrik Voss"

# ---- Phase 3..7: same shape for Welle-3 through Welle-7 ---------
# (Welle-3 is solo / KW-25; Welle-4+5 paired / KW-26; Welle-6+7
# paired / KW-27.)

# ---- Phase 8: Marathon closure ----------------------------------
marathon complete-check                  # all seven signed off?
marathon complete                        # preview the marker
# AR-hand ratification recorded separately:
#   state/ar-hand-phase-3-complete-stamp.json
# then finally:
marathon --live --confirm I-CONFIRM-LIVE-CUTOVER complete
```

## Sandbox-Stub-Mode

The CLI auto-detects whether SSH credentials are present:

* If `WAKIR_PILOT_SSH_KEY` does not resolve to a readable file,
  stub-mode is active.
* If `WAKIR_SSH_BIN=true`, stub-mode is forced (used by CI and by
  the Mira-sandbox hermetic test bed).
* `WAKIR_FORCE_STUB=1` is a manual override.

When stub-mode is active:

* All substrate invocations get `WAKIR_SSH_BIN=true` injected so
  the per-substrate hermetic tests do not open real SSH.
* `--live` is refused for `cutover` and `complete` — the CLI exits
  with a confirmation error instead of dispatching a half-real
  drill.

## Output formats

The `--format` flag is global (placed before the sub-command):

```bash
marathon --format json status
marathon --format table probe --all
```

* `table` is the default. ASCII summary with section headers.
* `json` is meant for downstream tooling. Stable schema (versioned
  by `schema_version`).

JSON envelope shape:

```json
{
  "schema_version": 1,
  "command": "signoff",
  "timestamp_utc": "2026-05-18T14:23:00Z",
  "verdict": "green",
  "stub_mode": true,
  "summary": "welle-3 signed off by Henrik Voss",
  "welle": 3,
  "details": { "...": "..." },
  "exit_code": 0
}
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | green / READY / OK |
| 1 | yellow / caution — operator decision required |
| 2 | red / BLOCK / FAIL — substrate refused or marathon halt |
| 3 | precond — bad args, missing substrate, refused confirmation |
| 4 | not-exec — sandbox-stub-mode succeeded, live not attempted |

## Authority & sandbox boundary

The CLI itself never opens an SSH connection — it only invokes
the underlying substrates as subprocesses. The substrates honour
the Mira-sandbox vs. live-VM separation per ADR-0058 §Nachtrag.
The CLI's `--live` flag is purely an authorisation marker; the
real SSH dispatch happens inside `live-vm-cutover-drill.sh` and is
guarded there by `WAKIR_SSH_BIN`.

## See also

* `docs/phase-3c/marathon-aggregat-tracker.md`
* `docs/phase-3c/cross-welle-generalprobe.md`
* `docs/phase-3c/live-vm-cutover-drill.md`
* ADR-0065 (Phase-3c Cutover-Plan)
* ADR-0066 (Phase-3c Beschleunigung Option-A+; Doppel-Welle order)
* `.github/workflows/phase-3-complete-marker.yml`
