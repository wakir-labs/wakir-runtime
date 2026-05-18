---
title: "Phase-3c Welle-1 v907_verify Operator-Cutover-Runbook"
owner: "Kai Hoffmann (DevOps), Tomás Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065"
welle: 1
component: "v907_verify"
env_var: "WAKIR_V907_VERIFY_BACKEND"
cutover_date: "2026-05-25"
cutover_window_cest: "10:00-14:00"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 34
---

# Phase-3c Welle-1 v907_verify Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-1-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die `v907_verify`-
Komponente der Persona-Engine). Ziel-Cutover-Datum: Montag
2026-05-25, KW-22 (vorbehaltlich Welle-1-Validation-Wednesday-Run
2026-05-20 Green-Verdict).

Dies ist das **operative Day-Of-Skript**. Hermetic-Validierung
(`phase-3c-welle-1-validation.yml`) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-1-runbook.md`](../operations/phase-3c-welle-1-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM,
echter NATS-Bus, echte Quadlet-Restart-Sequenz, echte Audit-
Stream-Beobachtung.

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-1-validation.yml` |
| Dry-Run-Runbook | `docs/operations/phase-3c-cutover-runbook.md` |
| Sibling-Welle-1-Validation-Runbook | `docs/operations/phase-3c-welle-1-runbook.md` |
| Quadlet-Inventar | `quadlet/wakir-rust-cli.container` |
| Cosign-Policy | `policies/cosign-policy-phase-3b.yaml` |
| Selin-Cutover-Smoke-Skript | `scripts/phase-3c/welle-1-v907-verify-cutover-smoke.sh` (Tag-34, PR pending) |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Bridge-Audit-Roundtrip-E2E | `tests/integration/test_bridge_audit_roundtrip_e2e.py` |
| Cross-Lang-Hash-Parity-Pins | PR #224, #170 |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya.

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar 7 Binaries)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `v907-verify` unter den 7 signierten Persona-Engine-Binaries.
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 7 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` Tag-24 Update
      enthaelt `wakir-persona-engine-v907-verify` im Binary-Block.
      PR #187 merged in main.
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence: `wirelang/persona_engine/rust_backend_switch.py`
      bzw. equivalent unterstuetzt `v907_verify` und liest
      `WAKIR_V907_VERIFY_BACKEND` als Pflicht-Env.
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet, GitHub-Runner-Baseline-File nicht).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — gruen. Evidence:
      `tests/integration/test_bridge_audit_roundtrip_e2e.py`
      passt (oder all-SKIP auf Runner ohne replay_cli-Binary).
- [ ] **Wednesday-Validation-Run gruen** (2026-05-20 06:00 UTC).
      Evidence: `cutover-acceptance-decision.json`
      `ready_for_live_smoke == true`. Artifact-Retention 30 Tage.
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, Python-Default-Posture). Latency-p50/p95, Error-Rate,
      BackendDecision-Volume pro Minute. Persistiert in
      `/var/lib/wakir/baselines/welle-1-pre-cutover-<TS>.json` auf
      Pilot-VM.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component v907_verify --window 5m --format json` liefert
      gueltige Records mit `backend=python` >99% (Baseline).
- [ ] **Quadlet 7-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 7 Binaries inklusive
      `wakir-persona-engine-v907-verify`.
- [ ] **Cosign-Policy 7-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit.
- [ ] **Henrik-Audit-Trail-Substrate ready** (Tag-27).
      Evidence: Bridge-Audit-Writer emittiert seit >24h ohne
      Errors auf Pilot-VM.
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt**
      (4h-Slot, naechster Werktag-Vormittag).

---

## §2 Pre-Flight-Smoke

Selin's Welle-1-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet
zur Pilot-VM testet und ist kein Pilot-internes Artefakt.

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-1-v907-verify-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component v907_verify \
    --env-var WAKIR_V907_VERIFY_BACKEND \
    --dry-run-window 5m \
    --json-out /tmp/welle-1-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated). Mira-Hand-Decision noetig vor §3.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Tomás (Matrix-Lead).

