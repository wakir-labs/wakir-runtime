# Pre-Cutover-Probe-Dashboard (Tag-42 Noa-SRE)

Operator-Doku zum Pre-Cutover-Probe-Phase-Observability-Block im
Grafana-Dashboard
`dashboards/phase-3c-cross-welle-coordination.json` (Panels 200-299).

## Zweck

Während der Pre-Cutover-Phase (typisch 3 Tage pro Welle) gibt das
Dashboard dem Operator und dem Aufsichtsrat eine Antwort auf die
Frage **"ist die Welle bereit für den Cutover?"** ohne in
sieben Welle-spezifische Dashboards springen zu müssen.

Anker:

- ADR-0066 §AR-Hand-Gate — Pre-Cutover-Probe-Stabilität ist
  Pre-Condition für AR-Hand-Sign-Off.
- ADR-0065 §Cutover-Plan — definiert die sieben Welle-Reihenfolge.
- PR #267 (Reza Tag-41) — Welle-1 Pre-Cutover-Sanity-Probe
  Referenz-Implementierung (Verdict-Schema).

## Datenfluss

```
welle-N-pre-cutover-probe.sh
        │
        ▼  schreibt
reports/live-vm/YYYY-MM-DD-welle-N-pre-cutover-probe.md
        │
        ▼  konsumiert
scripts/observability/pre-cutover-probe-failure-rate-tracker.py
        │
        ▼  emittiert
/var/lib/prometheus/node-exporter/wakir_pre_cutover_probe.prom
        │
        ▼  scrape
Prometheus  ──►  Grafana  ──►  Panel 201-299
```

Daneben:

- `reports/audit/henrik-pre-audit-signoffs.json` — Henrik-Pre-Audit-
  Sign-Off-Records (Tag-39 + Tag-40-Output).

## Panels im Überblick

| Panel-ID | Typ | Titel | Datenquelle |
|---|---|---|---|
| 200 | row | Pre-Cutover-Probe-Phase-Observability (Welle-1..7) | – |
| 201-207 | stat | Welle-N Pre-Cutover-Probe Verdict | `wakir_pre_cutover_probe_verdict{welle="welle-N"}` |
| 210 | row | Per-Welle Probe-Verdict-Historie | – |
| 211 | timeseries | Probe-Verdict-Historie (alle 7 Wellen) | `wakir_pre_cutover_probe_verdict` |
| 212 | bargauge | Stability-Score (Consecutive-GREEN, Threshold = 3) | `wakir_pre_cutover_probe_stability_consecutive_green` |
| 220 | row | Marathon-Readiness-Aggregate-Gauge | – |
| 221 | gauge | Marathon-Readiness-Score (0-100%) | `wakir_marathon_readiness_score` |
| 222 | table | Marathon-Readiness Breakdown per Welle | mehrere |
| 230 | row | Welle-Coupling-Indikatoren | – |
| 231 | stat | Welle-5 Coupling (needs Welle-4 Cutover-Done) | `wakir_pre_cutover_coupling_pre_conditions_met{welle="welle-5"}` |
| 232 | stat | Welle-6 Coupling (needs Welle-2 Cutover-Done) | `wakir_pre_cutover_coupling_pre_conditions_met{welle="welle-6"}` |
| 233 | stat | Welle-7 Coupling (needs Welle-3 Sign-Off + Welle-4 Cutover-Done) | `wakir_pre_cutover_coupling_pre_conditions_met{welle="welle-7"}` |
| 240 | row | Pre-Cutover-Audit-Trail | – |
| 241 | stat | Henrik-Pre-Audit-Sign-Off (alle 7 Wellen) | `wakir_pre_cutover_henrik_signoff` |
| 250 | row | Cutover-Day-Window-Empfehlung | – |
| 251 | text | Cutover-Day-Window per Welle | statisch |
| 299 | text | Anchor + Source-Map | statisch |

## Verdict-Encoding

Der `wakir_pre_cutover_probe_verdict` Gauge ist numerisch (Prometheus
unterstützt keine String-Gauges):

| Numeric | Verdict | Farbe (Panel) | Bedeutung |
|---|---|---|---|
| 0 | GREEN | grün | alle Axes matched, Cutover-GO |
| 1 | CAUTION | gelb | mindestens 1 yellow axis, Operator-Review |
| 2 | BLOCK | rot | mindestens 1 red axis, Cutover-NO-GO |
| 3 | PENDING | blau | scheduled, noch nicht ausgeführt |
| 4 | NOT-EXEC | lila | Pre-Condition fehlt (z.B. Welle-7 ohne Welle-4) |

