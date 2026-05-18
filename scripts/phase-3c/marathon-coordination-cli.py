#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""marathon-coordination-cli — Phase-3 marathon top-level operator CLI.

Tag-43 (Tomás): single entry-point that orchestrates the seven
substrates produced during Tag-40..42:

    * Selin marathon-aggregat-tracker     (state, scripts/phase-3c/)
    * Reza  cross-welle-cutover-generalprobe (dry-run dispatcher)
    * Kai   live-vm-cutover-drill         (Mira-Hand SSH driver)
    * Tomás welle-N-pre-cutover-probe.sh  (per-Welle probes)
    * Tomás phase-3-complete-marker workflow (final marker)

The substrates already exist and each has its own argparse/CLI
surface. This top-level CLI does NOT duplicate that logic — it
wraps the substrates with a uniform sub-command surface tuned for
the operator-day-of marathon workflow (see
``docs/phase-3c/marathon-coordination-cli.md``).

Sub-command surface (all dry-run by default; ``--live`` flag must
be explicit + confirmed for any cutover-execution path):

    marathon status
    marathon probe <welle-N>            [--all]
    marathon dryrun                     [--up-to-welle N]
    marathon cutover <welle-N>          [--dry-run | --live]
    marathon signoff <welle-N> --auditor <name>
    marathon complete-check
    marathon complete                   [--live]

Output formats:
    --format json   structured envelope on stdout
    --format table  ASCII summary on stdout (default)

Exit codes follow the substrate convention:
    0  green / READY / OK
    1  caution / YELLOW (operator decision)
    2  red / BLOCK / FAIL
    3  precond (bad args, missing substrate)
    4  not-exec (sandbox-stub-mode succeeded but live not attempted)

Sandbox-stub-mode
-----------------

The CLI auto-detects whether SSH credentials are present. When run
in CI / Mira-sandbox without ``$WAKIR_PILOT_SSH_KEY`` resolving to
a readable file, all substrates are invoked with
``WAKIR_SSH_BIN=true`` so they exercise their plumbing without
opening a real SSH connection. The ``--live`` flag forces real
substrate execution and refuses to run when SSH stub is active.

Author: Tomás Reinhart (Dev-Engineering / Matrix-Lead),
        Sprint-Tag-43, 2026-05-18.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


SCHEMA_VERSION = 1

#: Valid Welle indexes per ADR-0065 + ADR-0066.
WELLE_INDEXES: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)


#: Per-Welle metadata mirror (must match
#: scripts/phase-3c/marathon-aggregat-tracker.py WELLE_DEFINITIONS).
WELLE_METADATA: Dict[int, Dict[str, str]] = {
    1: {"domain": "v907_verify", "kw": "KW 24", "pair": "welle-2"},
    2: {"domain": "svid_workload_identity", "kw": "KW 24", "pair": "welle-1"},
    3: {"domain": "bridge_audit_writer", "kw": "KW 25", "pair": "solo"},
    4: {"domain": "state_backing", "kw": "KW 26", "pair": "welle-5"},
    5: {"domain": "lifecycle_state_machine", "kw": "KW 26", "pair": "welle-4"},
    6: {"domain": "subscribe_loop", "kw": "KW 27", "pair": "welle-7"},
    7: {"domain": "recovery_workflow", "kw": "KW 27", "pair": "welle-6"},
}


#: Default repo-relative substrate paths. All resolved against
#: ``--repo-root``.
SUBSTRATE_PATHS: Dict[str, str] = {
    "tracker": "scripts/phase-3c/marathon-aggregat-tracker.py",
    "generalprobe": "scripts/phase-3c/cross-welle-cutover-generalprobe.py",
    "drill": "scripts/phase-3c/live-vm-cutover-drill.sh",
    "probe_template": "scripts/phase-3c/welle-{n}-pre-cutover-probe.sh",
    "signoff_template": "state/welle-{n}-sign-off.json",
    "complete_marker": "state/phase-3-complete-marker.json",
}


CONFIRMATION_PHRASE = "I-CONFIRM-LIVE-CUTOVER"


#: Allowed sub-commands. Anything else -> exit-code 3.
SUB_COMMANDS: Tuple[str, ...] = (
    "status",
    "probe",
    "dryrun",
    "cutover",
    "signoff",
    "complete-check",
    "complete",
)


