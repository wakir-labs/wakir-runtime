<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Orchestrator NATS-JetStream KV Phase-1 — Operator Runbook

Status: draft, Phase 1b Sprint-2 Tag-8 (Sprint-2 closing consolidation).
Companion to `compose/nats.yaml` (substrate),
`scripts/init-nats-buckets.py` (Phase-1 four-bucket driver),
`scripts/check-nats-kv-health.py` (Phase-1 substrate health
check),
`scripts/check-federation-evaluator-health.py` (Phase-1b V-908
federation evaluator health check),
`tests/orchestrator/test_init_nats_buckets.py` +
`tests/orchestrator/test_compose_nats.py` +
`tests/orchestrator/test_check_nats_kv_health.py` +
`tests/orchestrator/test_check_federation_evaluator_health.py`
(hermetic regressions, 55 passed + 4 live-smoke skipped under
`tests/orchestrator/`; 189 passed + 23 skipped project-wide
post-Tag-7).

This runbook is the operator-facing checklist for bringing up and
maintaining the Phase-1b NATS-JetStream KV buckets that back the
read-through cache layer used by the orchestrator and the V-908
federation route registry consumed by the N2 evaluator. It is not
a design document — the substrate spec, the bucket value-envelope
contract, and the federation-evaluator semantics live in their own
memos and are referenced here only by name.

## 0. Section index (Tag-8 consolidation)

| §   | Topic                                                              | Source tags |
| --- | ------------------------------------------------------------------ | ----------- |
| 1   | Bucket inventory (Phase-1, four-bucket cache layer)                | Tag-2       |
| 2   | Pre-flight check                                                   | Tag-2       |
| 3   | Bring-up (cold start: substrate + buckets-init + tear-down)        | Tag-2, Tag-3 |
| 4   | Idempotency contract                                               | Tag-2       |
| 5   | Health checks                                                      | Tag-2, Tag-6, Tag-7 |
| 5.1 | `check-nats-kv-health` tool                                        | Tag-6       |
| 5.2 | Cron-slot deployment                                               | Tag-6       |
| 5.3 | `check-federation-evaluator-health` tool                           | Tag-7       |
| 6   | Recovery scenarios                                                 | Tag-2, Tag-7 |
| 6.1 | NATS down                                                          | Tag-2       |
| 6.2 | JetStream disk loss                                                | Tag-2       |
| 6.3 | Configuration drift                                                | Tag-2, Tag-6 |
| 6.4 | FTD poison-list growth                                             | Tag-2       |
| 6.5 | Federation-routes bucket creation (Phase-1b bring-up)              | Tag-7       |
| 7   | Open follow-ups (sprint-by-sprint backlog)                         | Tag-2..Tag-8 |
| 8   | Verification stamps (P5/P7)                                        | Tag-2..Tag-8 |

The four operator artefacts (compose substrate, bucket initialiser,
NATS-KV substrate health check, federation evaluator health check)
share a common JSON output shape and exit-code contract; cron and
systemd consumers see one consistent surface across all four tools.
Cross-tool drift is pinned by hermetic regression tests
(`test_inventory_matches_init_nats_buckets`,
`test_bucket_name_matches_route_registry_backend`,
`test_bucket_config_matches_route_registry_backend`,
`test_drift_comparator_field_set_matches_phase_1_health_check`).

## 1. Bucket inventory (Phase-1, single-node)

| name                  | history | ttl        | max-value | storage | replicas | purpose                                        |
| --------------------- | ------- | ---------- | --------- | ------- | -------- | ---------------------------------------------- |
| `wakir-schemas`       | 5       | unbounded  | 256 KiB   | file    | 1        | Wirelang schema registry cache                 |
| `wakir-aip-cache`     | 1       | 3600 s     | 64 KiB    | file    | 1        | AIP-Document resolver cache                    |
| `wakir-ftd-cache`     | 1       | 3600 s     | 64 KiB    | file    | 1        | Federation-Trust-Document cache                |
| `wakir-ftd-poisoned`  | 10      | unbounded  | 4 KiB     | file    | 1        | FTD poison-list marker (asymmetric vs. cache)  |

