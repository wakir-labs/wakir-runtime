#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""Python helpers backing ``scripts/demo-proof.sh``.

The bash driver shells out to this script for the five sub-steps. We
keep the Python surface in one file (rather than one per step) so
``demo-proof.sh`` only has one path to find and tests only have one
module to import.

Sub-commands
------------

- ``build-event``        — Step 1: emit a B1-canonical demo event.
- ``run-bridge``         — Step 2: call ``write_bridge_audit`` against
                           a temp spool + activity log.
- ``build-manifest``     — Step 3: project the spool's leaf record
                           into the aggregator's expected input shape
                           and drive ``wakir-merkle build``.
- ``verify-proof``       — Step 4: rebuild the inclusion proof and
                           verify it against the manifest root.
- ``fixture-verify``     — Step 5 fallback: re-derive the root from
                           the manifest's leaves to confirm the
                           runtime-local verifier and writer agree.

Each sub-command writes a JSON output file at ``--out`` so the bash
driver can ``jq`` the result without ever parsing Python prints.

The module is intentionally importable from tests: each sub-command
is a thin wrapper around a top-level ``do_*`` function so test code
can call ``do_build_event(...)`` directly without subprocessing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Path bootstrapping
# ---------------------------------------------------------------------------

# When ``demo-proof.sh`` invokes this file directly, the repository
# root is not necessarily on sys.path. Add it so ``import wat`` /
# ``import wirelang`` works without a pip install.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Constants — kept narrow on purpose; we are not building a parallel
# event schema here.
# ---------------------------------------------------------------------------

#: Demo event ID. Deterministic so the proof is reproducible across
#: runs; tests can override via ``--event-id`` if they want to vary it.
DEFAULT_EVENT_ID = "wakir-demo-proof-event-0001"

#: Demo persona slug. Match the bridge writer's expected lower-case
#: convention.
DEFAULT_PERSONA = "demo"

