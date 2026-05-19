---
title: "Branch-Protection Required-Check Wiring Doc Addendum (Tag-61)"
status: "active"
owner: "kai"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-61"
predecessor: "docs/operations/branch-protection-required-checks-tag59.md"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
related_docs:
  - "docs/operations/branch-protection-required-checks-tag59.md"
  - "docs/operations/branch-protection-required-status-checks.md"
related_prs:
  - "#386"
  - "#387"
related_memory:
  - "feedback_branch_protection_check_names.md"
  - "feedback_sandbox_host_trennung.md"
---

# Branch-Protection Required-Check Wiring Doc Addendum (Tag-61)

Erweiterung des Tag-59-Wiring-Docs um die zwei neuen Required-Status-
Check-Kandidaten aus Tag-60. Predecessor:
`docs/operations/branch-protection-required-checks-tag59.md`. Alle
Aktivierungs-Schritte bleiben **Operator-Hand-Sandbox-Gap** (ADR-0020
§10, Memory `feedback_sandbox_host_trennung`); diese Doc ist
Doc-Form-Only, keine Settings-Mutation.

Hintergrund: Tag-60 brachte zwei neue grüne main-Workflows mit
Required-fähigem Job-Display-Name. Sie kommen als sechster und siebter
Required-Check zum Tag-59-Pool hinzu und reihen sich in §4-
Aktivierungs-Reihenfolge nach Risk-Map-Stufung. Die etablierte Tag-59-
Check-Name-Verbatim-Disziplin (§3.2, Memory
`feedback_branch_protection_check_names`) gilt unverändert.

## §1 — Erweiterung der Required-Check-Tabelle (Tag-61 Addendum)

Zustand pro Required-Check zum Stand 2026-05-19 (Tag-61, post-merge
PR #386 + #387). Quelle: `gh api repos/wakir-labs/wakir-runtime/
commits/main/check-runs` plus Workflow-File-Verifikation
`.github/workflows/<file>.yml` `jobs.<id>.name` Field.

| # | Job-Display-Name (verbatim) | Workflow-File | Source-PR | erster-grüner-main-Run | Aktivierungs-Status |
|---|---|---|---|---|---|
| 6 | `pyramide cross-run stability pin (5 fixtures, 3 runs each)` | `.github/workflows/pyramide-cross-run-stability-pin-gate.yml` | #387 (Amara, Tag-60) | confirmed green on main (merged 2026-05-19T10:29:53Z, sha 1543ec0) | **PENDING-OPERATOR** |
| 7 | `g1-g2 operator-recipe smoke-validation` | `.github/workflows/g1-g2-operator-recipe-smoke-validation.yml` | #386 (Kai, Tag-60) | confirmed green on main (merged 2026-05-19T10:34:46Z, sha f91712a) | **PENDING-OPERATOR-AUDIT-ONLY** |

Anmerkungen zur Check-Name-Disziplin (Tag-61-Verstärkung der Tag-59-
§1-Regel):
- Check #6 `pyramide cross-run stability pin (5 fixtures, 3 runs each)`
  enthält Klammer-Inhalt `(5 fixtures, 3 runs each)` der **wörtlich**
  Bestandteil des Display-Names ist. Inline-Kommentar im Workflow-File
  weist explizit darauf hin: "Job-Display-Name MUSS exakt dieser
  String sein - er ist der Required-Status-Check-Name den Mira-Hand
  in Branch-Protection aktiviert (per
  feedback_branch_protection_check_names.md)". §3.2-Tag-59-Falle
  greift hier (Klammer-Inhalt).
- Check #7 `g1-g2 operator-recipe smoke-validation` enthält Bindestrich-
  Compound `g1-g2` — keine Unicode-Zeichen, aber Lowercase-Disziplin
  wichtig. Top-Level-Workflow-`name:` ist
  `g1-g2-operator-recipe-smoke-validation` (mit zusätzlichen Bindestrichen
  zwischen `g1-g2` und `operator-recipe`); der Job-`name:` hat dazwischen
  einen **Space** statt Bindestrich. Häufige Falle: copy/paste vom
  Workflow-Filename statt vom Job-Display-Name.

Aktualisierte Tag-61-Gesamt-Pool-Bilanz (Tag-59 + Tag-61-Addendum):

| Pool-Slot | Display-Name | Aktivierungs-Status | Tag-Quelle |
|---|---|---|---|
| 1 | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | PENDING-OPERATOR | Tag-59 |
| 2 | `pyramide layer-dependency DAG verify (6 layers, 16 edges)` | PENDING-OPERATOR | Tag-59 |
| 3 | `verify-containerfile-base-image-digest-pins` | PENDING-OPERATOR | Tag-59 |
| 4 | `wirelang spec v0.4.3 freeze-seal probe` | PENDING-OPERATOR | Tag-59 |
| 5 | `alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)` | PENDING-OPERATOR-AUDIT-ONLY | Tag-59 |
| 6 | `pyramide cross-run stability pin (5 fixtures, 3 runs each)` | PENDING-OPERATOR | **Tag-61** |
| 7 | `g1-g2 operator-recipe smoke-validation` | PENDING-OPERATOR-AUDIT-ONLY | **Tag-61** |

Pool-Total: 7 Required-Status-Check-Kandidaten pending Operator-Hand-
Aktivierung. Tag-61-Addendum-Delta: +2.

## §2 — Operator-Hand-Aktivierungs-Recipe (Delta zur Tag-59-§2)

Recipe-Form unverändert; einzig die `contexts`-Array-Payload für den
`gh api -X PUT` erweitert sich um die beiden neuen Display-Names.

```bash
# Snapshot der aktuellen Required-Checks (vor Tag-61-Erweiterung)
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/branch-protection-required-checks-snapshot-pre-tag61.json

