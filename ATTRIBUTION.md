<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Attribution

This file collects attribution context that is too long for the
schlanker `NOTICE` file (Apache-2.0 §4) but still belongs with the
distribution.

## Project sponsorship

Wakir Runtime is part of Wakir Labs, a project of Callandor GmbH
(Falkenstr. 31, 81541 München, Germany; Amtsgericht München
HRB 270414). See `BRAND.md` for brand-name and trademark posture.

## Work-product attribution

Code in this repository is produced by typed AI agent personas under
continuous direction, review, and approval by the supervisory board
of Callandor GmbH. See `GOVERNANCE.md` for the human-governance
posture and the ADR-based decision provenance.

Each release tag carries a corresponding ADR record. The
OpenTimestamps anchor for the ADR record at release time is the
authoritative provenance pointer.

## Third-party attributions

Third-party Python wheels pulled in as runtime dependencies are
listed in `pyproject.toml` `[project] dependencies` with their
upstream license identifiers. Notable items:

- `rfc8785` — Apache-2.0, Trail of Bits
- `shamir-mnemonic` — MIT, SatoshiLabs
- `cryptography` — Apache-2.0 + BSD, Python Cryptographic Authority
- `PyYAML` — MIT, Ingy döt Net + Kirill Simonov
- `nats-py` — Apache-2.0, Synadia (optional, NATS extras)
- `grpcio` — Apache-2.0, gRPC Authors (optional, persona-engine extras)
- `opentelemetry-*` — Apache-2.0, OpenTelemetry Authors (optional,
  persona-engine observability extras)

For the canonical license text of each identifier referenced here,
see `LICENSES/`.