#: Demo capability-token hash. Pinned to the all-zero 32-byte SHA-256
#: so the four-tuple has a stable canonical form for the audit-demo
#: trail; production frames would carry the real Macaroon token hash.
DEFAULT_CAPABILITY_HASH = "0" * 64


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, obj: Any) -> None:
    """Write ``obj`` to ``path`` as deterministic UTF-8 JSON.

    ``sort_keys=True`` lets the operator's diff workflow compare two
    demo runs without spurious key-order noise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Step 1 — build event
# ---------------------------------------------------------------------------


def _event_time_for_hour(hour: str) -> str:
    """Return an RFC-3339 timestamp inside ``hour`` (YYYY-MM-DDTHH).

    Pinned to ``:00:00Z`` so two demo runs against the same hour
    produce byte-identical events.
    """
    if len(hour) != 13 or hour[4] != "-" or hour[7] != "-" or hour[10] != "T":
        raise ValueError(f"hour {hour!r} not in YYYY-MM-DDTHH form")
    return f"{hour}:00:00Z"


def do_build_event(
    *,
    hour: str,
    out: Path,
    hash_out: Path,
    event_id: str = DEFAULT_EVENT_ID,
    capability_hash: str = DEFAULT_CAPABILITY_HASH,
) -> Dict[str, Any]:
    """Build a demo event matching the wakir-protocol B1 four-tuple.

    The payload is intentionally tiny (a deterministic JSON object
    with one string field) so a human auditor can ``less`` it and see
    the entire content. We compute the SHA-256 of the raw bytes
    written to disk and emit it as the ``payload_hash`` for the
    leaf-hash recipe.

    Returns the event dict (also written to ``out``) and additionally
    writes the hex payload hash to ``hash_out`` so the bash driver can
    pass it forward without re-hashing.
    """
    event_time = _event_time_for_hour(hour)
    payload_obj: Dict[str, Any] = {
        "schema": "wakir-protocol-demo/v1",
        "event_id": event_id,
        "time": event_time,
        "description": "demo-proof external-audit credibility-jump",
    }
    payload_bytes = (
        json.dumps(payload_obj, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        fh.write(payload_bytes)

    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    hash_out.parent.mkdir(parents=True, exist_ok=True)
    hash_out.write_text(payload_hash, encoding="utf-8")

    # Project a manifest-shaped "envelope" beside the payload so step 3
    # has all four B1 fields without round-tripping through the bridge
    # spool record format.
    envelope = {
        "event_id": event_id,
        "time": event_time,
        "payload_hash": payload_hash,
        "capability_token_hash": capability_hash,
        "payload_path": str(out),
    }
    _write_json(out.with_suffix(".envelope.json"), envelope)
    return envelope


# ---------------------------------------------------------------------------
# Step 2 — bridge writer
# ---------------------------------------------------------------------------


def do_run_bridge(
    *,
    payload: Path,
    payload_hash: str,
    spool_root: Path,
    activity_log: Path,
    event_time: str,
    out: Path,
    persona_id: str = DEFAULT_PERSONA,
    action_type: str = "demo-proof",
) -> Dict[str, Any]:
    """Invoke the bridge-audit writer once.

    We import the writer lazily so test code can monkey-patch or stub
    it without paying the import cost on every call.
    """
    from wat.anchor.bridge_audit_writer import write_bridge_audit  # noqa: WPS433

    spool_root.mkdir(parents=True, exist_ok=True)
    activity_log.parent.mkdir(parents=True, exist_ok=True)

    result = write_bridge_audit(
        persona_id=persona_id,
        action_type=action_type,
        payload_hash=payload_hash,
        metadata={"ref": f"demo-proof:{payload.name}"},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time=event_time,
    )

    result_dict = {
        "status": result.status,
        "persona_id": result.persona_id,
        "action_type": result.action_type,
        "event_time": result.event_time,
        "wat_spool_path": str(result.wat_spool_path) if result.wat_spool_path else "",
        "activity_log_path": str(result.activity_log_path) if result.activity_log_path else "",
        "error": result.error,
    }
    _write_json(out, result_dict)
    return result_dict


# ---------------------------------------------------------------------------
# Step 3 — manifest aggregator
# ---------------------------------------------------------------------------


def _spool_jsonl_to_aggregator_events(
    spool_file: Path,
    *,
    envelope_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Project bridge-writer spool records into aggregator input shape.

    The bridge writer's spool record contains the four B1 fields as
    top-level attributes (see ``wat.anchor.bridge_audit_writer``).
    The aggregator CLI's ``--input-events`` consumer expects exactly
    these four keys per line. When the spool record carries extra
    metadata we strip it.

    When ``envelope_path`` is supplied we fall back to the envelope's
    B1 tuple for any spool record missing a field. This handles the
    case where the bridge writer's spool format evolves slightly
    ahead of the demo: we still emit a valid aggregator-input
    document instead of failing the whole pipeline.
    """
    if not spool_file.exists():
        raise FileNotFoundError(f"spool file not found: {spool_file}")

    envelope: Optional[Dict[str, Any]] = None
    if envelope_path is not None and envelope_path.exists():
        envelope = _read_json(envelope_path)

    events: List[Dict[str, Any]] = []
    with spool_file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            record = json.loads(line)
            tuple_obj = {
                "event_id": record.get("event_id")
                or (envelope or {}).get("event_id", ""),
                "time": record.get("time")
                or record.get("event_time")
                or (envelope or {}).get("time", ""),
                "payload_hash": record.get("payload_hash")
                or (envelope or {}).get("payload_hash", ""),
                "capability_token_hash": record.get("capability_token_hash")
                or (envelope or {}).get("capability_token_hash", ""),
            }
            if not all(tuple_obj.values()):
                # Drop empty rows rather than letting the aggregator
                # die on a malformed spool entry — but record the
                # gap. ``capability_token_hash`` may legitimately be
                # absent in some flows; we require non-empty here for
                # the demo because the envelope always provides it.
                raise ValueError(
                    f"spool record missing B1 field: {tuple_obj!r}"
                )
            events.append(tuple_obj)
    return events


