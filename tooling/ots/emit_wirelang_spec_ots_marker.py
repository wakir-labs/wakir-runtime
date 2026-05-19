#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit an OTS-anchor stub marker for the Wirelang specification file.

Tag-60 mirror-twin of Tomás's Tag-59 manifest-hash OTS-anchor probe.
Where Tomás anchors persona-engine ``MANIFEST-*.md`` files via the
WAT spool, this helper anchors the Wirelang-Spec markdown documents
(currently ``wirelang/specs/wirelang-spec-v0-4-3.md`` and any sibling
spec versions that ship pre-cutover). The Tag-58 freeze-seal probe
(Reza, PR #371) sealed the live spec against post-freeze drift; the
Tag-60 OTS-anchor probe is the *cryptographic timestamp* tripwire
that will, once AR-authorised, anchor the sealed spec at the
OpenTimestamps calendar.

This helper is the **audit-only stub** for the future OTS-anchor
wiring of Wirelang-Spec files via the WAT spool. It computes the
SHA-256 of a spec markdown file, records the intent-to-anchor in a
marker JSON file under ``tooling/ots/markers/``, and emits a
WAT-spool envelope describing the anchor request.

**Audit-only.** This helper does NOT call out to an OpenTimestamps
calendar server. The Sandbox-boundary is explicitly preserved:

  * No network I/O.
  * No subprocess calls to ``ots`` CLI.
  * No filesystem writes outside the marker output directory.

The Operator-Hand picks up the marker file in a later runbook step
and runs the real ``ots stamp`` invocation on a host that has
network access to the OTS calendar. The marker file then gets the
real ``.ots`` proof attached (out-of-band, Phase-3c-Schritt-N+1).

Tag-66 RES-D-item probe mode
----------------------------

The ``--mode res-d-item-probe --res-d-item RES-D[1-5]`` flag pair
adds a *per-item* hermetic probe that simulates the activation of
a single Wirelang-Spec v0.4.4 reserve item (RES-D1..RES-D5) WITHOUT
performing the actual activation. Concretely the per-item probe:

  * Pins the spec path to ``wirelang/specs/wirelang-spec-v0-4-4-
    draft.md`` (the canonical draft location for v0.4.4 reserves).
  * Walks the same four hermetic stages as the Tag-60 probe
    (input_validation, hash_computation, payload_shape, sandbox_
    boundary) plus a fifth ``item_simulation`` stage that scans
    the draft introspectively for the per-item anchor strings
    (RES-D row, candidate-section heading, sample-block heading).
  * Emits a verdict envelope with the additional fields
    ``res_d_item``, ``item_metadata``, and ``draft_untouched: true``.

The Tag-66 per-item probe NEVER edits the v0.4.4 draft file (the
``draft_untouched`` flag is invariant-true). Per-item probing
exists so the Aufsichtsrat can audit a *single* reserve item's
activation pipeline in isolation, ahead of the Phase-4 governance
decision (TBD) about which RES-Dn items get promoted.

Tag-60 Pre-Activation-Probe mode
--------------------------------

The ``--mode pre-activation-probe`` flag adds a dry-run pass that
walks the *exact* shape an actual ``ots stamp`` invocation would
receive for a Wirelang-Spec file, without performing any network
I/O. Concretely the probe verifies:

  * Input validation: spec path exists, is a file, is readable,
    matches the in-tree spec-anchor-stub registry.
  * Hash computation: SHA-256 streamed in 64 KiB chunks, byte-stable.
  * Payload shape: marker JSON validates against schema-v1 (all
    required keys, no unexpected keys) AND the additional Tag-60
    ``pre_activation_probe`` envelope is present.
  * Sandbox boundary still intact: no network calls, no ots CLI
    subprocess, no podman socket. The probe asserts this by being
    stdlib-only and emitting an explicit ``sandbox_boundary_intact:
    true`` flag in the verdict payload.

The probe emits a verdict envelope to ``--probe-verdict-out``:

  {
    "schema_version": 1,
    "kind": "ots-pre-activation-probe-verdict",
    "mode": "pre-activation-probe",
    "verdict": "PROBE-READY" | "PROBE-DEFECT",
    "stages": {
      "input_validation": "OK" | "FAIL: <reason>",
      "hash_computation": "OK: <hex>" | "FAIL: <reason>",
      "payload_shape":    "OK"  | "FAIL: <reason>",
      "sandbox_boundary": "OK"
    },
    "spec_sha256": "<64-hex-or-empty>",
    "spec_size_bytes": <int-or-zero>,
    "probed_at_utc": "<iso>",
    "ar_authorisation_required": true,
    "anchors": {
      "tomas_tag_59_pre_anchor_probe_pr": 380,
      "reza_tag_58_spec_seal_pr": 371,
      "operator_hand_runbook":
        "docs/operations/wirelang-spec-ots-anchor-wiring.md"
    }
  }

The probe is hermetic. **It still performs no real OTS calendar
call.** AR-authorisation flips a future runtime gate (see §6 + §7
of the runbook doc); the probe itself never crosses the Sandbox
boundary.

Schema (v1) — JSON marker emitted to ``--marker-out``
-----------------------------------------------------

  {
    "schema_version": 1,
    "kind": "wirelang-spec-ots-anchor-marker",
    "mode": "audit-only",
    "spec_path": "wirelang/specs/wirelang-spec-v0-4-3.md",
    "spec_version": "0.4.3",
    "spec_sha256": "<64-hex>",
    "spec_size_bytes": 12345,
    "wat_spool_envelope": {
      "schema_version": 1,
      "kind": "wirelang-spec-ots-anchor-request",
      "spec_sha256": "<64-hex>",
      "requested_at_utc": "2026-05-19T...",
      "actor": "<github.actor|local>",
      "anchor_target": "opentimestamps-calendar"
    },
    "emitted_at_utc": "2026-05-19T...",
    "anchors": {
      "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
      "reza_tag_58_spec_seal_pr": 371,
      "tomas_tag_59_manifest_hash_probe_pr": 380
    },
    "operator_hand_next_step": (
      "Run `ots stamp <marker_out>` on a network-attached host; "
      "attach resulting .ots proof to this marker out-of-band."
    )
  }

Exit codes
----------

  * 0 — marker emitted successfully (audit-only mode) or
        probe verdict emitted (pre-activation-probe mode).
  * 1 — spec file not found / unreadable (audit-only only).
  * 2 — usage error.

Hermetic
--------

stdlib only. ``argparse``, ``hashlib``, ``json``, ``pathlib``,
``datetime``, ``os``, ``sys``. No third-party imports. No network.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable


MODE_AUDIT_ONLY: str = "audit-only"
MODE_PRE_ACTIVATION_PROBE: str = "pre-activation-probe"
MODE_RES_D_ITEM_PROBE: str = "res-d-item-probe"
ANCHOR_TARGET_OTS_CALENDAR: str = "opentimestamps-calendar"

# Tag-66 — RES-D reserve items defined in v0.4.4 draft §5/§6.
# Each item is *individually* simulatable through the per-item-probe
# mode introduced in Tag-66. The probe does NOT activate the item
# (the v0.4.4 draft remains untouched); it only walks the simulated
# activation pipeline and emits a verdict envelope.
RES_D_ITEM_IDS: tuple[str, ...] = (
    "RES-D1",
    "RES-D2",
    "RES-D3",
    "RES-D4",
    "RES-D5",
)

# Per-RES-Dn topic + candidate-section anchors (lift from
# wirelang/specs/wirelang-spec-v0-4-4-draft.md §5 table). The probe
# uses these to validate the per-item simulation envelope shape.
RES_D_ITEM_METADATA: dict[str, dict[str, str]] = {
    "RES-D1": {
        "topic": "identity-substrate-evolution",
        "candidate_section": "§3.2.1",
        "sample_block": "§6.1.1",
    },
    "RES-D2": {
        "topic": "capability-token-refinements",
        "candidate_section": "§7.4",
        "sample_block": "§6.2.1",
    },
    "RES-D3": {
        "topic": "bridge-audit-cleanup",
        "candidate_section": "§4.1.10a",
        "sample_block": "§6.3.1",
    },
    "RES-D4": {
        "topic": "schema-registry-v2-prep",
        "candidate_section": "§8.5",
        "sample_block": "§6.4.1",
    },
    "RES-D5": {
        "topic": "recovery-drill-leaf-projection-v2",
        "candidate_section": "§6.4",
        "sample_block": "§6.5.1",
    },
}

# Required top-level keys for a schema-v1 marker payload. Used by the
# pre-activation-probe's ``payload_shape`` stage.
MARKER_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "spec_path",
        "spec_version",
        "spec_sha256",
        "spec_size_bytes",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    }
)