Das JSON-Envelope (`/tmp/welle-1-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~2-4 min wall-clock. Skript prueft
SSH-Reachability, Quadlet-Status-Snapshot, Cosign-Policy-Match,
Engine-Health-Baseline-Delta gegen Tag-N-1, BackendDecision-
Aggregator-Sanity. Keine Side-Effects auf Pilot-VM (read-only).

---

## §3 Cutover-Step

**Mira-Hand-SSH-Authority** gemaess ADR-0058 §Nachtrag. AR-
Eskalations-Override nur fuer `irreversible despawn`-Pfade —
Quadlet-Restart und Env-Overlay fallen darunter **nicht**, das
ist routine Operator-Hand-Operation.

**Schritt 3.1 — SSH auf Pilot-VM**

```bash
ssh root@192.168.178.116
# Erwarteter Banner: "wakir-pilot — FCOS — Phase-3b live"
```

**Schritt 3.2 — Pre-Restart-Snapshot**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-1-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-1-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-1-cutover-pre-journal.txt
```

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht
in-place edit der Container-Unit. Reversibel, ADR-0058-konform.

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-1-v907-verify-rust.conf <<'EOF'
# Phase-3c Welle-1 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-1, Welle 2026-05-25
[Service]
Environment="WAKIR_V907_VERIFY_BACKEND=rust"
EOF
systemctl daemon-reload
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-1-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust` und `component=v907_verify` werden innerhalb
30s im Bridge-Audit-Stream emittiert.

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
    if "BackendDecision" in msg and "v907_verify" in msg and "backend=rust" in msg:
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision rust-records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

Wenn Boot-Audit-Wait-Loop Exit ≠ 0: sofort §6 Rollback-Procedure.

---

## §4 Post-Cutover-Verification (15-min Soak-Window)

Soak-Window ist die operative Acceptance-Phase. Vier parallele
Beobachtungs-Streams, jede mit harter Schwelle und
Rollback-Trigger.

**§4.1 — BackendDecision-Aggregator Sliding-Window**

```bash
# Auf Mira-Box, gegen Pilot-NATS (von Pilot-VM Forwarder):
cd /var/home/fred/AI-Corp/wakir-runtime
python3 scripts/phase-3c/backend-decision-aggregator.py \
    --component v907_verify \
    --window 15m \
    --target-backend rust \
    --min-rust-share 0.99 \
    --format json
echo "exit=$?"
```

Erwartung: `rust_share >= 0.99` ueber 15-min-Sliding-Window.
Exit 0 = green; Exit 1 = rust_share zwischen 0.95 und 0.99
(yellow, manual review noetig); Exit 2 = rust_share <0.95
(red, sofort Rollback).

**§4.2 — Cross-Lang-Hash-Parity gegen Python-Baseline**

PRs #224 + #170 stellen die SVID-Workload-Identity-Pins und
Cross-Lang-Hash-Parity-Anchors bereit. Im Soak-Window: 5
Synthetik-v907-Verify-Calls, jede mit Python-Vergleichs-Hash.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component v907_verify \
    --samples 5 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/integration/cross_lang_hash_parity_pins.json
```

Erwartung: 5/5 Hashes match. Jede Drift => sofort §6 Rollback.

**§4.3 — Latency-Histogramm aus Grafana (PR #179)**

Grafana-Dashboard `Persona-Engine — Backend Latency by
Component`. Filter: `component=v907_verify`, `backend=rust`,
last 15min.

Erwartete Schwellen (gegen Engine-Health-Baseline aus §1):

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

Operator: Screenshot pro 5min-Slice (3 Screenshots gesamt) +
JSON-Export an Henrik-Audit-Trail anhaengen.

**§4.4 — Bridge-Audit-Writer Error-Freiheit**

```bash
# Auf Pilot-VM:
journalctl -u wakir-bridge-audit-writer.service --since "${TS_RESTART}" \
    -p err --no-pager | tee /var/log/wakir/welle-1-bridge-audit-errors.txt
wc -l /var/log/wakir/welle-1-bridge-audit-errors.txt
```

Erwartung: 0 Error-Zeilen im 15-min-Soak-Window. Jede Error-
Zeile = automatischer §6 Rollback.

---

## §5 Rollback-Trigger — Exit-Decision-Matrix

Drei harte Trigger. Bei JEDEM einzigen Trigger: sofort §6,
keine Diskussion, keine Eskalations-Verzoegerung. Mira-Hand
entscheidet im Cutover-Window autark, AR-Override nur
post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.3) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | Audit-Record-Parse-Error | Bridge-Audit-Writer journal (§4.4) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | Cross-Lang-Hash-Drift | Parity-Probe (§4.2) | Jede einzelne Drift in 5 Samples | Rollback (§6) |

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1 Exit 1).
- Latency p99 > 2.0× Baseline (§4.3 Warn-Schwelle).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  ist <0.1%).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt,
Service-Restart, Verify Backend=python. Ziel: <90s
Time-to-Recovery.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-1-cutover.log

