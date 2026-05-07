<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Test Plan — `scripts/post-install-live-smoke.sh`

Status: Phase-1b Sprint-3 Tag-4 — pre-build-host-activation
test plan. Companion to `scripts/post-install-live-smoke.sh`.
This file documents the verification strategy that the supervisory-
board side runs once the build-host activation pass (operator
runbook §7.1 steps 2-5) has completed and the post-install live
smoke is the next thing to drive.

The plan is intentionally **markdown rather than pytest** because
the artefact under test is a multi-step bash driver that brings up
a real container substrate: a hermetic pytest is not the right
shape (it would either need a heavy compose-in-pytest harness or
re-implement the substrate in a mock, both of which lose the very
property the smoke is meant to verify, namely that the wired-up
build-host can in fact bring NATS up). The script's per-step exit-
code contract and its JSON summary on stdout are the machine-
parseable hooks that an operator wraps in a one-shot CI pass once
a build-host is online.

## 0. Pre-conditions

| # | Pre-condition                                  | How to verify                                |
|---|------------------------------------------------|----------------------------------------------|
| P1 | Build-host steps 2-5 of runbook §7.1 done      | `gcc --version`, `podman --version`, `podman-compose --version`, `nats --version`, `.venv/bin/python3 -c 'import nats'` all 0 |
| P2 | Repo cloned at `~/wakir-runtime` (or path)     | `[ -f compose/nats.yaml ]` and `[ -f scripts/post-install-live-smoke.sh ]` |
| P3 | venv populated with `nats-py`                  | `.venv/bin/python3 -c 'import nats; print(nats.__version__)'` exits 0 |
| P4 | NATS port 4222 free on host                    | `ss -lntp \| grep ':4222'` empty (or pre-existing nats container can be reused) |
| P5 | NATS HTTP port 8222 free on host               | `ss -lntp \| grep ':8222'` empty |
| P6 | Disk free in `/var/lib` and venv path ≥ 200 MB | `df -h` |

If any pre-condition is unmet, the script's own preflight (step 1)
is the failure surface — exit-code 1 with a JSON summary listing
the missing tools or files. Re-run after fixing.

## 1. Test-case inventory

The script is exercised across four operational modes plus three
fault-injection scenarios. Each row gives the invocation, the
expected steps to pass/fail/skip, and the expected exit code.

### 1.1 Happy-path full run

| Case ID | Invocation                                        | Expected step results                                                                                          | Expected exit |
|---------|---------------------------------------------------|----------------------------------------------------------------------------------------------------------------|---------------|
| TC-01   | `./scripts/post-install-live-smoke.sh`            | 1 ok, 2 ok, 3 ok, 4 ok, 5 ok, 6 ok, 7-pre ok, 7-teardown ok                                                    | 0             |

Notes:
* TC-01 is the canonical "build-host activation done" smoke. It
  pulls the image, brings the substrate up, runs the bucket init
  (creates four buckets on a fresh volume, no-op on a dirty one),
  round-trips a synthetic probe through the live KV bucket via
  the real `nats-py` adapter, runs the read-only KV health check,
  and tears the stack down with the volume removed.
* On a fresh build-host the wallclock is dominated by step 2
  (image pull, ~5-15 s on broadband) and step 4 (wait-ready,
  ~3-8 s). The full run typically completes in ≤ 60 s.

### 1.2 Operator-driven mode variations

| Case ID | Invocation                                                | Expected step results                                                                                       | Expected exit |
|---------|-----------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|---------------|
| TC-02   | `./scripts/post-install-live-smoke.sh --dry-run`          | 1 ok (preflight always real), 2 skip, 3 skip, 4 skip, 5 skip, 6 skip, 7-pre skip, 7-teardown skip          | 0             |
| TC-03   | `./scripts/post-install-live-smoke.sh --skip-teardown`    | 1-6 + 7-pre ok, 7-teardown skip                                                                             | 0             |
| TC-04   | `./scripts/post-install-live-smoke.sh --keep-volume`      | 1-6 + 7-pre ok, 7-teardown ok (compose down without `-v`)                                                   | 0             |
| TC-05   | `./scripts/post-install-live-smoke.sh --no-real-adapter`  | 1-5 ok, 6 skip, 7-pre ok, 7-teardown ok                                                                     | 0             |
| TC-06   | `./scripts/post-install-live-smoke.sh --engine docker`    | as TC-01, but `compose_bin` is `docker compose` and engine is `docker`                                      | 0             |

Verification specifics:

* **TC-02 (dry-run):** preflight runs for real (it is read-only), but
  steps 2-7 record `skip` and the JSON `highest_exit` is 0. This is
  the smoke we run on every CI tick on a host that is not the
  build-host itself.
* **TC-03 (skip-teardown):** after the script exits, the operator
  runs `podman ps --filter name=wakir-nats` and confirms one
  container still up; manual `podman-compose -f compose/nats.yaml
  down -v` is the cleanup.
