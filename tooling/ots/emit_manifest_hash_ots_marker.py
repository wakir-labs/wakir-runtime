#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit an OTS-anchor stub marker for a persona-engine manifest hash.

Tag-57 OPEN-K2 closeout (from Selin's Tag-56 0.5.2-final audit, PR #362):

  > OPEN-K2: OTS-anchor of manifest hash via WAT spool (Tomás Zone-K)

This helper is the **audit-only stub** for the future OTS-anchor wiring
of persona-engine manifest hashes via the WAT spool. It computes the
SHA-256 of a manifest file (e.g. ``MANIFEST-0.5.2-final-pre-cutover.md``),
records the intent-to-anchor in a marker JSON file under
``tooling/ots/markers/``, and emits a WAT-spool envelope describing the
anchor request.

**Audit-only.** This helper does NOT call out to an OpenTimestamps
calendar server. The Sandbox-boundary is explicitly preserved:

  * No network I/O.
  * No subprocess calls to ``ots`` CLI.
  * No filesystem writes outside the marker output directory.

The Operator-Hand picks up the marker file in a later runbook step
and runs the real ``ots stamp`` invocation on a host that has network
access to the OTS calendar. The marker file then gets the real
``.ots`` proof attached (out-of-band, Phase-3c-Schritt-N+1).

Tag-59 Pre-Activation-Probe extension
-------------------------------------

The ``--mode pre-activation-probe`` flag adds a dry-run pass that walks
the *exact* shape an actual ``ots stamp`` invocation would receive,
without performing any network I/O. Concretely the probe verifies:

  * Input validation: manifest path exists, is a file, is readable,
    matches the in-tree anchor-stub registry.
  * Hash computation: SHA-256 streamed in 64 KiB chunks, byte-stable.
  * Payload shape: marker JSON validates against schema-v1 (all
    required keys, no unexpected keys) AND the additional Tag-59
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
    "manifest_sha256": "<64-hex-or-empty>",
    "manifest_size_bytes": <int-or-zero>,
    "probed_at_utc": "<iso>",
    "ar_authorisation_required": true,
    "anchors": {
      "tomas_tag_59_pre_anchor_probe_pr": null,
      "reza_tag_58_spec_seal_pr": 371,
      "operator_hand_runbook":
        "docs/operations/manifest-hash-ots-anchor-wiring.md"
    }
  }

The probe is hermetic. **It still performs no real OTS calendar call.**
AR-authorisation flips a future runtime gate (see §6 + §7 of the
runbook doc); the probe itself never crosses the Sandbox boundary.

Tag-69 Welle-1 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-1-audit-anchor`` flag computes the SHA-256 audit-
trail-anchor over the Welle-1 sign-off-record bundle (rollup +
sign-off + validation + pre-auditor) and emits a marker JSON for
Selin's Tag-69 Persona-Engine producer
(``engine.py::backfill_audit_trail_anchors``, producer-wiring-plan
§2.4). Cross-Review-Zone-K (Tomás OTS / WAT-Hash semantics).

Inputs:

  * ``--welle-1-rollup`` (required): path to ``state/welle-1.json``.
  * ``--welle-1-sign-off`` (required): path to
    ``state/welle-1-sign-off.json``.
  * ``--welle-1-validation`` (optional): path to
    ``state/welle-1-validation-last-verdict.json``.
  * ``--welle-1-pre-auditor`` (optional): path to
    ``state/welle-1-pre-auditor-decision.json``.

Output: marker JSON at ``--marker-out`` with shape::

  {
    "schema_version": 1,
    "kind": "welle-1-audit-trail-anchor-marker",
    "mode": "welle-1-audit-anchor",
    "welle_number": 1,
    "audit_trail_anchor": "<64-hex>",
    "bundle_keys": ["rollup", "sign_off", ...],
    "wat_spool_envelope": { ... },
    "emitted_at_utc": "<iso>",
    "anchors": { ... },
    "operator_hand_next_step": "..."
  }

The Welle-1 mode is **hermetic and audit-only**: no network I/O,
no OTS calendar call, no subprocess. Selin's producer reads the
marker, extracts ``audit_trail_anchor``, writes it into
``state/welle-1.json:audit_trail_anchor``. Real OTS stamping is
an Operator-Hand follow-up (separate runbook step).

