---
title: "G1+G2 Operator-Hand Last-Mile Checklist (Tag-69)"
status: "active"
owner: "kai"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-69"
predecessors:
  - "docs/operations/cosign-g1-g2-operator-setup.md"
  - "docs/operations/strict-flip-readiness-map-tag58.md"
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
  - "ADR-0061"
  - "ADR-0065"
  - "ADR-0066"
related_docs:
  - "docs/operations/phase-3c-cutover-runbook.md"
  - "docs/operations/cosign-strict-mode-activation.md"
  - "docs/operations/phase-3c-welle-1-runbook.md"
  - "docs/operations/phase-3c-welle-2-runbook.md"
  - "docs/operations/phase-3c-welle-3-runbook.md"
  - "docs/operations/phase-3c-welle-4-runbook.md"
  - "docs/operations/cosign-g1-g2-operator-setup.md"
  - "docs/operations/strict-flip-readiness-map-tag58.md"
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/bulk-activation-pre-walk-recipe.md"
related_memory:
  - "feedback_sandbox_host_trennung.md"
  - "feedback_continuous_mode_keine_push_frage.md"
  - "feedback_live_bringup_sandbox_gap.md"
  - "feedback_branch_protection_check_names.md"
  - "feedback_anti_eskalations_drift.md"
related_zones:
  - "Zone-J/CI (Kai, Branch-Protection + Cosign-Strict + Bulk-Activation)"
  - "Zone-K (Tomás, REUSE-Wrap + OPEN-K3 Baseline-Metadata)"
---

# G1+G2 Operator-Hand Last-Mile Checklist (Tag-69)

This document is the **Last-Mile granular Operator-Hand checklist**
for the G1 (Quadlet-Cosign-Wiring across the 4 Wellen + Pilot-
Persona) and G2 (Trust-Root-Snapshot pin) Strict-Flip activation
on Cutover-Day-T0. Where the Tag-56 setup-guide
(`cosign-g1-g2-operator-setup.md`) covers the multi-week prep,
the Tag-58 Readiness-Map orchestrates the 7-day calendar, the
Tag-62 Bulk-Aktivierungs-Recipe handles the post-flip Required-
Status-Check wiring, and the Tag-66 Cutover-Eve-Final-Recipe folds
all the prior recipes into a day-by-day plan, **Tag-69 zooms
all the way in**: minute-by-minute Operator-Hand actions for the
24 h between T0-1 Eve (Sunday 2026-06-07) and the 30-minute T0
window (Monday 2026-06-08, 00:00 - 00:30 UTC).

This is **doc-form-only**. No workflow mutation, no `gh api PUT`,
no cosign invocation, no Containerfile mutation, no branch-
protection settings change. Every active operation in this
document is **Operator-Hand-Sandbox-Gap** per ADR-0020 §10 and
the Mira-Sandbox-vs-Host-Operations rule
(Memory `feedback_sandbox_host_trennung`). The Mira-Sandbox
produces this Last-Mile plan; the Operator (Fred plus AR pair)
executes it on the operator workstation.

The Last-Mile plan is structured as a **pro-Minuten-Plan**: the
operator opens this document at 19:00 UTC on Sunday 2026-06-07,
works the Eve-Setup actions across 5 hours of evening time
(§2), goes to bed at 24:00 UTC (= 00:00 UTC Monday, the moment
T0 starts), and **the AR pair plus a designated Operator-Hand
Pilot** drives the 30-minute T0 window (§3) live.

The 30-minute T0 window (§3) is broken into ten 3-minute slots
(T0.0 ... T0.9) instead of the Tag-66 §3 hour-blocks (T0.0 ...
T0.9 spread across 06:30 - 14:00 CEST). This is **intentional
densification**: T0 itself is the 30-minute strict-flip-merge
window; the post-T0 cutover-day actions remain on the Tag-66
hour-grid.

## §1 — Scope

| Item | Value |
|---|---|
| **Window covered** | T0-1 Eve 2026-06-07 19:00 UTC -> T0 2026-06-08 00:30 UTC |
| **Eve-block-time-budget** | 5 h Operator-Hand-Time (19:00 - 24:00 UTC) |
| **T0-block-time-budget** | 30 min critical Operator-Hand-Time (00:00 - 00:30 UTC) |
| **Eve actions** | §2 E1 ... E12 (Sunday evening pre-flight) |
| **T0 actions** | §3 T0.0 ... T0.9 (Monday 00:00 - 00:30 UTC) |
| **G1 sub-wave actions** | §4 G1.W1 ... G1.W4 (5-min spacing within T0) |
| **G2 sub-step actions** | §5 G2.S1 ... G2.S3 (post-G1-Green) |
| **Verification** | §6 V1 ... V6 (parallel + post) |
| **Failure-recovery** | §7 F1 ... F5 (trigger -> action mapping) |
| **Cross-refs + boundary** | §8 anchors + sandbox-boundary |
| **Driver during T0** | AR pair + designated Pilot Operator |
| **Sandbox boundary** | Every active step = Operator-Hand-Sandbox-Gap |
| **Predecessor docs** | Tag-56 setup-guide, Tag-58 map, Tag-62 recipe, Tag-66 eve-recipe |
| **Successor docs** | Tag-66 §3.5 ... §3.9 (post-T0 day-of) |

