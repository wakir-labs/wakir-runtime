---
title: "Branch-Protection Required-Check Wiring Doc Companion (Tag-64)"
status: "active"
owner: "amara"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-64"
predecessor: "docs/operations/branch-protection-required-checks-tag61-addendum.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
related_docs:
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-checks-tag61-addendum.md"
  - "docs/operations/branch-protection-required-status-checks.md"
related_prs:
  - "#400"
related_memory:
  - "feedback_branch_protection_check_names.md"
  - "feedback_sandbox_host_trennung.md"
  - "feedback_live_bringup_sandbox_gap.md"
---

# Branch-Protection Required-Check Wiring Doc Companion (Tag-64)

Erweiterung des Tag-61-Addendums um den achten Required-Status-Check-
Kandidaten aus Tag-63: das `E2E verdict (READY / DRIFT / DEFECT)`-Job-
Display-Name aus dem hermetic Pre-Cutover-Final-Acceptance E2E-Smoke
(PR #400, Amara, Tag-63). Predecessor:
`docs/operations/branch-protection-required-checks-tag61-addendum.md`.
Alle Aktivierungs-Schritte bleiben **Operator-Hand-Sandbox-Gap**
(ADR-0020 §10, Memory `feedback_sandbox_host_trennung`); diese Doc
ist Doc-Form-Only, keine Settings-Mutation.

Hintergrund: Tag-63 brachte den finalen E2E-Smoke-Workflow als
geschlossene Schleife ueber S1..S4 der Pre-Cutover-Final-Acceptance-
Pipeline. Der Aggregator-Job `e2e-verdict` traegt den Required-fähigen
Job-Display-Name `E2E verdict (READY / DRIFT / DEFECT)` und kommt
als achter Required-Check zum Tag-61-Pool hinzu. Die etablierte
Check-Name-Verbatim-Disziplin (Tag-59 §3.2, Memory
`feedback_branch_protection_check_names`) gilt unveraendert.

## §1 — Erweiterung der Required-Check-Tabelle (Tag-64 Companion)

Zustand des neuen Required-Check-Kandidaten zum Stand 2026-05-19
(Tag-64, post-merge PR #400). Quelle: Workflow-File-Verifikation
`.github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml`
`jobs.e2e-verdict.name` Field.

| # | Job-Display-Name (verbatim) | Workflow-File | Source-PR | erster-gruener-main-Run | Aktivierungs-Status |
|---|---|---|---|---|---|
| 8 | `E2E verdict (READY / DRIFT / DEFECT)` | `.github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml` | #400 (Amara, Tag-63) | pending — Workflow trigger ist `pull_request` + `workflow_dispatch` only, kein `push` auf `main`. Operator-Hand muss vor Aktivierung **mindestens einen** manuellen `workflow_dispatch`-Run gegen `main` ausloesen und auf `success` warten. | **PENDING-OPERATOR-AUDIT-ONLY** |

Anmerkungen zur Check-Name-Disziplin (Tag-64-Verstaerkung der Tag-59-
§1-Regel):

- Check #8 `E2E verdict (READY / DRIFT / DEFECT)` enthaelt Klammer-
  Inhalt `(READY / DRIFT / DEFECT)` der **woertlich** Bestandteil des
  Display-Names ist. Die drei Slash-getrennten Tokens sind durch
  Space-Slash-Space getrennt (` / `), nicht durch Komma. Falle:
  Copy-Paste aus Markdown-Tabellen ersetzt manchmal ` / ` durch ` | `
  oder `,`.
- Check #8 mischt Case: `E2E` ist uppercase (zwei Buchstaben +
  Ziffer); `verdict` ist lowercase. Falle: Lowercase-Autocorrect auf
  `e2e verdict` bricht den verbatim-Match.
- Check #8 setzt voraus, dass der `e2e-verdict`-Job nicht via
  `needs:`-Fan-In auf einem failed Upstream-Job hängt; sonst zeigt
  GitHub den Required-Check als `skipped` (= ungrün), nicht als
  `success`. Im Tag-63-Workflow steuert der Aggregator-Job aktiv die
  Verdict-Logik (READY/DRIFT/DEFECT) und ist self-contained nach
  S1..S4-`outputs`-Aggregation; daher kein `skipped`-Risiko bei
  voll-grünem upstream-Lauf. **Aber:** Bei `cancel`ed S1..S4-Stages
  durch Concurrency-Re-Run kann `e2e-verdict` als `skipped`
  erscheinen — Operator-Hand prueft dies vor Aktivierung.

Aktualisierte Tag-64-Gesamt-Pool-Bilanz (Tag-59 + Tag-61-Addendum +
Tag-64-Companion):

| Pool-Slot | Display-Name | Aktivierungs-Status | Tag-Quelle |
|---|---|---|---|
| 1 | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | PENDING-OPERATOR | Tag-59 |
| 2 | `pyramide layer-dependency DAG verify (6 layers, 16 edges)` | PENDING-OPERATOR | Tag-59 |
| 3 | `verify-containerfile-base-image-digest-pins` | PENDING-OPERATOR | Tag-59 |
| 4 | `wirelang spec v0.4.3 freeze-seal probe` | PENDING-OPERATOR | Tag-59 |
| 5 | `alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)` | PENDING-OPERATOR-AUDIT-ONLY | Tag-59 |
| 6 | `pyramide cross-run stability pin (5 fixtures, 3 runs each)` | PENDING-OPERATOR | Tag-61 |
| 7 | `g1-g2 operator-recipe smoke-validation` | PENDING-OPERATOR-AUDIT-ONLY | Tag-61 |
| 8 | `E2E verdict (READY / DRIFT / DEFECT)` | PENDING-OPERATOR-AUDIT-ONLY | **Tag-64** |

Pool-Total: 8 Required-Status-Check-Kandidaten pending Operator-Hand-
Aktivierung. Tag-64-Companion-Delta: +1.

## §2 — Operator-Hand-Aktivierungs-Recipe (Delta zur Tag-61-§2)

Recipe-Form unveraendert; einzig die `contexts`-Array-Payload für den
`gh api -X PUT` erweitert sich um den achten Display-Name. Der Kai-
Tag-62-Bulk-Aktivierungs-Helper (`tooling/ops/
_bulk_activate_required_checks.py`) wurde im Tag-64-Pass additiv um
diesen achten Check erweitert; siehe §2.2.

### §2.1 — Direkt-Recipe (Manual-Form)

```bash
# Snapshot der aktuellen Required-Checks (vor Tag-64-Erweiterung)
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/branch-protection-required-checks-snapshot-pre-tag64.json

# Tag-64-Erweiterung (Beispiel-Payload — Operator passt zusaetzlich
# bestehende Settings via /branches/main/protection PUT an; unten
# nur der required_status_checks-Block mit 8-Pool).
gh api -X PUT repos/wakir-labs/wakir-runtime/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
      "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
      "verify-containerfile-base-image-digest-pins",
      "wirelang spec v0.4.3 freeze-seal probe",
      "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
      "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
      "g1-g2 operator-recipe smoke-validation",
      "E2E verdict (READY / DRIFT / DEFECT)"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON

# Post-Snapshot
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/branch-protection-required-checks-snapshot-post-tag64.json
diff /tmp/branch-protection-required-checks-snapshot-pre-tag64.json \
     /tmp/branch-protection-required-checks-snapshot-post-tag64.json
```

Disziplin: Der PUT-Replace ueberschreibt komplett — der Operator muss
**alle** acht Display-Names im `contexts`-Array uebernehmen. Snapshot
pre-PUT ist die Quelle. Memory-Cross-Ref:
`feedback_branch_protection_check_names`.

### §2.2 — Bulk-Helper-Recipe (Planner-Form, Tag-62 lineage)

Der Tag-62-Bulk-Aktivierungs-Helper liest jetzt **drei** Doc-Quellen
(Tag-59 §1 + Tag-61 §1 + Tag-64 §1) und assembled den 8-Pool. Aufruf:

```bash
python3 tooling/ops/_bulk_activate_required_checks.py \
  --tag59-doc docs/operations/branch-protection-required-checks-tag59.md \
  --tag61-doc docs/operations/branch-protection-required-checks-tag61-addendum.md \
  --tag64-doc docs/operations/branch-protection-required-checks-tag64-companion.md \
  --put-payload
```

Output ist das `required_status_checks`-JSON-Block fuer den `gh api
-X PUT`-Call. Idempotency-Disziplin (`feedback_high_tempo_spawn_
collision`): der Helper validiert die Pool-Bilanz-Konsistenz und
weigert sich, ein inkonsistentes Payload zu emittieren. Operator-Hand
prueft Output-Inhalt vor PUT-Submit gegen die §2.1-Direkt-Form als
Cross-Check.

## §3 — Pre-Aktivierungs-Verifikations-Checklist (Tag-64 Delta)

Tag-59-§3-Checklist-Schritte gelten 1:1 fuer #8. Zusatz-Notizen:

### §3.1 — Bestaetigung erster gruener main-Run (Tag-64-Delta)

```bash
# Schritt 1: workflow_dispatch gegen main ausloesen
gh workflow run pre-cutover-final-acceptance-e2e-smoke.yml \
  --ref main \
  -f enforce=true

# Schritt 2: Run-ID erfassen + auf success warten
gh run list --workflow=pre-cutover-final-acceptance-e2e-smoke.yml \
  --branch=main \
  --limit=1 \
  --json databaseId,status,conclusion

# Schritt 3: Check-Run-Sichtbarkeit auf main-tip pruefen
gh api repos/wakir-labs/wakir-runtime/commits/main/check-runs \
  --jq '.check_runs[] | {name, status, conclusion}' \
  | grep -F 'E2E verdict (READY / DRIFT / DEFECT)'
```

Erwartung: mindestens ein Eintrag mit `"conclusion": "success"`.
Wichtig: Da der Workflow keinen `push`-Trigger hat, muessen
mindestens **zwei** workflow_dispatch-Runs erfolgreich sein, bevor
Promotion auf Required erfolgt — der erste etabliert die
`required_status_checks.contexts`-Eligibility-Sichtbarkeit, der
zweite verifiziert Reproduzierbarkeit.

### §3.2 — Check-Name-Verbatim-Match (Tag-64-spezifische Fallen)

Haeufige Fallen fuer #8:

- **Klammer-Inhalt** `(READY / DRIFT / DEFECT)` — vollstaendig
  uebernehmen. Space-Slash-Space zwischen den drei Tokens (` / `),
  nicht Komma-Space, nicht Pipe.
- **Case-Mix** `E2E verdict` — `E2E` uppercase, `verdict` lowercase.
  Auto-Kapitalisierung in einigen Editoren macht hier `E2E Verdict`
  — bricht den Match.
- **Leading/Trailing-Whitespace** im Klammer-String — leichter
  Lapsus beim Copy-Paste aus IDE; `grep -F` deckt das nicht ab,
  `gh api` Vergleich byte-exakt.

### §3.3 — Concurrency-Race-Falle (Tag-64-spezifisch)

Der Tag-63-Workflow nutzt `concurrency.cancel-in-progress: false`.
Aber bei manuellen Re-Runs (Operator-Hand-Triggers im
Aktivierungs-Smoke) kann ein Job `e2e-verdict` in `skipped`-State
landen wenn ein vorgaengiger Stage-Job `cancelled` ist. Operator
prueft vor Aktivierung: keine `cancelled`-Stage-Jobs im
ausgewaehlten Reference-Run.

## §4 — Aktivierungs-Reihenfolge mit Risk-Map (Tag-64 Erweiterung)

Tag-64-Pool: 8 Required-Checks. Empfohlene Sequenz erweitert die
Tag-61-Reihenfolge um einen zusaetzlichen Schritt, in Risk-Stufung
einsortiert nach §4.4 Tag-59-Pattern (low → medium → high; isoliert
→ cross-coupled).

| Reihenfolge | Check | Coupling-Failure-Mode | Risk-Level | Tag-Quelle |
|---|---|---|---|---|
| **1** | `verify-containerfile-base-image-digest-pins` | Isoliert, nur Containerfile-Pattern-Match. | low | Tag-59 |
| **2** | `wirelang spec v0.4.3 freeze-seal probe` | Isoliert, Spec-Dir + Freeze-Marker. | low | Tag-59 |
| **3** | `g1-g2 operator-recipe smoke-validation` | Isoliert, Sandbox-Recipe-Verify (Doc-Form). | low-medium | Tag-61 |
| **4** | `pyramide layer-dependency DAG verify (6 layers, 16 edges)` | DAG-Verify gegen Layer-Manifest. | medium | Tag-59 |
| **5** | `pyramide cross-run stability pin (5 fixtures, 3 runs each)` | Multi-Fixture-Stability-Pin. | medium | Tag-61 |
| **6** | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | Drei-Wege-Parity. | medium | Tag-59 |
| **7** | `alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)` | Cross-Repo-Clone-Coupling. | high | Tag-59 |
| **8** | `E2E verdict (READY / DRIFT / DEFECT)` | Vier-Stage-Fan-In Aggregator, kein push-Trigger (dispatch-only). Audit-only initial verpflichtend; Promotion erst nach >= 2 gruenen workflow_dispatch-Runs auf main. | **highest** | **Tag-64** |

Empfohlene Pause zwischen Schritten: mindestens 1 erfolgreicher
Test-PR-Smoke (Tag-59-§5) pro Check vor dem naechsten Aktivierungs-
Schritt.

Risk-Map-Notiz fuer #8:

- **Check #8 (E2E verdict)**: Stufung **highest** wegen Vier-Stage-
  Fan-In-Coupling (S1 Pyramide-Compositum, S2 Engine-Compositum, S3
  Cross-Gates, S4 Final-Sanity). Ein Stage-Probe-Defekt cascaded
  durch zum Aggregator. Failure-Mode: legit Refactor in einem der
  vier Stage-Bereiche fuehrt zu E2E-DRIFT oder E2E-DEFECT-Verdict.
  **Audit-only Required**-Stufung initial verpflichtend (analog
  Tag-59 #5 alert-routing + Tag-61 #7 g1-g2): mindestens 2
  aufeinanderfolgende gruene workflow_dispatch-Runs auf main vor
  Promotion zu enforced-Required. Memory-Cross-Ref:
  `feedback_anti_eskalations_drift` + `feedback_live_bringup_
  sandbox_gap`.

Aktivierungs-Reihenfolge-Rationale: Tag-59-§4-Pattern "isolierteste
zuerst, cross-coupled zuletzt" gilt fort. #8 ist im hoechsten
Coupling-Grad (Fan-In ueber alle Pre-Cutover-Pipeline-Stages) —
daher Position 8 als Last-Position im Pool, nach #7 (alert-routing
cross-repo). Promotion-Disziplin haerter als #7 wegen
trigger-Pattern (dispatch-only, kein push), die Required-Sichtbarkeit
verlangt aktive Operator-Hand-Action vor jeder Aktivierungs-Stage.

## §5 — Post-Aktivierungs-Smoke (Delta-Notiz)

Tag-59-§5-Smoke-Test-Recipe gilt 1:1 fuer #8 mit folgender
Anpassung:

- **#8 (E2E verdict)**: Smoke-Touch-Pfad innerhalb von
  `tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py` oder
  `tests/ci/test_pre_cutover_e2e_smoke_tag63.py` oder
  `.github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml`.
  Workflow triggert auf umfassendem path-filter ueber alle vier
  Stage-Substrate; Touch-Pfade ausserhalb dieser Pattern fuehren
  zu `skipped`-State und blockieren dann Required-Eligibility.

Smoke-Pass-Kriterien identisch zu Tag-59-§5.2.

## §6 — Sandbox-Boundary (Tag-64 Delta)

Tag-59-§6-Boundary-Tabelle gilt unveraendert. Diese Tag-64-Doc
selbst ist Sandbox-Erstellung (Amara-Spawn in Mira-Sandbox); die
Aktivierung des neuen Checks #8 erfolgt Operator-Hand.

| Phase | Mira-Sandbox | Operator-Hand |
|---|---|---|
| Doc-Erstellung (Tag-64 Companion dieses Doc) | **JA** (Mira-Sandbox, Amara-Spawn) | nein |
| Bulk-Script additive Erweiterung (8. Check) | **JA** (Mira-Sandbox, Amara-Spawn) | nein |
| workflow_dispatch-Run gegen main (Pre-Aktivierung) | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| gh-api Branch-Protection PUT (Tag-64-erweiterter Pool 8) | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| Smoke-Test-PR-Erstellung fuer #8 | **JA** (kann via Amara-Spawn) | optional |
| Smoke-Test-Verify fuer #8 (`gh pr checks`) | **JA** (read-only) | optional |
| Branch-Protection-Snapshot Audit (read-only) | **JA** (read-only gh-api) | optional |

Memory-Cross-Refs: `feedback_sandbox_host_trennung` —
claude-dev/Amara-Spawn darf keinen Host-Operator-Token-Zugriff
haben. `feedback_live_bringup_sandbox_gap` — Live-Setup-Schritte
(inkl. workflow_dispatch gegen main) sind Operator-Hand. ADR-0020
§10: "Kein Push auf Remote-Repos ohne explizite CEO-Freigabe pro
Push" — Branch-Protection-PUT ist inherent Operator-Hand, nicht
Amara-Hand.

## §7 — Cross-Persona-Coord-Notiz (Tag-64-spezifisch)

Diese Tag-64-Companion ist **additive** zur Tag-61-Addendum von Kai
und zerstoert keinen Kai-Schritt. Der Bulk-Aktivierungs-Helper
(`tooling/ops/_bulk_activate_required_checks.py`, Kai-Tag-62-Lineage)
wurde additiv um einen `--tag64-doc`-Flag erweitert; ohne den Flag
faellt der Helper auf das 7-Pool-Verhalten zurueck (Kai-Tag-62-
Pre-Walk-Recipe). Mit dem Flag bilanziert er den 8-Pool gemaess
Tag-64-Companion.

Tag-62-Walking-Skeleton-Fixtures (`tests/observability/fixtures/
branch-protection-walking-skeleton/`) bleiben fuer den 7-Pool-Pfad
unveraendert — Tag-64-Tests legen separate 8-Pool-Fixtures unter
`tests/observability/fixtures/branch-protection-walking-skeleton-
tag64/` ab.

— Amara (Tag-64, 2026-05-19)
