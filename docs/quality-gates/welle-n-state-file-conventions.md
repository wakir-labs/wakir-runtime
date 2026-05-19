# Quality-Gate — Welle-N State-File Conventions (Pre-Cutover-T0 Pin)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) and Zone-M cross-check via Tomás (Engineering) |
| Status | Active — pre-Cutover-T0 (KW-25 Welle-3 solo) baseline pin |
| Phase | 3c (closing) — Phase-3-Marathon control-surface state-file substrate |
| Source | Tag-66 (#L0 KW-24 Per-Welle Acceptance + E2E-Smoke Schedule, PR #419) -> Tag-67 (this doc) |
| Date | 2026-05-19 (Tag-67 pre-Cutover-T0 baseline pin) |
| Companion (Tag-66 Schedule) | `docs/quality-gates/kw-24-welle-acceptance-schedule.md` (Tag-66 wave-cadence anchor, where applicable) |
| Companion (Verifier) | `tooling/ci/verify_welle_state_file_conventions.py` (Tag-67 hermetic conformance helper) |
| Companion (Conformance-Test-Suite) | `tests/ci/test_welle_state_file_conventions_tag67.py` (Tag-67, 17 tests) |
| Companion (Stub-State-Files) | `state/welle-1.json` .. `state/welle-7.json` (initial-state canonical pins) |
| Audit-Boundary | Zone N: this doc is QA-domain artefact (system-behaviour state-file schema). Henrik consumes the schema-table + cross-anchor catalog as Audit-Evidence-Index. Zone M: state-file schema is QA-owned; per-component writers stay engineering-owned (Tomás OTS, Noa SRE, Selin persona-engine). |

## 0. Contract scope

This document is the **canonical structural contract** for the
`state/welle-N-*.json` family of state-files that the Phase-3-Marathon
control-surface consumes. The family is referenced by **eight distinct
upstream readers** (per-welle hot-spot aggregators 3..7,
phase-3-complete-marker-state-machine, marathon-rollback-manifest,
welle-validation-workflow output) but had no canonical schema-anchor
prior to Tag-67. Tag-66's KW-24 acceptance-schedule (PR #419) surfaced
the gap: the Welle-3-downstream-block-cascade (Welle-4/5/7 pre-
conditional block on Welle-3 audit-trail-integrity red) consumes
`state/welle-3-audit-trail-integrity.json` shape that is only
documented inside Tomás' Tag-45 aggregator docstring.

The contract here **does not introduce new state-files**: every path
documented in §2-§5 already has a producing workflow or runtime
emitter on `main` (per the Tag-67 grep-inventory). What Tag-67 adds is:

1. A **schema-pin** per file (required-fields, allowed-values, time-iso
   format).
2. A **canonical initial-state** (the seven `state/welle-N.json` stub
   files) so that hermetic tests + sandbox-replay drills do not need
   to fabricate state per-run.
3. A **conformance helper** (`verify_welle_state_file_conventions.py`)
   that any state-file producer can shell-out to in CI for schema-pin
   enforcement.

The pin **freezes** the schema as of pre-Cutover-T0. KW-25 Welle-3
goes live with this schema. Any post-Cutover-T0 schema-change is an
ADR-class change (the seven downstream readers are then in-flight and
schema-drift becomes a Phase-3-Marathon control-surface risk).

This doc is **prescriptive of the schema-pin** but **descriptive of
the producer-set**: it does not redirect who emits which file. It
codifies the schema that producers already implicitly satisfy and
that consumers already implicitly expect.

## 1. Scope (pre-Cutover-T0 Pin)

Tag-67 is the last working-day before KW-25 Welle-3 (Mittwoch 2026-
05-20 -- the cutover-T0). The state-file substrate has been organically
built over Tag-40..Tag-66 (8 tags) by five separate spawn-streams:

| Producer-Stream | Anchor-Tag | State-Files Emitted |
|---|---|---|
| Per-Welle Hot-Spot Aggregators (Tomás) | Tag-45..Tag-52 | `state/welle-{3..7}-hot-spot-trend/<date>.json` |
| Welle-Validation-Workflow (Tomás) | Tag-44 | `state/welle-{3..7}-validation-last-verdict.json` |
| Welle-Specific Drift-Detectors (per-Welle owner) | Tag-45..Tag-50 | `state/welle-3-audit-trail-integrity.json`, `state/welle-4-persistence-drift.json`, `state/welle-5-fsm-phantom-detection.json`, `state/welle-6-subscribe-mode-live.json`, `state/welle-7-recovery-drill-live.json` |
| IIA-1130 Pre-Auditor-Decision Tracker (AR-Hand, Henrik-coordinated) | Tag-39..Tag-46 | `state/welle-{3..7}-pre-auditor-decision.json` |
| Sign-Off State-Machine (Tomás) | Tag-40 | `state/welle-{1..7}-sign-off.json` |

The pin is **scoped to schema-shape only**, not to value-allowed-sets
beyond what is already enforced by the consuming workflows. Specifically:

- **In scope:** required-fields, field-types, time-iso format,
  enum-value sets (status, drift-verdict), file-path-naming convention.
- **Out of scope:** value-thresholds (Tomás-owned per aggregator),
  red/yellow/green decision-rules (per-welle owner), live-data-source
  (producer-internal).
- **Out of scope:** the new top-level `state/welle-N.json` per-welle
  rollup stubs that Tag-67 introduces are pinned here as **shape-only
  initial-state**; their post-Cutover-T0 producer-wiring is left to a
  future tag (the stubs satisfy hermetic-test fixture-needs today).

The pin **explicitly preserves operator-hand boundaries**: live-VM
state-files (`*-live.json` suffix) remain operator-territory; this doc
pins the shape that the operator-emit-script must produce, not the
emit-script itself (ADR-0058 §Nachtrag).

## 2. Per-Welle State-File-Schema

For each Welle-N where N in 1..7, the canonical state-file family is:

### 2.1 Top-level rollup -- `state/welle-N.json` (Tag-67 stub-pinned)

This is the Tag-67-new per-Welle rollup stub-file. Pre-Cutover-T0
initial-state pins the shape. Post-Cutover-T0 wiring is an open item.

```json
{
  "welle_number": <int 1..7>,
  "schema_version": "tag-67-v1",
  "phase": "phase-3-marathon",
  "kw_cutover_anchor": "<KW-22..KW-27 string>",
  "cutover_iso": "<ISO-8601 timestamp or empty-string for pending>",
  "signoff_iso": "<ISO-8601 timestamp or empty-string for pending>",
  "status": "<pending | in-progress | signed-off | rolled-back>",
  "rollup_links": {
    "sign_off": "state/welle-N-sign-off.json",
    "validation_last_verdict": "state/welle-N-validation-last-verdict.json",
    "hot_spot_trend_dir": "state/welle-N-hot-spot-trend/",
    "pre_auditor_decision": "state/welle-N-pre-auditor-decision.json"
  },
  "audit_trail_anchor": "<OTS-anchor-hash placeholder or empty-string>"
}
```

**Schema rules** (Tag-67 conformance helper enforces these):

- `welle_number` must equal the N in the filename.
- `schema_version` must equal `"tag-67-v1"` (frozen for this pin).
- `phase` is the literal `"phase-3-marathon"` (legacy values rejected).
- `kw_cutover_anchor` must match `^KW-2[2-7]$`.
- `status` must be one of the four enum values exactly.
- `rollup_links.*` paths must all start with `state/welle-N-` and
  match the welle-number in the file.
- ISO-timestamps either empty-string or full ISO-8601 with timezone
  (regex `^$|^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$`).

### 2.2 Sign-off marker -- `state/welle-N-sign-off.json`

Mirrors the canonical `SignOffMarker` shape from
`tests/phase_3c/test_phase_3_final_regression.py` (Tomás Tag-40 anchor,
itself mirroring Reza Tag-40 Cross-Welle-Generalprobe):

```json
{
  "welle_number": <int 1..7>,
  "status": "<signed-off | rolled-back | pending>",
  "ac_1_5_green": <bool>,
  "ac_4_consensus_personas": ["<persona-slug>", ...],
  "cross_welle_drift_assert": "<green | caution | blocker>",
  "cutover_iso": "<ISO-8601 or empty>",
  "signoff_iso": "<ISO-8601 or empty>"
}
```

Five fields are mandatory for the marker to count toward the
Phase-3-COMPLETE trigger: `welle_number`, `status`, `ac_1_5_green`,
`ac_4_consensus_personas`, `cross_welle_drift_assert`. Time-fields
are optional structurally but mandatory for chronological-ordering
assertions in `test_p3m_marker_*` (Tag-40 cascade).

### 2.3 Validation last-verdict -- `state/welle-N-validation-last-verdict.json`

Emitted by the weekly per-welle validation workflow:

```json
{
  "welle_number": <int 1..7>,
  "verdict": "<green | yellow | red>",
  "verdict_iso": "<ISO-8601 timestamp>",
  "checks": [
    {"name": "<check-id>", "verdict": "<green | yellow | red>", "evidence_ref": "<workflow-run-url-or-empty>"}
  ],
  "schema_version": "tag-67-v1"
}
```

### 2.4 Hot-spot trend day-file -- `state/welle-N-hot-spot-trend/<YYYY-MM-DD>.json`

Emitted by per-welle hot-spot aggregator:

```json
{
  "welle_number": <int 3..7>,
  "date": "<YYYY-MM-DD>",
  "aggregator_verdict": "<CLEAR | CAUTION | BLOCK>",
  "checks": {"<check_name>": "<green | yellow | red>", ...},
  "schema_version": "tag-67-v1"
}
```

Wellen 1+2 have no hot-spot trend file (no aggregator wired; their
sign-off is single-day-driven). Wellen 3..7 each have an aggregator
landed by Tag-45..Tag-52.

### 2.5 Pre-Auditor-Decision -- `state/welle-N-pre-auditor-decision.json`

IIA-1130-Pre-Auditor-Decision tracking, AR-Hand-emitted:

```json
{
  "welle_number": <int 3..7>,
  "decision": "<designated | pending | not-required>",
  "pre_auditor_slug": "<string-or-empty>",
  "designation_iso": "<ISO-8601 or empty>",
  "rationale_doc": "<doc-path-or-empty>",
  "schema_version": "tag-67-v1"
}
```

Wellen 3 + 7 are the two where Henrik cannot self-sign-off (he is
the substrate-author for audit-stream-hash and recovery-workflow
respectively). For these two, `decision == "designated"` is required
pre-sign-off. Wellen 4/5/6: `decision` may be `"not-required"` by AR.

### 2.6 Welle-specific drift-detector -- per-Welle name

Each Welle has its own drift-detector state-file, with a Welle-local
schema:

- `state/welle-3-audit-trail-integrity.json` — `{integrity_verdict, hash_chain_ok, last_checked_iso, schema_version}`.
- `state/welle-4-persistence-drift.json` — `{drift_verdict, persistence_layer, drift_bytes, last_checked_iso, schema_version}`.
- `state/welle-5-fsm-phantom-detection.json` — `{phantom_verdict, fsm_state_count, phantom_states_count, last_checked_iso, schema_version}`.
- `state/welle-6-subscribe-mode-live.json` — `{mode_verdict, subscribe_count, last_checked_iso, schema_version}`. (Live, operator-emitted.)
- `state/welle-7-recovery-drill-live.json` — `{drill_verdict, last_drill_iso, recovery_seconds, schema_version}`. (Live, operator-emitted.)

The conformance helper enforces presence of `schema_version: "tag-67-v1"`
on all six; the welle-specific payload-fields stay welle-local.

## 3. Cross-Welle-Reference-Pattern

The state-files form a **directed reference graph**, not a partition.
Two reference-patterns are pinned here:

### 3.1 Welle-3 downstream-propagation pattern (Tomás Tag-45 anchor)

```
state/welle-3-audit-trail-integrity.json
        |  (verdict == red)
        v
[propagation flag]
   |  Welle-4 (state_backing)         pre_conditional_blocked
   |  Welle-5 (lifecycle_state_machine) pre_conditional_blocked
   |  Welle-7 (recovery_workflow)      pre_conditional_blocked
```

This is **data-only**: the propagation flag lives in
`state/welle-3-hot-spot-trend/<date>.json` (`propagation` field). The
actual blocking happens in the four downstream workflows that consume
it. Cross-Welle-Reference-Pattern enforced by:

- Welle-3 aggregator writes `propagation` field listing downstream
  wellen.
- Welle-{4,5,7} aggregators read this field and gate their own
  `aggregator_verdict` accordingly.

### 3.2 Per-Welle rollup-link pattern (Tag-67 new)

```
state/welle-N.json (Tag-67 rollup)
        |
        +--> sign_off                  -> state/welle-N-sign-off.json
        +--> validation_last_verdict   -> state/welle-N-validation-last-verdict.json
        +--> hot_spot_trend_dir        -> state/welle-N-hot-spot-trend/
        +--> pre_auditor_decision      -> state/welle-N-pre-auditor-decision.json
```

The Tag-67 stub-state-files (§7) pin these four references for each
Welle-N. Conformance helper enforces (a) the rollup-link paths exist as
string-fields, and (b) their string-values follow the canonical naming.

## 4. Welle-3-Sign-off-Status-File

Welle-3 (Mittwoch KW-25, 2026-05-20) is the first sign-off after Tag-67
pin. Its sign-off-status state-file gets special attention:

- **File:** `state/welle-3-sign-off.json` (schema §2.2).
- **Pre-Cutover-T0 initial-state** (Tag-67 stub):
  ```json
  {
    "welle_number": 3,
    "status": "pending",
    "ac_1_5_green": false,
    "ac_4_consensus_personas": [],
    "cross_welle_drift_assert": "green",
    "cutover_iso": "",
    "signoff_iso": ""
  }
  ```
- **Sign-off transition** (Cutover-T0 + N): producer-workflow updates
  `status` to `"signed-off"`, fills `cutover_iso` + `signoff_iso`,
  populates `ac_4_consensus_personas` with the consenting persona-set.
- **Pre-Auditor-binding:** Welle-3 requires
  `state/welle-3-pre-auditor-decision.json.decision == "designated"`
  before sign-off can flip to `"signed-off"`. The phase-3-complete-
  marker state-machine cross-checks this in
  `test_p3m_marker_blocked_when_we_1_to_we_4_welle_ende_incomplete`.

## 5. Welle-7-Final-Marathon-Status-File

Welle-7 (Mittwoch KW-27, 2026-06-03) is the last sign-off, gating the
Phase-3-COMPLETE marker:

- **File:** `state/welle-7-sign-off.json` (schema §2.2).
- **Cross-file dependency:** Welle-7 sign-off requires
  - `state/welle-3-audit-trail-integrity.json.integrity_verdict ==
    "green"` (downstream-propagation requirement, §3.1).
  - `state/welle-7-pre-auditor-decision.json.decision == "designated"`
    (Henrik-cannot-self-sign-off; he authored the recovery-workflow).
  - `state/welle-7-recovery-drill-live.json.drill_verdict == "green"`
    within the previous 72h (live operator-emit constraint).
- **Phase-3-COMPLETE trigger:** when all seven `state/welle-N-sign-
  off.json` files report `status == "signed-off"` AND AC-1..AC-5 green
  AND welle-ende-gates green, the phase-3-complete-marker-workflow
  fires (Tomás Tag-40 anchor).
- **Marathon-final pin:** `state/welle-7.json` (Tag-67 rollup) carries
  the marathon-final `audit_trail_anchor` field — empty-string at
  Tag-67 pin, populated by the OTS-anchor-hash after the Phase-3-
  COMPLETE marker fires.

## 6. Audit-Trail-Schema (Cross-Anchor zu Tomás+Noa-Tag-66)

Cross-anchors to operational substrate landed by Tag-66:

### 6.1 OTS anchor cross-anchor (Tomás)

The `audit_trail_anchor` field on each `state/welle-N.json` is the OTS-
hash of the per-Welle sign-off-record-OTS-bundle. Pre-Cutover-T0 the
field is empty-string by design; the OTS-anchor is emitted by Tomás'
Tag-59 `OTS-Pre-Anchor Manifest-Hash Activation-Probe` (PR #380) once
the per-Welle sign-off-record is finalized.

The schema-pin here ensures the field-name is `audit_trail_anchor`
(not `ots_anchor` or `manifest_hash`) so that the Tomás anchor-writer
emits to the schema-pinned path. The conformance helper accepts both
empty-string and a full OTS-anchor-hash (regex `^$|^[0-9a-f]{64}$`).

### 6.2 SRE notify-event cross-anchor (Noa)

Each `state/welle-N-validation-last-verdict.json` is consumed by
Noa's Tag-59 `Watch-Day-Practice-Run hermetic Dry-Run-Replay workflow`
(PR #377). The `verdict_iso` field is the chronological anchor for
the Noa `notify-events` feed; the `verdict` field is the
green/yellow/red flag that drives the Noa `marathon-rollback-ar-notify`
build (Tag-50+ aggregator).

Schema-pin therefore freezes `verdict_iso` as ISO-8601 with timezone
(not Unix-epoch, not date-only) and `verdict` as the three-value enum
matching Noa's notify-event taxonomy.

### 6.3 Cross-anchor invariants

- Every state-file MUST carry `schema_version: "tag-67-v1"` (pre-
  Cutover-T0 pin) so that post-pin schema-evolution can be detected
  by string-equality.
- Every ISO-timestamp field MUST include a timezone marker (`Z` or
  `+/-HH:MM`); naive timestamps are rejected by the conformance helper.

## 7. Stub-Files initial-Pinned

Tag-67 pins seven initial-state stub-files at `state/welle-{1..7}.json`.
Their function:

1. **Hermetic-test fixture availability:** the Tag-67 conformance test-
   suite + future per-welle hermetic tests can read a stable starting
   state without fabricating one per-test.
2. **Sandbox-replay drill anchor:** the cutover-Mittwoch drill-replays
   (Kai Tag-66 Final-Recipe Konsolidat, PR #422) start from the
   stub-state and progress through to `status == "signed-off"`.
3. **Schema-anchor for producer-writers:** post-Cutover-T0, when a
   producer-workflow updates a Welle's rollup-state, it overwrites
   the stub. The stub is the schema-anchor for the overwrite.

All seven stubs are committed in the same Tag-67 PR. Their initial
values:

| File | `status` | `cutover_iso` | `signoff_iso` | `audit_trail_anchor` |
|---|---|---|---|---|
| `welle-1.json` | `pending` | `""` | `""` | `""` |
| `welle-2.json` | `pending` | `""` | `""` | `""` |
| `welle-3.json` | `pending` | `""` | `""` | `""` |
| `welle-4.json` | `pending` | `""` | `""` | `""` |
| `welle-5.json` | `pending` | `""` | `""` | `""` |
| `welle-6.json` | `pending` | `""` | `""` | `""` |
| `welle-7.json` | `pending` | `""` | `""` | `""` |

`kw_cutover_anchor` is filled per-Welle per ADR-0066: Welle-1 KW-22,
Welle-2 KW-23, Welle-3 KW-25, Welle-4 KW-25, Welle-5 KW-25, Welle-6
KW-26, Welle-7 KW-27.

## 8. Sandbox-Boundary

This doc, the helper, and the test-suite are **sandbox-hermetic**:

- The verifier (`verify_welle_state_file_conventions.py`) only reads
  files, never executes network calls, never writes to `state/`.
- The conformance test-suite ships with its own in-memory fixtures
  (mirroring the canonical schema) and never depends on a live state-
  file producer.
- The Tag-67 stubs (`state/welle-{1..7}.json`) are committed to the
  repo as static fixtures, not generated.

**Operator-Hand boundary:**

- Two state-files (`state/welle-6-subscribe-mode-live.json` and
  `state/welle-7-recovery-drill-live.json`) are **operator-emitted**
  on the live-VM. The conformance helper enforces only the schema-
  shape; it does not enforce existence (the live-VM emits these on
  drill-day, the sandbox does not).
- The OTS-anchor field `audit_trail_anchor` is **OTS-writer-emitted**
  on the host (post-Mira-Sandbox-vs-Host-Operations-Trennung). The
  conformance helper accepts empty-string-or-OTS-anchor; it does not
  itself attempt to verify the anchor against the OTS-calendar
  (Henrik's audit-trail-verification domain, Zone N).
- The pre-Auditor-decision field is **AR-Hand-emitted** (via
  Henrik-coordinated workflow). Sandbox emits the schema-pinned stub
  shape only.

This boundary is consistent with ADR-0058 §Nachtrag (live-VM
operator-hand) and Mira's Sandbox-vs-Host-Operations Trennung
direktive (no host-podman-socket-access from claude-dev).

— Amara (Tag-67, 2026-05-19, pre-Cutover-T0)
