---
title: "Strict-Flip Readiness Map (Tag-58)"
status: "active"
owner: "kai"
audience: "operator,ar"
created: "2026-05-19"
tag: "tag-58"
related_adrs:
  - "ADR-0020"
  - "ADR-0036"
related_docs:
  - "docs/operations/cosign-g1-g2-operator-setup.md"
  - "docs/operations/cosign-strict-mode-activation.md"
  - "docs/operations/phase-3c-cutover-runbook.md"
---

# Strict-Flip Readiness Map (Tag-58)

Day-by-day Operator-Hand-Recipe für den Strict-Cosign-Flip
pre-KW-24-Cutover. Alle Operator-Hand-Schritte sind als
Operator-Hand-Sandbox-Gap markiert; dieses Dokument ist **keine**
Live-Setup-Anleitung der Mira-Sandbox.

Ziel: nachvollziehbares Gate-für-Gate-Readiness-Bild plus eine
verbindliche 7-Tage-Recipe, die der Operator zwischen Tag-58 und
KW-24-Cutover-Day ausführt.

## §1 — Gate-Status

Zustand pro Strict-Flip-Gate G1..G6 zum Stand 2026-05-19 (Tag-58).
Quelle: `wakir-runtime` main + Cosign-Strict-Mode-Readiness-Check-
CI-Job + Cross-Substrate-Parity-Gate (PR #367, Tag-57).

| Gate | Scope | Status | Blocker | Owner |
|---|---|---|---|---|
| G1 | Quadlet-Cosign-Wiring 4 Wellen + Pilot-Persona | **BLOCKED** | Operator-Hand-PR nötig (siehe §3) | Operator |
| G2 | Trust-Root-Snapshot (cosign + fulcio + rekor pubkeys) | **BLOCKED** | Operator-Hand-PR nötig (siehe §4) | Operator |
| G3 | OIDC-Drift-Probe Daily-Cron grün | **GREEN** | — | Kai (CI) |
| G4 | Hash-Derivate-Gate green-on-PR | **GREEN** | — | Kai (CI) |
| G5 | Cross-Substrate-Parity-Gate (Tag-57 PR #367) | **GREEN** | — | Kai (CI) |
| G6 | Strict-Mode-Readiness-Check Daily-Cron grün | **GREEN** | — | Kai (CI) |

Verdict: **2 von 6 Gates BLOCKED**, beide Operator-Hand-Pfad.
G3..G6 hold-steady-monitoring (siehe §5).

## §2 — Operator-Hand-Pre-KW-24 7-Tage-Calendar

Recipe zwischen 2026-05-19 (Tag-58, heute) und KW-24-Cutover-Day-T0
(2026-06-08 Mo). Sieben Operator-Action-Days, jeweils ≤ 2 h
Operator-Hand-Zeit pro Tag.

### Day-1 (2026-05-19, Di): Trust-Root-Snapshot-Pull (G2-Phase-a)

- Operator-Hand-Sandbox-Gap: `cosign initialize` lokal lauffähig
  prüfen (Operator-Workstation), keine Sandbox.
- Output: `fulcio.pub`, `rekor.pub`, `cosign-root.json` ins
  Trust-Snapshot-Verzeichnis ablegen.
- Branch-Plan: `operator/g2-trust-root-snapshot` als leerer
  Vorbereitungs-Branch durch Operator angelegt.

### Day-2 (2026-05-20, Mi): G2-PR-Submit (G2-Phase-b)

- Operator-Hand-Sandbox-Gap: G2-Operator-Hand-PR submit
  (siehe §4 für PR-Inhalt). Self-Merge nicht erlaubt; AR-Approval
  Pflicht.
- Erwartung: Trust-Root-Snapshot-PR offen + AR-Review-angefordert.

### Day-3 (2026-05-21, Do): G1-Welle-1-Quadlet-Wiring

- Operator-Hand-Sandbox-Gap: Welle-1-Quadlet-Service-File mit
  `cosign verify --strict` vor `ExecStart` patchen.
- Branch-Plan: `operator/g1-welle-1-quadlet-cosign-wiring`.

### Day-4 (2026-05-22, Fr): G1-Welle-2/3-Quadlet-Wiring

- Operator-Hand-Sandbox-Gap: Wellen 2 + 3 analog Welle-1.
- Branch-Plan: `operator/g1-welle-2-3-quadlet-cosign-wiring`.

### Day-5 (2026-05-26, Di nach Pfingst-Mo): G1-Welle-4-+-Pilot-Persona

- Operator-Hand-Sandbox-Gap: Welle-4-Quadlet + Pilot-Persona
  (`mira-pilot.container`) Cosign-Wiring.
- Branch-Plan: `operator/g1-welle-4-pilot-persona-cosign-wiring`.

### Day-6 (2026-05-27, Mi): G1-PR-Bundle-Submit

- Operator-Hand-Sandbox-Gap: G1-Bundle-PR (5 Branches in einem
  Stack) submit. AR-Approval Pflicht. Self-Merge nicht erlaubt.

### Day-7 (2026-05-28, Do): Trockenlauf-Verify

- Operator-Hand-Sandbox-Gap: Trockenlauf des Strict-Modus auf
  Operator-Workstation: `cosign verify --strict $IMAGE` über alle
  4 Wellen-Images + Pilot-Persona-Image.
- Output: Trockenlauf-Report nach `outbox/operator/`.

Puffer-Tage 2026-05-29 (Fr) bis 2026-06-05 (Fr) für AR-Review-
Loops + Mitigation. KW-24-Cutover-Day-T0 = 2026-06-08 (Mo).

## §3 — G1 Operator-Hand-PR-Recipe (Quadlet-Cosign-Wiring)

Detail-Recipe für den G1-PR. Operator-Hand-Sandbox-Gap markiert,
da Quadlet-Service-Files auf Host-Pfaden liegen und keinen
Sandbox-Zugriff haben.

### G1.1 Welle-1-Quadlet (orchestrator-core)

- Datei: `/etc/containers/systemd/welle-1-orchestrator.container`
- Patch-Block:
  ```ini
  [Service]
  ExecStartPre=/usr/local/bin/cosign verify --strict \
      --certificate-identity-regexp ".*@wakir-labs.*" \
      --certificate-oidc-issuer-regexp ".*github.com.*" \
      ghcr.io/wakir-labs/orchestrator-core:tag-58
  ```
- Erwartung: Service startet nur bei erfolgreicher
  Cosign-Strict-Verify.

### G1.2 Welle-2-Quadlet (wirelang-bus)

- Datei: `/etc/containers/systemd/welle-2-wirelang-bus.container`
- Patch-Block: analog G1.1 mit Image `wirelang-bus:tag-58`.

### G1.3 Welle-3-Quadlet (persona-engine)

- Datei: `/etc/containers/systemd/welle-3-persona-engine.container`
- Patch-Block: analog G1.1 mit Image `persona-engine:tag-58`.

### G1.4 Welle-4-Quadlet (wat-core)

- Datei: `/etc/containers/systemd/welle-4-wat-core.container`
- Patch-Block: analog G1.1 mit Image `wat-core:tag-58`.

### G1.5 Pilot-Persona-Quadlet (mira-pilot)

- Datei: `/etc/containers/systemd/mira-pilot.container`
- Patch-Block: analog G1.1 mit Image `mira-pilot:tag-58`.

### G1-PR-Stack

- Branch-Stack: 5 Branches, ein PR. Operator-Hand-Sandbox-Gap.
- AR-Approval Pflicht; kein Self-Merge.
- Required-Status-Checks: `cosign-verify-images`,
  `cosign-strict-mode-readiness-check`,
  `cross-substrate-parity-gate`.

## §4 — G2 Operator-Hand-PR-Recipe (Trust-Root-Snapshot)

Detail-Recipe für G2-PR. Operator-Hand-Sandbox-Gap markiert,
da Trust-Root-Material aus Sigstore-Public-Good-Instance via
`cosign initialize` Operator-Workstation-Pull voraussetzt.

### G2.1 Snapshot-Pull

- Operator-Hand: `cosign initialize` lokal.
- Output-Pfad: `infra/cosign/trust-root-snapshot-tag58/`.
- Inhalt:
  - `root.json`
  - `targets.json`
  - `snapshot.json`
  - `timestamp.json`
  - `fulcio.pub`
  - `rekor.pub`

### G2.2 SHA-256-Manifest

- Datei: `infra/cosign/trust-root-snapshot-tag58/MANIFEST.sha256`
- Inhalt: sha256-Hash je Trust-Root-Datei + Pull-Timestamp.
- Erwartung: Manifest reproduzierbar durch Operator und AR.

### G2.3 Pin-Verify-Skript

- Datei: `tooling/ci/verify_trust_root_snapshot_pin.py`
- Bereits in `wakir-runtime` (Tag-54, PR #344).
- G2-PR: nur Snapshot-Material + MANIFEST.sha256-Update.

### G2-PR-Inhalt

- Branch: `operator/g2-trust-root-snapshot`.
- Single-Branch-PR.
- AR-Approval Pflicht; kein Self-Merge.
- Required-Status-Checks: `trust-root-snapshot-pin-verify`.

## §5 — G3..G6 Hold-Steady-Sanity-Probes

Die vier grünen Gates G3..G6 brauchen Hold-Steady-Monitoring
zwischen Tag-58 und KW-24-Cutover-Day. Drift-Detection via
Daily-Cron-Probes.

### G3 OIDC-Drift-Probe Hold-Steady

- Daily-Cron: `cosign-keyless-oidc-drift-probe.yml`.
- Erwartung: 7/7 Tage grün bis KW-24-Cutover-Day.
- Failure-Action: §7 Decisions.

### G4 Hash-Derivate-Gate Hold-Steady

- PR-Gate: `hash-derivate-gate.yml`.
- Erwartung: jeder PR green-on-merge.

### G5 Cross-Substrate-Parity-Gate Hold-Steady

- PR-Gate: `cross-substrate-parity-gate.yml` (Tag-57 PR #367).
- Erwartung: jeder PR green-on-merge.

### G6 Strict-Mode-Readiness-Check Hold-Steady

- Daily-Cron: `cosign-strict-mode-readiness-check.yml`.
- Erwartung: 7/7 Tage grün bis KW-24-Cutover-Day.
- Failure-Action: §7 Decisions.

## §6 — KW-24-Cutover-Day-Gate-Check-Sequence

Cutover-Day = 2026-06-08 (Mo). Sequence T0..T9, Operator-Hand-
Sandbox-Gap pro Step.

| T | Action | Owner | Stop-on-Fail |
|---|---|---|---|
| T0 | G1-Gate-Status check (operator-hand-pr merged) | Operator | yes |
| T1 | G2-Gate-Status check (operator-hand-pr merged) | Operator | yes |
| T2 | G3-Cron-Run last-24h-green | Operator | yes |
| T3 | G4-PR-Gate last-24h-green | Operator | yes |
| T4 | G5-Parity-Gate last-24h-green | Operator | yes |
| T5 | G6-Readiness-Cron last-24h-green | Operator | yes |
| T6 | Strict-Flip-PR-Submit (config: `cosign.strict = true`) | Operator | yes |
| T7 | Strict-Flip-PR-Merge + Quadlet-Reload | Operator | yes |
| T8 | Welle-1..4 + Pilot-Persona Health-Probe ≤ 5 min | Operator | yes |
| T9 | Strict-Flip Done-Marker emittieren | Operator | n/a |

Gesamt-Time-Budget T0..T9: ≤ 2 h.

## §7 — Failure-Recovery-Decisions

Failure-Handling für die zwei kritischsten Welle-Failures.

### Decision-A: G1-Fail-Welle-1

- Symptom: `cosign verify --strict` schlägt für
  `orchestrator-core:tag-58` fehl beim Trockenlauf (§2 Day-7)
  oder beim Cutover-Day-T8.
- Decision:
  1. Strict-Flip-Rollback ausführen (Quadlet-Reload mit
     `cosign.strict = false`).
  2. Image-Re-Sign mit Trust-Root-Snapshot Tag-58.
  3. Wenn Re-Sign-Fail: AR-Eskalation + Cutover-Verschiebung
     KW-25.
- Owner: Operator + AR (Eskalations-Pfad).

### Decision-B: G2-Fail-Welle-2

- Symptom: Trust-Root-Snapshot-Pin-Verify schlägt für
  `wirelang-bus:tag-58` beim Cutover-Day-T8 fehl.
- Decision:
  1. Trust-Root-Snapshot-Re-Pull via `cosign initialize`.
  2. SHA-256-MANIFEST-Diff prüfen.
  3. Wenn Snapshot-Drift: AR-Eskalation + Cutover-Verschiebung
     KW-25 + ADR-Bedarf-Notiz an Mira (Trust-Root-Drift-Policy).
- Owner: Operator + AR (Eskalations-Pfad).

## §8 — Sandbox-Boundary

Dieses Dokument beschreibt **keine** Sandbox-Operationen. Alle
Operator-Hand-Items sind explizit als Operator-Hand-Sandbox-Gap
markiert.

Sandbox-Scope (Mira-claude-dev):
- Doc-Pflege (dieses Dokument).
- Helper-Skript `tooling/ci/verify_strict_flip_readiness_map.py`.
- Test-Suite `tests/observability/test_strict_flip_readiness_map_doc_tag58.py`.
- PR-Submit + Self-Merge auf `wakir-labs/wakir-runtime`.

Out-of-Sandbox-Scope (Operator-Hand):
- Quadlet-Service-File-Patches auf Host (§3).
- Trust-Root-Snapshot-Pull via `cosign initialize` (§4).
- Strict-Flip-PR-Submit/Merge auf KW-24-Cutover-Day (§6).
- Health-Probe-Run auf Operator-Workstation (§6 T8).

Mira-Sandbox darf weder Host-podman-Socket-Zugriff noch
Sigstore-Pull anstoßen. Verstoß = Hard-Stop, AR-Eskalation.

---

— Kai (Tag-58, 2026-05-19)