The `wakir-ftd-poisoned` asymmetry is deliberate: a poisoned FTD must
outlive a cache-TTL window, so the bucket is unbounded and history is
deeper to support audit-trail review. A poison entry cannot be evicted
by the cache TTL of `wakir-ftd-cache`.

## 2. Pre-flight check

Before invoking the bucket initialiser:

| check                       | command                                                  | expected                       |
| --------------------------- | -------------------------------------------------------- | ------------------------------ |
| NATS server reachable       | `nc -z 127.0.0.1 4222 && echo ok`                        | `ok`                           |
| JetStream enabled           | `curl -s http://127.0.0.1:8222/jsz \| grep -q config`     | exit 0                         |
| Token env present (if used) | `[ -n "$WAKIR_NATS_TOKEN" ] && echo set \|\| echo unset` | `set` (or `unset` for no-auth) |
| Python interpreter          | `python3 --version`                                      | 3.11 or newer                  |
| `nats-py` installed         | `python3 -c 'import nats; print(nats.__version__)'`      | non-zero version string        |

The checklist assumes the operator is on a jump host or directly on
the orchestrator node. The script itself is dependency-free apart from
`nats-py`; the hermetic regression suite needs no NATS at all.

## 3. Bring-up (cold start)

Phase-1 cold-start is a two-step procedure: bring the substrate up
(NATS server + JetStream + named volume) via the compose file, then
initialise the four KV buckets via the python driver.

### 3.1 Substrate-up (compose)

```bash
# 1. Bring the NATS substrate up in the background. Loopback-only
#    publishing; named volume ``wakir-nats-jetstream-data`` survives
#    container recreate.
docker compose -f compose/nats.yaml up -d

# 2. Substrate readiness gates (each must be green before §3.2):
nc -z 127.0.0.1 4222 && echo client-port-ok        # NATS protocol
curl -s http://127.0.0.1:8222/jsz | jq -r .config  # JetStream live
docker compose -f compose/nats.yaml ps             # health: healthy
```

The compose file pins the image to a maintained alpine variant of the
official `nats` repository (see §8 verification stamp), drops all
Linux capabilities on the container, sets `no-new-privileges`, and
publishes only the loopback interface. The JetStream HTTP endpoint
(`/jsz`) is also loopback-only — never expose it without
authentication.

To upgrade the image-pin from tag-only to digest-pinned form (the
recommended Box-3-follow-up for the build host):

```bash
docker pull nats:2.11-alpine
docker inspect --format '{{index .RepoDigests 0}}' nats:2.11-alpine
# => nats@sha256:<full-digest>
# Replace the ``image:`` line in compose/nats.yaml with:
#     image: nats:2.11-alpine@sha256:<full-digest>
```

The hermetic test `test_nats_service_uses_documented_image_tag`
accepts both forms.

### 3.2 Buckets-init

```bash
# 1. Plan-only first; nothing is mutated.
python3 scripts/init-nats-buckets.py --dry-run

# 2. Apply.
python3 scripts/init-nats-buckets.py

# 3. Confirm exit 0 and a JSON report on stdout listing four
#    "created" actions and a summary block of {created: 4, ...}.
```

The script writes a structured JSON report to stdout (one document per
invocation) and a human-readable progress log to stderr. The
orchestrator container init parses the JSON; an operator running the
script by hand can pipe it through `jq` for readability:

```bash
python3 scripts/init-nats-buckets.py | jq .
```

To target a remote NATS:

```bash
python3 scripts/init-nats-buckets.py --servers nats://prod-nats:4222
```

To re-initialise a single bucket (idempotent on the rest):

```bash
python3 scripts/init-nats-buckets.py --bucket wakir-schemas
```

