<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Orchestrator NATS-JetStream KV Phase-1 — Operator Runbook

Status: draft, Phase-2 Sprint-5 Tag-2 (Z-B 7th-bucket
`wakir-capability-policies` paired-update — see §1, §3.2.3, §7.9
and the §8 Sprint-5 Tag-2 stamp; Sprint-6 Tag-1/Tag-2 added the
Quadlet/systemd dual-track sibling artefact under `quadlet/` and
the §9 brand-guide sweep across public-form files).
Companion to `compose/nats.yaml` (substrate),
`scripts/init-nats-buckets.py` (Phase-1 seven-bucket driver),
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

## 0. Section index

| §   | Topic                                                              |
| --- | ------------------------------------------------------------------ |
| 1   | Bucket inventory (Phase-1, seven-bucket layout)                    |
| 2   | Pre-flight check                                                   |
| 3   | Bring-up (cold start: substrate + buckets-init + tear-down)        |
| 3.2.1 | Backfill 5th bucket on pre-Tag-4 cluster                         |
| 3.2.2 | Backfill 6th bucket on pre-Tag-5 cluster                         |
| 3.2.3 | Backfill 7th bucket on pre-Sprint-5-Tag-2 cluster                |
| 4   | Idempotency contract                                               |
| 5   | Health checks                                                      |
| 5.1 | `check-nats-kv-health` tool                                        |
| 5.2 | Cron-slot deployment                                               |
| 5.3 | `check-federation-evaluator-health` tool                           |
| 6   | Recovery scenarios                                                 |
| 6.1 | NATS down                                                          |
| 6.2 | JetStream disk loss                                                |
| 6.3 | Configuration drift                                                |
| 6.4 | FTD poison-list growth                                             |
| 6.5 | Federation-routes bucket creation (now routine; fallback only)     |

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

| name                              | history | ttl        | max-value | storage | replicas | purpose                                                                                                       |
| --------------------------------- | ------- |
| `wakir-schemas`                   | 5       | unbounded  | 256 KiB   | file    | 1        | Wirelang schema-registry cache (Phase-1b consumer: Sprint-3 Tag-1)                                            |
| `wakir-aip-cache`                 | 1       | 3600 s     | 64 KiB    | file    | 1        | AIP-Document resolver cache                                                                                   |
| `wakir-ftd-cache`                 | 1       | 3600 s     | 64 KiB    | file    | 1        | Federation-Trust-Document cache                                                                               |
| `wakir-ftd-poisoned`              | 10      | unbounded  | 4 KiB     | file    | 1        | FTD poison-list marker (asymmetric vs. cache)                                                                 |
| `wakir-schema-registry-entries`   | 5       | unbounded  | 256 KiB   | file    | 1        | Wirelang schema-registry storage (Phase-2-reserved; no Phase-1b consumer)                                     |
| `wakir-federation-routes`         | 5       | unbounded  | 4 KiB     | file    | 1        | V-908 federation-route registry (Phase-1b consumer: Wirelang-side `NatsKvRouteRegistry`, Sprint-2 Tag-4/Tag-6) |
| `wakir-capability-policies`       | 10      | unbounded  | 4 KiB     | file    | 1        | Capability-policy persistence (Phase-3-reserved; no Phase-1b / Phase-2 consumer; audit-friendly small-marker shape) |

The `wakir-ftd-poisoned` asymmetry is deliberate: a poisoned FTD must
outlive a cache-TTL window, so the bucket is unbounded and history is
deeper to support audit-trail review. A poison entry cannot be evicted
by the cache TTL of `wakir-ftd-cache`.

The 5th bucket `wakir-schema-registry-entries` was added Sprint-4 Tag-4
as the Z-B paired-update with the Wirelang-side track. Its config intentionally mirrors
`wakir-schemas` (history=5, ttl unbounded, 256 KiB max-value) so the
Phase-2 migration off the cache bucket onto the storage bucket is a
value-copy without a config-drift step. There is **no Phase-1b
consumer** for this bucket: it is created on cluster bring-up so the
Phase-2 operator bring-up procedure collapses into the routine
`init-nats-buckets.py` pass (no manual `nats kv add` step on the
cluster). The Wirelang-side Sprint-3 Tag-1 schema-registry backend
(`wirelang.schemas.registry_nats_kv_backend`) continues to read and
write `wakir-schemas` in Phase-1b; switching the backend onto the new
storage bucket is the OI-7-Phase-2 slot the Wirelang-side track owns.

