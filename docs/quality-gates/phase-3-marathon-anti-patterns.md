# Quality-Gate — Phase-3-Marathon-Anti-Pattern Definition-of-Done

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft — pending Phase-3c-Welle-Marathon execution (ADR-0066 four-Wochen-Cadence KW-24 -> KW-27) |
| Phase | 3 (closing): control-plane anti-pattern Definition-of-Done |
| Source | Tag-44 Amara Auftrag (Continuous-Mode, 2026-05-18); ADR-0066 §Beschluss + §Wochen-Plan; ADR-0065 §Verifikations-Plan; `.github/workflows/phase-3-complete-marker.yml` (AC-1..AC-5 emit-gate); Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle (IIA-1130 anchor) |
| Date | 2026-05-18 (creation, Tag-44 anti-pattern spawn) |
| Test-File | `tests/phase_3c/test_marathon_anti_patterns.py` |
| Companion (positive marathon-sequence) | `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` (Tag-43) |
| Companion (per-day walkthrough) | `tests/phase_3c/test_cutover_day_e2e_drill.py` (Tag-41) |
| Companion (marker state-machine) | `tests/phase_3c/test_phase_3_final_regression.py` (Tag-40) |
| Companion (marker workflow) | `.github/workflows/phase-3-complete-marker.yml` (Tomás Tag-40) |
| Companion (audit-spec) | `docs/audit/phase-3-cutover-schluss-audit-spec.md` (Henrik) |

## 0. Contract scope

This document is the **control-plane anti-pattern** Definition-of-Done
for the Phase-3c-Welle-Marathon. Where the Tag-43 marathon-positive
suite pins the four-Wochen-Cadence sequence ("does the marathon thread
the per-day records into the AC-1..AC-5 conjunction and fire the
marker?"), this Tag-44 file pins ten dedicated **anti-pattern
failure-modes** that the marathon control-surface must reject by
construction — independent of whether any one Welle in any one week
signs off.

The Phase-3-Acceptance pyramid grows to four layers with this file:

| Layer | Suite | Owner | Contract |
|---|---|---|---|
| 1 — State-Machine | `test_phase_3_final_regression.py` (Tag-40) | Amara | Given seven sign-off-records, does the Phase-3-COMPLETE-marker fire? |
| 2 — Per-Day | `test_cutover_day_e2e_drill.py` (Tag-41) | Amara | Does one Cutover-Mittwoch produce a correctly-shaped sign-off-record? |
| 3 — Marathon | `test_marathon_schluss_acceptance_drill.py` (Tag-43) | Amara | Does the four-Wochen-Sequence thread the per-day records into the AC-1..AC-5 conjunction, fire the marker, fire the Bilanz-Trigger? |
| 4 — Anti-Pattern | `test_marathon_anti_patterns.py` (Tag-44, this doc) | Amara | Does the control-surface REJECT ten dedicated control-plane anti-patterns by construction? |

The four suites are **complementary, not substitutive**. None of the
four replaces the live-VM-acceptance-lane (operator-hand-territory,
ADR-0058 §Nachtrag). The Tag-44 anti-pattern layer is the *narrowest*
of the four: each AP-axis pins one invariant of the control surface
itself, not one Welle-state outcome.

## 1. The ten anti-pattern axes (AP-1..AP-10)

### AP-1 — Phase-3-COMPLETE-Marker race

**Anti-pattern.** Two parallel marker-emission workflows
(`workflow_dispatch` + `schedule: cron`) both successfully write
`state/phase-3-complete-marker.json`, producing either two competing
marker files (under different commits) or a corrupted single file.

**Production-anchor.** The Tomás Tag-40 marker-workflow's
`concurrency.group=phase-3-complete-marker` + `cancel-in-progress:
false` clause serialises marker-emission: at most one in-flight job
per repo. The second dispatch waits for the first to complete.

**Test rule (DoD).** Given two parallel `acquire()` calls on the
in-test `MarkerEmissionLease` oracle, exactly one MUST be admitted
and exactly one MUST be denied. The denied caller's `write_marker()`
attempt MUST be rejected at the write-step (second line of defense).
Serial `(acquire, release)` cycles MUST both be admitted (the rule
applies to parallelism, not idempotency).

**Anti-pattern signal in production.** Two `state/phase-3-complete-
marker.json` blobs reachable from `main` with different `emitted_at_utc`
values would surface this anti-pattern in the audit-trail.

### AP-2 — Welle-Sign-Off replay

**Anti-pattern.** A sign-off file is admitted twice for the same
`(welle_number, commit_sha)` pair, allowing the marker workflow to
double-count the same Welle's sign-off (or worse: a second submission
with a different `sign_off_status` shadow-writes the first).

