---
title: "Phase-3c Welle-5 lifecycle_state_machine Operator-Cutover-Runbook"
owner: "Kai Hoffmann (DevOps), Tomas Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065, 0066"
welle: 5
component: "lifecycle_state_machine"
component_short: "fsm"
env_var: "WAKIR_FSM_BACKEND"
env_value_cutover: "rust"
cutover_date: "2026-06-22"
cutover_window_cest: "10:00-14:00"
soak_window_minutes: 15
hairpin_rollback_window_cest: "Mi 09:00-13:00"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 38
parallel_welle: 4
parallel_welle_component: "state_backing"
parallel_welle_env_var: "WAKIR_STATE_BACKING_BACKEND"
sequence_after: "welle-4-§3.6 (Post-Restart-State-Read-Verify)"
risk_class: "doppel-welle-cross-modul-drift + fsm-phantom-transitions"
---

# Phase-3c Welle-5 lifecycle_state_machine Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-5-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die
`lifecycle_state_machine`-Komponente der Persona-Engine, 6. emittierte
`BackendDecision` — kurz `fsm` in In-Repo-Resolvern/Dry-Run-Scripts).
Ziel-Cutover-Datum: Montag 2026-06-22, KW-26, **parallel** zu
Welle-4 (`state_backing`) gemaess ADR-0066 §Option-A+, mit
**Sequenz-Constraint** (Welle-5-§3 startet nach Welle-4-§3.6).

