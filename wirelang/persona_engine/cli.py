# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""CLI entry points for ``persona-engine`` (v0.5.0-pilot).

Matches the CLI surface of the Sprint-10 Tag-4 stub binary
(``spawn`` / ``healthcheck`` / ``version``) so the Quadlet contract
(``Exec=spawn --persona-slug tomas --pilot-phase doppelbetrieb-shadow``)
is byte-stable across the stub-to-real engine swap.

The real ``spawn`` differs from the stub in semantics:

- Stub: reads axis-A, computes ``sha256-stub:`` pin, idles on
  SIGTERM with 30s heartbeats.
- Sync-real (default): full boot+spawn+run+despawn cycle, emits
  ``engineering_output`` events into the bridge-audit double-sink;
  no NATS-subscribe-loop activated.
- Async-real (Sprint-Pengine-12 Bug-41 — when ``WAKIR_SUBSCRIBE_ENV``
  is set): boots :class:`AsyncPersonaEngine`, attaches the
  :class:`NatsSubscribeLoop` to the canonical
  ``wakir.<env>.agent.agent.task.assigned.<persona-slug>`` subject,
  and runs until SIGTERM/SIGINT. This is the path the
  ``wakir-persona-tomas`` container needs to actually consume
  Mira-side bridge-forward auftraege.

The async path is opt-in via env var so the hermetic
``--one-shot`` mode and existing single-process containers continue
to work without an asyncio.run() shell.

Both honour the same env-var contract (spec §"Env var contract").
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .engine import (
    DEFAULT_HEARTBEAT_INTERVAL_SEC,
    ENGINE_VERSION,
    EnvContractError,
    PersonaEngine,
    resolve_env,
)
from .lifecycle_state_machine import InvalidTransitionError
from .v907_verify import PersonaHashComputeError, PersonaHashDriftError


# ---------------------------------------------------------------------------
# Exit code mapping (parity with persona-converter §7.4).
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_SCHEMA_ERROR = 1
EXIT_V907_HASH_DRIFT = 2
EXIT_INPUT_NOT_FOUND = 3
EXIT_ENV_MISCONFIG = 4
EXIT_USAGE_ERROR = 64


# ---------------------------------------------------------------------------
# Env-var name that toggles the async subscribe-loop path
# (Sprint-Pengine-12 Bug-41). Value must be a Bridge-Forward-Pipe env
# tag (``dev`` / ``staging`` / ``prod``); empty / unset = sync path.
# ---------------------------------------------------------------------------

SUBSCRIBE_ENV_VAR = "WAKIR_SUBSCRIBE_ENV"

#: Env var name used to pick the live NATS URL when the async path
#: builds its publish/subscribe binding. Defaults to ``WAKIR_NATS_SERVERS``
#: (the same var the state-backing already consumes) so the Quadlet
#: container only needs one NATS-URL knob.
NATS_URL_ENV_VAR = "WAKIR_NATS_SERVERS"

#: Optional token env-var (parity with ``wirelang.cli.mira_dispatch``).
NATS_TOKEN_ENV_VAR = "WAKIR_NATS_TOKEN"


# ---------------------------------------------------------------------------
# Sub-commands.
# ---------------------------------------------------------------------------


def _resolve_async_subscribe_env(env: Optional[dict] = None) -> Optional[str]:
    """Return the configured subscribe-env tag, or ``None`` if disabled.

    The async path activates iff the env var :data:`SUBSCRIBE_ENV_VAR`
    is set to a non-empty string. The value is validated against the
    Bridge-Forward-Pipe grammar (``dev`` / ``staging`` / ``prod``) by
    the subscribe-loop itself; this resolver only performs the
    presence check so unset / empty stays cleanly on the sync path.
    """
    src = env if env is not None else os.environ
    raw = src.get(SUBSCRIBE_ENV_VAR, "")
    if not raw:
        return None
    return raw