**Production-anchor.** The marker-workflow reads
`state/welle-{N}-sign-off.json` from the checked-out HEAD; the file
system is the idempotency-ledger. A second submission MUST land as a
file-level overwrite via PR-merge, audit-trailed in git history.

**Test rule (DoD).** Given the in-test `SignOffIdempotencyLedger`,
`admit(welle, sha, status)` MUST return `False` on the second call
with the same `(welle, sha)` pair, EVEN if the status differs. The
ledger MUST preserve the first-admitted status (no shadow write).
Distinct `(welle, sha)` pairs MUST be admitted independently
(the rule rejects natural-key replay, not legitimate re-signs after
fixup commits).

### AP-3 — Audit-Trail corruption (Self-Reference-Trap-Anti-Pattern-Probe)

**Anti-pattern.** Welle-3 cuts over the `bridge_audit_writer` itself
— the very component that writes the audit-records proving the
cutover happened. A corruption-window opens if (a) the new writer is
activated before the legacy writer drains, or (b) the legacy writer
is stopped before the new writer is ready, leaving an interregnum
during which audit-records are lost.

**Production-anchor.** The Welle-3 cutover-runbook
(`docs/runbooks/welle-3-bridge-audit-writer-cutover.md`) prescribes
the strict drain-before-activate ordering. The cutover-window state
transitions are `pre-cutover -> drain -> drain-complete -> activate
-> post-cutover`; the operator-hand-gate enforces that ordering.

**Test rule (DoD).** Given the in-test
`BridgeAuditWriterCutoverLedger`, the legal sequence MUST produce a
record-history where every record is owned by either the legacy or
the new writer (never neither). The illegal sequence (activate
before drain) MUST raise. After the legal cutover,
`has_corruption_window()` MUST return `False` and the record-history
length MUST equal the sum of pre-cutover + drain + post-cutover
writes.

### AP-4 — Cross-Welle FSM-state-leak

**Anti-pattern.** Welle-4 cuts over `state_backing`; Welle-5 cuts
over `lifecycle_state_machine`. Both touch persona FSM state. If the
state-backing keys are not namespaced per Welle, a Welle-4 write can
appear as a legitimate Welle-5 read, leading to FSM-state-bleed
across cutover boundaries.

**Production-anchor.** The state-backing schema namespace prefix
(`welle-4/` for state_backing, `welle-5/` for lifecycle_state_machine)
isolates the two layers. The Welle-4 + Welle-5 cutover-runbooks
prescribe the prefix discipline.

**Test rule (DoD).** Given the in-test `StateBackingLeakLedger`, a
write under one Welle's prefix MUST NOT be visible to the other
Welle's read of the same key. The namespace boundary MUST be
bidirectional (Welle-4 writes invisible to Welle-5 AND Welle-5
writes invisible to Welle-4). `keys_under_prefix(welle)` MUST return
only the keys written under that welle's prefix.

### AP-5 — Sign-Off timestamp drift

**Anti-pattern.** The per-KW sign-off-Freitag timestamps are not
monotonically ascending. KW-25 sign-off precedes KW-24 sign-off (or
two KWs share a timestamp), breaking the cadence-ordering on which
the cascade-block rule depends.

**Production-anchor.** ADR-0066 §Wochen-Plan fixes the four-Wochen-
Cadence as a strict total order. The Tag-40
`MARATHON_TRACE_TIMESTAMPS` table is the canonical timestamp anchor.

**Test rule (DoD).** Given the canonical
`MARATHON_TRACE_TIMESTAMPS`, the sign-off-Freitag ISOs MUST be
strictly monotonically ascending in BOTH the KW dimension AND the
parsed-datetime dimension. A drift-violating synthetic sequence
(e.g. swapped KW-25 / KW-26 timestamps) MUST be detected. Equal
adjacent timestamps MUST be rejected (the rule is strict ascending,
not non-decreasing).

### AP-6 — AR-Hand ratification bypass

