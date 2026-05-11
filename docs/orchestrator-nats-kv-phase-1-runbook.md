<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Orchestrator NATS-JetStream KV Phase-1 — Operator Runbook

Status: draft, Phase-2 Sprint-4 Tag-5 (Z-B 6th-bucket
`wakir-federation-routes` paired-update — see §1, §6.5, §7 and the
§8 Tag-5 stamp).
Companion to `compose/nats.yaml` (substrate),
`scripts/init-nats-buckets.py` (Phase-1 six-bucket driver),
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
| 1   | Bucket inventory (Phase-1, seven-bucket layout)                    | Tag-2, Sprint-4 Tag-4, Sprint-4 Tag-5, Sprint-5 Tag-2 |
| 2   | Pre-flight check                                                   | Tag-2       |
| 3   | Bring-up (cold start: substrate + buckets-init + tear-down)        | Tag-2, Tag-3 |
| 3.2.1 | Backfill 5th bucket on pre-Tag-4 cluster                         | Sprint-4 Tag-4 |
| 3.2.2 | Backfill 6th bucket on pre-Tag-5 cluster                         | Sprint-4 Tag-5 |
| 3.2.3 | Backfill 7th bucket on pre-Sprint-5-Tag-2 cluster                | Phase-2 Sprint-5 Tag-2 |
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
| 6.5 | Federation-routes bucket creation (now routine; fallback only)     | Tag-7, Phase-2 Sprint-4 Tag-5 |
| 7   | Open follow-ups (sprint-by-sprint backlog)                         | Tag-2..Tag-8, Sprint-3 Tag-2 |
| 7.1 | Build-host activation procedure (nine-step, expanded)              | Sprint-3 Tag-2 |
| 7.1.10 | Post-install live-smoke driver                                  | Sprint-3 Tag-4 |
| 7.2 | systemd-timer wiring + Prometheus textfile-collector adapter       | Sprint-3 Tag-3 |
| 7.3 | Live-NATS-Test-Mode driver (hermetic-default + Mock-vs-Live)       | Phase-2 Sprint-4 Tag-1 |
| 7.4 | First-time live-smoke execution record (host-substrate evidence)   | Phase-2 Sprint-4 Tag-2 |
| 7.5 | Image-digest verification gate (`verify-image-digest.sh`)          | Phase-2 Sprint-4 Tag-3 |
| 7.6 | 5th bucket: `wakir-schema-registry-entries` (Phase-2-reserved)     | Phase-2 Sprint-4 Tag-4 |
| 7.7 | 6th bucket: `wakir-federation-routes` (V-908 routine bring-up)     | Phase-2 Sprint-4 Tag-5 |
| 7.8 | SPIFFE Z-A JWT-SVID container-identity skizze (Z-A preparation)    | Phase-2 Sprint-4 Tag-6 |
| 7.9 | 7th bucket: `wakir-capability-policies` (Phase-3-reserved)         | Phase-2 Sprint-5 Tag-2 |
| 8   | Verification stamps (P5/P7)                                        | Tag-2..Tag-8, Sprint-3 Tag-2..Tag-4, Phase-2 Sprint-4 Tag-1..Tag-6, Phase-2 Sprint-5 Tag-2 |

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
| --------------------------------- | ------- | ---------- | --------- | ------- | -------- | ------------------------------------------------------------------------------------------------------------- |
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
Wirelang-side will be exported by the Reza-owned encoder/decoder module
when it lands (Capability-Token-Layer is Reza-owner per Persona-Matrix
§2); until then this entry stays in reservation-form (no
cross-import-mirror anchor). The Sprint-4-Tag-4 pre-Phase-2-reservation
pattern is the analogue; the Sprint-4-Tag-5 6th-bucket pattern is the
post-consumer-commit anchor that the 7th bucket will reach as a
follow-up. See §7.9 for substance, §3.2.3 for the no-downtime backfill
recipe.

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

### 3.2.1 Backfill the 5th bucket on a pre-Tag-4 cluster

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

### 3.2.2 Backfill the 6th bucket on a pre-Tag-5 cluster

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
Tag-N follow-up once the Reza-owned encoder/decoder module commits;
until then the in-tree mirror against `wakir-ftd-poisoned` guards
the reservation-form shape.

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

### 6.5 Federation-routes bucket creation (now routine; fallback only)

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
- Sprint-3: ~~extend `init-nats-buckets.py` `PHASE_1_BUCKETS` to
  include `wakir-federation-routes` as a fifth bucket so the
  bring-up procedure in §6.5 collapses into the routine `init`
  pass~~ — **done in Phase-2 Sprint-4 Tag-5** as the 6th bucket
  (the 5th-slot was claimed Tag-4 by `wakir-schema-registry-entries`;
  see §7.6). Both `scripts/init-nats-buckets.py` and
  `scripts/check-nats-kv-health.py` now register
  `wakir-federation-routes` as the 6th `PHASE_1_BUCKETS` entry with
  the documented Phase-1b config (history=5, ttl=0, max-value=4096B,
  storage=file, replicas=1) byte-aligned with
  `wirelang.federation.route_registry_nats_kv_backend.BUCKET_CONFIG`.
  §6.5 above describes the new routine bring-up path; the
  hand-creation fallback is retained only for out-of-band recreates.
  Five new hermetic tests (`T-Tag5-01..05`) in
  `test_init_nats_buckets.py` anchor the 6th-bucket contract
  (slot/order, Wirelang-side `BUCKET_CONFIG` mirror, empty-cluster
  create-call shape, single-bucket selector backfill path, idempotent
  replay). One gated-live anchor in `test_check_nats_kv_health.py`
  (`test_smoke_sixth_bucket_present_in_live_inventory`) probes the
  live cluster for the new bucket. Cross-Review Zone B follow-up
  paired-update closes the Sprint-2 Tag-7 Z-B Schluss-Marker open
  follow-up from the Wirelang-side track (Wirelang-track 2026-05-07
  Z-B-Konsument-Memo §4 / Sprint-4 Tag-4 paired-update §1
  "orthogonale federation-routes-Frage zur Klärung in Folge-Box").
- Sprint-3: full systemd-timer wiring for the health-check tool plus
  a Prometheus textfile-collector adapter consuming the JSON report's
  `summary` block. The §5.2 cron snippet is the Phase-1b minimum-viable
  deployment.
- Sprint-3: SPIFFE JWT-SVID auth (Cross-Review Zone A). The
  initialiser currently consumes a token from `WAKIR_NATS_TOKEN`; the
  SVID path will replace this with a workload-API call. The health
  check inherits the same token contract today and will inherit the
  SVID upgrade for free.
- Sprint-3 Tag-2: build-host activation. The Sprint-2 hermetic test
  suite is complete (55 + 4 skipped under `tests/orchestrator/`),
  but four live-smoke contracts are gated on `WAKIR_NATS_LIVE=1`
  and require a build host with `gcc` (for `nats-py` C-extension
  compilation, notably the `nkeys` CFFI dep), a container engine
  (`podman` or `docker`) for the compose substrate, and the `nats`
  CLI for the `kv add` step in §6.5. The expanded nine-step
  activation procedure is documented in §7.1 below; the operator-
  side checklist there carries the per-step footprint estimate,
  reversibility note, and security-review hint that the supervisory-
  board-side approval pass needs to triage. Until that activation,
  the hermetic suite is the production-grade contract surface; the
  live-smoke tests are activation-gated future work.

### 7.1 Build-host activation procedure (Phase-1b Sprint-3 Tag-2)

This sub-section is the operator-facing nine-step procedure that
brings a fresh build host up to the live-smoke-test contract
surface defined in Sprint-2 Tag-6 / Tag-7. It is the public-form
counterpart to the dev-engineering-3-side outbox sketch
`2026-05-07-phase-1b-sprint-3-tag-1-build-host-aktivierung-skizze`
filed for the supervisory-board-side approval pass.

The procedure assumes a Fedora-43-class host (dnf-based) with at
least 2 GB free disk, 2 GB RAM, and 2 cores. apt-based equivalents
(Debian / Ubuntu) substitute trivially; the dnf commands below are
the default. Each step lists: command(s), footprint estimate,
reversibility, security note, verification, and approval-pass
status (whether the supervisory-board-side approval pass needs to
gate the step before execution). The footprint and time estimates
are conjecture (P2): they are derived from upstream package-
metadata (Fedora repo metadata, PyPI, Synadia GitHub releases) and
not from a sandbox install — order-of-magnitude stable, absolute
values may drift ±20 %.

**Total disk footprint (steps 2–8, fresh install):** ~500 MB.
**Total network download (steps 2–8):** ~210 MB.
**Total wallclock (steps 1–8, install-only, excludes approval
latency):** ~15–23 minutes.

#### 7.1.1 Step 1 — pre-check (host platform detection)

Read-only. No approval-pass gate.

```bash
cat /etc/os-release
python3 --version
df -h /var/lib /usr /home
free -h
nproc
```

Verification: `os-release` shows `ID=fedora` and a recent
`VERSION_ID`; `python3 --version` ≥ 3.11; `df` shows ≥ 2 GB free
on `/var/lib` (for podman image storage) and ≥ 1 GB on `/usr`;
`nproc` ≥ 2.

#### 7.1.2 Step 2 — install gcc + python3-devel

C-compile toolchain for any `nats-py` dep-tree C-extensions
(`nkeys` CFFI). Approval-pass gate: yes.

```bash
sudo dnf install -y gcc python3-devel
# apt equivalent:
# sudo apt-get update && sudo apt-get install -y gcc python3-dev
```

Footprint: ~250 MB disk; ~80 MB download.
Reversibility: full (`sudo dnf remove gcc python3-devel`).
Security note: official Fedora repo, signed packages; no third-
party repo; gcc itself exposes no network surface.
Verification: `gcc --version` ≥ 13.x (Fedora-43 default);
`python3-config --includes` returns valid include paths.

#### 7.1.3 Step 3 — install podman + podman-compose

Rootless container engine plus compose-file interpreter. The
Phase-1b compose substrate (`compose/nats.yaml`) targets the
docker-compose v3 schema and is compatible with both podman-
compose and `docker compose`. Approval-pass gate: yes.

```bash
sudo dnf install -y podman podman-compose
# docker-ce alternative requires the docker-ce repo:
# sudo dnf install -y dnf-plugins-core
# sudo dnf config-manager --add-repo \
#   https://download.docker.com/linux/fedora/docker-ce.repo
# sudo dnf install -y docker-ce docker-ce-cli containerd.io \
#   docker-compose-plugin
```

Footprint: ~155 MB disk (podman ~80 MB + conmon/runc ~70 MB +
podman-compose ~5 MB); ~60 MB download.
Reversibility: full (`sudo dnf remove podman podman-compose`).
Container volumes under `~/.local/share/containers/` survive
package-removal; bulk cleanup via `podman system reset` is
destructive and must be approved separately.
Security note: official Fedora repo, signed packages. podman
defaults to rootless — no daemon, no privileged socket.
docker-ce alternative runs a root daemon and exposes
`/var/run/docker.sock`; that is a higher-risk choice and a
strategic-side decision, not a default.
Verification: `podman --version` ≥ 5.x; `podman info` shows
`graphRoot` under the user's home and `runRoot` under `/run/user`.

#### 7.1.4 Step 4 — install the `nats` CLI

Synadia upstream Go binary for bucket inspection, KV-add, and
pub/sub testing. Not packaged in Fedora repos as of Sprint-2
authoring (P2 conjecture, last checked Sprint-2 Tag-3); install
from upstream GitHub release with SHA256 verification.
Approval-pass gate: yes (curl-from-internet plus sudo install).

```bash
# (1) discover the latest release tag:
curl -fsSL \
  https://api.github.com/repos/nats-io/natscli/releases/latest \
  | grep '"tag_name"' | head -1
# (2) download the corresponding linux-amd64 archive (substitute
#     v0.1.x with the discovered tag):
curl -fsSL -o /tmp/nats.zip \
  "https://github.com/nats-io/natscli/releases/download/v0.1.x/nats-0.1.x-linux-amd64.zip"
# (3) download and verify the SHA256SUMS file:
curl -fsSL -o /tmp/SHA256SUMS \
  "https://github.com/nats-io/natscli/releases/download/v0.1.x/SHA256SUMS"
( cd /tmp && sha256sum --check --ignore-missing SHA256SUMS )
# (4) install:
unzip /tmp/nats.zip -d /tmp/nats-cli
sudo install -m 0755 \
  /tmp/nats-cli/nats-0.1.x-linux-amd64/nats \
  /usr/local/bin/nats
rm -rf /tmp/nats.zip /tmp/nats-cli /tmp/SHA256SUMS
```

Alternative (if `go` ≥ 1.21 is already installed):

```bash
go install github.com/nats-io/natscli/nats@latest
# binary lands in $GOPATH/bin or ~/go/bin
```

