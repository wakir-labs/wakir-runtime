# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""CLI entry points for ``persona-engine`` (v0.2.0-pilot).

Matches the CLI surface of the Sprint-10 Tag-4 stub binary
(``spawn`` / ``healthcheck`` / ``version``) so the Quadlet contract
(``Exec=spawn --persona-slug tomas --pilot-phase doppelbetrieb-shadow``)
is byte-stable across the stub-to-real engine swap.

The real ``spawn`` differs from the stub in semantics:

- Stub: reads axis-A, computes ``sha256-stub:`` pin, idles on
  SIGTERM with 30s heartbeats.
- Real: full boot+spawn+run+despawn cycle, emits
  ``engineering_output`` events into the bridge-audit double-sink.

Both honour the same env-var contract (spec §"Env var contract").
"""

from __future__ import annotations

import argparse
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
# Sub-commands.
# ---------------------------------------------------------------------------


def run_spawn(args: argparse.Namespace) -> int:
    """``spawn`` subcommand entry."""
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
            f"Sprint-Pengine-8). Drives the full spawn-session lifecycle "
            f"with engineering-output emission, bridge-audit double-sink, "
            f"V-907 pin verify, and SPIFFE workload-API probe."
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
