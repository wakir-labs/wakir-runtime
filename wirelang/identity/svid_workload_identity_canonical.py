# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""SVID-Workload-Identity canonical-snapshot helpers (Tag-33 Mini-Welle).

This module is the **Python authority** for the
``SvidWorkloadIdentitySnapshot`` cross-lang wire-shape. It pins the
JCS-canonical byte form of a snapshot of *currently-bound* SVID
workload identities (one or more orgs, each carrying zero or more
persona bindings with SPIFFE-ID + leaf-cert ``notAfter`` + leaf-cert
DER bind-state SHA-256).

Why a separate canonical-snapshot module?
-----------------------------------------

The Sprint-Pengine-9 :mod:`wirelang.persona_engine.svid_workload_identity`
module is the *gRPC fetch path* (BUSL-1.1; engine-side caller for
the SPIRE Workload-API). That module produces an in-memory
:class:`SvidFetchResult` per RPC round-trip. The wire-shape of that
``SvidFetchResult`` is **not** canonicalised today — it is consumed
by the engine boot path as a Python object, not serialised onto a
wire.

Tag-33 introduces a canonical *snapshot* form for **operator audit**
and **cross-lang parity**: a stable, JCS-canonical byte representation
of the set of currently-bound SVIDs in a persona-engine boot state,
suitable for:

- WAT-anchor pipeline -- hash an SVID-binding snapshot per boot for
  per-persona attestation (Zone-L cross-review surface with Tomás).
- Cross-lang parity -- the future Rust pendant in
  ``wirelang-rust/crates/persona-engine-svid-workload-identity``
  (currently a probe skeleton) MUST reproduce the same JCS bytes
  byte-for-byte once it ships a ``FetchX509SVID`` substrate.
- Audit-replay -- the operator-side fixture vectors pinned in
  ``tests/fixtures/svid-workload-cross-lang/fixtures.json`` form the
  Authority-Pin: any drift on either side breaks both fixture-test
  suites.

Apache-2.0 license posture
--------------------------

The Sprint-Pengine-9 fetch path is **BUSL-1.1** because it embeds
the engine-side gRPC client (commercial-use-restricted under
ADR-0060 commercial-licensing). The canonical-snapshot helpers are
**Apache-2.0** so downstream re-implementers (Rust pendant, audit
tooling, third-party verifiers) can reuse the same JCS-canonical
serialisation contract without inheriting the BUSL restriction.
This is the same sibling-pattern Reza established for
``federation_resolver_canonical`` (Apache-2.0) vs.
``federation_resolver`` (BUSL-1.1) on Tag-24.

Schema
------

The canonical snapshot carries exactly two top-level fields
(alphabetical):

- ``bindings`` -- Ordered list of :class:`SvidWorkloadBinding`
  projections. Each binding is a six-key object (alphabetical):

    - ``bind_state_sha256`` (string; ``"sha256:" + 64-char lower-case
      hex`` of the leaf-cert DER bytes)
    - ``expired`` (boolean; True iff ``not_after_utc`` <
      ``fixed_now_utc``)
    - ``not_after_utc`` (RFC-3339 second-precision UTC string;
      leaf-cert notAfter timestamp)
    - ``org_id`` (string)
    - ``persona_id`` (string)
    - ``spiffe_id`` (string; ``"spiffe://wakir.{org_id}/persona/{persona_id}"``
      template-resolved, but the canonical form pins the actual issued
      ID as observed)

  Bindings are sorted lexicographically by ``(org_id, persona_id,
  not_after_utc)`` so the snapshot byte-form is independent of
  insertion order.

- ``schema`` -- Schema identifier; constant
  ``"wakir.identity.svid-workload-cross-lang/1"``.

Serialisation
-------------

The canonical bytes are produced by ``json.dumps`` with
``sort_keys=True``, ``separators=(",", ":")``,
``ensure_ascii=False``, UTF-8-encoded. The outer snapshot hash is
``"sha256:" + hex(SHA-256(canonical_bytes))``. The same RFC-8785-JCS
contract used by :mod:`wirelang.identity.federation_resolver_canonical`
applies here -- the subset of JSON exercised by this snapshot
(strings + booleans + arrays) is well-inside the ``rfc8785.dumps`` /
:func:`wirelang.identity._jcs_pure.canonicalize` overlap.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/svid-workload-cross-lang/fixtures.json`` is the
byte-level cross-lang pin. Both
``tests/identity/test_svid_workload_identity_cross_lang_parity.py``
(Python) and -- once the Rust pendant ships a ``FetchX509SVID``
substrate -- a future
``wirelang-rust/crates/persona-engine-svid-workload-identity/tests/
svid_workload_cross_lang_fixture_test.rs`` (Rust) consume the same
vectors. The Tag-33 PR pins the Python side; the Rust side reserves
the same fixture path for the upcoming Sprint-Pengine-12 cutover.

