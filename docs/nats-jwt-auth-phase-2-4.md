# NATS-JWT-Auth Integration — Phase-2.4 Hermetic sketch

This document describes the **Phase-2.4 NATS-JWT-Auth wire-up** between
the SPIRE-Agent Workload-API (Phase-2.2) and the NATS-JetStream
Python client (`nats-py`). It is the paired companion to:

- `docs/spire-server-phase-2-1.md` (SPIRE-Server sidecar).
- `docs/spire-agent-phase-2-2.md` (SPIRE-Agent sidecar).
- `docs/archive/evidence/decisions/spiffe-jwt-svid-identity-sketch.md` (historical design sketch).

**Hermetic-only**: the substrate adds a callback-factory module
and 20 hermetic tests. No NATS-server is started. No SPIRE-Agent is
contacted. No real `nats.connect()` is issued. Live bring-up (real
SPIRE-Agent + real NATS-server + JWT-Auth handshake) is the
Phase-2.5 Operator-Hand slot (see §6).

## 0. Box-Brief alignment

| Item | Spec | deliverable |
|---|---|---|
| Substrate-Voraussetzung 1 | `nats-py` exposes `user_jwt_cb` callback (Client-Side) | Verified `nats/aio/client.py` Z. 110, 317, 370, 1666-1668 (see §3.1) |
| Substrate-Voraussetzung 2 | P7-verified | Confirmed; this runbook §3.1 carries the line-by-line citation |
| Substrate-Voraussetzung 3 | design sketch `docs/archive/evidence/decisions/spiffe-jwt-svid-identity-sketch.md` §4.2-Punkt-7 + §6 §3 | Cross-referenced (§3.2 below) |
| sketch | NATS-JWT-Auth wire-up between SPIRE-Agent Workload-API and NATS-JetStream client | `scripts/nats_jwt_callback_skizze.py` + this runbook |
| Mock/Stub `user_jwt_cb` | Path-by-name reference to protocol engineering Mock-Adapter `MockSpiffeWorkloadApiAdapter` | §4 + `scripts/nats_jwt_callback_skizze.py` (`InMemorySvidCache` stub, NOT a wirelang import) |
| Hermetic tests | No real NATS-server, no real SPIRE-Agent | `tests/orchestrator/test_nats_jwt_auth_phase_2_4.py` (20 tests) |
| JWT-Refresh-on-Reconnect pattern | Client-Side, per Ack §4.2 corrections | §3.3 + Block-4 tests |
| Runbook | Operator-workflow + acceptance-list | This document |
| protocol engineering Cross-Reference | `MockSpiffeWorkloadApiAdapter` path-by-name, no import | §4 |
| parallel landing | If `real_spiffe_workload_api.py` lands: update F-8 sync-item | F-8 status updated in §8 |

## 1. Substrate components

| Component | Path | Owner | Tag |
|---|---|---|---|
| NATS-JWT callback factory skizze | `scripts/nats_jwt_callback_skizze.py` | infrastructure engineering | |
| `JwtSvidCacheView` Protocol surface | same file | infrastructure engineering | |
| `InMemorySvidCache` hermetic stub | same file | infrastructure engineering | |
| `make_user_jwt_cb` factory | same file | infrastructure engineering | |
| Error hierarchy (`NatsJwtCallbackError` family) | same file | infrastructure engineering | |
| Hermetic acceptance tests (20) | `tests/orchestrator/test_nats_jwt_auth_phase_2_4.py` | infrastructure engineering | |
| SPIFFE constants (re-used) | `scripts/spiffe_skizze_constants.py` | infrastructure engineering | (re-used) |

## 2. Architecture

### 2.1 Topology (Phase-2 single-node)

