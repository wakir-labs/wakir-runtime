# SPDX-License-Identifier: Apache-2.0
"""``registered_by`` capability-gating for schema-registry entries
(Phase-2 Sprint-4 Tag-6).

This module is the Layer-3 capability-gating tier for Phase-2 schema-
registry signing. It binds the ``registered_by`` field of a
:class:`wirelang.schemas.registry_nats_kv_backend.SchemaRegistryEntry`
to an in-memory policy bundle that constrains *which* signing keys
(``kid``) and *which* schema triples (``layer`` × ``name``) a given
publisher identity is authorised to register.

Design contract (spec §5.12):

1. **Layered above cryptographic verification.** The gate is *additive*
   policy on top of :func:`wirelang.schemas.entry_signing.verify_entry_signature`.
   A cryptographically valid signature can still be denied if the
   ``registered_by`` identity does not hold capability over the schema
   triple it is attempting to register. Cryptographic correctness
   remains the single source of truth in
   :mod:`wirelang.schemas.entry_signing`; the gate is a *separate*
   authorisation layer.

2. **Policy bundle shape.** A :class:`CapabilityPolicy` carries:

   - ``registered_by``: free-form publisher identity string (matches
     the entry's ``registered_by`` field exactly).
   - ``allowed_kids``: tuple of ``kid`` strings the policy authorises
     (the entry's signature-block ``kid`` MUST be a member).
   - ``allowed_triples``: tuple of ``(layer, name_glob)`` pairs;
     ``layer`` may be ``"*"`` (any layer) or a concrete layer string;
     ``name_glob`` follows the :mod:`fnmatch` grammar (``*`` / ``?``
     / ``[seq]``). The entry's ``(layer, name)`` MUST match at least
     one pair.
   - ``not_before`` / ``not_after``: optional RFC-3339 datetime
     window. When supplied, ``as_of`` MUST fall within the window
     (inclusive of ``not_before``, exclusive of ``not_after``).
     ``None`` on either field disables the corresponding bound.
   - ``disabled``: boolean kill-switch. A disabled policy never
     matches.
   - ``note``: optional free-form audit string (carried verbatim into
     the :class:`CapabilityGateDecision` for downstream logs).

3. **Glob semantics.** Tag-6 ships ``fnmatch`` glob matching for
   schema names. The layer field is matched literally with one
   wildcard escape (``"*"``). This is intentionally restrictive: more
   expressive policy languages (regex, Datalog) are out of scope for
   Tag-6 and remain Phase-3 slots.

4. **Decision shape.** Every gate call returns a
   :class:`CapabilityGateDecision`. The decision records ``allowed``
   (bool), a free-form ``reason`` string suitable for audit logs, and
   the matched ``policy`` (``None`` when no policy matched). Callers
   that want exception semantics raise on
   ``not decision.allowed`` themselves.

5. **Registry lookup is keyed by ``registered_by`` exactly.** Two
   policies may share an issuer identity if they have disjoint
   ``allowed_triples`` — the registry's :meth:`policies_for` returns
   all matching policies; the gate iterates and short-circuits on the
   first allowing match. A policy missing the entry's
   ``registered_by`` is invisible to the gate.

Phase-2 Sprint-4 Tag-6 boundary (spec §5.12 boundary block):

- This module ships the policy bundle, the registry, and the gating
  function. It does NOT ship Biscuit binary token machinery (Phase-3:
  full Biscuit v3 token encode/decode + Datalog evaluation; see
  ``wirelang/schemas/layer-3-capability-token.json`` for the
  on-the-wire shape).
- This module does NOT mutate
  :class:`wirelang.schemas.registry_nats_kv_backend.NatsKvSchemaRegistry`;
  no new backend method, no envelope-schema change.
- This module does NOT fetch policies from a transport; the registry
  is in-process only. Persisted policy distribution (NATS-KV bucket
  ``wakir-capability-policies`` or analogous) is a Phase-3 slot.
- This module does NOT replace
  :func:`wirelang.schemas.entry_signing.verify_entry_signature`; the
  signature-verification primitive remains caller-driven and
  byte-identical.

Cross-Review-Zone-1 (Identity-Substrate) interaction:

- Z-1-K-Sprint-4-1 (kid-Resolver-Shape) is consumed *upstream* by the
  caller; the gate takes the ``signature_block["kid"]`` byte-equal as
  the caller supplied it and checks set-membership against
  ``allowed_kids``. The gate does NOT call
  :func:`wirelang.identity.kid_resolver.resolve_kid`.
- Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) is non-touched: the gate does
  not canonicalise anything; it is policy-evaluation only.
- Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519) is reinforced indirectly:
  the gate operates on the entry-signing layer (which is Ed25519); it
  carries no curve choice of its own.
- Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) is non-touched:
  the gate is *additional* policy and is orthogonal to the
  :class:`wirelang.schemas.entry_signing.VerifyMode` toggle.

References:

- Spec §5.12 (registered_by capability-gating operational contract).
- Schema-registry spec §5.8 (entry-signing layer; the upstream
  cryptographic primitive).
- :file:`wirelang/schemas/layer-3-capability-token.json` (the
  Wakir-Wirelang Layer-3 Biscuit v3 wrapper JSON schema; this Tag-6
  layer is a *prelude* to the full Biscuit machinery).
- Reza Persona §2 (Capability-Token-Layer: Reza-Owner-Domain).
"""

