---
title: "Phase-3c Welle-4 state_backing Operator-Cutover-Runbook"
owner: "Kai Hoffmann (DevOps), Tomas Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065, 0066"
welle: 4
component: "state_backing"
env_var: "WAKIR_STATE_BACKING_BACKEND"
env_var_variant: "rust_inmemory"
cutover_date: "2026-06-22"
cutover_window_cest: "10:00-14:00"
soak_window_minutes: 15
hairpin_rollback_window_cest: "Mi 09:00-13:00"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 37
parallel_welle: 5
parallel_welle_component: "lifecycle_state_machine"
parallel_welle_env_var: "WAKIR_FSM_BACKEND"
risk_class: "doppel-welle-cross-modul-drift"
---

# Phase-3c Welle-4 state_backing Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-4-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die `state_backing`-
Komponente der Persona-Engine, 5. emittierte `BackendDecision`).
Ziel-Cutover-Datum: Montag 2026-06-22, KW-26, **parallel** zu
Welle-5 (`lifecycle_state_machine`) gemaess ADR-0066 §Option-A+.

Dies ist das **operative Day-Of-Skript**. Hermetic-Validierung
(`phase-3c-welle-4-validation.yml`) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-4-runbook.md`](../operations/phase-3c-welle-4-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM, echter
NATS-Bus, echte Quadlet-Restart-Sequenz, echte State-Persistence-
Cross-Backend-Beobachtung.

Schwester-Runbook fuer Welle-5 (parallel-Cutover-Coordination):
- [`welle-5-lifecycle-state-machine-runbook.md`](./welle-5-lifecycle-state-machine-runbook.md)
  (paralleler Tag-37-Spawn, Kai-Folge-Spawn nach Welle-4-Liefer-
  Bericht).

Vorgaenger-Runbooks (Phase-3c-Sequenz):
- [`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md)
  (PR #228, Tag-34, Welle-1 `v907_verify` KW-24 Montag parallel zu Welle-2).
- [`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md)
  (PR #232, Tag-35, Welle-2 `svid_workload_identity` KW-24 Montag parallel zu Welle-1).
- [`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md)
  (PR #237, Tag-36, Welle-3 `bridge_audit_writer` KW-25 Montag solo Henrik-Caution).

## Welle-4-Charakter (state_backing-spezifisch)

**Welle-4 ist die erste Welle in der die zu cutover'nde Komponente
Engine-State persistiert.** Vorgaenger-Wellen (v907_verify, svid,
bridge_audit_writer) sind alle State-frei: V907-Verify ist Verify-
Computation, SVID ist Identity-Resolution, Bridge-Audit-Writer ist
Sink-Pfad. State-Backing dagegen ist Read-Write-Substrate fuer die
Persona-Engine-Snapshot-Persistenz (FSM-Transition-State, Mailbox-
Cursor, Drill-Scheduler-Tracking).

**Drei state_backing-spezifische Charakteristika:**

1. **Variant-Selection (rust_inmemory vs rust_natskv)** — der
   Resolver akzeptiert zwei Rust-Varianten (siehe
   `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE`
   Zeile 201). Welle-4-Cutover flippt auf `rust_inmemory` (Phase-3c-
   Default-Variant per ADR-0066). NATS-KV-Variant ist Phase-3d-
   Folge-Migration (nicht Teil von Welle-4).
2. **State-Read-Compatibility-Pre-Verification** — Engine schreibt
   im Python-Backend-Pfad, reboot mit Rust-Backend, validiert
   Read-Compatibility (§3.2.5 Pre-Cutover-State-Snapshot-Hash +
   §3.6 Post-Restart-State-Read-Verify). Ohne diesen Step ist nicht
   feststellbar ob das Rust-Backend den Pre-Cutover-State korrekt
   deserialisiert.
3. **Cross-Modul-Drift zu Welle-5 (parallel)** — `lifecycle_state_
   machine` (FSM) schreibt Transitions durch `state_backing`. Wenn
   beide Welle-4+5 parallel cutover'n: ein Schema-Drift in einem
   der beiden Substrate erscheint als Doppel-Welle-Symptom, nicht
   als Single-Modul-Issue. Mitigation: Cross-Modul-Stress-Test als
   §4.4 Soak-Step (Phase-2-Acceptance-Gate Step 6 aus PR #197).

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ + Doppel-Welle-Constraint | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Welle-4 Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-4-validation.yml` |
| Welle-4 Sibling-Validation-Runbook | `docs/operations/phase-3c-welle-4-runbook.md` |
| Welle-1 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-1-v907-verify-runbook.md` (PR #228, Tag-34) |
| Welle-2 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-2-svid-workload-identity-runbook.md` (PR #232, Tag-35) |
| Welle-3 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-3-bridge-audit-writer-runbook.md` (PR #237, Tag-36) |
| Welle-5 Coordination-Stub (parallel KW-26) | `docs/phase-3c/welle-5-lifecycle-state-machine-runbook.md` (Kai-Folge-Spawn Tag-37) |
| State-Backing Container-Image-Build-Pipeline | PR #167 (Tag-17) + Tag-33 Mini-Welle `state-backing-welle4` Quadlet-Carrier-Update |
| State-Backing Cross-Lang-Hash-Parity-Pins | `tests/fixtures/state-backing-cross-lang/fixtures.json` |
| Resolver `resolve_state_backing_backend` | `wirelang/persona_engine/rust_backend_switch.py` (`STATE_BACKING_BACKEND_ENV` L427, `DEFAULT_RUST_STATE_BACKING_BIN` L449) |
| Resolver-Variant-Map | `scripts/phase-3c-cutover-dry-run.py::COMPONENT_TO_RUST_VALUE` (state_backing -> rust_inmemory) |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Cross-Modul-Stress-Aggregator (Doppel-Welle-Pflicht) | `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress` (PR #197) |
| Quadlet-Inventar (9-Binary) | `quadlet/wakir-rust-cli.container` (Item 2 = `wakir-persona-engine-state-backing`) |
| Cosign-Policy (9-Binary) | `policies/cosign-policy-phase-3b.yaml` Zeile 223 `name: state-backing` |
| Selin Welle-4 Cutover-Smoke-Skript | `scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh` (Selin Tag-37, parallel zu diesem Runbook) |
| State-Backing Modul | `wirelang/persona_engine/state_backing.py` |
| FSM Modul (Welle-5-Cross-Modul-Anker) | `wirelang/persona_engine/fsm.py` (via Welle-5-Runbook konkretisiert) |
| Welle-4-Telemetry-Runbook | `docs/operations/welle-4-telemetry-runbook.md` |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya.

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar 9-Binary)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `state-backing` als 1. Persona-Engine-Binary
      (`name: state-backing` Zeile 223, mit
      `in_image_path: /opt/wakir/bin/wakir-persona-engine-state-
      backing`).
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 9 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` Tag-17 Update
      enthaelt `wakir-persona-engine-state-backing` als Item 2 der
      `Exec=`-Schleife des Installer-Containers. Tag-33 Mini-Welle
      ergaenzt `state-backing-welle4`-Variant-Pin (Carrier-Image-
      Verifikation via `sha256sum-checks`-Probe).
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence: `wirelang/persona_engine/rust_backend_switch.py`
      enthaelt `STATE_BACKING_BACKEND_ENV =
      "WAKIR_STATE_BACKING_BACKEND"` (L427) und
      `DEFAULT_RUST_STATE_BACKING_BIN ==
      /opt/wakir/bin/wakir-persona-engine-state-backing` (L449).
      Resolver akzeptiert Variant-Werte `rust_inmemory` ODER
      `rust_natskv` (siehe `VALID_STATE_BACKING_BACKEND_VALUES`
      L630). **Welle-4-Cutover nutzt `rust_inmemory`** (ADR-0066
      Phase-3c-Default, NATS-KV-Variant ist Phase-3d).
      Engine-Boot-Audit emittiert 5. `BackendDecision` mit
      `component=state_backing`.
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet, GitHub-Runner-Baseline-File nicht).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — gruen. Evidence:
      `tests/integration/test_bridge_audit_roundtrip_e2e.py` passt
      (oder all-SKIP auf Runner ohne replay_cli-Binary). State-
      Backing-State-Hash-Audit-Annotation wird emittiert.
- [ ] **Welle-4-Wednesday-Validation-Run gruen** (2026-06-17
      06:00 UTC, KW-25 Mittwoch — 5 Tage vor Cutover-Montag KW-26).
      Evidence: `cutover-acceptance-decision-welle-4.json`
      `ready_for_live_smoke == true` UND `cross_modul_stress_passed
      == true` (Step 6 PR #197). Artifact-Retention 30 Tage.
      Workflow: `.github/workflows/phase-3c-welle-4-validation.yml`.
- [ ] **Welle-3-Sign-Off-Verdict bekannt** (KW-25 Montag,
      mind. `green` ODER `green-with-yellow-notes-mit-Henrik-Hand-
      Approval` Pflicht). Drei zulaessige Zustaende fuer
      Welle-4-Trigger:
      - **(a) Welle-3 `green` Sign-Off** — Welle-4 startet planmaessig KW-26 Montag.
      - **(b) Welle-3 `green-with-yellow-notes` + Henrik-Hand-Approval-File** —
        Welle-4 startet, aber Mira-Hand-Decision-Point mit
        explizitem Yellow-Notes-Review im Cutover-Window.
      - **(c) Welle-3 `rollback` ODER `ar-hand-stop`** — Welle-4+5
        wird BLOCKIERT, nicht gestartet. AR-Eskalation Pflicht
        (§9 R-6).
- [ ] **Welle-5-Cutover-Status verifiziert** (Welle-5 ist
      parallel-laufend KW-26 Montag). Drei zulaessige Zustaende
      fuer Welle-4-Trigger relativ zu Welle-5:
      - **(a) Welle-5-Pre-Conditions gruen** — Welle-4+5 starten gemeinsam.
      - **(b) Welle-5-Pre-Conditions yellow** — Mira-Hand-Decision
        ob Welle-4 solo-vorzieht oder mit Welle-5 wartet
        (Doppel-Welle-Coupling, siehe Welle-5-Runbook §1).
      - **(c) Welle-5-Pre-Conditions red** — Welle-4 starten ohne
        Welle-5 ist **nicht** zulaessig (Cross-Modul-Stress-Test
        kann nicht ausgefuehrt werden ohne FSM-Doppelbetrieb-
        Substrate). Welle-4 verschiebt sich auf KW-27 (mit
        Welle-5-Re-Schedule).
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, **post-Welle-1+2+3 Engine-Posture**). Latency-p50/p95,
      Error-Rate, BackendDecision-Volume pro Minute, State-Backing-
      Read/Write-Rate, State-Snapshot-Size-Baseline. Persistiert in
      `/var/lib/wakir/baselines/welle-4-pre-cutover-<TS>.json`.
      **Wichtig:** Die Baseline wird **nach KW-24+25-Sign-Off und
      vor KW-26-Welle-4-Cutover** frisch aufgezeichnet — die Engine
      hat 3 von 9 Backends bereits auf Rust geflippt; eine Pre-
      Welle-1-Baseline ist nicht uebertragbar.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component state_backing --window 5m --format json` liefert
      gueltige Records mit `backend=python` >99% (Baseline).
- [ ] **Quadlet 9-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 9 Binaries inklusive
      `wakir-persona-engine-state-backing`.
- [ ] **Cosign-Policy 9-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit.
      Das transitiv-verifizierte Image-Manifest umfasst state-
      backing-Image als Item 2 der Build-Inventory.
- [ ] **State-Backing Cross-Lang-Hash-Parity-Pins frisch**.
      Evidence: `tests/fixtures/state-backing-cross-lang/
      fixtures.json` existiert, Pin-Count ≥ 5. Das ist die Baseline-
      Referenz fuer §4.2 Cross-Lang-Hash-Parity-Probe.
- [ ] **Cross-Modul-Stress-Test Wednesday-Run gruen** (Doppel-Welle-
      Pflicht aus ADR-0066 §Mitigations). Evidence: Welle-4-
      Validation-Workflow Step 6 (`doppelbetrieb-score-aggregator
      --mode=cross-modul-stress`) hat alle 3 Achsen `>= threshold`:
      - `cross-lang-pin-coverage` (state_backing x lifecycle_state_machine)
      - `cross-modul-fixture-stability`
      - `cross-modul-rollup-integrity`
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt** —
      Mittwoch KW-26, 09:00-13:00 CEST (4h-Slot, **erweitert** vs.
      Welle-1+2-Standard wegen Doppel-Welle-Cross-Modul-Drift-
      Koordination — Rollback Welle-4 ODER Welle-5 ODER beide
      braucht laengeren Slot).

---

## §2 Pre-Flight-Smoke

Selin's Welle-4-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet zur
Pilot-VM testet und kein Pilot-internes Artefakt ist. Skript
liefert Selin **parallel zu diesem Runbook** (Tag-37 Cross-Spawn).

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component state_backing \
    --env-var WAKIR_STATE_BACKING_BACKEND \
    --variant rust_inmemory \
    --parallel-welle 5 \
    --cross-modul-stress-axis state_backing,lifecycle_state_machine \
    --dry-run-window 5m \
    --json-out /tmp/welle-4-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated ODER Welle-3-`green-with-yellow-notes` post-hoc).
  Mira-Hand-Decision noetig vor §3.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Tomás (Matrix-Lead). **Bei red: kein Cutover-
  Versuch ohne Henrik-Hand-Override.**

Das JSON-Envelope (`/tmp/welle-4-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~3-5 min wall-clock (laenger als Welle-1/2
wegen Cross-Modul-Stress-Axis-Sample und State-Snapshot-Hash-Probe).
Skript prueft SSH-Reachability, Quadlet-Status-Snapshot, Cosign-
Policy-Match (9-Binary), Engine-Health-Baseline-Delta gegen Tag-N-1,
State-Snapshot-Hash-Sanity, BackendDecision-Aggregator-Sanity fuer
`component=state_backing`, Cross-Modul-Stress-Smoke (state_backing x
lifecycle_state_machine 3-Axen-Sample). Keine Side-Effects auf
Pilot-VM (read-only).

**Welle-4+5-Parallel-Hinweis:** Welle-4 und Welle-5 starten am
selben Cutover-Tag KW-26 Montag. Pre-Flight-Smokes Welle-4 und
Welle-5 duerfen parallel laufen, **aber** §3 Cutover-Step Welle-4
+ §3 Cutover-Step Welle-5 sind seriell-koordiniert (siehe §3.0
Doppel-Welle-Sequenz). Begruendung: gleichzeitiger Restart beider
Backends macht den Boot-Audit-Stream nicht eindeutig zuordbar zu
Welle-4-State-Snapshot-Read-Compatibility-Pre-Verify.

---

## §3 Cutover-Step

**Mira-Hand-SSH-Authority** gemaess ADR-0058 §Nachtrag. AR-
Eskalations-Override nur fuer `irreversible despawn`-Pfade —
Quadlet-Restart und Env-Overlay fallen darunter **nicht**, das
ist routine Operator-Hand-Operation.

**Welle-4-spezifische Erweiterung:** §3.2.5 State-Persistence-Pre-
Verification (Engine schreibt im Python-Backend, Hash + Snapshot;
reboot mit Rust-Backend; Read-Compatibility-Validation in §3.6).
Ohne diesen Step ist State-Read-Failure beim Rust-Backend nicht
unterscheidbar von Engine-Boot-Failure.

**Schritt 3.0 — Doppel-Welle-Sequenz (Welle-4 zuerst, Welle-5 folgt)**

Welle-4-Cutover beginnt **zuerst**, Welle-5-Cutover folgt nach
Welle-4-Boot-Audit-Pass (§3.5 hits >= 5 fuer `state_backing`).
Begruendung: `lifecycle_state_machine` schreibt durch
`state_backing`; wenn beide gleichzeitig flippen, ist eine
State-Backing-Read-Failure beim Engine-Restart nicht unterscheidbar
von einer FSM-Init-Failure. Sequenz garantiert, dass Welle-4-Rust-
Backend stabil ist bevor Welle-5-Rust-Backend Schreibungen einleitet.

Welle-5-Cutover-Step §3 startet erst nach Welle-4-§3.6 Post-Restart-
State-Read-Verify (Welle-4-State-Snapshot mit Rust-Backend deserialisierbar).

**Schritt 3.1 — SSH auf Pilot-VM**

```bash
ssh root@192.168.178.116
# Erwarteter Banner: "wakir-pilot — FCOS — Phase-3b live"
```

**Schritt 3.2 — Pre-Restart-Snapshot (post-Welle-1+2+3)**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-4 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-4-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-4-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-4-cutover-pre-journal.txt

# Welle-1+2+3-State-Check: bestaetige dass v907_verify + svid +
# anchor_emitter backend=rust laufen (KW-24+25-Cutover bereits erfolgt).
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -cE "BackendDecision.*(v907_verify|svid_workload_identity|anchor_emitter).*backend=rust" \
  | tee -a /var/log/wakir/welle-4-cutover.log
# Erwartung: > 0 Records pro Component (drei separate Linien).
```

**Schritt 3.2.5 — State-Persistence-Pre-Verification (Welle-4-spezifisch)**

**Kritisch.** Vor dem Restart muss der aktuelle Engine-State im
Python-Backend-Pfad als immutable Snapshot erfasst werden. Wenn
der Rust-Backend nach Restart den Snapshot nicht korrekt deserialisiert,
ist die Engine in einem inkonsistenten Zustand — Rollback gegen
diese Baseline garantiert deterministische Recovery.

```bash
# Auf Pilot-VM:
mkdir -p /var/lib/wakir/welle-4-state-baseline

# 1. Engine-State-Snapshot via CLI-Tool (Python-Backend-Pfad)
/opt/wakir/bin/wakir-persona-engine-state-backing \
    --mode=snapshot \
    --backend=python \
    --output=/var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.json
wc -c /var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.json \
    | tee -a /var/log/wakir/welle-4-cutover.log

# 2. Hash der State-Baseline (SHA-256 fuer immutability-Verify in §3.6 + §6)
sha256sum /var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.json \
    | tee /var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.sha256 \
    | tee -a /var/log/wakir/welle-4-cutover.log

# 3. State-Backing-Schema-Version erfassen (Python-Backend-Schreibweise)
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
  | grep "state_backing.*schema_version=" \
  | tail -3 \
  | tee /var/lib/wakir/welle-4-state-baseline/pre-cutover-schema-version-${TS_PRE}.txt
```

**Erwartete Evidenz:** Snapshot-File-Size > 0, Hash protokolliert,
Schema-Version bekannt. Wenn Snapshot 0 Bytes hat: STOP — State-
Backing ist bereits vor Cutover unreadable, das ist ein Pre-Cutover-
Red und §6 ist nicht der richtige Pfad (Reza + Henrik eskalieren,
Cutover absagen).

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht in-place
edit. Reversibel, ADR-0058-konform. **Welle-4-spezifisch:** Env-
Wert ist `rust_inmemory` (nicht `rust`).

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-4-state-backing-rust.conf <<'EOF'
# Phase-3c Welle-4 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-Sequenz, ADR-0066 §Option-A+
# state_backing Variant: rust_inmemory (Phase-3c-Default, NATS-KV ist Phase-3d)
[Service]
Environment="WAKIR_STATE_BACKING_BACKEND=rust_inmemory"
EOF
systemctl daemon-reload

# Sanity-Check: Welle-1 + Welle-2 + Welle-3 Drop-Ins existieren weiterhin.
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet:
#   welle-1-v907-verify-rust.conf
#   welle-2-svid-workload-identity-rust.conf
#   welle-3-bridge-audit-writer-rust.conf
#   welle-4-state-backing-rust.conf  (neu)
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-4-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s, 9/9 BackendDecisions)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust_inmemory` und `component=state_backing` werden
innerhalb 30s emittiert. Gleichzeitig muessen alle 9 Boot-
`BackendDecision`-Records sichtbar sein — wenn nur 8/9: Migrations-
Drift-Zustand, §6 Rollback ist Pflicht.

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
    if ("BackendDecision" in msg and "state_backing" in msg
            and "backend=rust_inmemory" in msg):
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision state_backing rust_inmemory records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

**Schritt 3.6 — Post-Restart-State-Read-Verify (Welle-4-spezifisch)**

Spezifisch fuer Welle-4: nach Restart muss der Rust-Backend den
Pre-Cutover-Python-State-Snapshot **deserialisieren koennen** und
das **gleiche kanonische State-Hash** liefern. State-Read-
Compatibility ist das Welle-4-Acceptance-Oracle.

```bash
# Auf Pilot-VM:
PRE_HASH=$(grep -oP '^[a-f0-9]{64}' \
    /var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.sha256)
echo "Pre-Cutover-State-Hash: ${PRE_HASH}" | tee -a /var/log/wakir/welle-4-cutover.log

# Rust-Backend State-Read via CLI-Tool
/opt/wakir/bin/wakir-persona-engine-state-backing \
    --mode=verify-read \
    --backend=rust_inmemory \
    --input=/var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.json \
    --output=/var/lib/wakir/welle-4-state-baseline/post-cutover-state-rust-${TS_PRE}.json
POST_HASH=$(sha256sum /var/lib/wakir/welle-4-state-baseline/post-cutover-state-rust-${TS_PRE}.json \
    | grep -oP '^[a-f0-9]{64}')
echo "Post-Cutover-State-Hash: ${POST_HASH}" | tee -a /var/log/wakir/welle-4-cutover.log

if [ "${PRE_HASH}" != "${POST_HASH}" ]; then
    echo "STATE-READ-COMPATIBILITY-FAIL: hash drift between python-write and rust-read" >&2
    echo "  PRE=${PRE_HASH}  POST=${POST_HASH}" >&2
    exit 2
fi
echo "STATE-READ-COMPATIBILITY-OK: hash match between python-write and rust-read"
```

Wenn Boot-Audit-Wait-Loop oder State-Read-Compatibility Exit ≠ 0:
sofort §6 Rollback-Procedure.

---

## §4 Post-Cutover-Verification (15-min Soak-Window)

Soak-Window **15min** (Welle-1/2-Standard, kein 30-min wie Welle-3
da kein Self-Reference-Risk). Vier parallele Beobachtungs-Streams,
jede mit harter Schwelle und Rollback-Trigger. **Welle-4-spezifisch:**
§4.4 Cross-Modul-Drift-Check gegen Welle-5 (`lifecycle_state_
machine`) ist Pflicht-Step im Doppel-Welle-Pattern.

**§4.1 — BackendDecision-Aggregator Sliding-Window**

```bash
# Auf Mira-Box, gegen Pilot-NATS:
cd /var/home/fred/AI-Corp/wakir-runtime
python3 scripts/phase-3c/backend-decision-aggregator.py \
    --component state_backing \
    --window 15m \
    --target-backend rust_inmemory \
    --min-rust-share 0.99 \
    --format json
echo "aggregator-exit=$?"
```

Erwartung: `rust_share >= 0.99` ueber 15-min-Sliding-Window.
Exit 0 = green; Exit 1 = rust_share zwischen 0.95 und 0.99
(yellow); Exit 2 = rust_share <0.95 (red, sofort Rollback).

**§4.2 — Cross-Lang-Hash-Parity gegen Python-Baseline**

State-Backing Cross-Lang-Hash-Parity-Pins (`tests/fixtures/
state-backing-cross-lang/fixtures.json`). Im Soak-Window: 5
Synthetik-State-Snapshot-Hash-Calls, jede mit Python-Vergleichs-
Hash gegen die Pin-Baseline.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component state_backing \
    --samples 5 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/fixtures/state-backing-cross-lang/fixtures.json \
    --canonical-module wirelang.persona_engine.state_backing
```

Erwartung: 5/5 Hashes match. Jede Drift => sofort §6 Rollback.

Hintergrund: die Cross-Lang-Parity prueft die deterministische
JCS-Kanonisierung der State-Snapshot-Envelopes. Drift heisst:
Python- und Rust-Side haben unterschiedliche Canonical-Forms — das
ist ein blocker-level Bug fuer State-Persistence-Continuity.

**§4.3 — State-Backing Read/Write-Error-Freiheit + Latency**

```bash
# Auf Pilot-VM:
journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" \
    -p err --no-pager \
    | grep "state_backing" \
    | tee /var/log/wakir/welle-4-state-backing-errors.txt
wc -l /var/log/wakir/welle-4-state-backing-errors.txt
```

Grafana-Dashboard `Persona-Engine — Backend Latency by Component`.
Filter: `component=state_backing`, `backend=rust_inmemory`, last
15min.

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

Operator: Screenshot pro 5min-Slice (3 Screenshots gesamt) + JSON-
Export an Henrik-Audit-Trail anhaengen.

Erwartung: 0 Error-Zeilen im 15-min-Soak-Window. Jede Error-Zeile
= automatischer §6 Rollback.

**§4.4 — Cross-Modul-Drift-Check gegen Welle-5 lifecycle_state_machine (Welle-4-spezifisch)**

Welle-4-exklusiv (im Doppel-Welle-Pattern): `state_backing` steht
in direkter Schreibe-Korrelation mit `lifecycle_state_machine`
(FSM schreibt Transitions in den State-Backing). Wenn Welle-4+5
parallel cutover: ein Schema-Drift in einem der beiden Substrate
emergiert als Cross-Modul-Drift gegen den anderen.

```bash
# Auf Mira-Box:
python3 scripts/doppelbetrieb-score-aggregator.py \
    --mode=cross-modul-stress \
    --threshold 3 \
    --target-component state_backing \
    --paired-component lifecycle_state_machine \
    --pilot 192.168.178.116 \
    --json-out /tmp/welle-4-cross-modul-drift.json
echo "cross-modul-drift-exit=$?"
```

Erwartung: 3-of-3 Cross-Modul-Achsen `>= threshold`:
- `cross-lang-pin-coverage` (state_backing × FSM cross-lang
  fixtures)
- `cross-modul-fixture-stability` (FSM-Transition-State-Backing-
  Roundtrip)
- `cross-modul-rollup-integrity` (Welle-4+5-Aggregate-Health)

Exit 0 = green; Exit non-zero = red (sofort Rollback, plus Welle-5-
Rollback-Koordination weil Doppel-Welle-Coupling — siehe §6
Schritt 5).

**§4.5 — Doppel-Welle-Coupling-Monitor (Welle-5-Cross-Status)**

```bash
# Auf Mira-Box, liest Welle-5-Cutover-Log (parallel-Cutover):
ssh root@192.168.178.116 'tail -50 /var/log/wakir/welle-5-cutover.log'
```

Erwartung: Welle-5-Boot-Audit-Pass (§3.5 Welle-5-Runbook) ist
abgeschlossen. Wenn Welle-5 im Soak-Window-Beginn von Welle-4 noch
nicht durch §3.5 ist: Mira-Hand-Decision-Point (Welle-4-Soak-Window
starten oder mit Welle-5-Boot-Audit-Pass warten).

**Cross-Welle-Yellow-Bedingung:** Wenn Welle-5 Boot-Audit-FAIL
hat aber Welle-4 OK ist: Welle-4 setzt Soak-Window fort, aber
Welle-5-Rollback wird parallel triggered. Cross-Modul-Drift-Check
§4.4 wird trotzdem ausgefuehrt — bei drift `> 0` mit Welle-5-
Rollback im Hintergrund: yellow (Mira-Hand-Decision).

---

## §5 Rollback-Trigger — Exit-Decision-Matrix

Fuenf harte Trigger (drei Standard, zwei Welle-4-spezifisch). Bei
JEDEM einzelnen Trigger: sofort §6, keine Diskussion, keine
Eskalations-Verzoegerung. Mira-Hand entscheidet im Cutover-Window
autark, AR-Override nur post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.3) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | State-Backing-Service ERR-Zeile | Journal (§4.3) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | State-Read-Failure (Post-Restart-Hash-Drift) | §3.6 State-Read-Verify | Hash-Drift `PRE != POST` | Rollback (§6) |
| T-4 | Cross-Modul-Inkonsistenz mit lifecycle_state_machine | §4.4 Cross-Modul-Drift | Eine der 3 Achsen `< threshold` | Rollback (§6) + Welle-5-Koordinations-Marker |
| T-5 | Cross-Lang-Hash-Drift | §4.2 Parity-Probe | Jede einzelne Drift in 5 Samples | Rollback (§6) |

**T-3 Begruendung (Welle-4-spezifisch):** State-Read-Failure ist
nicht reine Performance — sie ist Substrate-Konsistenz. Hash-Drift
zwischen Python-write und Rust-read heisst: das Rust-Backend
deserialisiert den Engine-State nicht zu derselben kanonischen
Form. Engine-State-Drift in laufender Engine ist ein Korruption-
Pfad fuer FSM-Transitions und Mailbox-Cursor (beide schreiben
durch State-Backing). Rollback ist Pflicht; keine yellow-Toleranz.

**T-4 Begruendung (Doppel-Welle-Cross-Modul):** Cross-Modul-Drift
gegen `lifecycle_state_machine` heisst entweder Schema-Drift in
State-Backing-Schreibweise ODER FSM-Transition-Drift. Beide Faelle
sind blocker-level fuer Engine-State-Continuity. **Welle-5-
Koordinations-Marker** wird gesetzt: `/var/lib/wakir/audit-holds/
welle-4-cross-modul-drift-<TS>.marker` — Welle-5 muss entsprechend
mit-rollback'n falls noch nicht stable.

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1 Exit 1).
- Latency p99 > 2.0× Baseline (§4.3 Warn-Schwelle).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  <0.1%).
- Welle-5-Boot-Audit-FAIL waehrend Welle-4 OK (§4.5 Cross-Welle-
  Yellow, Mira-Hand-Decision).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt, Service-
Restart, Verify Backend=python, **State-Snapshot-Read-Verify
gegen Pre-Cutover-Baseline** (Welle-4-spezifischer State-Recovery-
Step). Welle-1+2+3-State bleibt unberuehrt — nur das Welle-4-
Overlay-File wird entfernt.

**Welle-5-Koordination:** Wenn T-4 Trigger (Cross-Modul-Drift mit
Welle-5): Welle-5-Rollback parallel mit Welle-4-Rollback. Schritt
5 unten beschreibt die Welle-5-Koordinations-Eskalation.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-4 Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-4-cutover.log

# 1. Env-Overlay entfernen — NUR Welle-4-Drop-In, Welle-1+2+3 bleiben
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-4-state-backing-rust.conf
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet: welle-1-* + welle-2-* + welle-3-* bleiben; welle-4-* weg.
systemctl daemon-reload

# 2. Service-Restart
systemctl restart wakir-persona-engine.service
TS_RB_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 3. Verify backend=python (5 BackendDecision-Records innerhalb 30s)
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
    if "BackendDecision" in msg and "state_backing" in msg and "backend=python" in msg:
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified for state_backing")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 4. State-Snapshot-Read-Verify gegen Pre-Cutover-Baseline (Welle-4-spezifisch).
# Python-Backend muss den Pre-Cutover-State-Snapshot wieder lesen koennen
# und denselben Hash liefern wie vor Cutover. Drift hier heisst:
# der Pre-Cutover-State ist nicht mehr verifizierbar lesbar — Engine-
# State-Korruption-Verdacht, AR-Hand-Stop-Marker Pflicht.
PRE_HASH=$(grep -oP '^[a-f0-9]{64}' \
    /var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.sha256)
sleep 10  # Engine-Boot-Stabilisierung
/opt/wakir/bin/wakir-persona-engine-state-backing \
    --mode=verify-read \
    --backend=python \
    --input=/var/lib/wakir/welle-4-state-baseline/pre-cutover-state-${TS_PRE}.json \
    --output=/var/lib/wakir/welle-4-state-baseline/post-rollback-state-python-${TS_RB}.json
POST_RB_HASH=$(sha256sum /var/lib/wakir/welle-4-state-baseline/post-rollback-state-python-${TS_RB}.json \
    | grep -oP '^[a-f0-9]{64}')
echo "Pre-Cutover-Hash: ${PRE_HASH}  Post-Rollback-Hash: ${POST_RB_HASH}" \
    | tee -a /var/log/wakir/welle-4-cutover.log

if [ "${PRE_HASH}" != "${POST_RB_HASH}" ]; then
    echo "ROLLBACK-STATE-CONTINUITY-FAIL: hash drift between pre-cutover python-write and post-rollback python-read" >&2
    echo "AR-HAND-STOP-MARKER required" >&2
    touch /var/lib/wakir/audit-holds/welle-4-rollback-state-continuity-violation-${TS_RB}.marker
    exit 3   # exit-3 signalisiert AR-Hand-Stop-Marker, NICHT routine Rollback-Fail
fi

# 5. Welle-5-Koordinations-Pruefung (Doppel-Welle-Coupling).
# Wenn T-4 Trigger (Cross-Modul-Drift): Welle-5-Rollback parallel triggern.
# Wenn nur T-1/T-2/T-3/T-5 Trigger (Welle-4-local): Welle-5 darf in-flight bleiben,
# aber Mira-Hand-Decision-Point ob Welle-5-Sign-Off ohne Welle-4-Counterpart sinnvoll.
if [ -f /var/lib/wakir/audit-holds/welle-4-cross-modul-drift-*.marker ]; then
    echo "WELLE-5-COORDINATION-ROLLBACK required (T-4 Cross-Modul-Drift)" \
        | tee -a /var/log/wakir/welle-4-cutover.log
    # Welle-5-Rollback-Trigger: siehe Welle-5-Runbook §6 — Mira-Hand
fi

# 6. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-4 Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-4-cutover.log
```

**Eskalations-Schwelle bei Rollback-State-Continuity-Failure (exit-3):**
Wenn Schritt 4 ROLLBACK-STATE-CONTINUITY-FAIL meldet, ist das **kein**
routine-Rollback-Done sondern eine **AR-Hand-Stop-Marker-Bedingung**:

- Engine-State ist nicht mehr verifizierbar lesbar.
- Marker-File `/var/lib/wakir/audit-holds/welle-4-rollback-state-
  continuity-violation-*.marker` wird gesetzt.
- Eskalation Mira -> Priya -> AR sofort.
- Welle-5 (parallel KW-26) muss auch gestoppt werden bis State-
  Recovery-Decision vorliegt.
- Welle-6+7 (KW-27 geplant) ist blockiert.

Nach erfolgreichem Rollback (kein exit-3): 30-min Stabilitaets-
Beobachtung (Welle-1/2-Standard) mit BackendDecision-Aggregator
(§4.1, --target-backend python), State-Backing-Error-Monitor (§4.3),
und Cross-Modul-Drift-Check gegen Welle-5 (§4.4 mit aktuellem
Welle-5-Status). Dann §7 Sign-Off mit verdict=`rollback`, Root-
Cause-Analyse binnen 48h pflichtig:

- **Reza** — state-backing Rust-CLI-Substrate-Owner, JCS-Canonical-
  Form-Drift-Investigation, State-Schema-Migration-Validation.
- **Tomás** — Cross-Modul-Korrelation mit lifecycle_state_machine.
- **Henrik** — Audit-Trail-Integrity, State-Continuity-Verify.

---

## §7 Sign-Off — Henrik-Audit-Trail

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off ist
Pflicht **vor Welle-6+7-Trigger** (KW-27 geplant). Welle-4-Sign-Off
korreliert mit Welle-5-Sign-Off (Doppel-Welle-Coupling).

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-4-smoke-*.json` (§2 Skript-Output)
- Welle-4-Wednesday-Validation-`cutover-acceptance-decision-welle-
  4.json` (§1, GitHub-Actions-Artifact-URL, mit
  `cross_modul_stress_passed == true`)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-4-pre-
  cutover-*.json` (post-Welle-1+2+3, frisch)
- BackendDecision-Aggregator-Snapshot (§1, Python-Default
  `state_backing` ≥99%)
- **Pre-Cutover-State-Snapshot** (§3.2.5,
  `/var/lib/wakir/welle-4-state-baseline/pre-cutover-state-*.json`
  + SHA-256-Hash + Schema-Version)
- Welle-3-Sign-Off-Status (§1, Pflicht-Vorbedingung)
- Welle-5-Pre-Conditions-Status (§1, Doppel-Welle-Coupling)

**TEL-Evidenz (waehrend §4 15-min Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1, 15-min Window JSON)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 5/5 oder Abweichung)
- State-Backing-Error-Count + Latency-Histogramm (§4.3, 0-Zeilen-
  File + 3 Grafana-Screenshots)
- Cross-Modul-Drift-Check-Output (§4.4,
  `/tmp/welle-4-cross-modul-drift.json`, 3/3 Achsen >= threshold
  Pflicht)
- Welle-5-Cross-Status-Snapshot (§4.5, Welle-5-Cutover-Log-Tail)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-4-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- State-Read-Verify-Output (§3.6 PRE_HASH == POST_HASH; bei Rollback
  §6 Schritt 4 PRE_HASH == POST_RB_HASH)
- Bei Rollback: Welle-5-Coordination-Status (parallel-Rollback ja/nein)
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`,
  oder **`ar-hand-stop`** bei exit-3 State-Continuity-Violation)