```
┌──────────────────────────────────────────────────────────────────┐
│ podman-compose pod (wakir-runtime Phase-2)                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐    ┌────────────────────┐    │
│  │ SPIRE-Server │◄─┤ SPIRE-Agent  │◄───┤ Persona-Container  │    │
│  │              │  │              │WL  │ - wirelang adapter │    │
│  └──────────────┘  └──────┬───────┘ A  │   (protocol track) │    │
│   trust-bundle             │ Pi│       │ - JwtSvidCache     │    │
│   |                        ▼   │       │ - WatchJWTSVIDs    │    │
│   |                  /run/spire/agent  │   stream            │    │
│   |                  -sockets/api.sock │ - JWT callback      │    │
│   |                                    │   factory            │    │
│   |                                    └─────────┬───────────┘    │
│   |                                              │ user_jwt_cb    │
│   |                                              ▼                │
│   |                                    ┌────────────────────┐    │
│   |─trust-bundle-pin────────────────►  │  NATS-JetStream    │    │
│                                        │  (JWT-auth)        │    │
│                                        └────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

Components:

- **SPIRE-Server**: issues JWT-SVIDs; trust-bundle published to NATS.
- **SPIRE-Agent**: attests workloads, exposes Workload-API UDS.
- **Wirelang-side adapter** (protocol engineering; path-by-name):
  - Holds a `JwtSvidCache` populated by a background `WatchJWTSVIDs`
    stream against the Workload-API.
  - Surface: `MockSpiffeWorkloadApiAdapter` (hermetic) + real adapter
    (protocol engineering, once landed).
- **callback factory** (this skizze): builds the zero-arg
  callable `nats-py` invokes at every CONNECT-frame build.
- **NATS-JetStream**: configured with JWT-Auth; validates incoming
  JWT against the SPIRE trust-bundle.

### 2.2 Trust boundaries

| Boundary | Owner | stance |
|---|---|---|
| SPIRE-Server config (issuer, TTL, datastore) | infrastructure engineering (DevOps-track) | unchanged from |
| SPIRE-Agent config (attestor selectors, server-DNS) | infrastructure engineering (DevOps-track) | unchanged from |
| Workload-API UDS path inside persona-container | infrastructure engineering + protocol engineering (Z-A) | path-by-name (`/run/spire/agent-sockets/api.sock`) |
| `WatchJWTSVIDs` background stream | protocol engineering (wirelang-side adapter) | path-by-name; NOT in substrate |
| `JwtSvidCache` shape + lifecycle | protocol engineering (wirelang-side adapter) | references the Protocol surface; `InMemorySvidCache` is a hermetic-test stub |
| `user_jwt_cb` callable | infrastructure engineering (factory) | factory in `scripts/nats_jwt_callback_skizze.py` |
| NATS-server JWT-Auth config | infrastructure engineering (DevOps-track) | Phase-2.5+ Operator-Hand slot |
| JWT-SVID validation against trust-bundle | NATS-server | not part of substrate |

## 3. The `user_jwt_cb` Client-Side Callback Pattern

### 3.1 Upstream invariants (P7-verified)

`nats-py` v2.x exposes JWT-auth via a **Client-Side callback**, NOT a
server-feature. Verified line-by-line:

| File | Line | Element | Substance |
|---|---|---|---|
| `nats/aio/client.py` | 110 | `JWTCallback = Callable[[], Union[bytearray, bytes]]` | typedef pins the callable shape: zero-arg, returns bytes |
| `nats/aio/client.py` | 317 | `self._user_jwt_cb: Optional[JWTCallback] = None` | field holds the callback reference |
| `nats/aio/client.py` | 370 | `user_jwt_cb: Optional[JWTCallback] = None,` | `connect()` parameter accepts the callback |
| `nats/aio/client.py` | 1666-1668 | `if self._user_jwt_cb is not None:` ... `jwt = self._user_jwt_cb()` ... `options["jwt"] = jwt.decode()` | callback is invoked **inside the CONNECT-frame builder** |

**Critical invariant** (Z-A-Ack-Slot-4 correction): the CONNECT-frame
builder runs on **every** connect — including reconnect-after-network-
glitch. Therefore the callback is **re-invoked at reconnect**, and
the wirelang-side cache state at that moment is what becomes the new
CONNECT-frame JWT. No `connection.close() + connect()` cycle by the
persona-container is needed for token refresh — `nats-py`'s internal
reconnect mechanic plus the callback closure deliver it.

**Nuance** (Z. 1661-1668 in the live source): the callback is invoked
**only** when `_auth_configured` is true AND the server sent a
`nonce` AND a `signature_cb` is configured. In SPIFFE-JWT-Auth setup
the server-side `auth_configured` flag fires under Nkey-style JWT-auth,
and a SPIFFE-aware `signature_cb` is wired alongside the
`user_jwt_cb`. Phase-2.5 Operator-Hand bring-up (live wire-up) is the
verification point for this branch ordering.

### 3.2 Z-A-sketch cross-reference

Per Z-A-Ack-Slot-4 (`reza/outbox/2026-05-11-z-a-cross-review-
ack.md` §4.2):

> The NATS-JWT refresh-on-reconnect behaviour is a **Client-Side
> Callback-Pattern**, NOT a NATS-server-2.10+ feature. The token
> refresh is sourced from the wirelang-side `JwtSvidCache` populated
> by a background `WatchJWTSVIDs` stream against the SPIRE Workload-
> API. The `nats-py` `user_jwt_cb` parameter (NOT the static
> `user_jwt` string parameter) is the correct integration point.

`docs/archive/evidence/decisions/spiffe-jwt-svid-identity-sketch.md` §4.2-Punkt-7 + §6 §3 document the
same correction and are the upstream reference for substrate.

### 3.3 Refresh-on-Reconnect contract (substrate)

```
┌───────────────────────────────────────────────────────────┐
│ Wirelang-side adapter (protocol track)                    │
│                                                           │
│   ┌────────────────────┐    Workload-API     ┌────────┐  │
│   │ WatchJWTSVIDs      │ ◄──UDS stream─── ─► │ SPIRE  │  │
│   │ background task    │                     │ Agent  │  │
│   └─────────┬──────────┘                     └────────┘  │
│             │ push new SVID                              │
│             ▼                                            │
│   ┌────────────────────┐                                 │
│   │ JwtSvidCache       │                                 │
│   │ - current_token()  │   ◄────reads─────┐              │
│   │ - current_exp_at() │                  │              │
│   │ - current_spiffe_id│                  │              │
│   └────────────────────┘                  │              │
└───────────────────────────────────────────│──────────────┘
                                            │
                              ┌─────────────│─────────────┐
                              │ callback factory           │
                              │  make_user_jwt_cb(cache)   │
                              │  → returns closure         │
                              └─────────────│──────────────┘
                                            │ closure ref
                                            ▼
                              ┌─────────────────────────────┐
                              │ nats-py CONNECT-frame build │
                              │  (Z. 1666-1668)             │
                              │  jwt = self._user_jwt_cb()  │
                              └─────────────────────────────┘