### 3.3 Tear-down

```bash
# Stop the container, keep the volume (cache survives).
docker compose -f compose/nats.yaml down

# Stop the container and drop the volume (deliberate cache loss).
docker compose -f compose/nats.yaml down -v
```

`down -v` is the documented Phase-1 disk-loss recovery path (§6.2).
The cache is by definition not source-of-truth, so a deliberate drop
is a routine operation.

## 4. Idempotency contract

The script is safe to re-run. A re-run against an already-initialised
cluster reports every bucket as `unchanged` and exits 0. The script
**never deletes** a bucket and **never silently mutates** an existing
bucket's configuration.

If a bucket exists with a configuration that diverges from the
documented Phase-1 inventory above, the script reports `drift`,
includes a `{want, got}` diff payload per drifted field, and exits
with code 2. The operator decides how to reconcile: either correct the
documented inventory and re-deploy the script, or recreate the bucket
by hand (`nats kv rm` + `nats kv add`). Auto-correction is intentionally
out of scope: a silent overwrite of an operator-applied config would
violate ops-first discipline.

Exit codes:

- `0` — all buckets at the documented configuration
- `1` — connection failure, missing dependency, invalid CLI args
- `2` — at least one drift detected; nothing was mutated

## 5. Health checks

After bring-up:

1. `nats kv ls` — confirms the four bucket names are present.
2. `nats kv info wakir-schemas` — confirms history/TTL/replicas match
   §1 of this runbook.
3. Smoke read-through: from the orchestrator container, hit a known
   schema endpoint and confirm a cache miss populates the bucket on
   first hit and a hit returns from KV on second hit. The relevant
   trace fields are documented in the read-through wrapper module
   docstring.

### 5.1 `check-nats-kv-health` tool (Sprint-2 Tag-6)

The `nats` CLI commands above are fine for a one-off operator check,
but they do not produce a structured report and do not detect
configuration drift the way `init-nats-buckets.py` does. Tag-6 ships
a dedicated read-only tool, `scripts/check-nats-kv-health.py`, that
covers three checks in a single invocation and emits a JSON report
to stdout for downstream tooling (cron-driven monitoring, on-call
triage, CI smoke gates).

What it checks:

| Check | Mechanism | Reports |
| --- | --- | --- |
| Substrate connectivity | HTTP GET on `/jsz` (default `http://127.0.0.1:8222/jsz`) | `ok` / `unreachable` / `skipped` |
| Bucket existence | `js.key_value(bucket=<name>)` per documented Phase-1 bucket | `ok` / `missing` / `error` |
| Bucket configuration | `kv.status()` compared to `PHASE_1_BUCKETS` inventory | `ok` / `drift` (with `{want, got}` diff) |

The tool is **read-only**: it never calls `create_key_value` or any
write API. Idempotence is trivial: it has no side effects. An
operator can run it on any node with a valid NATS token without
giving that node write credentials.

Usage:

```bash
# Local single-node smoke (loopback NATS + /jsz)
python3 scripts/check-nats-kv-health.py

# Plan only — never opens a connection, prints the would-be checks
python3 scripts/check-nats-kv-health.py --dry-run

# Skip the /jsz HTTP probe (e.g. when the monitoring port is
# firewalled off but the NATS protocol port is reachable)
python3 scripts/check-nats-kv-health.py --skip-jsz

# Single-bucket triage
python3 scripts/check-nats-kv-health.py --bucket wakir-schemas

# Remote NATS
python3 scripts/check-nats-kv-health.py --servers nats://prod-nats:4222
```

Exit codes (the cron-monitor consumer contract):

- `0` — every requested bucket is `ok` and `/jsz` is `ok` (or
  `--skip-jsz` was passed).
- `1` — connection failure, missing dependency (`nats-py`),
  unreachable `/jsz` (when not skipped), or a per-bucket inspection
  error. This dominates any drift signal: the read may not be
  complete.
