---
title: "Phase-3c Welle-6 subscribe_loop Operator-Cutover-Runbook"
owner: "Kai Hoffmann (DevOps), Tomas Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065, 0066"
welle: 6
component: "subscribe_loop"
env_var: "WAKIR_SUBSCRIBE_LOOP_BACKEND"
env_value_cutover: "rust"
cutover_date: "2026-06-29"
cutover_window_cest: "10:00-14:00"
soak_window_minutes: 15
hairpin_rollback_window_cest: "Mi 09:00-13:00"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 39
parallel_welle: 7
parallel_welle_component: "recovery_workflow"
parallel_welle_env_var: "WAKIR_RECOVERY_BACKEND"
risk_class: "doppel-welle-cross-modul-drift + subscribe-loop-drain-coupling"
phase_marathon_end: "2026-06-21 (Phase-3c Cutover-Complete bei Welle-7-Sign-Off)"
---

# Phase-3c Welle-6 subscribe_loop Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-6-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die `subscribe_loop`-
Komponente der Persona-Engine, 7. emittierte `BackendDecision`).
Ziel-Cutover-Datum: Montag 2026-06-29, KW-27, **parallel** zu
Welle-7 (`recovery_workflow`) gemaess ADR-0066 §KW-27-Final-Doppel-
Welle. **Welle-7-Sign-Off-Green schliesst den Phase-3c-Marathon
ab — geplantes Ende ~2026-06-21 nach AR-Approval-Tag** (Phase-3-
Cutover COMPLETE).