__all__ = [
    "SCHEMA_VERSION",
    "WELLE_INDEXES",
    "WELLE_METADATA",
    "SUBSTRATE_PATHS",
    "SUB_COMMANDS",
    "CONFIRMATION_PHRASE",
    "CLIContext",
    "Envelope",
    "PrecondError",
    "ConfirmationError",
    "validate_welle",
    "detect_sandbox_stub_mode",
    "resolve_substrate",
    "run_substrate",
    "cmd_status",
    "cmd_probe",
    "cmd_dryrun",
    "cmd_cutover",
    "cmd_signoff",
    "cmd_complete_check",
    "cmd_complete",
    "render_envelope",
    "build_parser",
    "main",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PrecondError(Exception):
    """Raised for bad arguments / missing substrate / unknown Welle."""


class ConfirmationError(Exception):
    """Raised when ``--live`` is supplied but confirmation is missing."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_welle(value: Any) -> int:
    """Coerce ``value`` to an int in 1..7 or raise :class:`PrecondError`."""

    try:
        n = int(value)
    except (TypeError, ValueError):
        raise PrecondError(
            f"welle must be an integer in 1..7, got: {value!r}"
        )
    if n not in WELLE_INDEXES:
        raise PrecondError(
            f"welle must be one of {WELLE_INDEXES}, got: {n}"
        )
    return n


def detect_sandbox_stub_mode(env: Optional[Dict[str, str]] = None) -> bool:
    """Return True when SSH credentials are absent or stub is forced.

    The drill substrate already honours ``WAKIR_SSH_BIN=true`` for
    sandbox tests. This helper centralises the decision so the
    top-level CLI emits a consistent ``stub_mode`` field in every
    envelope.
    """

    e = env if env is not None else os.environ
    if e.get("WAKIR_SSH_BIN", "") in ("true", "/bin/true", "/usr/bin/true"):
        return True
    if e.get("WAKIR_FORCE_STUB", "") == "1":
        return True
    key_path = e.get(
        "WAKIR_PILOT_SSH_KEY",
        str(Path.home() / ".ssh" / "wakir-pilot-vm-diagnose"),
    )
    return not Path(key_path).is_file()


def resolve_substrate(repo_root: Path, key: str, welle: Optional[int] = None) -> Path:
    """Resolve a SUBSTRATE_PATHS entry to an absolute path.

    Raises :class:`PrecondError` when ``key`` is unknown or, for
    welle-templated paths, when ``welle`` is missing/invalid.
    """

    if key not in SUBSTRATE_PATHS:
        raise PrecondError(f"unknown substrate key: {key!r}")
    template = SUBSTRATE_PATHS[key]
    if "{n}" in template:
        if welle is None:
            raise PrecondError(
                f"substrate {key!r} requires --welle to resolve"
            )
        validate_welle(welle)
        rel = template.format(n=welle)
    else:
        rel = template
    return repo_root / rel


# ---------------------------------------------------------------------------
# Envelope + Context
# ---------------------------------------------------------------------------


@dataclass
class CLIContext:
    """Resolved invocation context for a sub-command."""

    repo_root: Path
    format: str = "table"
    live: bool = False
    confirm: Optional[str] = None
    stub_mode: bool = False
    env: Dict[str, str] = field(default_factory=dict)
    runner: Optional[Any] = None  # subprocess.run-compatible callable (test seam)

    def runner_call(self, argv: Sequence[str], **kw: Any) -> Any:
        """Dispatch a substrate invocation through the test-seam runner."""

        if self.runner is not None:
            return self.runner(list(argv), **kw)
        return subprocess.run(list(argv), **kw)


@dataclass
class Envelope:
    """Structured result envelope returned by every sub-command."""

    schema_version: int
    command: str
    timestamp_utc: str
    verdict: str  # green | yellow | red | block | ready | pending | error
    stub_mode: bool
    summary: str
    welle: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "command": self.command,
            "timestamp_utc": self.timestamp_utc,
            "verdict": self.verdict,
            "stub_mode": self.stub_mode,
            "summary": self.summary,
            "exit_code": self.exit_code,
        }
        if self.welle is not None:
            d["welle"] = self.welle
        if self.details:
            d["details"] = self.details
        return d


# ---------------------------------------------------------------------------
# Substrate runner
# ---------------------------------------------------------------------------


def run_substrate(
    ctx: CLIContext,
    argv: Sequence[str],
    *,
    capture: bool = True,
    timeout: Optional[float] = None,
) -> Tuple[int, str, str]:
    """Invoke a substrate subprocess via ``ctx``'s runner.

    Returns ``(returncode, stdout, stderr)``. Captures both streams
    when ``capture`` is True (the default). Never raises on non-zero
    exit; callers map exit-codes to envelope verdicts.
    """

    env = os.environ.copy()
    env.update(ctx.env)
    if ctx.stub_mode:
        env.setdefault("WAKIR_SSH_BIN", "true")
        env.setdefault("WAKIR_SCP_BIN", "true")

    kwargs: Dict[str, Any] = {"env": env}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    if timeout is not None:
        kwargs["timeout"] = timeout

    res = ctx.runner_call(list(argv), **kwargs)
    rc = getattr(res, "returncode", 0)
    out = getattr(res, "stdout", "") or ""
    err = getattr(res, "stderr", "") or ""
    return rc, out, err


def _verdict_for_exit_code(rc: int) -> str:
    if rc == 0:
        return "green"
    if rc == 1:
        return "yellow"
    if rc == 2:
        return "red"
    if rc == 3:
        return "precond"
    if rc == 4:
        return "not-exec"
    return "error"


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_status(ctx: CLIContext) -> Envelope:
    """``marathon status`` — render Marathon-Tracker state + dashboard pointer."""

    tracker_path = resolve_substrate(ctx.repo_root, "tracker")
    if not tracker_path.is_file():
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="status",
            timestamp_utc=_utc_now(),
            verdict="precond",
            stub_mode=ctx.stub_mode,
            summary=f"marathon-aggregat-tracker not found at {tracker_path}",
            exit_code=3,
        )

    rc, out, err = run_substrate(
        ctx,
        [
            sys.executable,
            str(tracker_path),
            "--repo-root",
            str(ctx.repo_root),
            "--show-marathon",
        ],
    )

    welle_states: Dict[int, str] = {}
    for line in out.splitlines():
        # The tracker prints "Welle N | <state> | ..." style rows.
        s = line.strip()
        if s.startswith("Welle "):
            parts = [p.strip() for p in s.split("|")]
            if len(parts) >= 2:
                try:
                    n = int(parts[0].split()[1])
                    welle_states[n] = parts[1]
                except (IndexError, ValueError):
                    pass

    pending = sum(1 for v in welle_states.values() if "pending" in v.lower())
    complete = sum(1 for v in welle_states.values() if "complete" in v.lower())

    verdict = _verdict_for_exit_code(rc)
    summary = (
        f"tracker rc={rc}; welles_seen={len(welle_states)}; "
        f"pending={pending}; complete={complete}"
    )
    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="status",
        timestamp_utc=_utc_now(),
        verdict=verdict,
        stub_mode=ctx.stub_mode,
        summary=summary,
        details={
            "tracker_rc": rc,
            "tracker_stdout_lines": len(out.splitlines()),
            "tracker_stderr_lines": len(err.splitlines()),
            "welle_states": welle_states,
            "dashboard_workflow": (
                ".github/workflows/phase-3c-pre-cutover-marathon-dashboard.yml"
            ),
        },
        exit_code=rc if rc in (0, 1, 2, 3, 4) else 2,
    )


def cmd_probe(
    ctx: CLIContext,
    welle: Optional[int] = None,
    all_welles: bool = False,
) -> Envelope:
    """``marathon probe <N>`` or ``marathon probe --all``."""

    if all_welles:
        targets: List[int] = list(WELLE_INDEXES)
    else:
        if welle is None:
            raise PrecondError("probe requires --welle <N> or --all")
        targets = [validate_welle(welle)]

    per_welle: List[Dict[str, Any]] = []
    worst_rc = 0
    missing = 0

    for n in targets:
        probe_path = resolve_substrate(ctx.repo_root, "probe_template", n)
        if not probe_path.is_file():
            per_welle.append(
                {
                    "welle": n,
                    "rc": 3,
                    "verdict": "precond",
                    "summary": f"probe script missing: {probe_path.name}",
                }
            )
            missing += 1
            worst_rc = max(worst_rc, 3)
            continue

        # Sandbox-stub: probes accept --dry-run for hermetic plumbing.
        argv = ["bash", str(probe_path), "--dry-run"]
        rc, out, err = run_substrate(ctx, argv)
        per_welle.append(
            {
                "welle": n,
                "rc": rc,
                "verdict": _verdict_for_exit_code(rc),
                "stdout_lines": len(out.splitlines()),
                "stderr_lines": len(err.splitlines()),
            }
        )
        # Probe rc=4 (not-exec) is non-blocking per Tag-41 AR-direktive.
        if rc == 4:
            worst_rc = max(worst_rc, 0)
        else:
            worst_rc = max(worst_rc, rc)

    green = sum(1 for x in per_welle if x["rc"] == 0)
    not_exec = sum(1 for x in per_welle if x["rc"] == 4)

    summary = (
        f"probes_run={len(per_welle)}; green={green}; "
        f"not_exec={not_exec}; missing={missing}"
    )
    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="probe",
        timestamp_utc=_utc_now(),
        verdict=_verdict_for_exit_code(worst_rc),
        stub_mode=ctx.stub_mode,
        summary=summary,
        welle=None if all_welles else targets[0],
        details={"per_welle": per_welle, "all": all_welles},
        exit_code=worst_rc if worst_rc in (0, 1, 2, 3, 4) else 2,
    )


def cmd_dryrun(
    ctx: CLIContext,
    up_to_welle: Optional[int] = None,
) -> Envelope:
    """``marathon dryrun`` — invoke Reza's cross-welle generalprobe."""

    gp_path = resolve_substrate(ctx.repo_root, "generalprobe")
    if not gp_path.is_file():
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="dryrun",
            timestamp_utc=_utc_now(),
            verdict="precond",
            stub_mode=ctx.stub_mode,
            summary=f"cross-welle generalprobe not found at {gp_path}",
            exit_code=3,
        )

    argv = [sys.executable, str(gp_path), "--dry-run"]
    if up_to_welle is not None:
        n = validate_welle(up_to_welle)
        argv += ["--up-to-welle", str(n)]

    rc, out, err = run_substrate(ctx, argv)

    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="dryrun",
        timestamp_utc=_utc_now(),
        verdict=_verdict_for_exit_code(rc),
        stub_mode=ctx.stub_mode,
        summary=(
            f"generalprobe rc={rc}; "
            f"up_to_welle={up_to_welle if up_to_welle else 'all'}"
        ),
        details={
            "rc": rc,
            "stdout_lines": len(out.splitlines()),
            "stderr_lines": len(err.splitlines()),
            "up_to_welle": up_to_welle,
        },
        exit_code=rc if rc in (0, 1, 2, 3, 4) else 2,
    )