- `2` — at least one bucket is `missing` or `drift`. The cluster is
  reachable; the configuration does not match the documented
  inventory.

The drift detector compares the same fields as `init-nats-buckets.py`
(`history`, `ttl`, `max_value_size`, `storage`, `replicas`) using the
identical comparison logic. A regression test
(`test_inventory_matches_init_nats_buckets`) keeps the two tools in
sync; an operator running the init script and then the health check
will never see fabricated drift.

JSON output shape (stable for Sprint-2 onwards; cron consumers may
rely on it):

```json
{
  "servers": "nats://127.0.0.1:4222",
  "jsz_url": "http://127.0.0.1:8222/jsz",
  "dry_run": false,
  "jsz": {"status": "ok", "detail": "2xx from /jsz", "http_status": 200},
  "summary": {"ok": 4, "missing": 0, "drift": 0, "error": 0, "total": 4},
  "checks": [
    {"name": "wakir-schemas", "status": "ok",
     "detail": "Wirelang schema registry cache (Phase-1)", "drift": {}}
  ]
}
```

### 5.2 Cron-slot deployment (Phase-1b operator hint)

The health-check tool is designed to be run periodically. A
recommended Phase-1b cadence is once every five minutes from a node
with a read-only NATS token; output is captured and forwarded to the
on-call channel only on non-zero exit.

Suggested cron entry (orchestrator host):

```cron
*/5 * * * * /usr/bin/python3 /opt/wakir-runtime/scripts/check-nats-kv-health.py >/var/log/wakir/nats-kv-health.json 2>>/var/log/wakir/nats-kv-health.stderr || /opt/wakir-runtime/scripts/notify-oncall.sh "$(date -u +%Y-%m-%dT%H:%M:%SZ) nats-kv-health exit=$?"
```

Two operator notes for the cron path:

- The token must be available in the cron user's environment
  (`WAKIR_NATS_TOKEN`); a systemd timer with `EnvironmentFile=` is
  the cleaner Phase-1b alternative if cron's env handling is
  inconvenient.
- The JSON report is overwritten on every run by design; if a longer
  history is desired, pipe to a date-stamped file or to a structured
  log consumer. The report's `summary` block is sufficient for a
  Prometheus textfile-collector adapter, which is a Phase-2 follow-up.

The full systemd-timer wiring (units + drop-ins + observability
forwarding) is out of scope for Tag-6; the cron snippet is the
minimum-viable deployment that an on-call can drop in same-day. A
proper systemd unit set will land alongside the OTel collector
in Sprint-3.

### 5.3 `check-federation-evaluator-health` tool (Sprint-2 Tag-7)

The federation-evaluator health-check tool is the next layer above
the NATS-KV substrate probe. It targets the V-908 federation route
registry that the N2 evaluator (wirelang-eng-side
`wirelang/federation/n2_evaluator.py`) consumes and reports on
operator-relevant statistics that the substrate-only tool cannot
see.

Cross-reference: this tool consumes the wirelang-eng-side modules
`wirelang/federation/route_registry_nats_kv_backend.py` (Tag-4)
and `wirelang/federation/n2_evaluator.py` (Tag-3) byte-precisely;
the bucket name and configuration come from the wirelang-eng module's
`BUCKET_NAME` / `BUCKET_CONFIG` constants (single source of truth,
no duplication).

| check                                  | mechanism                                                            | reports                                                |
| -------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------ |
| `wakir-federation-routes` bucket exists | `await js.key_value(bucket="wakir-federation-routes")`               | `missing` / `error` / `ok`                              |
| Bucket configuration drift             | `kv.status()` compared against wirelang-eng-side `BUCKET_CONFIG`             | per-field `{want, got}` for `history` / `ttl` / `max_value_size` / `storage` / `replicas` |
| Snapshot decode + tally                | `NatsKvRouteRegistry.snapshot()` walk over all keys                  | total / active / expired / not-yet-active / with_wat_anchor / poisoned_keys |
| Optional N2-evaluator smoke            | one `FederationEvaluator.evaluate_federation_route` call             | `ok` / `reject` (`error_kind`) / `error`                |
| Connectivity (`/jsz`)                  | HTTP probe (re-used from Tag-6)                                      | 2xx healthy / unreachable / skipped                     |

