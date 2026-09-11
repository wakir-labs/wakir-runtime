#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""Python helpers backing ``scripts/demo-proof.sh``.

The bash driver is a thin orchestrator: it decides the step order and
the short-circuit rule, nothing else. Every piece of JSON handling
(step records, report assembly, field access, proof and verifier
artefacts) lives here so there is exactly one code path and one
interpreter requirement (``python3``). No ``jq``.

Sub-commands
------------

Pipeline steps (each writes a JSON result file at ``--out`` / the
named output path and returns 0 on success, 10 on a substance
failure, 20 for an explicit skip):

- ``build-event``      Step 1: emit a B1-canonical demo event.
- ``run-bridge``       Step 2: call ``write_bridge_audit`` against a
                       temp spool + activity log.
- ``build-manifest``   Step 3: project the spool's leaf record into
                       the aggregator's input shape and drive
                       ``wakir-merkle build``.
- ``verify-proof``     Step 4: build the ``wakir-inclusion-proof/v1``
                       artefact (with sibling hashes) and verify it
                       against the manifest root in-tree.
- ``external-verify``  Step 5: re-verify manifest + proof through the
                       *wakir-verify library* (``wakir_verify.manifest``,
                       ``wakir_verify.merkle_proof``). ``skipped`` with
                       a reason when the package is not importable.

Driver plumbing (used by the bash script instead of ``jq``):

- ``emit-step``        Append one validated step record to the
                       steps file.
- ``assemble-report``  Fold the steps file into the final
                       ``wakir-demo-proof/v1`` report; fills missing
                       steps with ``not_run`` and computes the
                       aggregate exit code.
- ``json-get``         Print one scalar field from a JSON file.

The module is importable from tests: each sub-command is a thin
wrapper around a top-level ``do_*`` function.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


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
# Constants
# ---------------------------------------------------------------------------

#: Report envelope identifier.
REPORT_SCHEMA = "wakir-demo-proof/v1"

#: Proof artefact identifier (schema draft:
#: ``wirelang/schemas/wakir-inclusion-proof-v1.json``; canonical copy
#: is destined for wakir-protocol).
PROOF_SCHEMA = "wakir-inclusion-proof/v1"

#: The five steps, in the only order the report may present them.
STEP_NAMES: Tuple[str, ...] = (
    "protocol_event",
    "runtime_bridge",
    "merkle_manifest",
    "inclusion_proof",
    "external_verify",
)

#: Per-step exit codes. ``EXIT_NOT_RUN`` is assigned by the report
#: assembler for steps that never executed because an upstream step
#: failed; it is never returned by a step itself.
EXIT_OK = 0
EXIT_FAILED = 10
EXIT_SKIPPED = 20
EXIT_NOT_RUN = 30

STATUS_BY_EXIT = {
    EXIT_OK: "ok",
    EXIT_FAILED: "failed",
    EXIT_SKIPPED: "skipped",
    EXIT_NOT_RUN: "not_run",
}
VALID_STATUSES = frozenset(STATUS_BY_EXIT.values())

#: Demo event ID. Deterministic so the proof is reproducible across
#: runs; tests can override via ``--event-id`` if they want to vary it.
DEFAULT_EVENT_ID = "wakir-demo-proof-event-0001"

#: Demo persona slug. Match the bridge writer's expected lower-case
#: convention.
DEFAULT_PERSONA = "demo"

#: Demo capability-token hash. Pinned to the all-zero 32-byte SHA-256
#: so the four-tuple has a stable canonical form; production frames
#: would carry the real Macaroon token hash.
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