def _live_guard(ctx: CLIContext) -> None:
    """Validate that ``--live`` invocations carry the confirmation token.

    Refuses to run when sandbox-stub is active (no SSH key).
    """

    if not ctx.live:
        return
    if ctx.stub_mode:
        raise ConfirmationError(
            "--live refused: sandbox-stub-mode active "
            "(SSH key absent or WAKIR_SSH_BIN=true)"
        )
    if ctx.confirm != CONFIRMATION_PHRASE:
        raise ConfirmationError(
            f"--live requires --confirm {CONFIRMATION_PHRASE!r}"
        )


def cmd_cutover(
    ctx: CLIContext,
    welle: int,
    live: bool = False,
) -> Envelope:
    """``marathon cutover <N>`` — dispatch Kai's live-vm-cutover-drill."""

    n = validate_welle(welle)
    drill_path = resolve_substrate(ctx.repo_root, "drill")
    if not drill_path.is_file():
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="cutover",
            timestamp_utc=_utc_now(),
            verdict="precond",
            stub_mode=ctx.stub_mode,
            summary=f"live-vm-cutover-drill not found at {drill_path}",
            welle=n,
            exit_code=3,
        )

    # Re-apply the live-guard. ctx.live carries the original flag;
    # this call may override it.
    if live and not ctx.live:
        ctx.live = True
    _live_guard(ctx)

    action_flag = "--live" if ctx.live else "--dry-run"
    argv = [
        "bash",
        str(drill_path),
        "--welle",
        str(n),
        "--action",
        "pre",
        action_flag,
    ]
    rc, out, err = run_substrate(ctx, argv)

    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="cutover",
        timestamp_utc=_utc_now(),
        verdict=_verdict_for_exit_code(rc),
        stub_mode=ctx.stub_mode,
        summary=(
            f"drill welle-{n} action=pre mode={'live' if ctx.live else 'dry-run'} "
            f"rc={rc}"
        ),
        welle=n,
        details={
            "rc": rc,
            "mode": "live" if ctx.live else "dry-run",
            "stdout_lines": len(out.splitlines()),
            "stderr_lines": len(err.splitlines()),
        },
        exit_code=rc if rc in (0, 1, 2, 3, 4) else 2,
    )