Usage:

```bash
# Plan-only (dry-run; no NATS connection)
python3 scripts/check-federation-evaluator-health.py --dry-run

# Full structural check against the local cluster
python3 scripts/check-federation-evaluator-health.py

# Optional N2-evaluator smoke (operator must know the route_id)
python3 scripts/check-federation-evaluator-health.py \
    --probe-route "wakir->partner-A->treasury" \
    --probe-ftd-id "did:web:wakir.dev:ftd:v1"
```

Exit codes:

- `0` -- bucket present at documented config; snapshot decoded
  cleanly; `/jsz` healthy (or skipped); evaluator probe accepted
  (or not requested).
- `1` -- unrecoverable: connection failure, `nats-py` missing,
  `/jsz` HTTP non-2xx (when not skipped), wirelang-eng-side modules not on
  PYTHONPATH, invalid CLI arguments.
- `2` -- bucket missing OR drift OR snapshot poisoned OR evaluator
  rejected the probe.

JSON output shape (top-level keys, `sort_keys=True`):

```json
{
  "bucket": {"detail": "...", "drift": {}, "name": "wakir-federation-routes", "status": "ok"},
  "bucket_name": "wakir-federation-routes",
  "dry_run": false,
  "evaluator": {"detail": "...", "error_kind": null, "ftd_id": null, "route_id": null, "status": "skipped"},
  "jsz": {"detail": "...", "http_status": 200, "status": "ok"},
  "jsz_url": "http://127.0.0.1:8222/jsz",
  "servers": "nats://127.0.0.1:4222",
  "snapshot": {"active": 2, "detail": "...", "expired": 0, "not_yet_active": 0, "poisoned_keys": [], "status": "ok", "total": 2, "with_wat_anchor": 1}
}
```

The `snapshot.with_wat_anchor` counter is the Z2 cross-review
surface: it counts entries carrying a non-`null`
`wat_anchor_manifest_id` field, which downstream WAT-leaf consumers
will use to bind a route-registry version to a WAT manifest. The
counter is informational on the Phase-1b path; no Phase-1b code
asserts a non-zero value.

Pre-condition for non-dry-run usage: the `wakir-federation-routes`
bucket must exist on the live cluster. Phase-1b does not auto-create
the bucket from this tool (read-only contract); see §6.5 for the
operator-side bucket-creation procedure when the federation
evaluator is being brought up.

PYTHONPATH note: this tool imports from `wirelang.federation.*` and
must therefore be run with the `wakir-runtime` repo root on
`PYTHONPATH`, or with the package installed in the operator's
virtualenv. The Tag-6 NATS-KV health-check has no wirelang-eng-side
dependency and runs with no PYTHONPATH gymnastics; the federation
evaluator tool is one layer up and accepts that import cost as the
price of single-source-of-truth bucket constants.

## 6. Recovery scenarios

### 6.1 NATS down

The read-through wrapper invariant is: a `NatsConnectionError` is a
non-fatal cache miss. The orchestrator continues to serve from the
file-system fallback. Recovery is to bring NATS back; no state is
lost, because the cache is by definition not source-of-truth.

### 6.2 JetStream disk loss

Phase-1 is single-node file storage. Disk loss = cache loss. Recovery
is to recreate the buckets (`init-nats-buckets.py`) and let the
read-through repopulate them on demand. Phase-3 (replicated cluster)
eliminates this scenario; it is acceptable for Phase-1 because the
cache is not source-of-truth.

### 6.3 Configuration drift

