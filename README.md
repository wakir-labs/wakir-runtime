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

A separate, Apache-2.0-licensed offline verifier ships under the
top-level `wakir_verify` package as a Phase 1a deliverable; that
verifier is the public brand-proof tool and runs without any
WAT-side state.

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
wakir-verify --help
```

`wakir-verify` rebuilds the inclusion proof for an event from the
hour manifest, recomputes the leaf hash from the four B1-consensus
fields (`event_id`, `time`, `payload_hash`, `capability_token_hash`),
checks the proof against the stored Merkle root, and runs `ots verify`
on the per-hour receipt. Exit codes are `0` (verified), `1` (failed),
`3` (pending Bitcoin confirmation).

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

## Repository layout

```
wat/        — Wakir Audit Trail module (BSL 1.1, see wat/LICENSE-BSL.md)
tooling/    — CI/CD helpers              (Apache 2.0)
scripts/    — setup and maintenance      (Apache 2.0)
tests/      — test suite                 (Apache 2.0)
docs/       — Markdown documentation     (CC BY 4.0)
```

## License

Most modules are licensed under Apache License 2.0 (see [LICENSE](LICENSE)).

A small number of operations modules are released under the Business
Source License 1.1 with an automatic four-year conversion to Apache 2.0.
Each such module carries its own license header. The first such module
is the WAT pipeline; see [`wat/LICENSE-BSL.md`](wat/LICENSE-BSL.md) for
the per-module license text. Further BSL modules are introduced phase
by phase as documented in our public release notes.

See [NOTICE](NOTICE) for the attribution required by Apache 2.0 and
for context on how this code is produced under human governance.

## Brand

Wakir Labs is a project of Callandor GmbH. Documentation files in
this repository are released under Creative Commons Attribution 4.0
International (CC BY 4.0) where indicated.