```

Three invariants the callback enforces:

1. **Current-state read on every invocation.** The closure captures
   the cache reference, not a token snapshot. Each `nats-py`
   CONNECT-frame build reads `cache.current_token()` fresh.
2. **Empty cache → clean error.** When the cache is empty (cold-start
   window before the first `WatchJWTSVIDs` push, or a stream-stall
   that cleared the cache), the callback raises
   `NatsJwtCallbackCacheEmpty`. The persona-container boot path
   gates `nats.connect()` on cache-hot status (wirelang-side
   adapter exposes a "wait for first SVID" surface; the stub does
   not).
3. **Expiry-check is opt-in.** Default `enforce_exp=False` — NATS-
   server validates `exp` server-side. Tests / diagnostic paths
   set `enforce_exp=True` to surface stalled `WatchJWTSVIDs`
   streams client-side.

## 4. Cross-reference: protocol engineering Mock-Adapter

protocol engineering (`9c94517`) added
`wirelang/adapters/spiffe_workload_api.py` containing:

- `JwtSvid` value object (frozen dataclass; spiffe_id, token,
  audiences, expires_at).
- `MockSpiffeWorkloadApiAdapter` hermetic mock with
  `fetch_jwt_svid(audience: str) -> JwtSvid`.
- Error hierarchy: `SpiffeAdapterError`, `...Unavailable`,
  `...AttestationFailed`, `...AudienceRejected`.

**reference posture (path-by-name, NO import):**

- The skizze module (`scripts/nats_jwt_callback_skizze.py`)
  references the wirelang adapter path in its module docstring and
  in error messages (`NatsJwtCallbackCacheEmpty.__str__` names
  `wirelang/adapters/spiffe_workload_api.py JwtSvidCache wait-for-
  first-SVID surface`).
- The tests do NOT `import wirelang.*`; they use the local
  `InMemorySvidCache` stub. Verified by Block-7 test
  `test_path_by_name_pin_for_wirelang_adapter_holds`.
- **Why path-by-name**: the wirelang adapter is owned by the protocol
  track and evolves on a different branch, which does NOT carry the
  protocol-side adapter commit. Importing it would break the
  hermetic-sketch constraint.

**Real-world wire-up** (Phase-2.5+ Operator-Hand):

The wirelang-side `JwtSvidCache` (when protocol engineering lands the real
adapter `real_spiffe_workload_api.py`) implements the
`JwtSvidCacheView` Protocol from. The persona-container boot
path:

1. Instantiates the wirelang adapter (real or mock).
2. Awaits cache-hot signal (first SVID pushed).
3. Builds the callback: `cb = make_user_jwt_cb(adapter.cache)`.
4. Calls `await nats.connect(url, user_jwt_cb=cb, signature_cb=...)`.

## 5. Acceptance criteria

| AC | Criterion | Status |
|---|---|---|
| AC-1 | `scripts/nats_jwt_callback_skizze.py` exists | done |
| AC-2 | Module exports `JwtSvidCacheView`, `InMemorySvidCache`, `make_user_jwt_cb`, error types | done (`__all__`) |
| AC-3 | `make_user_jwt_cb` returns a zero-arg callable returning bytes | done (Block-3 tests 3-1, 3-2) |
| AC-4 | Callable shape matches `nats-py` `JWTCallback` typedef | done (Block-3 test 3-3) |
| AC-5 | Callback reads current cache state at each invocation (refresh-on-reconnect) | done (Block-4 tests 4-1, 4-2, 4-3) |
| AC-6 | Cold cache raises `NatsJwtCallbackCacheEmpty` | done (Block-5 tests 5-1, 5-2) |
| AC-7 | Expiry-check opt-in via `enforce_exp` parameter | done (Block-6 tests 6-1, 6-2, 6-3) |
| AC-8 | Clock-injection for deterministic tests | done (Block-6 test 6-3) |
| AC-9 | `InMemorySvidCache` validates input shape (token type, naive datetime, empty SPIFFE-ID) | done (Block-2 tests 2-1, 2-2, 2-3) |
| AC-10 | substrate does NOT import from `wirelang.*` | done (Block-7 test 7-3) |
| AC-11 | `docs/nats-jwt-auth-phase-2-4.md` runbook present | done (this file) |
| AC-12 | Hermetic-only — no real `nats.connect()`, no real SPIRE-Agent calls | done (verify: no `import nats`, no `from nats` in module) |
| AC-13 | Protocol-adapter cross-reference path-by-name documented | done (§4) |
| AC-14 | `nats-py` Z. 110/317/370/1666-1668 cited line-by-line | done (§3.1 table) |
| AC-15 | Z-A-sketch §4.2-Punkt-7 + §6 §3 cross-referenced | done (§3.2) |
| AC-16 | Test-self-check pins 20 tests in the test file | done (Block-8 test 8-1) |
| AC-17 | Full hermetic suite: +20 tests, 0 regressions on green tests | done (orchestrator 207 passed, full hermetic 341 passed, 25 skipped; 3 F-5 carry-over unchanged) |
| AC-18 | Worktree-Pattern ADR-0049 followed | done (worktree `/tmp/kai-sprint-6-tag-10-nats-jwt-runtime` from tip `740215b`) |
| AC-19 | Tool-Surface-Stempel ADR-0050 declared | done (outbox header) |
| AC-20 | Sandbox-Host-Trennung ADR-0051 honoured (no podman/skopeo/cosign/socket calls) | done |

## 6. Operator-Hand workflow (Phase-2.5+ Live Wire-Up)

substrate is hermetic. The live wire-up is Phase-2.5+ and is
Operator-Hand (per ADR-0051 sandbox-trennung). The workflow below is
a runbook for the Operator; the persona-container does NOT execute
these steps autonomously.

### 6.1 Pre-conditions

- Zone-C-Ack for SPIRE-Server digest-pin (F-1 carry-over).
- Zone-C-Ack for SPIRE-Agent digest-pin (F-1' from).
- protocol engineering `real_spiffe_workload_api.py` landed in the wirelang
      adapter substrate (currently F-8 carry-over).
- [ ] NATS-server image with JWT-Auth-compile-flag (NATS 2.x default).
- [ ] SPIRE-Server registration-entry for the persona-container's
      SPIFFE-ID exists.
- [ ] SPIRE-Server trust-bundle exported to a path the NATS-server
      config can reference.

### 6.2 Bring-up sequence

1. `podman-compose up spire-server` — verify health-check passes.
2. `podman-compose up spire-agent` — verify Workload-API socket is
   present on `spire_agent_sockets:/run/spire/agent-sockets/api.sock`.
3. SPIRE-Server: register the persona-container's SPIFFE-ID with the
   target audience `nats://wakir.local`.