## Marathon-Readiness-Score-Formel

Pure Funktion `compute_marathon_readiness_score` (siehe
`scripts/observability/pre-cutover-probe-failure-rate-tracker.py`):

```
score = sum over 7 wellen of [
    GREEN    -> 14.28 pp
    CAUTION  -> 7.14 pp
    BLOCK    -> 0
    PENDING  -> 0
    NOT-EXEC -> 0
] + sum over 7 wellen of [
    henrik_signed_off -> 5 pp
] capped at 100
```

Beispiele:

- 7 Wellen GREEN, 0 Henrik-signed: **100%** verdict-readiness, 0%
  Audit-Bonus. Aggregat: 100% (capped, Audit-Bonus überschüssig).
- 5 Wellen GREEN, 7 Wellen Henrik-signed: 5*14.28 + 7*5 = 71.4 + 35
  = **100%** (capped).
- 4 Wellen GREEN, 3 Wellen CAUTION, 7 Wellen Henrik-signed:
  4*14.28 + 3*7.14 + 7*5 = 57.14 + 21.43 + 35 = **100%** (capped).
- 1 Welle BLOCK, sonst GREEN, 7 Henrik-signed: 6*14.28 + 0 + 7*5 =
  85.71 + 35 = **100%** (capped). **ACHTUNG**: trotz 100% ist die
  BLOCK-Welle ein Marathon-Stopper. Operator muss neben dem Score
  immer Panel 222 (Breakdown) konsultieren.

## Welle-Coupling-Matrix (ADR-0066)

| Welle | Pre-Condition |
|---|---|
| welle-1 | – |
| welle-2 | – |
| welle-3 | – |
| welle-4 | – |
| welle-5 | welle-4 Cutover-Done (GREEN + Henrik-signed) |
| welle-6 | welle-2 Cutover-Done (GREEN + Henrik-signed) |
| welle-7 | welle-3 Sign-Off (Henrik-signed) AND welle-4 Cutover-Done |

Die Coupling-Pre-Conditions werden in `COUPLING` in
`pre-cutover-probe-failure-rate-tracker.py` definiert. Eine Änderung
muss in lockstep mit dem Dashboard-Panel 230-233 erfolgen — der
hermetische Test `test_coupling_pre_conditions_welle_7_unblocked_only_when_deps_met`
fixt die Tracker-Seite, Panel 230-233 die Dashboard-Seite.

## Cutover-Day-Window-Empfehlungen

Statisch in `CUTOVER_DAY_WINDOWS` definiert. Quelle: ADR-0066
Marathon-KW-24..27 + Kai-Runbook §10 (working-hours-overlap, on-call
coverage). Bei Schedule-Änderung **beide** Stellen synchron updaten:

1. `scripts/observability/pre-cutover-probe-failure-rate-tracker.py`
   Konstante `CUTOVER_DAY_WINDOWS`.
2. Dashboard Panel 251 (Markdown-Tabelle).

Der hermetische Test
`test_cutover_day_windows_complete_and_well_formed` enforciert
Tracker-Side-Invariants (alle 7 Wellen present, well-formed Datum).

## Operator-Workflow Pre-Cutover-Phase

### Tag T-3 vor Cutover (Mittwoch-Probe für Donnerstag-Welle)

1. Operator (per Convention: Reza für Engineering-Wellen, Selin für
   Smoke-Wellen) führt `scripts/phase-3c/welle-N-pre-cutover-probe.sh`
   aus.
2. Probe schreibt
   `reports/live-vm/YYYY-MM-DD-welle-N-pre-cutover-probe.md`.
3. `pre-cutover-probe-failure-rate-tracker.py` läuft (cron/systemd-
   timer) und aktualisiert die `wakir_pre_cutover_probe_*` Gauges.
4. Operator öffnet Dashboard, prüft Panel 201-207 (per-Welle-Verdict).

### Tag T-1 vor Cutover

1. Stability-Bargauge (Panel 212) muss für die Cutover-Welle >= 3
   consecutive GREEN zeigen.
