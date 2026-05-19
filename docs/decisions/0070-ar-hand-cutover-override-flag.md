# ADR-0070 — AR-Hand Cutover-Day-Morgen Override-Flag

<!--
SPDX-License-Identifier: BUSL-1.1
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

> **⚠️ MIGRATED 2026-05-20**: Diese Datei ist die ursprüngliche Tomás-Tag-65-Vorlage
> in wakir-runtime. Die offizielle Mira-Hand-approved Version liegt in der AI-Corp-
> ADR-Hierarchie als **ADR-0069** (Re-Nummerierung weil ADR-0068 zum Migrations-
> Zeitpunkt die Top-ID in AI-Corp war): `/AI-Corp/decisions/0069-ar-hand-cutover-
> override-flag.md`. Code-Referenzen auf "ADR-0070" in wakir-runtime bleiben gültig
> als Tomás-Vorlagen-Anker; die Strategy-Authority ist ADR-0069 in AI-Corp. Pattern
> per ADR-Cross-Repo-Migration (Tomás Tag-66 PR #420, docs/operations/adr-cross-
> repo-migration-pattern.md).

**Status:** APPROVED (via Mira-Hand-Freigabe als ADR-0069 in AI-Corp, 2026-05-20
nach AR-Delegation "Mira reicht", Aufsichtsrats-Dialog 2026-05-19 ~21:30 CEST).
Ursprünglich VORLAGE (Tomás-Matrix-Lead-Hut, Tag-65 Continuous-Mode, 2026-05-19).
Aufsichtsrat-Touch nicht direkt erforderlich (AR-Delegation an Mira-Hand, AR ist
über Pattern + Wirkung informiert).

**Numerierung:** ADR-0070 reiht sich an ADR-0068
(Status-Aggregator-Workflow-Required-Check) und ADR-0069
(Vorlage in flight) an. Falls 0069 vergeben ist, bitte umnumerieren.

**Author:** Tomás Reinhart (Matrix-Lead-Funktion).
**Reviewer:** Mira (CEO), Priya (CTO), Henrik (Internal Audit),
Selin (Tag-64 Cutover-Day-Morgen Auto-Scheduler-Owner).

## Context

Selin lieferte Tag-64 den `aggregate_cutover_day_morgen_verdict.py`
Auto-Scheduler. Der Scheduler liest jeden Cutover-Marathon-Morgen
(KW-24..27 Mo-Fr 06:00 UTC) drei Top-Level-Verdict-Envelopes
(`engine_composite`, `pyramide_composite`, `e2e_smoke`) und emittiert
ein aggregiertes Trinary-Verdict:

* `CUTOVER-DAY-MORGEN-READY`   -- alle drei grün.
* `CUTOVER-DAY-MORGEN-CAUTION` -- mindestens eines gelb, kein rot.
* `CUTOVER-DAY-MORGEN-BLOCK`   -- mindestens eines rot ODER ein
  Envelope fehlt / unparsbar.

Selins Tag-64 Follow-Up-Item §3 markiert eine Gap:

> "AR-Hand muss BLOCK-Verdict via Flag-File OVERRIDE-en können bei
> akzeptiertem-Risk (z.B. AR-Override OK, proceed despite block).
> Pattern analog Tomás-Tag-44 Stop-Marker, aber inversiv."

Der konkrete Anwendungsfall: an einem Cutover-Morgen liegt ein
bekannt-rotes Substrate vor (z.B. ein triagierter `e2e_smoke`
DEFECT, dessen Root-Cause AR-Hand bereits außerhalb des Marathons
bewertet hat). Der Marathon soll trotzdem fortgesetzt werden, weil
das Risiko explizit akzeptiert wurde und dokumentiert ist. Ohne
Override-Mechanismus muss der Scheduler-Output manuell überschrieben
werden, was Audit-Trail-Lücken erzeugt.

### Pattern-Analogie: Tag-44 Stop-Marker (Tomás)

