# Sprint-9 Tag-5 — NATS-Connection-Discrepancy Resolution

**Author:** Reza Tehrani (Dev-Engineering-2)
**Date:** 2026-05-13
**Phase:** Phase-2 Sprint-9 Tag-5
**Mira-Bug-Bilanz reference:** `agents-workspaces/mira/outbox/2026-05-13-pilot-bringup-bug-bilanz.md`
**Status:** delivered

## Context

The Pilot-VM live-bring-up on 2026-05-13 ~11:00–12:45 CEST
exposed a smoke-test result that oscillated between **2/6** and
**4/6 PASS** across back-to-back invocations of
`bin/proxmox-bringup-smoke`. The substrate was internally
consistent (NATS running, buckets initialised, SPIRE substrate
unstable but reachable in windows), but the smoke kept flipping
between two summary lines.

Mira's bug bilanz called out four candidate race conditions
(reproduced verbatim from the Mira-side memo):

1. **JWT-Auth-Timing-Race** — NATS-connect issued before the
   SPIRE-Agent has produced a JWT-SVID.
2. **Trust-Bundle-Rotation-Race** — NATS-server rejects connect
   because the rotated trust bundle has not yet landed
   server-side.
3. **SPIFFE-Workload-API-Socket-Permission-Drift** — agent
   produces SVIDs but the socket-file permissions block the
   wirelang-side reader.
4. **NATS-KV-Bucket-Init-Race** — buckets created but
   JetStream-stream registration not yet finalised when the
   smoke probes `nats kv ls`.

## Root-cause diagnosis

The 2/6 ↔ 4/6 split maps to **two flipping checks**:

- **Check 3 (`spire-server-healthy`)** — flips because the
  SPIRE-server gets restart-cycled by the agent-crash-loop
  (Kai-Bug-7); the smoke probes during the brief steady window
  and sees PASS, or during a restart and sees FAIL. This is
  primarily a **hypothesis 1+2 symptom** (the agent race chains
  back to a server-restart chain). Kai owns the primary Bug-7
  resolution (agent stability); the retry-layer in this PR is
  defence-in-depth so the smoke stops oscillating once Kai's
  fix lands.

- **Check 6 (`marker-stack-bucket-present`)** — flips because
  the bucket-init one-shot completed but the JetStream-stream
  registration that backs `nats kv ls` finalises **asynchronously**
  (server-side housekeeping). This is a pure **hypothesis 4**
  manifestation; no SPIRE involvement.

Hypothesis 3 (socket-permission-drift) is **not** the dominant
factor: the bug bilanz reports the agent is crash-loop-inactive,
not socket-permission-failing — when the agent is dead the
socket does not exist at all (clean FAIL), no race window.

Hypothesis 1 (JWT-cache-cold) **does** apply to wirelang-side
consumers (the bucket-init provisioner is currently the highest-
value one). The retry layer wires a `JwtCacheReadyView` Protocol
so a SPIRE-Workload-API-backed consumer can poll for cache-hot
before each connect attempt.

## Fix surface

Two complementary substrates, both hermetic-testable, both
BSL 1.1 per ADR-0059:

### Substrate A — Wirelang `connect_retry` module

`wirelang/adapters/real_nats_adapter/connect_retry.py` exposes:

- `connect_with_retry(connect_callable, ...)` — drives any
  zero-arg async connect coroutine through a structured retry
  loop with exponential-backoff + jitter, returning a
  `NatsConnectAttemptLog` that records per-attempt outcomes and
  reason codes (`tcp-unreachable`, `nats-py-connect-fail`,
  `auth-rejected`, `jwt-cache-cold`, `unknown-transient`,
  `success`).
- `JwtCacheReadyView` Protocol — read-only "is the JWT-SVID
  cache hot?" surface; a consumer wired to the SPIRE-Workload-
  API can pass an instance and the retry layer polls between
  attempts.
- `StaticReadyView` shim — for non-SPIFFE consumers that want
  a no-op cache surface.
- `classify_failure(exc)` — cooperative classifier that maps
  adapter exceptions onto reason codes without importing the
  `nats_jwt_callback_skizze` module (it matches the class name
  to stay decoupled).

The module ships with a 19-test hermetic suite
(`wirelang/tests/test_nats_connect_race_resilience.py`) that
reproduces all three applicable hypotheses with deterministic
mocks:

| Hypothesis | Tests |
|---|---|
| 1 (JWT-cache cold) | `test_hypothesis_1_*` (2 cases) |
| 2 (auth rotation) | `test_hypothesis_2_*` (2 cases) |
| 4 (TCP / stream init) | `test_hypothesis_4_*` (2 cases) |
| Mixed sequencing | `test_mixed_sequence_*` |
| Classifier | `test_classifier_*` (3 cases) |
| Jitter contract | `test_jittered_delay_*` (3 cases) |
| Log invariants | `test_attempt_log_*` (2 cases) |
| Edge cases | empty schedule, fast success, static view (4 cases) |

