#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""AR-Hand-Stop-Marker Listener — Detect-Step.

Reads either the GitHub push-event payload or the workflow_dispatch
inputs and extracts the (welle, trigger, ts, operator, filename)
quadruple for downstream cascade + cancel steps.

GitHub-Actions wire-protocol
----------------------------

Outputs are emitted as ``key=value`` lines to the file pointed to
by ``--out`` (the workflow passes ``$GITHUB_OUTPUT``). For
multi-line outputs the heredoc form is NOT used because all
outputs are single-line by construction (welle is int, trigger is
a token, ts is RFC3339, operator is a slug, filename is a single
path).

Sandbox-Boundary
----------------

Stdlib + the marker-set module's exported constants (no third-
party deps). The script reads the marker file from the local
checkout — no network, no gh CLI invocation.

Anchors
-------

  * `scripts/ci/ar-hand-stop-marker-set.py` (schema constants).
  * `.github/workflows/ar-hand-stop-marker-listener.yml`
    (caller).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Load the marker-set module via filesystem to avoid making it
# package-installable just for a CI helper.
# ---------------------------------------------------------------------------


_HERE = pathlib.Path(__file__).resolve().parent
_MARKER_SET_PATH = _HERE / "ar-hand-stop-marker-set.py"


def _load_marker_set_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ar_hand_stop_marker_set", _MARKER_SET_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(
            f"cannot load marker-set module at {_MARKER_SET_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MARKER_SET = _load_marker_set_module()


# ---------------------------------------------------------------------------
# Detect logic.
# ---------------------------------------------------------------------------


def detect_from_push_event(
    payload: dict[str, Any],
    *,
    repo_root: pathlib.Path,
) -> dict[str, str]:
    """Extract the marker quadruple from a push-event payload.

    Strategy: walk ``payload['commits']``, collect every file
    matching the marker pattern in ``added`` or ``modified``. If
    multiple match, the first by filename order wins (deterministic).
    The marker JSON is then read from the local checkout.
    """

    commits = payload.get("commits") or []
    marker_candidates: list[str] = []
    for commit in commits:
        for key in ("added", "modified"):
            for path in commit.get(key, []) or []:
                name = pathlib.Path(path).name
                if MARKER_SET.MARKER_FILENAME_RE.match(name):
                    marker_candidates.append(path)
    if not marker_candidates:
        raise LookupError(
            "no AR-Hand-Stop-Marker file found in push event commits"
        )
    marker_candidates.sort()
    marker_path = marker_candidates[0]
    return _read_marker(repo_root / marker_path, marker_path)


def detect_from_dispatch(
    *,
    dispatch_welle: str,
    dispatch_filename: str,
    repo_root: pathlib.Path,
) -> dict[str, str]:
    """Extract the marker quadruple from workflow_dispatch inputs."""

    if not dispatch_welle:
        raise LookupError(
            "workflow_dispatch invoked without --dispatch-welle"
        )
    welle = int(dispatch_welle)
    if not (
        MARKER_SET.WELLE_MIN <= welle <= MARKER_SET.WELLE_MAX
    ):
        raise ValueError(
            f"dispatch welle out of range: {welle} "
            f"(expected {MARKER_SET.WELLE_MIN}..{MARKER_SET.WELLE_MAX})"
        )

    state_dir = repo_root / "state"
    if dispatch_filename:
        target = state_dir / pathlib.Path(dispatch_filename).name
        if not target.exists():
            raise LookupError(
                f"dispatch marker filename not found: {target}"
            )
        return _read_marker(target, target.relative_to(repo_root).as_posix())

    # Search for the newest marker matching the welle.
    candidates = sorted(
        p
        for p in state_dir.glob(f"ar-hand-stop-welle-{welle}-*.json")
        if MARKER_SET.MARKER_FILENAME_RE.match(p.name)
    )
    if not candidates:
        raise LookupError(
            f"no marker file matching welle={welle} found in {state_dir}"
        )
    target = candidates[-1]
    return _read_marker(target, target.relative_to(repo_root).as_posix())


def _read_marker(marker_path: pathlib.Path, repo_rel: str) -> dict[str, str]:
    if not marker_path.exists():
        raise LookupError(f"marker file vanished: {marker_path}")
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    for field in ("welle", "trigger", "ts", "operator"):
        if field not in payload:
            raise ValueError(
                f"marker missing required field {field!r}: {marker_path}"
            )
    return {
        "welle": str(payload["welle"]),
        "trigger": str(payload["trigger"]),
        "ts": str(payload["ts"]),
        "operator": str(payload["operator"]),
        "filename": repo_rel,
    }


# ---------------------------------------------------------------------------
# GitHub-Actions output writer.
# ---------------------------------------------------------------------------


def write_outputs(out_path: pathlib.Path, mapping: dict[str, str]) -> None:
    lines = []
    for key, value in mapping.items():
        if "\n" in value:
            raise ValueError(
                f"detect output value for {key!r} contains newline: {value!r}"
            )
        lines.append(f"{key}={value}")
    body = "\n".join(lines) + "\n"
    # GitHub-Actions appends to GITHUB_OUTPUT; mirror that semantics.
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(body)


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ar-hand-stop-marker-listener-detect")
    p.add_argument("--event", required=True, help="GITHUB_EVENT_NAME")
    p.add_argument(
        "--event-payload",
        required=True,
        help="GITHUB_EVENT_PATH (push event JSON)",
    )
    p.add_argument("--dispatch-welle", default="", help="dispatch input")
    p.add_argument("--dispatch-filename", default="", help="dispatch input")
    p.add_argument(
        "--out",
        required=True,
        help="GITHUB_OUTPUT path (append-mode)",
    )
    p.add_argument(
        "--repo-root",
        default=str(pathlib.Path.cwd()),
        help="repo-root for resolving marker paths",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = pathlib.Path(args.repo_root).resolve()

    try:
        if args.event == "push":
            payload_path = pathlib.Path(args.event_payload)
            if not payload_path.exists():
                print(
                    f"ERROR: event payload not found: {payload_path}",
                    file=sys.stderr,
                )
                return 2
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            mapping = detect_from_push_event(payload, repo_root=repo_root)
        elif args.event == "workflow_dispatch":
            mapping = detect_from_dispatch(
                dispatch_welle=args.dispatch_welle,
                dispatch_filename=args.dispatch_filename,
                repo_root=repo_root,
            )
        else:
            print(
                f"ERROR: unsupported event: {args.event}", file=sys.stderr
            )
            return 2
    except (LookupError, ValueError) as exc:
        print(f"ERROR: detect failed: {exc}", file=sys.stderr)
        return 2

    write_outputs(pathlib.Path(args.out), mapping)
    print(f"detected marker: {mapping}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