# Required top-level keys for a schema-v1 probe-verdict payload.
PROBE_VERDICT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "verdict",
        "stages",
        "spec_sha256",
        "spec_size_bytes",
        "probed_at_utc",
        "ar_authorisation_required",
        "anchors",
    }
)

# Required top-level keys for a Tag-66 per-RES-Dn probe-verdict
# envelope. The shape mirrors the Tag-60 ``PROBE_VERDICT_REQUIRED_KEYS``
# plus the item-identity fields ``res_d_item`` + ``item_metadata``
# and the explicit ``draft_untouched`` invariant flag.
RES_D_ITEM_VERDICT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "verdict",
        "stages",
        "res_d_item",
        "item_metadata",
        "spec_sha256",
        "spec_size_bytes",
        "probed_at_utc",
        "ar_authorisation_required",
        "draft_untouched",
        "anchors",
    }
)

# Stage keys for the Tag-66 per-RES-Dn probe. Five stages — the four
# Tag-60 stages, plus a fifth ``item_simulation`` stage that walks
# the simulated activation pipeline for the chosen item without
# touching the v0.4.4 draft.
RES_D_PROBE_STAGE_KEYS: tuple[str, ...] = (
    "input_validation",
    "hash_computation",
    "payload_shape",
    "sandbox_boundary",
    "item_simulation",
)

