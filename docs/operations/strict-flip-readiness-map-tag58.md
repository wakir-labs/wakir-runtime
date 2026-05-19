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

## §9 — OPEN-J3 Containerfile-Label Carry-Forward (Tag-64-Append)

Tag-64-Append (2026-05-19) zum Tag-63-Selin-Audit-Bericht
`reports/audit/persona-engine-0-5-3-production-readiness-2026-05-19.md`
§D6 OPEN-J3. Diese §9 dokumentiert den explizit-intentionalen
Carry-Forward der OCI-`image.version`-Label-Refresh-Action von
`0.5.2-final-pre-cutover` auf `0.5.3` als Operator-Hand-/Kai-Hand-
Action der KW-24-Cutover-Image-Build-Pipeline, ausserhalb des
Tag-62/Tag-63-Engine-Release-Scope.

### §9.1 Quelle und Substrat-Beschreibung

- Datei: `infra/persona-engine/Containerfile.real`.
- Aktueller Wert (Tag-52-emittiert, byte-stable durch Tag-58, -62, -63):
  `LABEL org.opencontainers.image.version="0.5.2-final-pre-cutover"`
  (Containerfile.real Zeile 150).
- Ziel-Wert (KW-24-Cutover-Image-Build): `0.5.3`.
- 7 LABELs total (ADR-0061-LABEL-Konvention erfüllt):
  `title`, `description`, `version`, `licenses`, `source`, `url`,
  `documentation`.
- Audit-Verdict §D6: `MATCH-WITH-1-INTENTIONAL-CARRY-FORWARD`.

### §9.2 Begründung für Carry-Forward (kein Tag-64-Cleanup)

Drei substantielle Gründe halten die Label-Refresh auf der KW-24-
Cutover-Image-Build-Welle, **nicht** auf Tag-64:

1. **Scope-Split-Disziplin (Tag-62-Release-Notes §1).**
   Tag-62-Release-Notes §1 "Out of scope" listet explizit:
   "Containerfile-tag or compose-file change beyond what Kai
   coordinates separately (Zone-J)". Eine Tag-64-Label-Refresh-
   Aktion auf `0.5.3` würde Tag-62's dokumentierten Scope brechen
   und die Selin-Tag-63-Audit-Verdict-Substanz (engine-wiring vs.
   image-rebuild getrennt) rückwirkend invalidieren.

2. **Domain-Boundary (Selin endet bei Engine-Wiring, Kai beginnt
   bei Image-Rebuild).**
   Tag-63-Audit §D6 stellt fest: "Selin's domain ends at the
   engine wiring; Kai's domain begins at the Containerfile
   rebuild." Tag-64 ist nicht der Cutover-Image-Build-Tag.
   Cutover-Image-Build ist die KW-24-Operator-Hand-Action mit
   eigener Sequence (siehe §6 T6/T7 oben). Eine Tag-64-Label-
   Pre-Refresh würde diese Sequence-Disziplin brechen.

3. **Byte-Stability-Anker für Doppelbetrieb-Regression.**
   Der Wert `0.5.2-final-pre-cutover` ist die byte-stabile Anker-
   Identität, gegen die die Doppelbetrieb-Regression-Comparison-
   Baseline (Tag-48..Tag-52) läuft. Vor dem Cutover-T0 darf
   dieses Label nicht verändert werden, sonst entsteht ein
   Drift-Vektor zwischen Pre-Cutover-Image-Manifest und Engine-
   Substrat. Refresh erst **nach** Cutover-T0, im Image-Rebuild-
   Schritt (siehe §6 T6-Folge).

### §9.3 Refresh-Trigger-Sequence (KW-24-Cutover-Image-Build)

Die OCI-`image.version`-Label-Refresh ist explizite Kai-Hand-Action
im Folge-Schritt nach §6 T7 (Strict-Flip-PR-Merge + Quadlet-Reload).
Diese Sub-Sequence wird **nicht** vom Operator-Hand-Strict-Flip-PR
ausgeführt, sondern als separater Kai-Hand-Image-Rebuild:

| Sub-T | Action | Owner | Stop-on-Fail |
|---|---|---|---|
| J3-A | Diff `image.version` LABEL Containerfile.real vs. Engine-Version 0.5.3 | Kai | yes |
| J3-B | LABEL-Patch-PR: `0.5.2-final-pre-cutover` → `0.5.3` (Containerfile.real Zeile 150) | Kai | yes |
| J3-C | LABEL-description-Refresh: Tag-62-Konsolidierungs-Prosa → Tag-`KW-24`-Cutover-Prosa | Kai | no |
| J3-D | Image-Rebuild + Re-Sign (`cosign sign --keyless`) | Kai + Operator | yes |
| J3-E | Quadlet-Image-Tag-Bump auf neuen `0.5.3`-Image-Digest | Operator | yes |
| J3-F | Cross-Substrate-Parity-Gate green-on-PR | Kai (CI) | yes |
| J3-G | Containerfile-LABEL-Verify (`podman inspect`) gegen Refresh-Manifest | Operator | yes |

Total Time-Budget J3-A..J3-G: ≤ 90 min Kai-Hand + ≤ 30 min Operator-
Hand, an Cutover-T0+1 oder Cutover-T0+2 (KW-24 Di/Mi). **Nicht** an
Cutover-T0 selbst — der T0..T9-Pfad bleibt LABEL-byte-stable.

### §9.4 Carry-Forward-Status-Tabelle

| Property | Wert |
|---|---|
| Item-ID | OPEN-J3 |
| Audit-Quelle | Tag-63 Selin-Audit §D6 (`reports/audit/persona-engine-0-5-3-production-readiness-2026-05-19.md`) |
| Substrat-Datei | `infra/persona-engine/Containerfile.real` |
| Substrat-Zeile | 150 |
| Current-Label | `org.opencontainers.image.version="0.5.2-final-pre-cutover"` |
| Target-Label | `org.opencontainers.image.version="0.5.3"` |
| Owner | Kai (Zone-J) |
| Severity | `blocker-for-cutover-image-build` |
| Status | `intentional-carry-forward` |
| Closes Before | KW-24-Cutover-Image-Build (post Cutover-T0, Sub-Sequence §9.3) |
| Tag-64-Decision | Carry-Forward (kein Pre-Cutover-Refresh) |
| Decision-Begründung | §9.2 (3 Gründe: Scope-Split, Domain-Boundary, Byte-Stability) |

### §9.5 Rationale-Anker für AR-Sichtung

Drei AR-relevante Lese-Anker für die §9-Substanz:

- Audit-Quelle vs. Map-Eintrag konsistent: §9.1 zitiert Containerfile-
  Zeile 150 wörtlich, §D6 zitiert dieselbe Stelle.
- Scope-Disziplin: §9.2 Punkt 1 ist die direkte Out-of-Scope-Klausel
  aus Tag-62-Release-Notes §1, byte-genau zitiert.
- Refresh-Action im Cutover-Plan verankert: §9.3 J3-A..J3-G hängt
  hinter §6 T7, nicht parallel zu T0..T9 — die Strict-Flip-Sequenz
  bleibt LABEL-byte-stabil.

## §10 — Tag-67-Carry-Forward-Update (Tag-68-Append)

Tag-68-Append (2026-05-19, Continuous-Mode-Marathon) zur Strict-Flip-
Readiness-Map. Tag-58-Original ist neun Tage alt; zwischen Tag-58 und
Tag-67 wurden vier substantielle Anker an die Strict-Flip-Sequenz
angehängt, die hier konsolidiert dokumentiert werden, damit die Map
ohne Sprung in andere Dokumente lesbar bleibt.

Carry-Forward-Quellen Tag-58..Tag-67:

| Tag | PR | Substanz | Map-Effekt |
|---|---|---|---|
| Tag-58 | #369 | Map-Original (G1..G6 + 7-Tage-Calendar) | Basis |
| Tag-64 | #408 | OPEN-J3 Containerfile-Label Carry-Forward | §9 (Tag-64-Append) |
| Tag-66 | #422 | Operator-Hand Cutover-Eve Final-Recipe | §10.1 |
| Tag-67 | #425 | Watch-Day Pre-Cutover Live-Smoke | §10.2 |
| Tag-67 | #426 | Eve-Recipe Dry-Run Probe | §10.1 |
| Tag-67 | #427 | Wirelang-Spec v0.4.4 Activation Pre-Mortem | §10.3 |
| Tag-67 | #429 | Welle-N State-File Conventions | §10.4 |