4. Trust-bundle export: `spire-server bundle show -format pem` →
   write to `config/nats-trust-bundle.pem`.
5. Switch `nats-server.conf` to JWT-Auth mode with the exported
   trust-bundle as issuer-keys.
6. `podman-compose restart nats-server` — verify health-check passes.
7. Persona-container start: wirelang adapter populates `JwtSvidCache`
   from `WatchJWTSVIDs`; persona awaits cache-hot signal.
8. Persona-container calls `nats.connect(url, user_jwt_cb=cb, ...)`.
9. Verify in NATS-server log: CONNECT accepted with JWT-Auth.
10. Issue a test KV write/read to confirm end-to-end path works.

### 6.3 Tear-down

1. Persona-container drains active subscriptions.
2. Persona-container calls `nc.close()`.
3. `podman-compose down nats-server spire-agent spire-server`.

### 6.4 Failure modes (Operator-Hand diagnostic table)

| Symptom | Likely cause | First diagnostic |
|---|---|---|
| CONNECT rejected, NATS log: "JWT validation failed" | Trust-bundle mismatch / SPIRE-Server reissued keys | Re-export bundle (step 4) + restart NATS |
| CONNECT rejected, NATS log: "JWT expired" | `WatchJWTSVIDs` stream stalled, cache holds stale token | Set `enforce_exp=True` in callback factory, restart persona |
| Persona-container hangs at `nats.connect()` | Cache cold (no first SVID), gate not respected | Check wirelang adapter's wait-for-first-SVID surface |
| `NatsJwtCallbackCacheEmpty` at reconnect | Stream-stall after initial success | Inspect SPIRE-Agent log; restart agent if Workload-API stalled |
| All persona-containers hang at boot | SPIRE-Agent attestation rejects all workloads | Check registration-entries on SPIRE-Server |

