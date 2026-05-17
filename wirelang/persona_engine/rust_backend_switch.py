# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""ENV-gated production-default switch for Rust recovery + state-backing + FSM + V907-verify + bridge-diff.

Tag-17 / Tag-18 / Tag-19 / Tag-20 Mini-Welle — Phase-3b-Substanz. The
Rust crates
``persona-engine-recovery`` (PR #135),
``persona-engine-state-backing`` (PR #140),
``persona-engine-fsm`` (PR #137),
``persona-engine-v907-verify`` (PR #136), and
``persona-engine-bridge-diff`` (PR #131) are production-ready as
schema-byte-parity substrates of their Python pendants
(:mod:`wirelang.persona_engine.recovery_workflow`,
:mod:`wirelang.persona_engine.state_backing`,
:mod:`wirelang.persona_engine.lifecycle_state_machine`,
:mod:`wirelang.persona_engine.v907_verify`, and
:mod:`wirelang.persona_engine.bridge_audit_diff_engine`). This module
exposes the **production-default switch** — operators flip an env-var
to opt into the Rust subprocess-bridge without disrupting the Python
hot-path.

Tag-19 anchor — V-907 is the hash-determinism anchor
-----------------------------------------------------

V-907 is the **most critical** of the four switch components: it
computes the persona-hash pin that the WAT-audit substrate consumes
as the engine-side ground-truth. Any byte-drift between the Python
authority and the Rust subprocess-bridge would silently corrupt the
audit-trail. The Tag-19 wire-up therefore adds a hard byte-identity
gate (all-pin-pack-vectors-rust-verified) on top of the same
production-default-switch posture as Tag-17/Tag-18.

Tag-20 anchor — Bridge-Diff is the Doppelbetrieb oracle
--------------------------------------------------------

The bridge-diff engine is the Phase-3a/3b Doppelbetrieb comparison
oracle: it canonicalises (RFC 8785 JCS), hashes (SHA-256), and field-
level diffs (RFC 6901) CloudEvent envelopes emitted by two
implementations of the same emission. Any drift in the canonicaliser,
the hash, the field-walker, or the sort order surfaces in the audit-
trail — making this the **integrity oracle** for the entire Phase-3a
cross-language parity story. The Tag-20 wire-up therefore adds a hard
byte-identity gate across **all six cross-lang field-pin vectors**
(see ``cross_lang_field_diff_fixtures.json`` and PR #166's emitter
test) on top of the same production-default-switch posture as
Tag-17/Tag-18/Tag-19.

Posture
-------

- Default is **Python** (current behaviour, opt-in switch).
- Rust subprocess-bridge invokes a Rust CLI binary at a well-known
  path (``/opt/wakir/bin/wakir-persona-engine-recovery`` and
  ``/opt/wakir/bin/wakir-persona-engine-state-backing`` by default).
- **Graceful fallback**: when the Rust CLI binary is missing or
  non-executable, the switch silently falls back to the Python
  implementation and logs a structured ``backend-fallback`` record
  — operators see the degradation in the audit substrate.
- **Per-decision logging**: every backend selection emits a
  ``backend-decision`` record carrying the chosen backend label
  and the resolution latency (microseconds). The bridge-audit
  writer consumes these records for the Phase-3b Doppelbetrieb
  comparison set.

Env-var contract
----------------

``WAKIR_RECOVERY_BACKEND``:

* ``"python"`` (default) — Python :class:`RecoveryWorkflow`.
* ``"rust"`` — Rust-CLI subprocess-bridge. Falls back to ``"python"``
  with a structured-log warning when the binary is not callable.

``WAKIR_STATE_BACKING_BACKEND``:

* ``"python"`` (default) — Python state-backing selection
  (NATS-KV with fence to in-memory; the engine's existing
  ``_select_state_backing()`` logic).
* ``"rust_inmemory"`` — Rust-CLI subprocess-bridge against an
  in-memory state-backing (hermetic, no NATS).
* ``"rust_natskv"`` — Rust-CLI subprocess-bridge against a NATS-KV
  state-backing (production).

Both rust-bound values fall back to ``"python"`` with a structured-
log warning when the binary is not callable.

``WAKIR_FSM_BACKEND``:

* ``"python"`` (default) — Python :class:`LifecycleStateMachine`
  (six states, nine transitions per spec §3.3).
* ``"rust"`` — Rust-CLI subprocess-bridge against the
  ``persona-engine-fsm`` crate (PR #137, schema-byte-parity with
  the Python authority). Falls back to ``"python"`` with a
  structured-log warning when the binary is not callable.

``WAKIR_V907_VERIFY_BACKEND``:

* ``"python"`` (default) — Python :func:`compute_v907_pin` /
  :func:`verify_v907_pin` (spec §5 hash-determinism anchor).
* ``"rust"`` — Rust-CLI subprocess-bridge against the
  ``persona-engine-v907-verify`` crate (PR #136, byte-identical
  hash output verified against all pin-pack vectors). Falls back
  to ``"python"`` with a structured-log warning when the binary
  is not callable.

``WAKIR_BRIDGE_DIFF_BACKEND``:

* ``"python"`` (default) — Python
  :mod:`wirelang.persona_engine.bridge_audit_diff_engine`
  (PR #106, Doppelbetrieb comparison oracle: JCS + SHA-256 +
  RFC-6901 field-paths).
* ``"rust"`` — Rust-CLI subprocess-bridge against the
  ``persona-engine-bridge-diff`` crate (PR #131, byte-identical
  hash output AND byte-identical RFC-6901 field-path entries
  verified against all six cross-lang field-pin vectors, see PR
  #166). Falls back to ``"python"`` with a structured-log
  warning when the binary is not callable.

``WAKIR_RUST_RECOVERY_BIN``:

* Absolute path to the Rust recovery binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-recovery``.

``WAKIR_RUST_STATE_BACKING_BIN``:

* Absolute path to the Rust state-backing binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-state-backing``.

``WAKIR_RUST_FSM_BIN``:

* Absolute path to the Rust FSM binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-fsm``.

``WAKIR_RUST_V907_VERIFY_BIN``:

* Absolute path to the Rust V907-verify binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-v907-verify``.

``WAKIR_RUST_BRIDGE_DIFF_BIN``:

* Absolute path to the Rust bridge-diff binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-bridge-diff``.

``WAKIR_RUST_BACKEND_TIMEOUT_S``:

* Wall-clock timeout per subprocess call. Default ``5.0`` seconds.
  Resolution failure (non-positive / unparseable) falls back to
  the default with a warning — mirrors the
  :mod:`rust_adapter_hook` env-validation posture.

Unknown env-var values
----------------------

Unknown values for either backend-switch env-var raise
:class:`BackendSwitchValidationError` at resolution time. This is
strict on purpose: a typo in production-Quadlet env would otherwise
silently fall back to ``python`` and operators would miss the Rust-
default flip. Operators MUST opt out by writing ``python`` explicitly
if they want the Python path; an unset env-var defaults to ``python``
but a misspelled non-empty value is a hard error.

Hermetic-test guarantee
-----------------------

This module is 100% hermetic-testable: subprocess calls go through a
single :func:`_invoke_rust_subprocess` seam that tests can patch with
a stub. No real NATS, no real network, no real Rust binary required
in CI.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Mapping, Optional, TextIO

from .lifecycle_state_machine import (
    STATES as FSM_PY_STATES,
    VALID_TRANSITIONS as FSM_PY_VALID_TRANSITIONS,
    LifecycleStateMachine,
    TransitionRecord,
)
from .recovery_workflow import (
    RecoveryResult,
    RecoveryTrigger,
    RecoveryWorkflow,
)
from .state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateBacking,
    PersonaStateBackingError,
    PersonaStateSnapshot,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env-var contract.
# ---------------------------------------------------------------------------


RECOVERY_BACKEND_ENV = "WAKIR_RECOVERY_BACKEND"
STATE_BACKING_BACKEND_ENV = "WAKIR_STATE_BACKING_BACKEND"
FSM_BACKEND_ENV = "WAKIR_FSM_BACKEND"
V907_VERIFY_BACKEND_ENV = "WAKIR_V907_VERIFY_BACKEND"
BRIDGE_DIFF_BACKEND_ENV = "WAKIR_BRIDGE_DIFF_BACKEND"
RUST_RECOVERY_BIN_ENV = "WAKIR_RUST_RECOVERY_BIN"
RUST_STATE_BACKING_BIN_ENV = "WAKIR_RUST_STATE_BACKING_BIN"
RUST_FSM_BIN_ENV = "WAKIR_RUST_FSM_BIN"
RUST_V907_VERIFY_BIN_ENV = "WAKIR_RUST_V907_VERIFY_BIN"
RUST_BRIDGE_DIFF_BIN_ENV = "WAKIR_RUST_BRIDGE_DIFF_BIN"
RUST_BACKEND_TIMEOUT_ENV = "WAKIR_RUST_BACKEND_TIMEOUT_S"

DEFAULT_RUST_RECOVERY_BIN = "/opt/wakir/bin/wakir-persona-engine-recovery"
DEFAULT_RUST_STATE_BACKING_BIN = (
    "/opt/wakir/bin/wakir-persona-engine-state-backing"
)
DEFAULT_RUST_FSM_BIN = "/opt/wakir/bin/wakir-persona-engine-fsm"
DEFAULT_RUST_V907_VERIFY_BIN = "/opt/wakir/bin/wakir-persona-engine-v907-verify"
DEFAULT_RUST_BRIDGE_DIFF_BIN = "/opt/wakir/bin/wakir-persona-engine-bridge-diff"
DEFAULT_RUST_BACKEND_TIMEOUT_S = 5.0


class RecoveryBackend(str, Enum):
    """Closed enum of valid ``WAKIR_RECOVERY_BACKEND`` values."""

    PYTHON = "python"
    RUST = "rust"


class StateBackingBackend(str, Enum):
    """Closed enum of valid ``WAKIR_STATE_BACKING_BACKEND`` values."""

    PYTHON = "python"
    RUST_INMEMORY = "rust_inmemory"
    RUST_NATSKV = "rust_natskv"


class FsmBackend(str, Enum):
    """Closed enum of valid ``WAKIR_FSM_BACKEND`` values.

    Schema-byte-parity anchor: the Python authority is
    :mod:`wirelang.persona_engine.lifecycle_state_machine`
    (six states, nine transitions per spec §3.3). The Rust pendant
    is the ``persona-engine-fsm`` crate (PR #137, wire-string parity).
    """

    PYTHON = "python"
    RUST = "rust"


class V907VerifyBackend(str, Enum):
    """Closed enum of valid ``WAKIR_V907_VERIFY_BACKEND`` values.

    Hash-determinism anchor: the Python authority is
    :mod:`wirelang.persona_engine.v907_verify` (spec §5). The Rust
    pendant is the ``persona-engine-v907-verify`` crate (PR #136,
    byte-identical hash output verified against all pin-pack vectors).
    """

    PYTHON = "python"
    RUST = "rust"


class BridgeDiffBackend(str, Enum):
    """Closed enum of valid ``WAKIR_BRIDGE_DIFF_BACKEND`` values.

    Doppelbetrieb-oracle anchor: the Python authority is
    :mod:`wirelang.persona_engine.bridge_audit_diff_engine` (PR #106,
    JCS + SHA-256 + RFC-6901 field-paths). The Rust pendant is the
    ``persona-engine-bridge-diff`` crate (PR #131, byte-identical
    hash output AND byte-identical RFC-6901 field-path entries
    verified against all six cross-lang field-pin vectors per
    ``cross_lang_field_diff_fixtures.json`` / PR #166).
    """

    PYTHON = "python"
    RUST = "rust"


VALID_RECOVERY_BACKEND_VALUES = tuple(b.value for b in RecoveryBackend)
VALID_STATE_BACKING_BACKEND_VALUES = tuple(
    b.value for b in StateBackingBackend
)
VALID_FSM_BACKEND_VALUES = tuple(b.value for b in FsmBackend)
VALID_V907_VERIFY_BACKEND_VALUES = tuple(b.value for b in V907VerifyBackend)
VALID_BRIDGE_DIFF_BACKEND_VALUES = tuple(b.value for b in BridgeDiffBackend)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class BackendSwitchValidationError(ValueError):
    """Raised when an env-var carries an unknown backend label.

    Carries the env-var name, the offending value, and the closed set
    of valid values for operator-facing error reporting.
    """

    def __init__(
        self, env_var: str, value: str, valid_values: tuple
    ) -> None:
        self.env_var = env_var
        self.value = value
        self.valid_values = valid_values
        super().__init__(
            f"{env_var}={value!r} is not a valid backend label; "
            f"expected one of {list(valid_values)}"
        )


@dataclass(frozen=True)
class RustBackendError(Exception):
    """Structured error for Rust-backend subprocess failures.

    Mirrors :class:`wirelang.persona_engine.rust_adapter_hook.
    RustAdapterError` shape so the bridge-audit writer can dispatch
    on ``reason`` across both surfaces.
    """

    reason: str
    bin_path: str
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"RustBackendError(reason={self.reason!r} "
            f"bin={self.bin_path!r} rc={self.returncode!r})"
        )


# ---------------------------------------------------------------------------
# Per-decision logging.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendDecision:
    """One backend-selection event for per-decision logging.

    Fields
    ------
    domain
        ``"recovery"`` or ``"state_backing"``.
    requested_backend
        The env-var value the operator asked for, after normalisation
        (``rust`` / ``python`` / ``rust_inmemory`` / ``rust_natskv``).
    chosen_backend
        What the switch actually selected. Differs from
        ``requested_backend`` only when the Rust binary was missing
        and the switch gracefully fell back to Python.
    resolution_latency_us
        Wall-clock microseconds spent inside the
        :func:`resolve_recovery_backend` /
        :func:`resolve_state_backing_backend` call.
    fallback_reason
        Short token explaining why ``chosen_backend`` differs from
        ``requested_backend``. ``None`` when no fallback happened.
        Tokens: ``"binary_missing"`` / ``"binary_not_executable"`` /
        ``"explicit_python"``.
    bin_path
        Resolved Rust-binary path consulted during the decision.
        ``None`` for python-only decisions.
    """

    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


def log_backend_decision(
    decision: BackendDecision,
    *,
    log_sink: Optional[TextIO] = None,
) -> None:
    """Emit a structured ``backend-decision`` log record.

    Writes to the python ``logging`` module at INFO level AND, when a
    structured ``log_sink`` is provided, to that sink as a single
    JSON line. The engine orchestrator passes its existing log_sink so
    the audit substrate already in use stays populated.
    """
    record = {
        "level": "INFO",
        "msg": "backend-decision",
        "domain": decision.domain,
        "requested_backend": decision.requested_backend,
        "chosen_backend": decision.chosen_backend,
        "resolution_latency_us": decision.resolution_latency_us,
        "fallback_reason": decision.fallback_reason,
        "bin_path": decision.bin_path,
    }
    log.info(
        "backend-decision domain=%s requested=%s chosen=%s "
        "latency_us=%d fallback_reason=%s bin=%s",
        decision.domain,
        decision.requested_backend,
        decision.chosen_backend,
        decision.resolution_latency_us,
        decision.fallback_reason,
        decision.bin_path,
    )
    if log_sink is not None:
        log_sink.write(json.dumps(record, sort_keys=True) + "\n")
        log_sink.flush()


# ---------------------------------------------------------------------------
# Env-var resolution helpers.
# ---------------------------------------------------------------------------


def _env_get(
    key: str, env: Optional[Mapping[str, str]] = None
) -> Optional[str]:
    if env is None:
        env = os.environ
    return env.get(key)


def _resolve_timeout_s(
    env: Optional[Mapping[str, str]] = None,
) -> float:
    """Resolve the Rust-backend subprocess timeout.

    Negative / zero / unparseable values fall back to the default
    with a warning — mirror of :mod:`rust_adapter_hook` posture.
    """
    raw = _env_get(RUST_BACKEND_TIMEOUT_ENV, env)
    if raw is None:
        return DEFAULT_RUST_BACKEND_TIMEOUT_S
    try:
        parsed = float(raw)
    except ValueError:
        log.warning(
            "rust_backend_switch %s=%r unparseable; "
            "falling back to default %ss",
            RUST_BACKEND_TIMEOUT_ENV,
            raw,
            DEFAULT_RUST_BACKEND_TIMEOUT_S,
        )
        return DEFAULT_RUST_BACKEND_TIMEOUT_S
    if parsed <= 0:
        log.warning(
            "rust_backend_switch %s=%r non-positive; "
            "falling back to default %ss",
            RUST_BACKEND_TIMEOUT_ENV,
            raw,
            DEFAULT_RUST_BACKEND_TIMEOUT_S,
        )
        return DEFAULT_RUST_BACKEND_TIMEOUT_S
    return parsed


def _resolve_recovery_bin(
    env: Optional[Mapping[str, str]] = None,
) -> str:
    explicit = _env_get(RUST_RECOVERY_BIN_ENV, env)
    return explicit if explicit else DEFAULT_RUST_RECOVERY_BIN


def _resolve_state_backing_bin(
    env: Optional[Mapping[str, str]] = None,
) -> str:
    explicit = _env_get(RUST_STATE_BACKING_BIN_ENV, env)
    return explicit if explicit else DEFAULT_RUST_STATE_BACKING_BIN


def _resolve_fsm_bin(
    env: Optional[Mapping[str, str]] = None,
) -> str:
    explicit = _env_get(RUST_FSM_BIN_ENV, env)
    return explicit if explicit else DEFAULT_RUST_FSM_BIN


def _resolve_v907_verify_bin(
    env: Optional[Mapping[str, str]] = None,
) -> str:
    explicit = _env_get(RUST_V907_VERIFY_BIN_ENV, env)
    return explicit if explicit else DEFAULT_RUST_V907_VERIFY_BIN


def _resolve_bridge_diff_bin(
    env: Optional[Mapping[str, str]] = None,
) -> str:
    explicit = _env_get(RUST_BRIDGE_DIFF_BIN_ENV, env)
    return explicit if explicit else DEFAULT_RUST_BRIDGE_DIFF_BIN


def _binary_available(bin_path: str) -> tuple[bool, Optional[str]]:
    """Return ``(available, fallback_reason)``.

    Mirrors :meth:`SubprocessRustAdapterHook.available` semantics:
    path must exist, be a regular file, and have the execute bit set
    for the calling user. Returns a fallback_reason token for the
    per-decision log when ``available == False``.
    """
    if not bin_path:
        return False, "binary_missing"
    path = bin_path
    if not os.path.isabs(path):
        resolved = shutil.which(path)
        if resolved is None:
            return False, "binary_missing"
        path = resolved
    if not os.path.isfile(path):
        return False, "binary_missing"
    if not os.access(path, os.X_OK):
        return False, "binary_not_executable"
    return True, None


# ---------------------------------------------------------------------------
# Validation: closed-enum check.
# ---------------------------------------------------------------------------


def _validate_recovery_backend(value: Optional[str]) -> RecoveryBackend:
    """Validate a ``WAKIR_RECOVERY_BACKEND`` value (or ``None``).

    Empty / missing values default to ``RecoveryBackend.PYTHON``.
    Non-empty unknown values raise :class:`BackendSwitchValidationError`.
    """
    if value is None or value == "":
        return RecoveryBackend.PYTHON
    if value not in VALID_RECOVERY_BACKEND_VALUES:
        raise BackendSwitchValidationError(
            RECOVERY_BACKEND_ENV, value, VALID_RECOVERY_BACKEND_VALUES
        )
    return RecoveryBackend(value)


def _validate_state_backing_backend(
    value: Optional[str],
) -> StateBackingBackend:
    """Validate a ``WAKIR_STATE_BACKING_BACKEND`` value (or ``None``).

    Empty / missing values default to ``StateBackingBackend.PYTHON``.
    Non-empty unknown values raise :class:`BackendSwitchValidationError`.
    """
    if value is None or value == "":
        return StateBackingBackend.PYTHON
    if value not in VALID_STATE_BACKING_BACKEND_VALUES:
        raise BackendSwitchValidationError(
            STATE_BACKING_BACKEND_ENV,
            value,
            VALID_STATE_BACKING_BACKEND_VALUES,
        )
    return StateBackingBackend(value)


def _validate_fsm_backend(value: Optional[str]) -> FsmBackend:
    """Validate a ``WAKIR_FSM_BACKEND`` value (or ``None``).

    Empty / missing values default to ``FsmBackend.PYTHON``.
    Non-empty unknown values raise :class:`BackendSwitchValidationError`.
    """
    if value is None or value == "":
        return FsmBackend.PYTHON
    if value not in VALID_FSM_BACKEND_VALUES:
        raise BackendSwitchValidationError(
            FSM_BACKEND_ENV, value, VALID_FSM_BACKEND_VALUES
        )
    return FsmBackend(value)


def _validate_v907_verify_backend(
    value: Optional[str],
) -> V907VerifyBackend:
    """Validate a ``WAKIR_V907_VERIFY_BACKEND`` value (or ``None``).

    Empty / missing values default to ``V907VerifyBackend.PYTHON``.
    Non-empty unknown values raise :class:`BackendSwitchValidationError`.
    """
    if value is None or value == "":
        return V907VerifyBackend.PYTHON
    if value not in VALID_V907_VERIFY_BACKEND_VALUES:
        raise BackendSwitchValidationError(
            V907_VERIFY_BACKEND_ENV,
            value,
            VALID_V907_VERIFY_BACKEND_VALUES,
        )
    return V907VerifyBackend(value)


def _validate_bridge_diff_backend(
    value: Optional[str],
) -> BridgeDiffBackend:
    """Validate a ``WAKIR_BRIDGE_DIFF_BACKEND`` value (or ``None``).

    Empty / missing values default to ``BridgeDiffBackend.PYTHON``.
    Non-empty unknown values raise :class:`BackendSwitchValidationError`.
    """
    if value is None or value == "":
        return BridgeDiffBackend.PYTHON
    if value not in VALID_BRIDGE_DIFF_BACKEND_VALUES:
        raise BackendSwitchValidationError(
            BRIDGE_DIFF_BACKEND_ENV,
            value,
            VALID_BRIDGE_DIFF_BACKEND_VALUES,
        )
    return BridgeDiffBackend(value)


# ---------------------------------------------------------------------------
# Public resolution entry points.
# ---------------------------------------------------------------------------


def resolve_recovery_backend(
    env: Optional[Mapping[str, str]] = None,
    *,
    log_sink: Optional[TextIO] = None,
    binary_probe: Optional[Callable[[str], tuple[bool, Optional[str]]]] = None,
) -> tuple[RecoveryBackend, BackendDecision]:
    """Resolve the recovery backend per env-var + binary availability.

    Returns a ``(chosen_backend, decision)`` tuple. The decision
    object is also logged via :func:`log_backend_decision`.

    Parameters
    ----------
    env
        Env-var mapping; defaults to :data:`os.environ`.
    log_sink
        Optional structured-log sink. If provided, the decision is
        also written as a single JSON line.
    binary_probe
        Test-injection seam. Defaults to :func:`_binary_available`.

    Raises
    ------
    BackendSwitchValidationError
        On unknown env-var values.
    """
    start = time.perf_counter()
    raw_value = _env_get(RECOVERY_BACKEND_ENV, env)
    requested = _validate_recovery_backend(raw_value)

    if requested is RecoveryBackend.PYTHON:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="recovery",
            requested_backend=requested.value,
            chosen_backend=RecoveryBackend.PYTHON.value,
            resolution_latency_us=latency_us,
            fallback_reason=(
                "explicit_python" if raw_value == "python" else None
            ),
            bin_path=None,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return RecoveryBackend.PYTHON, decision

    # Requested == RUST.
    bin_path = _resolve_recovery_bin(env)
    probe = binary_probe or _binary_available
    available, fallback_reason = probe(bin_path)
    if available:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="recovery",
            requested_backend=requested.value,
            chosen_backend=RecoveryBackend.RUST.value,
            resolution_latency_us=latency_us,
            fallback_reason=None,
            bin_path=bin_path,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return RecoveryBackend.RUST, decision

    # Graceful fallback to Python.
    latency_us = int((time.perf_counter() - start) * 1_000_000)
    decision = BackendDecision(
        domain="recovery",
        requested_backend=requested.value,
        chosen_backend=RecoveryBackend.PYTHON.value,
        resolution_latency_us=latency_us,
        fallback_reason=fallback_reason,
        bin_path=bin_path,
    )
    log_backend_decision(decision, log_sink=log_sink)
    log.warning(
        "rust_backend_switch recovery requested=rust but binary "
        "unavailable (%s @ %s); falling back to python",
        fallback_reason,
        bin_path,
    )
    return RecoveryBackend.PYTHON, decision


def resolve_state_backing_backend(
    env: Optional[Mapping[str, str]] = None,
    *,
    log_sink: Optional[TextIO] = None,
    binary_probe: Optional[Callable[[str], tuple[bool, Optional[str]]]] = None,
) -> tuple[StateBackingBackend, BackendDecision]:
    """Resolve the state-backing backend per env-var + binary availability.

    Returns a ``(chosen_backend, decision)`` tuple. The decision
    object is also logged via :func:`log_backend_decision`.

    Same posture as :func:`resolve_recovery_backend`.

    Raises
    ------
    BackendSwitchValidationError
        On unknown env-var values.
    """
    start = time.perf_counter()
    raw_value = _env_get(STATE_BACKING_BACKEND_ENV, env)
    requested = _validate_state_backing_backend(raw_value)

    if requested is StateBackingBackend.PYTHON:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="state_backing",
            requested_backend=requested.value,
            chosen_backend=StateBackingBackend.PYTHON.value,
            resolution_latency_us=latency_us,
            fallback_reason=(
                "explicit_python" if raw_value == "python" else None
            ),
            bin_path=None,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return StateBackingBackend.PYTHON, decision

    # Requested == RUST_INMEMORY or RUST_NATSKV.
    bin_path = _resolve_state_backing_bin(env)
    probe = binary_probe or _binary_available
    available, fallback_reason = probe(bin_path)
    if available:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="state_backing",
            requested_backend=requested.value,
            chosen_backend=requested.value,
            resolution_latency_us=latency_us,
            fallback_reason=None,
            bin_path=bin_path,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return requested, decision

    # Graceful fallback to Python.
    latency_us = int((time.perf_counter() - start) * 1_000_000)
    decision = BackendDecision(
        domain="state_backing",
        requested_backend=requested.value,
        chosen_backend=StateBackingBackend.PYTHON.value,
        resolution_latency_us=latency_us,
        fallback_reason=fallback_reason,
        bin_path=bin_path,
    )
    log_backend_decision(decision, log_sink=log_sink)
    log.warning(
        "rust_backend_switch state_backing requested=%s but binary "
        "unavailable (%s @ %s); falling back to python",
        requested.value,
        fallback_reason,
        bin_path,
    )
    return StateBackingBackend.PYTHON, decision


def resolve_fsm_backend(
    env: Optional[Mapping[str, str]] = None,
    *,
    log_sink: Optional[TextIO] = None,
    binary_probe: Optional[Callable[[str], tuple[bool, Optional[str]]]] = None,
) -> tuple[FsmBackend, BackendDecision]:
    """Resolve the FSM backend per env-var + binary availability.

    Tag-18 Mini-Welle — 3rd production-default switch component
    (parallel to :func:`resolve_recovery_backend` and
    :func:`resolve_state_backing_backend`). The Python authority is
    :mod:`wirelang.persona_engine.lifecycle_state_machine` (six states,
    nine transitions per spec §3.3). The Rust pendant is the
    ``persona-engine-fsm`` crate (PR #137, schema-byte-parity).

    Returns a ``(chosen_backend, decision)`` tuple. The decision
    object is also logged via :func:`log_backend_decision`.

    Same posture as :func:`resolve_recovery_backend`: default is
    Python, ``rust`` requested + binary missing falls back to Python
    with a structured-log warning.

    Parameters
    ----------
    env
        Env-var mapping; defaults to :data:`os.environ`.
    log_sink
        Optional structured-log sink. If provided, the decision is
        also written as a single JSON line.
    binary_probe
        Test-injection seam. Defaults to :func:`_binary_available`.

    Raises
    ------
    BackendSwitchValidationError
        On unknown env-var values.
    """
    start = time.perf_counter()
    raw_value = _env_get(FSM_BACKEND_ENV, env)
    requested = _validate_fsm_backend(raw_value)

    if requested is FsmBackend.PYTHON:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="fsm",
            requested_backend=requested.value,
            chosen_backend=FsmBackend.PYTHON.value,
            resolution_latency_us=latency_us,
            fallback_reason=(
                "explicit_python" if raw_value == "python" else None
            ),
            bin_path=None,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return FsmBackend.PYTHON, decision

    # Requested == RUST.
    bin_path = _resolve_fsm_bin(env)
    probe = binary_probe or _binary_available
    available, fallback_reason = probe(bin_path)
    if available:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="fsm",
            requested_backend=requested.value,
            chosen_backend=FsmBackend.RUST.value,
            resolution_latency_us=latency_us,
            fallback_reason=None,
            bin_path=bin_path,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return FsmBackend.RUST, decision

    # Graceful fallback to Python.
    latency_us = int((time.perf_counter() - start) * 1_000_000)
    decision = BackendDecision(
        domain="fsm",
        requested_backend=requested.value,
        chosen_backend=FsmBackend.PYTHON.value,
        resolution_latency_us=latency_us,
        fallback_reason=fallback_reason,
        bin_path=bin_path,
    )
    log_backend_decision(decision, log_sink=log_sink)
    log.warning(
        "rust_backend_switch fsm requested=rust but binary "
        "unavailable (%s @ %s); falling back to python",
        fallback_reason,
        bin_path,
    )
    return FsmBackend.PYTHON, decision


def resolve_v907_verify_backend(
    env: Optional[Mapping[str, str]] = None,
    *,
    log_sink: Optional[TextIO] = None,
    binary_probe: Optional[Callable[[str], tuple[bool, Optional[str]]]] = None,
) -> tuple[V907VerifyBackend, BackendDecision]:
    """Resolve the V907-verify backend per env-var + binary availability.

    Tag-19 Mini-Welle — 4th production-default switch component
    (parallel to :func:`resolve_recovery_backend`,
    :func:`resolve_state_backing_backend`, and
    :func:`resolve_fsm_backend`). The Python authority is
    :mod:`wirelang.persona_engine.v907_verify` (spec §5 hash-
    determinism anchor). The Rust pendant is the
    ``persona-engine-v907-verify`` crate (PR #136, byte-identical
    hash output verified against all pin-pack vectors).

    Returns a ``(chosen_backend, decision)`` tuple. The decision
    object is also logged via :func:`log_backend_decision`.

    Same posture as :func:`resolve_recovery_backend`: default is
    Python, ``rust`` requested + binary missing falls back to Python
    with a structured-log warning. Critical anchor: V-907 is the
    hash-determinism gate, so the per-decision audit-record is
    essential for the Phase-3b Doppelbetrieb comparison set.

    Parameters
    ----------
    env
        Env-var mapping; defaults to :data:`os.environ`.
    log_sink
        Optional structured-log sink. If provided, the decision is
        also written as a single JSON line.
    binary_probe
        Test-injection seam. Defaults to :func:`_binary_available`.

    Raises
    ------
    BackendSwitchValidationError
        On unknown env-var values.
    """
    start = time.perf_counter()
    raw_value = _env_get(V907_VERIFY_BACKEND_ENV, env)
    requested = _validate_v907_verify_backend(raw_value)

    if requested is V907VerifyBackend.PYTHON:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="v907_verify",
            requested_backend=requested.value,
            chosen_backend=V907VerifyBackend.PYTHON.value,
            resolution_latency_us=latency_us,
            fallback_reason=(
                "explicit_python" if raw_value == "python" else None
            ),
            bin_path=None,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return V907VerifyBackend.PYTHON, decision

    # Requested == RUST.
    bin_path = _resolve_v907_verify_bin(env)
    probe = binary_probe or _binary_available
    available, fallback_reason = probe(bin_path)
    if available:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="v907_verify",
            requested_backend=requested.value,
            chosen_backend=V907VerifyBackend.RUST.value,
            resolution_latency_us=latency_us,
            fallback_reason=None,
            bin_path=bin_path,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return V907VerifyBackend.RUST, decision

    # Graceful fallback to Python.
    latency_us = int((time.perf_counter() - start) * 1_000_000)
    decision = BackendDecision(
        domain="v907_verify",
        requested_backend=requested.value,
        chosen_backend=V907VerifyBackend.PYTHON.value,
        resolution_latency_us=latency_us,
        fallback_reason=fallback_reason,
        bin_path=bin_path,
    )
    log_backend_decision(decision, log_sink=log_sink)
    log.warning(
        "rust_backend_switch v907_verify requested=rust but binary "
        "unavailable (%s @ %s); falling back to python",
        fallback_reason,
        bin_path,
    )
    return V907VerifyBackend.PYTHON, decision


def resolve_bridge_diff_backend(
    env: Optional[Mapping[str, str]] = None,
    *,
    log_sink: Optional[TextIO] = None,
    binary_probe: Optional[Callable[[str], tuple[bool, Optional[str]]]] = None,
) -> tuple[BridgeDiffBackend, BackendDecision]:
    """Resolve the bridge-diff backend per env-var + binary availability.

    Tag-20 Mini-Welle — 5th production-default switch component
    (parallel to :func:`resolve_recovery_backend`,
    :func:`resolve_state_backing_backend`,
    :func:`resolve_fsm_backend`, and
    :func:`resolve_v907_verify_backend`). The Python authority is
    :mod:`wirelang.persona_engine.bridge_audit_diff_engine` (PR #106,
    Doppelbetrieb comparison oracle: JCS + SHA-256 + RFC-6901 field-
    paths). The Rust pendant is the ``persona-engine-bridge-diff``
    crate (PR #131, byte-identical hash output AND byte-identical
    RFC-6901 field-path entries verified against all six cross-lang
    field-pin vectors).

    Returns a ``(chosen_backend, decision)`` tuple. The decision
    object is also logged via :func:`log_backend_decision`.

    Same posture as :func:`resolve_recovery_backend`: default is
    Python, ``rust`` requested + binary missing falls back to Python
    with a structured-log warning. Critical anchor: bridge-diff is
    the Doppelbetrieb oracle (Phase-3a/3b cross-lang parity gate) —
    the per-decision audit-record is essential for the Phase-3b
    comparison set, because any silent drift between Python and Rust
    diff outputs would corrupt the entire Doppelbetrieb truth claim.

    Parameters
    ----------
    env
        Env-var mapping; defaults to :data:`os.environ`.
    log_sink
        Optional structured-log sink. If provided, the decision is
        also written as a single JSON line.
    binary_probe
        Test-injection seam. Defaults to :func:`_binary_available`.

    Raises
    ------
    BackendSwitchValidationError
        On unknown env-var values.
    """
    start = time.perf_counter()
    raw_value = _env_get(BRIDGE_DIFF_BACKEND_ENV, env)
    requested = _validate_bridge_diff_backend(raw_value)

    if requested is BridgeDiffBackend.PYTHON:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="bridge_diff",
            requested_backend=requested.value,
            chosen_backend=BridgeDiffBackend.PYTHON.value,
            resolution_latency_us=latency_us,
            fallback_reason=(
                "explicit_python" if raw_value == "python" else None
            ),
            bin_path=None,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return BridgeDiffBackend.PYTHON, decision

    # Requested == RUST.
    bin_path = _resolve_bridge_diff_bin(env)
    probe = binary_probe or _binary_available
    available, fallback_reason = probe(bin_path)
    if available:
        latency_us = int((time.perf_counter() - start) * 1_000_000)
        decision = BackendDecision(
            domain="bridge_diff",
            requested_backend=requested.value,
            chosen_backend=BridgeDiffBackend.RUST.value,
            resolution_latency_us=latency_us,
            fallback_reason=None,
            bin_path=bin_path,
        )
        log_backend_decision(decision, log_sink=log_sink)
        return BridgeDiffBackend.RUST, decision

    # Graceful fallback to Python.
    latency_us = int((time.perf_counter() - start) * 1_000_000)
    decision = BackendDecision(
        domain="bridge_diff",
        requested_backend=requested.value,
        chosen_backend=BridgeDiffBackend.PYTHON.value,
        resolution_latency_us=latency_us,
        fallback_reason=fallback_reason,
        bin_path=bin_path,
    )
    log_backend_decision(decision, log_sink=log_sink)
    log.warning(
        "rust_backend_switch bridge_diff requested=rust but binary "
        "unavailable (%s @ %s); falling back to python",
        fallback_reason,
        bin_path,
    )
    return BridgeDiffBackend.PYTHON, decision


# ---------------------------------------------------------------------------
# Subprocess invocation seam.
# ---------------------------------------------------------------------------


def _invoke_rust_subprocess(
    bin_path: str,
    argv: List[str],
    *,
    stdin_payload: bytes,
    timeout_s: float,
) -> tuple[int, str, str]:
    """Invoke a Rust-backend binary with JSON-stdin transport.

    Returns ``(returncode, stdout_str, stderr_str)``. The caller is
    responsible for interpreting the exit code and parsing the
    stdout. This seam exists so tests can patch the subprocess layer
    without intercepting :mod:`subprocess` globally.

    Raises
    ------
    RustBackendError
        On subprocess.TimeoutExpired / OSError. Caller-facing
        contract mirrors :mod:`rust_adapter_hook`.
    """
    try:
        proc = subprocess.run(
            [bin_path, *argv],
            input=stdin_payload,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RustBackendError(
            reason="timeout",
            bin_path=bin_path,
            stdout=(exc.stdout or b"").decode("utf-8", errors="replace"),
            stderr=(exc.stderr or b"").decode("utf-8", errors="replace"),
        ) from exc
    except (OSError, ValueError) as exc:
        raise RustBackendError(
            reason="spawn_failed",
            bin_path=bin_path,
            stderr=str(exc),
        ) from exc
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


# ---------------------------------------------------------------------------
# Subprocess-bridge: state-backing snapshot / restore.
# ---------------------------------------------------------------------------


class RustSubprocessStateBacking(PersonaStateBacking):
    """Subprocess-bridge state-backing.

    Delegates ``snapshot`` / ``restore_latest`` / ``list_snapshots`` /
    ``atomic_swap_pinned_offset`` to a Rust-CLI subprocess. JSON-stdin
    carries the operation kind + arguments; JSON-stdout carries the
    response. The Rust binary is responsible for the actual
    in-memory or NATS-KV persistence.

    This is the production-default-bound binding when
    ``WAKIR_STATE_BACKING_BACKEND=rust_inmemory|rust_natskv`` is set
    AND the binary is available. Construction is cheap; per-call
    overhead is one subprocess spawn (acceptable for Phase-3b
    snapshot frequency).
    """

    def __init__(
        self,
        *,
        bin_path: Optional[str] = None,
        timeout_s: Optional[float] = None,
        kind: str = "rust_inmemory",
        env: Optional[Mapping[str, str]] = None,
        subprocess_invoker: Optional[Callable] = None,
    ) -> None:
        self.bin_path = (
            bin_path
            if bin_path is not None
            else _resolve_state_backing_bin(env)
        )
        self.timeout_s = (
            timeout_s
            if timeout_s is not None
            else _resolve_timeout_s(env)
        )
        if kind not in ("rust_inmemory", "rust_natskv"):
            raise BackendSwitchValidationError(
                STATE_BACKING_BACKEND_ENV,
                kind,
                ("rust_inmemory", "rust_natskv"),
            )
        self.kind = kind
        self._invoker = subprocess_invoker or _invoke_rust_subprocess

    def _call(self, op: str, payload: dict) -> Any:
        stdin_doc = {
            "schema": "wakir.persona-engine.state-backing/1",
            "kind": self.kind,
            "op": op,
            "payload": payload,
        }
        stdin_bytes = json.dumps(
            stdin_doc, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        rc, stdout, stderr = self._invoker(
            self.bin_path,
            ["state-backing", "--json"],
            stdin_payload=stdin_bytes,
            timeout_s=self.timeout_s,
        )
        if rc != 0:
            raise RustBackendError(
                reason="exit_nonzero",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RustBackendError(
                reason="bad_json",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            ) from exc
        if not isinstance(parsed, dict):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        return parsed

    def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        payload = {
            "persona_id": persona_id,
            "state": {
                "persona_hash": state.persona_hash,
                "audit_trace_offset": state.audit_trace_offset,
                "capability_token_ids": list(state.capability_token_ids),
                "snapshot_at_utc": state.snapshot_at_utc,
                "workspace_state_hash": state.workspace_state_hash,
            },
        }
        resp = self._call("snapshot", payload)
        offset = resp.get("offset")
        if not isinstance(offset, int):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return offset

    def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        payload = {"persona_id": persona_id}
        resp = self._call("restore_latest", payload)
        snap = resp.get("snapshot")
        if snap is None:
            return None
        if not isinstance(snap, dict):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return PersonaStateSnapshot(
            persona_hash=snap["persona_hash"],
            audit_trace_offset=snap["audit_trace_offset"],
            capability_token_ids=tuple(snap["capability_token_ids"]),
            snapshot_at_utc=snap["snapshot_at_utc"],
            workspace_state_hash=snap["workspace_state_hash"],
        )

    def list_snapshots(self, persona_id: str) -> List[int]:
        payload = {"persona_id": persona_id}
        resp = self._call("list_snapshots", payload)
        offsets = resp.get("offsets")
        if not isinstance(offsets, list):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return [int(o) for o in offsets]

    def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
        payload = {
            "persona_id": persona_id,
            "from_offset": from_offset,
            "to_offset": to_offset,
        }
        self._call("atomic_swap_pinned_offset", payload)


# ---------------------------------------------------------------------------
# Subprocess-bridge: recovery workflow.
# ---------------------------------------------------------------------------


@dataclass
class RustSubprocessRecoveryRunner:
    """Subprocess-bridge recovery-workflow runner.

    Delegates the R1..R4 workflow to a Rust-CLI subprocess. JSON-
    stdin carries the trigger flags + persona/org IDs; JSON-stdout
    carries a :class:`RecoveryResult`-equivalent envelope.

    Construction is cheap; per-call overhead is one subprocess spawn.
    """

    bin_path: str = ""
    timeout_s: float = DEFAULT_RUST_BACKEND_TIMEOUT_S
    _invoker: Callable = field(default=_invoke_rust_subprocess)

    def __init__(
        self,
        *,
        bin_path: Optional[str] = None,
        timeout_s: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
        subprocess_invoker: Optional[Callable] = None,
    ) -> None:
        self.bin_path = (
            bin_path
            if bin_path is not None
            else _resolve_recovery_bin(env)
        )
        self.timeout_s = (
            timeout_s
            if timeout_s is not None
            else _resolve_timeout_s(env)
        )
        self._invoker = subprocess_invoker or _invoke_rust_subprocess

    def run(
        self,
        *,
        org_id: str,
        persona_id: str,
        crash_detected: bool = False,
        despawn_mid_operation: bool = False,
        state_corruption: bool = False,
        force_trigger: Optional[RecoveryTrigger] = None,
    ) -> dict:
        """Run R1..R4 via Rust subprocess.

        Returns the parsed JSON envelope as a dict. The envelope
        schema mirrors :class:`RecoveryResult` byte-for-byte; the
        caller may construct a :class:`RecoveryResult` from it via
        :func:`envelope_to_recovery_result` (omitted here to keep
        the bridge surface narrow — the engine orchestrator consumes
        the envelope directly for the per-decision audit-record).

        Raises
        ------
        RustBackendError
            On subprocess / shape failure.
        """
        stdin_doc = {
            "schema": "wakir.persona-engine.recovery/1",
            "org_id": org_id,
            "persona_id": persona_id,
            "triggers": {
                "crash_detected": crash_detected,
                "despawn_mid_operation": despawn_mid_operation,
                "state_corruption": state_corruption,
                "force_trigger": (
                    force_trigger.value if force_trigger is not None else None
                ),
            },
        }
        stdin_bytes = json.dumps(
            stdin_doc, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        rc, stdout, stderr = self._invoker(
            self.bin_path,
            ["recovery", "--json"],
            stdin_payload=stdin_bytes,
            timeout_s=self.timeout_s,
        )
        if rc != 0:
            raise RustBackendError(
                reason="exit_nonzero",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RustBackendError(
                reason="bad_json",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            ) from exc
        if not isinstance(parsed, dict):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        return parsed


# ---------------------------------------------------------------------------
# Subprocess-bridge: lifecycle FSM.
# ---------------------------------------------------------------------------


class RustSubprocessFsm:
    """Subprocess-bridge persona-engine FSM.

    Delegates ``transition_to`` / ``can_transition_to`` / ``state`` /
    ``history`` to a Rust-CLI subprocess against the
    ``persona-engine-fsm`` crate (PR #137). JSON-stdin carries the
    operation kind + arguments; JSON-stdout carries the response.

    Schema-parity contract (spec §3.3, mirror of
    :class:`wirelang.persona_engine.lifecycle_state_machine.
    LifecycleStateMachine`):

    - Six states: ``uninstantiated`` | ``spawning`` | ``running`` |
      ``despawning`` | ``recovered`` | ``migrated``.
    - Nine transitions per :data:`FSM_PY_VALID_TRANSITIONS`.
    - Every transition attempt (accepted or rejected) is recorded.
    - Invalid transitions raise :class:`InvalidTransitionError`
      (mirror of Python's lifecycle_state_machine error).

    Wire-format (state-backing-pendant style):

    Stdin JSON:
        ``{"schema": "wakir.persona-engine.fsm/1", "op": "<op>",
        "payload": {...}}``

    The Rust binary is responsible for the actual state-machine
    evaluation. The Python side keeps a local mirror of state +
    history so callers (engine, despawn_clean) see the same API
    surface as the Python ``LifecycleStateMachine`` without an extra
    subprocess call per accessor.

    Construction is cheap; per-transition overhead is one subprocess
    spawn. The local-mirror posture keeps ``state`` / ``history`` /
    ``can_transition_to`` access subprocess-free.

    Tag-18 posture
    --------------
    This binding is the *opt-in* path: ``WAKIR_FSM_BACKEND=rust`` +
    available binary. Default and missing-binary fallback stay on
    the Python authority. The engine wire-in (Tag-18) records the
    backend decision but keeps ``self.fsm`` Python-backed during
    Phase-3b Doppelbetrieb — the bridge is exercised by the tests
    and the future Phase-3c cutover.
    """

    def __init__(
        self,
        persona_id: str,
        org_id: str,
        *,
        bin_path: Optional[str] = None,
        timeout_s: Optional[float] = None,
        initial_state: str = "uninstantiated",
        env: Optional[Mapping[str, str]] = None,
        subprocess_invoker: Optional[Callable] = None,
    ) -> None:
        if initial_state not in FSM_PY_STATES:
            raise ValueError(
                f"unknown initial state {initial_state!r}; "
                f"valid: {FSM_PY_STATES}"
            )
        self.persona_id: str = persona_id
        self.org_id: str = org_id
        self.bin_path: str = (
            bin_path if bin_path is not None else _resolve_fsm_bin(env)
        )
        self.timeout_s: float = (
            timeout_s if timeout_s is not None else _resolve_timeout_s(env)
        )
        self._state: str = initial_state
        self._history: List[TransitionRecord] = []
        self._invoker: Callable = (
            subprocess_invoker or _invoke_rust_subprocess
        )

    # ------------------------------------------------------------------
    # Accessors (no subprocess hop — local mirror).
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def history(self) -> List[TransitionRecord]:
        return list(self._history)

    def can_transition_to(self, to_state: str) -> bool:
        if to_state not in FSM_PY_STATES:
            return False
        return (self._state, to_state) in FSM_PY_VALID_TRANSITIONS

    # ------------------------------------------------------------------
    # Transition surface (subprocess hop).
    # ------------------------------------------------------------------

    def _call(self, op: str, payload: dict) -> dict:
        stdin_doc = {
            "schema": "wakir.persona-engine.fsm/1",
            "op": op,
            "payload": payload,
        }
        stdin_bytes = json.dumps(
            stdin_doc, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        rc, stdout, stderr = self._invoker(
            self.bin_path,
            ["fsm", "--json"],
            stdin_payload=stdin_bytes,
            timeout_s=self.timeout_s,
        )
        if rc != 0:
            raise RustBackendError(
                reason="exit_nonzero",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RustBackendError(
                reason="bad_json",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            ) from exc
        if not isinstance(parsed, dict):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        return parsed

    def transition_to(self, to_state: str) -> TransitionRecord:
        """Attempt a transition via the Rust subprocess.

        Mirrors :meth:`LifecycleStateMachine.transition_to` semantics
        byte-for-byte: appends a TransitionRecord on every attempt,
        raises :class:`InvalidTransitionError` on a rejected edge,
        and updates the local-mirror state on success.

        The Rust binary returns an envelope ``{"accepted": bool,
        "reason": Optional[str], "from_state": str, "to_state": str,
        "ts_utc": str}``. On ``accepted=false`` with reason
        ``not_in_valid_transitions`` or ``unknown_target_state`` the
        bridge translates the response into the matching Python
        exception so callers cannot tell the backends apart.
        """
        # Import lazily — keeps the module import-light for callers
        # that never trigger an FSM transition (e.g. the schema-test
        # surface).
        from .lifecycle_state_machine import (
            InvalidTransitionError,
            UnknownStateError,
        )

        payload = {
            "persona_id": self.persona_id,
            "org_id": self.org_id,
            "from_state": self._state,
            "to_state": to_state,
        }
        resp = self._call("transition_to", payload)
        accepted = bool(resp.get("accepted", False))
        reason = resp.get("reason")
        from_state = str(resp.get("from_state", self._state))
        ts_utc = str(resp.get("ts_utc", ""))
        rec = TransitionRecord(
            from_state=from_state,
            to_state=to_state,
            ts_utc=ts_utc,
            accepted=accepted,
            reason=reason if reason else None,
        )
        self._history.append(rec)
        if not accepted:
            if reason == "unknown_target_state":
                raise UnknownStateError(
                    f"unknown target state {to_state!r}; "
                    f"valid: {FSM_PY_STATES}"
                )
            raise InvalidTransitionError(self._state, to_state)
        self._state = to_state
        return rec


# ---------------------------------------------------------------------------
# Subprocess-bridge: V-907 pin-compute + verify.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V907SubprocessResult:
    """Result envelope for the V907 subprocess-bridge.

    Mirrors :class:`wirelang.persona_engine.v907_verify.V907VerifyResult`
    byte-for-byte so callers can treat the two backends interchangeably.

    Fields
    ------
    pin
        Computed pin (``"sha256:<64hex>"``).
    mode
        ``"real"`` for this bridge (the Rust crate always produces real
        pins; the ``sha256-stub:`` prefix is a Python-only legacy from
        the 0.1.0-pilot stub binary).
    matched
        Tri-state: ``True`` / ``False`` / ``None`` (None when no
        expected pin was supplied).
    """

    pin: str
    mode: str
    matched: Optional[bool]


class RustSubprocessV907Verify:
    """Subprocess-bridge persona-engine V-907 verify.

    Delegates ``compute_v907_pin`` / ``verify_v907_pin`` to a Rust-CLI
    subprocess against the ``persona-engine-v907-verify`` crate
    (PR #136). JSON-stdin carries the operation kind + arguments;
    JSON-stdout carries the response.

    Schema-byte-parity contract (spec §5, mirror of
    :mod:`wirelang.persona_engine.v907_verify`):

    - Pin format: ``"sha256:<64hex>"`` (32-byte JCS-SHA-256 over the
      engine-side canonical subset).
    - Canonical subset shape: ``{schema_version, identity_pinned?,
      capabilities?, domain?, reports_to?}`` (lenient — engine-side
      ``.claude/agents/*.md`` axis-A, NOT the strict
      ``persona-canonical-form-yaml`` nine-vector shape).
    - Drift behaviour: when an expected pin is supplied AND the
      computed pin disagrees, the bridge raises
      :class:`wirelang.persona_engine.v907_verify.PersonaHashDriftError`
      — byte-identical to the Python authority's behaviour.

    Wire-format:

    Stdin JSON:
        ``{"schema": "wakir.persona-engine.v907-verify/1",
        "op": "<op>", "payload": {...}}``

    Operations:

    - ``compute_pin`` — input ``{axis_a_bytes_b64: str}``;
      response ``{pin: "sha256:..."}``.
    - ``verify_pin`` — input ``{persona_id: str, axis_a_bytes_b64: str,
      expected_pin: Optional[str]}``; response ``{pin: str,
      mode: "real", matched: bool|null}``. On drift the binary exits
      non-zero AND sets ``response.drift = true`` with
      ``computed`` and ``expected`` fields for the bridge to
      surface as :class:`PersonaHashDriftError`.

    Construction is cheap; per-call overhead is one subprocess spawn.

    Tag-19 posture
    --------------
    This binding is the *opt-in* path: ``WAKIR_V907_VERIFY_BACKEND=rust``
    + available binary. Default and missing-binary fallback stay on
    the Python authority. The engine wire-in (Tag-19) records the
    backend decision but keeps ``self.v907_result`` Python-backed
    during Phase-3b Doppelbetrieb — the bridge is exercised by the
    tests and the future Phase-3c cutover (Zone-K coordination with
    Tomás for the binary-hash-pinning step).
    """

    def __init__(
        self,
        *,
        bin_path: Optional[str] = None,
        timeout_s: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
        subprocess_invoker: Optional[Callable] = None,
    ) -> None:
        self.bin_path: str = (
            bin_path if bin_path is not None
            else _resolve_v907_verify_bin(env)
        )
        self.timeout_s: float = (
            timeout_s if timeout_s is not None
            else _resolve_timeout_s(env)
        )
        self._invoker: Callable = (
            subprocess_invoker or _invoke_rust_subprocess
        )

    def _call(self, op: str, payload: dict) -> dict:
        stdin_doc = {
            "schema": "wakir.persona-engine.v907-verify/1",
            "op": op,
            "payload": payload,
        }
        stdin_bytes = json.dumps(
            stdin_doc, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        rc, stdout, stderr = self._invoker(
            self.bin_path,
            ["v907-verify", "--json"],
            stdin_payload=stdin_bytes,
            timeout_s=self.timeout_s,
        )
        # Drift envelope is conveyed via a Python-side translation:
        # the Rust binary exits non-zero on drift AND emits a JSON
        # body with drift=true. Parse stdout first so we can surface
        # the drift cleanly before raising RustBackendError for
        # actual subprocess failures.
        parsed: Optional[dict] = None
        if stdout:
            try:
                maybe = json.loads(stdout)
                if isinstance(maybe, dict):
                    parsed = maybe
            except json.JSONDecodeError:
                parsed = None
        if rc != 0:
            # Drift case: non-zero exit + drift=True in the JSON body.
            if parsed is not None and parsed.get("drift") is True:
                from .v907_verify import PersonaHashDriftError

                raise PersonaHashDriftError(
                    expected=str(parsed.get("expected", "")),
                    computed=str(parsed.get("computed", "")),
                    persona_id=str(parsed.get("persona_id", "")),
                )
            raise RustBackendError(
                reason="exit_nonzero",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        if parsed is None:
            raise RustBackendError(
                reason="bad_json",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        return parsed

    def compute_pin(self, axis_a_bytes: bytes) -> str:
        """Compute the V-907 pin via the Rust subprocess.

        Returns the byte-identical pin string (``"sha256:<64hex>"``)
        that the Python authority would produce for the same input.

        Raises
        ------
        RustBackendError
            On subprocess / shape failure.
        PersonaHashComputeError
            When the Rust binary signals a compute-stage failure
            (parse error, malformed YAML, etc.) — surfaced by
            mapping the binary's ``compute_error`` reason to the
            Python-side exception.
        """
        import base64

        payload = {
            "axis_a_bytes_b64": base64.b64encode(axis_a_bytes).decode(
                "ascii"
            ),
        }
        resp = self._call("compute_pin", payload)
        # Compute-error envelope (binary exit 0 but compute_error=true).
        if resp.get("compute_error") is True:
            from .v907_verify import PersonaHashComputeError

            raise PersonaHashComputeError(
                str(resp.get("detail", "rust-side compute_error"))
            )
        pin = resp.get("pin")
        if not isinstance(pin, str) or not pin.startswith("sha256:"):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return pin

    def verify_pin(
        self,
        *,
        persona_id: str,
        axis_a_bytes: bytes,
        expected_pin: Optional[str],
    ) -> V907SubprocessResult:
        """Compute + optionally verify the V-907 pin via subprocess.

        Mirrors
        :func:`wirelang.persona_engine.v907_verify.verify_v907_pin`
        semantics byte-for-byte: ``expected_pin=None`` or empty/
        whitespace returns ``matched=None``; a non-empty mismatch
        raises
        :class:`wirelang.persona_engine.v907_verify.PersonaHashDriftError`.

        Raises
        ------
        PersonaHashDriftError
            When ``expected_pin`` was supplied and the computed pin
            disagrees.
        PersonaHashComputeError
            On Rust-side compute-stage failure.
        RustBackendError
            On subprocess / shape failure.
        """
        import base64

        payload = {
            "persona_id": persona_id,
            "axis_a_bytes_b64": base64.b64encode(axis_a_bytes).decode(
                "ascii"
            ),
            "expected_pin": expected_pin,
        }
        resp = self._call("verify_pin", payload)
        if resp.get("compute_error") is True:
            from .v907_verify import PersonaHashComputeError

            raise PersonaHashComputeError(
                str(resp.get("detail", "rust-side compute_error"))
            )
        pin = resp.get("pin")
        mode = resp.get("mode", "real")
        matched = resp.get("matched")
        if not isinstance(pin, str) or not pin.startswith("sha256:"):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return V907SubprocessResult(
            pin=pin,
            mode=str(mode),
            matched=matched if matched is None else bool(matched),
        )


# ---------------------------------------------------------------------------
# High-level factory: build a state-backing per resolved backend.
# ---------------------------------------------------------------------------


def build_state_backing(
    backend: StateBackingBackend,
    *,
    nats_servers: str = "",
    org_id: str = "",
    persona_state_bucket: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    subprocess_invoker: Optional[Callable] = None,
    python_fallback_factory: Optional[Callable[[], PersonaStateBacking]] = None,
) -> PersonaStateBacking:
    """Build a state-backing matching ``backend``.

    For ``StateBackingBackend.PYTHON`` we delegate to
    ``python_fallback_factory`` (the engine passes its existing
    ``_select_state_backing`` bound method). For the Rust variants
    we construct a :class:`RustSubprocessStateBacking`.

    This factory does NOT re-probe binary availability — the caller
    is expected to have already run :func:`resolve_state_backing_backend`
    and obtained a ``StateBackingBackend`` value that reflects the
    actual chosen backend (Python on fallback). The factory therefore
    treats Rust-bound input as a hard contract: the caller MUST have
    verified availability.
    """
    if backend is StateBackingBackend.PYTHON:
        if python_fallback_factory is not None:
            return python_fallback_factory()
        # Tests / standalone callers without an engine-bound factory
        # get a pure InMemoryPersonaStateBacking.
        return InMemoryPersonaStateBacking()
    # Rust-bound.
    kind = backend.value  # "rust_inmemory" | "rust_natskv"
    return RustSubprocessStateBacking(
        kind=kind, env=env, subprocess_invoker=subprocess_invoker
    )


def build_fsm(
    backend: FsmBackend,
    persona_id: str,
    org_id: str,
    *,
    initial_state: str = "uninstantiated",
    env: Optional[Mapping[str, str]] = None,
    subprocess_invoker: Optional[Callable] = None,
):
    """Build an FSM matching ``backend``.

    For ``FsmBackend.PYTHON`` we return a fresh
    :class:`LifecycleStateMachine` (the Python authority).
    For ``FsmBackend.RUST`` we return a :class:`RustSubprocessFsm`
    subprocess-bridge instance.

    This factory does NOT re-probe binary availability — the caller
    is expected to have already run :func:`resolve_fsm_backend` and
    obtained an :class:`FsmBackend` value that reflects the actual
    chosen backend (Python on fallback). The factory therefore
    treats Rust-bound input as a hard contract: the caller MUST have
    verified availability.

    Both surfaces share the public method set
    (``state``, ``history``, ``can_transition_to``, ``transition_to``)
    so engine / despawn_clean callers cannot tell the backends
    apart at the API boundary.
    """
    if backend is FsmBackend.PYTHON:
        return LifecycleStateMachine(
            persona_id=persona_id,
            org_id=org_id,
            initial_state=initial_state,
        )
    # Rust-bound.
    return RustSubprocessFsm(
        persona_id=persona_id,
        org_id=org_id,
        initial_state=initial_state,
        env=env,
        subprocess_invoker=subprocess_invoker,
    )


def build_v907_verify(
    backend: V907VerifyBackend,
    *,
    env: Optional[Mapping[str, str]] = None,
    subprocess_invoker: Optional[Callable] = None,
):
    """Build a V-907 verify surface matching ``backend``.

    For ``V907VerifyBackend.PYTHON`` we return a small Python-side
    adapter exposing the same :meth:`compute_pin` /
    :meth:`verify_pin` methods as :class:`RustSubprocessV907Verify`
    so callers cannot tell the backends apart at the API boundary.
    For ``V907VerifyBackend.RUST`` we return a
    :class:`RustSubprocessV907Verify` subprocess-bridge instance.

    This factory does NOT re-probe binary availability — the caller
    is expected to have already run :func:`resolve_v907_verify_backend`
    and obtained a :class:`V907VerifyBackend` value that reflects the
    actual chosen backend (Python on fallback). The factory therefore
    treats Rust-bound input as a hard contract: the caller MUST have
    verified availability.

    Both surfaces share the public method set
    (``compute_pin``, ``verify_pin``) so engine / despawn_clean
    callers cannot tell the backends apart at the API boundary.
    Tag-19 keeps ``self.v907_result`` Python-backed during
    Phase-3b Doppelbetrieb; this factory is the Phase-3c-cutover
    hook (Zone-K coordination with Tomás for the binary-hash-
    pinning step).
    """
    if backend is V907VerifyBackend.PYTHON:
        return _PythonV907VerifyAdapter()
    # Rust-bound.
    return RustSubprocessV907Verify(
        env=env, subprocess_invoker=subprocess_invoker
    )


class _PythonV907VerifyAdapter:
    """Python-side adapter mirroring the :class:`RustSubprocessV907Verify`
    method-set.

    Delegates to :mod:`wirelang.persona_engine.v907_verify` for the
    actual compute / verify work. Constructed by :func:`build_v907_verify`
    on the Python path so callers see a uniform method surface across
    both backends during Phase-3b Doppelbetrieb.

    The adapter does NOT cache the result; each call recomputes via
    the Python authority. This matches the Rust subprocess-bridge
    posture (each call is a fresh subprocess spawn) so latency
    measurements are comparable across backends.
    """

    def compute_pin(self, axis_a_bytes: bytes) -> str:
        from .v907_verify import compute_v907_pin

        return compute_v907_pin(axis_a_bytes)

    def verify_pin(
        self,
        *,
        persona_id: str,
        axis_a_bytes: bytes,
        expected_pin: Optional[str],
    ) -> V907SubprocessResult:
        """Compute + optionally verify; surface as
        :class:`V907SubprocessResult` to match the Rust bridge shape.
        """
        from .v907_verify import compute_v907_pin

        pin = compute_v907_pin(axis_a_bytes)
        matched: Optional[bool] = None
        if expected_pin is not None and expected_pin.strip():
            matched = pin == expected_pin
            if not matched:
                from .v907_verify import PersonaHashDriftError

                raise PersonaHashDriftError(
                    expected=expected_pin,
                    computed=pin,
                    persona_id=persona_id,
                )
        return V907SubprocessResult(pin=pin, mode="real", matched=matched)


# ---------------------------------------------------------------------------
# Subprocess-bridge: bridge-diff (JCS + SHA-256 + RFC-6901 field-paths).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeDiffSubprocessFieldDiff:
    """One RFC-6901 field-path diff entry returned by the bridge.

    Mirrors
    :class:`wirelang.persona_engine.bridge_audit_diff_engine.FieldDiff`
    byte-for-byte so callers can treat the two backends interchangeably.
    The ``kind`` field carries the wire-string (``"value-mismatch"``,
    ``"only-in-a"``, ``"only-in-b"``, ``"type-mismatch"``) rather than
    an enum so the bridge surface is JSON-serialisable without
    additional translation.
    """

    path: str
    kind: str
    value_a: Any = None
    value_b: Any = None


@dataclass(frozen=True)
class BridgeDiffSubprocessReport:
    """Result envelope for the bridge-diff subprocess-bridge.

    Mirrors
    :class:`wirelang.persona_engine.bridge_audit_diff_engine.DiffReport`
    byte-for-byte (minus the ``envelope_a`` / ``envelope_b`` echo,
    which the caller already holds). Fast-path: when ``byte_identical``
    is True, ``field_diffs`` is empty and ``consistency_score`` is 1.0.
    """

    byte_identical: bool
    jcs_hash_a: str
    jcs_hash_b: str
    field_diffs: tuple
    consistency_score: float


class RustSubprocessBridgeDiff:
    """Subprocess-bridge persona-engine bridge-diff.

    Delegates ``jcs_hash`` / ``diff_envelopes`` / ``compare`` to a
    Rust-CLI subprocess against the ``persona-engine-bridge-diff``
    crate (PR #131). JSON-stdin carries the operation kind + arguments;
    JSON-stdout carries the response.

    Schema-byte-parity contract (mirror of
    :mod:`wirelang.persona_engine.bridge_audit_diff_engine`):

    - JCS canonicalisation: RFC 8785 via ``serde_jcs`` (Rust) /
      :mod:`wirelang.identity._jcs_pure` (Python) — byte-identical.
    - Hash: SHA-256 over JCS bytes; prefix ``"sha256:"`` + 64 hex.
    - Field-paths: RFC-6901 (leading slash, ``~`` -> ``~0``,
      ``/`` -> ``~1``); root envelope is ``""``.
    - Diff-kind alphabet: ``"value-mismatch"`` | ``"only-in-a"`` |
      ``"only-in-b"`` | ``"type-mismatch"``.
    - Sort order: field diffs sorted ascending by RFC-6901 path.

    Wire-format:

    Stdin JSON:
        ``{"schema": "wakir.persona-engine.bridge-diff/1",
        "op": "<op>", "payload": {...}}``

    Operations:

    - ``jcs_hash`` — input ``{envelope: <json>}``;
      response ``{hash: "sha256:..."}``.
    - ``diff_envelopes`` — input ``{envelope_a: <json>,
      envelope_b: <json>}``;
      response ``{field_diffs: [{path, kind, value_a, value_b}, ...]}``.
    - ``compare`` — input ``{envelope_a: <json>, envelope_b: <json>}``;
      response ``{byte_identical: bool, jcs_hash_a: str, jcs_hash_b: str,
      field_diffs: [...], consistency_score: float}``.

    Construction is cheap; per-call overhead is one subprocess spawn.

    Tag-20 posture
    --------------
    This binding is the *opt-in* path: ``WAKIR_BRIDGE_DIFF_BACKEND=rust``
    + available binary. Default and missing-binary fallback stay on
    the Python authority. The engine wire-in (Tag-20) records the
    backend decision but keeps the Python authority active during
    Phase-3b Doppelbetrieb — the bridge is exercised by the tests
    and the future Phase-3c cutover. Cross-lang field-pin parity is
    gated by the six fixture-pinned vectors per
    ``cross_lang_field_diff_fixtures.json`` (PR #166).
    """

    def __init__(
        self,
        *,
        bin_path: Optional[str] = None,
        timeout_s: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
        subprocess_invoker: Optional[Callable] = None,
    ) -> None:
        self.bin_path: str = (
            bin_path if bin_path is not None
            else _resolve_bridge_diff_bin(env)
        )
        self.timeout_s: float = (
            timeout_s if timeout_s is not None else _resolve_timeout_s(env)
        )
        self._invoker: Callable = (
            subprocess_invoker or _invoke_rust_subprocess
        )

    def _call(self, op: str, payload: dict) -> dict:
        stdin_doc = {
            "schema": "wakir.persona-engine.bridge-diff/1",
            "op": op,
            "payload": payload,
        }
        stdin_bytes = json.dumps(
            stdin_doc, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        rc, stdout, stderr = self._invoker(
            self.bin_path,
            ["bridge-diff", "--json"],
            stdin_payload=stdin_bytes,
            timeout_s=self.timeout_s,
        )
        if rc != 0:
            raise RustBackendError(
                reason="exit_nonzero",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RustBackendError(
                reason="bad_json",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            ) from exc
        if not isinstance(parsed, dict):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
            )
        return parsed

    def jcs_hash(self, envelope: Mapping[str, Any]) -> str:
        """Compute the JCS-SHA-256 hash via the Rust subprocess.

        Returns the byte-identical hash string (``"sha256:<64hex>"``)
        that the Python authority would produce for the same envelope.

        Raises
        ------
        RustBackendError
            On subprocess / shape failure.
        """
        resp = self._call("jcs_hash", {"envelope": dict(envelope)})
        hash_str = resp.get("hash")
        if (
            not isinstance(hash_str, str)
            or not hash_str.startswith("sha256:")
            or len(hash_str) != len("sha256:") + 64
        ):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return hash_str

    def diff_envelopes(
        self,
        envelope_a: Mapping[str, Any],
        envelope_b: Mapping[str, Any],
    ) -> tuple:
        """Compute the RFC-6901 field-path diff entries via subprocess.

        Returns a tuple of :class:`BridgeDiffSubprocessFieldDiff`
        entries, sorted by ``path`` (byte-identical order with the
        Python authority).

        Raises
        ------
        RustBackendError
            On subprocess / shape failure.
        """
        resp = self._call(
            "diff_envelopes",
            {
                "envelope_a": dict(envelope_a),
                "envelope_b": dict(envelope_b),
            },
        )
        entries = resp.get("field_diffs")
        if not isinstance(entries, list):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return tuple(
            BridgeDiffSubprocessFieldDiff(
                path=str(e["path"]),
                kind=str(e["kind"]),
                value_a=e.get("value_a"),
                value_b=e.get("value_b"),
            )
            for e in entries
        )

    def compare(
        self,
        envelope_a: Mapping[str, Any],
        envelope_b: Mapping[str, Any],
    ) -> BridgeDiffSubprocessReport:
        """Run the full compare (hash + diff + score) via subprocess.

        Returns a :class:`BridgeDiffSubprocessReport`. Fast-path:
        ``byte_identical == True`` ⇒ empty ``field_diffs`` and
        ``consistency_score == 1.0`` (matches the Python authority).

        Raises
        ------
        RustBackendError
            On subprocess / shape failure.
        """
        resp = self._call(
            "compare",
            {
                "envelope_a": dict(envelope_a),
                "envelope_b": dict(envelope_b),
            },
        )
        hash_a = resp.get("jcs_hash_a")
        hash_b = resp.get("jcs_hash_b")
        entries = resp.get("field_diffs")
        score = resp.get("consistency_score")
        byte_identical = resp.get("byte_identical")
        if (
            not isinstance(hash_a, str)
            or not isinstance(hash_b, str)
            or not isinstance(entries, list)
            or not isinstance(score, (int, float))
            or not isinstance(byte_identical, bool)
        ):
            raise RustBackendError(
                reason="bad_shape",
                bin_path=self.bin_path,
                stdout=json.dumps(resp),
            )
        return BridgeDiffSubprocessReport(
            byte_identical=byte_identical,
            jcs_hash_a=hash_a,
            jcs_hash_b=hash_b,
            field_diffs=tuple(
                BridgeDiffSubprocessFieldDiff(
                    path=str(e["path"]),
                    kind=str(e["kind"]),
                    value_a=e.get("value_a"),
                    value_b=e.get("value_b"),
                )
                for e in entries
            ),
            consistency_score=float(score),
        )


class _PythonBridgeDiffAdapter:
    """Python-side adapter mirroring the :class:`RustSubprocessBridgeDiff`
    method-set.

    Delegates to :mod:`wirelang.persona_engine.bridge_audit_diff_engine`
    for the actual canonicalise / hash / diff work. Constructed by
    :func:`build_bridge_diff` on the Python path so callers see a
    uniform method surface across both backends during Phase-3b
    Doppelbetrieb.

    The adapter does NOT cache the result; each call recomputes via
    the Python authority. This matches the Rust subprocess-bridge
    posture (each call is a fresh subprocess spawn) so latency
    measurements are comparable across backends.
    """

    def jcs_hash(self, envelope: Mapping[str, Any]) -> str:
        from .bridge_audit_diff_engine import jcs_hash

        return jcs_hash(envelope)

    def diff_envelopes(
        self,
        envelope_a: Mapping[str, Any],
        envelope_b: Mapping[str, Any],
    ) -> tuple:
        from .bridge_audit_diff_engine import diff_envelopes

        diffs = diff_envelopes(envelope_a, envelope_b)
        return tuple(
            BridgeDiffSubprocessFieldDiff(
                path=fd.path,
                kind=fd.kind.value,
                value_a=fd.value_a,
                value_b=fd.value_b,
            )
            for fd in diffs
        )

    def compare(
        self,
        envelope_a: Mapping[str, Any],
        envelope_b: Mapping[str, Any],
    ) -> BridgeDiffSubprocessReport:
        from .bridge_audit_diff_engine import (
            consistency_score,
            diff_envelopes,
            jcs_hash,
        )

        hash_a = jcs_hash(envelope_a)
        hash_b = jcs_hash(envelope_b)
        if hash_a == hash_b:
            return BridgeDiffSubprocessReport(
                byte_identical=True,
                jcs_hash_a=hash_a,
                jcs_hash_b=hash_b,
                field_diffs=(),
                consistency_score=1.0,
            )
        diffs = diff_envelopes(envelope_a, envelope_b)
        score = consistency_score(envelope_a, envelope_b, diffs)
        return BridgeDiffSubprocessReport(
            byte_identical=False,
            jcs_hash_a=hash_a,
            jcs_hash_b=hash_b,
            field_diffs=tuple(
                BridgeDiffSubprocessFieldDiff(
                    path=fd.path,
                    kind=fd.kind.value,
                    value_a=fd.value_a,
                    value_b=fd.value_b,
                )
                for fd in diffs
            ),
            consistency_score=float(score),
        )


def build_bridge_diff(
    backend: BridgeDiffBackend,
    *,
    env: Optional[Mapping[str, str]] = None,
    subprocess_invoker: Optional[Callable] = None,
):
    """Build a bridge-diff surface matching ``backend``.

    For ``BridgeDiffBackend.PYTHON`` we return a small Python-side
    adapter exposing the same :meth:`jcs_hash` / :meth:`diff_envelopes`
    / :meth:`compare` methods as :class:`RustSubprocessBridgeDiff` so
    callers cannot tell the backends apart at the API boundary.
    For ``BridgeDiffBackend.RUST`` we return a
    :class:`RustSubprocessBridgeDiff` subprocess-bridge instance.

    This factory does NOT re-probe binary availability — the caller
    is expected to have already run :func:`resolve_bridge_diff_backend`
    and obtained a :class:`BridgeDiffBackend` value that reflects the
    actual chosen backend (Python on fallback). The factory therefore
    treats Rust-bound input as a hard contract: the caller MUST have
    verified availability.

    Both surfaces share the public method set
    (``jcs_hash``, ``diff_envelopes``, ``compare``) so engine /
    bridge-audit-writer callers cannot tell the backends apart at the
    API boundary. Tag-20 keeps the Python authority active during
    Phase-3b Doppelbetrieb; this factory is the Phase-3c-cutover hook.
    """
    if backend is BridgeDiffBackend.PYTHON:
        return _PythonBridgeDiffAdapter()
    # Rust-bound.
    return RustSubprocessBridgeDiff(
        env=env, subprocess_invoker=subprocess_invoker
    )


__all__ = [
    # Env-var keys.
    "RECOVERY_BACKEND_ENV",
    "STATE_BACKING_BACKEND_ENV",
    "FSM_BACKEND_ENV",
    "V907_VERIFY_BACKEND_ENV",
    "BRIDGE_DIFF_BACKEND_ENV",
    "RUST_RECOVERY_BIN_ENV",
    "RUST_STATE_BACKING_BIN_ENV",
    "RUST_FSM_BIN_ENV",
    "RUST_V907_VERIFY_BIN_ENV",
    "RUST_BRIDGE_DIFF_BIN_ENV",
    "RUST_BACKEND_TIMEOUT_ENV",
    # Defaults.
    "DEFAULT_RUST_RECOVERY_BIN",
    "DEFAULT_RUST_STATE_BACKING_BIN",
    "DEFAULT_RUST_FSM_BIN",
    "DEFAULT_RUST_V907_VERIFY_BIN",
    "DEFAULT_RUST_BRIDGE_DIFF_BIN",
    "DEFAULT_RUST_BACKEND_TIMEOUT_S",
    # Enums + valid-value tuples.
    "RecoveryBackend",
    "StateBackingBackend",
    "FsmBackend",
    "V907VerifyBackend",
    "BridgeDiffBackend",
    "VALID_RECOVERY_BACKEND_VALUES",
    "VALID_STATE_BACKING_BACKEND_VALUES",
    "VALID_FSM_BACKEND_VALUES",
    "VALID_V907_VERIFY_BACKEND_VALUES",
    "VALID_BRIDGE_DIFF_BACKEND_VALUES",
    # Errors.
    "BackendSwitchValidationError",
    "RustBackendError",
    # Per-decision logging.
    "BackendDecision",
    "log_backend_decision",
    # Resolution entry points.
    "resolve_recovery_backend",
    "resolve_state_backing_backend",
    "resolve_fsm_backend",
    "resolve_v907_verify_backend",
    "resolve_bridge_diff_backend",
    # Subprocess bridges.
    "RustSubprocessStateBacking",
    "RustSubprocessRecoveryRunner",
    "RustSubprocessFsm",
    "RustSubprocessV907Verify",
    "RustSubprocessBridgeDiff",
    "V907SubprocessResult",
    "BridgeDiffSubprocessFieldDiff",
    "BridgeDiffSubprocessReport",
    # Factories.
    "build_state_backing",
    "build_fsm",
    "build_v907_verify",
    "build_bridge_diff",
]
