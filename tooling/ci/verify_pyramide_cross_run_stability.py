#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pyramide Cross-Run Stability-Pin Helper (Amara Tag-60).

Anlass
------
Tag-57 PR #365: Pre-Cutover-Acceptance-Pyramide Run-Order-Doc + per-Welle
und Global Verdict-Aggregator (``aggregate_pyramide_run_order_verdict.py``).
Tag-58 PR #374: Cross-Layer Dependency-DAG Verify-Gate.
Tag-60 (this helper): pin **byte-stability** of the Verdict-Envelope across
N consecutive deterministic invocations of the aggregator on the same input.

Why
---
The aggregator helper is documented to emit a JSON envelope per §7 of the
Tag-57 doc. A Pre-Cutover Final-Acceptance-Pyramide must be **reproducible
byte-for-byte** when run on identical input -- if the same input produces
different envelopes across runs (key-order drift, whitespace drift,
non-deterministic Python dict iteration, etc.), the per-Welle and Global
verdict is not a stable acceptance signal.

Tag-60 closes that gap: it invokes the aggregator helper N times on the
same input fixture, hashes each envelope, and emits a CROSS-RUN-STABLE or
CROSS-RUN-DRIFT verdict.

Sandbox
-------
Stdlib only (json, hashlib, subprocess, sys, argparse, pathlib, typing,
os). subprocess only spawns the aggregator helper in-process via
``python -m`` style invocation; no network, no podman, no live-VM.

Schema
------
The emitted envelope is a JSON object with the keys::

    {
      "schema_version": "1.0.0",
      "doc_version": "tag-60",
      "verdict": "CROSS-RUN-STABLE" | "CROSS-RUN-DRIFT" | "CROSS-RUN-ERROR",
      "exit_code": 0 | 2 | 1,
      "n_runs": <int>,
      "fixture_path": <str>,
      "mode": "welle" | "global",
      "welle_id": <int | None>,
      "envelope_hashes": [<sha256-hex>, ...],
      "stable_hash": <sha256-hex | None>,
      "drift_pairs": [[<run_idx_a>, <run_idx_b>], ...],
      "first_envelope": <object | None>,
      "notes": [<str>, ...]
    }

Verdicts
--------
CROSS-RUN-STABLE  (exit 0): all N envelopes share the same sha256.
CROSS-RUN-DRIFT   (exit 2): >=2 distinct envelope hashes observed.
CROSS-RUN-ERROR   (exit 1): aggregator returned non-zero or fixture malformed.

