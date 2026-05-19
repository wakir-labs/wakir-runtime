# Pre-Cutover-Watch-Day Spec (Tag-54)

**Owner:** Noa Bergstroem (SRE).
**Status:** approved — operator-facing spec for the Day-1 pre-cutover
watch shift (the calendar day immediately preceding any KW-24..27
Welle-Cutover-Mittwoch per ADR-0066 §Cutover-Plan).
**Anchors:**

- ADR-0066 §Cutover-Plan — Welle-Mittwoch-Cadence (KW-24..27).
- ADR-0066 §Mitigation-1 — Doppel-Welle KW-26.
- ADR-0066 §Mitigation-2 — Cross-Welle-Coordination-Test on-stream.
- ADR-0065 §AR-Hand-Gate — Pre-Cutover-Probe-Stability pre-condition.
- ADR-0025 — SRE Performance-Mess-Anker (Output-Disziplin).

---

## 1. Purpose and scope

This document is the **Pre-Cutover-Watch-Day spec**: the operator
playbook for the calendar day **immediately before** any planned
Welle-Cutover (Cutover-Mittwoch). It is the bridge between the
Tag-53 pre-cutover-final-sanity-gate (a CI verdict at T-1d) and the
Tag-41 cutover-day-watch-runbook (the live-stream watch on the
Cutover-Mittwoch morning).

**In scope (Watch-Day = D-1, typically Tuesday for a Wednesday
cutover):**

1. Activation checklist for *all* Tag-N dashboards and alert-rules
   that must be green and scraping by D-1 18:00 CEST.
2. The Watch-Day operator-procedure (08:00-18:00 CEST, six checkpoint
   slots).
3. Escalation-path list (named persona, channel, expected response
   time per severity class).
4. Pre-Cutover-Drift-Triage steps for the three drift-types the
   D-1 surface can show.
5. AR-Hand-Stop conditions that abort the cutover before the
   Wednesday morning live-stream-watch ever starts.

**Out of scope:**

- The Cutover-Mittwoch live-stream watch itself — covered by
  `docs/observability/cutover-day-watch-runbook.md`.
- The CI verdict logic — covered by
  `docs/ci/pre-cutover-final-sanity-gate-runbook.md`.
- Per-Welle hot-spot probe deep-dives — covered by the per-Welle
  hot-spot-probe-runbook files under `docs/ci/`.
- WAT-anchor SLO definitions — owned by Tomas via Zone-I; this doc
  consumes those SLOs, does not redefine them.

**Why this is its own document (not folded into the Cutover-Day
runbook):** the Watch-Day has a fundamentally different question
("are we ready to start the cutover tomorrow?") from the
Cutover-Day ("is the cutover-in-progress drifting?"). Conflating
the two has historically caused operator-cognitive-load spikes; the
Tag-53 pre-cutover-final-sanity-gate-runbook touches the CI gate
piece, but does not cover the human watch-shift on D-1. This doc
fills that gap.

---

## 2. Watch-Day calendar position

For each Welle in the ADR-0066 cutover plan, the Watch-Day is:

| Cutover-Mittwoch | Welle(s) | Watch-Day (D-1) | Watch-Day operator-on-call |
|---|---|---|---|
| KW-24 Wed | Welle-1 + Welle-2 (parallel) | KW-24 Tue | Noa (primary) + Kai (substrate-backup) |
| KW-25 Wed | Welle-3 (solo, Henrik-caution) | KW-25 Tue | Noa (primary) + Henrik (audit-shadow) |
| KW-26 Wed | Welle-4 + Welle-5 (parallel) | KW-26 Tue | Noa (primary) + Tomas (WAT-cross-review) |
| KW-27 Wed | Welle-6 + Welle-7 (parallel) | KW-27 Tue | Noa (primary) + Kai (substrate-backup) |

The Watch-Day starts **08:00 CEST** and ends **18:00 CEST**. After
18:00 the Cutover-Mittwoch starts at **06:30 CEST** the next day
per the Tag-41 cutover-day-watch-runbook; the gap 18:00..06:30 is
**deliberately unwatched** — anything that breaks overnight is
caught by the 06:00 CEST pre-flight checklist in §3.2 of the
Tag-41 runbook.

---

## 3. Dashboard and alert activation checklist (must be green by D-1 18:00 CEST)

This is the canonical inventory of every Tag-N observability
artefact the operator confirms scraping and rendering on D-1.
Each row carries an explicit "operator-question" — the single
question that artefact must answer. No metric sprawl, no Vanity
Dashboard.

### 3.1 Dashboards (Grafana)