def cmd_signoff(
    ctx: CLIContext,
    welle: int,
    auditor: str,
) -> Envelope:
    """``marathon signoff <N> --auditor <name>`` — write sign-off marker."""

    n = validate_welle(welle)
    if not auditor or not auditor.strip():
        raise PrecondError("signoff requires --auditor <name>")

    signoff_path = ctx.repo_root / SUBSTRATE_PATHS["signoff_template"].format(n=n)
    signoff_path.parent.mkdir(parents=True, exist_ok=True)

    if signoff_path.exists():
        # Idempotent: keep existing marker, surface as yellow.
        existing = json.loads(signoff_path.read_text(encoding="utf-8"))
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="signoff",
            timestamp_utc=_utc_now(),
            verdict="yellow",
            stub_mode=ctx.stub_mode,
            summary=(
                f"welle-{n} sign-off already exists "
                f"(auditor={existing.get('auditor', 'unknown')})"
            ),
            welle=n,
            details={"existing": existing, "path": str(signoff_path)},
            exit_code=1,
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "welle": n,
        "domain": WELLE_METADATA[n]["domain"],
        "kw": WELLE_METADATA[n]["kw"],
        "status": "green",
        "auditor": auditor.strip(),
        "signed_off_utc": _utc_now(),
        "source": "marathon-coordination-cli",
    }
    signoff_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="signoff",
        timestamp_utc=_utc_now(),
        verdict="green",
        stub_mode=ctx.stub_mode,
        summary=f"welle-{n} signed off by {auditor.strip()}",
        welle=n,
        details={"path": str(signoff_path), "payload": payload},
        exit_code=0,
    )