**Anti-pattern.** AC-5 in the marker-workflow checks for
`state/ar-hand-phase-3-complete-stamp.json` with
`ar_hand_ratification=True` AND a non-empty `ar_hand_quote`. A
bypass attempt submits a dummy file with the right filename but a
wrong payload (e.g. `ar_hand_ratification: "True"` as string,
or empty quote), or the right payload but a wrong filename
(e.g. `state/ar-hand-fake-stamp.json`).

**Production-anchor.** The workflow probe in
`.github/workflows/phase-3-complete-marker.yml` §`verify-ac-5-ar-
hand-ratification` runs `python -c "import json; print(json.load
(open('state/ar-hand-phase-3-complete-stamp.json')).get
('ar_hand_ratification', False))"` and checks the boolean literal
result and non-empty quote-length.

**Test rule (DoD).** Given the in-test `ArHandStampCandidate`, a
candidate is admissible only if (1) `filename == "state/ar-hand-
phase-3-complete-stamp.json"`, (2) the payload contains
`ar_hand_ratification`, `ar_hand_quote`, `timestamp_utc`, (3)
`ar_hand_ratification is True` (boolean, not string), and (4)
`ar_hand_quote` is a non-empty (after strip) string. Eight bypass
variants (wrong name, missing key, string-True, empty quote,
whitespace quote, missing timestamp, non-string quote) MUST all be
rejected.

### AP-7 — IIA-1130 Welle-7 self-audit trap

**Anti-pattern.** Henrik (Internal Audit) signs Welle-7 sign-off.
This violates IIA-1130 (independence): Welle-7 sign-off triggers the
Phase-3-COMPLETE-marker workflow which Henrik's R-A1..R-A6
ratification (AC-4) gates; if Henrik also performs the substantive
sign-off-decision, Internal Audit would be both signer and ratifier
on the same decision-chain.

**Production-anchor.** Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle +
`docs/audit/phase-3-cutover-schluss-audit-spec.md` §IIA-1130 Pt-5:
"Marker setting is mechanical-executive (workflow emits the file);
Internal Audit RATIFIES (AC-4), AR-Hand RATIFIES FINAL (AC-5). At
no point is Internal Audit the marker-actor." The Welle-7-Pre-
Auditor-Decision is the AR-Hand substitute for the Welle-7
signer-of-record.

**Test rule (DoD).** Given the in-test
`Welle7SignOffSubmission`, `admit_welle_7_signoff` MUST reject any
submission with `signer_role="henrik_internal_audit"` with a reason
referencing IIA-1130. It MUST also reject any non-AR-Hand role
(`mira_ceo`, `tomas_engineering`, ad-hoc external). It MUST admit
AR-Hand submissions ONLY if the payload carries both
`welle_7_pre_auditor_decision_present=True` AND a non-empty
`iia_1130_independence_anchor`.

### AP-8 — Cutover-day timing drift

**Anti-pattern.** A cutover is dispatched outside the canonical
window (Mo-Fr 09:00-14:00 CEST). Night-time, weekend, and off-hour
weekday dispatches are rejected by the runbook but might still be
attempted via ad-hoc operator override.

**Production-anchor.** ADR-0066 §Wochen-Plan + Tomás cutover-
runbook: Cutover-Mittwoch ≈ Wednesday 09:00 CEST; the maximum
extension allowed is 14:00 CEST (lunch-break boundary, Cross-Review-
Donnerstag preparation). Nights and weekends are forbidden by the
runbook.

**Test rule (DoD).** Given the `is_within_cutover_window` oracle,
the four canonical Cutover-Mittwoch timestamps (KW-24..KW-27, all
09:00 CEST) MUST be admitted. Seven off-window timestamps —
Saturday, Sunday, Wednesday 02:00, Wednesday 08:59, Wednesday 14:00
(exclusive boundary), Wednesday 14:30, Wednesday 23:00 — MUST all be
rejected. Wednesday 09:00 (boundary, inclusive) MUST be admitted.

### AP-9 — Rollback cascade

**Anti-pattern.** Welle-3 rolls back (e.g. Henrik-Caution flag fires
during the cutover), but Welle-4..7 cutovers are dispatched anyway,
on the false assumption that the rollback is local. The Phase-3-
COMPLETE-marker would then aggregate three pre-Welle-3 sign-offs +
four post-rollback sign-offs and falsely fire.

