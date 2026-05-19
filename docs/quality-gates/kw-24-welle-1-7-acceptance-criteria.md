# Quality-Gate — KW-24 Welle-1..7 Per-Welle Acceptance-Criteria

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft — pre-cutover acceptance-criteria pin for KW-24 Cutover-Marathon |
| Phase | 3c, KW-24..KW-27 Cutover-Marathon (T0 = KW-24 Mo 2026-06-08/09) |
| Source | ADR-0066 (Doppel-Welle Cadence), ADR-0065 (Cutover-Sequencing), Tag-44 Henrik-Pre-Mortem, Tag-45 Hot-Spot-Aggregator Family, Tag-63 E2E-Smoke (PR #400), Tag-65 Stability-Window-Probe (PR #416) |
| Date | 2026-05-19 (Tag-66, Amara, Continuous-Mode-Marathon) |
| Pattern lineage | Tag-63 E2E-Smoke trinary-verdict-rule, Tag-65 Stability-Window-Probe per-run-status classification, Tag-45..49 Welle-Hot-Spot-Aggregator family |

## 0. Scope

This document pins the per-Welle acceptance-criteria for the
KW-24..KW-27 Cutover-Marathon. The marathon proceeds wave-by-wave
(Welle-1..Welle-7) over four CI-weeks, with a per-Welle E2E-smoke-
schedule that triggers automatically on the documented anchor-day
(see §0.2 schedule-table).

### 0.1 What this doc owns

- Per-Welle acceptance-criteria (what does GREEN/YELLOW/RED mean
  for that Welle's CI surface).
- Per-Welle anchor-day cron-trigger schedule (the
  ``pre-cutover-final-acceptance-e2e-smoke.yml`` matrix-strategy
  expansion documented in §0.3).
- Per-Welle Acceptance-Verdict aggregation rule (§8) — how
  per-Welle stage-statuses fold into a single
  ``WELLE-{N}-{READY|DRIFT|DEFECT}`` verdict.

### 0.2 What this doc does NOT own

- Per-Welle bug-fixes (Engineering-Personae own those — Zone-M).
- Per-Welle production-substrate implementation (Engineering-
  Personae own those — Zone-M).
- Per-Welle audit-trail interpretation (Henrik owns that —
  Zone-N).
- Per-Welle ADR-justification (Mira/Aufsichtsrat own those).

### 0.3 KW-24..KW-27 schedule table

| # | Welle | KW | Anchor-Day | T-Offset | Substrate-Focus |
|---|---|---|---|---|---|
| 1 | Engine-Cutover | KW-24 | Mo 2026-06-08 | T0 | Persona-Engine Rust-Boot |
| 2 | Doppelbetrieb-Sealing | KW-24 | Mi 2026-06-10 | T+2d | Bilanz-Validation cutover-seal |
| 3 | Bridge-Audit | KW-24 | Fr 2026-06-12 | T+4d | bridge-audit-writer KW-24-pin |
| 4 | State-Backing | KW-25 | Mo 2026-06-15 | T+7d | rust_inmemory backend |
| 5 | Capability-Token | KW-25 | Fr 2026-06-19 | T+11d | capability-token enforce-mode |
| 6 | Cross-Substrate-Parity | KW-26 | Fr 2026-06-26 | T+18d | cross-substrate parity-gate |
| 7 | Final-Sealing | KW-27 | Fr 2026-07-03 | T+25d | marathon-final-sealing |

Cron-trigger anchor: per-Welle workflow_dispatch + scheduled cron
on the documented anchor-day at 06:00 UTC (matrix-strategy in
``.github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml``).

### 0.4 Verdict shape (canonical)

Each Welle emits one of three verdicts (same shape as Tag-63
E2E-Smoke):

- ``WELLE-{N}-READY`` — all stage-probes green.
- ``WELLE-{N}-DRIFT`` — 1..N yellow stages, zero red.
- ``WELLE-{N}-DEFECT`` — any red stage.

## §1. Welle-1 KW-24 Mo — Engine-Cutover

**Anchor:** KW-24 Mo 2026-06-08 (T0).
**Substrate:** Persona-Engine Rust-Boot cutover (Selin, ADR-0065).
**Hot-Spot rank (Henrik Pre-Mortem):** #2 — boot-time regression
risk + first-cutover-day blast-radius.

### §1.1 Acceptance probes (green-criterion)

1. **W1-S1 Engine-Boot-Smoke** — `persona-engine-pre-cutover-final-
   acceptance-composite.yml` returns ENGINE-READY. Helper:
   ``tooling/ci/aggregate_persona_engine_pre_cutover_final.py``.
2. **W1-S2 Rust-Boot-Verify** — Boot-marker present in
   ``state/persona-engine-rust-boot-verify.json``; aggregator
   returns ``boot_status=ready``.
3. **W1-S3 Cutover-Day-Morgen** — Tag-64/65 Trinary-Routing
   workflow YAML present and parseable
   (``.github/workflows/cutover-day-morgen-trinary-routing-validate.yml``).
4. **W1-S4 AR-Hand Override Listener** — Tag-65 Override-Flag
   listener workflow present (``cutover-day-morgen-auto-scheduler.yml``).

### §1.2 Yellow conditions (DRIFT)

- W1-S2 boot-marker missing but engine-composite green
  (pre-cutover state).
- W1-S4 listener present but cron-window outside the KW-24
  Mo anchor (operator-hand fallback usable).

### §1.3 Red conditions (DEFECT)

- W1-S1 engine-composite returns ENGINE-DEFECT.
- W1-S2 aggregator returns ``boot_status=defect``.
- W1-S3 trinary-routing YAML missing or unparseable.

## §2. Welle-2 KW-24 Mi — Doppelbetrieb-Sealing

**Anchor:** KW-24 Mi 2026-06-10 (T+2d).
**Substrate:** Bilanz-Validation cutover-seal (Tomas, Zone-K).
**Hot-Spot rank (Henrik Pre-Mortem):** #5 — sealing-event idempotency.

### §2.1 Acceptance probes (green-criterion)

1. **W2-S1 Bilanz-Validation Fixture** — `phase-3-bilanz-validation-
   fixtures.md` referenced fixtures present;
   ``tests/fixtures/phase_3_bilanz_validation/`` populated.
2. **W2-S2 Doppelbetrieb-Score-Aggregator** — `doppelbetrieb-
   score-aggregator` helper importable in
   ``--mode=cross-modul-stress``.
3. **W2-S3 Sealing-Event Marker** — `state/welle-2-doppelbetrieb-
   sealing-verdict.json` present (post-cutover write).
4. **W2-S4 Pyramide-Compositum Re-Run** — Tag-62 pyramide-
   compositum returns PYRAMIDE-READY after sealing-event.

### §2.2 Yellow conditions (DRIFT)

- W2-S3 sealing-event marker present but timestamp older than
  Welle-2 anchor (stale-write).
- W2-S4 pyramide-compositum returns PYRAMIDE-DRIFT (1..N yellow).

### §2.3 Red conditions (DEFECT)

- W2-S2 score-aggregator non-importable or mode-flag rejected.
- W2-S4 pyramide-compositum returns PYRAMIDE-DEFECT.

## §3. Welle-3 KW-24 Fr — Bridge-Audit

**Anchor:** KW-24 Fr 2026-06-12 (T+4d).
**Substrate:** bridge-audit-writer KW-24-pin (Selin + Henrik IIA-1130
Pre-Auditor).
**Hot-Spot rank (Henrik Pre-Mortem):** #1 — Self-Reference-Trap +
audit-trail-integrity propagation to Welle-4/5/7.

### §3.1 Acceptance probes (green-criterion)

1. **W3-S1 Self-Reference-Trap Probe** — Tag-45 Welle-3 hot-spot
   aggregator returns ``self_reference_trap=none``. Helper:
   ``tooling/ci/welle_3_hot_spot_aggregator.py``.
2. **W3-S2 Cross-Welle-Propagation-Risk** — ``state/welle-3-audit-
   trail-integrity.json`` returns ``integrity=green``; Welle-4/5/7
   not flagged ``pre_conditional_blocked``.
3. **W3-S3 Independent-Oracle-Agreement** — doppelbetrieb-score-
   aggregator cross-modul-stress agrees with bridge-audit-writer
   health (no mis-attribution).
4. **W3-S4 IIA-1130 Pre-Auditor-Decision** — `state/welle-3-pre-
   auditor-decision.json` present with Henrik sign-off.

### §3.2 Yellow conditions (DRIFT)

- W3-S2 integrity green but Welle-4 flagged conditionally (e.g.
  state-backing pre-warm requested but not yet executed).
- W3-S4 Pre-Auditor-Decision file present but sign-off timestamp
  pre-dates the Welle-3 anchor (Henrik re-sign required).

### §3.3 Red conditions (DEFECT)

- W3-S1 Self-Reference-Trap detected.
- W3-S2 integrity red (propagation to downstream Wellen triggered).
- W3-S3 Oracle-disagreement (mis-attribution risk).

## §4. Welle-4 KW-25 Mo — State-Backing

**Anchor:** KW-25 Mo 2026-06-15 (T+7d).
**Substrate:** `WAKIR_STATE_BACKING_BACKEND=rust_inmemory` (Selin,
ADR-0066 §Beschluss).
**Hot-Spot rank (Henrik Pre-Mortem):** #3 — state-migration race.

### §4.1 Acceptance probes (green-criterion)

1. **W4-S1 State-Backing Smoke** — `tooling/ci/welle_4_hot_spot_
   aggregator.py` returns ``state_backing=green``.
2. **W4-S2 Doppel-Welle-Path Decision** — `phase-3c-doppel-welle-
   4-5.md` PAR/SEQ-decision-marker present in
   ``state/doppel-welle-4-5-path-decision.json``.
3. **W4-S3 Rollback-Drill** — Tag-56 Marathon-Rollback workflow
   green (`.github/workflows/phase-3-marathon-rollback.yml`).
4. **W4-S4 Welle-3-Propagation-Clear** — Welle-3 audit-trail-
   integrity remains green at Welle-4 anchor (no downstream-block).

### §4.2 Yellow conditions (DRIFT)

- W4-S2 path-decision present but SEQ chosen (slower path,
  acceptable).
- W4-S3 rollback-drill green on probe but no recent live-drill run.

### §4.3 Red conditions (DEFECT)

- W4-S1 state-backing aggregator returns red.
- W4-S4 Welle-3 downstream-block remains active (Welle-4 must wait
  for Welle-3 re-green).

## §5. Welle-5 KW-25 Fr — Capability-Token

**Anchor:** KW-25 Fr 2026-06-19 (T+11d).
**Substrate:** capability-token enforce-mode (Reza, Zone-L).
**Hot-Spot rank (Henrik Pre-Mortem):** #4 — token-enforce-mode
mis-config blast-radius.

### §5.1 Acceptance probes (green-criterion)

1. **W5-S1 Capability-Token Smoke** — `tooling/ci/welle_5_hot_
   spot_aggregator.py` returns ``capability_token=enforce``.
2. **W5-S2 Reza Spec-Coverage** — `docs/ops/v0.4.4-reserve-item-
   promotion-sequencing.md` capability-token coverage section
   present.
3. **W5-S3 Enforce-Mode Verify** — workflow-dispatch trigger on
   capability-token-enforce-validate returns green.
4. **W5-S4 Token-Rotation-Drill** — `state/capability-token-rotation-
   drill.json` present with timestamp >= Welle-5 anchor-7d.

### §5.2 Yellow conditions (DRIFT)

- W5-S2 spec-coverage present but partial (some token-classes
  not covered).
- W5-S4 rotation-drill timestamp 8..14d before anchor (stale-warm).

### §5.3 Red conditions (DEFECT)

- W5-S1 capability-token aggregator returns red.
- W5-S3 enforce-mode probe returns audit-only-mode (enforce-flag
  not active).

## §6. Welle-6 KW-26 Fr — Cross-Substrate-Parity

**Anchor:** KW-26 Fr 2026-06-26 (T+18d).
**Substrate:** cross-substrate parity-gate (Kai+Amara, Tag-32/57).
**Hot-Spot rank (Henrik Pre-Mortem):** #6 — cross-substrate fan-out.

### §6.1 Acceptance probes (green-criterion)

1. **W6-S1 Parity-Gate Workflow** — `.github/workflows/cross-
   substrate-parity-gate.yml` present and parseable.
2. **W6-S2 Welle-6 Hot-Spot Probe** — `tooling/ci/welle_6_hot_
   spot_aggregator.py` returns ``parity=green``.
3. **W6-S3 Cross-Substrate-Pin** — image-pin-idempotent-resolver
   returns identical SHA across all substrates.
4. **W6-S4 Doppel-Welle-6-7 Companion** — `phase-3c-doppel-welle-
   6-7.md` referenced.

### §6.2 Yellow conditions (DRIFT)

- W6-S3 SHA-pin identical on 2/3 substrates (one substrate stale).
- W6-S4 doppel-welle-6-7 doc present but no recent revision.

### §6.3 Red conditions (DEFECT)

- W6-S1 parity-gate workflow missing or unparseable.
- W6-S3 SHA-pin mismatch on more than one substrate.

## §7. Welle-7 KW-27 Fr — Final-Sealing

**Anchor:** KW-27 Fr 2026-07-03 (T+25d).
**Substrate:** marathon-final-sealing (Tomas+Amara, Tag-56).
**Hot-Spot rank (Henrik Pre-Mortem):** #7 — final-sealing event
finality + audit-bundle completeness.

### §7.1 Acceptance probes (green-criterion)

1. **W7-S1 Marathon-Final-Acceptance Live-Verify** — `marathon-
   final-acceptance-live-verify-gate.yml` returns LIVE-VERIFY-READY.
2. **W7-S2 Welle-7 Hot-Spot Probe** — `tooling/ci/welle_7_hot_
   spot_aggregator.py` returns ``final_sealing=green``.
3. **W7-S3 Final-Bilanz-Aggregator** — `marathon-final-bilanz-
   aggregator` returns BILANZ-CLOSED.
4. **W7-S4 IIA-1130 Final Pre-Auditor-Decision** — `state/welle-7-
   pre-auditor-decision.json` final sign-off by Henrik.

### §7.2 Yellow conditions (DRIFT)

- W7-S3 bilanz-aggregator returns BILANZ-CLOSED-WITH-CARRY-FORWARD
  (open OPEN-K-items deferred to post-cutover).
- W7-S4 final sign-off present but conditional (Henrik flagged
  carry-forward).

### §7.3 Red conditions (DEFECT)

- W7-S1 live-verify returns LIVE-VERIFY-DEFECT.
- W7-S3 bilanz-aggregator returns BILANZ-OPEN.
- W7-S4 IIA-1130 final decision missing.

## §8. Acceptance-Verdict Aggregation per Welle

### §8.1 Per-Welle aggregation rule

For each Welle N in 1..7:

```
inputs:  W{N}-S1, W{N}-S2, W{N}-S3, W{N}-S4  (each green|yellow|red)
output:  WELLE-{N}-{READY|DRIFT|DEFECT}

decide:
  if any S is red    -> WELLE-{N}-DEFECT
  elif any S is yellow -> WELLE-{N}-DRIFT
  else                  -> WELLE-{N}-READY
```

Same shape as Tag-63 E2E-Smoke trinary-verdict-rule (any red
collapses, any yellow degrades).

### §8.2 Cross-Welle propagation

Welle-3 (Bridge-Audit) downstream-blocks Welle-4/5/7 per Tag-45
Hot-Spot-Aggregator. If `WELLE-3-DEFECT` -> Welle-4/5/7
downstream-verdict appended with ``pre_conditional_blocked: true``
until Welle-3 re-greens.

No other cross-Welle dependencies are mandatory (Welle-1/2/6
verdicts are independent of upstream-Wellen).

### §8.3 Matrix-strategy job-shape

The Tag-66 workflow extension expands
``pre-cutover-final-acceptance-e2e-smoke.yml`` with a
``matrix.welle: [1,2,3,4,5,6,7]`` strategy. Each matrix-cell
emits a per-Welle verdict to the job-summary and uploads a
per-Welle verdict envelope as artifact named
``welle-{N}-acceptance-verdict``.

### §8.4 Aggregator helper

`tooling/ci/aggregate_kw_24_welle_acceptance.py` performs the
per-Welle aggregation. Inputs come from per-Welle stage-status
environment variables (`W{N}_S{1..4}_STATUS`,
`W{N}_S{1..4}_NOTE`), output is a verdict envelope JSON with
schema:

```json
{
  "verdict": "WELLE-{N}-{READY|DRIFT|DEFECT}",
  "welle": N,
  "anchor_kw": "KW-{24..27}",
  "anchor_weekday": "Mo|Mi|Fr",
  "stages": {"s1": "...", "s2": "...", "s3": "...", "s4": "..."},
  "notes": "stage_a:note;stage_b:note",
  "downstream_blocks": ["welle-N", ...] | [],
  "pattern_lineage": "tag-63-e2e-smoke + tag-45-hot-spot-aggregator",
  "cross_review_markers": ["zone-M (Tomás)", "zone-N (Henrik)"]
}
```

### §8.5 Anti-Patterns guarded

- **Per-Welle verdict-drift across runs** — the Tag-65 Stability-
  Window-Probe pattern is reused: per-Welle verdict must be
  identical across 3 back-to-back probes on the anchor-day to
  qualify for `READY`.
- **Self-aggregation bias** — the per-Welle aggregator MUST NOT
  read its own previous verdict as input (Self-Reference-Trap
  guard, Henrik Tag-39 hypothesis).
- **Anchor-day drift** — if a Welle's cron-trigger fires outside
  the documented anchor-day window (±24h), the workflow falls
  back to operator-hand workflow_dispatch (no auto-promotion to
  Required-Status-Check).

## §9. Cross-Review markers (Zone-M / Zone-N)

- **Zone-M (QA × Engineering, via Tomás):** Welle-1 (Selin
  engine-cutover), Welle-2 (Tomás doppelbetrieb), Welle-3 (Selin
  bridge-audit, IIA-1130 with Henrik), Welle-4 (Selin state-
  backing), Welle-5 (Reza capability-token), Welle-6 (Kai cross-
  substrate-parity), Welle-7 (Tomás final-sealing). Per-Welle
  stage-probe helpers owned by the listed Engineering-Persona;
  Amara's aggregator only walks the helpers.
- **Zone-N (QA × Henrik Audit):** Welle-3 and Welle-7 IIA-1130
  Pre-Auditor-Decisions are Henrik's domain. The Tag-66 doc
  references them as inputs but does NOT decide them. Welle-3
  downstream-propagation rule is the only cross-Welle data-only
  flag carried by the aggregator; the actual blocking happens in
  the downstream Welle workflows when consuming this aggregator's
  verdict.

## §10. Anti-Scope (what Amara does not own here)

- Production-code implementation for any Welle substrate
  (Engineering-Personae own those — Zone-M).
- ADR-drafting for KW-24 cutover-decisions (Mira / Aufsichtsrat).
- Audit-trail forensics (Henrik — Zone-N).
- Persona-definition changes (Aisha).

— Amara