def _run_spawn_sync(args: argparse.Namespace) -> int:
    """Sync-engine spawn path (backward-compat, no subscribe-loop).

    Behaviour identical to the v0.4.1-pilot ``run_spawn`` body.
    """
    try:
        env = resolve_env(persona_id=args.persona_slug)
    except EnvContractError as exc:
        sys.stderr.write(f"env-misconfig: {exc}\n")
        return EXIT_ENV_MISCONFIG
    if not env.axis_a_path.is_file():
        sys.stderr.write(
            f"axis-A path not found: {env.axis_a_path}\n"
            f"remediation: verify Quadlet Volume= line bind-mounts "
            f"the persona-md\n"
        )
        return EXIT_INPUT_NOT_FOUND
    engine = PersonaEngine(env_contract=env)
    try:
        engine.boot()
    except PersonaHashDriftError as exc:
        sys.stderr.write(f"v907-pin-drift: {exc}\n")
        return EXIT_V907_HASH_DRIFT
    except PersonaHashComputeError as exc:
        sys.stderr.write(f"v907-compute-failed: {exc}\n")
        return EXIT_SCHEMA_ERROR
    try:
        engine.spawn()
    except InvalidTransitionError as exc:
        sys.stderr.write(f"lifecycle-fsm-error: {exc}\n")
        return EXIT_SCHEMA_ERROR
    if args.one_shot:
        # One-shot mode is a hermetic-test escape hatch: spawn + immediate
        # despawn without entering the heartbeat loop. Production
        # invocation omits --one-shot.
        try:
            engine.despawn_clean_run()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"despawn-clean-failed: {exc}\n")
            return EXIT_SCHEMA_ERROR
        return EXIT_SUCCESS
    engine.run_until_signal()
    try:
        engine.despawn_clean_run()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"despawn-clean-failed: {exc}\n")
        return EXIT_SCHEMA_ERROR
    return EXIT_SUCCESS