Dies ist das **operative Day-Of-Skript**. Hermetic-Validierung
(`phase-3c-welle-6-validation.yml`) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-6-runbook.md`](../operations/phase-3c-welle-6-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM, echter
NATS-Bus, echte Quadlet-Restart-Sequenz, echte Subscribe-Loop-
NATS-Connection-Persistence-Beobachtung.

Schwester-Runbook fuer Welle-7 (parallel-Cutover-Coordination):
- [`welle-7-recovery-workflow-runbook.md`](./welle-7-recovery-workflow-runbook.md)
  (paralleler Tag-39-Spawn, dieser Bundle-PR).

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

## Welle-6-Charakter (subscribe_loop-spezifisch)

**Welle-6 ist die erste Welle in der die zu cutover'nde Komponente
einen persistenten NATS-Subscription-Stream haelt.** Vorgaenger-
Wellen sind alle entweder Verify-Computation (v907_verify),
Identity-Resolution (svid), Sink-Pfad (bridge_audit_writer),
Read-Write-State-Substrate (state_backing) oder Transition-FSM
(lifecycle_state_machine). Subscribe-Loop dagegen ist Ingress-
Substrate: eine NATS-Subscription pro Inbox-Subject, mit Per-Frame-
Ack-Records (`subscribe_ack` sibling-module, PR #172) und einer
laufenden In-Flight-Message-Liste. Ein Restart ohne Pre-Drain
verliert in-flight Frames — Subscribe-Loop ist die erste Welle, bei
der der Cutover-Step einen **Pre-Drain-Step** als Pflicht-Phase
hat.

**Drei subscribe_loop-spezifische Charakteristika:**

1. **Single-Value-Variant (`rust`, identisch zu Welle-3/5)** — der
   Resolver `resolve_subscribe_loop_backend` akzeptiert nur die
   Standard-Werte aus `VALID_SUBSCRIBE_LOOP_BACKEND_VALUES`
   (`python` ODER `rust`). Welle-6-Env-Overlay setzt
   `WAKIR_SUBSCRIBE_LOOP_BACKEND=rust` (siehe
   `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE`
   Zeile 203).
2. **Pre-Drain-Pflicht-Phase (§3.2.7)** — vor dem Engine-Restart
   muessen in-flight Subscribe-Loop-Frames vollstaendig abgearbeitet
   sein. Subscribe-Loop ist ein **stateful Ingress-Substrate**:
   ein laufender Subscription-Cursor plus N in-flight Frames die
   noch nicht ack'd sind. Ein Restart ohne Pre-Drain produziert
   entweder doppelte Frame-Acks (NATS redelivers) oder verlorene
   Frames (NATS dropped pending acks im max-redeliveries-Modus).
   Pre-Drain wartet bis `in_flight_count == 0` ODER ein 60s-Hard-
   Cap erreicht ist (siehe §3.2.7 Detail-Implementation).
3. **Cross-Modul-Drift zu Welle-7 (recovery_workflow, parallel)**
   — Subscribe-Loop ist der **Detect-Trigger-Substrate** fuer
   R1-Recovery-Phase: wenn der Subscribe-Loop einen NATS-Connection-
   Drop bemerkt, ist das einer der drei R1-Trigger-Klassen
   (`subscribe_loop_failure`-Flag, siehe `recovery_workflow.py`
   §3.7.4.5). Wenn beide Welle-6+7 parallel cutover: ein Schema-
   Drift in einer der beiden Komponenten emergiert als Doppel-
   Welle-Symptom, nicht als Single-Modul-Issue. Mitigation: Cross-
   Modul-Stress-Test als §4.4 Soak-Step (Phase-2-Acceptance-Gate
   Step 6 aus PR #197), 3-Achsen-Schwelle subscribe_loop x
   recovery.

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ + KW-27-Final-Doppel-Welle | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Welle-6 Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-6-validation.yml` |
| Welle-6 Sibling-Validation-Runbook | `docs/operations/phase-3c-welle-6-runbook.md` |
| Welle-1 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-1-v907-verify-runbook.md` (PR #228, Tag-34) |
| Welle-2 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-2-svid-workload-identity-runbook.md` (PR #232, Tag-35) |
| Welle-3 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-3-bridge-audit-writer-runbook.md` (PR #237, Tag-36) |
| Welle-4 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-4-state-backing-runbook.md` (PR #243, Tag-37) |
| Welle-5 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-5-lifecycle-state-machine-runbook.md` (PR #247, Tag-38) |
| Welle-7 Pre-Cutover-Operator-Runbook (paralleler Partner) | `docs/phase-3c/welle-7-recovery-workflow-runbook.md` (gleicher Bundle-PR Tag-39) |
| Subscribe-Loop Container-Image-Build-Pipeline | PR #167 (Tag-17) + Tag-33 Mini-Welle `subscribe-loop-welle6` Quadlet-Carrier-Update |
| Subscribe-Loop Cross-Lang-Hash-Parity-Pins | `tests/fixtures/subscribe-loop-cross-lang/fixtures.json` |
| Resolver `resolve_subscribe_loop_backend` | `wirelang/persona_engine/rust_backend_switch.py` (`SUBSCRIBE_LOOP_BACKEND_ENV` L431, `DEFAULT_RUST_SUBSCRIBE_LOOP_BIN` L455) |
| Resolver-Variant-Map | `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE` (subscribe_loop -> rust) |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Cross-Modul-Stress-Aggregator (Doppel-Welle-Pflicht) | `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress` (PR #197) |
| Quadlet-Inventar (9-Binary) | `quadlet/wakir-rust-cli.container` (`wakir-persona-engine-subscribe-loop` in Exec-Schleife) |
| Cosign-Policy (9-Binary) | `policies/cosign-policy-phase-3b.yaml` `name: subscribe-loop` |
| Selin Welle-6 Cutover-Smoke-Skript | `scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh` (Selin Tag-39, paralleler Cross-Spawn) |
| Subscribe-Loop Python-Sibling | `wirelang/persona_engine/subscribe_ack.py` (PR #172) |
| Recovery-Workflow Python-Modul (Welle-7-Cross-Modul-Anker) | `wirelang/persona_engine/recovery_workflow.py` |
| Welle-6-Telemetry-Runbook | `docs/operations/welle-6-telemetry-runbook.md` (falls vorhanden — sonst Welle-5-Telemetry-Runbook als Cross-Anker) |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya.

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar 9-Binary)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `subscribe-loop` mit
      `in_image_path: /opt/wakir/bin/wakir-persona-engine-subscribe-loop`.
      Tag-33 Mini-Welle ergaenzt einen `subscribe-loop-welle6`-Variant-
      Eintrag mit demselben Crate-Pfad.
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 9 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` listet
      `wakir-persona-engine-subscribe-loop` in der `Exec=`-Schleife
      des Installer-Containers. Tag-33 Mini-Welle ergaenzt
      `wakir-persona-engine-subscribe-loop-welle6`-Variant-Pin
      (Carrier-Image-Verifikation via `sha256sum-checks`-Probe).
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence: `wirelang/persona_engine/rust_backend_switch.py`
      enthaelt `SUBSCRIBE_LOOP_BACKEND_ENV =
      "WAKIR_SUBSCRIBE_LOOP_BACKEND"` (L431) und
      `DEFAULT_RUST_SUBSCRIBE_LOOP_BIN ==
      /opt/wakir/bin/wakir-persona-engine-subscribe-loop` (L455).
      Resolver akzeptiert nur Standard-Werte `python` ODER `rust`
      (siehe `VALID_SUBSCRIBE_LOOP_BACKEND_VALUES` L636).
      Engine-Boot-Audit emittiert 7. `BackendDecision` mit
      `component=subscribe_loop`.
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet, GitHub-Runner-Baseline-File nicht).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — gruen. Evidence:
      `tests/integration/test_bridge_audit_roundtrip_e2e.py` passt
      (oder all-SKIP auf Runner ohne replay_cli-Binary). Subscribe-
      Loop-Ack-Record-Audit-Annotation wird emittiert.
- [ ] **Welle-6-Wednesday-Validation-Run gruen** (2026-06-24
      06:00 UTC, KW-26 Mittwoch — 5 Tage vor Cutover-Montag KW-27).
      Evidence: `cutover-acceptance-decision-welle-6.json`
      `ready_for_live_smoke == true` UND `cross_modul_stress_passed
      == true` (Step 6 PR #197). Artifact-Retention 30 Tage.
      Workflow: `.github/workflows/phase-3c-welle-6-validation.yml`.
- [ ] **Welle-3-5 Sign-Off-Verdicte alle bekannt** (Pflicht-
      Vorbedingung fuer KW-27-Final-Doppel-Welle):
      - **Welle-3** `green` ODER `green-with-yellow-notes-mit-
        Henrik-Hand-Approval` (KW-25 Montag).
      - **Welle-4** `green` ODER `green-with-yellow-notes` (KW-26
        Montag, Doppel-Welle-Partner Welle-5).
      - **Welle-5** `green` ODER `green-with-yellow-notes` (KW-26
        Montag, Doppel-Welle-Partner Welle-4).
      Drei zulaessige Zustaende fuer Welle-6-Trigger:
      - **(a) Alle drei `green`** — Welle-6 startet planmaessig KW-27 Montag.
      - **(b) Mindestens eine `green-with-yellow-notes` + Henrik-Hand-Approval-File** —
        Welle-6 startet, aber Mira-Hand-Decision-Point mit
        explizitem Yellow-Notes-Review im Cutover-Window.
      - **(c) Jede Welle in `rollback` ODER `ar-hand-stop`** —
        Welle-6+7 wird BLOCKIERT, nicht gestartet. AR-Eskalation
        Pflicht (§9 R-6). Begruendung: Phase-3c-Marathon-Schluss-
        Stempel braucht 5/5-stabile-Vorgaenger-Substrate.
- [ ] **Welle-7-Pre-Conditions-Status verifiziert** (Welle-7 ist
      parallel-laufend KW-27 Montag, symmetric A7). Drei zulaessige
      Zustaende fuer Welle-6-Trigger relativ zu Welle-7:
      - **(a) Welle-7-Pre-Conditions gruen** — Welle-6+7 starten gemeinsam.
      - **(b) Welle-7-Pre-Conditions yellow** — Mira-Hand-Decision
        ob Welle-6 solo-vorzieht oder mit Welle-7 wartet
        (Doppel-Welle-Coupling — Recovery-Drill-Pflicht steht
        sonst noch).
      - **(c) Welle-7-Pre-Conditions red** — Welle-6 starten ohne
        Welle-7 ist **nicht** zulaessig (Cross-Modul-Stress-Test
        kann nicht ausgefuehrt werden ohne Recovery-Substrate-
        Doppelbetrieb). Welle-6 verschiebt sich auf KW-28 (mit
        Welle-7-Re-Schedule). **Phase-3c-Marathon-End verschiebt
        sich entsprechend.**
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, **post-Welle-1+2+3+4+5 Engine-Posture**). Latency-
      p50/p95, Error-Rate, BackendDecision-Volume pro Minute,
      Subscribe-Loop-In-Flight-Frame-Count, Subscribe-Loop-Ack-
      Record-Rate, NATS-Connection-Up-Time-Counter. Persistiert in
      `/var/lib/wakir/baselines/welle-6-pre-cutover-<TS>.json`.
      **Wichtig:** Die Baseline wird **nach KW-24+25+26-Sign-Off
      und vor KW-27-Welle-6+7-Cutover** frisch aufgezeichnet —
      die Engine hat 5 von 9 Backends bereits auf Rust geflippt;
      eine Pre-Welle-1-Baseline ist nicht uebertragbar.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component subscribe_loop --window 5m --format json` liefert
      gueltige Records mit `backend=python` >99% (Baseline).
- [ ] **Quadlet 9-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 9 Binaries inklusive
      `wakir-persona-engine-subscribe-loop`.
- [ ] **Cosign-Policy 9-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit.
      Das transitiv-verifizierte Image-Manifest umfasst subscribe-
      loop-Image (sowohl Tag-17-Origin `subscribe-loop` als auch
      Tag-33-Variant `subscribe-loop-welle6`).
- [ ] **Subscribe-Loop Cross-Lang-Hash-Parity-Pins frisch**.
      Evidence: `tests/fixtures/subscribe-loop-cross-lang/
      fixtures.json` existiert, Pin-Count ≥ 5 (Per-Frame-Ack-
      Record-Fixtures). Das ist die Baseline-Referenz fuer §4.2
      Cross-Lang-Hash-Parity-Probe.
- [ ] **Cross-Modul-Stress-Test Wednesday-Run gruen** (Doppel-Welle-
      Pflicht aus ADR-0066 §Mitigations, symmetric zu Welle-4/5).
      Evidence: Welle-6-Validation-Workflow Step 6
      (`doppelbetrieb-score-aggregator --mode=cross-modul-stress`)
      hat alle 3 Achsen `>= threshold`:
      - `cross-lang-pin-coverage` (subscribe_loop x recovery_workflow)
      - `cross-modul-fixture-stability` (Subscribe-Drop -> R1-Trigger-Sanity)
      - `cross-modul-rollup-integrity` (Welle-6+7-Aggregate-Health)
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt** —
      Mittwoch KW-27, 09:00-13:00 CEST (4h-Slot, identisch zu
      Welle-4/5 wegen Doppel-Welle-Cross-Modul-Drift-Koordination).
      **Welle-6+7 teilen sich denselben Rollback-Slot** —
      parallel-Rollback ist explizit erwartet bei T-4 Cross-Modul-
      Trigger.
- [ ] **NATS-JetStream-Konnektivitaet stabil 24h pre-Cutover** —
      Pflicht-Vorbedingung wegen Subscribe-Loop-Connection-Persistenz
      (siehe §9 R-2). Evidence: `nats stream info` plus `nats
      consumer info` ueber 24h-Sample, kein Connection-Drop in
      Engine-Journal `journalctl -u wakir-persona-engine.service
      --since "-24h" | grep -c 'NATS connection lost'` == 0.

---

## §2 Pre-Flight-Smoke

Selin's Welle-6-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet zur
Pilot-VM testet und kein Pilot-internes Artefakt ist. Skript
liefert Selin **parallel zu diesem Runbook** (Tag-39 Cross-Spawn).

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component subscribe_loop \
    --env-var WAKIR_SUBSCRIBE_LOOP_BACKEND \
    --env-value rust \
    --parallel-welle 7 \
    --cross-modul-stress-axis subscribe_loop,recovery \
    --dry-run-window 5m \
    --json-out /tmp/welle-6-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated ODER Welle-3-5 `green-with-yellow-notes` post-hoc).
  Mira-Hand-Decision noetig vor §3.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Tomás (Matrix-Lead). **Bei red: kein Cutover-
  Versuch ohne Henrik-Hand-Override.**

Das JSON-Envelope (`/tmp/welle-6-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~3-5 min wall-clock (laenger als Welle-1/2
wegen Cross-Modul-Stress-Axis-Sample und Subscribe-Loop-In-Flight-
Frame-Probe). Skript prueft SSH-Reachability, Quadlet-Status-
Snapshot, Cosign-Policy-Match (9-Binary), Engine-Health-Baseline-
Delta gegen Tag-N-1, Subscribe-Loop-In-Flight-Frame-Count-Sanity
(`< 100` als Pre-Cutover-Gesundheits-Indikator), BackendDecision-
Aggregator-Sanity fuer `component=subscribe_loop`, Cross-Modul-
Stress-Smoke (subscribe_loop × recovery 3-Axen-Sample). Keine
Side-Effects auf Pilot-VM (read-only).

**Welle-6+7-Parallel-Hinweis:** Welle-6 und Welle-7 starten am
selben Cutover-Tag KW-27 Montag. Pre-Flight-Smokes Welle-6 und
Welle-7 duerfen parallel laufen, **aber** §3 Cutover-Step Welle-6
+ §3 Cutover-Step Welle-7 sind seriell-koordiniert (siehe §3.0
Doppel-Welle-Sequenz, Welle-6 zuerst). Begruendung: Subscribe-
Loop-Drop ist einer der drei R1-Detect-Trigger im
Recovery-Workflow — wenn beide gleichzeitig flippen, kann eine
echte Subscribe-Drop-Detect-Race mit dem Welle-7-Engine-Restart
nicht von einem Welle-6-Boot-Failure unterschieden werden.

---

## §3 Cutover-Step

**Mira-Hand-SSH-Authority** gemaess ADR-0058 §Nachtrag. AR-
Eskalations-Override nur fuer `irreversible despawn`-Pfade —
Quadlet-Restart und Env-Overlay fallen darunter **nicht**, das
ist routine Operator-Hand-Operation.

**Welle-6-spezifische Erweiterung:** §3.2.7 Subscribe-Loop-Pre-
Drain (vor Engine-Restart in-flight Subscribe-Loop-Frames
abarbeiten lassen, bis `in_flight_count == 0` ODER 60s-Hard-Cap)
plus §3.6 Subscribe-Loop-Resume-Verify (nach Restart: Subscribe-
Loop-Subscription ist wieder aktiv, In-Flight-Frame-Count beginnt
bei 0, Per-Frame-Ack-Rate ist erkennbar > 0 nach 30s).

**Schritt 3.0 — Doppel-Welle-Sequenz (Welle-6 zuerst, Welle-7 folgt)**

Welle-6-Cutover beginnt **zuerst**, Welle-7-Cutover folgt nach
Welle-6-Boot-Audit-Pass (§3.5 hits >= 5 fuer `subscribe_loop`).
Begruendung: Subscribe-Loop-Drop ist einer der drei R1-Detect-
Trigger im Recovery-Workflow (siehe `recovery_workflow.py` §3.7.4.5
R1 failure path). Wenn beide gleichzeitig flippen, ist eine
Subscribe-Loop-NATS-Reconnect-Latency beim Restart nicht
unterscheidbar von einer R1-Detect-Init-Failure. Sequenz garantiert,
dass Welle-6-Rust-Subscribe-Loop stabil ist bevor Welle-7-Rust-
Recovery den Subscribe-Loop-Drop als R1-Trigger-Source sieht.

Welle-7-Cutover-Step §3 startet erst nach Welle-6-§3.6 Subscribe-
Loop-Resume-Verify (Per-Frame-Ack-Rate > 0 nach 30s).

**Schritt 3.1 — SSH auf Pilot-VM**

```bash
ssh root@192.168.178.116
# Erwarteter Banner: "wakir-pilot — FCOS — Phase-3b live"
```

**Schritt 3.2 — Pre-Restart-Snapshot (post-Welle-1+2+3+4+5)**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-6 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-6-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-6-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-6-cutover-pre-journal.txt

# Welle-1-5-State-Check: bestaetige dass alle Vorgaenger backend=rust
# (bzw. rust_inmemory fuer state_backing) laufen.
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -cE "BackendDecision.*(v907_verify|svid_workload_identity|anchor_emitter|state_backing|fsm).*backend=(rust|rust_inmemory)" \
  | tee -a /var/log/wakir/welle-6-cutover.log
# Erwartung: > 0 Records pro Component (fuenf separate Linien).
```

**Schritt 3.2.5 — Subscribe-Loop-State-Snapshot (Welle-6-spezifisch)**

Vor dem Pre-Drain: Subscribe-Loop-Cursor-Position + In-Flight-Frame-
Set + Ack-Counter werden als Pre-Cutover-Baseline-Snapshot erfasst.
Das ermoeglicht in §3.6 die Verifikation, dass der Rust-Subscribe-
Loop nach Restart bei der erwarteten Cursor-Position weiter macht.

```bash
# Auf Pilot-VM:
mkdir -p /var/lib/wakir/welle-6-subscribe-baseline

# 1. Subscribe-Loop-Cursor-Snapshot via CLI-Tool (Python-Backend-Pfad)
/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
    --mode=snapshot \
    --backend=python \
    --output=/var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-${TS_PRE}.json
wc -c /var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-${TS_PRE}.json \
    | tee -a /var/log/wakir/welle-6-cutover.log

# 2. Hash der Subscribe-Baseline (SHA-256 fuer immutability-Verify in §3.6 + §6)
sha256sum /var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-${TS_PRE}.json \
    | tee /var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-${TS_PRE}.sha256 \
    | tee -a /var/log/wakir/welle-6-cutover.log

# 3. Subscribe-Loop-Subjects + Consumer-Names + Cursor-Sequences erfassen
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
  | grep -E "subscribe_loop.*(subject=|consumer=|cursor=)" \
  | tail -10 \
  | tee /var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-cursor-${TS_PRE}.txt
```

**Erwartete Evidenz:** Snapshot-File-Size > 0, Hash protokolliert,
Cursor-Position fuer alle aktiven Subjects bekannt. Wenn Snapshot
0 Bytes hat: STOP — Subscribe-Loop ist bereits vor Cutover
unhealthy, das ist ein Pre-Cutover-Red und §6 ist nicht der richtige
Pfad (Reza + Henrik eskalieren, Cutover absagen).

**Schritt 3.2.7 — Subscribe-Loop-Pre-Drain (Welle-6-spezifisch, PFLICHT)**

**Kritisch.** Subscribe-Loop ist ein **stateful Ingress-Substrate**.
Ein Restart ohne Pre-Drain verliert in-flight Frames (max-redeliveries
ungebremst) oder produziert Doppel-Acks (NATS redelivery + Python-
Local-Cursor-Replay). Pre-Drain wartet bis `in_flight_count == 0`
ODER 60s-Hard-Cap.

```bash
# Auf Pilot-VM:
TS_DRAIN_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Pre-Drain-Start: ${TS_DRAIN_START}" | tee -a /var/log/wakir/welle-6-cutover.log

# Signal an Engine: subscribe-loop in drain-mode, neue Frames pause,
# in-flight Frames bis ack'd abarbeiten.
/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
    --mode=drain-initiate \
    --backend=python \
    --timeout-sec=60 \
    --output=/var/lib/wakir/welle-6-subscribe-baseline/drain-progress-${TS_PRE}.json

# Poll-Loop: in_flight_count alle 5s, max 60s Hard-Cap.
DEADLINE=$(($(date +%s) + 60))
while [ $(date +%s) -lt ${DEADLINE} ]; do
    IN_FLIGHT=$(/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
        --mode=in-flight-count --backend=python 2>/dev/null || echo "-1")
    echo "$(date -u +%H:%M:%S) in_flight=${IN_FLIGHT}" \
        | tee -a /var/log/wakir/welle-6-cutover.log
    if [ "${IN_FLIGHT}" = "0" ]; then
        echo "DRAIN-COMPLETE" | tee -a /var/log/wakir/welle-6-cutover.log
        break
    fi
    if [ "${IN_FLIGHT}" = "-1" ]; then
        echo "DRAIN-PROBE-FAIL: in-flight-count CLI returned error" >&2
        exit 2
    fi
    sleep 5
done

TS_DRAIN_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Pre-Drain-End: ${TS_DRAIN_END}" | tee -a /var/log/wakir/welle-6-cutover.log

# Hard-Cap-Check: wenn 60s erreicht ohne in_flight==0,
# Engineering-Decision-Point ob Cutover abgebrochen oder
# durchgezogen wird (akzeptierter In-Flight-Loss).
if [ "${IN_FLIGHT}" != "0" ]; then
    echo "DRAIN-HARD-CAP-EXCEEDED: in_flight=${IN_FLIGHT} after 60s" >&2
    echo "MIRA-HAND-DECISION required: cutover-abort vs accepted-loss" >&2
    # Default: cutover-abort. Operator kann mit --force-drain-cap fortfahren.
    exit 2
fi
```

**Erwartete Evidenz:** `in_flight=0` innerhalb 60s. Wenn Hard-Cap
erreicht: Mira-Hand-Decision — Standard ist Cutover-Abort, Forced-
Override braucht Henrik-Hand-Approval-File.

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht in-place
edit. Reversibel, ADR-0058-konform. **Welle-6-spezifisch:** Env-
Wert ist `rust` (Single-Variant, identisch zu Welle-3/5).

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-6-subscribe-loop-rust.conf <<'EOF'
# Phase-3c Welle-6 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-Sequenz, ADR-0066 §KW-27-Final-Doppel-Welle
# subscribe_loop Variant: rust (Single-Variant)
[Service]
Environment="WAKIR_SUBSCRIBE_LOOP_BACKEND=rust"
EOF
systemctl daemon-reload

# Sanity-Check: Welle-1 + Welle-2 + Welle-3 + Welle-4 + Welle-5 Drop-Ins existieren weiterhin.
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet:
#   welle-1-v907-verify-rust.conf
#   welle-2-svid-workload-identity-rust.conf
#   welle-3-bridge-audit-writer-rust.conf
#   welle-4-state-backing-rust.conf
#   welle-5-lifecycle-state-machine-rust.conf
#   welle-6-subscribe-loop-rust.conf  (neu)
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-6-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s, 9/9 BackendDecisions, subscribe_loop rust)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust` und `component=subscribe_loop` werden innerhalb 30s
emittiert. Gleichzeitig muessen alle 9 Boot-`BackendDecision`-
Records sichtbar sein — wenn nur 8/9: Migrations-Drift-Zustand,
§6 Rollback ist Pflicht.

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
    if ("BackendDecision" in msg
            and "component=subscribe_loop" in msg
            and "backend=rust" in msg):
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision subscribe_loop rust records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

**Schritt 3.6 — Subscribe-Loop-Resume-Verify (Welle-6-spezifisch)**

Spezifisch fuer Welle-6: nach Restart muss der Rust-Subscribe-Loop
(a) eine **aktive NATS-Subscription** halten, (b) den Pre-Cutover-
Cursor weiterzaehlen (kein Reset auf 0), und (c) eine **Per-Frame-
Ack-Rate > 0** innerhalb 30s nach Restart erkennen lassen.

```bash
# Auf Pilot-VM:
sleep 5  # Engine-Boot-Stabilisierung

# (a) Subscription-Status-Probe
/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
    --mode=subscription-status \
    --backend=rust \
    --output=/var/lib/wakir/welle-6-subscribe-baseline/post-cutover-subscription-${TS_PRE}.json
SUB_STATUS=$(grep -oP '"subscription_active":\s*\K(true|false)' \
    /var/lib/wakir/welle-6-subscribe-baseline/post-cutover-subscription-${TS_PRE}.json)
echo "Subscription-Active: ${SUB_STATUS}" | tee -a /var/log/wakir/welle-6-cutover.log
if [ "${SUB_STATUS}" != "true" ]; then
    echo "SUBSCRIBE-LOOP-RESUME-FAIL: subscription not active" >&2
    exit 2
fi

# (b) Cursor-Continuity-Probe
PRE_CURSOR=$(grep -oP '"cursor":\s*\K[0-9]+' \
    /var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-${TS_PRE}.json | head -1)
POST_CURSOR=$(grep -oP '"cursor":\s*\K[0-9]+' \
    /var/lib/wakir/welle-6-subscribe-baseline/post-cutover-subscription-${TS_PRE}.json | head -1)
echo "Pre-Cursor: ${PRE_CURSOR}  Post-Cursor: ${POST_CURSOR}" \
    | tee -a /var/log/wakir/welle-6-cutover.log
if [ "${POST_CURSOR}" -lt "${PRE_CURSOR}" ]; then
    echo "CURSOR-REGRESSION-DETECTED: post < pre — Subscribe-Loop hat Cursor verloren" >&2
    exit 2
fi

# (c) Per-Frame-Ack-Rate-Probe (30s post-Restart)
sleep 25  # Total 30s nach Restart
ACK_COUNT_30S=$(journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" --no-pager \
    | grep -cE "subscribe_loop.*ack_record_emitted" || echo "0")
echo "Ack-Records 30s post-Restart: ${ACK_COUNT_30S}" \
    | tee -a /var/log/wakir/welle-6-cutover.log
if [ "${ACK_COUNT_30S}" -lt 1 ]; then
    echo "ACK-RATE-ZERO: no ack-record emitted in 30s — Subscribe-Loop hangs?" >&2
    exit 2
fi
echo "SUBSCRIBE-LOOP-RESUME-OK: active, cursor-continuous, ack-rate>0"
```

Wenn Boot-Audit-Wait-Loop oder Subscribe-Loop-Resume-Verify Exit ≠ 0:
sofort §6 Rollback-Procedure.

---

## §4 Post-Cutover-Verification (15-min Soak-Window)

Soak-Window **15min** (Welle-1/2/4/5-Standard, kein 30-min wie
Welle-3). Vier parallele Beobachtungs-Streams plus Cross-Welle-
Coupling-Monitor. **Welle-6-spezifisch:** §4.3 enthaelt Output-
Reply-Timeliness-p99-Probe (FSM-Output-Hook-Awareness post-Welle-5),
§4.4 Cross-Modul-Drift-Check gegen Welle-7 (`recovery_workflow`).

**§4.1 — BackendDecision-Aggregator Sliding-Window**

```bash
# Auf Mira-Box, gegen Pilot-NATS:
cd /var/home/fred/AI-Corp/wakir-runtime
python3 scripts/phase-3c/backend-decision-aggregator.py \
    --component subscribe_loop \
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

Subscribe-Loop Cross-Lang-Hash-Parity-Pins (`tests/fixtures/
subscribe-loop-cross-lang/fixtures.json`). Im Soak-Window: 5
Synthetik-Ack-Record-Hash-Calls, jede mit Python-Vergleichs-Hash
gegen die Pin-Baseline.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component subscribe_loop \
    --samples 5 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/fixtures/subscribe-loop-cross-lang/fixtures.json \
    --canonical-module wirelang.persona_engine.subscribe_ack
```

Erwartung: 5/5 Hashes match. Jede Drift => sofort §6 Rollback.

Hintergrund: die Cross-Lang-Parity prueft die deterministische
JCS-Kanonisierung der Subscribe-Loop-Per-Frame-Ack-Record-Envelopes.
Drift heisst: Python- und Rust-Side haben unterschiedliche
Canonical-Forms — das ist ein blocker-level Bug fuer Ack-Record-
Persistence-Continuity (Bridge-Audit-Stream-Konformitaet).

**§4.3 — Output-Reply-Timeliness p99 + Subscribe-Loop-Error-Freiheit + Latency**

**Welle-6-spezifischer Output-Reply-Timeliness-Check:** Subscribe-
Loop steht nach Welle-5-Cutover unter FSM-Output-Hook-Awareness —
ein Subscribe-Loop-Frame, das eine FSM-Transition triggert,
muss eine Output-Reply innerhalb p99 ≤ 45s emittieren. Welle-6-Soak
beobachtet diese Round-Trip-Latenz als zusaetzliche Welle-6-
spezifische Achse.

```bash
# Auf Pilot-VM:
journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" \
    -p err --no-pager \
    | grep -E "subscribe_loop|subscribe_ack" \
    | tee /var/log/wakir/welle-6-subscribe-loop-errors.txt
wc -l /var/log/wakir/welle-6-subscribe-loop-errors.txt
```

Grafana-Dashboard `Persona-Engine — Backend Latency by Component`.
Filter: `component=subscribe_loop`, `backend=rust`, last 15min.

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

**Welle-6-spezifische Latenz-Achse — Output-Reply-Timeliness:**

| Metrik | Schwelle |
|---|---|
| Output-Reply-p50 | ≤ 5s |
| Output-Reply-p95 | ≤ 20s |
| Output-Reply-p99 | ≤ 45s (HARTE GRENZE — siehe §5 T-3 zusaetzliche Subachse) |

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/output-reply-timeliness-probe.py \
    --pilot 192.168.178.116 \
    --window 15m \
    --percentile 99 \
    --threshold-sec 45 \
    --json-out /tmp/welle-6-output-reply-timeliness.json
echo "output-reply-exit=$?"
```

Operator: Screenshot pro 5min-Slice (3 Screenshots gesamt) + JSON-
Export an Henrik-Audit-Trail anhaengen.

Erwartung: 0 Error-Zeilen im 15-min-Soak-Window. Jede Error-Zeile
= automatischer §6 Rollback.

**§4.4 — Cross-Modul-Drift-Check gegen Welle-7 recovery_workflow (Welle-6-spezifisch)**

Welle-6-exklusiv (im Doppel-Welle-Pattern): `subscribe_loop` steht
in direkter Trigger-Korrelation mit `recovery_workflow` — Subscribe-
Loop-Drop ist R1-Trigger-Klasse `subscribe_loop_failure` (siehe
`recovery_workflow.py::detect_trigger`). Wenn Welle-6+7 parallel
cutover: ein Schema-Drift in einem der beiden Substrate emergiert
als Cross-Modul-Drift gegen den anderen.

```bash
# Auf Mira-Box:
python3 scripts/doppelbetrieb-score-aggregator.py \
    --mode=cross-modul-stress \
    --threshold 3 \
    --target-component subscribe_loop \
    --paired-component recovery \
    --pilot 192.168.178.116 \
    --json-out /tmp/welle-6-cross-modul-drift.json
echo "cross-modul-drift-exit=$?"
```

Erwartung: 3-of-3 Cross-Modul-Achsen `>= threshold`:
- `cross-lang-pin-coverage` (subscribe_loop × recovery cross-lang
  fixtures)
- `cross-modul-fixture-stability` (Subscribe-Drop -> R1-Trigger-
  Sanity, Subscribe-Loop-Resume nach R4-Resume-Phase)
- `cross-modul-rollup-integrity` (Welle-6+7-Aggregate-Health)

Exit 0 = green; Exit non-zero = red (sofort Rollback, plus Welle-7-
Rollback-Koordination weil Doppel-Welle-Coupling — siehe §6
Schritt 5).

**§4.5 — Doppel-Welle-Coupling-Monitor (Welle-7-Cross-Status)**

```bash
# Auf Mira-Box, liest Welle-7-Cutover-Log (parallel-Cutover):
ssh root@192.168.178.116 'tail -50 /var/log/wakir/welle-7-cutover.log'
```

Erwartung: Welle-7-Boot-Audit-Pass (§3.5 Welle-7-Runbook) ist
abgeschlossen. Wenn Welle-7 im Soak-Window-Beginn von Welle-6 noch
nicht durch §3.5 ist: Mira-Hand-Decision-Point (Welle-6-Soak-Window
starten oder mit Welle-7-Boot-Audit-Pass warten).

**Cross-Welle-Yellow-Bedingung:** Wenn Welle-7 Boot-Audit-FAIL
hat aber Welle-6 OK ist: Welle-6 setzt Soak-Window fort, aber
Welle-7-Rollback wird parallel triggered. Cross-Modul-Drift-Check
§4.4 wird trotzdem ausgefuehrt — bei drift `> 0` mit Welle-7-
Rollback im Hintergrund: yellow (Mira-Hand-Decision).

---

## §5 Rollback-Trigger — Exit-Decision-Matrix

Fuenf harte Trigger (drei Standard, zwei Welle-6-spezifisch). Bei
JEDEM einzelnen Trigger: sofort §6, keine Diskussion, keine
Eskalations-Verzoegerung. Mira-Hand entscheidet im Cutover-Window
autark, AR-Override nur post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.3) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | Subscribe-Loop-Service ERR-Zeile | Journal (§4.3) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | Lag-Excursion ODER Output-Reply-Timeliness-Excursion ODER Subscribe-Drain-Hang | §4.3 + §3.2.7 | Lag > 90s anhaltend ≥3 Slices ODER Output-Reply-p99 > 45s ODER Drain-Hard-Cap-Exceeded-without-Override | Rollback (§6) |
| T-4 | Cross-Modul-Inkonsistenz mit recovery_workflow | §4.4 Cross-Modul-Drift | Eine der 3 Achsen `< threshold` | Rollback (§6) + Welle-7-Koordinations-Marker |
| T-5 | Cross-Lang-Hash-Drift | §4.2 Parity-Probe | Jede einzelne Drift in 5 Samples | Rollback (§6) |

**T-3 Begruendung (Welle-6-spezifisch, Lag + Output-Reply + Drain):**
Subscribe-Loop-Lag > 90s heisst entweder: (a) Subscribe-Loop holt
Frames nicht schnell genug ab (NATS-Backlog steigt), oder (b) Per-
Frame-Ack-Rate ist zu langsam (acks accumulieren). Beide Faelle
sind blocker-level fuer Ingress-Durchsatz. Output-Reply-Timeliness-
p99 > 45s heisst: Subscribe-Loop-Frame triggert FSM, aber Output-
Reply braucht zu lange — das deutet auf FSM-Output-Hook-Backpressure
ODER Subscribe-Loop-Stall hin. Subscribe-Drain-Hang (§3.2.7 Hard-
Cap ohne Force-Override) ist Pre-Cutover-Block.

**T-4 Begruendung (Doppel-Welle-Cross-Modul, recovery):**
Cross-Modul-Drift gegen `recovery_workflow` heisst entweder
Subscribe-Loop-Schema-Drift in Drop-Detect-Signalisierung ODER
Recovery-R1-Trigger-Drift in Subscribe-Loop-Failure-Klassifikation.
Beide Faelle sind blocker-level fuer Engine-Resilience-Continuity.
**Welle-7-Koordinations-Marker** wird gesetzt: `/var/lib/wakir/
audit-holds/welle-6-cross-modul-drift-<TS>.marker` — Welle-7 muss
entsprechend mit-rollback'n falls noch nicht stable.

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1 Exit 1).
- Latency p99 > 2.0× Baseline (§4.3 Warn-Schwelle).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  <0.1%).
- Welle-7-Boot-Audit-FAIL waehrend Welle-6 OK (§4.5 Cross-Welle-
  Yellow, Mira-Hand-Decision).
- Output-Reply-Timeliness-p95 > 20s aber p99 ≤ 45s (Subscribe-
  Loop-FSM-Output-Hook-Backpressure-Warnung, kein Auto-Rollback).
- Lag zwischen 30s und 90s anhaltend ≥3 Slices (Yellow-Backlog-
  Warnung).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt, Service-
Restart (mit Pre-Drain-Repeat), Verify Backend=python, Subscribe-
Loop-Cursor-Continuity-Verify gegen Pre-Cutover-Baseline. Welle-
1+2+3+4+5-State bleibt unberuehrt — nur das Welle-6-Overlay-File
wird entfernt.

**Welle-7-Koordination:** Wenn T-4 Trigger (Cross-Modul-Drift mit
Welle-7): Welle-7-Rollback parallel mit Welle-6-Rollback. Schritt
5 unten beschreibt die Welle-7-Koordinations-Eskalation.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-6 Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-6-cutover.log

# 1. Subscribe-Loop-Pre-Drain-Repeat (Rust-Backend in drain-mode,
# 60s Hard-Cap). Identisch zu §3.2.7 aber Rust-Backend.
/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
    --mode=drain-initiate \
    --backend=rust \
    --timeout-sec=60 \
    --output=/var/lib/wakir/welle-6-subscribe-baseline/rollback-drain-progress-${TS_RB}.json
DEADLINE=$(($(date +%s) + 60))
while [ $(date +%s) -lt ${DEADLINE} ]; do
    IN_FLIGHT=$(/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
        --mode=in-flight-count --backend=rust 2>/dev/null || echo "-1")
    if [ "${IN_FLIGHT}" = "0" ]; then break; fi
    sleep 5
done

# 2. Env-Overlay entfernen — NUR Welle-6-Drop-In, Welle-1..5 bleiben
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-6-subscribe-loop-rust.conf
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet: welle-1-* bis welle-5-* bleiben; welle-6-* weg.
systemctl daemon-reload

# 3. Service-Restart
systemctl restart wakir-persona-engine.service
TS_RB_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 4. Verify backend=python (5 BackendDecision-Records innerhalb 30s)
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
            and "component=subscribe_loop" in msg
            and "backend=python" in msg):
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified for subscribe_loop")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 5. Subscribe-Loop-Cursor-Continuity-Verify gegen Pre-Cutover-Baseline.
# Python-Backend muss bei einer Cursor-Position >= Pre-Cutover-Cursor
# wieder aufnehmen. Drift hier heisst: Rollback hat den Cursor verloren —
# AR-Hand-Stop-Marker Pflicht.
sleep 10  # Engine-Boot-Stabilisierung
PRE_CURSOR=$(grep -oP '"cursor":\s*\K[0-9]+' \
    /var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-${TS_PRE}.json | head -1)
/opt/wakir/bin/wakir-persona-engine-subscribe-loop \
    --mode=subscription-status \
    --backend=python \
    --output=/var/lib/wakir/welle-6-subscribe-baseline/post-rollback-subscription-${TS_RB}.json
POST_RB_CURSOR=$(grep -oP '"cursor":\s*\K[0-9]+' \
    /var/lib/wakir/welle-6-subscribe-baseline/post-rollback-subscription-${TS_RB}.json | head -1)
echo "Pre-Cutover-Cursor: ${PRE_CURSOR}  Post-Rollback-Cursor: ${POST_RB_CURSOR}" \
    | tee -a /var/log/wakir/welle-6-cutover.log

if [ "${POST_RB_CURSOR}" -lt "${PRE_CURSOR}" ]; then
    echo "ROLLBACK-CURSOR-REGRESSION: post-rollback < pre-cutover" >&2
    echo "AR-HAND-STOP-MARKER required" >&2
    mkdir -p /var/lib/wakir/audit-holds
    touch /var/lib/wakir/audit-holds/welle-6-rollback-cursor-regression-${TS_RB}.marker
    exit 3   # exit-3 signalisiert AR-Hand-Stop-Marker, NICHT routine Rollback-Fail
fi

# 6. Welle-7-Koordinations-Pruefung (Doppel-Welle-Coupling).
if ls /var/lib/wakir/audit-holds/welle-6-cross-modul-drift-*.marker >/dev/null 2>&1; then
    echo "WELLE-7-COORDINATION-ROLLBACK required (T-4 Cross-Modul-Drift)" \
        | tee -a /var/log/wakir/welle-6-cutover.log
    # Welle-7-Rollback-Trigger: siehe Welle-7-Runbook §6 — Mira-Hand
fi

# 7. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-6 Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-6-cutover.log
```

**Eskalations-Schwelle bei Rollback-Cursor-Regression (exit-3):**
Wenn Schritt 5 ROLLBACK-CURSOR-REGRESSION meldet, ist das **kein**
routine-Rollback-Done sondern eine **AR-Hand-Stop-Marker-Bedingung**:

- Subscribe-Loop hat im Rollback Cursor-Position verloren.
- In-Flight Frames sind unter Umstaenden doppelt-prozessiert.
- Marker-File `/var/lib/wakir/audit-holds/welle-6-rollback-cursor-
  regression-*.marker` wird gesetzt.
- Eskalation Mira -> Priya -> AR sofort.
- Welle-7 (parallel KW-27) muss auch gestoppt werden bis Cursor-
  Recovery-Decision vorliegt.
- **Phase-3c-Marathon-Schluss-Stempel verzoegert sich entsprechend.**

Nach erfolgreichem Rollback (kein exit-3): 30-min Stabilitaets-
Beobachtung (Welle-1/2-Standard) mit BackendDecision-Aggregator
(§4.1, --target-backend python), Subscribe-Loop-Error-Monitor
(§4.3), und Cross-Modul-Drift-Check gegen Welle-7 (§4.4 mit
aktuellem Welle-7-Status). Dann §7 Sign-Off mit verdict=`rollback`,
Root-Cause-Analyse binnen 48h pflichtig:

- **Reza** — subscribe-loop Rust-CLI-Substrate-Owner, JCS-Canonical-
  Form-Drift-Investigation, Per-Frame-Ack-Record-Schema-Validation.
- **Tomás** — Cross-Modul-Korrelation mit recovery_workflow.
- **Henrik** — Audit-Trail-Integrity, Cursor-Continuity-Verify.

---

## §7 Sign-Off — Henrik-Audit-Trail

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off ist
Pflicht **vor Welle-7-Sign-Off-Trigger** (KW-27 geplant). Welle-6-
Sign-Off korreliert mit Welle-7-Sign-Off (Doppel-Welle-Coupling).
**Welle-7-Sign-Off-Green = Phase-3c-Marathon COMPLETE.**

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-6-smoke-*.json` (§2 Skript-Output)
- Welle-6-Wednesday-Validation-`cutover-acceptance-decision-welle-
  6.json` (§1, GitHub-Actions-Artifact-URL, mit
  `cross_modul_stress_passed == true`)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-6-pre-
  cutover-*.json` (post-Welle-1+2+3+4+5, frisch)
- BackendDecision-Aggregator-Snapshot (§1, Python-Default
  `subscribe_loop` ≥99%)
- **Pre-Cutover-Subscribe-Loop-Snapshot** (§3.2.5,
  `/var/lib/wakir/welle-6-subscribe-baseline/pre-cutover-subscribe-
  *.json` + SHA-256-Hash + Cursor-Position)
- **Pre-Drain-Evidence** (§3.2.7,
  `/var/lib/wakir/welle-6-subscribe-baseline/drain-progress-*.json`,
  `in_flight_count == 0`-Confirm)
- Welle-3-5 Sign-Off-Status (§1, Pflicht-Vorbedingung)
- Welle-7-Pre-Conditions-Status (§1, Doppel-Welle-Coupling)

**TEL-Evidenz (waehrend §4 15-min Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1, 15-min Window JSON)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 5/5 oder Abweichung)
- Subscribe-Loop-Error-Count + Latency-Histogramm (§4.3, 0-Zeilen-
  File + 3 Grafana-Screenshots)
