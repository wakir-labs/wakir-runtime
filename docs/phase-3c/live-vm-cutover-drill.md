---
title: "Phase-3c Live-VM Cutover-Drill — Operator-Doku"
owner: "Kai Hoffmann (DevOps)"
audit: "Henrik Voss (Internal Audit)"
adr: "0058, 0065, 0066"
sprint_tag: 40
status: "ready-for-ar-pre-sichtung"
---

# Phase-3c Live-VM Cutover-Drill — Operator-Doku

`scripts/phase-3c/live-vm-cutover-drill.sh` ist der SSH-Hand
Marathon-Driver fuer den KW-24..27 Phase-3c Cutover gegen die
wakir-pilot Live-VM (`192.168.178.116`).  Er wickelt die in den
sieben Welle-Runbooks (`docs/phase-3c/welle-{1..7}-*-runbook.md`)
dokumentierten Operator-Schritte §3.3 + §3.4 + §3.5 + §6 in eine
einheitliche, maschinen-parseable Sequenz pro Welle, plus einen
`--full-marathon`-Modus der alle sieben Wellen in der ADR-0066
Doppel-Welle-Reihenfolge durchspielt.

Dieses Skript ersetzt **nicht** die Welle-Runbooks.  Es konsolidiert
ihre operativen Day-Of-Steps, damit die Mira-SSH-Hand-Authority in
einem reproduzierbaren Marathon-Lauf wirkt und damit die
Sequenz-Gates (Welle-1-Sign-Off vor Welle-2, Welle-3-Sign-Off vor
Welle-4+5, etc.) zwingend erzwungen werden.

## Anchor-Tabelle

| Anker | Pfad |
|---|---|
| ADR-0058 §Nachtrag Mira-SSH-Hand-Authority | `decisions/0058-pilot-persona-migrations-plan.md` |
| ADR-0065 Phase-3c Cutover-Plan | `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md` |
| ADR-0066 Beschleunigung Option-A+ | `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` |
| Welle-Runbooks 1..7 | `docs/phase-3c/welle-{1..7}-*-runbook.md` |
| Hermetic Tests | `tests/scripts/test_live_vm_cutover_drill.py` |
| Skript | `scripts/phase-3c/live-vm-cutover-drill.sh` |

---

## §1 Pre-Conditions

Vor jedem Drill-Aufruf (Live oder Dry-Run):

- [ ] SSH-Key `~/.ssh/wakir-pilot-vm-diagnose` ist lesbar
      (`-r` mode bits) auf der Mira-Box.  Live-Mode prueft das
      automatisch und exit-codet 3 bei Fehlen.
- [ ] Welle-Runbook §1 Pre-Conditions fuer die Ziel-Welle sind alle
      auf gruen.  Die Drill-Skript **prueft die Welle-Runbook-Gates
      nicht** — sie bleiben Operator-Hand-Verantwortung gemaess
      jeweiligem Welle-Runbook §1.
- [ ] Sequence-Gate-Sign-Offs fuer alle Parent-Wellen sind unter
      `${WAKIR_DRILL_LOG_DIR:-/tmp/wakir-cutover-drill}/signoff/
      welle-<N>.signoff` mit `verdict=green` oder
      `verdict=green-with-yellow-notes` gesetzt.  Marker werden
      automatisch vom Drill bei erfolgreichem `--full-marathon`
      gesetzt; bei Solo-Welle-Aufrufen ist der Operator
      verantwortlich (oder benutzt `--skip-gate` fuer Replay).
- [ ] Pilot-VM erreichbar; Quadlet 7-Binary-Set deployed.

**Pflicht-Stempel-Datum**: jeder Drill-Run schreibt Log-Datei nach
`${WAKIR_DRILL_LOG_DIR}/welle-<N>-<action>-<ts>.log` (Solo) bzw.
`${WAKIR_DRILL_LOG_DIR}/marathon-<ts>.log` (Marathon).

---

## §2 Operator-Modes

### §2.1 Solo-Welle-Replay

Operator-Hand-Aktion fuer einen einzelnen Cutover-Step.  Standard-
Pfad fuer KW-24..27 Live-Cutover-Tage.

```bash
# Pre-Snapshot (vor §3.3 Overlay-Schreibung)
scripts/phase-3c/live-vm-cutover-drill.sh \
    --welle 1 --action pre

# Cutover-Step (§3.3 + §3.4 + §3.5 Boot-Audit Wait-Loop)
scripts/phase-3c/live-vm-cutover-drill.sh \
    --welle 1 --action cutover

# Post-Verify (Backend-Decision-Stream sliding-window-Smoke)
scripts/phase-3c/live-vm-cutover-drill.sh \
    --welle 1 --action post

# Rollback-Path (§6 — Overlay entfernen, Verify backend=python)
scripts/phase-3c/live-vm-cutover-drill.sh \
    --welle 1 --action rollback
```

