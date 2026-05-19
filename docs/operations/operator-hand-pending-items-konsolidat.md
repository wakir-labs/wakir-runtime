---
title: "Operator-Hand Pending-Items Konsolidat (Tag-77)"
status: "active"
owner: "kai"
audience: "operator,ar,engineering,internal-audit"
created: "2026-05-19"
tag: "tag-77"
predecessors:
  - "docs/operations/operator-hand-production-bringup-recipe.md"
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-5-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-6-eve-recipe-patch.md"
  - "docs/operations/operator-hand-welle-7-eve-recipe-patch.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
  - "docs/operations/cosign-g1-g2-operator-setup.md"
  - "docs/operations/open-k3-v907-baseline-metadata-carry-forward.md"
  - "docs/operations/wakir-protocol-cross-review-zone-3-handoff-plan.md"
  - "docs/operations/branch-protection-required-status-checks.md"
  - "docs/operations/cross-substrate-parity-runbook.md"
related_adrs:
  - "ADR-0065"
  - "ADR-0066"
  - "ADR-0070"
related_docs:
  - "docs/operations/operator-hand-production-bringup-recipe.md"
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
  - "docs/operations/g1-g2-last-mile-operator-checklist.md"
  - "docs/operations/cosign-g1-g2-operator-setup.md"
  - "docs/operations/cross-substrate-parity-runbook.md"
  - "docs/operations/wakir-protocol-cross-review-zone-3-handoff-plan.md"
related_prs:
  - "#389"
  - "#395"
  - "#396"
  - "#411"
  - "#477"
  - "#484"
related_memory:
  - "Pre-Cutover-Eve (Datum 2026-06-26 Fr) ist der letzte Stichtag vor dem Marathon-Start an dem die Operator-Hand-Items aus Tag-50..76 zusammengefuehrt sein muessen. Die Items entstanden ueber 26 Operator-Hand-Spawn-Tage in vier Cluster: (a) Required-Status-Checks-Aktivierung (8 Checks aus PR #389, #396, #411), (b) Cosign-Quadlet-Wiring + Trust-Root-Snapshot (G1+G2-Operator-PRs), (c) Cross-Substrate-Parity-Required-Check, (d) Carry-Forward-Items aus OPEN-J2/J3/K3. Diese Doc konsolidiert die 10 Item-Cluster pro Item: Owner, Timing, Prerequisites, Step-by-Step, Verification, Rollback. Sie ersetzt KEINES der referenzierten Predecessor-Doks -- sie ist Eve-Aggregator-Master-Reference."
---

# Operator-Hand Pending-Items Konsolidat

**Tag-77 Marathon-Polish-Phase Master-Doc**. Diese Doc konsolidiert
alle Operator-Hand-Sandbox-Gap-Items, die ueber den Spawn-Korridor
**Tag-50..Tag-76** entstanden sind und die noch vor dem Marathon-
Cutover (Welle-1-Start 2026-06-27 Sa, Pre-Cutover-Eve 2026-06-26 Fr)
durch **Operator-Hand-Live-VM** ausgefuehrt sein muessen.

Die 26 Spawn-Tage seit Tag-50 haben acht Operator-Hand-Item-Cluster
produziert. Jeder Cluster wurde zum Zeitpunkt seiner Entstehung in
einer dedizierten Doc gefasst (Tag-59 Branch-Protection-Wiring,
Tag-60 G1+G2-Recipe-Smoke, Tag-62 Bulk-Aktivierung-Recipe, Tag-64
OPEN-J3-Containerfile-Label, Tag-67 Eve-Recipe-Dry-Run, Tag-70
Recipe-Cross-Validation, Tag-72 Tag-58-Signaturzeile-Fix, Tag-74
Welle-6-Recipe-Patch, Tag-76 Production-Bringup-Recipe). Diese
**Konsolidat-Doc** liefert die **single-pane-of-glass-Master-
Checkliste**, die der Operator am Pre-Cutover-Eve-Stichtag
(2026-06-26 Fr) durchgeht, um sicherzustellen, dass keiner der
Operator-Hand-Items uebersehen wurde.

