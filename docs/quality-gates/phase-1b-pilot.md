# Quality-Gate — Phase 1b (Pilot)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Active for Sprint-Pengine-12 → Sprint-QA-Tag-15 |
| Phase | 1b — Pilot (Single-org pilot-VM with Tomás-Persona-Container live + Pre-Framework-Tomás still authoritative) |
| Source | ADR-0058 (Pilot-Persona-Migrations-Plan), feedback_live_bringup_sandbox_gap |
| Date approved | 2026-05-16 (draft pending Zone-N review) |

## 0. Phase contract

Phase 1b is the **substrate-and-pilot-spawn phase**: the wakir-runtime
stack is up on a real CoreOS Pilot-VM (NATS + SPIRE-Server +
SPIRE-Agent + persona-tomas Quadlet container running in
DOUBLE-SHADOW mode), and the Tomás-Persona-Container produces
shadow engineering-output that the bridge-audit double-sink captures
for the Doppelbetrieb-Score-CLI. Pre-Framework-Tomás still drives all
production engineering traffic; the wakir-Tomás-container is
observed-only.

Entry from Phase 1a (pre-pilot) requires every gate in this document
to be green.

## 1. Acceptance-Gates

### 1.1 Substrate green — CI-Live-VM-Acceptance-Gate exit 0

* **Gate:** `bin/proxmox-bringup-smoke --json` returns 6/6 PASS and
  `acceptance-gate.sh` returns exit 0.
* **Evidence:** `gate-verdict.json` with `verdict == "PASS"`,
  `pass_count == 6`, `fail_count == 0`, `bug_vectors == []`.
* **Owned-by:** Kai (substrate) + Tomas (acceptance-script).
* **Test-Vector:** existing `tests/infra/test_vm_e2e_acceptance_gate.py`
  G1–G11; new `tests/infra/test_pilot_phase_e2e_smoke.py`
  TV-PIL-BUGMAP-01..07.

### 1.2 Persona-Container Lifecycle green

* **Gate:** Spawning the persona-tomas Quadlet container walks the
  spec-canonical FSM path `uninstantiated → spawning → running` and
  emits at least one `engineering_output` event before SIGTERM.
* **Evidence:** persona-engine state-machine transition-records
  serialised to NATS-KV bucket `wakir-persona-state-acme-tomas`;
  bridge-audit-writer writes `engineering_output` to both sinks.
* **Owned-by:** Selin (persona-engine).
* **Test-Vector:** `tests/infra/test_pilot_phase_e2e_smoke.py`
  TV-PIL-FSM-01..06.

### 1.3 V-907 build-time-pin / runtime-attest roundtrip

* **Gate:** The pin computed at build-time against the source-tree
  axis-A file matches the pin re-computed at runtime against the
  bind-mounted `/etc/wakir/persona/<slug>.md`. Drift raises
  `PersonaHashDriftError` and the container exits with rc=2
  (EXIT_V907_HASH_DRIFT).
* **Evidence:** Container-start log shows `v907-verify ok pin=sha256:…`;
  bridge-audit `axis-a-pin` record matches the build-time pin.
* **Owned-by:** Selin (persona-engine).
* **Test-Vector:** `tests/infra/test_pilot_phase_e2e_smoke.py`
  TV-PIL-V907-01..04.

### 1.4 Bridge-Forward Pipe consumes auftraege

* **Gate:** The persona-engine container running in async-real mode
  (`WAKIR_SUBSCRIBE_ENV=dev` or higher) receives at least one
  auftrag-envelope on `wakir.<env>.agent.agent.task.assigned.tomas`
  and publishes a reply on `wakir.<env>.agent.agent.task.output.tomas`
  within 30 seconds of the publish.
* **Evidence:** NATS subject metrics show a non-zero publish-count on
  the output subject; bridge-audit `reply` record matches the
  publish.
* **Owned-by:** Selin (persona-engine subscribe-loop) + Reza (schema).
* **Test-Vector:** `tests/infra/test_pilot_phase_e2e_smoke.py`
  TV-PIL-BUG42-01..04.

### 1.5 Doppelbetrieb-Score-CLI ingests both sinks

