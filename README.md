# Wakir Runtime

The reference implementation of the Wakir Labs framework for accountable
multi-agent systems: typed inter-agent messaging, capability tokens,
identity substrate, and audit trails anchored to Bitcoin.

This repository is in early development. Architecture decisions and
implementation notes will land here as the framework comes together.

## Status

Pre-launch. The first build phase begins in calendar week 21 of 2026.
Foundation work has been pulled forward by one week and is in flight.

## What lives here

- **Wirelang** — typed inter-agent message schema (transport, wire format,
  semantic, audit layers)
- **WAT (Wakir Audit Trail)** — Bitcoin-anchored audit trail layer with
  per-hour Merkle aggregation and verification CLI; lives in [`wat/`](wat/).
  See [WAT module](#wat-module) below.
- **Capability tokens** — adoption of AIP and Biscuit, with a Wakir
  vocabulary and Datalog caveat set
- **Container orchestrator** — agent-per-container deployment substrate
  (later phase)
- **Federation** — adoption of A2A and ERC-8004 standards plus a
  cross-organisation audit federation annex (later phase)

## WAT module

The Wakir Audit Trail aggregates inter-agent messages into a per-hour
Merkle tree, anchors each hourly root to Bitcoin via OpenTimestamps,
and stores enough manifest metadata next to each receipt so that any
third party can reconstruct an inclusion proof for a specific event
without access to a Wakir-side database.

The audit horizon WAT is designed for is three years of online
verifiability per anchored hour, with public Bitcoin attestation
giving the irreversible time bound.

The module lives under [`wat/`](wat/) and is laid out as:

- `wat/merkle/` — Merkle tree construction
- `wat/anchor/` — OpenTimestamps anchor pipeline
- `wat/verify/` — server-side verification helpers
- `wat/cmd/` — console-script entry points

A separate, Apache-2.0-licensed offline verifier ships in its own
public repository: [`wakir-labs/wakir-verify`](https://github.com/wakir-labs/wakir-verify).
That verifier is the public brand-proof tool and runs without any
WAT-side state. It was split out of this repository as ADR-0062
Cut-1; the substance-classification rationale lives in
[`docs/decisions/cut1-verifier-substance-classification.md`](docs/decisions/cut1-verifier-substance-classification.md).
The in-tree console script `wakir-wat-verify` under
[`wat/verify/cli.py`](wat/verify/cli.py) is the BUSL-1.1 operator-
facing convenience verifier and stays here as hosted-service
substrate; it was renamed from `wakir-verify` to avoid a console-
script-name collision with the standalone Apache-2.0 package
(ADR-0062 Cut-1 follow-up, 2026-05-16).

To install the offline brand-proof verifier alongside this runtime
without manually depending on the upstream package, use the
`[verify]` extra:

```sh
pip install 'wakir-runtime[verify]'
```

That pulls in `wakir-verify>=0.1.0` from PyPI and exposes the
standalone `wakir-verify` console script in the same environment
as `wakir-wat-verify`.

## Setup

The setup script provisions a project-local venv at `.venv`, installs
the package in editable mode with the `[test]` extras, and verifies
that the `ots` CLI from `opentimestamps-client` is on `PATH`. After
that the three console scripts are available:

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
hourly anchor timer drives `scripts/wat-hourly.sh` five minutes past
each UTC hour boundary; the backfill timer drives
`scripts/wat-backfill.sh` four times a day.

```sh
mkdir -p ~/.config/systemd/user
cp scripts/systemd/wakir-wat-hourly.{service,timer} ~/.config/systemd/user/
cp scripts/systemd/wakir-wat-backfill.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wakir-wat-hourly.timer wakir-wat-backfill.timer
```

Both services need `WAKIR_EVENT_SPOOL` (input) and
`WAKIR_RECEIPT_ARCHIVE` (output) defined in your user environment, e.g.
in `~/.config/environment.d/wakir.conf`.

The drivers log to systemd-journald with the `[wat-hourly]` and
`[wat-backfill]` prefixes:

```sh
journalctl --user -u wakir-wat-hourly.service -f
journalctl --user -u wakir-wat-backfill.service --since '1 day ago'
```

A backfill exit code of `1` means at least one pending receipt has
aged past the seven-day soft window; the audit-alarm channel surfaces
those for human review (WAT-Phase-1a-Spec §3.4).

### Backfill operations setup

The backfill driver is the failsafe for the hourly anchor: when
the public OpenTimestamps calendars are unreachable for several
consecutive hours, pending receipts accumulate in the archive and
need to be upgraded once the calendars come back. The 4×/day
cadence (00:30, 06:30, 12:30, 18:30 UTC) is documented in
`scripts/systemd/wakir-wat-backfill.timer` and is the expected
operational frequency: a single Bitcoin-confirmation delay never
holds a pending receipt for more than ~6 hours.

Soft-window behaviour:

- pending receipts ≤ 7 days old are silently retried every pass,
- pending receipts > 7 days old trigger the hard alarm path (exit
  code 1, ERROR-level log line `backfill: receipt … pending for
  N days (soft window 7)` in the journal),
- finalised receipts are reported once with their Bitcoin block
  height and then ignored on subsequent passes (the upgrade is
  a no-op).

To override the default soft window for a specific deployment,
set `WAKIR_BACKFILL_MAX_AGE` (in days) in the service environment.
This should be a deliberate, documented choice — the seven-day
default is a soft commitment to anyone reading
`docs/wat-tv3-test-plan.md` §3.

#### SRE persona handoff (post-ADR-0042)

Backfill alarm channel design — journal-grep cadence, ntfy topic,
escalation policy, dashboard rendering — is operational concern,
not implementation concern. Once the SRE persona is activated in
KW 22-23 of 2026 (per ADR-0042), the following items move to the
SRE inbox:

- decide on a journal-grep tool and cadence for surfacing
  `[wat-backfill]` ERROR lines,
- pick an ntfy.sh topic and message template for breached
  receipts,
- define escalation steps (auto-page vs. dashboard accumulation),
- own the runbook for the case where an aged receipt cannot be
  upgraded (calendar permanently lost a record, manifest needs
  re-anchoring).

Until the SRE persona is active, the operator runs
`journalctl --user -u wakir-wat-backfill.service --since '1 day
ago' | grep ERROR` once a day as the manual stand-in. The
implementation contract — exit code 1 on breach, `ERROR` log line
on each breached receipt — is fixed by `tests/wat/test_tv3_
backfill_leg.py` and will not shift under SRE.

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
operators run the public infrastructure for free; please do not run
the suite in a tight loop.

### One-command smoke driver

`scripts/wat-smoke-test.sh` is the auditor / pipeline-friendly
single-command driver: it spools 8 synthetic events, walks
`build -> stamp -> verify-pending`, and exits with the same code
shape as `wakir-wat-verify` (`0` finalised, `1` failed, `3`
pending, `4` chain-mismatch).

```sh
bash scripts/wat-smoke-test.sh           # full run, 5-min sleep
bash scripts/wat-smoke-test.sh --quick   # skip the upgrade wait
```

The full Tag-22 smoke plan, including 100-event vectors and
calendar-failover drills, is documented in
[`docs/wat-smoke-test-plan.md`](docs/wat-smoke-test-plan.md).

## CI matrix

Three GitHub Actions workflows guard this repository:

- **`tests.yml` — wirelang production lane.** Full install set
  (`rfc8785` + `jsonschema` + everything in `dependencies`). Pairs
  with the sandbox lane below for the two-sided drift envelope.
- **`sandbox-ci.yml` — wirelang sandbox lane.** Minimal install set
  (no `rfc8785`, no `jsonschema`). Proves the pure-Python fallback
  path stays green. Drift between sandbox and production lane
  collected-counts is itself a CI signal.
- **`external-verifier-drift.yml` — python-bitcoinlib drift matrix.**
  Phase-2 Sprint-8 Tag-4 Teil B. Runs the external-verifier test
  surface against three pinned `python-bitcoinlib` versions
  (`0.11.2`, `0.12.1`, `0.12.2` as of 2026-05-13) on Python 3.12. The
  matrix probes three invariants any auditor-injected
  `python-bitcoinlib`-backed `proof_reader` depends on:
  block-hash byte-order canonicalisation (`b2lx` vs `b2x`),
  OP_RETURN script serialisation round-trip, and
  `bitcoin.__version__` packaging sanity. The verifier sub-package
  itself does NOT import `python-bitcoinlib` (zero-PyPI-surface
  brand-proof posture); the matrix instead pins the contract the
  moment an auditor or operator chooses to layer it in via the
  documented `proof_reader` injection seam. Matrix jobs that fail
  to install a pinned version emit a `skip-with-marker` warning
  rather than failing the workflow — a single version dropping out
  of Python-interpreter support must not block the rest of the
  matrix. New `python-bitcoinlib` releases land in the matrix by
  explicit pin in a follow-up sprint, never as a floating `latest`
  tag (a floating tag would make a future fail ambiguous between
  verifier regression and upstream release).

## WAT bridge — Wirelang frame ingestion

The bridge that sits between the Wirelang Layer-1 frame stream and
the hourly aggregator lives under [`wat/ingestion/`](wat/ingestion/)
(BSL 1.1). It exposes two pieces:

- `project_l1_frame_to_leaf(frame)` — projects a CloudEvents-1.0 +
  Wakir-extension frame onto the 9-field `LeafRecord` (4 B1 hash-input
  fields + 5 audit-metadata fields per
  [`docs/wat-spool-spec.md`](docs/wat-spool-spec.md) §2). The four
  hash-input fields are the `compute_leaf_hash` input from the cross-
  review-zone-2 consensus marker.
- `append_leaf_to_spool(leaf, spool_dir)` and
  `seal_hour(spool_dir, hour_slot)` — JSONL append plus the atomic
  rename that flips an open `<hour>.jsonl` to `<hour>.jsonl.sealed`
  once the H_end + 5min late-frame window has elapsed.

The hourly cron driver (`scripts/wat-hourly.sh`) seals the hour file
before invoking `wakir-merkle build`, which now reads the `.sealed`
artefact rather than the open spool file.

### Cross-review-zone-2 — three sync clarifications

Three points flagged in the Tag-6 spec hand-off resolve as follows:

1. **Test-vector metadata convention.** Test-vector JSON files under
   `tests/fixtures/jcs-leaf-vectors/` reserve leading-underscore keys
   (`_spdx`, `_copyright`, `_notes`) at the top level for non-schema
   metadata. The `input` and `expected_leaf_hash` blocks are schema-
   bearing; the underscore-prefixed keys are stripped by machine
   consumers via a single-character prefix check. The convention is
   asserted in `tests/wat/test_hash_consistency.py` so a vector that
   omits the metadata fails CI.
2. **Multi-capability ordering.** The leaf projection commits to
   `caprefs[0]` per
   [`wirelang/specs/wat-leaf-projection.md`](wirelang/specs/wat-leaf-projection.md)
   §3.4.1. Producers control ordering; the first entry is the
   capability primarily invoked. A future v2 may introduce a multi-
   cap representation, additively. Producers that need to bind
   multiple capabilities into the audit trail today should emit one
   frame per capability.
3. **`recovery-drill-` prefix namespace.** The Phase-1b recovery-
   drill projection
   ([`wirelang/specs/recovery-drill-leaf-projection.md`](wirelang/specs/recovery-drill-leaf-projection.md)
   §2.1) prefixes drill `event_id`s with `recovery-drill-`. The bridge
   treats `event_id` byte-faithfully and does not bless or reject the
   prefix; namespace disjointness with regular UUIDv7 IDs is the
   producer's responsibility. Unit-tested in
   `tests/wat/test_bridge.py::test_event_id_namespace_disjoint`.

## Specifications

The cross-module contracts between Wirelang and WAT are documented in
plain Markdown under `docs/` and `wirelang/specs/`:

- [`wirelang/specs/wat-leaf-projection.md`](wirelang/specs/wat-leaf-projection.md)
  — how a Layer-1 frame projects onto the four-field WAT leaf tuple.
- [`docs/wat-spool-spec.md`](docs/wat-spool-spec.md) — the JSONL hour-
  spool format the bridge writes and the aggregator reads.
- [`docs/wat-hash-spec.md`](docs/wat-hash-spec.md) — the cross-domain
  JCS+SHA-256+hex-lower hash contract shared by all WAT-anchored data.
- [`docs/wat-manifest-spec.md`](docs/wat-manifest-spec.md) — the
  hourly manifest format that the verify CLI consumes.
- [`wirelang/specs/recovery-drill-leaf-projection.md`](wirelang/specs/recovery-drill-leaf-projection.md)
  — Phase-1b sketch: how quarterly cold-storage recovery drills
  project onto WAT leaves for three-year audit beyond the operator's
  own logs.

Test vectors for the JCS+SHA-256 leaf hash live under
[`tests/fixtures/jcs-leaf-vectors/`](tests/fixtures/jcs-leaf-vectors/).
Five vectors cover empty payloads, typical capability-bound frames,
the no-capability-token path, multi-byte UTF-8, and large nested
payloads. Each vector ships with a pre-computed `expected_leaf_hash`
that matches `wat.merkle.aggregator.compute_leaf_hash`.

## Repository layout

```
wat/        — Wakir Audit Trail module (BSL 1.1, see wat/LICENSE-BSL.md)
tooling/    — CI/CD helpers              (Apache 2.0)
scripts/    — setup and maintenance      (Apache 2.0)
tests/      — test suite                 (Apache 2.0)
docs/       — Markdown documentation     (CC BY 4.0)
```

## License

This repository is mixed-license. Apache-2.0 is the default for
foundation code and verifier tooling. Selected operational modules
are licensed under BUSL-1.1 and convert to Apache-2.0 on their
stated Change Date. Documentation is CC-BY-4.0 where marked. See
[LICENSING.md](./LICENSING.md) for the authoritative map.

See [NOTICE](NOTICE) for the attribution required by Apache 2.0,
[GOVERNANCE.md](./GOVERNANCE.md) for the human-governance posture,
[BRAND.md](./BRAND.md) for trademark and brand-asset posture, and
[ATTRIBUTION.md](./ATTRIBUTION.md) for sponsorship, work-product,
and third-party attribution context.

## Brand

Wakir Labs is a project of Callandor GmbH. Documentation files in
this repository are released under Creative Commons Attribution 4.0
International (CC BY 4.0) where indicated.