| # | Dashboard UID | Operator-Question | Source-Anchor |
|---|---|---|---|
| D1 | `wakir-phase-3-marathon-slo-final` | Are all 7 Marathon-SLOs in compliance? | Tag-52 SLO-final dashboard |
| D2 | `wakir-phase-3c-cutover-day-live-stream` | (sleeping, prepped) Will the live-stream aggregator render on Wed morning? | Tag-41 cutover-day dashboard |
| D3 | `wakir-phase-3c-cross-welle-coordination` | Per-Welle pre-cutover-probe verdict trend? | Tag-42 cross-welle dashboard |
| D4 | `wakir-per-welle-trend-heatmap` | Per-Welle drift heatmap over trailing 24h? | Tag-31 per-Welle heatmap |
| D5 | `wakir-persona-engine-backend-decisions` | Persona-engine backend-decision health? | Tag-30 backend-decision dashboard |
| D6 | `wakir-persona-engine-health` | Persona-engine liveness/readiness baseline? | Tag-15 persona-engine-health |
| D7 | `wakir-persona-engine-phase-3c-welle-status` | Per-Welle state-machine state? | Tag-32 welle-status dashboard |
| D8 | `wakir-persona-engine-routing-decisions` | Routing-decision distribution baseline? | Tag-15 routing-decisions |
| D9 | `wakir-wat-anchor-latency-histograms` | WAT-anchor pipeline latency? | Tag-15 WAT (Tomas-owned, consumed) |
| D10 | `wakir-persona-engine-cost-cache` | Cost-burn trajectory (info-only)? | Tag-15 cost-cache (Daniel-owned) |

Acceptance per dashboard:

- Dashboard loads in < 5 s (operator browser).
- All panels render with data (no "N/A" / "No Data" for time-windows
  inside the trailing 24h).
- The dashboard-UID is bookmarked in the Watch-Day operator browser
  with no auth-prompt blocking.

### 3.2 Alert-rule groups (Prometheus + AlertManager)

| # | Alert-rule file | Operator-Question | Source-Anchor |
|---|---|---|---|
| A1 | `dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml` | Multi-window multi-burn-rate alerts for SLO-1..7? | Tag-53 SLO burn-rate alerts |
| A2 | `dashboards/phase-3-marathon-alerts.yaml` | Tag-40 event-based phase-3-marathon alerts? | Tag-40 marathon alerts |

Acceptance per alert-rule group:

- `promtool check rules <file>` exits 0 against the file on D-1.
- The rule-group is loaded in the running Prometheus
  (`/api/v1/rules` returns the group name).