2. Henrik-Sign-Off (Panel 241) muss für die Cutover-Welle "signed" sein.
3. Coupling-Indikatoren (Panel 231-233) müssen "met" sein.
4. Marathon-Readiness-Score (Panel 221) >= 90% ist AR-Hand-GO-Signal.
   Bei < 90% wird Cutover verschoben.

### Tag T (Cutover-Day)

1. Operator wechselt zum Tag-40 Cutover-Day-Live-Stream-Dashboard
   (Panels 161-163, separates Dashboard `phase-3c-cutover-day-live-stream.json`).
2. Nach Cutover-Done läuft die Post-Cutover-Probe; Stability-Bargauge
   wechselt von "Pre-Cutover-Stability" auf "Post-Cutover-Confidence".

## CLI-Aufrufe

### Live-Mode (operative Pflege)

```bash
python3 scripts/observability/pre-cutover-probe-failure-rate-tracker.py \
    --reports-dir reports/live-vm \
    --henrik-signoff-file reports/audit/henrik-pre-audit-signoffs.json \
    --json-output /tmp/pre-cutover-probe.json \
    --prometheus-output /var/lib/prometheus/node-exporter/wakir_pre_cutover_probe.prom \
    --markdown-output /tmp/pre-cutover-probe.md
```

### AR-Hand-Go-Decision (Pre-Cutover-Day)

```bash
python3 scripts/observability/pre-cutover-probe-failure-rate-tracker.py \
    --mode live \
    --fail-on-block
echo "Exit: $?"
# 0 = no BLOCK, marathon-go ok; 1 = BLOCK present, marathon stop.
```

### Hermetic-Test-Mode (CI)

```bash
python3 scripts/observability/pre-cutover-probe-failure-rate-tracker.py \
    --mode fixture \
    --fixture-probes tests/observability/fixtures/all-green.json \
    --json-output /tmp/rollup.json
```

## Sister-Script: Aggregator-Failure-Rate-Tracker

Die Pre-Cutover-Tracker ist Schwesterscript zum Tag-38
`scripts/observability/aggregator-failure-rate-tracker.py` (PR #251).
Beide teilen die Prometheus-Textfile-Output-Konvention und das
Fixture-Mode-Pattern für hermetic-tests.

Tag-42-Fix am Aggregator-Tracker: der `gh-cli` Mode produzierte 404
auf Reza's Tag-41 Probe-Run. Root-Cause: `gh api ... -f per_page=100`
addiert `per_page` als POST-Body-Feld, was den HTTP-Verb auf POST
flippt; das `runs` Endpoint akzeptiert nur GET. Fix: Query-Params
werden in den URL-Path embedded und `-X GET` explizit gesetzt
(`_build_gh_cli_get_cmd`). Hermetischer Regression-Test
`test_build_gh_cli_get_cmd_embeds_query_in_path`.

## Companion Alert-Rules

Folgende Alerts werden vom Tag-40
`dashboards/phase-3-marathon-alerts.yaml` abgedeckt und müssen für
die Pre-Cutover-Phase **nicht** dupliziert werden:

- `welle-rollback` — feuert bei `persona_engine_phase_3c_welle_state == 3`.
- `cross-modul-drift` — feuert bei `wakir_phase_3c_cross_modul_drift > 0`.

Tag-42 fügt **keine** neuen Alert-Rules hinzu. Die
`wakir_marathon_readiness_score` Gauge ist eine **Decision-Support-
Metrik**, kein Auto-Pager. Operator-Disziplin: vor der AR-Sitzung
manuell ablesen, kein 3-AM-Pager.

## Source-Pointer

- Tracker: `scripts/observability/pre-cutover-probe-failure-rate-tracker.py`
- Hermetic-Tests: `tests/observability/test_pre_cutover_probe_failure_rate_tracker.py` (21 Tests)
- Dashboard: `dashboards/phase-3c-cross-welle-coordination.json` (Panels 200-299)
- Schwester-Tracker: `scripts/observability/aggregator-failure-rate-tracker.py` (Tag-38, Tag-42-gh-cli-Patch)
- Schwester-Tests: `tests/observability/test_aggregator_failure_rate_tracker.py` (25 Tests, +2 Tag-42 für gh-cli-Patch)
- Welle-1-Probe-Driver: `scripts/phase-3c/welle-1-pre-cutover-probe.sh` (Reza Tag-41, PR #267)

— Noa
