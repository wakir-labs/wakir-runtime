# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Wirelang Layer-1 frame -> WAT leaf projection.

Implements the four contracts handed over by the Tag-6 spec pack:

- ``wirelang/specs/wat-leaf-projection.md`` -- the frame -> leaf
  projection rule (4 B1-hash fields).
- ``docs/wat-spool-spec.md`` -- the 9-field hour-spool tuple
  (4 hash-input + 5 audit-metadata).
- ``docs/wat-hash-spec.md`` -- the JCS+SHA-256+hex-lower contract.
- ``docs/wat-manifest-spec.md`` -- downstream consumer.

The projection is **byte-faithful**: ``time`` and ``event_id`` are
copied verbatim from the L1 frame; ``payload_hash`` is recomputed
locally over ``frame.data`` (NOT taken from any pre-computed field on
the frame -- see consensus marker A1, commit ``338e007``);
``capability_token_hash`` is the first ``caprefs`` entry stripped of
its ``sha256:`` prefix, or the empty string sentinel.

Multi-capability frames -- consensus
------------------------------------

Per ``wirelang/specs/wat-leaf-projection.md`` §3.4.1 the projection
commits to **caprefs[0]** -- the first entry. Producers control
ordering and the first entry is the capability *primarily* invoked.
A future ``wakir-wat-leaf-projection/v2`` MAY introduce a multi-cap
representation; the v1 first-entry rule is forward-compatible.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from wat.merkle.aggregator import _canonicalise


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Layer-1 ``caprefs`` entries are constrained to the form
#: ``sha256:<64-char-hex>``. The bridge strips this prefix and forwards
#: the 64-char hex tail to the leaf tuple.
CAPREF_PREFIX = "sha256:"

#: Sentinel value used by ``compute_leaf_hash`` for events that carry
#: no capability token. The leaf-projection spec §3.4 normatively
#: defines this as the empty string.
NO_CAPABILITY_SENTINEL = ""


# ---------------------------------------------------------------------------
# 9-field LeafRecord (4 B1 hash-input + 5 audit-metadata)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeafRecord:
    """One spool line.

    The first four fields are the input to
    ``wat.merkle.aggregator.compute_leaf_hash`` per the
    cross-review-zone-2 B1 consensus marker. The last five are
    audit-metadata: they pass through to the manifest's per-event
    entries to support post-hoc audit queries (e.g. "show all writes
    by ``actorrole=treasury-operator`` in hour H") without re-fetching
    the original frames.

    Audit metadata is informational at the spool layer. Independent
    verifiers MUST NOT depend on these fields for the integrity proof
    -- the integrity proof flows through the four hash-input fields
    and the Merkle root only (``docs/wat-spool-spec.md`` §2.2).
    """

    # --- 4 hash-input fields (B1 consensus marker) ---
    event_id: str
    time: str
    payload_hash: str
    capability_token_hash: str

    # --- 5 audit-metadata fields (pass-through) ---
    source: str
    actorrole: str
    agentid: str
    schemaid: str
    schemaversion: str

    def to_jsonl_dict(self) -> dict[str, str]:
        """Return the 9-field dict as written to the JSONL hour-spool.

        Field order in the dict matches ``docs/wat-spool-spec.md`` §2:
        hash-input fields first, then audit-metadata. JSON object key
        ordering is informative only -- the leaf hash uses JCS, which
        sorts keys -- but the spec's documented order helps human
        operators ``less`` the spool without confusion.
        """
        return asdict(self)


# ---------------------------------------------------------------------------
# Hash helpers (cross-domain JCS+SHA-256+hex-lower contract)
# ---------------------------------------------------------------------------


def compute_payload_hash(frame_data: Any) -> str:
    """Compute ``payload_hash`` for a Layer-1 frame's ``data`` slot.

    Per ``docs/wat-hash-spec.md`` and ``wirelang/specs/wat-leaf-projection.md``
    §3.3 the rule is:

    .. code-block::

        payload_hash = hex_lower( SHA-256( JCS( frame.data ) ) )

    Empty / absent ``data`` collapses to ``JCS({})`` per spec §3.3.1
    -- callers that wish to record "no payload" as a distinct outcome
    SHOULD use a different ``schemaid`` rather than a missing-vs-empty
    ``data`` distinction.

    Note (consensus marker A1, commit ``338e007``): the payload hash
    is computed *locally* over ``frame.data`` -- it is **not** taken
    from any pre-computed ``dataschemaref`` field on the frame. The
    bridge is the source of truth for payload hashing; the aggregator
    consumes only the resulting hex string.
    """
    if frame_data is None:
        frame_data = {}
    canonical = _canonicalise(frame_data)
    return hashlib.sha256(canonical).hexdigest()


