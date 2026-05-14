<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Migrations-Pilot Validation-Phase Setup — ADR-0058 Schritt 10

**Status:** Phase-1c ADR-0058-Pilot, Sprint-9 Tag-9. Diese Datei
ergänzt [`infra/migration-pilot/TOMAS_SPAWN_RECIPE.md`](../infra/migration-pilot/TOMAS_SPAWN_RECIPE.md) (Schritt 9)
um die **Validation-Phase-Setup-Substanz** für die 6 Pilot-Wochen
(4 Wochen Doppelbetrieb + 2 Wochen Stress-Test-Validation).

**Companion-Artefakte:**

- [`decisions/0058-pilot-persona-migrations-plan.md`](../../../decisions/0058-pilot-persona-migrations-plan.md)
  (AI-Corp Hauptrepo) — Pilot-Phase-Plan, Acceptance-Kriterien.
- [`infra/migration-pilot/TOMAS_SPAWN_RECIPE.md`](../infra/migration-pilot/TOMAS_SPAWN_RECIPE.md) —
  Schritt 9 (Spawn).
- [`projects/migration-plan.md`](../../../projects/migration-plan.md)
  (AI-Corp Hauptrepo) — Sequenz-Tracking.

## 0. Was hier passiert (Überblick)

ADR-0058 §Phase-2 fixiert eine 4-Wochen-Doppelbetrieb-Phase, in der
**Pre-Framework-Tomás-Spawn + Wakir-Runtime-Tomás-Spawn** parallel die
gleichen Engineering-Aufträge erhalten und der Bridge-Audit-Writer
(PR #19 `2c1f3a6`) beide Outputs in dieselben Sinks schreibt. Diese
Phase erzeugt das Vergleichs-Datenmaterial für die Cutover-Entscheidung
am Ende von Woche 6.

Dieses Setup-Doc fixiert die drei operative Achsen:

1. **§1 Acceptance-Kriterien-Setup** — wie messen wir Cutover-Readiness
   konkret? Welche Schwellwerte gelten als PASS/FAIL?
2. **§2 Observability-Setup** — welche Metriken sammeln wir während
   4 Wochen, mit welchem Schema, in welche Sinks?
3. **§3 Rollback-Trigger-Konditionen** — wann brechen wir den Pilot
   ab, und was sind die Aktionen?

## 1. Acceptance-Kriterien-Setup

ADR-0058 §Phase-4 (Cutover-Entscheidung) listet 5 Erfolgs-Kriterien.
Dieses Setup-Doc operationalisiert sie als **PASS/FAIL-Schwellwerte**
plus die konkreten **Mess-Substrate** pro Kriterium.

### 1.1 Kriterium 1 — Audit-Trail-Lücke = 0 über 4 Wochen

**Mess-Substrate:** Bridge-Audit-Writer-Sink-Konsistenz-Check (CLI:
`wakir-bridge-audit-verify` aus PR #19 `2c1f3a6`).

**Schwellwert:** Pro Auftrag mit `BRIDGE-PERSONA-tomas`-Marker MUSS
gelten: Pre-Framework-Sink-Entry + Wakir-Runtime-Sink-Entry sind beide
vorhanden und referenzieren denselben `wat_anchor_manifest_id`.

**Messung:**

```bash
# Wöchentlich (Mo 09:30 CEST), Mira-Hand:
cd /var/home/fred/AI-Corp/wakir-runtime
./target/release/wakir-bridge-audit-verify \
  --persona-id dev-engineering \
  --window-start "$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --window-end   "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --report-format json \
  > /var/home/fred/AI-Corp/projects/reports/pilot-week-N-audit-trail.json
```

**PASS-Bedingung:** `gap_count == 0` über die 4 Wochen.
**FAIL-Bedingung:** auch nur 1 Auftrag ohne paired entry.

### 1.2 Kriterium 2 — Output-Qualität Wakir-Runtime ≥ Pre-Framework

**Mess-Substrate:** Manuelle 4-Achsen-Score-Bilanz (ADR-0058 §Phase-2,
"Vergleichs-Testset").

**Schwellwert:** Wöchentlich min. 10 Engineering-Aufträge gescoret
(Substanz / Format / Brand-Wording / ADR-0048-Pattern), je 0-5 Punkte.
Wakir-Runtime-Cumulative-Score MUSS ≥ Pre-Framework-Cumulative-Score
über die 4 Wochen (Toleranz ±5%).

**Messung:** Mira-Hand wöchentlich, Eintrag in
`projects/reports/pilot-week-N-quality-score.md` (4-Achsen-Tabelle).

**PASS-Bedingung:** wakir_score ≥ 0.95 × preframework_score.
**FAIL-Bedingung:** wakir_score < 0.95 × preframework_score
in 2 aufeinanderfolgenden Wochen.

### 1.3 Kriterium 3 — Operations-Disruption-Frequenz ≤ 1/Woche

**Mess-Substrate:** Marker-Stack-Events mit
`event_kind ∈ {tomas-pilot-rollback, tomas-pilot-incident, tomas-pilot-degraded}`.

**Schwellwert:** Pro Pilot-Woche maximal 1 Operations-Disruption-Event.
Eine Disruption = jeder Vorgang, der den Pre-Framework-Engineering-Spawn
oder Mira-Hand-Operations für >10 Minuten blockiert.

**Messung:**

```bash
# Wöchentlich:
sudo -u wakir nats kv ls wakir-marker-stack-acme | \
  while read key; do \
    sudo -u wakir nats kv get wakir-marker-stack-acme --raw "$key" | \
      jq -r 'select(.event_kind | startswith("tomas-pilot-") and (test("rollback|incident|degraded"))) | .timestamp'; \
  done | wc -l
```

**PASS-Bedingung:** ≤ 4 Disruption-Events über die gesamten 4 Wochen
Doppelbetrieb.
**FAIL-Bedingung:** > 4 Disruption-Events oder ≥ 2 in einer Woche.

### 1.4 Kriterium 4 — Henrik-Sample-Audits 4×PASS

**Mess-Substrate:** Henrik (internal-audit) führt 1 Sample-Audit pro
Pilot-Woche durch, Output als
`agents-workspaces/internal-audit/outbox/pilot-week-N-tomas-audit.md`.

**Schwellwert:** 4 Wochen × 1 Audit = 4 Sample-Audits. Alle 4 MÜSSEN
ohne kritischen Befund passieren (kritisch = "Operator-Hand-Aktion
erforderlich" oder höher).

**PASS-Bedingung:** 4/4 Audits ohne kritischen Befund.
**FAIL-Bedingung:** ≥ 1 kritischer Befund.

### 1.5 Kriterium 5 — Stress-Test-Drills (Wochen 5-6) alle grün

**Mess-Substrate:** Recovery-Drill-Pattern aus persona-engine-format-
spec §3.7.2 + §3.7.4 (Sprint-Pengine-7 Tag-3 + Tag-4-Substanz).

**Drill-Set (siehe Spec §3.7.2.1):**

| Drill | Frequenz | Substrate-Layer | Acceptance |
|---|---|---|---|
| `DRILL_CONTAINER_CRASH` | je 1× in Woche 5 + 6 | engine-runtime | 4 Invarianten aus §3.7.2.2 |
| `DRILL_NATS_BUCKET_LOST` | 1× in Woche 5 | storage-substrate | 4 Invarianten aus §3.7.2.2 |
| `DRILL_SPIRE_SVID_EXPIRED` | 1× in Woche 6 | identity | 4 Invarianten aus §3.7.2.2 |
| **Konverter-Idempotency-Test** | 1× in Woche 5 | engine-runtime | `wakir-persona-convert` bytestable über 2 Pässe |
| **Capability-Token-Rotation+Replay** | 1× in Woche 6 | identity | Reza Sprint-9-Tag-2-substrate |

**PASS-Bedingung:** 5/5 Drills + Tests grün.
**FAIL-Bedingung:** ≥ 1 Drill rot.

### 1.6 Cutover-Approval-Schwelle (Aggregat)

**Cutover wird Mira an AR empfohlen** wenn:

- Kriterium 1: PASS
- Kriterium 2: PASS
- Kriterium 3: PASS
- Kriterium 4: PASS
- Kriterium 5: PASS (alle 5 Drills grün)

**5/5 PASS = Cutover-Vorlage an AR.**
**4/5 PASS = 2 Wochen Beobachtung verlängern + zweite Bilanz.**
**≤ 3/5 PASS = Rollback per ADR-0036 Schritt 9 erwogen.**

## 2. Observability-Setup

### 2.1 Metriken-Sinks

Während der 4-Wochen-Pilot-Phase schreiben wir Metriken in drei Sinks
(Sprint-8-Tag-4-Pattern):

| Sink | Schema | Cadence | Owner |
|---|---|---|---|
| **NATS-KV `wakir-marker-stack-acme`** | Bestehendes Marker-Schema (Sprint-6-Tag-9) | Per Event | Operator-Hand |
| **WAT-Bridge-Anchored** | Sprint-3-Tag-19-WAT-Frame | Stündlich (cron) | Tomás-Side-WAT-Cron |
| **`projects/reports/pilot-week-N-*.md`** | Markdown-Report-Tabelle | Wöchentlich | Mira-Hand |

### 2.2 Metriken-Liste

Pro Persona-Activity-Event (≈ 1 Engineering-Auftrag) sammeln wir:

| Metrik | Typ | Quelle | Verwendung |
|---|---|---|---|
| `event_id` | UUIDv7 | Pre-Framework-side | Bridge-Audit-Writer-Pairing |
| `persona_id` | string | beide Spawns | Konsistenz-Check |
| `auftrag_slug` | string | Mira-Hand-Spawn-Brief | Score-Tabelle-Pivot |
| `preframework_started_at_utc` | RFC3339 | Pre-Framework-Spawn | Latency-Vergleich |
| `wakir_runtime_started_at_utc` | RFC3339 | Wakir-Runtime-Spawn | Latency-Vergleich |
| `preframework_finished_at_utc` | RFC3339 | Pre-Framework | dito |
| `wakir_runtime_finished_at_utc` | RFC3339 | Wakir-Runtime | dito |
| `wat_anchor_manifest_id_preframework` | sha256 hex | WAT-Cron | Audit-Trail-Pairing |
| `wat_anchor_manifest_id_wakir_runtime` | sha256 hex | WAT-Cron | dito |
| `score_substanz` | int 0-5 | Mira-Hand-Score-Tabelle | Quality-Score |
| `score_format` | int 0-5 | Mira-Hand | dito |
| `score_brand_wording` | int 0-5 | Mira-Hand | dito |
| `score_adr0048_pattern` | int 0-5 | Mira-Hand | dito |
| `disruption_flag` | bool | Operator-Hand-Marker-Event | Kriterium 3 |
| `disruption_reason` | string | Operator-Hand | Forensik |
| `token_consumption_preframework` | int | Pre-Framework-side | Performance-Tracking |
| `token_consumption_wakir_runtime` | int | Wakir-Runtime-side | dito |
| `latency_ms_preframework` | int | Pre-Framework | Performance-Tracking |
| `latency_ms_wakir_runtime` | int | Wakir-Runtime | dito |

### 2.3 Recovery-Drill-Observability (Wochen 5-6)

Pro Drill-Run emittieren wir einen `recovery_drill_outcome`-Event
(OI-PEF-11, Reza-Sprint-9-Tag-2-durable-ledger-substrate):

```json
{
  "event_kind": "recovery_drill_outcome",
  "persona_id": "dev-engineering",
  "drill_class": "DRILL_CONTAINER_CRASH | DRILL_NATS_BUCKET_LOST | DRILL_SPIRE_SVID_EXPIRED",
  "outcome": "PASSED | FAILED",
  "started_at_utc": "<RFC 3339>",
  "finished_at_utc": "<RFC 3339>",
  "elapsed_seconds": <float, MUST be <= 30 (RECOVERY_BUDGET_SECONDS)>,
  "invariants": {
    "hash_pre_post_identical": true | false,
    "audit_trail_gap_zero":     true | false,
    "capability_token_continuity": true | false,
    "container_state_convergence_within_budget": true | false
  },
  "failure_mode": null | "TriggerAmbiguous | BackingUnreachable | SnapshotCorrupt | IdentityRebindFailed | ResumeTimeout"
}
```

WAT-Anchoring: jeder `recovery_drill_outcome`-Event wird via Reza-
Sprint-9-Tag-2-durable-ledger in den WAT-Merkle-Tree für cross-org-
auditable Evidenz aufgenommen.

## 3. Rollback-Trigger-Konditionen

**Sofortige Rollback-Trigger** (innerhalb 10 Minuten Operator-Reaktion):

| Trigger | Detection | Aktion |
|---|---|---|
| **R-A** Pre-Framework-Tomás-Spawn wird gestört durch Wakir-Runtime-Spawn | Mira-Hand-Bericht oder Operator-Beobachtung | Sofort `wakir-persona-dev-engineering`-Container stoppen + Recipe §7 atomic Rollback |
| **R-B** Bridge-Audit-Writer-Sink-Konsistenz-Lücke (Audit-Trail-Gap > 0) auch nur ein einziges Mal in einer Pilot-Woche | `wakir-bridge-audit-verify` Wochen-Report | Sofort Rollback; Henrik-Audit für Forensik; Mira eskaliert AR |
| **R-C** V-907-Hash-Drift zwischen Pre-Framework-Tomás-Spawn und Wakir-Runtime-Tomás-Spawn | Mira-Hand-Verify per `wakir-persona-convert` + `--pin-hash-v907` | Sofort Rollback; Selin-Forensics (Konverter-Bug? Spec-Drift?) |
| **R-D** SPIRE-SVID kann nicht refresht werden für > 1h | Container-Logs + SPIRE-Server-Health-Check | Sofort Rollback; Reza-Forensics |
| **R-E** NATS-KV-Bucket-Korruption (Sprint-8-Tag-3-Reducer-Konflikt) | Marker-Stack-Reducer-Output-Drift | Sofort Rollback; Tomás-WAT-Forensics |

**Verzögerte Rollback-Trigger** (innerhalb 24h Operator-Reaktion):

| Trigger | Detection | Aktion |
|---|---|---|
| **R-F** Output-Qualität wakir_score < 0.90 × preframework_score in 2 Wochen | Wöchentliche Score-Tabelle | Mira-Vorlage an AR: weitere 2 Wochen Beobachtung oder Rollback |
| **R-G** Disruption-Frequenz > 1/Woche im Mittel | Marker-Stack-Event-Count | Mira-Vorlage an AR; ggf. Engineering-Pipeline-Schutz-Verstärkung |
| **R-H** Stress-Test-Drill (Wochen 5-6) FAILED | Drill-Outcome-Event | Drill-Spezifischer Forensics + Fix-Rebuild-Retry; bei 2× FAIL: Rollback |

### 3.1 Atomic-Rollback-Sequenz

Identisch zu Recipe §7 (`infra/migration-pilot/TOMAS_SPAWN_RECIPE.md`):

```bash
# Wakir-Runtime-Tomás-Container stoppen + entfernen:
sudo -u wakir podman stop wakir-persona-dev-engineering
sudo -u wakir podman rm   wakir-persona-dev-engineering

# NATS-KV-Bucket leeren:
sudo -u wakir nats kv rm wakir-persona-state-dev-engineering -f

# SPIRE-Registry-Entry entfernen:
sudo -u wakir /opt/spire/bin/spire-server entry delete -entryID <id>

# Marker-Stack-Event:
wakir-marker-stack-emit \
  --bucket wakir-marker-stack-acme \
  --event-kind tomas-pilot-rollback \
  --persona-id dev-engineering \
  --metadata '{"reason":"<R-X>","trigger":"<details>"}'
```

**Pre-Framework-Tomás-Spawn bleibt unverändert produktiv** — das ist
die ADR-0036-Garantie + ADR-0058 §Engineering-Pipeline-Schutz-Klausel.

### 3.2 Post-Rollback-Forensics

Nach jedem Rollback:

1. Mira-Hand-Memo an AR (Trigger, Aktion, Status).
2. Henrik-Sample-Audit ad-hoc (auch wenn nicht regulär dran).
3. ggf. Selin/Reza/Kai-Forensics-Spawn (substrat-spezifisch).
4. ADR-0036-Schritt-9-Re-Evaluation (zweiter Pilot-Versuch oder
   Henrik-Erst-Pilot-Wechsel).

## 4. Engineering-Pipeline-Schutz-Maßnahmen (Recap)

ADR-0058 §Engineering-Pipeline-Schutz + ADR-0036-Risiko §Persona-
Container-Drift:

- **Pre-Framework-Tomás-Spawn bleibt voll aktiv** während gesamter
  6 Wochen Pilot-Phase.
- **Schatten-Modus:** Wakir-Runtime-Tomás-Spawn ist Schatten-Spawn
  für Vergleich, kein Pre-Framework-Block.
- **Bandbreiten-Verteilung:** ~80% Engineering-Substanz
  (Sprint-10+ Multi-Org-Federation-Production-Polish), ~20%
  Migrations-Pilot-Beobachtung.
- **Atomic-Rollback:** Pre-Framework-Spawn bleibt unbeeinflusst bei
  Wakir-Runtime-Container-Failure.

## 5. Pilot-Phase-Done-Definition (Schritt 10 abgeschlossen)

Schritt 10 selbst (dieses Setup-Doc) ist done sobald:

- ✅ Dieses Dokument im Repo.
- ✅ Companion Recipe (Schritt 9) im Repo.
- ✅ Persona-Pilot-Export-CLI im Repo (Schritt 8).
- ✅ Operator-Sandbox-Hand kann Schritt 8 ausführen ohne Zusatz-Doku.
- ✅ Operator-Pilot-VM-Hand kann Schritt 9 ausführen mit dem Recipe.
- ✅ Mira-Hand hat das Mess-Schema für Wochen 1-4 fixiert.
- ✅ Selin-Hand hat das Drill-Set für Wochen 5-6 fixiert.

**Trigger für Pilot-Phase-Start (Schritt 9 erstmaliger Spawn):**
ADR-0058 §Folgeartefakte "Bei Approval + Schritt-1-Proxmox-Live-Bring-up
+ Schritt-2-Persona-Engine-Format-Spec + Schritt-3-Konverter ✅:
**Pilot-Phase-Trigger durch Mira**".

Heute (2026-05-14) sind alle drei ✅ DONE. Schritt 8 + 9 + 10 sind mit
diesem PR ebenfalls ✅. **Mira-Hand-Pilot-Trigger ist next.**

— Selin (pengine-eng)