# 1. Env-Overlay entfernen
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-1-v907-verify-rust.conf
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
    if "BackendDecision" in msg and "v907_verify" in msg and "backend=python" in msg:
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 4. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-1-cutover.log
```

Nach Rollback: 30-min Stabilitaets-Beobachtung mit
BackendDecision-Aggregator (§4.1, --target-backend python).
Dann §7 Sign-Off mit verdict=`rollback`, Root-Cause-Analyse
binnen 48h pflichtig (Reza Backend-Switch-Resolver, Tomás
Cross-Module-Korrelation, Henrik Audit-Sicht).

---

## §7 Sign-Off — Henrik-Audit-Trail

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off
ist Pflicht vor Welle-2-Trigger.

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-1-smoke-*.json` (§2 Skript-Output)
- Wednesday-Validation-`cutover-acceptance-decision.json`
  (§1, GitHub-Actions-Artifact-URL)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-1-
  pre-cutover-*.json`
- BackendDecision-Aggregator-Snapshot (§1, Python-Default
  ≥99%)

**TEL-Evidenz (waehrend §4 Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1, 15-min Window
  JSON)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 5/5 oder Abweichung)
- Grafana-Latency-Histogramm-Screenshots (§4.3, 3 Screenshots)
- Bridge-Audit-Writer-Error-Count (§4.4, 0-Zeilen-File)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-1-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`)
- AR-Approval-Tag fuer Welle-2-Trigger (nur bei `green`)

**Sign-Off-Template:**

```yaml
welle: 1
component: v907_verify
cutover_date: 2026-05-25
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
verdict: green | green-with-yellow-notes | rollback
yellow_notes: []
red_triggers_hit: []
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
ar_approval_tag_for_welle_2: null  # gesetzt durch AR post-Sign-Off
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-1-v907-verify-signoff-2026-05-25.yaml`

---

## §8 Mira-SSH-Hand-Authority

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-
Hand-Authority fuer Pilot-VM-Operations:

- **Mira-Hand-Operations (autark):** systemctl restart,
  Env-Overlay-File-Edits, Journal-Reads, Quadlet-Override-
  Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
  Cron-Re-Schedule innerhalb Cutover-Window.
- **AR-Hand-Operations (irreversibel-despawn):** `podman rm`
  ohne Backup, Volume-Wipe (`podman volume rm`), System-
  Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade,
  Disk-Repartitionierung.
- **Cutover-Step §3 + Rollback §6 = Mira-Hand-Operations.**
  Keine AR-Eskalation noetig. AR-Sichtung ist post-hoc
  Sign-Off-Pflicht (§7).

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-
   Kombination): Mira-Hand-Decision autark. Henrik-Audit
   protokolliert die Entscheidung.
2. **Substanz-Konflikt** (z.B. Cross-Lang-Hash-Drift bei
   wiederholtem Cutover): Eskalation Mira -> Priya -> AR.
3. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-
   Drop): Mira-Hand Rollback nach §6, dann Eskalation
   Mira -> AR fuer Recovery-Decision.

---

## §9 Bekannte Risiken

**R-1 — Henrik-Caution Welle-3 (Day-0-Pipeline-Orchestrator)**
PR #222 ist eingebaut, aber Henrik-Caution-Item bleibt fuer
Welle-3. Welle-1 Cutover beruehrt es **nicht direkt**, aber:
Welle-1-Rollback aktiviert die Day-0-Pipeline indirekt
(BackendDecision-Aggregator-Re-Snapshot). Operator-Hand-
Awareness: bei Rollback Welle-3-Substrate beobachten.

**R-2 — Henrik-Caution Welle-5** (Caution-Item Tag-31).
Welle-1 trifft Welle-5-Pfad nicht; aber Welle-1-rollback-
Frequenz waere ein Vorindikator fuer Welle-5-Risiko-Anstieg.

**R-3 — Tag-24-Drift-Finding SVID-Resolver-Gap**
ADR-0066-Streichen-Erratum fuer Welle-2 (`svid_workload_
identity`) ist pending AR-Approval. Bedeutet: Welle-1
Cutover-Erfolg darf NICHT automatisch Welle-2-Cutover
auf den Mittwoch-Validation-Wednesday triggern. AR-Hand
muss Welle-2-Erratum explizit clearen oder Welle-2 streichen
bevor Welle-2-Validation-Wednesday-Workflow startet.