def _read_text_or_empty(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


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
    with one string field) so a human reviewer can ``less`` it and
    see the entire content. We compute the SHA-256 of the raw bytes
    written to disk and emit it as the ``payload_hash`` for the
    leaf-hash recipe.

    Returns the envelope dict (also written to ``<out>.envelope.json``)
    and additionally writes the hex payload hash to ``hash_out`` so
    the bash driver can pass it forward without re-hashing.
    """
    event_time = _event_time_for_hour(hour)
    payload_obj: Dict[str, Any] = {
        "schema": "wakir-protocol-demo/v1",
        "event_id": event_id,
        "time": event_time,
        "description": "wakir demo-proof event",
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
                # A malformed spool entry is a hard error, not a row to
                # drop silently. ``capability_token_hash`` may be absent
                # in some flows; the demo envelope always provides it.
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
# Step 4 — inclusion proof (wakir-inclusion-proof/v1)
# ---------------------------------------------------------------------------


def _manifest_leaves(manifest_blob: Dict[str, Any]) -> List[bytes]:
    """Recompute every leaf hash from the manifest's B1 event rows."""
    from wat.merkle.aggregator import compute_leaf_hash  # noqa: WPS433

    leaves: List[bytes] = []
    for ev in manifest_blob.get("events", []):
        leaves.append(
            compute_leaf_hash(
                event_id=ev["event_id"],
                time=ev["time"],
                payload_hash=ev["payload_hash"],
                capability_token_hash=ev["capability_token_hash"],
            )
        )
    return leaves


def do_verify_proof(
    *,
    manifest: Path,
    event: Path,
    out: Path,
) -> Dict[str, Any]:
    """Build and verify the inclusion proof for the demo event.

    The bridge writer rewrites ``event_id`` from the operator-supplied
    payload into a deterministic SHA-256-derived 32-hex digest before
    the leaf hits the manifest, so we cannot recompute the expected
    leaf hash from the envelope alone. Instead we recompute the leaf
    hash from each manifest event row (all four B1 fields), match the
    demo event by ``payload_hash`` (which the bridge passes through
    unchanged), build the inclusion proof via ``merkle_proof`` and
    verify it against the manifest's stored root.

    The artefact written to ``out`` is a ``wakir-inclusion-proof/v1``
    document. It carries the sibling hashes with their side markers
    so a third party can recompute the root with nothing but SHA-256:
    start at ``leaf_hash``, then for each sibling bottom-up hash
    ``sibling || current`` when ``side == "L"`` or ``current ||
    sibling`` when ``side == "R"``.

    Returns ``{"proof": <artefact>, "verified": <bool>}``. The verdict
    is deliberately *not* part of the artefact: a proof is data, the
    verdict belongs to whoever checks it.
    """
    from wat.merkle.aggregator import (  # noqa: WPS433
        merkle_proof,
        verify_merkle_proof,
    )

    manifest_blob = _read_json(manifest)
    envelope = _read_json(event.with_suffix(".envelope.json"))
    target_payload_hash = envelope["payload_hash"]

    leaves = _manifest_leaves(manifest_blob)
    leaf_index = -1
    matched_event: Optional[Dict[str, Any]] = None
    for idx, ev in enumerate(manifest_blob.get("events", [])):
        if ev["payload_hash"] == target_payload_hash:
            leaf_index = idx
            matched_event = ev
            break

    if leaf_index < 0 or matched_event is None:
        raise ValueError(
            f"demo event payload_hash {target_payload_hash!r} not found "
            "in manifest leaves; aggregator drift between bridge and "
            "manifest writer"
        )
    expected_leaf = leaves[leaf_index]

    proof = merkle_proof(leaves, leaf_index)
    root_hex = manifest_blob["merkle_root"]
    verified = verify_merkle_proof(expected_leaf, proof, bytes.fromhex(root_hex))

    artefact: Dict[str, Any] = {
        "schema": PROOF_SCHEMA,
        "manifest_version": manifest_blob.get("version", ""),
        "hour": manifest_blob.get("hour_slot"),
        "merkle_root": root_hex,
        "leaf_hash": expected_leaf.hex(),
        "leaf_index": leaf_index,
        "leaf_count": len(leaves),
        "event_id": matched_event["event_id"],
        "siblings": [
            {"hash": sibling.hex(), "side": side} for sibling, side in proof
        ],
    }
    _write_json(out, artefact)
    return {"proof": artefact, "verified": bool(verified)}


