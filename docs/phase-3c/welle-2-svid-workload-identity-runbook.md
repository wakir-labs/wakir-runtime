---
title: "Phase-3c Welle-2 svid_workload_identity Operator-Cutover-Runbook"
owner: "Kai Hoffmann (DevOps), Tomás Reinhart (Matrix-Lead)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065, 0066"
welle: 2
component: "svid_workload_identity"
env_var: "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"
cutover_date: "2026-06-08"
cutover_window_cest: "10:00-14:00"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 35
parallel_welle: 1
---

# Phase-3c Welle-2 svid_workload_identity Operator-Cutover-Runbook

Operator-Runbook fuer den **Welle-2-Cutover-Tag** der Phase-3c
Migration (Python-Default -> Rust-Default fuer die
`svid_workload_identity`-Komponente der Persona-Engine, 8. emittierte
`BackendDecision`). Ziel-Cutover-Datum: Montag 2026-06-08, KW-24
parallel zu Welle-1 (`v907_verify`) gemaess ADR-0066 §Option-A+.

Dies ist das **operative Day-Of-Skript**. Hermetic-Validation
(`phase-3c-welle-2-validation.yml`, PR #196) gehoert in das Schwester-
Runbook [`../operations/phase-3c-welle-2-runbook.md`](../operations/phase-3c-welle-2-runbook.md).
Dieses Runbook hier ist Operator-Hand-Territory: Pilot-VM, echter
NATS-Bus, echte Quadlet-Restart-Sequenz, echte SPIFFE-Workload-API-
Stream-Beobachtung.

Schwester-Runbook fuer Welle-1 (parallel-Cutover-Coordination):
[`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md)
(PR #228, Tag-34).

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0065 Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| ADR-0058 Pilot-Persona-Migration + SSH-Hand-Nachtrag | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0060 Live-FCOS-VM-CI-Gate | `decisions/0060-live-fcos-vm-ci-gate.md` |
| Welle-2 Wednesday-Validation-Workflow | `.github/workflows/phase-3c-welle-2-validation.yml` (PR #196, `2a33a8c` Tag-29) |
| Welle-2 Sibling-Validation-Runbook | `docs/operations/phase-3c-welle-2-runbook.md` |
| Welle-1 Pre-Cutover-Operator-Runbook | `docs/phase-3c/welle-1-v907-verify-runbook.md` (PR #228, Tag-34) |
| SVID-Substrate-Resolver | PR #191 (`7e2defb` Tag-25) — `wirelang/persona_engine/rust_backend_switch.py::resolve_svid_workload_identity_backend` |
| SVID-Container-Image-Build-Pipeline | PR #201 (`cddce13` Tag-29) — `docs/operations/svid-workload-identity-image-build.md` |
| SVID Cross-Lang-Hash-Parity-Pins | PR #224 (`de47cb3` Tag-33, Henrik F-6 Mitigation) — `tests/fixtures/svid-workload-cross-lang/fixtures.json` |
| BackendDecision-Aggregator | `scripts/phase-3c/backend-decision-aggregator.py` (PR #179) |
| Quadlet-Inventar (9-Binary) | `quadlet/wakir-rust-cli.container` |
| Cosign-Policy | `policies/cosign-policy-phase-3b.yaml` |
| SVID Cross-Lang-Parity-Test | `tests/identity/test_svid_workload_identity_cross_lang_parity.py` |
| SVID Workload-API E2E-Acceptance | `tests/acceptance/phase_3c/test_welle_2_svid_workload_identity_e2e.py` |
| Selin-Cutover-Smoke-Skript | `scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.sh` (Selin Tag-35, parallel zu diesem Runbook) |
| SVID-Canonical-Schema | `wirelang/identity/svid_workload_identity_canonical.py` |

---

## §1 Pre-Conditions

**Pflicht-Checkliste**. Jeder Punkt muss vor dem Cutover-Step (§3)
verifiziert und mit Evidenz-Pfad protokolliert sein. Bei jedem
Nein: Stop und Eskalation an Mira -> Priya.

- [ ] **Gate-1 (Cosign-Policy-Signing-Inventar)** — gruen.
      Evidence: `policies/cosign-policy-phase-3b.yaml` listet
      `svid-workload-identity` unter den 9 signierten Persona-Engine-
      Binaries (`name: svid-workload-identity`, Zeile ~312, mit
      `in_image_path: /opt/wakir/bin/wakir-persona-engine-svid-
      workload-identity`).
      `scripts/phase-3c-trigger-gate-aggregator.py --json` Gate-1
      `status: green`.
- [ ] **Gate-2 (Quadlet-Inventar 9 Binaries)** — gruen.
      Evidence: `quadlet/wakir-rust-cli.container` Tag-29-Update
      enthaelt `wakir-persona-engine-svid-workload-identity` im
      Binary-Block (Item 8 der 9-Binary-Liste in der
      `Exec=`-Schleife des Installer-Containers, ergaenzt durch
      `wakir-persona-engine-v907-verify` als Item 9 Tag-31). PR
      #201 fuer SVID-Image-Build und folgende Quadlet-PRs sind
      gemerged.
- [ ] **Gate-3 (Rust-Backend-Switch-Resolver wired)** — gruen.
      Evidence:
      `wirelang/persona_engine/rust_backend_switch.py::resolve_svid_workload_identity_backend`
      existiert (PR #191 Tag-25), liest
      `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` als Pflicht-Env, mit
      `DEFAULT_RUST_SVID_WORKLOAD_IDENTITY_BIN ==
      /opt/wakir/bin/wakir-persona-engine-svid-workload-identity`.
      Engine-Boot-Audit emittiert 8. `BackendDecision` mit
      `component=svid_workload_identity` (siehe `wirelang/persona_engine/engine.py` Zeilen 564-573).
- [ ] **Gate-4 (Observability-Baseline)** — gruen ODER yellow-
      tolerated (operator-hand-staged Baseline-File auf Pilot-VM
      ist erwartet, GitHub-Runner-Baseline-File nicht).
- [ ] **Gate-5 (Bridge-Audit-Roundtrip)** — gruen. Evidence:
      `tests/integration/test_bridge_audit_roundtrip_e2e.py` passt
      (oder all-SKIP auf Runner ohne replay_cli-Binary). SVID-Bind-
      State-Hash-Audit-Annotation wird emittiert.
- [ ] **Welle-2-Wednesday-Validation-Run gruen** (2026-06-03
      06:00 UTC, KW-23 Mittwoch — 5 Tage vor Cutover-Montag).
      Evidence: `cutover-acceptance-decision-welle-2.json`
      `ready_for_live_smoke == true`. Artifact-Retention 30 Tage.
      Workflow: `.github/workflows/phase-3c-welle-2-validation.yml`
      (PR #196).
- [ ] **Welle-1-Cutover-Status verifiziert** (Welle-1 ist
      parallel-laufend KW-24 Montag). Drei zulaessige Zustaende
      fuer Welle-2-Cutover-Trigger:
      - **(a) Welle-1 `green` Sign-Off** (§7 Welle-1-Runbook) —
        Welle-2 startet planmaessig.
      - **(b) Welle-1 `green-with-yellow-notes`** — Welle-2 startet,
        aber Mira-Hand-Decision-Point mit explizitem Yellow-Notes-
        Review im Cutover-Window.
      - **(c) Welle-1 `rollback`** — Welle-2 wird VERSCHOBEN, nicht
        gestartet (siehe §9 R-3). AR-Eskalation Pflicht.
- [ ] **Engine-Health-Baseline aufgezeichnet** (Pilot-VM, letzte
      30 min, Python-Default-Posture). Latency-p50/p95, Error-Rate,
      BackendDecision-Volume pro Minute, SPIFFE-ID-Resolution-Rate.
      Persistiert in
      `/var/lib/wakir/baselines/welle-2-pre-cutover-<TS>.json` auf
      Pilot-VM. **Wichtig:** Diese Baseline wird nach Welle-1-
      Cutover und vor Welle-2-Cutover frisch aufgezeichnet — die
      `v907_verify`-Cutover hat die Engine-Posture veraendert, eine
      Pre-Welle-1-Baseline ist nicht uebertragbar.
- [ ] **BackendDecision-Aggregator-Snapshot vorhanden** (PR #179).
      Evidence: `scripts/phase-3c/backend-decision-aggregator.py
      --component svid_workload_identity --window 5m --format json`
      liefert gueltige Records mit `backend=python` >99% (Baseline).
- [ ] **Quadlet 9-Binary-Set deployed auf Pilot-VM**.
      Evidence: `ssh root@192.168.178.116 'ls -la /opt/wakir/bin/'`
      zeigt alle 9 Binaries inklusive
      `wakir-persona-engine-svid-workload-identity` und
      `wakir-persona-engine-v907-verify`.
- [ ] **Cosign-Policy 9-Binary signiert + verifiziert**.
      Evidence: `cosign verify --policy
      policies/cosign-policy-phase-3b.yaml
      ghcr.io/wakir-labs/wakir-persona-engine:<digest>` 0-exit. Das
      transitiv-verifizierte Image-Manifest umfasst SVID-Image
      (PR #201) als Item 8 der Build-Inventory und federation-
      resolver-Image als Item 9.
- [ ] **SPIFFE-Workload-API-Socket bind-mounted und reachable**.
      Evidence: `ssh root@192.168.178.116 'ls -la /run/spire/agent-
      sockets/api.sock'` zeigt UDS, `nc -z -U /run/spire/agent-
      sockets/api.sock` 0-exit. SPIRE-Agent-Service `systemctl
      status spire-agent.service` aktiv.
- [ ] **Henrik-Audit-Trail-Substrate ready** (Tag-27).
      Evidence: Bridge-Audit-Writer emittiert seit >24h ohne
      Errors auf Pilot-VM. SVID-Audit-Annotation (SPIFFE-ID, SAN-
      Liste, cert-not-after, bind-state-hash) wird beobachtet im
      Python-Default-Pfad.
- [ ] **Cross-Lang-Hash-Parity-Pins frisch** (PR #224 Tag-33,
      Henrik F-6 Mitigation). Evidence:
      `tests/fixtures/svid-workload-cross-lang/fixtures.json`
      existiert, Pin-Count ≥ 5, last-mod ≥ Tag-33. Das ist die
      Baseline-Referenz fuer §4.2 Cross-Lang-Hash-Parity-Probe.
- [ ] **Hairpin-Rollback-Fenster im Kalender geblockt**
      (4h-Slot, naechster Werktag-Vormittag).

---

## §2 Pre-Flight-Smoke

Selin's Welle-2-Smoke-Skript ausfuehren, Operator-Hand auf der
**Mira-Box** (nicht Pilot-VM), weil das Skript Konnektivitaet
zur Pilot-VM testet und kein Pilot-internes Artefakt ist. Skript
liefert Selin parallel zu diesem Runbook (Tag-35 Cross-Spawn).

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.sh \
    --pilot 192.168.178.116 \
    --component svid_workload_identity \
    --env-var WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND \
    --dry-run-window 5m \
    --json-out /tmp/welle-2-smoke-$(date +%Y%m%d-%H%M%S).json
echo "exit=$?"
```

**Erwartete Outputs:**

- **Exit-Code 0** = green. Cutover-Step §3 darf starten.
- **Exit-Code 1** = yellow (nur Gate-4 Observability-Baseline
  isolated ODER Welle-1-`green-with-yellow-notes` post-hoc).
  Mira-Hand-Decision noetig vor §3.
- **Exit-Code ≥2** = red. Stop. Eskalation an Selin (Persona-
  Engine-Owner) + Reza (SVID-Substrate-Owner) + Tomás
  (Matrix-Lead).

Das JSON-Envelope (`/tmp/welle-2-smoke-*.json`) ist Henrik-Audit-
Pflicht-Evidenz und wird in §7 Sign-Off zitiert.

**Timing-Erwartung:** ~2-4 min wall-clock. Skript prueft
SSH-Reachability, Quadlet-Status-Snapshot, Cosign-Policy-Match,
Engine-Health-Baseline-Delta gegen Tag-N-1, SPIFFE-Workload-API-
Socket-Reachability, BackendDecision-Aggregator-Sanity fuer
`component=svid_workload_identity`. Keine Side-Effects auf Pilot-VM
(read-only).

**Welle-1-Parallel-Hinweis:** Wenn Welle-1-Cutover noch im Soak-
Window (§4 Welle-1-Runbook) laeuft: Welle-2 Pre-Flight-Smoke darf
parallel laufen, **aber** §3 Cutover-Step Welle-2 startet erst
nach Welle-1-Soak-Window-Ende (T_Welle1_Sign-Off_Initial). Begruendung:
zwei gleichzeitige Backend-Flips wuerden den BackendDecision-
Aggregator-Sliding-Window mit ueberlappenden Component-Signals
verrauschen.

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

**Schritt 3.2 — Pre-Restart-Snapshot (post-Welle-1)**

```bash
# Auf Pilot-VM, root-shell:
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-2 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-2-cutover.log
systemctl status wakir-persona-engine.service --no-pager | head -20 \
    | tee -a /var/log/wakir/welle-2-cutover.log
journalctl -u wakir-persona-engine.service --since "-5 min" --no-pager \
    | tail -50 > /var/log/wakir/welle-2-cutover-pre-journal.txt
# Welle-1-State-Check: bestaetige dass v907_verify backend=rust laeuft
# (Welle-1 ist bereits gecutovered an diesem Tag).
journalctl -u wakir-persona-engine.service --since "-30 min" --no-pager \
  | grep -c "BackendDecision.*v907_verify.*backend=rust" \
  | tee -a /var/log/wakir/welle-2-cutover.log
```

**Schritt 3.3 — Quadlet-Env-Overlay setzen**

Quadlet-Override-Pattern: drop-in env-overlay-File, nicht
in-place edit der Container-Unit. Reversibel, ADR-0058-konform.
Coexistiert mit Welle-1-Overlay (separates Drop-in-File).

```bash
# Auf Pilot-VM:
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
cat > /etc/systemd/system/wakir-persona-engine.service.d/welle-2-svid-workload-identity-rust.conf <<'EOF'
# Phase-3c Welle-2 Cutover-Overlay
# Generated: <TS_PRE>
# ADR-0065 §Welle-2, ADR-0066 §Option-A+ KW-24 parallel
[Service]
Environment="WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust"
EOF
systemctl daemon-reload
# Sanity-Check: Welle-1-Drop-In existiert weiterhin (kein Konflikt).
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
```

**Schritt 3.4 — Restart Persona-Engine**

```bash
# Auf Pilot-VM:
systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-2-cutover.log
```

**Schritt 3.5 — Boot-Audit Wait-Loop (30s, 8/9 BackendDecisions)**

Erwartung: mindestens 5 `BackendDecision`-Records mit
`backend=rust` und `component=svid_workload_identity` werden
innerhalb 30s im Bridge-Audit-Stream emittiert. Gleichzeitig
muessen die 8. (svid) und 9. (v907) `BackendDecision`-Boot-
Records sichtbar sein — wenn nur 7/9 oder weniger, dann ist die
Engine im Migrations-Drift-Zustand und §6 Rollback ist Pflicht.

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
    if "BackendDecision" in msg and "svid_workload_identity" in msg and "backend=rust" in msg:
        hits += 1
        print(f"hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("BOOT-AUDIT-OK: 5 BackendDecision svid_workload_identity rust-records within window")
        sys.exit(0)
    if time.monotonic() > deadline:
        print(f"BOOT-AUDIT-FAIL: only {hits}/5 hits within 30s", file=sys.stderr)
        sys.exit(2)
print(f"BOOT-AUDIT-FAIL: stream-end, hits={hits}", file=sys.stderr)
sys.exit(2)
'
```

**Schritt 3.6 — SPIFFE-ID-Resolution-Stream-Sanity (zusaetzlich
zu Welle-1-Pattern)**

Spezifisch fuer Welle-2: nach Restart muss die erste Workload-
API-Fetch-RPC innerhalb 60s erfolgreich sein und einen gueltigen
SPIFFE-ID (Subject URI `spiffe://wakir.{org_id}/persona/{persona_id}`)
emittieren. Wenn die Workload-API-Fetch-Sequenz schlaegt fehl, ist
das ein Welle-2-spezifisches Health-Signal, das im Welle-1-Pattern
nicht existiert.

```bash
# Auf Pilot-VM:
timeout 60 journalctl -u wakir-persona-engine.service \
    --since "${TS_RESTART}" -f \
    --output=json --no-pager \
  | python3 -c '
import json, sys, time
deadline = time.monotonic() + 60
for line in sys.stdin:
    try:
        rec = json.loads(line)
    except Exception:
        continue
    msg = rec.get("MESSAGE", "")
    if "spiffe://wakir." in msg and "/persona/" in msg:
        print(f"SPIFFE-ID-OK: {msg[:200]}")
        sys.exit(0)
    if time.monotonic() > deadline:
        print("SPIFFE-ID-FAIL: no spiffe:// emission within 60s", file=sys.stderr)
        sys.exit(2)
sys.exit(2)
'
```

Wenn Boot-Audit-Wait-Loop oder SPIFFE-ID-Sanity Exit ≠ 0: sofort
§6 Rollback-Procedure.

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
    --component svid_workload_identity \
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

**§4.2 — Cross-Lang-Hash-Parity gegen Python-Baseline (PR #224)**

PR #224 (`de47cb3` Tag-33, Henrik F-6 Mitigation) stellt die
SVID-Workload-Identity Cross-Lang-Hash-Parity-Pins bereit. Im
Soak-Window: 5 Synthetik-SVID-Canonical-Hash-Calls, jede mit
Python-Vergleichs-Hash gegen die Pin-Baseline.

```bash
# Auf Mira-Box:
python3 scripts/phase-3c/cross-lang-hash-parity-probe.py \
    --component svid_workload_identity \
    --samples 5 \
    --pilot 192.168.178.116 \
    --baseline-pins tests/fixtures/svid-workload-cross-lang/fixtures.json \
    --canonical-module wirelang.identity.svid_workload_identity_canonical
```

Erwartung: 5/5 Hashes match. Jede Drift => sofort §6 Rollback.

Hintergrund: die Cross-Lang-Parity prueft die deterministische
Kanonisierung der SVID-Binding-Records (`bindings` JSON-Schema
`wakir.identity.svid-workload`, siehe
`wirelang/identity/svid_workload_identity_canonical.py`). Drift
heisst: Python- und Rust-Side haben unterschiedliche Canonical-
Forms — das ist ein blocker-level Bug fuer SPIFFE-Audit-Trail-
Konsistenz.

**§4.3 — Latency-Histogramm + SPIFFE-Workload-API-Fetch-Latency
aus Grafana (PR #179)**

Grafana-Dashboard `Persona-Engine — Backend Latency by
Component`. Filter: `component=svid_workload_identity`,
`backend=rust`, last 15min.

Erwartete Schwellen (gegen Engine-Health-Baseline aus §1):

| Perzentil | Schwelle |
|---|---|
| p50 | ≤ 1.2× Baseline |
| p95 | ≤ 1.5× Baseline (HARTE GRENZE — siehe §5 Trigger) |
| p99 | ≤ 2.0× Baseline (Warn-Schwelle, kein Auto-Rollback) |

**SVID-spezifisches Sub-Panel:** `SPIFFE-Workload-API-Fetch-Latency`
— die gRPC-FetchX509SVID-RPC-Roundtrip-Time gegen den
SPIRE-Agent-UDS-Socket. Erwartung: p95 ≤ 50ms (intra-VM UDS-RPC).
Bei p95 > 200ms: SPIRE-Agent-Health-Issue, Rollback.

Operator: Screenshot pro 5min-Slice (3 Screenshots gesamt) +
JSON-Export an Henrik-Audit-Trail anhaengen.

**§4.4 — Bridge-Audit-Writer Error-Freiheit + SPIFFE-Audit-
Annotation-Stream**

```bash
# Auf Pilot-VM:
journalctl -u wakir-bridge-audit-writer.service --since "${TS_RESTART}" \
    -p err --no-pager | tee /var/log/wakir/welle-2-bridge-audit-errors.txt
wc -l /var/log/wakir/welle-2-bridge-audit-errors.txt

# SVID-spezifisch: Audit-Annotation-Records mit SPIFFE-ID + cert-not-after
journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" \
    --no-pager | grep -c "spiffe://wakir\." \
    | tee -a /var/log/wakir/welle-2-cutover.log
```

Erwartung:
- 0 Error-Zeilen im 15-min-Soak-Window. Jede Error-Zeile =
  automatischer §6 Rollback.
- `spiffe://wakir.`-Annotation-Count > 0 (Smoke fuer SPIFFE-ID-
  Resolution-Continuity).

---

## §5 Rollback-Trigger — Exit-Decision-Matrix

Vier harte Trigger (drei wie Welle-1 plus ein SVID-spezifischer).
Bei JEDEM einzigen Trigger: sofort §6, keine Diskussion, keine
Eskalations-Verzoegerung. Mira-Hand entscheidet im Cutover-Window
autark, AR-Override nur post-hoc dokumentiert.

| # | Trigger | Quelle | Schwelle | Aktion |
|---|---|---|---|---|
| T-1 | Latency p95 > 1.5× Baseline | Grafana (§4.3) | Anhaltend ≥3 Slices (15min) | Rollback (§6) |
| T-2 | SPIFFE-Audit-Parse-Error | Bridge-Audit-Writer journal (§4.4) | Jede einzelne ERR-Zeile | Rollback (§6) |
| T-3 | Cross-Lang-Hash-Drift | Parity-Probe (§4.2) | Jede einzelne Drift in 5 Samples | Rollback (§6) |
| T-4 | SVID-Cert-Validity-Window-Drift | Engine-Audit-Stream `spiffe://wakir.*` Annotations | cert-not-after-Skew zwischen Python-Baseline und Rust-Backend ≥ 5s ODER cert-not-after liegt in der Vergangenheit | Rollback (§6) |

**T-4 Begruendung:** Der Rust-Backend liest den X.509-SVID via
gRPC FetchX509SVID; die not-after-Timestamp-Parse-Semantik
zwischen Python-asn1crypto und Rust-x509-parser muss bit-identisch
sein. Bei Skew ≥ 5s ist die Audit-Annotation nicht-deterministisch,
was die Cross-Lang-Hash-Parity (§4.2) zwar fangen sollte — aber
T-4 ist Defense-in-Depth fuer den Fall dass der Parse-Drift
unterhalb der Pin-Sample-Diversitaet liegt.

**Sekundaere Yellow-Trigger** (kein Auto-Rollback, aber
Mira-Hand-Decision-Point):

- BackendDecision-Aggregator `rust_share` zwischen 0.95-0.99
  (§4.1 Exit 1).
- Latency p99 > 2.0× Baseline (§4.3 Warn-Schwelle).
- SPIFFE-Workload-API-Fetch-Latency p95 zwischen 50ms-200ms
  (§4.3 Sub-Panel).
- Error-Rate Engine-Service zwischen 0.1% und 0.5% (Baseline
  ist <0.1%).
- Welle-1-`green-with-yellow-notes` (parallel-coupled Yellow-Pfad,
  siehe §9 R-3).

Bei zwei oder mehr gleichzeitigen yellow-Triggern: Behandlung
als red. Rollback.

---

## §6 Rollback-Procedure

Reversibel-by-design. Drop-in Env-Overlay wird entfernt,
Service-Restart, Verify Backend=python, SPIFFE-Resolution-
Continuity verify. Ziel: <90s Time-to-Recovery. Welle-1-State
(falls Welle-1 `green`) bleibt unberuehrt — nur das Welle-2-
Overlay-File wird entfernt.

```bash
# Auf Pilot-VM (SSH bereits offen aus §3):
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-2 Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-2-cutover.log

# 1. Env-Overlay entfernen — NUR Welle-2-Drop-In, Welle-1 bleibt
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-2-svid-workload-identity-rust.conf
ls -la /etc/systemd/system/wakir-persona-engine.service.d/
# Erwartet: welle-1-v907-verify-rust.conf bleibt; welle-2-svid-* weg.
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
    if "BackendDecision" in msg and "svid_workload_identity" in msg and "backend=python" in msg:
        hits += 1
        print(f"rb-hit#{hits}: {msg[:160]}", flush=True)
    if hits >= 5:
        print("ROLLBACK-OK: backend=python verified for svid_workload_identity")
        sys.exit(0)
    if time.monotonic() > deadline:
        sys.exit(2)
sys.exit(2)
'

# 4. SPIFFE-Resolution-Continuity verify (60s Window post-Rollback-Restart)
timeout 60 journalctl -u wakir-persona-engine.service \
    --since "${TS_RB_RESTART}" -f \
    --output=json --no-pager \
  | grep -m1 "spiffe://wakir\." \
  | tee -a /var/log/wakir/welle-2-cutover.log

# 5. Log-Tail
TS_RB_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Welle-2 Rollback-Done: ${TS_RB_DONE}" | tee -a /var/log/wakir/welle-2-cutover.log
```

Nach Rollback: 30-min Stabilitaets-Beobachtung mit
BackendDecision-Aggregator (§4.1, --target-backend python) und
SPIFFE-Resolution-Stream-Sanity (§3.6-Pattern). Dann §7 Sign-Off
mit verdict=`rollback`, Root-Cause-Analyse binnen 48h pflichtig
(Reza SVID-Substrate-Resolver, Tomás Cross-Module-Korrelation,
Henrik Audit-Sicht).

---

## §7 Sign-Off — Henrik-Audit-Trail

Drei-Phasen-Evidenz pro Cutover-Run. Henrik-Audit-Sign-Off
ist Pflicht vor Welle-3-Trigger.

**PRE-Evidenz (vor §3 Cutover-Step):**

- `/tmp/welle-2-smoke-*.json` (§2 Skript-Output)
- Welle-2-Wednesday-Validation-`cutover-acceptance-decision-welle-
  2.json` (§1, GitHub-Actions-Artifact-URL)
- Engine-Health-Baseline `/var/lib/wakir/baselines/welle-2-pre-
  cutover-*.json` (post-Welle-1, frisch)
- BackendDecision-Aggregator-Snapshot (§1, Python-Default
  `svid_workload_identity` ≥99%)
- Welle-1-Sign-Off-Status (§1, Pflicht-Vorbedingung, drei zulaessige Zustaende)

**TEL-Evidenz (waehrend §4 Soak-Window):**

- BackendDecision-Aggregator-Run-Output (§4.1, 15-min Window JSON)
- Cross-Lang-Hash-Parity-Probe-Run (§4.2, 5/5 oder Abweichung)
- Grafana-Latency-Histogramm-Screenshots (§4.3, 3 Screenshots,
  inkl. SPIFFE-Workload-API-Fetch-Latency-Sub-Panel)
- Bridge-Audit-Writer-Error-Count (§4.4, 0-Zeilen-File)
- `spiffe://wakir.`-Annotation-Count (§4.4, >0)

**POST-Evidenz (nach §4 oder §6):**

- Cutover-Log `/var/log/wakir/welle-2-cutover.log` (vollstaendig)
- Journal-Excerpt Engine-Service +1h post-cutover
- Final-Verdict (`green`, `green-with-yellow-notes`, `rollback`)
- AR-Approval-Tag fuer Welle-3-Trigger (nur bei `green`)

**Sign-Off-Template:**

```yaml
welle: 2
component: svid_workload_identity
cutover_date: 2026-06-08
cutover_window_cest_start: HH:MM
cutover_window_cest_end: HH:MM
operator: mira
audit: henrik
verdict: green | green-with-yellow-notes | rollback
yellow_notes: []
red_triggers_hit: []
welle_1_signoff_status: green | green-with-yellow-notes | rollback
pre_evidence_paths: [...]
tel_evidence_paths: [...]
post_evidence_paths: [...]
ar_approval_tag_for_welle_3: null  # gesetzt durch AR post-Sign-Off
```

Henrik-Audit-Sign-Off-File-Pfad:
`/var/home/fred/AI-Corp/agents-workspaces/henrik/audit/welle-2-svid-workload-identity-signoff-2026-06-08.yaml`

---

## §8 Mira-SSH-Hand-Authority

ADR-0058 §Nachtrag (approved KW-20) etabliert die Mira-SSH-
Hand-Authority fuer Pilot-VM-Operations:

- **Mira-Hand-Operations (autark):** systemctl restart,
  Env-Overlay-File-Edits, Journal-Reads, Quadlet-Override-
  Drop-Ins, Service-Status-Checks, Cosign-Verify-Calls,
  Cron-Re-Schedule innerhalb Cutover-Window, SPIRE-Agent-
  Health-Probe (`nc -z -U`-Pattern, read-only).
- **AR-Hand-Operations (irreversibel-despawn):** `podman rm`
  ohne Backup, Volume-Wipe (`podman volume rm`), System-
  Hostname-Change, Network-Namespace-Drop, FCOS-Upgrade,
  Disk-Repartitionierung, SPIRE-Server-Trust-Bundle-Rotation,
  SPIFFE-Trust-Domain-Change.
- **Cutover-Step §3 + Rollback §6 = Mira-Hand-Operations.**
  Keine AR-Eskalation noetig. AR-Sichtung ist post-hoc
  Sign-Off-Pflicht (§7).

Eskalations-Wege im Cutover-Window:

1. **Operator-Konflikt** (z.B. yellow-yellow Trigger-
   Kombination): Mira-Hand-Decision autark. Henrik-Audit
   protokolliert die Entscheidung.
2. **Substanz-Konflikt** (z.B. Cross-Lang-Hash-Drift bei
   wiederholtem Cutover ODER SVID-Cert-Validity-Drift T-4):
   Eskalation Mira -> Priya -> AR. Reza wird hinzugezogen
   (SVID-Substrate-Owner).
3. **Infra-Incident** (z.B. Pilot-VM SSH-Loss, NATS-Bus-
   Drop, SPIRE-Agent-Socket-Loss): Mira-Hand Rollback nach
   §6, dann Eskalation Mira -> AR fuer Recovery-Decision.

---

## §9 Bekannte Risiken

**R-1 — Parallel-Cutover Welle-1 ↔ Welle-2 (ADR-0066 §Option-A+)**
Welle-1 (`v907_verify`) und Welle-2 (`svid_workload_identity`)
landen am selben Cutover-Tag (Montag KW-24). Sequenzierungs-Regel:
**Welle-1 zuerst, Welle-2 zweitens, Soak-Windows getrennt.**
Welle-2 startet erst nach Welle-1-Sign-Off-Initial (§7 Welle-1-
Runbook, `verdict: green` ODER `green-with-yellow-notes`). Die
beiden Engine-Restarts liegen mindestens 15min auseinander
(Welle-1-Soak-Window-Ende = T_Welle1_Restart + 15min = frueheste
Welle-2-Restart-Zeit). Begruendung: Aggregator-Sliding-Window-
Klarheit pro Komponente, Disambiguierung von BackendDecision-
Records.

**R-2 — Read-Only-Identity-Charakter (geringes Risiko)**
SVID-Workload-Identity ist ein **Lookup-Pfad**, nicht ein
Mutations-Pfad. Rollback-Cost ist gering: env unset + restart
genuegt. Keine persistenten State-Aenderungen, keine
Transaction-Log-Inkonsistenzen, keine Cross-Module-State-
Migration. Das ist der ADR-0066-Begruendung fuer Welle-2-
Acceleration zugrundeliegende Risiko-Calc.

**R-3 — Pre-Phase-3a-Gap: SVID-Pin-Coverage relativ jung**
Die SVID-Workload-Identity Cross-Lang-Hash-Parity-Pins (PR #224
`de47cb3` Tag-33, Henrik F-6 Mitigation) sind 2 Tage frisch zum
Cutover-Datum (Tag-33 -> Tag-35-Cutover-Date-Decision-Point ->
Tag-N=Tag-35+~13 = KW-24 Montag). Pin-Sample-Diversitaet ist mit
≥ 5 Samples kalibriert, aber 30-Tage-Soak-Wert noch nicht
erreicht. Mitigation: T-4 SVID-Cert-Validity-Window-Drift in §5
ist Defense-in-Depth fuer Drift-Patterns die unterhalb der
Pin-Sample-Diversitaet liegen.

Zusaetzlich: Henrik F-6 (Tag-33) wurde durch PR #224 explizit
adressiert. Wenn der Cutover-Cross-Lang-Hash-Parity-Probe (§4.2)
auf die PR-#224-Pins kalibriert ist und passt, ist F-6 substantiell
mitigiert. Sollte die Probe failen, ist das ein F-6-Reactivation-
Signal und Henrik-Hand-Audit-Hold ist die korrekte Eskalation.

**R-4 — Cosign-Image-Pin-Drift (PR #201 9-Binary)**
Pilot-VM zieht `ghcr.io/wakir-labs/wakir-persona-engine:<tag>`
ueber Quadlet-Pull-Pattern. SVID-Image landete in PR #201
(`cddce13` Tag-29) als Item 8 der Build-Inventory; federation-
resolver-Image landete als Item 9 (Tag-31). Bei Tag-Mutation
zwischen Wednesday-Validation und Monday-Cutover: Cosign-Verify
in §1 Gate-2 wuerde nicht zwingend bemerken. Mitigation:
Pre-Cutover-Step zusaetzlich `podman image inspect ghcr.io/wakir-
labs/wakir-persona-engine | grep Digest` gegen Wednesday-
Validation-Digest-Pin (analog Welle-1 §9 R-6).

**R-5 — SPIRE-Agent-Socket-Availability**
Welle-2 ist die erste Welle, die hartabhaengig vom
SPIRE-Agent-UDS-Socket ist (`/run/spire/agent-sockets/api.sock`).
Falls SPIRE-Agent-Service im Cutover-Window crashes oder den Socket
verliert: Rust-Backend wuerde gRPC-Channel-Error werfen, Python-
Backend wuerde dasselbe Verhalten zeigen (gleiche Fetch-Pfad).
**Pre-Cutover-Verification §1 SPIFFE-Workload-API-Socket bind-
mounted und reachable** addressiert das.

Mitigation: wenn SPIRE-Agent-Loss waehrend Soak-Window: das ist
**kein** Welle-2-Rollback-Trigger im klassischen Sinne (Rollback
wuerde nichts loesen — Python-Backend haengt am selben Socket).
Eskalation Mira -> AR fuer SPIRE-Agent-Recovery, Welle-2-Sign-Off-
Verdict wird `green-with-yellow-notes` mit explizitem SPIRE-
Caveat.

**R-6 — BackendDecision-Aggregator Sliding-Window Schema-Drift**
PR #179 ist tag-recent (KW-21), Schema-Field-Stability noch nicht
30-Tage-soak. Welle-2-Cutover ist KW-24 = 3 Wochen nach #179-Merge
— Schema sollte stabil sein, aber Mitigation analog Welle-1:
Cross-Lang-Hash-Parity-Probe (§4.2) ist unabhaengig vom Aggregator-
Schema. Bei Aggregator-Parse-Fehlern im Cutover-Window: Parity-
Probe ist der Veto-Pfad.

**R-7 — Welle-1-Rollback-Coupling**
Falls Welle-1 `rollback` (§1 zulaessiger Zustand (c)): Welle-2-
Cutover wird VERSCHOBEN, nicht gestartet. Begruendung: Welle-1-
Rollback signalisiert eine Substanz-Anomalie in der
Engine-Posture, die Welle-2-Cutover-Risk-Calc invalidiert (R-2
Read-Only-Argument haelt nur unter normalem Engine-Zustand).
AR-Eskalation Pflicht; Welle-2-Re-Scheduling ist AR-Decision.

---

## §10 Time-Estimate — Cutover-Window-Empfehlung

**Empfehlung:** Werktag-Vormittag, **derselbe Montag wie Welle-1**,
10:00-14:00 CEST, niedriger Stress-Slot. Welle-2 startet nach
Welle-1-Sign-Off-Initial (15min Pufferzeit nach Welle-1-Soak-Ende).

**Konkretes Cutover-Window — Welle-1 + Welle-2 sequenziell am
selben Tag (ADR-0066 §Option-A+):**

| Welle | Sub-Phase | Slot CEST |
|---|---|---|
| Welle-1 | Pre-Conditions Walk-Through | 10:00-10:20 |
| Welle-1 | Pre-Flight-Smoke + Decision | 10:20-10:30 |
| Welle-1 | Cutover-Step | 10:30-10:35 |
| Welle-1 | Soak-Window | 10:35-10:50 |
| Welle-1 | Sign-Off-Initial-Draft | 10:50-11:00 |
| **Pufferzeit (15min)** | Welle-2-Baseline-Re-Aufzeichnung post-Welle-1 | 11:00-11:15 |
| Welle-2 | Pre-Conditions Walk-Through | 11:15-11:35 |
| Welle-2 | Pre-Flight-Smoke + Decision | 11:35-11:45 |
| Welle-2 | Cutover-Step (incl. SPIFFE-ID-Sanity) | 11:45-11:55 |
| Welle-2 | Soak-Window | 11:55-12:10 |
| Welle-2 | Sign-Off-Initial-Draft | 12:10-12:20 |
| Reserve | Beide Wellen Rollback-Reserve (60min) | 12:20-13:20 |
| Reserve | Henrik-Audit-Sign-Off-Review (60min) | 13:20-14:20 |

**Datum: Montag 2026-06-08 (KW-24)**

- **Welle-1-Cutover-Start:** 10:00 CEST
- **Welle-2-Cutover-Start:** 11:45 CEST (frueheste; oder spaeter
  bei Welle-1-Soak-Window-Extension)
- **Welle-2-Latest-Commit-To-Rust:** 11:55 CEST (Boot-Audit-Pass)
- **Welle-2-Soak-Window-Ende:** 12:10 CEST
- **Welle-2-Sign-Off-Window-Ende:** 14:20 CEST
- **Hairpin-Rollback-Slot:** Dienstag 2026-06-09, 09:00-13:00 CEST

**Begruendung Werktag-Vormittag + Sequenziell statt Parallel:**

1. Geringer Side-Effect-Load auf Pilot-VM (keine Cron-Job-
   Konflikte, keine Wartungs-Fenster ueberlappend).
2. Engineering-Verfuegbarkeit hoch (Reza, Selin, Tomás,
   Henrik). Sofort-Eskalation moeglich.
3. Hairpin-Rollback-Fenster am Folgetag faellt nicht auf
   Wochenende.
4. AR-Sichtungs-Fenster (Sign-Off-Approval fuer Welle-3-
   Trigger) liegt innerhalb der Werktags-Woche.
5. **Sequenziell statt parallel:** BackendDecision-Aggregator-
   Sliding-Window pro Komponente bleibt disambiguiert. Zwei
   gleichzeitige Backend-Flips wuerden die Cross-Lang-Hash-
   Parity-Probe-Interpretation verkomplizieren (welche Drift
   gehoert zu welchem Component-Flip?). 15min Pufferzeit ist
   ausreichend fuer Engine-State-Re-Stabilisierung.

**Verbotene Cutover-Slots:**

- Freitag-Nachmittag (Wochenend-Rollback-Risiko).
- Mittwoch-Mittag (kollidiert mit Wednesday-Validation-Run-
  Re-Run-Option).
- Sonntag/Feiertag (kein Engineering-Standby).
- Parallel zu Welle-1-Cutover-Step §3 (siehe R-1).

---

## Anhang A — Notruf-Eskalations-Kette

| Stufe | Wer | Wann |
|---|---|---|
| 0 | Mira (Operator) | autonom im Cutover-Window |
| 1 | Priya (CTO) | bei Cross-Module-Substanz-Konflikt |
| 2 | Reza (SVID-Substrate-Owner) | bei SVID-Canonical-Drift, SPIFFE-ID-Template-Issue, cert-not-after-Skew |
| 3 | Tomás (Matrix-Lead) | bei Welle-1/Welle-2/Welle-3-Interaktion |
| 4 | Henrik (Internal Audit) | bei Audit-Trail-Luecke, F-6-Reactivation-Signal |
| 5 | AR (Fred) | bei irreversible-despawn-Bedarf, Welle-1-Rollback-Coupling, SPIRE-Trust-Domain-Issue |

---

## Anhang B — Cross-Welle-Coordination-Checkliste

Vor Welle-2-Cutover-Start: explizite Verifikation der Welle-1-
Coordination-Items.

- [ ] Welle-1-Runbook gelesen ([`welle-1-v907-verify-runbook.md`](./welle-1-v907-verify-runbook.md))
- [ ] Welle-1-Sign-Off-Verdict bekannt (`green`, `green-with-
      yellow-notes`, oder `rollback`)
- [ ] Bei Welle-1-`rollback`: Welle-2 verschoben (AR-Eskalation)
- [ ] Welle-1-Drop-In-File auf Pilot-VM vorhanden (Welle-1-Cutover
      tatsaechlich passiert): `ls /etc/systemd/system/wakir-persona-
      engine.service.d/welle-1-v907-verify-rust.conf`
- [ ] Welle-1-`v907_verify` `backend=rust` im Aggregator >99%
      (Welle-2-Pre-Cutover-Snapshot bestaetigt)
- [ ] Welle-2-Engine-Health-Baseline frisch aufgezeichnet
      POST-Welle-1 (nicht uebertragen aus Welle-1-Pre-Baseline)

---

— Kai Hoffmann (DevOps), Sprint-Tag-35, 2026-05-18.