- Every rule in the group has at least one firing-target
  Prometheus-series in the last 6 h (i.e., the metric the rule
  evaluates *exists* — not "the alert is firing", but "the alert
  is *evaluable*"). A rule against a non-existent series is a
  dead-rule and counts as **not-active**.

### 3.3 Pre-Cutover-Probe verdicts (per Welle, file-side)

| # | File pattern | Operator-Question |
|---|---|---|
| P1 | `reports/live-vm/YYYY-MM-DD-welle-N-pre-cutover-probe.md` | Did the per-Welle probe write a verdict for D-1? |
| P2 | `reports/audit/henrik-pre-audit-signoffs.json` | Is the Henrik-pre-audit-signoff for the cutover-Welle(s) present? |

Acceptance: for each cutover-Welle scheduled for tomorrow, the D-1
probe-report file exists, is non-empty, and its `verdict` field is
either `GREEN` or `AMBER`. RED on D-1 is an automatic
AR-Hand-Stop-Trigger (see §6).

### 3.4 CI gates (Tag-53 pre-cutover-final-sanity-gate)

| # | Workflow | Operator-Question |
|---|---|---|
| C1 | `.github/workflows/pre-cutover-final-sanity-gate.yml` | Did the T-1d CI gate verdict come back GREEN? |
| C2 | `.github/workflows/image-build-reproducibility-daily.yml` | Did the 15-binary build-reproducibility daily come back GREEN? |

Acceptance: the most recent run on the cutover-target branch is
`success`, completed within the trailing 24 h, and its summary
verdict (parsed via the Tag-53 aggregator) is GREEN.

---

## 4. Watch-Day procedure (08:00-18:00 CEST)

Six checkpoint slots, two-hour cadence. Each slot has a fixed
agenda; the operator does **not** improvise (anti-Alert-Fatigue
discipline). Deviations are logged in the Watch-Day journal.

### 4.1 08:00 CEST — Watch-Day Pre-Flight (90 min slot)

1. Open the ten dashboards from §3.1 in tabs. Confirm each renders.
2. Run `promtool check rules` against the two alert-rule files in
   §3.2 from the current cutover-target branch tip. Confirm exit 0.
3. Query Prometheus `/api/v1/rules` and confirm both groups loaded.
4. Check that the most recent run of C1 and C2 (Tag-53 gate + image-
   build-reproducibility-daily) is `success` in the trailing 24 h.
5. For each cutover-Welle scheduled for tomorrow, confirm the D-1
   pre-cutover-probe report file exists and verdict is GREEN/AMBER.
6. Write the 08:00 checkpoint entry to the Watch-Day journal:
   `${WATCH_STATE_DIR}/watch-day-journal.jsonl`, one JSON object,
   with `slot=08`, the dashboard / alert / probe pass/fail tally,
   and the operator-name.

If any of D1..D10, A1..A2, P1, C1, C2 fail at 08:00: **the
Watch-Day enters drift-triage** (§5) and stays there until either
the failure is resolved or an AR-Hand-Stop is triggered (§6).

### 4.2 10:00 CEST — SLO-Burn-Rate snapshot

1. On dashboard D1, screenshot the SLO-1..SLO-7 panels.
2. Compute the burn-rate-budget-remaining per SLO over the trailing
   30-day window. The Tag-53 burn-rate alert file embeds the
   formulas; the dashboard already renders them.
3. Log the snapshot to the journal (`slot=10`).
4. **No action** unless any SLO has burnt > 50 % of its 30-day
   budget in the trailing week; that is a Pre-Cutover-Drift-Triage
   trigger (§5).

### 4.3 12:00 CEST — Drift-Heatmap & per-Welle health

1. On dashboard D4 (`wakir-per-welle-trend-heatmap`), screenshot
   the 24 h heatmap for each cutover-Welle scheduled tomorrow.
2. On dashboard D7 (welle-status), confirm each cutover-Welle is in
   the expected pre-cutover state-machine state per ADR-0066.
3. Log the snapshot to the journal (`slot=12`).
4. **No action** unless heatmap shows a Welle with > 5 RED cells in
   the trailing 24 h or D7 reports an unexpected state. Either is
   a §5 drift-triage trigger.

### 4.4 14:00 CEST — WAT-anchor pipeline health (Zone-I, Tomas-owned, Noa-watch)

1. On dashboard D9 (WAT-anchor-latency-histograms), screenshot the
   trailing-24h p50 / p95 / p99 anchor-latency.
2. Compare against the Tomas-owned WAT-SLOs in
   `docs/observability/sli-slo-wat-phase-2.md`. **Read-only.**
3. Log the snapshot to the journal (`slot=14`).
4. If WAT-pipeline is in regression at the 14:00 slot: **Zone-I
   escalation** to Tomas (§6.3) — Noa does not triage WAT-internal
   issues, Tomas owns the call.

### 4.5 16:00 CEST — Final Re-Check & Cutover-GO/NO-GO recommendation

1. Re-open all ten dashboards. Confirm each still renders.
2. Re-confirm both alert-rule groups loaded in Prometheus
   (`/api/v1/rules`).
3. Compute the Watch-Day-Verdict per the §7 verdict-formula.
4. Log the verdict to the journal (`slot=16`), include the
   verdict-string `GREEN` / `AMBER` / `RED`.
5. GREEN: cutover proceeds tomorrow morning per Tag-41 runbook.
6. AMBER: cutover proceeds, **but the operator notifies Mira** via
   the standard Mira-Notify channel before 18:00; Mira decides
   GO / NO-GO at her own discretion. AMBER does **not** auto-pause.
7. RED: cutover **does not** proceed; AR-Hand-Stop (§6) is invoked.

### 4.6 18:00 CEST — Watch-Day Close-Out

1. Write the Watch-Day-Close-Out entry to the journal (`slot=18`),
   include the verdict, the operator-name, and any open follow-up
   items the next-morning operator (Cutover-Day-Watch primary)
   needs to know.
2. Tar the `${WATCH_STATE_DIR}` directory into
   `${HOME}/watch-day-$(date +%Y%m%d).tar.gz`.
3. Push the journal entry into the Henrik-audit-log:
   `echo "$(date -Is) watch-day verdict=$VERDICT operator=$OPERATOR" >> /var/lib/wakir/audit/watch-day.log`.

After 18:00, the Watch-Day is closed. Overnight is unwatched (see
§2 rationale).

---

## 5. Pre-Cutover-Drift-Triage steps

Three drift-types the Watch-Day surface can show. Each has a
deterministic triage-flow; Noa does not improvise during a triage.

### 5.1 Drift-type A: Dashboard or alert-rule **inactive**

Symptom: a §3.1 dashboard fails to render, or a §3.2 alert-rule
group is missing from `/api/v1/rules`, or `promtool check rules`
exits non-zero.

Triage:

1. Is the failing artefact in Kai's substrate-domain (Prometheus
   config, Grafana config, scrape-target)? — Zone-H escalation to
   Kai (§6.2).