- **Output-Reply-Timeliness-Probe-Output** (§4.3,
  `/tmp/welle-6-output-reply-timeliness.json`, p99 ≤ 45s Pflicht)
- Cross-Modul-Drift-Check-Output (§4.4,
  `/tmp/welle-6-cross-modul-drift.json`, 3/3 Achsen >= threshold
  Pflicht)
- Welle-7-Cross-Status-Snapshot (§4.5, Welle-7-Cutover-Log-Tail)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-6-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- Subscribe-Loop-Resume-Verify-Output (§3.6 Sub-Status,
  Cursor-Continuity, Ack-Rate)
- Bei Rollback: Welle-7-Coordination-Status (parallel-Rollback ja/nein)
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`,
  oder **`ar-hand-stop`** bei exit-3 Cursor-Regression)
- Welle-7-Sign-Off-Status (Cross-Welle-Korrelation)
- **Phase-3c-Marathon-Schluss-Stempel-Bit** (`phase_3c_complete`
  Flag — gesetzt nur wenn Welle-6-`green`/`yellow` UND
  Welle-7-`green`/`yellow`)

**Sign-Off-Template:**

```yaml
welle: 6
component: subscribe_loop
variant: rust
cutover_date: 2026-06-29
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
verdict: green | green-with-yellow-notes | rollback | ar-hand-stop
yellow_notes: []
red_triggers_hit: []
# Welle-6-spezifische Achsen:
subscribe_loop_drain_in_flight_zero_within_60s: true | false  # MUSS true fuer green
subscribe_loop_cursor_continuity: true | false  # MUSS true fuer green
subscribe_loop_resume_ack_rate_30s_gt_0: true | false  # MUSS true fuer green
output_reply_timeliness_p99_sec: <number>  # MUSS <= 45 fuer green
cross_modul_drift_axes_pass: 3   # MUSS 3 fuer green (subscribe_loop x recovery)
# Cross-Welle-Coupling:
welle_3_signoff_status: green | green-with-yellow-notes | rollback
welle_4_signoff_status: green | green-with-yellow-notes | rollback
welle_5_signoff_status: green | green-with-yellow-notes | rollback
welle_7_signoff_status: green | green-with-yellow-notes | rollback
# Phase-3c-Marathon-Schluss-Stempel:
phase_3c_complete: false  # gesetzt durch AR post-Welle-7-Sign-Off
# Evidenz-Pfade:
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
pre_cutover_subscribe_sha256: <hash>
pre_cutover_cursor: <int>
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-6-subscribe-loop-signoff-2026-06-29.yaml`

---

## §8 Mira-SSH-Hand-Authority + AR-Hand-Stop-Marker

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-Hand-
Authority fuer Pilot-VM-Operations.

**Mira-Hand-Operations (autark, identisch zu Welle-1-5):**
systemctl restart, Env-Overlay-File-Edits, Journal-Reads, Quadlet-
Override-Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
Subscribe-Loop-Drain-Initiate (read-write CLI on Subscribe-Loop
state — drain-mode, kein irreversibles despawn), Subscribe-Loop-
Snapshot-Creation (read-only).

**AR-Hand-Operations (irreversibel-despawn, identisch zu Welle-1-5):**
`podman rm` ohne Backup, Volume-Wipe (`podman volume rm`), System-
Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade, Disk-
Repartitionierung.

**Welle-6-Neu — AR-Hand-Stop-Marker-Bedingungen:**

Drei Bedingungen triggern automatisch ein Marker-File und
sofortige AR-Eskalation (Mira -> Priya -> AR):

1. **Rollback-Cursor-Regression** (§6 Schritt 5 exit-3) — Subscribe-
   Loop-Cursor nach Rollback < Pre-Cutover-Cursor; In-Flight-Frames
   moeglicherweise doppelt-prozessiert.
2. **Drain-Hard-Cap-Hang ohne Force-Override** (§3.2.7 exit-2 mit
   Mira-Hand-Decision `cutover-abort`) — Subscribe-Loop kann nicht
   drained werden, das ist Pre-Cutover-Block. Falls Hard-Cap-Hang
   nach Cutover-Versuch ohne erfolgreichen Rollback: AR-Hand-Stop.
3. **T-4 Cross-Modul-Drift + Welle-7-Coordination-Fail** — wenn
   Welle-7-Rollback nicht erfolgreich nach Welle-6-T-4-Trigger.

Marker-File-Pfad-Pattern:
`/var/lib/wakir/audit-holds/welle-6-<bedingung>-<TS>.marker`

Bei AR-Hand-Stop-Marker: **Phase-3c-Marathon-Schluss-Stempel
verzoegert sich.** Welle-7 muss parallel gestoppt werden. Henrik-
Hand-Forensik-Pflicht binnen 72h.

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-Kombination):
   Mira-Hand-Decision autark. Henrik-Audit protokolliert.
2. **Substanz-Konflikt** (z.B. Subscribe-Loop-Error-Rate ODER Cross-
   Lang-Hash-Drift): Mira-Hand Rollback nach §6, dann Eskalation
   Mira -> Priya -> Reza (subscribe-loop-Rust-Substrate-Owner).
3. **Cursor-Regression (Rollback exit-3) oder Drain-Hang-Abort**:
   AR-Hand-Stop-Marker setzen, sofortige Mira -> AR-Eskalation,
   Phase-3c-Marathon-Schluss-Stempel-Verzoegerung dokumentieren.
4. **Cross-Modul-Drift mit Welle-7** (T-4): Welle-7-Koordinations-
   Marker, parallel-Rollback Welle-6+7, danach Eskalation Mira ->
   Priya -> Tomás (Cross-Modul-Korrelations-Owner).
5. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-Drop):
   Mira-Hand Rollback, dann Eskalation Mira -> AR fuer Recovery.

---

## §9 Bekannte Risiken

**R-1 — Cross-Modul-Drift zu Welle-7 parallel-Cutover (symmetric A7)**
ADR-0066 §KW-27-Final-Doppel-Welle erlaubt Welle-6+7 parallel im
KW-27. Subscribe-Loop und Recovery teilen Detect-Trigger-Semantik
(Subscribe-Loop-Drop ist R1-Klasse `subscribe_loop_failure`). Ein
Schema-Drift in einem der beiden Substrate erscheint als Doppel-
Welle-Symptom, nicht als Single-Modul-Issue. Mitigation: §4.4
Cross-Modul-Drift-Check mit `doppelbetrieb-score-aggregator
--mode=cross-modul-stress` (PR #197) als Pflicht-Step; T-4 Trigger
bei Drift > 0; Welle-7-Koordinations-Marker im Rollback-Pfad.
Sekundaere Mitigation: Doppel-Welle-Sequenz (§3.0) — Welle-6-§3
beginnt zuerst, Welle-7-§3 folgt nach Welle-6-§3.6.

**R-2 — NATS-Connection-Persistence ueber Engine-Restart**
Subscribe-Loop ist der einzige Phase-3c-Substrate mit persistenter
NATS-Subscription. Beim Engine-Restart wird der NATS-Client
disconnected, beim Boot-Audit-Pass muss er reconnected werden und
beim Subject-Subscription-Wire ist der Server-Side Consumer-State
mit dem neuen Client zu verbinden. Risiko: (a) NATS-Server hat den
Consumer-State expired (max-deliver oder ack-wait timeout), (b)
Rust-Client subscribet auf falsches Subject (Subject-Pattern-Drift
in Rust-Crate-Spec). Mitigation: §1 NATS-JetStream-Konnektivitaet-
24h-Pre-Cutover-Stable-Gate; §3.6 Subscription-Status-Plus-Cursor-
Continuity-Check; §3.2.7 Pre-Drain (in_flight==0 vor Restart
minimiert Risiko der server-side consumer-state-expirations); §4.3
Output-Reply-Timeliness-Check fasst NATS-Reconnect-Latenz als End-
to-End-Achse.

**R-3 — FSM-Output-Hook-Awareness (post-Welle-5)**
Welle-5 hat den FSM auf Rust geflippt. FSM-Output-Hooks werden
durch Subscribe-Loop-Frames getriggert (Subscribe-Loop-Frame mit
`fsm_trigger`-Annotation -> FSM-Transition -> Output-Hook). Wenn
Subscribe-Loop-Rust den Output-Hook-Trigger-Encoding aenderlich
emittiert (Schema-Drift gegen Welle-5-FSM-Rust): FSM erkennt den
Trigger nicht, Output-Reply bleibt aus, p99-Latenz schraubt sich
hoch. Mitigation: §4.3 Output-Reply-Timeliness-Probe (p99 ≤ 45s
HART); cross-modul-fixture-stability-Achse in §4.4 prueft Subscribe-
Drop -> R1-Trigger-Sanity (symmetric mit Subscribe-Frame -> FSM-
Trigger als gleicher Schema-Surface).

**R-4 — Pre-Drain-Hard-Cap-Hang (60s nicht ausreichend)**
§3.2.7 Pre-Drain wartet bis `in_flight_count == 0` ODER 60s. Wenn
in der Pilot-VM-Engine ein langlaufender Frame (z.B. Persona-
Decision mit grosser Context-Loadout) noch in-flight ist und nicht
innerhalb 60s ack'd wird: Hard-Cap-Hang, Mira-Hand-Decision
cutover-abort vs. accepted-loss. Mitigation: Pre-Cutover-In-Flight-
Frame-Count-Sanity in Selin-Smoke (§2: erwartet `< 100`); Mira-
Hand-Discipline bei Hard-Cap-Hit (Standard: abort, Force-Override
nur mit Henrik-Hand-Approval-File).

**R-5 — Welle-7-Solo-Vorzieh-Risiko**
Wenn Welle-7-Pre-Conditions yellow ist (§1 Welle-7-Coupling-Status
(b)) und Mira-Hand-Decision: "Welle-6 solo, Welle-7 verschiebt
sich um eine Woche": Cross-Modul-Stress-Test §4.4 laeuft trotzdem,
aber gegen Python-Default-Recovery (keine Doppel-Welle-Cross-Lang-
Achse). Welle-6-Sign-Off bleibt moeglich, aber Welle-7-Re-Schedule
auf KW-28 verschiebt **Phase-3c-Marathon-Schluss-Stempel auf
2026-07-05+**. Mitigation: Pre-Conditions §1 dokumentiert die
drei Welle-7-Coupling-Zustaende explizit; Mira-Hand-Decision ist
protokolliert.

**R-6 — Welle-3-5-Rollback-Coupling**
Falls eine der Welle-3/4/5 `rollback` ODER `ar-hand-stop` (§1
zulaessiger Zustand (c)): Welle-6+7 (KW-27) sind BLOCKIERT.
Begruendung: Subscribe-Loop schreibt Ack-Records in den Bridge-
Audit-Stream (Welle-3-Substrate) und triggert FSM-Outputs (Welle-5-
Substrate) und persistiert ueber State-Backing (Welle-4-Substrate).
Welle-6 hat drei Vorgaenger-Substrate-Abhaengigkeiten — jeder
Rollback dort macht Welle-6-Cross-Modul-Drift-Check falsch-positiv.
AR-Eskalation Pflicht; Welle-6+7-Re-Scheduling ist AR-Decision.

**R-7 — Phase-3c-Marathon-Schluss-Stempel-Dependency**
Welle-6 selbst ist nicht der Marathon-Schluss-Stempel — das ist
Welle-7. Aber Welle-6-Rollback ODER Welle-6-yellow blockiert
Welle-7-Sign-Off (siehe §1 Doppel-Welle-Coupling Pflicht-
Vorbedingung). Mitigation: Welle-6-Sign-Off mit ≥yellow ist
Pflicht-Vorbedingung fuer Phase-3c-Marathon-Complete-Flag.
**Geplantes Phase-3c-Ende: ~2026-06-21** (Welle-7-Sign-Off-Day
KW-27 Montag plus Henrik-Sign-Off-Window). Bei Welle-6-Verzoegerung
verschiebt sich das proportional.

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, **Montag KW-27 (2026-06-29)**,
**10:00-14:00 CEST Cutover-Window** (4h, identisch zu Welle-4/5-
Window weil Doppel-Welle-Pattern symmetrisch).

**Konkretes Cutover-Window — Welle-6 (parallel Welle-7, Welle-6 zuerst):**

| Sub-Phase | Slot CEST |
|---|---|
| Pre-Conditions Walk-Through (Welle-6 + Welle-7 sync) | 10:00-10:20 |
| Pre-Flight-Smoke Welle-6 (§2) + Welle-7-Smoke (parallel) | 10:20-10:30 |
| Pre-Cutover-Subscribe-Loop-Snapshot (§3.2.5) Welle-6 | 10:30-10:40 |
| **Pre-Drain Welle-6 (§3.2.7, 60s Hard-Cap)** | 10:40-10:42 |
| Cutover-Step Welle-6 (§3.1-§3.6) | 10:42-11:05 |
| Cutover-Step Welle-7 (parallel, startet nach Welle-6 §3.6) | 11:05-11:25 |
| Soak-Window Welle-6+7 (§4, 15-min) | 11:25-11:40 |
| Cross-Modul-Drift-Check (§4.4) + Output-Reply-Timeliness | 11:40-11:55 |
| Sign-Off-Initial-Draft (§7) Welle-6 + Welle-7 | 11:55-12:35 |
| Reserve — Rollback + Cursor-Continuity-Verify (Welle-6 ODER 7 ODER beide) | 12:35-14:00 |
| **Pause + Audit-Trail-Submission an Henrik** | 14:00-15:30 |
| **Henrik-Audit-Sign-Off-Window (Welle-6 + Welle-7 = Phase-3c-MARATHON-CLOSURE)** | 15:30-17:00 |

**Datum: Montag 2026-06-29 (KW-27)**

- **Welle-6-Cutover-Start:** 10:00 CEST
- **Welle-6-Latest-Commit-To-Rust:** 11:05 CEST (Boot-Audit-Pass + Resume-Verify)
- **Welle-7-Cutover-Start:** 11:05 CEST (nach Welle-6-§3.6)
- **Welle-6+7-Soak-Window-Ende:** 11:40 CEST
- **Welle-6+7-Sign-Off-Window-Ende:** 17:00 CEST
- **Phase-3c-Marathon-Schluss-Stempel:** 17:00 CEST 2026-06-29
  (sobald Welle-7-Sign-Off-Green vorliegt; Henrik-AR-Tag bis
  ~2026-06-30 Dienstag-Morgen)
- **Hairpin-Rollback-Slot:** Mittwoch 2026-07-01, 09:00-13:00 CEST

**Begruendung Werktag-Vormittag + Doppel-Welle-Sequenz + 4h-Window:**

1. **Doppel-Welle (symmetric Welle-4/5):** Pre-Conditions Walk-
   Through und Pre-Flight-Smokes sync zwischen Welle-6 und Welle-7
   (Mira-Hand-Owner beider). 4h-Window deckt Welle-6-§3 + Welle-7-
   §3 + gemeinsamer Soak-Window + Reserve fuer parallel-Rollback ab.
2. **Welle-7-Sequenz-Constraint:** Welle-7-Cutover startet erst
   nach Welle-6-§3.6 Subscribe-Loop-Resume-Verify (siehe §3.0).
   Welle-7-Cutover-Window-Start ist daher ~60min nach Welle-6-Start.
3. **Pre-Drain-Pflicht-Slot:** Welle-6 hat einen zusaetzlichen 2-
   minute-Pre-Drain-Slot (10:40-10:42) den Welle-1-5 nicht hatte.
4. **Cross-Modul-Drift-Check (§4.4) + Output-Reply-Timeliness:**
   Pflicht-Step im Soak-Window weil Doppel-Welle-Coupling +
   Welle-6-spezifischer Output-Reply-p99-Check. Zusaetzliche 15min-
   Slot vor Sign-Off.
5. **Henrik-Sign-Off-Window 15:30-17:00 = Phase-3c-Marathon-Closure:**
   Henrik prueft Welle-6-Sign-Off und Welle-7-Sign-Off als
   korreliertes Paar UND setzt den `phase_3c_complete: true`-Flag
   wenn beide Sign-Offs ≥ yellow.
6. **Hairpin-Rollback-Slot Mi (KW-27):** Falls Welle-6 ODER 7
   ODER beide yellow-with-Henrik-Hand-Approval-Bedarf — Mittwoch-
   Vormittag (09:00-13:00, 4h-Window, geteilt) ist der naechste
   sinnvolle Slot.
7. **Phase-3c-Marathon-End ~2026-06-21:** Plan ist Welle-7-Sign-Off-
   Tag plus Henrik-Hand-Verzoegerung. Konkret: bei Welle-6+7-Green
   am 2026-06-29 ist Phase-3c-Marathon-COMPLETE-Flag bis spaetestens
   2026-06-30 Mittag gesetzt; das Mira-Hand-Anchor-Bit
   (`phase_3c_complete: true`) wird im Activity-Log dokumentiert.

**Verbotene Cutover-Slots:**

- Freitag-Nachmittag (Wochenend-Rollback-Risiko).
- Mittwoch-Mittag (kollidiert mit Wednesday-Validation-Run-Re-Run-
  Option).
- Sonntag/Feiertag (kein Engineering-Standby).
- Parallel zu Welle-4+5-Cutover-Step (KW-26, siehe §9 R-6).
- KW-27-Mittwoch-Cutover-Slot (Mittwoch ist Hairpin-Rollback-Slot,
  nicht Cutover-Slot).

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Reza (subscribe-loop-Rust-Substrate-Owner) | bei JCS-Canonical-Drift, Per-Frame-Ack-Schema-Drift, Cursor-Regression-Investigation, NATS-Reconnect-Issue |
| 3 | Tomás (Matrix-Lead) | bei Welle-6/7-Cross-Modul-Korrelation, Doppel-Welle-Coupling-Konflikt |
| 4 | Henrik (Internal Audit) | bei Audit-Trail-Anomaly, T-3 oder T-4 Trigger, Drain-Hard-Cap-Force-Override-Approval, Phase-3c-Marathon-Closure-Audit |
| 5 | AR (Fred) | bei AR-Hand-Stop-Marker, Cursor-Regression (§6 exit-3), Drain-Hard-Cap-Abort, Welle-3-5-Rollback-Coupling-Block, Phase-3c-Marathon-End-Approval |

---

## Anhang B — Cross-Welle-Coordination-Checkliste (KW-27 Doppel-Welle 6+7)

Vor Welle-6-Cutover-Start: explizite Verifikation der Welle-1-5-
Coordination-Items und der Welle-7-Parallel-Coordination. **Dies
ist die finale Coordination-Checkliste der Phase-3c-Marathon-Sequenz.**

- [ ] Welle-1-Runbook gelesen ([`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md), PR #228 Tag-34)
- [ ] Welle-2-Runbook gelesen ([`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md), PR #232 Tag-35)
- [ ] Welle-3-Runbook gelesen ([`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md), PR #237 Tag-36)
- [ ] Welle-4-Runbook gelesen ([`welle-4-state-backing-runbook.md`](./welle-4-state-backing-runbook.md), PR #243 Tag-37)
- [ ] Welle-5-Runbook gelesen ([`welle-5-lifecycle-state-machine-runbook.md`](./welle-5-lifecycle-state-machine-runbook.md), PR #247 Tag-38)
- [ ] Welle-7-Runbook gelesen ([`welle-7-recovery-workflow-runbook.md`](./welle-7-recovery-workflow-runbook.md), gleicher Bundle-PR Tag-39, paralleler Doppel-Welle-Partner)
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
- [ ] Welle-1-`v907_verify` `backend=rust` im Aggregator >99%
- [ ] Welle-2-`svid_workload_identity` `backend=rust` im Aggregator >99%
- [ ] Welle-3-`anchor_emitter` `backend=rust` im Aggregator >99%
- [ ] Welle-4-`state_backing` `backend=rust_inmemory` im Aggregator >99%
- [ ] Welle-5-`fsm` `backend=rust` im Aggregator >99%
- [ ] Welle-6-Engine-Health-Baseline frisch aufgezeichnet POST-Welle-1+2+3+4+5
- [ ] Welle-6-spezifischer Pre-Cutover-Subscribe-Loop-Snapshot vorhanden (§3.2.5, SHA-256-Hash + Cursor-Position protokolliert)
- [ ] **Welle-6-Pre-Drain (§3.2.7) erfolgreich** (`in_flight==0` innerhalb 60s)
- [ ] Welle-7-Pre-Conditions-Status gepruft (§1 Coupling-Zustaende a/b/c)
- [ ] Doppel-Welle-Sequenz §3.0 verstanden (Welle-6-§3.6 vor Welle-7-§3)
- [ ] Cross-Modul-Stress-Test Wednesday-Run gruen (Pflicht aus ADR-0066 §Mitigations, symmetric A7)
- [ ] **NATS-JetStream-Konnektivitaet 24h pre-Cutover stabil** (Welle-6-spezifisch, §1 R-2 Mitigation)
- [ ] **Phase-3c-Marathon-Closure-Bewusstsein:** Welle-7-Sign-Off-Green schliesst Marathon ab; Welle-6 ist nicht der Schluss-Stempel aber blockiert ihn bei Rollback

---

## Anhang C — Welle-6-spezifische Cross-Spawn-Coordination (Tag-39)

Tag-39 hat parallele Spawns laufen lassen (Continuous-Mode, KW-27
Final-Doppel-Welle-Vorbereitung):

| Spawn | Owner | Artefakt | Pfad |
|---|---|---|---|
| Welle-6-Operator-Runbook (dieses Dokument) | Kai | `docs/phase-3c/welle-6-subscribe-loop-runbook.md` | dieses File |
| Welle-6-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh` | Pfad in §2 zitiert (parallel Tag-39) |
| Welle-7-Operator-Runbook (Bundle-Partner) | Kai | `docs/phase-3c/welle-7-recovery-workflow-runbook.md` | gleicher Bundle-PR Tag-39 |
| Welle-7-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh` | Selin parallel Tag-39 |
| Tomás-Tag-39-Workflow-Adjustment (Welle-6+7) | Tomás | CI-Workflow-Validation | siehe Tomás-Tag-39-Liefer-Bericht |
| Reza-Tag-39-Substrate (Welle-6+7 Substanz) | Reza | Substanz-Coverage-Spawn (ADR-0068-Migration) | siehe Reza-Tag-39-Liefer-Bericht |
| Amara-Tag-39-Doppel-Welle-Closure-E2E | Amara | E2E-Closure-Acceptance-Suite | siehe Amara-Tag-39-Liefer-Bericht |
| Henrik-Tag-39-Marathon-Closure-Audit-Prep | Henrik | Audit-Trail-Pre-Closure-Review | siehe Henrik-Tag-39-Liefer-Bericht |

Pre-Cutover-Cross-Spawn-Verifikation (in §1 implizit, hier
explizit gelistet): alle Tag-37+38+39-Artefakte muessen auf main
gemerged sein vor Welle-6-Wednesday-Validation-Run-Trigger
(KW-26-Mittwoch 2026-06-24).

---

## Anhang D — Symmetric-Coordination-Stub zu Welle-7

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
| §3.2.5 Pre-Verify | Subscribe-Cursor-Snapshot-Hash | Recovery-Drill-Pre-Snapshot (R1..R4-Histograms) |
| §3.2.7 Pre-Step (Welle-6-only) | Pre-Drain (in_flight==0 innerhalb 60s) | (keine analoge Pflicht — Recovery hat Drill-Pre-Snapshot statt) |
| §3.6 Post-Verify | Subscribe-Loop-Resume-Verify (Sub-Status + Cursor + Ack-Rate) | R1..R4-Drill-Post-Verify (Recovery-Latency-Histogramm-Match) |
| T-3 Trigger | Lag>90s ODER Output-Reply-p99>45s ODER Drain-Hang | Recovery-Drill-Fail (R1..R4-Phase-Excursion) |
| T-4 Trigger Paired-Component | `recovery` | `subscribe_loop` |
| Cross-Modul-§4.4 Target | subscribe_loop × recovery | recovery × subscribe_loop (symmetric) |
| AR-Hand-Stop-Bedingungen | 3 (§6 exit-3 Cursor-Regression, §3.2.7 Drain-Abort, T-4 + Cross-Welle-Coordination-Fail) | siehe Welle-7-Runbook §8 |
| Phase-3c-Marathon-Schluss-Stempel | blockiert ihn bei Rollback | **setzt ihn** bei Sign-Off-Green |

**Doppel-Welle-Cross-Spawn-Pflicht:** Welle-6 und Welle-7 muessen
gemeinsam Sign-Off (mind. yellow) erreichen, damit der Phase-3c-
Marathon-Closure-Flag (`phase_3c_complete: true`) gesetzt werden
kann. Ein einseitiger green-Sign-Off (z.B. Welle-6 green, Welle-7
rollback) blockiert den Marathon-Schluss-Stempel.

**Phase-3c-Marathon-Schluss-Stempel (Plan): Montag 2026-06-29
17:00 CEST.** Bei Welle-6 ODER Welle-7-Rollback verschiebt sich
das auf KW-28 (~2026-07-06 Montag, Re-Schedule durch AR).

---

— Kai Hoffmann (DevOps), Sprint-Tag-39, 2026-05-18.