* **TC-04 (keep-volume):** after teardown the volume
  `wakir-nats-jetstream-data` survives; `podman volume ls --filter
  name=wakir-nats-jetstream-data` shows one entry. The next run
  finds the buckets already initialised (idempotency).
* **TC-05 (no-real-adapter):** step 6 records `skip`; the JSON
  reflects this. Useful when nats-py-API churn temporarily breaks
  step 6 but the substrate-side smoke is still wanted.
* **TC-06 (docker engine):** the `nats:2.11-alpine` pull goes via
  Docker; `compose_bin` is `docker compose` (subcommand, not
  `docker-compose-plugin` legacy). Functionally identical otherwise.

### 1.3 Fault-injection cases

| Case ID | Fault setup                                          | Invocation                                              | Expected step results                              | Expected exit |
|---------|------------------------------------------------------|---------------------------------------------------------|----------------------------------------------------|---------------|
| TC-07   | uninstall `nats-cli` (`sudo rm /usr/local/bin/nats`) | `./scripts/post-install-live-smoke.sh`                  | 1 fail (preflight catches missing tool)            | 1             |
| TC-08   | break venv (`mv .venv .venv.bak`)                    | `./scripts/post-install-live-smoke.sh`                  | 1 fail (preflight catches missing `.venv/bin/python3`) | 1         |
| TC-09   | port 4222 in use (`nc -lp 4222 &`)                   | `./scripts/post-install-live-smoke.sh`                  | 1 ok, 2 ok, 3 ok or fail, 4 may fail               | 2             |
| TC-10   | NATS image-tag does not resolve (offline host)       | unplug network, then run                                | 1 ok, 2 fail (image pull errors)                   | 2             |
| TC-11   | bucket-init drift (operator pre-creates a bucket with non-default config; e.g. `nats kv add wakir-schemas --history=99`) | `./scripts/post-install-live-smoke.sh`                  | 1-4 ok, 5 fail (init exits 2 on drift)             | 3             |
| TC-12   | adapter probe key collision (operator pre-puts a different value at `wakir-schemas/post-install-live-smoke-probe`) | `./scripts/post-install-live-smoke.sh`                  | 1-5 ok, 6 ok (the probe overwrites and re-asserts) | 0             |

Notes on the fault-injection cases:

* **TC-09:** behaviour depends on the engine: `podman-compose up`
  may report port-allocation failure at step 3, or it may succeed
  but the wait-ready loop (step 4) never sees a healthy `/jsz`.
  Either path lifts `highest_exit` to 2.
* **TC-10:** the image pull failure surfaces with the engine's own
  error text on stderr; the script records step 2 as `fail` and
  the EXIT trap still attempts teardown (which is a no-op because
  the substrate never came up).
* **TC-11:** the `init-nats-buckets.py` driver exits 2 on
  documented configuration drift (see its `--help`); the smoke
  script lifts `highest_exit` to 3 and the teardown still runs.
* **TC-12:** the script's adapter snippet uses `kv.put` (not
  `create`), so a pre-existing key is overwritten cleanly. The
  cleanup at the end of step 6 re-asserts the post-condition.

### 1.4 Idempotency cases

| Case ID | Setup                                                    | Invocation                                                          | Expected step results                              | Expected exit |
|---------|----------------------------------------------------------|---------------------------------------------------------------------|----------------------------------------------------|---------------|
| TC-13   | run TC-01 once, then re-run with `--keep-volume`         | `./scripts/post-install-live-smoke.sh --keep-volume` (twice)        | first: 1-7-pre ok, 7-teardown ok (no -v); second: identical, but step 5 reports "no changes" in init-nats-buckets JSON output | 0 both runs   |
| TC-14   | repeat TC-01 with `--skip-teardown`, then run TC-01 plain | first leaves stack up; second sees `wakir-nats` already running    | first: 1-7-pre ok, 7-teardown skip; second: 1-3 may report "already running" warnings (engine-dependent) but should converge ok | 0 both runs   |

## 2. Verification mechanics

### 2.1 Per-step assertions

For TC-01 (and the other green-path cases), the operator confirms
each step result in three places:

1. **stderr line log:** every step prints a `[step N/7]` opening
   line and, on success, an `ok` closing line; on failure, an
   `[error]` line.
2. **stdout JSON summary:** at end-of-run, a single JSON object
   lists every step with `name`, `result` (`ok`/`fail`/`skip`),
   and `duration_s`. The operator pipes stdout to `jq` (e.g.
   `./scripts/post-install-live-smoke.sh | tee /tmp/smoke.json |
   jq '.highest_exit'`).
3. **exit code:** `echo $?` after the run; matches the JSON
   `highest_exit`.

### 2.2 Side-effect assertions

After TC-01:

```bash
# Buckets exist with documented config:
nats --server=nats://127.0.0.1:4222 kv ls
# expected: wakir-schemas, wakir-aip-cache, wakir-ftd-cache,
#           wakir-ftd-poisoned (no others created by the smoke)

# The synthetic probe key was deleted at end of step 6:
nats --server=nats://127.0.0.1:4222 kv get wakir-schemas \
  post-install-live-smoke-probe
# expected: "Error: nats: key not found" (after teardown the
# bucket itself is also gone if -v was passed)

# The teardown removed the volume:
podman volume ls --filter name=wakir-nats-jetstream-data
# expected: empty (no row) when run without --keep-volume
```

### 2.3 JSON-summary contract

Every run, regardless of success or failure, emits a single JSON
object on stdout. Schema:

```json
{
  "tool": "post-install-live-smoke.sh",
  "phase": "phase-1b-sprint-3-tag-4",
  "engine": "podman" | "docker",
  "compose_bin": "podman-compose" | "docker compose",
  "nats_server": "nats://...",
  "jsz_url": "http://.../jsz",
  "highest_exit": 0..6,
  "steps": [
    {"name": "<step-name>", "result": "ok"|"fail"|"skip", "duration_s": "<int|->"},
    ...
  ]
}
```

The schema is intentionally minimal; the runbook §7 next-sprint
backlog tracks adding a Prometheus textfile-collector emit so the
post-install smoke participates in §7.2 monitoring (Sprint-4
follow-up).

### 2.4 Exit-code reference

| Exit | Meaning                                               | Operator action                                                          |
|------|-------------------------------------------------------|--------------------------------------------------------------------------|
| 0    | all steps clean                                       | none; the post-install activation is verified                            |
| 1    | preflight failure                                     | rerun runbook §7.1 steps 2-5 to fix the missing tool/path                |
| 2    | substrate did not come up or did not become ready     | check engine logs (`podman ps -a`, `podman logs wakir-nats`); verify port 4222/8222 free |
| 3    | bucket init exit non-zero                             | re-read `init-nats-buckets.py` JSON output to identify drift; manual `nats kv` rm/recreate per documented config |
| 4    | real-adapter smoke failed (import, connect, mismatch) | check nats-py version; re-run with `--no-real-adapter` to confirm the rest of the pipeline; isolate the import vs network vs round-trip cause from stderr |
| 5    | KV health check exit non-zero                         | rerun the health check directly with verbose stderr; inspect the JSON it emits to identify the failing bucket |
| 6    | teardown failed                                       | manual `podman-compose -f compose/nats.yaml down -v`; investigate stuck container or volume |

## 3. Out of scope

* **`pytest`-driven invocation of the smoke script:** the existing
  pytest suite is hermetic by contract; running a real-engine
  compose pass inside pytest would break that contract. The
  `tests/orchestrator/test_compose_nats.py` parser-level tests
  cover the compose file's static shape; the live-smoke is the
  complement of that, not a substitute.
* **`systemd-analyze verify` of the §7.2 timer units:** that
  belongs to the build-host activation pass itself (Sprint-3
  Tag-2 follow-up); the smoke script does not enable any timers.
* **Prometheus textfile-collector emit from the smoke:** out of
  scope here; the smoke writes a one-line JSON summary on stdout.
  A textfile-collector wrapper is a Sprint-4 follow-up.
* **SPIFFE/SVID token injection:** the Phase-1b NATS substrate is
  unauthenticated; the smoke does not deal with auth. Cross-Review
  Zone A drop-in upgrade once the SPIRE-server side lands.
* **Multi-host federation smoke:** Phase-3.

## 4. Cross-tool consistency

The seven steps in the smoke are deliberately a strict subset of
the operator runbook §7.1 step ordering — the smoke automates the
post-step-5 verification that an operator would do by hand. Any
divergence in the step order between this script and the runbook
is a drift bug; the canonical source is the runbook §7.1.

The bucket inventory consumed by step 5 (init) and step 7-pre
(health check) is shared with the existing hermetic regression
test `test_inventory_matches_init_nats_buckets`. If the inventory
is changed, all three (init script, health-check tool, this smoke)
should be re-pinned in the same diff.

## 5. Approval gate

Before the supervisory-board approval pass green-lights running
the smoke on the build-host:

1. The seven runbook §7.1 steps must be done (gcc, podman,
   podman-compose, nats-cli, nats-py-in-venv all green).
2. The host's `df -h` and `free -h` show the documented headroom
   (≥ 2 GB free disk, ≥ 2 GB RAM).
3. No production NATS endpoint is reachable from the host (the
   smoke is unauthenticated; pointing it at a production cluster
   is a deployment-side error). Verify by `nats --server=<prod>
   server check connection` returning a connection-refused or
   auth-error from the production cluster.

The first run of the smoke on the build-host should be supervised
(operator watches the line log on stderr); subsequent runs (e.g.
post-image-bump, post-bucket-inventory-change) can be unattended.
