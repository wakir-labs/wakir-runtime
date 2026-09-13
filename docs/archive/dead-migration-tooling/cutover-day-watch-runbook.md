# Cutover-Day-Watch Runbook (Phase-3c, Tag-41)

Operator-Runbook für den Tag-41 Live-Stream-Aggregator
(`scripts/observability/cutover-day-live-stream-aggregator.py` +
`scripts/observability/cutover-day-watch.sh`) während der Phase-3c
Cutover-Wellen KW-24..27 (ADR-0066).

Owner: Noa Bergstroem (SRE).
Audit-Anker: ADR-0066 §Cutover-Plan, ADR-0066 §Mitigation-2
(Cross-Welle-Coordination-Test on-stream).

---

## 1. Was tut der Live-Stream-Watch?

Während eines Cutover-Tag-Morgens (06:30 CEST, ADR-0066 §Cutover-
Plan) beobachtet der Watch in Realtime:

- pro aktiver Welle die **Backend-Decision-Verteilung** (production /
  shadow / fallback / skipped) über ein gleitendes Fenster (Default
  300 Events);
- die **Cross-Welle-Drift** zwischen aktiven Welle-Paaren als Total-
  Variation-Distanz mit RED/AMBER/GREEN-Banden;
- pro Welle die **BackendDecision-Latenz-Perzentile** (p50/p95/p99);
- **Band-Crossings** als operator-greifbare Notify-Zeilen auf stderr.

Output-Kanäle:

| Kanal | Inhalt | Konsument |
|---|---|---|
| Terminal (stdout) | Live-Snapshot-JSON-Tail | Operator (visuell) |
| `${STATE_DIR}/live-stream.jsonl` | append-only JSON-Snapshots | Replay / Audit |
| `${STATE_DIR}/notify.log` | DRIFT_*_CROSSING Zeilen | Mira-Notify-Pickup-Skript |
| `${STATE_DIR}/final-state.json` | Final-State bei SIGINT/SIGTERM | Post-Mortem |
| `--prometheus-output PATH` | `wakir_cutover_live_*` Gauges | Prometheus-Scrape |

Das Grafana-Dashboard `dashboards/phase-3c-cutover-day-live-stream.json`
(7 Panels, UID `wakir-phase-3c-cutover-day-live-stream`) ist der
Zweit-Bildschirm; das Terminal ist der Erst-Bildschirm.

---

## 2. Vorbereitung am Cutover-Tag-Vorabend

**Aufgabe**: Trockenlauf mit Fixture-Daten, Operator-Routine üben.

1. State-Verzeichnis vorbereiten:

   ```bash
   export STATE_DIR="${HOME}/cutover-watch-state-$(date +%Y%m%d)"
   mkdir -p "$STATE_DIR"
   ```

2. Fixture-Stream aus dem Vor-Cutover-Baseline-Tag bauen
   (Helper-Skript: `scripts/observability/cutover-day-live-stream-aggregator.py`
   im `--mode=fixture`):

   ```bash
   # Fixture aus dem letzten 24h NATS-replay-archiv exportieren.
   # Format pro Zeile: {"welle":"welle-N","outcome":"production","latency_ms":12.4,...}
   # Quelle: persona-engine boot-decision-audit replay (Reza-Ownership).
   ```

3. Trockenlauf:

   ```bash
   scripts/observability/cutover-day-watch.sh \
       --mode fixture \
       --fixture-stream "$STATE_DIR/baseline-replay.jsonl" \
       --window-size 300 \
       --state-dir "$STATE_DIR"
   ```

4. Erwartung: alle aktiven Wellen erscheinen im stdout-tail, Drift
   bleibt GREEN, `notify.log` bleibt leer, `final-state.json` wird
   bei `Ctrl-C` geschrieben.

---

## 3. Cutover-Tag-Morgen 06:30 CEST — Live-Start

### 3.1 Pre-Flight (5 Min vor 06:30)

- [ ] NATS-CLI auf PATH (`command -v nats`)
- [ ] SPIFFE-Workload-Identity-SVID gemountet
      (siehe Kai/ADR-0020 NATS substrate)
- [ ] Prometheus-Node-Exporter läuft mit textfile-collector
- [ ] Grafana-Dashboard `wakir-phase-3c-cutover-day-live-stream`
      offen auf zweitem Monitor