2. Is the failing artefact in Noa's domain (alert-rule expression,
   dashboard JSON, recording-rule)? — Noa-Hand fix on the cutover-
   target branch. The fix is a single-purpose PR; if the fix
   cannot land within 4 h, the Watch-Day-Verdict goes RED.

### 5.2 Drift-type B: SLO **burn-rate excess**

Symptom: any SLO has burnt > 50 % of its 30-day budget in the
trailing week, **or** the Tag-53 fast-burn-rate alert is currently
firing for any SLO.

Triage:

1. Which SLO? Look at the dashboard D1 SLO-N panel.
2. Is it a Welle-specific SLO (SLO-1) for a cutover-Welle scheduled
   tomorrow? — that is a **direct cutover-blocker**; Watch-Day-
   Verdict goes RED immediately and AR-Hand-Stop (§6) is invoked.
3. Is it a hard-zero SLO (SLO-2, SLO-5, SLO-6, SLO-7)? — that is a
   **direct cutover-blocker**; Watch-Day-Verdict goes RED
   immediately and AR-Hand-Stop is invoked.
4. Is it an informational SLO (SLO-3 alert-volume-trend, SLO-4
   AR-Hand-Stop-trigger-rate)? — no auto-block; log to journal,
   notify Mira via the standard Mira-Notify channel.

### 5.3 Drift-type C: Per-Welle pre-cutover-probe **RED verdict**

Symptom: any §3.3 P1 probe-report file for a cutover-Welle has
verdict `RED`.

Triage:

1. RED on D-1 is **non-negotiable**: AR-Hand-Stop (§6) is invoked.
   Cutover does **not** proceed tomorrow.
2. The RED-verdict triggers a per-Welle hot-spot-probe-runbook
   deep-dive (see `docs/ci/welle-N-hot-spot-probe-runbook.md` for
   the cutover-Welle in question). That deep-dive is owned by
   whoever owns the Welle-component (per the Welle-N component-map
   in ADR-0066).

---

## 6. Escalation-path list

Named persona, channel, expected response-time. **No anonymous
escalation, no "wakir-ops"-mail-alias.** Severity is the operator
judgment per §5; the channel is fixed per persona.

### 6.1 Severity-class P (Page): immediate, < 15 min response

| Trigger | Persona | Channel | SLA |
|---|---|---|---|
| Watch-Day-Verdict RED | Mira (CEO) | Mira-Notify push high-priority | 15 min |
| AR-Hand-Stop invoked | Mira → AR | Mira-Notify push critical | 15 min |
| Hard-zero SLO breached | Mira (CEO) + Priya (CTO) | Mira-Notify push high-priority | 15 min |

### 6.2 Severity-class T (Ticket): < 4 h response

| Trigger | Persona | Channel | SLA |
|---|---|---|---|
| Drift-type A (Kai-domain) | Kai (Container-Infra) | inbox/kai/ + Mira-Notify medium | 4 h |
| Drift-type A (Noa-domain) | Noa (self-hand) | self, single-purpose PR | 4 h |
| WAT-pipeline regression | Tomas (WAT-owner) | inbox/tomas/ + Mira-Notify medium | 4 h |
| Drift-type B informational | Mira (CEO, info) | inbox/mira/ + Mira-Notify low | next biz-day |

### 6.3 Zone-H / Zone-I cross-review escalation

For any Watch-Day finding that crosses domain-boundaries:

- **Zone-H (SRE x Kai-Container-Operations):** Kai is the substrate-
  owner. Noa describes the finding, Kai owns the fix. Joint review
  before the fix lands on the cutover-target branch.
- **Zone-I (SRE x Tomas-WAT-Pipeline):** Tomas is the WAT-owner.
  Noa describes the finding, Tomas owns the fix and the SLO
  re-calibration if any. Aisha protocols the Zone-I cross-review
  outcome to the audit-archive.

### 6.4 What Noa does **not** escalate (anti-eskalations-drift)

- A single AMBER probe-verdict (not RED). Logged to journal,
  watched at the next slot; no escalation.
- A single alert firing for < 5 min (single-window). Burn-rate
  alerts are intentionally multi-window so they only escalate on
  sustained signal.