Footprint: ~25 MB disk; ~10 MB download.
Reversibility: full (`sudo rm /usr/local/bin/nats` or
`rm ~/go/bin/nats`).
Security note: SHA256-verify before `sudo install` is mandatory.
The procedure deliberately avoids the `curl ... | sh` pattern;
each artefact is downloaded to `/tmp` and verified before it is
moved into a privileged location. The two upstream URLs
(`api.github.com/repos/nats-io/natscli/releases/latest` and
`github.com/nats-io/natscli/releases/download/...`) are conjecture
(P2): they follow the GitHub-API and GitHub-Releases conventions
but were not 200-verified during runbook authoring (the authoring
sandbox has no internet egress). The supervisory-board-side
approval pass should perform a one-shot HTTP-200 check on those
two URLs before greenlighting this step.
Verification: `nats --version` returns a non-zero version string;
`nats --help | head -10` prints the upstream usage banner.

#### 7.1.5 Step 5 — install `nats-py` (PyPI, in repo-local venv)

Python async client for the real-nats-py-adapter (Sprint-2 Box-5
follow-up) and the bucket-init driver. Approval-pass gate: yes
(PyPI install, supply-chain surface).

```bash
# precondition: the wakir-runtime repo has been cloned (step 6)
cd ~/wakir-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install nats-py
deactivate
```

Footprint: ~5 MB disk in the venv (nats-py + nkeys + asyncio
deps); ~2 MB download.
Reversibility: full (`rm -rf .venv`).
Security note: `nats-py` is Synadia-published on PyPI; the
maintainer is verifiable on `pypi.org/project/nats-py/`. Pip-
hash-pinning (`pip install --require-hashes -r requirements.txt`)
is a Phase-3 reproducibility item (Sprint-4+) and is not gated by
this step. The repo-local venv pattern is preferred over a global
install so that an `rm -rf .venv` rolls the install back without
affecting the host's system Python.
Verification:

```bash
source .venv/bin/activate
python3 -c "import nats; print(nats.__version__)"
deactivate
```

Expected: a non-zero version string ≥ 2.6 (Sprint-2 Tag-3
authoring baseline; PyPI HEAD may be higher; the API surface used
by the adapter is stable across the 2.x line).

#### 7.1.6 Step 6 — clone the repo and run a compose smoke test

Clone `wakir-runtime`, bring the NATS substrate up via the Tag-3
compose file, ping the server, then bring it back down.
Approval-pass gate: yes (clone + image-pull from internet).

```bash
git clone \
  https://github.com/wakir-labs/wakir-runtime.git \
  ~/wakir-runtime
cd ~/wakir-runtime
podman-compose -f compose/nats.yaml up -d
sleep 10
podman ps  # the nats container should be "Up"
nats --server=nats://localhost:4222 server check connection
podman-compose -f compose/nats.yaml down
```

Footprint: ~30 MB repo + ~25 MB image-pull = ~55 MB disk;
network ~55 MB.
Reversibility: full. `podman-compose down` stops the container.
`podman volume rm <name>` removes the JetStream state volume
(destructive; `nats-jetstream`). `rm -rf ~/wakir-runtime` removes
the repo.
Security note: HTTPS-only clone (no SSH key needed for read-only
access). The compose file pins `nats:2.11-alpine` by tag; the
Sprint-3 image-pipeline-side digest-pin upgrade (Cross-Review
Zone C) replaces the tag with `@sha256:<digest>` once the
build-host operator resolves it. `nats server check connection`
is a read-only operation. If the host's firewall is active, the
NATS port `4222/tcp` may need to be opened temporarily for the
test (`sudo firewall-cmd --add-port=4222/tcp`) and closed again
afterwards.
Verification: `podman ps --filter name=nats` shows one running
container; `nats ... server check connection` exits 0; localhost
roundtrip ≤ 5 ms.

#### 7.1.7 Step 7 — initialise the four Phase-1 KV buckets

Run `scripts/init-nats-buckets.py` against the running NATS
container. Approval-pass gate: yes (first live bucket-write
operation on this host).

```bash
cd ~/wakir-runtime
podman-compose -f compose/nats.yaml up -d
sleep 10
source .venv/bin/activate
python3 scripts/init-nats-buckets.py --server nats://localhost:4222
nats --server=nats://localhost:4222 kv ls
deactivate
```

Footprint: ~5 MB JetStream storage in the `nats-jetstream`
volume.
Reversibility: full. `nats ... kv del <bucket>` removes a single
bucket; `podman volume rm nats-jetstream` is the bulk-cleanup
path (destructive). `podman-compose down` does not touch the
volume.
Security note: the Phase-1b NATS substrate runs without
authentication (Cross-Review Zone A SPIFFE/SVID auth is a
Sprint-3 follow-up). The four buckets are publicly readable and
writable inside the local NATS container. **Do not connect this
substrate to a production NATS without first completing the
Zone-A auth setup.**
Verification:

```bash
nats --server=nats://localhost:4222 kv ls
# expected: four bucket names:
#   wakir-schemas, wakir-aip-cache,
#   wakir-ftd-cache, wakir-ftd-poisoned
nats --server=nats://localhost:4222 kv info wakir-schemas
# expected: bucket details (max-bytes, history, ttl) matching §1
```

For Phase-1b operators who also need the V-908 federation routes
bucket, follow §6.5 immediately after step 7 (one additional
`nats kv add wakir-federation-routes ...` invocation; a Sprint-3
follow-up collapses this into the routine `init` driver pass).

#### 7.1.8 Step 8 — activate the live-smoke regression contract

Re-export `WAKIR_NATS_LIVE=1` and run the gated test suite to
exercise the four live-smoke contracts (Box-5 real-nats-py-
adapter + Tag-6 NATS-KV health + Tag-7 federation-evaluator
health, two of which target the Tag-7 evaluator under §6.5).
Approval-pass gate: yes (first-time live-smoke activation; the
test run is read/write on JetStream state).

```bash
cd ~/wakir-runtime
podman-compose -f compose/nats.yaml up -d
sleep 10
source .venv/bin/activate
WAKIR_NATS_LIVE=1 \
  WAKIR_NATS_SERVER=nats://localhost:4222 \
  pytest tests/orchestrator/ -v
deactivate
podman-compose -f compose/nats.yaml down
```

Expected outcome: 55 hermetic + 4 live-smoke = 59 passed; 0
skipped; 0 failed (assuming step 6.5 has been run for the
federation-routes bucket; otherwise the two §6.5-dependent
live-smoke tests fail with a per-field drift report). Without
`WAKIR_NATS_LIVE=1` the four live-smoke tests stay skipped — that
is the Sprint-2 default and the contract surface for the
build-host-less authoring sandbox.
Footprint: ~5 MB test-output logs.
Reversibility: full. Test data writes leave the four (or five)
KV buckets in a non-empty state; cleanup via `nats ... kv purge
<bucket>` per bucket, or via `podman volume rm nats-jetstream`
for bulk cleanup. The hermetic regression baseline is preserved
(Tag-7 stamp: 55 + 4 skipped); zero-drift verification is the
exit criterion for Sprint-3 Tag-2.
Verification:

```bash
pytest tests/orchestrator/ -v 2>&1 | tail -20
# expected: "59 passed in X.XXs" with WAKIR_NATS_LIVE=1, or
#           "55 passed, 4 skipped" without it.
```

A convenience driver that chains steps 6-8 (image-pull, compose-
up, wait-ready, bucket-init, real-adapter round-trip, KV health
check, teardown) into a single invocation lives at
`scripts/post-install-live-smoke.sh`. The driver is the canonical
post-install verification surface — once steps 2-5 of this section
are done on the build-host, the operator runs the driver and
confirms `highest_exit: 0` from its JSON summary on stdout. See
§7.1.10 for the driver's exit-code contract and CLI surface.

#### 7.1.9 Step 9 — cleanup / rollback procedure

Reverse-sequence for build-host deactivation (Phase-1c hand-off
or post-Sprint-3 cleanup). Approval-pass gate: yes (destructive:
volume removal, package removal).

```bash
# (1) compose-down + volume cleanup (destructive: state loss)
cd ~/wakir-runtime
podman-compose -f compose/nats.yaml down
podman volume ls --filter name=nats
podman volume rm nats-jetstream

# (2) repo removal
deactivate 2>/dev/null || true
rm -rf ~/wakir-runtime

# (3) pip packages — non-issue when venv was used
# global-install rollback (only if step 5 was global):
# pip uninstall nats-py

# (4) nats CLI removal
sudo rm /usr/local/bin/nats

# (5) image cleanup
podman image rm nats:2.11-alpine

# (6) optional system-package removal (if the host is no longer
#     used as a build host)
sudo dnf remove gcc python3-devel podman podman-compose
sudo dnf autoremove
```

Footprint: reverse operation; ~460 MB disk freed.
Security note: `podman volume rm nats-jetstream` is destructive;
JetStream state is not recoverable afterwards. Sprint-2 has no
state of operational value, so the bulk path is safe; Sprint-3
Phase-3 introduces a JetStream backup pipeline before this
becomes a live concern. `dnf remove` is a clean rollback for
system packages.
Verification:

```bash
which gcc podman nats 2>&1   # all "not found" expected
ls ~/wakir-runtime 2>&1       # "No such file or directory" expected
```

#### 7.1.10 Post-install live-smoke driver

`scripts/post-install-live-smoke.sh` chains the seven post-step-5
verification actions (image-pull, compose-up, wait-ready, bucket-
init, real-`nats-py` adapter round-trip, NATS-KV health check,
teardown) into a single idempotent invocation. It is the canonical
"build-host activation done" smoke; the gated pytest run in §7.1.8
is the broader regression contract that runs after the smoke.

```bash
# Default: podman engine, full run, volume dropped on teardown.
cd ~/wakir-runtime
source .venv/bin/activate
./scripts/post-install-live-smoke.sh
deactivate

# Useful operator-driven variants:
./scripts/post-install-live-smoke.sh --dry-run         # plan only
./scripts/post-install-live-smoke.sh --skip-teardown   # leave up
./scripts/post-install-live-smoke.sh --keep-volume     # state survives
./scripts/post-install-live-smoke.sh --no-real-adapter # skip step 6
./scripts/post-install-live-smoke.sh --engine docker   # docker variant
```

Stdout is a single-line JSON summary keyed by the seven step names,
each with a `result` (`ok`/`fail`/`skip`) and a `duration_s`. Stderr
is a human-readable line log; one `[step N/7]` line per step plus
an `ok`/`error` closing line. The exit code mirrors the strictest
sub-step:

| exit | meaning                                              |
| ---- | ---------------------------------------------------- |
| 0    | all steps clean                                      |
| 1    | preflight failure (a tool is missing or `.venv` not there) |
| 2    | substrate up or wait-ready failed                    |
| 3    | bucket init exit non-zero                            |
| 4    | real-adapter round-trip failed                       |
| 5    | KV health check exit non-zero                        |
| 6    | teardown failed (substrate state may persist)        |

The driver's test plan lives at
`tests/orchestrator/test_post_install_live_smoke_plan.md` and
covers fourteen cases (one happy path, five operator-driven
variants, six fault-injection scenarios, two idempotency
re-runs). The plan is markdown rather than pytest because the
driver needs a real container substrate; a hermetic pytest
would either lose that property or duplicate it as a mock. The
existing hermetic compose-shape regression in
`tests/orchestrator/test_compose_nats.py` is the static-side
complement of this live-side smoke.

A first-time run on a fresh build-host should be operator-
supervised (watch the stderr line log); subsequent runs (post-
image-bump, post-bucket-inventory-change) can be unattended in
CI. A Prometheus textfile-collector wrapper for the driver is
a Sprint-4 follow-up; for now the JSON summary on stdout is the
machine-parseable hook (`./scripts/post-install-live-smoke.sh |
jq '.highest_exit'`).

#### 7.1.11 Risk register

| risk                                                       | likelihood | impact      | mitigation                                                                  |
| ---------------------------------------------------------- | ---------- | ----------- | --------------------------------------------------------------------------- |
| dnf repo slowdown / mirror offline                         | low        | medium      | retry; alternative mirror URL                                               |
| `nats` CLI GitHub release outage                           | low        | medium      | fallback: `go install` (step 4 alternative)                                 |
| `nats-py` PyPI version conflict                            | low        | low         | repo-local venv isolates; hash-pinning is a Sprint-4 item                   |
| compose image-pull drift (`nats:2.11-alpine` tag move)     | low        | medium      | digest-pin upgrade path documented in §3.1 (Cross-Review Zone C)            |
| build-host disk full                                       | low        | high        | step 1 pre-check verifies ≥ 2 GB free                                       |
| approval-pass latency stalls activation                    | medium     | medium      | the dev-engineering-3-side outbox sketch is the pre-approval staging item   |
| upstream API drift (`nats-py` 2.x → 3.x)                   | low        | low         | hermetic suite stays green; the live-smoke adapter is robust to 2.x→3.x    |