def do_local_root_check(*, manifest: Path) -> Dict[str, Any]:
    """Re-derive the manifest root from its leaves with the in-tree tree.

    Used by step 5 when wakir-verify is not importable so the
    ``skipped`` record still carries a local consistency signal. This
    does not exercise the cross-repo leg and never upgrades the step
    to ``ok``.
    """
    from wat.merkle.aggregator import build_merkle_tree  # noqa: WPS433

    blob = _read_json(manifest)
    leaves = _manifest_leaves(blob)
    if not leaves:
        return {"root_ok": False, "reason": "manifest has no events"}
    root, _ = build_merkle_tree(leaves)
    return {
        "root_ok": root.hex() == blob["merkle_root"],
        "rederived_root": root.hex(),
        "manifest_root": blob["merkle_root"],
    }


# ---------------------------------------------------------------------------
# Step 5 — external verify via the wakir-verify library
# ---------------------------------------------------------------------------


def _wakir_verify_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("wakir-verify")
        except PackageNotFoundError:
            return "unknown"
    except Exception:  # pragma: no cover — importlib.metadata is stdlib
        return "unknown"


def do_external_verify(
    *,
    manifest: Path,
    proof: Path,
    out: Path,
    simulate_missing: bool = False,
) -> Dict[str, Any]:
    """Re-verify manifest and inclusion proof through wakir-verify.

    This is the cross-repo leg: the manifest written by the runtime
    aggregator is loaded by ``wakir_verify.manifest``, its root is
    re-derived by the verifier's own Merkle code, and the
    ``wakir-inclusion-proof/v1`` artefact from step 4 is checked with
    ``wakir_verify.merkle_proof.verify_merkle_proof``. No network, no
    CLI, no new verifier pole.

    Result ``status``:

    - ``ok``       wakir_verify importable and every check true.
    - ``failed``   wakir_verify importable but a check is false.
    - ``skipped``  wakir_verify not importable; ``reason`` says so.
      The in-tree root re-derivation still runs so the record is not
      empty, but it cannot turn the step green.

    ``simulate_missing`` is a test hook (driver only forwards it under
    ``DEMO_PROOF_TEST_MODE=1``).
    """
    try:
        if simulate_missing:
            raise ImportError("simulated missing package (test mode)")
        from wakir_verify import manifest as wv_manifest  # noqa: WPS433
        from wakir_verify import merkle_proof as wv_merkle  # noqa: WPS433
    except ImportError as exc:
        local = do_local_root_check(manifest=manifest)
        result: Dict[str, Any] = {
            "status": "skipped",
            "exit_code": EXIT_SKIPPED,
            "mode": "library",
            "reason": (
                f"wakir_verify not importable ({exc}); install wakir-verify "
                "into the active Python environment to run the cross-repo leg"
            ),
            "local_root_rederived": bool(local.get("root_ok")),
        }
        _write_json(out, result)
        return result

    loaded = wv_manifest.load_manifest_from_file(manifest)
    manifest_consistent = bool(wv_manifest.compute_manifest_consistency(loaded))

    proof_blob = _read_json(proof)
    if proof_blob.get("schema") != PROOF_SCHEMA:
        raise ValueError(
            f"proof artefact schema {proof_blob.get('schema')!r} != {PROOF_SCHEMA!r}"
        )
    leaf = bytes.fromhex(proof_blob["leaf_hash"])
    siblings = [
        (bytes.fromhex(s["hash"]), s["side"]) for s in proof_blob["siblings"]
    ]
    root_match = loaded.merkle_root.hex() == proof_blob["merkle_root"]
    leaf_hashes = list(loaded.leaf_hashes)
    leaf_present = (
        0 <= proof_blob["leaf_index"] < len(leaf_hashes)
        and leaf_hashes[proof_blob["leaf_index"]] == leaf
    )
    proof_verified = bool(
        wv_merkle.verify_merkle_proof(leaf, siblings, loaded.merkle_root)
    )

    ok = manifest_consistent and root_match and leaf_present and proof_verified
    result = {
        "status": "ok" if ok else "failed",
        "exit_code": EXIT_OK if ok else EXIT_FAILED,
        "mode": "library",
        "wakir_verify_version": _wakir_verify_version(),
        "manifest_consistent": manifest_consistent,
        "root_match": root_match,
        "leaf_present": leaf_present,
        "proof_verified": proof_verified,
        "leaf_count": len(leaf_hashes),
    }
    _write_json(out, result)
    return result


