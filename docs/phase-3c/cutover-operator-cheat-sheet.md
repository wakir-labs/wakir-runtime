---
title: "Phase-3c Cutover-Operator-Cheat-Sheet"
owner: "Tomás Reinhart (Dev-Engineering, Tag-54 refresh)"
audit: "Henrik Voss (Internal Audit)"
adr: "0065, 0066, 0058, 0060, 0068"
status: "ready-for-ar-pre-sichtung"
sprint_tag: 54
sprint_tag_baseline: 43
purpose: "compact quick-reference for cutover-day operator (print/side-by-side)"
target_lines: 600
intended_render: "1-page-PDF (landscape, fontsize ~9pt) or 2-screen side-by-side"
welle_count: 7
phase_window_start: "2026-05-25"
phase_window_end: "2026-06-29"
phase_marathon_close: "Welle-7-Sign-Off-Green sets phase_3c_complete=true"
engine_anchor: "persona-engine-0.5.2-final-pre-cutover (PR #336)"
spec_anchor: "wakir-wirelang v0.4.3 pre-cutover-freeze (PR #338)"
sanity_gate_workflow: "pre-cutover-final-sanity-gate.yml (PR #339)"
cascade_live_test_workflow: "ar-hand-stop-cascade-live-test.yml (PR #335)"
marathon_cli: "scripts/phase-3c/marathon-coordination-cli.py (PR #276)"
migration_helper: "scripts/persona-engine/migrate-0-5-1-to-0-5-2.sh (PR #343)"
refresh_log: "Tag-54 refresh by Tomás — Tag-43 baseline (Kai PR #281); folds in Tag-44..53 substrates"
---

# Phase-3c Cutover-Operator-Cheat-Sheet

Operator-Quick-Reference fuer **Phase-3c-Cutover-Marathon** (7
Wellen, KW-24..27). Voll-Runbooks pro Welle in
`docs/phase-3c/welle-{1..7}-*-runbook.md` (Pflicht-Lesen vor
Cutover-Tag); dies hier ist Tasten-Referenz, kein Ersatz.

**Mira-Hand-SSH-Authority** (ADR-0058 §Nachtrag) fuer alle Wellen.
Pilot-VM: `root@192.168.178.116`. Banner: `wakir-pilot — FCOS — Phase-3b live`.

**Tag-54-Refresh-Anker** (gegen Tag-43 baseline):