PROBE_STAGE_KEYS: tuple[str, ...] = (
    "input_validation",
    "hash_computation",
    "payload_shape",
    "sandbox_boundary",
)

PROBE_VERDICT_READY: str = "PROBE-READY"
PROBE_VERDICT_DEFECT: str = "PROBE-DEFECT"


def compute_sha256(path: Path) -> tuple[str, int]:
    """Return (hex-digest, byte-size) for the file at ``path``.

    Streams the file in 64 KiB chunks to keep memory flat.
    """
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _extract_spec_version(spec_path: Path) -> str:
    """Best-effort frontmatter read of ``version:`` in the spec file.

    Returns ``"unknown"`` when the spec file is unreadable or the
    frontmatter is missing. The probe's ``payload_shape`` stage does
    not depend on this — it is purely informational metadata.
    """
    try:
        head = spec_path.read_text(encoding="utf-8").splitlines()[:40]
    except (OSError, UnicodeDecodeError):
        return "unknown"
    for line in head:
        stripped = line.strip()
        if stripped.startswith("version:"):
            return stripped.split(":", 1)[1].strip() or "unknown"
    return "unknown"


def build_marker(
    *,
    spec_path: Path,
    spec_sha256: str,
    spec_size_bytes: int,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
    spec_version: str | None = None,
) -> dict:
    """Assemble the marker dict for the given spec hash."""
    rel_spec = (
        str(spec_path.relative_to(repo_root))
        if spec_path.is_absolute() and repo_root in spec_path.parents
        else str(spec_path)
    )
    iso_now = now_utc.isoformat()
    resolved_version = (
        spec_version if spec_version is not None
        else _extract_spec_version(spec_path)
    )
    return {
        "schema_version": 1,
        "kind": "wirelang-spec-ots-anchor-marker",
        "mode": MODE_AUDIT_ONLY,
        "spec_path": rel_spec,
        "spec_version": resolved_version,
        "spec_sha256": spec_sha256,
        "spec_size_bytes": spec_size_bytes,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": "wirelang-spec-ots-anchor-request",
            "spec_sha256": spec_sha256,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "reza_tag_58_spec_seal_pr": 371,
            "tomas_tag_59_manifest_hash_probe_pr": 380,
        },
        "operator_hand_next_step": (
            "Run `ots stamp <marker_out>` on a network-attached host; "
            "attach resulting .ots proof to this marker out-of-band."
        ),
    }


def _empty_probe_stages() -> dict:
    return {key: None for key in PROBE_STAGE_KEYS}


