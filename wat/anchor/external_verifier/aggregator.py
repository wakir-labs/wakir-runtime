# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""4-pole cross-library aggregator for WAT anchor verification.

The aggregator runs each configured pole against the same input
(merkle root hash plus OTS proof file) and folds the per-pole
verdicts into a quorum decision. The cross-library witness contract
is documented in the Position-Paper §L4-References annex; this
module is the executable form.

Aggregator semantics
--------------------

Each pole returns a :class:`PoleResult` with:

* ``ok`` — a boolean: did this pole independently verify the anchor?
* ``verdict`` — one of ``"verified"``, ``"failed"``, ``"unavailable"``
  (when the pole could not run at all, e.g. CLI binary missing or
  HTTP transport returned an error).
* ``witness`` — a free-form dict that captures the substance the
  pole observed (block hash, height, ``ots`` output snippet, …)
  so a human auditor can correlate verdicts across poles.

Quorum
------

Quorum is configurable:

* ``QuorumPolicy.THREE_OF_FOUR`` (default) — at least three poles
  return ``ok=True``. This tolerates one transient unavailable pole.
* ``QuorumPolicy.ALL`` — every pole must return ``ok=True``.
* ``QuorumPolicy.TWO_OF_FOUR`` — for archive-debugging scenarios
  where two poles are known unavailable; **never** the default in
  production.

A pole that returns ``unavailable`` counts as a non-vote, not a
``False`` vote — except under ``QuorumPolicy.ALL`` where any
non-``True`` fails the quorum. Rationale: a network blip on
mempool.space should not flip a finalised verified anchor to
failed; a stricter operator can opt into ``ALL``.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Callable, Mapping, Optional

from wat.anchor.external_verifier import poles as _poles
from wat.anchor.external_verifier.types import PoleResult


# ---------------------------------------------------------------------------
# Public dataclasses and enums
# ---------------------------------------------------------------------------


class QuorumPolicy(str, enum.Enum):
    """Quorum threshold for the aggregator's ``ok`` verdict."""

    #: At least three poles must return ``ok=True``. Default.
    THREE_OF_FOUR = "3-of-4"
    #: All four poles must return ``ok=True``.
    ALL = "all"
    #: At least two poles must return ``ok=True``. Debug-only.
    TWO_OF_FOUR = "2-of-4"


@dataclasses.dataclass(frozen=True)
class AnchorVerification:
    """Aggregated outcome of an :func:`verify_wat_anchor` call.

    Attributes
    ----------
    anchor_hash:
        The 32-byte merkle root hash that was checked, lowercase hex.
    quorum_policy:
        The :class:`QuorumPolicy` requested at call time.
    quorum:
        ``True`` when the configured quorum was reached.
    pole_results:
        Per-pole :class:`PoleResult` keyed by pole name.
    witnesses:
        Compact list of ``(pole_name, witness_dict)`` for callers
        that want to render an audit table without flattening
        ``pole_results`` themselves.
    """

    anchor_hash: str
    quorum_policy: QuorumPolicy
    quorum: bool
    pole_results: dict[str, PoleResult]
    witnesses: list[tuple[str, Mapping[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_hash": self.anchor_hash,
            "quorum_policy": self.quorum_policy.value,
            "quorum": self.quorum,
            "pole_results": {
                name: pr.to_dict() for name, pr in self.pole_results.items()
            },
        }


# ---------------------------------------------------------------------------
# Pole registry
# ---------------------------------------------------------------------------


#: Mapping from pole name to ``(verify-callable, doc-string)``. The order
#: is the canonical pole order rendered in CLI output and ``to_dict``.
POLE_REGISTRY: dict[str, Callable[..., PoleResult]] = {
    "pole_python_stdlib": _poles.pole_python_stdlib_verify,
    "pole_ots_cli": _poles.pole_ots_cli_verify,
    "pole_mempool_space": _poles.pole_mempool_space_verify,
    "pole_esplora_blockstream": _poles.pole_esplora_blockstream_verify,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_wat_anchor(
    anchor_hash: str,
    ots_proof_path: str,
    *,
    quorum_policy: QuorumPolicy = QuorumPolicy.THREE_OF_FOUR,
    enabled_poles: Optional[list[str]] = None,
    pole_overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> AnchorVerification:
    """Run the 4-pole cross-library verifier on a WAT anchor.

    Parameters
    ----------
    anchor_hash:
        Lowercase 64-hex-char string. The merkle root the OTS proof
        attests to.
    ots_proof_path:
        Filesystem path to the ``.ots`` receipt file.
    quorum_policy:
        Threshold policy. See :class:`QuorumPolicy`.
    enabled_poles:
        Optional list of pole names to run. ``None`` runs every
        pole in :data:`POLE_REGISTRY`. Useful for narrow re-runs.
    pole_overrides:
        Mapping ``pole_name -> kwargs`` for per-pole injection
        (transport mocks, alternative base URLs, custom CLI runner).
        Tests use this to keep the suite fully offline.

    Returns
    -------
    :class:`AnchorVerification`
    """
    if not _is_hex_hash(anchor_hash):
        raise ValueError(
            f"anchor_hash must be a 64-char lowercase hex string, got "
            f"{anchor_hash!r}"
        )

    names = enabled_poles or list(POLE_REGISTRY.keys())
    overrides = pole_overrides or {}

    pole_results: dict[str, PoleResult] = {}
    for name in names:
        if name not in POLE_REGISTRY:
            raise ValueError(f"unknown pole: {name}")
        kwargs = dict(overrides.get(name, {}))
        try:
            result = POLE_REGISTRY[name](
                anchor_hash=anchor_hash,
                ots_proof_path=ots_proof_path,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - poles must never crash aggregator
            result = PoleResult(
                name=name,
                ok=False,
                verdict="unavailable",
                witness={},
                note=f"pole crashed: {type(exc).__name__}: {exc}",
            )
        pole_results[name] = result

    quorum = _evaluate_quorum(pole_results, quorum_policy)
    witnesses = [(name, pr.witness) for name, pr in pole_results.items()]

    return AnchorVerification(
        anchor_hash=anchor_hash,
        quorum_policy=quorum_policy,
        quorum=quorum,
        pole_results=pole_results,
        witnesses=witnesses,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _evaluate_quorum(
    pole_results: Mapping[str, PoleResult],
    policy: QuorumPolicy,
) -> bool:
    ok_count = sum(1 for pr in pole_results.values() if pr.ok)
    total = len(pole_results)
    if total == 0:
        return False
    if policy == QuorumPolicy.ALL:
        return ok_count == total
    if policy == QuorumPolicy.THREE_OF_FOUR:
        return ok_count >= 3
    if policy == QuorumPolicy.TWO_OF_FOUR:
        return ok_count >= 2
    raise ValueError(f"unknown quorum policy: {policy}")  # pragma: no cover


def _is_hex_hash(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 64:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return s == s.lower()
