# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Publisher/Subscriber surface compatibility contract (Tag-41 Bug-42).

This module is the Tag-41 substantive close-out of the Bug-42 class
documented in ``wirelang/specs/wirelang-spec-v0-2.md`` §13 (Layer-0
Subscribe-Mode contract).

Bug-42 manifests as a silent message-drop when a producer publishes
via core-NATS (``nc.publish``) and a subscriber binds via a
JetStream-pull-consumer expecting persistence semantics — the wire
format is well-formed, the connection succeeds, but no message ever
arrives. The compatibility matrix in spec §13.2 catalogues six
failure modes (F-1..F-6); this module provides the programmatic
substrate to detect and refuse incompatible bring-ups before the
silent-drop happens.

Public surface
--------------
- :data:`PUBLISH_MODE_CORE`, :data:`PUBLISH_MODE_JETSTREAM`: producer
  declarations.
- :data:`SUBSCRIBE_SURFACE_CORE`, :data:`SUBSCRIBE_SURFACE_JS_PUSH`,
  :data:`SUBSCRIBE_SURFACE_JS_PULL`: subscriber declarations.
- :class:`CompatibilityVerdict`: result of a compatibility check.
- :func:`check_compatibility`: produce a verdict for a (producer,
  subscriber) pair against the spec §13.2 matrix.
- :func:`require_compatible`: raise :class:`SurfaceMismatchError` on
  silent-drop pairs. The persona-engine CLI calls this at bring-up.

Design constraints
------------------
- Pure-Python, zero dependencies. No nats-py import. Hermetic-test-
  ready and importable in any context.
- Mirrors :mod:`nats_subscribe_loop` mode-string conventions for the
  subscriber side; producer side is brand-new (Adapter-B substrate).
- The matrix is a frozen table; new modes require an explicit
  spec-update + matrix patch + Tomás cross-review (Zone K parity).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple


# ---------------------------------------------------------------------------
# Mode constants
# ---------------------------------------------------------------------------

#: Core-NATS publish surface — ``nc.publish(subject, payload)``.
#: Fire-and-forget; no server-side persistence.
PUBLISH_MODE_CORE = "core"

#: JetStream publish surface — ``js.publish(subject, payload)`` against
#: a stream whose ``subjects`` filter includes the published subject.
PUBLISH_MODE_JETSTREAM = "jetstream"

#: All valid publish-mode strings (used by the bridge-forward CLI).
VALID_PUBLISH_MODES: Tuple[str, ...] = (
    PUBLISH_MODE_CORE,
    PUBLISH_MODE_JETSTREAM,
)

#: Default publish-mode for the Bridge-Forward-Pipe (spec §13.5
#: locks it to ``core`` for Bridge-Forward-Pipe v1 compatibility).
DEFAULT_PUBLISH_MODE = PUBLISH_MODE_CORE

#: Env-var name that overrides the default publish-mode.
PUBLISH_MODE_ENV_VAR = "WAKIR_NATS_PUBLISH_MODE"


#: Subscriber surface — core NATS subscribe. Mirrors
#: :data:`nats_subscribe_loop.SUBSCRIBE_MODE_CORE_CALLBACK` and
#: :data:`nats_subscribe_loop.SUBSCRIBE_MODE_CORE_ITERATOR`; both
#: are operationally "core" against the matrix.
SUBSCRIBE_SURFACE_CORE = "core"

#: Subscriber surface — JetStream push-consumer.
SUBSCRIBE_SURFACE_JS_PUSH = "jetstream-push"

#: Subscriber surface — JetStream pull-consumer. Mirrors
#: :data:`nats_subscribe_loop.SUBSCRIBE_MODE_JETSTREAM_PULL`.
SUBSCRIBE_SURFACE_JS_PULL = "jetstream-pull"