#### 7.1.12 Cross-review zone touch

| zone                                                  | step touches                                    | sprint follow-up                                 |
| ----------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------ |
| Zone A (container-identity × identity-spec)           | none directly (Sprint-3 SPIFFE item is separate) | Sprint-3 SPIFFE/SVID auth integration            |
| Zone B (NATS schema × wirelang)                       | step 7 + step 8 exercise the registry surface   | Sprint-3 paired-update with the wirelang-eng track |
| Zone C (image pipeline × OTS)                         | step 6 image-pull (`nats:2.11-alpine`)          | Sprint-3 digest-pin upgrade (§3.1)               |
| Zone D (Phala × identity-bridge)                      | none                                            | Sprint-3+                                        |

The Zone-C touch in step 6 is operationalised under the existing
ack/modify/veto memo filed in the dev-engineering inbox (slug
`2026-05-07-kai-zone-c-image-pin-nats-2.11-alpine`); no new
zone-C consensus is required for this sub-section.
- Phase-3: replicated JetStream (replicas > 1) requires a multi-node
  cluster topology. Bucket spec changes are limited to `replicas`; the
  initialiser already plumbs that field end-to-end and the health
  check's drift detector compares it.

### 7.2 systemd-timer wiring + Prometheus textfile-collector adapter (Phase-1b Sprint-3 Tag-3)

The cron snippet in §5.2 is the same-day minimum-viable deployment
for the NATS-KV health check. This sub-section is the production
form: two systemd timers on a 5-minute cadence, two oneshot service
units that capture the JSON report to a fixed path, one template-
unit textfile adapter that translates the JSON into Prometheus
textfile-collector format, and a small alerting rule set on top of
the resulting metrics. The wiring is shipped under
`scripts/systemd/` and `scripts/prometheus-textfile-adapter.py`.

**Why systemd-timer over cron.** The cron path in §5.2 leaves three
gaps: cron's environment is brittle (the operator notes called out
the `WAKIR_NATS_TOKEN` injection problem), cron does not capture
exit-code distribution into a journal that an on-call can grep, and
cron offers no observable surface for "the timer is itself stuck"
beyond the absence of the JSON file. systemd timers solve all three:
`EnvironmentFile=` is a clean knob, `journalctl -u
wakir-nats-kv-health.service` shows the per-run distribution, and a
stuck timer is observable both via `systemctl list-timers` and via
the textfile-adapter's last-run-seconds gauge in Prometheus.

#### 7.2.1 Operator install

Drop the unit files in place, create the env files (one per check),
ensure the log directory exists, and reload:

```bash
sudo install -m 0644 \
    scripts/systemd/wakir-nats-kv-health.service \
    scripts/systemd/wakir-nats-kv-health.timer \
    scripts/systemd/wakir-federation-evaluator-health.service \
    scripts/systemd/wakir-federation-evaluator-health.timer \
    scripts/systemd/wakir-prometheus-textfile-adapter@.service \
    /etc/systemd/system/
sudo install -d -m 0750 /var/log/wakir
sudo install -d -m 0755 /var/lib/node_exporter/textfile_collector

# Per-check env files (read-only NATS token, optional URL overrides).
sudo install -d -m 0750 /etc/wakir
sudo install -m 0640 /dev/null /etc/wakir/nats-kv-health.env
sudo install -m 0640 /dev/null /etc/wakir/federation-evaluator-health.env
# Edit and add WAKIR_NATS_TOKEN=... in each.

sudo systemctl daemon-reload
sudo systemctl enable --now wakir-nats-kv-health.timer
sudo systemctl enable --now wakir-federation-evaluator-health.timer
```

The unit files ship with `WorkingDirectory=/opt/wakir-runtime`. If
the orchestrator host installs the runtime elsewhere, edit the unit
or use a drop-in (`systemctl edit wakir-nats-kv-health.service`)
rather than mutating the upstream file.

#### 7.2.2 Cadence and timer tuning

Both timers fire every 5 minutes (`OnUnitActiveSec=5min`) with a
`RandomizedDelaySec=30s` jitter to spread load across hosts when
multiple orchestrators are deployed. `OnBootSec=2min` (KV check)
and `OnBootSec=3min` (federation check) stagger the first run after
boot so the KV check completes (or fails) before the federation
check runs against potentially-empty buckets. `Persistent=true`
replays a missed cycle on next boot; the health checks are
idempotent so a late replay simply rewrites the JSON.

#### 7.2.3 Adapter contract

`scripts/prometheus-textfile-adapter.py` is a single-pass, stdlib-
only translator. It takes a JSON report on `--input` and writes a
textfile-collector `.prom` on `--output` via an atomic rename. It
auto-detects the report flavour by inspecting the top-level keys
(`checks` + `summary` → NATS-KV; `snapshot` + `bucket_name` →
federation-evaluator); ambiguous or unknown payloads are rejected
with exit 1.

The adapter is wired as `OnSuccess=` and `OnFailure=` consequence
units on each health-check service, so the textfile is rewritten
exactly once per timer cycle without an additional timer. The
adapter unit is a template (`wakir-prometheus-textfile-adapter@`)
instantiated with the report basename:

* `wakir-prometheus-textfile-adapter@nats-kv-health.service`
* `wakir-prometheus-textfile-adapter@federation-evaluator-health.service`

The atomic-rename contract guarantees node_exporter never reads a
partial file.

Adapter exit codes:

* `0` — output file written.
* `1` — input missing, malformed JSON, or unknown flavour.
* `2` — output directory not writable.

#### 7.2.4 Emitted metrics

| metric | flavour | type | meaning |
| ------ | ------- | ---- | ------- |
| `wakir_nats_kv_jsz_up{servers}` | nats-kv | gauge | 1 if `/jsz` returned 2xx, else 0 |
| `wakir_nats_kv_buckets_total` | nats-kv | gauge | Documented bucket count (Phase-1: 4) |
| `wakir_nats_kv_buckets_{ok,missing,drift,error}` | nats-kv | gauge | Per-status counts from the summary block |
| `wakir_nats_kv_bucket_status{bucket}` | nats-kv | gauge | Per-bucket status (`0=ok 1=missing 2=drift 3=error`) |
| `wakir_nats_kv_adapter_last_run_seconds` | nats-kv | gauge | Unix timestamp of the most recent adapter run |
| `wakir_federation_evaluator_jsz_up{servers}` | federation | gauge | 1 if `/jsz` returned 2xx, else 0 |
| `wakir_federation_evaluator_bucket_status{bucket}` | federation | gauge | Federation-routes bucket status (same encoding) |
| `wakir_federation_evaluator_routes_{total,active,expired,not_yet_active,with_wat_anchor}` | federation | gauge | Snapshot counters |
| `wakir_federation_evaluator_poisoned_keys_total` | federation | gauge | Poisoned-key count from the snapshot |
| `wakir_federation_evaluator_probe_status` | federation | gauge | Optional N2-evaluator probe (`0=ok 1=skipped 2=reject 3=error`) |
| `wakir_federation_evaluator_adapter_last_run_seconds` | federation | gauge | Unix timestamp of the most recent adapter run |

The status enums are stable; downstream alerts rely on the integer
encoding rather than label values.

#### 7.2.5 Suggested alerting rules

```yaml
groups:
  - name: wakir-orchestrator-substrate
    rules:
      - alert: WakirNatsKvJsZUnreachable
        expr: wakir_nats_kv_jsz_up == 0
        for: 5m
        labels: {severity: warning, team: orchestrator}
        annotations:
          summary: "NATS /jsz unreachable for 5m on {{ $labels.servers }}"

      - alert: WakirNatsKvBucketDrift
        expr: wakir_nats_kv_buckets_drift > 0
        for: 10m
        labels: {severity: warning, team: orchestrator}
        annotations:
          summary: "NATS-KV bucket configuration drift on {{ $labels.servers }}"

      - alert: WakirNatsKvBucketMissing
        expr: wakir_nats_kv_buckets_missing > 0
        for: 5m
        labels: {severity: critical, team: orchestrator}
        annotations:
          summary: "Documented NATS-KV bucket missing"

      - alert: WakirHealthCheckStale
        expr: time() - wakir_nats_kv_adapter_last_run_seconds > 900
        for: 5m
        labels: {severity: warning, team: orchestrator}
        annotations:
          summary: "NATS-KV health adapter has not run in 15m"

      - alert: WakirFederationRoutesPoisoned
        expr: wakir_federation_evaluator_poisoned_keys_total > 0
        for: 10m
        labels: {severity: warning, team: orchestrator}
        annotations:
          summary: "Federation route registry has poisoned keys"
```

The 5/10/15-minute windows match the timer cadence: a 5-minute
window guarantees one full cycle between the alert window and the
next-run-cycle, eliminating false positives from a single missed
cycle. The "Stale" alert fires from the adapter's last-run-seconds
gauge; this is the symptom that catches "the systemd timer itself
hung" — the JSON file would still be on disk but the gauge would
stop advancing.

#### 7.2.6 What this sub-section does not cover

* **Build-host gating.** The systemd units assume the build-host
  activation procedure (§7.1) has been completed: `nats-py` must be
  on `PATH` inside the venv, and the federation-evaluator unit
  additionally needs the wirelang-eng modules importable via
  `PYTHONPATH`. The unit files set this up declaratively; the
  *contents* of the venv are §7.1's responsibility.
* **node_exporter installation.** The textfile-collector path
  (`/var/lib/node_exporter/textfile_collector`) assumes node_exporter
  is already installed and configured to read it. That is a
  deployment-side decision (typically already in place on hosts that
  run Prometheus); the orchestrator runbook does not prescribe a
  node_exporter install.
* **SVID auth.** The unit files consume `WAKIR_NATS_TOKEN` from the
  per-check env file; the SPIFFE/SVID upgrade (Sprint-3 Cross-Review
  Zone A) replaces this with a workload-API call. The unit contract
  remains the same — only the env-file content changes — so the
  upgrade is a drop-in.
* **Multi-host federation.** The recommended `RandomizedDelaySec`
  jitter is the only built-in concession to multi-host deployments;
  for Phase-1b's single-node assumption it is over-engineered but
  cheap. A genuine multi-host topology is a Phase-3 follow-up.

The hermetic test suite for the adapter
(`tests/orchestrator/test_prometheus_textfile_adapter.py`, 29
tests) covers flavour detection, render output for both flavours,
atomic-write semantics, and the CLI exit-code matrix.

### 7.3 Live-NATS-Test-Mode driver (Phase-2 Sprint-4 Tag-1)

The §7.1.10 post-install live-smoke driver and the §7.2 systemd
wiring both presuppose that the pytest suite can be trusted to flag
a regression *before* the build-host activation pass declares done.
That trust is gated on a single contract: a Mock-vs-Live byte-identity
cross-validation of the planner output that the orchestrator container's
init step parses on start. This sub-section documents the
operator-facing driver for that contract.

**Why a dedicated driver over re-using §7.1.10.** The post-install
live-smoke driver (`scripts/post-install-live-smoke.sh`) brings the
substrate up, initialises buckets, and runs a single non-destructive
round-trip — it is the substrate-side gate for the build-host
activation pass. The Live-NATS-Test-Mode driver
(`scripts/run-live-smoke-tests.sh`) is the pytest-side gate: it
consumes an already-up substrate and runs the full gated test
selection against it, with byte-identity cross-validation on top.
Splitting the two lets an operator re-run only the pytest gate on a
stable substrate without paying the compose-up cost again.

**Operator-hand-only.** ADR-0051 (CEO-side-sandbox vs. host-operations
trennung) was rejected, but the operative practice it formalised
remains as an operative-side hand-off rule: the CEO-side sandbox cannot
reach the host NATS substrate, so live-NATS smoke is driven from the
operator hand and never from inside the orchestrator container or a
CEO-side-spawned agent. The driver enforces this implicitly via its
pre-flight (a CEO-side-sandbox invocation hits a TCP-unreachable probe
and exits 1 before any test runs).

#### 7.3.1 Hermetic-default + Live opt-in contract

The Sprint-4 Tag-1 cross-validation suite
(`tests/orchestrator/test_live_nats_cross_validation.py`) ships
four hermetic tests that run on every pytest invocation plus two
live-gated tests that activate only when `WAKIR_NATS_LIVE=1` is set
in the environment. The hermetic tests pin the byte-shape of
`InitReport.to_json()` for the two cross-validated scenarios; the
live tests assert that the real cluster produces the same byte
sequence as the in-memory mock.

| scenario      | cluster state           | dry-run | expected statuses (×4)                |
| ------------- | ----------------------- | ------- | ------------------------------------- |
| empty         | no Phase-1 buckets      | yes     | all four `would_create`               |
| populated     | all four buckets at spec | yes     | all four `unchanged`                  |