from __future__ import annotations

import enum
import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from wirelang.schemas.registry_nats_kv_backend import SchemaRegistryEntry


# ---------------------------------------------------------------------------
# Typed exception (structural failure class, spec §5.12).
# ---------------------------------------------------------------------------


class RegisteredByCapabilityError(Exception):
    """Structural failure in capability-policy construction or gating.

    Raised on: empty ``registered_by``, empty ``allowed_kids``, empty
    ``allowed_triples``, non-datetime ``not_before`` / ``not_after``,
    inverted validity window (``not_before >= not_after``), and on
    type-violations of the gate-call arguments. A non-matching
    *policy outcome* (no policy for this issuer, kid not in the
    allowed set, etc.) is NOT a structural failure; it surfaces as
    a :class:`CapabilityGateDecision` with ``allowed=False`` and a
    descriptive ``reason`` string.

    This split mirrors the
    :class:`wirelang.schemas.entry_signing.SchemaRegistrySignatureError`
    convention: structural failures raise; policy / cryptographic
    outcomes are returned via the decision/Bool path.
    """


# ---------------------------------------------------------------------------
# Decision-source enum (audit aid).
# ---------------------------------------------------------------------------


class DecisionSource(enum.Enum):
    """Where the gate's decision originated.

    Carried on :class:`CapabilityGateDecision` for downstream audit
    consumers that want to distinguish *why* a decision was reached
    without parsing the free-form ``reason`` string.
    """

    POLICY_MATCH = "policy_match"
    POLICY_DISABLED = "policy_disabled"
    NO_POLICY_FOR_ISSUER = "no_policy_for_issuer"
    KID_NOT_ALLOWED = "kid_not_allowed"
    TRIPLE_NOT_ALLOWED = "triple_not_allowed"
    OUTSIDE_VALIDITY_WINDOW = "outside_validity_window"
    POLICY_REVOKED = "policy_revoked"


