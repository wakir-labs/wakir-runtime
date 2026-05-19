<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# Tag-66 Watch-Day Operator-Trigger Audit-Trail Marker-Catalog (Noa SRE)

Status: **substrate** — single-source-of-truth for the audit-marker-tag
classes that the Tag-66 verifier (`tooling/ci/
verify_watch_day_operator_trigger_audit_trail.py`) enforces on every
Watch-Day operator-trigger event.

Anchor: Tag-66 Marathon-Continuous-Mode Pre-KW-24 closeout.

Co-substrate:

  * **Tag-62** (PR #397) `watch-day-operator-trigger-simulation.yml`
    — operator-trigger pipeline simulator.
  * **Tag-63** (PR #402) `operator-trigger-alert-routing-integration.yml`
    — trigger-event + alert-routing integration.
  * **Tag-66** (this) — audit-trail-conformance per individual
    trigger-event.
  * **Tomás-Tag-66** — sibling AR-override audit-trail verifier
    (analogous shape, distinct source class).

## Motivation

Tag-62 and Tag-63 pin **what** the operator emits on Cutover-Day T0
and **which** routing-table receives the event. Neither pins the
**audit-trail conformance of every individual event**. The failure
mode without Tag-66:

> The operator runs the Tag-56 workflow on Cutover-Day. The
> `workflow_dispatch` envelope is well-formed (Tag-62 green), the
> alert-routing recognises the source (Tag-63 green), but the
> envelope carries no `actor` field, no `audit_marker_tag`, and no
> `dispatched_at` timestamp. A post-incident audit cannot
> reconstruct *who* triggered *what* *when* — only that *something*
> dispatched.

Tag-66 pins the per-event audit-trail-marker contract.

## Required audit-marker key-set

Every Watch-Day operator-trigger envelope MUST carry:

| key | type | example |
|-----|------|---------|
| `event` | string | `"workflow_dispatch"` |
| `workflow` | string | `"phase-3c-watch-day-practice-run.yml"` |
| `ref` | string | `"refs/heads/main"` |
| `inputs` | mapping | `{"diagnostic": "true"}` |
| `actor` | string | `"mira-hand-operator"` |
| `dispatched_at` | ISO-8601 string | `"2026-06-09T05:00:00Z"` |
| `audit_marker_tag` | tag (see below) | `"watch-day-operator-20260609-3bc7794"` |
| `trigger_sequence_id` | UUIDv4 string | `"a3e4f5b6-..."` |

The four `event`/`workflow`/`ref`/`inputs` keys are the Tag-62
**base shape** (legacy-compatible).

The four `actor`/`dispatched_at`/`audit_marker_tag`/`trigger_sequence_id`
keys are the **audit-only overlay**: missing audit-only keys downgrade
the per-envelope status from green to yellow, not red.

## audit-marker-tag pattern

```
watch-day-<source>-<YYYYMMDD>-<short-hash>
```

Regex: `^watch-day-(operator|ar|cron|replay)-(\d{8})-([0-9a-f]{7,12})$`

* `<source>` — one of the four canonical marker classes below.
* `<YYYYMMDD>` — dispatch-date in UTC, no separators.
* `<short-hash>` — git-short-hash (7–12 hex chars) of the commit
  the workflow runs against, for post-mortem traceability.

Examples:

* `watch-day-operator-20260609-3bc7794` — Mira-Hand operator-dispatch
  on Cutover-Day T0 (Tue 2026-06-09) against commit `3bc7794`.
* `watch-day-ar-20260609-7a9b00e` — Aufsichtsrat override-flag dispatch
  on the same day.
* `watch-day-cron-20260609-3bc7794` — Tag-56 scheduled cron-fire.
* `watch-day-replay-20260612-3bc7794` — Tag-59 replay-driver re-dispatch
  three days post-incident.

## Canonical marker classes

The Tag-66 verifier enumerates exactly four legitimate trigger
origins for Watch-Day-substrate `workflow_dispatch` events. Each
class has a canonical name + source-token + expected `event` type.

### operator-hand-dispatch

* **source**: `operator`
* **expected event**: `workflow_dispatch`
* **description**: Mira-Hand operator clicks "Run workflow" on
  Cutover-Day T0 against the Tag-56 watch-day-practice-run workflow.
* **canonical actor**: `mira-hand-operator` (or the actual GitHub
  account name of the operator-on-call).

### ar-hand-override

* **source**: `ar`
* **expected event**: `workflow_dispatch`
* **description**: Aufsichtsrat override-flag dispatch, rare. Wired
  to the Tag-65 AR-Hand cutover-override-listener
  (`tooling/ci/ar_hand_cutover_override_listener.py`).
* **canonical actor**: `aufsichtsrat-override`.

### scheduled-cron

* **source**: `cron`
* **expected event**: `schedule`
* **description**: Calendar-pinned cron-fire (Tag-56 watch-day cron,
  Tue 05:00 UTC). When an envelope carrying a `cron` marker tag
  appears inside a `workflow_dispatch` event, the verifier downgrades
  to yellow (source-event-mismatch) — this is operationally legit
  only for the Tag-57 cron-pre-fire-probe replay path.
* **canonical actor**: `github-actions[bot]`.

### replay-driver

* **source**: `replay`
* **expected event**: `workflow_dispatch`
* **description**: Tag-59 replay-driver re-dispatch for post-incident
  reconstruction. The replay-driver re-emits a historical envelope
  with the original `trigger_sequence_id` preserved, plus a fresh
  audit-marker-tag identifying the replay dispatch.
* **canonical actor**: `replay-driver-bot`.

## Per-envelope verdict logic

Per Tag-66 Stage 1 (trigger-event-schema-audit), each envelope is
classified:

* **green**: all required keys present, all shapes match.
* **yellow**: base keys present, ≥1 audit-only key missing (legacy
  Tag-62 envelope without Tag-66 overlay).
* **red**: base keys missing, or any shape malformed.

Stage 2 (marker-tag-catalog-conformance) then classifies the
`audit_marker_tag` against this catalog:

* **green**: tag pattern matches AND source recognised AND source's
  `expected event == workflow_dispatch`.
* **yellow**: tag + source recognised, but source's expected_event
  differs from `workflow_dispatch` (i.e., a `cron`-source tag emitted
  in a `workflow_dispatch` event — operationally legit for replay
  paths but flagged for review).
* **red**: tag pattern malformed or source not in catalog.

Stage 3 (cross-substrate-marker-reference) verifies each marker
class is referenced by ≥1 of the canonical downstream substrates
(this document, the pre-mortem notify-catalog, the backend alert
rules, or the alert-rule-to-mira-notify bridge). A class referenced
by zero substrates is an orphan-marker yellow; two or more orphans
is red.

## Cross-references

This catalog is itself one of the downstream substrates the Tag-66
verifier checks (it enumerates every marker class explicitly).
Removing or renaming a marker class here without updating the
catalog enumeration in
`tooling/ci/verify_watch_day_operator_trigger_audit_trail.py`
(constant `AUDIT_MARKER_CATALOG`) is a contract-drift the test suite
`tests/observability/test_watch_day_audit_trail_tag66.py` catches.

## Sandbox boundary

The Tag-66 verifier is **hermetic**: stdlib + python 3.11 only.
No GitHub-API call, no podman, no NATS emit, no Mira-Notify webhook
fire, no AlertManager call. Reads only on-disk text/JSON.

## Promotion-to-required-status-check

Per `feedback_branch_protection_check_names.md` the required status
check, once promoted to a branch-protection gate, is:

```
Stage 4 Aggregate Verdict (AUDIT-TRAIL-INTACT/DRIFT/DEFECT) / watch-day-operator-trigger-audit-trail-verify
```

Initial landing does NOT add the gate; promotion is a follow-up
after one green run on main.

— Noa Bergstroem (SRE), Tag-66 Marathon-Continuous-Mode
