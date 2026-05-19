#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-59 V-907 Persona-Hash-Pin-Build-Step Verifier
=================================================

Purpose
-------
Engine 0.5.3-rc1 (Tag-58, PR #372) is the final Pre-Cutover RC before
the KW-24 cutover gate opens. The persona-engine emits ten
``BackendDecision`` records on every cold-start in a strictly-ordered
boot fan-out (manifest §1). V-907 (record #4) is the persona-hash
integrity anchor; the surrounding nine records are the substrate the
manifest pins as byte-stable.

A silent post-Tag-58 edit to any of the three authority surfaces below
breaks the V-907 pin against which Phase-3c cutover acceptance is
declared:

  * Manifest §1 — the ten-row component-inventory table in
    ``wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md``.
  * Pin-Pack ``boot_wired_crates`` — the YAML list under
    ``boot_wired_crates:`` in
    ``infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml``.
  * engine.py resolver-imports — the alphabetically-sorted resolver-
    function import block + the resolver-call sites inside
    ``PersonaEngine.__init__`` in
    ``wirelang/persona_engine/engine.py``.

This helper is **stdlib-only** by design (no pip install in CI). It
mirrors the structure of the Tag-58 spec-seal probe
(``tooling/audit/verify_wirelang_spec_freeze_seal.py``) so the CI
gate boilerplate is byte-stable.

Stages
------

Stage 1 — Extract canonical bytes from the three authority surfaces.
  - Manifest §1 table is sliced between the ``## 1. Component
    Inventory`` heading and the next top-level ``##`` heading. Markdown
    is normalised by stripping trailing whitespace and collapsing CRLF.
  - Pin-Pack ``boot_wired_crates`` section is sliced between the
    ``boot_wired_crates:`` line and the next top-level YAML key
    (``boot_unwired_crates:`` in the Tag-58 layout, or any other
    top-level key that comes after).
  - engine.py resolver-block is the contiguous import block that
    contains all ten ``resolve_*_backend`` symbols, plus the body of
    ``PersonaEngine.__init__`` (where the resolvers are actually
    called). The slice is between the first ``resolve_anchor_emitter_
    backend,`` line and the last ``resolve_bridge_audit_writer_backend(``
    call site.

Stage 2 — Compute the composite hash.
  ``sha256("manifest_slice\\x1f" + "pin_pack_slice\\x1f" +
           "engine_resolver_slice")`` — ASCII unit-separator between
  segments so re-ordering of segments cannot collide. The composite
  hash is the V-907-persona-hash-pin.

Stage 3 — Verdict.
  - ``HASH-PIN-INTACT`` if composite hash matches baseline.
  - ``HASH-PIN-DRIFT`` otherwise; per-segment hashes are emitted so
    the operator can localise the drift.

Output
------
The helper prints a single JSON envelope to stdout (one line) and an
optional human-readable verdict banner to stderr. The envelope schema
matches the Tag-58 seal-probe envelope as far as ``verdict`` and
``verdict_class`` so the CI gate boilerplate can be re-used.

Scope discipline (Selin, ADR-0036/0043/0065/0066)
-------------------------------------------------
This file documents the persona-engine CI gate. It does **not**
modify persona definitions (Aisha-Domäne), WAT-core / V-907 logic
itself (Tomás-Domäne, Zone-K), identity-substrate design (Reza-
Domäne, Zone-L), or container-infra (Kai-Domäne, Zone-J). The
substance pinned by this gate is byte-bounded; the cross-zone
ownership matrix is byte-bounded.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants — repo-relative authority surfaces.
# ---------------------------------------------------------------------------

MANIFEST_RELPATH = (
    "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md"
)
PIN_PACK_RELPATH = (
    "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml"
)
ENGINE_PY_RELPATH = "wirelang/persona_engine/engine.py"
BASELINE_RELPATH = (
    "wirelang/persona_engine/v907-hash-baseline.json"
)

# Manifest §1 slice anchors.
MANIFEST_SLICE_START_MARKER = "## 1. Component Inventory"
MANIFEST_SLICE_END_PREFIX = "## "  # any top-level heading after §1

# Pin-Pack slice anchors.
PIN_PACK_SLICE_START_KEY = "boot_wired_crates:"
PIN_PACK_SLICE_END_KEYS = (
    "boot_unwired_crates:",
    "cross_backend:",
    "resilience_contract:",
    "spec_source_of_truth:",
    "legacy_env_detection:",
    "invariants:",
)

# engine.py resolver-slice anchors. The block must contain all ten
# resolver-function names; we slice from the first import line that
# carries one of them down to the last ``resolve_*_backend(`` call.
RESOLVER_NAMES: Tuple[str, ...] = (
    "resolve_recovery_backend",
    "resolve_state_backing_backend",
    "resolve_fsm_backend",
    "resolve_v907_verify_backend",
    "resolve_bridge_diff_backend",
    "resolve_subscribe_loop_backend",
    "resolve_anchor_emitter_backend",
    "resolve_svid_workload_identity_backend",
    "resolve_federation_resolver_backend",
    "resolve_bridge_audit_writer_backend",
)


# ---------------------------------------------------------------------------
# Slicing helpers — pure, no IO.
# ---------------------------------------------------------------------------


def normalise_text(text: str) -> str:
    """Collapse CRLF + strip trailing whitespace on each line.

    The output is the canonical byte-shape used for hashing.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def slice_manifest_section_1(manifest_text: str) -> str:
    """Return the canonical bytes for Manifest §1 (Component Inventory)."""
    norm = normalise_text(manifest_text)
    lines = norm.split("\n")
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if start_idx is None and line.startswith(MANIFEST_SLICE_START_MARKER):
            start_idx = i
            continue
        if start_idx is not None and i > start_idx:
            stripped = line.strip()
            if (
                stripped.startswith(MANIFEST_SLICE_END_PREFIX)
                and not stripped.startswith("### ")
                and not stripped.startswith(MANIFEST_SLICE_START_MARKER)
            ):
                end_idx = i
                break
    if start_idx is None:
        raise SliceError(
            f"Manifest §1 start marker '{MANIFEST_SLICE_START_MARKER}'"
            f" not found in manifest text"
        )
    if end_idx is None:
        # §1 might be the last section; slice to EOF.
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx]).rstrip() + "\n"


def slice_pin_pack_boot_wired_crates(pin_pack_text: str) -> str:
    """Return the canonical bytes for Pin-Pack ``boot_wired_crates``."""
    norm = normalise_text(pin_pack_text)
    lines = norm.split("\n")
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if start_idx is None and line.rstrip() == PIN_PACK_SLICE_START_KEY:
            start_idx = i
            continue
        if start_idx is not None and i > start_idx:
            stripped = line.rstrip()
            # A top-level YAML key has no leading whitespace and ends with ':'.
            if (
                stripped
                and not line.startswith(" ")
                and not line.startswith("\t")
                and not line.startswith("#")
                and stripped.endswith(":")
            ):
                end_idx = i
                break
    if start_idx is None:
        raise SliceError(
            f"Pin-Pack key '{PIN_PACK_SLICE_START_KEY}' not found"
        )
    if end_idx is None:
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx]).rstrip() + "\n"


def slice_engine_py_resolvers(engine_py_text: str) -> str:
    """Return the canonical bytes for engine.py resolver-slice.

    Slice = first line that mentions any of the ten resolver-function
    names down to the last line that does so (inclusive). This
    captures both the import block and every resolver-call site in
    ``PersonaEngine.__init__``.
    """
    norm = normalise_text(engine_py_text)
    lines = norm.split("\n")
    first_hit: Optional[int] = None
    last_hit: Optional[int] = None
    for i, line in enumerate(lines):
        if any(name in line for name in RESOLVER_NAMES):
            if first_hit is None:
                first_hit = i
            last_hit = i
    if first_hit is None or last_hit is None:
        raise SliceError(
            "engine.py contains no resolver-function references"
        )
    return "\n".join(lines[first_hit : last_hit + 1]).rstrip() + "\n"


class SliceError(RuntimeError):
    """Raised when an authority-surface slice cannot be extracted."""


# ---------------------------------------------------------------------------
# Hashing.
# ---------------------------------------------------------------------------


UNIT_SEPARATOR = "\x1f"  # ASCII US — never appears in source text


def sha256_hex(payload: str) -> str:
    """SHA-256 over UTF-8-encoded payload, hex-encoded."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_composite_hash(
    manifest_slice: str, pin_pack_slice: str, engine_resolver_slice: str
) -> str:
    """Compute the V-907 persona-hash-pin composite hash.

    Format: ``sha256(manifest \\x1f pin_pack \\x1f engine_resolver)``.
    """
    payload = (
        manifest_slice
        + UNIT_SEPARATOR
        + pin_pack_slice
        + UNIT_SEPARATOR
        + engine_resolver_slice
    )
    return sha256_hex(payload)


# ---------------------------------------------------------------------------
# Envelope.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class HashPinEnvelope:
    """V-907 persona-hash-pin verdict envelope."""

    verdict: str  # "HASH-PIN-INTACT" | "HASH-PIN-DRIFT"
    verdict_class: str
    engine_version: str
    composite_hash: str
    baseline_composite_hash: str
    segment_hashes: Dict[str, str]
    baseline_segment_hashes: Dict[str, str]
    drifted_segments: List[str]
    authority_paths: Dict[str, str]

    def to_dict(self) -> Dict[str, object]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------


def load_baseline(baseline_path: pathlib.Path) -> Dict[str, object]:
    if not baseline_path.exists():
        raise FileNotFoundError(
            f"baseline file is missing: {baseline_path}"
        )
    return json.loads(baseline_path.read_text(encoding="utf-8"))


def run_audit(
    repo_root: pathlib.Path,
    baseline_path: Optional[pathlib.Path] = None,
) -> HashPinEnvelope:
    """Run the full V-907 persona-hash-pin audit and return the envelope."""
    manifest_path = repo_root / MANIFEST_RELPATH
    pin_pack_path = repo_root / PIN_PACK_RELPATH
    engine_py_path = repo_root / ENGINE_PY_RELPATH
    baseline_path = baseline_path or (repo_root / BASELINE_RELPATH)

    for label, p in (
        ("manifest", manifest_path),
        ("pin_pack", pin_pack_path),
        ("engine_py", engine_py_path),
    ):
        if not p.exists():
            raise FileNotFoundError(
                f"authority surface '{label}' is missing: {p}"
            )

    manifest_slice = slice_manifest_section_1(
        manifest_path.read_text(encoding="utf-8")
    )
    pin_pack_slice = slice_pin_pack_boot_wired_crates(
        pin_pack_path.read_text(encoding="utf-8")
    )
    engine_resolver_slice = slice_engine_py_resolvers(
        engine_py_path.read_text(encoding="utf-8")
    )

    segment_hashes = {
        "manifest_section_1": sha256_hex(manifest_slice),
        "pin_pack_boot_wired_crates": sha256_hex(pin_pack_slice),
        "engine_py_resolvers": sha256_hex(engine_resolver_slice),
    }
    composite = compute_composite_hash(
        manifest_slice, pin_pack_slice, engine_resolver_slice
    )

    baseline = load_baseline(baseline_path)
    baseline_segment_hashes: Dict[str, str] = {
        k: str(v) for k, v in baseline.get("segment_hashes", {}).items()
    }
    baseline_composite = str(baseline.get("composite_hash", ""))
    engine_version = str(baseline.get("engine_version", ""))

    drifted = sorted(
        seg
        for seg, h in segment_hashes.items()
        if baseline_segment_hashes.get(seg) != h
    )

    if composite == baseline_composite and not drifted:
        verdict = "HASH-PIN-INTACT"
        verdict_class = "intact"
    else:
        verdict = "HASH-PIN-DRIFT"
        if not drifted:
            # composite drifted but per-segment didn't — baseline file
            # is malformed.
            verdict_class = "baseline-malformed"
        elif len(drifted) == 1:
            verdict_class = f"single-segment-drift:{drifted[0]}"
        else:
            verdict_class = "multi-segment-drift"

    return HashPinEnvelope(
        verdict=verdict,
        verdict_class=verdict_class,
        engine_version=engine_version,
        composite_hash=composite,
        baseline_composite_hash=baseline_composite,
        segment_hashes=segment_hashes,
        baseline_segment_hashes=baseline_segment_hashes,
        drifted_segments=drifted,
        authority_paths={
            "manifest": MANIFEST_RELPATH,
            "pin_pack": PIN_PACK_RELPATH,
            "engine_py": ENGINE_PY_RELPATH,
            "baseline": BASELINE_RELPATH,
        },
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tag-59 V-907 Persona-Hash-Pin-Build-Step verifier "
            "(stdlib-only)."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help=(
            "Repository root (default: cwd). All authority surfaces "
            "are resolved relative to this directory."
        ),
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help=(
            "Optional override for the baseline-lock JSON path. "
            "Default: <repo-root>/" + BASELINE_RELPATH
        ),
    )
    parser.add_argument(
        "--print-banner",
        action="store_true",
        help="Emit a human-readable banner on stderr alongside the JSON.",
    )
    args = parser.parse_args(argv)

    repo_root = pathlib.Path(args.repo_root).resolve()
    baseline_path = pathlib.Path(args.baseline).resolve() if args.baseline else None

    try:
        envelope = run_audit(repo_root, baseline_path)
    except (FileNotFoundError, SliceError) as exc:
        err = {
            "verdict": "HASH-PIN-DRIFT",
            "verdict_class": "authority-surface-missing",
            "error": str(exc),
        }
        print(json.dumps(err, sort_keys=True))
        return 2

    print(envelope.to_json())

    if args.print_banner:
        banner = (
            f"V-907 persona-hash-pin verdict: {envelope.verdict} "
            f"({envelope.verdict_class}) for engine "
            f"{envelope.engine_version or '<unset>'}"
        )
        print(banner, file=sys.stderr)

    return 0 if envelope.verdict == "HASH-PIN-INTACT" else 1


if __name__ == "__main__":
    sys.exit(main())