- Welle-5-Sign-Off-Status (Cross-Welle-Korrelation)
- AR-Approval-Tag fuer Welle-6+7-Trigger (nur bei `green` ODER
  `green-with-yellow-notes` UND Welle-5-Sign-Off mind. yellow)

**Sign-Off-Template:**

```yaml
welle: 4
component: state_backing
variant: rust_inmemory
cutover_date: 2026-06-22
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
verdict: green | green-with-yellow-notes | rollback | ar-hand-stop
yellow_notes: []
red_triggers_hit: []
# Welle-4-spezifische Achsen:
state_read_compatibility_hash_match: true | false  # MUSS true fuer green
cross_modul_drift_axes_pass: 3   # MUSS 3 fuer green (state_backing x FSM)
# Cross-Welle-Coupling:
welle_3_signoff_status: green | green-with-yellow-notes | rollback
welle_5_signoff_status: green | green-with-yellow-notes | rollback
# Evidenz-Pfade:
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
pre_cutover_state_sha256: <hash>
ar_approval_tag_for_welle_6_7: null  # gesetzt durch AR post-Sign-Off
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-4-state-backing-signoff-2026-06-22.yaml`

---

## §8 Mira-SSH-Hand-Authority + AR-Hand-Stop-Marker

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-Hand-
Authority fuer Pilot-VM-Operations.