# ---------------------------------------------------------------------------
# Policy bundle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityPolicy:
    """A capability-policy bundle for one ``registered_by`` identity.

    Frozen at construction; the registry stores instances by reference
    and the gate evaluates against a read-only view. Construction
    validates the bundle shape; downstream consumers can trust the
    invariants byte-equally.
    """

    registered_by: str
    allowed_kids: Tuple[str, ...]
    allowed_triples: Tuple[Tuple[str, str], ...]
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    disabled: bool = False
    note: Optional[str] = None
    # Phase-2 Sprint-6 Tag-1: explicit revocation surface.
    # ``revoked_at`` is the wall-clock instant at which the policy
    # becomes revoked; if supplied, the gate denies any call with
    # ``as_of >= revoked_at`` with source ``POLICY_REVOKED``.
    # ``revocation_reason`` is a free-form audit string (carried into
    # the decision for downstream logs). Both fields default to
    # ``None`` (no revocation); shape is additive to the
    # Sprint-4 Tag-6 bundle. Revocation has *precedence* over disabled
    # / kid / triple / window checks: a revoked policy denies
    # categorically once the revocation instant has passed.
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.registered_by, str) or self.registered_by == "":
            raise RegisteredByCapabilityError(
                f"registered_by must be a non-empty string: got "
                f"{self.registered_by!r}"
            )
        if not isinstance(self.allowed_kids, tuple) or len(self.allowed_kids) == 0:
            raise RegisteredByCapabilityError(
                "allowed_kids must be a non-empty tuple of kid strings"
            )
        for k in self.allowed_kids:
            if not isinstance(k, str) or k == "":
                raise RegisteredByCapabilityError(
                    f"allowed_kids entries must be non-empty strings: got "
                    f"{k!r}"
                )
        if not isinstance(self.allowed_triples, tuple) or len(self.allowed_triples) == 0:
            raise RegisteredByCapabilityError(
                "allowed_triples must be a non-empty tuple of "
                "(layer, name_glob) pairs"
            )
        for t in self.allowed_triples:
            if (
                not isinstance(t, tuple)
                or len(t) != 2
                or not isinstance(t[0], str)
                or not isinstance(t[1], str)
                or t[0] == ""
                or t[1] == ""
            ):
                raise RegisteredByCapabilityError(
                    f"allowed_triples entries must be (layer, name_glob) "
                    f"pairs of non-empty strings: got {t!r}"
                )
        if self.not_before is not None and not isinstance(
            self.not_before, datetime
        ):
            raise RegisteredByCapabilityError(
                f"not_before must be a datetime or None: type="
                f"{type(self.not_before).__name__}"
            )
        if self.not_after is not None and not isinstance(self.not_after, datetime):
            raise RegisteredByCapabilityError(
                f"not_after must be a datetime or None: type="
                f"{type(self.not_after).__name__}"
            )
        if (
            self.not_before is not None
            and self.not_after is not None
            and self.not_before >= self.not_after
        ):
            raise RegisteredByCapabilityError(
                f"not_before must be strictly less than not_after: "
                f"not_before={self.not_before!r} not_after={self.not_after!r}"
            )
        if not isinstance(self.disabled, bool):
            raise RegisteredByCapabilityError(
                f"disabled must be a bool: type={type(self.disabled).__name__}"
            )
        if self.note is not None and not isinstance(self.note, str):
            raise RegisteredByCapabilityError(
                f"note must be a string or None: type="
                f"{type(self.note).__name__}"
            )
        # Phase-2 Sprint-6 Tag-1: revocation field validation.
        if self.revoked_at is not None and not isinstance(
            self.revoked_at, datetime
        ):
            raise RegisteredByCapabilityError(
                f"revoked_at must be a datetime or None: type="
                f"{type(self.revoked_at).__name__}"
            )
        if self.revoked_at is not None and self.revoked_at.tzinfo is None:
            raise RegisteredByCapabilityError(
                "revoked_at must be timezone-aware"
            )
        if self.revocation_reason is not None and not isinstance(
            self.revocation_reason, str
        ):
            raise RegisteredByCapabilityError(
                f"revocation_reason must be a string or None: type="
                f"{type(self.revocation_reason).__name__}"
            )
        if self.revocation_reason is not None and self.revoked_at is None:
            raise RegisteredByCapabilityError(
                "revocation_reason requires revoked_at to be set"
            )

    def covers_triple(self, layer: str, name: str) -> bool:
        """Return True iff at least one ``allowed_triples`` entry
        matches ``(layer, name)``.

        Layer match is literal with ``"*"`` as wildcard; name match
        is :mod:`fnmatch` glob.
        """
        for pat_layer, pat_name in self.allowed_triples:
            if pat_layer != "*" and pat_layer != layer:
                continue
            if not fnmatch.fnmatchcase(name, pat_name):
                continue
            return True
        return False


# ---------------------------------------------------------------------------
# Decision dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityGateDecision:
    """The outcome of a gate evaluation.

    Frozen; equality-by-value. The ``policy`` field is the matched
    policy bundle for an allow decision, the *attempted* policy bundle
    for a deny-by-disabled / deny-by-window / deny-by-kid /
    deny-by-triple decision, or ``None`` for a no-policy-for-issuer
    decision.
    """

    allowed: bool
    reason: str
    source: DecisionSource
    policy: Optional[CapabilityPolicy] = None


# ---------------------------------------------------------------------------
# Registry.
# ---------------------------------------------------------------------------


