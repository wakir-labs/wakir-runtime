# SPDX-License-Identifier: Apache-2.0
"""Wirelang canonical-form primitives.

This package contains canonicalisation rules that pin pin-hash-style
artefacts in Wirelang. The first member is :mod:`caveat_set`
implementing the Caveat-Set Canonicalisation Rule (§4-CSC) ratified
in ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md`` §4.

Subsequent canonicalisation rules — for example a future
``federation_route`` registry artefact canonicaliser — would land
here as additional sibling modules.

Protocol-layer consolidation (ADR-0062 Cut-2, 2026-05-16)
---------------------------------------------------------
This Apache-2.0 package is also published as
``wakir_protocol.canonical`` under the standalone
``wakir-labs/wakir-protocol`` repository. The in-tree copy under
``wirelang.canonical`` is the runtime-internal mirror; external
adopters should depend on ``wakir-protocol`` and import from
``wakir_protocol.canonical`` directly.
"""

from wirelang.canonical.caveat_set import (
    canonical_caveat_set_bytes,
    canonical_caveat_set_hash,
    canonicalize_caveat_set,
)

__all__ = [
    "canonical_caveat_set_bytes",
    "canonical_caveat_set_hash",
    "canonicalize_caveat_set",
]