#: All valid subscriber-surface strings.
VALID_SUBSCRIBE_SURFACES: Tuple[str, ...] = (
    SUBSCRIBE_SURFACE_CORE,
    SUBSCRIBE_SURFACE_JS_PUSH,
    SUBSCRIBE_SURFACE_JS_PULL,
)


def resolve_subscribe_surface_from_subscribe_mode(subscribe_mode: str) -> str:
    """Map a :mod:`nats_subscribe_loop` mode string to a surface.

    The subscribe-loop has three modes (``core-callback``,
    ``core-iterator``, ``jetstream-pull``) but only two operational
    surfaces (``core``, ``jetstream-pull``). This helper performs
    the mapping so the compatibility-matrix can be evaluated against
    surface-only semantics.

    Raises :class:`ValueError` on unknown subscribe-mode strings.
    """
    if subscribe_mode in ("core-callback", "core-iterator"):
        return SUBSCRIBE_SURFACE_CORE
    if subscribe_mode == "jetstream-pull":
        return SUBSCRIBE_SURFACE_JS_PULL
    if subscribe_mode == "jetstream-push":
        return SUBSCRIBE_SURFACE_JS_PUSH
    raise ValueError(
        f"unknown subscribe_mode: {subscribe_mode!r}. "
        f"Valid: core-callback, core-iterator, jetstream-pull, jetstream-push"
    )


# ---------------------------------------------------------------------------
# Compatibility matrix (spec §13.2, frozen)
# ---------------------------------------------------------------------------

#: Pairs that deliver messages without an explicit cross-mode adapter.
#: The tuple is (publish_mode, subscribe_surface). Pairs absent from
#: this set are operationally broken pipes (silent message drop).
#:
#: Note: ``(PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_CORE)`` is listed
#: as "YES (fan-out)" in spec §13.2 with the explicit caveat that
#: producers and subscribers MUST NOT rely on the fan-out leg for
#: correctness. For programmatic checking we treat this as
#: :data:`VERDICT_FANOUT` — neither hard YES nor hard NO.
_HARD_COMPATIBLE: FrozenSet[Tuple[str, str]] = frozenset({
    (PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_CORE),
    (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_JS_PUSH),
    (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_JS_PULL),
})

_FANOUT_DEPENDENT: FrozenSet[Tuple[str, str]] = frozenset({
    (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_CORE),
})


#: Verdict tags.
VERDICT_COMPATIBLE = "compatible"
VERDICT_FANOUT = "fanout-dependent"
VERDICT_BROKEN = "broken-pipe"


# ---------------------------------------------------------------------------
# Failure-mode catalogue (spec §13.3, machine-readable)
# ---------------------------------------------------------------------------

#: Maps a (publish_mode, subscribe_surface) silent-drop pair to its
#: spec §13.3 failure-mode-id. Used by :class:`CompatibilityVerdict`
#: to populate ``failure_mode_id`` so operator runbooks can reference
#: the exact catalogue entry.
_FAILURE_MODE_BY_PAIR: Dict[Tuple[str, str], str] = {
    (PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_JS_PULL): "F-1",
    (PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_JS_PUSH): "F-2",
}


@dataclass(frozen=True)
class CompatibilityVerdict:
    """Result of a publish/subscribe surface compatibility check.

    Attributes
    ----------
    publish_mode
        The producer-side declaration (``core`` / ``jetstream``).
    subscribe_surface
        The subscriber-side surface (``core`` / ``jetstream-push``
        / ``jetstream-pull``).
    verdict
        One of :data:`VERDICT_COMPATIBLE`, :data:`VERDICT_FANOUT`,
        :data:`VERDICT_BROKEN`.
    failure_mode_id
        Spec §13.3 catalogue id if ``verdict == VERDICT_BROKEN``,
        else ``None``.
    diagnosis
        Human-readable diagnosis sentence — surfaces in operator
        logs at bring-up so the silent-drop pair is observable.
    recommended_adapter
        Spec §13.4 adapter recommendation if remediation is needed,
        else ``None``.
    """

    publish_mode: str
    subscribe_surface: str
    verdict: str
    failure_mode_id: Optional[str]
    diagnosis: str
    recommended_adapter: Optional[str]