Anders als die Predecessor-Docs ist diese Doc **kein Recipe** und
**keine Run-Order**. Sie ist ein **Aggregator-Index**: pro Item
liefert sie sechs Felder (Owner, Timing, Prerequisites, Step-by-Step,
Verification, Rollback) und referenziert die kanonische Source-Doc
fuer das vollstaendige Recipe. Der Operator nutzt diese Doc als
**Pre-Cutover-Eve-Walkthrough-Pruefkarte**, nicht als Step-Recipe-
Replacement.

## Scope und Abgrenzung

Diese Doc ist **kein Ersatz** fuer:

* Das Tag-66 Eve-Recipe (`operator-hand-cutover-eve-final-recipe.md`)
  -- das deckt die Welle-Cutover-Day-Sequenz T0..T0+6 ab.
* Das Tag-76 Production-Bringup-Recipe (`operator-hand-production-
  bringup-recipe.md`) -- das deckt die Post-Sign-off-Day-1..Day-7-
  Operator-Aktionen ab.
* Die Tag-59/Tag-61/Tag-64 Branch-Protection-Required-Checks-Docs --
  die liefern die exakte Check-Namen-Liste pro Welle.
* Die G1+G2-Last-Mile-Operator-Checklist (`g1-g2-last-mile-operator-
  checklist.md`) -- die liefert das Cosign-Quadlet-Wiring-Recipe.
* Das Wakir-Protocol-Cross-Review-Zone-3-Handoff-Plan -- das liefert
  den Zone-3-Hand-off-PR-Inhalt fuer Reza-Tag-62 PR #395.

Diese Doc ist der **Master-Aggregator**: er listet alle 10 Item-
Cluster mit den sechs Standard-Feldern und referenziert die Source-
Doc fuer das vollstaendige Recipe. Sie ist **explizit Pre-Cutover-
Eve-positioned** (Stichtag 2026-06-26 Fr) und **explizit
operator-walkthrough-orientiert** (nicht engineering-design-
orientiert).

## Zeit-Domain

| Phase | Zeit-Window | Operator-Touchpoint |
|---|---|---|
| Pre-Cutover-Eve-Stichtag | 2026-06-26 Fr | Diese Doc als Pre-Walkthrough-Pruefkarte |
| Welle-1-Cutover-Tag | 2026-06-27 Sa | Tag-66 Eve-Recipe T0..T0+6 |
| Marathon-Lauf | 2026-06-27 .. 2026-07-03 | Welle-3-7 Tag-71/73/74/75 Patches |
| Welle-7-Sign-off | 2026-07-03 Fr | Tag-75 Welle-7-Patch P5-Final-Sealing |
| Production-Bringup-Window | 2026-07-04..2026-07-10 | Tag-76 Production-Bringup-Recipe |

Die **Aktiv-Phase dieser Doc** ist Pre-Cutover-Eve-Stichtag
2026-06-26 Fr. Ab Welle-1-Cutover (2026-06-27 Sa) treten die
Welle-spezifischen Recipe-Docs in Kraft; diese Doc dient ab Cutover-
Start als **Audit-Trail-Reference** (welcher Pre-Cutover-Item wann
abgehakt wurde).

## §1 -- Required-Status-Checks-Pool-Aktivierung (8 Checks)

### Item I1 -- 8-Check-Bulk-Aktivierung

**Owner**: Operator-Hand (Live-VM, GitHub-API-PUT)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, vor Welle-1-Cutover
**Prerequisites**:

* Tag-59 Doc `branch-protection-required-status-checks.md` vorhanden
* Tag-61 Addendum `branch-protection-required-checks-tag61-addendum.md`
  vorhanden
* Tag-64 Companion `branch-protection-required-checks-tag64-companion.md`
  vorhanden
* PR #389 Pre-Walk-Recipe (Kai), PR #396 Bulk-Aktivierung (Kai),
  PR #411 Subsumption-Check (Amara) sind alle gemerged