**Production-anchor.** Welle-3 cuts over the audit-trail writer
itself (`bridge_audit_writer`); Welle-4..7 cross-modul-drift
assertions depend on the post-cutover audit-trail being in its new
state. A Welle-3 rollback rolls back the audit-trail-writer baseline
on which Welle-4..7 assertions rest.

**Test rule (DoD).** Given the in-test
`apply_welle_3_rollback_cascade`, a rollback-set containing Welle-3
MUST yield `welle_3_rolled_back=True`, `blocked_wellen=(3,4,5,6,7)`,
`marker_admissible=False`, and a reason mentioning "welle-3". An
empty rollback-set MUST yield `welle_3_rolled_back=False`,
`blocked_wellen=()`, and `marker_admissible=True` (other AC checks
apply downstream). A non-Welle-3 rollback (e.g. Welle-6 alone) MUST
NOT cascade backwards but MUST still set `marker_admissible=False`.

The cross-check via the Tag-40
`Phase3CompleteMarkerStateMachine.compute_verdict()` MUST report
`phase_3_complete=False` AND `cascade_blocked=True` for a markers-
dict containing a Welle-3 rollback alongside six green sign-offs.

### AP-10 — COMPLETE-marker false-positive via empty state-files

**Anti-pattern.** An empty state-file (zero bytes), a minimal `{}`,
a whitespace-only file, or a JSON-null file is accepted by one of
the AC-1..AC-5 probes — leading to a false-positive marker emission
on essentially-absent evidence.

**Production-anchor.** Each `verify-ac-{1..5}-*` job in
`.github/workflows/phase-3-complete-marker.yml` reads specific
fields from the corresponding state-file. The job MUST set
`{ac}_pass=false` on any field absence or type mismatch.

**Test rule (DoD).** Given the four in-test probes
(`state_file_passes_ac1_probe`, `state_file_passes_ac3_probe`,
`state_file_passes_ac4_probe`, `state_file_passes_ac5_probe`), six
degenerate payloads — empty string, `{}`, whitespace, non-JSON,
JSON-array, JSON-null — MUST all be rejected by every probe.

The complementary positive case: well-shaped payloads pass their
respective probes, with the field-validation rules enforced exactly
(AC-1 status not in `{green, yellow_henrik_hand_approval}` rejected;
AC-3 count mismatch rejected; AC-4 missing R-A flag rejected; AC-5
whitespace-only quote rejected).

## 2. Cross-suite contract-lock-step

The Tag-44 anti-pattern suite reuses the following contract surfaces
from companion suites:

| Surface | Source | Use in Tag-44 |
|---|---|---|
| `ADR_0066_REIHENFOLGE` | Tag-40 | AP-9 markers-dict construction |
| `ADR_0065_AC_4_PERSONAS` | Tag-40 | AP-9 green-signoff fixture |
| `WELLE_ENDE_GATES` | Tag-40 | AP-9 Welle-Ende gate map |
| `MARATHON_TRACE_TIMESTAMPS` | Tag-40 | AP-5 monotonicity probe, AP-8 timing-window probe |
| `SignOffMarker` | Tag-40 | AP-9 cascade cross-check fixture |
| `Phase3CompleteMarkerStateMachine` | Tag-40 | AP-9 cascade verdict cross-check |
| `KW_TO_WELLEN` | Tag-43 | AP-9 cascade-set construction |

The Tag-44 suite does NOT introduce new constants that the Tag-40 /
Tag-43 / Tag-41 suites do not already pin. This means a future
ADR-0066 amendment that changes the Reihenfolge or the timestamps
needs to be reflected in exactly one place (Tag-40) and the Tag-44
suite picks it up transitively.

## 3. Hermetic-Sandbox-Boundary

All 20 Tag-44 tests are full-hermetic:

* Pure stdlib + pytest (no jsonschema, no hypothesis at suite-import
  time, no PyYAML).
* No file-system writes outside `pytest`'s default tmp-area (none of
  the tests write any files; oracles are pure-Python in-memory).
* No GitHub-API probes, no podman, no NATS, no live-VM.
* Companion-test-module loading uses `importlib.util.spec_from_file_
  location` to reuse Tag-40 / Tag-43 constants without re-execution
  side-effects.

Per ADR-0058 §Nachtrag, the live-VM-acceptance-lane is operator-
hand-territory and not in this suite's scope. The Tag-44 anti-
pattern suite is the *pre-image* of the live-VM-rejection-rules —
the live-VM-lane is the substrate-confirmation.