Dies ist das **operative Day-Of-Skript**. Hermetic-Validierung
(`phase-3c-welle-5-validation.yml`) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-5-runbook.md`](../operations/phase-3c-welle-5-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM, echter
NATS-Bus, echte Quadlet-Restart-Sequenz, echte FSM-Transition-
Integritaets-Beobachtung.

Schwester-Runbook fuer Welle-4 (parallel-Cutover-Coordination):
- [`welle-4-state-backing-runbook.md`](./welle-4-state-backing-runbook.md)
  (PR #243, Tag-37, Welle-4 `state_backing` KW-26 Montag parallel zu Welle-5).

Vorgaenger-Runbooks (Phase-3c-Sequenz):
- [`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md)
  (PR #228, Tag-34, Welle-1 `v907_verify` KW-24 Montag parallel zu Welle-2).
- [`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md)
  (PR #232, Tag-35, Welle-2 `svid_workload_identity` KW-24 Montag parallel zu Welle-1).
- [`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md)
  (PR #237, Tag-36, Welle-3 `bridge_audit_writer` KW-25 Montag solo Henrik-Caution).
- [`welle-4-state-backing-runbook.md`](./welle-4-state-backing-runbook.md)
  (PR #243, Tag-37, Welle-4 `state_backing` KW-26 Montag, paralleler Doppel-Welle-Partner).

## Welle-5-Charakter (lifecycle_state_machine-spezifisch)

**Welle-5 ist die erste Welle in der die zu cutover'nde Komponente
eine deterministische Finite-State-Machine ist.** Vorgaenger-Wellen
sind alle entweder Verify-Computation (v907_verify), Identity-
Resolution (svid), Sink-Pfad (bridge_audit_writer) oder Read-Write-
State-Substrate (state_backing). FSM dagegen ist Transition-Logik:
sechs States, neun Transitionen (spec §3.3), guarded durch
`_VALID_TRANSITIONS`. Ein falscher Backend-Pfad produziert nicht
nur Performance-Drift sondern **Phantom-Transitions** — Transitions
die im laufenden System sichtbar werden, aber im Spec-Set nicht
existieren.

**Drei lifecycle_state_machine-spezifische Charakteristika:**

1. **Single-Value-Variant (`rust`, nicht `rust_inmemory`)** — der
   Resolver `resolve_fsm_backend` akzeptiert nur die Standard-
   Werte aus `VALID_FSM_BACKEND_VALUES` (`python` ODER `rust`),
   nicht die Welle-4-Doppel-Variant (`rust_inmemory` vs
   `rust_natskv`). Welle-5-Env-Overlay setzt
   `WAKIR_FSM_BACKEND=rust` (siehe
   `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE`
   Zeile 202).
2. **FSM-Transition-Integrity-Pre-Verification + Post-Verify** — vor
   Restart wird der aktuelle FSM-State-Plus-Transitions-Counter im
   Python-Backend-Pfad als immutable Snapshot erfasst (§3.2.5),
   nach Restart prueft §3.6 dass der Rust-Backend dieselben
   Transitions emittiert und keine Phantom-Transitions im Boot-
   Stream auftauchen. State-Backing schreibt durch FSM-Transitions
   — wenn beide Backend-Wechsel gleichzeitig laufen, ist eine
   Transition-Drift nur durch sequenzielle Verifikation isolierbar.
3. **Cross-Modul-Drift zu Welle-4 (parallel, symmetric A7)** —
   `lifecycle_state_machine` schreibt durch `state_backing`
   (FSM-Transition persistiert via State-Backing). Symmetric zu
   Welle-4 §4.4 (state_backing × FSM): Welle-5 §4.4 prueft FSM ×
   state_backing aus der FSM-Perspektive. Mitigation: Cross-Modul-
   Stress-Test als §4.4 Soak-Step (Phase-2-Acceptance-Gate Step 6
   aus PR #197), identische 3-Achsen-Schwelle.

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ + Doppel-Welle-Constraint | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Welle-5 Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-5-validation.yml` |
| Welle-5 Sibling-Validation-Runbook | `docs/operations/phase-3c-welle-5-runbook.md` |
| Welle-1 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-1-v907-verify-runbook.md` (PR #228, Tag-34) |
| Welle-2 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-2-svid-workload-identity-runbook.md` (PR #232, Tag-35) |
| Welle-3 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-3-bridge-audit-writer-runbook.md` (PR #237, Tag-36) |
| Welle-4 Pre-Cutover-Operator-Runbook (paralleler Partner) | `docs/phase-3c/welle-4-state-backing-runbook.md` (PR #243, Tag-37) |
| Welle-5 Container-Image-Build-Pipeline | PR #167 (Tag-17) + Tag-33 Mini-Welle `fsm-welle5` Quadlet-Carrier-Update |
| FSM Cross-Lang-Hash-Parity-Pins | `tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json` |
| Resolver `resolve_fsm_backend` | `wirelang/persona_engine/rust_backend_switch.py` (`FSM_BACKEND_ENV` L428, `DEFAULT_RUST_FSM_BIN` L452) |
| Resolver-Variant-Map | `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE` (fsm -> rust) |
| Component-Alias-Map | `scripts/phase-3c-cutover-dry-run.py::PHASE_3C_COMPONENT_ALIASES` (`lifecycle_state_machine` -> `fsm`) |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Cross-Modul-Stress-Aggregator (Doppel-Welle-Pflicht) | `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress` (PR #197) |
| Quadlet-Inventar (9-Binary) | `quadlet/wakir-rust-cli.container` (`wakir-persona-engine-fsm` in Exec-Schleife L187) |
| Cosign-Policy (9-Binary) | `policies/cosign-policy-phase-3b.yaml` Zeile 236 `name: fsm`; Zeile 387 `name: fsm-welle5` (Tag-33 Mini-Welle) |
| Selin Welle-5 Cutover-Smoke-Skript | `scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh` (Selin Tag-38, parallel zu diesem Runbook) |
| FSM Modul | `wirelang/persona_engine/lifecycle_state_machine.py` |
| State-Backing Modul (Welle-4-Cross-Modul-Anker) | `wirelang/persona_engine/state_backing.py` (via Welle-4-Runbook konkretisiert) |
| Welle-5-Telemetry-Runbook | `docs/operations/welle-5-telemetry-runbook.md` (falls vorhanden — sonst Welle-4-Telemetry-Runbook als Cross-Anker) |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya.

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar 9-Binary)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `fsm` mit `component: persona-engine-fsm` und
      `in_image_path: /opt/wakir/bin/wakir-persona-engine-fsm`
      (Zeile 236). Tag-33 Mini-Welle ergaenzt einen `fsm-welle5`-
      Variant-Eintrag (Zeile 387) mit demselben Crate-Pfad.
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 9 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` Zeile 187 listet
      `wakir-persona-engine-fsm` in der `Exec=`-Schleife des
      Installer-Containers. Tag-33 Mini-Welle ergaenzt
      `wakir-persona-engine-fsm-welle5`-Variant-Pin
      (Carrier-Image-Verifikation via `sha256sum-checks`-Probe).
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence: `wirelang/persona_engine/rust_backend_switch.py`
      enthaelt `FSM_BACKEND_ENV =
      "WAKIR_FSM_BACKEND"` (L428) und `DEFAULT_RUST_FSM_BIN ==
      /opt/wakir/bin/wakir-persona-engine-fsm` (L452). Resolver
      akzeptiert nur Standard-Werte `python` ODER `rust` (siehe
      `VALID_FSM_BACKEND_VALUES` L633 — kein Welle-4-Doppel-Variant).
      Engine-Boot-Audit emittiert 6. `BackendDecision` mit
      `component=fsm` (in-repo short form) bzw.
      `lifecycle_state_machine` (long-form Alias).
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet, GitHub-Runner-Baseline-File nicht).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — gruen. Evidence:
      `tests/integration/test_bridge_audit_roundtrip_e2e.py` passt
      (oder all-SKIP auf Runner ohne replay_cli-Binary). FSM-
      Transition-Audit-Annotation wird emittiert.
- [ ] **Welle-5-Wednesday-Validation-Run gruen** (2026-06-17
      06:00 UTC, KW-25 Mittwoch — 5 Tage vor Cutover-Montag KW-26).
      Evidence: `cutover-acceptance-decision-welle-5.json`
      `ready_for_live_smoke == true` UND `cross_modul_stress_passed
      == true` (Step 6 PR #197). Artifact-Retention 30 Tage.
      Workflow: `.github/workflows/phase-3c-welle-5-validation.yml`.
- [ ] **Welle-3-Sign-Off-Verdict bekannt** (KW-25 Montag,
      mind. `green` ODER `green-with-yellow-notes-mit-Henrik-Hand-
      Approval` Pflicht — symmetric Welle-4-§1-Bedingung). Drei
      zulaessige Zustaende fuer Welle-5-Trigger:
      - **(a) Welle-3 `green` Sign-Off** — Welle-5 startet planmaessig KW-26 Montag.
      - **(b) Welle-3 `green-with-yellow-notes` + Henrik-Hand-Approval-File** —
        Welle-5 startet, aber Mira-Hand-Decision-Point mit
        explizitem Yellow-Notes-Review im Cutover-Window.
      - **(c) Welle-3 `rollback` ODER `ar-hand-stop`** — Welle-4+5
        wird BLOCKIERT, nicht gestartet. AR-Eskalation Pflicht
        (§9 R-6). Begruendung: FSM-Transitions emittieren Audit-
        Annotations in den Bridge-Audit-Stream (Welle-3-Substrate);
        ein Welle-3-Rollback bedeutet die Audit-Substrate ist nicht
        stabil — Welle-5-FSM-Transition-Audit waere unverlaesslich.
- [ ] **Welle-4-Cutover-Status verifiziert (Doppel-Welle-Sequenz-Constraint, Welle-4 zuerst)** —
      Welle-5-§3 darf erst starten **nach Welle-4-§3.6 Post-
      Restart-State-Read-Verify** (siehe §3.0). Drei zulaessige
      Zustaende fuer Welle-5-Trigger relativ zu Welle-4:
      - **(a) Welle-4-§3.6 green (Hash-Match Pre==Post)** —
        Welle-5-§3 startet planmaessig KW-26 ~11:00 CEST.
      - **(b) Welle-4-§3.6 yellow (Boot-Audit-OK aber sekundaere
        Yellow-Trigger im Aggregator/Latency)** — Mira-Hand-Decision
        ob Welle-5 mit Cross-Modul-Coupling fortfaehrt oder solo-
        verschiebt. Doppel-Welle-Coupling stark: Drift in Welle-4-
        State-Substrate macht Welle-5-FSM-Transition-Persistenz
        unverlaesslich.
      - **(c) Welle-4-§3.6 red (Hash-Drift, T-3 Rollback)** —
        Welle-5-Cutover wird **NICHT** gestartet. Welle-4-Rollback
        und Welle-5-Verschiebung auf KW-27 oder spaeter
        (Re-Schedule mit Welle-4-§6-Sign-Off als Re-Trigger).
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, **post-Welle-1+2+3 Engine-Posture und vor Welle-4-
      Cutover-Start**). Latency-p50/p95, Error-Rate,
      BackendDecision-Volume pro Minute, FSM-Transition-Rate
      pro Minute, FSM-Transition-Type-Distribution (welche der
      9 Spec-Transitions wie oft). Persistiert in
      `/var/lib/wakir/baselines/welle-5-pre-cutover-<TS>.json`.
      **Wichtig:** Die Baseline wird **nach KW-24+25-Sign-Off
      und vor Welle-4+5-KW-26-Cutover-Start** frisch aufgezeichnet.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component fsm --window 5m --format json` liefert gueltige
      Records mit `backend=python` >99% (Baseline).
- [ ] **Quadlet 9-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 9 Binaries inklusive
      `wakir-persona-engine-fsm`.
- [ ] **Cosign-Policy 9-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit.
      Das transitiv-verifizierte Image-Manifest umfasst fsm-Image
      (sowohl Tag-17-Origin `fsm` als auch Tag-33-Variant
      `fsm-welle5`).
- [ ] **FSM Cross-Lang-Hash-Parity-Pins frisch**.
      Evidence: `tests/fixtures/lifecycle-state-machine-cross-lang/
      fixtures.json` existiert, Pin-Count ≥ 5 (`fixtures` Liste
      im Dict). Das ist die Baseline-Referenz fuer §4.2 Cross-
      Lang-Hash-Parity-Probe.
- [ ] **Cross-Modul-Stress-Test Wednesday-Run gruen** (Doppel-Welle-
      Pflicht aus ADR-0066 §Mitigations, symmetric zu Welle-4-§1).
      Evidence: Welle-5-Validation-Workflow Step 6
      (`doppelbetrieb-score-aggregator --mode=cross-modul-stress`)
      hat alle 3 Achsen `>= threshold`:
      - `cross-lang-pin-coverage` (lifecycle_state_machine x state_backing)
      - `cross-modul-fixture-stability`
      - `cross-modul-rollup-integrity`
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt** —
      Mittwoch KW-26, 09:00-13:00 CEST (4h-Slot, identisch zu
      Welle-4 wegen Doppel-Welle-Cross-Modul-Drift-Koordination).
      **Welle-4+5 teilen sich denselben Rollback-Slot** —
      parallel-Rollback ist explizit erwartet bei T-4 Cross-Modul-
      Trigger.

---

## §2 Pre-Flight-Smoke

Selin's Welle-5-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet zur
Pilot-VM testet und kein Pilot-internes Artefakt ist. Skript
liefert Selin **parallel zu diesem Runbook** (Tag-38 Cross-Spawn).

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component lifecycle_state_machine \
    --component-short fsm \
    --env-var WAKIR_FSM_BACKEND \
    --env-value rust \
    --parallel-welle 4 \
    --cross-modul-stress-axis lifecycle_state_machine,state_backing \
    --sequence-after-welle 4 \
    --dry-run-window 5m \
    --json-out /tmp/welle-5-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten **nach
  Welle-4-§3.6**.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated ODER Welle-3-`green-with-yellow-notes` post-hoc).
  Mira-Hand-Decision noetig vor §3.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Tomás (Matrix-Lead). **Bei red: kein Cutover-
  Versuch ohne Henrik-Hand-Override.**

Das JSON-Envelope (`/tmp/welle-5-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~3-5 min wall-clock (laenger als Welle-1/2
wegen Cross-Modul-Stress-Axis-Sample und FSM-Transition-Sanity-
Probe). Skript prueft SSH-Reachability, Quadlet-Status-Snapshot,
Cosign-Policy-Match (9-Binary), Engine-Health-Baseline-Delta gegen
Tag-N-1, FSM-Transition-Counter-Sanity (alle 9 Spec-Transitions
seit Engine-Start gesehen?), BackendDecision-Aggregator-Sanity fuer
`component=fsm` (long-form `lifecycle_state_machine`), Cross-
Modul-Stress-Smoke (FSM × state_backing 3-Axen-Sample). Keine
Side-Effects auf Pilot-VM (read-only).

**Welle-4+5-Parallel-Hinweis:** Welle-5 und Welle-4 starten am
selben Cutover-Tag KW-26 Montag. Pre-Flight-Smokes Welle-5 und
Welle-4 duerfen parallel laufen, **aber** §3 Cutover-Step Welle-4
+ §3 Cutover-Step Welle-5 sind seriell-koordiniert: Welle-5-§3
beginnt erst nach Welle-4-§3.6 (siehe §3.0 Doppel-Welle-Sequenz).
Begruendung: FSM-Transition schreibt durch State-Backing. Wenn
beide Backends gleichzeitig flippen, ist eine FSM-Phantom-
Transition nicht unterscheidbar von einer State-Backing-Read-
Failure beim Engine-Restart.

---

## §3 Cutover-Step

**Mira-Hand-SSH-Authority** gemaess ADR-0058 §Nachtrag. AR-
Eskalations-Override nur fuer `irreversible despawn`-Pfade —
Quadlet-Restart und Env-Overlay fallen darunter **nicht**, das
ist routine Operator-Hand-Operation.

**Welle-5-spezifische Erweiterung:** §3.2.5 FSM-State-Persistence-
Pre-Verification (Engine schreibt im Python-FSM-Backend einen
FSM-State-Plus-Transition-Counter-Snapshot; reboot mit Rust-FSM-
Backend; Transition-Integrity-Validation in §3.6). Ohne diesen
Step ist eine FSM-Phantom-Transition nicht unterscheidbar von
einer Boot-Failure.

**Schritt 3.0 — Doppel-Welle-Sequenz (Welle-4 zuerst, Welle-5 folgt)**

Welle-5-Cutover beginnt **nach** Welle-4-§3.6 Post-Restart-State-
Read-Verify. Begruendung: `lifecycle_state_machine` schreibt durch
`state_backing`; wenn beide gleichzeitig flippen, ist eine
State-Backing-Read-Failure beim Engine-Restart nicht unterscheidbar
von einer FSM-Init-Failure. Sequenz garantiert, dass Welle-4-Rust-
Backend stabil ist bevor Welle-5-Rust-FSM-Backend Transitions
schreibt.

Welle-5-Cutover-Step §3.1 startet erst nach Welle-4-§3.6 PRE_HASH
== POST_HASH Match.

**Schritt 3.1 — SSH auf Pilot-VM**

```bash
ssh root@192.168.178.116
# Erwarteter Banner: "wakir-pilot — FCOS — Phase-3b live"
```

**Schritt 3.2 — Pre-Restart-Snapshot (post-Welle-1+2+3+4)**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-5 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-5-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-5-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-5-cutover-pre-journal.txt

# Welle-1+2+3+4-State-Check: bestaetige dass v907_verify + svid +
# anchor_emitter + state_backing backend=rust (bzw. rust_inmemory)
# laufen.
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -cE "BackendDecision.*(v907_verify|svid_workload_identity|anchor_emitter|state_backing).*backend=(rust|rust_inmemory)" \
  | tee -a /var/log/wakir/welle-5-cutover.log
# Erwartung: > 0 Records pro Component (vier separate Linien).
```

**Schritt 3.2.5 — FSM-State-Persistence-Pre-Verification (Welle-5-spezifisch)**

**Kritisch.** Vor dem Restart muss der aktuelle FSM-State-Plus-
Transition-Counter im Python-Backend-Pfad als immutable Snapshot
erfasst werden. Wenn der Rust-FSM-Backend nach Restart Phantom-
Transitions emittiert oder den Pre-Cutover-FSM-State nicht zur
gleichen kanonischen Form deserialisiert, ist die Engine in einem
inkonsistenten Zustand — Rollback gegen diese Baseline garantiert
deterministische Recovery.

```bash
# Auf Pilot-VM:
mkdir -p /var/lib/wakir/welle-5-fsm-baseline

# 1. FSM-State + Transition-Counter via CLI-Tool (Python-Backend-Pfad)
/opt/wakir/bin/wakir-persona-engine-fsm \
    --mode=snapshot \
    --backend=python \
    --output=/var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.json
wc -c /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.json \
    | tee -a /var/log/wakir/welle-5-cutover.log

# 2. Hash der FSM-Baseline (SHA-256 fuer immutability-Verify in §3.6 + §6)
sha256sum /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.json \
    | tee /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.sha256 \
    | tee -a /var/log/wakir/welle-5-cutover.log

# 3. FSM-Schema-Version + Transition-Spec-Version erfassen
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
  | grep -E "fsm.*(schema_version=|spec_version=)" \
  | tail -3 \
  | tee /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-spec-version-${TS_PRE}.txt

# 4. Transition-Type-Distribution (welche der 9 Spec-Transitions
# wie oft seit Engine-Start). Cross-Check fuer §3.6 Post-Restart.
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -oE "fsm.transition=[a-z_]+" \
  | sort | uniq -c \
  | tee /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-transition-dist-${TS_PRE}.txt
```

**Erwartete Evidenz:** Snapshot-File-Size > 0, Hash protokolliert,
Schema-Version bekannt, Transition-Type-Distribution erfasst (mind.
3 der 9 Spec-Transition-Types gesehen — Engine-Tier-1-Baseline).
Wenn Snapshot 0 Bytes hat ODER Transition-Type-Distribution
0 Lines hat: STOP — FSM ist bereits vor Cutover unhealthy, das
ist ein Pre-Cutover-Red und §6 ist nicht der richtige Pfad
(Reza + Henrik eskalieren, Cutover absagen).

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht in-place
edit. Reversibel, ADR-0058-konform. **Welle-5-spezifisch:** Env-
Wert ist `rust` (Single-Variant, kein Welle-4-Doppel-Variant).

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-5-lifecycle-state-machine-rust.conf <<'EOF'
# Phase-3c Welle-5 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-Sequenz, ADR-0066 §Option-A+
# lifecycle_state_machine (in-repo short form: fsm) Variant: rust
[Service]
Environment="WAKIR_FSM_BACKEND=rust"
EOF
systemctl daemon-reload

# Sanity-Check: Welle-1 + Welle-2 + Welle-3 + Welle-4 Drop-Ins existieren weiterhin.
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet:
#   welle-1-v907-verify-rust.conf
#   welle-2-svid-workload-identity-rust.conf
#   welle-3-bridge-audit-writer-rust.conf
#   welle-4-state-backing-rust.conf
#   welle-5-lifecycle-state-machine-rust.conf  (neu)
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-5-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s, 9/9 BackendDecisions, fsm rust)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust` und `component=fsm` (oder `lifecycle_state_machine`
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
    # accept either in-repo short form (component=fsm) or
    # ADR-0065 long form (component=lifecycle_state_machine).
    if ("BackendDecision" in msg
            and ("component=fsm" in msg or "component=lifecycle_state_machine" in msg)
            and "backend=rust" in msg
            and "backend=rust_inmemory" not in msg):  # disambiguate from welle-4
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision fsm rust records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

**Schritt 3.6 — Post-Restart-FSM-Transition-Integrity-Verify (Welle-5-spezifisch)**

Spezifisch fuer Welle-5: nach Restart muss der Rust-FSM-Backend (a)
denselben Pre-Cutover-FSM-State-Snapshot **deserialisieren koennen**
und denselben kanonischen Hash liefern, UND (b) **keine Phantom-
Transitions** im Boot-Stream emittieren (alle beobachteten
Transitions muessen zur Spec-Set `_VALID_TRANSITIONS` gehoeren).

```bash
# Auf Pilot-VM:
PRE_HASH=$(grep -oP '^[a-f0-9]{64}' \
    /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.sha256)
echo "Pre-Cutover-FSM-Hash: ${PRE_HASH}" | tee -a /var/log/wakir/welle-5-cutover.log

# (a) Rust-FSM-Backend State-Read via CLI-Tool
/opt/wakir/bin/wakir-persona-engine-fsm \
    --mode=verify-read \
    --backend=rust \
    --input=/var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.json \
    --output=/var/lib/wakir/welle-5-fsm-baseline/post-cutover-fsm-rust-${TS_PRE}.json
POST_HASH=$(sha256sum /var/lib/wakir/welle-5-fsm-baseline/post-cutover-fsm-rust-${TS_PRE}.json \
    | grep -oP '^[a-f0-9]{64}')
echo "Post-Cutover-FSM-Hash: ${POST_HASH}" | tee -a /var/log/wakir/welle-5-cutover.log

if [ "${PRE_HASH}" != "${POST_HASH}" ]; then
    echo "FSM-STATE-READ-COMPATIBILITY-FAIL: hash drift between python-write and rust-read" >&2
    echo "  PRE=${PRE_HASH}  POST=${POST_HASH}" >&2
    exit 2
fi
echo "FSM-STATE-READ-COMPATIBILITY-OK: hash match between python-write and rust-read"

# (b) Phantom-Transition-Scan: scan post-restart journal for ANY
# fsm.transition= value NOT in the 9-Spec-Set.
SPEC_TRANSITIONS=$(/opt/wakir/bin/wakir-persona-engine-fsm \
    --mode=dump-spec-transitions \
    | tr '\n' '|' | sed 's/|$//')
echo "FSM-Spec-Transitions (9): ${SPEC_TRANSITIONS}" \
    | tee -a /var/log/wakir/welle-5-cutover.log

journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" --no-pager \
  | grep -oE "fsm.transition=[a-z_]+" \
  | sort -u \
  | tee /var/lib/wakir/welle-5-fsm-baseline/post-cutover-observed-transitions-${TS_PRE}.txt

PHANTOM=$(journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" --no-pager \
  | grep -oE "fsm.transition=[a-z_]+" \
  | sort -u \
  | grep -vE "^fsm.transition=(${SPEC_TRANSITIONS})$" || true)
if [ -n "${PHANTOM}" ]; then
    echo "FSM-PHANTOM-TRANSITION-DETECTED:" >&2
    echo "${PHANTOM}" >&2
    exit 2
fi
echo "FSM-PHANTOM-TRANSITION-SCAN-OK: only spec-set transitions observed"
```

Wenn Boot-Audit-Wait-Loop oder FSM-State-Read-Compatibility oder
FSM-Phantom-Transition-Scan Exit ≠ 0: sofort §6 Rollback-Procedure.

---

## §4 Post-Cutover-Verification (15-min Soak-Window)

Soak-Window **15min** (Welle-1/2/4-Standard, kein 30-min wie
Welle-3 da kein Self-Reference-Risk; aber doppel-welle-symmetric
zu Welle-4). Vier parallele Beobachtungs-Streams plus Cross-Welle-
Coupling-Monitor, jede mit harter Schwelle und Rollback-Trigger.
**Welle-5-spezifisch:** §4.4 Cross-Modul-Drift-Check gegen Welle-4
(`state_backing`) ist Pflicht-Step im Doppel-Welle-Pattern,
symmetrisch zu Welle-4-§4.4 (A7-Symmetrie aus Selin-Welle-4-Smoke-
Skript).

**§4.1 — BackendDecision-Aggregator Sliding-Window**

```bash
# Auf Mira-Box, gegen Pilot-NATS:
cd /var/home/fred/AI-Corp/wakir-runtime
python3 scripts/phase-3c/backend-decision-aggregator.py \
    --component fsm \
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

FSM Cross-Lang-Hash-Parity-Pins (`tests/fixtures/lifecycle-state-
machine-cross-lang/fixtures.json`). Im Soak-Window: 5 Synthetik-
FSM-Transition-Hash-Calls, jede mit Python-Vergleichs-Hash gegen
die Pin-Baseline.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component fsm \
    --samples 5 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json \
    --canonical-module wirelang.persona_engine.lifecycle_state_machine
```

Erwartung: 5/5 Hashes match. Jede Drift => sofort §6 Rollback.

Hintergrund: die Cross-Lang-Parity prueft die deterministische
JCS-Kanonisierung der FSM-Transition-Envelopes (welcher State zu
welchem State plus Transition-Type). Drift heisst: Python- und
Rust-Side haben unterschiedliche Canonical-Forms — das ist ein
blocker-level Bug fuer FSM-Transition-Persistence-Continuity.

**§4.3 — FSM Transition-Error-Freiheit + Latency**

```bash
# Auf Pilot-VM:
journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" \
    -p err --no-pager \
    | grep -E "fsm|lifecycle_state_machine" \
    | tee /var/log/wakir/welle-5-fsm-errors.txt
wc -l /var/log/wakir/welle-5-fsm-errors.txt
```

Grafana-Dashboard `Persona-Engine — Backend Latency by Component`.
Filter: `component=fsm`, `backend=rust`, last 15min.

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

Operator: Screenshot pro 5min-Slice (3 Screenshots gesamt) + JSON-
Export an Henrik-Audit-Trail anhaengen.

Erwartung: 0 Error-Zeilen im 15-min-Soak-Window. Jede Error-Zeile
= automatischer §6 Rollback.

Zusatz-Probe (Welle-5-spezifisch): Phantom-Transition-Stream-Live-
Scan im Soak-Window (analog §3.6 (b), aber als laufender Stream).
Jede Phantom-Transition im Soak-Window = T-3 Rollback-Trigger.

```bash
# Auf Pilot-VM, paralleler Stream-Filter im Soak-Window:
SPEC_TRANSITIONS=$(/opt/wakir/bin/wakir-persona-engine-fsm --mode=dump-spec-transitions \
    | tr '\n' '|' | sed 's/|$//')
timeout 900 journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" -f --no-pager \
  | grep -oE "fsm.transition=[a-z_]+" \
  | grep -vE "^fsm.transition=(${SPEC_TRANSITIONS})$" \
  | tee /var/log/wakir/welle-5-phantom-transitions-soak.txt &
PHANTOM_PID=$!
echo "Phantom-Transition-Watcher PID: ${PHANTOM_PID}"
```

**§4.4 — Cross-Modul-Drift-Check gegen Welle-4 state_backing (Welle-5-spezifisch, symmetric A7)**

Welle-5-exklusiv (im Doppel-Welle-Pattern, symmetric zu Welle-4-
§4.4): `lifecycle_state_machine` steht in direkter Schreibe-
Korrelation mit `state_backing` (FSM-Transition schreibt durch
State-Backing). Wenn Welle-4+5 parallel cutover: ein Schema-Drift
in einem der beiden Substrate emergiert als Cross-Modul-Drift
gegen den anderen.

```bash
# Auf Mira-Box:
python3 scripts/doppelbetrieb-score-aggregator.py \
    --mode=cross-modul-stress \
    --threshold 3 \
    --target-component lifecycle_state_machine \
    --paired-component state_backing \
    --pilot 192.168.178.116 \
    --json-out /tmp/welle-5-cross-modul-drift.json
echo "cross-modul-drift-exit=$?"
```

Erwartung: 3-of-3 Cross-Modul-Achsen `>= threshold`:
- `cross-lang-pin-coverage` (FSM × state_backing cross-lang
  fixtures)
- `cross-modul-fixture-stability` (FSM-Transition-State-Backing-
  Roundtrip)
- `cross-modul-rollup-integrity` (Welle-4+5-Aggregate-Health)

Exit 0 = green; Exit non-zero = red (sofort Rollback, plus Welle-4-
Rollback-Koordination weil Doppel-Welle-Coupling — siehe §6
Schritt 5).

**§4.5 — Doppel-Welle-Coupling-Monitor (Welle-4-Cross-Status)**

```bash
# Auf Mira-Box, liest Welle-4-Cutover-Log (parallel-Cutover):
ssh root@192.168.178.116 'tail -50 /var/log/wakir/welle-4-cutover.log'
```

Erwartung: Welle-4-Soak-Window-Status (§4.1-§4.5 Welle-4-Runbook)
laeuft sauber. Wenn Welle-4 im Soak-Window-Beginn von Welle-5
einen sekundaeren yellow-Trigger hat: Mira-Hand-Decision-Point
(Welle-5-Soak-Window fortfuehren oder Welle-5 parallel-Rollback
einleiten).

**Cross-Welle-Yellow-Bedingung:** Wenn Welle-4 Rollback-Trigger
hat aber Welle-5 OK ist: Welle-5 setzt Soak-Window fort, aber
Welle-4-Rollback wird parallel triggered. Cross-Modul-Drift-Check
§4.4 wird trotzdem ausgefuehrt — bei drift `> 0` mit Welle-4-
Rollback im Hintergrund: yellow (Mira-Hand-Decision).

---

## §5 Rollback-Trigger — Exit-Decision-Matrix

Fuenf harte Trigger (drei Standard, zwei Welle-5-spezifisch). Bei
JEDEM einzelnen Trigger: sofort §6, keine Diskussion, keine
Eskalations-Verzoegerung. Mira-Hand entscheidet im Cutover-Window
autark, AR-Override nur post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.3) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | FSM-Service ERR-Zeile | Journal (§4.3) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | FSM-Transition-Inkonsistenz (Phantom-Transition ODER Post-Restart-Hash-Drift) | §3.6 + §4.3-Stream | Eine einzelne Phantom-Transition ODER Hash-Drift `PRE != POST` | Rollback (§6) |
| T-4 | Cross-Modul-Inkonsistenz mit state_backing | §4.4 Cross-Modul-Drift | Eine der 3 Achsen `< threshold` | Rollback (§6) + Welle-4-Koordinations-Marker |
| T-5 | Cross-Lang-Hash-Drift | §4.2 Parity-Probe | Jede einzelne Drift in 5 Samples | Rollback (§6) |

**T-3 Begruendung (Welle-5-spezifisch, FSM-Phantom-Transitions):**
FSM-Transition-Inkonsistenz ist nicht reine Performance — sie ist
Spec-Konformitaet. Eine Phantom-Transition (Transition die nicht
in den 9 Spec-Transitions ist) bedeutet: das Rust-FSM-Backend
emittiert eine Transition die im Python-Backend-Pfad nicht
existiert. Das ist entweder ein Rust-Bug (false-positive Transition)
oder ein Schema-Drift (Spec-Update nicht synchronisiert). Beide
Faelle sind blocker-level fuer FSM-Korrektheit. Rollback ist
Pflicht; keine yellow-Toleranz. Symmetric-Fall Hash-Drift (Rust-
FSM-State liest Python-FSM-State zu anderer kanonischer Form) ist
ebenfalls T-3.

**T-4 Begruendung (Doppel-Welle-Cross-Modul, symmetric Welle-4 T-4):**
Cross-Modul-Drift gegen `state_backing` heisst entweder FSM-
Transition-Drift in Persistenz-Schicht ODER State-Backing-Schema-
Drift in Read-Pfad. Beide Faelle sind blocker-level fuer Engine-
State-Continuity. **Welle-4-Koordinations-Marker** wird gesetzt:
`/var/lib/wakir/audit-holds/welle-5-cross-modul-drift-<TS>.marker`
— Welle-4 muss entsprechend mit-rollback'n falls noch nicht stable.

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1 Exit 1).
- Latency p99 > 2.0× Baseline (§4.3 Warn-Schwelle).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  <0.1%).
- Welle-4-Sekundaer-Yellow waehrend Welle-5 OK (§4.5 Cross-Welle-
  Yellow, Mira-Hand-Decision).
- Transition-Type-Distribution-Drift (Rust-Backend emittiert
  Spec-Transitions, aber in einer auffaellig anderen Verteilung
  als Pre-Cutover-Baseline — z.B. eine seltene Transition wird
  ploetzlich haeufiger; das ist nicht spec-illegal, aber moeglicher
  Bug-Indikator).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt, Service-
Restart, Verify Backend=python, **FSM-Transition-Read-Verify
gegen Pre-Cutover-Baseline** (Welle-5-spezifischer FSM-Recovery-
Step). Welle-1+2+3+4-State bleibt unberuehrt — nur das Welle-5-
Overlay-File wird entfernt.

**Welle-4-Koordination:** Wenn T-4 Trigger (Cross-Modul-Drift mit
Welle-4): Welle-4-Rollback parallel mit Welle-5-Rollback. Schritt
5 unten beschreibt die Welle-4-Koordinations-Eskalation.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-5 Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-5-cutover.log

# Stop Phantom-Transition-Watcher (falls noch laufend aus §4.3)
kill -TERM "${PHANTOM_PID}" 2>/dev/null || true

# 1. Env-Overlay entfernen — NUR Welle-5-Drop-In, Welle-1+2+3+4 bleiben
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-5-lifecycle-state-machine-rust.conf
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet: welle-1-* + welle-2-* + welle-3-* + welle-4-* bleiben; welle-5-* weg.
systemctl daemon-reload

# 2. Service-Restart
systemctl restart wakir-persona-engine.service
TS_RB_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 3. Verify backend=python fuer fsm (5 BackendDecision-Records innerhalb 30s)
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
            and ("component=fsm" in msg or "component=lifecycle_state_machine" in msg)
            and "backend=python" in msg):
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified for fsm")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 4. FSM-State-Read-Verify gegen Pre-Cutover-Baseline (Welle-5-spezifisch).
# Python-FSM-Backend muss den Pre-Cutover-FSM-Snapshot wieder lesen koennen
# und denselben Hash liefern wie vor Cutover. Drift hier heisst:
# der Pre-Cutover-FSM-State ist nicht mehr verifizierbar lesbar — Engine-
# FSM-Korruption-Verdacht, AR-Hand-Stop-Marker Pflicht.
PRE_HASH=$(grep -oP '^[a-f0-9]{64}' \
    /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.sha256)
sleep 10  # Engine-Boot-Stabilisierung
/opt/wakir/bin/wakir-persona-engine-fsm \
    --mode=verify-read \
    --backend=python \
    --input=/var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-${TS_PRE}.json \
    --output=/var/lib/wakir/welle-5-fsm-baseline/post-rollback-fsm-python-${TS_RB}.json
POST_RB_HASH=$(sha256sum /var/lib/wakir/welle-5-fsm-baseline/post-rollback-fsm-python-${TS_RB}.json \
    | grep -oP '^[a-f0-9]{64}')
echo "Pre-Cutover-Hash: ${PRE_HASH}  Post-Rollback-Hash: ${POST_RB_HASH}" \
    | tee -a /var/log/wakir/welle-5-cutover.log

if [ "${PRE_HASH}" != "${POST_RB_HASH}" ]; then
    echo "ROLLBACK-FSM-CONTINUITY-FAIL: hash drift between pre-cutover python-write and post-rollback python-read" >&2
    echo "AR-HAND-STOP-MARKER required" >&2
    mkdir -p /var/lib/wakir/audit-holds
    touch /var/lib/wakir/audit-holds/welle-5-rollback-fsm-continuity-violation-${TS_RB}.marker
    exit 3   # exit-3 signalisiert AR-Hand-Stop-Marker, NICHT routine Rollback-Fail
fi

# 4b. Post-Rollback Phantom-Transition-Re-Scan (Welle-5-spezifisch):
# nach Rollback duerfen wieder NUR Spec-Transitions emittiert werden.
sleep 5
SPEC_TRANSITIONS=$(/opt/wakir/bin/wakir-persona-engine-fsm \
    --mode=dump-spec-transitions --backend=python \
    | tr '\n' '|' | sed 's/|$//')
PHANTOM_RB=$(journalctl -u wakir-persona-engine.service --since "${TS_RB_RESTART}" --no-pager \
  | grep -oE "fsm.transition=[a-z_]+" \
  | sort -u \
  | grep -vE "^fsm.transition=(${SPEC_TRANSITIONS})$" || true)
if [ -n "${PHANTOM_RB}" ]; then
    echo "ROLLBACK-PHANTOM-TRANSITION-DETECTED: ${PHANTOM_RB}" >&2
    echo "Python-FSM emittiert Phantom-Transitions — schwerer Spec-Drift, AR-HAND-STOP" >&2
    touch /var/lib/wakir/audit-holds/welle-5-rollback-phantom-transition-${TS_RB}.marker
    exit 3
fi
echo "ROLLBACK-PHANTOM-SCAN-OK: nur Spec-Transitions in Python-Backend nach Rollback"

# 5. Welle-4-Koordinations-Pruefung (Doppel-Welle-Coupling).
# Wenn T-4 Trigger (Cross-Modul-Drift): Welle-4-Rollback parallel triggern.
# Wenn nur T-1/T-2/T-3/T-5 Trigger (Welle-5-local): Welle-4 darf in-flight bleiben,
# aber Mira-Hand-Decision-Point ob Welle-4-Sign-Off ohne Welle-5-Counterpart sinnvoll.
if ls /var/lib/wakir/audit-holds/welle-5-cross-modul-drift-*.marker >/dev/null 2>&1; then
    echo "WELLE-4-COORDINATION-ROLLBACK required (T-4 Cross-Modul-Drift)" \
        | tee -a /var/log/wakir/welle-5-cutover.log
    # Welle-4-Rollback-Trigger: siehe Welle-4-Runbook §6 — Mira-Hand
fi

# 6. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-5 Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-5-cutover.log
```

**Eskalations-Schwelle bei Rollback-FSM-Continuity-Failure oder
Rollback-Phantom-Transition (exit-3):**
Wenn Schritt 4 oder 4b exit-3 meldet, ist das **kein**
routine-Rollback-Done sondern eine **AR-Hand-Stop-Marker-Bedingung**:

- FSM-State ist nicht mehr verifizierbar lesbar (Hash-Drift) ODER
  Python-FSM emittiert Phantom-Transitions.
- Marker-File `/var/lib/wakir/audit-holds/welle-5-rollback-(fsm-
  continuity-violation|phantom-transition)-*.marker` wird gesetzt.
- Eskalation Mira -> Priya -> AR sofort.
- Welle-4 (parallel KW-26) muss auch gestoppt werden bis FSM-
  Recovery-Decision vorliegt.
- Welle-6+7 (KW-27 geplant) ist blockiert.

Nach erfolgreichem Rollback (kein exit-3): 30-min Stabilitaets-
Beobachtung (Welle-1/2-Standard) mit BackendDecision-Aggregator
(§4.1, --target-backend python), FSM-Error-Monitor (§4.3), und
Cross-Modul-Drift-Check gegen Welle-4 (§4.4 mit aktuellem Welle-4-
Status). Dann §7 Sign-Off mit verdict=`rollback`, Root-Cause-
Analyse binnen 48h pflichtig:

- **Reza** — fsm Rust-CLI-Substrate-Owner, JCS-Canonical-Form-
  Drift-Investigation, FSM-Transition-Spec-Migration-Validation,
  Phantom-Transition-Root-Cause.
- **Tomás** — Cross-Modul-Korrelation mit state_backing.
- **Henrik** — Audit-Trail-Integrity, FSM-Continuity-Verify.

---

## §7 Sign-Off — Henrik-Audit-Trail

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off ist
Pflicht **vor Welle-6+7-Trigger** (KW-27 geplant). Welle-5-Sign-Off
korreliert mit Welle-4-Sign-Off (Doppel-Welle-Coupling).

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-5-smoke-*.json` (§2 Skript-Output)
- Welle-5-Wednesday-Validation-`cutover-acceptance-decision-welle-
  5.json` (§1, GitHub-Actions-Artifact-URL, mit
  `cross_modul_stress_passed == true`)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-5-pre-
  cutover-*.json` (post-Welle-1+2+3, pre-Welle-4-Cutover, frisch)
- BackendDecision-Aggregator-Snapshot (§1, Python-Default `fsm`
  ≥99%)
- **Pre-Cutover-FSM-Snapshot** (§3.2.5,
  `/var/lib/wakir/welle-5-fsm-baseline/pre-cutover-fsm-*.json`
  + SHA-256-Hash + Spec-Version + Transition-Type-Distribution)
- Welle-3-Sign-Off-Status (§1, Pflicht-Vorbedingung wegen Bridge-
  Audit-Substrate-Coupling)
- Welle-4-§3.6-Status (§1, Doppel-Welle-Sequenz-Constraint)

**TEL-Evidenz (waehrend §4 15-min Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1, 15-min Window JSON)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 5/5 oder Abweichung)
- FSM-Error-Count + Latency-Histogramm (§4.3, 0-Zeilen-File +
  3 Grafana-Screenshots + Phantom-Transition-Stream-Watcher-Output
  `welle-5-phantom-transitions-soak.txt`)
- Cross-Modul-Drift-Check-Output (§4.4,
  `/tmp/welle-5-cross-modul-drift.json`, 3/3 Achsen >= threshold
  Pflicht)
- Welle-4-Cross-Status-Snapshot (§4.5, Welle-4-Cutover-Log-Tail)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-5-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- FSM-State-Read-Verify-Output (§3.6 PRE_HASH == POST_HASH; bei
  Rollback §6 Schritt 4 PRE_HASH == POST_RB_HASH)
- FSM-Phantom-Transition-Scan-Output (§3.6 (b) leerer Phantom-Set;
  bei Rollback §6 Schritt 4b leerer Phantom-Set)
- Bei Rollback: Welle-4-Coordination-Status (parallel-Rollback ja/nein)
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`,
  oder **`ar-hand-stop`** bei exit-3 FSM-Continuity-Violation ODER
  Phantom-Transition-Post-Rollback)
- Welle-4-Sign-Off-Status (Cross-Welle-Korrelation)
- AR-Approval-Tag fuer Welle-6+7-Trigger (nur bei `green` ODER
  `green-with-yellow-notes` UND Welle-4-Sign-Off mind. yellow)

**Sign-Off-Template:**

```yaml
welle: 5
component: lifecycle_state_machine
component_short: fsm
variant: rust
cutover_date: 2026-06-22
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
verdict: green | green-with-yellow-notes | rollback | ar-hand-stop
yellow_notes: []
red_triggers_hit: []
# Welle-5-spezifische Achsen:
fsm_state_read_compatibility_hash_match: true | false  # MUSS true fuer green
fsm_phantom_transition_count: 0  # MUSS 0 fuer green (§3.6 (b) + §4.3-Stream)
cross_modul_drift_axes_pass: 3   # MUSS 3 fuer green (FSM x state_backing)
# Cross-Welle-Coupling:
welle_3_signoff_status: green | green-with-yellow-notes | rollback
welle_4_signoff_status: green | green-with-yellow-notes | rollback
welle_4_sequence_pre_§3_6_pass: true | false   # Pflicht-Vorbedingung fuer Welle-5-§3
# Evidenz-Pfade:
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
pre_cutover_fsm_sha256: <hash>
pre_cutover_transition_dist_file: /var/lib/wakir/welle-5-fsm-baseline/pre-cutover-transition-dist-*.txt
ar_approval_tag_for_welle_6_7: null  # gesetzt durch AR post-Sign-Off
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-5-lifecycle-state-machine-signoff-2026-06-22.yaml`

---

## §8 Mira-SSH-Hand-Authority + AR-Hand-Stop-Marker

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-Hand-
Authority fuer Pilot-VM-Operations.

**Mira-Hand-Operations (autark, identisch zu Welle-1-4):**
systemctl restart, Env-Overlay-File-Edits, Journal-Reads, Quadlet-
Override-Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
FSM-CLI-Snapshot-Creation (read-only), Phantom-Transition-Watcher-
Kill-Send (`kill -TERM ${PHANTOM_PID}`).

**AR-Hand-Operations (irreversibel-despawn, identisch zu Welle-1-4):**
`podman rm` ohne Backup, Volume-Wipe (`podman volume rm`), System-
Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade, Disk-
Repartitionierung.

**Welle-5-Neu — AR-Hand-Stop-Marker-Bedingungen:**

Vier Bedingungen triggern automatisch ein Marker-File und
sofortige AR-Eskalation (Mira -> Priya -> AR):

1. **Rollback-FSM-Continuity-Violation** (§6 Schritt 4 exit-3) — FSM-
   Snapshot nach Rollback nicht hash-verifizierbar zum Pre-Cutover-
   FSM-State.
2. **Rollback-Phantom-Transition-Post-Rollback** (§6 Schritt 4b
   exit-3) — Python-FSM emittiert nach Rollback Phantom-Transitions
   (Spec-Drift in Python-Backend).
3. **T-3 FSM-Transition-Inkonsistenz (Post-Restart)** — Engine-
   FSM-State korrupt durch Rust-Backend-Deserialisierung ODER
   Rust-Backend emittiert Phantom-Transitions.
4. **T-4 Cross-Modul-Drift + Welle-4-Coordination-Fail** — wenn
   Welle-4-Rollback nicht erfolgreich nach Welle-5-T-4-Trigger.

Marker-File-Pfad-Pattern:
`/var/lib/wakir/audit-holds/welle-5-<bedingung>-<TS>.marker`

Bei AR-Hand-Stop-Marker: Welle-6+7 (KW-27) sind blockiert bis
AR-Decision-Output vorliegt. Henrik-Hand-Forensik-Pflicht binnen
72h. Welle-4 muss parallel gestoppt werden.

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-Kombination):
   Mira-Hand-Decision autark. Henrik-Audit protokolliert.
2. **Substanz-Konflikt** (z.B. FSM-State-Read-Failure ODER Cross-
   Lang-Hash-Drift): Mira-Hand Rollback nach §6, dann Eskalation
   Mira -> Priya -> Reza (fsm-Rust-Substrate-Owner).
3. **FSM-Phantom-Transition-Detected (T-3 ODER Rollback exit-3
   Phantom)**: AR-Hand-Stop-Marker setzen, sofortige Mira -> AR-
   Eskalation, kein Welle-6+7-Trigger. Spec-Drift-Forensik durch
   Reza + Henrik.
4. **Cross-Modul-Drift mit Welle-4** (T-4): Welle-4-Koordinations-
   Marker, parallel-Rollback Welle-4+5, danach Eskalation Mira ->
   Priya -> Tomás (Cross-Modul-Korrelations-Owner).
5. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-Drop):
   Mira-Hand Rollback, dann Eskalation Mira -> AR fuer Recovery.

---

## §9 Bekannte Risiken

**R-1 — Cross-Modul-Drift zu Welle-4 parallel-Cutover (symmetric A7)**
ADR-0066 §Option-A+ erlaubt Welle-4+5 parallel im KW-26. FSM
(lifecycle_state_machine) und State-Backing teilen State-Mutation-
Semantik (FSM-Transition schreibt durch State-Backing). Ein
Schema-Drift in einem der beiden Substrate erscheint als Doppel-
Welle-Symptom, nicht als Single-Modul-Issue. Mitigation: §4.4
Cross-Modul-Drift-Check mit `doppelbetrieb-score-aggregator
--mode=cross-modul-stress` (PR #197) als Pflicht-Step; T-4 Trigger
bei Drift > 0; Welle-4-Koordinations-Marker im Rollback-Pfad.
Sekundaere Mitigation: Doppel-Welle-Sequenz (§3.0) — Welle-5-§3
beginnt **nach** Welle-4-§3.6, nicht parallel. Symmetric-Achse zu
Welle-4-R-1 — Selin-Welle-4-Smoke A7-Achse `cross-modul-drift-to-
welle-5` ist die Welle-4-Seite der gleichen Drift-Achse.

**R-2 — FSM-Phantom-Transitions (Rust-Backend emittiert nicht-
spec-konforme Transitions)**
FSM ist deterministisch durch `_VALID_TRANSITIONS` (9 Transitions,
spec §3.3). Wenn der Rust-FSM-Backend eine Transition emittiert
die nicht in dem 9-Set ist: das ist nicht Performance-Drift
sondern Korrektheits-Drift. Phantom-Transitions koennen verursacht
sein durch (a) Rust-Bug (falsche Transition-Encoding), (b) Spec-
Drift zwischen Python-Spec und Rust-Crate, (c) Race-Condition mit
State-Backing-Backend (FSM liest inconsistent State). Mitigation:
§3.6 (b) Phantom-Transition-Scan als Pflicht-Step nach Boot;
§4.3 Live-Stream-Watcher im Soak-Window; T-3 Trigger bei Erstem
Phantom-Sample; §6 Schritt 4b Re-Scan post-Rollback.

**R-3 — FSM-Transition-State-Read-Backward-Compat (rust liest python-write)**
Wie Welle-4 ist FSM eine state-persistent Komponente (FSM-State
plus Transition-Counter). Wenn Rust-FSM-Backend den Python-FSM-
write-State nicht zu derselben kanonischen Form deserialisiert:
Hash-Drift in §3.6 (a), sofortiger Rollback-Trigger T-3. **Kritisch:**
Rollback selbst muss den FSM-State weiterhin lesbar machen — §6
Schritt 4 verifiziert das. Bei Hash-Drift post-Rollback: AR-Hand-
Stop-Marker (exit-3), Engine-FSM-State-Korruption-Verdacht.
Mitigation: Reza-Tag-17/33-Cross-Lang-Test-Coverage (`tests/
fixtures/lifecycle-state-machine-cross-lang/fixtures.json` ≥ 5
Pins) als Wednesday-Validation-Step Pflicht-Gate.

**R-4 — Parallel-Cutover-Race (Welle-4-§3.4 Restart vs. Welle-5-§3.4 Restart)**
Wenn Mira im Cutover-Window versehentlich Welle-5-§3.4 parallel
zu Welle-4-§3.4 ausloest (statt sequenziell nach Welle-4-§3.6):
**zwei aufeinanderfolgende Engine-Restarts** in einem ~30s-Fenster.
Das ist nicht reversibel als Race-Condition: wenn Welle-4-Boot-
Audit nicht durch ist und Welle-5-Restart starten wuerde, ist der
zweite Restart effektiv ein Abort des Welle-4-Boot-Audit-Streams.
Mitigation: §3.0 explizite Sequenz-Constraint plus §3.5 Boot-
Audit-Wait-Loop-Pflicht; Mira-Hand-Discipline im Cutover-Window
(Welle-5-§3.1 SSH-Login erst nach Welle-4-§3.6 PRE_HASH==POST_HASH-
Bestaetigung); Welle-5-Smoke-Skript-Pre-Check
`--sequence-after-welle 4` prueft ob Welle-4-Drop-In-File
existiert UND Welle-4-Boot-Audit-Pass im Journal.

**R-5 — Welle-3-FSM-Aware-Dependents (audit-trail-Bindung)**
FSM-Transitions emittieren Audit-Annotations in den Bridge-Audit-
Stream (Welle-3-Substrate). Wenn Welle-3-`anchor_emitter` instabil
ist (z.B. Welle-3 verdict yellow-with-Henrik-Hand-Approval mit
Audit-Stream-Drift): FSM-Transition-Audit-Annotations sind nicht
verlaesslich, was wiederum §4.4 Cross-Modul-Rollup-Integrity
verzerrt (false-positive Drift). Mitigation: §1 Welle-3-Sign-Off-
Pflicht-Vorbedingung; bei Welle-3-Rollback oder ar-hand-stop ist
Welle-5-Cutover BLOCKIERT (§9 R-6). Bei Welle-3-yellow-with-
Henrik-Approval: Mira-Hand-Decision-Point mit Bridge-Audit-Sanity-
Spot-Check vor Welle-5-§3.1.

**R-6 — Welle-3-Rollback-Coupling**
Falls Welle-3 `rollback` ODER `ar-hand-stop` (§1 zulaessiger
Zustand (c)): Welle-4+5 (KW-26) sind BLOCKIERT. Begruendung:
Bridge-Audit-Writer-Rollback signalisiert Audit-Stream-Substrate-
Anomalie; FSM-Cutover schreibt FSM-Transition-Audit-Annotations
in den Bridge-Audit-Stream, ein Welle-3-Rollback bedeutet die
Audit-Substrate ist nicht stabil — Cross-Modul-Drift wuerde
falsch-positiv triggern und Phantom-Transition-Scan wuerde gegen
einen unstable Audit-Stream laufen. AR-Eskalation Pflicht; Welle-
4+5-Re-Scheduling ist AR-Decision.

**R-7 — Single-Variant-Constraint (`rust`, kein `rust_inmemory`-Fallback)**
Im Unterschied zu Welle-4 (`rust_inmemory` vs `rust_natskv`)
akzeptiert `resolve_fsm_backend` nur `python` ODER `rust`. Wenn
Env-Overlay versehentlich einen anderen Wert setzt (z.B. `rust_inmemory`
als Copy-Paste aus Welle-4-Drop-In): Engine-Boot-Failure mit
expliziter Resolver-Validierungs-Fehlermeldung. Das ist ein Pre-
Cutover-Bug, kein Cutover-Bug — Mitigation: §3.3 Env-Overlay-
Heredoc nutzt exakten String `rust` (Single-Token, keine Variant-
Suffixe); §3.5 Boot-Audit-Filter prueft auf `backend=rust` aber
explizit `backend=rust_inmemory not in msg` (disambiguate from
Welle-4-Boot-Stream).

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, **Montag KW-26 (2026-06-22)**,
**10:00-14:00 CEST Cutover-Window** (4h, identisch zu Welle-4
und symmetric zu Doppel-Welle-Pattern — Welle-4 und Welle-5
teilen sich das Window).

**Konkretes Cutover-Window — Welle-5 (parallel Welle-4, sequenziert nach Welle-4-§3.6):**

| Sub-Phase | Slot CEST |
|---|---|
| Pre-Conditions Walk-Through (Welle-4 + Welle-5 sync) | 10:00-10:20 |
| Pre-Flight-Smoke Welle-5 (§2) + Welle-4-Smoke (parallel) | 10:20-10:30 |
| Pre-Cutover-FSM-Snapshot (§3.2.5) Welle-5 (kann parallel zu Welle-4-§3.2.5) | 10:30-10:40 |
| Cutover-Step Welle-4 (§3.1-§3.6) | 10:40-11:00 |
| **Welle-5-§3.0-Gate-Check** (Welle-4-§3.6 PRE_HASH==POST_HASH bestaetigt) | 11:00-11:05 |
| Cutover-Step Welle-5 (§3.1-§3.6) | 11:05-11:20 |
| Soak-Window Welle-4+5 (§4, 15-min, parallel) | 11:20-11:35 |
| Cross-Modul-Drift-Check (§4.4) Welle-5 + Welle-4 symmetric | 11:35-11:50 |
| Sign-Off-Initial-Draft (§7) Welle-4 + Welle-5 | 11:50-12:30 |
| Reserve — Rollback + FSM-Continuity-Verify (Welle-4 ODER 5 ODER beide) | 12:30-14:00 |
| **Pause + Audit-Trail-Submission an Henrik** | 14:00-15:30 |
| Henrik-Audit-Sign-Off-Window (Welle-4 + Welle-5) | 15:30-17:00 |

**Datum: Montag 2026-06-22 (KW-26)**

- **Welle-5-Cutover-Vorbereitung-Start:** 10:00 CEST (parallel mit Welle-4)
- **Welle-5-Cutover-§3-Start:** 11:05 CEST (nach Welle-4-§3.6)
- **Welle-5-Latest-Commit-To-Rust:** 11:20 CEST (Boot-Audit-Pass + Phantom-Scan-OK)
- **Welle-4+5-Soak-Window-Ende:** 11:35 CEST
- **Welle-4+5-Sign-Off-Window-Ende:** 17:00 CEST
- **Hairpin-Rollback-Slot:** Mittwoch 2026-06-24, 09:00-13:00 CEST (geteilt mit Welle-4)

**Begruendung Werktag-Vormittag + Doppel-Welle-Sequenz + 4h-Window:**

1. **Doppel-Welle (symmetric Welle-4):** Pre-Conditions Walk-Through
   und Pre-Flight-Smokes sync zwischen Welle-5 und Welle-4
   (Mira-Hand-Owner beider). 4h-Window deckt Welle-4-§3 + Welle-5-
   §3 + gemeinsamer Soak-Window + Reserve fuer parallel-Rollback ab.
2. **Welle-5-Sequenz-Constraint (§3.0):** Welle-5-Cutover startet
   erst nach Welle-4-§3.6 Post-Restart-State-Read-Verify. Welle-5-
   Cutover-Window-§3-Start ist daher ~60min nach Cutover-Window-
   Opening.
3. **Cross-Modul-Drift-Check (§4.4):** Pflicht-Step im Soak-Window
   weil Doppel-Welle-Coupling. Zusaetzliche 15min-Slot vor Sign-Off
   fuer FSM × state_backing symmetric drift-Probe.
4. **Henrik-Sign-Off-Window 15:30-17:00:** Henrik prueft Welle-4-
   Sign-Off und Welle-5-Sign-Off als korreliertes Paar (Cross-
   Welle-Coupling-Check), inkl. FSM-Phantom-Transition-Spec-
   Konformitaets-Audit.
5. **Hairpin-Rollback-Slot Mi (KW-26):** Falls Welle-4 ODER 5
   ODER beide yellow-with-Henrik-Hand-Approval-Bedarf — Mittwoch-
   Vormittag (09:00-13:00, 4h-Window, geteilt) ist der naechste
   sinnvolle Slot.
6. **Welle-6+7 KW-27-Trigger:** Welle-6+7 sind in KW-27 geplant
   (parallel, Standard-Acceptance per ADR-0066). Welle-4-Sign-Off-
   Green UND Welle-5-Sign-Off-Green ist Pflicht-Vorbedingung.
   Wenn eine der beiden bis Mittwoch nicht green: Welle-6+7
   verschieben auf KW-28.
7. **Engineering-Verfuegbarkeit:** Reza, Selin, Tomás, Henrik im
   Cutover-Window aktiv. Sofort-Eskalation moeglich.

**Verbotene Cutover-Slots:**

- Freitag-Nachmittag (Wochenend-Rollback-Risiko).
- Mittwoch-Mittag (kollidiert mit Wednesday-Validation-Run-Re-Run-
  Option).
- Sonntag/Feiertag (kein Engineering-Standby).
- Parallel zu Welle-3-Cutover-Step (KW-25, siehe §9 R-6 +
  ADR-0066 §Bridge-Audit-Welle-solo).
- KW-26-Mittwoch-Cutover-Slot (Mittwoch ist Hairpin-Rollback-Slot,
  nicht Cutover-Slot).
- **Welle-5-§3 BEFORE Welle-4-§3.6 — strikt verboten (§3.0
  Sequenz-Constraint).**

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Reza (fsm-Rust-Substrate-Owner) | bei JCS-Canonical-Drift, FSM-Spec-Migration-Issue, FSM-Phantom-Transition-Detection, FSM-State-Read-Hash-Drift |
| 3 | Tomás (Matrix-Lead) | bei Welle-4/5-Cross-Modul-Korrelation, Doppel-Welle-Coupling-Konflikt |
| 4 | Henrik (Internal Audit) | bei Audit-Trail-Anomaly, T-3 oder T-4 Trigger, Phantom-Transition-Spec-Konformitaets-Audit, F-Item-Reactivation |
| 5 | AR (Fred) | bei AR-Hand-Stop-Marker, Rollback-FSM-Continuity-Violation (§6 exit-3), Rollback-Phantom-Transition (§6 Schritt 4b exit-3), Welle-3-Rollback-Coupling-Block, Phase-3c-Sequenz-Re-Sequencing |

---

## Anhang B — Cross-Welle-Coordination-Checkliste

Vor Welle-5-Cutover-Start: explizite Verifikation der Welle-1+2+3-
Coordination-Items und der Welle-4-Sequenz-Coupling.

- [ ] Welle-1-Runbook gelesen ([`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md), PR #228 Tag-34)
- [ ] Welle-2-Runbook gelesen ([`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md), PR #232 Tag-35)
- [ ] Welle-3-Runbook gelesen ([`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md), PR #237 Tag-36)
- [ ] Welle-4-Runbook gelesen ([`welle-4-state-backing-runbook.md`](./welle-4-state-backing-runbook.md), PR #243 Tag-37, paralleler Doppel-Welle-Partner)
- [ ] Welle-1-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`)
- [ ] Welle-2-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`)
- [ ] Welle-3-Sign-Off-Verdict bekannt (`green`, `green-with-yellow-notes`, oder `rollback`/`ar-hand-stop`)
- [ ] Bei Welle-3-`rollback` ODER `ar-hand-stop`: Welle-4+5 BLOCKIERT (AR-Eskalation)
- [ ] Welle-1-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-1-v907-verify-rust.conf`
- [ ] Welle-2-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-2-svid-workload-identity-rust.conf`
- [ ] Welle-3-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-3-bridge-audit-writer-rust.conf`
- [ ] **Welle-4-§3.6 Sequenz-Gate verifiziert** (PRE_HASH == POST_HASH
      im Welle-4-Cutover-Log) BEVOR Welle-5-§3.1 SSH-Login startet
- [ ] Welle-4-Drop-In-File auf Pilot-VM vorhanden NACH Welle-4-§3.6:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/welle-4-state-backing-rust.conf`
- [ ] Welle-1-`v907_verify` `backend=rust` im Aggregator >99% (Welle-5-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-2-`svid_workload_identity` `backend=rust` im Aggregator >99% (Welle-5-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-3-`anchor_emitter` `backend=rust` im Aggregator >99% (Welle-5-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-4-`state_backing` `backend=rust_inmemory` im Aggregator >99% NACH Welle-4-§3.6
- [ ] Welle-5-Engine-Health-Baseline frisch aufgezeichnet POST-Welle-1+2+3 (nicht uebertragen aus Welle-1/2/3/4-Pre-Baselines)
- [ ] Welle-5-spezifischer Pre-Cutover-FSM-Snapshot vorhanden (§3.2.5, SHA-256-Hash + Spec-Version + Transition-Distribution protokolliert)
- [ ] Welle-4-§3.6-Pre/Post-Hash-Match dokumentiert (§3.0 Sequenz-Constraint)
- [ ] Doppel-Welle-Sequenz §3.0 verstanden (Welle-4-§3.6 vor Welle-5-§3.1)
- [ ] Cross-Modul-Stress-Test Wednesday-Run gruen (Pflicht aus ADR-0066 §Mitigations, symmetric A7)

---

## Anhang C — Welle-5-spezifische Cross-Spawn-Coordination (Tag-38)

Tag-38 hat parallele Spawns laufen lassen (Continuous-Mode):

| Spawn | Owner | Artefakt | Pfad |
|---|---|---|---|
| Welle-5-Operator-Runbook (dieses Dokument) | Kai | `docs/phase-3c/welle-5-lifecycle-state-machine-runbook.md` | dieses File |
| Welle-5-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh` | Pfad in §2 zitiert (parallel Tag-38) |
| Welle-4-Operator-Runbook (Vorgaenger-Partner) | Kai | `docs/phase-3c/welle-4-state-backing-runbook.md` | PR #243 Tag-37 |
| Welle-4-Cutover-Smoke-Skript (Vorgaenger-Partner) | Selin | `scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh` | PR #245 Tag-37 |
| Tomás-Tag-38-Workflow-Adjustment (Welle-5) | Tomás | CI-Workflow-Validation | siehe Tomás-Tag-38-Liefer-Bericht |
| Reza-Tag-38-Substrate (Welle-5 Substanz) | Reza | Substanz-Coverage-Spawn | siehe Reza-Tag-38-Liefer-Bericht |

Pre-Cutover-Cross-Spawn-Verifikation (in §1 implizit, hier
explizit gelistet): alle Tag-37+38-Artefakte muessen auf main
gemerged sein vor Welle-5-Wednesday-Validation-Run-Trigger
(KW-25-Mittwoch 2026-06-17).

---

## Anhang D — Symmetric-Coordination-Stub zu Welle-4

Welle-4 und Welle-5 sind im KW-26 Doppel-Welle-Pattern symmetric
gekoppelt. Diese Anhang dokumentiert die Symmetrie explizit zur
Operator-Hand-Hygiene.

| Achse | Welle-4 (state_backing) | Welle-5 (lifecycle_state_machine) |
|---|---|---|
| Env-Var | `WAKIR_STATE_BACKING_BACKEND` | `WAKIR_FSM_BACKEND` |
| Cutover-Wert | `rust_inmemory` (Doppel-Variant) | `rust` (Single-Variant) |
| Sequenz-Position | zuerst (§3.0) | folgt nach Welle-4-§3.6 (§3.0) |
| Component-Short | `state_backing` (no-alias) | `fsm` (Long-form alias `lifecycle_state_machine`) |
| Cross-Lang-Fixtures | `tests/fixtures/state-backing-cross-lang/fixtures.json` | `tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json` |
| Quadlet-Binary | `wakir-persona-engine-state-backing` | `wakir-persona-engine-fsm` |
| Mini-Welle-Carrier | `state-backing-welle4` (Tag-33) | `fsm-welle5` (Tag-33) |
| §3.2.5 Pre-Verify | State-Snapshot-Hash | FSM-Snapshot-Hash + Transition-Distribution |
| §3.6 Post-Verify | State-Read-Compatibility-Hash-Match | FSM-Read-Compatibility-Hash-Match + Phantom-Transition-Scan |
| T-3 Trigger | State-Read-Hash-Drift | FSM-Hash-Drift ODER Phantom-Transition |
| T-4 Trigger Paired-Component | `lifecycle_state_machine` | `state_backing` |
| Cross-Modul-§4.4 Target | state_backing × FSM | FSM × state_backing (symmetric) |
| AR-Hand-Stop-Bedingungen | 3 (§6 exit-3, T-3, T-4 + Cross-Welle-Coordination-Fail) | 4 (§6 Schritt 4 exit-3, §6 Schritt 4b exit-3 Phantom-Post-Rollback, T-3, T-4 + Cross-Welle-Coordination-Fail) |

**Doppel-Welle-Cross-Spawn-Pflicht:** Welle-4 und Welle-5 muessen
gemeinsam Sign-Off (mind. yellow) erreichen, bevor Welle-6+7 in
KW-27 trigger'n duerfen. Ein einseitiger green-Sign-Off (z.B.
Welle-4 green, Welle-5 rollback) blockiert die Phase-3c-
Fortschritts-Kette.

---

— Kai Hoffmann (DevOps), Sprint-Tag-38, 2026-05-18.