def do_build_manifest(
    *,
    spool_root: Path,
    hour: str,
    aggregator_input: Path,
    manifest_out: Path,
    persona_id: str = DEFAULT_PERSONA,
) -> Dict[str, Any]:
    """Drive the aggregator end-to-end for a single hour.

    Returns the manifest dict written to disk so test code can assert
    on the shape without re-reading the file.
    """
    from wat.cmd.aggregator_cli import build_command  # noqa: WPS433

    spool_file = spool_root / persona_id / f"{hour}.jsonl"
    envelope_path = aggregator_input.parent / "event.envelope.json"
    events = _spool_jsonl_to_aggregator_events(
        spool_file, envelope_path=envelope_path
    )

    aggregator_input.parent.mkdir(parents=True, exist_ok=True)
    with aggregator_input.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True) + "\n")

    manifest = build_command(
        hour=hour,
        input_events=aggregator_input,
        output_manifest=manifest_out,
    )
    return manifest


# ---------------------------------------------------------------------------
# Step 4 — inclusion proof
# ---------------------------------------------------------------------------


def do_verify_proof(
    *,
    manifest: Path,
    event: Path,
    out: Path,
) -> Dict[str, Any]:
    """Rebuild the inclusion proof for the demo event.

    The bridge writer rewrites ``event_id`` from the operator-supplied
    payload into a deterministic SHA-256-derived 32-hex digest before
    the leaf hits the manifest, so we cannot recompute the expected
    leaf hash from the envelope alone — the envelope's ``event_id``
    is the input identifier, but the manifest records the bridge's
    derived one.

    Instead we recompute the leaf hash from each manifest event row
    (all four B1 fields), match the demo event by ``payload_hash``
    (which the bridge passes through unchanged), rebuild the
    inclusion proof via ``merkle_proof``, and verify it against the
    manifest's stored root via ``verify_merkle_proof``. All three
    steps are local; no network or filesystem side-effects.
    """
    from wat.merkle.aggregator import (  # noqa: WPS433
        compute_leaf_hash,
        merkle_proof,
        verify_merkle_proof,
    )

    manifest_blob = _read_json(manifest)
    envelope = _read_json(event.with_suffix(".envelope.json"))
    target_payload_hash = envelope["payload_hash"]

    leaves: List[bytes] = []
    leaf_index = -1
    matched_event: Optional[Dict[str, Any]] = None
    for idx, ev in enumerate(manifest_blob.get("events", [])):
        leaf = compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        leaves.append(leaf)
        if ev["payload_hash"] == target_payload_hash and leaf_index < 0:
            leaf_index = idx
            matched_event = ev

    if leaf_index < 0 or matched_event is None:
        raise ValueError(
            f"demo event payload_hash {target_payload_hash!r} not found "
            "in manifest leaves; aggregator drift between bridge and "
            "manifest writer"
        )
    expected_leaf = leaves[leaf_index]

    proof = merkle_proof(leaves, leaf_index)
    root_hex = manifest_blob["merkle_root"]
    root_bytes = bytes.fromhex(root_hex)
    verified = verify_merkle_proof(expected_leaf, proof, root_bytes)

    result = {
        "verified": bool(verified),
        "leaf_index": leaf_index,
        "leaf_count": len(leaves),
        "proof_depth": len(proof),
        "merkle_root": root_hex,
        "leaf_hash_hex": expected_leaf.hex(),
    }
    _write_json(out, result)
    return result


# ---------------------------------------------------------------------------
# Step 5 — fixture-based fallback verifier
# ---------------------------------------------------------------------------