class SurfaceMismatchError(RuntimeError):
    """Raised when :func:`require_compatible` finds a broken pipe.

    The exception's ``verdict`` attribute carries the full
    :class:`CompatibilityVerdict` so callers can render structured
    error logs.
    """

    def __init__(self, verdict: CompatibilityVerdict) -> None:
        self.verdict = verdict
        super().__init__(verdict.diagnosis)


def check_compatibility(
    publish_mode: str,
    subscribe_surface: str,
) -> CompatibilityVerdict:
    """Evaluate the (producer, subscriber) pair against spec §13.2.

    Inputs
    ------
    publish_mode
        Must be one of :data:`VALID_PUBLISH_MODES`.
    subscribe_surface
        Must be one of :data:`VALID_SUBSCRIBE_SURFACES`. If callers
        have a subscribe-mode string (``core-callback`` etc) from
        :mod:`nats_subscribe_loop` they should pass it through
        :func:`resolve_subscribe_surface_from_subscribe_mode` first.

    Raises
    ------
    ValueError
        If either input is not in the valid-mode set.
    """
    if publish_mode not in VALID_PUBLISH_MODES:
        raise ValueError(
            f"publish_mode must be one of {VALID_PUBLISH_MODES}, "
            f"got {publish_mode!r}"
        )
    if subscribe_surface not in VALID_SUBSCRIBE_SURFACES:
        raise ValueError(
            f"subscribe_surface must be one of {VALID_SUBSCRIBE_SURFACES}, "
            f"got {subscribe_surface!r}"
        )

    pair = (publish_mode, subscribe_surface)
    if pair in _HARD_COMPATIBLE:
        return CompatibilityVerdict(
            publish_mode=publish_mode,
            subscribe_surface=subscribe_surface,
            verdict=VERDICT_COMPATIBLE,
            failure_mode_id=None,
            diagnosis=(
                f"publish={publish_mode} + subscribe={subscribe_surface} "
                f"is compatible per spec §13.2."
            ),
            recommended_adapter=None,
        )
    if pair in _FANOUT_DEPENDENT:
        return CompatibilityVerdict(
            publish_mode=publish_mode,
            subscribe_surface=subscribe_surface,
            verdict=VERDICT_FANOUT,
            failure_mode_id=None,
            diagnosis=(
                f"publish={publish_mode} + subscribe={subscribe_surface} "
                f"depends on JetStream server-side fan-out (spec §13.2 "
                f"footnote ¹). Producers and subscribers MUST NOT rely "
                f"on the fan-out leg for correctness; consider switching "
                f"the subscriber to {SUBSCRIBE_SURFACE_JS_PUSH} or "
                f"{SUBSCRIBE_SURFACE_JS_PULL}."
            ),
            recommended_adapter=None,
        )
    # Broken pipe: a publish/subscribe pair that does not deliver
    # messages without an explicit cross-mode adapter.
    failure_id = _FAILURE_MODE_BY_PAIR.get(pair)
    recommended = _recommend_adapter(publish_mode, subscribe_surface)
    return CompatibilityVerdict(
        publish_mode=publish_mode,
        subscribe_surface=subscribe_surface,
        verdict=VERDICT_BROKEN,
        failure_mode_id=failure_id,
        diagnosis=(
            f"publish={publish_mode} + subscribe={subscribe_surface} "
            f"is a broken pipe per spec §13.2 "
            f"({failure_id or 'unclassified'}). "
            f"Producer publishes do not reach subscriber binds. "
            f"Remediation: insert a cross-mode adapter (§13.4) — "
            f"recommended: {recommended}."
        ),
        recommended_adapter=recommended,
    )