# Tag-61-Erweiterung (Beispiel-Payload — Operator passt zusätzlich
# bestehende Settings via /branches/main/protection PUT an; unten
# nur der required_status_checks-Block mit 7-Pool).
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
      "g1-g2 operator-recipe smoke-validation"
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
  > /tmp/branch-protection-required-checks-snapshot-post-tag61.json
diff /tmp/branch-protection-required-checks-snapshot-pre-tag61.json \
     /tmp/branch-protection-required-checks-snapshot-post-tag61.json
```

Disziplin: Der PUT-Replace überschreibt komplett — der Operator muss
**alle** sieben Display-Names im `contexts`-Array übernehmen. Snapshot
pre-PUT ist die Quelle. Memory-Cross-Ref:
`feedback_branch_protection_check_names`.

## §3 — Pre-Aktivierungs-Verifikations-Checklist (Delta-Notiz)

Tag-59-§3-Checklist-Schritte gelten 1:1 für #6 und #7. Zusatz-Notizen
für die zwei neuen Checks:

### §3.1 — Bestätigung erster grüner main-Run (Tag-61-Delta)

Für Check #6:

```bash
gh api repos/wakir-labs/wakir-runtime/commits/main/check-runs \
  --jq '.check_runs[] | {name, status, conclusion}' \
  | grep -F 'pyramide cross-run stability pin (5 fixtures, 3 runs each)'
```

Für Check #7:

```bash
gh api repos/wakir-labs/wakir-runtime/commits/main/check-runs \
  --jq '.check_runs[] | {name, status, conclusion}' \
  | grep -F 'g1-g2 operator-recipe smoke-validation'