Resolution semantics
--------------------

The :class:`InMemorySvidWorkloadRegistry` exposes a
``resolve(org_id, persona_id, now_utc)`` operation that returns the
*most recently issued* in-window binding for the given pair (i.e.
``not_after_utc > now_utc``), prefering -- if multiple unexpired
bindings exist -- the binding with the lexicographically-latest
``not_after_utc``. This mirrors the SPIRE-Agent rotation semantics:
the engine always uses the freshest SVID. Bindings with
``not_after_utc <= now_utc`` are filtered out (expired). If no
in-window binding exists, ``resolve`` returns ``None``.

Replay-detection semantics
--------------------------

The :class:`SvidWorkloadBinding` carries a ``bind_state_sha256``
field that is the SHA-256 of the leaf-cert DER bytes (mirror of
:attr:`wirelang.persona_engine.svid_workload_identity.SvidFetchResult.bind_state_sha256`).
Registering two bindings with the same ``(org_id, persona_id)`` but
*different* ``bind_state_sha256`` AND the same ``not_after_utc`` is
a key-rotation replay signal and is rejected. (Two bindings with
the same ``(org_id, persona_id)`` but *different* ``not_after_utc``
is a legitimate rotation and is allowed -- the resolver picks the
freshest by ``not_after_utc``.)

Schema-parity table (Python <-> Rust pendant slot)
--------------------------------------------------

::

    Python                                              <-> Rust
    ------                                              ---     ----
    SVID_WORKLOAD_IDENTITY_SCHEMA                       SVID_WORKLOAD_IDENTITY_SCHEMA
    HASH_PREFIX                                         HASH_PREFIX
    SHA256_HEX_LEN                                      SHA256_HEX_LEN
    BIND_STATE_PREFIX                                   BIND_STATE_PREFIX
    SvidWorkloadBinding {                               struct SvidWorkloadBinding {
      bind_state_sha256,                                  bind_state_sha256,
      expired,                                            expired,
      not_after_utc,                                      not_after_utc,
      org_id,                                             org_id,
      persona_id,                                         persona_id,
      spiffe_id,                                          spiffe_id,
    }                                                   }
    SvidWorkloadIdentitySnapshot {                      struct SvidWorkloadIdentitySnapshot {
      bindings: Vec<SvidWorkloadBinding>,                 bindings: Vec<SvidWorkloadBinding>,
      schema,                                             schema,
    }                                                   }
    InMemorySvidWorkloadRegistry                        InMemorySvidWorkloadRegistry
    .register(binding)                                  .register(binding)
    .snapshot() -> Snapshot                             .snapshot() -> Snapshot
    .resolve(org_id, persona_id, now_utc) -> Option     .resolve(org_id, persona_id, now_utc) -> Option

References (URL-200-stamped 2026-05-18):

- RFC 8785 JCS: <https://datatracker.ietf.org/doc/html/rfc8785>
- SPIFFE Workload-API v0.4 (defines the SPIFFE-ID + notAfter
  shape this module canonicalises):
  <https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE_Workload_API.md>
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ---------------------------------------------------------------------
# Public constants (Zone-L cross-review surface; Rust-pendant pin)
# ---------------------------------------------------------------------

#: Snapshot schema identifier. The trailing ``/1`` is the major
#: version; a breaking-change to the snapshot wire-shape MUST bump
#: this to ``/2``.
SVID_WORKLOAD_IDENTITY_SCHEMA = "wakir.identity.svid-workload-cross-lang/1"

#: SHA-256 hex digest length (lower-case hex).
SHA256_HEX_LEN = 64

#: Hash prefix used for the outer snapshot hash.
HASH_PREFIX = "sha256:"

#: Prefix used inside ``bind_state_sha256`` field values. The full
#: field shape is ``"sha256:" + 64-char-lower-hex``.
BIND_STATE_PREFIX = "sha256:"

#: Total length of a ``bind_state_sha256`` field value:
#: ``len("sha256:") + 64``.
BIND_STATE_LEN = len(BIND_STATE_PREFIX) + SHA256_HEX_LEN