def _recommend_adapter(
    publish_mode: str,
    subscribe_surface: str,
) -> str:
    """Pick a spec §13.4 adapter for a broken pipe.

    Heuristic
    ---------
    - core publisher + JetStream subscriber: Adapter A (stream-mirror)
      is the operational default per spec §13.4. Adapter B (producer-
      rewrite) is the strategic target for Phase-2c-Closeout.
    """
    if (
        publish_mode == PUBLISH_MODE_CORE
        and subscribe_surface in (
            SUBSCRIBE_SURFACE_JS_PULL,
            SUBSCRIBE_SURFACE_JS_PUSH,
        )
    ):
        return (
            "Adapter A (stream-mirror — operational default) or "
            "Adapter B (producer-rewrite to js.publish — Phase-2c "
            "strategic target)"
        )
    return "see spec §13.4 for adapter catalogue"


def require_compatible(
    publish_mode: str,
    subscribe_surface: str,
    *,
    allow_fanout: bool = False,
) -> CompatibilityVerdict:
    """Raise :class:`SurfaceMismatchError` for broken-pipe pairs.

    Parameters
    ----------
    publish_mode, subscribe_surface
        As for :func:`check_compatibility`.
    allow_fanout
        If ``True``, accept :data:`VERDICT_FANOUT` as compatible.
        Default ``False`` because spec §13.2 footnote ¹ is explicit
        that fan-out MUST NOT be relied upon for correctness.

    Returns
    -------
    CompatibilityVerdict
        The verdict; the caller can log its ``diagnosis`` for the
        bring-up record.

    Raises
    ------
    SurfaceMismatchError
        If the pair is :data:`VERDICT_BROKEN`, or if it is
        :data:`VERDICT_FANOUT` and ``allow_fanout`` is False.
    """
    verdict = check_compatibility(publish_mode, subscribe_surface)
    if verdict.verdict == VERDICT_COMPATIBLE:
        return verdict
    if verdict.verdict == VERDICT_FANOUT and allow_fanout:
        return verdict
    raise SurfaceMismatchError(verdict)


# ---------------------------------------------------------------------------
# Env-var resolver (parity with nats_subscribe_loop.resolve_subscribe_mode)
# ---------------------------------------------------------------------------


def resolve_publish_mode(env: Optional[Dict[str, str]] = None) -> str:
    """Return the configured publish-mode (env-var or default).

    Raises ``ValueError`` if the env-var is set to an unknown mode.
    Returns :data:`DEFAULT_PUBLISH_MODE` if unset / empty.
    """
    src = env if env is not None else None
    if src is None:
        import os as _os
        src = _os.environ
    raw = src.get(PUBLISH_MODE_ENV_VAR, "")
    if not raw:
        return DEFAULT_PUBLISH_MODE
    if raw not in VALID_PUBLISH_MODES:
        raise ValueError(
            f"{PUBLISH_MODE_ENV_VAR}={raw!r} is not one of "
            f"{VALID_PUBLISH_MODES}"
        )
    return raw


__all__ = [
    "CompatibilityVerdict",
    "DEFAULT_PUBLISH_MODE",
    "PUBLISH_MODE_CORE",
    "PUBLISH_MODE_ENV_VAR",
    "PUBLISH_MODE_JETSTREAM",
    "SUBSCRIBE_SURFACE_CORE",
    "SUBSCRIBE_SURFACE_JS_PULL",
    "SUBSCRIBE_SURFACE_JS_PUSH",
    "SurfaceMismatchError",
    "VALID_PUBLISH_MODES",
    "VALID_SUBSCRIBE_SURFACES",
    "VERDICT_BROKEN",
    "VERDICT_COMPATIBLE",
    "VERDICT_FANOUT",
    "check_compatibility",
    "require_compatible",
    "resolve_publish_mode",
    "resolve_subscribe_surface_from_subscribe_mode",
]