**Mira-Hand-Operations (autark, identisch zu Welle-1-3):**
systemctl restart, Env-Overlay-File-Edits, Journal-Reads, Quadlet-
Override-Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
State-Backing-CLI-Snapshot-Creation (read-only).

**AR-Hand-Operations (irreversibel-despawn, identisch zu Welle-1-3):**
`podman rm` ohne Backup, Volume-Wipe (`podman volume rm`), System-
Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade, Disk-
Repartitionierung.

**Welle-4-Neu — AR-Hand-Stop-Marker-Bedingungen:**

Drei Bedingungen triggern automatisch ein Marker-File und
sofortige AR-Eskalation (Mira -> Priya -> AR):

1. **Rollback-State-Continuity-Violation** (§6 exit-3) — State-
   Snapshot nach Rollback nicht hash-verifizierbar zum Pre-Cutover-
   State.
2. **T-3 State-Read-Failure (Post-Restart-Hash-Drift)** — Engine-
   State korrupt durch Rust-Backend-Deserialisierung.
3. **T-4 Cross-Modul-Drift + Welle-5-Coordination-Fail** — wenn
   Welle-5-Rollback nicht erfolgreich nach Welle-4-T-4-Trigger.

Marker-File-Pfad-Pattern:
`/var/lib/wakir/audit-holds/welle-4-<bedingung>-<TS>.marker`