Note: the times in this document are in **UTC**. The Tag-66 doc
uses CEST. Conversion: 00:00 UTC on Mon 2026-06-08 = 02:00 CEST,
so the strict-flip merge-window lands **between 02:00 and 02:30
CEST**. This is deliberate: the bulk of the European-time-zone
AR pair is asleep, the operator + designated Pilot drive a
small-blast-radius window. The Tag-66 §3 06:30 CEST window
remains the **post-T0 verification + bulk-activation** window;
Tag-69 sequences the **strict-flip merge itself** into the night
hours so that any unexpected impact is contained to a small
operator+AR-Pilot crew.

This is consistent with the Tag-58 §6 Cutover-Day-Gate-Check-
Sequence: G1 + G2 are the **first two gates** of the day; the
remaining gates (G3 hold-steady, G4 hold-steady, G5 hold-steady,
G6 hold-steady) are read-only checks; bulk-activation of the 8
Required-Status-Checks happens at T0+0.5 = 04:00 UTC = 06:00 CEST
(Tag-66 §3.4).

## §2 — Eve-Setup Actions (T0-1 Eve, Sunday 2026-06-07)

The Operator opens this section on Sunday 2026-06-07 at **19:00
UTC** (= 21:00 CEST). Total time budget: **5 h Operator-Hand-
Time**. Twelve Eve-Setup pre-flight steps (E1 ... E12) sequenced
top-to-bottom; each step declares **Time-slot**, **Owner**,
**Action**, **Sandbox-OK**, and **Verdict-Marker**.

### §2.1 — Eve-E1: Cosign-CLI Pre-Flight (19:00 - 19:15 UTC)

- **Time-slot**: 19:00 - 19:15 UTC.
- **Owner**: Operator.
- **Action**: Confirm `cosign version` on the operator workstation
  reports a release that matches the Tag-56 setup-guide §2 pinned
  version. Confirm `cosign initialize` succeeds against the
  fulcio + rekor public keys snapshotted into the G2 trust-root
  directory (`fulcio.pub`, `rekor.pub`, `cosign-root.json`).
- **Sandbox-OK**: `cosign version` is read-only and Operator-Hand-
  Sandbox-Gap-Op (binary is on operator workstation, not in Mira-
  Sandbox). `cosign initialize` is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E1-COSIGN-READY` / `EVE-E1-HOLD`.

### §2.2 — Eve-E2: Env-Var Pre-Flight (19:15 - 19:30 UTC)

- **Time-slot**: 19:15 - 19:30 UTC.
- **Owner**: Operator.
- **Action**: Confirm the following env-vars are set in the
  operator-shell (not the Mira-Sandbox) for the T0 window:
    - `WAKIR_COSIGN_STRICT_MODE=1` (will be exported into the
      strict-flip-PR target branch).
    - `WAKIR_TRUST_ROOT_DIR=/path/to/operator/g2-trust-root-snapshot`.
    - `WAKIR_OPERATOR_HAND_AUTHORIZED=1` (Mira-Hand-
      Authorisierungs-Klausel per Memory
      `feedback_force_push_bundle_merge_ok.md`).
- **Sandbox-OK**: Setting + reading env-vars in operator-shell is
  Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E2-ENV-READY` / `EVE-E2-DRIFT`.

### §2.3 — Eve-E3: OIDC Token Pre-Flight (19:30 - 19:45 UTC)

- **Time-slot**: 19:30 - 19:45 UTC.
- **Owner**: Operator.
- **Action**: Confirm the GitHub OIDC token endpoint is reachable
  from the operator workstation. Confirm the OIDC token-issuer
  matches the Tag-56 setup-guide §3 pinned-issuer. Confirm token-
  TTL stays >= 1 h at T0-start.
