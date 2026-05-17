# Wakir Runtime

The operational runtime for accountable multi-agent systems. Pairs
typed inter-agent messaging with capability tokens, an identity
substrate, and Bitcoin-anchored audit trails so that what your
agents did, and what they were allowed to do, remains verifiable to
a third party years later.

## How the three repositories fit together

The Wakir stack ships as three coordinated repositories:

- **[`wakir-protocol`](https://github.com/wakir-labs/wakir-protocol)**
  — the language: Wirelang specs, JSON schemas, capability-token
  envelope, identity substrate. Apache-2.0 for code, CC-BY-4.0 for
  the spec prose.
- **`wakir-runtime`** (this repository) — the operator: the
  reference implementation that turns the protocol into a running
  organization. Mixed-license, BUSL-1.1-dominant for operational
  modules, Apache-2.0 for the foundation. Converts to Apache-2.0
  on stated Change Dates.
- **[`wakir-verify`](https://github.com/wakir-labs/wakir-verify)**
  — the third-party check: a single-binary verifier that
  reconstructs an inclusion proof from a public WAT archive and
  validates the Bitcoin attestation. Apache-2.0, zero PyPI surface
  on the hot path.

The one-line gloss:

> `wakir-protocol` defines the language, `wakir-runtime` operates
> the organization, `wakir-verify` checks the proof.

If you only need to validate an audit trail someone else published,
you want `wakir-verify`. If you want to read or implement the
on-the-wire formats, you want `wakir-protocol`. If you want to run
an accountable multi-agent organization end-to-end, you are in the
right place.

## What lives in this repository

- **WAT (Wakir Audit Trail)** — Bitcoin-anchored audit trail with
  per-hour Merkle aggregation and a verification CLI; the module
  lives under [`wat/`](wat/) and is the subject of the rest of this
  README.
- **Container orchestrator** — the agent-per-container deployment
  substrate that runs each persona in its own boundary.
- **Federation substrate** — A2A and ERC-8004 adoption plus a
  cross-organization audit federation annex.
- **Persona engine** — the runtime layer that resolves agent
  identities, capability tokens, and routing decisions against the
  protocol-layer schemas.

The protocol-layer artefacts that these components consume —
Wirelang specs, JSON schemas, the capability-token envelope, the
identity substrate — live in `wakir-protocol` and are pulled in
either as a PyPI dependency or as a sibling clone during
development. See [Protocol-layer dependency](#protocol-layer-dependency)
below.

## WAT module

The Wakir Audit Trail aggregates inter-agent messages into a
per-hour Merkle tree, anchors each hourly root to Bitcoin via
OpenTimestamps, and stores enough manifest metadata next to each
receipt so that any third party can reconstruct an inclusion proof
for a specific event without access to a Wakir-side database.

The audit horizon WAT is designed for is three years of online
verifiability per anchored hour, with public Bitcoin attestation
giving the irreversible time bound.

The module lives under [`wat/`](wat/) and is laid out as:

- `wat/merkle/` — Merkle tree construction
- `wat/anchor/` — OpenTimestamps anchor pipeline
- `wat/verify/` — server-side verification helpers
- `wat/cmd/` — console-script entry points

A separate, Apache-2.0-licensed offline verifier ships as its own
public repository: [`wakir-labs/wakir-verify`](https://github.com/wakir-labs/wakir-verify).
That verifier is the public brand-proof tool and runs without any
WAT-side state. The in-tree console script `wakir-wat-verify`
under [`wat/verify/cli.py`](wat/verify/cli.py) is the BUSL-1.1
operator-facing convenience verifier and stays here as
hosted-service substrate; it was renamed from `wakir-verify` to
avoid a console-script-name collision with the standalone
Apache-2.0 package.

To install the offline brand-proof verifier alongside this runtime
without manually depending on the upstream package, use the
`[verify]` extra:

```sh
pip install 'wakir-runtime[verify]'
```

That pulls in `wakir-verify>=0.1.0` from PyPI and exposes the
standalone `wakir-verify` console script in the same environment
as `wakir-wat-verify`.

## Protocol-layer dependency

The Apache-2.0 protocol layer — Wirelang specs, JSON schemas,
AIP/DID identity substrate, Biscuit capability-token wrapper —
ships in [`wakir-labs/wakir-protocol`](https://github.com/wakir-labs/wakir-protocol).
To opt in to the protocol-layer dependency, install the
`[protocol]` extra:

```sh
pip install 'wakir-runtime[protocol]'
```

That pulls in `wakir-protocol>=0.1.0` from PyPI. The in-tree
`wirelang/` package retains the BUSL-1.1 runtime-internal modules
(`federation/`, `persona_engine/`,
`identity/federation_resolver.py`, `persona/persona_state_kv*.py`,
`cli/marker_stack_*.py`) as part of the operational substrate
during the transitional period; the import migration from
`wirelang.*` to `wakir_protocol.*` is in progress.

## Setup

The setup script provisions a project-local venv at `.venv`,
installs the package in editable mode with the `[test]` extras,
and verifies that the `ots` CLI from `opentimestamps-client` is
on `PATH`. After that the three console scripts are available:

```sh
bash scripts/setup.sh
source .venv/bin/activate

wakir-merkle --help
wakir-anchor --help
wakir-wat-verify --help
```

`wakir-wat-verify` rebuilds the inclusion proof for an event from
the hour manifest, recomputes the leaf hash from the four
B1-consensus fields (`event_id`, `time`, `payload_hash`,
`capability_token_hash`), checks the proof against the stored
Merkle root, and runs `ots verify` on the per-hour receipt. Exit
codes are `0` (verified), `1` (failed), `3` (pending Bitcoin
confirmation).

## End-to-end flow

The three console scripts compose into a single contract:

```sh
# 1. Spool one JSONL event per line for an hour, with the four
#    B1-consensus fields on every event.
cat > /tmp/2026-05-06T17.jsonl <<'EOF'
{"event_id":"evt-0000","time":"2026-05-06T17:00:00Z","payload_hash":"00...","capability_token_hash":"01..."}
{"event_id":"evt-0001","time":"2026-05-06T17:01:00Z","payload_hash":"02...","capability_token_hash":"03..."}
EOF

# 2. Build the hour manifest. Output is JSON in the format documented
#    in docs/wat-manifest-spec.md; the same file is later read by
#    wakir-wat-verify.
mkdir -p /tmp/wat-archive/2026-05-06T17
wakir-merkle build \
    --hour 2026-05-06T17 \
    --input-events /tmp/2026-05-06T17.jsonl \
    --output-manifest /tmp/wat-archive/2026-05-06T17/manifest.json

# 3. Anchor the resulting Merkle root via OpenTimestamps. Reads the
#    root from the manifest and writes root.bin and root.bin.ots
#    into the per-hour archive directory.
ROOT_HEX=$(python -c "import json; print(json.load(open('/tmp/wat-archive/2026-05-06T17/manifest.json'))['merkle_root'])")
wakir-anchor stamp "$ROOT_HEX" --out /tmp/wat-archive/2026-05-06T17 --min-calendars 2

# 4. Verify a single event end-to-end. Exit 0 means the event is in
#    the manifest, the inclusion proof rebuilds to the manifest root,
#    and the OTS receipt has been finalised on Bitcoin.
wakir-wat-verify evt-0001 --archive-dir /tmp/wat-archive
```

Empty hours short-circuit cleanly: `wakir-merkle build` emits a
manifest with `merkle_root: null` and the hourly driver
(`scripts/wat-hourly.sh`) skips the anchor step.

## WAT hourly operations

Two systemd timer templates land under `scripts/systemd/`. The
hourly anchor timer drives `scripts/wat-hourly.sh` five minutes
past each UTC hour boundary; the backfill timer drives
`scripts/wat-backfill.sh` four times a day.

```sh
mkdir -p ~/.config/systemd/user
cp scripts/systemd/wakir-wat-hourly.{service,timer} ~/.config/systemd/user/
cp scripts/systemd/wakir-wat-backfill.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wakir-wat-hourly.timer wakir-wat-backfill.timer
```

Both services need `WAKIR_EVENT_SPOOL` (input) and
`WAKIR_RECEIPT_ARCHIVE` (output) defined in your user environment,
e.g. in `~/.config/environment.d/wakir.conf`.

The drivers log to systemd-journald with the `[wat-hourly]` and
`[wat-backfill]` prefixes:

```sh
journalctl --user -u wakir-wat-hourly.service -f
journalctl --user -u wakir-wat-backfill.service --since '1 day ago'
```

A backfill exit code of `1` means at least one pending receipt has
aged past the seven-day soft window; the audit-alarm channel
surfaces those for human review.

### Backfill operations

The backfill driver is the failsafe for the hourly anchor: when
the public OpenTimestamps calendars are unreachable for several
consecutive hours, pending receipts accumulate in the archive and
need to be upgraded once the calendars come back. The four-runs-
per-day cadence (00:30, 06:30, 12:30, 18:30 UTC) is documented in
`scripts/systemd/wakir-wat-backfill.timer`: a single
Bitcoin-confirmation delay never holds a pending receipt for more
than about six hours.

Soft-window behaviour:

- pending receipts ≤ 7 days old are silently retried every pass,
- pending receipts > 7 days old trigger the hard alarm path (exit
  code 1, ERROR-level log line `backfill: receipt … pending for
  N days (soft window 7)` in the journal),
- finalised receipts are reported once with their Bitcoin block
  height and then ignored on subsequent passes.

To override the default soft window for a specific deployment,
set `WAKIR_BACKFILL_MAX_AGE` (in days) in the service environment.
This should be a deliberate, documented choice — the seven-day
default is a soft commitment to anyone reading
`docs/wat-tv3-test-plan.md` §3.

## Smoke test

Two layers of smoke coverage land under `tests/wat/` and `scripts/`.

### Realistic OTS integration tests

`tests/wat/test_ots_integration.py` walks the production code path
against the public OpenTimestamps calendar pool. The tests are
opt-in and gated on the `OTS_INTEGRATION_TEST` environment variable
so CI never touches the public calendars on every push.

```sh
OTS_INTEGRATION_TEST=1 pytest tests/wat/test_ots_integration.py
```

Without the env variable set the four cases skip cleanly. Calendar
operators run the public infrastructure for free; please do not
run the suite in a tight loop.

### One-command smoke driver

`scripts/wat-smoke-test.sh` is the auditor / pipeline-friendly
single-command driver: it spools synthetic events, walks
`build -> stamp -> verify-pending`, and exits with the same code
shape as `wakir-wat-verify` (`0` finalised, `1` failed, `3`
pending, `4` chain-mismatch).

```sh
bash scripts/wat-smoke-test.sh           # full run, with sleep
bash scripts/wat-smoke-test.sh --quick   # skip the upgrade wait
```

The full smoke-test plan, including 100-event vectors and
calendar-failover drills, is documented in
[`docs/wat-smoke-test-plan.md`](docs/wat-smoke-test-plan.md).

## CI matrix

Three GitHub Actions workflows guard this repository:

- **`tests.yml` — production lane.** Full install set
  (`rfc8785` + `jsonschema` + everything in `dependencies`). Pairs
  with the sandbox lane below for the two-sided drift envelope.
- **`sandbox-ci.yml` — sandbox lane.** Minimal install set (no
  `rfc8785`, no `jsonschema`). Proves the pure-Python fallback
  path stays green. Drift between sandbox and production-lane
  collected-counts is itself a CI signal.
- **`external-verifier-drift.yml` — python-bitcoinlib drift
  matrix.** Runs the external-verifier test surface against three
  pinned `python-bitcoinlib` versions on Python 3.12. The matrix
  probes three invariants any auditor-injected
  `python-bitcoinlib`-backed `proof_reader` depends on:
  block-hash byte-order canonicalisation (`b2lx` vs `b2x`),
  OP_RETURN script serialisation round-trip, and
  `bitcoin.__version__` packaging sanity. The verifier
  sub-package itself does NOT import `python-bitcoinlib` (zero-
  PyPI-surface brand-proof posture); the matrix instead pins the
  contract the moment an auditor or operator chooses to layer it
  in via the documented `proof_reader` injection seam. Matrix
  jobs that fail to install a pinned version emit a
  `skip-with-marker` warning rather than failing the workflow —
  a single version dropping out of Python-interpreter support
  must not block the rest of the matrix.

## WAT bridge — Wirelang frame ingestion

The bridge that sits between the Wirelang Layer-1 frame stream
and the hourly aggregator lives under
[`wat/ingestion/`](wat/ingestion/). It exposes two pieces:

- `project_l1_frame_to_leaf(frame)` — projects a CloudEvents-1.0
  + Wakir-extension frame onto the 9-field `LeafRecord` (4 B1
  hash-input fields + 5 audit-metadata fields per
  [`docs/wat-spool-spec.md`](docs/wat-spool-spec.md) §2). The
  four hash-input fields are the `compute_leaf_hash` input.
- `append_leaf_to_spool(leaf, spool_dir)` and
  `seal_hour(spool_dir, hour_slot)` — JSONL append plus the
  atomic rename that flips an open `<hour>.jsonl` to
  `<hour>.jsonl.sealed` once the H_end + 5min late-frame window
  has elapsed.

The hourly cron driver (`scripts/wat-hourly.sh`) seals the hour
file before invoking `wakir-merkle build`, which reads the
`.sealed` artefact rather than the open spool file.

### Bridge behaviour

Three points worth knowing when integrating against the bridge:

1. **Test-vector metadata convention.** Test-vector JSON files
   under `tests/fixtures/jcs-leaf-vectors/` reserve leading-
   underscore keys (`_spdx`, `_copyright`, `_notes`) at the top
   level for non-schema metadata. The `input` and
   `expected_leaf_hash` blocks are schema-bearing; the
   underscore-prefixed keys are stripped by machine consumers
   via a single-character prefix check. The convention is
   asserted in `tests/wat/test_hash_consistency.py` so a vector
   that omits the metadata fails CI.
2. **Multi-capability ordering.** The leaf projection commits to
   `caprefs[0]` per
   [`wirelang/specs/wat-leaf-projection.md`](wirelang/specs/wat-leaf-projection.md)
   §3.4.1. Producers control ordering; the first entry is the
   capability primarily invoked. A future v2 may introduce a
   multi-cap representation, additively. Producers that need to
   bind multiple capabilities into the audit trail today should
   emit one frame per capability.
3. **`recovery-drill-` prefix namespace.** The recovery-drill
   projection
   ([`wirelang/specs/recovery-drill-leaf-projection.md`](wirelang/specs/recovery-drill-leaf-projection.md)
   §2.1) prefixes drill `event_id`s with `recovery-drill-`. The
   bridge treats `event_id` byte-faithfully and does not bless
   or reject the prefix; namespace disjointness with regular
   UUIDv7 IDs is the producer's responsibility. Unit-tested in
   `tests/wat/test_bridge.py::test_event_id_namespace_disjoint`.

## Specifications

The cross-module contracts between Wirelang and WAT are
documented in plain Markdown under `docs/` and `wirelang/specs/`:

- [`wirelang/specs/wat-leaf-projection.md`](wirelang/specs/wat-leaf-projection.md)
  — how a Layer-1 frame projects onto the four-field WAT leaf
  tuple.
- [`docs/wat-spool-spec.md`](docs/wat-spool-spec.md) — the JSONL
  hour-spool format the bridge writes and the aggregator reads.
- [`docs/wat-hash-spec.md`](docs/wat-hash-spec.md) — the
  cross-domain JCS+SHA-256+hex-lower hash contract shared by all
  WAT-anchored data.
- [`docs/wat-manifest-spec.md`](docs/wat-manifest-spec.md) — the
  hourly manifest format that the verify CLI consumes.
- [`wirelang/specs/recovery-drill-leaf-projection.md`](wirelang/specs/recovery-drill-leaf-projection.md)
  — how quarterly cold-storage recovery drills project onto WAT
  leaves for three-year audit beyond the operator's own logs.

Test vectors for the JCS+SHA-256 leaf hash live under
[`tests/fixtures/jcs-leaf-vectors/`](tests/fixtures/jcs-leaf-vectors/).
Five vectors cover empty payloads, typical capability-bound
frames, the no-capability-token path, multi-byte UTF-8, and large
nested payloads. Each vector ships with a pre-computed
`expected_leaf_hash` that matches
`wat.merkle.aggregator.compute_leaf_hash`.

## Repository layout

```
wat/            — Wakir Audit Trail module (BUSL-1.1)
wirelang/       — runtime-internal modules (BUSL-1.1) plus
                  transitional Apache-2.0 sources mirrored from
                  wakir-protocol
tooling/        — CI/CD helpers              (Apache-2.0)
scripts/        — setup and maintenance      (Apache-2.0)
tests/          — test suite                 (Apache-2.0)
docs/           — Markdown documentation     (CC-BY-4.0)
```

## License

This repository is mixed-license. Apache-2.0 is the default for
foundation code and verifier tooling. Selected operational
modules are licensed under BUSL-1.1 and convert to Apache-2.0 on
their stated Change Date. Documentation is CC-BY-4.0 where
marked. See [LICENSING.md](./LICENSING.md) for the authoritative
map.

See [NOTICE](NOTICE) for the attribution required by Apache-2.0,
[GOVERNANCE.md](./GOVERNANCE.md) for the human-governance
posture, [BRAND.md](./BRAND.md) for trademark and brand-asset
posture, and [ATTRIBUTION.md](./ATTRIBUTION.md) for sponsorship,
work-product, and third-party attribution context.

## Brand

Wakir Labs is a project of Callandor GmbH. Documentation files
in this repository are released under Creative Commons
Attribution 4.0 International (CC-BY-4.0) where indicated.
