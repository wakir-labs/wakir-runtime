# Wakir Runtime

The reference implementation of the Wakir Labs framework for accountable
multi-agent systems: typed inter-agent messaging, capability tokens,
identity substrate, and audit trails anchored to Bitcoin.

This repository is in early development. Architecture decisions and
implementation notes will land here as the framework comes together.

## Status

Pre-launch. The first build phase begins in calendar week 21 of 2026.

## What lives here

- **Wirelang** — typed inter-agent message schema (transport, wire format,
  semantic, audit layers)
- **WAT (Wakir Audit Trail)** — Bitcoin-anchored audit trail layer with
  per-hour Merkle aggregation and verification CLI
- **Capability tokens** — adoption of AIP and Biscuit, with a Wakir
  vocabulary and Datalog caveat set
- **Container orchestrator** — agent-per-container deployment substrate
  (later phase)
- **Federation** — adoption of A2A and ERC-8004 standards plus a
  cross-organisation audit federation annex (later phase)

## License

Most modules are licensed under Apache License 2.0 (see [LICENSE](LICENSE)).

A small number of operations modules are released under the Business
Source License 1.1 with an automatic four-year conversion to Apache 2.0.
Each such module carries its own license header. The first such module
will be the WAT pipeline server; further BSL modules are introduced
phase by phase as documented in our public release notes.

See [NOTICE](NOTICE) for the attribution required by Apache 2.0 and
for context on how this code is produced under human governance.

## Brand

Wakir Labs is a project of Callandor GmbH. Documentation files in
this repository are released under Creative Commons Attribution 4.0
International (CC BY 4.0) where indicated.
