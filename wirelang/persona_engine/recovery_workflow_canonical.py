# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Canonical-projection helpers for the persona-engine recovery workflow.

This module is the **cross-lang parity surface** for the R1..R4
recovery workflow. It produces a deterministic, timing-free
projection of a :class:`~wirelang.persona_engine.recovery_workflow.RecoveryResult`
and serialises it via RFC 8785 JCS so the byte-form is identical to
the Rust sibling
``persona-engine-recovery::recovery_outcome_jcs_bytes``.

License posture
---------------

The reference :mod:`recovery_workflow` module is BUSL-1.1 (sits under
``wirelang/persona_engine/LICENSE-BSL.md``). This canonical-projection
helper is **Apache-2.0** so the cross-lang parity test suite — and
any downstream re-implementer — can re-use the projection contract
without inheriting the BUSL-1.1 obligations. The module imports only
the data-class shapes (``PhaseResult`` and ``RecoveryResult``) from
the BUSL-1.1 module; no runtime behaviour is taken.

Cross-lang contract
-------------------

| Python concept                            | Rust sibling                              |
|-------------------------------------------|-------------------------------------------|
| :data:`RECOVERY_OUTCOME_SCHEMA`           | ``RECOVERY_OUTCOME_SCHEMA``               |
| :data:`HASH_PREFIX` / :data:`SHA256_HEX_LEN` | ``HASH_PREFIX`` / ``SHA256_HEX_LEN``      |
| :func:`recovery_outcome_canonical_dict`   | ``recovery_outcome_canonical_value``      |
| :func:`recovery_outcome_jcs_bytes`        | ``recovery_outcome_jcs_bytes``            |
| :func:`recovery_outcome_sha256_hex`       | ``recovery_outcome_sha256_hex``           |
| :func:`recovery_outcome_hash_prefixed`    | ``recovery_outcome_hash_prefixed``        |

Wire shape (alphabetical keys via JCS):

.. code-block:: json

   {
     "final_state": "...",
     "phases": [
       {
         "audit_annotation": "...",
         "elapsed_sec": 0,
         "phase": "R1",
         "soft_cap_exceeded": false,
         "terminal_status": "..."
       }
     ],
     "schema": "wakir.persona-engine.recovery-outcome/1",
     "success": true,
     "total_elapsed_sec": 0,
     "trigger": "..."
   }

Note on JCS float emission
--------------------------

RFC 8785 JCS (and both ``rfc8785`` for Python and ``serde_jcs`` for
Rust) serialise the floating-point literal ``0.0`` as the JSON token
``0`` (not ``0.0``). The canonical-projection therefore emits an
integer-form zero for the timing fields; this is intentional and
load-bearing on the byte-form. If the projection contract ever moves
to non-zero timings, the JCS-mandated number canonicalisation
(IEEE-754 shortest round-trip) takes over.

Fixture-derivation procedure
----------------------------

The authoritative fixture vectors live in
``tests/fixtures/recovery-workflow-cross-lang/fixtures.json``. To
re-derive after an intentional wire-shape change:

1. Update :func:`recovery_outcome_canonical_dict` (here) and
   ``recovery_outcome_canonical_value`` (Rust) in the same PR.
2. Run ``scripts/derive_recovery_workflow_cross_lang_fixtures.py``
   to recompute the fixture vectors from the Python side.
3. Re-run both test suites — both sides must read the new fixtures
   without modification.

If a wire-shape change is *accidental*, the cross-lang fixture test
fires on both sides, which is the intended boundary detector.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from .recovery_workflow import PhaseResult, RecoveryResult, RecoveryTrigger

# ---------------------------------------------------------------------------
# Constants — pin to Rust sibling.
# ---------------------------------------------------------------------------

#: Schema identifier for the canonical-projection wire-form (Tag-20
#: Python-sync cross-lang parity sweep). Byte-identical with the Rust
#: sibling constant ``RECOVERY_OUTCOME_SCHEMA``.
RECOVERY_OUTCOME_SCHEMA: str = "wakir.persona-engine.recovery-outcome/1"

#: Hash prefix tag used by the canonical-projection helpers.
HASH_PREFIX: str = "sha256:"

#: Length of a lowercase hex-encoded SHA-256 digest.
SHA256_HEX_LEN: int = 64


# ---------------------------------------------------------------------------
# Canonical projection.
# ---------------------------------------------------------------------------