## 7. Test inventory

`tests/orchestrator/test_nats_jwt_auth_phase_2_4.py` — 20 hermetic tests:

| Block | Test ID | Substance |
|---|---|---|
| 1 — Protocol | `test_in_memory_cache_implements_view_protocol` | three Protocol methods present + callable |
| 1 — Protocol | `test_cold_cache_returns_none_on_all_readers` | cold cache yields None everywhere |
| 2 — Mutation | `test_cache_set_validates_input_shape` | set() rejects malformed inputs |
| 2 — Mutation | `test_cache_clear_resets_state` | clear() goes back to cold |
| 2 — Mutation | `test_cache_set_round_trips` | set() values readable via Protocol readers |
| 3 — Factory | `test_make_user_jwt_cb_returns_zero_arg_callable` | factory yields zero-arg callable |
| 3 — Factory | `test_callback_returns_bytes` | callback returns bytes (not str) |
| 3 — Factory | `test_callback_signature_matches_nats_py_jwt_callback_typedef` | annotation pins `bytes` |
| 4 — Refresh | `test_callback_reads_current_state_each_invocation` | refresh-on-reconnect; cache rotation surfaces in next call |
| 4 — Refresh | `test_callback_handles_repeated_invocation_stability` | stable bytes across repeated calls on static cache |
| 4 — Refresh | `test_callback_transitions_through_clear_then_refresh` | empty-window → CacheEmpty → recovery → bytes |
| 5 — Empty | `test_cold_cache_raises_cache_empty` | cold cache raises NatsJwtCallbackCacheEmpty |
| 5 — Empty | `test_cache_empty_message_points_to_wirelang_cache_surface` | error message references wirelang adapter path |
| 6 — Expiry | `test_default_enforce_exp_false_does_not_check_expiry` | default does not enforce client-side exp |
| 6 — Expiry | `test_enforce_exp_true_raises_on_past_exp` | opt-in exp check raises |
| 6 — Expiry | `test_enforce_exp_with_clock_injection` | injected clock controls exp comparison |
| 7 — Cross-ref | `test_skizze_module_path_exists` | scripts/ location pin |
| 7 — Cross-ref | `test_spiffe_constants_reachable_from_skizze_tree` | constants module loadable |
| 7 — Cross-ref | `test_path_by_name_pin_for_wirelang_adapter_holds` | docstring references adapter path; no wirelang imports |
| 8 — Self-check | `test_this_file_contains_twenty_tests` | 20-test pin for drift-detection |

