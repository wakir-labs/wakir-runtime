---
title: "Phase-3c Welle-7 recovery_workflow Operator-Cutover-Runbook (PHASE-3c-MARATHON-CLOSURE)"
owner: "Kai Hoffmann (DevOps), Tomas Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065, 0066"
welle: 7
component: "recovery_workflow"
component_short: "recovery"
env_var: "WAKIR_RECOVERY_BACKEND"
env_value_cutover: "rust"
cutover_date: "2026-06-29"
cutover_window_cest: "10:00-14:00"
soak_window_minutes: 15
hairpin_rollback_window_cest: "Mi 09:00-13:00"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 39
parallel_welle: 6
parallel_welle_component: "subscribe_loop"
parallel_welle_env_var: "WAKIR_SUBSCRIBE_LOOP_BACKEND"
sequence_after: "welle-6-§3.6 (Subscribe-Loop-Resume-Verify)"
risk_class: "doppel-welle-cross-modul-drift + recovery-drill-marathon-closure"
phase_marathon_end: "2026-06-21 — Welle-7-Sign-Off-Green setzt phase_3c_complete: true"
---

# Phase-3c Welle-7 recovery_workflow Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-7-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die `recovery_workflow`-
Komponente der Persona-Engine, 8. emittierte `BackendDecision` —
kurz `recovery` in In-Repo-Resolvern/Dry-Run-Scripts).
Ziel-Cutover-Datum: Montag 2026-06-29, KW-27, **parallel** zu
Welle-6 (`subscribe_loop`) gemaess ADR-0066 §KW-27-Final-Doppel-
Welle, mit **Sequenz-Constraint** (Welle-7-§3 startet nach Welle-6-
§3.6).

**PHASE-3c-MARATHON-CLOSURE:** Welle-7-Sign-Off-Green setzt den
`phase_3c_complete: true`-Flag und schliesst die Phase-3c-Cutover-
Sequenz (KW-24 bis KW-27) ab. Geplantes Phase-3-Marathon-Ende per
ADR-0066: ~2026-06-21 nach Welle-7-Sign-Off-Day plus Henrik-Hand-
Tag-Verzoegerung.