Both scenarios use `dry_run=True`, so the live cluster is touched
read-only (the planner only calls `js.key_value` and `kv.status()`).
Drift detection still runs — if a bucket exists with a divergent
configuration, the live test reports `drift` instead of `unchanged`,
diverges from the mock baseline, and fails byte-identity. That
divergence is the contract: a quiet drift in the substrate becomes
a loud pytest failure.

#### 7.3.2 Operator install

The driver and the test suite ship with the repo; no install step
beyond the §7.1 build-host activation is required. Once `nats-py`
is importable in `.venv/` and the compose substrate is up on
`localhost:4222`, run:

```bash
# Scenario A: empty cluster (compose up, no init).
sudo systemctl stop wakir-nats-kv-health.timer 2>/dev/null || true
podman-compose -f compose/nats.yaml down -v
podman-compose -f compose/nats.yaml up -d
scripts/run-live-smoke-tests.sh --scenario empty

# Scenario B: populated cluster (after bucket init).
.venv/bin/python3 scripts/init-nats-buckets.py
scripts/run-live-smoke-tests.sh --scenario populated

# Both scenarios in one session (operator drives the state machine
# between invocations; the driver does not).
scripts/run-live-smoke-tests.sh --scenario both
```

The driver re-uses the existing gated live-smoke suites
(`test_init_nats_buckets`, `test_check_nats_kv_health`,
`test_check_federation_evaluator_health`) under the same
`WAKIR_NATS_LIVE=1` flag, so a single invocation exercises all four
gated test modules. `--no-cross-validation` runs the legacy three
without the new byte-identity suite.

#### 7.3.3 Pre-flight probes

The driver runs four pre-flight probes before invoking pytest:

| probe         | command-equivalent                                | gates                |
| ------------- | ------------------------------------------------- | -------------------- |
| TCP 4222      | `bash -c '>/dev/tcp/127.0.0.1/4222'` (2 s timeout) | hard fail            |
| HTTP /jsz     | `curl --fail --max-time 2 ${JSZ_URL}`             | hard fail            |
| `nats` CLI    | `nats server ping --count 1 --timeout 2s`         | best-effort (skip OK) |
| venv          | `python3 -c 'import nats'` + `pytest` exists      | hard fail            |

The `nats` CLI probe is best-effort because a build-host without the
`nats` CLI installed is still valid for the pytest gate (the
hermetic + gated-live suites do not call the CLI). Both TCP+JSZ
probes are short-timeout to keep a wedged box bounded.

The driver emits a JSON summary on stdout (machine-parseable) and a
human-readable line log on stderr. Exit codes:

| code | meaning                                                     |
| ---- | ----------------------------------------------------------- |
| 0    | pre-flight ok, pytest exit 0                                |
| 1    | pre-flight failed (NATS unreachable, nats-py missing, etc.) |
| 2    | pytest reported failure                                     |
| 3    | bad CLI argument                                            |

#### 7.3.4 Cross-validation byte-identity contract

The byte-identity contract is *deliberately strict*. The planner
output is constructed via `json.dumps(..., sort_keys=True,
separators=(",", ":"))`, so the only sources of nondeterminism are
the action list order (driven by `PHASE_1_BUCKETS` ordering, fixed)
and any field that differs between the mock and the real
`KeyValueStatus` surface. The hermetic test
`test_hermetic_to_json_is_byte_stable_across_invocations` locks
deterministic JSON across consecutive invocations; the live test
catches transport drift.

If a future `nats-py` release surfaces a new field on `KeyValueStatus`
that the planner reads, the mock must be updated in lock-step or the
live test will fail. That is by design: the mock is the contract;
the live test is the regression detector. The runbook does not pin
`nats-py` (see §8) precisely because the byte-identity contract is
the binding artefact, not a version string.

#### 7.3.5 Failure modes and recovery

The live tests `skipTest` (not `fail`) if the cluster is in an
unexpected state: an `--scenario empty` run against a populated
cluster, or vice versa. The skip diagnostic prints the observed
status map so the operator can correct the state and re-run. This
matches the §6 recovery posture — operator-driven state corrections,
never silent overwrite.

A genuine byte-identity failure (live and mock disagree on
`to_json()` output) means one of three things:

1. **Mock drift.** The mock and the real `KeyValueStatus` have
   diverged; the mock must be updated. Bisect against the
   `nats-py` changelog.
2. **Live cluster drift.** An operator changed a bucket out of band
   (e.g. via `nats kv edit`). Re-run `scripts/init-nats-buckets.py`
   in plan mode to see which bucket diverged; reconciliation is the
   §6.3 procedure.
3. **Planner regression.** A change to `init-nats-buckets.py` broke
   the JSON contract. Revert the offending commit and re-add with a
   matching hermetic baseline update.

The live test failure message prints both byte sequences side by
side so the diagnosis can be done from the operator log without a
second invocation.

#### 7.3.6 What this sub-section does not cover

* **Substrate bring-up.** §7.1.10 owns that. Run
  `scripts/post-install-live-smoke.sh` first; once it reports clean,
  the §7.3 driver consumes the same substrate.
* **SPIFFE/SVID auth.** The driver reads `WAKIR_NATS_TOKEN` if set;
  the Cross-Review Zone A SVID upgrade replaces the token with a
  workload-API call without changing the driver's CLI surface.
* **Adapter-side cross-validation.** The Prometheus textfile-collector
  adapter (§7.2.3) has its own 29-test hermetic suite; no live cross-
  validation is required because the adapter is a pure JSON-to-text
  translator with no NATS surface.
* **Multi-host federation.** The pre-flight TCP probe is loopback by
  default. A multi-host scenario sets `WAKIR_NATS_URL` to the remote
  endpoint; the operator owns the consequences of pointing a
  destructive (`compose down -v` between scenarios) workflow at a
  shared cluster.

### 7.4 First-time live-smoke execution record (Phase-2 Sprint-4 Tag-2)

The §7.3 driver is *substrate-agnostic by design* — it presupposes that
some operator hand brought the NATS substrate up before the pytest gate
runs. This sub-section is the first execution record against a real
host substrate, written down so a future operator who reads §7.3 has
empirical evidence — not just contract prose — that the byte-identity
gate actually fires on a live cluster.

**Substrate.** Aufsichtsrat-Operator brought up a `wakir-nats` container
on the workstation host at 2026-05-11 ~16:30 CEST (operative-side
hand pass; the CEO-side sandbox itself remains closed per
ADR-0051-rejected-but-retained operative practice). Substrate-side
smoke at hand-off:

| probe        | result                                                  |
| ------------ | ------------------------------------------------------- |
| TCP 4222     | reachable from toolbox loopback                         |
| HTTP /jsz    | 200 OK; `streams: 0` (empty JetStream)                  |
| server id    | `NDYYBKTP4TOVSAYZ2IKVYTEAYCFKK2YRF7YEYAB2ZIHXUZZ32THQQ3PO` |
| store dir    | `/tmp/nats/jetstream` (ephemeral, container-scoped)     |

**Driver run, Phase A — empty cluster.** `WAKIR_NATS_LIVE=1 bash
scripts/run-live-smoke-tests.sh` against a fresh substrate
(`streams: 0`) at 2026-05-11T16:53Z:

| field                | value                                          |
| -------------------- | ---------------------------------------------- |
| preflight tcp_4222   | ok                                             |
| preflight jsz_8222   | ok                                             |
| preflight nats-cli   | unreachable (CLI not on toolbox `PATH`; documented best-effort) |
| preflight venv       | ok (after `.venv/bin/pip install nats-py` → 2.14.0) |
| pytest exit          | 0                                              |
| tests passed         | 55                                             |
| tests skipped        | 1                                              |
| live empty matched   | byte-identical (`would_create` × 4)            |
| live populated       | skipped (cluster not populated; expected)      |

Skip diagnostic for `test_live_populated_cluster_...` was exactly the
§7.3.5 documented behaviour: skip-not-fail with the observed status
map printed, no false-positive failure.

**Driver run, Phase B — populated cluster.** `.venv/bin/python3
scripts/init-nats-buckets.py --servers nats://127.0.0.1:4222` created
the four Phase-1 buckets (`wakir-schemas`, `wakir-aip-cache`,
`wakir-ftd-cache`, `wakir-ftd-poisoned`; all four `status:created`,
summary `{created:4, total:4}`). Immediately followed by
`WAKIR_NATS_LIVE=1 bash scripts/run-live-smoke-tests.sh` again at
2026-05-11T16:54Z:

| field                | value                                          |
| -------------------- | ---------------------------------------------- |
| preflight all probes | identical to Phase A (only `nats-cli` flagged) |
| pytest exit          | 0                                              |
| tests passed         | 55                                             |
| tests skipped        | 1                                              |
| live populated       | byte-identical (`unchanged` × 4)               |
| live empty           | skipped (cluster no longer empty; expected)    |

**Byte-identity proof (out-of-band SHA256).** As an additional check
beyond the assertEqual inside the pytest gate, the populated-scenario
JSON was captured from both transports separately and digested:

```
live JSON  len=594 sha256=4eceed0338840f34696fd7913e95566d25637fdcde44978727a8a40cf65da9cc
mock JSON  len=594 sha256=4eceed0338840f34696fd7913e95566d25637fdcde44978727a8a40cf65da9cc
match: True
```

The two byte sequences are character-for-character identical across
the live `nats-py` 2.14.0 transport and the in-memory `_MockJetStream`
surface: `nats-py` 2.14.0's `KeyValueStatus` does not surface a field
the mock omits, and vice versa. The §7.3.4 contract is met in
practice, not just by hermetic baseline.

**Side-effects on the live substrate.** The Phase-1 buckets are now
present on the host `wakir-nats` container. Per the operator-side
hand-off note, the Operator will `podman stop wakir-nats` later this
evening, which discards the ephemeral `/tmp/nats/jetstream` store;
the buckets do not persist beyond that. Operators reproducing this
record must redo the `init-nats-buckets.py` step after any
subsequent substrate bring-up.

**What this record demonstrates that the §7.3 contract alone does
not.**

1. The state-machine semantics (operator drives cluster between
   `empty` and `populated`; driver does not) work in practice: a
   single substrate session covered both scenarios via one
   `init-nats-buckets` invocation between two `run-live-smoke-tests.sh`
   runs.
2. The `nats-py` 2.14.0 transport produces byte-output indistinguishable
   from the mock for the two cross-validated scenarios. No drift
   reconciliation was required for this release.
3. The pre-flight venv probe correctly distinguishes a usable venv
   from one without `nats-py`: the same `.venv/` reported `venv: ok`
   only after `pip install nats-py` and `venv: missing` before.
   That gate is what keeps a CEO-side-sandbox-equivalent run from
   silently activating the live tests under false pretences.
4. The `nats` CLI probe being best-effort is operationally correct on
   a toolbox that does not ship `nats`: the gate still fires and the
   live tests still run. A build host with `nats` CLI installed will
   see `nats_cli_ping: ok`; a toolbox without it sees `unreachable`
   and the run still completes.

**What this record explicitly does not cover.**

* **Persistent storage.** The host substrate writes JetStream to
  `/tmp/nats/jetstream`, which does not survive a container restart.
  The Phase-1b build-host activation pass (§7.1) uses
  `compose/nats.yaml` with a named volume; a build-host execution
  record is a separate Sprint-4 deliverable (Tag-3 onward) and is
  not covered here.
* **`nats` CLI probe in `ok` state.** The toolbox does not ship the
  CLI; a build-host activation pass that does will produce a
  `nats_cli_ping: ok` line in the JSON summary. The driver does not
  treat the absence of the CLI as a fault.
* **Token-auth path.** The host substrate is no-auth (Phase-1
  default). `WAKIR_NATS_TOKEN` was unset throughout; the
  cross-validation contract is independent of the auth surface.
* **SPIFFE/SVID.** Cross-Review Zone A is unchanged by this record.

**Reproduction recipe.**

```bash
# Pre-conditions: live wakir-nats container reachable on host:4222.
cd /path/to/wakir-runtime
.venv/bin/pip install nats-py            # if not already present

# Phase A — empty cluster gate.
curl -fsS 'http://127.0.0.1:8222/jsz' | jq '.streams'   # expect: 0
WAKIR_NATS_LIVE=1 bash scripts/run-live-smoke-tests.sh
# expect: pytest_exit=0, 55 passed, 1 skipped (populated)

# Phase B — populate cluster, then gate.
.venv/bin/python3 scripts/init-nats-buckets.py \
    --servers nats://127.0.0.1:4222
curl -fsS 'http://127.0.0.1:8222/jsz' | jq '.streams'   # expect: 4
WAKIR_NATS_LIVE=1 bash scripts/run-live-smoke-tests.sh
# expect: pytest_exit=0, 55 passed, 1 skipped (empty)
```

If both runs report `pytest_exit: 0` with one scenario passed and the
other scenario skipped (for the documented reason), the byte-identity
contract holds on the live substrate for this release.