## 8. Follow-up items

| ID | Item | Owner | Status |
|---|---|---|---|
| F-1 | SPIRE-Server digest-pin substitution | Operator-Hand + dev engineering Zone-C-Ack | unchanged from — pending |
| F-1' | SPIRE-Agent digest-pin substitution | Operator-Hand + dev-engineering Zone-C ack | unchanged — pending |
| F-5 | WAT-Aggregator-Test-Isolation drift (3 failing tests) | dev engineering (WAT core) | unchanged carry-over — the three failures do not touch this substrate |
| F-7 | Phase-2.5 End-to-End Smoke (real SPIRE + NATS) | Operator-Hand | NEW prereqs added; gated on F-1, F-1', F-8 |
| F-8 | `real_spiffe_workload_api.py` landing | protocol engineering | the observed protocol-track branch is publisher-CLI, NOT the SPIFFE adapter; `real_spiffe_workload_api.py` not yet landed; keeps the path-by-name reference posture |
| F-9 (NEW) | Phase-2.6 Trust-Bundle-Rotation Runbook | infrastructure engineering | scoped: rotation procedure when SPIRE-Server reissues trust-bundle (NATS-server config reload + persona-container reconnect verification) |
| F-10 (NEW) | Quadlet extension for SPIRE-Server + Agent | infrastructure engineering | scoped: analog `quadlet/wakir-nats-server.container` pattern; lands after Phase-2.5 live-validation |

## 9. Risk register