#: Expected SPIFFE-ID template -- mirror of
#: :data:`wirelang.persona_engine.svid_workload_identity.SPIFFE_ID_TEMPLATE`.
#: This module does NOT require the binding's ``spiffe_id`` to match
#: the template (the SPIRE-Agent is the authority on the issued ID);
#: the template is exposed here as a helper for downstream callers
#: that wish to assert the expected shape.
SPIFFE_ID_TEMPLATE = "spiffe://wakir.{org_id}/persona/{persona_id}"


class SvidWorkloadIdentityError(ValueError):
    """Raised when an SVID-workload-identity binding violates the
    Tag-33 shape pre-conditions."""


# ---------------------------------------------------------------------
# Wire-shape dataclasses
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class SvidWorkloadBinding:
    """One bound SVID workload identity (one ``(org_id, persona_id)``
    pair, one SPIRE-Agent-issued leaf cert).

    Field order matches the JCS-canonical key order (alphabetical).
    All six fields are required.

    Attributes:
        bind_state_sha256: ``"sha256:" + 64-char-lower-hex`` of the
            leaf-cert DER bytes (parity with
            :attr:`wirelang.persona_engine.svid_workload_identity.SvidFetchResult.bind_state_sha256`).
            Acts as the cheap cross-correlation fingerprint across
            audit annotations.
        expired: Materialised flag; True iff ``not_after_utc`` <=
            ``fixed_now_utc`` at snapshot time. The flag is part of
            the canonical wire-shape so an audit replay does not
            need to re-evaluate the comparison on the consumer side
            (the canonical bytes alone carry the verdict).
        not_after_utc: Leaf-cert notAfter timestamp; RFC-3339
            second-precision UTC string.
        org_id: Operator-org identifier (e.g. ``"wakir-labs"``,
            ``"callandor"``).
        persona_id: Persona identifier within the org. The template-
            resolved SPIFFE-ID is
            ``spiffe://wakir.{org_id}/persona/{persona_id}``.
        spiffe_id: The SPIFFE-ID *as actually issued* by the
            SPIRE-Agent (URI form). The canonical form pins what was
            observed -- a mismatch versus the template-resolved ID
            is an audit anomaly the consumer flags via
            :func:`spiffe_id_matches_template`.
    """

    bind_state_sha256: str
    expired: bool
    not_after_utc: str
    org_id: str
    persona_id: str
    spiffe_id: str


@dataclass(frozen=True)
class SvidWorkloadIdentitySnapshot:
    """JCS-canonical wire-shape of a registry's full binding set.

    Two top-level fields (alphabetical): ``bindings`` (sorted) and
    ``schema``. The snapshot is the cross-lang-pinned byte form;
    drift on either Python or Rust side breaks both fixture-test
    suites.
    """

    bindings: List[SvidWorkloadBinding] = field(default_factory=list)
    schema: str = SVID_WORKLOAD_IDENTITY_SCHEMA


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------


def _is_lower_hex(s: str, expected_len: int) -> bool:
    """Return True iff ``s`` is exactly ``expected_len`` lower-case
    hex characters."""
    if len(s) != expected_len:
        return False
    for ch in s:
        if not (("0" <= ch <= "9") or ("a" <= ch <= "f")):
            return False
    return True


def _validate_bind_state_sha256(value: str) -> None:
    """Validate the ``"sha256:" + 64-hex`` shape of a bind-state
    fingerprint."""
    if not isinstance(value, str) or not value:
        raise SvidWorkloadIdentityError(
            f"bind_state_sha256 must be a non-empty string; got {value!r}"
        )
    if not value.startswith(BIND_STATE_PREFIX):
        raise SvidWorkloadIdentityError(
            f"bind_state_sha256 must start with {BIND_STATE_PREFIX!r}; "
            f"got {value!r}"
        )
    hex_part = value[len(BIND_STATE_PREFIX):]
    if not _is_lower_hex(hex_part, SHA256_HEX_LEN):
        raise SvidWorkloadIdentityError(
            f"bind_state_sha256 hex tail must be {SHA256_HEX_LEN} lower-case "
            f"hex chars; got {hex_part!r}"
        )


