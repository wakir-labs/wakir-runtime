<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Persona-Engine — State-File Producer-Wiring-Plan (post-Cutover-T0)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), with Zone-K cross-anchor at Tomás (OTS / WAT-Hash) and Zone-J cross-anchor at Kai (Container-Bridge) |
| Status | Active — plan-doc only (Tag-68). Implementation deferred to Tag-69+. |
| Phase | 3c (closing) — Phase-3-Marathon control-surface producer-wiring substrate |
| Source | Tag-67 Amara Welle-N State-File Conventions Pin (PR #429) → Tag-68 (this doc) |
| Date | 2026-05-19 (Tag-68 pre-Cutover-T0 last-working-day pre-KW-25-Welle-3) |
| Companion (Schema-Pin) | `docs/quality-gates/welle-n-state-file-conventions.md` (Amara Tag-67) |
| Companion (Verifier) | `tooling/ci/verify_welle_state_file_conventions.py` (Amara Tag-67) |
| Companion (Helper Stub) | `tooling/ci/render_engine_state_file_stub.py` (Tag-68, audit-only) |
| Companion (Test-Suite) | `wirelang/tests/persona_engine/test_state_file_producer_plan_tag68.py` (Tag-68, ≥12 tests) |
| Audit-Boundary | Zone-N (Henrik): plan-doc is reviewable as Audit-Evidence-Index. Zone-K (Tomás): OTS-anchor field semantics. Zone-J (Kai): container-side write-mount path. Zone-M (Aisha): governance grain over persona definitions remains untouched. |

## §1 Scope (post-Cutover-T0 Producer-Wiring)

Tag-67 (PR #429) pinned the **schema-shape** of the seven new
`state/welle-N.json` top-level rollup-files plus the existing
`state/welle-N-{sign-off,validation-last-verdict,pre-auditor-
decision}.json` family and the `state/welle-N-hot-spot-trend/`
directory. The pin landed seven stub-files (`state/welle-1.json`
through `state/welle-7.json`) in canonical `status: "pending"`
initial-state with empty `cutover_iso`, `signoff_iso`, and
`audit_trail_anchor` fields.

Tag-67's pin was **descriptive of the producer-set**: it did not
redirect who writes which file. Tag-68 (this doc) is the
**Engine-Side Producer-Wiring-Plan**: the prescriptive map of
**which Persona-Engine code-path must write which field of which
state-file at which lifecycle-event** to satisfy the Tag-67 pin
from Cutover-T0 (KW-25 Welle-3, Mittwoch 2026-05-20) onward.

In scope for Tag-68:

- The plan-doc itself (this file, six sections).
- A stdlib-only helper-stub
  (`tooling/ci/render_engine_state_file_stub.py`) that the
  Tag-69+ wiring will call to **render** a canonical-initial-state
  rollup-file from a `(welle_number, kw_anchor)` pair. The stub is
  audit-only at Tag-68: it produces strings but is not yet wired
  into a producer-workflow.
- The Tag-68 test-suite which pins the plan-doc structure +
  helper-stub render-contract.

Out of scope for Tag-68 (deferred to Tag-69+ per the
Tag-68-roadmap in §5):

- Actual engine-side write-call insertion into `engine.py`,
  `engine_async.py`, despawn-clean handlers, lifecycle-state-
  machine transitions.
- Workflow-side write-call insertion into the per-Welle sign-off
  workflows.
- OTS-anchor backfill (the `audit_trail_anchor` field stays empty-
  string until Tomás' Tag-59 OTS-Pre-Anchor-Manifest-Hash-
  Activation-Probe — PR #380 — fires post-Phase-3-COMPLETE).
- Operator-emit-script wiring for `*-live.json` state-files (Kai-
  domain, Zone-J).
- Schema-change to the `state/welle-N.json` envelope (Tag-67 pin
  frozen; any schema-change is ADR-class post-Cutover-T0).

This is a **doc-form-only** Tag-68 deliverable. No engine code is
touched. No workflow is touched. The plan is reviewable by Tomás
(Zone-K), Kai (Zone-J), Aisha (Zone-M), Henrik (Zone-N) before
Tag-69+ implementation begins.

## §2 Per-Welle Engine-Side-Producer-Trigger

For each Welle-N where N in 1..7, the rollup-file
`state/welle-N.json` has six writable fields beyond the frozen-
literal fields:

- `cutover_iso` — ISO-8601 timestamp of the Cutover-T0 event.
- `signoff_iso` — ISO-8601 timestamp of the sign-off event.
- `status` — enum `pending | in-progress | signed-off |
  rolled-back`.
- `audit_trail_anchor` — OTS-anchor-hash placeholder
  (string or empty).
- `rollup_links.*` — frozen reference-paths (no engine writes
  here post-Tag-67-pin).
- `welle_number`, `schema_version`, `phase`, `kw_cutover_anchor` —
  frozen literals.

The engine-side producer-trigger map is:

### §2.1 Trigger: `Welle-N-Cutover-T0-Event-Received`

**Engine code-path:** lifecycle-state-machine transition
`welle:pending -> welle:in-progress` triggered by the
per-Welle-validation workflow run-completion event (Tomás
Tag-44 substrate). The Cutover-T0 event is the moment the
per-Welle test-pyramide is launched.

**Writer:** Persona-Engine async-event-handler
(`engine_async.py::handle_welle_cutover_event`, Tag-69+ insertion
point). Reads the current `state/welle-N.json`, sets
`status = "in-progress"`, sets `cutover_iso` to the event-iso
(from the workflow envelope), writes back atomically (write-tmp
+ rename).

**Idempotency:** the handler is a no-op if
`status != "pending"`. This protects against double-fire on
retried workflow events.

**Audit-trail:** the handler emits an audit-record to the
bridge-audit-writer (`bridge_audit_writer.py`, Tag-48 substrate).
The record references the welle-N + the new status + the
cutover_iso.

### §2.2 Trigger: `Welle-N-Sign-Off-Event-Received`

**Engine code-path:** lifecycle-state-machine transition
`welle:in-progress -> welle:signed-off`. Triggered by the
sign-off-state-machine emission (Tomás Tag-40 substrate) once the
five mandatory sign-off-marker fields are green
(`ac_1_5_green=true`, `ac_4_consensus_personas` non-empty,
`cross_welle_drift_assert == "green"`, plus the welle-specific
drift-detector verdict green per §2.6 of the schema-pin).

**Writer:** Persona-Engine sync-event-handler
(`engine.py::handle_welle_sign_off_event`, Tag-69+ insertion
point). Reads the current `state/welle-N.json`, sets
`status = "signed-off"`, sets `signoff_iso` to the event-iso
(from the sign-off-marker envelope), writes back atomically.

**Pre-condition guard:** the handler refuses to write if
- `status != "in-progress"` (out-of-order transition rejected), OR
- the companion `state/welle-N-sign-off.json` does not parse, OR
- the companion sign-off-file's `status != "signed-off"` (the
  sign-off-marker must be present before the rollup-file flips).

**Wellen 3 + 7 extra guard:** for N in {3, 7}, the handler
additionally requires `state/welle-N-pre-auditor-decision.json.
decision == "designated"` (Henrik-cannot-self-sign-off
constraint per Schema-Pin §2.5 / §5).

**Audit-trail:** emits two records to the bridge-audit-writer:
the rollup-file-write itself, and a marker-record using the
Tag-67 shared `audit_trail_marker_constants` module (Tomás PR
#430).

### §2.3 Trigger: `Welle-N-Rollback-Event-Received`

**Engine code-path:** lifecycle-state-machine transition
`{welle:in-progress | welle:signed-off} -> welle:rolled-back`.
Triggered by the marathon-rollback-manifest emission (Tomás
Tag-43 substrate) when the rollback-verdict for the Welle is
`ROLLBACK-REQUIRED`.

**Writer:** Persona-Engine async-event-handler
(`engine_async.py::handle_welle_rollback_event`, Tag-69+
insertion point). Sets `status = "rolled-back"`. Does NOT clear
`cutover_iso` (historical record preserved). Does NOT clear
`signoff_iso` if it was previously set (the rollback is recorded
as a delta-event, not a state-erasure).

**Audit-trail:** emits a rollback-record to the bridge-audit-
writer carrying the prior `status` value and the rollback-source
manifest reference.

### §2.4 Trigger: `Phase-3-COMPLETE-Marker-Fired`

**Engine code-path:** the phase-3-complete-marker-workflow
(Tomás Tag-40 substrate) fires once all seven
`state/welle-N-sign-off.json` files report `status ==
"signed-off"` AND AC-1..AC-5 green AND welle-ende-gates green.
This triggers the OTS-anchor backfill: the
`audit_trail_anchor` field on each of the seven
`state/welle-N.json` rollup-files is populated with the
OTS-hash of the per-Welle sign-off-record-OTS-bundle.

**Writer:** Persona-Engine batch-writer
(`engine.py::backfill_audit_trail_anchors`, Tag-69+ insertion
point). Iterates Welle-1..7, fetches the OTS-anchor-hash from
Tomás' Tag-59 OTS-Pre-Anchor-Manifest-Hash-Activation-Probe
output (PR #380, envelope read via stdlib JSON, no live OTS
call), writes the hash into the `audit_trail_anchor` field.

**Pre-condition guard:** the batch-writer requires
- all seven rollup-files at `status == "signed-off"`,
- the OTS-anchor-bundle envelope to exist and parse,
- the bundle to carry one anchor-hash per Welle.

The batch-writer is a **post-Phase-3-COMPLETE** action, not a
hot-path action. It runs once and is idempotent thereafter (a
populated `audit_trail_anchor` is a no-op).

**Audit-trail:** emits a Phase-3-COMPLETE-batch-record to the
bridge-audit-writer carrying the seven anchor-hashes and the
batch-completion-iso.

### §2.5 Producer-Trigger-Summary-Table

| Trigger | Writer code-path | Fields written | Status-transition | Tag-69+ insertion |
|---|---|---|---|---|
| §2.1 Cutover-T0-Event | `engine_async.py` | `status`, `cutover_iso` | pending → in-progress | Tag-69 |
| §2.2 Sign-Off-Event | `engine.py` | `status`, `signoff_iso` | in-progress → signed-off | Tag-69 |
| §2.3 Rollback-Event | `engine_async.py` | `status` | any → rolled-back | Tag-70 |
| §2.4 Phase-3-COMPLETE Backfill | `engine.py` | `audit_trail_anchor` | (no transition) | Tag-71+ |

## §3 State-Transitions pending → in-progress → signed-off

The `status` field of `state/welle-N.json` follows a strict
four-state lifecycle. The transition-graph (formal):

```
                Cutover-T0-Event
   pending  ─────────────────────────►  in-progress
      │                                       │
      │                                       │ Sign-Off-Event
      │                                       │ (with pre-auditor
      │                                       │  guard for N in
      │                                       │  {3, 7})
      │                                       ▼
      │                                signed-off
      │                                       │
      │ Rollback-Event                        │ Rollback-Event
      │ (rare; pre-cutover                    │
      │  rollback)                            ▼
      └────────────────────────────►  rolled-back
```

### §3.1 Allowed transitions

The lifecycle-state-machine permits exactly these transitions:

- `pending -> in-progress` (Cutover-T0-Event, §2.1)
- `pending -> rolled-back` (pre-cutover-rollback, rare)
- `in-progress -> signed-off` (Sign-Off-Event, §2.2)
- `in-progress -> rolled-back` (Rollback-Event, §2.3)
- `signed-off -> rolled-back` (post-sign-off-rollback, §2.3)

### §3.2 Forbidden transitions

The lifecycle-state-machine **rejects** these transitions with a
defensive guard:

- `signed-off -> in-progress` (no un-sign-off; rollback only)
- `signed-off -> pending` (no state-erasure)
- `rolled-back -> *` (rollback is terminal at the rollup-file
  level; a re-attempt of the Welle is a new sub-tag, not a
  state-machine reset)
- `in-progress -> pending` (no demotion)
- Any self-transition (`X -> X`) is a no-op (idempotency
  protection).

### §3.3 Cross-Welle ordering invariants

The state-machine is **per-Welle local**: it does not enforce
cross-Welle ordering. The phase-3-complete-marker-workflow
(Tomás Tag-40) is the cross-Welle ordering authority. The
engine-side producer-wiring is **single-Welle scope** by design,
which keeps the writer-handlers stateless across Wellen and
allows concurrent Welle-N + Welle-M state-file writes (the
filesystem rename-atomicity guarantee is per-file).

### §3.4 Time-field invariants

- `cutover_iso` is set exactly once (on first transition into
  `in-progress`). Subsequent rollback does not clear it.
- `signoff_iso` is set exactly once (on first transition into
  `signed-off`). Subsequent rollback does not clear it.
- `cutover_iso <= signoff_iso` must hold whenever both are
  non-empty (chronological-ordering invariant). The writer
  enforces this; a violation is a hard refusal-to-write.
- Both fields use the ISO-8601 format defined by the schema-pin:
  `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$`.

## §4 Cross-Anchor zu Amara-Tag-67-Schema

This plan-doc is **prescriptive of the writer-set** but
**descriptive of the schema**: every field this plan writes is
already pinned by Amara's Tag-67 schema-pin. The plan does not
introduce a single new schema-field. Every writer-path here is
covered by the Tag-67 verifier
(`tooling/ci/verify_welle_state_file_conventions.py --rollup`).

### §4.1 Field-by-field schema-anchor

| Field | Tag-67 schema-pin reference | Tag-68 writer (§2 ref) |
|---|---|---|
| `welle_number` | §2.1 frozen literal | not written by engine (Tag-67 stub-init) |
| `schema_version` | §2.1 frozen literal (`"tag-67-v1"`) | not written by engine |
| `phase` | §2.1 frozen literal (`"phase-3-marathon"`) | not written by engine |
| `kw_cutover_anchor` | §2.1 frozen literal | not written by engine |
| `cutover_iso` | §2.1 ISO-8601 or empty | §2.1 writer |
| `signoff_iso` | §2.1 ISO-8601 or empty | §2.2 writer |
| `status` | §2.1 four-enum | §2.1 / §2.2 / §2.3 writers |
| `rollup_links.*` | §2.1 / §3.2 reference-graph | not written by engine |
| `audit_trail_anchor` | §2.1 OTS-hash placeholder | §2.4 writer |

### §4.2 Verifier-shellout contract

The Tag-69+ engine-side writers will shellout to
`tooling/ci/verify_welle_state_file_conventions.py --rollup
state/welle-N.json` **after every write** to enforce the Tag-67
schema-pin at write-time (write → verify → audit-emit, atomic at
the rename step). Verifier exit-code 0 is required; exit-code 1
is a hard-refusal-and-rollback-the-write (restore from
write-tmp + abort).

### §4.3 Schema-change discipline

Any post-Cutover-T0 schema-change is **ADR-class** per the
Tag-67 pin (§0). The Tag-68 plan-doc does not propose any
schema-change; it is purely a writer-wiring plan against the
frozen schema. If a Tag-69+ implementation surfaces a
schema-gap, the response is an ADR vorlage (via Mira / Priya),
not a unilateral schema-extension.

## §5 Tag-69+-Implementation-Roadmap (Stub-only Tag-68)

The Tag-68 plan-doc + helper-stub are **doc-form-only**. No
engine code is touched in this PR. The implementation-rollout
follows this roadmap:

### §5.1 Tag-69 — Cutover-T0 + Sign-Off writers

- Insert §2.1 writer (`handle_welle_cutover_event`) into
  `engine_async.py`. Test-coverage: pending → in-progress
  transition + idempotency + invalid-status-reject.
- Insert §2.2 writer (`handle_welle_sign_off_event`) into
  `engine.py`. Test-coverage: in-progress → signed-off
  transition + pre-condition-guard (sign-off-file present and
  green) + Wellen 3/7 extra-guard (pre-auditor designated).
- Verifier-shellout integration. Test-coverage: post-write
  verifier exit-0 and exit-1 handling.
- Bridge-audit-writer record-emit. Test-coverage: cross-lang
  parity with the Tag-48 substrate.

### §5.2 Tag-70 — Rollback writer

- Insert §2.3 writer (`handle_welle_rollback_event`) into
  `engine_async.py`. Test-coverage: in-progress → rolled-back
  and signed-off → rolled-back transitions + cutover_iso /
  signoff_iso preservation + audit-record-emit.

### §5.3 Tag-71+ — Phase-3-COMPLETE audit-trail-anchor backfill

- Insert §2.4 batch-writer (`backfill_audit_trail_anchors`)
  into `engine.py`. Test-coverage: all-seven-rollup pre-
  condition + OTS-anchor-bundle envelope parse + idempotent
  re-run.
- This is the **last** Tag-68-plan deliverable. It cannot
  fire until Phase-3-COMPLETE marker has fired, which in turn
  requires Welle-7 signed-off in KW-27 (2026-06-03).

### §5.4 Cross-Welle implementation-ordering

- Tag-69 is the **Cutover-T0 hot-path**: KW-25 Welle-3
  Mittwoch 2026-05-20 is the first live trigger. The Tag-69
  PR **must land by Tag-68-end-of-day** to be live for the
  Welle-3 cutover. If it slips, the Welle-3 cutover proceeds
  with the Tag-67 stub-state (operator-hand fills the fields
  manually post-cutover; the Tag-69 writer back-fills on
  catch-up).
- Tag-70 rollback-writer can land between Welle-3 and Welle-4
  (KW-25/KW-26 gap).
- Tag-71+ batch-writer can land any time before Welle-7
  signed-off (KW-27).

### §5.5 Cross-Review gates per Tag-69+ PR

Tag-69 (Cutover-T0 + Sign-Off writers) requires:

- Zone-K cross-review by Tomás (the writer reads from his
  Tag-44 validation-workflow envelope + emits to his Tag-48
  bridge-audit-writer + Tag-40 sign-off-state-machine).
- Zone-N cross-review by Henrik (the writer touches the
  audit-trail substrate that the IIA-1130 pre-auditor-
  decision tracker depends on).
- Aisha protocols Konsens-Zeitpunkt per ADR-0043
  Cross-Review-Zonen.

Tag-70 (Rollback writer) requires:

- Zone-K cross-review by Tomás (reads from his Tag-43
  marathon-rollback-manifest substrate).

Tag-71+ (Phase-3-COMPLETE batch-writer) requires:

- Zone-K cross-review by Tomás (reads from his Tag-59
  OTS-Pre-Anchor-Manifest-Hash-Activation-Probe envelope).
- Zone-L cross-review by Reza (the OTS-anchor-hash is a
  cryptographic-identity-substrate concern; the writer must
  not misinterpret hash semantics).

## §6 Sandbox-Boundary

This plan-doc + helper-stub are hermetic-by-construction:

- The helper-stub `tooling/ci/render_engine_state_file_stub.py`
  is **stdlib-only**, never writes to disk in its render-mode
  (CLI prints to stdout), never makes network calls, never
  imports anything outside the stdlib. The plan-doc is pure
  Markdown.
- The Tag-68 test-suite
  (`wirelang/tests/persona_engine/test_state_file_producer_plan_tag68.py`)
  is hermetic: no NATS, no SPIRE, no gRPC, no subprocess outside
  in-process stdlib calls. It validates the plan-doc structure
  and the helper-stub render-contract.
- The Tag-69+ engine-side writers (when they land) **will**
  perform filesystem writes (atomic write-tmp + rename) but
  only against repo-local `state/welle-N.json` paths. They will
  not invoke network, podman, NATS, SPIRE, or any host
  operator-substrate.
- Per Mira's Sandbox-vs-Host-Operations Trennung
  (feedback-2026-05-13): `*-live.json` state-files are
  operator-territory and are **not** written by the engine
  here. The Tag-68 plan explicitly excludes operator-emit-
  script wiring from its scope (§1 out-of-scope). Kai-Domain
  (Zone-J).

### §6.1 What the engine never touches (operator-hand only)

- `state/welle-6-subscribe-mode-live.json` — operator-emitted
  per schema-pin §2.6.
- `state/welle-7-recovery-drill-live.json` — operator-emitted
  per schema-pin §2.6.
- Any state-file with `-live.json` suffix — operator-hand by
  ADR-0058 §Nachtrag and feedback-sandbox-host-trennung.

### §6.2 What the engine writes (Tag-69+ wiring scope)

- `state/welle-N.json` rollup-file's `status`, `cutover_iso`,
  `signoff_iso`, `audit_trail_anchor` fields, via the four
  writers §2.1..§2.4.
- No other `state/welle-*` file is written by the engine. The
  sign-off-file is written by Tomás' Tag-40 sign-off-state-
  machine; the validation-last-verdict file is written by his
  Tag-44 workflow; the pre-auditor-decision file is written
  AR-hand; the hot-spot-trend files are written by per-Welle
  hot-spot-aggregators; the welle-specific drift-detector
  files are written by per-Welle owners. The engine is the
  **rollup-file-only** writer.

### §6.3 Audit-only at Tag-68

The Tag-68 helper-stub `render_engine_state_file_stub.py`
operates in render-mode only: it accepts a `(welle_number,
kw_anchor)` pair and prints the canonical pending-status JSON
to stdout. It deliberately does NOT have a write-mode at
Tag-68; the write-path is the Tag-69+ engine-side writer's
responsibility. This keeps Tag-68 a doc + audit-stub PR with
no behavioural change to any producer.

---

— Selin, Tag-68
