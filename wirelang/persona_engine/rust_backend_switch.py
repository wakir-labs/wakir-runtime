# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""ENV-gated production-default switch for Rust recovery + state-backing + FSM.

Tag-17 / Tag-18 Mini-Welle — Phase-3b-Substanz. The Rust crates
``persona-engine-recovery`` (PR #135),
``persona-engine-state-backing`` (PR #140), and
``persona-engine-fsm`` (PR #137) are production-ready as
schema-byte-parity substrates of their Python pendants
(:mod:`wirelang.persona_engine.recovery_workflow`,
:mod:`wirelang.persona_engine.state_backing`, and
:mod:`wirelang.persona_engine.lifecycle_state_machine`). This module
exposes the **production-default switch** — operators flip an env-var
to opt into the Rust subprocess-bridge without disrupting the Python
hot-path.

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

``WAKIR_RUST_RECOVERY_BIN``:

* Absolute path to the Rust recovery binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-recovery``.

``WAKIR_RUST_STATE_BACKING_BIN``:

* Absolute path to the Rust state-backing binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-state-backing``.

``WAKIR_RUST_FSM_BIN``:

* Absolute path to the Rust FSM binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-fsm``.

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
RUST_RECOVERY_BIN_ENV = "WAKIR_RUST_RECOVERY_BIN"
RUST_STATE_BACKING_BIN_ENV = "WAKIR_RUST_STATE_BACKING_BIN"
RUST_FSM_BIN_ENV = "WAKIR_RUST_FSM_BIN"
RUST_BACKEND_TIMEOUT_ENV = "WAKIR_RUST_BACKEND_TIMEOUT_S"

DEFAULT_RUST_RECOVERY_BIN = "/opt/wakir/bin/wakir-persona-engine-recovery"
DEFAULT_RUST_STATE_BACKING_BIN = (
    "/opt/wakir/bin/wakir-persona-engine-state-backing"
)
DEFAULT_RUST_FSM_BIN = "/opt/wakir/bin/wakir-persona-engine-fsm"
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


VALID_RECOVERY_BACKEND_VALUES = tuple(b.value for b in RecoveryBackend)
VALID_STATE_BACKING_BACKEND_VALUES = tuple(
    b.value for b in StateBackingBackend
)
VALID_FSM_BACKEND_VALUES = tuple(b.value for b in FsmBackend)


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


__all__ = [
    # Env-var keys.
    "RECOVERY_BACKEND_ENV",
    "STATE_BACKING_BACKEND_ENV",
    "FSM_BACKEND_ENV",
    "RUST_RECOVERY_BIN_ENV",
    "RUST_STATE_BACKING_BIN_ENV",
    "RUST_FSM_BIN_ENV",
    "RUST_BACKEND_TIMEOUT_ENV",
    # Defaults.
    "DEFAULT_RUST_RECOVERY_BIN",
    "DEFAULT_RUST_STATE_BACKING_BIN",
    "DEFAULT_RUST_FSM_BIN",
    "DEFAULT_RUST_BACKEND_TIMEOUT_S",
    # Enums + valid-value tuples.
    "RecoveryBackend",
    "StateBackingBackend",
    "FsmBackend",
    "VALID_RECOVERY_BACKEND_VALUES",
    "VALID_STATE_BACKING_BACKEND_VALUES",
    "VALID_FSM_BACKEND_VALUES",
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
    # Subprocess bridges.
    "RustSubprocessStateBacking",
    "RustSubprocessRecoveryRunner",
    "RustSubprocessFsm",
    # Factories.
    "build_state_backing",
    "build_fsm",
]