def _validate_binding(binding: SvidWorkloadBinding) -> None:
    """Raise :class:`SvidWorkloadIdentityError` if ``binding`` violates
    Tag-33 shape pre-conditions.

    Checks:

    - ``bind_state_sha256`` is ``"sha256:" + 64-hex`` lower-case.
    - ``not_after_utc`` is a non-empty RFC-3339 UTC string (lexical
      order = chronological for second-precision UTC).
    - ``org_id`` / ``persona_id`` are non-empty strings.
    - ``spiffe_id`` is a non-empty string starting with ``"spiffe://"``.
    - ``expired`` is a Python ``bool``.
    """
    if not isinstance(binding, SvidWorkloadBinding):
        raise SvidWorkloadIdentityError(
            f"binding must be SvidWorkloadBinding; got {type(binding).__name__}"
        )
    _validate_bind_state_sha256(binding.bind_state_sha256)
    if not isinstance(binding.expired, bool):
        raise SvidWorkloadIdentityError(
            f"expired must be a bool; got {type(binding.expired).__name__}"
        )
    if not isinstance(binding.not_after_utc, str) or not binding.not_after_utc:
        raise SvidWorkloadIdentityError(
            f"not_after_utc must be a non-empty string; got {binding.not_after_utc!r}"
        )
    if not isinstance(binding.org_id, str) or not binding.org_id:
        raise SvidWorkloadIdentityError(
            f"org_id must be a non-empty string; got {binding.org_id!r}"
        )
    if not isinstance(binding.persona_id, str) or not binding.persona_id:
        raise SvidWorkloadIdentityError(
            f"persona_id must be a non-empty string; got {binding.persona_id!r}"
        )
    if not isinstance(binding.spiffe_id, str) or not binding.spiffe_id:
        raise SvidWorkloadIdentityError(
            f"spiffe_id must be a non-empty string; got {binding.spiffe_id!r}"
        )
    if not binding.spiffe_id.startswith("spiffe://"):
        raise SvidWorkloadIdentityError(
            f"spiffe_id must start with 'spiffe://'; got {binding.spiffe_id!r}"
        )


# ---------------------------------------------------------------------
# Registry Protocol + reference implementation
# ---------------------------------------------------------------------


@runtime_checkable
class SvidWorkloadRegistry(Protocol):
    """Minimal shape every SVID-workload registry implementation honours.

    The Phase-Tag-33 in-memory reference implementation
    :class:`InMemorySvidWorkloadRegistry` satisfies this Protocol. A
    future production implementation backed by NATS-KV or a remote
    registry MAY substitute as long as the three methods below carry
    the same semantics.
    """

    def register(self, binding: SvidWorkloadBinding) -> None:
        """Register one binding.

        Idempotent on full-tuple match; a duplicate
        ``(org_id, persona_id, not_after_utc)`` with a *different*
        ``bind_state_sha256`` MUST raise
        :class:`SvidWorkloadIdentityError` (key-rotation replay signal).
        """
        ...

    def snapshot(self, *, fixed_now_utc: str) -> SvidWorkloadIdentitySnapshot:
        """Return a JCS-canonical snapshot of the registry's full
        binding set. ``fixed_now_utc`` materialises the ``expired``
        flag per binding."""
        ...

    def resolve(
        self, org_id: str, persona_id: str, now_utc: str
    ) -> Optional[SvidWorkloadBinding]:
        """Return the most-recently-issued in-window binding for
        ``(org_id, persona_id)``, or ``None`` if no in-window binding
        exists."""
        ...