Bei AR-Hand-Stop-Marker: Welle-6+7 (KW-27) sind blockiert bis
AR-Decision-Output vorliegt. Henrik-Hand-Forensik-Pflicht binnen
72h. Welle-5 muss parallel gestoppt werden.

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-Kombination):
   Mira-Hand-Decision autark. Henrik-Audit protokolliert.
2. **Substanz-Konflikt** (z.B. State-Read-Failure ODER Cross-Lang-
   Hash-Drift): Mira-Hand Rollback nach §6, dann Eskalation Mira
   -> Priya -> Reza (state-backing-Rust-Substrate-Owner).
3. **State-Continuity-Violation** (T-3 oder Rollback exit-3):
   AR-Hand-Stop-Marker setzen, sofortige Mira -> AR-Eskalation,
   kein Welle-6+7-Trigger.
4. **Cross-Modul-Drift mit Welle-5** (T-4): Welle-5-Koordinations-
   Marker, parallel-Rollback Welle-4+5, danach Eskalation Mira ->
   Priya -> Tomás (Cross-Modul-Korrelations-Owner).
5. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-Drop):
   Mira-Hand Rollback, dann Eskalation Mira -> AR fuer Recovery.

---

## §9 Bekannte Risiken

**R-1 — Cross-Modul-Drift zu Welle-5 parallel-Cutover**
ADR-0066 §Option-A+ erlaubt Welle-4+5 parallel im KW-26. State-
Backing und FSM (lifecycle_state_machine) teilen State-Mutation-
Semantik (FSM-Transition schreibt durch State-Backing). Ein
Schema-Drift in einem der beiden Substrate erscheint als Doppel-
Welle-Symptom, nicht als Single-Modul-Issue. Mitigation: §4.4
Cross-Modul-Drift-Check mit `doppelbetrieb-score-aggregator
--mode=cross-modul-stress` (PR #197) als Pflicht-Step; T-4 Trigger
bei Drift > 0; Welle-5-Koordinations-Marker im Rollback-Pfad.
Sekundaere Mitigation: Doppel-Welle-Sequenz (§3.0) — Welle-4-§3
beginnt zuerst, Welle-5-§3 folgt nach Welle-4-Boot-Audit-Pass.

**R-2 — State-Migration-Backward-Compat (rust_inmemory liest python-write)**
State-Backing ist die erste Phase-3c-Welle mit Engine-State-
Persistenz-Beteiligung. Wenn Rust-Backend den Python-write-State
nicht zu derselben kanonischen Form deserialisiert: Hash-Drift in
§3.6, sofortiger Rollback-Trigger T-3. **Kritisch:** Rollback
selbst muss den State weiterhin lesbar machen — §6 Schritt 4
verifiziert das. Bei Hash-Drift post-Rollback: AR-Hand-Stop-Marker
(exit-3), Engine-State-Korruption-Verdacht. Mitigation: Reza-Tag-
17/33-Cross-Lang-Test-Coverage (`tests/fixtures/state-backing-
cross-lang/fixtures.json` ≥ 5 Pins) als Wednesday-Validation-Step
Pflicht-Gate.

**R-3 — Persistence-Layer-Cosign-Pin (Tag-33 Mini-Welle-Carrier)**
Quadlet-Inventar Tag-33 Mini-Welle (`state-backing-welle4` Carrier-
Image-Update via `quadlet/wakir-rust-cli.container`) liegt
zwischen Welle-3-Cutover und Welle-4-Cutover. Wenn Carrier-Image-
Tag zwischen Wednesday-Validation und Monday-Cutover mutiert:
Cosign-Verify in §1 Gate-1 wuerde nicht zwingend bemerken.
Mitigation: Pre-Cutover-Step zusaetzlich `podman image inspect
ghcr.io/wakir-labs/wakir-persona-engine | grep Digest` gegen
Wednesday-Validation-Digest-Pin. **Zusatz fuer Welle-4:** der
Carrier-Image hat **zwei** state-backing-Binaries (`wakir-persona-
engine-state-backing` Tag-17-Origin + `wakir-persona-engine-state-
backing-welle4` Tag-33-Variant) — beide muessen verifiziert sein.

**R-4 — Variant-Selection-Drift (rust_inmemory vs rust_natskv)**
Resolver akzeptiert beide Variants. Welle-4-Cutover ist
`rust_inmemory` (ADR-0066 Phase-3c-Default). Wenn Env-Overlay
faelschlich `rust_natskv` setzt: Engine versucht NATS-KV-Connect,
das ist nicht Teil von Phase-3c-Substrate (Phase-3d-Folge-
Migration). Mitigation: §3.3 Env-Overlay-File enthaelt exakten
String `rust_inmemory`; §3.5 Boot-Audit-Filter prueft auf
`backend=rust_inmemory` (nicht `backend=rust_natskv`); §4.1
Aggregator `--target-backend rust_inmemory`.

**R-5 — Welle-5-Solo-Vorzieh-Risiko**
Wenn Welle-5-Pre-Conditions yellow ist (§1 Welle-5-Coupling-
Status (b)) und Mira-Hand-Decision: "Welle-4 solo, Welle-5
verschiebt sich um eine Woche": Cross-Modul-Stress-Test §4.4
laeuft trotzdem, aber gegen Python-Default-FSM (keine Doppel-
Welle-Cross-Lang-Achse). Welle-4-Sign-Off bleibt moeglich, aber
Welle-5-Re-Schedule auf KW-27 verschiebt Welle-6+7 auf KW-28.
Mitigation: Pre-Conditions §1 dokumentiert die drei Welle-5-
Coupling-Zustaende explizit; Mira-Hand-Decision ist
protokolliert.

**R-6 — Welle-3-Rollback-Coupling**
Falls Welle-3 `rollback` ODER `ar-hand-stop` (§1 zulaessiger
Zustand (c)): Welle-4+5 (KW-26) sind BLOCKIERT. Begruendung:
Bridge-Audit-Writer-Rollback signalisiert Audit-Stream-Substrate-
Anomalie; State-Backing-Cutover schreibt State-Audit-Annotations
in den Bridge-Audit-Stream, ein Welle-3-Rollback bedeutet die
Audit-Substrate ist nicht stabil — Cross-Modul-Drift wuerde
falsch-positiv triggern. AR-Eskalation Pflicht; Welle-4+5-Re-
Scheduling ist AR-Decision.

**R-7 — Engine-State-Persistenz-vs-Volatile-Substrate**
State-Backing-Variant `rust_inmemory` ist **volatile** (Engine-
Restart loescht State). Welle-4-Cutover-Pattern erfordert Engine-
Restart in §3.4. Daher: State muss VOR Restart in einer extern-
persistenten Form sein (`pre-cutover-state-*.json` Datei).
§3.2.5 erfasst diesen Snapshot; §3.6 verifiziert dass das Rust-
Backend nach Restart denselben Snapshot lesen kann. Bei Variant-
`rust_natskv` (Phase-3d) entfaellt das Volatility-Problem — das
ist aber **nicht** Welle-4-Scope. Mitigation: §3.2.5 Pre-Cutover-
Snapshot ist Pflicht-Step, ohne den ist State-Continuity nicht
beweisbar.

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, **Montag KW-26 (2026-06-22)**,
**10:00-14:00 CEST Cutover-Window** (4h, identisch zu Welle-1/2-
Window, weil Doppel-Welle-Pattern mehr Operator-Bandbreite braucht
als Welle-3-Solo-3h-Window).

**Konkretes Cutover-Window — Welle-4 (parallel Welle-5):**

| Sub-Phase | Slot CEST |
|---|---|
| Pre-Conditions Walk-Through (Welle-4 + Welle-5 sync) | 10:00-10:20 |
| Pre-Flight-Smoke Welle-4 (§2) + Welle-5-Smoke (parallel) | 10:20-10:30 |
| Pre-Cutover-State-Snapshot (§3.2.5) Welle-4 | 10:30-10:40 |
| Cutover-Step Welle-4 (§3.1-§3.6) | 10:40-11:00 |
| Cutover-Step Welle-5 (parallel, startet nach Welle-4 §3.6) | 11:00-11:20 |
| Soak-Window Welle-4+5 (§4, 15-min) | 11:20-11:35 |
| Cross-Modul-Drift-Check (§4.4) | 11:35-11:50 |
| Sign-Off-Initial-Draft (§7) Welle-4 + Welle-5 | 11:50-12:30 |
| Reserve — Rollback + State-Continuity-Verify (Welle-4 ODER 5 ODER beide) | 12:30-14:00 |
| **Pause + Audit-Trail-Submission an Henrik** | 14:00-15:30 |
| Henrik-Audit-Sign-Off-Window (Welle-4 + Welle-5) | 15:30-17:00 |

**Datum: Montag 2026-06-22 (KW-26)**

- **Welle-4-Cutover-Start:** 10:00 CEST
- **Welle-4-Latest-Commit-To-Rust:** 11:00 CEST (Boot-Audit-Pass)
- **Welle-5-Cutover-Start:** 11:00 CEST (nach Welle-4-§3.6)
- **Welle-4+5-Soak-Window-Ende:** 11:35 CEST
- **Welle-4+5-Sign-Off-Window-Ende:** 17:00 CEST
- **Hairpin-Rollback-Slot:** Mittwoch 2026-06-24, 09:00-13:00 CEST

**Begruendung Werktag-Vormittag + Doppel-Welle-Sequenz + 4h-Window:**

1. **Doppel-Welle:** Pre-Conditions Walk-Through und Pre-Flight-
   Smokes sync zwischen Welle-4 und Welle-5 (Mira-Hand-Owner
   beider). 4h-Window deckt Welle-4-§3 + Welle-5-§3 + gemeinsamer
   Soak-Window + Reserve fuer parallel-Rollback ab.
2. **Welle-5-Sequenz-Constraint:** Welle-5-Cutover startet erst
   nach Welle-4-§3.6 Post-Restart-State-Read-Verify (siehe §3.0).
   Welle-5-Cutover-Window-Start ist daher ~60min nach Welle-4-
   Start.
3. **Cross-Modul-Drift-Check (§4.4):** Pflicht-Step im Soak-Window
   weil Doppel-Welle-Coupling. Zusaetzliche 15min-Slot vor Sign-Off.
4. **Henrik-Sign-Off-Window 15:30-17:00:** Henrik prueft Welle-4-
   Sign-Off und Welle-5-Sign-Off als korreliertes Paar (Cross-
   Welle-Coupling-Check). Welle-1+2-Sign-Off war ebenfalls
   paralleler Pattern, aber State-Backing + FSM ist Cross-Modul-
   intensiver.
5. **Hairpin-Rollback-Slot Mi (KW-26):** Falls Welle-4 ODER 5
   ODER beide yellow-with-Henrik-Hand-Approval-Bedarf — Mittwoch-
   Vormittag (09:00-13:00, 4h-Window) ist der naechste sinnvolle
   Slot.
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

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Reza (state-backing-Rust-Substrate-Owner) | bei JCS-Canonical-Drift, State-Schema-Migration-Issue, State-Read-Hash-Drift |
| 3 | Tomás (Matrix-Lead) | bei Welle-4/5-Cross-Modul-Korrelation, Doppel-Welle-Coupling-Konflikt |
| 4 | Henrik (Internal Audit) | bei Audit-Trail-Anomaly, T-3 oder T-4 Trigger, F-Item-Reactivation |
| 5 | AR (Fred) | bei AR-Hand-Stop-Marker, Rollback-State-Continuity-Violation (§6 exit-3), Welle-3-Rollback-Coupling-Block, Phase-3c-Sequenz-Re-Sequencing |

---

## Anhang B — Cross-Welle-Coordination-Checkliste

Vor Welle-4-Cutover-Start: explizite Verifikation der Welle-1+2+3-
Coordination-Items und der Welle-5-Parallel-Coordination.

- [ ] Welle-1-Runbook gelesen ([`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md), PR #228 Tag-34)
- [ ] Welle-2-Runbook gelesen ([`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md), PR #232 Tag-35)
- [ ] Welle-3-Runbook gelesen ([`welle-3-bridge-audit-writer-runbook.md`](./welle-3-bridge-audit-writer-runbook.md), PR #237 Tag-36)
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
- [ ] Welle-1-`v907_verify` `backend=rust` im Aggregator >99% (Welle-4-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-2-`svid_workload_identity` `backend=rust` im Aggregator >99% (Welle-4-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-3-`anchor_emitter` `backend=rust` im Aggregator >99% (Welle-4-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-4-Engine-Health-Baseline frisch aufgezeichnet POST-Welle-1+2+3 (nicht uebertragen aus Welle-1/2/3-Pre-Baselines)
- [ ] Welle-4-spezifischer Pre-Cutover-State-Snapshot vorhanden (§3.2.5, SHA-256-Hash protokolliert)
- [ ] Welle-5-Pre-Conditions-Status gepruft (§1 Coupling-Zustaende a/b/c)
- [ ] Doppel-Welle-Sequenz §3.0 verstanden (Welle-4-§3 vor Welle-5-§3)
- [ ] Cross-Modul-Stress-Test Wednesday-Run gruen (Pflicht aus ADR-0066 §Mitigations)

---

## Anhang C — Welle-4-spezifische Cross-Spawn-Coordination (Tag-37)

Tag-37 hat parallele Spawns laufen lassen (Continuous-Mode):

| Spawn | Owner | Artefakt | Pfad |
|---|---|---|---|
| Welle-4-Operator-Runbook (dieses Dokument) | Kai | `docs/phase-3c/welle-4-state-backing-runbook.md` | dieses File |
| Welle-4-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh` | Pfad in §2 zitiert |
| Welle-5-Operator-Runbook (Folge-Spawn) | Kai | `docs/phase-3c/welle-5-lifecycle-state-machine-runbook.md` | parallel Tag-37 |
| Welle-5-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh` | Selin parallel Tag-37 |
| Tomás-Tag-37-Workflow-Adjustment (Welle-4+5) | Tomás | CI-Workflow-Validation | siehe Tomás-Tag-37-Liefer-Bericht |
| Reza-Tag-37-Substrate (Welle-4 Substanz) | Reza | Substanz-Coverage-Spawn | siehe Reza-Tag-37-Liefer-Bericht |

Pre-Cutover-Cross-Spawn-Verifikation (in §1 implizit, hier
explizit gelistet): alle Tag-37-Artefakte muessen auf main
gemerged sein vor Welle-4-Wednesday-Validation-Run-Trigger
(KW-25-Mittwoch 2026-06-17).

---

— Kai Hoffmann (DevOps), Sprint-Tag-37, 2026-05-18.