* **Gate:** Running `wirelang doppelbetrieb-score` over the
  bridge-audit double-sink emits a four-axis score JSON with the
  spec-canonical schema, and the `verdict` field is one of
  `pass | warn | fail`.
* **Evidence:** Score-JSON output file with `schema` field set to
  the spec-canonical id and all four axes populated.
* **Owned-by:** Selin (CLI) + Reza (schema).
* **Test-Vector:** `tests/infra/test_pilot_phase_e2e_smoke.py`
  TV-PIL-DOP-01..04 + existing `tests/test_cli_doppelbetrieb_score.py`.

## 2. Test-Coverage thresholds

| Component | Coverage threshold (line) | Coverage threshold (branch) | Source |
|---|---|---|---|
| `wirelang.persona_engine.lifecycle_state_machine` | 95% | 90% | Selin |
| `wirelang.persona_engine.v907_verify` | 95% | 90% | Selin |
| `wirelang.persona_engine.nats_subscribe_loop` | 85% | 80% | Selin |
| `wirelang.cli.doppelbetrieb_score` | 90% | 85% | Selin |
| `infra/test-e2e/vm-lifecycle-harness/acceptance-gate.sh` | n/a (shell — branch via failure-path test) | every CHECK_TO_BUGS entry exercised | Kai+Amara |
| `scripts/ci-live-vm-acceptance-wrapper.sh` | n/a (shell) | every documented `--flag` exercised | Kai+Amara |

Coverage is reported per CI-run as
`coverage.xml` artefacts. Below-threshold = QA-blocker; Engineering-
persona-Owner files a follow-up unit-test PR before the
Phase-1b → Phase-2 promotion can proceed.

Coverage is a proxy-metric per `qa.md` Arbeitsstil-Anker. Tests
that exist to bump coverage without exercising a behavioural
invariant do not count toward the threshold.

## 3. SLI/SLO requirements (coordination with Noa SRE)

Phase 1b is observed-only for production traffic — the SLOs below
are **substrate-health SLOs**, not Wakir-Service-SLOs:

| SLI | Window | SLO | Owner |
|---|---|---|---|
| Persona-Container `up` (Quadlet active) | rolling 24h | ≥99.0% | Noa |
| NATS-jetstream availability (substrate) | rolling 24h | ≥99.5% | Noa |
| SPIRE-Server `healthy` | rolling 24h | ≥99.5% | Noa |
| Bridge-Forward end-to-end latency p95 (publish → reply on output subject) | rolling 1h | ≤30s | Noa |
| Subscribe-loop dropped-envelope rate (malformed + parse-error) | rolling 1h | ≤1% of publish-count | Noa |

Coordination note: I (Amara) have not yet held the Phase-1b
SLI/SLO-design session with Noa. The numbers above are proposed
defaults derived from the Sprint-10 Tag-6 substrate-spec and the
ADR-0058 Phase-2 cutover-criteria. Noa-Owned. Marked
**vorläufig** per `qa.md` Antwort-Disziplin P2 until Noa signs off.

## 4. Henrik-Audit-Punkte (Zone N)

Henrik's Audit-Sample for Phase 1b consumes:

* **A.** The `gate-verdict.json` files from the CI-Live-VM runs
  (audit-trail of substrate health over time — sampled monthly).
* **B.** The bridge-audit `axis-a-pin` records (audit-trail of V-907
  pin-drift detections — sampled per pilot-spawn).
* **C.** The Doppelbetrieb-Score JSON outputs (Migration-Playbook §5
  comparison-test-set evidence — sampled per Doppelbetrieb-week).
* **D.** This document, the test-plan
  `docs/test-plans/sprint-qa-tag-15-e2e-pilot-smoke.md`, and the
  test-suite coverage-report — for Zone-N boundary verification
  (does QA-evidence overlap with audit-evidence?).

Henrik does **not** consume:

* Raw pytest-output (this is operative QA-evidence, not
  audit-trail).
* Coverage.xml as such (Henrik samples the high-level coverage
  threshold compliance, not the file-by-file numbers).

Boundary holds: QA covers functional invariants; Audit covers
governance-compliance (ADR-0058 §"Phase 4 Cutover-Entscheidung"
criteria are met, the cutover-decision honours the four-axis acceptance
criteria, etc.).

— Amara