class InMemorySvidWorkloadRegistry:
    """Reference in-memory implementation of :class:`SvidWorkloadRegistry`.

    The registry stores bindings in a dict keyed by
    ``(org_id, persona_id, not_after_utc)``; the snapshot serialises
    the full set sorted by ``(org_id, persona_id, not_after_utc)``.
    """

    def __init__(self) -> None:
        self._bindings: Dict[Tuple[str, str, str], SvidWorkloadBinding] = {}

    def register(self, binding: SvidWorkloadBinding) -> None:
        _validate_binding(binding)
        key = (binding.org_id, binding.persona_id, binding.not_after_utc)
        existing = self._bindings.get(key)
        if existing is not None:
            if (
                existing.bind_state_sha256 != binding.bind_state_sha256
                or existing.spiffe_id != binding.spiffe_id
                or existing.expired != binding.expired
            ):
                raise SvidWorkloadIdentityError(
                    f"duplicate (org_id={binding.org_id!r}, "
                    f"persona_id={binding.persona_id!r}, "
                    f"not_after_utc={binding.not_after_utc!r}) triple with "
                    f"differing bind_state_sha256/spiffe_id/expired payload "
                    f"-- key-rotation replay signal"
                )
            # Full-tuple match -> idempotent no-op.
            return
        self._bindings[key] = binding

    def _materialise_expired(self, binding: SvidWorkloadBinding, fixed_now_utc: str) -> SvidWorkloadBinding:
        """Return a copy of ``binding`` with ``expired`` re-evaluated
        against ``fixed_now_utc``."""
        # RFC-3339 second-precision UTC: lexical compare == chronological.
        new_expired = binding.not_after_utc <= fixed_now_utc
        if new_expired == binding.expired:
            return binding
        return SvidWorkloadBinding(
            bind_state_sha256=binding.bind_state_sha256,
            expired=new_expired,
            not_after_utc=binding.not_after_utc,
            org_id=binding.org_id,
            persona_id=binding.persona_id,
            spiffe_id=binding.spiffe_id,
        )

    def snapshot(self, *, fixed_now_utc: str) -> SvidWorkloadIdentitySnapshot:
        """Return a JCS-canonical snapshot.

        ``fixed_now_utc`` re-evaluates the ``expired`` flag per
        binding -- the registry stores the binding as-registered but
        the snapshot materialises ``expired`` against the snapshot-
        time clock. This keeps the registry insertion semantics simple
        while letting the canonical snapshot reflect a chosen "now".
        """
        if not isinstance(fixed_now_utc, str) or not fixed_now_utc:
            raise SvidWorkloadIdentityError(
                f"fixed_now_utc must be a non-empty string; "
                f"got {fixed_now_utc!r}"
            )
        bindings_sorted = sorted(
            (self._materialise_expired(b, fixed_now_utc) for b in self._bindings.values()),
            key=lambda b: (b.org_id, b.persona_id, b.not_after_utc),
        )
        return SvidWorkloadIdentitySnapshot(
            bindings=bindings_sorted,
            schema=SVID_WORKLOAD_IDENTITY_SCHEMA,
        )

    def resolve(
        self, org_id: str, persona_id: str, now_utc: str
    ) -> Optional[SvidWorkloadBinding]:
        """Return the freshest in-window binding for ``(org_id,
        persona_id)`` (highest ``not_after_utc`` strictly greater
        than ``now_utc``), or ``None`` if no such binding exists."""
        candidates: List[SvidWorkloadBinding] = []
        for (oid, pid, _na), binding in self._bindings.items():
            if oid != org_id or pid != persona_id:
                continue
            # In-window iff not_after_utc strictly greater than now_utc.
            if binding.not_after_utc <= now_utc:
                continue
            candidates.append(binding)
        if not candidates:
            return None
        # Prefer the lexicographically-latest not_after_utc (= freshest).
        chosen = max(candidates, key=lambda b: b.not_after_utc)
        # Materialise expired against now_utc for caller consistency.
        return SvidWorkloadBinding(
            bind_state_sha256=chosen.bind_state_sha256,
            expired=False,  # in-window by construction
            not_after_utc=chosen.not_after_utc,
            org_id=chosen.org_id,
            persona_id=chosen.persona_id,
            spiffe_id=chosen.spiffe_id,
        )


# ---------------------------------------------------------------------
# JCS canonicalisation
# ---------------------------------------------------------------------


def _binding_to_wire_dict(binding: SvidWorkloadBinding) -> Dict[str, Any]:
    """Project a binding onto its six-key wire-shape (alphabetical)."""
    return {
        "bind_state_sha256": binding.bind_state_sha256,
        "expired": binding.expired,
        "not_after_utc": binding.not_after_utc,
        "org_id": binding.org_id,
        "persona_id": binding.persona_id,
        "spiffe_id": binding.spiffe_id,
    }


def snapshot_to_wire_dict(
    snap: SvidWorkloadIdentitySnapshot,
) -> Dict[str, Any]:
    """Project a snapshot onto its two-key wire-shape (alphabetical).

    Bindings are pre-sorted by the registry; the projection preserves
    that order so :func:`serialize_snapshot` is order-deterministic.
    """
    return {
        "bindings": [_binding_to_wire_dict(b) for b in snap.bindings],
        "schema": snap.schema,
    }


