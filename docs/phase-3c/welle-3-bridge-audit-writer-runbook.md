---
title: "Phase-3c Welle-3 bridge_audit_writer Operator-Cutover-Runbook"
owner: "Kai Hoffmann (DevOps), Tomas Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit) — Henrik-Caution-Sign-Off Pflicht"
adr: "0065, 0066"
welle: 3
component: "bridge_audit_writer"
component_alias: "anchor_emitter"
env_var_long: "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
env_var_resolver: "WAKIR_ANCHOR_EMITTER_BACKEND"
cutover_date: "2026-06-15"
cutover_window_cest: "09:00-12:00"
signoff_window_cest: "13:30-15:00"
hairpin_rollback_window_cest: "Mi 09:00-12:00"
soak_window_minutes: 30
status: "ready-for-ar-pre-sichtung"
sprint_tag: 36
parallel_welle: "none (solo per ADR-0066)"
risk_class: "henrik-caution-high"
---

# Phase-3c Welle-3 bridge_audit_writer Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-3-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die
`bridge_audit_writer`-Komponente der Persona-Engine, 9. emittierte
`BackendDecision`, Resolver-Alias `anchor_emitter`). Ziel-Cutover-
Datum: Montag 2026-06-15, KW-25, **solo** gemaess ADR-0066
§"Bridge-Audit-Welle bleibt strikt solo".