- [ ] Mira-Notify-Pickup-Skript läuft (tailed `$STATE_DIR/notify.log`)

### 3.2 Start

```bash
export STATE_DIR="/var/lib/wakir/cutover-state-$(date +%Y%m%d)"
mkdir -p "$STATE_DIR"

scripts/observability/cutover-day-watch.sh \
    --mode nats \
    --window-size 300 \
    --emit-every 50 \
    --state-dir "$STATE_DIR" \
    --prometheus-output /var/lib/prometheus/node-exporter/wakir_cutover_live_stream.prom
```

Der Watch läuft bis Operator-`Ctrl-C` oder externes SIGTERM. Erwartung:

- erstes JSON-Snapshot im Terminal innerhalb von 30–60 s nach Start
  (sobald 50 Events ingestiert wurden);
- Per-Welle-Distribution zeigt > 95 % `production` (Pre-Cutover-
  Baseline) für jede aktive Welle;
- Drift-Indikator GREEN für alle aktiven Welle-Paare.

---

## 4. Notify-Thresholds

### 4.1 Bands (operator-tuned, fest in der Aggregator-Logik)

| Total-Variation-Drift | Band | Operator-Aktion |
|---|---|---|
| `< 0.05` | GREEN | Keine Aktion. Normalbetrieb. |
| `0.05 <= d < 0.15` | AMBER | Im Log notieren. Beobachten ob Trend ins RED kippt. |
| `>= 0.15` | RED | **Mira-Notify auslösen. Cutover-Pause-Check.** |

### 4.2 RED-Crossing-Prozedur

Sobald eine `DRIFT_RED_CROSSING`-Zeile in `${STATE_DIR}/notify.log`
erscheint:

1. **T+0** Cutover-Pause-Flag setzen (das Persona-Engine-Cutover-Skript
   prüft dieses Flag vor jedem Welle-Step). Operator-Hand:
   ```bash
   touch /var/lib/wakir/cutover-pause-flag
   ```

2. **T+1 min** Mira-Notify an die SRE-On-Call-Queue (manueller
   Push falls Pickup-Skript versagt):
   ```bash
   cat "$STATE_DIR/notify.log" | tail -1 | wakir-notify-push --priority high
   ```

3. **T+3 min** Investigation: Grafana-Dashboard öffnen, betroffenes
   Welle-Paar im Heatmap-Panel lokalisieren, Per-Welle-Distribution
   in Panel 1 prüfen. Welche Outcome-Verteilung ist gedriftet?

4. **T+5 min** Entscheidung Pause vs. Resume:
   - **Pause** wenn Drift in `fallback` oder `unknown` driftet
     (Indikation: Backend-Switch fehlgeschlagen, Welle-spezifisch).
   - **Resume** wenn Drift nur zwischen `production` und `shadow`
     wandert (kein Cutover-Failure-Modus, eher Traffic-Schwankung).
     Pause-Flag entfernen, Notify als false-positive markieren.

5. **T+10 min** Henrik-Audit-Log-Eintrag (manueller Push):
   ```bash
   echo "$(date -Is) RED-crossing $WELLE_PAIR drift=$DRIFT decision=$ACTION" \
       >> /var/lib/wakir/audit/cutover-decisions.log
   ```

### 4.3 AMBER-Crossing — keine Pause, nur Aufzeichnung

`DRIFT_AMBER_CROSSING`-Zeilen werden geloggt, aber nicht eskaliert.
Eine Häufung (≥3 AMBER-Crossings auf demselben Welle-Paar innerhalb
von 5 Minuten) ist Operator-Indikator für eine bevorstehende RED-
Eskalation; in diesem Fall **pro-aktiv** in Schritt 3 (Investigation)
einsteigen, **ohne** Pause-Flag zu setzen.

---

## 5. Stream-Silent-Investigation

Wenn der Active-Welle-Inventory-Stat (Dashboard Panel 6) auf 0 geht
während ein Cutover laufen sollte:

1. NATS-CLI-Verbindung prüfen: `nats sub wakir.persona-engine.boot-decision-audit.* --count 5 --raw`
   sollte Events liefern.
2. Persona-Engine-Liveness prüfen: `wakir-status persona-engine`.
3. Wenn NATS leer aber Persona-Engine healthy: Emit-Pfad gebrochen,
   Reza eskalieren (`scripts/persona-engine/backend-decision-observability.py`).