The 6th bucket `wakir-federation-routes` was added Sprint-4 Tag-5 as
the Z-B follow-up paired-update, closing the Sprint-2 Tag-7 Z-B
inventory-drift open follow-up. Unlike the 5th bucket this entry HAS
a live Phase-1b consumer: the Wirelang-side
`wirelang.federation.route_registry_nats_kv_backend.NatsKvRouteRegistry`
(Sprint-2 Tag-4 read/write backend + Sprint-2 Tag-6 watch-stream
snapshot layer). Before Tag-5 the bucket was created out-of-band per
the §6.5 hand-creation recipe; Tag-5 promotes it into the routine
`init-nats-buckets.py` pass. Bucket-config mirrors the Wirelang-side
`BUCKET_CONFIG` constant byte-precisely (history=5, ttl unbounded,
4 KiB max-value, file storage, replicas=1); the dual-anchor parity
contract is enforced by the hermetic
`test_t_tag5_02_sixth_bucket_config_mirrors_wirelang_consumer_bucket_config`
test plus the existing `test_inventory_matches_init_nats_buckets`
cross-script parity test.

The 7th bucket `wakir-capability-policies` was added Sprint-5 Tag-2 as
the Z-B paired-update with the Wirelang-side Sprint-5 Tag-2
capability-policy persistence track. The bucket is **reserved for the
Phase-3 promotion** of the operator-local `--capability-registry`
JSON-file shape (Sprint-5 Tag-1 publisher-CLI; see
`wirelang/schemas/publisher_cli.py` `--capability-registry` /
`--gate` flags) onto a cluster-wide cross-invocation policy store.
There is **no Phase-1b / Phase-2 live consumer** for this bucket; it is
registered ahead of time so the Phase-3 operator bring-up procedure
collapses into the routine `init-nats-buckets.py` pass (no manual
`nats kv add` step on the cluster). Bucket-config uses audit-friendly
defaults: history=10 (capability-policy rotations want a deep audit
trail, mirroring `wakir-ftd-poisoned`), ttl unbounded (policies live
until explicit rotation), max-value 4 KiB (a single serialised policy
entry is small; mirrors the small-marker shape of
`wakir-ftd-poisoned`). The concrete `BUCKET_CONFIG` constant on the
Wirelang-side will be exported by the Wirelang-track-owned
encoder/decoder module when it lands (Capability-Token-Layer is
Wirelang-track-owner per Persona-Matrix §2); until then this entry
stays in reservation-form (no
cross-import-mirror anchor). The Sprint-4-Tag-4 pre-Phase-2-reservation
pattern is the analogue; the Sprint-4-Tag-5 6th-bucket pattern is the
post-consumer-commit anchor that the 7th bucket will reach as a
follow-up. See §7.9 for substance, §3.2.3 for the no-downtime backfill
recipe.

## 2. Pre-flight check

Before invoking the bucket initialiser:

| check                       | command                                                  | expected                       |
| --------------------------- | -------------------------------------------------------- |
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
initialise the **six** KV buckets via the python driver
(five Phase-1b-consumed buckets + 1 Phase-2-reserved
`wakir-schema-registry-entries`; see §1). The 6th bucket
`wakir-federation-routes` is part of the routine init pass from
Sprint-4 Tag-5 onward; pre-Tag-5 clusters that used the §6.5
hand-creation recipe are no-downtime-upgradable via the §3.2.2
backfill recipe.

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

**Image-pin form (post-Phase-2 Sprint-4 Tag-3, Cross-Review Zone-C):**

The compose file is digest-pinned to the manifest-list digest of
`nats:2.11-alpine` resolved 2026-05-11 via Docker Hub public registry
API:

```yaml
image: nats:2.11-alpine@sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00
```

The digest-pin gate is enforced by `scripts/verify-image-digest.sh`
(see §7.5). The hermetic test `test_nats_service_uses_documented_image_tag`
continues to accept both the digest-pin and the tag-only fallback
form, so a debug bring-up that intentionally rolls back to tag-only
does not break the contract.

To resolve a fresh digest from a build host (when upstream pushes a
new 2.11-alpine alpine and the operator wants to advance the pin):

```bash
docker pull nats:2.11-alpine
docker inspect --format '{{index .RepoDigests 0}}' nats:2.11-alpine
# => nats@sha256:<full-digest>
# Replace the ``image:`` line in compose/nats.yaml with:
#     image: nats:2.11-alpine@sha256:<full-digest>
# Then re-run scripts/verify-image-digest.sh (see §7.5).
```

### 3.2 Buckets-init