**R-4 — BackendDecision-Aggregator Sliding-Window
Schema-Drift** PR #179 ist tag-recent (KW-21), Schema-
Field-Stability noch nicht 30-Tage-soak. Mitigation:
Cross-Lang-Hash-Parity-Probe (§4.2) ist unabhaengig vom
Aggregator-Schema. Bei Aggregator-Parse-Fehlern im
Cutover-Window: Parity-Probe ist der Veto-Pfad.

**R-5 — Pilot-VM-Stress-Window** Werktag-Vormittag ist
optimal (siehe §10), aber Mittwoch-Validation-Wednesday-
Run und Welle-1-Cutover am Montag fallen in
unterschiedliche Wochen. Welle-1-Cutover-Datum (Montag
2026-05-25) ist 5 Tage NACH dem Wednesday-Validation-Run
(2026-05-20) — Gate-Evidence-Frische ist OK, aber kein
Drift-Auto-Reroll-Mechanismus. Bei Auffaelligkeit zwischen
Mi und Mo: manuelles Re-Run der Validation-Workflow am
Cutover-Tag morgens.

**R-6 — Cosign-Policy-Image-Digest-Drift** Pilot-VM zieht
`ghcr.io/wakir-labs/wakir-persona-engine:<tag>` ueber
Quadlet-Pull-Pattern. Bei Tag-Mutation (z.B. neuer Image-
Build seit Wednesday-Validation): Cosign-Verify in §1
Gate-2 wuerde nicht zwingend bemerken. Mitigation:
Pre-Cutover-Step zusaetzlich `podman image inspect
ghcr.io/wakir-labs/wakir-persona-engine | grep Digest`
gegen Wednesday-Validation-Digest-Pin.

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, 10:00-14:00 CEST, niedriger
Stress-Slot.

| Sub-Phase | Dauer | Kumulativ |
|---|---|---|
| §1 Pre-Conditions Walk-Through | 20 min | 0:20 |
| §2 Pre-Flight-Smoke | 5 min | 0:25 |
| Mira-Hand-Decision-Point (Final-Go) | 5 min | 0:30 |
| §3 Cutover-Step (incl. Boot-Audit) | 5 min | 0:35 |
| §4 Soak-Window | 15 min | 0:50 |
| §7 Sign-Off Initial-Draft | 10 min | 1:00 |
| Reserve fuer Rollback (§5 + §6 + 30min Beobachtung) | 60 min | 2:00 |
| Henrik-Audit-Sign-Off-Review-Buffer | 60 min | 3:00 |
| Hairpin-Rollback-Fenster (am Folgetag) | 4h | n/a |

**Konkretes Cutover-Window:**

- **Datum:** Montag 2026-05-25 (KW-22)
- **Cutover-Start:** 10:00 CEST
- **Cutover-Latest-Commit-To-Rust:** 10:35 CEST (Boot-Audit-Pass)
- **Soak-Window-Ende:** 10:50 CEST
- **Sign-Off-Window-Ende:** 13:00 CEST
- **Hairpin-Rollback-Slot:** Dienstag 2026-05-26, 09:00-13:00 CEST

**Begruendung Werktag-Vormittag:**

1. Geringer Side-Effect-Load auf Pilot-VM (keine Cron-Job-
   Konflikte, keine Wartungs-Fenster ueberlappend).
2. Engineering-Verfuegbarkeit hoch (Reza, Selin, Tomás,
   Henrik). Sofort-Eskalation moeglich.
3. Hairpin-Rollback-Fenster am Folgetag faellt nicht auf
   Wochenende.
4. AR-Sichtungs-Fenster (Sign-Off-Approval fuer Welle-2-
   Trigger) liegt innerhalb der Werktags-Woche.

**Verbotene Cutover-Slots:**

- Freitag-Nachmittag (Wochenend-Rollback-Risiko).
- Mittwoch-Mittag (kollidiert mit Wednesday-Validation-Run-
  Re-Run-Option).
- Sonntag/Feiertag (kein Engineering-Standby).

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Tomás (Matrix-Lead) | bei Welle-1/Welle-2/Welle-3-Interaktion |
| 3 | Henrik (Internal Audit) | bei Audit-Trail-Luecke |
| 4 | AR (Fred) | bei irreversible-despawn-Bedarf oder Substanz-Eskalation |

---

— Kai Hoffmann (DevOps), Sprint-Tag-34, 2026-05-18.