async def _run_spawn_async(
    args: argparse.Namespace,
    subscribe_env: str,
) -> int:
    """Async-engine spawn path (Sprint-Pengine-12 Bug-41).

    Activated when :data:`SUBSCRIBE_ENV_VAR` is set. Wires:

      1. :class:`AsyncPersonaEngine` (boot + spawn).
      2. :class:`NatsSubscribeLoop` bound to the canonical
         ``wakir.<env>.agent.agent.task.assigned.<persona-slug>`` subject
         via :meth:`AsyncPersonaEngine.attach_subscribe_loop`. The runner
         lazy-imports ``nats-py`` and connects to
         ``WAKIR_NATS_SERVERS`` (with optional ``WAKIR_NATS_TOKEN``).
      3. SIGTERM / SIGINT graceful shutdown via
         :meth:`AsyncPersonaEngine.run_until_signal`.

    Returns standard CLI exit code (EXIT_SUCCESS on graceful shutdown,
    EXIT_ENV_MISCONFIG on env contract failures, EXIT_INPUT_NOT_FOUND
    on missing axis-A, EXIT_V907_HASH_DRIFT on pin drift,
    EXIT_SCHEMA_ERROR on lifecycle FSM violations or NATS wheel
    missing).
    """
    # Lazy-import the async engine + subscribe-loop pieces inside the
    # async path so the sync path keeps its zero-async import surface
    # (parity with the PEP-562 lazy-attr pattern in __init__.py).
    from .engine_async import AsyncPersonaEngine
    from .nats_subscribe_loop import (
        DEFAULT_SUBSCRIBE_MODE,
        NatsSubscribeLoop,
        SUBSCRIBE_MODE_CORE_CALLBACK,
        SUBSCRIBE_MODE_CORE_ITERATOR,
        SUBSCRIBE_MODE_JETSTREAM_PULL,
        SubscribeLoopConfig,
        build_subscribe_subject,
        resolve_subscribe_mode,
    )

    try:
        env = resolve_env(persona_id=args.persona_slug)
    except EnvContractError as exc:
        sys.stderr.write(f"env-misconfig: {exc}\n")
        return EXIT_ENV_MISCONFIG
    if not env.axis_a_path.is_file():
        sys.stderr.write(
            f"axis-A path not found: {env.axis_a_path}\n"
            f"remediation: verify Quadlet Volume= line bind-mounts "
            f"the persona-md\n"
        )
        return EXIT_INPUT_NOT_FOUND

    nats_url = os.environ.get(NATS_URL_ENV_VAR, "").strip()
    if not nats_url and not args.one_shot:
        # Live mode (no --one-shot) requires the NATS URL to bind the
        # subscribe-loop. One-shot skips the run-loop entirely (boot +
        # spawn + despawn-clean) so the missing URL is tolerated as a
        # hermetic-test escape hatch.
        sys.stderr.write(
            f"env-misconfig: {SUBSCRIBE_ENV_VAR} is set but "
            f"{NATS_URL_ENV_VAR} is empty — cannot bind subscribe-loop "
            f"to NATS\n"
        )
        return EXIT_ENV_MISCONFIG
    nats_token = os.environ.get(NATS_TOKEN_ENV_VAR) or None

    # Bind log_sink to the *current* sys.stderr (not the import-time
    # default in AsyncPersonaEngine.__init__) so hermetic tests using
    # capsys / capfd see the engine logs. In production this resolves
    # to the same stderr the CLI inherited from the Quadlet exec.
    engine = AsyncPersonaEngine(
        env_contract=env,
        subscribe_env=subscribe_env,
        log_sink=sys.stderr,
    )
    try:
        await engine.boot()
    except PersonaHashDriftError as exc:
        sys.stderr.write(f"v907-pin-drift: {exc}\n")
        return EXIT_V907_HASH_DRIFT
    except PersonaHashComputeError as exc:
        sys.stderr.write(f"v907-compute-failed: {exc}\n")
        return EXIT_SCHEMA_ERROR
    try:
        await engine.spawn()
    except InvalidTransitionError as exc:
        sys.stderr.write(f"lifecycle-fsm-error: {exc}\n")
        return EXIT_SCHEMA_ERROR

    # Wire the subscribe-loop. We don't use ``attach_subscribe_loop()``
    # directly (it's the hermetic-test surface that consumes an
    # externally-supplied msg_iter). Instead we construct a
    # :class:`NatsSubscribeLoop` and set the engine's ``subscribe_runner``
    # to the live ``run_live`` coroutine. The engine.run_until_signal
    # awaits the runner via its ``_subscribe_loop`` task wrapper.
    if engine.bridge_writer is None:  # defensive
        sys.stderr.write("internal-error: bridge_writer is None after spawn\n")
        return EXIT_SCHEMA_ERROR
    subscribe_cfg = SubscribeLoopConfig(
        env=subscribe_env,
        persona_slug=env.persona_id,
        org_id=env.org_id,
        bridge_writer=engine.bridge_writer,
        hook=engine._llm_hook,
        tracker=engine.task_tracker,
        publish_output=True,
    )
    subscribe_subject = build_subscribe_subject(
        subscribe_env, env.persona_id,
    )
    sub_loop = NatsSubscribeLoop(
        subscribe_cfg,
        log_sink=engine.log_sink,
    )
    # Expose it on the engine so introspection (and the
    # ``subscribe_loop`` property used by the hermetic tests) works.
    engine._attached_subscribe_loop = sub_loop

    # Sprint-Pengine-13 Bug-42 — resolve the subscribe wire-mode.
    # Default ``core-callback`` avoids the iterator-cancellation
    # surface that produced Bug-42 (silent message-drop when
    # ``asyncio.wait_for(__anext__(), 0.5)`` timed out and cancelled
    # the inner nats-py ``get_task``).
    try:
        subscribe_mode = resolve_subscribe_mode()
    except ValueError as exc:
        sys.stderr.write(f"env-misconfig: {exc}\n")
        return EXIT_ENV_MISCONFIG

    # Tag-41 Bug-42 — pre-flight surface-compatibility check.
    # If the operator has declared the producer's publish-mode via
    # WAKIR_NATS_PUBLISH_MODE we verify it against the resolved
    # subscribe-surface (spec wirelang-spec-v0-2 §13.2). A broken
    # pair (e.g. core publisher + jetstream-pull subscriber) is
    # refused at bring-up rather than silently dropping messages.
    from .publish_mode_contract import (
        SurfaceMismatchError,
        resolve_publish_mode,
        resolve_subscribe_surface_from_subscribe_mode,
        require_compatible,
    )
    try:
        declared_publish_mode = resolve_publish_mode()
    except ValueError as exc:
        sys.stderr.write(f"env-misconfig: {exc}\n")
        return EXIT_ENV_MISCONFIG
    try:
        subscribe_surface = resolve_subscribe_surface_from_subscribe_mode(
            subscribe_mode,
        )
    except ValueError as exc:
        sys.stderr.write(f"env-misconfig: {exc}\n")
        return EXIT_ENV_MISCONFIG
    try:
        compat_verdict = require_compatible(
            declared_publish_mode,
            subscribe_surface,
        )
    except SurfaceMismatchError as exc:
        sys.stderr.write(
            "surface-mismatch: "
            f"{exc.verdict.diagnosis}\n"
            f"  failure_mode_id: {exc.verdict.failure_mode_id}\n"
            f"  recommended_adapter: {exc.verdict.recommended_adapter}\n"
        )
        return EXIT_ENV_MISCONFIG
    engine._log({
        "level": "INFO",
        "msg": "subscribe-surface-compatibility-verified",
        "publish_mode": declared_publish_mode,
        "subscribe_surface": subscribe_surface,
        "subscribe_mode": subscribe_mode,
        "verdict": compat_verdict.verdict,
    })

    # Inline runner: lazy-import nats-py + dispatch to the selected
    # subscribe-mode path on the sub_loop. We do NOT call
    # ``sub_loop.run_live(...)`` directly here because the engine
    # owns the connection lifecycle (drain on stop) AND the
    # publish_sink wiring before the loop starts — sub_loop.run_live
    # owns its own connection.
    async def _live_runner() -> None:
        try:
            import nats  # type: ignore
        except ImportError as exc:  # pragma: no cover - wheel missing
            engine._log({
                "level": "ERROR",
                "msg": "subscribe-loop-nats-py-missing",
                "reason": str(exc),
            })
            return
        try:
            nc = await nats.connect(nats_url, token=nats_token)
        except Exception as exc:  # pragma: no cover - network
            engine._log({
                "level": "ERROR",
                "msg": "subscribe-loop-nats-connect-failed",
                "reason": repr(exc),
                "nats_url": nats_url,
            })
            return
        sub_loop.publish_sink = nc
        engine._log({
            "level": "INFO",
            "msg": "subscribe-loop-started",
            "subject": subscribe_subject,
            "subscribe_env": subscribe_env,
            "persona_slug": env.persona_id,
            "nats_url": nats_url,
            "subscribe_mode": subscribe_mode,
        })
        try:
            if subscribe_mode == SUBSCRIBE_MODE_CORE_CALLBACK:
                async def _msg_handler(msg) -> None:  # type: ignore
                    await sub_loop._handle_message(msg)
                sub = await nc.subscribe(
                    subscribe_subject, cb=_msg_handler,
                )
                # Block on the engine stop-event; messages are
                # delivered to the callback in the background.
                await engine._stop_event.wait()
                try:
                    await sub.unsubscribe()
                except Exception:  # pragma: no cover - best-effort
                    pass
            elif subscribe_mode == SUBSCRIBE_MODE_CORE_ITERATOR:
                sub = await nc.subscribe(subscribe_subject)
                await sub_loop.run_with_iterator(
                    sub.messages, stop_event=engine._stop_event,
                )
            elif subscribe_mode == SUBSCRIBE_MODE_JETSTREAM_PULL:
                js = nc.jetstream()
                durable_name = (
                    f"wakir-persona-{env.persona_id}-{subscribe_env}"
                )
                psub = await js.pull_subscribe(
                    subscribe_subject, durable=durable_name,
                )
                engine._log({
                    "level": "INFO",
                    "msg": "subscribe-loop-jetstream-pull-bound",
                    "durable": durable_name,
                })
                while not engine._stop_event.is_set():
                    try:
                        msgs = await psub.fetch(batch=4, timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as exc:  # pragma: no cover
                        engine._log({
                            "level": "ERROR",
                            "msg": "jetstream-fetch-failed",
                            "reason": repr(exc),
                        })
                        continue
                    for msg in msgs:
                        await sub_loop._handle_message(msg)
            else:  # defensive — resolve_subscribe_mode already validated
                engine._log({
                    "level": "ERROR",
                    "msg": "subscribe-mode-unknown",
                    "subscribe_mode": subscribe_mode,
                })
        finally:
            try:
                await nc.drain()
            except Exception:  # pragma: no cover - best-effort
                pass

    engine._subscribe_runner = _live_runner

    engine._log({
        "level": "INFO",
        "msg": "cli-async-dispatch",
        "subscribe_env": subscribe_env,
        "persona_slug": env.persona_id,
        "subscribe_subject": subscribe_subject,
        "nats_url": nats_url,
        "subscribe_mode": subscribe_mode,
        "one_shot": bool(args.one_shot),
    })

    if args.one_shot:
        # Hermetic-test escape hatch: spawn + immediate despawn.
        try:
            await engine.despawn_clean_run()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"despawn-clean-failed: {exc}\n")
            return EXIT_SCHEMA_ERROR
        return EXIT_SUCCESS

    await engine.run_until_signal()
    try:
        await engine.despawn_clean_run()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"despawn-clean-failed: {exc}\n")
        return EXIT_SCHEMA_ERROR
    return EXIT_SUCCESS


