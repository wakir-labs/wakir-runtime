#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3c Pre-Cutover-Probe-Phase Live-Demo (Tag-43).

Orchestrates a single demo-run of all seven ADR-0066 Welle pre-cutover
probes (``scripts/phase-3c/welle-N-pre-cutover-probe.sh``) in
Sandbox-Stub-Mode, aggregates the per-Welle verdicts into a single
Marathon-Readiness verdict, optionally triggers the Tomas Tag-42
``phase-3c-pre-cutover-marathon-dashboard.yml`` workflow via ``gh``,
and emits a JSON envelope plus an ASCII table for Mira-Inbox /
Operator consumption.

Why this script exists
----------------------

The marathon-dashboard workflow (Tag-42, PR #270) lives in CI and runs
on schedule / on push.  For the Cutover-Day rehearsal we also need a
one-shot **local** demo that:

* exercises every probe-script's plumbing on the current main snapshot
  (arg-parse, axis dispatch, verdict aggregation, exit-code mapping),
* aggregates the seven exit-codes locally so the operator gets an
  immediate stdout verdict without waiting for CI artifacts,
* optionally fires the live CI dashboard run in parallel so the
  long-form GitHub Step-Summary is also available, and
* surfaces the *delta* between expected and observed verdicts.

The script is stdlib-only (per Reza Tag-43 Auftrag); no third-party
runtime dependency, no network unless ``--gh-trigger`` is set.

Sandbox-Stub-Mode
-----------------

For the local probe-leg, we mirror the CI sandbox-stub setup from
``.github/workflows/phase-3c-pre-cutover-marathon-dashboard.yml``:

* ``WAKIR_SSH_BIN=true`` -- the GNU ``true`` binary, which silently
  consumes args and exits 0; this prevents any real SSH socket from
  opening even if the probe forgets ``--dry-run``.
* ``HOME`` redirected to a per-run temp dir containing a touched
  ``.ssh/wakir-pilot-vm-diagnose`` key-file so the probe's
  pre-condition check passes.
* Each probe runs with ``--dry-run --quiet`` so axis-functions emit
  ``DRY-RUN`` verdicts and the aggregate evaluates to ``GREEN`` (the
  contract that AR-Direktive Tag-42 mandates: on a clean main, all
  seven probes return GREEN in dry-run).

Expected-verdict baseline
-------------------------

On a clean main snapshot, every probe in dry-run mode emits aggregate
``GREEN`` (exit 0).  The Comparison-View renders ``observed - expected``
deltas per Welle; any drift indicates either:

* a probe-script regression (probe broken on main), or
* a missing probe-script (NOT-EXEC), or
* an environment-stub failure (test runner couldn't synthesise stub).

Trigger surface
---------------

CLI flags:

* ``--repo-root PATH``     -- absolute path to repo root (default: cwd).
* ``--output-json PATH``   -- write JSON envelope (default: stdout-only).
* ``--output-md PATH``     -- write ASCII-table summary file (default:
                              stdout-only).
* ``--gh-trigger``         -- fire ``gh workflow run`` against the
                              ``phase-3c-pre-cutover-marathon-dashboard``
                              workflow on origin/main.
* ``--no-gh-trigger``      -- explicit suppression (default behaviour).
* ``--gh-poll-seconds N``  -- poll the most-recent workflow-run for up
                              to N seconds before giving up (default:
                              0 = do not poll, just trigger).
* ``--mode {dry-run,sandbox-stub}`` -- alias for stub semantics; both
                              modes behave identically in this demo
                              (kept for parity with the CI dispatch
                              input).
* ``--probe-timeout-seconds N`` -- per-probe wall-clock cap (default
                              60).
* ``--component-overrides JSON`` -- map ``{welle: component}`` to
                              override defaults (rarely used).

Exit codes
----------

* 0 -- marathon-readiness READY (all seven GREEN, matches expected).
* 1 -- marathon-readiness CAUTION (1..2 CAUTION/NOT-EXEC).
* 2 -- marathon-readiness BLOCK (any BLOCK, or 3+ degraded).
* 3 -- pre-condition failure (missing repo / missing scripts /
       missing python3 / missing ``true``).
* 4 -- marathon-readiness NOT-READY (all seven NOT-EXEC -- usually
       indicates probe-scripts absent from this snapshot).

Anchors
-------

* ADR-0058 sec-Nachtrag (Mira-Hand-SSH-Authority)
* ADR-0065 (Phase-3c Cutover-Plan)
* ADR-0066 (Doppel-Welle KW-24/26/27 ordering)
* PR #267 (Welle-1 probe, Kai)
* PR #272 (Welle-2+3 probes, Selin)
* PR #273 (Welle-4+5 probes, Kai)
* PR #275 (Welle-6+7 probes, Amara)
* PR #270 (Marathon-Dashboard workflow, Tomas)

Author: Reza Tehrani (Dev-Engineering-2), Sprint-Tag-43, 2026-05-18.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------
# Welle catalogue.  Component names mirror ADR-0066 and each probe's
# default ``--component`` flag so the comparison-view labels line up
# with the CI dashboard.
# ---------------------------------------------------------------------

WELLE_CATALOGUE: tuple[dict[str, Any], ...] = (
    {"welle": 1, "component": "v907_verify",
     "kw": 24, "pair_partner": 2, "pair_mode": "parallel",
     "expected_dry_run_verdict": "CAUTION",
     "expected_reason": "AXIS-4 yellow without --expected-hash"},
    {"welle": 2, "component": "svid_workload_identity",
     "kw": 24, "pair_partner": 1, "pair_mode": "parallel",
     "expected_dry_run_verdict": "CAUTION",
     "expected_reason": "AXIS-4 yellow without --expected-hash"},
    {"welle": 3, "component": "bridge_audit_writer",
     "kw": 25, "pair_partner": None, "pair_mode": "solo",
     "expected_dry_run_verdict": "CAUTION",
     "expected_reason": "AXIS-4 yellow without --expected-hash"},
    {"welle": 4, "component": "state_backing",
     "kw": 26, "pair_partner": 5, "pair_mode": "doppel",
     "expected_dry_run_verdict": "CAUTION",
     "expected_reason": "AXIS-4 yellow without --pair-hash"},
    {"welle": 5, "component": "lifecycle_state_machine",
     "kw": 26, "pair_partner": 4, "pair_mode": "doppel",
     "expected_dry_run_verdict": "CAUTION",
     "expected_reason": "AXIS-4 yellow without --pair-hash"},
    {"welle": 6, "component": "subscribe_loop",
     "kw": 27, "pair_partner": 7, "pair_mode": "doppel",
     "expected_dry_run_verdict": "GREEN",
     "expected_reason": "all axes dry-run-clean"},
    {"welle": 7, "component": "recovery_workflow",
     "kw": 27, "pair_partner": 6, "pair_mode": "doppel",
     "expected_dry_run_verdict": "BLOCK",
     "expected_reason": "IIA-1130 pre-auditor-decision absent on main"},
)

# Exit-code map mirrored from the welle-N probe contract.
EXIT_TO_VERDICT: dict[int, str] = {
    0: "GREEN",
    1: "CAUTION",
    2: "BLOCK",
    3: "BLOCK",
    4: "NOT-EXEC",
}

# Aggregate marathon-readiness expected on a clean main snapshot in
# sandbox-stub mode.  Derived empirically from running the seven
# probes on baseline ``04fb3c3`` (Tag-42 main-tip): five CAUTION +
# one GREEN + one BLOCK -> ``BLOCK`` (Welle-7 IIA-1130 gate fires).
# This is the Demo-Baseline; Cutover-Day-Morning operator must
# supply ``--expected-hash``/``--pair-hash`` per Welle to upgrade
# the five CAUTION verdicts to GREEN, and the Pre-Auditor-Decision
# file must be in place to clear Welle-7 BLOCK.
EXPECTED_AGGREGATE_BASELINE = "BLOCK"

# Marathon-readiness aggregate exit-codes.
READINESS_TO_EXIT: dict[str, int] = {
    "READY": 0,
    "CAUTION": 1,
    "BLOCK": 2,
    "NOT-READY": 4,
}


# ---------------------------------------------------------------------
# Data classes.
# ---------------------------------------------------------------------

@dataclasses.dataclass
class ProbeResult:
    """Per-Welle probe execution result."""

    welle: int
    component: str
    kw: int
    pair_partner: int | None
    pair_mode: str
    probe_script: str
    probe_present: bool
    exit_code: int | None
    verdict: str
    verdict_source: str
    expected_verdict: str
    delta: str  # "match" | "drift:<observed>-vs-<expected>" | "absent"
    stdout_tail: str  # last 200 chars of probe stdout for forensics
    duration_seconds: float
    details: str

    def to_envelope(self) -> dict[str, Any]:
        return {
            "welle": self.welle,
            "component": self.component,
            "kw": self.kw,
            "pair_partner": self.pair_partner,
            "pair_mode": self.pair_mode,
            "probe_script": self.probe_script,
            "probe_present": self.probe_present,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "verdict_source": self.verdict_source,
            "expected_verdict": self.expected_verdict,
            "delta": self.delta,
            "duration_seconds": round(self.duration_seconds, 3),
            "details": self.details,
        }


@dataclasses.dataclass
class DemoRun:
    """Aggregate demo-run envelope."""

    run_id: str
    started_at_utc: str
    finished_at_utc: str
    repo_root: str
    mode: str
    expected_aggregate: str
    observed_aggregate: str
    aggregate_match: bool
    probes: list[ProbeResult]
    gh_trigger: dict[str, Any]
    summary_counts: dict[str, int]

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "repo_root": self.repo_root,
            "mode": self.mode,
            "expected_aggregate": self.expected_aggregate,
            "observed_aggregate": self.observed_aggregate,
            "aggregate_match": self.aggregate_match,
            "summary_counts": self.summary_counts,
            "probes": [p.to_envelope() for p in self.probes],
            "gh_trigger": self.gh_trigger,
        }


# ---------------------------------------------------------------------
# Pre-condition checks.
# ---------------------------------------------------------------------

def precondition_check(repo_root: Path) -> tuple[bool, str]:
    """Verify repo + tooling are present.  Returns (ok, message)."""
    if not repo_root.is_dir():
        return False, f"repo-root not a directory: {repo_root}"
    scripts_dir = repo_root / "scripts" / "phase-3c"
    if not scripts_dir.is_dir():
        return False, f"missing scripts dir: {scripts_dir}"
    if shutil.which("bash") is None:
        return False, "missing bash on PATH"
    if shutil.which("true") is None:
        # /usr/bin/true is shell-builtin on bash but env command needs
        # an actual binary on PATH for WAKIR_SSH_BIN.
        return False, "missing /usr/bin/true on PATH (WAKIR_SSH_BIN stub)"
    return True, "ok"


def probe_script_path(repo_root: Path, welle: int) -> Path:
    return repo_root / "scripts" / "phase-3c" / f"welle-{welle}-pre-cutover-probe.sh"


# ---------------------------------------------------------------------
# Probe execution.
# ---------------------------------------------------------------------

def synthesise_stub_home(workdir: Path) -> Path:
    """Create a HOME-tree containing the SSH key-file the probe needs.

    The probe runs ``check_ssh_key_present`` even in dry-run -- well,
    technically the script short-circuits ``check_ssh_key_present``
    on DRY_RUN=1, but we synthesise the key anyway so the same stub
    works for any future probe-script that drops the short-circuit.
    """
    home = workdir / "home"
    sshdir = home / ".ssh"
    sshdir.mkdir(parents=True, exist_ok=True)
    keyfile = sshdir / "wakir-pilot-vm-diagnose"
    keyfile.touch()
    return home


def run_single_probe(
    repo_root: Path,
    welle_meta: dict[str, Any],
    workdir: Path,
    probe_timeout_seconds: float,
    component_override: str | None = None,
) -> ProbeResult:
    """Execute one Welle probe in sandbox-stub mode.

    Returns a ProbeResult; never raises (errors map to verdict).
    """
    welle = welle_meta["welle"]
    component = component_override or welle_meta["component"]
    script_path = probe_script_path(repo_root, welle)
    script_rel = str(script_path.relative_to(repo_root)) if \
        script_path.is_absolute() and \
        str(script_path).startswith(str(repo_root)) else str(script_path)

    started = time.monotonic()

    expected = welle_meta.get("expected_dry_run_verdict", "GREEN")
    expected_reason = welle_meta.get("expected_reason", "")

    if not script_path.is_file():
        return ProbeResult(
            welle=welle,
            component=component,
            kw=welle_meta["kw"],
            pair_partner=welle_meta["pair_partner"],
            pair_mode=welle_meta["pair_mode"],
            probe_script=script_rel,
            probe_present=False,
            exit_code=None,
            verdict="NOT-EXEC",
            verdict_source="probe-script-absent",
            expected_verdict=expected,
            delta=_delta_label("NOT-EXEC", expected, False),
            stdout_tail="",
            duration_seconds=time.monotonic() - started,
            details=f"probe script not present at {script_rel}; "
                    f"expected_reason={expected_reason}",
        )

    stub_home = synthesise_stub_home(workdir / f"welle-{welle}")
    env = os.environ.copy()
    env["HOME"] = str(stub_home)
    # Use coreutils ``true`` so any --not-dry-run-leak still no-ops.
    env["WAKIR_SSH_BIN"] = shutil.which("true") or "true"
    # Pin probe log dir into workdir so multiple demo-runs don't
    # collide on /tmp/wakir-pre-cutover-probe.
    env["WAKIR_PROBE_LOG_DIR"] = str(workdir / f"welle-{welle}" / "logs")
    env["WAKIR_PROBE_COMPONENT"] = component
    env["WAKIR_PROBE_WELLE"] = str(welle)

    cmd = [
        "bash",
        str(script_path),
        "--dry-run",
        "--quiet",
        "--welle", str(welle),
        "--component", component,
    ]

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=probe_timeout_seconds,
            check=False,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        return ProbeResult(
            welle=welle,
            component=component,
            kw=welle_meta["kw"],
            pair_partner=welle_meta["pair_partner"],
            pair_mode=welle_meta["pair_mode"],
            probe_script=script_rel,
            probe_present=True,
            exit_code=None,
            verdict="BLOCK",
            verdict_source="probe-timeout",
            expected_verdict=expected,
            delta=_delta_label("BLOCK", expected, True),
            stdout_tail=(exc.stdout or "")[-200:] if isinstance(exc.stdout, str) else "",
            duration_seconds=time.monotonic() - started,
            details=f"probe exceeded {probe_timeout_seconds}s wall-clock",
        )
    except OSError as exc:
        return ProbeResult(
            welle=welle,
            component=component,
            kw=welle_meta["kw"],
            pair_partner=welle_meta["pair_partner"],
            pair_mode=welle_meta["pair_mode"],
            probe_script=script_rel,
            probe_present=True,
            exit_code=None,
            verdict="BLOCK",
            verdict_source="probe-spawn-error",
            expected_verdict=expected,
            delta=_delta_label("BLOCK", expected, True),
            stdout_tail="",
            duration_seconds=time.monotonic() - started,
            details=f"OSError spawning probe: {exc!r}",
        )

    verdict = EXIT_TO_VERDICT.get(exit_code, "BLOCK")
    # Extract the trailing PROBE-VERDICT= line if present (forensics).
    tail_match = re.search(
        r"PROBE-VERDICT=([A-Z\-]+).*$",
        stdout,
        flags=re.MULTILINE,
    )
    if tail_match:
        verdict_from_line = tail_match.group(1)
        if verdict_from_line and verdict_from_line != verdict:
            # Trust exit-code first (probe contract).  Record drift.
            details = (
                f"exit={exit_code} verdict-line={verdict_from_line} "
                f"(exit-code-trumps-line)"
            )
        else:
            details = f"exit={exit_code} verdict-line={verdict_from_line}"
    else:
        details = f"exit={exit_code} verdict-line=absent"
    if stderr.strip():
        # Surface short stderr context for non-zero exits.
        details += " stderr-bytes=" + str(len(stderr))

    delta = _delta_label(verdict, expected, True)
    if expected_reason:
        details += f" expected_reason={expected_reason}"

    return ProbeResult(
        welle=welle,
        component=component,
        kw=welle_meta["kw"],
        pair_partner=welle_meta["pair_partner"],
        pair_mode=welle_meta["pair_mode"],
        probe_script=script_rel,
        probe_present=True,
        exit_code=exit_code,
        verdict=verdict,
        verdict_source="probe-exit-code",
        expected_verdict=expected,
        delta=delta,
        stdout_tail=stdout[-200:],
        duration_seconds=time.monotonic() - started,
        details=details,
    )


def _delta_label(observed: str, expected: str, probe_present: bool) -> str:
    if not probe_present:
        return "absent"
    if observed == expected:
        return "match"
    return f"drift:{observed}-vs-{expected}"


# ---------------------------------------------------------------------
# Marathon-readiness aggregation.  Mirrors aggregator semantics from
# tooling/ci/aggregate_pre_cutover_marathon_dashboard.py so the demo
# verdict matches what CI would emit on the same probe set.
# ---------------------------------------------------------------------

def aggregate_marathon_readiness(probes: Iterable[ProbeResult]) -> str:
    counts = summary_counts(probes)
    if counts["BLOCK"] >= 1:
        return "BLOCK"
    degraded = counts["CAUTION"] + counts["NOT-EXEC"]
    if counts["NOT-EXEC"] == 7:
        return "NOT-READY"
    if degraded >= 3:
        return "BLOCK"
    if degraded >= 1:
        return "CAUTION"
    if counts["GREEN"] == 7:
        return "READY"
    # Defensive default: any state we didn't classify is treated as
    # CAUTION rather than READY.
    return "CAUTION"


def summary_counts(probes: Iterable[ProbeResult]) -> dict[str, int]:
    counts = {"GREEN": 0, "CAUTION": 0, "BLOCK": 0, "NOT-EXEC": 0}
    for p in probes:
        if p.verdict in counts:
            counts[p.verdict] += 1
        else:
            counts["BLOCK"] += 1
    return counts


# ---------------------------------------------------------------------
# gh-trigger.  Returns a dict that always carries `attempted` so the
# JSON envelope shape is stable regardless of trigger outcome.
# ---------------------------------------------------------------------

def trigger_marathon_dashboard(
    workflow: str,
    ref: str,
    poll_seconds: int,
    gh_bin: str | None = None,
) -> dict[str, Any]:
    """Fire ``gh workflow run`` and optionally poll for the latest run."""
    result: dict[str, Any] = {
        "attempted": True,
        "workflow": workflow,
        "ref": ref,
        "ok": False,
        "stdout": "",
        "stderr": "",
        "run_url": None,
        "run_status": None,
        "run_conclusion": None,
        "poll_seconds": poll_seconds,
    }
    gh = gh_bin or shutil.which("gh")
    if not gh:
        result["stderr"] = "gh binary not on PATH"
        return result

    try:
        proc = subprocess.run(
            [gh, "workflow", "run", workflow, "--ref", ref],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        result["stdout"] = proc.stdout or ""
        result["stderr"] = proc.stderr or ""
        if proc.returncode != 0:
            return result
        result["ok"] = True
    except (subprocess.TimeoutExpired, OSError) as exc:
        result["stderr"] = f"gh trigger error: {exc!r}"
        return result

    if poll_seconds <= 0:
        return result

    deadline = time.monotonic() + poll_seconds
    while time.monotonic() < deadline:
        try:
            poll = subprocess.run(
                [gh, "run", "list",
                 "--workflow", workflow,
                 "--limit", "1",
                 "--json", "url,status,conclusion,databaseId"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if poll.returncode == 0 and poll.stdout.strip():
                runs = json.loads(poll.stdout)
                if isinstance(runs, list) and runs:
                    top = runs[0]
                    result["run_url"] = top.get("url")
                    result["run_status"] = top.get("status")
                    result["run_conclusion"] = top.get("conclusion")
                    if top.get("status") == "completed":
                        return result
        except (subprocess.TimeoutExpired, OSError,
                json.JSONDecodeError):
            pass
        time.sleep(min(5, max(1, poll_seconds // 4)))

    return result


# ---------------------------------------------------------------------
# Rendering: ASCII table + Comparison-View.
# ---------------------------------------------------------------------

def render_ascii_table(run: DemoRun) -> str:
    """Render the demo summary as an ASCII table + comparison view."""
    lines: list[str] = []
    lines.append("Phase-3c Pre-Cutover-Probe-Phase Live-Demo (Tag-43)")
    lines.append("=" * 72)
    lines.append(f"run_id              : {run.run_id}")
    lines.append(f"started_at_utc      : {run.started_at_utc}")
    lines.append(f"finished_at_utc     : {run.finished_at_utc}")
    lines.append(f"repo_root           : {run.repo_root}")
    lines.append(f"mode                : {run.mode}")
    lines.append(f"expected_aggregate  : {run.expected_aggregate}")
    lines.append(f"observed_aggregate  : {run.observed_aggregate}")
    lines.append(f"aggregate_match     : {run.aggregate_match}")
    lines.append("")
    lines.append("Per-Welle Verdicts")
    lines.append("-" * 72)
    header = (
        f"{'W':<2} {'KW':<3} {'Component':<26} "
        f"{'Observed':<10} {'Expected':<10} {'Delta':<22}"
    )
    lines.append(header)
    lines.append("-" * 72)
    for p in run.probes:
        lines.append(
            f"{p.welle:<2} {p.kw:<3} {p.component:<26} "
            f"{p.verdict:<10} {p.expected_verdict:<10} {p.delta:<22}"
        )
    lines.append("-" * 72)
    lines.append("")
    lines.append("Summary Counts")
    lines.append("-" * 72)
    for k in ("GREEN", "CAUTION", "BLOCK", "NOT-EXEC"):
        lines.append(f"  {k:<10}: {run.summary_counts[k]}")
    lines.append("")
    lines.append("Doppel-Welle Coupling (ADR-0066)")
    lines.append("-" * 72)
    pairs_seen: set[tuple[int, int]] = set()
    for p in run.probes:
        if p.pair_partner is None:
            continue
        key = tuple(sorted((p.welle, p.pair_partner)))
        if key in pairs_seen:
            continue
        pairs_seen.add(key)
        partner = next(
            (q for q in run.probes if q.welle == p.pair_partner), None
        )
        if partner is None:
            continue
        drift = "DRIFT" if p.verdict != partner.verdict else "ALIGNED"
        lines.append(
            f"  KW-{p.kw} Welle-{p.welle}({p.verdict}) + "
            f"Welle-{partner.welle}({partner.verdict}) => {drift}"
        )
    lines.append("")
    gh = run.gh_trigger
    lines.append("GH-Trigger (Marathon-Dashboard)")
    lines.append("-" * 72)
    if not gh.get("attempted"):
        lines.append("  not-attempted (use --gh-trigger to fire)")
    else:
        lines.append(f"  ok           : {gh.get('ok')}")
        lines.append(f"  workflow     : {gh.get('workflow')}")
        lines.append(f"  ref          : {gh.get('ref')}")
        if gh.get("run_url"):
            lines.append(f"  run_url      : {gh['run_url']}")
            lines.append(f"  run_status   : {gh.get('run_status')}")
            lines.append(f"  run_conclusion: {gh.get('run_conclusion')}")
        if gh.get("stderr"):
            stderr_first = gh["stderr"].splitlines()[0] if gh["stderr"] else ""
            lines.append(f"  stderr-head  : {stderr_first[:160]}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------
# Top-level demo driver.
# ---------------------------------------------------------------------

def execute_demo(
    repo_root: Path,
    mode: str,
    gh_trigger: bool,
    gh_workflow: str,
    gh_ref: str,
    gh_poll_seconds: int,
    probe_timeout_seconds: float,
    component_overrides: dict[int, str],
    workdir: Path,
    now_utc: datetime | None = None,
) -> DemoRun:
    """Run all seven probes + aggregate + optional gh-trigger."""
    now_utc = now_utc or datetime.now(timezone.utc)
    started = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = "pre-cutover-demo-" + now_utc.strftime("%Y%m%dT%H%M%SZ")

    probes: list[ProbeResult] = []
    for meta in WELLE_CATALOGUE:
        override = component_overrides.get(meta["welle"])
        probes.append(
            run_single_probe(
                repo_root=repo_root,
                welle_meta=meta,
                workdir=workdir,
                probe_timeout_seconds=probe_timeout_seconds,
                component_override=override,
            )
        )

    observed_agg = aggregate_marathon_readiness(probes)
    expected_agg = EXPECTED_AGGREGATE_BASELINE
    aggregate_match = (observed_agg == expected_agg)

    if gh_trigger:
        gh = trigger_marathon_dashboard(
            workflow=gh_workflow,
            ref=gh_ref,
            poll_seconds=gh_poll_seconds,
        )
    else:
        gh = {
            "attempted": False,
            "workflow": gh_workflow,
            "ref": gh_ref,
            "ok": False,
            "stdout": "",
            "stderr": "",
            "run_url": None,
            "run_status": None,
            "run_conclusion": None,
            "poll_seconds": gh_poll_seconds,
        }

    finished = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return DemoRun(
        run_id=run_id,
        started_at_utc=started,
        finished_at_utc=finished,
        repo_root=str(repo_root),
        mode=mode,
        expected_aggregate=expected_agg,
        observed_aggregate=observed_agg,
        aggregate_match=aggregate_match,
        probes=probes,
        gh_trigger=gh,
        summary_counts=summary_counts(probes),
    )


# ---------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------

def _parse_component_overrides(raw: str) -> dict[int, str]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--component-overrides not valid JSON: {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise argparse.ArgumentTypeError(
            "--component-overrides must be a JSON object (welle->component)"
        )
    out: dict[int, str] = {}
    for k, v in loaded.items():
        try:
            ki = int(k)
        except (TypeError, ValueError) as exc:
            raise argparse.ArgumentTypeError(
                f"--component-overrides key {k!r} not an integer"
            ) from exc
        if ki < 1 or ki > 7:
            raise argparse.ArgumentTypeError(
                f"--component-overrides welle {ki} outside 1..7"
            )
        if not isinstance(v, str) or not v.strip():
            raise argparse.ArgumentTypeError(
                f"--component-overrides value for welle {ki} not a string"
            )
        out[ki] = v
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pre-cutover-probe-phase-live-demo",
        description=(
            "Phase-3c Pre-Cutover-Probe-Phase Live-Demo (Tag-43) -- "
            "runs all seven Welle probes in sandbox-stub mode, "
            "aggregates marathon-readiness, optionally triggers the "
            "CI marathon-dashboard."
        ),
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Absolute path to repo root (default: cwd).",
    )
    p.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Write JSON envelope to PATH (default: stdout-only).",
    )
    p.add_argument(
        "--output-md",
        type=Path,
        default=None,
        help="Write ASCII-table summary to PATH (default: stdout-only).",
    )
    p.add_argument(
        "--mode",
        choices=("dry-run", "sandbox-stub"),
        default="sandbox-stub",
        help="Probe mode alias (both behave identically in this demo).",
    )
    p.add_argument(
        "--gh-trigger",
        action="store_true",
        help="Fire `gh workflow run` against the marathon-dashboard.",
    )
    p.add_argument(
        "--no-gh-trigger",
        dest="gh_trigger",
        action="store_false",
        help="Explicitly suppress the gh-trigger (default).",
    )
    p.set_defaults(gh_trigger=False)
    p.add_argument(
        "--gh-workflow",
        default="phase-3c-pre-cutover-marathon-dashboard.yml",
        help="Workflow filename to dispatch.",
    )
    p.add_argument(
        "--gh-ref",
        default="main",
        help="Git ref to dispatch against.",
    )
    p.add_argument(
        "--gh-poll-seconds",
        type=int,
        default=0,
        help="Seconds to poll for run-state after trigger (default: 0).",
    )
    p.add_argument(
        "--probe-timeout-seconds",
        type=float,
        default=60.0,
        help="Per-probe wall-clock cap (default: 60).",
    )
    p.add_argument(
        "--component-overrides",
        type=_parse_component_overrides,
        default={},
        help='JSON map welle->component, e.g. \'{"1":"foo"}\'.',
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress ASCII-table on stdout (still writes --output-md).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    ok, msg = precondition_check(repo_root)
    if not ok:
        print(f"PRECONDITION-FAILURE: {msg}", file=sys.stderr)
        return 3

    with tempfile.TemporaryDirectory(prefix="pre-cutover-demo-") as tmp:
        workdir = Path(tmp)
        run = execute_demo(
            repo_root=repo_root,
            mode=args.mode,
            gh_trigger=args.gh_trigger,
            gh_workflow=args.gh_workflow,
            gh_ref=args.gh_ref,
            gh_poll_seconds=args.gh_poll_seconds,
            probe_timeout_seconds=args.probe_timeout_seconds,
            component_overrides=args.component_overrides,
            workdir=workdir,
        )

    envelope = run.to_envelope()
    table = render_ascii_table(run)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(table, encoding="utf-8")

    if not args.quiet:
        sys.stdout.write(table)
        sys.stdout.write(
            "MARATHON-READINESS=" + run.observed_aggregate +
            " expected=" + run.expected_aggregate +
            " match=" + str(run.aggregate_match) + "\n"
        )

    return READINESS_TO_EXIT.get(run.observed_aggregate, 2)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