def cmd_complete_check(ctx: CLIContext) -> Envelope:
    """``marathon complete-check`` — dry-run Phase-3-COMPLETE marker readiness."""

    # AC-1: all seven welle sign-offs present.
    missing: List[int] = []
    found: List[int] = []
    for n in WELLE_INDEXES:
        p = ctx.repo_root / SUBSTRATE_PATHS["signoff_template"].format(n=n)
        if p.is_file():
            found.append(n)
        else:
            missing.append(n)

    # AC-2: complete-marker workflow YAML present.
    workflow_path = (
        ctx.repo_root
        / ".github"
        / "workflows"
        / "phase-3-complete-marker.yml"
    )
    workflow_present = workflow_path.is_file()

    # AC-3: existing marker would be re-written?
    marker_path = ctx.repo_root / SUBSTRATE_PATHS["complete_marker"]
    marker_exists = marker_path.is_file()

    all_signed = not missing
    ready = all_signed and workflow_present and not marker_exists

    rc = 0 if ready else (1 if all_signed else 2)
    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="complete-check",
        timestamp_utc=_utc_now(),
        verdict="ready" if ready else ("yellow" if all_signed else "red"),
        stub_mode=ctx.stub_mode,
        summary=(
            f"signoffs={len(found)}/7; missing={missing}; "
            f"workflow={'present' if workflow_present else 'MISSING'}; "
            f"marker_exists={marker_exists}"
        ),
        details={
            "signed": found,
            "missing": missing,
            "workflow_present": workflow_present,
            "marker_exists": marker_exists,
            "ready": ready,
        },
        exit_code=rc,
    )


