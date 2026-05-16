# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Rust persona-engine adapter hook — Phase-3a Doppelbetrieb-Third-Sink.

Sprint-Rust-Adapter-Hook-Skeleton-MINI follow-on to PR #113
(``bridge_audit_triangle``). The triangle module shipped the 3-way
cross-check entry point plus a *byte-identical stub* for the Rust
persona-engine sink. This module ships the **operator-facing hook
contract** that consumes a real Rust-engine binary when one is
deployed alongside the Python sinks.

Where this fits
---------------

PR #113 (:mod:`wirelang.persona_engine.bridge_audit_triangle`) defined:

* :class:`Implementation` protocol — adapter callable from
  :class:`DiffInput` to :class:`CloudEventEnvelope`.
* :func:`default_rust_engine_stub` — a *byte-identical-by-construction*
  placeholder that proves the triangle wiring without a real binary.
* :func:`cross_check_triangle` — the 2-way / 3-way mode-resolving
  cross-check entry point.

That left the gap: **how does the Python side actually call out to
the Rust binary in production?** Phase-3a Quadlet units co-mount the
Rust binary at a well-known path
(``/opt/wakir/bin/wakir-persona-engine-rust`` by default) and the
Python orchestrator subprocess-invokes it with a JSON-stdin job-
payload, reading the resulting CloudEvent envelope from stdout.

This module ships:

* :class:`RustAdapterHook` — the Protocol callers depend on.
* :class:`SubprocessRustAdapterHook` — the production implementation
  that subprocess-runs the binary.
* :class:`MockRustAdapterHook` — the deterministic hermetic-test
  implementation used by the triangle-test fixtures.
* :func:`hook_to_implementation` — adapter that turns a
  :class:`RustAdapterHook` into an :class:`Implementation` callable
  ready for :func:`cross_check_triangle`.
* :func:`build_triangle_impl_c` — the operator-facing factory that
  resolves :class:`RustAdapterHook` availability and falls back to
  the stub (with a warning log) when the binary is not callable.

Env-var contract
----------------

