<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Orchestrator NATS-JetStream KV Phase-1 — Operator Runbook

Status: draft, Phase 1b Sprint-2 Tag-2.
Companion to `scripts/init-nats-buckets.py` (driver) and
`tests/orchestrator/test_init_nats_buckets.py` (hermetic regression).

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

If `init-nats-buckets.py` exits 2 with drift on a production cluster:

1. Capture the JSON report (`script ... > drift-report.json`).
2. Triage with the engineering on-call: was the drift intentional
   (operator override) or an accident (manual misconfiguration)?
3. If intentional, file an ADR amendment to the documented inventory
   in §1 of this runbook and patch `PHASE_1_BUCKETS` in the script.
4. If accidental, recreate the affected bucket by hand and re-run the
   initialiser.

### 6.4 FTD poison-list growth

`wakir-ftd-poisoned` is unbounded by design. If it grows beyond
operationally tolerable size (Phase-1 working assumption: < 10k
entries), trigger a manual audit review. Eviction policy beyond
audit review is a Phase-2 follow-up; do not auto-evict in Phase-1.

## 7. Open follow-ups

- Sprint-2 Box-3: pin the NATS server image tag in `compose/nats.yaml`.
  Verification snapshot recorded in §8 below; the active candidate is
  `nats:2.11-alpine`. The bucket initialiser is image-tag-agnostic.
- Sprint-2 Box-5: real `nats-py` (`nats.aio`) sync-adapter for the
  read-through wrapper. The initialiser already uses the async API; no
  rework expected on the bucket side.
- Sprint-3: SPIFFE JWT-SVID auth (Cross-Review Zone A). The
  initialiser currently consumes a token from `WAKIR_NATS_TOKEN`; the
  SVID path will replace this with a workload-API call.
- Phase-3: replicated JetStream (replicas > 1) requires a multi-node
  cluster topology. Bucket spec changes are limited to `replicas`; the
  initialiser already plumbs that field end-to-end.

## 8. Verification stamps (P5/P7)

- Authoring date: `date -u` 2026-05-07T (CEST 2026-05-07, Sprint-2 Tag-2).
- NATS server image-tag candidate verification (Phase-1b production
  baseline): the official `nats` Docker Hub repository lists
  `2.11-alpine` as a maintained alpine variant, last pushed 9 days
  before authoring. The 2.10 line is no longer in the official
  maintained-tags listing; operators upgrading from a Phase-0 PoC that
  pinned `2.10-alpine` should move to `2.11-alpine` in Box-3.
  Verification was a Docker Hub web snapshot; a `docker pull` on the
  build host before Box-3 commit is mandatory and must reproduce the
  digest in the `compose/nats.yaml` image-pin line.
- `nats-py` version: not pinned in this runbook. Pinning belongs in
  the orchestrator container's Python dependency manifest, not in
  this operator-facing document.
- Hermetic regression suite: 10 tests pass under Python 3.14.4 +
  pytest 9.0.3 (Phase-1b shared `.venv`); `tests/orchestrator/`.