- Cost-trajectory drift. Daniel (CFO) owns cost; Noa does not page
  Daniel on cost (Daniel's own dashboards page him).

---

## 7. Watch-Day-Verdict formula

The Watch-Day-Verdict at the 16:00 slot is computed
deterministically. No "operator gut-feel" override; if the operator
wants to override, that is an AR-Hand-Stop conversation (§6.1),
not a verdict-flip.

```
verdict = GREEN  iff   all of:
                       - every dashboard D1..D10 rendered in §4.1 and §4.5
                       - every alert-rule group A1..A2 loaded and evaluable
                       - every D-1 probe-verdict P1 in {GREEN}
                       - both CI gates C1, C2 GREEN within 24h
                       - no SLO burn-rate alert firing for a hard-zero SLO
                       - no SLO-1 fast-burn-rate alert firing for a tomorrow-cutover-Welle

verdict = AMBER  iff   not GREEN, and none of:
                       - any D-1 probe-verdict P1 == RED
                       - any hard-zero SLO breached
                       - any SLO-1 fast-burn for a tomorrow-cutover-Welle
                       - either CI gate C1, C2 missing or non-success in trailing 24h

verdict = RED    iff   any of the AMBER-blockers above is true
```

The verdict is logged at slot=16 in the journal, then re-confirmed
at slot=18 in the close-out entry.

---

## 8. State-directory layout

```
${WATCH_STATE_DIR}/
    watch-day-journal.jsonl       # append-only, six slot-entries
    snapshots/
        slot-08-dashboards/       # screenshot dump
        slot-10-slo-burn-rate/    # screenshot dump
        slot-12-heatmap/          # screenshot dump
        slot-14-wat/              # screenshot dump
        slot-16-final/            # screenshot dump + verdict.txt
    verdict.txt                   # final verdict, one line: GREEN|AMBER|RED
```

The directory is the artefact handed off to the Cutover-Day
operator-on-call at 18:00 CEST. The Cutover-Day operator's
06:00 CEST pre-flight checklist (Tag-41 runbook §3.1) opens
`verdict.txt` first and aborts the live-stream-watch start if it
reads RED.

---

## 9. Anti-Alert-Fatigue discipline

Per ADR-0025 Noa-Performance-Mess-Anker:

- The six slots are **fixed**. No improvised checks between slots
  except when triggered by an actual page (§6.1).
- The Watch-Day operator does **not** ad-hoc-tune any threshold
  during the shift. Threshold-tuning is a separate Noa-persona-
  definition-change, performed cold between Watch-Days.
- The journal-entry per slot is **strictly templated** (JSON
  schema in §10). Free-form prose is captured in a `notes` field,
  not in the verdict-decision-fields.

---

## 10. Journal-entry schema

Each slot writes one JSON object to
`${WATCH_STATE_DIR}/watch-day-journal.jsonl` with the following
required fields:

```json
{
  "slot": "08",
  "timestamp_iso": "2026-06-09T08:00:00+02:00",
  "operator": "noa",
  "cutover_welle": ["welle-1", "welle-2"],
  "dashboards_pass_count": 10,
  "dashboards_fail_count": 0,
  "alerts_pass_count": 2,
  "alerts_fail_count": 0,
  "probes_pass_count": 2,
  "probes_fail_count": 0,
  "ci_gate_c1": "success",
  "ci_gate_c2": "success",
  "verdict": null,
  "notes": ""
}
```

The final-slot entry (slot=16 and slot=18) carries `verdict` in
`{"GREEN", "AMBER", "RED"}`. Earlier-slot entries carry
`verdict: null`.

---

## 11. Anchors and references

- ADR-0066 §Cutover-Plan, §Mitigation-1, §Mitigation-2.
- ADR-0065 §AR-Hand-Gate.
- ADR-0025 SRE Performance-Mess-Anker.
- `docs/observability/cutover-day-watch-runbook.md` — Tag-41,
  successor-doc for the Cutover-Mittwoch morning.
- `docs/observability/sli-slo-phase-3-marathon.md` — Tag-52 SLO
  catalogue, SLI-MARATHON-1..7.
- `docs/observability/pre-cutover-probe-dashboard.md` — Tag-42
  per-Welle pre-cutover-probe dashboard.
- `docs/ci/pre-cutover-final-sanity-gate-runbook.md` — Tag-53 CI
  gate.
- `docs/ci/welle-N-hot-spot-probe-runbook.md` — per-Welle hot-spot
  probe deep-dives.
- `dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml` — Tag-53
  burn-rate alerts.
- `dashboards/phase-3-marathon-alerts.yaml` — Tag-40 event-based
  alerts.

— Noa
