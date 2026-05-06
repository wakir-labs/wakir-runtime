# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""WAT ingestion: Wirelang Layer-1 frame -> hour-spool bridge.

This sub-package implements the Phase-1a-Tag-7 contract that connects
the Wirelang Layer-1 frame stream to the hourly Merkle aggregator
(``wat.merkle.aggregator``). It owns:

- ``wirelang_bridge`` -- pure projection of an L1 frame onto the
  9-field ``LeafRecord`` (4 hash-input + 5 audit-metadata) per
  ``wirelang/specs/wat-leaf-projection.md`` and ``docs/wat-spool-spec.md``.
- ``spool_writer`` -- append-only JSONL writer with the hour-boundary
  sealed-rename pattern documented in ``docs/wat-spool-spec.md``.

The package is the *bridge* between two licence domains:

- Wirelang produces frames under Apache-2.0.
- WAT consumes them under BSL-1.1 (this package).

The contract documents in ``wirelang/specs/`` and ``docs/`` are
CC-BY-4.0; the leaf-hash core (``compute_leaf_hash``) is BSL-1.1; this
ingestion bridge follows the WAT module licence because the hour-spool
artefact it produces is a WAT-internal staging format consumed by
``wakir-merkle build``.
"""

from wat.ingestion.wirelang_bridge import (
    LeafRecord,
    compute_payload_hash,
    extract_capability_token_hash,
    project_l1_frame_to_leaf,
)
from wat.ingestion.spool_writer import (
    HOUR_SLOT_FORMAT,
    LATE_FRAME_WINDOW_MINUTES,
    SEALED_SUFFIX,
    append_leaf_to_spool,
    hour_slot_for_time,
    seal_hour,
    seal_due_hours,
)

__all__ = [
    "HOUR_SLOT_FORMAT",
    "LATE_FRAME_WINDOW_MINUTES",
    "LeafRecord",
    "SEALED_SUFFIX",
    "append_leaf_to_spool",
    "compute_payload_hash",
    "extract_capability_token_hash",
    "hour_slot_for_time",
    "project_l1_frame_to_leaf",
    "seal_due_hours",
    "seal_hour",
]