``WAKIR_BRIDGE_MODE`` (Phase-2 / Phase-3a switch — owned by PR #113):

* ``"2way"`` — Python sinks only; this hook is **never invoked**.
* ``"3way"`` — Rust-engine binary is invoked. If
  :meth:`RustAdapterHook.available` returns ``False`` (binary missing
  or non-executable) the orchestrator logs a warning and degrades
  gracefully back to 2-way semantics by feeding the stub adapter to
  the triangle. Triangle ``all_consistent`` then collapses to the
  pairwise A↔B result; the 3rd-sink edge is preserved as a
  byte-identical stub so the report shape stays 3-way for downstream
  consumers but no real Rust cross-check is performed.

``WAKIR_RUST_ENGINE_BIN`` (this module — Sprint-Rust-Adapter-Hook-
Skeleton-MINI):

* Absolute path to the Rust persona-engine binary. Default
  ``/opt/wakir/bin/wakir-persona-engine-rust``. Resolved at
  hook-construction time; subsequent rebinds require re-construction
  (the hook is a long-lived per-engine-session object).

``WAKIR_RUST_ENGINE_TIMEOUT_S`` (this module):

* Wall-clock timeout for a single subprocess call. Default ``30.0``
  seconds. Parsed as a float at hook-construction time. Negative or
  zero values fall back to the default with a warning.

Wire protocol
-------------

The subprocess is invoked with exactly two CLI arguments::

    <bin> emit --json

stdin receives a JCS-canonical JSON object::

    {
        "schema": "wakir.persona.engineering-output/1",
        "input": {
            "org_id": ...,
            "persona_id": ...,
            "session_id": ...,
            "step_index": ...,
            "output_kind": ...,
            "payload_b64": "<base64(payload_bytes)>",
            "ts_utc": ...
        },
        "persona_def": "<persona-definition-markdown>"
    }

stdout MUST be a single JSON object — the CloudEvent envelope. The
adapter parses it directly into a :class:`CloudEventEnvelope` (a
plain ``dict``). Any non-JSON stdout, non-zero exit code, or stderr-
only output raises :class:`RustAdapterError` carrying the captured
streams so the bridge-audit writer can surface a structured error.

Failure modes (all wrapped in :class:`RustAdapterError`)
--------------------------------------------------------

* Binary missing or not executable ⇒ raised by :meth:`available`
  returning ``False``; callers see no exception.
* Subprocess timeout ⇒ :class:`RustAdapterError` with ``reason=
  "timeout"`` and the captured-so-far stdout/stderr.
* Non-zero exit code ⇒ ``reason="exit_nonzero"``.
* stdout not valid JSON ⇒ ``reason="bad_json"``.
* stdout JSON is not a mapping ⇒ ``reason="bad_shape"``.

The structured-error shape is contractual: the triangle integration
layer uses ``reason`` to decide whether to degrade to 2-way (transient
failure) or to fail the emission (configuration / contract failure).

Hermetic-test guarantee
-----------------------

:class:`MockRustAdapterHook` produces fully deterministic outputs
from the same canonical projection the Python sinks use, exactly
like :func:`default_rust_engine_stub` from PR #113. The Mock is the
preferred adapter for new triangle-tests (PR #113 already tests the
``default_rust_engine_stub`` path; this module's tests exercise the
subprocess invocation surface separately).
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol

from .bridge_audit_diff_engine import (
    CloudEventEnvelope,
    DiffInput,
    Implementation,
)
from .bridge_audit_triangle import (
    BridgeMode,
    default_rust_engine_stub,
    resolve_bridge_mode,
)
from .bridge_audit_writer import ENGINEERING_OUTPUT_SCHEMA, sha256_hex


__all__ = [
    "RUST_ENGINE_BIN_ENV",
    "RUST_ENGINE_TIMEOUT_ENV",
    "DEFAULT_RUST_ENGINE_BIN",
    "DEFAULT_RUST_ENGINE_TIMEOUT_S",
    "RustAdapterError",
    "RustAdapterHook",
    "SubprocessRustAdapterHook",
    "MockRustAdapterHook",
    "hook_to_implementation",
    "build_triangle_impl_c",
]


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env-var contract
# ---------------------------------------------------------------------------


RUST_ENGINE_BIN_ENV = "WAKIR_RUST_ENGINE_BIN"
RUST_ENGINE_TIMEOUT_ENV = "WAKIR_RUST_ENGINE_TIMEOUT_S"

DEFAULT_RUST_ENGINE_BIN = "/opt/wakir/bin/wakir-persona-engine-rust"
DEFAULT_RUST_ENGINE_TIMEOUT_S = 30.0


def _resolve_bin_path(
    explicit: Optional[str],
    env: Optional[Mapping[str, str]],
) -> str:
    """Resolve the Rust-engine binary path.

    Precedence (highest to lowest):
    1. Explicit constructor argument ``explicit``.
    2. ``WAKIR_RUST_ENGINE_BIN`` env-var.
    3. :data:`DEFAULT_RUST_ENGINE_BIN`.
    """
    if explicit is not None:
        return explicit
    if env is None:
        env = os.environ
    return env.get(RUST_ENGINE_BIN_ENV, DEFAULT_RUST_ENGINE_BIN)


def _resolve_timeout_s(
    explicit: Optional[float],
    env: Optional[Mapping[str, str]],
) -> float:
    """Resolve the subprocess wall-clock timeout in seconds.

    Negative / zero / unparseable values fall back to the default
    with a warning — the hook deliberately does NOT raise on a bad
    timeout-env because the Quadlet env-var contract is best-effort
    operator-facing config; an unparseable value should not brick
    the persona-engine spawn.
    """
    if explicit is not None:
        if explicit > 0:
            return float(explicit)
        log.warning(
            "rust_adapter_hook explicit timeout %r non-positive; "
            "falling back to default %ss",
            explicit,
            DEFAULT_RUST_ENGINE_TIMEOUT_S,
        )
        return DEFAULT_RUST_ENGINE_TIMEOUT_S
    if env is None:
        env = os.environ
    raw = env.get(RUST_ENGINE_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_RUST_ENGINE_TIMEOUT_S
    try:
        parsed = float(raw)
    except ValueError:
        log.warning(
            "rust_adapter_hook %s=%r unparseable; "
            "falling back to default %ss",
            RUST_ENGINE_TIMEOUT_ENV,
            raw,
            DEFAULT_RUST_ENGINE_TIMEOUT_S,
        )
        return DEFAULT_RUST_ENGINE_TIMEOUT_S
    if parsed <= 0:
        log.warning(
            "rust_adapter_hook %s=%r non-positive; "
            "falling back to default %ss",
            RUST_ENGINE_TIMEOUT_ENV,
            raw,
            DEFAULT_RUST_ENGINE_TIMEOUT_S,
        )
        return DEFAULT_RUST_ENGINE_TIMEOUT_S
    return parsed


# ---------------------------------------------------------------------------
# Structured error
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RustAdapterError(Exception):
    """Structured error for Rust-engine subprocess failures.

    Carries enough context for the bridge-audit writer to log a
    drift-annotation that distinguishes transient failures (timeout,
    crash) from contract failures (bad JSON shape).

    Attributes
    ----------
    reason
        Short token: ``"timeout"`` / ``"exit_nonzero"`` /
        ``"bad_json"`` / ``"bad_shape"`` / ``"not_available"`` /
        ``"spawn_failed"``.
    bin_path
        The binary path the adapter attempted to invoke.
    returncode
        Subprocess exit code, or ``None`` if the process did not
        complete normally (timeout / spawn failure).
    stdout
        Captured stdout (``str``); may be empty.
    stderr
        Captured stderr (``str``); may be empty.
    """

    reason: str
    bin_path: str
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"RustAdapterError(reason={self.reason!r} "
            f"bin={self.bin_path!r} rc={self.returncode!r})"
        )


# ---------------------------------------------------------------------------
# Hook protocol
# ---------------------------------------------------------------------------


class RustAdapterHook(Protocol):
    """Contract for a Rust persona-engine adapter.

    Two implementations ship in this module:

    * :class:`SubprocessRustAdapterHook` — production.
    * :class:`MockRustAdapterHook` — tests.

    Callers that want a :class:`Implementation` callable (the
    :func:`cross_check_triangle` adapter contract) wrap a
    :class:`RustAdapterHook` via :func:`hook_to_implementation`.
    """

    def available(self) -> bool:  # pragma: no cover - protocol
        """Return ``True`` iff the underlying engine can be invoked.

        Production hook checks binary presence + executable bit.
        Mock hook returns a constructor-pinned constant.
        """
        ...

    def compute_output(
        self,
        input_payload: dict,
        persona_def: str,
    ) -> CloudEventEnvelope:  # pragma: no cover - protocol
        """Compute the Rust-engine CloudEvent envelope.

        Parameters
        ----------
        input_payload
            JSON-friendly dict carrying the :class:`DiffInput` fields
            plus an optional schema-pin under key ``"schema"``. The
            ``payload`` bytes from :class:`DiffInput` are base64-
            encoded under ``payload_b64`` (binary-safe transport
            over JSON-stdin).
        persona_def
            The persona-definition markdown source (axis-A document
            from the V-907 pin set). Passed verbatim — the Rust
            engine is responsible for parsing.

        Returns
        -------
        CloudEventEnvelope
            A JSON-friendly mapping suitable for direct comparison
            via :func:`compare_implementations`.

        Raises
        ------
        RustAdapterError
            On any subprocess / shape failure. Implementations MUST
            NOT raise other exception classes — the triangle
            integration layer dispatches on ``reason`` only.
        """
        ...


# ---------------------------------------------------------------------------
# Subprocess implementation
# ---------------------------------------------------------------------------


@dataclass
class SubprocessRustAdapterHook:
    """Production hook: subprocess-invokes the Rust persona-engine binary.

    The binary contract is documented in the module docstring under
    "Wire protocol". The hook is intentionally stateless across
    invocations — every :meth:`compute_output` call spawns a fresh
    process. Per-call overhead is acceptable in the Phase-3a
    Doppelbetrieb window because emissions are low-frequency
    (one per persona-engine output step, not per LLM token).

    Attributes
    ----------
    bin_path
        Absolute path to the Rust-engine binary. Resolved from the
        constructor argument, then the env-var, then the default.
    timeout_s
        Wall-clock timeout in seconds per subprocess call.
    """

    bin_path: str = field(default="")
    timeout_s: float = field(default=DEFAULT_RUST_ENGINE_TIMEOUT_S)

    def __init__(
        self,
        *,
        bin_path: Optional[str] = None,
        timeout_s: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.bin_path = _resolve_bin_path(bin_path, env)
        self.timeout_s = _resolve_timeout_s(timeout_s, env)

    def available(self) -> bool:
        """Return ``True`` iff the binary exists and is executable.

        Uses :func:`shutil.which`-style semantics for an absolute
        path: the path must exist, be a regular file, and have the
        execute bit set for the calling user. Symlinks are followed.
        """
        path = self.bin_path
        if not path:
            return False
        if not os.path.isabs(path):
            # Allow PATH-resolved binaries via shutil.which; relative
            # paths without PATH-presence are not available.
            resolved = shutil.which(path)
            if resolved is None:
                return False
            path = resolved
        if not os.path.isfile(path):
            return False
        return os.access(path, os.X_OK)

    def compute_output(
        self,
        input_payload: dict,
        persona_def: str,
    ) -> CloudEventEnvelope:
        if not self.available():
            raise RustAdapterError(
                reason="not_available",
                bin_path=self.bin_path,
            )
        stdin_doc = {
            "schema": input_payload.get(
                "schema", ENGINEERING_OUTPUT_SCHEMA
            ),
            "input": {
                k: v
                for k, v in input_payload.items()
                if k != "schema"
            },
            "persona_def": persona_def,
        }
        stdin_bytes = json.dumps(
            stdin_doc, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        try:
            proc = subprocess.run(
                [self.bin_path, "emit", "--json"],
                input=stdin_bytes,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RustAdapterError(
                reason="timeout",
                bin_path=self.bin_path,
                stdout=(exc.stdout or b"").decode(
                    "utf-8", errors="replace"
                ),
                stderr=(exc.stderr or b"").decode(
                    "utf-8", errors="replace"
                ),
            ) from exc
        except (OSError, ValueError) as exc:
            # OSError covers spawn failure (binary disappeared
            # between the available() check and exec); ValueError
            # covers argument-shape failures.
            raise RustAdapterError(
                reason="spawn_failed",
                bin_path=self.bin_path,
                stderr=str(exc),
            ) from exc

        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RustAdapterError(
                reason="exit_nonzero",
                bin_path=self.bin_path,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RustAdapterError(
                reason="bad_json",
                bin_path=self.bin_path,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            ) from exc
        if not isinstance(parsed, dict):
            raise RustAdapterError(
                reason="bad_shape",
                bin_path=self.bin_path,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        return parsed


# ---------------------------------------------------------------------------
# Mock implementation
# ---------------------------------------------------------------------------


@dataclass
class MockRustAdapterHook:
    """Deterministic hook for hermetic tests.

    Produces an envelope that matches the
    :func:`default_rust_engine_stub` shape from PR #113 by default,
    so the mock plays the same byte-identical role in 3-way
    triangle tests but exercises the hook surface (``available`` +
    ``compute_output``) rather than the stub-implementation surface.

    Attributes
    ----------
    is_available
        Constructor-pinned :meth:`available` return value.
    engine_version
        Echoed into the returned envelope; defaults to the rust-
        stub suffix so the mock is distinguishable from the Python
        sinks in test logs.
    v907_pin
        Echoed into the returned envelope.
    raise_on_compute
        If not ``None``, :meth:`compute_output` raises this
        :class:`RustAdapterError` instead of returning. Lets tests
        exercise the structured-error path.
    captured_calls
        Append-only log of ``(input_payload, persona_def)`` tuples
        for each :meth:`compute_output` invocation. Lets tests
        assert wire-payload shape without intercepting subprocess.
    """

    is_available: bool = True
    engine_version: str = "0.2.0-pilot-rust-stub"
    v907_pin: str = "sha256:" + "a" * 64
    raise_on_compute: Optional[RustAdapterError] = None
    captured_calls: list = field(default_factory=list)

    def available(self) -> bool:
        return self.is_available

    def compute_output(
        self,
        input_payload: dict,
        persona_def: str,
    ) -> CloudEventEnvelope:
        self.captured_calls.append((dict(input_payload), persona_def))
        if self.raise_on_compute is not None:
            raise self.raise_on_compute
        # Reconstruct the canonical engineering-output envelope from
        # the input-payload mapping. The mock deliberately mirrors
        # the Python-sink projection so triangle tests collapse to
        # byte-identical when the mock is paired with the matching
        # Python adapters.
        payload_b64 = input_payload.get("payload_b64", "")
        try:
            payload_bytes = base64.b64decode(payload_b64.encode("ascii"))
        except (ValueError, TypeError):
            payload_bytes = b""
        return {
            "engine_version": self.engine_version,
            "event_kind": "engineering_output",
            "org_id": input_payload.get("org_id", ""),
            "output_kind": input_payload.get("output_kind", ""),
            "output_payload_sha256": sha256_hex(payload_bytes),
            "persona_id": input_payload.get("persona_id", ""),
            "schema": input_payload.get(
                "schema", ENGINEERING_OUTPUT_SCHEMA
            ),
            "session_id": input_payload.get("session_id", ""),
            "step_index": input_payload.get("step_index", 0),
            "ts_utc": input_payload.get("ts_utc", ""),
            "v907_pin": self.v907_pin,
        }


# ---------------------------------------------------------------------------
# Hook → Implementation bridge
# ---------------------------------------------------------------------------


def _diff_input_to_payload(input_: DiffInput) -> dict:
    """Translate :class:`DiffInput` into the JSON-stdin payload dict.

    Binary ``payload`` bytes are base64-encoded under
    ``payload_b64`` so the JSON-stdin transport is binary-safe.
    """
    return {
        "org_id": input_.org_id,
        "persona_id": input_.persona_id,
        "session_id": input_.session_id,
        "step_index": input_.step_index,
        "output_kind": input_.output_kind,
        "payload_b64": base64.b64encode(input_.payload).decode("ascii"),
        "ts_utc": input_.ts_utc,
        "schema": ENGINEERING_OUTPUT_SCHEMA,
    }


def hook_to_implementation(
    hook: RustAdapterHook,
    *,
    persona_def: str = "",
) -> Implementation:
    """Wrap a :class:`RustAdapterHook` into an :class:`Implementation`.

    The returned callable is suitable for direct use as ``impl_c``
    in :func:`cross_check_triangle`. ``persona_def`` is the V-907-
    pinned persona-definition markdown body that the Rust engine
    consumes; it is passed verbatim on every call (the Phase-3a
    contract is one-persona-per-session, so the persona-def does
    not vary across emissions in a single session).

    Errors raised by the hook propagate as :class:`RustAdapterError`
    — callers that want graceful 2-way degradation should use
    :func:`build_triangle_impl_c` instead.
    """

    def _impl(input_: DiffInput) -> CloudEventEnvelope:
        payload = _diff_input_to_payload(input_)
        return hook.compute_output(payload, persona_def)

    return _impl


# ---------------------------------------------------------------------------
# Triangle integration: availability-aware impl_c factory
# ---------------------------------------------------------------------------


def build_triangle_impl_c(
    hook: Optional[RustAdapterHook] = None,
    *,
    persona_def: str = "",
    env: Optional[Mapping[str, str]] = None,
    fallback_engine_version: str = "0.2.0-pilot",
    fallback_v907_pin: str = "sha256:" + "a" * 64,
) -> Implementation:
    """Build the ``impl_c`` adapter for :func:`cross_check_triangle`.

    Behaviour matrix:

    +----------------------+------------------+----------------------+
    | ``WAKIR_BRIDGE_MODE``| ``hook``         | Returned adapter     |
    +======================+==================+======================+
    | ``2way``             | any              | stub (never called)  |
    +----------------------+------------------+----------------------+
    | ``3way``             | ``None``         | stub + warning log   |
    +----------------------+------------------+----------------------+
    | ``3way``             | hook.available() | hook-backed impl     |
    |                      | == True          |                      |
    +----------------------+------------------+----------------------+
    | ``3way``             | hook.available() | stub + warning log   |
    |                      | == False         | (graceful 2-way      |
    |                      |                  | fallback)            |
    +----------------------+------------------+----------------------+

    Graceful fallback in 3-way mode: when the Rust binary is not
    callable the operator-facing report stays 3-way-shaped (so
    dashboards do not flicker between report shapes) but the
    ``impl_c`` adapter is the byte-identical stub, which means the
    triangle's ``all_consistent`` flag reduces to the A↔B pairwise
    result. A WARNING-level log line is emitted on every fallback
    so operators see the degradation in :class:`BridgeAuditWriter`
    structured-log output.

    Parameters
    ----------
    hook
        The :class:`RustAdapterHook` to consult. Pass ``None`` to
        force stub-only behaviour (useful for tests that exercise
        the writer-side wiring without a hook).
    persona_def
        Persona-definition markdown body forwarded to the hook.
    env
        Env-var mapping used to resolve :data:`BRIDGE_MODE_ENV`.
        Defaults to :data:`os.environ`.
    fallback_engine_version, fallback_v907_pin
        Knobs forwarded to :func:`default_rust_engine_stub` when
        constructing the fallback adapter. Default values match
        the Python-sink projection so the stub is byte-identical.
    """
    mode = resolve_bridge_mode(env)
    stub = default_rust_engine_stub(
        engine_version=fallback_engine_version,
        v907_pin=fallback_v907_pin,
    )
    if mode == BridgeMode.TWO_WAY:
        # In 2-way mode the triangle never invokes ``impl_c``; we
        # return the stub anyway so callers that pre-bind all three
        # adapters do not crash on a ``None``.
        return stub
    if hook is None:
        log.warning(
            "rust_adapter_hook 3way mode without hook; "
            "falling back to byte-identical stub"
        )
        return stub
    if not hook.available():
        log.warning(
            "rust_adapter_hook 3way mode but hook not available; "
            "falling back to byte-identical stub"
        )
        return stub
    return hook_to_implementation(hook, persona_def=persona_def)