* GitHub-API-Token mit `repo`-Scope auf den drei Wakir-Repos verfuegbar

**Step-by-Step**:

1. Operator oeffnet `branch-protection-required-status-checks.md`
   §3-Table und liest die 8 Check-Display-Names verbatim ab.
2. Operator fuehrt `tooling/ci/bulk_activate_required_checks.py` mit
   Flag `--repo wakir-runtime --repo wakir-protocol --repo wakir-site`
   gegen die Live-API aus.
3. Helper PUT-t pro Repo das Branch-Protection-Settings-Object mit
   `required_status_checks.contexts` = 8 Check-Names.
4. Helper waited auf 200-Response pro Repo und loggt OK / FAIL pro Repo.

**Verification**:

* Manuelle Spot-Check: `gh api /repos/wakir-labs/wakir-runtime/branches/
  main/protection | jq .required_status_checks.contexts | wc -l` muss
  `8` zurueckgeben.
* Tag-70 Recipe-Cross-Validation-Test-Suite `test_eve_recipes_cross_
  validation_tag70.py` muss gruen sein (laeuft hermetic, prueft Doc-
  Konsistenz, nicht Live-State).

**Rollback**:

* `tooling/ci/bulk_activate_required_checks.py --revert` PUT-t den
  vorherigen Settings-Snapshot zurueck (vom Helper vor PUT erstellt
  in `state/branch-protection-pre-activation-snapshot.json`).

## §2 -- G1+G2 Cosign-Quadlet-Wiring + Trust-Root-Snapshot

### Item I2 -- G1 Cosign-Quadlet-Wiring

**Owner**: Operator-Hand (Live-VM, Cosign-CLI + Quadlet-Edit)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, vor Welle-1-Cutover
**Prerequisites**:

* Tag-60 Doc `g1-g2-last-mile-operator-checklist.md` vorhanden
* Tag-60 Doc `cosign-g1-g2-operator-setup.md` vorhanden
* Cosign-CLI v2.4+ installiert (Live-VM)
* Cosign-Public-Key-Pair (G1) im operator-Vault-Slot abgelegt
* Quadlet-Service-Files vorhanden in `/etc/containers/systemd/`

**Step-by-Step**:

1. Operator liest `g1-g2-last-mile-operator-checklist.md` §G1-Step-1
   bis §G1-Step-6 verbatim.
2. Operator triggert `cosign sign --key=<g1-vault-slot> <image-ref>`
   fuer alle vier Persona-Engine-Images (orchestrator, agent-rust,
   agent-python, bridge-audit-writer).
3. Operator editiert `/etc/containers/systemd/<service>.container`
   um `PolicyContext=enforce-cosign-g1` einzufuegen.
4. Operator triggert `systemctl daemon-reload && systemctl restart
   <service>` und prueft Service-Status `active (running)`.

**Verification**:

* `cosign verify --key=<g1-pubkey> <image-ref>` returns OK fuer alle
  vier Persona-Engine-Images.
* `systemctl status <service>` zeigt `active (running)` und Image-
  Pull-Log enthaelt `cosign-policy: enforce-cosign-g1 passed`.

**Rollback**:

* Editiere `/etc/containers/systemd/<service>.container` um
  `PolicyContext=enforce-cosign-g1` zu entfernen.
* `systemctl daemon-reload && systemctl restart <service>` setzt
  den Service auf Pre-G1-State zurueck.

### Item I3 -- G2 Trust-Root-Snapshot

**Owner**: Operator-Hand (Live-VM, Trust-Root-Snapshot-Helper)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, nach Item I2
**Prerequisites**:

* Item I2 abgeschlossen und verifiziert
* `tooling/ci/snapshot_trust_root.py` vorhanden
* `state/trust-root-snapshots/` Verzeichnis vorhanden

**Step-by-Step**:

1. Operator fuehrt `tooling/ci/snapshot_trust_root.py --output
   state/trust-root-snapshots/pre-cutover-eve-2026-06-26.json` aus.