If `init-nats-buckets.py` exits 2 with drift on a production cluster
— or `check-nats-kv-health.py` exits 2 with `drift` on the read-side:

1. Capture the JSON report (`script ... > drift-report.json`). Both
   tools emit the same `{want, got}` diff shape on the per-bucket
   record.
2. Triage with the engineering on-call: was the drift intentional
   (operator override) or an accident (manual misconfiguration)?
3. If intentional, file an ADR amendment to the documented inventory
   in §1 of this runbook and patch `PHASE_1_BUCKETS` in both scripts.
   The cross-script regression test keeps them in lock-step.
4. If accidental, recreate the affected bucket by hand and re-run the
   initialiser; the health-check tool then reports `ok`.

### 6.4 FTD poison-list growth

`wakir-ftd-poisoned` is unbounded by design. If it grows beyond
operationally tolerable size (Phase-1 working assumption: < 10k
entries), trigger a manual audit review. Eviction policy beyond
audit review is a Phase-2 follow-up; do not auto-evict in Phase-1.

### 6.5 Federation-routes bucket creation (Phase-1b bring-up)

The `wakir-federation-routes` bucket is the V-908 federation route
registry consumed by the N2 evaluator. Phase-1b does not yet
include this bucket in the `init-nats-buckets.py` driver inventory
(documented divergence; see §7 follow-up); for Phase-1b bring-up
the operator creates the bucket by hand using the documented
configuration:

```bash
nats kv add wakir-federation-routes \
    --history=5 \
    --ttl=0 \
    --max-value-size=4096 \
    --storage=file \
    --replicas=1 \
    --description="V-908 federation-route registry (Phase-1b)"
```

The values mirror the constant
`wirelang.federation.route_registry_nats_kv_backend.BUCKET_CONFIG`
byte-precisely. The
`scripts/check-federation-evaluator-health.py` tool verifies the
match on every run; drift surfaces as exit code 2 with a per-field
`{want, got}` diff.

After bucket creation, populate the registry with the operator's
documented routes (out-of-scope for this runbook; see the V-908
operator playbook). Re-run
`scripts/check-federation-evaluator-health.py` and confirm exit 0.

## 7. Open follow-ups

- Sprint-2 Box-3: ~~pin the NATS server image tag in `compose/nats.yaml`~~
  done in Sprint-2 Tag-3 — `compose/nats.yaml` pins `nats:2.11-alpine`
  with a documented digest-pin upgrade path (§3.1) for build-host
  operators with a container engine. Cross-Review Zone C (Image-
  Pipeline × OTS-Anchoring) sync with Engineering-Lead pending; the
  ack/modify/veto memo is logged in the dev-engineering inbox under
  `2026-05-07-kai-zone-c-image-pin-nats-2.11-alpine.md`.
- Sprint-2 Box-3 build-host follow-up: an operator on a machine with
  a container engine resolves the digest (`docker pull` +
  `docker inspect`) and replaces the tag-pin with the
  `@sha256:<digest>` form. No code change required — the hermetic
  test suite accepts both forms.
- Sprint-2 Box-5: real `nats-py` (`nats.aio`) sync-adapter for the
  read-through wrapper. The initialiser already uses the async API; no
  rework expected on the bucket side.
- Sprint-2 Tag-6: ~~ship a structured-output operator health check~~
  done — `scripts/check-nats-kv-health.py` plus its hermetic test
  suite (`tests/orchestrator/test_check_nats_kv_health.py`) and the
  §5.1/§5.2 runbook entries. Build-host live-smoke (`WAKIR_NATS_LIVE=1`)
  is the Tag-6 follow-up: the two gated smoke tests need a Box-3
  compose stack to exercise.