### 7.5 Image-digest verification gate (Phase-2 Sprint-4 Tag-3)

`scripts/verify-image-digest.sh` is the operator-facing verification
gate for the `compose/nats.yaml` image-pin. The script has three
modes:

| Mode | Flags | Touches network? | Requires cosign? | Use case |
| --- | --- | --- | --- | --- |
| Hermetic (default) | none | no | no | Sandbox + CI smoke; parses the compose file, asserts the image-pin is in one of the accepted forms, validates digest-hex shape |
| Strict | `--strict` | no | no | Build-host policy gate; fails exit 2 on tag-only pins |
| Registry cross-reference | `--with-registry` | yes (Docker Hub public registry API) | no | Build-host CI smoke; verifies the compose-pin digest matches the upstream tag's current manifest-list digest |
| Cosign verify | `--with-cosign` | depends on cosign | yes | Build-host advanced trust gate; signature-based attestation (Phase-1b: official NATS image is not currently signed by Synadia, so this mode is a future opt-in) |

Default invocation:

```bash
scripts/verify-image-digest.sh
# => human log on stderr, JSON summary on stdout
```

JSON-only mode (for CI pipelines that consume the summary):

```bash
scripts/verify-image-digest.sh --json | jq .
```

Strict mode (rejects tag-only pins):

```bash
scripts/verify-image-digest.sh --strict
# exit 2 if compose is tag-only; exit 0 if digest-pinned
```

Pin-to-a-specific-digest mode (CI smoke gate that pins both the tag
and the digest):

```bash
scripts/verify-image-digest.sh \
    --expected-tag nats:2.11-alpine \
    --expected-digest e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00
```

Registry cross-reference (build-host operator hand only — the CEO-
side authoring sandbox does not use this mode per the operative
sandbox-host trennung):

```bash
scripts/verify-image-digest.sh --with-registry
# resolves https://registry.hub.docker.com/v2/repositories/library/nats/tags/2.11-alpine
# and asserts the manifest-list digest matches the compose-pin
```

Cosign verify (future opt-in once upstream signs):

```bash
scripts/verify-image-digest.sh --with-cosign
# requires cosign on PATH; exits 1 if missing
# Phase-1b: official NATS image is unsigned; this mode currently
# returns verify-failed, which is a documented gap not a substrate
# fault
```

Exit-code contract:

| Code | Meaning |
| --- | --- |
| 0 | Image-pin accepted (form + optional cross-reference) |
| 1 | Pin malformed, compose file missing, registry probe failed, cosign requested but binary missing, cosign verify failed |
| 2 | Tag-only pin under `--strict` (rejected by policy, not by substrate) |

Cross-Review Zone-C (digest-pin upgrade over the Sprint-2-Tag-3
tag-pin) lands here: the manifest-list digest in `compose/nats.yaml`
is the substantive trust anchor for Phase-1b; the hermetic gate
catches drift between the compose file and the test fixture; the
opt-in registry cross-reference catches drift between the compose
file and the upstream tag.

The hermetic gate is exercised in CI by
`tests/orchestrator/test_verify_image_digest.py` (10 hermetic tests:
digest-pin form, tag-only fallback, malformed pin rejection,
`--strict` mode, `--expected-digest` mismatch, `--expected-tag`
mismatch, executable bit, syntax gate).

### 7.6 5th bucket: `wakir-schema-registry-entries` (Phase-2 Sprint-4 Tag-4)

Sprint-4 Tag-4 closed the Z-B paired-update slot by adding
`wakir-schema-registry-entries` as the 5th bucket in
`PHASE_1_BUCKETS`. The bucket is **Phase-2-reserved** — there is no
Phase-1b consumer module that reads or writes it. It is registered
during cluster bring-up so the Phase-2 schema-registry storage
migration (Wirelang-side OI-7-Phase-2 slot) does not require a manual
`nats kv add` step on the live cluster.

**Bucket-config (mirrors `wakir-schemas`):**

| field            | value         |
| ---------------- | ------------- |
| history          | 5             |
| ttl              | unbounded     |
| max_value_size   | 256 KiB       |
| storage          | file          |
| replicas         | 1             |

The deliberate mirror is the design property: the Phase-2 migration
off the cache bucket onto the storage bucket is a value-copy without
any config-drift step. The `init-nats-buckets.py` planner enforces the
documented config; a drift report on the new bucket surfaces in the
operator log under `wakir-schema-registry-entries` exactly like the
four pre-Tag-4 buckets.

**Hermetic tests (Tag-4 additions):**

`tests/orchestrator/test_init_nats_buckets.py` carries five new tests
under the `T-Tag4-01..05` series:

| # | Name (short) | What it pins |
| --- | --- | --- |
| T-Tag4-01 | `..._is_the_fifth_bucket_in_documented_order` | Slot 4 (0-indexed) is `wakir-schema-registry-entries`, config matches the table above, description references Phase-2 and `wakir-schemas` |
| T-Tag4-02 | `..._config_mirrors_wakir_schemas_cache` | The 5th bucket's history / ttl / max_value_size / storage / replicas equal the `wakir-schemas` bucket byte-for-byte; description and name differ by design |
| T-Tag4-03 | `..._create_on_empty_cluster_carries_documented_kv_config` | An empty-cluster planner pass emits a single `create_key_value` call for the 5th bucket with the documented kwargs |
| T-Tag4-04 | `..._bucket_filter_can_select_fifth_bucket` | `--bucket wakir-schema-registry-entries` selects only the 5th bucket (no-churn backfill path, see §3.2.1) |
| T-Tag4-05 | `..._idempotent_replay_marks_unchanged` | A second planner pass after the 5th bucket exists is a no-op (idempotency contract) |

`tests/orchestrator/test_check_nats_kv_health.py` carries one new
gated-live anchor: `test_smoke_fifth_bucket_present_in_live_inventory`
(under `WAKIR_NATS_LIVE=1`). It asserts the live cluster's
inspect-pass produces exactly one check for the 5th bucket whose
status is one of `ok` / `missing` / `drift` (never `error`). Live
gating mirrors the §7.4 first-time-live-smoke pattern; without the
gate the test is skipped during the hermetic CI pass.

**Cross-script parity:** the existing
`test_inventory_matches_init_nats_buckets` test in
`test_check_nats_kv_health.py` continues to enforce that the init
script and the health-check script agree on the full inventory; the
5th bucket inherits the dual-source contract for free.

**Cross-Review Zone B paired-update:** the Wirelang-side
`registry_nats_kv_backend.py` continues to point at `wakir-schemas`
(the cache bucket) in Phase-1b; switching the consumer onto the new
storage bucket is the OI-7-Phase-2 slot the Wirelang-side track owns. A Cross-Review-
Memo from the DevOps track to the Wirelang track confirms the 5th-
bucket creation and the Phase-2 reservation rationale (see
`agents-workspaces/reza/inbox/2026-05-11-kai-zone-b-fifth-bucket-paired-update.md`).

### 7.7 6th bucket: `wakir-federation-routes` (Phase-2 Sprint-4 Tag-5)

Sprint-4 Tag-5 closed the Sprint-2 Tag-7 Z-B Schluss-Marker open
follow-up by adding `wakir-federation-routes` as the 6th bucket in
`PHASE_1_BUCKETS`. Unlike the 5th bucket, this entry has a live
Phase-1b consumer: the Wirelang-side
`wirelang.federation.route_registry_nats_kv_backend.NatsKvRouteRegistry`
(Sprint-2 Tag-4 read/write backend + Sprint-2 Tag-6 watch-stream
snapshot layer). Pre-Tag-5 the bucket was created out-of-band per the
§6.5 hand-creation recipe; Tag-5 promotes it into the routine
`init-nats-buckets.py` pass.

**Bucket-config (mirrors Wirelang-side `BUCKET_CONFIG`):**

| field            | value         |
| ---------------- | ------------- |
| history          | 5             |
| ttl              | unbounded     |
| max_value_size   | 4 KiB         |
| storage          | file          |
| replicas         | 1             |

The byte-precise mirror is the design property: a drift between the
orchestrator-side and the Wirelang-side constants is a regression that
would force the operator to revert to the §6.5 hand-creation recipe.
The dual-anchor parity contract is enforced by:

- `test_t_tag5_02_sixth_bucket_config_mirrors_wirelang_consumer_bucket_config`
  (orchestrator suite) — asserts the orchestrator-side `BucketSpec`
  fields equal the Wirelang-side `BUCKET_CONFIG` mapping.
- `test_inventory_matches_init_nats_buckets` (orchestrator suite) —
  asserts the init script and the health-check script agree on the
  full inventory; the 6th bucket inherits the parity contract for free.

**Hermetic tests (Tag-5 additions):**

`tests/orchestrator/test_init_nats_buckets.py` carries five new tests
under the `T-Tag5-01..05` series:

| # | Name (short) | What it pins |
| --- | --- | --- |
| T-Tag5-01 | `..._is_the_sixth_bucket_in_documented_order` | Slot 5 (0-indexed) is `wakir-federation-routes`, config matches the table above, description references V-908 and Phase-1b |
| T-Tag5-02 | `..._config_mirrors_wirelang_consumer_bucket_config` | The 6th bucket's history / ttl / max_value_size / storage / replicas / description equal the Wirelang `BUCKET_CONFIG` mapping byte-for-byte |
| T-Tag5-03 | `..._create_on_empty_cluster_carries_documented_kv_config` | An empty-cluster planner pass emits a single `create_key_value` call for the 6th bucket with the documented kwargs |
| T-Tag5-04 | `..._bucket_filter_can_select_sixth_bucket` | `--bucket wakir-federation-routes` selects only the 6th bucket (no-churn backfill path, see §3.2.2) |
| T-Tag5-05 | `..._idempotent_replay_marks_unchanged` | A second planner pass after the 6th bucket exists is a no-op (idempotency contract) |

`tests/orchestrator/test_check_nats_kv_health.py` carries one new
gated-live anchor: `test_smoke_sixth_bucket_present_in_live_inventory`
(under `WAKIR_NATS_LIVE=1`). It asserts the live cluster's
inspect-pass produces exactly one check for the 6th bucket whose
status is one of `ok` / `missing` / `drift` (never `error`). Live
gating mirrors the §7.6 5th-bucket gated-live anchor pattern; without
the gate the test is skipped during the hermetic CI pass.

**Cross-Review Zone B paired-update:** the Wirelang-side
`NatsKvRouteRegistry` consumer continues to read and write
`wakir-federation-routes` unchanged; the Tag-5 patch is purely an
orchestrator-side inventory-registration change with no Wirelang-side
code edit required. The dual-anchor parity test is the only new
cross-side contract surface. A follow-up Cross-Review-Memo to the
Wirelang track confirms the registration and lists the Phase-2
follow-up (operator-hand population of routes is still out of scope
for `init-nats-buckets.py`; see V-908 operator playbook).

### 7.8 SPIFFE Z-A JWT-SVID Container-Identity-Skizze (Phase-2 Sprint-4 Tag-6)

Sprint-4 Tag-6 added a stand-alone Skizze document
`docs/spiffe-z-a-jwt-svid-skizze.md` describing the proposed
SPIFFE/SPIRE Container-Identity substrate path for Phase-2 Sprint-5
and beyond. The Skizze is **Cross-Review Zone A preparation
material**: no substrate change has been applied, and no SPIRE
container has been started. The Skizze collects:

- **Trust-domain proposal** (§2): `wakir.local` for Phase-2 single-
  node; `<org-id>.wakir.dev` for Phase-3a federation-ready.
- **SPIFFE-ID path patterns** (§3): persona-container IDs as
  `spiffe://<trust-domain>/agent/<persona-slug>/<persona-hash-12>`;
  substrate-service IDs as `spiffe://<trust-domain>/service/<service-name>`.
- **JWT-SVID issuance sequence** (§4): SPIRE-server sidecar →
  Workload-API Unix-socket → persona container → NATS-JWT-Auth.
- **SPIRE-server minimal config skizze** (§5): SQLite-DataStore, disk
  KeyManager, Join-Token NodeAttestor as Phase-2 boring-defaults.
- **Adapter-layer path** (§6, ADR-0035-bound): SPIRE container as
  Sidecar (Go-native upstream), `py-spiffe` Workload-API client in
  persona-container base image (Python adapter — no Go code written
  by the DevOps owner), `nats-py` `user_jwt` connection parameter.
- **Phase plan for Sprint-5** (§9): six-step Tag-by-Tag plan
  (Phase-2.1..2.6), gated on Z-A consensus marker.

**Test surface (Tag-6 additions):**

`tests/orchestrator/test_spiffe_z_a_skizze.py` carries three
hermetic Skizze-Validations tests under the `T-Tag6-Z-A-01..03`
series. They validate the format constants exported by
`scripts/spiffe_skizze_constants.py` (a new constants-only module
with no runtime behaviour) against the Skizze §2 / §3.1 / §3.2 /
§4.1 proposals:

| # | Name (short) | What it pins |
| --- | --- | --- |
| T-Tag6-Z-A-01 | `..._spiffe_id_pattern_constants_are_well_formed` | Trust-domain default is `wakir.local`; persona-ID and service-ID regexes accept the §3.1 / §3.2 exemplars and reject obviously malformed inputs; known Phase-2 service set matches §3.2 table |
| T-Tag6-Z-A-02 | `..._persona_hash_short_is_12_hex_chars` | `PERSONA_HASH_SHORT_LEN` is 12; regex enforces exactly that length and lower-case hex only |
| T-Tag6-Z-A-03 | `..._workload_api_socket_path_is_documented_phase_2_default` | Socket path is `/run/spire/sockets/agent.sock`; override env-var name is `SPIFFE_ENDPOINT_SOCKET` (SPIFFE-spec convention); JWT-SVID TTL default is 15 min; NATS audience is `nats://wakir.local` |

These tests do not require a running SPIRE server or NATS cluster.
They are drift-detectors: when Cross-Review Zone A consensus later
overrides a proposal (different trust-domain format, different
hash-length, different socket path), the tests break loudly and force
a co-edit of the constants module. This is the same drift-detection
discipline the `test_inventory_matches_init_nats_buckets` parity test
applies to the orchestrator-vs-Wirelang bucket-config mirror.

**Cross-Review Zone A status (Tag-6 authoring stamp):** consensus
marker not yet recorded; HR-track Cross-Review-protocol pending. All Skizze
constants are *proposals*, not decisions. Phase-2 Sprint-5 Z-A
implementation (Phase-2.1..2.6 per Skizze §9) is gated on the Z-A
consensus marker.

**Out of scope for the Tag-6 Skizze:**

- No SPIRE-server image-tag selection (Cosign-pinning slot analogous
  to the Tag-3 NATS-image-pin practice).
- No NATS-JWT-Auth final claims-set specification (Wirelang-side
  Identity-Document-Schema slot).
- No Vault-backend integration (V-907 + Z-A follow-up slot, Phase-3).
- No Phala-Cloud TEE-attestation integration (V-904 Z-D follow-up,
  Phase-3).

### 7.9 7th bucket: `wakir-capability-policies` (Phase-2 Sprint-5 Tag-2)