class CapabilityPolicyRegistry:
    """In-memory registry of :class:`CapabilityPolicy` bundles.

    Indexed by ``registered_by`` identity; one identity may carry
    multiple policies (e.g. one per kid generation, or one per schema
    layer). The gate iterates all matching policies and short-circuits
    on the first allowing match.

    The registry is mutable: callers add policies via :meth:`add_policy`
    and look up via :meth:`policies_for`. List operations return
    defensive tuples; the underlying storage is not exposed.
    """

    def __init__(self) -> None:
        self._by_issuer: dict[str, list[CapabilityPolicy]] = {}

    def add_policy(self, policy: CapabilityPolicy) -> None:
        """Add a policy to the registry.

        Idempotent: adding the same policy instance twice is harmless
        (the second add appends a duplicate entry to the per-issuer
        list, which the gate evaluates as a no-op equivalent — the
        first allowing match short-circuits the iteration). Adding
        two distinct policies with the same ``registered_by`` is
        explicitly supported and is the canonical way to express
        per-kid / per-layer policy splits.
        """
        if not isinstance(policy, CapabilityPolicy):
            raise RegisteredByCapabilityError(
                f"policy must be a CapabilityPolicy: type="
                f"{type(policy).__name__}"
            )
        self._by_issuer.setdefault(policy.registered_by, []).append(policy)

    def policies_for(self, registered_by: str) -> Tuple[CapabilityPolicy, ...]:
        """Return all policies registered for ``registered_by`` (tuple
        snapshot; mutation-safe)."""
        if not isinstance(registered_by, str):
            raise RegisteredByCapabilityError(
                f"registered_by must be a string: type="
                f"{type(registered_by).__name__}"
            )
        return tuple(self._by_issuer.get(registered_by, ()))

    def list_issuers(self) -> Tuple[str, ...]:
        """Return all known ``registered_by`` identities (sorted tuple
        snapshot)."""
        return tuple(sorted(self._by_issuer.keys()))


# ---------------------------------------------------------------------------
# Gating function.
# ---------------------------------------------------------------------------


def _is_revoked(
    policy: CapabilityPolicy, as_of: Optional[datetime]
) -> bool:
    """Return True iff the policy carries an explicit revocation and
    ``as_of`` has reached or passed the revocation instant.

    Phase-2 Sprint-6 Tag-1: an unrevoked policy returns False
    regardless of ``as_of``. A revoked policy returns True for any
    ``as_of`` greater than or equal to ``policy.revoked_at``. When
    ``as_of`` is ``None`` (callers that omit time-gating intent), a
    revoked policy is treated as revoked unconditionally — revocation
    is a categorical authority gesture, not a window. This is
    deliberately stricter than the Sprint-4 Tag-6 ``_window_contains``
    semantics for ``not_before`` / ``not_after`` (which skip on
    ``as_of=None``); a revocation must never be silently bypassed by
    a verifier that omits a clock.
    """
    if policy.revoked_at is None:
        return False
    if as_of is None:
        return True
    return as_of >= policy.revoked_at


def _window_contains(
    policy: CapabilityPolicy, as_of: Optional[datetime]
) -> bool:
    """Return True iff ``as_of`` is inside the policy's validity
    window (inclusive of ``not_before``, exclusive of ``not_after``).

    When ``as_of`` is ``None`` the window check is skipped (callers
    that omit ``as_of`` declare intent to bypass time gating;
    production verifier paths SHOULD supply ``as_of``).
    """
    if as_of is None:
        return True
    if policy.not_before is not None and as_of < policy.not_before:
        return False
    if policy.not_after is not None and as_of >= policy.not_after:
        return False
    return True