- Sprint-2 Tag-7: ~~ship a federation-evaluator health-check tool~~
  done — `scripts/check-federation-evaluator-health.py` plus its
  hermetic test suite
  (`tests/orchestrator/test_check_federation_evaluator_health.py`,
  20 hermetic + 2 live-smoke gated) and the §5.3 + §6.5 runbook
  entries. Cross-script parity tests pin the wirelang-eng-side `BUCKET_NAME`
  / `BUCKET_CONFIG` / drift-field-set against the Tag-6 health
  check.
- Sprint-2 Tag-8: ~~runbook consolidation pass~~ done — header
  bumped to Sprint-2 closing state, §0 section index added, §8
  verification stamps refreshed for the full Tag-2..Tag-7 surface,
  cross-references between §5 and §6.5 verified. No new tool, no
  new test surface; this pass is documentation-only and ships
  alongside the Sprint-2 dev-engineering-3-side acceptance memo
  (see the dev-engineering-3 outbox under
  `agents-workspaces/<dev-engineering-3>/outbox/`, file slug
  `2026-05-07-phase-1b-sprint-2-acceptance-doku`).
- Sprint-3: extend `init-nats-buckets.py` `PHASE_1_BUCKETS` to
  include `wakir-federation-routes` as a fifth bucket so the
  bring-up procedure in §6.5 collapses into the routine `init`
  pass. The Tag-7 federation evaluator health check already
  consumes the bucket-config constant from the wirelang-eng-side module;
  the orchestrator-side init driver has not yet picked up the
  fifth entry. Cross-Review Zone B (NATS-KV × Wirelang)
  paired-update with the wirelang-eng track when this lands.
- Sprint-3: full systemd-timer wiring for the health-check tool plus
  a Prometheus textfile-collector adapter consuming the JSON report's
  `summary` block. The §5.2 cron snippet is the Phase-1b minimum-viable
  deployment.
- Sprint-3: SPIFFE JWT-SVID auth (Cross-Review Zone A). The
  initialiser currently consumes a token from `WAKIR_NATS_TOKEN`; the
  SVID path will replace this with a workload-API call. The health
  check inherits the same token contract today and will inherit the
  SVID upgrade for free.
- Sprint-3: build-host activation. The Sprint-2 hermetic test suite
  is complete (55 + 4 skipped under `tests/orchestrator/`), but four
  live-smoke contracts are gated on `WAKIR_NATS_LIVE=1` and require
  a build host with `gcc` (for `nats-py` compilation), a container
  engine (`podman` or `docker`) for the compose substrate, and the
  `nats` CLI for the `kv add` step in §6.5. Activation order:
  (i) install gcc + podman + nats-py + nats-cli, (ii) `docker
  compose -f compose/nats.yaml up -d` (Box-3 substrate), (iii)
  `python3 scripts/init-nats-buckets.py` (Phase-1 four-bucket
  init), (iv) `nats kv add wakir-federation-routes ...` per §6.5
  (Phase-1b fifth bucket), (v) `WAKIR_NATS_LIVE=1 python3 -m
  pytest tests/orchestrator/` to exercise the four live-smoke
  contracts (Box-5 real-nats-py-adapter + Tag-6 NATS-KV health +
  Tag-7 federation-evaluator health). Until that activation, the
  hermetic suite is the production-grade contract surface; the
  live-smoke tests are activation-gated future work.
- Phase-3: replicated JetStream (replicas > 1) requires a multi-node
  cluster topology. Bucket spec changes are limited to `replicas`; the
  initialiser already plumbs that field end-to-end and the health
  check's drift detector compares it.

## 8. Verification stamps (P5/P7)

- Authoring date (Tag-3 update): `date -u` 2026-05-07T (CEST
  2026-05-07, Sprint-2 Tag-3).
