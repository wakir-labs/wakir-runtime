<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Orchestrator NATS-JetStream KV Phase-1 — Operator Runbook

Status: draft, Phase 1b Sprint-2 Tag-3.
Companion to `compose/nats.yaml` (substrate),
`scripts/init-nats-buckets.py` (driver), and
`tests/orchestrator/test_init_nats_buckets.py` +
`tests/orchestrator/test_compose_nats.py` (hermetic regressions).

This runbook is the operator-facing checklist for bringing up and
maintaining the four Phase-1 NATS-JetStream KV buckets that back the
read-through cache layer used by the orchestrator. It is not a design
document — the substrate spec and the bucket value-envelope contract
live in their own memos and are referenced here only by name.

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
- Sprint-3: full systemd-timer wiring for the health-check tool plus
  a Prometheus textfile-collector adapter consuming the JSON report's
  `summary` block. The §5.2 cron snippet is the Phase-1b minimum-viable
  deployment.
- Sprint-3: SPIFFE JWT-SVID auth (Cross-Review Zone A). The
  initialiser currently consumes a token from `WAKIR_NATS_TOKEN`; the
  SVID path will replace this with a workload-API call. The health
  check inherits the same token contract today and will inherit the
  SVID upgrade for free.
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
- Hermetic regression suite (Tag-6 update): 35 tests pass + 2 skipped
  (live smoke, gated on `WAKIR_NATS_LIVE=1`) under Python 3.14.4 +
  pytest 9.0.3 (Phase-1b shared `.venv`); `tests/orchestrator/`.
  Composition: 10 tests for the bucket initialiser (Tag-2), 9 tests
  for the compose substrate (Tag-3), 16 tests for the health-check
  tool (Tag-6) including a cross-script inventory-parity regression
  (`test_inventory_matches_init_nats_buckets`). Test stamp:
  `date -u` 2026-05-07T12:39:46Z (CEST 14:39).
- Health-check tool authoring date (Tag-6 addition): `date -u`
  2026-05-07T12:39:46Z (CEST 2026-05-07, Sprint-2 Tag-6).
  `scripts/check-nats-kv-health.py` is read-only by construction;
  it does not introduce a new image-tag dependency, a new auth
  surface, or a new schema surface. The tool consumes the existing
  Tag-2 inventory and the existing Tag-3 compose `/jsz` endpoint.