Das Tag-44 AR-Hand-Stop-Marker-Pattern operiert symmetrisch in die
entgegengesetzte Richtung: ein Push eines Marker-Files
`state/ar-hand-stop-welle-N-<ts>-<op>.json` triggert einen Listener-
Workflow, der eine laufende Welle abbricht. Schema:

* `kind`, `welle`, `trigger`, `ts`, `operator`, optional `sign_offs`.
* Hermetic-listener mit Detect → Cascade → Cancel → Verdict-Phasen.
* Audit-Trail über das committed Marker-File selbst.

Tag-65 spiegelt dieses Pattern für die **Resume-Halt-Richtung**:
statt eines Stops eine Override-Erlaubnis.

## Question

Wie sieht das AR-Hand-Override-Mechanismus für
`CUTOVER-DAY-MORGEN-BLOCK` aus, sodass

1. Override **explizit dokumentiert** und audit-trail-fähig ist,
2. **niemals** akzidentell ein READY oder CAUTION downgegradet wird,
3. der Tag-64-Aggregator-Verdict-Envelope **unverändert** als
   Source-of-Truth erhalten bleibt,
4. das Pattern **hermetic** testbar ist (stdlib-only, kein Live-CI),
5. Rare-Use enforced wird (nicht zur Routine werden darf)?

## Decision

### Marker-File-Schema

AR-Hand-Override ist ein versioniertes JSON-File, das committed
werden MUSS (Audit-Trail über Git-History):

```json
{
  "schema_version": 1,
  "kind": "ar-hand-cutover-override-flag",
  "operator": "<slug>",
  "ts": "<RFC3339 UTC>",
  "iso_week": 25,
  "reason": "<free-text, min 16 chars>",
  "accepted_risk_id": "<slug, z.B. ar-risk-tag-65-01>",
  "override_target_verdict": "CUTOVER-DAY-MORGEN-BLOCK",
  "post_override_verdict":   "CUTOVER-DAY-MORGEN-CAUTION"
}
```

**Constraints:**

* `override_target_verdict` MUSS `CUTOVER-DAY-MORGEN-BLOCK` sein
  (das einzige zulässige Override-Ziel).
* `post_override_verdict` MUSS `CUTOVER-DAY-MORGEN-CAUTION` sein
  (Override macht NIE einen BLOCK zu einem READY -- der Override-
  Residue ist immer als "akzeptiertes Gelb" auf dem Marathon-
  Dashboard sichtbar).
* `reason` MUSS ≥16 Zeichen nach `strip()` enthalten (keine
  leeren Override-Files).
* `operator` und `accepted_risk_id` MÜSSEN `[a-z0-9][a-z0-9-]{1,63}`
  matchen.
* `ts` MUSS RFC3339-konform sein (mit Zeitzone).

### Listener-Komponente

`tooling/ci/ar_hand_cutover_override_listener.py` (Tag-65 Tomás):

* Liest den Tag-64 Aggregator-Output-Envelope (input).
* Liest den optionalen Override-Marker-File (kann fehlen).
* Validiert das Marker-Schema strikt.
* Emittiert einen **neuen** Envelope mit:
  * `applied: bool` -- ob Override appliziert wurde.
  * `verdict` -- post-override-Verdict, oder input-Verdict
    unverändert.
  * `input_verdict_envelope` -- der Tag-64-Envelope verbatim.
  * `override_marker` -- das validierte Marker-JSON oder `null`.
  * `audit_trail_note` -- 1-Zeilen-Zusammenfassung.

Read-only über alle Inputs. Stdlib-only. Kein gh CLI, kein NATS,
kein SPIRE.

### Aggregator-Integration (Tag-64 Selin-Code)

`aggregate_cutover_day_morgen_verdict.py` wird um ein
`--ar-hand-override-marker` Argument erweitert. Der Aggregator
appliziert das Override **nicht selbst** -- er surfaced nur einen
Descriptor unter `ar_hand_override` für den Tag-65-Listener
downstream. Der Aggregator-Verdict bleibt die un-overridete
Wahrheit (Single-Source-of-Truth-Disziplin).