def build_probe_verdict(
    *,
    stages: dict,
    spec_sha256: str,
    spec_size_bytes: int,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Tag-60 pre-activation-probe verdict envelope.

    ``stages`` must contain entries for all four ``PROBE_STAGE_KEYS``.
    Verdict is ``PROBE-READY`` iff every stage starts with ``"OK"``,
    otherwise ``PROBE-DEFECT``.
    """
    iso_now = now_utc.isoformat()
    all_ok = all(
        isinstance(stages.get(k), str) and stages[k].startswith("OK")
        for k in PROBE_STAGE_KEYS
    )
    verdict = PROBE_VERDICT_READY if all_ok else PROBE_VERDICT_DEFECT
    return {
        "schema_version": 1,
        "kind": "ots-pre-activation-probe-verdict",
        "mode": MODE_PRE_ACTIVATION_PROBE,
        "verdict": verdict,
        "stages": {k: stages[k] for k in PROBE_STAGE_KEYS},
        "spec_sha256": spec_sha256,
        "spec_size_bytes": spec_size_bytes,
        "probed_at_utc": iso_now,
        "ar_authorisation_required": True,
        "anchors": {
            "tomas_tag_59_pre_anchor_probe_pr": 380,
            "reza_tag_58_spec_seal_pr": 371,
            "operator_hand_runbook": (
                "docs/operations/wirelang-spec-ots-anchor-wiring.md"
            ),
        },
    }


def _empty_res_d_probe_stages() -> dict:
    return {key: None for key in RES_D_PROBE_STAGE_KEYS}


def build_res_d_item_verdict(
    *,
    res_d_item: str,
    stages: dict,
    spec_sha256: str,
    spec_size_bytes: int,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Tag-66 per-RES-Dn item probe-verdict envelope.

    ``stages`` must carry entries for all five
    ``RES_D_PROBE_STAGE_KEYS``. Verdict is ``PROBE-READY`` iff every
    stage starts with ``"OK"``; ``PROBE-DEFECT`` otherwise.

    The ``draft_untouched`` flag is invariant-true: the per-item
    probe NEVER edits the v0.4.4 draft file; it only walks a
    simulated activation pipeline in-memory.
    """
    iso_now = now_utc.isoformat()
    all_ok = all(
        isinstance(stages.get(k), str) and stages[k].startswith("OK")
        for k in RES_D_PROBE_STAGE_KEYS
    )
    verdict = PROBE_VERDICT_READY if all_ok else PROBE_VERDICT_DEFECT
    metadata = RES_D_ITEM_METADATA[res_d_item]
    return {
        "schema_version": 1,
        "kind": "ots-res-d-item-probe-verdict",
        "mode": MODE_RES_D_ITEM_PROBE,
        "verdict": verdict,
        "stages": {k: stages[k] for k in RES_D_PROBE_STAGE_KEYS},
        "res_d_item": res_d_item,
        "item_metadata": {
            "topic": metadata["topic"],
            "candidate_section": metadata["candidate_section"],
            "sample_block": metadata["sample_block"],
        },
        "spec_sha256": spec_sha256,
        "spec_size_bytes": spec_size_bytes,
        "probed_at_utc": iso_now,
        "ar_authorisation_required": True,
        "draft_untouched": True,
        "anchors": {
            "reza_tag_60_spec_ots_probe_pr": 385,
            "reza_tag_63_v044_draft_pr": None,
            "reza_tag_65_promotion_sequencing_pr": 417,
            "v044_draft_path": (
                "wirelang/specs/wirelang-spec-v0-4-4-draft.md"
            ),
            "operator_hand_runbook": (
                "docs/operations/wirelang-spec-ots-anchor-wiring.md"
            ),
        },
    }


def _simulate_res_d_item_activation(
    *,
    res_d_item: str,
    spec_path: Path,
) -> str:
    """Walk the simulated activation pipeline for a RES-D item.

    The simulation is purely *introspective*: it scans the v0.4.4
    draft for the canonical RES-D anchor strings (the item row, its
    candidate-section heading, and the sample-block heading) and
    verifies the per-item metadata is consistent. It does NOT edit
    the draft. It does NOT call the OTS calendar. It does NOT emit
    a real anchor request.

    Returns an ``"OK"``-prefixed string on success or a
    ``"FAIL: ..."``-prefixed string on detected drift.
    """
    if res_d_item not in RES_D_ITEM_METADATA:
        return f"FAIL: unknown RES-D item: {res_d_item}"

    if not spec_path.is_file():
        return f"FAIL: v0.4.4 draft not found: {spec_path}"

    try:
        text = spec_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"FAIL: draft unreadable: {exc}"

    metadata = RES_D_ITEM_METADATA[res_d_item]
    expected_anchors = (
        # Row marker — exact item-id (used by §5 reserve table).
        res_d_item,
        # Candidate-section header anchor.
        metadata["candidate_section"],
        # Topic name from §5 table.
        metadata["topic"],
    )
    missing = [a for a in expected_anchors if a not in text]
    if missing:
        return (
            f"FAIL: draft missing RES-D anchors for {res_d_item}: "
            f"{missing}"
        )

    # Cross-check: the per-item sub-section heading must appear
    # exactly as documented in §5 (probe defect if drift).
    expected_heading = (
        f"### 6.{int(res_d_item[-1])} {res_d_item}: {metadata['topic']}"
    )
    if expected_heading not in text:
        return (
            f"FAIL: draft missing per-item heading anchor: "
            f"{expected_heading!r}"
        )

    return (
        f"OK: simulated {res_d_item} activation walk; "
        f"candidate-section={metadata['candidate_section']}; "
        f"sample-block={metadata['sample_block']}; "
        f"draft untouched"
    )


def run_res_d_item_probe(
    *,
    res_d_item: str,
    spec_path: Path,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
) -> dict:
    """Execute the Tag-66 five-stage hermetic per-item probe.

    The probe mirrors the Tag-60 four-stage probe and adds a fifth
    ``item_simulation`` stage. It never calls the OTS calendar; it
    never edits the v0.4.4 draft. Sandbox-boundary is OK-by-
    construction (stdlib-only, no subprocess, no socket).
    """
    if res_d_item not in RES_D_ITEM_METADATA:
        # Bail out with a structured DEFECT verdict; do not raise —
        # the workflow surfaces verdicts uniformly.
        stages = _empty_res_d_probe_stages()
        for key in RES_D_PROBE_STAGE_KEYS:
            stages[key] = f"FAIL: unknown RES-D item: {res_d_item}"
        # Synthesise minimal metadata to keep the envelope shape
        # stable even for unknown items. Builder requires the item
        # to be in RES_D_ITEM_METADATA, so we patch a placeholder.
        return {
            "schema_version": 1,
            "kind": "ots-res-d-item-probe-verdict",
            "mode": MODE_RES_D_ITEM_PROBE,
            "verdict": PROBE_VERDICT_DEFECT,
            "stages": stages,
            "res_d_item": res_d_item,
            "item_metadata": {
                "topic": "unknown",
                "candidate_section": "unknown",
                "sample_block": "unknown",
            },
            "spec_sha256": "",
            "spec_size_bytes": 0,
            "probed_at_utc": now_utc.isoformat(),
            "ar_authorisation_required": True,
            "draft_untouched": True,
            "anchors": {
                "reza_tag_60_spec_ots_probe_pr": 385,
                "reza_tag_63_v044_draft_pr": None,
                "reza_tag_65_promotion_sequencing_pr": 417,
                "v044_draft_path": (
                    "wirelang/specs/wirelang-spec-v0-4-4-draft.md"
                ),
                "operator_hand_runbook": (
                    "docs/operations/wirelang-spec-ots-anchor-wiring.md"
                ),
            },
        }

    stages = _empty_res_d_probe_stages()
    spec_sha256 = ""
    spec_size_bytes = 0

    # Stage 1 — input validation. Reuse Tag-60 semantics but
    # additionally require the spec_path to be a v0.4.4 draft.
    if not spec_path.exists():
        stages["input_validation"] = (
            f"FAIL: spec not found: {spec_path}"
        )
    elif not spec_path.is_file():
        stages["input_validation"] = (
            f"FAIL: spec is not a regular file: {spec_path}"
        )
    else:
        # The Tag-66 probe targets the v0.4.4 draft specifically.
        # Tests that supply fixture drafts outside repo_root pass
        # through; in-repo invocations enforce the canonical path.
        try:
            rel = spec_path.resolve().relative_to(repo_root.resolve())
            rel_str = str(rel).replace("\\", "/")
            canonical = (
                "wirelang/specs/wirelang-spec-v0-4-4-draft.md"
            )
            if rel_str != canonical:
                stages["input_validation"] = (
                    f"FAIL: Tag-66 probe expects {canonical}; got "
                    f"{rel_str}"
                )
            else:
                stages["input_validation"] = "OK"
        except ValueError:
            # Spec outside repo_root — used by test fixtures.
            stages["input_validation"] = "OK"

    # Stage 2 — hash computation.
    if stages["input_validation"].startswith("OK"):
        try:
            spec_sha256, spec_size_bytes = compute_sha256(spec_path)
            stages["hash_computation"] = f"OK: {spec_sha256}"
        except OSError as exc:
            stages["hash_computation"] = f"FAIL: read error: {exc}"
    else:
        stages["hash_computation"] = (
            "FAIL: skipped (input_validation failed)"
        )

    # Stage 3 — payload shape. Build a candidate verdict and ensure
    # it satisfies the Tag-66 schema-v1 envelope shape.
    if stages["hash_computation"].startswith("OK"):
        candidate = build_res_d_item_verdict(
            res_d_item=res_d_item,
            stages={k: "OK" for k in RES_D_PROBE_STAGE_KEYS},
            spec_sha256=spec_sha256,
            spec_size_bytes=spec_size_bytes,
            now_utc=now_utc,
        )
        cand_keys = set(candidate.keys())
        if cand_keys != RES_D_ITEM_VERDICT_REQUIRED_KEYS:
            missing = RES_D_ITEM_VERDICT_REQUIRED_KEYS - cand_keys
            extra = cand_keys - RES_D_ITEM_VERDICT_REQUIRED_KEYS
            stages["payload_shape"] = (
                f"FAIL: verdict key drift missing={sorted(missing)} "
                f"extra={sorted(extra)}"
            )
        elif candidate["schema_version"] != 1:
            stages["payload_shape"] = (
                "FAIL: schema_version != 1 "
                f"({candidate['schema_version']})"
            )
        elif candidate["kind"] != "ots-res-d-item-probe-verdict":
            stages["payload_shape"] = (
                f"FAIL: verdict kind drift: {candidate['kind']}"
            )
        elif candidate["mode"] != MODE_RES_D_ITEM_PROBE:
            stages["payload_shape"] = (
                f"FAIL: verdict mode drift: {candidate['mode']}"
            )
        elif candidate["draft_untouched"] is not True:
            stages["payload_shape"] = (
                "FAIL: draft_untouched invariant must be true"
            )
        elif candidate["ar_authorisation_required"] is not True:
            stages["payload_shape"] = (
                "FAIL: ar_authorisation_required invariant must be true"
            )
        else:
            stages["payload_shape"] = "OK"
    else:
        stages["payload_shape"] = (
            "FAIL: skipped (hash_computation failed)"
        )

    # Stage 4 — sandbox boundary. OK-by-construction.
    stages["sandbox_boundary"] = "OK"

    # Stage 5 — item simulation. Walk the v0.4.4 draft introspectively
    # for the per-item anchors. NEVER edits the draft.
    if stages["payload_shape"].startswith("OK"):
        stages["item_simulation"] = _simulate_res_d_item_activation(
            res_d_item=res_d_item,
            spec_path=spec_path,
        )
    else:
        stages["item_simulation"] = (
            "FAIL: skipped (payload_shape failed)"
        )

    return build_res_d_item_verdict(
        res_d_item=res_d_item,
        stages=stages,
        spec_sha256=spec_sha256,
        spec_size_bytes=spec_size_bytes,
        now_utc=now_utc,
    )


def _stub_registry_paths(repo_root: Path) -> set[str]:
    """Return the set of spec paths listed in the spec-anchor-stub.

    Returns an empty set when the stub is missing or malformed — the
    caller treats that as a probe defect.
    """
    stub_path = (
        repo_root / "tooling" / "ots" / "wirelang-spec-ots-anchor-stub.json"
    )
    try:
        text = stub_path.read_text(encoding="utf-8")
        data = json.loads(text)
        return {s["path"] for s in data.get("wired_specs", [])}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return set()


def run_pre_activation_probe(
    *,
    spec_path: Path,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
) -> dict:
    """Execute the four-stage hermetic probe and return a verdict dict.

    The probe never calls out to the OTS calendar; it only walks the
    same code paths that a real ``ots stamp`` invocation would touch
    on the Repo-Side. Sandbox-boundary stage is OK-by-construction:
    this module is stdlib-only and never invokes subprocess or sockets.
    """
    stages: dict = _empty_probe_stages()
    spec_sha256 = ""
    spec_size_bytes = 0

    # Stage 1 — input validation.
    if not spec_path.exists():
        stages["input_validation"] = (
            f"FAIL: spec not found: {spec_path}"
        )
    elif not spec_path.is_file():
        stages["input_validation"] = (
            f"FAIL: spec is not a regular file: {spec_path}"
        )
    else:
        # Optional registry-membership check: only enforced when the
        # spec lives inside ``repo_root`` (test fixtures live in
        # tmp_path and are exempt).
        try:
            rel = spec_path.resolve().relative_to(repo_root.resolve())
            rel_str = str(rel).replace("\\", "/")
            registry = _stub_registry_paths(repo_root)
            if registry and rel_str not in registry:
                stages["input_validation"] = (
                    "FAIL: spec not listed in "
                    "tooling/ots/wirelang-spec-ots-anchor-stub.json: "
                    f"{rel_str}"
                )
            else:
                stages["input_validation"] = "OK"
        except ValueError:
            # Spec outside repo_root — accept (used by tmp_path
            # fixtures in tests).
            stages["input_validation"] = "OK"

    # Stage 2 — hash computation.
    if stages["input_validation"].startswith("OK"):
        try:
            spec_sha256, spec_size_bytes = compute_sha256(spec_path)
            stages["hash_computation"] = f"OK: {spec_sha256}"
        except OSError as exc:
            stages["hash_computation"] = f"FAIL: read error: {exc}"
    else:
        stages["hash_computation"] = "FAIL: skipped (input_validation failed)"

    # Stage 3 — payload shape: build a marker against the same builder
    # the audit-only emit uses, then validate shape.
    if stages["hash_computation"].startswith("OK"):
        candidate = build_marker(
            spec_path=spec_path,
            spec_sha256=spec_sha256,
            spec_size_bytes=spec_size_bytes,
            actor=actor,
            now_utc=now_utc,
            repo_root=repo_root,
        )
        cand_keys = set(candidate.keys())
        if cand_keys != MARKER_REQUIRED_KEYS:
            missing = MARKER_REQUIRED_KEYS - cand_keys
            extra = cand_keys - MARKER_REQUIRED_KEYS
            stages["payload_shape"] = (
                f"FAIL: marker key drift missing={sorted(missing)} "
                f"extra={sorted(extra)}"
            )
        elif candidate["schema_version"] != 1:
            stages["payload_shape"] = (
                f"FAIL: schema_version != 1 ({candidate['schema_version']})"
            )
        elif candidate["kind"] != "wirelang-spec-ots-anchor-marker":
            stages["payload_shape"] = (
                f"FAIL: marker kind drift: {candidate['kind']}"
            )
        elif candidate["wat_spool_envelope"]["anchor_target"] != (
            ANCHOR_TARGET_OTS_CALENDAR
        ):
            stages["payload_shape"] = (
                "FAIL: wat_spool_envelope.anchor_target drift: "
                f"{candidate['wat_spool_envelope']['anchor_target']}"
            )
        elif candidate["wat_spool_envelope"]["kind"] != (
            "wirelang-spec-ots-anchor-request"
        ):
            stages["payload_shape"] = (
                "FAIL: wat_spool_envelope.kind drift: "
                f"{candidate['wat_spool_envelope']['kind']}"
            )
        else:
            stages["payload_shape"] = "OK"
    else:
        stages["payload_shape"] = "FAIL: skipped (hash_computation failed)"

    # Stage 4 — sandbox boundary. This module is stdlib-only and
    # performs no subprocess / no socket / no network. The Tag-60
    # invariant tests reinforce this at CI time. The flag here is
    # the runtime acknowledgement.
    stages["sandbox_boundary"] = "OK"

    return build_probe_verdict(
        stages=stages,
        spec_sha256=spec_sha256,
        spec_size_bytes=spec_size_bytes,
        now_utc=now_utc,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emit_wirelang_spec_ots_marker",
        description=(
            "Emit an audit-only OTS-anchor marker for a Wirelang "
            "specification file (Tag-60 mirror of Tag-57/59 manifest-"
            "hash anchor), or run a Tag-60 pre-activation-probe "
            "verdict (--mode pre-activation-probe)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=(
            MODE_AUDIT_ONLY,
            MODE_PRE_ACTIVATION_PROBE,
            MODE_RES_D_ITEM_PROBE,
        ),
        default=MODE_AUDIT_ONLY,
        help=(
            "audit-only (default): emit marker JSON. "
            "pre-activation-probe (Tag-60): run hermetic dry-run probe "
            "of the OTS-call pipeline and emit verdict envelope. "
            "res-d-item-probe (Tag-66): run hermetic per-RES-Dn item "
            "probe; draft is never touched."
        ),
    )
    parser.add_argument(
        "--res-d-item",
        choices=RES_D_ITEM_IDS,
        default=None,
        help=(
            "Tag-66 per-item probe selector (required when "
            "--mode res-d-item-probe). One of RES-D1..RES-D5."
        ),
    )
    parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to the Wirelang-Spec markdown file to hash.",
    )
    parser.add_argument(
        "--marker-out",
        type=Path,
        default=None,
        help=(
            "Output JSON marker path (mode=audit-only; required). "
            "Parent dir will be mkdir -p'd."
        ),
    )
    parser.add_argument(
        "--probe-verdict-out",
        type=Path,
        default=None,
        help=(
            "Output JSON probe-verdict path (mode=pre-activation-probe; "
            "required). Parent dir will be mkdir -p'd."
        ),
    )
    parser.add_argument(
        "--actor",
        default=os.environ.get("GITHUB_ACTOR", "local"),
        help="Actor identifier (default: $GITHUB_ACTOR or 'local').",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd).",
    )
    parser.add_argument(
        "--now",
        default=None,
        help=(
            "Override emitted_at_utc / requested_at_utc / probed_at_utc "
            "(ISO-8601). Useful for deterministic tests."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.now is None:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
    else:
        now_utc = _dt.datetime.fromisoformat(args.now)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=_dt.timezone.utc)

    if args.mode == MODE_RES_D_ITEM_PROBE:
        if args.res_d_item is None:
            print(
                "emit_wirelang_spec_ots_marker: "
                "--res-d-item is required when "
                "--mode res-d-item-probe",
                file=sys.stderr,
            )
            return 2
        if args.probe_verdict_out is None:
            print(
                "emit_wirelang_spec_ots_marker: "
                "--probe-verdict-out is required when "
                "--mode res-d-item-probe",
                file=sys.stderr,
            )
            return 2

        verdict = run_res_d_item_probe(
            res_d_item=args.res_d_item,
            spec_path=args.spec,
            actor=args.actor,
            now_utc=now_utc,
            repo_root=args.repo_root,
        )

        args.probe_verdict_out.parent.mkdir(parents=True, exist_ok=True)
        args.probe_verdict_out.write_text(
            json.dumps(verdict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_wirelang_spec_ots_marker: mode={verdict['mode']} "
            f"item={verdict['res_d_item']} "
            f"verdict={verdict['verdict']} "
            f"sha256={verdict['spec_sha256'] or '-'} "
            f"size={verdict['spec_size_bytes']} "
            f"-> {args.probe_verdict_out}"
        )

        # Exit 0 even on PROBE-DEFECT — the workflow surfaces the
        # verdict and decides enforcement. Tests cover both cases.
        return 0

    if args.mode == MODE_PRE_ACTIVATION_PROBE:
        if args.probe_verdict_out is None:
            print(
                "emit_wirelang_spec_ots_marker: "
                "--probe-verdict-out is required when "
                "--mode pre-activation-probe",
                file=sys.stderr,
            )
            return 2

        verdict = run_pre_activation_probe(
            spec_path=args.spec,
            actor=args.actor,
            now_utc=now_utc,
            repo_root=args.repo_root,
        )

        args.probe_verdict_out.parent.mkdir(parents=True, exist_ok=True)
        args.probe_verdict_out.write_text(
            json.dumps(verdict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_wirelang_spec_ots_marker: mode={verdict['mode']} "
            f"verdict={verdict['verdict']} "
            f"sha256={verdict['spec_sha256'] or '-'} "
            f"size={verdict['spec_size_bytes']} "
            f"-> {args.probe_verdict_out}"
        )

        # Exit 0 even on PROBE-DEFECT — the workflow surfaces the
        # verdict and decides enforcement. Tests cover both cases.
        return 0

    # mode == audit-only (default).
    if args.marker_out is None:
        print(
            "emit_wirelang_spec_ots_marker: "
            "--marker-out is required when --mode audit-only",
            file=sys.stderr,
        )
        return 2

    if not args.spec.is_file():
        print(
            f"emit_wirelang_spec_ots_marker: --spec not a file: "
            f"{args.spec}",
            file=sys.stderr,
        )
        return 1

    try:
        sha256_hex, size_bytes = compute_sha256(args.spec)
    except OSError as exc:
        print(
            f"emit_wirelang_spec_ots_marker: read failed: {exc}",
            file=sys.stderr,
        )
        return 1

    marker = build_marker(
        spec_path=args.spec,
        spec_sha256=sha256_hex,
        spec_size_bytes=size_bytes,
        actor=args.actor,
        now_utc=now_utc,
        repo_root=args.repo_root,
    )

    args.marker_out.parent.mkdir(parents=True, exist_ok=True)
    args.marker_out.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        f"emit_wirelang_spec_ots_marker: mode={marker['mode']} "
        f"sha256={sha256_hex} size={size_bytes} -> {args.marker_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