def run_spawn(args: argparse.Namespace) -> int:
    """``spawn`` subcommand entry.

    Dispatches to the sync-engine path (backward-compat) or the
    async-engine + subscribe-loop path (Sprint-Pengine-12 Bug-41)
    based on the :data:`SUBSCRIBE_ENV_VAR` env var. The dispatch
    decision is logged to stderr so live-smoke operators can verify
    which path the container actually took.
    """
    subscribe_env = _resolve_async_subscribe_env()
    if subscribe_env is None:
        return _run_spawn_sync(args)
    return asyncio.run(_run_spawn_async(args, subscribe_env))


def run_healthcheck(_args: argparse.Namespace) -> int:
    """``healthcheck`` subcommand entry."""
    # The healthcheck must be cheap (Quadlet runs it every 15s). We
    # check the persona-def bind-mount and the engine version printable;
    # the live spawn-session state-machine state is observed via the
    # marker-stack-kv backend, not via this CLI invocation.
    persona_def_dir = Path("/etc/wakir/persona")
    if not persona_def_dir.is_dir():
        sys.stderr.write(
            f"healthcheck-fail: persona-def dir missing at {persona_def_dir}\n"
        )
        return 1
    return EXIT_SUCCESS


def run_version(_args: argparse.Namespace) -> int:
    """``version`` subcommand entry."""
    sys.stdout.write(f"wakir-persona-engine {ENGINE_VERSION} (real)\n")
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Parser.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree (matches the Sprint-10 Tag-4 stub surface)."""
    p = argparse.ArgumentParser(
        prog="persona-engine",
        description=(
            f"wakir-persona-engine v{ENGINE_VERSION} (real implementation; "
            f"Sprint-Pengine-12). Drives the full spawn-session lifecycle "
            f"with engineering-output emission, bridge-audit double-sink, "
            f"V-907 pin verify, SPIFFE workload-API probe, and (when "
            f"WAKIR_SUBSCRIBE_ENV is set) auto-activated NATS-subscribe "
            f"loop for Bridge-Forward-Pipe auftrag intake."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    spawn = sub.add_parser(
        "spawn",
        help="Spawn the persona (boots, transitions to running, emits output).",
    )
    spawn.add_argument(
        "--persona-slug",
        required=False,
        default=None,
        help=(
            "Persona slug; overrides WAKIR_PERSONA_ID env var if set."
        ),
    )
    spawn.add_argument(
        "--pilot-phase",
        required=False,
        default="doppelbetrieb-shadow",
        help=(
            "Pilot-phase mode tag (informational only — real engine "
            "behaviour is identical across pilot phases)."
        ),
    )
    spawn.add_argument(
        "--one-shot",
        action="store_true",
        default=False,
        help=(
            "Spawn then immediately despawn-clean (hermetic-test mode; "
            "do not use in production)."
        ),
    )
    spawn.set_defaults(func=run_spawn)

    hc = sub.add_parser(
        "healthcheck",
        help="Quadlet HealthCmd= entry; exit 0 iff engine is healthy.",
    )
    hc.set_defaults(func=run_healthcheck)

    ver = sub.add_parser(
        "version",
        help="Print engine version and exit.",
    )
    ver.set_defaults(func=run_version)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover — direct module exec
    raise SystemExit(main())