- NATS server image-tag candidate verification (Phase-1b production
  baseline): the official `nats` Docker Hub repository lists
  `2.11-alpine` as a maintained alpine variant, last pushed 9 days
  before Tag-2 authoring. The 2.10 line is no longer in the official
  maintained-tags listing; operators upgrading from a Phase-0 PoC that
  pinned `2.10-alpine` should move to `2.11-alpine`. The 2.14 line is
  fresh-GA (released ~7 days before Tag-2 authoring) and is rejected
  for Phase-1b under boring-tech-bias. Verification was a Docker Hub
  web snapshot from Tag-2 (2026-05-07T11:36 UTC); the authoring
  sandbox has no container engine, so digest-reproduction was
  deferred to a build-host follow-up. The `image:` line in
  `compose/nats.yaml` is therefore tag-pinned; the upgrade procedure
  to digest-pinned form is documented in §3.1.
- `nats-py` version: not pinned in this runbook. Pinning belongs in
  the orchestrator container's Python dependency manifest, not in
  this operator-facing document.
- Hermetic regression suite (Tag-7 update): 55 tests pass + 4 skipped
  (live smoke, gated on `WAKIR_NATS_LIVE=1`) under Python 3.14.4 +
  pytest 9.0.3 (Phase-1b shared `.venv`); `tests/orchestrator/`.
  Composition: 10 tests for the bucket initialiser (Tag-2), 9 tests
  for the compose substrate (Tag-3), 16 tests for the NATS-KV
  health-check tool (Tag-6) including a cross-script inventory-parity
  regression (`test_inventory_matches_init_nats_buckets`), 20 tests
  for the federation evaluator health-check tool (Tag-7) including
  three cross-tool parity regressions
  (`test_bucket_name_matches_route_registry_backend`,
  `test_bucket_config_matches_route_registry_backend`,
  `test_drift_comparator_field_set_matches_phase_1_health_check`).
  Test stamp: `date -u` 2026-05-07T13:09:42Z (CEST 15:09).
- Health-check tool authoring date (Tag-6 addition): `date -u`
  2026-05-07T12:39:46Z (CEST 2026-05-07, Sprint-2 Tag-6).
  `scripts/check-nats-kv-health.py` is read-only by construction;
  it does not introduce a new image-tag dependency, a new auth
  surface, or a new schema surface. The tool consumes the existing
  Tag-2 inventory and the existing Tag-3 compose `/jsz` endpoint.
- Federation-evaluator health-check tool authoring date (Tag-7
  addition): `date -u` 2026-05-07T13:09:42Z (CEST 2026-05-07,
  Sprint-2 Tag-7).
  `scripts/check-federation-evaluator-health.py` is read-only by
  construction; it consumes the wirelang-eng-side
  `wirelang/federation/route_registry_nats_kv_backend.py` (Tag-4)
  and `wirelang/federation/n2_evaluator.py` (Tag-3) byte-precisely
  via direct constant import (single source of truth, no
  duplication). The tool introduces no new image-tag dependency,
  no new auth surface, and no new schema surface; it does require
  the wakir-runtime repo root on PYTHONPATH so the
  `wirelang.federation.*` imports resolve. Full project-wide test
  suite stamp post-Tag-7: `189 passed, 23 skipped, 0 regressions`.
- Tag-8 consolidation stamp: `date -u` 2026-05-07T13:29:47Z
  (CEST 2026-05-07T15:29). This pass is documentation-only. No
  code surface is touched; no test surface is added; no exit-code
  contract changes; no schema changes; no auth-surface changes.
  The verification stamp re-runs the full test suite to confirm
  zero-drift: `tests/orchestrator/` 55 passed + 4 skipped (Tag-7
  baseline preserved); project-wide 189 passed + 23 skipped
  (Tag-7 baseline preserved); zero regressions. The §0 section
  index, the §7 Tag-8 entry, and this verification stamp are the
  only Tag-8 additions to the runbook proper. The Sprint-2
  dev-engineering-3-side acceptance memo (slug
  `2026-05-07-phase-1b-sprint-2-acceptance-doku` in the
  dev-engineering-3 outbox) is the companion deliverable for the
  Sprint-2 closing gate.