def _phase_result_canonical_dict(p: PhaseResult) -> Dict[str, Any]:
    """Project a single :class:`PhaseResult` into the canonical dict
    shape with timing fields zeroed (parity with Rust
    ``recovery_outcome_canonical_value`` per-phase JSON object)."""
    return {
        "audit_annotation": p.audit_annotation,
        # JCS emits ``0`` (integer form) for both ``0`` and ``0.0`` —
        # we pass the Python int literal so the intent is explicit.
        "elapsed_sec": 0,
        "phase": p.phase,
        "soft_cap_exceeded": False,
        "terminal_status": p.terminal_status,
    }


def recovery_outcome_canonical_dict(
    *,
    trigger: RecoveryTrigger,
    phases: List[PhaseResult],
    final_state: str,
    success: bool,
) -> Dict[str, Any]:
    """Build the canonical-projection dict.

    Accepts the four shaping fields directly (rather than a
    :class:`RecoveryResult` instance) so callers can pin partial /
    failure-mode outcomes that the workflow itself does not always
    instantiate as a complete ``RecoveryResult`` (e.g. the trigger-
    ambiguous case, where the workflow raises before constructing a
    result).

    The dict is timing-free: ``elapsed_sec``, ``total_elapsed_sec``,
    and ``soft_cap_exceeded`` are zero/false regardless of input. This
    keeps the byte-form deterministic across runs and across
    languages.
    """
    return {
        "final_state": final_state,
        "phases": [_phase_result_canonical_dict(p) for p in phases],
        "schema": RECOVERY_OUTCOME_SCHEMA,
        "success": success,
        "total_elapsed_sec": 0,
        "trigger": trigger.value,
    }


def recovery_outcome_canonical_dict_from_result(
    result: RecoveryResult,
) -> Dict[str, Any]:
    """Convenience wrapper: project a :class:`RecoveryResult` into
    the canonical dict shape. Used by in-engine consumers that
    already hold a complete result."""
    return recovery_outcome_canonical_dict(
        trigger=result.trigger,
        phases=list(result.phases),
        final_state=result.final_state,
        success=result.success,
    )


# ---------------------------------------------------------------------------
# JCS bytes + SHA-256 helpers.
# ---------------------------------------------------------------------------


def _import_rfc8785() -> Any:
    """Lazy-import ``rfc8785`` so module load does not require the
    optional wheel. The fixture-pin tests will fail with a clear
    ImportError if the wheel is absent; the BUSL-1.1 reference
    workflow does not depend on this helper at runtime."""
    try:
        import rfc8785  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised in CI without dep
        raise ImportError(
            "rfc8785 is required for recovery-outcome JCS canonicalisation. "
            "Install via: pip install rfc8785>=0.1.4"
        ) from exc
    return rfc8785


def recovery_outcome_jcs_bytes(canonical_dict: Dict[str, Any]) -> bytes:
    """Serialise a canonical-projection dict via RFC 8785 JCS.

    Byte-identical with the Rust sibling ``recovery_outcome_jcs_bytes``
    (which uses ``serde_jcs``). The input must already be the
    canonical-projection dict — call :func:`recovery_outcome_canonical_dict`
    first.
    """
    rfc8785 = _import_rfc8785()
    return rfc8785.dumps(canonical_dict)


def recovery_outcome_sha256_hex(canonical_dict: Dict[str, Any]) -> str:
    """Lowercase hex SHA-256 of the JCS-canonical bytes.

    Parity with Rust ``recovery_outcome_sha256_hex``.
    """
    bytes_ = recovery_outcome_jcs_bytes(canonical_dict)
    return hashlib.sha256(bytes_).hexdigest()


def recovery_outcome_hash_prefixed(canonical_dict: Dict[str, Any]) -> str:
    """``sha256:`` + lowercase hex SHA-256 (parity with Rust helper)."""
    return HASH_PREFIX + recovery_outcome_sha256_hex(canonical_dict)


def serialize_and_hash(canonical_dict: Dict[str, Any]) -> tuple[bytes, str]:
    """Return ``(jcs_bytes, hash_prefixed)`` in one call (parity with
    the precedent in
    :mod:`wirelang.persona_engine.subscribe_ack.serialize_and_hash`)."""
    rfc8785 = _import_rfc8785()
    bytes_ = rfc8785.dumps(canonical_dict)
    digest = hashlib.sha256(bytes_).hexdigest()
    return bytes_, HASH_PREFIX + digest


__all__ = [
    "RECOVERY_OUTCOME_SCHEMA",
    "HASH_PREFIX",
    "SHA256_HEX_LEN",
    "recovery_outcome_canonical_dict",
    "recovery_outcome_canonical_dict_from_result",
    "recovery_outcome_jcs_bytes",
    "recovery_outcome_sha256_hex",
    "recovery_outcome_hash_prefixed",
    "serialize_and_hash",
]