- **Sandbox-OK**: OIDC-token pull is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E3-OIDC-READY` / `EVE-E3-HOLD`.

### §2.4 — Eve-E4: Strict-Flip-PR Final Read (19:45 - 20:15 UTC)

- **Time-slot**: 19:45 - 20:15 UTC.
- **Owner**: Operator + AR pair.
- **Action**: Final read-through of the Strict-Flip-PR. Confirm
  the PR diff touches exactly: (a) 4 Welle-Quadlet-service-files
  (`infra/persona-engine/quadlets/wave-{1,2,3,4}-*.container`),
  (b) the Pilot-Persona Quadlet, (c) the Trust-Root pin file.
  Confirm no out-of-scope mutation.
- **Sandbox-OK**: Read-only PR review is Sandbox-OK.
- **Verdict-Marker**: `EVE-E4-PR-READY` / `EVE-E4-DRIFT`.

### §2.5 — Eve-E5: Pilot Operator Hand-Off (20:15 - 20:30 UTC)

- **Time-slot**: 20:15 - 20:30 UTC.
- **Owner**: Operator + designated Pilot Operator.
- **Action**: Hand-off briefing between the Operator (Fred) and
  the designated Pilot Operator who drives the T0 window
  live. Walk the Pilot through this Last-Mile document end-to-
  end. Confirm Pilot has shell access to the operator workstation
  for the T0 window (00:00 - 00:30 UTC).
- **Sandbox-OK**: Hand-off is doc + voice. Sandbox-OK.
- **Verdict-Marker**: `EVE-E5-PILOT-BRIEFED` / `EVE-E5-RESCHEDULE`.

### §2.6 — Eve-E6: AR-Pair Voice-Channel Pre-Open (20:30 - 20:45 UTC)

- **Time-slot**: 20:30 - 20:45 UTC.
- **Owner**: Operator + AR pair.
- **Action**: Open the AR-pair voice channel at 20:30 UTC. AR
  pair confirms presence and stays connected through T0+0.5 =
  00:30 UTC. The Operator (Fred) is **on-call but not driving**;
  the Pilot drives.
- **Sandbox-OK**: Voice channel is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E6-AR-CONNECTED` / `EVE-E6-HOLD`.

### §2.7 — Eve-E7: T0 Watchdog Pre-Arm (20:45 - 21:00 UTC)

- **Time-slot**: 20:45 - 21:00 UTC.
- **Owner**: Operator.
- **Action**: Pre-arm the T0 watchdog: confirm the Cosign-Strict-
  Mode-Readiness-Check daily-cron will NOT run during the T0
  window (window-block per Tag-58 §5 G6 watch-day-pause). Confirm
  the OIDC-Drift-Probe daily-cron similarly held during T0.
- **Sandbox-OK**: Cron schedule inspection is Operator-Hand-
  Sandbox-Gap (read-only `gh api`).
- **Verdict-Marker**: `EVE-E7-WATCHDOG-ARMED` / `EVE-E7-DRIFT`.

### §2.8 — Eve-E8: G1 Wave-Slot Pre-Order (21:00 - 21:30 UTC)

- **Time-slot**: 21:00 - 21:30 UTC.
- **Owner**: Operator + Pilot.
- **Action**: Pre-order the G1 wave activation slots: G1.W1
  (v907_verify, Welle-1), G1.W2 (federation-substrate, Welle-2),
  G1.W3 (persona-engine, Welle-3), G1.W4 (cross-org-resolver,
  Welle-4). Confirm the 5-min spacing per §4 of this document.
- **Sandbox-OK**: Pre-order is doc + diagram. Sandbox-OK.
- **Verdict-Marker**: `EVE-E8-WAVE-ORDER-LOCKED` / `EVE-E8-DRIFT`.

### §2.9 — Eve-E9: G2 Trust-Root Final Freshness (21:30 - 21:45 UTC)

- **Time-slot**: 21:30 - 21:45 UTC.
- **Owner**: Operator.
- **Action**: Final freshness check on the G2 Trust-Root-Snapshot
  files: `fulcio.pub` + `rekor.pub` + `cosign-root.json`
  last-modified within 7 days. If stale: re-pull is Operator-
  Hand-Sandbox-Gap and **must** complete within this slot or T0
  pushes by 24 h.