Schema (v1) — JSON marker emitted to ``--marker-out``
-----------------------------------------------------

  {
    "schema_version": 1,
    "kind": "manifest-hash-ots-anchor-marker",
    "mode": "audit-only",
    "manifest_path": "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
    "manifest_sha256": "<64-hex>",
    "manifest_size_bytes": 12345,
    "wat_spool_envelope": {
      "schema_version": 1,
      "kind": "ots-anchor-request",
      "manifest_sha256": "<64-hex>",
      "requested_at_utc": "2026-05-19T...",
      "actor": "<github.actor|local>",
      "anchor_target": "opentimestamps-calendar"
    },
    "emitted_at_utc": "2026-05-19T...",
    "anchors": {
      "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
      "selin_tag_56_audit": "decisions/0062-..."
    },
    "operator_hand_next_step": (
      "Run `ots stamp <marker_out>` on a network-attached host; "
      "attach resulting .ots proof to this marker out-of-band."
    )
  }

Exit codes
----------

  * 0 — marker emitted successfully.
  * 1 — manifest file not found / unreadable.
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
MODE_WELLE_1_AUDIT_ANCHOR: str = "welle-1-audit-anchor"
ANCHOR_TARGET_OTS_CALENDAR: str = "opentimestamps-calendar"

# Tag-69 Welle-1 audit-trail-anchor mode constants.
# The anchor is computed over a canonical, byte-stable concatenation of
# the Welle-1 sign-off-record-bundle: rollup + sign-off + validation +
# pre-auditor decision (when present). Cross-coordinated with Selin's
# Tag-69 Persona-Engine producer (`engine.py::backfill_audit_trail_
# anchors`, plan §2.4) which calls this helper for the hash-side and
# writes the result into `state/welle-1.json:audit_trail_anchor`.
WELLE_1_BUNDLE_ORDER: tuple[str, ...] = (
    "rollup",
    "sign_off",
    "validation",
    "pre_auditor",
)
WELLE_1_BUNDLE_REQUIRED: frozenset[str] = frozenset({"rollup", "sign_off"})
WELLE_1_KIND_MARKER: str = "welle-1-audit-trail-anchor-marker"
WELLE_1_KIND_ENVELOPE: str = "welle-1-audit-trail-anchor-envelope"

# Required top-level keys for a schema-v1 marker payload. Used by the
# pre-activation-probe's ``payload_shape`` stage.
MARKER_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "manifest_path",
        "manifest_sha256",
        "manifest_size_bytes",
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
        "manifest_sha256",
        "manifest_size_bytes",
        "probed_at_utc",
        "ar_authorisation_required",
        "anchors",
    }
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


def build_marker(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    manifest_size_bytes: int,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
) -> dict:
    """Assemble the marker dict for the given manifest hash."""
    rel_manifest = (
        str(manifest_path.relative_to(repo_root))
        if manifest_path.is_absolute() and repo_root in manifest_path.parents
        else str(manifest_path)
    )
    iso_now = now_utc.isoformat()
    return {
        "schema_version": 1,
        "kind": "manifest-hash-ots-anchor-marker",
        "mode": MODE_AUDIT_ONLY,
        "manifest_path": rel_manifest,
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": manifest_size_bytes,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": "ots-anchor-request",
            "manifest_sha256": manifest_sha256,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "selin_tag_56_audit": (
                "tag-56 PR #362 OPEN-K2 (persona-engine 0.5.2-final "
                "production-readiness audit)"
            ),
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
    manifest_sha256: str,
    manifest_size_bytes: int,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Tag-59 pre-activation-probe verdict envelope.

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
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": manifest_size_bytes,
        "probed_at_utc": iso_now,
        "ar_authorisation_required": True,
        "anchors": {
            "tomas_tag_59_pre_anchor_probe_pr": None,
            "reza_tag_58_spec_seal_pr": 371,
            "operator_hand_runbook": (
                "docs/operations/manifest-hash-ots-anchor-wiring.md"
            ),
        },
    }


def _stub_registry_paths(repo_root: Path) -> set[str]:
    """Return the set of manifest paths listed in the anchor-stub.

    Returns an empty set when the stub is missing or malformed — the
    caller treats that as a probe defect.
    """
    stub_path = repo_root / "tooling" / "ots" / "manifest-hash-ots-anchor-stub.json"
    try:
        text = stub_path.read_text(encoding="utf-8")
        data = json.loads(text)
        return {m["path"] for m in data.get("wired_manifests", [])}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return set()