## 4. Test count and naming convention

The suite has 20 tests, two per AP-axis:

| AP | Test 1 (negative — anti-pattern rejected) | Test 2 (positive — non-violating input admitted) |
|---|---|---|
| AP-1 | `test_ap_1_two_parallel_acquirers_yields_one_admit_one_deny` | `test_ap_1_serial_acquire_release_admits_both_in_sequence` |
| AP-2 | `test_ap_2_replay_with_same_welle_and_sha_is_rejected` | `test_ap_2_different_sha_or_welle_is_a_distinct_submission` |
| AP-3 | `test_ap_3_legal_cutover_sequence_leaves_no_corruption_window` (legal sequence MUST NOT corrupt) | `test_ap_3_illegal_activate_before_drain_is_rejected` (illegal sequence MUST raise) |
| AP-4 | `test_ap_4_welle_5_read_under_its_own_prefix_does_not_see_welle_4_data` | `test_ap_4_welle_5_writes_are_invisible_to_welle_4_reads` |
| AP-5 | `test_ap_5_canonical_marathon_trace_is_strictly_monotonic` | `test_ap_5_drift_violating_sequence_is_rejected` |
| AP-6 | `test_ap_6_canonical_stamp_is_admissible` | `test_ap_6_bypass_attempts_are_rejected` |
| AP-7 | `test_ap_7_henrik_internal_audit_signer_is_rejected` | `test_ap_7_ar_hand_signer_with_complete_payload_is_admitted` |
| AP-8 | `test_ap_8_canonical_cutover_mittwoche_are_in_window` | `test_ap_8_off_window_timestamps_are_rejected` |
| AP-9 | `test_ap_9_welle_3_rollback_blocks_all_subsequent_wellen` | `test_ap_9_no_rollback_yields_admissible_marker_path` |
| AP-10 | `test_ap_10_empty_or_minimal_payloads_fail_all_probes` | `test_ap_10_well_shaped_payloads_pass_their_respective_probes` |

The two-tests-per-axis pattern is intentional: each anti-pattern
rule is double-anchored as (1) "the rule fires on a violating input"
and (2) "the rule does not over-fire on a non-violating input". A
test-suite that pinned only the violation-case would not detect a
regression in which the rule became *always-rejecting*.

## 5. Pass-criteria

The suite is green when:

* All 20 tests pass via `pytest tests/phase_3c/test_marathon_anti_patterns.py -v`.
* No new external dependencies introduced (stdlib + pytest only).
* All companion-module imports resolve without network access.
* Run-time under 5 seconds on a clean checkout.

## 6. Cross-reference to Tag-40 / Tag-41 / Tag-43

The Tag-44 anti-pattern suite **does not duplicate** any test in the
Tag-40 / Tag-41 / Tag-43 suites:

* Tag-40 NEG-axis pins per-marker degenerate cases (e.g. 6/7 signed
  off, AC-1..AC-5 not green). Tag-44 pins control-plane invariants
  (race, replay, corruption-window, leak, timing, bypass, IIA-1130,
  cascade, false-positive).
* Tag-41 pins the per-day Cutover-Mittwoch happy-path shape; Tag-44
  AP-8 pins the timing-window invariant the runbook ENFORCES.
* Tag-43 NEG-axis pins five anti-false-positive marathon-aggregate
  cases (rollback-blocks-marker, Welle-7-Pre-Auditor missing, cross-
  modul-drift blocker, 6/7 signoffs, KW-26 partial). Tag-44 AP-9
  pins the rollback-CASCADE-rule at the *control-surface* layer
  rather than at the marathon-aggregate-layer.

## 7. Zone-N — Henrik Internal-Audit cross-check

Per the §IIA-1130 contract, Henrik's audit-sample MAY review the
Tag-44 suite for:

* AP-3 self-reference-trap encoding (does the test pin the strict
  drain-before-activate ordering that the runbook prescribes?).
* AP-7 IIA-1130 anchor (does the test reject Henrik as Welle-7 signer
  with a reason that explicitly references IIA-1130?).
* AP-10 false-positive-rejection completeness (does the test cover
  every probe with every degenerate-payload variant?).

Henrik's review is RATIFY-only on this suite; the substantive
test-authoring is QA's (Amara's) responsibility. The Zone-N boundary
is preserved.

— Amara