4. Wenn Persona-Engine down: Cutover-Rollback initiieren (ADR-0066
   §Rollback-Plan, Kai-Hand).

---

## 6. Unexpected-Welle-Activation

Wenn Panel 6 > 2 anzeigt während laut Cutover-Plan nur eine Doppel-
Welle aktiv ist (oder > 1 wenn Solo-Welle):

1. Welche Wellen-Slots aktiv sind in `${STATE_DIR}/live-stream.jsonl`
   nachsehen (letztes Snapshot, `wellen`-key, alle mit `sample_count > 0`).
2. Cross-Reference gegen ADR-0066 Cutover-Plan (KW-Eintrag).
3. Wenn Welle XX aktiv ist die nicht im Plan steht: **sofort** das
   Persona-Engine-Cutover-Tooling stoppen, Mira-Notify mit Tag
   `unexpected-welle-activation`. Tomás (WAT-Owner) eskalieren —
   ungeplante Welle-Aktivierung bedeutet entweder Bug im Cutover-
   Stepper oder ein orphan-State im persona-engine-state-backing.

---

## 7. Shutdown

### 7.1 Geplanter Shutdown (Cutover-Tag-Abend, ~22:00 CEST)

Operator: `Ctrl-C` im Watch-Terminal. Erwartung:

- Bash-Wrapper schickt SIGTERM an den Aggregator (Python-Prozess);
- Aggregator dumpt `final-state.json` in `${STATE_DIR}/final-state.json`;
- Wrapper schreibt finalen State auf stderr und exited 0.

Nach dem Shutdown den State-Ordner archivieren:

```bash
tar czf "$HOME/cutover-watch-$(date +%Y%m%d).tar.gz" -C / "${STATE_DIR#/}"
```

### 7.2 Crash-Recovery (Watch stirbt unerwartet)

Wenn `cutover-day-watch.sh` ohne SIGINT exitiert:

1. Exit-Code des Wrappers prüfen (≠ 0 = aggregator crashed).
2. `${STATE_DIR}/aggregator.pid` prüfen — falls vorhanden, der
   Aggregator-Prozess ist verwaist (nicht aufgeräumt).
3. Aggregator manuell stoppen:
   ```bash
   AGG_PID=$(cat ${STATE_DIR}/aggregator.pid 2>/dev/null)
   [ -n "$AGG_PID" ] && kill -TERM "$AGG_PID" 2>/dev/null
   rm -f "${STATE_DIR}/aggregator.pid"
   ```
4. Watch neu starten mit demselben `--state-dir` — der JSON-Stream
   wird truncated (frischer Start), das ist Absicht. Lückenlose
   Aufzeichnung kommt aus Prometheus, nicht aus dem stdout-Tail.
5. Post-Mortem: warum ist der Watch gefallen? Bash-Wrapper-Stderr
   geht in den systemd-journal (wenn unter systemd-run), sonst
   stderr-Capture des Terminals.

---

## 8. Anti-Alert-Fatigue-Check

Vor jedem Cutover-Tag-Morgen Noa-SRE-Disziplin:

- Notify-Threshold-Bands seit dem letzten Lauf unverändert?
- Im letzten Cutover-Lauf RED-Crossings die sich als false-positive
  erwiesen → Threshold-Review nötig?
- AMBER-Spam (>20 AMBER-Crossings/Tag) → Window-Size erhöhen
  (300 → 1800), um Kurz-Rausch-Empfindlichkeit zu senken.

Threshold-Anpassungen sind eine Persona-Definition-Änderung
(Noa-Hand). Cross-Review mit Tomás (WAT-Owner) wenn Drift-Bands
auf WAT-Pipeline-Komponenten wirken.

---

## 9. Anker und Referenzen

- ADR-0066 — Phase-3c Cutover-Plan Welle-1..7
- ADR-0066 §Mitigation-1 — Doppel-Welle KW-26
- ADR-0066 §Mitigation-2 — Cross-Welle-Coordination-Test (on-stream A7)
- PR #251 — Tag-38 aggregator-failure-rate-tracker (Pattern-Quelle)
- PR #260 — Tag-40 Phase-3-Marathon-Dashboard (71 Panels, Eltern-Dashboard)
- `scripts/persona-engine/backend-decision-observability.py` — Stream-Emit-Quelle
- `tests/observability/test_cutover_day_live_stream_aggregator.py` — hermetische Tests

— Noa