def cmd_complete(ctx: CLIContext) -> Envelope:
    """``marathon complete`` — write Phase-3-COMPLETE marker (live only)."""

    _live_guard(ctx)

    check = cmd_complete_check(ctx)
    if check.exit_code != 0 and not ctx.live:
        # Dry-run preview: return the check verdict verbatim.
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="complete",
            timestamp_utc=_utc_now(),
            verdict=check.verdict,
            stub_mode=ctx.stub_mode,
            summary=f"complete-check would block: {check.summary}",
            details={"check": check.to_dict(), "mode": "preview"},
            exit_code=check.exit_code,
        )

    if not ctx.live:
        # Dry-run: report what would happen but do not write.
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="complete",
            timestamp_utc=_utc_now(),
            verdict="ready",
            stub_mode=ctx.stub_mode,
            summary="complete-check green; --live would write marker",
            details={"check": check.to_dict(), "mode": "preview"},
            exit_code=0,
        )

    # Live path: refuse to overwrite an existing marker.
    marker_path = ctx.repo_root / SUBSTRATE_PATHS["complete_marker"]
    if marker_path.is_file():
        return Envelope(
            schema_version=SCHEMA_VERSION,
            command="complete",
            timestamp_utc=_utc_now(),
            verdict="yellow",
            stub_mode=ctx.stub_mode,
            summary=f"marker already present at {marker_path}",
            details={"path": str(marker_path), "mode": "live"},
            exit_code=1,
        )

    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "phase": "phase-3",
        "status": "complete",
        "completed_utc": _utc_now(),
        "wellen": [
            {
                "welle": n,
                "domain": WELLE_METADATA[n]["domain"],
                "kw": WELLE_METADATA[n]["kw"],
            }
            for n in WELLE_INDEXES
        ],
        "source": "marathon-coordination-cli",
        "confirm_token": CONFIRMATION_PHRASE,
    }
    marker_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return Envelope(
        schema_version=SCHEMA_VERSION,
        command="complete",
        timestamp_utc=_utc_now(),
        verdict="green",
        stub_mode=ctx.stub_mode,
        summary=f"Phase-3-COMPLETE marker written to {marker_path}",
        details={"path": str(marker_path), "mode": "live", "payload": payload},
        exit_code=0,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_table(env: Envelope) -> str:
    """Render an envelope as an ASCII summary block."""

    lines = [
        "=" * 64,
        f"Marathon-Coordination-CLI :: {env.command}",
        "=" * 64,
        f"timestamp_utc : {env.timestamp_utc}",
        f"verdict       : {env.verdict}",
        f"exit_code     : {env.exit_code}",
        f"stub_mode     : {env.stub_mode}",
    ]
    if env.welle is not None:
        lines.append(f"welle         : {env.welle}")
    lines.append(f"summary       : {env.summary}")
    if env.details:
        lines.append("details:")
        # Per-welle table for probe --all
        per_welle = env.details.get("per_welle")
        if isinstance(per_welle, list) and per_welle:
            lines.append("  welle | rc | verdict")
            lines.append("  ------+----+--------")
            for row in per_welle:
                lines.append(
                    f"  {row.get('welle', '?'):>5} | "
                    f"{row.get('rc', '?'):>2} | "
                    f"{row.get('verdict', '?')}"
                )
        else:
            for k, v in env.details.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    lines.append(f"  {k} = {v}")
                else:
                    lines.append(f"  {k} = (complex; see --format json)")
    lines.append("=" * 64)
    return "\n".join(lines) + "\n"


def render_envelope(env: Envelope, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(env.to_dict(), indent=2, sort_keys=True) + "\n"
    if fmt == "table":
        return _render_table(env)
    raise PrecondError(f"unknown --format: {fmt!r}")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="marathon",
        description=(
            "Phase-3 marathon top-level operator CLI. Wraps tracker / "
            "generalprobe / drill / probes / complete-marker into one "
            "sub-command surface. See "
            "docs/phase-3c/marathon-coordination-cli.md."
        ),
    )
    p.add_argument(
        "--repo-root",
        default=None,
        help="Override repo root. Default: current working directory.",
    )
    p.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format. Default: table.",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help=(
            "Execute against the live VM (drill --live or marker --live). "
            f"Requires --confirm {CONFIRMATION_PHRASE!r} and a real SSH key."
        ),
    )
    p.add_argument(
        "--confirm",
        default=None,
        help=f"Confirmation token for --live. Must equal {CONFIRMATION_PHRASE!r}.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show marathon tracker state + aggregate")

    p_probe = sub.add_parser(
        "probe", help="Run per-Welle Pre-Cutover-Sanity-Probe(s)"
    )
    g = p_probe.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--welle",
        type=int,
        help="Welle index to probe (1..7).",
    )
    g.add_argument(
        "--all",
        action="store_true",
        help="Probe all seven Wellen and aggregate verdict.",
    )

    p_dry = sub.add_parser(
        "dryrun", help="Run Reza's cross-welle cutover generalprobe (dry-run)"
    )
    p_dry.add_argument(
        "--up-to-welle",
        type=int,
        default=None,
        help="Truncate the marathon at Welle N. Default: all seven.",
    )

    p_co = sub.add_parser(
        "cutover", help="Dispatch Kai's live-vm-cutover-drill for one Welle"
    )
    p_co.add_argument("--welle", type=int, required=True, help="Welle index 1..7.")
    co_mode = p_co.add_mutually_exclusive_group()
    co_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute drill in dry-run mode (default).",
    )
    co_mode.add_argument(
        "--live",
        dest="cutover_live",
        action="store_true",
        help=(
            "Execute drill against the live VM. Requires top-level "
            "--live + --confirm."
        ),
    )

    p_so = sub.add_parser(
        "signoff", help="Record an operator/auditor sign-off for one Welle"
    )
    p_so.add_argument("--welle", type=int, required=True, help="Welle index 1..7.")
    p_so.add_argument(
        "--auditor",
        required=True,
        help="Name of the ratifying person.",
    )

    sub.add_parser(
        "complete-check",
        help="Dry-run check that Phase-3-COMPLETE marker readiness is satisfied",
    )

    sub.add_parser(
        "complete",
        help=(
            "Write the Phase-3-COMPLETE marker. Without --live this is "
            "a preview that does not touch the filesystem."
        ),
    )

    return p


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None, *, runner: Optional[Any] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse exits with code 2 on bad usage; remap to 3 (precond)
        # so callers can distinguish from substrate red.
        return 3 if e.code in (2, None) else int(e.code or 0)

    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()
    stub_mode = detect_sandbox_stub_mode()

    ctx = CLIContext(
        repo_root=repo_root,
        format=args.format,
        live=bool(args.live),
        confirm=args.confirm,
        stub_mode=stub_mode,
        runner=runner,
    )

    try:
        if args.command == "status":
            env = cmd_status(ctx)
        elif args.command == "probe":
            env = cmd_probe(
                ctx,
                welle=args.welle,
                all_welles=bool(getattr(args, "all", False)),
            )
        elif args.command == "dryrun":
            env = cmd_dryrun(ctx, up_to_welle=args.up_to_welle)
        elif args.command == "cutover":
            cutover_live = bool(getattr(args, "cutover_live", False))
            if cutover_live and not ctx.live:
                # The sub-command --live shorthand still needs the
                # top-level --live + --confirm for safety.
                sys.stderr.write(
                    "cutover --live requires top-level --live --confirm "
                    f"{CONFIRMATION_PHRASE!r}\n"
                )
                return 3
            env = cmd_cutover(ctx, welle=args.welle, live=cutover_live or ctx.live)
        elif args.command == "signoff":
            env = cmd_signoff(ctx, welle=args.welle, auditor=args.auditor)
        elif args.command == "complete-check":
            env = cmd_complete_check(ctx)
        elif args.command == "complete":
            env = cmd_complete(ctx)
        else:  # pragma: no cover - argparse enforces choices
            sys.stderr.write(f"unknown command: {args.command!r}\n")
            return 3
    except PrecondError as exc:
        sys.stderr.write(f"precond: {exc}\n")
        return 3
    except ConfirmationError as exc:
        sys.stderr.write(f"confirmation: {exc}\n")
        return 3

    sys.stdout.write(render_envelope(env, ctx.format))
    return env.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