- Engine **0.5.2-final-pre-cutover** (PR #336, Tag-52); rotation via
  `migrate-0-5-1-to-0-5-2.sh` (PR #343, Tag-53).
- Spec **wakir-wirelang v0.4.3-freeze** (PR #338, strict-superset / v0.4.2 PR #320).
- **Pre-Cutover-Final-Sanity-Gate** (PR #339) Mo 05:00 UTC + Tag-41
  Sanity-Probe 06:00 UTC -> Auto-Scheduler 07:00 (READY/CAUTION/BLOCK).
- **AR-Hand-Stop-Cascade-Live-Test** (PR #335): E2E Marker->Detect->
  Cascade->Cancel->Verdict.
- **Marathon-Coordination-CLI** (PR #276): one-stop Operator-CLI.

---

## §A — Cross-Welle-Coordination-Mini-Tabelle

| KW | Cutover-Tag | Wellen | Modus | Sequenz-Constraint |
|---|---|---|---|---|
| 24 | 2026-05-25 (Mo) | W1 (v907_verify) + W2 (svid_workload_identity) | parallel | unabhaengig |
| 25 | 2026-06-15 (Mo) | W3 (bridge_audit_writer + anchor_emitter) | solo | Henrik-Caution; post W1+2-Sign-Off-Green |
| 26 | 2026-06-22 (Mo) | W4 (state_backing) + W5 (lifecycle_state_machine) | parallel +Sequenz | W5-§3.1 post W4-§3.6 PRE_HASH==POST_HASH |
| 27 | 2026-06-29 (Mo) | W6 (subscribe_loop) + W7 (recovery_workflow) | parallel +Sequenz | W7-§3 post W6-§3.6 Resume-Verify |

**Hairpin-Rollback-Window:** Mi 09:00-13:00 CEST nach Cutover-Montag.
**Sign-Off-Lock:** Welle-N+1 startet nicht ohne Welle-N Sign-Off `green | green-with-yellow-notes`; bei `yellow_henrik_hand_approval` -> Henrik-Hand-Tag.
**Marathon-Ende:** ~2026-06-30 (Welle-7-Sign-Off + Henrik-Hand-Tag).

**Tag-54 Pre-Cutover-Day-Check** (KW-24 Mo 05:00..07:00 UTC):

```bash
gh run list --workflow=phase-3c-pre-cutover-sanity.yml --limit 1 --json conclusion       # Tag-41, 06:00 UTC
gh run list --workflow=pre-cutover-final-sanity-gate.yml --limit 1 --json conclusion     # PR #339, 05:00 UTC
gh run list --workflow=phase-3-cutover-day-auto-scheduler.yml --limit 1 --json conclusion # 07:00 UTC
# Expect: all three `success` AND marathon_readiness=READY before Cutover-Start.
```

---

## §B — Welle-1: v907_verify (KW-24, 2026-05-25)

**Identitaet:** Welle-1, `v907_verify`, KW-24, Risiko: LOW (Lesepfad, Resolver-Default-Switch).

### Pre-Conditions (max 5)

- [ ] Gate-1 Cosign-Policy-Signing-Inventar — green
- [ ] Gate-2 Quadlet-Inventar — green (15-Binary, Tag-48 PR #313)
- [ ] Gate-3 Rust-Backend-Switch-Resolver wired — green
- [ ] Welle-1-Wednesday-Validation-Run (2026-05-20) — green
- [ ] Pilot-VM SSH erreichbar + Banner-Match; Engine == 0.5.2-final

### Cutover-Step (copy-paste-ready)

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-1 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-1-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_V907_VERIFY_BACKEND=rust"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-1-v907-verify-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-1-cutover.log
```

### Post-Verify (max 3 Asserts)

1. `journalctl -u wakir-persona-engine.service --since "${TS_RESTART}" | grep -c "BackendDecision.*v907_verify.*backend=rust"` >= 5 (innerhalb 30s)
2. `backend-decision-aggregator.py --component v907_verify --window 15m --target-backend rust --min-rust-share 0.99` Exit 0
3. `cross-lang-hash-parity-probe.py --component v907_verify --samples 5` Exit 0

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-1-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-1-v907-verify-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*v907_verify.*backend=python" | awk '$1>=5'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-1-cutover.log
```

### Phone-a-Friend

**Reza** (Backend-Switch-Resolver) bei BackendDecision-Drift;
**Tomás** (Welle-1+2 Parallel-Coordination) bei Cross-Welle-Anomalie.

**Voll-Runbook:** [welle-1-v907-verify-runbook.md](./welle-1-v907-verify-runbook.md)

---

## §C — Welle-2: svid_workload_identity (KW-24, 2026-05-25)

**Identitaet:** Welle-2, `svid_workload_identity`, KW-24, Risiko: LOW (SPIRE-Identitaets-Pfad).

### Pre-Conditions (max 5)

- [ ] Welle-1-Pre-Conditions analog — green
- [ ] Welle-2-Wednesday-Validation-Run (2026-05-20) — green
- [ ] SPIRE-Agent auf Pilot-VM erreichbar
- [ ] SVID-JWT-Issuer-Cache populiert (siehe §3.2-Pre-Snapshot)
- [ ] Welle-1-Pre-Flight-Smoke green (parallel-Coordination)

### Cutover-Step

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-2 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-2-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-2-svid-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-2-cutover.log
```

### Post-Verify

1. >= 5 `BackendDecision.*svid_workload_identity.*backend=rust` in 30s
2. `backend-decision-aggregator.py --component svid_workload_identity --window 15m --target-backend rust --min-rust-share 0.99` Exit 0
3. SVID-JWT-Token-Issue-Latency P95 < 250ms (`welle-2-svid-workload-identity-cutover-smoke.sh`)

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-2-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-2-svid-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*svid_workload_identity.*backend=python" | awk '$1>=5'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-2-cutover.log
```

### Phone-a-Friend

**Reza** (SPIRE-Workload-Identity-Spec, Zone-A);
**Kai** (SPIRE-Server-Operator).

**Voll-Runbook:** [welle-2-svid-workload-identity-runbook.md](./welle-2-svid-workload-identity-runbook.md)

---

## §D — Welle-3: bridge_audit_writer + anchor_emitter (KW-25, 2026-06-15)

**Identitaet:** Welle-3, `bridge_audit_writer` (+Resolver-Alias `anchor_emitter`), KW-25 **solo**, Risiko: **HIGH (Henrik-Caution)** — Audit-Trail + OTS-Anchor.

### Pre-Conditions (max 5)

- [ ] Bridge-Audit-Konsistenz-Oracle (Cross-Modul-Stress-Aggregator) green
- [ ] Welle-3-Wednesday-Validation-Run (2026-06-10) green + `henrik_caution_applied=true`
- [ ] Welle-1+2-Sign-Off-Verdict `green` ODER `green-with-yellow-notes`
- [ ] Cosign-Policy enthaelt `bridge-audit-writer` als 9. Binary; Wire-In Tag-48 PR #313
- [ ] OTS-Anchor-Pipeline-Health green (Tomás-Cross-Review-Zone-C)

### Cutover-Step

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-3 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-3-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust"\nEnvironment="WAKIR_ANCHOR_EMITTER_BACKEND=rust"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-3-bridge-audit-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-3-cutover.log
```

### Post-Verify

1. >= 5 `BackendDecision.*(bridge_audit_writer|anchor_emitter).*backend=rust` in 30s
2. `welle-3-bridge-audit-writer-cutover-smoke.sh` Exit 0 (Cross-Modul-Stress-Aggregator-Replay)
3. Bridge-Audit-Roundtrip-E2E gegen Tag-N-Baseline = Byte-Identitaet (Henrik-Acceptance-Oracle)

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-3-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-3-bridge-audit-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*(bridge_audit_writer|anchor_emitter).*backend=python" | awk '$1>=10'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-3-cutover.log
```

### Phone-a-Friend

**Henrik** (Audit-Trail-Owner) — KRITISCH bei Audit-Stream-Diff;
**Tomás** (OTS-Anchoring + Cross-Modul-Stress-Aggregator);
**Reza** (BackendDecision-Schema).

**Voll-Runbook:** [welle-3-bridge-audit-writer-runbook.md](./welle-3-bridge-audit-writer-runbook.md)

---

## §E — Welle-4: state_backing (KW-26, 2026-06-22)

**Identitaet:** Welle-4, `state_backing`, KW-26, Risiko: MEDIUM (In-Memory-State; parallel zu Welle-5). Cutover-Wert: `rust_inmemory`.

### Pre-Conditions (max 5)

- [ ] Welle-3-Sign-Off-Verdict `green` ODER `green-with-yellow-notes`
- [ ] Welle-4-Wednesday-Validation-Run (2026-06-17) green
- [ ] Cross-Modul-Stress-Test (PR #178+) green vor Cutover-Start
- [ ] PRE_HASH state-snapshot fixiert (siehe §3.2 Voll-Runbook)
- [ ] Welle-5-Coordination-Block ack (Welle-5-§3 wartet auf §3.6)

### Cutover-Step

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-4 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-4-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_STATE_BACKING_BACKEND=rust_inmemory"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-4-state-backing-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-4-cutover.log
```

### Post-Verify

1. >= 5 `BackendDecision.*state_backing.*backend=rust_inmemory` in 30s
2. POST_HASH state-snapshot == PRE_HASH (Byte-Identitaet; Welle-5-Trigger-Gate)
3. `backend-decision-aggregator.py --component state_backing --window 15m --target-backend rust_inmemory --min-rust-share 0.99` Exit 0

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-4-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-4-state-backing-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*state_backing.*backend=python" | awk '$1>=5'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-4-cutover.log
```

### Phone-a-Friend

**Tomás** (State-Backing-Owner + Welle-4+5-Coordination);
**Reza** (Cross-Modul-Stress-Aggregator-Resolver);
**Henrik** bei POST_HASH-Mismatch.

**Voll-Runbook:** [welle-4-state-backing-runbook.md](./welle-4-state-backing-runbook.md)

---

## §F — Welle-5: lifecycle_state_machine (KW-26, 2026-06-22)

**Identitaet:** Welle-5, `lifecycle_state_machine`, KW-26, Risiko: MEDIUM-HIGH (FSM-Phantom-Transitions; parallel zu Welle-4 **mit Sequenz**).

### Pre-Conditions (max 5)

- [ ] Welle-4-§3.6 PRE_HASH == POST_HASH bestaetigt
- [ ] Welle-5-Wednesday-Validation-Run (2026-06-17) green
- [ ] FSM-State-Persistence-Pre-Snapshot geschrieben (Python-FSM-Backend)
- [ ] Welle-3-Sign-Off-Verdict bekannt
- [ ] Transition-Counter-Baseline-Pin (cross-lang FSM-Hash-Parity)

### Cutover-Step

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-5 Cutover-Start (post Welle-4 §3.6): ${TS_PRE}" | tee -a /var/log/wakir/welle-5-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_FSM_BACKEND=rust"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-5-fsm-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-5-cutover.log
```

### Post-Verify

1. >= 5 `BackendDecision.*lifecycle_state_machine.*backend=rust` in 30s
2. FSM-Transition-Integrity-Validation green (no phantom-transitions; Transition-Counter delta matches Python-Baseline)
3. `welle-5-lifecycle-state-machine-cutover-smoke.sh` Exit 0

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-5-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-5-fsm-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*lifecycle_state_machine.*backend=python" | awk '$1>=5'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-5-cutover.log
```

### Phone-a-Friend

**Tomás** (FSM-Owner + Welle-4+5-Sequenz-Lead);
**Selin** (Welle-5-Cutover-Smoke-Test);
**Henrik** bei Phantom-Transition-Verdacht.

**Voll-Runbook:** [welle-5-lifecycle-state-machine-runbook.md](./welle-5-lifecycle-state-machine-runbook.md)

---

## §G — Welle-6: subscribe_loop (KW-27, 2026-06-29)

**Identitaet:** Welle-6, `subscribe_loop`, KW-27 (Doppel-Welle 6+7), Risiko: MEDIUM (NATS-Subscribe-Drain-Coupling).

### Pre-Conditions (max 5)

- [ ] Welle-4+5-Sign-Off-Verdict `green` (beide!)
- [ ] Welle-6-Wednesday-Validation-Run (2026-06-24) green
- [ ] NATS-JetStream-Backup vorhanden (R-A4 mitigation)
- [ ] Subscribe-Loop-Drain-Pin-Baseline gesetzt
- [ ] Welle-7-Coordination-Stub ack (Welle-7-§3 wartet auf §3.6)

### Cutover-Step

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-6 Cutover-Start: ${TS_PRE}" | tee -a /var/log/wakir/welle-6-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_SUBSCRIBE_LOOP_BACKEND=rust"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-6-subscribe-loop-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-6-cutover.log
```

### Post-Verify

1. >= 5 `BackendDecision.*subscribe_loop.*backend=rust` in 30s
2. NATS-Consumer-Lag P95 < 50ms ueber 15-min-Soak-Window
3. Subscribe-Loop-Resume-Verify green (Welle-7-Trigger-Gate)

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-6-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-6-subscribe-loop-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*subscribe_loop.*backend=python" | awk '$1>=5'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-6-cutover.log
```

### Phone-a-Friend

**Reza** (NATS-Wirelang-Schema, Zone-B);
**Kai** (NATS-Operations);
**Noa** (Subscribe-Loop-Drain-Observability).

**Voll-Runbook:** [welle-6-subscribe-loop-runbook.md](./welle-6-subscribe-loop-runbook.md)

---

## §H — Welle-7: recovery_workflow (KW-27, 2026-06-29) — MARATHON-CLOSURE

**Identitaet:** Welle-7, `recovery_workflow`, KW-27 (Doppel-Welle 6+7), Risiko: MEDIUM-HIGH (Recovery-Drill + Marathon-Closure). **Welle-7-Sign-Off-Green setzt `phase_3c_complete: true`.**

### Pre-Conditions (max 5)

- [ ] Welle-6-§3.6 Subscribe-Loop-Resume-Verify green
- [ ] Welle-7-Wednesday-Validation-Run (2026-06-24) green
- [ ] R1..R4-Drill-Latency-Baseline Pin (recovery-drill marathon-closure oracle)
- [ ] Welle-4+5+6 alle Sign-Off `green` (Marathon-Closure-Pre-Gate)
- [ ] Henrik-Tag-39-Audit-Spec `phase-3-cutover-schluss-audit-spec.md` gelesen

### Cutover-Step

```bash
ssh root@192.168.178.116
TS_PRE=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Welle-7 Cutover-Start (post Welle-6 §3.6): ${TS_PRE}" | tee -a /var/log/wakir/welle-7-cutover.log
install -d -m 0755 /etc/systemd/system/wakir-persona-engine.service.d
printf '[Service]\nEnvironment="WAKIR_RECOVERY_BACKEND=rust"\n' \
  > /etc/systemd/system/wakir-persona-engine.service.d/welle-7-recovery-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
TS_RESTART=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Restart-Issued: ${TS_RESTART}" | tee -a /var/log/wakir/welle-7-cutover.log
```

### Post-Verify

1. >= 5 `BackendDecision.*recovery_workflow.*backend=rust` in 30s
2. R1..R4-Drill-Latency-Histogramm P95 innerhalb Baseline-Envelope (no recovery-regression)
3. `welle-7-recovery-workflow-cutover-smoke.sh` Exit 0 (Marathon-Closure-Acceptance-Oracle)

### Rollback-Step

```bash
TS_RB=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "Rollback-Start: ${TS_RB}" | tee -a /var/log/wakir/welle-7-cutover.log
rm -f /etc/systemd/system/wakir-persona-engine.service.d/welle-7-recovery-rust.conf
systemctl daemon-reload && systemctl restart wakir-persona-engine.service
journalctl -u wakir-persona-engine.service --since "-1 min" | grep -c "BackendDecision.*recovery_workflow.*backend=python" | awk '$1>=5'
echo "Rollback-Done: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a /var/log/wakir/welle-7-cutover.log
```

### Phone-a-Friend

**Tomás** (Recovery-Workflow + Phase-3-Marathon-Closure-Lead);
**Henrik** (Marathon-Closure-Audit + Sign-Off-Trail);
**Amara** (Phase-3-Final-Regression).

**Voll-Runbook:** [welle-7-recovery-workflow-runbook.md](./welle-7-recovery-workflow-runbook.md)

---

## §I — AR-Hand-Stop-Marker — Operator-Trigger-Bedingungen

Operator setzt **AR-Hand-Stop-Marker** und eskaliert sofort (Mira-0
-> Priya-1 -> AR-4). **Cutover-Sequenz haltet bis Sign-Off.**

1. **Cross-Modul-Drift > 0** im BackendDecision-Stream (python trotz WAKIR_*_BACKEND=rust).
2. **Self-Reference-Trap-Fire** (Cross-Lang-Hash-Parity-Probe -> Python-Hash mit Rust-Backend).
3. **OTS-Anchor-Emission-Stop** im Welle-3-Soak — Bitcoin-Trail-Bruch.
4. **POST_HASH != PRE_HASH** in Welle-4 — State-Backing-Read-Failure.
5. **FSM-Phantom-Transition** in Welle-5 — Transition-Counter-Delta ohne Event.
6. **NATS-Consumer-Lag P95 > 500ms** in Welle-6 (10x baseline).
7. **Pre-Cutover-Final-Sanity-Gate** (PR #339) `marathon_readiness=BLOCK` am Cutover-Morgen.
8. **AR-Hand-Stop-Cascade-Live-Test** (PR #335) faellt durch beim Mo-night Run.
9. **Quadlet-Restart-Failure** mit Engine-Init-Loop (Container-Identity-Drift / Image-Hash-Mismatch nach Restart).
10. **Cosign-Verify-Fail** im Pre-Cutover-15-Binary-Live-Boot-Test (Supply-Chain-Triad-Bruch).

**Marker-Setzen** (Tag-47 PR #304):

```bash
python scripts/ci/ar-hand-stop-marker-set.py --welle N --trigger "<bedingung>" --operator mira --commit --push
# Listener (PR #304 + Cascade-Live-Test PR #335) reagiert <=2 min: Detect -> Cascade -> Cancel -> Verdict.
```

Cutover-Sequenz haltet bis `state/ar-hand-stop-sign-off-welle-N.json` im Repo.

---

## §J — Phase-3-COMPLETE-Marker — Finale Setzung

Marathon-Closure ueber Tomás-Workflows (PR #258 + PR #266) im
`wakir-runtime`-Repo.

**`phase-3-complete-marker.yml`** (PR #258) verifiziert konjunktiv:

- **AC-1:** 7 `state/welle-{1..7}-sign-off.json` (green | yellow_henrik_hand_approval).
- **AC-2:** Aggregate-consistency — alle Welle-Validation-Workflows `success` auf `main`.
- **AC-3:** Phase-3a (15/15) + Phase-3b (9/9) + Phase-3c (7/7) Closure-Attestation.
- **AC-4:** `state/henrik-phase-3-complete-ratification.json` (R-A1..R-A6, ratified).
- **AC-5:** `state/ar-hand-phase-3-complete-stamp.json` (ar_hand_ratification:true).

Nur bei ALL FIVE pass: emittiert `state/phase-3-complete-marker.json`.
Trigger: `workflow_dispatch` (Mira-Hand) ODER `cron "0 12 * * 1"`.
**`phase-3c-marathon-tracker-gate.yml`** (PR #266): Required-Status-Check.

**Operator-Setzung (Post-Welle-7-Sign-Off-Green):**

```bash
# 0. Engine-Rotation (Tag-53 PR #343), falls noch nicht passiert:
scripts/persona-engine/migrate-0-5-1-to-0-5-2.sh pre-check && \
  scripts/persona-engine/migrate-0-5-1-to-0-5-2.sh rotate --apply && \
  scripts/persona-engine/migrate-0-5-1-to-0-5-2.sh post-verify
# 1..3. Sign-Off-Files: welle-7-sign-off.json, henrik-phase-3-complete-ratification.json, ar-hand-phase-3-complete-stamp.json
# 4. Marker:
gh workflow run phase-3-complete-marker.yml --repo wakir-labs/wakir-runtime --ref main
# Emission: state/phase-3-complete-marker.json
```

**IIA-1130:** Internal-Audit (AC-4); AR-Hand final (AC-5).
Marker-Setzung mechanisch-exekutiv, nie bewertend.

---

## §K — Cheat-Sheet-PDF-Render — Operator-Tag-Druck

Aus Markdown 1-Seite-PDF (Landscape, ~9pt) fuer Operator-Tisch.

```bash
pandoc docs/phase-3c/cutover-operator-cheat-sheet.md \
  -o /tmp/cutover-cheat-sheet.pdf --pdf-engine=xelatex \
  -V geometry:landscape -V geometry:margin=8mm -V fontsize=9pt
```

Alt: Browser-Print (Strg+P, Landscape A4, Margins=Minimum, Scale=80%).
Print: A4-Landscape, beidseitig, laminiert.

---

## §L — Anker-Tabelle (alle Welle-Runbooks + Tag-54 Refresh-Anker)

- W1: [welle-1-v907-verify-runbook.md](./welle-1-v907-verify-runbook.md)
- W2: [welle-2-svid-workload-identity-runbook.md](./welle-2-svid-workload-identity-runbook.md)
- W3: [welle-3-bridge-audit-writer-runbook.md](./welle-3-bridge-audit-writer-runbook.md)
- W4: [welle-4-state-backing-runbook.md](./welle-4-state-backing-runbook.md)
- W5: [welle-5-lifecycle-state-machine-runbook.md](./welle-5-lifecycle-state-machine-runbook.md)
- W6: [welle-6-subscribe-loop-runbook.md](./welle-6-subscribe-loop-runbook.md)
- W7: [welle-7-recovery-workflow-runbook.md](./welle-7-recovery-workflow-runbook.md)

Cross-Welle: cross-welle-generalprobe.md, live-vm-cutover-drill.md,
marathon-aggregat-tracker.md, marathon-coordination-cli.md.

**Tag-54 Refresh-Anker:**
- Engine 0.5.2-final (PR #336 Selin) + rotate `migrate-0-5-1-to-0-5-2.sh` (PR #343).
- Spec v0.4.3-freeze (PR #338 Reza).
- `pre-cutover-final-sanity-gate.yml` (PR #339, Tag-53).
- `ar-hand-stop-cascade-live-test.yml` (PR #335, Tag-52).
- `marathon-coordination-cli.py` (PR #276, Tag-43).
- `phase-3-complete-marker.yml` (PR #258) + Tracker-Gate (PR #266).

ADRs: 0065 (Cutover-Plan), 0066 (Option-A+ KW-24..27), 0058 (SSH-
Hand-Nachtrag), 0060 (Live-FCOS-CI-Gate), 0068 (Status-Aggregator).

---

*Tag-54-Refresh, Tomás Reinhart. Baseline: Tag-43 Kai PR #281.
Folds in Tag-44..53 substrates. Hermetic-Tests:
`tests/phase_3c/test_cutover_cheat_sheet_structure.py`.*

— Tomás