```

Erwartung: mindestens ein Eintrag mit `"conclusion": "success"`.

### §3.2 — Check-Name-Verbatim-Match (Tag-61-spezifische Fallen)

Häufige Fallen für Tag-61-Checks:

- **#6**: Klammer-Inhalt `(5 fixtures, 3 runs each)` — vollständig
  übernehmen. Komma + Space nach `fixtures` ist Teil des Strings.
- **#6**: Trailing-Whitespace im Klammer-String — leichter Lapsus
  beim Copy-Paste aus IDE; `grep -F` deckt das nicht ab, `gh api`
  Vergleich byte-exakt.
- **#7**: `g1-g2` vs. `G1-G2` — Lowercase ist Pflicht (Workflow-File
  declared lowercase `name:` field).
- **#7**: `operator-recipe` vs. `operator recipe` — Bindestrich-Compound
  zwischen `operator` und `recipe`.
- **#7**: Workflow-Top-Level-`name:` `g1-g2-operator-recipe-smoke-
  validation` (3 Bindestriche zwischen Token-Gruppen) vs. Job-`name:`
  `g1-g2 operator-recipe smoke-validation` (2 Bindestriche + 2
  Spaces). Letzteres ist der Required-Status-Check-Name.

### §3.3 — PR-Review-Stack-Abgleich

Tag-59-§3.3 unverändert. Vor Tag-61-Aktivierung prüfen ob offene PRs
existieren, die durch die zwei neuen Required-Checks unintended-blocked
würden. Insbesondere für #6 (pyramide cross-run stability pin): legit
Layer-Manifest-Changes können hier false-positive führen. Für #7
(g1-g2 operator-recipe smoke-validation): Cosign-Strict-Mode-Recipe-
Edits können den Smoke-Validation-Pfad ändern.

## §4 — Aktivierungs-Reihenfolge mit Risk-Map (Tag-61-Erweiterung)

Tag-61-Pool: 7 Required-Checks. Empfohlene Sequenz erweitert die
Tag-59-Reihenfolge um zwei zusätzliche Schritte, in Risk-Stufung
einsortiert nach §4.4 Tag-59-Pattern (low → medium → high; isoliert
→ cross-coupled).

| Reihenfolge | Check | Coupling-Failure-Mode | Risk-Level | Tag-Quelle |
|---|---|---|---|---|
| **1** | `verify-containerfile-base-image-digest-pins` | Isoliert, nur Containerfile-Pattern-Match. Failure-Mode: false-positive auf legit Containerfile-Updates. | low | Tag-59 |
| **2** | `wirelang spec v0.4.3 freeze-seal probe` | Isoliert, nur Spec-Dir-Pfad-Check + Freeze-Marker. Failure-Mode: blockiert legit Spec-Edits post-Freeze (gewollt). | low | Tag-59 |
| **3** | `g1-g2 operator-recipe smoke-validation` | Isoliert, Sandbox-Recipe-Verify (Doc-Form, kein Live-Cosign-Call). Failure-Mode: Recipe-File-Edit ohne Doc-Refresh führt zu false-positive. Stufung als audit-only initial empfohlen — Aktivierung als Required nach ≥ 2 grünen main-Runs. | low-medium | **Tag-61** |
| **4** | `pyramide layer-dependency DAG verify (6 layers, 16 edges)` | DAG-Verify gegen Layer-Manifest; abhängig von Layer-Refactors. Failure-Mode: false-positive bei legit Layer-Topology-Shift. | medium | Tag-59 |
| **5** | `pyramide cross-run stability pin (5 fixtures, 3 runs each)` | Multi-Fixture-Stability-Pin (5 fixtures × 3 runs); abhängig von Pyramide-Fixture-Topologie und Run-Reproduzierbarkeit. Failure-Mode: Flake bei Fixture-Add ohne Pin-Refresh; Multi-Run-Topology-Drift. | medium | **Tag-61** |
| **6** | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | Drei-Wege-Parity, abhängig von Cosign-Manifest, Quadlet-Files, BackendDecision-Engine. Failure-Mode: false-positive bei legit Substrate-Add. | medium | Tag-59 |
| **7** | `alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)` | Cross-Repo-Clone von `wakir-protocol`. Failure-Mode: Network-Flake → 5xx von github.com clone → unintended block. Audit-only initial. | high | Tag-59 |

Empfohlene Pause zwischen Schritten: mindestens 1 erfolgreicher
Test-PR-Smoke (Tag-59-§5) pro Check vor dem nächsten Aktivierungs-
Schritt.

Risk-Map-Notizen für die zwei Tag-61-Checks:

- **Check #6 (pyramide cross-run stability pin)**: Stufung medium
  wegen Multi-Run-Reproduzierbarkeits-Anforderung (3 Runs pro 5
  Fixtures). Ein Flake-Run führt zum Required-PENDING. Operator-Hand
  prüft vor Aktivierung: mindestens 2 aufeinanderfolgende main-Runs
  grün ohne Flake. Falls Flake-Rate > 1/20 Runs: Aktivierung
  zurückstellen bis Flake-Quelle identifiziert (cross-ref:
  `feedback_live_bringup_sandbox_gap` für hosted-runner-Flakes).
- **Check #7 (g1-g2 operator-recipe smoke-validation)**: Stufung
  low-medium wegen Sandbox-Recipe-Form (Doc-Form, kein Live-Cosign-
  Call). Failure-Mode hauptsächlich Recipe-Edit-ohne-Doc-Refresh-
  Drift. Empfohlene Aktivierung als **audit-only initial** (analog
  Tag-59 Check #5): ≥ 2 grüne main-Runs akkumulieren bevor Required-
  Promotion. Memory-Cross-Ref: `feedback_anti_eskalations_drift`
  (operative Hygiene-Items sind Operator-Hand, kein AR-Reaching).

Aktivierungs-Reihenfolge-Rationale: Tag-59-§4-Pattern "isolierteste
zuerst, cross-coupled zuletzt" gilt fort. #7 ist isoliert (Recipe-
Smoke ist single-repo, kein Cross-Repo-Reach) — daher Position 3.
#6 ist medium-coupled (5 Fixtures × 3 Runs Reproduzierbarkeit) —
daher Position 5 zwischen den Tag-59-medium-Checks. Keine
Vermischung mit Tag-59-§4-Reihenfolge unter dem high-Risk-Check #7
(alert-routing cross-repo mirror) — der bleibt letzter (Position 7
im Pool).

## §5 — Post-Aktivierungs-Smoke (Delta-Notiz)

Tag-59-§5-Smoke-Test-Recipe gilt 1:1 für #6 und #7. Smoke-Touch-
Pfad-Hinweise für die Tag-61-Checks:

- **#6 (pyramide cross-run stability pin)**: Smoke-Touch-Pfad muss
  unter dem Workflow-Trigger-Pattern liegen. Falls Workflow nur auf
  `wirelang/**` oder `tests/quality_gates/**` triggert: Touch-Pfad
  entsprechend wählen. Falls Workflow auf `**` triggert (universal):
  beliebiger Touch-Pfad genügt.
- **#7 (g1-g2 operator-recipe smoke-validation)**: Smoke-Touch-Pfad
  innerhalb von `tooling/ci/`, `docs/operations/`, oder
  `tests/observability/` empfohlen (Workflow triggert auf Recipe-File-
  Bereich). Andere Pfade riskieren `skipped`-State.

Smoke-Pass-Kriterien identisch zu Tag-59-§5.2.

## §6 — Sandbox-Boundary (Tag-61-Delta)

Tag-59-§6-Boundary-Tabelle gilt unverändert. Diese Tag-61-Doc selbst
ist Sandbox-Erstellung (Kai-Spawn in Mira-Sandbox); die Aktivierung
der zwei neuen Checks erfolgt Operator-Hand.

| Phase | Mira-Sandbox | Operator-Hand |
|---|---|---|
| Doc-Erstellung (Tag-61 Addendum dieses Doc) | **JA** (Mira-Sandbox, Kai-Spawn) | nein |
| gh-api Branch-Protection PUT (Tag-61-erweiterter Pool) | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| Smoke-Test-PR-Erstellung für #6 + #7 | **JA** (kann via Kai-Spawn) | optional |
| Smoke-Test-Verify für #6 + #7 (`gh pr checks`) | **JA** (read-only) | optional |
| Branch-Protection-Snapshot Audit (read-only) | **JA** (read-only gh-api) | optional |

Memory-Cross-Refs: `feedback_sandbox_host_trennung` —
claude-dev/Kai-Spawn darf keinen Host-Operator-Token-Zugriff haben.
`feedback_live_bringup_sandbox_gap` — Live-Setup-Schritte sind
Operator-Hand. ADR-0020 §10: "Kein Push auf Remote-Repos ohne
explizite CEO-Freigabe pro Push" — Branch-Protection-PUT ist inherent
Operator-Hand, nicht Kai-Hand.

— Kai (Tag-61, 2026-05-19)