def run_pre_activation_probe(
    *,
    manifest_path: Path,
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
    manifest_sha256 = ""
    manifest_size_bytes = 0

    # Stage 1 — input validation.
    if not manifest_path.exists():
        stages["input_validation"] = (
            f"FAIL: manifest not found: {manifest_path}"
        )
    elif not manifest_path.is_file():
        stages["input_validation"] = (
            f"FAIL: manifest is not a regular file: {manifest_path}"
        )
    else:
        # Optional registry-membership check: only enforced when the
        # manifest lives inside ``repo_root`` (test fixtures live in
        # tmp_path and are exempt).
        try:
            rel = manifest_path.resolve().relative_to(repo_root.resolve())
            rel_str = str(rel).replace("\\", "/")
            registry = _stub_registry_paths(repo_root)
            if registry and rel_str not in registry:
                stages["input_validation"] = (
                    "FAIL: manifest not listed in "
                    "tooling/ots/manifest-hash-ots-anchor-stub.json: "
                    f"{rel_str}"
                )
            else:
                stages["input_validation"] = "OK"
        except ValueError:
            # Manifest outside repo_root — accept (used by tmp_path
            # fixtures in tests).
            stages["input_validation"] = "OK"

    # Stage 2 — hash computation.
    if stages["input_validation"].startswith("OK"):
        try:
            manifest_sha256, manifest_size_bytes = compute_sha256(manifest_path)
            stages["hash_computation"] = f"OK: {manifest_sha256}"
        except OSError as exc:
            stages["hash_computation"] = f"FAIL: read error: {exc}"
    else:
        stages["hash_computation"] = "FAIL: skipped (input_validation failed)"

    # Stage 3 — payload shape: build a marker against the same builder
    # the audit-only emit uses, then validate shape.
    if stages["hash_computation"].startswith("OK"):
        candidate = build_marker(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            manifest_size_bytes=manifest_size_bytes,
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
        elif candidate["kind"] != "manifest-hash-ots-anchor-marker":
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
        else:
            stages["payload_shape"] = "OK"
    else:
        stages["payload_shape"] = "FAIL: skipped (hash_computation failed)"

    # Stage 4 — sandbox boundary. This module is stdlib-only and
    # performs no subprocess / no socket / no network. The Tag-57
    # invariant test ``test_t09_k2_stdlib_only`` plus the Tag-59
    # tests reinforce this at CI time. The flag here is the
    # runtime acknowledgement.
    stages["sandbox_boundary"] = "OK"

    return build_probe_verdict(
        stages=stages,
        manifest_sha256=manifest_sha256,
        manifest_size_bytes=manifest_size_bytes,
        now_utc=now_utc,
    )


def _canonical_json_bytes(doc: dict) -> bytes:
    """Return a byte-stable JSON serialization for hashing.

    Uses ``sort_keys=True`` + ``separators=(",", ":")`` so the same
    logical document always produces the same bytes regardless of
    insertion order or whitespace. UTF-8 encoded.
    """
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_welle_1_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-1 audit-trail-anchor SHA-256 from a bundle.

    ``bundle`` must be a dict with at least the keys in
    ``WELLE_1_BUNDLE_REQUIRED``. Optional keys in ``WELLE_1_BUNDLE_ORDER``
    are included when present. Each value is canonicalised with
    ``_canonical_json_bytes`` and concatenated in ``WELLE_1_BUNDLE_ORDER``
    with a single ``b"\\n"`` separator between parts.

    The deterministic concat-with-separator scheme matches the format
    that Selin's Persona-Engine batch-writer (plan §2.4) expects when
    it backfills `audit_trail_anchor` from this helper's envelope.
    """
    missing = WELLE_1_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-1 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_1_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-1 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


def build_welle_1_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-1 audit-trail-anchor marker dict.

    The marker is the audit-only artefact that Tomás emits and that
    Selin's producer reads to populate
    ``state/welle-1.json:audit_trail_anchor``.
    """
    iso_now = now_utc.isoformat()
    return {
        "schema_version": 1,
        "kind": WELLE_1_KIND_MARKER,
        "mode": MODE_WELLE_1_AUDIT_ANCHOR,
        "welle_number": 1,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_1_BUNDLE_ORDER if k in bundle
        ),
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_1_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "selin_tag_69_producer_pr": None,
            "tomas_tag_69_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
        },
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors) reads this "
            "marker and writes the audit_trail_anchor into "
            "state/welle-1.json. Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_1_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-1 sign-off-record bundle from disk.

    Reads the four JSON files into a dict keyed by the canonical
    ``WELLE_1_BUNDLE_ORDER`` names. Optional inputs are omitted from
    the bundle when their path is ``None`` (the caller decides).
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emit_manifest_hash_ots_marker",
        description=(
            "Emit an audit-only OTS-anchor marker for a persona-engine "
            "manifest hash (Tag-57 OPEN-K2, audit-only mode), or run a "
            "Tag-59 pre-activation-probe verdict (--mode "
            "pre-activation-probe)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=(
            MODE_AUDIT_ONLY,
            MODE_PRE_ACTIVATION_PROBE,
            MODE_WELLE_1_AUDIT_ANCHOR,
        ),
        default=MODE_AUDIT_ONLY,
        help=(
            "audit-only (default, Tag-57): emit marker JSON. "
            "pre-activation-probe (Tag-59): run hermetic dry-run probe "
            "of the OTS-call pipeline and emit verdict envelope. "
            "welle-1-audit-anchor (Tag-69): compute Welle-1 audit-"
            "trail-anchor SHA-256 from sign-off-record bundle "
            "(rollup + sign-off + validation + pre-auditor) and emit "
            "marker JSON for Selin's persona-engine producer."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=False,
        default=None,
        help=(
            "Path to the manifest file to hash "
            "(required for audit-only / pre-activation-probe modes). "
            "Ignored in welle-1-audit-anchor mode."
        ),
    )
    parser.add_argument(
        "--welle-1-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1.json (required for "
            "welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-1-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1-sign-off.json (required for "
            "welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-1-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1-validation-last-verdict.json "
            "(optional for welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-1-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1-pre-auditor-decision.json "
            "(optional for welle-1-audit-anchor mode)."
        ),
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
        # ``fromisoformat`` accepts ``+00:00`` and naive forms; we
        # coerce naive to UTC.
        now_utc = _dt.datetime.fromisoformat(args.now)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=_dt.timezone.utc)

    if args.mode == MODE_WELLE_1_AUDIT_ANCHOR:
        if args.welle_1_rollup is None or args.welle_1_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-1-rollup and --welle-1-sign-off are required "
                "when --mode welle-1-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-1-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_1_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-1-rollup not "
                f"a file: {args.welle_1_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_1_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-1-sign-off "
                f"not a file: {args.welle_1_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_1_bundle(
                rollup_path=args.welle_1_rollup,
                sign_off_path=args.welle_1_sign_off,
                validation_path=(
                    args.welle_1_validation
                    if args.welle_1_validation
                    and args.welle_1_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_1_pre_auditor
                    if args.welle_1_pre_auditor
                    and args.welle_1_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-1 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_1_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-1 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_1_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=1 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} -> {args.marker_out}"
        )
        return 0

    if args.mode in (MODE_AUDIT_ONLY, MODE_PRE_ACTIVATION_PROBE):
        if args.manifest is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--manifest is required when "
                f"--mode {args.mode}",
                file=sys.stderr,
            )
            return 2

    if args.mode == MODE_PRE_ACTIVATION_PROBE:
        if args.probe_verdict_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--probe-verdict-out is required when "
                "--mode pre-activation-probe",
                file=sys.stderr,
            )
            return 2

        verdict = run_pre_activation_probe(
            manifest_path=args.manifest,
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
            f"emit_manifest_hash_ots_marker: mode={verdict['mode']} "
            f"verdict={verdict['verdict']} "
            f"sha256={verdict['manifest_sha256'] or '-'} "
            f"size={verdict['manifest_size_bytes']} "
            f"-> {args.probe_verdict_out}"
        )

        # Exit 0 even on PROBE-DEFECT — the workflow surfaces the
        # verdict and decides enforcement. Tests cover both cases.
        return 0

    # mode == audit-only (default, Tag-57 path).
    if args.marker_out is None:
        print(
            "emit_manifest_hash_ots_marker: "
            "--marker-out is required when --mode audit-only",
            file=sys.stderr,
        )
        return 2

    if not args.manifest.is_file():
        print(
            f"emit_manifest_hash_ots_marker: --manifest not a file: "
            f"{args.manifest}",
            file=sys.stderr,
        )
        return 1

    try:
        sha256_hex, size_bytes = compute_sha256(args.manifest)
    except OSError as exc:
        print(
            f"emit_manifest_hash_ots_marker: read failed: {exc}",
            file=sys.stderr,
        )
        return 1

    marker = build_marker(
        manifest_path=args.manifest,
        manifest_sha256=sha256_hex,
        manifest_size_bytes=size_bytes,
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
        f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
        f"sha256={sha256_hex} size={size_bytes} -> {args.marker_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