# ---------------------------------------------------------------------------
# Driver plumbing — step records, report assembly, field access
# ---------------------------------------------------------------------------


def _parse_kv(pairs: Sequence[str], *, as_int: bool) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {pair!r}")
        parsed[key] = int(value) if as_int else value
    return parsed


def _pick_fields(blob: Dict[str, Any], pick: Optional[str]) -> Dict[str, Any]:
    """Select ``a,b:alias,c`` from ``blob``; no ``pick`` copies everything."""
    if not pick:
        return dict(blob)
    picked: Dict[str, Any] = {}
    for spec in pick.split(","):
        spec = spec.strip()
        if not spec:
            continue
        key, _, alias = spec.partition(":")
        if key in blob:
            picked[alias or key] = blob[key]
    return picked


def do_emit_step(
    *,
    steps_file: Path,
    name: str,
    status: str,
    code: int,
    details_json: Optional[str] = None,
    result_file: Optional[Path] = None,
    pick: Optional[str] = None,
    kv: Sequence[str] = (),
    int_kv: Sequence[str] = (),
    error_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append one validated step record to ``steps_file``.

    ``details`` is assembled from, in order: ``details_json`` (must be
    a JSON object), fields picked from ``result_file``, ``kv`` string
    pairs, ``int_kv`` integer pairs, and the contents of ``error_file``
    under ``details.error``. The record is validated before it is
    written, so a malformed detail cannot silently drop a step.
    """
    if name not in STEP_NAMES:
        raise ValueError(f"unknown step name {name!r}; expected one of {STEP_NAMES}")
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {sorted(VALID_STATUSES)}")
    if STATUS_BY_EXIT.get(code) != status:
        raise ValueError(f"exit code {code} does not match status {status!r}")

    details: Dict[str, Any] = {}
    if details_json:
        parsed = json.loads(details_json)
        if not isinstance(parsed, dict):
            raise ValueError("--details-json must be a JSON object")
        details.update(parsed)
    if result_file is not None:
        blob = _read_json(result_file)
        if not isinstance(blob, dict):
            raise ValueError(f"result file {result_file} is not a JSON object")
        details.update(_pick_fields(blob, pick))
    details.update(_parse_kv(kv, as_int=False))
    details.update(_parse_kv(int_kv, as_int=True))
    if error_file is not None:
        details["error"] = _read_text_or_empty(error_file).strip()

    record = {"name": name, "status": status, "exit_code": code, "details": details}
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    json.loads(line)  # round-trip guard
    steps_file.parent.mkdir(parents=True, exist_ok=True)
    with steps_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return record


def _load_step_records(steps_file: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    text = _read_text_or_empty(steps_file)
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        record = json.loads(line)
        name = record.get("name")
        if name not in STEP_NAMES:
            raise ValueError(f"{steps_file}:{lineno}: unknown step name {name!r}")
        if name in records:
            raise ValueError(f"{steps_file}:{lineno}: duplicate step record for {name!r}")
        if record.get("status") not in VALID_STATUSES:
            raise ValueError(f"{steps_file}:{lineno}: invalid status {record.get('status')!r}")
        if not isinstance(record.get("details"), dict):
            raise ValueError(f"{steps_file}:{lineno}: details must be an object")
        records[name] = record
    return records


def aggregate_exit_code(steps: Sequence[Dict[str, Any]]) -> int:
    """``EXIT_FAILED`` if any step failed, otherwise ``EXIT_OK``.

    ``skipped`` and ``not_run`` never make the demo exit non-zero on
    their own: a fresh clone without wakir-verify must still exit 0.
    (``not_run`` only ever appears together with a ``failed`` step.)
    The CI gate layers a stricter ``external_verify == ok`` rule on
    top of this via the report validator.
    """
    return EXIT_FAILED if any(s["status"] == "failed" for s in steps) else EXIT_OK


def do_assemble_report(
    *,
    steps_file: Path,
    out: Path,
    runtime_commit: str,
    protocol_commit: str,
    verify_commit: str,
    workdir: str,
    hour: str,
    short_circuited_after: Optional[str] = None,
) -> Dict[str, Any]:
    """Fold the steps file into the final ``wakir-demo-proof/v1`` report.

    Every one of the five step names is present exactly once, in
    canonical order. Steps that never ran get ``status: "not_run"``
    with a reason naming the step that failed first.
    """
    records = _load_step_records(steps_file)
    failed_first = short_circuited_after or next(
        (n for n in STEP_NAMES if records.get(n, {}).get("status") == "failed"),
        None,
    )

    steps: List[Dict[str, Any]] = []
    for name in STEP_NAMES:
        if name in records:
            steps.append(records[name])
            continue
        reason = (
            f"short-circuited after {failed_first} failed"
            if failed_first
            else "step produced no record"
        )
        steps.append(
            {
                "name": name,
                "status": "not_run",
                "exit_code": EXIT_NOT_RUN,
                "details": {"reason": reason},
            }
        )

    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "hour": hour,
        "workdir": workdir,
        "commits": {
            "wakir_runtime": runtime_commit,
            "wakir_protocol": protocol_commit,
            "wakir_verify": verify_commit,
        },
        "steps": steps,
        "exit_code": aggregate_exit_code(steps),
    }
    _write_json(out, report)
    return report


def do_json_get(*, path: Path, key: str) -> str:
    """Return the scalar at dotted ``key`` in the JSON file as text.

    Booleans print as ``true``/``false`` and ``null`` as ``null`` so
    bash comparisons read naturally. Non-scalars are printed as
    compact JSON.
    """
    blob = _read_json(path)
    current: Any = blob
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.lstrip("-").isdigit():
            current = current[int(part)]
        else:
            raise KeyError(f"{key!r} not found in {path}")
    if isinstance(current, bool):
        return "true" if current else "false"
    if current is None:
        return "null"
    if isinstance(current, (str, int, float)):
        return str(current)
    return json.dumps(current, sort_keys=True, separators=(",", ":"))


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

    p4 = sub.add_parser("verify-proof", help="Step 4: build + verify inclusion proof.")
    p4.add_argument("--manifest", required=True, type=Path)
    p4.add_argument("--event", required=True, type=Path)
    p4.add_argument("--out", required=True, type=Path)

    p5 = sub.add_parser(
        "external-verify",
        help="Step 5: re-verify through the wakir-verify library.",
    )
    p5.add_argument("--manifest", required=True, type=Path)
    p5.add_argument("--proof", required=True, type=Path)
    p5.add_argument("--out", required=True, type=Path)
    p5.add_argument(
        "--simulate-missing",
        action="store_true",
        help="Test hook: behave as if wakir_verify were not installed.",
    )

    pe = sub.add_parser("emit-step", help="Append one step record.")
    pe.add_argument("--steps-file", required=True, type=Path)
    pe.add_argument("--name", required=True)
    pe.add_argument("--status", required=True)
    pe.add_argument("--code", required=True, type=int)
    pe.add_argument("--details-json", default=None)
    pe.add_argument("--result-file", default=None, type=Path)
    pe.add_argument("--pick", default=None, help="comma list of key[:alias]")
    pe.add_argument("--kv", action="append", default=[], help="key=value (string)")
    pe.add_argument("--int", dest="int_kv", action="append", default=[], help="key=value (int)")
    pe.add_argument("--error-file", default=None, type=Path)

    pa = sub.add_parser("assemble-report", help="Fold step records into the report.")
    pa.add_argument("--steps-file", required=True, type=Path)
    pa.add_argument("--out", required=True, type=Path)
    pa.add_argument("--runtime-commit", required=True)
    pa.add_argument("--protocol-commit", required=True)
    pa.add_argument("--verify-commit", required=True)
    pa.add_argument("--workdir", required=True)
    pa.add_argument("--hour", required=True)
    pa.add_argument("--short-circuited-after", default=None)

    pg = sub.add_parser("json-get", help="Print one field from a JSON file.")
    pg.add_argument("path", type=Path)
    pg.add_argument("key")

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "build-event":
        do_build_event(
            hour=args.hour,
            out=args.out,
            hash_out=args.hash_out,
            event_id=args.event_id,
            capability_hash=args.capability_hash,
        )
        return EXIT_OK
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
        return EXIT_OK if result["status"] == "ok" else EXIT_FAILED
    if args.cmd == "build-manifest":
        do_build_manifest(
            spool_root=args.spool_root,
            hour=args.hour,
            aggregator_input=args.aggregator_input,
            manifest_out=args.manifest_out,
            persona_id=args.persona,
        )
        return EXIT_OK
    if args.cmd == "verify-proof":
        result = do_verify_proof(
            manifest=args.manifest,
            event=args.event,
            out=args.out,
        )
        return EXIT_OK if result["verified"] else EXIT_FAILED
    if args.cmd == "external-verify":
        result = do_external_verify(
            manifest=args.manifest,
            proof=args.proof,
            out=args.out,
            simulate_missing=args.simulate_missing,
        )
        return int(result["exit_code"])
    if args.cmd == "emit-step":
        do_emit_step(
            steps_file=args.steps_file,
            name=args.name,
            status=args.status,
            code=args.code,
            details_json=args.details_json,
            result_file=args.result_file,
            pick=args.pick,
            kv=args.kv,
            int_kv=args.int_kv,
            error_file=args.error_file,
        )
        return EXIT_OK
    if args.cmd == "assemble-report":
        do_assemble_report(
            steps_file=args.steps_file,
            out=args.out,
            runtime_commit=args.runtime_commit,
            protocol_commit=args.protocol_commit,
            verify_commit=args.verify_commit,
            workdir=args.workdir,
            hour=args.hour,
            short_circuited_after=args.short_circuited_after,
        )
        return EXIT_OK
    if args.cmd == "json-get":
        sys.stdout.write(do_json_get(path=args.path, key=args.key))
        return EXIT_OK
    raise AssertionError(f"unhandled sub-command {args.cmd!r}")  # pragma: no cover


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Any exception is a substance failure (exit 10).

    The message goes to stderr so the bash driver can capture it into
    the step record; the traceback is suppressed on purpose because
    the report, not a stack dump, is the operator-facing surface.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except Exception as exc:  # noqa: BLE001 — every failure becomes a step failure
        sys.stderr.write(f"{args.cmd}: {type(exc).__name__}: {exc}\n")
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CAPABILITY_HASH",
    "DEFAULT_EVENT_ID",
    "DEFAULT_PERSONA",
    "EXIT_FAILED",
    "EXIT_NOT_RUN",
    "EXIT_OK",
    "EXIT_SKIPPED",
    "PROOF_SCHEMA",
    "REPORT_SCHEMA",
    "STEP_NAMES",
    "aggregate_exit_code",
    "build_parser",
    "do_assemble_report",
    "do_build_event",
    "do_build_manifest",
    "do_emit_step",
    "do_external_verify",
    "do_json_get",
    "do_local_root_check",
    "do_run_bridge",
    "do_verify_proof",
    "main",
]
