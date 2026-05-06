# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Hourly Merkle aggregator (skeleton).

Reference algorithm (to be implemented):

- Hash function: SHA-256 (FIPS 180-4 / RFC 6234), via stdlib hashlib.
- Padding: when leaf count is not a power of two, duplicate the last
  leaf until 2^n is reached (Bitcoin-style padding).
- Leaf order: lexicographic by stable identifier (event_id for
  Wirelang frames; document path for identity-document leaves).
- Internal node: SHA-256(left_child || right_child).
- Output: 32-byte root hash per UTC hour.

Library decision (Phase 1a, day 1 compatibility check):
  merkletools 1.0.3 (PyPI, MIT) — fails to build under Python 3.14
    (depends on pysha3 with a C extension that no longer compiles
    against modern CPython headers).
  pymerkle 6.1.0 (PyPI, GPLv3+) — installs cleanly but is license-
    incompatible with BSL 1.1 module distribution.
  Resulting plan: small in-house implementation (~150 lines) with
    test vectors derived from the Bitcoin block-hash specification
    and from RFC 6234. Implementation lands in Phase 1a, day 2+.

This file currently exposes only the public function signatures so
that downstream callers and the verify CLI can be wired up against a
stable interface.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence


def leaf_hash(canonical_bytes: bytes) -> bytes:
    """Compute the leaf hash for one canonical entry.

    The input must be the canonical-form byte representation of the
    entry (e.g. RFC 8785 JCS-encoded JSON for Wirelang frames).
    Returns a 32-byte SHA-256 digest.
    """
    raise NotImplementedError("Phase 1a, day 2+: in-house implementation pending")


def build_merkle_tree(leaves: Sequence[bytes]) -> List[List[bytes]]:
    """Build a balanced binary Merkle tree from sorted leaves.

    Returns the tree as a list of levels, where level 0 is the leaves
    and the last level is a single-element list containing the root.
    Padding follows the Bitcoin convention (duplicate last leaf until
    the level size is a power of two).
    """
    raise NotImplementedError("Phase 1a, day 2+: in-house implementation pending")


def root_hash(leaves: Iterable[bytes]) -> bytes:
    """Compute only the Merkle root from a sequence of leaf hashes.

    Convenience wrapper around `build_merkle_tree` that discards the
    intermediate levels. Returns a 32-byte digest.
    """
    raise NotImplementedError("Phase 1a, day 2+: in-house implementation pending")