### Pipeline

```
[V1 engine]      [V2 pyramide]    [V3 e2e_smoke]
       \             |               /
        \            |              /
         aggregate_cutover_day_morgen_verdict.py
                 |
                 v
         <tag-64 envelope> (verdict = BLOCK)
                 |
                 v   +-- [state/ar-hand-cutover-override-*.json] (optional)
                 |   |
                 v   v
         ar_hand_cutover_override_listener.py
                 |
                 v
         <tag-65 envelope> (applied=true, verdict = CAUTION)
                 |
                 v
         marathon-dashboard / notify-cascade
```

### Rare-Use-Enforcement

Soft-Enforcement durch Audit-Surface, kein technischer
Rate-Limit:

* Jedes Override committed das Marker-File → Git-History-trail.
* `accepted_risk_id` muss auf einen dokumentierten Risk-Eintrag
  zeigen (außerhalb dieser ADR -- Internal-Audit-Pflicht).
* Internal-Audit (Henrik) reviewt Override-Frequency wöchentlich
  während Cutover-Marathon (KW-24..27).
* Bei ≥2 Overrides in 5 Cutover-Marathon-Tagen: automatic
  AR-Hand-Eskalation (Mira-Hand-Pflicht).

## Consequences

### Vorteile

* **Audit-Trail vollständig**: Marker-File ist committed, Aggregator-
  Envelope unverändert, Listener-Envelope ist neuer Artefakt.
* **Kein unbeabsichtigter Downgrade**: READY/CAUTION-Inputs sind
  schema-konform unangreifbar.
* **Hermetic testbar**: stdlib + pytest, ≥15 Tests Tag-65 (siehe
  `tests/ci/test_ar_hand_cutover_override_listener_tag65.py`).
* **Pattern-Konsistenz** mit Tag-44 Stop-Marker (gleiche
  Schema-Disziplin, gleiche Listener-Architektur).

### Risiken

* **Rare-Use-Drift**: wenn Override-Frequency steigt, signalisiert
  das ein Tag-64-Aggregator-Calibration-Problem (zu strikte BLOCK-
  Bedingungen) oder einen Substrate-Defekt. Internal-Audit-Trigger
  bei ≥2/5 Tagen.
* **Operator-Misclick**: falsch konfigurierter Marker (z.B. Typo
  in `accepted_risk_id`) wird vom Schema-Validator gefangen;
  `--strict-marker` Flag eskaliert auf exit-3.
* **Override-Approval-Boundary**: wer ist "AR-Hand"? Diese ADR
  delegiert das an die Aufsichtsrats-Governance -- der `operator`-
  Slug muss auf eine `governance/operators.md` (TBD) Eintragsliste
  matchen. Pre-Approval-Frage an Mira-Hand.

### Offene Punkte (für Mira-Hand-Sichtung)

1. ADR-Nummer: ist 0070 frei? (0069 vermutlich in flight)
2. Operator-Allowlist: wo lebt sie? `governance/operators.md`?
3. Internal-Audit-Frequency: wöchentlich während Marathon vs.
   täglich -- Mira / Henrik Abstimmung.
4. Notify-Cascade-Integration: soll Override automatisch
   Aufsichtsrat-Push triggern? (Tag-65-Listener emittiert
   `applied: true` -- downstream-Hook ist out-of-scope dieser
   ADR.)

## Anchors

* Tag-44 AR-Hand-Stop-Marker (Tomás): pattern-Vorlage.
* Tag-64 Cutover-Day-Morgen Auto-Scheduler (Selin): input-source.
* Tag-65 Listener: `tooling/ci/ar_hand_cutover_override_listener.py`.
* Tag-65 Tests:
  `tests/ci/test_ar_hand_cutover_override_listener_tag65.py`.
* ADR-0068: Status-Aggregator-Workflow-Required-Check (sibling).

-- Tomás (Matrix-Lead-Hut, Tag-65 Continuous-Mode)