Sprint-5 Tag-2 promoted the Phase-3-reserved capability-policy
persistence bucket `wakir-capability-policies` into the routine
`init-nats-buckets.py` inventory pass as the Z-B paired-update with
the Wirelang-side Sprint-5 Tag-2 capability-policy persistence track.
This entry closes the inventory-side gap that the Sprint-5 Tag-1
Reza outbox §6 flagged as a future Phase-3 bucket-add ("Kai-
coordination für Bucket-Inventory"); Mira-Strategie-Hand 2026-05-11
promoted the slot to a paired Sprint-5 Tag-2 add.

**Context.** Sprint-5 Tag-1 (Wirelang) added a publisher-CLI
`--gate` / `--capability-registry` flag pair to
`wirelang.schemas.publisher_cli.py`. The capability-registry is an
operator-local JSON-file containing a `policies` array; each policy
entry is a small JSON object (issuer, allowed kids, allowed triples,
optional validity window). The Sprint-5 Tag-1 implementation loads
the policy registry from disk on every CLI invocation — no
cluster-wide cross-invocation state. The Phase-3 promotion will move
the policy registry onto a NATS-KV bucket so that operator-side
policy rotations propagate to all CLI invocations without a
file-distribution step.

**Bucket-config (reservation-form).** Sprint-5 Tag-2 ships the
bucket-spec with audit-friendly defaults; the Reza-owned
encoder/decoder module commits the authoritative `BUCKET_CONFIG`
constant as a follow-up, at which point the in-tree mirror against
`wakir-ftd-poisoned` is replaced by a cross-import-mirror anchor
analogous to `test_t_tag5_02_sixth_bucket_config_mirrors_wirelang_consumer_bucket_config`.

| field            | value      | rationale                                                                         |
| ---------------- | ---------- | --------------------------------------------------------------------------------- |
| `history`        | 10         | capability-policy rotations want a deep audit trail (mirrors `wakir-ftd-poisoned`) |
| `ttl_seconds`    | 0          | policies live until explicit rotation; no time-based eviction                     |
| `max_value_size` | 4 KiB      | a single serialised policy entry is small (mirrors `wakir-ftd-poisoned`)          |
| `storage`        | `file`     | Phase-1 single-node storage convention                                            |
| `replicas`       | 1          | Phase-1 single-node replication convention                                        |

**Operator surface (no Phase-1b / Phase-2 user-visible change).** The
7th bucket has no live consumer in Phase-1b / Phase-2; the operator
sees one extra `created` entry in the JSON report from
`init-nats-buckets.py` and one extra `ok` entry in
`check-nats-kv-health.py`. No service in the current runtime reads or
writes the bucket. The §3.2.3 no-downtime backfill recipe covers
pre-Sprint-5-Tag-2 clusters that did not get the bucket on first
bring-up.

**Test surface (hermetic).** Five hermetic tests in
`tests/orchestrator/test_init_nats_buckets.py` (T-Tag2-01..05) anchor
the slot, the in-tree mirror against `wakir-ftd-poisoned`, the
create-call shape, the `--bucket` selector path, and the idempotent
replay contract. The inventory-contract test
`test_phase_1_inventory_is_the_documented_seven_buckets` is bumped
from six- to seven-bucket. The cross-script parity test
`test_inventory_matches_init_nats_buckets` covers the dual-source
contract for the new entry automatically.

**Test surface (gated-live).** One gated-live smoke test
`test_smoke_seventh_bucket_present_in_live_inventory` in
`test_check_nats_kv_health.py` confirms the 7th bucket shows up in
the live cluster inventory after an init-pass. Skipped by default;
runs under `WAKIR_NATS_LIVE=1`. The status semantics accept
`ok`/`missing`/`drift` (the `missing` allowance reflects that the
bucket is a fresh add — operators on a pre-Sprint-5-Tag-2 cluster
will see `missing` until they re-run `init-nats-buckets.py`, see
§3.2.3).

**Cross-Review-Status.** Z-B (NATS-Schema × Wirelang) paired-update
with the Wirelang-side Sprint-5 Tag-2 capability-policy persistence
track. The cross-import-mirror anchor (analogous to Tag-5 6th-bucket
`test_t_tag5_02` pattern) lands as a Sprint-5 Tag-N follow-up once
the Reza-owned encoder/decoder module commits a `BUCKET_CONFIG`
constant upstream. Until then, the reservation-form mirror against
`wakir-ftd-poisoned` (test `test_t_tag2_02`) guards the in-tree
shape. No Z-A (Container-Identity × SPIFFE-Spec) or Z-C
(Container-Image-Pipeline × OTS-Anchoring) touchpoints; the
bucket-add is in the NATS-KV substrate surface, fully within
Z-B scope.

**Out of scope for Sprint-5 Tag-2:**

- No Wirelang-side encoder/decoder module (Reza-owner, separate
  Sprint-5 Tag-2 deliverable on the Wirelang track).
- No Phase-3 capability-policy persistence consumer (no service in
  Phase-1b / Phase-2 reads or writes the bucket).
- No NATS-KV-CAS-quorum semantics for policy writes (Phase-3 design
  decision on the Reza-side; the bucket-config does not pre-commit
  to a specific consumer-side concurrency model).
- No Biscuit-v3 binary-token codec on the bucket (the Sprint-5 Tag-1
  publisher-CLI `--capability-registry` JSON-file shape is the
  Phase-3 reservation; binary-token promotion is a separate Phase-3
  slot on the Reza-side).

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
- Sprint-3 Tag-2 §7.1 expansion stamp: `date -u`
  2026-05-07T14:07:19Z (CEST 2026-05-07T16:07). This pass is
  documentation-only. No code surface is touched; no test surface
  is added; no exit-code contract changes; no schema changes; no
  auth-surface changes. The §7.1 nine-step build-host activation
  procedure expands the Tag-8 §7 Sprint-3 build-host bullet into
  per-step command, footprint, reversibility, security note,
  verification, and approval-pass-gate metadata so an external
  operator can execute the activation without reading the
  dev-engineering-3-side workspace outbox sketch. The §0 section
  index, the §7 Sprint-3 build-host bullet rewrite, the new
  §7.1 sub-section (steps 7.1.1 through 7.1.11), and this
  verification stamp are the only Sprint-3 Tag-2 additions to
  the runbook. Zero-drift verification: `tests/orchestrator/`
  55 passed + 4 skipped (Tag-7 baseline preserved); zero
  regressions. The §7.1 footprint and time estimates are
  conjecture (P2): they are derived from upstream package metadata
  (Fedora dnf, PyPI, Synadia GitHub Releases) and not from a
  sandbox install, so absolute values may drift ±20 % while
  order-of-magnitude is stable. The two upstream URLs cited in
  step 7.1.4 (`api.github.com/repos/nats-io/natscli/releases/latest`
  and `github.com/nats-io/natscli/releases/download/...`) follow
  GitHub-API and GitHub-Releases conventions but were not
  HTTP-200-verified during runbook authoring (the authoring
  sandbox has no internet egress); the supervisory-board-side
  approval pass should run a one-shot 200-check on those URLs
  before greenlighting step 7.1.4. The third URL
  (`github.com/wakir-labs/wakir-runtime`) is verified-existing
  via the Sprint-2 push history for this repo. Sprint-3 Tag-2
  companion artefact: the dev-engineering-3-side workspace
  outbox sketch `2026-05-07-phase-1b-sprint-3-tag-1-build-host-
  aktivierung-skizze` (Tag-1 deliverable) plus the Sprint-3 Tag-2
  outbox slug `2026-05-07-phase-1b-sprint-3-tag-2`.
- Sprint-3 Tag-3 §7.2 wiring stamp: `date -u`
  2026-05-07T14:20:46Z (CEST 2026-05-07T16:20). This pass adds
  five systemd unit files under `scripts/systemd/`
  (`wakir-nats-kv-health.{service,timer}`,
  `wakir-federation-evaluator-health.{service,timer}`, and the
  template unit `wakir-prometheus-textfile-adapter@.service`),
  one Prometheus textfile-collector adapter
  (`scripts/prometheus-textfile-adapter.py`, ~330 LOC, stdlib-
  only), and the §7.2 runbook sub-section. Test surface adds 29
  hermetic tests under
  `tests/orchestrator/test_prometheus_textfile_adapter.py` covering
  flavour detection (4), NATS-KV render (6), federation render
  (6), top-level render + last-run-stamp (3), atomic write (3),
  and the CLI exit-code matrix (7). Zero-drift verification:
  `tests/orchestrator/` 84 passed + 4 skipped (was 55 + 4 before
  Tag-3; +29 from the new adapter suite); project-wide 218 passed
  + 23 skipped (was 189 + 23 before Tag-3; +29 from the new
  adapter suite); zero regressions. The adapter never opens a
  network socket; the systemd units never write outside
  `/var/log/wakir` and `/var/lib/node_exporter/textfile_collector`
  (`ProtectSystem=strict` + `ReadWritePaths=` enforce this). The
  units assume a `/opt/wakir-runtime` checkout with the project
  installed in `.venv/`; operators on a different layout adjust
  via `systemctl edit` drop-ins rather than mutating the upstream
  files.
- Sprint-3 Tag-4 §7.1.10 post-install-live-smoke driver stamp:
  `date -u` 2026-05-07T17:37:17Z (CEST 2026-05-07T19:37). This
  pass adds `scripts/post-install-live-smoke.sh` (a bash-driver
  that chains image-pull, compose-up, wait-ready, bucket-init,
  real-`nats-py` adapter round-trip, NATS-KV health check, and
  teardown into a single idempotent invocation with a JSON summary
  on stdout, an exit-code-via-trap discipline, and seven CLI
  options for operator-driven variants), the companion test plan
  `tests/orchestrator/test_post_install_live_smoke_plan.md` (14
  cases: 1 happy-path, 5 operator-driven variants, 6 fault-
  injection, 2 idempotency re-runs), and the §7.1.10 runbook sub-
  section that documents the driver's CLI surface and exit-code
  contract. The §0 section index gains a `7.1.10` row; the §7.1
  sub-section renumbering shifts the existing 7.1.10 (risk
  register) to 7.1.11 and the 7.1.11 (cross-review zone touch)
  to 7.1.12. The driver runs `bash -n` clean and a `--dry-run`
  smoke from the authoring sandbox (no podman/nats/nats-py
  available — the post-gcc activation wave is partially landed,
  the rest pending) correctly fails preflight at step 1 with
  exit 1 and emits a parseable JSON summary; the same dry-run
  on a fully-activated build-host should record `1-preflight: ok`
  and `2-7-pre, 7-teardown: skip` for an `highest_exit: 0`. Test
  surface is unchanged in pytest terms: project-wide 218 passed +
  23 skipped, `tests/orchestrator/` 84 passed + 4 skipped — the
  new test plan is markdown-only by design (§7.1.10 motivates
  why a hermetic pytest of a real-substrate driver would lose
  the property under test).
- Phase-2 Sprint-4 Tag-1 §7.3 Live-NATS-Test-Mode driver stamp:
  `date -u` 2026-05-11T16:34:55Z (CEST 2026-05-11T18:34). This pass
  adds `scripts/run-live-smoke-tests.sh` (a bash-driver that runs
  four pre-flight probes — TCP 4222, HTTP /jsz, optional `nats`-CLI
  ping, repo venv `import nats` + `pytest` presence — then invokes
  pytest with `WAKIR_NATS_LIVE=1` against an operator-selectable
  subset of the gated orchestrator tests, emitting a JSON summary on
  stdout with a four-state exit-code contract), the companion test
  module `tests/orchestrator/test_live_nats_cross_validation.py`
  (six tests: four hermetic baselines for the `InitReport.to_json()`
  byte-shape in the empty-cluster and populated-cluster `dry_run=True`
  scenarios plus a byte-stability lock-down across invocations and
  across distinct mock instances, two `WAKIR_NATS_LIVE=1`-gated
  cross-validation tests that assert the live cluster produces a
  byte-identical JSON payload for both scenarios), and the §7.3
  sub-section (7.3.1 hermetic-default contract, 7.3.2 operator
  install, 7.3.3 pre-flight probes, 7.3.4 byte-identity contract,
  7.3.5 failure modes and recovery, 7.3.6 out-of-scope). The §0
  section index gains a `7.3` row; no existing sub-section is
  renumbered. The driver runs `bash -n` clean and a `--dry-run`
  from the authoring sandbox correctly skips both pre-flight and
  pytest and emits a parseable JSON plan; a live `--no-cross-
  validation --collect-only` against an up substrate but a venv
  without `nats-py` correctly fails pre-flight at venv with exit 1
  and emits the JSON summary. The new cross-validation suite adds
  six tests to `tests/orchestrator/`: zero-drift verification:
  `tests/orchestrator/` 88 passed + 6 skipped (was 84 + 4 before
  Tag-1; +4 hermetic and +2 gated-live from the new suite); zero
  regressions. The Sprint-4 Tag-1 ADR-0051 context: ADR-0051
  (CEO-side-sandbox vs. host-operations trennung) was rejected (per
  CEO closeout 2026-05-07 ~18:10 CEST); the operative-side
  hand-off rule that the CEO-side sandbox cannot reach the host NATS
  substrate is retained and is the binding rationale for the
  driver's operator-hand-only posture. The byte-identity contract
  is the cross-validation gate that lets the §7.1.10 post-install
  driver and the §7.2 systemd wiring trust the pytest suite to flag
  a substrate-side regression before the build-host activation pass
  declares done. No image-tag dependency is introduced; no new
  schema surface; no new auth surface (`WAKIR_NATS_TOKEN` flow
  unchanged). The verification stamp also re-runs the legacy gated
  suite manifest: `test_init_nats_buckets.py` (10 hermetic),
  `test_check_nats_kv_health.py` (16 hermetic + 2 gated-live),
  `test_check_federation_evaluator_health.py` (20 hermetic + 2
  gated-live) — the Tag-1 driver re-uses these under the same
  `WAKIR_NATS_LIVE=1` flag.
- Phase-2 Sprint-4 Tag-2 §7.4 first-time live-smoke execution record
  stamp: `date -u` 2026-05-11T16:56:08Z (CEST 2026-05-11T18:56). This
  pass is documentation-only. No code surface is touched; no test
  surface is added; no exit-code contract changes; no schema changes;
  no auth-surface changes. The Tag-2 record captures the first
  end-to-end run of `scripts/run-live-smoke-tests.sh` against a real
  host `wakir-nats` substrate (Aufsichtsrat-Operator brought it up at
  ~16:30 CEST); it documents the two scenario passes (empty cluster
  and populated cluster, driven via the state machine described in
  §7.3.2), the SHA256-equality of the populated-scenario live and mock
  `InitReport.to_json()` byte sequences (594-byte payload,
  sha256 `4eceed0338840f34696fd7913e95566d25637fdcde44978727a8a40cf65da9cc`
  on both transports), the pre-flight result breakdown (TCP+JSZ+venv
  ok; `nats` CLI unreachable as documented best-effort), and the
  side-effects on the live substrate (four Phase-1 buckets created,
  ephemeral storage, operator-driven teardown). The host substrate
  uses `nats-py` 2.14.0 (installed into the repo `.venv/` for the
  duration of this record; pinning belongs in the orchestrator
  container's Python dependency manifest per §8 nats-py policy).
  Zero-drift verification on the pytest gate: `tests/orchestrator/`
  88 passed + 6 skipped under hermetic invocation (matches Tag-1
  baseline); under `WAKIR_NATS_LIVE=1` against the live substrate,
  55 passed + 1 skipped per scenario for both empty and populated
  states (4 of 6 cross-validation tests run hermetically every time;
  the 2 live-gated tests fire exactly one match + one skip per
  scenario depending on cluster state). No regressions. The Tag-2
  ADR-0051 context is unchanged: ADR-0051 rejected, operative-side
  hand-off rule retained; the CEO-side sandbox did not touch the
  container lifecycle for the record run (host bring-up is
  Aufsichtsrat-Operator hand, the CEO-side sandbox connects via
  NATS protocol on `localhost:4222` only).
  Reproduction recipe is embedded in §7.4 so a future operator can
  re-run the record without reading the outbox closeout note.
- Phase-2 Sprint-4 Tag-3 §7.5 image-digest verification gate stamp:
  `date -u` 2026-05-11T17:09:11Z (CEST 2026-05-11T19:09). This pass
  is the Cross-Review Zone-C digest-pin upgrade over the Sprint-2-
  Tag-3 tag-pin (Engineering-Lead-side ack 2026-05-07T12:07:19Z paired
  with dev-engineering-3-side memo 2026-05-07T11:50:36Z; ack-condition:
  digest-pin lands before
  any OTS-anchor pipeline consumes `compose/*.yaml` as trusted
  input). Substance: (a) `compose/nats.yaml` `services.nats.image`
  upgraded from `nats:2.11-alpine` to
  `nats:2.11-alpine@sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00`
  (manifest-list digest; multi-arch-stable), with the amd64-image
  digest `sha256:a7d440bf0240e664ed74fc17c70d616e6ff4bb9890dc26f7276589daedd1e196`
  recorded in commentary for amd64-only hosts; (b) new operator
  script `scripts/verify-image-digest.sh` providing a hermetic-by-
  default digest-form gate with three opt-in modes (`--strict`,
  `--with-registry`, `--with-cosign`) and a JSON summary surface
  (exit codes 0/1/2 per §7.5 contract); (c) ten new hermetic tests
  in `tests/orchestrator/test_verify_image_digest.py` (digest-pin
  form, tag-only fallback, malformed pin, short-digest rejection,
  `--expected-digest` match/mismatch, `--expected-tag` mismatch,
  executable bit, `bash -n` syntax gate, repo-default contract
  anchor). Image-digest resolution method: Docker Hub public
  registry API
  `https://registry.hub.docker.com/v2/repositories/library/nats/tags/2.11-alpine`
  (HTTP 200 verified 2026-05-11T17:09Z; response body includes the
  `digest` field with value `sha256:e4bf...8cc00` and
  `last_updated` `2026-04-28T01:57:25Z`). The hermetic test surface
  invokes the script via `subprocess.run` against synthetic
  compose fixtures in tmpdir; no container engine, no network, no
  cosign required for any of the ten tests. The cosign mode is a
  surface-only future opt-in for Phase-1b — the official `nats`
  image is not currently signed by Synadia with a published key,
  so `cosign verify` against the sigstore public-good log returns
  verify-failed for the unsigned image (the script surfaces this
  diagnostic clearly so an operator opting in does not mistake the
  gap for a substrate fault). Zero-drift verification:
  `tests/orchestrator/` 98 passed + 6 skipped post-Tag-3 (Tag-2
  baseline 88+6, net +10 hermetic from the new test file);
  project-wide 232 passed + 25 skipped post-Tag-3 (Tag-2 baseline
  222+25, net +10 hermetic). The four live-gated tests in the
  orchestrator suite remain `WAKIR_NATS_LIVE=1`-gated; the image-
  digest gate does not introduce a new live dependency. The
  existing compose hermetic suite `test_compose_nats.py` (test
  `test_nats_service_uses_documented_image_tag`) accepts both
  tag-only and digest-pin forms by regex; the Tag-3 compose update
  is digest-pin form, so the existing test stays green without
  edits.
- Phase-2 Sprint-4 Tag-4 §7.6 5th-bucket-paired-update stamp:
  `date -u` 2026-05-11T17:48:06Z (CEST 2026-05-11T19:48). This pass
  is the Cross-Review Zone-B paired-update slot per the Sprint-4
  Tag-4 re-spawn auftrag. Substance: (a) `scripts/init-nats-buckets.py`
  `PHASE_1_BUCKETS` extended from four to five entries with
  `wakir-schema-registry-entries` appended at slot index 4 (history=5,
  ttl unbounded, max_value_size 262 144 B, storage=file, replicas=1
  — config mirrors `wakir-schemas` so the Phase-2 schema-registry
  storage migration is a value-copy without a config-drift step);
  (b) `scripts/check-nats-kv-health.py` `PHASE_1_BUCKETS` extended
  identically (cross-script parity test
  `test_inventory_matches_init_nats_buckets` continues to enforce
  the dual-source contract); (c) `compose/nats.yaml` header
  commentary updated to reference the five-bucket layout (compose
  hermetic test `test_compose_commentary_references_all_phase_1_buckets`
  pins the inventory-set on the compose-side); (d) five new
  hermetic tests in `tests/orchestrator/test_init_nats_buckets.py`
  under the T-Tag4-01..05 series (slot ordering, config mirror,
  empty-cluster create kwargs, single-bucket backfill, idempotent
  replay) plus the inventory-list expansion of two existing tests
  (`test_phase_1_inventory_is_the_documented_five_buckets`,
  `test_report_to_json_has_stable_shape_and_summary` summary block);
  (e) one new gated-live anchor
  `test_smoke_fifth_bucket_present_in_live_inventory` in
  `tests/orchestrator/test_check_nats_kv_health.py` (under
  `WAKIR_NATS_LIVE=1`); (f) runbook updates: new §3.2.1 backfill
  recipe for pre-Tag-4 clusters (no-downtime upgrade path), §1
  inventory table expanded to five rows with Phase-2-reserved
  annotation, §5 health-check guidance updated to expect five
  buckets, new §7.6 substance section (config rationale, hermetic
  test inventory, Cross-Review-Zone-B paired-update statement,
  Wirelang-side consumer status). Cross-Review Zone-B paired-update
  memo to the Wirelang track:
  `agents-workspaces/reza/inbox/2026-05-11-kai-zone-b-fifth-bucket-paired-update.md`.
  Domain-discipline statement: the 5th bucket is operator-side
  infra (DevOps-track-owned per §1 Persona); the Wirelang-side
  consumer for Phase-2 schema-registry storage migration is the
  OI-7-Phase-2 slot the Wirelang track owns and is **not** touched
  by this Tag-4
  delivery. The bucket has no Phase-1b consumer; it is registered
  ahead of time so the Phase-2 operator bring-up procedure
  collapses into the routine `init-nats-buckets.py` pass.
  Zero-drift verification: `tests/orchestrator/` 103 passed + 6
  skipped post-Tag-4 (Tag-3 baseline 98+6, net +5 hermetic; the
  one new gated-live test is skip-counted under the project-wide
  total), project-wide 237 passed + 26 skipped post-Tag-4 (Tag-3
  baseline 232+25, net +5 hermetic + 1 gated-live skip).
  Auftrags-Wortlaut Bindung: the re-spawn auftrag referenced
  `wakir-schema-registry-entries` as the 5th bucket explicitly; this
  Tag-4 pass binds to that wording. The pre-Tag-4 acceptance-doku
  §5.5 reference to `wakir-federation-routes` as the 5th bucket is
  superseded by this auftrag; the federation-routes bucket
  remains an operator-hand `nats kv add` step per §6.5, and a
  future paired-update slot can extend `PHASE_1_BUCKETS` to a 6th
  bucket without breaking the Tag-4 contract (see §7 follow-ups
  Sprint-3 line, updated annotation).
- Phase-2 Sprint-4 Tag-5 §7.7 6th-bucket-paired-update stamp:
  `date -u` 2026-05-11T18:20:17Z (CEST 2026-05-11T20:20). This pass
  is the Cross-Review Zone-B follow-up paired-update slot per the
  Sprint-4 Tag-5 auftrag, closing the Sprint-2 Tag-7 Z-B Schluss-
  Marker open follow-up that asked for `wakir-federation-routes` to
  be registered in the routine init inventory. The Tag-4 outbox
  signalled this exact follow-up in §8 "future paired-update slot
  can extend `PHASE_1_BUCKETS` to a 6th bucket without breaking the
  Tag-4 contract"; Tag-5 lands the 6th-slot. Substance:
  (a) `scripts/init-nats-buckets.py` `PHASE_1_BUCKETS` extended from
  five to six entries with `wakir-federation-routes` appended at
  slot index 5 (history=5, ttl unbounded, max_value_size 4096 B,
  storage=file, replicas=1 — config mirrors the Wirelang-side
  `wirelang.federation.route_registry_nats_kv_backend.BUCKET_CONFIG`
  byte-precisely so the operator-hand fallback in §6.5 collapses
  into the routine `init-nats-buckets.py` pass);
  (b) `scripts/check-nats-kv-health.py` `PHASE_1_BUCKETS` extended
  identically (cross-script parity test
  `test_inventory_matches_init_nats_buckets` continues to enforce
  the dual-source contract; the 6th bucket inherits parity for free);
  (c) `compose/nats.yaml` header commentary updated to reference the
  six-bucket layout (compose hermetic test
  `test_compose_commentary_references_all_phase_1_buckets` pins the
  inventory-set on the compose-side); (d) five new hermetic tests in
  `tests/orchestrator/test_init_nats_buckets.py` under the
  T-Tag5-01..05 series (slot ordering, Wirelang `BUCKET_CONFIG`
  mirror via lazy import of the consumer module, empty-cluster create
  kwargs, single-bucket backfill selector, idempotent replay) plus
  the inventory-list expansion of two existing tests
  (`test_phase_1_inventory_is_the_documented_six_buckets`,
  `test_report_to_json_has_stable_shape_and_summary` summary block);
  (e) one new gated-live anchor
  `test_smoke_sixth_bucket_present_in_live_inventory` in
  `tests/orchestrator/test_check_nats_kv_health.py` (under
  `WAKIR_NATS_LIVE=1`); (f) runbook updates: new §3.2.2 backfill
  recipe for pre-Tag-5 clusters (no-downtime upgrade path), §1
  inventory table expanded to six rows with V-908 consumer
  annotation, §3 cold-start intro updated to "six KV buckets",
  §3.2 JSON-summary expectation updated to `{created: 6, ...}` with
  upgrade-path-hint, §5 health-check guidance updated to expect six
  buckets including the V-908 `nats kv info wakir-federation-routes`
  check, §6.5 federation-routes section flipped from "Phase-1b
  bring-up" to "now routine; fallback only" with the
  `init-nats-buckets.py --bucket wakir-federation-routes` recipe
  added next to the legacy `nats kv add` recipe, new §7.7 substance
  section (config rationale with Wirelang-side `BUCKET_CONFIG`
  byte-mirror, hermetic test inventory, gated-live anchor,
  Cross-Review-Zone-B paired-update statement, dual-anchor parity
  contract), §7 follow-up Sprint-3 line struck through and annotated
  with "done in Phase-2 Sprint-4 Tag-5 as the 6th bucket". Cross-
  Review Zone-B follow-up paired-update memo to the Wirelang track:
  `agents-workspaces/reza/inbox/2026-05-11-kai-zone-b-sixth-bucket-paired-update.md`.
  Domain-discipline statement: the 6th bucket is operator-side
  infra (DevOps-track-owned per §1 Persona); the Wirelang-side
  consumer (`wirelang.federation.route_registry_nats_kv_backend`)
  is NOT touched by this Tag-5 delivery — the orchestrator-side
  inventory addition is byte-equal verifiable against the existing
  Wirelang `BUCKET_CONFIG` constant via the lazy-import parity test
  T-Tag5-02. Phase-1b consumer status: the Wirelang-side
  `NatsKvRouteRegistry` continues to read and write the bucket
  exactly as before; the only operational change is that operators
  bringing up a fresh cluster no longer need the §6.5 hand-creation
  step (the routine `init-nats-buckets.py` pass materialises the
  bucket together with the other five). Zero-drift verification:
  `tests/orchestrator/` 108 passed + 8 skipped post-Tag-5 (Tag-4
  baseline 103+6, net +5 hermetic + 2 gated-live skips — the new
  T-Tag5-02 lazy-imports the Wirelang module so this also exercises
  the orchestrator-suite parity probe against the consumer-side
  `BUCKET_CONFIG`), project-wide 245 passed + 24 skipped post-Tag-5
  (Tag-4 baseline 237+26, net +8 passed and -2 skipped — the net
  delta reflects the +5 hermetic Tag-5 adds, the +1 new gated-live
  skip, plus inventory test count adjustments where pre-existing
  inventory tests now exercise a six-element set instead of five).
  Auftrags-Wortlaut Bindung: the Tag-5 auftrag referenced
  `wakir-federation-routes` as the 6th bucket explicitly, citing
  the Wirelang-track Sprint-3-Tag-4 `NatsKvRouteRegistry` backend
  as the consumer-side anchor; this Tag-5 pass binds to that wording. The
  stash@{0} snapshot
  `tag-4-federation-routes-prior-attempt` (created during the Tag-4
  re-spawn pivot) was consulted as a substance-anchor for the
  6th-bucket BucketSpec values and the runbook §6.5 transformation
  prose; the changes here are freshly written on the Tag-4 commit
  base (`16ddaba`), not a stash-pop apply — preserving the
  Tag-5 commit's full attribution chain.
- Authoring date (Phase-2 Sprint-4 Tag-6 update): `date -u`
  2026-05-11T18:30:01Z (CEST 2026-05-11 20:30). Sprint-4 Tag-6
  60-min-box. Substance delivered: (a) new stand-alone Skizze
  document `docs/spiffe-z-a-jwt-svid-skizze.md` (~430 lines)
  describing the proposed SPIFFE/SPIRE Container-Identity substrate
  path for Phase-2 Sprint-5 and beyond — Cross-Review Zone A
  preparation material, no substrate change; (b) new constants-only
  module `scripts/spiffe_skizze_constants.py` exporting the
  Skizze §2 trust-domain default, §3.1 / §3.2 SPIFFE-ID regex
  patterns, §3.1 `PERSONA_HASH_SHORT_LEN=12` proposal, §3.2
  `KNOWN_PHASE_2_SERVICES` frozenset, §4.1 Workload-API socket-path
  default `/run/spire/sockets/agent.sock` plus
  `SPIFFE_ENDPOINT_SOCKET` override env-var convention, §4.3
  JWT-SVID-TTL `15*60` seconds default and NATS audience
  `nats://wakir.local`; (c) new hermetic test file
  `tests/orchestrator/test_spiffe_z_a_skizze.py` with three Skizze-
  Validations tests T-Tag6-Z-A-01..03 covering format-pattern
  acceptors and rejecters, persona-hash short-form length pinning
  (12 hex chars, lower-case enforced), Workload-API socket-path
  defaults; (d) new runbook section §7.8 summarising the Skizze and
  the Tag-6 test additions, with explicit out-of-scope statements
  (no SPIRE image-tag selection, no NATS-JWT-Auth final claims-set,
  no Vault-backend integration, no Phala-Cloud TEE attestation
  here); (e) §0 section-index updated to list §7.8 and to extend
  the §8 source-tags range to Phase-2 Sprint-4 Tag-1..Tag-6. Tag-6
  zero-substrate-change discipline: no `compose/*.yaml` edits, no
  `init-nats-buckets.py` edit, no `check-nats-kv-health.py` edit,
  no Wirelang-side edit; this is a Skizze + tests delivery only.
  Test-count delta: project-wide 245 passed + 24 skipped post-Tag-5
  → 248 passed + 24 skipped post-Tag-6 (+3 new hermetic tests from
  T-Tag6-Z-A-01..03; zero regression on the existing suite).
  Cross-Review Zone A status: consensus marker not yet recorded;
  HR-track Cross-Review-protocol pending. All Skizze constants are *proposals*,
  not decisions. Phase-2 Sprint-5 Z-A implementation gated on the
  Z-A consensus marker. Stash-disposition: the Tag-5 outbox §9
  proposal to drop `stash@{0}` (`tag-4-federation-routes-prior-
  attempt`) was actioned at Tag-6 box-start — verified via
  `git stash drop stash@{0}` → `Dropped stash@{0} (fa598a48...)`;
  post-drop `git stash list` is empty. The Tag-5 commit `7fc13ee`
  remains authoritative for the 6th-bucket substance.
- Phase-2 Sprint-5 Tag-2 §7.9 7th-bucket-paired-update stamp:
  authoring `date -u` 2026-05-11T19:18:29Z (CEST 2026-05-11 21:18).
  Sprint-5 Tag-2 60-min-box. Substance delivered: (a) 7th
  `BucketSpec` entry `wakir-capability-policies` in
  `scripts/init-nats-buckets.py` `PHASE_1_BUCKETS` (slot 6, after
  `wakir-federation-routes`) plus mirror entry in
  `scripts/check-nats-kv-health.py` with audit-friendly defaults
  history=10, ttl_seconds=0, max_value_size=4096, storage="file",
  replicas=1; (b) `compose/nats.yaml` header commentary bumped from
  6 → 7 buckets with the Sprint-5 Tag-2 capability-policy-
  reservation rationale embedded; (c) five hermetic tests T-Tag2-
  01..05 in `test_init_nats_buckets.py` anchoring slot, in-tree
  mirror against `wakir-ftd-poisoned`, create-call shape, selector
  path, and idempotent replay; plus the bumped inventory contract
  `test_phase_1_inventory_is_the_documented_seven_buckets`
  (renamed-from-six in both `test_init_nats_buckets.py` and
  `test_check_nats_kv_health.py`); plus the bumped summary-shape
  test (`"created": 7`, `"total": 7`) and the compose-commentary
  reference test (`bucket_names ==` seven-element set); (d) one
  gated-live smoke test `test_smoke_seventh_bucket_present_in_live_inventory`
  in `test_check_nats_kv_health.py` (skipped by default; runs under
  `WAKIR_NATS_LIVE=1`); (e) §0 section-index updated to list §3.2.3
  and §7.9 and to extend the §8 source-tags range to Phase-2
  Sprint-5 Tag-2; (f) §1 inventory table bumped to seven-bucket
  layout; (g) §3.2.3 no-downtime backfill recipe for the 7th bucket
  modelled on the §3.2.1 pre-Tag-4 5th-bucket pattern; (h) §7.9
  substance section covering context (Sprint-5 Tag-1 publisher-CLI
  `--capability-registry` JSON-file shape as the Phase-3 promotion
  source), bucket-config rationale table, operator-surface
  no-change discipline, hermetic + gated-live test surface,
  cross-review status, out-of-scope list. **Cross-Review Zone B**
  (NATS-Schema × Wirelang) paired-update with the Wirelang-side
  Sprint-5 Tag-2 capability-policy persistence track. The cross-
  import-mirror anchor against the Wirelang-side `BUCKET_CONFIG`
  constant (analogous to `test_t_tag5_02` 6th-bucket pattern) lands
  as a Sprint-5 Tag-N follow-up once the Reza-owned encoder/decoder
  module commits upstream; until then the in-tree mirror against
  `wakir-ftd-poisoned` (test `test_t_tag2_02`) guards the
  reservation-form shape. No Zone-A or Zone-C touchpoints.
  Test-count delta: orchestrator-suite 111 passed + 8 skipped
  post-Tag-6 → 116 passed + 9 skipped post-Sprint-5-Tag-2 (+5 new
  hermetic from T-Tag2-01..05, +1 new gated-live from
  `test_smoke_seventh_bucket_present_in_live_inventory`); zero
  regression on the existing suite. Project-wide: 253 passed + 25
  skipped at Sprint-5-Tag-2-acceptance-time (Sprint-5 Tag-1
  Wirelang additions are included in the +8 net-passed swing since
  Sprint-4-Tag-6-acceptance-doku reported 245+27). The Test-Counts
  drift flagged in the Sprint-4-acceptance-doku §9 (3 skip-statt-
  pass between Tag-6-authoring and Sprint-5-Tag-1-acceptance-box)
  resolves cleanly here: a `nats-py` reinstall and the cumulative
  Reza-side Sprint-5 Tag-1 hermetic-test adds (no skip flips on the
  Kai side) bring project-wide back to a passed-monotonic state
  (245 → 253 = +8 passed; -2 skipped reflects gated-live additions
  net of the prior skip-statt-pass drift, see Sprint-4-acceptance-
  doku §9 P2-Hinweis for the prior baseline). Stash-disposition:
  Sprint-5 Tag-2 box-start `git stash list` empty (carried clean
  from Tag-6 box-end post-`stash drop stash@{0}`); no new stashes
  produced during the Tag-2 box.