2. Helper exportiert alle aktiven Cosign-Public-Keys, SPIRE-Trust-
   Bundles, und ESO-Secret-References in die Snapshot-Datei.
3. Operator commit-et die Snapshot-Datei: `git add state/trust-root-
   snapshots/pre-cutover-eve-2026-06-26.json && git commit -m
   "ops(trust-root): pre-cutover-eve snapshot 2026-06-26"`.
4. Operator OTS-stamp-t den Commit via Tomas-OTS-Pipeline (siehe §10).

**Verification**:

* Snapshot-Datei existiert und ist nicht-leer (`test -s state/trust-
  root-snapshots/pre-cutover-eve-2026-06-26.json`).
* Snapshot-Datei enthaelt valide JSON: `jq . state/trust-root-
  snapshots/pre-cutover-eve-2026-06-26.json` returns OK.
* OTS-Stamp-Commit ist in der `chore(ots): timestamp <hash>`-Linie
  sichtbar.

**Rollback**:

* Loesche die Snapshot-Datei und revert-e den Commit:
  `git revert <snapshot-commit-sha>`.
* Re-trigger Item I3 mit aktualisiertem Datum.

## §3 -- Cross-Substrate-Parity-Required-Check Aktivierung

### Item I4 -- Cross-Substrate-Parity-Check on-Branch-Protection

**Owner**: Operator-Hand (Live-VM, GitHub-API-PUT)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, nach Item I1
**Prerequisites**:

* Tag-57 Doc `cross-substrate-parity-runbook.md` vorhanden
* Tag-62 Bulk-Aktivierung-Recipe-Doc gemerged (PR #396)
* Workflow `.github/workflows/cross-substrate-parity.yml` aktiv und
  laeuft pro PR

**Step-by-Step**:

1. Operator liest `cross-substrate-parity-runbook.md` §4 Required-
   Check-Aktivierung-Step.
2. Operator triggert `tooling/ci/bulk_activate_required_checks.py
   --add-check "Cross-Substrate-Parity" --repo wakir-runtime --repo
   wakir-protocol` (Site-Repo NICHT, da kein Engine-Substrate).
3. Helper PUT-t den zusaetzlichen Check-Display-Name in die
   `required_status_checks.contexts`-Liste.

**Verification**:

* `gh api /repos/wakir-labs/wakir-runtime/branches/main/protection |
  jq -r '.required_status_checks.contexts[]' | grep -c "Cross-
  Substrate-Parity"` muss `1` zurueckgeben.
* Selbes fuer `wakir-protocol`.

**Rollback**:

* `tooling/ci/bulk_activate_required_checks.py --remove-check
  "Cross-Substrate-Parity" --repo wakir-runtime --repo wakir-protocol`
  entfernt den Check wieder.

## §4 -- OPEN-J2 Live-VM Rotation 0.5.1 -> 0.5.3

### Item I5 -- OPEN-J2 Persona-Engine-Image-Rotation

**Owner**: Operator-Hand (Live-VM, Image-Pull + Quadlet-Restart)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, nach Item I2/I3
**Prerequisites**:

* Persona-Engine-Image `wakir-persona-engine:0.5.3` gebuilt und in
  Registry gepusht (siehe `docs/operations/persona-engine-image-
  build.md`)
* Cosign-Signature auf `0.5.3`-Tag vorhanden (`cosign verify`-OK)
* Item I2 (G1 Cosign-Quadlet-Wiring) abgeschlossen

**Step-by-Step**:

1. Operator pruefft Source-Version: `podman inspect wakir-persona-
   engine:current | jq .Config.Labels.version` muss `0.5.1` zurueck-
   geben.
2. Operator pull-t Target-Image: `podman pull registry.wakir.dev/
   wakir-persona-engine:0.5.3`.
3. Operator verifiziert Cosign: `cosign verify --key=<g1-pubkey>
   registry.wakir.dev/wakir-persona-engine:0.5.3` returns OK.
4. Operator updated Quadlet-Service-File `/etc/containers/systemd/
   wakir-persona-engine.container` Image-Line auf `:0.5.3`.
5. Operator triggert `systemctl daemon-reload && systemctl restart
   wakir-persona-engine`.

**Verification**:

* `systemctl status wakir-persona-engine` zeigt `active (running)`
  und Image-ID matched `0.5.3`-Tag.
* Smoke-Test `tooling/ci/persona-engine-smoke-test.py` returns OK.
* `journalctl -u wakir-persona-engine --since "5 minutes ago" | grep
  -c "ERROR"` muss `0` zurueckgeben.

**Rollback**:

* Editiere Quadlet-Service-File Image-Line zurueck auf `:0.5.1`.
* `systemctl daemon-reload && systemctl restart wakir-persona-engine`.
* Smoke-Test re-run.

## §5 -- OPEN-J3+K3 Carry-Forward-Items

### Item I6 -- OPEN-J3 Containerfile-Label-Carry-Forward

**Owner**: Operator-Hand (Live-VM, Image-Rebuild + Quadlet-Restart)
**Timing**: Production-Bringup-Day-6 (2026-07-09 Do), nicht Pre-
Cutover-Eve (J3-Closure ist Phase-3-close, nicht Phase-3-open)
**Prerequisites**:

* Tag-64 Doc `open-j3-v907-base-image-digest-label.md` vorhanden
* Tag-64 Doc `open-k3-v907-baseline-metadata-carry-forward.md`
  vorhanden
* Welle-7-Sign-off (2026-07-03 Fr) erreicht und Phase-3-COMPLETE-
  Marker gefeuert (Day-1, 2026-07-04 Sa)
* Marathon-Acceptance-Verdict APPROVED

**Step-by-Step**:

1. Operator liest `open-j3-v907-base-image-digest-label.md` §3
   Carry-Forward-Procedure.
2. Operator rebuild-et Persona-Engine-Image mit OPEN-J3-Label:
   `podman build --label org.wakir.v907-base-digest=<digest>
   --tag wakir-persona-engine:0.5.3-j3-carry .` (oder via CI-
   Pipeline `.github/workflows/persona-engine-image-build.yml`).
3. Operator pull-t neuen Image und triggert Quadlet-Restart (siehe
   Item I5 Step 2-5).
4. Operator commit-et OPEN-J3-Closure-Record in
   `state/open-closure-records/open-j3-closure-2026-07-09.json`.

**Verification**:

* `podman inspect wakir-persona-engine:0.5.3-j3-carry | jq
  .Config.Labels[\"org.wakir.v907-base-digest\"]` returns valider
  Digest-String.
* OPEN-J3-Closure-Record-File existiert und enthaelt Closure-
  Timestamp.

**Rollback**:

* Re-pull `:0.5.3`-Image (ohne `-j3-carry`-Suffix) und Quadlet-
  Restart.
* Loesche Closure-Record-File (oder markiere als `closure-reverted`).

### Item I7 -- OPEN-K3 Baseline-Metadata-Carry-Forward

**Owner**: Operator-Hand (Live-VM, Metadata-Refresh-Helper)
**Timing**: Production-Bringup-Day-6 (2026-07-09 Do), parallel zu Item I6
**Prerequisites**:

* Tag-64 Doc `open-k3-v907-baseline-metadata-carry-forward.md`
  vorhanden
* Item I6 (OPEN-J3-Carry-Forward) parallel laufend oder abgeschlossen
* `tooling/ci/refresh_baseline_metadata.py` vorhanden

**Step-by-Step**:

1. Operator liest `open-k3-v907-baseline-metadata-carry-forward.md`
   §4 Carry-Forward-Procedure.
2. Operator fuehrt `tooling/ci/refresh_baseline_metadata.py
   --output state/baseline-metadata/post-welle-7.json` aus.
3. Helper sammelt aktuelle Image-Digests, Persona-Manifest-Hashes,
   und ADR-State-Snapshots in die Output-Datei.
4. Operator commit-et OPEN-K3-Closure-Record in
   `state/open-closure-records/open-k3-closure-2026-07-09.json`.

**Verification**:

* `test -s state/baseline-metadata/post-welle-7.json` returns 0.
* OPEN-K3-Closure-Record-File existiert und enthaelt Closure-
  Timestamp + Metadata-Source-Reference.

**Rollback**:

* Loesche `state/baseline-metadata/post-welle-7.json` und Closure-
  Record-File.

## §6 -- ADR-0070-Migration nach AI-Corp/decisions/

### Item I8 -- ADR-0070-Cross-Repo-Migration

**Owner**: Operator-Hand (Live-VM, Git-Cross-Repo-Commit) +
**Co-Owner**: Mira (Approval-Pre-Migration)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, nach Item I4
**Prerequisites**:

* ADR-0070-Draft in `wakir-runtime/decisions/0070-*.md` vorhanden
* Mira-Approval-Stamp im Draft-Header
* Tag-50 Doc `adr-cross-repo-migration-pattern.md` vorhanden
* Operator hat Push-Access auf `AI-Corp` (Mira-Hand-Repo)

**Step-by-Step**:

1. Operator liest `adr-cross-repo-migration-pattern.md` §3
   Migration-Procedure.
2. Operator copy-t Draft-File `wakir-runtime/decisions/0070-*.md`
   nach `AI-Corp/decisions/0070-*.md` (via local clone).
3. Operator commit-et im AI-Corp-Repo: `git add decisions/0070-*.md
   && git commit -m "adr(0070): migrate from wakir-runtime per
   tag-50 pattern"`.
4. Operator push-t AI-Corp-Commit (Mira-Hand-authorisiert per
   Continuous-Mode-Pre-Approval).
5. Operator commit-et im wakir-runtime-Repo: `git mv
   decisions/0070-*.md decisions/migrated/0070-*.md` mit Stub-
   Pointer auf AI-Corp.

**Verification**:

* `gh api /repos/wakir-labs/AI-Corp/contents/decisions/0070-*.md`
  returns 200.
* `wakir-runtime/decisions/migrated/0070-*.md` existiert als Stub-
  Pointer.

**Rollback**:

* AI-Corp-Commit revert-en: `git revert <adr-migration-commit>`.
* wakir-runtime: `git mv decisions/migrated/0070-*.md
  decisions/0070-*.md`.

## §7 -- wakir-protocol Cross-Review-Zone-3 Hand-off-PR (#395)

### Item I9 -- Zone-3-Hand-off-PR-Merge

**Owner**: Operator-Hand (Live-VM, gh pr merge) +
**Co-Owner**: Reza (Zone-3-Spec-Owner, Cross-Review-Konsens)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, nach Item I4
**Prerequisites**:

* Tag-62 PR #395 (Reza, Cross-Review-Zone-3-Hand-off) ist `open`
  und review-approved
* Tag-62 Doc `wakir-protocol-cross-review-zone-3-handoff-plan.md`
  vorhanden
* Aisha-Cross-Review-Konsens-Protokoll in `state/cross-review-
  consensus/zone-3-2026-XX-XX.md` vorhanden

**Step-by-Step**:

1. Operator liest `wakir-protocol-cross-review-zone-3-handoff-
   plan.md` §5 Merge-Procedure.
2. Operator prueft Required-Checks-Status auf PR #395: alle 8
   Checks gruen (per Item I1 aktiviert).
3. Operator triggert `gh pr merge 395 --squash --repo wakir-labs/
   wakir-protocol --delete-branch`.
4. Operator commit-et Closure-Record in
   `state/cross-review-consensus/zone-3-handoff-closure-2026-06-26.md`.

**Verification**:

* `gh pr view 395 --repo wakir-labs/wakir-protocol --json state |
  jq -r .state` returns `MERGED`.
* Closure-Record-File existiert mit Merge-Commit-SHA.

**Rollback**:

* Bei Post-Merge-Bug: `git revert <merge-commit>` auf
  wakir-protocol main, dann PR re-open.

## §8 -- Operator-Hand-OTS-Stamping pre-Cutover-Eve

### Item I10 -- OTS-Stamping-Pipeline pre-Cutover-Eve

**Owner**: Tomas (OTS-Pipeline-Owner) + **Co-Owner**: Operator-Hand
(Live-VM, `chore(ots): timestamp <hash>`-Commit-Auslosung)
**Timing**: Pre-Cutover-Eve-Stichtag 2026-06-26 Fr, als letzter
Pre-Cutover-Step (nach Items I1..I9)
**Prerequisites**:

* Tomas-Tag-76 OTS-Pipeline aktiv und smoke-tested
* `WAKIR_OTS_LIVE_EMIT=1` Environment-Variable im Operator-Shell
  gesetzt
* `tooling/ots/stamp_commit.py` vorhanden und ausfuehrbar
* OTS-Calendar-Server erreichbar (`curl
  https://alice.btc.calendar.opentimestamps.org` returns 200)

**Step-by-Step**:

1. Operator setzt `export WAKIR_OTS_LIVE_EMIT=1` im Live-VM-Shell.
2. Operator identifiziert die letzten Pre-Cutover-Eve-Commits
   (Items I1..I9 produced Commits + Trust-Root-Snapshot-Commit).
3. Operator fuehrt `tooling/ots/stamp_commit.py --commit HEAD
   --calendar alice.btc.calendar.opentimestamps.org` pro relevantem
   Commit aus.
4. Helper produziert pro Commit eine `chore(ots): timestamp <hash>`-
   Folge-Commit mit `.ots`-Attachment.
5. Operator push-t alle OTS-Stamp-Commits (Mira-Hand-Continuous-Mode-
   Pre-Approval).

**Verification**:

* `git log --oneline | grep -c "chore(ots): timestamp"` zeigt
  Increment um die Anzahl der Pre-Cutover-Eve-Commits.
* Pro Commit: `.ots`-File existiert in `state/ots-stamps/<commit-
  sha>.ots` und ist nicht-leer.
* `tooling/ots/verify_ots_stamp.py --commit <sha>` returns OK.

**Rollback**:

* OTS-Stamps sind append-only und nicht rollback-bar (Bitcoin-
  Anchoring-Property). Bei Pipeline-Fehler: Re-Trigger des Stamp-
  Helpers; Duplikat-Stamps sind unbedenklich.
* `WAKIR_OTS_LIVE_EMIT=0` setzen, um weitere Stamps zu unterbinden.

## §9 -- Aggregate-Pre-Cutover-Eve-Verdict-Roll-up

Diese Sektion fasst die zehn Operator-Hand-Items I1..I10 in ein
einziges Aggregate-Verdict zusammen, das der Operator am Pre-Cutover-
Eve-Stichtag-Ende (2026-06-26 Fr 22:00 CEST) als finale Pruefung
ausspricht.

### Verdict-Marker

| Marker | Bedeutung | Triggert |
|---|---|---|
| `EVE-VERDICT-ALL-CLEAN` | I1..I10 alle abgeschlossen, alle Verifications passed | Welle-1-Cutover 2026-06-27 Sa Start |
| `EVE-VERDICT-PARTIAL-HOLD` | >=1 Item failed, Operator-Triage erforderlich | Cutover-Postpone-Decision an AR |
| `EVE-VERDICT-DEFER` | >=1 Item nicht startbar (Prerequisite-Gap), Pre-Walk re-run | Re-Walk + Re-Verdict-Run |
| `EVE-VERDICT-EMERGENCY-HOLD` | Trust-Root-Snapshot oder OTS-Stamping failed | AR-Hand-Sofort-Touchpoint TP-EVE-1 |

### Verdict-Commit-Procedure

1. Operator fuehrt am Pre-Cutover-Eve-Ende `tooling/ci/
   verify_operator_pending_konsolidat_doc.py --aggregate-verdict`
   aus.
2. Helper liest die Closure-Records I1..I10 (siehe §1..§8) und
   produziert ein Aggregate-State-File `state/pre-cutover-eve-
   verdict-2026-06-26.json`.
3. Operator commit-et das Verdict-File und triggert OTS-Stamping
   (Item I10).
4. Operator notifiziert Mira und AR via `inbox/2026-06-26-operator-
   pre-cutover-eve-verdict.md`-Lieferbericht.

### AR-Hand-Touchpoints

| Touchpoint | Trigger | AR-Action |
|---|---|---|
| TP-EVE-1 | EVE-VERDICT-EMERGENCY-HOLD | Sofort-Sichtung + Cutover-Halt-Decision |
| TP-EVE-2 | EVE-VERDICT-PARTIAL-HOLD | 24h-Triage-Sichtung + Postpone-or-Proceed-Decision |
| TP-EVE-3 | EVE-VERDICT-ALL-CLEAN | Routine-Sichtung + Welle-1-Cutover-Go-Signal |

## §10 -- AR-Vorzeichen "Halt vor Phase 4" Governance-Pin

Das **AR-Vorzeichen "Halt vor Phase 4"** (Tag-65 AR-Signal, verbatim
in `operator-hand-production-bringup-recipe.md` §9) ist die
**governance-pin**, die durch das gesamte Pre-Cutover-Eve-Window,
durch den Marathon-Lauf, durch das Production-Bringup-Window, und
bis zum expliziten AR-Hand-PHASE-4-RE-ARMED-Signal haelt.

### Verbatim-Wortlaut (Tag-65 AR-Signal)

> Phase-3-Marathon ends at Welle-7 cutover. No Phase-4 substrate
> enters the planning, the spec-stack, or any Operator-Hand-Recipe
> until an explicit AR-Hand re-arm signal lifts this pin.

### Konsolidat-Doc-Implikation

Diese Doc (Tag-77 Konsolidat) ist **explizit Phase-3-close-
positioned**: alle 10 Items I1..I10 sind **Marathon-Vorbereitung
oder Marathon-Stability**, **kein Item oeffnet Phase-4-Substrate**.

Konkret bedeutet das:

* Item I6 (OPEN-J3-Carry-Forward) und Item I7 (OPEN-K3-Carry-
  Forward) sind **Phase-3-Schluss-Items**, keine Phase-4-Open-Items.
* Item I8 (ADR-0070-Migration) ist eine **Repo-Topologie-Migration
  per ADR-Cross-Repo-Migration-Pattern**, keine ADR-Substanz-
  Aenderung Richtung Phase 4.
* Item I9 (Zone-3-Hand-off-PR) ist ein **Cross-Review-Konsens-
  Schluss**, nicht ein neuer Phase-4-Zone-Open.
* Item I10 (OTS-Stamping) ist ein **Audit-Trail-Persistence-Step**,
  kein Phase-4-Trigger.

Wenn der Operator zwischen Pre-Cutover-Eve und Welle-7-Sign-off
auf einen Item-Spawn stosst, der Phase-4-Substrate eroeffnen wuerde,
muss er **stoppen** und an AR via Mira eskalieren. Die governance-
pin haelt unverhandelt.

### Re-Arm-Signal-Mechanik

Das Re-Arm-Signal wird **ausschliesslich vom AR via Mira-Hand**
ausgesprochen und manifestiert sich als:

1. Mira-Commit in `AI-Corp/activity-log.md` mit Marker
   `PHASE-4-RE-ARMED-<datum>`.
2. Mira-ADR-Vorlage `AI-Corp/decisions/NNNN-phase-4-re-arm-
   trigger.md`.
3. AR-Approval-Stamp auf der ADR.

**Erst nach allen drei Markern** darf ein Engineering-Agent (Kai,
Reza, Tomas) Phase-4-Substrate planen oder spec-schreiben. Diese
Doc dokumentiert das **als Konsolidat-Reference**, ohne selbst das
Signal zu sein.

— Kai