Dies ist das **operative Day-Of-Skript**. Hermetic-Validation
(`phase-3c-welle-3-validation.yml`) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-3-runbook.md`](../operations/phase-3c-welle-3-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM, echter
NATS-Bus, echte Quadlet-Restart-Sequenz, echte Bridge-Audit-Stream-
Beobachtung — und kritisch: **Audit-Stream-Continuity** waehrend
das Audit-Oracle selbst geflippt wird.

Schwester-Runbooks (parallel-Sign-Off-Kette KW-24 -> KW-25):

- [`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md)
  (PR #228, Tag-34, Welle-1 `v907_verify` KW-24 Montag).
- [`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md)
  (PR #232, Tag-35, Welle-2 `svid_workload_identity` KW-24 Montag,
  sequenziell nach Welle-1).

## Henrik-Caution-Charakter (ADR-0066 §Bridge-Audit-Welle-solo)

**Welle-3 ist die einzige Welle in der die zu cutover'nde Komponente
identisch ist mit dem Audit-Oracle, das die Cutover-Konsistenz
beobachten muesste.** Der `bridge_audit_writer` ist das Substrat
hinter dem kanonischen Cross-Lang-Konsistenz-Oracle
`tests/integration/test_bridge_audit_roundtrip_e2e.py`. Welle-1 und
Welle-2 haben dieses Oracle in Step 4 ihrer Validation genutzt;
Welle-3 darf das nicht — sonst zertifiziert das Subjekt sich selbst.

**Drei Henrik-Caution-Items (Tag-27 Audit-Trail-Setup):**

1. **Konsistenz-Oracle-Self-Reference-Trap** — der Cutover-Step
   darf das Audit-Oracle nicht selbst zur Verifikation des
   Cutovers verwenden. Independent-Oracle via
   `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-
   stress` (siehe §3.5, §4.1).
2. **Cross-Modul-Drift** — `bridge_audit_writer` ist Konsument von
   `anchor_emitter`-Output und Lieferant fuer `bridge_diff`-Audit-
   Continuity. Cross-Modul-Drift gegen diese beiden Module ist
   ein hartes Veto (§4.4, §5 T-4).
3. **Audit-Trail-Continuity** — der Audit-Stream darf waehrend
   des Restart-Fensters nicht laenger als 30s unterbrochen sein,
   sonst entstehen unverlinkbare Audit-Bloecke im Henkrik-
   Cumulative-Audit-Log (§4.3, §5 T-3).

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ + Solo-Welle-Constraint | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Welle-3 Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-3-validation.yml` |
| Welle-3 Sibling-Validation-Runbook | `docs/operations/phase-3c-welle-3-runbook.md` |
| Welle-1 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-1-v907-verify-runbook.md` (PR #228, Tag-34) |
| Welle-2 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-2-svid-workload-identity-runbook.md` (PR #232, Tag-35) |
| Bridge-Audit-Writer Container-Image-Build-Pipeline | PR #210 (`0168ac3`, Tag-31) — `docs/operations/bridge-audit-writer-image-build.md` |
| Bridge-Audit-Writer Cross-Lang-Hash-Parity-Pins | `tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json` (Tag-33 Derivat, `scripts/derive-bridge-audit-writer-fixtures.py`) |
| Resolver `resolve_anchor_emitter_backend` | `wirelang/persona_engine/rust_backend_switch.py` (DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN L467, env-const `BRIDGE_AUDIT_WRITER_BACKEND_ENV` L435) |
| Resolver-Aliasmap | `scripts/phase-3c-cutover-dry-run.py::PHASE_3C_COMPONENT_ALIASES` |
| Independent-Oracle Cross-Modul-Stress | `scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress` (PR #197, Henrik-Caution-Mitigation) |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Quadlet-Inventar (9-Binary) | `quadlet/wakir-rust-cli.container` (Item 9 = `wakir-persona-engine-bridge-audit-writer`) |
| Cosign-Policy (9-Binary) | `policies/cosign-policy-phase-3b.yaml` Zeile 330 `name: bridge-audit-writer` |
| Welle-3 Telemetry-Runbook | `docs/operations/welle-3-telemetry-runbook.md` |
| Welle-1-2-Doppel-Telemetry-Runbook (Vorgaenger-Telemetry) | `docs/operations/welle-1-2-doppel-telemetry-runbook.md` |
| Bridge-Audit-Stream-Hash-Modul | `wirelang/persona_engine/bridge_audit_stream_hash.py` |
| Bridge-Audit-Diff-Engine | `wirelang/persona_engine/bridge_audit_diff_engine.py` |
| Bridge-Audit-Triangle (Cross-Modul-Korrelation) | `wirelang/persona_engine/bridge_audit_triangle.py` |
| Selin Welle-3 Cutover-Smoke-Skript | `scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh` (Selin Tag-36, parallel zu diesem Runbook) |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya. **Welle-3 hat
zusaetzlich Henrik-Caution-Pre-Gate (siehe Item ★).**

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar 9-Binary)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `bridge-audit-writer` als 9. Persona-Engine-Binary
      (`name: bridge-audit-writer` Zeile 330, mit
      `in_image_path: /opt/wakir/bin/wakir-persona-engine-bridge-
      audit-writer`).
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 9 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` Tag-31-Update
      enthaelt `wakir-persona-engine-bridge-audit-writer` als
      Item 9 der `Exec=`-Schleife des Installer-Containers.
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence: `wirelang/persona_engine/rust_backend_switch.py`
      enthaelt `BRIDGE_AUDIT_WRITER_BACKEND_ENV =
      "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"` (L435) und
      `DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN ==
      /opt/wakir/bin/wakir-persona-engine-bridge-audit-writer`
      (L467). Resolver-Alias-Tabelle (`PHASE_3C_COMPONENT_ALIASES`
      in `scripts/phase-3c-cutover-dry-run.py`) mappt
      `bridge_audit_writer -> anchor_emitter`.
      Engine-Boot-Audit emittiert 9. `BackendDecision` mit
      `component=anchor_emitter` (Resolver-Schreibweise).
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — **Welle-3-spezifischer
      Modus**: passt im Python-Default-Pfad gegen Tag-N-1-Baseline
      (read-only Smoke), aber DIESES Ergebnis ist **nicht** das
      Welle-3-Cutover-Acceptance-Oracle (Henrik-Caution-Item 1).
      Pre-Cutover-Gate-5 dient nur als Engine-Health-Smoke fuer
      den Pre-Cutover-Zustand.
- [ ] **Welle-3-Wednesday-Validation-Run gruen** (2026-06-10
      06:00 UTC, KW-24 Mittwoch — 5 Tage vor Cutover-Montag KW-25).
      Evidence: `cutover-acceptance-decision-welle-3.json`
      `ready_for_live_smoke == true` UND
      `henrik_caution_applied == true` UND
      `step_4_oracle == "cross-modul-stress-aggregator"`.
      Artifact-Retention 30 Tage. Workflow:
      `.github/workflows/phase-3c-welle-3-validation.yml`.
- [ ] **Welle-2-Sign-Off-Verdict bekannt** (KW-24 Montag,
      `verdict: green` ODER `green-with-yellow-notes` Pflicht).
      Drei zulaessige Zustaende fuer Welle-3-Trigger:
      - **(a) Welle-2 `green` Sign-Off** — Welle-3 startet planmaessig KW-25 Montag.
      - **(b) Welle-2 `green-with-yellow-notes`** — Welle-3 startet,
        aber Mira-Hand-Decision-Point mit explizitem Yellow-Notes-
        Review im Cutover-Window UND **Henrik-Hand-Approval Pflicht
        binnen 48h vor Welle-3-Start** (ADR-0066 §Bridge-Audit-
        Welle-solo, Cross-Wave-Risk-Klausel).
      - **(c) Welle-2 `rollback`** — Welle-3 wird VERSCHOBEN, nicht
        gestartet. AR-Eskalation Pflicht (§9 R-7).
- [ ] **Welle-1-Sign-Off-Verdict bekannt** (KW-24 Montag,
      mind. `green-with-yellow-notes` Pflicht). Bei
      Welle-1-`rollback` UND Welle-2-`rollback` UND noch nicht
      remedi'iert: Welle-3 ist BLOCKIERT (§9 R-7-Coupling).
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, **post-Welle-1 + post-Welle-2 Engine-Posture**).
      Latency-p50/p95, Error-Rate, BackendDecision-Volume pro
      Minute, Bridge-Audit-Stream-Records-pro-Minute, Anchor-
      Emitter-Output-Rate. Persistiert in
      `/var/lib/wakir/baselines/welle-3-pre-cutover-<TS>.json`.
      **Wichtig:** Die Baseline wird **nach KW-24-Welle-1+2-Sign-
      Off und vor KW-25-Welle-3-Cutover** frisch aufgezeichnet — die
      Engine hat 2 von 9 Backends bereits auf Rust geflippt; eine
      Pre-Welle-1-Baseline ist nicht uebertragbar.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component anchor_emitter --window 5m --format json`
      liefert gueltige Records mit `backend=python` >99%
      (Baseline). **Resolver-Schreibweise pruefen** (Aggregator
      liest die Resolver-Aliasmap, also `anchor_emitter`, nicht
      `bridge_audit_writer`).
- [ ] **Quadlet 9-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 9 Binaries inklusive
      `wakir-persona-engine-bridge-audit-writer`.
- [ ] **Cosign-Policy 9-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit.
      Das transitiv-verifizierte Image-Manifest umfasst
      bridge-audit-writer-Image (PR #210 Tag-31) als Item 9 der
      Build-Inventory.
- [ ] **Bridge-Audit-Writer Cross-Lang-Hash-Parity-Pins frisch**.
      Evidence: `tests/fixtures/bridge-audit-writer-cross-lang/
      fixtures.json` existiert, Pin-Count ≥ 5, generiert via
      `scripts/derive-bridge-audit-writer-fixtures.py` mit Tag-N-1-
      Engine-Snapshot. Das ist die Baseline-Referenz fuer §4.2
      Cross-Lang-Hash-Parity-Probe.
- [ ] **Bridge-Audit-Stream-Continuity-Snapshot 24h gruen** —
      Henrik-Audit-Trail-Substrate-Pre-Gate (Tag-27 Audit-Setup).
      Evidence: `journalctl -u wakir-bridge-audit-writer.service
      --since "-24h" -p err --no-pager | wc -l` = 0 UND
      `scripts/phase-3c-welle-status-emitter.py
      --component anchor_emitter --window 24h` liefert
      `audit_stream_gap_max_seconds < 5`.
- [ ] **★ Henrik-Caution-Pre-Gate (Welle-3-spezifisch)** —
      Independent-Oracle-Wednesday-Snapshot `cross-modul-stress-
      rollup.json` (KW-24 Mittwoch Validation-Workflow-Artifact)
      liegt vor UND alle 3 Cross-Modul-Achsen `>= threshold`
      (`cross-lang-pin-coverage`, `cross-modul-fixture-stability`,
      `cross-modul-rollup-integrity`). Wenn eine der 3 Achsen
      `< threshold`: Stop, Henrik-Hand-Eskalation, kein Cutover.
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt** —
      Mittwoch KW-25, 09:00-12:00 CEST (3h-Slot, **erweitert** vs.
      Welle-1+2 wegen Henrik-Caution-Coordination-Overhead).

---

## §2 Pre-Flight-Smoke

Selin's Welle-3-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet
zur Pilot-VM testet und kein Pilot-internes Artefakt ist. Skript
liefert Selin **parallel zu diesem Runbook** (Tag-36 Cross-Spawn).

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component bridge_audit_writer \
    --component-alias anchor_emitter \
    --env-var-long WAKIR_BRIDGE_AUDIT_WRITER_BACKEND \
    --env-var-resolver WAKIR_ANCHOR_EMITTER_BACKEND \
    --independent-oracle cross-modul-stress \
    --audit-stream-continuity-window 24h \
    --dry-run-window 5m \
    --json-out /tmp/welle-3-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated ODER Welle-2-`green-with-yellow-notes` post-hoc UND
  Henrik-Hand-Approval-File vorhanden).
  Mira-Hand-Decision noetig vor §3. **Welle-3-Yellow ist nicht
  identisch zu Welle-1/2-Yellow** — Henrik-Caution erfordert
  explizite Henrik-Approval-File im 48h-Pre-Window.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Tomás (Matrix-Lead) + Henrik (Audit-Sign-Off).
  **Bei red: kein Cutover-Versuch ohne Henrik-Hand-Override.**

Das JSON-Envelope (`/tmp/welle-3-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~3-5 min wall-clock (laenger als Welle-1/2
wegen Audit-Stream-Continuity-Probe und Independent-Oracle-Re-Run).
Skript prueft SSH-Reachability, Quadlet-Status-Snapshot, Cosign-
Policy-Match (9-Binary), Engine-Health-Baseline-Delta gegen Tag-N-1,
Bridge-Audit-Stream-Continuity-Window (24h, Gap-Max-Threshold),
BackendDecision-Aggregator-Sanity fuer `component=anchor_emitter`,
Independent-Oracle-Smoke (`cross-modul-stress-aggregator` 3-Axen-
Sample). Keine Side-Effects auf Pilot-VM (read-only).

**Welle-3-Solo-Sequencing-Hinweis:** Welle-3 ist **die einzige
solo-Welle** in der ADR-0066-Sequenz. Pre-Flight darf parallel zu
KW-24-Sign-Off-Review laufen, **aber** §3 Cutover-Step startet
erst nach Welle-1+2-Sign-Off-Initial (beide Verdicts vorhanden,
keiner = `rollback`). Begruendung: doppelte Backend-Migration in
benachbarter Engine-Posture macht den Cross-Modul-Drift-Check
(§4.4) instabil.

---

## §3 Cutover-Step

**Mira-Hand-SSH-Authority** gemaess ADR-0058 §Nachtrag. AR-
Eskalations-Override nur fuer `irreversible despawn`-Pfade —
Quadlet-Restart und Env-Overlay fallen darunter **nicht**, das
ist routine Operator-Hand-Operation. **Welle-3-spezifische
Erweiterung:** §3.2.5 Baseline-Audit-Stream-Snapshot Pflicht
**vor** dem Restart (Self-Reference-Trap-Mitigation).

**Schritt 3.1 — SSH auf Pilot-VM**

```bash
ssh root@192.168.178.116
# Erwarteter Banner: "wakir-pilot — FCOS — Phase-3b live"
```

**Schritt 3.2 — Pre-Restart-Snapshot (post-Welle-1+2)**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-3 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-3-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-3-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-3-cutover-pre-journal.txt

# Welle-1+2-State-Check: bestaetige dass v907_verify + svid_workload_identity
# backend=rust laufen (KW-24-Cutover bereits erfolgt).
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -cE "BackendDecision.*(v907_verify|svid_workload_identity).*backend=rust" \
  | tee -a /var/log/wakir/welle-3-cutover.log
# Erwartung: > 0 Records pro Component.
```

**Schritt 3.2.5 — Baseline-Audit-Stream-Snapshot (Self-Reference-Trap-Mitigation, Welle-3-spezifisch)**

**Kritisch.** Vor dem Restart muss eine immutable Baseline des
aktuellen Audit-Streams (Python-Default-Pfad) erfasst werden.
Wenn der Cutover failt und §6 Rollback noetig wird, dient diese
Baseline als Continuity-Referenz: der Audit-Stream nach Rollback
muss strukturell-aequivalent zum Pre-Cutover-Stream sein. Ohne
diesen Snapshot kann nicht zwischen "Rollback-Recovery erfolgreich"
und "Audit-Oracle stillschweigend kaputt" unterschieden werden.

```bash
# Auf Pilot-VM:
mkdir -p /var/lib/wakir/welle-3-audit-baseline
journalctl -u wakir-bridge-audit-writer.service --since "-15 min" \
    --output=json --no-pager \
    > /var/lib/wakir/welle-3-audit-baseline/pre-cutover-${TS_PRE}.jsonl
wc -l /var/lib/wakir/welle-3-audit-baseline/pre-cutover-${TS_PRE}.jsonl \
    | tee -a /var/log/wakir/welle-3-cutover.log
# Hash der Baseline zur immutability-Pruefung:
sha256sum /var/lib/wakir/welle-3-audit-baseline/pre-cutover-${TS_PRE}.jsonl \
    | tee -a /var/log/wakir/welle-3-cutover.log

# Engine-internal: aktueller Anchor-Emitter-Output-Index erfassen.
# Anchor-Index ist der monoton wachsende Sequenz-Counter im
# Bridge-Audit-Stream — Stream-Continuity nach Restart bedeutet:
# kein Index-Sprung > 1 und kein Index-Rewind.
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
  | grep "anchor_emitter.*output_index=" \
  | tail -3 \
  | tee /var/lib/wakir/welle-3-audit-baseline/pre-cutover-anchor-index-${TS_PRE}.txt
```

**Erwartete Evidenz:** Baseline-File-Size > 0, mind. 50 Audit-
Records (Python-Default-Volume), Anchor-Output-Index bekannt.
Wenn Baseline-Snapshot 0 Records hat: STOP — Audit-Stream ist
bereits vor dem Cutover unterbrochen, das ist ein Pre-Cutover-Red
und §6 ist nicht der richtige Pfad (Reza + Henrik eskalieren,
Cutover absagen).

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht
in-place edit. Reversibel, ADR-0058-konform. **Welle-3-spezifisch:
beide Env-Var-Schreibweisen** setzen (ADR-0065-long-form +
Resolver-short-form), gemaess Welle-3-Validation-Workflow Step 3.

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-3-bridge-audit-writer-rust.conf <<'EOF'
# Phase-3c Welle-3 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-Sequenz, ADR-0066 §Bridge-Audit-Welle-solo
# Beide Env-Var-Schreibweisen Pflicht (Resolver liest short-form,
# Operator + Audit-Trail lesen long-form).
[Service]
Environment="WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust"
Environment="WAKIR_ANCHOR_EMITTER_BACKEND=rust"
EOF
systemctl daemon-reload

# Sanity-Check: Welle-1 + Welle-2 Drop-Ins existieren weiterhin.
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet:
#   welle-1-v907-verify-rust.conf
#   welle-2-svid-workload-identity-rust.conf
#   welle-3-bridge-audit-writer-rust.conf  (neu)
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-3-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s, 9/9 BackendDecisions)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust` und `component=anchor_emitter` (Resolver-
Schreibweise) werden innerhalb 30s emittiert. Gleichzeitig
muessen alle 9 Boot-`BackendDecision`-Records sichtbar sein
(v907_verify, svid_workload_identity, anchor_emitter, +6 weitere)
— wenn nur 8/9: Migrations-Drift-Zustand, §6 Rollback ist Pflicht.

**Welle-3-spezifisch:** Filter sucht `anchor_emitter` (Resolver-
Schreibweise), nicht `bridge_audit_writer` (ADR-0065-long-form).
Das ist die Aliasmap-Tatsache aus
`scripts/phase-3c-cutover-dry-run.py::PHASE_3C_COMPONENT_ALIASES`.

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
    if "BackendDecision" in msg and "anchor_emitter" in msg and "backend=rust" in msg:
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision anchor_emitter rust-records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

**Schritt 3.6 — Bridge-Audit-Stream-Resumption-Verify (Welle-3-spezifisch)**

Spezifisch fuer Welle-3: nach Restart muss der Bridge-Audit-Stream
**vor T_RESTART + 30s** wieder Records emittieren UND der Anchor-
Output-Index muss strikt monoton wachsen relativ zum Pre-Cutover-
Baseline-Index (kein Rewind, kein Sprung > N+10).

```bash
# Auf Pilot-VM:
PRE_INDEX=$(cat /var/lib/wakir/welle-3-audit-baseline/pre-cutover-anchor-index-${TS_PRE}.txt \
    | grep -oP 'output_index=\K[0-9]+' | tail -1)
echo "Pre-Cutover-Anchor-Index: ${PRE_INDEX}" | tee -a /var/log/wakir/welle-3-cutover.log

timeout 30 journalctl -u wakir-persona-engine.service \
    --since "${TS_RESTART}" -f \
    --output=cat --no-pager \
  | grep "anchor_emitter.*output_index=" \
  | head -3 \
  | tee -a /var/log/wakir/welle-3-cutover.log

POST_INDEX=$(journalctl -u wakir-persona-engine.service \
    --since "${TS_RESTART}" --no-pager \
  | grep -oP 'anchor_emitter.*output_index=\K[0-9]+' \
  | head -1)
echo "Post-Cutover-Anchor-Index: ${POST_INDEX}" | tee -a /var/log/wakir/welle-3-cutover.log

if [ -n "${POST_INDEX}" ] && [ -n "${PRE_INDEX}" ]; then
    DELTA=$((POST_INDEX - PRE_INDEX))
    echo "Anchor-Index-Delta: ${DELTA}" | tee -a /var/log/wakir/welle-3-cutover.log
    if [ "${DELTA}" -lt 1 ]; then
        echo "STREAM-CONTINUITY-FAIL: index-rewind oder no-progress (Delta=${DELTA})" >&2
        exit 2
    fi
    if [ "${DELTA}" -gt 10 ]; then
        echo "STREAM-CONTINUITY-WARN: index-sprung Delta=${DELTA} > 10 (yellow)" >&2
    fi
else
    echo "STREAM-CONTINUITY-FAIL: kein Post-Index extrahiert" >&2
    exit 2
fi
```

Wenn Boot-Audit-Wait-Loop oder Stream-Resumption Exit ≠ 0:
sofort §6 Rollback-Procedure.

---

## §4 Post-Cutover-Verification (30-min Soak-Window — verlaengert wegen Henrik-Caution)

Soak-Window **30min** (doppelt so lang wie Welle-1/2-15min) wegen
Henrik-Caution-Items: Cross-Modul-Drift braucht laengere
Beobachtungs-Zeitspanne, da `bridge_audit_writer` Konsument von
zwei vorgeschalteten Modulen (`anchor_emitter`-Source-of-Truth)
und Lieferant fuer `bridge_diff`-Continuity ist. Fuenf parallele
Beobachtungs-Streams, jede mit harter Schwelle und Rollback-
Trigger.

**§4.1 — BackendDecision-Aggregator Sliding-Window + Independent-Oracle**

```bash
# Auf Mira-Box, gegen Pilot-NATS:
cd /var/home/fred/AI-Corp/wakir-runtime

# A: Standard-Aggregator-Probe (Resolver-Schreibweise).
python3 scripts/phase-3c/backend-decision-aggregator.py \
    --component anchor_emitter \
    --window 30m \
    --target-backend rust \
    --min-rust-share 0.99 \
    --format json
echo "aggregator-exit=$?"

# B: Independent-Oracle — Henrik-Caution-Pflicht.
# Diese Probe NICHT identisch zu Step 4 der Wednesday-Validation —
# hier laeuft sie gegen die Pilot-VM-Engine-Stream und nicht gegen
# den GitHub-Runner-Hermetic-Fixture-Set.
python3 scripts/doppelbetrieb-score-aggregator.py \
    --mode=cross-modul-stress \
    --threshold 3 \
    --target-component anchor_emitter \
    --pilot 192.168.178.116
echo "independent-oracle-exit=$?"
```

Erwartung A: `rust_share >= 0.99` ueber 30-min-Sliding-Window.
Exit 0 = green; Exit 1 = rust_share zwischen 0.95 und 0.99
(yellow); Exit 2 = rust_share <0.95 (red, sofort Rollback).

Erwartung B: 3-of-3 Cross-Modul-Achsen `>= threshold`. Exit 0 =
green; Exit non-zero = red (Henrik-Caution-Veto, sofort Rollback).

**§4.2 — Cross-Lang-Hash-Parity gegen Python-Baseline**

Bridge-Audit-Writer Cross-Lang-Hash-Parity-Pins (`tests/fixtures/
bridge-audit-writer-cross-lang/fixtures.json`, Tag-33 Derivat).
Im Soak-Window: 10 Synthetik-Bridge-Audit-Envelope-Hash-Calls
(doppelt so viele wie Welle-1/2-Pattern, wegen Henrik-Caution-
Cross-Modul-Drift-Sensitivitaet), jede mit Python-Vergleichs-Hash
gegen die Pin-Baseline.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component anchor_emitter \
    --samples 10 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json \
    --canonical-module wirelang.persona_engine.bridge_audit_writer
```

Erwartung: 10/10 Hashes match. Jede Drift => sofort §6 Rollback.

Hintergrund: die Cross-Lang-Parity prueft die deterministische
JCS-Kanonisierung der `EngineeringOutputEvent`-Envelopes (siehe
`wirelang/persona_engine/bridge_audit_writer.py::to_jcs_bytes` und
`bridge_audit_stream_hash.py`). Drift heisst: Python- und Rust-
Side haben unterschiedliche Canonical-Forms — das ist ein blocker-
level Bug fuer die gesamte Audit-Trail-Continuity (nicht nur fuer
Welle-3 selbst, sondern fuer **alle** vorausgegangenen Wellen, da
ihre Audit-Annotations nicht mehr deterministisch verlinkbar
waeren).

**§4.3 — Audit-Stream-Continuity-Gap-Monitor (Welle-3-spezifisch, Henrik-Caution-Item 3)**

Welle-3-exklusiv: der Bridge-Audit-Stream darf im Soak-Window
keine Gaps > 30s aufweisen. Anchor-Output-Index muss strikt
monoton ohne Rewind.

```bash
# Auf Mira-Box, gegen Pilot-VM-Forwarder:
python3 scripts/phase-3c-welle-status-emitter.py \
    --component anchor_emitter \
    --window 30m \
    --pilot 192.168.178.116 \
    --gap-threshold-seconds 30 \
    --monotonicity-check strict \
    --json-out /tmp/welle-3-soak-continuity.json
echo "continuity-exit=$?"
```

Erwartung: `audit_stream_gap_max_seconds < 30` UND
`anchor_index_monotonicity == "strict"` UND `anchor_index_rewinds == 0`.

Jeder Gap > 30s oder Rewind => sofort §6 Rollback **und** Henrik-
Hand-Audit-Hold-Marker setzen (`/var/lib/wakir/audit-holds/welle-
3-continuity-violation-${TS}.marker`).

**§4.4 — Cross-Modul-Drift-Check gegen anchor_emitter + bridge_diff (Welle-3-spezifisch, Henrik-Caution-Item 2)**

Welle-3-exklusiv: Bridge-Audit-Writer steht in Cross-Modul-
Korrelation mit zwei benachbarten Modulen.

- **Upstream:** `anchor_emitter` (Resolver-internal-Schreibweise =
  identisch mit `bridge_audit_writer` an der Cutover-Stelle —
  aber das Modul `wirelang/persona_engine/anchor_emitter.py` ist
  separat und liefert Source-Of-Truth-Anchors die der bridge-
  audit-writer konsumiert).
- **Downstream:** `bridge_diff` (`wirelang/persona_engine/
  bridge_audit_diff_engine.py`). Liest Bridge-Audit-Writer-Output
  fuer Cross-Lang-Diff-Berechnung.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-modul-drift-check.py \
    --target anchor_emitter \
    --upstream-modul anchor_emitter \
    --downstream-modul bridge_diff \
    --window 30m \
    --pilot 192.168.178.116 \
    --tolerance-bps 0 \
    --json-out /tmp/welle-3-cross-modul-drift.json
echo "cross-modul-drift-exit=$?"
```

Erwartung: `drift_bps == 0` fuer beide Korrelations-Achsen.
**Tolerance ist 0 (kein Drift erlaubt)** — Henrik-Caution-Item 2
ist nicht-tolerant. Jeder Drift > 0 => sofort §6 Rollback.

Wenn das Skript `cross-modul-drift-check.py` zum Cutover-Zeitpunkt
noch nicht existiert (Reza-Tag-36-Spawn-Liefer-Status pruefen):
Fallback-Probe ist Triangle-Modul-Hash-Sample (3-Way-Hash zwischen
`bridge_audit_triangle.py`-Output, Python-bridge-audit-writer und
Rust-bridge-audit-writer-CLI). Fallback-Skript:
`scripts/phase-3c/triangle-hash-sample.py` mit `--samples 3
--tolerance 0`.

**§4.5 — Bridge-Audit-Writer Error-Freiheit + Latency**

```bash
# Auf Pilot-VM:
journalctl -u wakir-bridge-audit-writer.service --since "${TS_RESTART}" \
    -p err --no-pager | tee /var/log/wakir/welle-3-bridge-audit-errors.txt
wc -l /var/log/wakir/welle-3-bridge-audit-errors.txt
```

Grafana-Dashboard `Persona-Engine — Backend Latency by Component`.
Filter: `component=anchor_emitter`, `backend=rust`, last 30min.

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

Operator: Screenshot pro 5min-Slice (6 Screenshots gesamt, vs.
3 bei Welle-1/2) + JSON-Export an Henrik-Audit-Trail anhaengen.

Erwartung: 0 Error-Zeilen im 30-min-Soak-Window. Jede Error-Zeile
= automatischer §6 Rollback.

---

## §5 Rollback-Trigger — Exit-Decision-Matrix (Henrik-Caution-Verschaerft)

Sechs harte Trigger (drei Standard, drei Welle-3-spezifisch). Bei
JEDEM einzelnen Trigger: sofort §6, keine Diskussion, keine
Eskalations-Verzoegerung. Mira-Hand entscheidet im Cutover-Window
autark, AR-Override nur post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.5) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | Bridge-Audit-Writer-Service ERR-Zeile | Journal (§4.5) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | Audit-Stream-Continuity-Gap > 30s ODER Anchor-Index-Rewind | Continuity-Monitor (§4.3) | Jeder Gap, jeder Rewind | Rollback (§6) + Henrik-Audit-Hold-Marker |
| T-4 | Cross-Modul-Drift > 0 (anchor_emitter ↔ bridge_audit_writer ↔ bridge_diff) | Cross-Modul-Drift-Check (§4.4) | Drift_bps > 0 auf einer der 2 Korrelations-Achsen | Rollback (§6) + Henrik-Audit-Hold-Marker |
| T-5 | Cross-Lang-Hash-Drift | Parity-Probe (§4.2) | Jede einzelne Drift in 10 Samples | Rollback (§6) + Henrik-Audit-Hold-Marker |
| T-6 | Independent-Oracle Cross-Modul-Stress-Fail | `doppelbetrieb-score-aggregator --mode=cross-modul-stress` (§4.1B) | Eine der 3 Achsen `< threshold` | Rollback (§6) + Henrik-Audit-Hold-Marker |

**T-3 Begruendung (Henrik-Caution-Item 3):** Audit-Stream-
Continuity ist nicht reine Performance — sie ist
Korrelationspflicht. Gap > 30s heisst: Audit-Bloecke vor und nach
dem Gap koennen nicht mehr durch monotone Sequenz verlinkt werden;
das ist eine permanente Audit-Trail-Beschaedigung die durch
Rollback NICHT geheilt wird (Rollback stellt den Service-Pfad
wieder her, aber die fehlenden Records bleiben fehlend).

Self-Reference-Loop-Detection: wenn der Bridge-Audit-Writer im
Soak-Window seine eigenen Migrations-Audit-Records emittiert UND
diese Records die Cross-Modul-Drift-Check selbst speisen wuerden:
das ist ein Self-Reference-Loop. Mitigation ist die unabhaengige
Oracle-Quelle (§4.1B) — `doppelbetrieb-score-aggregator
--mode=cross-modul-stress` nutzt Cross-Modul-Pin-Coverage,
Cross-Modul-Fixture-Stability und Cross-Modul-Rollup-Integrity,
keine dieser drei Achsen nutzt `bridge_audit_writer` als Source.
Wenn das Aggregator-Skript dennoch faelschlich Bridge-Audit-
Output liest (Self-Reference-Bug): das ist ein T-6-Red und Henrik-
Caution-Sign-Off ist ungueltig.

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1A Exit 1).
- Latency p99 > 2.0× Baseline (§4.5 Warn-Schwelle).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  <0.1%).
- Anchor-Index-Sprung > 10 ohne Rewind (§3.6 Stream-Resumption-
  Verify-Warn).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt, Service-
Restart, Verify Backend=python, **Audit-Stream-Continuity-Verify
gegen Pre-Cutover-Baseline** (kritisch — Welle-3-spezifischer
Continuity-Verify-Step). Welle-1+2-State bleibt unberuehrt — nur
das Welle-3-Overlay-File wird entfernt.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-3 Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-3-cutover.log

# 1. Env-Overlay entfernen — NUR Welle-3-Drop-In, Welle-1+2 bleiben
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-3-bridge-audit-writer-rust.conf
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet: welle-1-* + welle-2-* bleiben; welle-3-* weg.
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
    if "BackendDecision" in msg and "anchor_emitter" in msg and "backend=python" in msg:
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified for anchor_emitter")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 4. Audit-Stream-Continuity-Verify gegen Pre-Cutover-Baseline (Welle-3-spezifisch).
# Anchor-Output-Index muss strikt nach Pre-Cutover-Baseline-Index
# weiterzaehlen — ein Rewind oder ein Gap > 60s zwischen Pre-Cutover-
# Baseline-Tail-Index und Post-Rollback-Restart-Index ist eine
# unaufhebbare Audit-Trail-Beschaedigung.
PRE_INDEX=$(cat /var/lib/wakir/welle-3-audit-baseline/pre-cutover-anchor-index-${TS_PRE}.txt \
    | grep -oP 'output_index=\K[0-9]+' | tail -1)
sleep 30  # Anchor-Emitter Boot-Stabilisierung
POST_RB_INDEX=$(journalctl -u wakir-persona-engine.service \
    --since "${TS_RB_RESTART}" --no-pager \
  | grep -oP 'anchor_emitter.*output_index=\K[0-9]+' \
  | head -1)
echo "Pre-Cutover-Index: ${PRE_INDEX}  Post-Rollback-Index: ${POST_RB_INDEX}" \
    | tee -a /var/log/wakir/welle-3-cutover.log

if [ -z "${POST_RB_INDEX}" ] || [ "${POST_RB_INDEX}" -lt "${PRE_INDEX}" ]; then
    echo "ROLLBACK-CONTINUITY-FAIL: Audit-Stream rewind oder gap detected" >&2
    echo "AR-HAND-STOP-MARKER required" >&2
    touch /var/lib/wakir/audit-holds/welle-3-rollback-continuity-violation-${TS_RB}.marker
    exit 3   # exit-3 signalisiert AR-Hand-Stop-Marker, NICHT routine Rollback-Fail
fi

# 5. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-3 Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-3-cutover.log
```

**Eskalations-Schwelle bei Rollback-Continuity-Failure (exit-3):**
Wenn Schritt 4 ROLLBACK-CONTINUITY-FAIL meldet, ist das **kein**
routine-Rollback-Done sondern eine **AR-Hand-Stop-Marker-Bedingung**:

- Der Audit-Stream ist nicht mehr verlinkbar zum Pre-Cutover-Zustand.
- Das Marker-File `/var/lib/wakir/audit-holds/welle-3-rollback-
  continuity-violation-*.marker` wird gesetzt.
- Eskalation Mira -> Priya -> AR sofort.
- Welle-4+5 (KW-26 geplant) ist blockiert bis Audit-Trail-
  Recovery-Decision vorliegt.

Nach erfolgreichem Rollback (kein exit-3): 60-min Stabilitaets-
Beobachtung (doppelt so lang wie Welle-1/2-30min-Stabilitaet)
mit BackendDecision-Aggregator (§4.1A, --target-backend python),
Audit-Stream-Continuity-Monitor (§4.3), und Cross-Modul-Drift-
Check (§4.4). Dann §7 Sign-Off mit verdict=`rollback`, Root-Cause-
Analyse binnen 48h pflichtig:

- **Reza** — bridge-audit-writer Rust-CLI-Substrate-Owner,
  Canonical-Form-Drift-Investigation.
- **Tomás** — Cross-Modul-Korrelation, anchor_emitter/bridge_diff-
  Interaktion.
- **Henrik** — Audit-Trail-Integrity, Self-Reference-Detection-
  Verify, F-Item-Reactivation-Bewertung.

---

## §7 Sign-Off — Henrik-Audit-Trail (Verschaerftes Welle-3-Template)

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off ist
Pflicht **vor Welle-4+5-Trigger** (KW-26 geplant). Welle-3-Sign-Off-
Template traegt **3 verschaerfte Achsen** vs. Welle-1/2-Template:
Cross-Modul-Drift, Audit-Continuity, Self-Reference-Detection.

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-3-smoke-*.json` (§2 Skript-Output)
- Welle-3-Wednesday-Validation-`cutover-acceptance-decision-welle-
  3.json` (§1, GitHub-Actions-Artifact-URL, mit
  `henrik_caution_applied == true`)
- `cross-modul-stress-rollup.json` (§1 Pre-Gate ★)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-3-pre-
  cutover-*.json` (post-Welle-1+2, frisch)
- BackendDecision-Aggregator-Snapshot (§1, Python-Default
  `anchor_emitter` ≥99%)
- Bridge-Audit-Stream-Continuity-24h-Snapshot (§1, gap-max <5s)
- **Pre-Cutover-Audit-Stream-Baseline-Snapshot** (§3.2.5,
  `/var/lib/wakir/welle-3-audit-baseline/pre-cutover-*.jsonl` +
  Sha256-Hash + Anchor-Output-Index)
- Welle-1+Welle-2 Sign-Off-Status (§1, Pflicht-Vorbedingung)

**TEL-Evidenz (waehrend §4 30-min Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1A, 30-min Window JSON)
- Independent-Oracle Cross-Modul-Stress-Run (§4.1B, 3-Axen-Rollup
  Pilot-Mode)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 10/10 oder Abweichung)
- Audit-Stream-Continuity-Monitor-Output (§4.3,
  `/tmp/welle-3-soak-continuity.json`)
- Cross-Modul-Drift-Check-Output (§4.4,
  `/tmp/welle-3-cross-modul-drift.json`, drift_bps=0 Pflicht)
- Grafana-Latency-Histogramm-Screenshots (§4.5, 6 Screenshots)
- Bridge-Audit-Writer-Error-Count (§4.5, 0-Zeilen-File)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-3-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- Bei Rollback: Continuity-Verify-Output gegen Pre-Cutover-
  Baseline (§6 Schritt 4)
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`,
  oder **`ar-hand-stop`** bei exit-3 Continuity-Violation)
- AR-Approval-Tag fuer Welle-4+5-Trigger (nur bei `green` ODER
  `green-with-yellow-notes` mit Henrik-Hand-Hand-Approval)

**Verschaerftes Sign-Off-Template (Welle-3-spezifisch):**

```yaml
welle: 3
component: bridge_audit_writer
component_alias: anchor_emitter
cutover_date: 2026-06-15
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
audit_caution_applied: true
verdict: green | green-with-yellow-notes | rollback | ar-hand-stop
yellow_notes: []
red_triggers_hit: []
# Welle-3-spezifische Verschaerfte Achsen:
cross_modul_drift_bps: 0   # MUSS 0 sein fuer green
audit_continuity_gap_max_seconds: <number>  # MUSS < 30 fuer green
self_reference_detection_clean: true | false  # MUSS true fuer green
# Cross-Welle-Coupling:
welle_1_signoff_status: green | green-with-yellow-notes | rollback
welle_2_signoff_status: green | green-with-yellow-notes | rollback
# Evidenz-Pfade:
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
pre_cutover_audit_baseline_sha256: <hash>
ar_approval_tag_for_welle_4_5: null  # gesetzt durch AR post-Sign-Off
henrik_hand_approval_required: true | false  # true bei yellow oder rollback
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-3-bridge-audit-writer-signoff-2026-06-15.yaml`

---

## §8 Mira-SSH-Hand-Authority + AR-Hand-Stop-Marker (Welle-3-spezifisch)

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-Hand-
Authority fuer Pilot-VM-Operations. **Welle-3-spezifische
Erweiterung:** AR-Hand-Stop-Marker bei kritischen Rollback-
Failures.

**Mira-Hand-Operations (autark, identisch zu Welle-1/2):**
systemctl restart, Env-Overlay-File-Edits, Journal-Reads, Quadlet-
Override-Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
Cron-Re-Schedule innerhalb Cutover-Window, Audit-Stream-Snapshot-
Creation (read-only).

**AR-Hand-Operations (irreversibel-despawn, identisch zu Welle-1/2):**
`podman rm` ohne Backup, Volume-Wipe (`podman volume rm`), System-
Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade, Disk-
Repartitionierung.

**Welle-3-Neu — AR-Hand-Stop-Marker-Bedingungen:**

Vier Bedingungen triggern automatisch ein Marker-File und
sofortige AR-Eskalation (Mira -> Priya -> AR):

1. **Rollback-Continuity-Violation** (§6 exit-3) — Audit-Stream
   nach Rollback nicht verlinkbar zum Pre-Cutover-State.
2. **Self-Reference-Loop-Detection** — Independent-Oracle (§4.1B)
   meldet `bridge_audit_writer` als Source einer ihrer eigenen
   3 Achsen (Aggregator-Bug, Henrik-Caution-Sign-Off ungueltig).
3. **T-3 Audit-Stream-Continuity-Gap > 30s** — siehe §5.
4. **T-4 Cross-Modul-Drift > 0** — siehe §5.

Marker-File-Pfad-Pattern:
`/var/lib/wakir/audit-holds/welle-3-<bedingung>-<TS>.marker`

Bei AR-Hand-Stop-Marker: Welle-4+5 (KW-26) sind blockiert bis
AR-Decision-Output vorliegt. Henrik-Hand-Forensik-Pflicht binnen
72h.

**Cutover-Step §3 + Rollback §6 = Mira-Hand-Operations**
(routinemaessig). **AR-Hand-Stop-Marker** ist die Ausnahme-
Eskalations-Schwelle. AR-Sichtung im routine-Pfad ist post-hoc
Sign-Off-Pflicht (§7).

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-Kombination):
   Mira-Hand-Decision autark. Henrik-Audit protokolliert.
2. **Substanz-Konflikt** (z.B. Cross-Modul-Drift > 0 ODER Cross-
   Lang-Hash-Drift): Mira-Hand Rollback nach §6, dann Eskalation
   Mira -> Priya -> Henrik (Audit-Trail-Hold), Reza wird hinzu-
   gezogen (bridge-audit-writer-Rust-Substrate-Owner).
3. **Audit-Trail-Continuity-Violation** (T-3 oder T-4 ODER
   Rollback exit-3): AR-Hand-Stop-Marker setzen, sofortige
   Mira -> AR-Eskalation, kein Welle-4+5-Trigger.
4. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-Drop):
   Mira-Hand Rollback, dann Eskalation Mira -> AR fuer Recovery.

---

## §9 Bekannte Risiken

**R-1 — Welle-3-Solo-Sequencing (kein Parallel-Welle)**
Im Gegensatz zu Welle-1+2 (KW-24 parallel) und geplantem
Welle-4+5 (KW-26 parallel) ist Welle-3 die **einzige solo-
Welle** in der ADR-0066-Sequenz. Begruendung: Bridge-Audit-Writer
ist das Audit-Oracle selbst, eine parallele Backend-Migration
einer benachbarten Komponente waehrend des Bridge-Audit-Cutovers
wuerde die Independent-Oracle-Cross-Modul-Stress-Achsen verrauschen
(zwei gleichzeitige Drift-Quellen, nicht eindeutig zuordenbar).
Mitigation: KW-25 ist der gesamte Wochenslot fuer Welle-3
reserviert; KW-24-Sign-Off-Verzoegerung Welle-1 oder Welle-2
verschiebt Welle-3 als Ganzes, kein "wir starten Welle-3 schon
mal" Workaround.

**R-2 — Read-Only-Sink-Charakter mit Cross-Modul-Footprint**
Bridge-Audit-Writer ist ein **Sink-Pfad** (Engineering-Output-
Event-Emission), kein Mutations-Pfad fuer Engine-State. Rollback-
Cost technisch gering (env unset + restart). **Aber:** der Sink
schreibt in den Audit-Stream, und nach Rollback fehlt ein
zeitlicher Block zwischen Pre-Cutover und Post-Rollback-Recovery.
Mitigation: §3.2.5 Pre-Cutover-Audit-Baseline-Snapshot + §6
Schritt 4 Continuity-Verify gegen Baseline-Index. Wenn Continuity
nicht herstellbar: exit-3 AR-Hand-Stop-Marker.

**R-3 — Pre-Phase-3a-Gap: Bridge-Audit-Pin-Coverage relativ jung**
Die Bridge-Audit-Writer Cross-Lang-Hash-Parity-Pins (`tests/
fixtures/bridge-audit-writer-cross-lang/fixtures.json`, Tag-33
Derivat via `scripts/derive-bridge-audit-writer-fixtures.py`) sind
zum Cutover-Datum ~7 Tage frisch (Tag-33 -> Tag-36-Decision-Point
-> KW-25-Montag). Pin-Sample-Diversitaet ist mit ≥ 5 Samples
kalibriert, aber 30-Tage-Soak-Wert noch nicht erreicht. Mitigation:
§4.2 Cross-Lang-Hash-Parity-Probe nutzt **10 Samples** statt 5
(doppelter Diversitaets-Floor); §4.4 Cross-Modul-Drift-Check ist
Defense-in-Depth.

**R-4 — Cosign-Image-Pin-Drift (PR #210 9-Binary)**
Pilot-VM zieht `ghcr.io/wakir-labs/wakir-persona-engine:<tag>`
ueber Quadlet-Pull-Pattern. Bridge-Audit-Writer-Image landete in
PR #210 (`0168ac3` Tag-31) als Item 9 der Build-Inventory. Bei
Tag-Mutation zwischen Wednesday-Validation und Monday-Cutover:
Cosign-Verify in §1 Gate-1 wuerde nicht zwingend bemerken.
Mitigation: Pre-Cutover-Step zusaetzlich
`podman image inspect ghcr.io/wakir-labs/wakir-persona-engine |
grep Digest` gegen Wednesday-Validation-Digest-Pin (analog
Welle-1+2 §9 R-4).

**R-5 — Konsistenz-Oracle-Cutover-Subjekt-Self-Reference (Henrik-Caution-Item 1)**
Bridge-Audit-Writer ist das Substrat hinter dem Cross-Lang-
Konsistenz-Oracle (`tests/integration/test_bridge_audit_
roundtrip_e2e.py`). Wenn der Cutover dieses Oracle zur Cutover-
Acceptance nutzt: Subject-zertifiziert-sich-selbst-Trap.
Mitigation (ADR-0066 §Henrik-Sign-off): Welle-3-Validation-
Workflow Step 4 nutzt Independent-Oracle (`doppelbetrieb-score-
aggregator --mode=cross-modul-stress`), dessen 3 Achsen
**strukturell unabhaengig** von Bridge-Audit-Writer sind:

- `cross-lang-pin-coverage` (federation_frame, state_backing,
  lifecycle_state_machine, subscribe_loop, recovery_workflow)
- `cross-modul-fixture-stability`
- `cross-modul-rollup-integrity`

§4.1B repliziert diese Probe gegen die Pilot-VM-Engine-Stream
(nicht gegen GitHub-Runner-Hermetic-Fixtures), damit der Live-
Cutover-Pfad ein **Live-Independent-Oracle** hat. Wenn die
Aggregator-Implementation faelschlich `bridge_audit_writer` als
Source nimmt: T-6-Red, Henrik-Caution-Sign-Off ungueltig.

**R-6 — Cross-Modul-Drift (Henrik-Caution-Item 2, Tag-27)**
Bridge-Audit-Writer steht in Cross-Modul-Korrelation mit
`anchor_emitter`-Upstream und `bridge_diff`-Downstream. Drift
zwischen Python-Default-Korrelation und Rust-Backend-Korrelation
ist ein blocker-level Audit-Bug. Mitigation: §4.4 Cross-Modul-
Drift-Check mit Tolerance=0; bei Drift > 0 sofort Rollback +
Henrik-Audit-Hold. Fallback wenn `cross-modul-drift-check.py`
nicht verfuegbar: Triangle-Modul-Hash-Sample (3-Way-Hash gegen
`bridge_audit_triangle.py`).

**R-7 — Audit-Stream-Continuity-Gap (Henrik-Caution-Item 3, Tag-27)**
Restart-Fenster muss < 30s sein, sonst entstehen unverlinkbare
Audit-Bloecke. Mitigation: §3.2.5 Pre-Cutover-Snapshot, §4.3
Soak-Window-Monitor, §6 Rollback-Continuity-Verify gegen Baseline-
Index. Bei Gap > 30s ODER Anchor-Index-Rewind: T-3-Red + AR-Hand-
Stop-Marker (nicht nur Rollback — Audit-Trail ist persistent
beschaedigt).

**R-8 — Welle-2-Rollback-Coupling**
Falls Welle-2 `rollback` (§1 zulaessiger Zustand (c)): Welle-3-
Cutover wird VERSCHOBEN. Begruendung: SVID-Workload-Identity-
Rollback signalisiert Substrate-Anomalie, die Bridge-Audit-Writer-
Cutover-Risk-Calc invalidiert (Bridge-Audit-Writer schreibt
SPIFFE-ID-Bindings in den Audit-Stream, ein SVID-Rollback bedeutet
die SPIFFE-ID-Resolution ist nicht stabil — Cross-Modul-Drift wuerde
falsch-positiv triggern). AR-Eskalation Pflicht; Welle-3-Re-
Scheduling ist AR-Decision.

Analog: Falls **beide** Welle-1+2 `rollback` UND nicht remedi'iert:
Welle-3 ist BLOCKIERT, Phase-3c-Sequenz steht. AR-Decision noetig
ueber Welle-Re-Sequencing oder ADR-0066-Revision.

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, **Montag KW-25 (2026-06-15)**,
09:00-12:00 CEST Cutover-Window (3h, vs. Welle-1/2 4h-Window —
Welle-3 hat schlankeres Window da solo, aber laengeres 30-min
Soak und 60-min Stabilitaets-Beobachtung).

**Konkretes Cutover-Window — Welle-3 solo:**

| Sub-Phase | Slot CEST |
|---|---|
| Pre-Conditions Walk-Through + Henrik-Caution-Pre-Gate (★) | 09:00-09:25 |
| Pre-Flight-Smoke (§2) + Decision | 09:25-09:35 |
| Pre-Cutover-Audit-Baseline-Snapshot (§3.2.5) | 09:35-09:45 |
| Cutover-Step (§3.1-§3.6) | 09:45-10:00 |
| Soak-Window (§4, 30-min) | 10:00-10:30 |
| Sign-Off-Initial-Draft (§7) | 10:30-11:00 |
| Reserve — Rollback + Continuity-Verify | 11:00-12:00 |
| **Pause + Audit-Trail-Submission an Henkrik** | 12:00-13:30 |
| Henrik-Audit-Sign-Off-Window | 13:30-15:00 |

**Datum: Montag 2026-06-15 (KW-25)**

- **Welle-3-Cutover-Start:** 09:00 CEST
- **Welle-3-Latest-Commit-To-Rust:** 10:00 CEST (Boot-Audit-Pass)
- **Welle-3-Soak-Window-Ende:** 10:30 CEST
- **Welle-3-Sign-Off-Window-Ende:** 15:00 CEST
- **Hairpin-Rollback-Slot:** Mittwoch 2026-06-17, 09:00-12:00 CEST

**Begruendung Werktag-Vormittag + Solo-Sequencing + verlaengerte Windows:**

1. **Solo-Welle:** Keine Pufferzeit fuer parallele Welle noetig,
   aber Henrik-Caution-Cross-Modul-Probe braucht 30min-Soak +
   Pre-Cutover-Baseline-Snapshot-Step (§3.2.5, ~10min Operator-
   Hand).
2. **Henrik-Caution-Sign-Off-Window 13:30-15:00:** Henrik hat 3h
   nach Sign-Off-Initial-Draft fuer Independent-Oracle-Output-
   Review, Cross-Modul-Drift-Output-Pruefung, Audit-Stream-
   Continuity-Output-Pruefung. Welle-1+2 hatten dieses
   verschaerfte Henrik-Window nicht.
3. **Hairpin-Rollback-Slot Mi (KW-25):** Falls Welle-3-Sign-Off
   yellow-with-Henrik-Hand-Approval-Bedarf ODER post-hoc-
   Continuity-Issue auftaucht — Mittwoch-Vormittag ist der naechste
   sinnvolle Slot (Engineering-Verfuegbarkeit, kein Wochenende-
   Risiko, AR-Sichtung-moeglich).
4. **Welle-4+5 KW-26-Trigger:** Welle-4+5 sind in KW-26 geplant
   (parallel, analog Welle-1+2-Pattern). Welle-3-Sign-Off-Green
   ist Pflicht-Vorbedingung. Wenn Welle-3-Sign-Off bis Mittwoch
   nicht green: Welle-4+5 verschieben auf KW-27.
5. **Engineering-Verfuegbarkeit:** Reza, Selin, Tomás, Henrik im
   Cutover-Window aktiv. Sofort-Eskalation moeglich.

**Verbotene Cutover-Slots:**

- Freitag-Nachmittag (Wochenend-Rollback-Risiko).
- Mittwoch-Mittag (kollidiert mit Wednesday-Validation-Run-Re-Run-
  Option).
- Sonntag/Feiertag (kein Engineering-Standby).
- Parallel zu Welle-1+2-Cutover-Step (KW-24, siehe §9 R-1 +
  ADR-0066 §Bridge-Audit-Welle-solo).
- KW-25-Mittwoch-Cutover-Slot (Mittwoch ist Hairpin-Rollback-Slot,
  nicht Cutover-Slot — schon spezieller fuer Welle-3 reserviert).

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Reza (bridge-audit-writer-Rust-Substrate-Owner) | bei JCS-Canonical-Drift, EngineeringOutputEvent-Schema-Issue, output_index-Anomalien |
| 3 | Tomás (Matrix-Lead) | bei Welle-1/2/3-Interaktion, Cross-Modul-Korrelation |
| 4 | **Henrik (Internal Audit)** — Henrik-Caution-Sign-Off-Owner | bei Audit-Trail-Continuity-Gap, T-3/T-4/T-6 Trigger, Self-Reference-Detection-Suspicion, F-Item-Reactivation |
| 5 | AR (Fred) | bei AR-Hand-Stop-Marker, Rollback-Continuity-Violation (§6 exit-3), Welle-1+2-Rollback-Coupling-Block, Phase-3c-Sequenz-Re-Sequencing |

---

## Anhang B — Cross-Welle-Coordination-Checkliste

Vor Welle-3-Cutover-Start: explizite Verifikation der Welle-1+2-
Coordination-Items.

- [ ] Welle-1-Runbook gelesen ([`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md), PR #228 Tag-34)
- [ ] Welle-2-Runbook gelesen ([`welle-2-svid-workload-identity-runbook.md`](./welle-2-svid-workload-identity-runbook.md), PR #232 Tag-35)
- [ ] Welle-1-Sign-Off-Verdict bekannt (`green`, `green-with-
      yellow-notes`, oder `rollback`)
- [ ] Welle-2-Sign-Off-Verdict bekannt (`green`, `green-with-
      yellow-notes`, oder `rollback`)
- [ ] Bei Welle-2-`rollback`: Welle-3 verschoben (AR-Eskalation)
- [ ] Bei Welle-1+Welle-2 beide `rollback` UND nicht remedi'iert:
      Welle-3 BLOCKIERT (Phase-3c-Sequenz-AR-Decision)
- [ ] Welle-1-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/
      welle-1-v907-verify-rust.conf`
- [ ] Welle-2-Drop-In-File auf Pilot-VM vorhanden:
      `ls /etc/systemd/system/wakir-persona-engine.service.d/
      welle-2-svid-workload-identity-rust.conf`
- [ ] Welle-1-`v907_verify` `backend=rust` im Aggregator >99%
      (Welle-3-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-2-`svid_workload_identity` `backend=rust` im
      Aggregator >99% (Welle-3-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-3-Engine-Health-Baseline frisch aufgezeichnet
      POST-Welle-1+2 (nicht uebertragen aus Welle-1- oder Welle-2-
      Pre-Baselines)
- [ ] Welle-3-spezifischer Pre-Cutover-Audit-Stream-Baseline-
      Snapshot vorhanden (§3.2.5, Sha256-Hash protokolliert)
- [ ] Henrik-Caution-Pre-Gate ★ gruen (§1)
- [ ] Independent-Oracle Wednesday-Snapshot 3-of-3 Achsen pass

---

## Anhang C — Welle-3-spezifische Cross-Spawn-Coordination (Tag-36)

Tag-36 hat parallele Spawns laufen lassen (Continuous-Mode):

| Spawn | Owner | Artefakt | Pfad |
|---|---|---|---|
| Welle-3-Operator-Runbook (dieses Dokument) | Kai | `docs/phase-3c/welle-3-bridge-audit-writer-runbook.md` | dieses File |
| Welle-3-Cutover-Smoke-Skript | Selin | `scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh` | Pfad in §2 zitiert |
| Cross-Modul-Drift-Check-Skript | Reza | `scripts/phase-3c/cross-modul-drift-check.py` | Pfad in §4.4 zitiert (Fallback: Triangle-Hash-Sample) |
| Welle-3-E2E-CI-Fix | Tomás | CI-Workflow-Adjustment | siehe Tomás-Tag-36-Liefer-Bericht |

Pre-Cutover-Cross-Spawn-Verifikation (in §1 implizit, hier
explizit gelistet): alle 4 Tag-36-Artefakte muessen auf main
gemerged sein vor Welle-3-Wednesday-Validation-Run-Trigger
(KW-24-Mittwoch).

---

— Kai Hoffmann (DevOps), Sprint-Tag-36, 2026-05-18.