def check_registered_by_capability(
    entry: SchemaRegistryEntry,
    signature_block: Mapping[str, Any],
    registry: CapabilityPolicyRegistry,
    *,
    as_of: Optional[datetime] = None,
) -> CapabilityGateDecision:
    """Gate a schema-registry entry against the capability policy
    registry.

    Evaluation order:

    1. Look up policies for ``entry.registered_by``. If none exist,
       return a deny decision with source ``NO_POLICY_FOR_ISSUER``.
    2. Iterate the candidate policies. For each:

       a. If ``policy.disabled``, skip (the first non-disabled match
          drives the decision; a registry that only carries disabled
          policies for this issuer returns a deny with source
          ``POLICY_DISABLED``).
       b. If ``signature_block["kid"]`` is not in ``policy.allowed_kids``,
          remember as a fallback deny-source and continue.
       c. If ``policy.covers_triple(entry.layer, entry.name)`` is
          False, remember as a fallback deny-source and continue.
       d. If ``as_of`` is supplied and falls outside the policy's
          validity window, remember as a fallback deny-source and
          continue.
       e. Otherwise, return an allow decision with source
          ``POLICY_MATCH``.
    3. If no policy allowed and any fallback deny-source was
       remembered, return that. Otherwise return a deny with
       ``NO_POLICY_FOR_ISSUER``.

    The fallback deny-source ordering is: first-encountered
    structural mismatch (kid > triple > window). Callers that need
    a tabular view of *all* policy mismatches can call
    :meth:`CapabilityPolicyRegistry.policies_for` directly.
    """
    if not isinstance(entry, SchemaRegistryEntry):
        raise RegisteredByCapabilityError(
            f"entry must be a SchemaRegistryEntry: type="
            f"{type(entry).__name__}"
        )
    if not isinstance(signature_block, Mapping):
        raise RegisteredByCapabilityError(
            f"signature_block must be a mapping: type="
            f"{type(signature_block).__name__}"
        )
    if "kid" not in signature_block:
        raise RegisteredByCapabilityError(
            "signature_block missing required field: 'kid'"
        )
    if not isinstance(registry, CapabilityPolicyRegistry):
        raise RegisteredByCapabilityError(
            f"registry must be a CapabilityPolicyRegistry: type="
            f"{type(registry).__name__}"
        )
    if as_of is not None and not isinstance(as_of, datetime):
        raise RegisteredByCapabilityError(
            f"as_of must be a datetime or None: type="
            f"{type(as_of).__name__}"
        )

    kid = signature_block["kid"]
    if not isinstance(kid, str) or kid == "":
        raise RegisteredByCapabilityError(
            f"signature_block kid must be a non-empty string: got {kid!r}"
        )

    candidates = registry.policies_for(entry.registered_by)
    if not candidates:
        return CapabilityGateDecision(
            allowed=False,
            reason=(
                f"no capability policy registered for "
                f"registered_by={entry.registered_by!r}"
            ),
            source=DecisionSource.NO_POLICY_FOR_ISSUER,
            policy=None,
        )

    fallback: Optional[CapabilityGateDecision] = None
    all_disabled = True

    for policy in candidates:
        # Phase-2 Sprint-6 Tag-1: revocation has top precedence.
        # An issuer's revoked policy is filtered out before the
        # disabled / kid / triple / window checks; a revoked policy
        # never produces an allow decision, regardless of any other
        # field. The fallback deny-source ordering is amended:
        # POLICY_REVOKED outranks POLICY_DISABLED / KID_NOT_ALLOWED /
        # TRIPLE_NOT_ALLOWED / OUTSIDE_VALIDITY_WINDOW so that a
        # mixed-state registry (one revoked + one stale-fallback
        # policy) reports the revocation as the canonical reason.
        if _is_revoked(policy, as_of):
            if fallback is None or fallback.source is not DecisionSource.POLICY_REVOKED:
                reason_suffix = (
                    f" reason={policy.revocation_reason!r}"
                    if policy.revocation_reason is not None
                    else ""
                )
                fallback = CapabilityGateDecision(
                    allowed=False,
                    reason=(
                        f"policy for registered_by="
                        f"{entry.registered_by!r} was revoked at "
                        f"{policy.revoked_at!r}{reason_suffix}"
                    ),
                    source=DecisionSource.POLICY_REVOKED,
                    policy=policy,
                )
            continue

        if policy.disabled:
            if fallback is None:
                fallback = CapabilityGateDecision(
                    allowed=False,
                    reason=(
                        f"policy for registered_by="
                        f"{entry.registered_by!r} is disabled"
                    ),
                    source=DecisionSource.POLICY_DISABLED,
                    policy=policy,
                )
            continue
        all_disabled = False

        if kid not in policy.allowed_kids:
            if fallback is None or fallback.source is DecisionSource.POLICY_DISABLED:
                fallback = CapabilityGateDecision(
                    allowed=False,
                    reason=(
                        f"kid={kid!r} not in allowed_kids="
                        f"{policy.allowed_kids!r} for registered_by="
                        f"{entry.registered_by!r}"
                    ),
                    source=DecisionSource.KID_NOT_ALLOWED,
                    policy=policy,
                )
            continue

        if not policy.covers_triple(entry.layer, entry.name):
            if (
                fallback is None
                or fallback.source
                in (DecisionSource.POLICY_DISABLED, DecisionSource.KID_NOT_ALLOWED)
            ):
                fallback = CapabilityGateDecision(
                    allowed=False,
                    reason=(
                        f"triple=(layer={entry.layer!r}, name="
                        f"{entry.name!r}) not covered by allowed_triples="
                        f"{policy.allowed_triples!r} for registered_by="
                        f"{entry.registered_by!r}"
                    ),
                    source=DecisionSource.TRIPLE_NOT_ALLOWED,
                    policy=policy,
                )
            continue

        if not _window_contains(policy, as_of):
            if (
                fallback is None
                or fallback.source
                in (
                    DecisionSource.POLICY_DISABLED,
                    DecisionSource.KID_NOT_ALLOWED,
                    DecisionSource.TRIPLE_NOT_ALLOWED,
                )
            ):
                fallback = CapabilityGateDecision(
                    allowed=False,
                    reason=(
                        f"as_of={as_of!r} outside policy validity window "
                        f"[{policy.not_before!r}, {policy.not_after!r}) "
                        f"for registered_by={entry.registered_by!r}"
                    ),
                    source=DecisionSource.OUTSIDE_VALIDITY_WINDOW,
                    policy=policy,
                )
            continue

        return CapabilityGateDecision(
            allowed=True,
            reason=(
                f"policy match for registered_by={entry.registered_by!r}, "
                f"kid={kid!r}, triple=(layer={entry.layer!r}, name="
                f"{entry.name!r})"
            ),
            source=DecisionSource.POLICY_MATCH,
            policy=policy,
        )

    if all_disabled and fallback is not None:
        return fallback
    if fallback is not None:
        return fallback
    # Defensive fall-through; control flow should always have returned
    # by now.
    return CapabilityGateDecision(  # pragma: no cover
        allowed=False,
        reason=(
            f"no policy matched for registered_by={entry.registered_by!r}"
        ),
        source=DecisionSource.NO_POLICY_FOR_ISSUER,
        policy=None,
    )