Dies ist das **operative Day-Of-Skript**. Hermetic-Validierung
(`phase-3c-welle-7-validation.yml`) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-7-runbook.md`](../operations/phase-3c-welle-7-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM, echter
NATS-Bus, echte Quadlet-Restart-Sequenz, echte R1..R4-Drill-Latency-
Histogramm-Beobachtung.

Schwester-Runbook fuer Welle-6 (parallel-Cutover-Coordination):
- [`welle-6-subscribe-loop-runbook.md`](./welle-6-subscribe-loop-runbook.md)
  (paralleler Tag-39-Spawn, gleicher Bundle-PR).

Vorgaenger-Runbooks (Phase-3c-Sequenz, alle auf main):
- [`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md)
  (PR #228, Tag-34, Welle-1 `v907_verify` KW-24 Montag parallel zu Welle-2).
- [`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md)
  (PR #232, Tag-35, Welle-2 `svid_workload_identity` KW-24 Montag parallel zu Welle-1).
- [`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md)
  (PR #237, Tag-36, Welle-3 `bridge_audit_writer` KW-25 Montag solo Henrik-Caution).
- [`welle-4-state-backing-runbook.md`](./welle-4-state-backing-runbook.md)
  (PR #243, Tag-37, Welle-4 `state_backing` KW-26 Montag paralleler Doppel-Welle-Partner zu Welle-5).
- [`welle-5-lifecycle-state-machine-runbook.md`](./welle-5-lifecycle-state-machine-runbook.md)
  (PR #247, Tag-38, Welle-5 `lifecycle_state_machine` KW-26 Montag paralleler Doppel-Welle-Partner zu Welle-4).

## Welle-7-Charakter (recovery_workflow-spezifisch)

**Welle-7 ist die einzige Welle in der die zu cutover'nde Komponente
eine vier-phasige Recovery-Orchestrator-Sequence ist.** Vorgaenger-
Wellen sind alle entweder Verify-Computation (v907_verify),
Identity-Resolution (svid), Sink-Pfad (bridge_audit_writer), Read-
Write-State-Substrate (state_backing), Transition-FSM (FSM) oder
Ingress-Substrate (subscribe_loop). Recovery-Workflow dagegen ist
ein **State-Dependency-Substrate**: R1 Detect klassifiziert den
Trigger, R2 Reload zieht State aus dem State-Backing (Welle-4-
Substrate), R3 Re-register refresht SPIFFE-SVID (Welle-2-Substrate),
R4 Resume transitiet den Quadlet-Container nach `active`. Recovery
hat die staerkste Cross-Welle-Dependency aller Phase-3c-Wellen.

**Drei recovery_workflow-spezifische Charakteristika:**

1. **Single-Value-Variant (`rust`, identisch zu Welle-3/5/6)** —
   der Resolver `resolve_recovery_backend` akzeptiert nur die
   Standard-Werte aus `VALID_RECOVERY_BACKEND_VALUES` (`python`
   ODER `rust`). Welle-7-Env-Overlay setzt
   `WAKIR_RECOVERY_BACKEND=rust` (siehe
   `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE`
   Zeile 204).
2. **R1..R4-Drill-Pre-Snapshot + Post-Verify (§3.2.5 + §3.6)** —
   vor Restart wird ein Recovery-Drill im Python-Backend ausgefuehrt
   (synthetischer R1-Trigger, R2-Reload-Probe, R3-SVID-Refresh-
   Probe, R4-Resume-Probe), die Latency-Histogramme pro Phase werden
   als immutable Snapshot erfasst. Nach Restart prueft §3.6 mit
   einem identischen Drill, ob die Rust-Backend-Latency-Histogramme
   in der Spec-Hard-Cap bleiben (R1 ≤ 1s, R2 ≤ 15s, R3 ≤ 5s, R4
   ≤ 9s — siehe `recovery_workflow.py::PHASE_SOFT_CAPS_SEC`).
3. **State-Backing-Dependency (Welle-4 schon cutovert)** — R2
   Reload liest aus `state_backing` (Welle-4-Substrate). Wenn
   Welle-4-`rust_inmemory` einen Read-Path-Bug hat, wird R2 Reload
   im Welle-7-Cutover stallen. Mitigation: §1 Welle-4-Sign-Off-
   Pflicht-Vorbedingung; §3.6 R2-Phase-Latency-Spec-Cap-Check;
   §4.4 Cross-Modul-Drift-Check (R2-State-Read-Sanity-Achse).
   Cross-Modul-Stress-Test als §4.4 Soak-Step (Phase-2-Acceptance-
   Gate Step 6 aus PR #197), 3-Achsen-Schwelle recovery x
   subscribe_loop.

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ + KW-27-Final-Doppel-Welle | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Welle-7 Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-7-validation.yml` |
| Welle-7 Sibling-Validation-Runbook | `docs/operations/phase-3c-welle-7-runbook.md` |
| Welle-1 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-1-v907-verify-runbook.md` (PR #228, Tag-34) |
| Welle-2 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-2-svid-workload-identity-runbook.md` (PR #232, Tag-35) |
| Welle-3 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-3-bridge-audit-writer-runbook.md` (PR #237, Tag-36) |
| Welle-4 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-4-state-backing-runbook.md` (PR #243, Tag-37) |
| Welle-5 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-5-lifecycle-state-machine-runbook.md` (PR #247, Tag-38) |
| Welle-6 Pre-Cutover-Operator-Runbook (paralleler Partner) | `docs/phase-3c/welle-6-subscribe-loop-runbook.md` (gleicher Bundle-PR Tag-39) |
| Recovery Container-Image-Build-Pipeline | PR #167 (Tag-17) + Tag-33 Mini-Welle `recovery-welle7` Quadlet-Carrier-Update |
| Recovery Cross-Lang-Hash-Parity-Pins | `tests/fixtures/recovery-workflow-cross-lang/fixtures.json` |
| Resolver `resolve_recovery_backend` | `wirelang/persona_engine/rust_backend_switch.py` (`RECOVERY_BACKEND_ENV` L426, `DEFAULT_RUST_RECOVERY_BIN` L448) |
| Resolver-Variant-Map | `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE` (recovery -> rust) |
| Component-Alias-Map | `scripts/phase-3c-cutover-dry-run.py::PHASE_3C_COMPONENT_ALIASES` (`recovery_workflow` -> `recovery`) |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Cross-Modul-Stress-Aggregator (Doppel-Welle-Pflicht) | `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress` (PR #197) |
| Quadlet-Inventar (9-Binary) | `quadlet/wakir-rust-cli.container` (`wakir-persona-engine-recovery` in Exec-Schleife) |
| Cosign-Policy (9-Binary) | `policies/cosign-policy-phase-3b.yaml` `name: recovery` |
| Selin Welle-7 Cutover-Smoke-Skript | `scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh` (Selin Tag-39, paralleler Cross-Spawn) |
| Recovery Modul | `wirelang/persona_engine/recovery_workflow.py` (R1..R4 Spec §3.7.4) |
| Subscribe-Loop Modul (Welle-6-Cross-Modul-Anker) | `wirelang/persona_engine/subscribe_ack.py` (via Welle-6-Runbook konkretisiert) |
| State-Backing Modul (Welle-4-Read-Dependency) | `wirelang/persona_engine/state_backing.py` (R2-Reload-Source) |
| SVID-Modul (Welle-2-Read-Dependency) | `wirelang/persona_engine/svid_workload_identity.py` (R3-Re-Register-Source) |
| Welle-7-Telemetry-Runbook | `docs/operations/welle-7-telemetry-runbook.md` (falls vorhanden — sonst Welle-5-Telemetry-Runbook als Cross-Anker) |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya.

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar 9-Binary)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `recovery` mit
      `in_image_path: /opt/wakir/bin/wakir-persona-engine-recovery`.
      Tag-33 Mini-Welle ergaenzt einen `recovery-welle7`-Variant-
      Eintrag mit demselben Crate-Pfad.
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 9 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` listet
      `wakir-persona-engine-recovery` in der `Exec=`-Schleife des
      Installer-Containers. Tag-33 Mini-Welle ergaenzt
      `wakir-persona-engine-recovery-welle7`-Variant-Pin
      (Carrier-Image-Verifikation via `sha256sum-checks`-Probe).
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence: `wirelang/persona_engine/rust_backend_switch.py`
      enthaelt `RECOVERY_BACKEND_ENV =
      "WAKIR_RECOVERY_BACKEND"` (L426) und
      `DEFAULT_RUST_RECOVERY_BIN ==
      /opt/wakir/bin/wakir-persona-engine-recovery` (L448).
      Resolver akzeptiert nur Standard-Werte `python` ODER `rust`
      (siehe `VALID_RECOVERY_BACKEND_VALUES` L629).
      Engine-Boot-Audit emittiert 8. `BackendDecision` mit
      `component=recovery` (in-repo short form) bzw.
      `recovery_workflow` (long-form Alias).
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet, GitHub-Runner-Baseline-File nicht).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — gruen. Evidence:
      `tests/integration/test_bridge_audit_roundtrip_e2e.py` passt
      (oder all-SKIP auf Runner ohne replay_cli-Binary). Recovery-
      R1..R4-Phase-Audit-Annotation wird emittiert.
- [ ] **Welle-7-Wednesday-Validation-Run gruen** (2026-06-24
      06:00 UTC, KW-26 Mittwoch — 5 Tage vor Cutover-Montag KW-27).
      Evidence: `cutover-acceptance-decision-welle-7.json`
      `ready_for_live_smoke == true` UND `cross_modul_stress_passed
      == true` (Step 6 PR #197). Artifact-Retention 30 Tage.
      Workflow: `.github/workflows/phase-3c-welle-7-validation.yml`.
- [ ] **Welle-3-6 Sign-Off-Verdicte alle bekannt** (Pflicht-
      Vorbedingung fuer KW-27-Final-Doppel-Welle-Welle-7):
      - **Welle-3** `green` ODER `green-with-yellow-notes-mit-
        Henrik-Hand-Approval` (KW-25 Montag, Bridge-Audit-Substrate
        fuer R1-Recovery-Audit-Annotations).
      - **Welle-4** `green` ODER `green-with-yellow-notes` (KW-26
        Montag, **R2-Reload-Source-Substrate**, kritischer Welle-7-
        Vorbedingung).
      - **Welle-5** `green` ODER `green-with-yellow-notes` (KW-26
        Montag, FSM emittiert Transition-State-Snapshots die R2
        liest).
      - **Welle-6** Pre-Conditions-Status (KW-27 Doppel-Welle-Partner
        — Welle-6 cutovert parallel, nicht vorher).
      Vier zulaessige Zustaende fuer Welle-7-Trigger:
      - **(a) Welle-3+4+5 alle `green`, Welle-6 Pre-Cond green** —
        Welle-7 startet planmaessig KW-27 Montag ~11:05 CEST.
      - **(b) Mindestens eine Welle-3+4+5 `green-with-yellow-notes`
        + Henrik-Hand-Approval-File** — Welle-7 startet, aber Mira-
        Hand-Decision-Point mit explizitem Yellow-Notes-Review im
        Cutover-Window.
      - **(c) Jede Welle-3+4+5 in `rollback` ODER `ar-hand-stop`**
        — Welle-6+7 wird BLOCKIERT, nicht gestartet. AR-Eskalation
        Pflicht (§9 R-6). **Phase-3c-Marathon-Schluss-Stempel
        verschiebt sich.**
      - **(d) Welle-6-§3.6 yellow ODER red** — siehe naechster
        Punkt fuer Sequenz-Constraint.
- [ ] **Welle-6-Cutover-Status verifiziert (Doppel-Welle-Sequenz-Constraint, Welle-6 zuerst)** —
      Welle-7-§3 darf erst starten **nach Welle-6-§3.6 Subscribe-
      Loop-Resume-Verify** (siehe §3.0). Drei zulaessige Zustaende
      fuer Welle-7-Trigger relativ zu Welle-6:
      - **(a) Welle-6-§3.6 green (Sub-Active + Cursor-Continuity + Ack-Rate>0)** —
        Welle-7-§3 startet planmaessig KW-27 ~11:05 CEST.
      - **(b) Welle-6-§3.6 yellow (Boot-Audit-OK aber sekundaere
        Yellow-Trigger im Output-Reply oder Lag)** — Mira-Hand-
        Decision ob Welle-7 mit Cross-Modul-Coupling fortfaehrt oder
        solo-verschiebt. Doppel-Welle-Coupling stark: Drift in
        Welle-6-Subscribe-Loop macht Welle-7-R1-Detect-Triggering
        unverlaesslich.
      - **(c) Welle-6-§3.6 red (Cursor-Regression, Drain-Hang oder
        T-3 Rollback)** — Welle-7-Cutover wird **NICHT** gestartet.
        Welle-6-Rollback und Welle-7-Verschiebung auf KW-28 oder
        spaeter (Re-Schedule mit Welle-6-§6-Sign-Off als Re-Trigger).
        **Phase-3c-Marathon-Schluss-Stempel verschiebt sich auf KW-28+.**
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, **post-Welle-1+2+3+4+5 Engine-Posture und vor Welle-6-
      Cutover-Start**). Latency-p50/p95, Error-Rate,
      BackendDecision-Volume pro Minute, Recovery-Drill-Count
      seit Engine-Start (R1..R4-Phase-Counter, falls jemals
      getriggert). Persistiert in
      `/var/lib/wakir/baselines/welle-7-pre-cutover-<TS>.json`.
      **Wichtig:** Die Baseline wird **nach KW-24+25+26-Sign-Off
      und vor Welle-6+7-KW-27-Cutover-Start** frisch aufgezeichnet.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component recovery --window 5m --format json` liefert
      gueltige Records mit `backend=python` >99% (Baseline).
- [ ] **Quadlet 9-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 9 Binaries inklusive
      `wakir-persona-engine-recovery`.
- [ ] **Cosign-Policy 9-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit.
      Das transitiv-verifizierte Image-Manifest umfasst recovery-
      Image (sowohl Tag-17-Origin `recovery` als auch Tag-33-Variant
      `recovery-welle7`).
- [ ] **Recovery Cross-Lang-Hash-Parity-Pins frisch**.
      Evidence: `tests/fixtures/recovery-workflow-cross-lang/
      fixtures.json` existiert, Pin-Count ≥ 5 (R1..R4-Phase-Audit-
      Annotation-Fixtures). Das ist die Baseline-Referenz fuer
      §4.2 Cross-Lang-Hash-Parity-Probe.
- [ ] **Cross-Modul-Stress-Test Wednesday-Run gruen** (Doppel-Welle-
      Pflicht aus ADR-0066 §Mitigations, symmetric zu Welle-4/5).
      Evidence: Welle-7-Validation-Workflow Step 6
      (`doppelbetrieb-score-aggregator --mode=cross-modul-stress`)
      hat alle 3 Achsen `>= threshold`:
      - `cross-lang-pin-coverage` (recovery x subscribe_loop)
      - `cross-modul-fixture-stability` (R1-Trigger-Klassifikation
        gegen Subscribe-Loop-Drop-Signal)
      - `cross-modul-rollup-integrity` (Welle-6+7-Aggregate-Health)
- [ ] **R2-State-Backing-Read-Sanity gruen** (Welle-7-spezifisch).
      Welle-4-`state_backing` ist seit KW-26 auf `rust_inmemory`.
      R2 Reload liest aus diesem Backend. Pre-Cutover-Sanity-Check:
      `scripts/phase-3c/r2-state-read-sanity-probe.py --pilot
      192.168.178.116 --window 5m` liefert `state_read_p99_ms < 500`
      ueber 12 Reload-Samples.
- [ ] **R3-SVID-Refresh-Sanity gruen** (Welle-7-spezifisch).
      Welle-2-`svid_workload_identity` ist seit KW-24 auf Rust.
      R3 Re-Register refresht SPIFFE-SVID via diesem Backend.
      Pre-Cutover-Sanity-Check: `scripts/phase-3c/r3-svid-refresh-
      sanity-probe.py --pilot 192.168.178.116 --window 5m` liefert
      `svid_refresh_p99_ms < 1000` ueber 12 Refresh-Samples.
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt** —
      Mittwoch KW-27, 09:00-13:00 CEST (4h-Slot, identisch zu
      Welle-6 wegen Doppel-Welle-Cross-Modul-Drift-Koordination).
      **Welle-6+7 teilen sich denselben Rollback-Slot** —
      parallel-Rollback ist explizit erwartet bei T-4 Cross-Modul-
      Trigger.
- [ ] **Phase-3c-Marathon-Closure-Bewusstsein:** Welle-7-Sign-Off
      ist der **Schluss-Stempel** der Phase-3c-Cutover-Sequenz.
      Henrik-AR-Tag setzt `phase_3c_complete: true` im Activity-
      Log nach Welle-7-Green. Bei Welle-7-Rollback verschiebt sich
      der Schluss-Stempel auf KW-28+ (Re-Schedule durch AR).

---

## §2 Pre-Flight-Smoke

Selin's Welle-7-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet zur
Pilot-VM testet und kein Pilot-internes Artefakt ist. Skript
liefert Selin **parallel zu diesem Runbook** (Tag-39 Cross-Spawn).

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component recovery_workflow \
    --component-short recovery \
    --env-var WAKIR_RECOVERY_BACKEND \
    --env-value rust \
    --parallel-welle 6 \
    --cross-modul-stress-axis recovery,subscribe_loop \
    --sequence-after-welle 6 \
    --recovery-drill-phases R1,R2,R3,R4 \
    --dry-run-window 5m \
    --json-out /tmp/welle-7-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten **nach
  Welle-6-§3.6**.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated ODER Welle-3-5 `green-with-yellow-notes` post-hoc).
  Mira-Hand-Decision noetig vor §3.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Tomás (Matrix-Lead). **Bei red: kein Cutover-
  Versuch ohne Henrik-Hand-Override.**

Das JSON-Envelope (`/tmp/welle-7-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~4-6 min wall-clock (laenger als Welle-1/2/4
wegen Cross-Modul-Stress-Axis-Sample + Recovery-Drill-Pre-Sanity
auf vier Phasen R1..R4). Skript prueft SSH-Reachability, Quadlet-
Status-Snapshot, Cosign-Policy-Match (9-Binary), Engine-Health-
Baseline-Delta gegen Tag-N-1, R1..R4-Phase-Latency-Histogramme
(Python-Backend-Baseline gegen Spec-Hard-Caps), BackendDecision-
Aggregator-Sanity fuer `component=recovery` (long-form
`recovery_workflow`), Cross-Modul-Stress-Smoke (Recovery x
subscribe_loop 3-Axen-Sample). Keine Side-Effects auf Pilot-VM
(read-only).

**Welle-6+7-Parallel-Hinweis:** Welle-7 und Welle-6 starten am
selben Cutover-Tag KW-27 Montag. Pre-Flight-Smokes Welle-7 und
Welle-6 duerfen parallel laufen, **aber** §3 Cutover-Step Welle-6
+ §3 Cutover-Step Welle-7 sind seriell-koordiniert: Welle-7-§3
beginnt erst nach Welle-6-§3.6 (siehe §3.0 Doppel-Welle-Sequenz).
Begruendung: Subscribe-Loop-Drop ist R1-Detect-Trigger im Recovery-
Workflow. Wenn beide Backends gleichzeitig flippen, ist eine R1-
Detect-Race mit dem Subscribe-Loop-Reconnect-Latenz nicht
unterscheidbar von einer Recovery-Init-Failure.

---

## §3 Cutover-Step

**Mira-Hand-SSH-Authority** gemaess ADR-0058 §Nachtrag. AR-
Eskalations-Override nur fuer `irreversible despawn`-Pfade —
Quadlet-Restart und Env-Overlay fallen darunter **nicht**, das
ist routine Operator-Hand-Operation.

**Welle-7-spezifische Erweiterung:** §3.2.5 Recovery-Drill-Pre-
Snapshot (Python-Backend-Recovery-Drill mit synthetischen R1..R4-
Phasen, Latency-Histogramme persistiert; reboot mit Rust-Recovery-
Backend; identischer Drill in §3.6 mit Latency-Histogramm-Compare
gegen Spec-Hard-Caps). Ohne diesen Step ist eine Recovery-Drill-
Latency-Excursion nicht unterscheidbar von einer Boot-Failure.

**Schritt 3.0 — Doppel-Welle-Sequenz (Welle-6 zuerst, Welle-7 folgt)**

Welle-7-Cutover beginnt **nach** Welle-6-§3.6 Subscribe-Loop-
Resume-Verify. Begruendung: Subscribe-Loop ist R1-Detect-Trigger-
Source. Wenn beide gleichzeitig flippen, ist eine echte Subscribe-
Drop-Detect-Race mit dem Welle-7-Engine-Restart nicht unterscheidbar
von einer Welle-6-Boot-Failure. Sequenz garantiert, dass Welle-6-
Rust-Subscribe-Loop stabil ist bevor Welle-7-Rust-Recovery den
Subscribe-Loop-Drop als R1-Trigger-Source sieht.

Welle-7-Cutover-Step §3.1 startet erst nach Welle-6-§3.6 Subscribe-
Loop-Resume-Verify-OK (Sub-Active + Cursor-Continuity + Ack-Rate>0).

**Schritt 3.1 — SSH auf Pilot-VM**

```bash
ssh root@192.168.178.116
# Erwarteter Banner: "wakir-pilot — FCOS — Phase-3b live"
```

**Schritt 3.2 — Pre-Restart-Snapshot (post-Welle-1+2+3+4+5+6)**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-7 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-7-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-7-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-7-cutover-pre-journal.txt

# Welle-1-6-State-Check: bestaetige dass alle Vorgaenger backend=rust
# (bzw. rust_inmemory fuer state_backing) laufen.
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -cE "BackendDecision.*(v907_verify|svid_workload_identity|anchor_emitter|state_backing|fsm|subscribe_loop).*backend=(rust|rust_inmemory)" \
  | tee -a /var/log/wakir/welle-7-cutover.log
# Erwartung: > 0 Records pro Component (sechs separate Linien).
```

**Schritt 3.2.5 — Recovery-Drill-Pre-Snapshot (Welle-7-spezifisch)**

**Kritisch.** Vor dem Restart muss ein vollstaendiger Recovery-
Drill im Python-Backend ausgefuehrt werden, mit synthetischem R1-
Trigger (kein echter Failure-Trigger), R2-Reload-Probe, R3-SVID-
Refresh-Probe, R4-Resume-Probe. Latency-Histogramme pro Phase
werden als immutable Snapshot erfasst. Das ist die Vergleichs-
Baseline fuer §3.6 Post-Restart-Drill.

```bash
# Auf Pilot-VM:
mkdir -p /var/lib/wakir/welle-7-recovery-baseline

# 1. Recovery-Drill via CLI-Tool (Python-Backend-Pfad, synthetic-trigger-mode)
/opt/wakir/bin/wakir-persona-engine-recovery \
    --mode=drill \
    --backend=python \
    --synthetic-trigger=manual_drill \
    --phases=R1,R2,R3,R4 \
    --output=/var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-${TS_PRE}.json
wc -c /var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-${TS_PRE}.json \
    | tee -a /var/log/wakir/welle-7-cutover.log

# 2. Latency-Histogramm-Extract pro R-Phase
python3 -c '
import json, sys
with open("/var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-'${TS_PRE}'.json") as f:
    d = json.load(f)
for phase in ("R1","R2","R3","R4"):
    h = d["phases"][phase]["latency_histogram_ms"]
    print(f"{phase}: p50={h[\"p50\"]} p95={h[\"p95\"]} p99={h[\"p99\"]} cap={h[\"soft_cap_ms\"]}")
' | tee -a /var/log/wakir/welle-7-cutover.log

# 3. Hash der Recovery-Baseline (SHA-256 fuer immutability-Verify in §6)
sha256sum /var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-${TS_PRE}.json \
    | tee /var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-${TS_PRE}.sha256 \
    | tee -a /var/log/wakir/welle-7-cutover.log

# 4. Spec-Hard-Cap-Check (Python-Backend muss schon innerhalb spec-cap sein)
# R1 ≤ 1s, R2 ≤ 15s, R3 ≤ 5s, R4 ≤ 9s (PHASE_SOFT_CAPS_SEC)
python3 -c '
import json, sys
with open("/var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-'${TS_PRE}'.json") as f:
    d = json.load(f)
fail = False
for phase, cap_ms in (("R1",1000),("R2",15000),("R3",5000),("R4",9000)):
    p99 = d["phases"][phase]["latency_histogram_ms"]["p99"]
    if p99 > cap_ms:
        print(f"PRE-CUTOVER-DRILL-EXCURSION: {phase} p99={p99}ms > cap={cap_ms}ms", file=sys.stderr)
        fail = True
sys.exit(1 if fail else 0)
'
if [ $? -ne 0 ]; then
    echo "PRE-CUTOVER-DRILL-FAIL: Python-Backend ueberschreitet Spec-Hard-Cap" >&2
    echo "Cutover ABBRUCH — Reza-Hand-Forensik-Eskalation" >&2
    exit 2
fi
```

**Erwartete Evidenz:** Drill-File-Size > 0, alle vier R-Phasen mit
gueltigen Latency-Histogrammen (p99 ≤ Spec-Hard-Cap), Hash
protokolliert. Wenn Python-Backend bereits ueber Spec-Hard-Cap:
STOP — Recovery-Workflow ist bereits vor Cutover unhealthy, das
ist ein Pre-Cutover-Red und §6 ist nicht der richtige Pfad (Reza
+ Henrik eskalieren, Cutover absagen).

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht in-place
edit. Reversibel, ADR-0058-konform. **Welle-7-spezifisch:** Env-
Wert ist `rust` (Single-Variant).

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-7-recovery-workflow-rust.conf <<'EOF'
# Phase-3c Welle-7 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-Sequenz, ADR-0066 §KW-27-Final-Doppel-Welle
# recovery_workflow (in-repo short form: recovery) Variant: rust
[Service]
Environment="WAKIR_RECOVERY_BACKEND=rust"
EOF
systemctl daemon-reload

# Sanity-Check: Welle-1-6 Drop-Ins existieren weiterhin.
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet:
#   welle-1-v907-verify-rust.conf
#   welle-2-svid-workload-identity-rust.conf
#   welle-3-bridge-audit-writer-rust.conf
#   welle-4-state-backing-rust.conf
#   welle-5-lifecycle-state-machine-rust.conf
#   welle-6-subscribe-loop-rust.conf
#   welle-7-recovery-workflow-rust.conf  (neu)
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-7-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s, 9/9 BackendDecisions, recovery rust)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust` und `component=recovery` (oder `recovery_workflow`
long-form) werden innerhalb 30s emittiert. Gleichzeitig muessen alle
9 Boot-`BackendDecision`-Records sichtbar sein — wenn nur 8/9:
Migrations-Drift-Zustand, §6 Rollback ist Pflicht.

```bash
# Auf Pilot-VM:
timeout 30 journalctl -u wakir-persona-engine.service \
    --since "${TS_RESTART}" -f \
    --output=json --no-pager \
  | python3 -c '
import json, sys, time
hits = 0
deadline = time.monotonic() + 30
for line in sys.stdin:
    try:
        rec = json.loads(line)
    except Exception:
        continue
    msg = rec.get("MESSAGE", "")
    # accept either in-repo short form (component=recovery) or
    # ADR-0065 long form (component=recovery_workflow).
    if ("BackendDecision" in msg
            and ("component=recovery" in msg or "component=recovery_workflow" in msg)
            and "backend=rust" in msg):
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision recovery rust records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

**Schritt 3.6 — R1..R4-Drill-Post-Verify (Welle-7-spezifisch)**

Spezifisch fuer Welle-7: nach Restart muss ein **identischer
Recovery-Drill** im Rust-Backend ausgefuehrt werden (synthetic-
trigger=manual_drill, gleicher Drill-Input wie §3.2.5), und die
Latency-Histogramme pro R-Phase muessen (a) in den Spec-Hard-Caps
bleiben (R1 ≤ 1s, R2 ≤ 15s, R3 ≤ 5s, R4 ≤ 9s) UND (b) keine grobe
Excursion gegen die Python-Baseline zeigen (Faktor ≤ 1.5× pro
Phase-p99).

```bash
# Auf Pilot-VM:
sleep 5  # Engine-Boot-Stabilisierung

# (a) Recovery-Drill via CLI-Tool (Rust-Backend-Pfad, gleicher synthetic-trigger)
/opt/wakir/bin/wakir-persona-engine-recovery \
    --mode=drill \
    --backend=rust \
    --synthetic-trigger=manual_drill \
    --phases=R1,R2,R3,R4 \
    --output=/var/lib/wakir/welle-7-recovery-baseline/post-cutover-drill-rust-${TS_PRE}.json
wc -c /var/lib/wakir/welle-7-recovery-baseline/post-cutover-drill-rust-${TS_PRE}.json \
    | tee -a /var/log/wakir/welle-7-cutover.log

# (b) Spec-Hard-Cap-Check fuer Rust-Backend
python3 -c '
import json, sys
with open("/var/lib/wakir/welle-7-recovery-baseline/post-cutover-drill-rust-'${TS_PRE}'.json") as f:
    d = json.load(f)
fail = False
for phase, cap_ms in (("R1",1000),("R2",15000),("R3",5000),("R4",9000)):
    p99 = d["phases"][phase]["latency_histogram_ms"]["p99"]
    if p99 > cap_ms:
        print(f"POST-CUTOVER-DRILL-EXCURSION: {phase} p99={p99}ms > cap={cap_ms}ms", file=sys.stderr)
        fail = True
    print(f"{phase}: rust p99={p99}ms cap={cap_ms}ms")
sys.exit(1 if fail else 0)
' | tee -a /var/log/wakir/welle-7-cutover.log
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "POST-CUTOVER-DRILL-FAIL: Rust-Backend ueberschreitet Spec-Hard-Cap" >&2
    exit 2
fi

# (c) Cross-Backend-Compare (Rust p99 muss <= 1.5x Python-Baseline p99 pro Phase)
python3 -c '
import json, sys
with open("/var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-'${TS_PRE}'.json") as fpy:
    py = json.load(fpy)
with open("/var/lib/wakir/welle-7-recovery-baseline/post-cutover-drill-rust-'${TS_PRE}'.json") as fru:
    ru = json.load(fru)
fail = False
for phase in ("R1","R2","R3","R4"):
    py_p99 = py["phases"][phase]["latency_histogram_ms"]["p99"]
    ru_p99 = ru["phases"][phase]["latency_histogram_ms"]["p99"]
    ratio = ru_p99 / max(py_p99, 1)
    status = "OK" if ratio <= 1.5 else "EXCURSION"
    print(f"{phase}: python={py_p99}ms rust={ru_p99}ms ratio={ratio:.2f} [{status}]")
    if ratio > 1.5:
        fail = True
sys.exit(1 if fail else 0)
' | tee -a /var/log/wakir/welle-7-cutover.log
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "POST-CUTOVER-DRILL-CROSS-EXCURSION: Rust > 1.5x Python pro R-Phase" >&2
    exit 2
fi

echo "R1..R4-DRILL-POST-VERIFY-OK: Spec-Caps + Cross-Backend-Ratio innerhalb tolerance"
```

Wenn Boot-Audit-Wait-Loop oder R1..R4-Drill-Post-Verify Exit ≠ 0:
sofort §6 Rollback-Procedure.

---

## §4 Post-Cutover-Verification (15-min Soak-Window)

Soak-Window **15min** (Welle-1/2/4/5/6-Standard, kein 30-min wie
Welle-3). Vier parallele Beobachtungs-Streams plus Cross-Welle-
Coupling-Monitor. **Welle-7-spezifisch:** §4.3 R1..R4-Recovery-
Latency-Histogramme als Soak-Achse, §4.4 Cross-Modul-Drift-Check
gegen Welle-6 (`subscribe_loop`) symmetric.

**§4.1 — BackendDecision-Aggregator Sliding-Window**

```bash
# Auf Mira-Box, gegen Pilot-NATS:
cd /var/home/fred/AI-Corp/wakir-runtime
python3 scripts/phase-3c/backend-decision-aggregator.py \
    --component recovery \
    --window 15m \
    --target-backend rust \
    --min-rust-share 0.99 \
    --format json
echo "aggregator-exit=$?"
```

Erwartung: `rust_share >= 0.99` ueber 15-min-Sliding-Window.
Exit 0 = green; Exit 1 = rust_share zwischen 0.95 und 0.99
(yellow); Exit 2 = rust_share <0.95 (red, sofort Rollback).

**§4.2 — Cross-Lang-Hash-Parity gegen Python-Baseline**

Recovery Cross-Lang-Hash-Parity-Pins (`tests/fixtures/recovery-
workflow-cross-lang/fixtures.json`). Im Soak-Window: 5 Synthetik-
R-Phase-Audit-Annotation-Hash-Calls, jede mit Python-Vergleichs-
Hash gegen die Pin-Baseline.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component recovery \
    --samples 5 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/fixtures/recovery-workflow-cross-lang/fixtures.json \
    --canonical-module wirelang.persona_engine.recovery_workflow
```

Erwartung: 5/5 Hashes match. Jede Drift => sofort §6 Rollback.

Hintergrund: die Cross-Lang-Parity prueft die deterministische
JCS-Kanonisierung der R-Phase-Audit-Annotation-Envelopes (welche
R-Phase, welcher Trigger-Typ, welche Latency-Histogramm-Buckets).
Drift heisst: Python- und Rust-Side haben unterschiedliche
Canonical-Forms — das ist ein blocker-level Bug fuer Recovery-Audit-
Trail-Persistence-Continuity.

**§4.3 — R1..R4-Recovery-Latency-Histogramme + Error-Freiheit + Backend-Latency**

```bash
# Auf Pilot-VM:
journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" \
    -p err --no-pager \
    | grep -E "recovery|recovery_workflow" \
    | tee /var/log/wakir/welle-7-recovery-errors.txt
wc -l /var/log/wakir/welle-7-recovery-errors.txt
```

Grafana-Dashboard `Persona-Engine — Backend Latency by Component`.
Filter: `component=recovery`, `backend=rust`, last 15min.

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

**Welle-7-spezifische Latenz-Achse — R1..R4-Phase-Latency-Histogramme:**

Soak-Window-Probe alle 5min mit echtem (nicht synthetic-trigger)
Recovery-Drill-Probe. Drei Probes gesamt, jede mit allen 4 R-
Phasen-p99-Werten.

| Phase | Spec-Hard-Cap (Soft-Cap-Sec) | Soak-Threshold |
|---|---|---|
| R1 Detect | 1s (1000ms) | p99 ≤ 1000ms |
| R2 Reload | 15s (15000ms) | p99 ≤ 15000ms |
| R3 Re-register | 5s (5000ms) | p99 ≤ 5000ms |
| R4 Resume | 9s (9000ms) | p99 ≤ 9000ms |

```bash
# Auf Mira-Box, alle 5min im Soak-Window:
for i in 1 2 3; do
    python3 scripts/phase-3c/r1-r4-drill-probe.py \
        --pilot 192.168.178.116 \
        --synthetic-trigger=soak_probe_${i} \
        --phases R1,R2,R3,R4 \
        --spec-caps R1=1000,R2=15000,R3=5000,R4=9000 \
        --json-out /tmp/welle-7-soak-drill-${i}.json
    echo "soak-probe-${i}-exit=$?"
    sleep 300
done
```

Operator: Screenshot pro 5min-Slice (3 Screenshots gesamt) + JSON-
Export an Henrik-Audit-Trail anhaengen.

Erwartung: 0 Error-Zeilen + 3/3 Soak-Drill-Probes mit allen R-Phase-
p99 unter Spec-Cap. Jede Excursion = automatischer §6 Rollback
(T-3 Trigger).

**§4.4 — Cross-Modul-Drift-Check gegen Welle-6 subscribe_loop (Welle-7-spezifisch, symmetric A7)**

Welle-7-exklusiv (im Doppel-Welle-Pattern, symmetric zu Welle-6-
§4.4): `recovery_workflow` steht in direkter Trigger-Korrelation
mit `subscribe_loop` (Subscribe-Loop-Drop ist R1-Trigger-Klasse
`subscribe_loop_failure`). Wenn Welle-6+7 parallel cutover: ein
Schema-Drift in einem der beiden Substrate emergiert als Cross-
Modul-Drift gegen den anderen.

```bash
# Auf Mira-Box:
python3 scripts/doppelbetrieb-score-aggregator.py \
    --mode=cross-modul-stress \
    --threshold 3 \
    --target-component recovery \
    --paired-component subscribe_loop \
    --pilot 192.168.178.116 \
    --json-out /tmp/welle-7-cross-modul-drift.json
echo "cross-modul-drift-exit=$?"
```

Erwartung: 3-of-3 Cross-Modul-Achsen `>= threshold`:
- `cross-lang-pin-coverage` (recovery × subscribe_loop cross-lang
  fixtures)
- `cross-modul-fixture-stability` (Subscribe-Drop -> R1-Trigger-
  Klassifikation Sanity, symmetric mit Welle-6-§4.4)
- `cross-modul-rollup-integrity` (Welle-6+7-Aggregate-Health =
  Phase-3c-Marathon-Aggregate)

Exit 0 = green; Exit non-zero = red (sofort Rollback, plus Welle-6-
Rollback-Koordination weil Doppel-Welle-Coupling — siehe §6
Schritt 5).

**§4.5 — Doppel-Welle-Coupling-Monitor (Welle-6-Cross-Status)**

```bash
# Auf Mira-Box, liest Welle-6-Cutover-Log (parallel-Cutover):
ssh root@192.168.178.116 'tail -50 /var/log/wakir/welle-6-cutover.log'
```

Erwartung: Welle-6-Soak-Window-Status (§4.1-§4.5 Welle-6-Runbook)
laeuft sauber. Wenn Welle-6 im Soak-Window-Beginn von Welle-7 einen
sekundaeren yellow-Trigger hat: Mira-Hand-Decision-Point (Welle-7-
Soak-Window fortfuehren oder Welle-7 parallel-Rollback einleiten).

**Cross-Welle-Yellow-Bedingung:** Wenn Welle-6 Rollback-Trigger
hat aber Welle-7 OK ist: Welle-7 setzt Soak-Window fort, aber
Welle-6-Rollback wird parallel triggered. Cross-Modul-Drift-Check
§4.4 wird trotzdem ausgefuehrt — bei drift `> 0` mit Welle-6-
Rollback im Hintergrund: yellow (Mira-Hand-Decision).

---

## §5 Rollback-Trigger — Exit-Decision-Matrix

Fuenf harte Trigger (drei Standard, zwei Welle-7-spezifisch). Bei
JEDEM einzelnen Trigger: sofort §6, keine Diskussion, keine
Eskalations-Verzoegerung. Mira-Hand entscheidet im Cutover-Window
autark, AR-Override nur post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.3) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | Recovery-Service ERR-Zeile | Journal (§4.3) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | Recovery-Drill-Fail (R1..R4-Phase-Excursion) ODER State-Backing-Read-Fail (R2-Phase) | §3.6 + §4.3-Soak-Drill | Eine einzelne R-Phase p99 > Spec-Hard-Cap ODER R2-State-Read-Failure | Rollback (§6) |
| T-4 | Cross-Modul-Inkonsistenz mit subscribe_loop | §4.4 Cross-Modul-Drift | Eine der 3 Achsen `< threshold` | Rollback (§6) + Welle-6-Koordinations-Marker |
| T-5 | Cross-Lang-Hash-Drift | §4.2 Parity-Probe | Jede einzelne Drift in 5 Samples | Rollback (§6) |

**T-3 Begruendung (Welle-7-spezifisch, R-Phase-Excursion + State-Read):**
Recovery-Drill-Fail in einer der vier R-Phasen ist nicht reine
Performance — sie ist Spec-Konformitaet. Eine R2-Reload-Latency
> 15s heisst: State-Backing-Read (Welle-4-Substrate) hat eine
Latenz-Regression, oder Rust-Recovery-Backend kann den State nicht
in der spec'd Zeit lesen. R3-SVID-Refresh > 5s heisst: SPIFFE-SVID-
Refresh ueber Workload-API hat eine Regression (Welle-2-Substrate-
Coupling). Beide Faelle sind blocker-level fuer Engine-Recovery-
Continuity. **State-Backing-Read-Fail** im R2-Path ist ein
zusaetzlicher T-3-Sub-Trigger: wenn der R2-Reload nicht den State
liefert (egal ob Latenz oder Substrate-Failure), ist die Recovery
nicht durchfuehrbar. Rollback ist Pflicht; keine yellow-Toleranz.

**T-4 Begruendung (Doppel-Welle-Cross-Modul, symmetric Welle-6 T-4):**
Cross-Modul-Drift gegen `subscribe_loop` heisst entweder Recovery-
R1-Trigger-Klassifikation-Drift in Subscribe-Loop-Failure-Detect
ODER Subscribe-Loop-Schema-Drift in Drop-Signalisierung. Beide
Faelle sind blocker-level fuer Engine-Resilience-Continuity.
**Welle-6-Koordinations-Marker** wird gesetzt:
`/var/lib/wakir/audit-holds/welle-7-cross-modul-drift-<TS>.marker`
— Welle-6 muss entsprechend mit-rollback'n falls noch nicht stable.

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1 Exit 1).
- Latency p99 > 2.0× Baseline (§4.3 Warn-Schwelle).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  <0.1%).
- Welle-6-Sekundaer-Yellow waehrend Welle-7 OK (§4.5 Cross-Welle-
  Yellow, Mira-Hand-Decision).
- R-Phase-Latency p99 zwischen Spec-Cap/2 und Spec-Cap (z.B.
  R2-p99 zwischen 7.5s und 15s — Rust-Backend operiert in oberer
  Spec-Cap-Haelfte; kein Auto-Rollback, aber Reza-Hand-Forensik-
  Eskalation post-Sign-Off).
- Cross-Backend-Ratio zwischen 1.5× und 2.0× (Rust ist 1.5-2×
  langsamer als Python, aber noch im Spec-Cap).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt, Service-
Restart, Verify Backend=python, Recovery-Drill-Post-Rollback-Verify
gegen Pre-Cutover-Baseline. Welle-1+2+3+4+5+6-State bleibt unberuehrt
— nur das Welle-7-Overlay-File wird entfernt.

**Welle-6-Koordination:** Wenn T-4 Trigger (Cross-Modul-Drift mit
Welle-6): Welle-6-Rollback parallel mit Welle-7-Rollback. Schritt
5 unten beschreibt die Welle-6-Koordinations-Eskalation.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-7 Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-7-cutover.log

# 1. Env-Overlay entfernen — NUR Welle-7-Drop-In, Welle-1..6 bleiben
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-7-recovery-workflow-rust.conf
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet: welle-1-* bis welle-6-* bleiben; welle-7-* weg.
systemctl daemon-reload

# 2. Service-Restart
systemctl restart wakir-persona-engine.service
TS_RB_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 3. Verify backend=python fuer recovery (5 BackendDecision-Records innerhalb 30s)
timeout 30 journalctl -u wakir-persona-engine.service \
    --since "${TS_RB_RESTART}" -f \
    --output=json --no-pager \
  | python3 -c '
import json, sys, time
hits = 0
deadline = time.monotonic() + 30
for line in sys.stdin:
    try:
        rec = json.loads(line)
    except Exception:
        continue
    msg = rec.get("MESSAGE", "")
    if ("BackendDecision" in msg
            and ("component=recovery" in msg or "component=recovery_workflow" in msg)
            and "backend=python" in msg):
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified for recovery")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 4. Recovery-Drill-Post-Rollback-Verify gegen Pre-Cutover-Baseline.
# Python-Backend muss den gleichen Drill ausfuehren koennen und denselben
# Spec-Hard-Cap-Compliance liefern. Drift hier heisst: der Python-Backend
# ist nach Rollback nicht mehr drill-capable — Engine-Recovery-Korruption-
# Verdacht, AR-Hand-Stop-Marker Pflicht.
sleep 10  # Engine-Boot-Stabilisierung
/opt/wakir/bin/wakir-persona-engine-recovery \
    --mode=drill \
    --backend=python \
    --synthetic-trigger=rollback_verify \
    --phases=R1,R2,R3,R4 \
    --output=/var/lib/wakir/welle-7-recovery-baseline/post-rollback-drill-python-${TS_RB}.json

python3 -c '
import json, sys
with open("/var/lib/wakir/welle-7-recovery-baseline/post-rollback-drill-python-'${TS_RB}'.json") as f:
    d = json.load(f)
fail = False
for phase, cap_ms in (("R1",1000),("R2",15000),("R3",5000),("R4",9000)):
    p99 = d["phases"][phase]["latency_histogram_ms"]["p99"]
    if p99 > cap_ms:
        print(f"POST-ROLLBACK-DRILL-EXCURSION: {phase} p99={p99}ms > cap={cap_ms}ms", file=sys.stderr)
        fail = True
sys.exit(1 if fail else 0)
'
if [ $? -ne 0 ]; then
    echo "ROLLBACK-DRILL-CONTINUITY-FAIL: Python-Backend post-rollback ueber Spec-Hard-Cap" >&2
    echo "AR-HAND-STOP-MARKER required" >&2
    mkdir -p /var/lib/wakir/audit-holds
    touch /var/lib/wakir/audit-holds/welle-7-rollback-drill-continuity-violation-${TS_RB}.marker
    exit 3   # exit-3 signalisiert AR-Hand-Stop-Marker, NICHT routine Rollback-Fail
fi

# 5. Welle-6-Koordinations-Pruefung (Doppel-Welle-Coupling).
# Wenn T-4 Trigger (Cross-Modul-Drift): Welle-6-Rollback parallel triggern.
# Wenn nur T-1/T-2/T-3/T-5 Trigger (Welle-7-local): Welle-6 darf in-flight
# bleiben, aber Mira-Hand-Decision-Point ob Welle-6-Sign-Off ohne Welle-7-
# Counterpart sinnvoll (Phase-3c-Marathon-Closure-Implication).
if ls /var/lib/wakir/audit-holds/welle-7-cross-modul-drift-*.marker >/dev/null 2>&1; then
    echo "WELLE-6-COORDINATION-ROLLBACK required (T-4 Cross-Modul-Drift)" \
        | tee -a /var/log/wakir/welle-7-cutover.log
    # Welle-6-Rollback-Trigger: siehe Welle-6-Runbook §6 — Mira-Hand
fi

# 6. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-7 Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-7-cutover.log
echo "PHASE-3c-MARATHON-CLOSURE-DELAYED: Welle-7 in rollback verdict" \
    | tee -a /var/log/wakir/welle-7-cutover.log
```

**Eskalations-Schwelle bei Rollback-Drill-Continuity-Failure (exit-3):**
Wenn Schritt 4 ROLLBACK-DRILL-CONTINUITY-FAIL meldet, ist das **kein**
routine-Rollback-Done sondern eine **AR-Hand-Stop-Marker-Bedingung**:

- Python-Backend kann post-Rollback nicht in Spec-Hard-Caps drillen.
- Recovery-Continuity ist nicht mehr verifizierbar.
- Marker-File `/var/lib/wakir/audit-holds/welle-7-rollback-drill-
  continuity-violation-*.marker` wird gesetzt.
- Eskalation Mira -> Priya -> AR sofort.
- Welle-6 (parallel KW-27) muss auch gestoppt werden bis
  Recovery-Recovery-Decision vorliegt.
- **Phase-3c-Marathon-Schluss-Stempel verzoegert sich.** Bei dieser
  Bedingung ist Marathon-End-Datum nicht ohne AR-Intervention
  bestimmbar.

Nach erfolgreichem Rollback (kein exit-3): 30-min Stabilitaets-
Beobachtung (Welle-1/2-Standard) mit BackendDecision-Aggregator
(§4.1, --target-backend python), Recovery-Error-Monitor (§4.3),
und Cross-Modul-Drift-Check gegen Welle-6 (§4.4 mit aktuellem
Welle-6-Status). Dann §7 Sign-Off mit verdict=`rollback`, Root-
Cause-Analyse binnen 48h pflichtig:

- **Reza** — recovery Rust-CLI-Substrate-Owner, JCS-Canonical-
  Form-Drift-Investigation, R-Phase-Latency-Spec-Compliance-Audit.
- **Tomás** — Cross-Modul-Korrelation mit subscribe_loop +
  Phase-3c-Marathon-Closure-Re-Schedule-Planung.
- **Henrik** — Audit-Trail-Integrity, Recovery-Continuity-Verify,
  Phase-3c-Closure-Audit-Re-Run.

---

## §7 Sign-Off — Henrik-Audit-Trail (PHASE-3c-MARATHON-CLOSURE-SIGN-OFF)

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off ist
**PFLICHT fuer Phase-3c-Marathon-Closure-Flag**. Welle-7-Sign-Off-
Green setzt `phase_3c_complete: true` im Activity-Log. Welle-7-
Sign-Off korreliert mit Welle-6-Sign-Off (Doppel-Welle-Coupling).

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-7-smoke-*.json` (§2 Skript-Output)
- Welle-7-Wednesday-Validation-`cutover-acceptance-decision-welle-
  7.json` (§1, GitHub-Actions-Artifact-URL, mit
  `cross_modul_stress_passed == true`)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-7-pre-
  cutover-*.json` (post-Welle-1+2+3+4+5, pre-Welle-6-Cutover, frisch)
- BackendDecision-Aggregator-Snapshot (§1, Python-Default
  `recovery` ≥99%)
- **Pre-Cutover-Recovery-Drill** (§3.2.5,
  `/var/lib/wakir/welle-7-recovery-baseline/pre-cutover-drill-*.json`
  + SHA-256-Hash + R1..R4-Latency-Histogramme + Spec-Hard-Cap-Pass)
- **R2-State-Backing-Read-Sanity-Output** (§1, p99 < 500ms ueber 12 Samples)
- **R3-SVID-Refresh-Sanity-Output** (§1, p99 < 1000ms ueber 12 Samples)
- Welle-3-5 Sign-Off-Status (§1, Pflicht-Vorbedingung)
- Welle-6-§3.6-Status (§1, Doppel-Welle-Sequenz-Constraint)

**TEL-Evidenz (waehrend §4 15-min Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1, 15-min Window JSON)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 5/5 oder Abweichung)
- Recovery-Error-Count + Latency-Histogramm (§4.3, 0-Zeilen-File +
  3 Grafana-Screenshots + 3 Soak-Drill-Probes
  `welle-7-soak-drill-1/2/3.json` mit R1..R4-Spec-Cap-Pass)
- Cross-Modul-Drift-Check-Output (§4.4,
  `/tmp/welle-7-cross-modul-drift.json`, 3/3 Achsen >= threshold
  Pflicht)
- Welle-6-Cross-Status-Snapshot (§4.5, Welle-6-Cutover-Log-Tail)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-7-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- R1..R4-Drill-Post-Verify-Output (§3.6 Spec-Cap-Pass + Cross-Backend-
  Ratio ≤ 1.5×; bei Rollback §6 Schritt 4 Post-Rollback-Drill-Spec-
  Cap-Pass)
- Bei Rollback: Welle-6-Coordination-Status (parallel-Rollback ja/nein)
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`,
  oder **`ar-hand-stop`** bei exit-3 Drill-Continuity-Violation)
- Welle-6-Sign-Off-Status (Cross-Welle-Korrelation)
- **`phase_3c_complete`-Flag** (`true` nur wenn Welle-7-`green` ODER
  `green-with-yellow-notes` UND Welle-6-Sign-Off ≥ yellow; gesetzt
  durch AR-Hand post-Henrik-Sign-Off)

**Sign-Off-Template (PHASE-3c-MARATHON-CLOSURE-VERSION):**

```yaml
welle: 7
component: recovery_workflow
component_short: recovery
variant: rust
cutover_date: 2026-06-29
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
verdict: green | green-with-yellow-notes | rollback | ar-hand-stop
yellow_notes: []
red_triggers_hit: []
# Welle-7-spezifische Achsen:
recovery_drill_pre_cutover_spec_cap_pass: true | false  # MUSS true fuer green (§3.2.5)
recovery_drill_post_cutover_spec_cap_pass: true | false  # MUSS true fuer green (§3.6 (b))
recovery_drill_cross_backend_ratio_max: <number>  # MUSS <= 1.5 fuer green (§3.6 (c))
r1_p99_ms: <number>  # MUSS <= 1000 fuer green
r2_p99_ms: <number>  # MUSS <= 15000 fuer green
r3_p99_ms: <number>  # MUSS <= 5000 fuer green
r4_p99_ms: <number>  # MUSS <= 9000 fuer green
cross_modul_drift_axes_pass: 3   # MUSS 3 fuer green (recovery x subscribe_loop)
# Cross-Welle-Coupling:
welle_3_signoff_status: green | green-with-yellow-notes | rollback
welle_4_signoff_status: green | green-with-yellow-notes | rollback
welle_5_signoff_status: green | green-with-yellow-notes | rollback
welle_6_signoff_status: green | green-with-yellow-notes | rollback
welle_6_sequence_pre_§3_6_pass: true | false   # Pflicht-Vorbedingung fuer Welle-7-§3
# Phase-3c-Marathon-Closure:
phase_3c_complete: false  # gesetzt durch AR-Hand post-Sign-Off bei verdict ≥ yellow
phase_3c_closure_timestamp_cest: null  # AR-Hand-Setting nach Sign-Off
# Evidenz-Pfade:
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
pre_cutover_drill_sha256: <hash>
soak_drill_1_path: /tmp/welle-7-soak-drill-1.json
soak_drill_2_path: /tmp/welle-7-soak-drill-2.json
soak_drill_3_path: /tmp/welle-7-soak-drill-3.json
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-7-recovery-workflow-signoff-2026-06-29.yaml`

**Phase-3c-Marathon-Closure-Activity-Log-Entry-Template:**

```
## YYYY-MM-DD HH:MM CEST — PHASE-3c-MARATHON-COMPLETE

ADR-0065 Phase-3c Python-Default-zu-Rust-Default-Cutover-Sequenz
abgeschlossen. Alle 9 Persona-Engine-Komponenten laufen auf Rust-
Default (`state_backing` als `rust_inmemory`-Variant, alle anderen
als `rust`). Welle-1 (KW-24 v907_verify) bis Welle-7 (KW-27
recovery_workflow) Sign-Off-Verdict-Aggregat: <green-count>/7
green, <yellow-count>/7 green-with-yellow-notes, 0/7 rollback.

Phase-3c-Marathon-Dauer: ~28 Tage (2026-06-01 Welle-1-Cutover-Day
bis 2026-06-29 Welle-7-Cutover-Day). Phase-3d-Folge-Migrations
(rust_natskv-State-Backing-Variant, OTS-Anchoring-Crate-Migration)
sind separater Phase und nicht Teil dieses Closure.
```

---

## §8 Mira-SSH-Hand-Authority + AR-Hand-Stop-Marker

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-Hand-
Authority fuer Pilot-VM-Operations.

**Mira-Hand-Operations (autark, identisch zu Welle-1-6):**
systemctl restart, Env-Overlay-File-Edits, Journal-Reads, Quadlet-
Override-Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
Recovery-Drill-CLI-Invocation mit synthetic-trigger (read-only,
emittiert keine echten Recovery-Actions, nur Drill-Annotations).

**AR-Hand-Operations (irreversibel-despawn, identisch zu Welle-1-6):**
`podman rm` ohne Backup, Volume-Wipe (`podman volume rm`), System-
Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade, Disk-
Repartitionierung, **`phase_3c_complete: true`-Flag-Setting im
Activity-Log** (AR-Hand-Exclusive, weil Marathon-Closure-Stempel
mit organisationsweiter Bedeutung).

**Welle-7-Neu — AR-Hand-Stop-Marker-Bedingungen:**

Drei Bedingungen triggern automatisch ein Marker-File und
sofortige AR-Eskalation (Mira -> Priya -> AR):

1. **Rollback-Drill-Continuity-Violation** (§6 Schritt 4 exit-3) —
   Python-Backend post-Rollback ueber Spec-Hard-Cap; Recovery-
   Continuity nicht mehr verifizierbar.
2. **T-3 Recovery-Drill-Fail (R1..R4-Phase-Excursion) UND
   State-Backing-Read-Fail** — wenn der R2-Phase-Fail durch eine
   gleichzeitige Welle-4-State-Backing-Substrate-Failure verursacht
   ist (nicht durch Welle-7-Recovery-Crate selbst). Diese
   Kombination signalisiert Welle-4-Regression nach Welle-4-Sign-
   Off — schwerer Cross-Welle-Anomalie.
3. **T-4 Cross-Modul-Drift + Welle-6-Coordination-Fail** — wenn
   Welle-6-Rollback nicht erfolgreich nach Welle-7-T-4-Trigger.

Marker-File-Pfad-Pattern:
`/var/lib/wakir/audit-holds/welle-7-<bedingung>-<TS>.marker`

Bei AR-Hand-Stop-Marker: **Phase-3c-Marathon-Closure-Flag NICHT
gesetzt.** Welle-6 muss parallel gestoppt werden. Henrik-Hand-
Forensik-Pflicht binnen 72h. Phase-3c-Marathon-Schluss-Stempel-
Re-Schedule durch AR-Decision.

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-Kombination):
   Mira-Hand-Decision autark. Henrik-Audit protokolliert.
2. **Substanz-Konflikt** (z.B. R-Phase-Excursion ODER Cross-Lang-
   Hash-Drift): Mira-Hand Rollback nach §6, dann Eskalation Mira
   -> Priya -> Reza (recovery-Rust-Substrate-Owner).
3. **Recovery-Drill-Continuity-Violation (T-3 oder Rollback exit-3)**:
   AR-Hand-Stop-Marker setzen, sofortige Mira -> AR-Eskalation,
   Phase-3c-Marathon-Closure-Verzoegerung dokumentieren.
4. **Cross-Modul-Drift mit Welle-6** (T-4): Welle-6-Koordinations-
   Marker, parallel-Rollback Welle-6+7, danach Eskalation Mira ->
   Priya -> Tomás (Cross-Modul-Korrelations-Owner).
5. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-Drop):
   Mira-Hand Rollback, dann Eskalation Mira -> AR fuer Recovery.
6. **Phase-3c-Marathon-Closure-Stempel-Setting**: AR-Hand-Exclusive
   nach Henrik-Sign-Off-Bestaetigung beider Welle-6+7-Sign-Off-Files.

---

## §9 Bekannte Risiken

**R-1 — Cross-Modul-Drift zu Welle-6 parallel-Cutover (symmetric A7)**
ADR-0066 §KW-27-Final-Doppel-Welle erlaubt Welle-6+7 parallel im
KW-27. Recovery und Subscribe-Loop teilen Detect-Trigger-Semantik
(Subscribe-Loop-Drop ist R1-Klasse `subscribe_loop_failure`). Ein
Schema-Drift in einem der beiden Substrate erscheint als Doppel-
Welle-Symptom, nicht als Single-Modul-Issue. Mitigation: §4.4
Cross-Modul-Drift-Check mit `doppelbetrieb-score-aggregator
--mode=cross-modul-stress` (PR #197) als Pflicht-Step; T-4 Trigger
bei Drift > 0; Welle-6-Koordinations-Marker im Rollback-Pfad.
Sekundaere Mitigation: Doppel-Welle-Sequenz (§3.0) — Welle-7-§3
beginnt **nach** Welle-6-§3.6, nicht parallel. Symmetric-Achse zu
Welle-6-R-1.

**R-2 — State-Backing-Dependency-Drift (Welle-4 schon cutovert)**
R2 Reload liest aus `state_backing` (Welle-4-Substrate). Welle-4
ist seit KW-26 auf `rust_inmemory`. Wenn Welle-4-`rust_inmemory`
einen latenten Read-Path-Bug hat der nur unter Welle-7-Recovery-
Drill-Load triggert: R2-Phase-Excursion (p99 > 15s), T-3 Rollback-
Trigger. Mitigation: §1 R2-State-Backing-Read-Sanity-Pre-Cutover-
Gate (12 Samples, p99 < 500ms); §3.6 Spec-Cap-Check pro R-Phase
einzeln; §4.4 Cross-Modul-Drift `cross-modul-fixture-stability`-
Achse umfasst R2-State-Read-Sanity. Edge-Case: Welle-4-Latency
ist 400ms (passes Pre-Sanity), aber R2-Reload triggert 30 State-
Reads in Serie => kumulativ > 15s. Mitigation: Recovery-Drill-Probe
benutzt realistische State-Read-Tiefe.

**R-3 — SVID-Re-Register-Dependency-Drift (Welle-2 schon cutovert)**
R3 Re-register refresht SPIFFE-SVID via Welle-2-Substrate
(`svid_workload_identity`, seit KW-24 auf Rust). Wenn Welle-2-Rust
einen latenten Latency-Bug hat der nur unter Recovery-Drill-Load
triggert: R3-Phase-Excursion (p99 > 5s), T-3 Rollback-Trigger.
Mitigation: §1 R3-SVID-Refresh-Sanity-Pre-Cutover-Gate (12 Samples,
p99 < 1000ms); §3.6 Spec-Cap-Check pro R-Phase einzeln.

**R-4 — R-Drill-Edge-Cases (synthetic-trigger vs. real-trigger)**
§3.2.5 + §3.6 + §4.3 alle benutzen `synthetic-trigger=*`-Probes,
nicht echte Recovery-Triggers (kein NATS-Disconnect-Inject, kein
State-Backing-Forced-Read-Fail, kein SVID-Expiry-Simulation). Das
ist gut fuer Cutover-Safety (kein echter Recovery-Run im Cutover-
Fenster), aber bedeutet: ein latenter Edge-Case-Bug der nur unter
echtem Failure-Trigger-Druck zum Vorschein kommt, wird durch das
Cutover-Verfahren nicht entdeckt. Mitigation: Welle-7-Wednesday-
Validation-Workflow Step 7 (CI-only, nicht Live-Pilot)
enthaelt Recovery-Drill-mit-realem-Failure-Inject als hermetic-
Test-Pflicht; bei Sign-Off-Yellow-Note "real-trigger-coverage-
limited" wird Henrik-Hand-Forensik 1 Woche post-Sign-Off
durchgefuehrt.

**R-5 — Welle-6-Solo-Vorzieh-Risiko**
Wenn Welle-6-Pre-Conditions yellow ist und Mira-Hand-Decision:
"Welle-6 solo, Welle-7 verschiebt sich um eine Woche": Phase-3c-
Marathon-Schluss-Stempel verschiebt sich auf KW-28+. Mitigation:
Pre-Conditions §1 dokumentiert die drei Welle-6-Coupling-Zustaende
explizit; Mira-Hand-Decision ist protokolliert. **Marathon-End-
Datum-Aenderung wird im Activity-Log mit AR-Hand-Bestaetigung
dokumentiert.**

**R-6 — Welle-3-5-Rollback-Coupling**
Falls eine der Welle-3/4/5 `rollback` ODER `ar-hand-stop` (§1
zulaessiger Zustand (c)): Welle-6+7 (KW-27) sind BLOCKIERT.
Begruendung: Recovery hat dreifache Cross-Welle-Substrate-
Dependency (Welle-2 SVID via R3, Welle-3 Bridge-Audit-Stream via
R-Audit-Annotations, Welle-4 State-Backing via R2-Reload, Welle-5
FSM via R-Phase-State-Snapshot). Jeder Welle-3/4/5-Rollback macht
Welle-7-Cross-Modul-Drift-Check falsch-positiv. AR-Eskalation
Pflicht; Welle-6+7-Re-Scheduling ist AR-Decision.

**R-7 — Phase-3c-Marathon-Schluss-Stempel-Atomic-Setting**
`phase_3c_complete: true` ist ein **organisationsweiter Marathon-
Closure-Stempel**, kein Per-Welle-Verdict. Setting durch AR-Hand-
Exclusive im Activity-Log nach Henrik-Sign-Off-Bestaetigung beider
Welle-6+7. Risiko: Operator setzt Flag versehentlich vor Henrik-
Sign-Off (Race-Condition mit Henrik-Hand-Audit-Window). Mitigation:
Flag-Setting ist AR-Hand-Exclusive, nicht Mira-Hand; Henrik-Sign-
Off-File-Existenz ist Pre-Condition fuer Flag-Setting (Henrik-Hand-
File-Path-Pattern: `agents-workspaces/henrik/audit/welle-7-recovery-
workflow-signoff-2026-06-29.yaml` mit `verdict: green` ODER
`verdict: green-with-yellow-notes`).

**R-8 — Welle-7-Sign-Off-Verzoegerung-Cascading-Effect**
Welle-7-Sign-Off-Day ist Marathon-End-Day. Bei Welle-7-Rollback
ODER `ar-hand-stop`: kein Marathon-End in KW-27. Re-Schedule auf
KW-28 ist Standard (mit Welle-7-Re-Validation Mittwoch KW-27).
Bei Welle-7-`ar-hand-stop` mit Recovery-Continuity-Violation:
**Marathon-End-Datum ist nicht ohne AR-Intervention bestimmbar**
— moeglicherweise mehrere Wochen Re-Forensik. Mitigation:
Phase-3c-Plan-Buffer von 2 Wochen post-2026-06-21 ist ADR-0066-
implizit (Phase-3d-Migration nicht startend vor 2026-07-05).

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, **Montag KW-27 (2026-06-29)**,
**10:00-14:00 CEST Cutover-Window** (4h, identisch zu Welle-6
und symmetric zu Doppel-Welle-Pattern — Welle-6 und Welle-7
teilen sich das Window).

**Konkretes Cutover-Window — Welle-7 (parallel Welle-6, sequenziert nach Welle-6-§3.6):**

| Sub-Phase | Slot CEST |
|---|---|
| Pre-Conditions Walk-Through (Welle-6 + Welle-7 sync) | 10:00-10:20 |
| Pre-Flight-Smoke Welle-7 (§2) + Welle-6-Smoke (parallel) | 10:20-10:30 |
| Pre-Cutover-Recovery-Drill (§3.2.5) Welle-7 (parallel zu Welle-6-§3.2.5+§3.2.7) | 10:30-10:42 |
| Cutover-Step Welle-6 (§3.1-§3.6) | 10:42-11:05 |
| **Welle-7-§3.0-Gate-Check** (Welle-6-§3.6 Subscribe-Resume-OK bestaetigt) | 11:05-11:07 |
| Cutover-Step Welle-7 (§3.1-§3.6 inkl. R1..R4-Drill-Post-Verify) | 11:07-11:25 |
| Soak-Window Welle-6+7 (§4, 15-min, parallel) | 11:25-11:40 |
| Cross-Modul-Drift-Check (§4.4) + 3× Soak-Drill-Probes | 11:40-11:55 |
| Sign-Off-Initial-Draft (§7) Welle-6 + Welle-7 | 11:55-12:35 |
| Reserve — Rollback + Drill-Continuity-Verify (Welle-6 ODER 7 ODER beide) | 12:35-14:00 |
| **Pause + Audit-Trail-Submission an Henrik** | 14:00-15:30 |
| **Henrik-Audit-Sign-Off-Window (Welle-6 + Welle-7 = Phase-3c-MARATHON-CLOSURE)** | 15:30-17:00 |
| **AR-Hand-Phase-3c-Marathon-Closure-Flag-Setting (`phase_3c_complete: true`)** | 17:00+ (post-Henrik) |

**Datum: Montag 2026-06-29 (KW-27) — PHASE-3c-MARATHON-CLOSURE-DAY**

- **Welle-7-Cutover-Vorbereitung-Start:** 10:00 CEST (parallel mit Welle-6)
- **Welle-7-Cutover-§3-Start:** 11:07 CEST (nach Welle-6-§3.6)
- **Welle-7-Latest-Commit-To-Rust:** 11:25 CEST (Boot-Audit-Pass + R1..R4-Drill-Post-Verify)
- **Welle-6+7-Soak-Window-Ende:** 11:40 CEST
- **Welle-6+7-Sign-Off-Window-Ende:** 17:00 CEST
- **Phase-3c-Marathon-Closure-Stempel:** 17:00+ CEST 2026-06-29
  (sobald Welle-7-Sign-Off-Green vorliegt; AR-Hand-Flag-Setting
  bis ~2026-06-30 Dienstag-Morgen)
- **Hairpin-Rollback-Slot:** Mittwoch 2026-07-01, 09:00-13:00 CEST (geteilt mit Welle-6)

**Begruendung Werktag-Vormittag + Doppel-Welle-Sequenz + 4h-Window + Marathon-Closure:**

1. **Doppel-Welle (symmetric Welle-6):** Pre-Conditions Walk-
   Through und Pre-Flight-Smokes sync zwischen Welle-7 und Welle-6
   (Mira-Hand-Owner beider). 4h-Window deckt Welle-6-§3 + Welle-7-
   §3 + gemeinsamer Soak-Window + Reserve fuer parallel-Rollback ab.
2. **Welle-7-Sequenz-Constraint (§3.0):** Welle-7-Cutover startet
   erst nach Welle-6-§3.6 Subscribe-Loop-Resume-Verify. Welle-7-
   Cutover-Window-§3-Start ist daher ~60min nach Cutover-Window-
   Opening.
3. **Pre-Cutover-Recovery-Drill (§3.2.5) parallel zu Welle-6-Pre-Drain:**
   Welle-7-Pre-Drill kann parallel zu Welle-6-§3.2.7 Pre-Drain
   laufen (beide unabhaengig, beide Operator-Hand). Spart 15min.
4. **Cross-Modul-Drift-Check (§4.4) + 3× Soak-Drill-Probes:**
   Pflicht-Step im Soak-Window weil Doppel-Welle-Coupling +
   Welle-7-spezifischer R1..R4-Soak-Drill. Zusaetzliche 15min-Slot
   vor Sign-Off.
5. **Henrik-Sign-Off-Window 15:30-17:00 = Phase-3c-Marathon-Closure:**
   Henrik prueft Welle-6-Sign-Off und Welle-7-Sign-Off als
   korreliertes Paar UND empfiehlt AR-Hand-Setting des
   `phase_3c_complete: true`-Flags wenn beide Sign-Offs ≥ yellow.
6. **AR-Hand-Phase-3c-Closure-Flag-Setting 17:00+:** AR-Hand-
   Exclusive nach Henrik-Sign-Off. Setting im Activity-Log + Mira-
   Hand-Acknowledge-Eintrag. **Marathon-End-Datum-Markierung der
   gesamten Phase-3c-Sequenz.**
7. **Hairpin-Rollback-Slot Mi (KW-27):** Falls Welle-6 ODER 7
   ODER beide yellow-with-Henrik-Hand-Approval-Bedarf — Mittwoch-
   Vormittag (09:00-13:00, 4h-Window, geteilt) ist der naechste
   sinnvolle Slot.
8. **Phase-3c-Marathon-End ~2026-06-21:** Plan-Anker per ADR-0066.
   Konkret Welle-7-Cutover-Day ist 2026-06-29 (KW-27 Montag), der
   ADR-0066-Plan-Anker bezieht sich auf den Schluss-Stempel ohne
   AR-Hand-Tag-Verzoegerung. Real-Closure-Datum: 2026-06-29
   17:00+ CEST (Henrik-Sign-Off) plus AR-Hand-Flag bis ~2026-06-30
   Morgen.

**Verbotene Cutover-Slots:**

- Freitag-Nachmittag (Wochenend-Rollback-Risiko).
- Mittwoch-Mittag (kollidiert mit Wednesday-Validation-Run-Re-Run-
  Option).
- Sonntag/Feiertag (kein Engineering-Standby).
- Parallel zu Welle-4+5-Cutover-Step (KW-26, siehe §9 R-6).
- KW-27-Mittwoch-Cutover-Slot (Mittwoch ist Hairpin-Rollback-Slot,
  nicht Cutover-Slot).
- **Welle-7-§3 BEFORE Welle-6-§3.6 — strikt verboten (§3.0
  Sequenz-Constraint).**

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Reza (recovery-Rust-Substrate-Owner) | bei JCS-Canonical-Drift, R-Phase-Latency-Spec-Compliance-Drift, R-Drill-Continuity-Failure |
| 3 | Tomás (Matrix-Lead) | bei Welle-6/7-Cross-Modul-Korrelation, Doppel-Welle-Coupling-Konflikt, Phase-3c-Marathon-Closure-Re-Schedule-Planung |
| 4 | Henrik (Internal Audit) | bei Audit-Trail-Anomaly, T-3 oder T-4 Trigger, Drill-Spec-Cap-Audit, **Phase-3c-Marathon-Closure-Sign-Off** |
| 5 | AR (Fred) | bei AR-Hand-Stop-Marker, Rollback-Drill-Continuity-Violation (§6 exit-3), Welle-3-5-Rollback-Coupling-Block, Phase-3c-Sequenz-Re-Sequencing, **`phase_3c_complete: true`-Flag-Setting**, **Marathon-End-Datum-Anpassung** |

---

## Anhang B — Cross-Welle-Coordination-Checkliste (KW-27 Doppel-Welle 6+7 — MARATHON-CLOSURE)

Vor Welle-7-Cutover-Start: explizite Verifikation aller Welle-1-6-
Coordination-Items und der Welle-6-Sequenz-Coupling. **Dies ist
die finale Coordination-Checkliste der Phase-3c-Marathon-Sequenz —
Phase-3c-Schluss-Stempel ist nur eine Sign-Off-Welle weiter.**

- [ ] Welle-1-Runbook gelesen ([`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md), PR #228 Tag-34)
- [ ] Welle-2-Runbook gelesen ([`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md), PR #232 Tag-35)
- [ ] Welle-3-Runbook gelesen ([`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md), PR #237 Tag-36)
- [ ] Welle-4-Runbook gelesen ([`welle-4-state-backing-runbook.md`](./welle-4-state-backing-runbook.md), PR #243 Tag-37)
- [ ] Welle-5-Runbook gelesen ([`welle-5-lifecycle-state-machine-runbook.md`](./welle-5-lifecycle-state-machine-runbook.md), PR #247 Tag-38)
- [ ] Welle-6-Runbook gelesen ([`welle-6-subscribe-loop-runbook.md`](./welle-6-subscribe-loop-runbook.md), gleicher Bundle-PR Tag-39, paralleler Doppel-Welle-Partner)
- [ ] Welle-1-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`)
- [ ] Welle-2-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`)
- [ ] Welle-3-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`/`ar-hand-stop`)
- [ ] Welle-4-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`/`ar-hand-stop`)
- [ ] Welle-5-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`/`ar-hand-stop`)
- [ ] Bei Welle-3/4/5 `rollback` ODER `ar-hand-stop`: Welle-6+7 BLOCKIERT (AR-Eskalation, §9 R-6)
- [ ] Welle-1-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-1-v907-verify-rust.conf`
- [ ] Welle-2-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-2-svid-workload-identity-rust.conf`
- [ ] Welle-3-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-3-bridge-audit-writer-rust.conf`
- [ ] Welle-4-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-4-state-backing-rust.conf`
- [ ] Welle-5-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-5-lifecycle-state-machine-rust.conf`
- [ ] **Welle-6-§3.6 Sequenz-Gate verifiziert** (Subscribe-Loop-Resume-OK
      im Welle-6-Cutover-Log) BEVOR Welle-7-§3.1 SSH-Login startet
- [ ] Welle-6-Drop-In-File auf Pilot-VM vorhanden NACH Welle-6-§3.6:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-6-subscribe-loop-rust.conf`
- [ ] Welle-1-`v907_verify` `backend=rust` im Aggregator >99%
- [ ] Welle-2-`svid_workload_identity` `backend=rust` im Aggregator >99%
- [ ] Welle-3-`anchor_emitter` `backend=rust` im Aggregator >99%
- [ ] Welle-4-`state_backing` `backend=rust_inmemory` im Aggregator >99%
- [ ] Welle-5-`fsm` `backend=rust` im Aggregator >99%
- [ ] Welle-6-`subscribe_loop` `backend=rust` im Aggregator >99% NACH Welle-6-§3.6
- [ ] Welle-7-Engine-Health-Baseline frisch aufgezeichnet POST-Welle-1+2+3+4+5
- [ ] Welle-7-spezifischer Pre-Cutover-Recovery-Drill vorhanden (§3.2.5, SHA-256-Hash + R1..R4-Latency-Histogramme + Spec-Hard-Cap-Pass)
- [ ] **R2-State-Backing-Read-Sanity Pre-Gate gruen** (p99 < 500ms, 12 Samples)
- [ ] **R3-SVID-Refresh-Sanity Pre-Gate gruen** (p99 < 1000ms, 12 Samples)
- [ ] Welle-6-§3.6-Resume-OK dokumentiert (§3.0 Sequenz-Constraint)
- [ ] Doppel-Welle-Sequenz §3.0 verstanden (Welle-6-§3.6 vor Welle-7-§3.1)
- [ ] Cross-Modul-Stress-Test Wednesday-Run gruen (Pflicht aus ADR-0066 §Mitigations, symmetric A7)
- [ ] **Phase-3c-Marathon-Closure-Bewusstsein:** Welle-7-Sign-Off-Green-Tag setzt `phase_3c_complete: true`; Welle-7-Sign-Off ist der **Schluss-Stempel** der gesamten Phase-3c-Sequenz.
- [ ] **AR-Hand-Bereitschaft-Bestaetigung:** AR ist verfuegbar fuer Flag-Setting nach Henrik-Sign-Off im Cutover-Window-Nachmittag (17:00+ CEST).

---

## Anhang C — Welle-7-spezifische Cross-Spawn-Coordination (Tag-39)

Tag-39 hat parallele Spawns laufen lassen (Continuous-Mode, KW-27
Final-Doppel-Welle-Vorbereitung):

| Spawn | Owner | Artefakt | Pfad |
|---|---|---|---|
| Welle-7-Operator-Runbook (dieses Dokument) | Kai | `docs/phase-3c/welle-7-recovery-workflow-runbook.md` | dieses File |
| Welle-7-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh` | Pfad in §2 zitiert (parallel Tag-39) |
| Welle-6-Operator-Runbook (Bundle-Partner) | Kai | `docs/phase-3c/welle-6-subscribe-loop-runbook.md` | gleicher Bundle-PR Tag-39 |
| Welle-6-Cutover-Smoke-Skript (Bundle-Partner) | Selin | `scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh` | Selin parallel Tag-39 |
| Tomás-Tag-39-Workflow-Adjustment (Welle-6+7) | Tomás | CI-Workflow-Validation | siehe Tomás-Tag-39-Liefer-Bericht |
| Reza-Tag-39-Substrate (Welle-6+7 Substanz, ADR-0068-Migration) | Reza | Substanz-Coverage-Spawn | siehe Reza-Tag-39-Liefer-Bericht |
| Amara-Tag-39-Doppel-Welle-Closure-E2E | Amara | E2E-Closure-Acceptance-Suite | siehe Amara-Tag-39-Liefer-Bericht |
| Henrik-Tag-39-Marathon-Closure-Audit-Prep | Henrik | Audit-Trail-Pre-Closure-Review | siehe Henrik-Tag-39-Liefer-Bericht |

Pre-Cutover-Cross-Spawn-Verifikation (in §1 implizit, hier
explizit gelistet): alle Tag-37+38+39-Artefakte muessen auf main
gemerged sein vor Welle-7-Wednesday-Validation-Run-Trigger
(KW-26-Mittwoch 2026-06-24).

---

## Anhang D — Symmetric-Coordination-Stub zu Welle-6

Welle-6 und Welle-7 sind im KW-27 Doppel-Welle-Pattern symmetric
gekoppelt — analog Welle-4/5-Doppel-Welle. Diese Anhang dokumentiert
die Symmetrie explizit zur Operator-Hand-Hygiene.

| Achse | Welle-6 (subscribe_loop) | Welle-7 (recovery_workflow) |
|---|---|---|
| Env-Var | `WAKIR_SUBSCRIBE_LOOP_BACKEND` | `WAKIR_RECOVERY_BACKEND` |
| Cutover-Wert | `rust` (Single-Variant) | `rust` (Single-Variant) |
| Sequenz-Position | zuerst (§3.0) | folgt nach Welle-6-§3.6 (§3.0) |
| Component-Short | `subscribe_loop` (no-alias) | `recovery` (Long-form alias `recovery_workflow`) |
| Cross-Lang-Fixtures | `tests/fixtures/subscribe-loop-cross-lang/fixtures.json` | `tests/fixtures/recovery-workflow-cross-lang/fixtures.json` |
| Quadlet-Binary | `wakir-persona-engine-subscribe-loop` | `wakir-persona-engine-recovery` |
| Mini-Welle-Carrier | `subscribe-loop-welle6` (Tag-33) | `recovery-welle7` (Tag-33) |
| §3.2.5 Pre-Verify | Subscribe-Cursor-Snapshot-Hash | R1..R4-Drill-Pre-Snapshot (Latency-Histogramm-Set) |
| §3.2.7 Pre-Step (Welle-6-only) | Pre-Drain (in_flight==0 innerhalb 60s) | (keine analoge Pflicht — Recovery hat Drill-Pre-Snapshot in §3.2.5 als Aequivalent) |
| §3.6 Post-Verify | Subscribe-Loop-Resume-Verify | R1..R4-Drill-Post-Verify (Spec-Cap + Cross-Backend-Ratio) |
| T-3 Trigger | Lag>90s ODER Output-Reply-p99>45s ODER Drain-Hang | R-Phase-Excursion (R1/R2/R3/R4 > Spec-Cap) ODER State-Backing-Read-Fail (R2-Sub) |
| T-4 Trigger Paired-Component | `recovery` | `subscribe_loop` |
| Cross-Modul-§4.4 Target | subscribe_loop × recovery | recovery × subscribe_loop (symmetric) |
| AR-Hand-Stop-Bedingungen | 3 (Cursor-Regression, Drain-Abort, T-4 + Cross-Welle-Coordination-Fail) | 3 (Drill-Continuity-Violation, T-3+State-Backing-Combined, T-4 + Cross-Welle-Coordination-Fail) |
| Phase-3c-Marathon-Schluss-Stempel | blockiert ihn bei Rollback | **setzt ihn** bei Sign-Off-Green |

**Doppel-Welle-Cross-Spawn-Pflicht:** Welle-6 und Welle-7 muessen
gemeinsam Sign-Off (mind. yellow) erreichen, damit der Phase-3c-
Marathon-Closure-Flag (`phase_3c_complete: true`) gesetzt werden
kann. Ein einseitiger green-Sign-Off (z.B. Welle-6 green, Welle-7
rollback) blockiert den Marathon-Schluss-Stempel.

**Phase-3c-Marathon-Schluss-Stempel (Plan):** Montag 2026-06-29
17:00+ CEST nach Henrik-Sign-Off und AR-Hand-Flag-Setting. Bei
Welle-6 ODER Welle-7-Rollback verschiebt sich das auf KW-28
(~2026-07-06 Montag, Re-Schedule durch AR). **ADR-0066-Plan-Anker
fuer Phase-3c-Ende:** ~2026-06-21 als Zielwert; Real-Closure-Day
ist Welle-7-Cutover-Day mit Henrik-Sign-Off-Window.

---

## Anhang E — Phase-3c-Marathon-Closure-Checklist (PHASE-CLOSURE-SPECIFIC)

Diese Checkliste wird nach Welle-7-Sign-Off durch Mira-Hand
bearbeitet und ist Voraussetzung fuer AR-Hand-Flag-Setting.

- [ ] Welle-7-Sign-Off-File existiert: `agents-workspaces/henrik/audit/welle-7-recovery-workflow-signoff-2026-06-29.yaml`
- [ ] Welle-7-Sign-Off-Verdict ist `green` ODER `green-with-yellow-notes` (kein `rollback`/`ar-hand-stop`)
- [ ] Welle-6-Sign-Off-File existiert: `agents-workspaces/henrik/audit/welle-6-subscribe-loop-signoff-2026-06-29.yaml`
- [ ] Welle-6-Sign-Off-Verdict ist `green` ODER `green-with-yellow-notes` (kein `rollback`/`ar-hand-stop`)
- [ ] Welle-1-5-Sign-Off-Files alle existieren mit ≥ yellow Verdict
- [ ] Welle-7-Pilot-VM Drop-In-File deployed: `welle-7-recovery-workflow-rust.conf`
- [ ] Welle-7-BackendDecision-Aggregator-Run-Output ≥ 99% rust
- [ ] **Cross-Welle-Aggregat-Probe**: alle 9 Persona-Engine-Backends
      operieren auf Rust (bzw. rust_inmemory fuer state_backing).
      `scripts/phase-3c/all-9-backends-rust-aggregator.py --window
      30m --pilot 192.168.178.116 --json-out /tmp/phase-3c-closure-
      aggregate.json` liefert `all_rust: true` ueber 30min-Window.
- [ ] **Henrik-Phase-3c-Closure-Audit-Sign-Off**: Henrik-Hand-File
      `agents-workspaces/henrik/audit/phase-3c-closure-audit-2026-06-29.yaml`
      existiert mit `closure_audit_verdict: green`.
- [ ] **Activity-Log-Entry-Draft vorbereitet** (Anhang B oben mit
      Phase-3c-Marathon-Complete-Block-Template).
- [ ] AR-Hand-Verfuegbarkeit bestaetigt fuer Flag-Setting (Mira-Hand-
      Ping an AR vor 17:00 CEST).

Nach AR-Hand-Flag-Setting im Activity-Log:

- [ ] `phase_3c_complete: true` im Welle-7-Sign-Off-File aktualisiert.
- [ ] Mira-Hand-Acknowledge-Eintrag im Activity-Log (Mira-Hand-
      Bestaetigung dass Flag-Setting bemerkt wurde).
- [ ] Henrik-Audit-Trail final-Sign-Off-File.
- [ ] **Cross-Org-Communication-Stempel:** Mira-Hand-Notify an alle
      Engineering-Agents (Tomás, Reza, Selin, Amara, Henrik) ueber
      Phase-3c-Marathon-Closure (Channel: Activity-Log-Verweis,
      kein ntfy-Push wegen Vertraulichkeits-Direktive).

---

— Kai Hoffmann (DevOps), Sprint-Tag-39, 2026-05-18.
