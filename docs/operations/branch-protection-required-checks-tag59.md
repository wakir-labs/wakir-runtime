---
title: "Branch-Protection Required-Check Wiring Doc (Tag-59)"
status: "active"
owner: "kai"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-59"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
related_docs:
  - "docs/operations/strict-flip-readiness-map-tag58.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
related_memory:
  - "feedback_branch_protection_check_names.md"
---

# Branch-Protection Required-Check Wiring Doc (Tag-59)

Operator-Hand-Recipe für die einmalige Aktivierung von 5 Required-
Status-Checks in der `main`-Branch-Protection-Konfiguration des
Repos `wakir-labs/wakir-runtime`. Alle hier dokumentierten Schritte
sind **Operator-Hand-Sandbox-Gap** — die Mira-Sandbox darf keinen
Branch-Protection-Settings-Write-Zugriff haben (ADR-0020 §10,
Memory `feedback_sandbox_host_trennung`).

Ziel: nachvollziehbares Wiring-Bild der 5 pending Required-Checks
plus eine verbindliche Aktivierungs-Reihenfolge mit Risk-Map und
Post-Aktivierungs-Smoke.

Hintergrund: Memory `feedback_branch_protection_check_names`
(PR #102 forever-pending 2026-05-16) — Required-Status-Checks
brauchen den **exakten Job-Display-Name** des Jobs (`jobs.<id>.name`
im Workflow-File), nicht den Workflow-Namen (`name:` auf top-level).
Falsche Check-Names lassen PRs unendlich auf einen nie feuernden
Check warten.

## §1 — Status pro Required-Check

Zustand pro Required-Check zum Stand 2026-05-19 (Tag-59, 05:21 CEST).
Quelle: GitHub-Actions-Runs gegen `main` post-Merge.

| # | Job-Display-Name (verbatim) | Workflow-File | Source-PR | erster-grüner-main-Run | Aktivierungs-Status |
|---|---|---|---|---|---|
| 1 | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | `.github/workflows/cross-substrate-parity-gate.yml` | #367 (Kai, Tag-57) | confirmed green on main (merged 2026-05-19T02:52:58Z) | **PENDING-OPERATOR** |
| 2 | `pyramide layer-dependency DAG verify (6 layers, 16 edges)` | `.github/workflows/pyramide-layer-dependency-verify-gate.yml` | #374 (Amara, Tag-58) | confirmed green on main (merged 2026-05-19T03:16:04Z) | **PENDING-OPERATOR** |
| 3 | `verify-containerfile-base-image-digest-pins` | `.github/workflows/containerfile-digest-pin-gate.yml` | #366 (Tomás, Tag-57) | confirmed green on main (merged 2026-05-19T02:50:31Z) | **PENDING-OPERATOR** |
| 4 | `wirelang spec v0.4.3 freeze-seal probe` | `.github/workflows/wirelang-spec-freeze-seal-probe.yml` | #371 (Reza, Tag-58) | confirmed green on main (merged 2026-05-19T03:11:48Z) | **PENDING-OPERATOR** |
| 5 | `alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)` | `.github/workflows/alert-routing-cross-repo-mirror.yml` | #373 (Noa, Tag-58) | confirmed green on main (merged 2026-05-19T03:12:13Z) | **PENDING-OPERATOR-AUDIT-ONLY** |

Anmerkungen zur Check-Name-Disziplin:
- Display-Names sind **wörtlich** (inklusive Unicode-Pfeile `↔`,
  Klammern, Spaces) zu übernehmen — Memory-Lesson PR #102.
- Display-Name kommt aus `jobs.<id>.name:` im Workflow-File, nicht
  aus dem Top-Level `name:`.
- Bei Diskrepanz: gh-api zeigt den realen Check-Run-Name, der von
  GitHub angelegt wird; siehe §3-Verifikations-Checklist.

## §2 — Operator-Hand-Aktivierungs-Recipe

Operator-Hand-Sandbox-Gap. Nicht in Mira-Sandbox ausführen. Zwei
Pfade dokumentiert: gh-api (Skript-fähig) und Web-UI (manuell).

### §2.1 — gh-api Pfad (empfohlen)

Voraussetzung: Operator-Token mit `repo` + `admin:repo_hook` +
`administration:write` Scopes.

```bash
# Snapshot der aktuellen Required-Checks (vor Änderung)
gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
  --jq '.required_status_checks.contexts' \
  > /tmp/branch-protection-required-checks-snapshot-pre-tag59.json

# Aktualisierung (Beispiel-Payload — Operator passt zusätzlich
# bestehende Settings via /branches/main/protection PUT an;
# unten nur der required_status_checks-Block).
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
      "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)"
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
  > /tmp/branch-protection-required-checks-snapshot-post-tag59.json
diff /tmp/branch-protection-required-checks-snapshot-pre-tag59.json \
     /tmp/branch-protection-required-checks-snapshot-post-tag59.json
```

Disziplin: Der Operator muss **alle** bisherigen Required-Checks
in den `contexts`-Array übernehmen — der PUT überschreibt komplett.
Snapshot pre-PUT ist die Quelle.

### §2.2 — Web-UI Pfad

Pfad: `Settings → Branches → Branch protection rules → main → Edit →
"Require status checks to pass before merging" → Status checks that
are required → Add checks`.

Reihenfolge der UI-Eingabe identisch zu §4.

## §3 — Pre-Aktivierungs-Verifikations-Checklist

Pflicht vor jedem PUT bzw. UI-Save. Operator-Hand.

### §3.1 — Schritt 1: erster grüner main-Run bestätigen

Für jeden der 5 Checks:

```bash
gh api repos/wakir-labs/wakir-runtime/commits/main/check-runs \
  --jq '.check_runs[] | {name, status, conclusion}' \
  | grep -F '<DISPLAY-NAME>'
```

Erwartung: mindestens ein Eintrag mit `"conclusion": "success"`.
Falls leer: Check feuert noch nicht gegen main → **nicht
aktivieren** (würde alle PRs blockieren).

### §3.2 — Schritt 2: Check-Name-Verbatim-Match

Display-Name aus gh-api **bit-genau** mit `contexts`-Array
abgleichen. Häufige Fallen:

- Unicode-Pfeil `↔` (U+2194) vs. ASCII-Approximation `<->`.
- Trailing-Spaces.
- Klammer-Inhalt (z.B. `(6 layers, 16 edges)` vs. nur Funktion).
- Workflow-Top-Level-`name` (`cross-substrate-parity-gate`) vs.
  Job-Display-`name` (`cross-substrate parity (cosign ↔ quadlet ↔
  backend-switch)`).

### §3.3 — Schritt 3: PR-Review-Stack abgleichen

Vor PUT prüfen ob offene PRs existieren, die durch Aktivierung
unintended-blocked werden. Falls ja: PR-Owner notifizieren oder
PUT verschieben bis nach Rebase.

## §4 — Aktivierungs-Reihenfolge mit Risk-Map

Empfohlene Sequenz für die Operator-Hand-Session. Reihenfolge minimiert
das Coupling-Failure-Risk: zuerst die isoliertesten Checks (single-
repo, kein Cross-Repo-Reach), dann die Cross-Repo-Checks.

| Reihenfolge | Check | Coupling-Failure-Mode | Risk-Level |
|---|---|---|---|
| **1** | `verify-containerfile-base-image-digest-pins` | Isoliert, nur Containerfile-Pattern-Match. Failure-Mode: false-positive auf legit Containerfile-Updates. | low |
| **2** | `wirelang spec v0.4.3 freeze-seal probe` | Isoliert, nur Spec-Dir-Pfad-Check + Freeze-Marker. Failure-Mode: blockiert legit Spec-Edits post-Freeze (gewollt). | low |
| **3** | `pyramide layer-dependency DAG verify (6 layers, 16 edges)` | DAG-Verify gegen Layer-Manifest; abhängig von Layer-Refactors. Failure-Mode: false-positive bei legit Layer-Topology-Shift. | medium |
| **4** | `cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)` | Drei-Wege-Parity, abhängig von Cosign-Manifest, Quadlet-Files, BackendDecision-Engine. Failure-Mode: false-positive bei legit Substrate-Add. | medium |
| **5** | `alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)` | Cross-Repo-Clone von `wakir-protocol`. Failure-Mode: Network-Flake → 5xx von github.com clone → unintended block. Tag-58 als **audit-only initial** dokumentiert; Aktivierung als Required-Check unter Vorbehalt. | high |

Empfohlene Pause zwischen Schritten: mindestens 1 erfolgreicher
Test-PR-Smoke (siehe §5) pro Check vor dem nächsten Aktivierungs-
Schritt. Bei high-Risk-Check #5 explizit: zwei Tage observability
bevor Activation als Required (audit-only Run-Akkumulation).

Risk-Map-Notiz zu Check #5: gemäss PR #373 ist der Check initial
**audit-only** designt. Die Aktivierung als Required-Status-Check
kann verzögert werden bis ≥ 3 grüne main-Runs ohne 5xx-Flake
akkumuliert sind. Memory-Cross-Ref: `feedback_anti_eskalations_drift`
(operative Hygiene-Items sind Mira/Operator-Hand, nicht AR).

## §5 — Post-Aktivierungs-Smoke

Nach jedem Schritt aus §4 (also fünfmal) führt der Operator einen
Smoke-Test durch.

### §5.1 — Smoke-Test-Recipe

```bash
# 1. Test-PR-Branch (harmloser Touch)
git checkout -b operator/smoke-required-check-<CHECK-N>-<DATE>
date -Iseconds > docs/operations/.smoke-touch-<CHECK-N>.txt
git add docs/operations/.smoke-touch-<CHECK-N>.txt
git commit -m "smoke(operator): trigger required-check #<CHECK-N>"
git push -u origin HEAD

# 2. PR erstellen
gh pr create --title "smoke(operator): required-check #<CHECK-N> verification" \
             --body "Operator-Hand-Smoke-Test für Required-Check #<CHECK-N>. \
                     Self-close after green." \
             --base main

# 3. Verify Required-Check feuert
sleep 30
gh pr checks <PR-NUMBER> --json name,state \
  | grep -F '<DISPLAY-NAME>'

# Erwartung: state = "pending" oder "success", state ≠ "skipped".
# Falls "skipped" oder fehlt → Check-Name-Mismatch (§3.2 wiederholen).

# 4. Post-Verify: PR closen ohne merge
gh pr close <PR-NUMBER> --delete-branch
```

### §5.2 — Smoke-Pass-Kriterien

Pro Required-Check ist der Smoke-Test grün wenn:

1. Check erscheint in `gh pr checks <N>` mit dem **exakten** Display-
   Name (Unicode-bit-genau).
2. Check-State ist `pending` (Run läuft) oder `success` (Run done).
3. Check-State ist **nicht** `skipped` (Workflow-Condition-Failure)
   oder `missing` (Check-Name-Mismatch).
4. PR-Merge-Button ist disabled wenn Check `pending` (Beweis für
   Required-Status-Enforcement).

### §5.3 — Smoke-Fail-Triage

Falls Smoke fehlschlägt:

- **`skipped`-State**: Workflow `on:`-Trigger prüfen; PR-Path-Filter
  schließt Smoke-Touch-Datei aus. Operator-Hand-Fix: Touch-Pfad
  ändern auf Pfad innerhalb Workflow-Trigger-Pattern.
- **Check fehlt komplett**: Check-Name-Mismatch (§3.2). PUT-Payload
  korrigieren, neu submitten.
- **5xx-Flake**: bei Check #5 erwartbar — retry +30 Min.

## §6 — Sandbox-Boundary

Durchgängige Markierung:

| Phase | Sandbox | Operator-Hand |
|---|---|---|
| Doc-Erstellung (Tag-59 dieses Doc) | **JA** (Mira-Sandbox, Kai-Spawn) | nein |
| gh-api Branch-Protection PUT | nein | **JA** (Operator-Workstation, ADR-0020 §10) |
| Web-UI Settings-Save | nein | **JA** (Browser-Session des Operators) |
| Smoke-Test-PR-Erstellung | **JA** (kann via Kai-Spawn) | optional |
| Smoke-Test-Verify (`gh pr checks`) | **JA** (read-only) | optional |
| Branch-Protection-Snapshot Audit (read-only) | **JA** (read-only gh-api) | optional |

Memory-Cross-Ref: `feedback_sandbox_host_trennung` — claude-dev darf
keinen Host-Operator-Token-Zugriff haben. `feedback_live_bringup_sandbox_gap`
— Live-Setup-Schritte sind Operator-Hand.

ADR-0020 §10 (Befugnis-Rahmen Kai): "Kein Push auf Remote-Repos
ohne explizite CEO-Freigabe pro Push" — Branch-Protection-PUT ist
inherent Operator-Hand, nicht Kai-Hand.

— Kai (Tag-59, 2026-05-19)
