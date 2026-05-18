<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Mira-Notify Runbook (Tag-46)

**Owner:** Noa Bergstroem (SRE)
**Companion artefacts:**
- `scripts/observability/mira-notify-emitter.py`
- `scripts/observability/mira-notify-receiver.py`
- `docs/observability/pre-mortem-failure-mode-notify-catalog.md`
  (Tag-45 catalog, PR #292)
- `dashboards/phase-3-marathon-alerts.yaml`

**Status:** proposed (pending Henrik catalog cross-review + Kai
Zone-H deployment substrate review).

---

## 1. Scope

This runbook explains how the Mira-Notify substance (emitter +
receiver) materialises catalogued alert-fires into the Mira-Hand
inbox so the operator can act without polling Grafana or PagerDuty
during Cutover-Tag.

It does **not** cover:

* PagerDuty webhook fan-out (deferred to Tag-47 candidate;
  requires external secrets the Mira-Sandbox cannot resolve).
* ntfy push-channel fan-out (same reason).
* Alert-rule authoring; see `phase-3-marathon-alerts.yaml`.

## 2. Data flow

```
+---------------------------+        +----------------------------+
| Internal tool (tracker,   |        | Operator-Hand (ad-hoc       |
| aggregator, ...)          |        | python mira-notify-emitter) |
+-------------+-------------+        +-------------+--------------+
              |                                    |
              | make_event() / emit_notify()       | CLI `emit`
              v                                    v
        +-----+------------------------------------+-----+
        |          mira-notify-emitter.py (lib + CLI)    |
        +------------------------+-----------------------+
                                 |
                                 | append JSONL
                                 v
                  infra/notify-log.jsonl  (append-only)
                                 |
                                 | tail / file / stdin
                                 v
        +------------------------+-----------------------+
        |         mira-notify-receiver.py (CLI)          |
        +------------------------+-----------------------+
                                 |
                                 | one .md per event
                                 v
        agents-workspaces/mira/inbox/notify-<sev>-<ts>-<id>.md
```

## 3. Severity contract

| Severity  | Filename prefix    | Required fields                  | Side effects (Tag-46 scope) |
|-----------|--------------------|----------------------------------|----------------------------|
| `page`    | `notify-page-`     | `alert_name`, `summary`, `runbook_url`, `fired_at_utc` | Inbox markdown (high prio) |
| `warning` | `notify-warn-`     | `alert_name`, `summary`, `fired_at_utc`               | Inbox markdown (normal)    |
| `info`    | `notify-info-`     | `alert_name`, `summary`, `fired_at_utc`               | Inbox markdown (low)       |

The receiver embeds the severity in the filename so Mira-Hand can
glob-prioritise (`inbox/notify-page-*.md` first).

## 4. Emitter (producer-side)

### 4.1 Library use (preferred when calling from Python)

```python
from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location(
    "mira_notify_emitter",
    "scripts/observability/mira-notify-emitter.py",
)
emitter = module_from_spec(spec); spec.loader.exec_module(emitter)

ev = emitter.make_event(
    alert_name="WakirPhase3FailureModeA1CrossModulDriftPerWelle",
    severity="page",
    summary="A1 drift detected: welle-3 -> welle-4 count=2",
    runbook_url="https://wakir-labs.example/runbooks/failure-mode-a1",
    failure_mode_id="A1",
    labels={"source_welle": "3", "target_welle": "4"},
    source="aggregator-failure-rate-tracker",
)
emitter.emit_notify(ev, log_path=Path("infra/notify-log.jsonl"))
```

`make_event` raises `ValueError` on validation failure. The
emitter does **not** swallow errors silently; callers must handle
them so a broken catalog entry surfaces in the originating tool's
exit-code, not in a missing inbox entry.

### 4.2 CLI use (one-shot from shell)

```bash
python3 scripts/observability/mira-notify-emitter.py emit \
    --alert-name WakirPhase3FailureModeC1HourlyTickSilence \
    --severity page \
    --summary "Hourly-Tick silent for >65 min on host-A" \
    --runbook https://wakir-labs.example/runbooks/failure-mode-c1 \
    --failure-mode-id C1 \
    --labels host=host-a \
    --source operator-hand
```

Default log path is `infra/notify-log.jsonl`. Override via
`--log-path`. Add `--stdout` to also echo the JSONL line on stdout
(useful for piping into the receiver in `--mode=stdin`).

### 4.3 Validate a JSONL stream before commit

```bash
python3 scripts/observability/mira-notify-emitter.py validate \
    infra/notify-log.jsonl
```

Non-zero exit lists each malformed line.

## 5. Receiver (consumer-side)

### 5.1 One-shot file mode (default)

```bash
python3 scripts/observability/mira-notify-receiver.py \
    --mode=file \
    --input infra/notify-log.jsonl \
    --inbox agents-workspaces/mira/inbox
```

Reads the entire file once, materialises each new event, and exits.
Idempotent: a second run on the same file deduplicates via
`inbox/.notify-event-ids.txt` and materialises nothing.

### 5.2 Tail mode (long-running)

```bash
python3 scripts/observability/mira-notify-receiver.py \
    --mode=tail \
    --input infra/notify-log.jsonl \
    --inbox agents-workspaces/mira/inbox \
    --max-idle-seconds 3600
```

Tails the JSONL file from a persisted byte-offset
(`<input>.receiver-offset`). The `--max-idle-seconds` bound makes
this safe to run from cron without leaking processes; the next
cron tick will pick up where this one left off.

### 5.3 Pipe mode (stdin)

```bash
python3 scripts/observability/mira-notify-emitter.py emit \
    --alert-name X --severity info --summary s --stdout \
    | python3 scripts/observability/mira-notify-receiver.py \
        --mode=stdin --inbox agents-workspaces/mira/inbox
```

Useful for inline ad-hoc emissions during incidents when you do not
want to touch the append log.

## 6. Dedupe semantics

`event_id` is derived deterministically from
`sha256(alert_name|fired_at_utc|sorted-labels)[:16]`. Two emitters
that observe the same alert-fire at the same Prometheus scrape
boundary will produce the **same** event_id and the receiver will
materialise only one inbox entry.

`fired_at_utc` resolution is 1 second; an alert that fires twice
within the same second with identical labels deduplicates. That is
acceptable for catalogued alerts which all have `for: >=60s`
windows.

To force a distinct event_id (e.g. for incident-replay), supply
`--fired-at-utc` explicitly with a different value or pass a custom
`event_id` via the library API.

## 7. Dead-letter handling

Events that fail JSON parse, `NotifyEvent` construction, or
`validate_event` land in `inbox/.notify-dead-letter.jsonl` with an
extra `_error` field. The receiver exit-code is `1` for the run
that produced any dead-letters, so a cron wrapper can alarm on
non-zero exit.

Recovery procedure:

1. Inspect `inbox/.notify-dead-letter.jsonl`.
2. Identify upstream tool from the line content (or `_raw` field).
3. Fix the emitter side; if unfixable, hand-write the equivalent
   Mira-Hand-inbox markdown file.
4. Truncate the dead-letter file once entries are processed:
   `: > inbox/.notify-dead-letter.jsonl`.

## 8. Hermetic test surface

44 hermetic tests cover the emitter + receiver:

* `tests/observability/test_mira_notify_emitter.py` (21 tests):
  pure-function core, serialisation, CLI emit/validate.
* `tests/observability/test_mira_notify_receiver.py` (23 tests):
  parser, markdown render, run_intake dedupe/dead-letter logic,
  CLI file/tail/stdin modes.

Run:

```bash
python3 -m pytest tests/observability/test_mira_notify_emitter.py \
                   tests/observability/test_mira_notify_receiver.py -v
```

## 9. Dead-letter queue (Tag-51 substance)

The receiver writes one record per failed intake to
`<inbox>/.notify-dead-letter.jsonl` with envelope
`{"_error": "...", "_raw": "..."}`.  Until Tag-51 this file was
write-only; an event that failed validation simply vanished from
Mira-Hand's perspective.

`scripts/observability/mira-notify-dlq.py` (Tag-51) closes the loop:

* **`inspect`** (read-only): summarise total / by-category / by-alert-name
  / earliest+latest fired_at_utc.  Output JSON or Markdown.
* **`replay`** (default dry-run; `--apply` to mutate): re-process each
  record after optional patches (`--set-schema-version`,
  `--fill-missing-fired-at-utc`, `--normalise-severity`,
  `--default-severity`).  On success the record is written to the
  inbox + dedupe-set and **removed** from the dead-letter file; on
  failure the record stays in place.
* **`prune`** (default dry-run; `--apply` to mutate): drop records
  whose `event_id` is already in the inbox dedupe-set (i.e. the
  producer re-emitted the corrected event in a later run).

The companion workflow `mira-notify-dlq-daily.yml` runs `inspect` on
a daily schedule at 07:30 UTC and exposes the markdown report as the
Job-Summary; `replay`/`prune` are dispatch-only so the scheduled run
remains read-only.

### Recipe — recover a dead-lettered alarm batch

1. `python3 scripts/observability/mira-notify-dlq.py inspect --format markdown`
2. Identify the dominant category in the histogram (e.g.
   `schema_version_mismatch` after a producer rolling-upgrade).
3. Run the matching patch in dry-run:
   `python3 scripts/observability/mira-notify-dlq.py replay --set-schema-version --format markdown`
4. When the dry-run shows `replayed: N`, `still_failed: 0`, apply:
   `python3 scripts/observability/mira-notify-dlq.py replay --apply --set-schema-version --format markdown`
5. Confirm the dead-letter file is empty:
   `python3 scripts/observability/mira-notify-dlq.py inspect --format json | jq '.total'`

### Operational guardrails

* Replay-`--apply` runs MUST be outside the receiver's `--mode=tail`
  window; the dead-letter file is whole-file rewritten and the
  receiver's offset-file is not coupled to this rewrite.  A
  receiver running in `--mode=file`/`stdin` is safe.
* Patches are deliberately restricted to low-risk repairs.  Anything
  more invasive (synthesising a missing `alert_name`, for instance)
  is not in scope; fix the producer instead.
* Exit-code 1 from `replay --apply` means at least one record could
  not be recovered with the supplied patches.  The workflow surfaces
  this as a red Job-Summary.

## 10. Out-of-scope (Tag-52+)

* PagerDuty webhook fan-out (catalogued severity=page also needs
  PagerDuty; today only the Mira-Hand inbox side is implemented).
* ntfy push-channel fan-out.
* Receiver as a long-running container (Kai Zone-H deployment).
* Receiver-side Activity-Log append (currently Mira-Hand reads
  inbox markdown and appends as part of normal triage).

## 11. Cross-Review-Zones

* **Zone H (SRE x Kai):** Container substrate for a long-running
  receiver is Kai's territory; the Tag-46 substance is invocation-
  bound (cron / inline). When Kai turns the receiver into a daemon,
  the `--mode=tail` semantics + offset-file contract here are the
  invariant.
* **Zone I (SRE x Tomas):** WAT-pipeline alerts route through the
  same emitter once Tomas's WAT-Anker SLOs land. Field schema is
  stable from Tag-46; only the catalog gets new entries.
* **Henrik (Audit):** Catalog cross-review (Tag-45 PR #292) is the
  pre-condition for treating page-severity emissions as actionable
  for the AR-Ticker.

---

_Maintained by Noa Bergstroem (SRE). Bring catalog updates first;
adjust this runbook only when the data flow changes._