```bash
# 1. Plan-only first; nothing is mutated.
python3 scripts/init-nats-buckets.py --dry-run

# 2. Apply.
python3 scripts/init-nats-buckets.py

# 3. Confirm exit 0 and a JSON report on stdout listing six
#    "created" actions and a summary block of {created: 6, ...}.
#    (Pre-Sprint-4-Tag-4 clusters report four created + two "would
#    create" or "missing"; pre-Sprint-4-Tag-5 clusters that already
#    have the 5th bucket report five created + one "would create" or
#    "missing" for `wakir-federation-routes`. Re-run after the new
#    tag lands to backfill the missing bucket(s); see §3.2.1 + §3.2.2.)
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

### 3.2.1 Backfill the 5th bucket on a pre-Tag-4 cluster (Phase-2 Sprint-4 Tag-4)

Clusters brought up before Sprint-4 Tag-4 have only the four
Phase-1b-consumed buckets. After pulling the Tag-4 runtime onto the
build host, an operator backfills the 5th bucket without churning the
existing four:

```bash
# Plan-only first.
python3 scripts/init-nats-buckets.py --dry-run \
  --bucket wakir-schema-registry-entries
# Expect a single "would_create" action in the JSON report.

# Apply.
python3 scripts/init-nats-buckets.py \
  --bucket wakir-schema-registry-entries
# Expect exit 0 and a single "created" action.

# Full-inventory confirmation:
python3 scripts/init-nats-buckets.py
# Expect: 4 unchanged + 1 unchanged (post-backfill), or
# 4 unchanged + 1 created (if the backfill step above was skipped).
```

The 5th bucket has no Phase-1b consumer, so the backfill can be
performed at any operator-convenient window — there is no read or
write traffic against the new bucket until the Phase-2 schema-registry
storage migration lands. This is the no-downtime upgrade path.

### 3.2.2 Backfill the 6th bucket on a pre-Tag-5 cluster (Phase-2 Sprint-4 Tag-5)

Clusters brought up before Sprint-4 Tag-5 either (a) used the §6.5
hand-creation recipe to materialise `wakir-federation-routes`
out-of-band, or (b) had no V-908 bucket yet (the consumer-side
backend `wirelang.federation.route_registry_nats_kv_backend` would
fail on first read or write against an absent bucket). After
pulling the Tag-5 runtime onto the build host, an operator backfills
the 6th bucket without churning the existing five:

```bash
# Plan-only first.
python3 scripts/init-nats-buckets.py --dry-run \
  --bucket wakir-federation-routes
# Expect a single "would_create" action in the JSON report if the
# bucket is absent; a single "unchanged" if §6.5 hand-creation
# already established it with the documented config; a single
# "drift" if a hand-create used non-documented values (operator
# action: see §6.3 drift recovery).

# Apply (only if the dry-run reported "would_create").
python3 scripts/init-nats-buckets.py \
  --bucket wakir-federation-routes
# Expect exit 0 and a single "created" action.

# Full-inventory confirmation:
python3 scripts/init-nats-buckets.py
# Expect: 5 unchanged + 1 unchanged (post-backfill), or
# 5 unchanged + 1 created (if the backfill step above was skipped).
```

Unlike the 5th bucket, the 6th bucket has a live Wirelang-side
consumer. If the V-908 consumer is actively reading or writing
the bucket during the backfill pass, the operation is still safe
because `init-nats-buckets.py` is read-mostly: it only issues a
`create_key_value` call when the bucket is absent and never mutates
an existing bucket. An operator who wants to coordinate with the
consumer can run the backfill during a maintenance window, but it is
not required. This is the no-downtime upgrade path.

### 3.2.3 Backfill the 7th bucket on a pre-Sprint-5-Tag-2 cluster

Clusters brought up before Sprint-5 Tag-2 have no
`wakir-capability-policies` bucket. There is **no Phase-1b / Phase-2
live consumer** for this bucket, so the absence is silent (no
runtime error, no operator alert). The backfill is purely
preparatory: an operator can run it whenever convenient before the
Phase-3 capability-policy persistence promotion lands. After pulling
the Sprint-5 Tag-2 runtime onto the build host, the no-downtime
backfill is:

```bash
# Plan-only first.
python3 scripts/init-nats-buckets.py --dry-run \
  --bucket wakir-capability-policies
# Expect a single "would_create" action in the JSON report if the
# bucket is absent; a single "unchanged" if a previous pass
# established it with the documented config.

# Apply (only if the dry-run reported "would_create").
python3 scripts/init-nats-buckets.py \
  --bucket wakir-capability-policies
# Expect exit 0 and a single "created" action.