Total: 19 tests.

### Substrate B — Smoke-script retry wrapper

`bin/proxmox-bringup-smoke` extended with a generic
`with_retry` driver that wraps the four race-prone checks:

| Check | Race window addressed |
|---|---|
| Check 2 `nats-jetstream-reachable` | hypothesis 4 (stream-init) |
| Check 3 `spire-server-healthy`   | server-restart-loop window |
| Check 4 `spire-agent-healthy`    | agent-svid-issuance window |
| Check 6 `marker-stack-bucket-present` | hypothesis 4 (stream-registration) |

Default schedule: 5 retries + 1 initial; sleeps 0.5/1/2/4/5s;
worst-case per check ~12.5s; worst-case total smoke ~50s. The
schedule is tunable via `WAKIR_SMOKE_RETRY_MAX` and
`WAKIR_SMOKE_RETRY_BASE`; `WAKIR_SMOKE_RETRY_MAX=0` collapses
the script back to Tag-1 single-shot semantics for hermetic
tests of the legacy code path.

The retry wrapper:

- Records per-check `attempts=N` in the human log line so the
  operator sees WHICH check raced and how many tries cleared it.
- Surfaces a **reason code** in the FAIL detail (e.g.
  `race: stream-registration-pending`, `race: server-restart-loop-window`)
  so an operator can map the failure onto the bug-bilanz
  hypothesis catalog.

The wrapper ships with a 9-test hermetic suite
(`tests/orchestrator/test_proxmox_bringup_smoke_retry.py`) that
reproduces the Pilot-VM 2/6 ↔ 4/6 discrepancy with flipping
mocks and proves the retry layer resolves it (6/6 PASS), and
that disabling the retry layer (`RETRY_MAX=0`) reverts to the
bug-pattern (4/6 PASS).

## Cross-persona dependencies

- **Kai (Bug 7: SPIRE-Agent stability)** — owns the primary
  resolution. The retry layer here makes the smoke
  non-oscillating once Kai's fix lands; without Kai's fix the
  retry layer simply reports an honest `FAIL [attempts=6]`
  rather than a flipping result.
- **Tomás (CI hygiene)** — no conflict zone. The new files are
  inside `wirelang/adapters/real_nats_adapter/` and
  `tests/orchestrator/`; no overlap with Tomás's CI substrate.
- **Amara (E2E suite)** — the retry layer is the substrate
  Amara's end-to-end-live-bring-up-test-suite can build on. The
  attempt-log shape (`NatsConnectAttemptLog`) gives Amara a
  structured assertion surface for "the bring-up reached steady
  state inside N retries".

## Test bilanz

|                          | Baseline (`e5067b4`) | With fix | Delta |
|--------------------------|----------------------|----------|-------|
| `tests/` + `wirelang/tests/` | 2276 passed | **2304 passed** | **+28** |
| skipped | 51 | 51 | 0 |
| failed | 0 | 0 | 0 |

Delta: +28 hermetic tests. Distribution:

- `wirelang/tests/test_nats_connect_race_resilience.py`: +19
- `tests/orchestrator/test_proxmox_bringup_smoke_retry.py`: +9

## Sandbox boundary

All tests are hermetic per the
`feedback_sandbox_host_trennung.md` boundary:

- No real NATS connection — the wirelang module is a pure
  orchestration layer that drives any async-callable.
- No real SPIRE Workload-API — the `JwtCacheReadyView` is a
  Protocol with deterministic mock implementations.
- No real `podman`/`systemctl`/`curl` — the smoke-script tests
  inject bash mock-wrappers via the `WAKIR_SMOKE_*` env hooks.
- No real `sleep` in the smoke retry loops — tests inject
  `WAKIR_SMOKE_SLEEP=noop-sleep` so race reproduction stays
  sub-second.

Per ADR-0051 (rejected; operative Mira-Hand-Regel): `claude-dev`
has NO host podman-socket access. Live bring-up validation is
operator-hand on the Pilot-VM (post-Kai-Bug-7-fix-merge).

## Operator-Hand follow-up

After this PR + Kai-Bug-7-PR land on `wakir-runtime/main`, the
operator-hand follow-up is:

1. Take a fresh snapshot of the Pilot-VM.
2. Run `sudo bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh`
   end-to-end (no manual fixes).
3. Run `bin/proxmox-bringup-smoke --org acme --json`.

Expected outcome:

- **6/6 PASS** within ~30-60 seconds (real smoke runtime includes
  the retry sleeps; worst-case 50s + healthy-state probe time).
- Each race-tolerant check reports `attempts=1` if the substrate
  is hot from the start, or `attempts=2..6` if it caught a race
  window — both are PASS.
- The `--json` payload includes the attempts count per check (a
  future extension; this PR ships the human-log surface only).

If the smoke still reports FAIL after Kai's fix and this retry
layer, the failing check's reason code (`race: ...`) maps onto
the bug-bilanz hypothesis catalog and a focused Tag-6 spawn can
address the specific window.

— Reza