### §2.2 Full-Marathon

Walks Wellen 1..7 in der ADR-0066-Reihenfolge.  Stoppt sofort bei
erster Welle die rot wird.  Sign-Off-Marker werden automatisch
geschrieben.

```bash
scripts/phase-3c/live-vm-cutover-drill.sh --full-marathon
```

**Wichtig:** der Marathon-Modus rollt **nicht automatisch zurueck**
bei einem Welle-Fail.  Rollback ist Operator-Hand-Decision gemaess
ADR-0058 §Nachtrag.  Die failende Welle bleibt im Rust-State; der
Operator muss explizit `--welle N --action rollback` aufrufen.

### §2.3 Dry-Run

`--dry-run` deaktiviert die SSH-Dispatch komplett.  Jede Operation
wird in Log-Form ausgegeben, ohne dass eine reale Verbindung zur
Pilot-VM aufgebaut wird.  CI-friendly; auch fuer Welle-Marathon-
Probelaeufe ohne Live-VM-Last.

```bash
scripts/phase-3c/live-vm-cutover-drill.sh \
    --welle 3 --action cutover --dry-run --skip-gate
```

---

## §3 Cross-Welle-Coordination — Sequence-Gates

Pflicht-Reihenfolge gemaess ADR-0066:

```
Welle-1 → Welle-2 → Welle-3 → (Welle-4 || Welle-5) → (Welle-6 || Welle-7)
```

Die Drill-Skript-Sequence-Gate-Tabelle (siehe `welle_gate_parents`
im Skript):

| Welle | Parents (Sign-Off-Pflicht) |
|---|---|
| 1 | (root, keine Parents) |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 1, 2, 3 |
| 5 | 1, 2, 3 (parallel zu 4) |
| 6 | 1, 2, 3, 4, 5 |
| 7 | 1, 2, 3, 4, 5 (parallel zu 6) |

Wird Welle-N ohne alle Parent-Sign-Offs aufgerufen, schlaegt der
Drill mit Exit-Code 3 fehl und logt die fehlenden Parents.  Das
ist die strukturelle Absicherung gegen Operator-Out-of-Order-
Cutover-Versuche.

**Replay-Override:** `--skip-gate` deaktiviert die Sequence-Gate-
Pruefung explizit.  Verwendung nur fuer:

- Hermetic-Tests (siehe `tests/scripts/test_live_vm_cutover_drill.py`)
- Operator-Hand Rollback-Drill, wenn Welle-N rolled back werden muss
  und die Parent-Sign-Offs eingefroren waren.

---

## §4 Welle-Matrix — Per-Welle Parameter

Die Matrix lebt im Skript unter `WELLE_MATRIX` (TAB-separierte
Source-of-Truth-Tabelle).  Hier zur Doku gespiegelt:

| Welle | Component | Env-Vars | Wert | Overlay-File |
|---|---|---|---|---|
| 1 | v907_verify | `WAKIR_V907_VERIFY_BACKEND` | rust | welle-1-v907-verify-rust.conf |
| 2 | svid_workload_identity | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` | rust | welle-2-svid-workload-identity-rust.conf |
| 3 | bridge_audit_writer | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`, `WAKIR_ANCHOR_EMITTER_BACKEND` | rust | welle-3-bridge-audit-writer-rust.conf |
| 4 | state_backing | `WAKIR_STATE_BACKING_BACKEND` | rust_inmemory | welle-4-state-backing-rust.conf |
| 5 | lifecycle_state_machine | `WAKIR_FSM_BACKEND` | rust | welle-5-lifecycle-state-machine-rust.conf |
| 6 | subscribe_loop | `WAKIR_SUBSCRIBE_LOOP_BACKEND` | rust | welle-6-subscribe-loop-rust.conf |
| 7 | recovery_workflow | `WAKIR_RECOVERY_BACKEND` | rust | welle-7-recovery-workflow-rust.conf |

Besonderheiten:

- **Welle-3** hat zwei Env-Vars (Writer + Resolver) — beide werden
  in eine Overlay-File geschrieben (zwei `Environment="..."`-Zeilen
  im `[Service]`-Block).
- **Welle-4** ist die einzige Welle die einen Nicht-`rust`-Wert
  verwendet (`rust_inmemory`).  Der Boot-Audit-Wait-Loop sucht
  entsprechend nach `backend=rust_inmemory`.

---

## §5 AR-Hand-Stop-Marker

Ein Welle-Cutover wird durch den Drill **nicht** abgeschlossen.  Das
Skript erledigt §3.3 + §3.4 + §3.5 (Overlay schreiben, daemon-
reload, restart, Boot-Audit-Wait-Loop ≥5 BackendDecision-Records).
Die nachfolgenden Steps bleiben Operator-Hand-Verantwortung:

- **§4 Soak-Window** (15min): Latency-Histogramm, Cross-Lang-Hash-
  Parity-Probe, Bridge-Audit-Writer-Error-Count.  Mira-Hand-
  Decision-Point fuer §5 Rollback-Trigger.
- **§7 Sign-Off**: Henrik-Audit-Trail mit PRE/TEL/POST-Evidenz-
  Pfaden.  AR-Approval-Tag wird durch AR (Fred) post-Sign-Off
  gesetzt.

**Hard-Stop-Marker fuer den Drill:**

1. Boot-Audit-Wait-Loop liefert weniger als `WAKIR_BOOT_AUDIT_MIN_HITS`
   Hits innerhalb `WAKIR_BOOT_AUDIT_TIMEOUT_SEC`.  Default
   5 Hits / 30 Sekunden.
2. SSH-Operation exit-codet nicht-Null (mit Ausnahme der
   read-only-Snapshot-Steps die mit `;true` toleriert werden).
3. Sequence-Gate-Violation: Parent-Sign-Off fehlt oder ist nicht
   `green` / `green-with-yellow-notes`.

Bei jedem Hard-Stop: Drill exit-codet 2 (red) oder 3 (precond) und
Operator entscheidet ueber Rollback gemaess Welle-Runbook §5
Rollback-Trigger.

---

## §6 Hermetic-Test-Coverage

`tests/scripts/test_live_vm_cutover_drill.py` enthaelt 15 hermetic
Tests (Auftrag-Tag-40 Minimum: 12).  Alle Tests stubben `ssh` ueber
`$WAKIR_SSH_BIN` und `date` ueber `$WAKIR_DATE_BIN`, so dass keine
reale SSH-Verbindung und kein realer Wall-Clock-Read passiert.

Coverage-Slice:

- CLI-Parsing & Pre-Condition-Gates (5 Tests)
- Per-Welle-Matrix-Rendering inkl. Welle-3-Dual-Env und Welle-4-
  `rust_inmemory` (3 Tests)
- Cutover/Rollback/Post-Verify-Pfade (3 Tests)
- Full-Marathon-Sequence + Sign-Off-Marker-Erzeugung (1 Test)
- Sequence-Gate-Enforcement (2 Tests)
- SSH-Key-Pre-Condition (1 Test)

Run:

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
python3 -m pytest tests/scripts/test_live_vm_cutover_drill.py -v
```

Erwartung: 15 passed in <5s.

---

## §7 Konfigurations-Variablen (Env-Override-Surface)

| Variable | Default | Zweck |
|---|---|---|
| `WAKIR_PILOT_HOST` | `192.168.178.116` | Pilot-VM IP / Hostname |
| `WAKIR_PILOT_USER` | `root` | SSH-User auf Pilot-VM |
| `WAKIR_PILOT_SSH_KEY` | `~/.ssh/wakir-pilot-vm-diagnose` | SSH-Key Pfad |
| `WAKIR_SSH_BIN` | `ssh` | SSH-Binary (Test-Stub via Override) |
| `WAKIR_DATE_BIN` | `date` | Date-Binary (Test-Stub via Override) |
| `WAKIR_DRILL_LOG_DIR` | `/tmp/wakir-cutover-drill` | Log-Datei-Ziel |
| `WAKIR_DRILL_SNAPSHOT_DIR` | `/var/lib/wakir/cutover-drill` | Pre-Snapshot-Ziel (Pilot-VM) |
| `WAKIR_BOOT_AUDIT_TIMEOUT_SEC` | `30` | Wait-Loop-Timeout |
| `WAKIR_BOOT_AUDIT_MIN_HITS` | `5` | Wait-Loop-Schwelle |

---

## §8 Beispiel — KW-22 Welle-1-Cutover

Konkret-Run am 2026-05-25 (Welle-1, v907_verify):

```bash
# Mira-Box: SSH-Key verifizieren
ls -la ~/.ssh/wakir-pilot-vm-diagnose

# Drill aktivieren (gegen reale Pilot-VM)
cd /var/home/fred/AI-Corp/wakir-runtime
./scripts/phase-3c/live-vm-cutover-drill.sh --welle 1 --action pre
./scripts/phase-3c/live-vm-cutover-drill.sh --welle 1 --action cutover
# (Operator-Hand: 15-min Soak-Window mit Welle-Runbook §4)
./scripts/phase-3c/live-vm-cutover-drill.sh --welle 1 --action post

# Bei green-Verdict: Sign-Off-Marker setzen (manuell oder via Marathon).
echo "welle=1
verdict=green
timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > /tmp/wakir-cutover-drill/signoff/welle-1.signoff
```

Nach gruen-Sign-Off ist Welle-2 (KW-23 / 2026-06-08) freigeschaltet.

---

— Kai Hoffmann (DevOps), Sprint-Tag-40, 2026-05-18.