- **Sandbox-OK**: Read-only freshness check is Sandbox-OK; re-pull
  is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-E9-TRUST-ROOT-FRESH` / `EVE-E9-STALE`.

### §2.10 — Eve-E10: Rollback-Anchor Final-Read (21:45 - 22:00 UTC)

- **Time-slot**: 21:45 - 22:00 UTC.
- **Owner**: Operator + Pilot.
- **Action**: Final read of §7 of this document (Failure-Recovery-
  Triggers) plus `docs/operations/phase-3c-cutover-runbook.md`
  §Rollback. Confirm both Pilot and Operator know the F1 ... F5
  trigger -> action mapping by heart.
- **Sandbox-OK**: Read-only doc inspection. Sandbox-OK.
- **Verdict-Marker**: `EVE-E10-ROLLBACK-MEMORIZED` /
  `EVE-E10-HOLD`.

### §2.11 — Eve-E11: Eve-Verdict Roll-Up (22:00 - 22:30 UTC)

- **Time-slot**: 22:00 - 22:30 UTC.
- **Owner**: Operator + AR pair.
- **Action**: Aggregate E1 ... E10 verdicts. If all 10 are READY
  / CLEAN / FRESH / BRIEFED / CONNECTED / ARMED / LOCKED /
  MEMORIZED: emit `EVE-VERDICT-GO-LAST-MILE`. If any HOLD or
  DRIFT or STALE or RESCHEDULE: emit `EVE-VERDICT-HOLD-LAST-MILE`
  and push T0 by 24 h (AR pair confirms re-schedule).
- **Sandbox-OK**: Aggregate is Sandbox-OK; AR-pair-log entry is
  Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `EVE-VERDICT-GO-LAST-MILE` /
  `EVE-VERDICT-HOLD-LAST-MILE`.

### §2.12 — Eve-E12: Bed-Down (22:30 - 24:00 UTC)

- **Time-slot**: 22:30 - 24:00 UTC.
- **Owner**: Operator (Fred goes to bed; Pilot stays awake).
- **Action**: Operator hands the workstation to Pilot. Pilot
  stays connected to AR-pair voice channel, monitors the
  workstation for any spurious activity until 24:00 UTC. At
  24:00 UTC = 00:00 UTC Monday = T0.0, Pilot opens §3 of this
  document.
- **Sandbox-OK**: Pilot-monitor is read-only. Sandbox-OK.
- **Verdict-Marker**: `EVE-E12-BED-DOWN-CLEAN` / `EVE-E12-DRIFT`.

## §3 — T0.0-Sequence Minute-by-Minute (00:00 - 00:30 UTC)

The Pilot Operator opens this section at **00:00 UTC on Monday
2026-06-08**. The full T0 critical-window is **30 minutes**:
00:00 - 00:30 UTC. Sequenced as ten 3-minute slots T0.0 ...
T0.9.

Every slot declares **Time-slot**, **Owner**, **Action**,
**Sandbox-OK**, and **Verdict-Marker**. **Stop-on-Fail**: any
single slot that misses its verdict triggers the §7 failure-
recovery decision tree.

### §3.1 — T0.0: Window-Open + AR-GO Confirmation (00:00 - 00:03)

- **Time-slot**: 00:00 - 00:03 UTC.
- **Owner**: Pilot + AR pair.
- **Action**: Pilot announces window-open on AR-pair voice
  channel. AR pair confirms `EVE-VERDICT-GO-LAST-MILE` from
  §2.11 still holds (no overnight drift). AR pair signals final
  GO.
- **Sandbox-OK**: Voice + AR-pair-log entry. Operator-Hand-
  Sandbox-Gap.
- **Verdict-Marker**: `T0.0-WINDOW-OPEN` / `T0.0-HOLD`.

### §3.2 — T0.1: G1.W1 Activation (Welle-1 v907_verify) (00:03 - 00:06)

- **Time-slot**: 00:03 - 00:06 UTC.
- **Owner**: Pilot.
- **Action**: Activate G1.W1: wire `cosign verify --strict` into
  the Welle-1 v907_verify Quadlet-service. See §4.1 for the per-
  wave detail.
- **Sandbox-OK**: Quadlet-service mutation is Operator-Hand-
  Sandbox-Gap.
- **Verdict-Marker**: `T0.1-G1-W1-WIRED` / `T0.1-G1-W1-FAIL`.

### §3.3 — T0.2: G1.W2 Activation (Welle-2 federation) (00:06 - 00:09)

- **Time-slot**: 00:06 - 00:09 UTC.
- **Owner**: Pilot.
- **Action**: Activate G1.W2: wire `cosign verify --strict` into
  the Welle-2 federation-substrate Quadlet-service. See §4.2.
- **Sandbox-OK**: Quadlet-service mutation is Operator-Hand-
  Sandbox-Gap.
- **Verdict-Marker**: `T0.2-G1-W2-WIRED` / `T0.2-G1-W2-FAIL`.

### §3.4 — T0.3: G1.W3 Activation (Welle-3 persona-engine) (00:09 - 00:12)

- **Time-slot**: 00:09 - 00:12 UTC.
- **Owner**: Pilot.
- **Action**: Activate G1.W3: wire `cosign verify --strict` into
  the Welle-3 persona-engine Quadlet-service. See §4.3.
- **Sandbox-OK**: Quadlet-service mutation is Operator-Hand-
  Sandbox-Gap.
- **Verdict-Marker**: `T0.3-G1-W3-WIRED` / `T0.3-G1-W3-FAIL`.

### §3.5 — T0.4: G1.W4 Activation (Welle-4 cross-org-resolver) (00:12 - 00:15)

- **Time-slot**: 00:12 - 00:15 UTC.
- **Owner**: Pilot.
- **Action**: Activate G1.W4: wire `cosign verify --strict` into
  the Welle-4 cross-org-resolver Quadlet-service. See §4.4.
- **Sandbox-OK**: Quadlet-service mutation is Operator-Hand-
  Sandbox-Gap.
- **Verdict-Marker**: `T0.4-G1-W4-WIRED` / `T0.4-G1-W4-FAIL`.

### §3.6 — T0.5: G1 Green-Probe (00:15 - 00:18)

- **Time-slot**: 00:15 - 00:18 UTC.
- **Owner**: Pilot.
- **Action**: Run the G1 green-probe across all 4 Wellen +
  Pilot-Persona. Confirm `cosign verify --strict` returns exit-
  code 0 against the placeholder-digest substitution from the
  Tag-56 setup-guide §3.
- **Sandbox-OK**: Read-only cosign-verify is Operator-Hand-
  Sandbox-Gap (binary on operator workstation).
- **Verdict-Marker**: `T0.5-G1-GREEN` / `T0.5-G1-FAIL`.

### §3.7 — T0.6: G2.S1 Trust-Root Pin (00:18 - 00:21)

- **Time-slot**: 00:18 - 00:21 UTC.
- **Owner**: Pilot.
- **Action**: G2.S1: pin the Trust-Root-Snapshot reference into
  the Quadlet-service environment (`WAKIR_TRUST_ROOT_DIR=...`).
  See §5.1.
- **Sandbox-OK**: Env-pin is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `T0.6-G2-S1-PINNED` / `T0.6-G2-S1-FAIL`.

### §3.8 — T0.7: G2.S2 Trust-Root Snapshot-Verify (00:21 - 00:24)

- **Time-slot**: 00:21 - 00:24 UTC.
- **Owner**: Pilot.
- **Action**: G2.S2: verify the pinned trust-root-snapshot is
  byte-identical to the E9 Eve-freshness-check value. See §5.2.
- **Sandbox-OK**: SHA256-compare on operator workstation is
  Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `T0.7-G2-S2-VERIFIED` / `T0.7-G2-S2-FAIL`.

### §3.9 — T0.8: G2.S3 Strict-Mode-Active Probe (00:24 - 00:27)

- **Time-slot**: 00:24 - 00:27 UTC.
- **Owner**: Pilot.
- **Action**: G2.S3: run the Cosign-Strict-Mode-Readiness-Check
  probe against the post-flip state. Expect verdict
  `STRICT-MODE-ACTIVE`. See §5.3.
- **Sandbox-OK**: Read-only probe-run is Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `T0.8-STRICT-MODE-ACTIVE` /
  `T0.8-STRICT-MODE-FAIL`.

### §3.10 — T0.9: T0-Close + AR-Hand-Off (00:27 - 00:30)

- **Time-slot**: 00:27 - 00:30 UTC.
- **Owner**: Pilot + AR pair.
- **Action**: Pilot announces window-close on AR-pair voice
  channel. AR pair signs off `T0-LAST-MILE-DONE`. Pilot logs
  the close-time + verdicts into the AR-pair log. AR pair
  releases Pilot at 00:30 UTC; Operator (Fred) picks up at
  06:00 CEST = 04:00 UTC for the Tag-66 §3.0 Stand-up.
- **Sandbox-OK**: Voice + AR-log entry. Operator-Hand-Sandbox-Gap.
- **Verdict-Marker**: `T0.9-T0-LAST-MILE-DONE` /
  `T0.9-T0-LAST-MILE-HOLD`.

## §4 — G1-Aktivierung pro Welle (4 Wellen, 5 Min Spacing)

The G1 activation is sequenced as **four wave slots** with a
5-minute spacing between activation start times (T0.1 = 00:03,
T0.2 = 00:06 -> note the 3-min slot-grid; the **action-start**
within each slot is locked to the slot-start, so wave-to-wave
elapsed start-time is exactly 3 minutes -> the **5-min spacing**
target collapses to 3-min in the densified Last-Mile grid; this
is intentional). The Pilot drives each wave; the AR pair
monitors.

Per-wave-substance below. Each wave declares the **Quadlet-
file**, the **before/after wiring**, the **probe**, and the
**verdict**.

### §4.1 — G1.W1 Welle-1 v907_verify

- **Quadlet-file**: `infra/persona-engine/quadlets/wave-1-v907-verify.container`.
- **Before-wiring**: `cosign verify` (no `--strict`).
- **After-wiring**: `cosign verify --strict` plus trust-root-dir
  env-var reference (G2 pin).
- **Probe**: `systemctl --user start wave-1-v907-verify.service`
  on operator workstation; confirm `cosign verify --strict`
  exit-code 0 in service-log.
- **Verdict**: `G1-W1-WIRED-GREEN` / `G1-W1-FAIL`.
- **Sandbox-boundary**: Quadlet-file mutation + systemctl-start =
  Operator-Hand-Sandbox-Gap.

### §4.2 — G1.W2 Welle-2 federation-substrate

- **Quadlet-file**: `infra/persona-engine/quadlets/wave-2-federation.container`.
- **Before-wiring**: `cosign verify` (no `--strict`).
- **After-wiring**: `cosign verify --strict` plus trust-root-dir
  env-var reference.
- **Probe**: `systemctl --user start wave-2-federation.service`;
  confirm strict-verify exit-code 0.
- **Verdict**: `G1-W2-WIRED-GREEN` / `G1-W2-FAIL`.
- **Sandbox-boundary**: Operator-Hand-Sandbox-Gap.

### §4.3 — G1.W3 Welle-3 persona-engine

- **Quadlet-file**: `infra/persona-engine/quadlets/wave-3-persona-engine.container`.
- **Before-wiring**: `cosign verify` (no `--strict`).
- **After-wiring**: `cosign verify --strict` plus trust-root-dir
  env-var reference.
- **Probe**: `systemctl --user start wave-3-persona-engine.service`;
  confirm strict-verify exit-code 0.
- **Verdict**: `G1-W3-WIRED-GREEN` / `G1-W3-FAIL`.
- **Sandbox-boundary**: Operator-Hand-Sandbox-Gap.

### §4.4 — G1.W4 Welle-4 cross-org-resolver

- **Quadlet-file**: `infra/persona-engine/quadlets/wave-4-cross-org-resolver.container`.
- **Before-wiring**: `cosign verify` (no `--strict`).
- **After-wiring**: `cosign verify --strict` plus trust-root-dir
  env-var reference.
- **Probe**: `systemctl --user start wave-4-cross-org-resolver.service`;
  confirm strict-verify exit-code 0.
- **Verdict**: `G1-W4-WIRED-GREEN` / `G1-W4-FAIL`.
- **Sandbox-boundary**: Operator-Hand-Sandbox-Gap.

## §5 — G2-Aktivierung post-G1-Green

G2 activates only after **G1 green-probe in §3.6 (T0.5) passes**.
Three sub-steps S1, S2, S3 sequenced within T0.6 ... T0.8.

### §5.1 — G2.S1 Trust-Root-Pin

- **Action**: Pin the `WAKIR_TRUST_ROOT_DIR` env-var into each
  of the four Welle-Quadlet-service-files plus the Pilot-Persona
  Quadlet. The pin references the operator-workstation directory
  carrying the SHA256-verified `fulcio.pub` + `rekor.pub` +
  `cosign-root.json`.
- **Verdict**: `G2-S1-PINNED` / `G2-S1-FAIL`.
- **Sandbox-boundary**: Quadlet env-var mutation =
  Operator-Hand-Sandbox-Gap.

### §5.2 — G2.S2 Snapshot-Verify

- **Action**: SHA256-compare the pinned-directory content against
  the Eve-E9 freshness-check baseline (logged into AR-pair log
  at 21:45 UTC Eve). Byte-identical hash -> verdict pass; any
  diff -> verdict fail and F4 trigger fires (see §7).
- **Verdict**: `G2-S2-VERIFIED` / `G2-S2-FAIL`.
- **Sandbox-boundary**: SHA256 + diff = Operator-Hand-Sandbox-Gap.

### §5.3 — G2.S3 Strict-Mode-Active Probe

- **Action**: Run the Cosign-Strict-Mode-Readiness-Check probe
  against the post-G1-W4 + post-G2-S2 state. Expected verdict:
  `STRICT-MODE-ACTIVE`. Any other verdict (`STRICT-MODE-DRIFT`,
  `STRICT-MODE-DEFECT`) -> F5 trigger fires (see §7).
- **Verdict**: `G2-S3-STRICT-MODE-ACTIVE` / `G2-S3-FAIL`.
- **Sandbox-boundary**: Read-only probe = Operator-Hand-Sandbox-Gap.

## §6 — Verification-Sequence

Six verification probes V1 ... V6 layered on top of the §3 main
sequence. V1 ... V4 are **per-wave** (run inline at the end of
each G1.W_n slot); V5 + V6 are **post-T0** (run between 00:30
UTC close and 04:00 UTC Tag-66 §3.0 Stand-up).

### §6.1 — V1 G1-W1 Inline-Verify

- **Run-at**: end of T0.1 (00:06 UTC).
- **Action**: Pilot confirms G1.W1 service-log shows strict-
  verify exit 0. If fail: F1 trigger.
- **Verdict**: `V1-GREEN` / `V1-FAIL`.

### §6.2 — V2 G1-W2 Inline-Verify

- **Run-at**: end of T0.2 (00:09 UTC).
- **Action**: As V1 but for G1.W2.
- **Verdict**: `V2-GREEN` / `V2-FAIL`.

### §6.3 — V3 G1-W3 Inline-Verify

- **Run-at**: end of T0.3 (00:12 UTC).
- **Action**: As V1 but for G1.W3.
- **Verdict**: `V3-GREEN` / `V3-FAIL`.

### §6.4 — V4 G1-W4 Inline-Verify

- **Run-at**: end of T0.4 (00:15 UTC).
- **Action**: As V1 but for G1.W4.
- **Verdict**: `V4-GREEN` / `V4-FAIL`.

### §6.5 — V5 Cross-Wave Sanity Probe

- **Run-at**: 00:35 UTC (5 min post-close).
- **Action**: Pilot reads the four Welle-Quadlet-service-logs
  inline and confirms no spurious strict-verify failures occurred
  after activation. Logs to AR-pair log.
- **Verdict**: `V5-GREEN` / `V5-FAIL`.

### §6.6 — V6 Eve-vs-T0 Drift Audit

- **Run-at**: 03:00 UTC (3 h post-close, AR pair handover slot).
- **Action**: AR pair compares the Eve-E11 GO verdict vs. the T0
  V1 ... V5 verdicts. Confirms no silent drift introduced into
  the operator workstation overnight or during T0.
- **Verdict**: `V6-NO-DRIFT` / `V6-DRIFT-DETECTED`.

## §7 — Failure-Recovery-Triggers

Five failure-recovery decision triggers F1 ... F5 mapped to
specific T0 slot fails. Each trigger declares **Trigger-
condition**, **Recovery-action**, **Time-budget**, and **Fall-
back-pin**.

### §7.1 — F1: G1.W_n Wave-Wire-Fail

- **Trigger-condition**: Any of T0.1 / T0.2 / T0.3 / T0.4 reports
  `G1-W_n-FAIL`.
- **Recovery-action**: Pilot reverts the failed Welle's Quadlet-
  file to pre-wiring state. Pilot does **not** continue to next
  Welle; instead announces F1-trigger on AR-pair voice channel.
  AR pair decides: (a) full T0 abort, push T0 by 24 h, OR (b)
  partial-T0 close with the wired Wellen kept (only valid if
  the failed Welle is Welle-4).
- **Time-budget**: 5 min from trigger to AR decision.
- **Fall-back-pin**: Pre-T0 main-tip commit; Welle-quadlet-file
  reverts via `git checkout`.

### §7.2 — F2: G1 Green-Probe Fail (T0.5)

- **Trigger-condition**: T0.5 reports `T0.5-G1-FAIL`.
- **Recovery-action**: Pilot enumerates which Wellen failed (V1
  ... V4 verdicts); reverts only those Wellen. AR pair decides
  full vs. partial abort.
- **Time-budget**: 8 min from trigger to AR decision.
- **Fall-back-pin**: Pre-T0 main-tip commit; per-Welle revert.

### §7.3 — F3: G2.S1 Trust-Root-Pin Fail

- **Trigger-condition**: T0.6 reports `T0.6-G2-S1-FAIL` (env-var
  pin failed, e.g. directory not readable or wrong permissions).
- **Recovery-action**: Pilot diagnoses the file-system issue;
  fixes only if recoverable within 3 min; else announces F3-
  trigger; AR pair triggers full T0 abort + push.
- **Time-budget**: 3 min recovery + 2 min AR decision.
- **Fall-back-pin**: G1 wiring stays (it is independent of G2);
  trust-root-pin is the only revert.

### §7.4 — F4: G2.S2 Snapshot-Verify Fail

- **Trigger-condition**: T0.7 reports `T0.7-G2-S2-FAIL`
  (SHA256-mismatch vs. Eve-E9 baseline).
- **Recovery-action**: **Hard-abort**. SHA256-mismatch is a trust-
  chain integrity violation; no partial close is valid. Pilot
  reverts G1 + G2 to pre-T0 state, announces F4-trigger, AR pair
  signs off full abort + 24 h push.
- **Time-budget**: 5 min for revert + AR sign-off.
- **Fall-back-pin**: Pre-T0 main-tip commit; full revert.

### §7.5 — F5: G2.S3 Strict-Mode-Active Probe Fail

- **Trigger-condition**: T0.8 reports `T0.8-STRICT-MODE-FAIL`.
- **Recovery-action**: Pilot enumerates which sub-condition failed
  (cosign-verify exit non-zero, trust-root not found, env-var
  unset, ...). If recoverable within 5 min: fix-forward; else
  F5-trigger -> AR full-abort decision.
- **Time-budget**: 5 min fix-forward window + 2 min AR decision.
- **Fall-back-pin**: G1 + G2 revert to pre-T0 main-tip commit.

## §8 — Cross-References + Sandbox-Boundary

### §8.1 — Cross-References

- **Tag-56 G1+G2 Operator-Setup-Guide**:
  `docs/operations/cosign-g1-g2-operator-setup.md` — the multi-
  week prep that this Last-Mile-Checklist densifies into the
  Eve + T0 window.
- **Tag-58 Strict-Flip Readiness-Map**:
  `docs/operations/strict-flip-readiness-map-tag58.md` — the
  7-day calendar map that brackets the Last-Mile.
- **Tag-62 Bulk-Aktivierungs-Recipe**:
  `docs/operations/bulk-activation-pre-walk-recipe.md` — the
  post-T0 bulk-wiring at T0+0.5 = 04:00 UTC.
- **Tag-66 Cutover-Eve-Final-Recipe**:
  `docs/operations/operator-hand-cutover-eve-final-recipe.md` —
  the day-by-day plan that includes T0+0 stand-up at 06:00 CEST.
- **Tag-67 Eve-Recipe-Dry-Run**:
  `tooling/ci/dry_run_operator_eve_recipe.py` — hermetic dry-run
  probe; companion to this Last-Mile-Checklist for E1 ... E12
  verdict shape.
- **Tag-68 Strict-Flip-Map-Refresh §10**:
  `docs/operations/strict-flip-readiness-map-tag58.md` §10 —
  the carry-forward update that landed in PR #435; this Last-
  Mile-Checklist references the §10-updated gate-status table.
- **Phase-3c Cutover-Runbook**:
  `docs/operations/phase-3c-cutover-runbook.md` — the master
  cutover-runbook that holds the §Rollback section.
- **ADR-0020**: Container-Orchestration (Compose-First-Pfad +
  Operator-Hand-Sandbox-Boundary).
- **ADR-0036**: Migrations-Sequenz-Disziplin (10-Schritte-Plan).
- **ADR-0061**: Strict-Mode-Readiness-Check.
- **ADR-0065**: AR-Hand-Cutover-Day-Morgen-Override-Flag.
- **ADR-0066**: Walking-Skeleton Post-Activate-Verify.

### §8.2 — Sandbox-Boundary

| Action class | Sandbox-OK | Operator-Hand-Sandbox-Gap |
|---|---|---|
| Read-only `cosign version` | yes | no |
| `cosign initialize` | no | yes |
| Read-only `cosign verify --strict` log inspection | yes | no |
| Quadlet-file mutation | no | yes |
| `systemctl --user start` | no | yes |
| Env-var read in operator-shell | no | yes |
| Env-var read in Mira-Sandbox | yes (always-unset) | no |
| SHA256-compare on operator workstation | no | yes |
| AR-pair voice channel | no | yes |
| AR-pair-log entry | no | yes |
| `gh api` snapshot read | no | yes |
| `gh api PUT` | **forbidden in Mira-Sandbox** | yes |
| Read-only doc inspection (this file) | yes | no |
| Cron-schedule inspection | no | yes |
| Workflow_dispatch trigger | no | yes |

Every active step in §2, §3, §4, §5, §6, §7 of this document is
flagged **Operator-Hand-Sandbox-Gap** at the slot level. The
Mira-Sandbox produced this document; the Operator + Pilot +
AR pair execute it on the operator workstation. No exception.

This document is **doc-form-only**: producing the markdown is
Sandbox-OK; executing the procedure is Operator-Hand-Sandbox-Gap.

---

— Kai (Tag-69, 2026-05-19)