### §10.1 — Cutover-Eve-Recipe-Status (Tag-66 PR #422 + Tag-67 PR #426)

Operator-Hand-Cutover-Eve-Final-Recipe ist seit Tag-66 als Konsolidat
verfügbar (`docs/operations/operator-hand-cutover-eve-final-recipe.md`,
864 Zeilen). Tag-67 hat den hermetischen Dry-Run-Probe-Lauf nachgereicht
(`tooling/ci/dry_run_operator_eve_recipe.py` + Workflow
`.github/workflows/operator-eve-recipe-dry-run-probe.yml`, 14 Tests).

| Property | Wert |
|---|---|
| Recipe-Doc | `docs/operations/operator-hand-cutover-eve-final-recipe.md` |
| Dry-Run-Probe | `tooling/ci/dry_run_operator_eve_recipe.py` |
| Dry-Run-Verdict | `CLEAN` (Tag-67 PR #426) |
| Eve-Checks | E1..E7 (Dashboard, Post-Activate, Trust-Root, ...) |
| Verdict-Marker | `EVE-E*-READY` / `EVE-E*-HOLD` / `EVE-E*-DEFECT` |
| Owner | Kai (Recipe), Operator (Execution) |
| Status | `READY-FOR-CUTOVER-EVE` (Tag-68 frozen) |
| Sandbox-Scope | Recipe + Dry-Run **in** Sandbox; Live-Execution Operator-Hand |

Anbindung an §2 7-Tage-Calendar: Day-6/Day-7 (G1-Bundle + Trockenlauf)
sind das Pre-Eve-Window. Cutover-Eve = Tag-vor-T0 = 2026-06-07 (So) →
Eve-Recipe-Run startet 17:00 CEST mit E1-Dashboard-Scan.

### §10.2 — Live-Smoke-DEFECT-Status (Tag-67 PR #425, Noa-SRE)

Tag-67 hat den Watch-Day-Pre-Cutover-Live-Smoke-Probe gelandet
(`tooling/ci/aggregate_watch_day_pre_cutover_live_smoke.py` +
Workflow `.github/workflows/watch-day-pre-cutover-live-smoke.yml`,
16 Tests). Sechs-Stage-Layout (Practice-Run, Cron-Pre-Fire, Replay
Multi-Sample, Operator-Trigger-Integration, Audit-Trail-Verify,
Substrate-Coupling-Map-Cross-Check), Tri-State-Verdict
`LIVE-SMOKE-INTACT` / `DRIFT` / `DEFECT`.

Erster Lauf hat **4 Drift-Stages** befundet (Stage-2 Cron-Pre-Fire-
Timing-Drift, Stage-3 Replay-Multi-Sample Off-by-one, Stage-4
Operator-Trigger Alert-Routing-Race, Stage-5 Audit-Trail-Marker-
Skew). Verdict: **DRIFT** (>=3 Yellow → grenzwertig zu DEFECT).

| Property | Wert |
|---|---|
| Probe-Workflow | `.github/workflows/watch-day-pre-cutover-live-smoke.yml` |
| Probe-Aggregator | `tooling/ci/aggregate_watch_day_pre_cutover_live_smoke.py` |
| Erst-Lauf-Verdict | `DRIFT` (4 Drift-Stages) |
| Affected Stages | Stage-2, Stage-3, Stage-4, Stage-5 |
| Tag-68-Folge-Action | Sweep-Spawn pro Stage (Noa+Selin+Tomás+Amara) |
| Required-Eve-Verdict | `LIVE-SMOKE-INTACT` vor Cutover-T0 |
| Status | `DEFECT-CARRY-FORWARD` (4 Drifts → Tag-68 Sweep, dann Re-Probe) |

**Cutover-Gate-Effekt:** §6 T0..T9 darf nicht starten, solange der
Watch-Day-Live-Smoke-Probe `DRIFT` oder `DEFECT` meldet. Tag-68
Sweep-Plan = Voraussetzung für Cutover-Eve-Recipe E2 (Post-Activate-
Clean-Check), siehe §10.1.

### §10.3 — Activation-Pre-Mortem-Cross-Anchor (Tag-67 PR #427, Reza)

Wirelang-Spec v0.4.4 Activation Pre-Mortem ist seit Tag-67 verfügbar
(`docs/spec/wirelang-spec-v0-4-4-activation-pre-mortem.md`, 327 Zeilen,
17 Tests). Reza-Owner; Cross-Anchor zur Strict-Flip-Map via
Cross-Substrate-Parity-Gate (§1 G5).

| Property | Wert |
|---|---|
| Spec-Doc | `docs/spec/wirelang-spec-v0-4-4-activation-pre-mortem.md` |
| Owner | Reza (Zone B) |
| Map-Cross-Anchor | §1 G5 (Cross-Substrate-Parity-Gate) |
| Verifier | `tooling/audit/verify_activation_pre_mortem_doc.py` |
| Status | `LANDED-TAG-67` (Pre-Mortem-Konsens dokumentiert) |
| Cutover-Effekt | Failure-Mode-Library für §7 Decision-A/B Erweiterung |

**Konsequenz für §7:** Decision-A (G1-Fail) + Decision-B (G2-Fail)
bleiben unverändert; das Pre-Mortem liefert keine neuen
Failure-Pfade, die Strict-Flip-spezifisch sind. Wirelang-Layer-0-2-
Failures sind Reza-Domain (Zone B) und werden über das eigene
Reserve-Item-Promotion-Sequencing-Doc (Tag-65 PR #417) gehandhabt.

### §10.4 — Welle-N State-File Conventions Cross-Anchor (Tag-67 PR #429, Amara)

Tag-67 hat Welle-1..7 State-File-Conventions als Pre-Cutover-T0-Pin
gelandet (`state/welle-{1..7}.json` + Doc
`docs/operations/welle-n-state-file-conventions.md`, 18 Tests).
Anker für die §6 T8 Health-Probe-Sequence (Welle-1..4 + Pilot-
Persona).

| Property | Wert |
|---|---|
| State-Files | `state/welle-1.json` .. `state/welle-7.json` |
| Doc | `docs/operations/welle-n-state-file-conventions.md` |
| Verifier | `tooling/ci/verify_welle_state_file_conventions.py` |
| Pin-Status | `BYTE-STABLE-PRE-CUTOVER-T0` |
| Map-Anker | §6 T8 (Welle-1..4 + Pilot-Persona Health-Probe ≤ 5 min) |
| Status | `LANDED-TAG-67` |

### §10.5 — OPEN-J3 Status-Refresh (Tag-64 PR #408, Kai-Hand-Refresh-Sequence)

OPEN-J3 (Containerfile-Label-Carry-Forward von `0.5.2-final-pre-cutover`
auf `0.5.3`, siehe §9) bleibt im `intentional-carry-forward`-Status.
Tag-68-Refresh:

| Property | Wert |
|---|---|
| Item-ID | OPEN-J3 |
| Status-Tag-58..67 | unverändert `intentional-carry-forward` |
| Substrat-Datei | `infra/persona-engine/Containerfile.real` Zeile 150 |
| Refresh-Sub-Sequence | J3-A..J3-G (siehe §9.3) |
| Refresh-Trigger | post Cutover-T0, Sub-Sequence §9.3 |
| Time-Budget | ≤ 90 min Kai-Hand + ≤ 30 min Operator-Hand |
| Tag-68-Decision | weiterhin Carry-Forward, keine Pre-Cutover-Action |
| Cross-Anchor | §9 (Tag-64-Append), §6 T7-Folge (Cutover-Sub-Sequence) |

**Begründung Tag-68 unverändert:** Die drei Carry-Forward-Gründe aus
§9.2 (Scope-Split, Domain-Boundary, Byte-Stability) gelten 1:1 weiter.
Keine Substanz aus Tag-65..Tag-67 invalidiert die Carry-Forward-
Begründung.

### §10.6 — 7-Pool Required-Status-Checks Aktivierungs-Status

Tag-59 PR #375 + Tag-61 PR #389 haben das 7-Pool-Required-Status-
Check-Target dokumentiert. Tag-62 PR (Bulk-Activation-Pre-Walk-Recipe)
hat den Aktivierungs-Pfad als Operator-Hand-Recipe festgehalten.
Stand Tag-68: alle 7 Pool-Checks sind **on main**, Aktivierung in
Branch-Protection ist **Operator-Hand-pending** für Cutover-T0.

| Pool-Check | Quelle | On-Main | BP-Aktivierung |
|---|---|---|---|
| `cosign-verify-images` | Tag-49 | yes | pending-T0 |
| `hash-derivate-gate` | Tag-52 | yes | pending-T0 |
| `cross-substrate-parity-gate` | Tag-57 PR #367 | yes | pending-T0 |
| `cosign-keyless-oidc-drift-probe` | Tag-54 | yes | pending-T0 |
| `cosign-strict-mode-readiness-check` | Tag-55 | yes | pending-T0 |
| `trust-root-snapshot-pin-verify` | Tag-54 PR #344 | yes | pending-T0 |
| `pre-cutover-final-sanity-gate` | Tag-55 | yes | pending-T0 |

Aktivierung erfolgt im Cutover-T0.3 Bulk-Activation-Walk
(`tooling/ops/_bulk_activate_required_checks.py --enforce`), siehe
Tag-66 Eve-Final-Recipe §3.4. Sandbox-Boundary unverändert:
`--enforce`-Modus ist **Operator-Hand-Sandbox-Gap**.

**Anmerkung 8-Pool-Erweiterung:** Tag-64 OPEN-J3 referenziert einen
optionalen 8. Check (`containerfile-label-verify`) für die KW-24-
Cutover-Image-Build-Pipeline (§9.3 J3-G). Dieser ist **nicht** Teil
des 7-Pool-Pre-Cutover-T0-Targets und wird post-Cutover-T0+1/+2
als Kai-Hand-Action gewired.

### §10.7 — Tag-68-Carry-Forward-Verdict

Konsolidiertes Cutover-Readiness-Verdict per Tag-68:

| Axis | Status | Blocker | Owner |
|---|---|---|---|
| G1 (Quadlet-Wiring) | **BLOCKED** | Operator-Hand-PR Day-3..Day-6 | Operator |
| G2 (Trust-Root-Snapshot) | **BLOCKED** | Operator-Hand-PR Day-1..Day-2 | Operator |
| G3..G6 (Hold-Steady) | **GREEN** | hold-steady-monitoring | Kai (CI) |
| Cutover-Eve-Recipe | **READY** | Dry-Run-Probe CLEAN (Tag-67 PR #426) | Kai (Recipe), Operator (Run) |
| Live-Smoke-Probe | **DRIFT (4 stages)** | Tag-68 Sweep nötig | Noa+Selin+Tomás+Amara |
| Activation-Pre-Mortem | **LANDED** | — | Reza |
| Welle-N State-Files | **PIN-STABLE** | — | Amara |
| OPEN-J3 | **CARRY-FORWARD** | post-Cutover-T0 Sub-Sequence | Kai |
| 7-Pool Required-Checks | **ON-MAIN** | BP-Aktivierung Cutover-T0.3 | Operator |

**Gesamt-Verdict Tag-68:** Cutover-Pfad-Readiness ist **2 von 2
Operator-Hand-Gates BLOCKED** + **1 Live-Smoke-DRIFT zu sweepen**.
Erwartete Tag-68..Tag-71-Bewegung: Live-Smoke-Sweep schließt 4 Drifts;
G1+G2 Operator-Hand-PRs durch Operator (Day-1..Day-6 7-Tage-Calendar);
G3..G6 hold-steady. Kein Phase-3-Cutover-Slip erwartet, KW-24 (2026-06-08)
bleibt T0-Datum.

---

— Kai (Tag-58 Original, Tag-64-Append + Tag-68-Append + Tag-72-Signaturzeile-Fix 2026-05-19)

<!--
Tag-72 Signaturzeile-Drift-Fix (Noa-Tag-71-Side-Finding):
Footer ist append-only. Tag-58 Original ist der Anker. Tag-64-Append
+ Tag-68-Append + Tag-72-Signaturzeile-Fix sind Append-Wellen, die
die Authorship-Chain dokumentieren. Append-Format-Regel:
  "Tag-58 Original, Tag-<N>-Append [+ Tag-<M>-Append ...] YYYY-MM-DD"
Test_17 in test_open_j3_containerfile_label_tag64.py prueft jetzt
substring-tolerant (Tag-58 Original / Tag-64-Append / Datum), so
dass zusaetzliche Append-Wellen ohne Test-Drift moeglich sind.
-->