| Risk | Disposition |
|---|---|
| `nats-py` Z. 1666-1668 callback invocation is gated on `nonce` + `signature_cb` | Phase-2.5 live wire-up MUST configure a SPIFFE-aware `signature_cb` alongside `user_jwt_cb`; documented in §3.1 nuance |
| `JwtSvidCacheView` Protocol drift between stub and protocol engineering real adapter | Path-by-name pin (Block-7 test) breaks if path moves; Protocol-shape drift is Z-A re-coordination signal |
| Persona-container boot races (cold cache at first `nats.connect()`) | Persona-container MUST await cache-hot signal from wirelang adapter; callback raises a clean `NatsJwtCallbackCacheEmpty` if the gate is missed |
| Stale token in cache surviving past `exp` | `enforce_exp=True` opt-in raises client-side; default relies on NATS-server-side `exp` validation |
| protocol engineering adapter Protocol shape change | `InMemorySvidCache` MUST satisfy `JwtSvidCacheView` Protocol; any drift breaks Block-1 Protocol tests + forces co-edit |
| NATS-server JWT-Auth config typo (trust-bundle pem mis-pathed) | Operator-Hand checklist §6.1 step + §6.4 first-symptom row |

## 10. Anti-Bullshit-Disziplin (P5/P7/P2)

- **Authoring timestamp:** `date -u` 2026-05-12T18:30:45Z
  (Phase-2 box).
- **`nats-py` line-by-line citation verified (P7):** Read tool
  against `/var/home/fred/AI-Corp/agents-workspaces/kai/wakir-
  runtime/.venv/lib/python3.14/site-packages/nats/aio/client.py`
  Z. 100-115, 313-322, 365-379, 1660-1680. Substance matches the
  Z-A sketch §4.2 item 7 + §6 §3 citations.
- **Mock-Adapter source verified (P7):** `git show 9c94517:
  wirelang/adapters/spiffe_workload_api.py` against
  `/tmp/kai-sprint-6-tag-10-nats-jwt-runtime` — `MockSpiffeWorkloadApi
  Adapter`, `JwtSvid`, error hierarchy confirmed.
- **Protocol publisher-CLI branch verified (P7):** `git log --oneline
  origin/reza-sprint-6-tag-7-publisher-cli-unrevoke -1` — branch name
  is publisher-cli, not adapter. F-8 status confirmed.
- **test-execution verified:** `pytest tests/orchestrator/
  test_nats_jwt_auth_phase_2_4.py -v` → 20 passed.
- **Full hermetic suite verified:** `pytest tests/` → 341 passed,
  25 skipped, 3 failed (F-5 WAT-Aggregator carry-over).
- **P2 explicit:** the Phase-2.5 live wire-up step ordering
  (`signature_cb` + `user_jwt_cb` paired) is documented based on
  `nats/aio/client.py` Z. 1661-1668 branch reading; behaviour under
  live SPIFFE-JWT-Auth is verified by Operator-Hand at Phase-2.5
  bring-up (F-7).
- **P2 explicit:** the wirelang-side `JwtSvidCache` shape is's
  Protocol surface proposal; the protocol track may refine the surface
  (e.g. add a `wait_for_first_svid()` async method); the path-by-
  name pin breaks loudly if the path or core surface drifts.

## 11. Domain-Disziplin (footer)

- **DevOps-track-owned:** the `user_jwt_cb` callback factory pattern
  itself, the runbook, the hermetic tests, the Operator-Hand
  bring-up procedure, the Trust-Bundle-Rotation slot (F-9), the
  Quadlet extension slot (F-10).
- **Wirelang-side-owned (protocol engineering):** the `JwtSvidCache` concrete type,
  the `WatchJWTSVIDs` background stream implementation, the real
  `spiffe_workload_api.py` adapter (pending), the Persona-
  Container boot-path "wait for first SVID" surface.
- **NATS-server-side-owned (infrastructure engineering, Phase-2.5):** the JWT-Auth config,
  the trust-bundle import, the audience-validation policy.
- **Cross-Review-Zone-A bound:** the Protocol surface (`JwtSvidCache
  View`) is Z-A-Substanz; any shape change triggers Z-A re-
  coordination.
- **No ADR introduced:** is hermetic skizze, no architecture
  decision. Phase-2.5 live wire-up may surface ADR-worthy decisions
  (e.g. `signature_cb` SPIFFE-binding implementation choice); flagged
  for that box.