Doc-Anchor
----------
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` (Tag-57) §7.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"
DOC_VERSION = "tag-60"
DOC_ANCHOR = "docs/quality-gates/pre-cutover-acceptance-run-order.md"

DEFAULT_N_RUNS = 3
MIN_N_RUNS = 3
MAX_N_RUNS = 32

VERDICT_STABLE = "CROSS-RUN-STABLE"
VERDICT_DRIFT = "CROSS-RUN-DRIFT"
VERDICT_ERROR = "CROSS-RUN-ERROR"

EXIT_STABLE = 0
EXIT_ERROR = 1
EXIT_DRIFT = 2


def _aggregator_path(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "tooling" / "ci" / "aggregate_pyramide_run_order_verdict.py"


def _load_fixture(fixture_path: pathlib.Path) -> Dict[str, object]:
    """Load and validate a fixture file.

    The fixture is a JSON object with the keys:
      - mode: "welle" or "global"
      - welle: int (required when mode == "welle")
      - layer_outcomes: dict (per §7 schema; passed to aggregator stdin)
      - per_welle_verdicts: dict (required when mode == "global")
    """
    if not fixture_path.is_file():
        raise FileNotFoundError(f"fixture not found: {fixture_path}")
    raw = fixture_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("fixture root must be a JSON object")
    mode = data.get("mode")
    if mode not in ("welle", "global"):
        raise ValueError(f"fixture.mode must be 'welle' or 'global', got {mode!r}")
    if mode == "welle":
        welle = data.get("welle")
        if not isinstance(welle, int) or welle < 1 or welle > 7:
            raise ValueError(f"fixture.welle must be int 1..7, got {welle!r}")
    if "layer_outcomes" not in data or not isinstance(data["layer_outcomes"], dict):
        raise ValueError("fixture.layer_outcomes must be an object")
    if mode == "global":
        if "per_welle_verdicts" not in data or not isinstance(
            data["per_welle_verdicts"], dict
        ):
            raise ValueError(
                "fixture.per_welle_verdicts must be an object when mode=global"
            )
    return data


def _aggregator_stdin_payload(fixture: Dict[str, object]) -> str:
    """Build the JSON payload that gets piped to the aggregator's stdin.

    The aggregator's CLI accepts an object with `layer_outcomes` for both
    modes, plus `per_welle_verdicts` for mode=global.
    """
    payload: Dict[str, object] = {
        "layer_outcomes": fixture["layer_outcomes"],
    }
    if fixture.get("mode") == "global":
        payload["per_welle_verdicts"] = fixture["per_welle_verdicts"]
    return json.dumps(payload, sort_keys=True)


def _invoke_aggregator(
    repo_root: pathlib.Path,
    fixture: Dict[str, object],
    python_exe: str,
) -> Tuple[int, str, str]:
    """Invoke the aggregator helper exactly once.

    Returns (return_code, stdout, stderr).
    """
    aggregator = _aggregator_path(repo_root)
    if not aggregator.is_file():
        raise FileNotFoundError(f"aggregator not found: {aggregator}")
    mode = fixture["mode"]
    cmd: List[str] = [python_exe, str(aggregator), "--mode", str(mode), "--input", "-"]
    if mode == "welle":
        cmd.extend(["--welle", str(fixture["welle"])])
    payload = _aggregator_stdin_payload(fixture)
    # Force a deterministic-leaning environment: clear PYTHONHASHSEED-
    # affected randomness sources is unnecessary because the aggregator
    # uses sort_keys=True in its json.dump, but we pin PYTHONHASHSEED=0
    # so that any nested dict-ordering in the helper is fully pinned.
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["LC_ALL"] = "C"
    proc = subprocess.run(
        cmd,
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(repo_root),
    )
    return proc.returncode, proc.stdout, proc.stderr


def _hash_envelope(stdout: str) -> str:
    """Hash the raw stdout bytes (UTF-8 encoded).

    We intentionally hash the **raw bytes** of stdout, not the parsed
    JSON re-serialized -- the byte-stability claim is exactly that the
    aggregator emits byte-identical bytes on identical input. Re-
    serializing would mask key-order or whitespace drift in the helper.
    """
    return hashlib.sha256(stdout.encode("utf-8")).hexdigest()


def cross_run_verify(
    repo_root: pathlib.Path,
    fixture_path: pathlib.Path,
    n_runs: int = DEFAULT_N_RUNS,
    python_exe: Optional[str] = None,
) -> Dict[str, object]:
    """Run the aggregator N times on the same fixture and verify stability.

    Returns a verdict envelope (dict).
    """
    if n_runs < MIN_N_RUNS:
        raise ValueError(f"n_runs must be >= {MIN_N_RUNS}, got {n_runs}")
    if n_runs > MAX_N_RUNS:
        raise ValueError(f"n_runs must be <= {MAX_N_RUNS}, got {n_runs}")
    if python_exe is None:
        python_exe = sys.executable or "python3"

    notes: List[str] = []
    envelope_hashes: List[str] = []
    envelopes: List[str] = []
    first_parsed: Optional[Dict[str, object]] = None

    try:
        fixture = _load_fixture(fixture_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "doc_version": DOC_VERSION,
            "verdict": VERDICT_ERROR,
            "exit_code": EXIT_ERROR,
            "n_runs": n_runs,
            "fixture_path": str(fixture_path),
            "mode": None,
            "welle_id": None,
            "envelope_hashes": [],
            "stable_hash": None,
            "drift_pairs": [],
            "first_envelope": None,
            "notes": [f"fixture-load-error: {exc!s}"],
            "doc_anchor": DOC_ANCHOR,
        }

    mode = fixture["mode"]
    welle_id = fixture.get("welle") if mode == "welle" else None

    for run_idx in range(n_runs):
        try:
            rc, stdout, stderr = _invoke_aggregator(repo_root, fixture, python_exe)
        except FileNotFoundError as exc:
            notes.append(f"aggregator-missing: {exc!s}")
            return {
                "schema_version": SCHEMA_VERSION,
                "doc_version": DOC_VERSION,
                "verdict": VERDICT_ERROR,
                "exit_code": EXIT_ERROR,
                "n_runs": n_runs,
                "fixture_path": str(fixture_path),
                "mode": mode,
                "welle_id": welle_id,
                "envelope_hashes": envelope_hashes,
                "stable_hash": None,
                "drift_pairs": [],
                "first_envelope": first_parsed,
                "notes": notes,
                "doc_anchor": DOC_ANCHOR,
            }
        if rc != 0:
            notes.append(
                f"aggregator-nonzero on run {run_idx}: rc={rc} stderr={stderr.strip()[:200]!r}"
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "doc_version": DOC_VERSION,
                "verdict": VERDICT_ERROR,
                "exit_code": EXIT_ERROR,
                "n_runs": n_runs,
                "fixture_path": str(fixture_path),
                "mode": mode,
                "welle_id": welle_id,
                "envelope_hashes": envelope_hashes,
                "stable_hash": None,
                "drift_pairs": [],
                "first_envelope": first_parsed,
                "notes": notes,
                "doc_anchor": DOC_ANCHOR,
            }
        h = _hash_envelope(stdout)
        envelope_hashes.append(h)
        envelopes.append(stdout)
        if first_parsed is None:
            try:
                first_parsed = json.loads(stdout)
            except json.JSONDecodeError as exc:
                notes.append(f"aggregator-emitted-non-json on run {run_idx}: {exc!s}")
                return {
                    "schema_version": SCHEMA_VERSION,
                    "doc_version": DOC_VERSION,
                    "verdict": VERDICT_ERROR,
                    "exit_code": EXIT_ERROR,
                    "n_runs": n_runs,
                    "fixture_path": str(fixture_path),
                    "mode": mode,
                    "welle_id": welle_id,
                    "envelope_hashes": envelope_hashes,
                    "stable_hash": None,
                    "drift_pairs": [],
                    "first_envelope": None,
                    "notes": notes,
                    "doc_anchor": DOC_ANCHOR,
                }

    distinct = set(envelope_hashes)
    if len(distinct) == 1:
        verdict = VERDICT_STABLE
        exit_code = EXIT_STABLE
        stable_hash: Optional[str] = envelope_hashes[0]
        drift_pairs: List[List[int]] = []
        notes.append(
            f"all {n_runs} envelopes share sha256={envelope_hashes[0][:16]}..."
        )
    else:
        verdict = VERDICT_DRIFT
        exit_code = EXIT_DRIFT
        stable_hash = None
        drift_pairs = []
        # Record every (a,b) pair where hashes differ; small N -> O(N^2)
        # is fine.
        for a in range(len(envelope_hashes)):
            for b in range(a + 1, len(envelope_hashes)):
                if envelope_hashes[a] != envelope_hashes[b]:
                    drift_pairs.append([a, b])
        notes.append(
            f"observed {len(distinct)} distinct envelope hashes across {n_runs} runs"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "doc_version": DOC_VERSION,
        "verdict": verdict,
        "exit_code": exit_code,
        "n_runs": n_runs,
        "fixture_path": str(fixture_path),
        "mode": mode,
        "welle_id": welle_id,
        "envelope_hashes": envelope_hashes,
        "stable_hash": stable_hash,
        "drift_pairs": drift_pairs,
        "first_envelope": first_parsed,
        "notes": notes,
        "doc_anchor": DOC_ANCHOR,
    }


def _emit_envelope(envelope: Dict[str, object], json_mode: bool) -> None:
    if json_mode:
        json.dump(envelope, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"verdict: {envelope['verdict']}\n")
        sys.stdout.write(f"exit_code: {envelope['exit_code']}\n")
        sys.stdout.write(f"n_runs: {envelope['n_runs']}\n")
        sys.stdout.write(f"fixture: {envelope['fixture_path']}\n")
        sys.stdout.write(f"mode: {envelope['mode']}\n")
        if envelope.get("welle_id") is not None:
            sys.stdout.write(f"welle_id: {envelope['welle_id']}\n")
        stable_hash = envelope.get("stable_hash")
        if stable_hash:
            sys.stdout.write(f"stable_hash: {stable_hash}\n")
        else:
            sys.stdout.write("stable_hash: <none>\n")
        sys.stdout.write(f"envelope_hashes:\n")
        for i, h in enumerate(envelope.get("envelope_hashes", [])):
            sys.stdout.write(f"  [{i}] {h}\n")
        drift = envelope.get("drift_pairs", [])
        if drift:
            sys.stdout.write(f"drift_pairs:\n")
            for pair in drift:
                sys.stdout.write(f"  - run {pair[0]} vs run {pair[1]}\n")
        for note in envelope.get("notes", []):
            sys.stdout.write(f"note: {note}\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pyramide Cross-Run Stability-Pin (Tag-60): runs the "
            "aggregate_pyramide_run_order_verdict.py helper N times on a "
            "fixture and verifies the envelope is byte-identical across runs."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default=".",
        help="Repository root (contains tooling/ci/aggregate_pyramide_run_order_verdict.py).",
    )
    parser.add_argument(
        "--fixture",
        type=str,
        required=True,
        help="Path to a JSON fixture (mode, welle, layer_outcomes, per_welle_verdicts).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_N_RUNS,
        help=f"Number of consecutive runs (default {DEFAULT_N_RUNS}, min {MIN_N_RUNS}, max {MAX_N_RUNS}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit envelope as JSON on stdout (default: human-readable).",
    )
    args = parser.parse_args(argv)

    repo_root = pathlib.Path(args.repo_root).resolve()
    fixture_path = pathlib.Path(args.fixture).resolve()
    try:
        envelope = cross_run_verify(
            repo_root=repo_root,
            fixture_path=fixture_path,
            n_runs=args.runs,
        )
    except ValueError as exc:
        sys.stderr.write(f"verify_pyramide_cross_run_stability: {exc!s}\n")
        return EXIT_ERROR

    _emit_envelope(envelope, json_mode=args.json)
    exit_code = envelope.get("exit_code", EXIT_ERROR)
    if not isinstance(exit_code, int):
        return EXIT_ERROR
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