def serialize_snapshot(snap: SvidWorkloadIdentitySnapshot) -> bytes:
    """Serialise a snapshot to its JCS-canonical UTF-8 byte form.

    Uses ``json.dumps`` with ``sort_keys=True``,
    ``separators=(",", ":")``, ``ensure_ascii=False``. The subset of
    JSON exercised (strings + booleans + arrays of objects) is well-
    inside the RFC-8785 / Python ``json.dumps`` overlap, so the bytes
    match what an RFC-8785 reference encoder would produce.
    """
    wire = snapshot_to_wire_dict(snap)
    return json.dumps(
        wire,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    """Return the lower-case hex SHA-256 digest of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def snapshot_sha256_hex(snap: SvidWorkloadIdentitySnapshot) -> str:
    """Return the bare-hex SHA-256 digest of the snapshot canonical bytes."""
    return sha256_hex(serialize_snapshot(snap))


def snapshot_hash_prefixed(snap: SvidWorkloadIdentitySnapshot) -> str:
    """Return the prefixed (``"sha256:"`` + hex) snapshot hash."""
    return HASH_PREFIX + snapshot_sha256_hex(snap)


def serialize_and_hash(
    snap: SvidWorkloadIdentitySnapshot,
) -> Tuple[bytes, str, str]:
    """Convenience helper: return ``(canonical_bytes, bare_hex,
    prefixed_hash)`` in one call."""
    canonical = serialize_snapshot(snap)
    bare = sha256_hex(canonical)
    return canonical, bare, HASH_PREFIX + bare


# ---------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------


def build_binding(
    *,
    org_id: str,
    persona_id: str,
    spiffe_id: Optional[str] = None,
    not_after_utc: str,
    bind_state_sha256: str,
    expired: bool = False,
) -> SvidWorkloadBinding:
    """Build a binding, defaulting ``spiffe_id`` to the template-
    resolved form when not explicitly supplied.

    The default-template path is the convenience for the engine
    boot path which knows ``(org_id, persona_id)`` and trusts the
    SPIRE-Agent to issue the template-resolved SPIFFE-ID. Test
    fixtures that simulate an issuance anomaly (cross-org spoofing,
    template-drift) MUST pass ``spiffe_id`` explicitly.
    """
    resolved_spiffe_id = (
        spiffe_id
        if spiffe_id is not None
        else SPIFFE_ID_TEMPLATE.format(org_id=org_id, persona_id=persona_id)
    )
    binding = SvidWorkloadBinding(
        bind_state_sha256=bind_state_sha256,
        expired=expired,
        not_after_utc=not_after_utc,
        org_id=org_id,
        persona_id=persona_id,
        spiffe_id=resolved_spiffe_id,
    )
    _validate_binding(binding)
    return binding


def build_snapshot_from_bindings(
    bindings: List[SvidWorkloadBinding],
    *,
    fixed_now_utc: str,
) -> SvidWorkloadIdentitySnapshot:
    """Build a snapshot from a list of bindings, materialising
    ``expired`` against ``fixed_now_utc``.

    The bindings are sorted by ``(org_id, persona_id, not_after_utc)``
    so the resulting snapshot is independent of input order. This is
    the test-fixture path; production callers use
    :meth:`InMemorySvidWorkloadRegistry.snapshot`.
    """
    if not isinstance(fixed_now_utc, str) or not fixed_now_utc:
        raise SvidWorkloadIdentityError(
            f"fixed_now_utc must be a non-empty string; got {fixed_now_utc!r}"
        )
    materialised: List[SvidWorkloadBinding] = []
    for b in bindings:
        _validate_binding(b)
        new_expired = b.not_after_utc <= fixed_now_utc
        if new_expired == b.expired:
            materialised.append(b)
        else:
            materialised.append(
                SvidWorkloadBinding(
                    bind_state_sha256=b.bind_state_sha256,
                    expired=new_expired,
                    not_after_utc=b.not_after_utc,
                    org_id=b.org_id,
                    persona_id=b.persona_id,
                    spiffe_id=b.spiffe_id,
                )
            )
    materialised.sort(key=lambda b: (b.org_id, b.persona_id, b.not_after_utc))
    return SvidWorkloadIdentitySnapshot(
        bindings=materialised,
        schema=SVID_WORKLOAD_IDENTITY_SCHEMA,
    )


def spiffe_id_matches_template(
    binding: SvidWorkloadBinding,
) -> bool:
    """Return True iff the binding's ``spiffe_id`` equals the
    template-resolved form for its ``(org_id, persona_id)`` pair."""
    expected = SPIFFE_ID_TEMPLATE.format(
        org_id=binding.org_id, persona_id=binding.persona_id
    )
    return binding.spiffe_id == expected