def extract_capability_token_hash(frame: Mapping[str, Any]) -> str:
    """Project a frame's ``caprefs`` onto a single ``capability_token_hash``.

    Multi-cap-ordering disciplin (Tag-7 sync clarification 2)
    ------------------------------------------------------

    Per ``wirelang/specs/wat-leaf-projection.md`` §3.4.1 the projection
    commits to ``caprefs[0]``: the first entry. Choices considered and
    rejected:

    - **Lexicographic minimum**: producer-independent but breaks the
      "primary capability" semantics.
    - **Last entry**: would mirror "most recently attenuated" but is
      counter-intuitive in a delegation chain.
    - **Concatenated digests / Merkle-of-caps**: deferred to v2.

    Producers that need to bind multiple capabilities into the audit
    trail right now SHOULD emit one frame per capability and let the
    Merkle tree aggregate them naturally (spec §3.4.1).

    Rules
    -----

    - ``caprefs`` absent or empty -> empty string sentinel.
    - ``caprefs`` with one or more entries -> first entry, with the
      ``sha256:`` prefix stripped. Hex tail is forwarded verbatim.
    - Entries that do not carry the ``sha256:`` prefix are accepted
      but logged at the next layer (no projection-level rejection,
      because the Layer-1 schema enforces the prefix upstream and a
      bridge that disagreed with the schema would mask producer bugs).
    """
    caprefs = frame.get("caprefs")
    if not caprefs:
        return NO_CAPABILITY_SENTINEL
    first = caprefs[0]
    if not isinstance(first, str):
        # Defensive: a malformed frame that survived schema validation
        # MUST NOT crash the bridge. Treat as no-cap and let the
        # downstream audit query surface the anomaly.
        return NO_CAPABILITY_SENTINEL
    if first.startswith(CAPREF_PREFIX):
        return first[len(CAPREF_PREFIX):]
    return first


# ---------------------------------------------------------------------------
# Frame -> LeafRecord projection
# ---------------------------------------------------------------------------


def project_l1_frame_to_leaf(frame: Mapping[str, Any]) -> LeafRecord:
    """Project a CloudEvents-1.0 + Wakir-extended Layer-1 frame onto
    a 9-field ``LeafRecord``.

    The projection is one-way and deterministic: given the same frame,
    every conformant implementation MUST produce the same 9-field
    tuple (``wirelang/specs/wat-leaf-projection.md`` §1).

    Recovery-drill-prefix namespace disjointness (Tag-7 sync clarification 3)
    ---------------------------------------------------------------------

    The ``recovery-drill-`` ``event_id`` prefix used by the Phase-1b
    drill projection (``wirelang/specs/recovery-drill-leaf-projection.md``
    §2.1) is **opaque** to the leaf-hash function: ``event_id`` is a
    string field and the projection treats it byte-faithfully. The
    bridge therefore neither blesses nor rejects the prefix; namespace
    disjointness with regular UUIDv7 ``id`` values is the producer's
    responsibility (recovery-drill producer prefixes; regular
    Wirelang producers emit UUIDv7 only).

    Required fields
    ---------------

    The Layer-1 schema (``wirelang/schemas/layer-1-wire.json``)
    requires ``id``, ``time``, ``source``, ``schemaid``, ``schemaversion``,
    ``actorrole``, and ``agentid``. The bridge does NOT re-validate
    the schema -- that is the producer's job upstream -- but it does
    surface a ``KeyError`` early if a required field is missing, so
    operators see a single actionable error rather than a hash that
    quietly differs from spec.
    """
    try:
        event_id = frame["id"]
        time = frame["time"]
        source = frame["source"]
        schemaid = frame["schemaid"]
        schemaversion = frame["schemaversion"]
        actorrole = frame["actorrole"]
        agentid = frame["agentid"]
    except KeyError as exc:
        raise KeyError(
            f"Layer-1 frame missing required field {exc!s}; "
            f"upstream schema validation should have rejected it"
        ) from exc

    # ``data`` is OPTIONAL on the Layer-1 envelope (CloudEvents
    # convention); spec §3.3.1 requires absent/empty data to project
    # identically to ``data: {}``.
    payload_hash = compute_payload_hash(frame.get("data"))
    capability_token_hash = extract_capability_token_hash(frame)

    return LeafRecord(
        event_id=str(event_id),
        time=str(time),
        payload_hash=payload_hash,
        capability_token_hash=capability_token_hash,
        source=str(source),
        actorrole=str(actorrole),
        agentid=str(agentid),
        schemaid=str(schemaid),
        schemaversion=str(schemaversion),
    )


__all__ = [
    "CAPREF_PREFIX",
    "NO_CAPABILITY_SENTINEL",
    "LeafRecord",
    "compute_payload_hash",
    "extract_capability_token_hash",
    "project_l1_frame_to_leaf",
]