# ---------------------------------------------------------------------------
# Composition helper (signed-entry shortcut).
# ---------------------------------------------------------------------------


def gate_signed_entry(
    signed: "Any",  # SignedSchemaRegistryEntry, lazy-imported to avoid cycle
    registry: CapabilityPolicyRegistry,
    *,
    as_of: Optional[datetime] = None,
) -> CapabilityGateDecision:
    """Gate a :class:`wirelang.schemas.entry_signing.SignedSchemaRegistryEntry`
    end-to-end.

    This is a thin convenience wrapper: it extracts ``signed.entry``
    and ``signed.signature`` and routes them through
    :func:`check_registered_by_capability`. The signed wrapper's
    cryptographic correctness is NOT re-verified here — the caller is
    expected to have run
    :func:`wirelang.schemas.entry_signing.verify_entry_signature`
    already (or to do so independently); the gate is *additive*
    authorisation policy.
    """
    # Local import to avoid a circular-import path:
    # entry_signing imports SchemaRegistryEntry from
    # registry_nats_kv_backend, which is also our base. Importing
    # entry_signing at module-import time would create a cycle if any
    # future entry_signing change ever imports from this module. The
    # function-local import keeps the cycle impossible.
    from wirelang.schemas.entry_signing import SignedSchemaRegistryEntry

    if not isinstance(signed, SignedSchemaRegistryEntry):
        raise RegisteredByCapabilityError(
            f"signed must be a SignedSchemaRegistryEntry: type="
            f"{type(signed).__name__}"
        )
    return check_registered_by_capability(
        signed.entry, signed.signature, registry, as_of=as_of
    )


__all__ = [
    "RegisteredByCapabilityError",
    "DecisionSource",
    "CapabilityPolicy",
    "CapabilityGateDecision",
    "CapabilityPolicyRegistry",
    "check_registered_by_capability",
    "gate_signed_entry",
]