def do_fixture_verify(
    *,
    manifest: Path,
    out: Path,
) -> Dict[str, Any]:
    """Fallback for step 5 when ``wakir-verify`` is not installed.

    Re-derives the manifest root from the recorded leaves using the
    in-tree Merkle implementation and asserts byte-equality with the
    manifest's stored root. This does not exercise the cross-repo
    dependency leg; the bash driver marks the step ``skipped`` in the
    final demo report regardless of this function's success.
    """
    from wat.merkle.aggregator import build_merkle_tree, compute_leaf_hash  # noqa: WPS433

    blob = _read_json(manifest)
    leaves: List[bytes] = []
    for ev in blob.get("events", []):
        leaves.append(
            compute_leaf_hash(
                event_id=ev["event_id"],
                time=ev["time"],
                payload_hash=ev["payload_hash"],
                capability_token_hash=ev["capability_token_hash"],
            )
        )
    if not leaves:
        result = {"fixture_ok": False, "reason": "manifest has no events"}
        _write_json(out, result)
        return result

    root, _ = build_merkle_tree(leaves)
    fixture_ok = root.hex() == blob["merkle_root"]
    result = {
        "fixture_ok": fixture_ok,
        "rederived_root": root.hex(),
        "manifest_root": blob["merkle_root"],
    }
    _write_json(out, result)
    return result


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="demo_proof_helpers",
        description="Python sub-step helpers for scripts/demo-proof.sh.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("build-event", help="Step 1: build a B1 demo event.")
    p1.add_argument("--hour", required=True)
    p1.add_argument("--out", required=True, type=Path)
    p1.add_argument("--hash-out", required=True, type=Path)
    p1.add_argument("--event-id", default=DEFAULT_EVENT_ID)
    p1.add_argument("--capability-hash", default=DEFAULT_CAPABILITY_HASH)

    p2 = sub.add_parser("run-bridge", help="Step 2: drive write_bridge_audit.")
    p2.add_argument("--payload", required=True, type=Path)
    p2.add_argument("--payload-hash", required=True)
    p2.add_argument("--spool-root", required=True, type=Path)
    p2.add_argument("--activity-log", required=True, type=Path)
    p2.add_argument("--event-time", required=True)
    p2.add_argument("--out", required=True, type=Path)
    p2.add_argument("--persona", default=DEFAULT_PERSONA)

    p3 = sub.add_parser("build-manifest", help="Step 3: build hourly manifest.")
    p3.add_argument("--spool-root", required=True, type=Path)
    p3.add_argument("--hour", required=True)
    p3.add_argument("--aggregator-input", required=True, type=Path)
    p3.add_argument("--manifest-out", required=True, type=Path)
    p3.add_argument("--persona", default=DEFAULT_PERSONA)

    p4 = sub.add_parser("verify-proof", help="Step 4: rebuild + verify proof.")
    p4.add_argument("--manifest", required=True, type=Path)
    p4.add_argument("--event", required=True, type=Path)
    p4.add_argument("--out", required=True, type=Path)

    p5 = sub.add_parser(
        "fixture-verify",
        help="Step 5 fallback: re-derive manifest root locally.",
    )
    p5.add_argument("--manifest", required=True, type=Path)
    p5.add_argument("--out", required=True, type=Path)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "build-event":
        do_build_event(
            hour=args.hour,
            out=args.out,
            hash_out=args.hash_out,
            event_id=args.event_id,
            capability_hash=args.capability_hash,
        )
        return 0
    if args.cmd == "run-bridge":
        result = do_run_bridge(
            payload=args.payload,
            payload_hash=args.payload_hash,
            spool_root=args.spool_root,
            activity_log=args.activity_log,
            event_time=args.event_time,
            out=args.out,
            persona_id=args.persona,
        )
        return 0 if result["status"] == "ok" else 10
    if args.cmd == "build-manifest":
        do_build_manifest(
            spool_root=args.spool_root,
            hour=args.hour,
            aggregator_input=args.aggregator_input,
            manifest_out=args.manifest_out,
            persona_id=args.persona,
        )
        return 0
    if args.cmd == "verify-proof":
        result = do_verify_proof(
            manifest=args.manifest,
            event=args.event,
            out=args.out,
        )
        return 0 if result["verified"] else 10
    if args.cmd == "fixture-verify":
        result = do_fixture_verify(
            manifest=args.manifest,
            out=args.out,
        )
        return 0 if result["fixture_ok"] else 10

    parser.error(f"unknown sub-command: {args.cmd}")
    return 2  # pragma: no cover — argparse.error raises SystemExit


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CAPABILITY_HASH",
    "DEFAULT_EVENT_ID",
    "DEFAULT_PERSONA",
    "build_parser",
    "do_build_event",
    "do_build_manifest",
    "do_fixture_verify",
    "do_run_bridge",
    "do_verify_proof",
    "main",
]