# Full-inventory confirmation:
python3 scripts/init-nats-buckets.py
# Expect: 6 unchanged + 1 unchanged (post-backfill), or
# 6 unchanged + 1 created (if the backfill step above was skipped).
```

Because the 7th bucket has no Phase-1b / Phase-2 consumer, the
backfill cannot cause runtime traffic against the new bucket until
the Phase-3 capability-policy persistence promotion lands. This is
the no-downtime upgrade path; identical reasoning to §3.2.1 (5th
bucket Phase-2-reservation). The cross-import-mirror anchor against
the Wirelang-side `BUCKET_CONFIG` constant lands as a Sprint-5
Tag-N follow-up once the Wirelang-track-owned encoder/decoder
module commits; until then the in-tree mirror against
`wakir-ftd-poisoned` guards the reservation-form shape.

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

1. `nats kv ls` — confirms the six bucket names are present
   (Sprint-4 Tag-5 onward).
2. `nats kv info wakir-schemas` — confirms history/TTL/replicas match
   §1 of this runbook. The same check applies to
   `wakir-schema-registry-entries` since the two buckets share their
   storage config; `nats kv info wakir-federation-routes` confirms the
   V-908 bucket matches the Wirelang-side `BUCKET_CONFIG` (history=5,
   ttl unbounded, 4 KiB max-value).
3. Smoke read-through: from the orchestrator container, hit a known
   schema endpoint and confirm a cache miss populates the bucket on
   first hit and a hit returns from KV on second hit. The relevant
   trace fields are documented in the read-through wrapper module
   docstring.

### 5.1 `check-nats-kv-health` tool (Phase-1b Sprint-2 Tag-6)

The `nats` CLI commands above are fine for a one-off operator check,
but they do not produce a structured report and do not detect
configuration drift the way `init-nats-buckets.py` does. Tag-6 ships
a dedicated read-only tool, `scripts/check-nats-kv-health.py`, that
covers three checks in a single invocation and emits a JSON report
to stdout for downstream tooling (cron-driven monitoring, on-call
triage, CI smoke gates).

What it checks:

| Check | Mechanism | Reports |
| --- | --- |
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

### 5.2 Cron-slot deployment (Phase-1b Sprint-2 Tag-6, operator hint)

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

### 5.3 `check-federation-evaluator-health` tool (Phase-1b Sprint-2 Tag-7)

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
| -------------------------------------- | -------------------------------------------------------------------- |
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

### 6.5 Federation-routes bucket creation (now routine; fallback only) (Phase-1b Sprint-2 Tag-7, flip Phase-2 Sprint-4 Tag-5)

The `wakir-federation-routes` bucket is the V-908 federation route
registry consumed by the N2 evaluator. As of **Phase-2 Sprint-4 Tag-5**
this bucket is included in the `PHASE_1_BUCKETS` inventory of both
`scripts/init-nats-buckets.py` and `scripts/check-nats-kv-health.py`,
so the routine cold-start procedure in §3.2 materialises it together
with the other five buckets. No separate bring-up step is required;
pre-Tag-5 clusters that used this hand-creation recipe are
no-downtime-upgradable via the §3.2.2 backfill recipe.

The hand-creation fallback below remains documented for the rare case
of an out-of-band recreate (e.g. an operator wiped only the V-908
bucket and wants to rebuild it without touching the rest):

```bash
nats kv add wakir-federation-routes \
    --history=5 \
    --ttl=0 \
    --max-value-size=4096 \
    --storage=file \
    --replicas=1 \
    --description="V-908 federation-route registry (Phase-1b)"

# Equivalent via the routine init driver (preferred):
python3 scripts/init-nats-buckets.py --bucket wakir-federation-routes
```

The values mirror the constant
`wirelang.federation.route_registry_nats_kv_backend.BUCKET_CONFIG`
byte-precisely. Dual-anchor contract:
`test_t_tag5_02_sixth_bucket_config_mirrors_wirelang_consumer_bucket_config`
(orchestrator suite) plus the existing
`test_inventory_matches_init_nats_buckets` cross-script parity test
keep all sides aligned. The `scripts/check-federation-evaluator-health.py`
tool verifies the live cluster's match on every run; drift surfaces
as exit code 2 with a per-field `{want, got}` diff.

After bucket creation, populate the registry with the operator's
documented routes (out-of-scope for this runbook; see the V-908
operator playbook). Re-run
`scripts/check-federation-evaluator-health.py` and confirm exit 0.

## 7. History

The sprint-by-sprint follow-up backlog and the per-increment
verification stamps that used to close this runbook were removed in
the Phase-4 public-surface cleanup (ADR-0072). They are addressable
in git history at the tag `archive/pre-phase-4`
(`git show archive/pre-phase-4:docs/orchestrator-nats-kv-phase-1-runbook.md`).
Operational content (§1–§6) is unchanged.
