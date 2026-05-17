# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Backend dispatcher for WAT anchor-submit.

Tag-16 Mini-Welle — Phase-3b production-wiring.

This module is the integration boundary between the legacy Python
anchor pipeline (``wat.anchor.ots_anchor.anchor_root``) and the Rust
``persona-engine-anchor-submit-worker`` crate (PR #149, gemerged) and
its operator CLI ``submit_worker`` (Tag-16).

Backend selection
-----------------

The ``WAKIR_ANCHOR_BACKEND`` environment variable picks the backend:

* ``python`` (default): legacy in-process ``ots stamp`` flow. The
  dispatcher is a pure no-op passthrough.
* ``rust_submit_worker``: opt-in. The dispatcher serialises the
  anchor request to a single-line JSON envelope, spawns the Rust
  ``submit_worker`` binary, parses the JSON result, and translates it
  back into the Python ``AnchorReceipt`` / ``AnchorError`` surface
  the legacy callers expect.

Fallback policy
---------------

If the backend is ``rust_submit_worker`` but the binary is not
discoverable on ``$PATH`` (and ``WAKIR_SUBMIT_WORKER_BIN`` is unset),
the dispatcher falls back to the Python backend and emits a single
``RuntimeWarning`` so operators notice the silent downgrade. This
matches the "no-regret default" posture: the WAT pipeline never goes
silent because the Rust binary is missing.

Hermetic-test posture
---------------------

Subprocess invocations are mocked in unit tests via the
``_run_submit_worker`` indirection. Tests never spawn the real
binary; they either patch ``_run_submit_worker`` directly or set
``WAKIR_SUBMIT_WORKER_BIN`` to a fixture binary on disk. The
production transport (``ots_cli``) is *also* gated behind a mock in
the test suite — no real ``ots`` calls fire.

ADR anchors
-----------

* ADR-0063 §Folgeartefakte Phase-3a Modul 12 (Rust crate).
* PR #149 — persona-engine-anchor-submit-worker (Reza, gemerged).
* PR #154 — wat/anchor latency-emission (Noa) — pinned the per-stage
  latency emit hooks that this dispatcher intentionally does not
  duplicate (the Python backend keeps owning the per-stage histogram
  for now).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants — env vars, defaults, subprocess timeouts.
# ---------------------------------------------------------------------------

#: Environment variable selecting the backend.
ENV_BACKEND: str = "WAKIR_ANCHOR_BACKEND"

#: Allowed values for ``ENV_BACKEND``.
BACKEND_PYTHON: str = "python"
BACKEND_RUST: str = "rust_submit_worker"
ALLOWED_BACKENDS: tuple[str, ...] = (BACKEND_PYTHON, BACKEND_RUST)

#: Environment variable pointing at the ``submit_worker`` binary
#: explicitly. Falls back to ``shutil.which("submit_worker")``.
ENV_SUBMIT_WORKER_BIN: str = "WAKIR_SUBMIT_WORKER_BIN"

#: Hard wall-clock timeout for one ``submit_worker`` invocation.
#: Matches the OTS-side ``SUBPROCESS_TIMEOUT_S`` (90 s) — the binary
#: wraps a single transport attempt so its budget cannot exceed the
#: legacy in-process budget.
SUBMIT_WORKER_TIMEOUT_S: int = 90


# ---------------------------------------------------------------------------
# Data class — Rust-side bridge result.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BridgeResult:
    """One ``tick()`` outcome from the Rust submit-worker.

    Mirrors the Rust ``BridgeOutput`` shape one-for-one. Production
    callers do not normally inspect this directly — they go through
    :func:`anchor_root_via_backend` which translates this into an
    ``AnchorReceipt`` or raises ``AnchorError``.
    """

    #: ``success`` / ``throttled`` / ``retrying`` / ``dead`` / ``idle``.
    result_kind: str
    #: Echoed envelope identifier.
    event_id: str
    #: Populated only for ``retrying``.
    attempt: Optional[int]
    #: Populated only for ``retrying``. Seconds.
    next_delay_secs: Optional[int]
    #: Populated only for ``dead``.
    terminal_error: Optional[str]
    #: Populated only for ``success`` when ``ots_cli`` produced a
    #: receipt file. ``None`` for mock transports and all non-success
    #: variants.
    receipt_path: Optional[str]

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "BridgeResult":
        """Build from the parsed JSON dict the binary emits on stdout."""
        return cls(
            result_kind=str(payload["result_kind"]),
            event_id=str(payload["event_id"]),
            attempt=_opt_int(payload.get("attempt")),
            next_delay_secs=_opt_int(payload.get("next_delay_secs")),
            terminal_error=_opt_str(payload.get("terminal_error")),
            receipt_path=_opt_str(payload.get("receipt_path")),
        )


def _opt_int(v: object) -> Optional[int]:
    if v is None:
        return None
    return int(v)  # type: ignore[arg-type]


def _opt_str(v: object) -> Optional[str]:
    if v is None:
        return None
    return str(v)


# ---------------------------------------------------------------------------
# Public surface — backend selection + dispatcher.
# ---------------------------------------------------------------------------


def selected_backend(getenv: Callable[[str], Optional[str]] = os.environ.get) -> str:
    """Return the active backend name.

    Defaults to ``"python"``. Unknown values fall back to the default
    with a ``RuntimeWarning`` (no exception — the WAT cron must not
    crash on a typo).
    """
    raw = (getenv(ENV_BACKEND) or "").strip()
    if raw == "":
        return BACKEND_PYTHON
    if raw in ALLOWED_BACKENDS:
        return raw
    warnings.warn(
        f"unknown {ENV_BACKEND}={raw!r}; falling back to {BACKEND_PYTHON!r}",
        RuntimeWarning,
        stacklevel=2,
    )
    return BACKEND_PYTHON


def resolve_submit_worker_binary(
    getenv: Callable[[str], Optional[str]] = os.environ.get,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[str]:
    """Return the path to ``submit_worker`` or ``None`` if not found.

    Resolution order:
    1. ``$WAKIR_SUBMIT_WORKER_BIN`` (explicit override; must point at
       an existing file).
    2. ``shutil.which("submit_worker")`` on ``$PATH``.
    """
    explicit = (getenv(ENV_SUBMIT_WORKER_BIN) or "").strip()
    if explicit:
        if Path(explicit).is_file():
            return explicit
        warnings.warn(
            f"{ENV_SUBMIT_WORKER_BIN}={explicit!r} does not point at a file; "
            f"falling back to PATH lookup",
            RuntimeWarning,
            stacklevel=2,
        )
    found = which("submit_worker")
    return found


def anchor_root_via_backend(
    merkle_root: bytes,
    calendars: Optional[Sequence[str]] = None,
    min_calendars: int = 2,
    *,
    target_dir: Optional[Path] = None,
    persona_id: str = "wat-anchor-cron",
    event_id: Optional[str] = None,
    getenv: Callable[[str], Optional[str]] = os.environ.get,
) -> "AnchorReceiptLike":
    """Dispatch ``anchor_root`` through the configured backend.

    Returns an object behaviourally compatible with
    ``wat.anchor.ots_anchor.AnchorReceipt`` (subset surface — the
    fields the WAT cron consumes downstream).

    Raises ``AnchorError`` on terminal failure.
    """
    backend = selected_backend(getenv)
    if backend == BACKEND_PYTHON:
        return _legacy_python_anchor_root(
            merkle_root=merkle_root,
            calendars=calendars,
            min_calendars=min_calendars,
            target_dir=target_dir,
        )

    # Rust backend.
    binary = resolve_submit_worker_binary(getenv=getenv)
    if binary is None:
        warnings.warn(
            f"{ENV_BACKEND}={BACKEND_RUST} but submit_worker binary not "
            f"resolvable; falling back to {BACKEND_PYTHON} (set "
            f"{ENV_SUBMIT_WORKER_BIN} or put submit_worker on $PATH to "
            f"avoid this warning)",
            RuntimeWarning,
            stacklevel=2,
        )
        return _legacy_python_anchor_root(
            merkle_root=merkle_root,
            calendars=calendars,
            min_calendars=min_calendars,
            target_dir=target_dir,
        )

    return _rust_backend_anchor_root(
        merkle_root=merkle_root,
        calendars=calendars,
        min_calendars=min_calendars,
        target_dir=target_dir,
        persona_id=persona_id,
        event_id=event_id,
        binary=binary,
    )


# ---------------------------------------------------------------------------
# Internal — Rust backend implementation.
# ---------------------------------------------------------------------------


def _rust_backend_anchor_root(
    *,
    merkle_root: bytes,
    calendars: Optional[Sequence[str]],
    min_calendars: int,
    target_dir: Optional[Path],
    persona_id: str,
    event_id: Optional[str],
    binary: str,
) -> "AnchorReceiptLike":
    """Spawn the Rust ``submit_worker`` binary and translate the result."""
    # Late-import the legacy module so callers that only need the
    # Python backend do not pay its import cost (and so the test
    # fixtures can isolate the import boundary).
    from wat.anchor import ots_anchor as _legacy

    if len(merkle_root) != 32:
        raise _legacy.AnchorError(
            f"merkle_root must be 32 bytes, got {len(merkle_root)}"
        )
    cal_list = (
        tuple(calendars) if calendars is not None else _legacy.DEFAULT_CALENDARS
    )
    if min_calendars < 1:
        raise ValueError("min_calendars must be >= 1")
    if min_calendars > len(cal_list):
        raise ValueError(
            f"min_calendars={min_calendars} exceeds calendar count {len(cal_list)}"
        )
    if target_dir is None:
        target_dir = Path("meta/timestamps/wat/_pending")

    ev_id = event_id or _default_event_id(merkle_root)
    timestamp_utc = _utc_now_rfc3339()

    payload = {
        "event_id": ev_id,
        "timestamp_utc": timestamp_utc,
        "persona_id": persona_id,
        "payload_root_hex": merkle_root.hex(),
        "calendars": list(cal_list),
        "min_calendars": int(min_calendars),
        "target_dir": str(target_dir),
    }
    bridge = _run_submit_worker(binary, json.dumps(payload))

    if bridge.result_kind == "success":
        # The receipt file the Rust transport produced (when
        # ``ots_cli`` ran successfully). Mock transports leave this
        # empty; for those we materialise a sentinel path so the
        # caller's downstream "receipt exists?" check is a no-op.
        receipt_path = (
            Path(bridge.receipt_path)
            if bridge.receipt_path
            else target_dir / "root.bin.ots"
        )
        return AnchorReceiptLike(
            merkle_root=merkle_root,
            submission_time=timestamp_utc,
            calendar_responses={u: "ok" for u in cal_list},
            receipt_path=receipt_path,
        )

    if bridge.result_kind == "throttled":
        # Throttle is back-pressure, not a failure. The cron should
        # retry on the next hourly tick. We translate this into a
        # retriable AnchorError so callers can distinguish it from a
        # terminal dead-letter.
        raise _legacy.AnchorError(
            f"submit_worker reported throttled for event_id={bridge.event_id}; "
            f"retry on next tick"
        )

    if bridge.result_kind == "retrying":
        raise _legacy.AnchorError(
            f"submit_worker reported retrying (attempt={bridge.attempt}, "
            f"next_delay_secs={bridge.next_delay_secs}); "
            f"retry on next tick"
        )

    if bridge.result_kind == "dead":
        raise _legacy.AnchorError(
            f"submit_worker dead-lettered event_id={bridge.event_id}: "
            f"{bridge.terminal_error}"
        )

    if bridge.result_kind == "idle":
        raise _legacy.AnchorError(
            f"submit_worker reported idle for event_id={bridge.event_id}; "
            f"unexpected — single-shot tick should advance the FSM"
        )

    raise _legacy.AnchorError(
        f"submit_worker emitted unknown result_kind={bridge.result_kind!r}"
    )


def _run_submit_worker(binary: str, stdin_payload: str) -> BridgeResult:
    """Invoke the binary; isolated so tests can patch one symbol.

    Hard 90-second timeout (mirrors ``ots_anchor.SUBPROCESS_TIMEOUT_S``).
    """
    try:
        proc = subprocess.run(  # noqa: S603 — explicit args, no shell.
            [binary],
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=SUBMIT_WORKER_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        from wat.anchor import ots_anchor as _legacy

        raise _legacy.AnchorError(
            f"submit_worker timed out after {SUBMIT_WORKER_TIMEOUT_S}s"
        ) from exc

    # Exit code 1 == Dead (FSM terminal); we still parse stdout below
    # because the binary emits the JSON in that case. Codes 2/3 are
    # internal-config / usage errors and have empty stdout — we raise
    # an AnchorError with the stderr captured for diagnostics.
    if proc.returncode in (2, 3):
        from wat.anchor import ots_anchor as _legacy

        raise _legacy.AnchorError(
            f"submit_worker exited {proc.returncode}: {proc.stderr.strip()}"
        )

    if not proc.stdout.strip():
        from wat.anchor import ots_anchor as _legacy

        raise _legacy.AnchorError(
            f"submit_worker emitted empty stdout (exit={proc.returncode}, "
            f"stderr={proc.stderr.strip()!r})"
        )

    try:
        parsed = json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError as exc:
        from wat.anchor import ots_anchor as _legacy

        raise _legacy.AnchorError(
            f"submit_worker emitted malformed JSON: {exc}; stdout={proc.stdout!r}"
        ) from exc

    return BridgeResult.from_json(parsed)


def _legacy_python_anchor_root(
    *,
    merkle_root: bytes,
    calendars: Optional[Sequence[str]],
    min_calendars: int,
    target_dir: Optional[Path],
) -> "AnchorReceiptLike":
    """Pure passthrough to the legacy in-process Python implementation."""
    from wat.anchor import ots_anchor as _legacy

    receipt = _legacy.anchor_root(
        merkle_root=merkle_root,
        calendars=calendars,
        min_calendars=min_calendars,
        target_dir=target_dir,
    )
    # The legacy AnchorReceipt is already structurally compatible —
    # but we wrap it for typing-cleanliness so callers do not depend
    # on the legacy class directly.
    return AnchorReceiptLike(
        merkle_root=receipt.merkle_root,
        submission_time=receipt.submission_time,
        calendar_responses=dict(receipt.calendar_responses),
        receipt_path=receipt.receipt_path,
    )


# ---------------------------------------------------------------------------
# Receipt shim — the unified return type.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AnchorReceiptLike:
    """Unified receipt shape returned by both backends.

    Structurally compatible with
    :class:`wat.anchor.ots_anchor.AnchorReceipt` — same field names,
    same types. We deliberately do *not* re-export the legacy class to
    keep the import boundary one-way (this module imports the legacy
    one, but the legacy module never imports this one).
    """

    merkle_root: bytes
    submission_time: str
    calendar_responses: dict[str, str]
    receipt_path: Path

    def successful_calendars(self) -> list[str]:
        return [u for u, r in self.calendar_responses.items() if r == "ok"]


# ---------------------------------------------------------------------------
# Helpers — timestamp + default event_id.
# ---------------------------------------------------------------------------


def _utc_now_rfc3339() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_event_id(merkle_root: bytes) -> str:
    """Build a deterministic event_id from the root + UTC hour.

    The WAT cron anchors one root per hour, so a per-hour event_id is
    the natural choice. The root hex tail is appended so two roots
    submitted in the same hour (a backfill scenario) still get
    distinct ids.
    """
    hour = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H")
    return f"wat-anchor-{hour}-{merkle_root.hex()[:16]}"


__all__ = [
    "ENV_BACKEND",
    "ENV_SUBMIT_WORKER_BIN",
    "BACKEND_PYTHON",
    "BACKEND_RUST",
    "ALLOWED_BACKENDS",
    "SUBMIT_WORKER_TIMEOUT_S",
    "BridgeResult",
    "AnchorReceiptLike",
    "anchor_root_via_backend",
    "resolve_submit_worker_binary",
    "selected_backend",
]
