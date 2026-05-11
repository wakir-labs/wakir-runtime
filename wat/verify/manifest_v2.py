# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Standalone verifier stub for WAT hour-manifest v2 envelopes.

The event-centric verifier in :mod:`wat.verify.cli` answers "did
event X land in a Bitcoin-anchored hour?". This module answers a
sister question that external implementers actually ask first when
they get handed a manifest file: "is this manifest internally
consistent with itself, and does it match the v2 schema contract?"

In Sprint-2 Tag-1 the trigger code-touchpoint in
``wat/aggregator.py`` does not yet exist. The pin tests
(``tests/wat/test_manifest_v2_schema_smoke.py``) cover the schema
contract at structural level; this stub adds the **cross-module
integrity** check that those tests cannot express because they
operate on opaque hex placeholders.

What this module checks
-----------------------

1. **Schema validation** against
   ``wirelang/schemas/wat-manifest-v2.json``. Reuses the existing
   Draft-2020-12 validator. Failures here are reported with the JSON
   pointer of the offending field so external authors can pinpoint
   the schema delta to fix.
2. **Cross-module integrity**:

   - ``len(events) == event_count == len(leaves)``.
   - ``leaves[i]`` (recomputed from each event's B1 four-tuple, when
     the event carries the four fields; otherwise compared verbatim
     against the recorded hex) feed a Merkle tree whose root matches
     ``merkle_root``.
   - ``tree_levels`` is the same tree the verifier rebuilds — leaves
     at level 0, root at the last level, every level the result of
     duplicating-and-pairing the previous one.
   - For ``wat-manifest/2.0`` only:
     - every key in ``multi_cap_events`` matches an ``event_id`` in
       ``events``,
     - ``caprefs_root`` re-derives correctly from ``caprefs_full``
       under the canonical-Merkle convention (provisional ordered
       per OQ-1; see :ref:`OQ-1 strict-mode flag` below),
     - ``multi_cap_summary.events_with_multi_cap`` equals
       ``len(multi_cap_events)``,
     - ``multi_cap_summary.max_caprefs_in_any_event`` equals
       ``max(len(caprefs_full) for entry in multi_cap_events)``.

3. **Trigger discipline:** v1 manifests must not carry multi-cap
   sidecar keys; v2 manifests must carry both. The schema enforces
   this; the stub re-asserts it as a code-side double-check so an
   auditor can see the failure mode in a verifier log even without
   re-running the schema validator.

Provisional / OQ-1
------------------

Per ``docs/wat-manifest-v2-spec.md`` §9 OQ-1 (ratified
2026-05-07 by wirelang-engineering Cross-Review-Zone-2), the
canonical Merkle ordering for ``caprefs_root`` is **ordered
Merkle** (preserves producer / issuance intent). This stub
implements the ordered convention; strict-mode is the default
since Sprint-2 Tag-4:

- ``--strict-multi-cap-root`` (default **on** since Sprint-2
  Tag-4) — recompute ``caprefs_root`` and reject on mismatch
  with exit code 1 and reason ``multi_cap_root_mismatch``.
- ``--no-strict-multi-cap-root`` (lenient escape hatch for
  third-party verifiers that have not yet adopted the locked
  ordering) — emit a warning ``multi_cap_root not yet
  verified (OQ-1 pending)`` and continue.

This matches the spec §8 verifier-posture matrix: strict is the
reference-verifier default since Sprint-2 Tag-4; lenient remains
available as a forward-compat escape hatch for downstream
verifiers that have not yet adopted the locked ordering.

Exit codes
----------

Aligned with :mod:`wat.verify.cli` so operator tooling does not need
two semantic tables:

- ``0`` — manifest validates and is internally consistent.
- ``1`` — schema-validation failure, cross-integrity failure, or
  ``multi_cap_root_mismatch`` under strict mode.

Real-manifest mode (Sprint-2 Tag-5)
-----------------------------------

The v2-spec verifier above operates on manifests that conform to
``wirelang/schemas/wat-manifest-v2.json``. The real aggregator
(``wat/aggregator.py`` v1 branch) emits a sister shape today —
``wakir-wat-manifest/v1`` — with ``leaf_hash`` (vs ``leaf``),
``leaves`` as objects (vs hex strings), and an optional
``prev_hour_root``. Real manifests live next to ``root.bin`` and
``root.bin.ots`` (OpenTimestamps proof) under
``.runtime/wat-tv*-archive/<RUN>/<HOUR>/manifest.json``.

The :func:`verify_real_manifest_file` entry consumes that real
on-disk shape directly, performs field-validation and Merkle-rebuild
without going through the v2 JSON-Schema (which would reject the
v1 wire-form), and optionally verifies the OTS-anchor side-files:

- ``root.bin`` exists, is exactly 32 bytes, and its raw content
  hex-encodes to the manifest's ``merkle_root``.
- ``root.bin.ots`` exists and starts with the OpenTimestamps
  ``\\x00OpenTimestamps\\x00\\x00Proof\\x00`` magic header (we do
  not re-verify the timestamp itself — that is ``ots verify``
  territory and would require Bitcoin RPC access).

Multi-cap awareness in real-manifest mode is conditional: today's
v1 aggregator does not emit ``multi_cap_events`` or
``multi_cap_summary``. When a real manifest does carry those keys
(future v2 producer-code), the same multi-cap consistency check
(strict default ON since Sprint-2 Tag-4) runs against them.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from wat.merkle.aggregator import (
    build_merkle_tree,
    compute_inner_hash,
    compute_leaf_hash,
)


# ---------------------------------------------------------------------------
# OTS anchor magic header
# ---------------------------------------------------------------------------

#: OpenTimestamps proof-file magic header. Bytes 0-15 of any valid
#: ``.ots`` file. We check the first 16 bytes (enough to disambiguate
#: from any other file format we care about) without depending on the
#: ``opentimestamps`` Python client — that dep is heavy and would make
#: this stub non-hermetic. Full verification (Bitcoin attestation
#: completion) is ``ots verify`` territory; this stub only asserts the
#: file is well-formed at the magic-header level.
_OTS_MAGIC_HEADER = b"\x00OpenTimestamps\x00"


# ---------------------------------------------------------------------------
# Schema location
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Default location of the v2 schema relative to the repo. Tests and
#: callers can override via ``schema_path`` parameter when the
#: repo layout differs.
DEFAULT_SCHEMA_PATH = (
    _REPO_ROOT / "wirelang" / "schemas" / "wat-manifest-v2.json"
)

#: Default location of the v1 (real-manifest) schema relative to the
#: repo. Used by ``verify_real_manifest_file`` when called with
#: ``use_schema_file=True`` (off-default since Sprint-2 Tag-6) and by
#: the CLI ``--use-schema-file`` flag. The v1 schema is the
#: source-of-truth pin for the on-disk wakir-wat-manifest/v1 wire-form
#: emitted by the aggregator; the in-code field-by-field validator
#: remains the redundant hermetic-no-deps path so that a missing
#: ``jsonschema`` install does not block manifest verification.
DEFAULT_REAL_SCHEMA_PATH = (
    _REPO_ROOT / "wirelang" / "schemas" / "wakir-wat-manifest-v1.json"
)

#: Wat-manifest version strings recognised by this stub. A future
#: ``wat-manifest/3.0`` would land here as a separate code path; until
#: then anything outside this set fails schema validation up-front.
_VERSION_V1 = "wat-manifest/1.0"
_VERSION_V2 = "wat-manifest/2.0"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ManifestV2Result:
    """Outcome of verifying a WAT v2-aware manifest file.

    Attributes
    ----------
    manifest_path:
        Path the verifier read from. Echoed back so log-aggregation
        tooling does not have to reconstruct it from the CLI invocation.
    version:
        Manifest version as observed in the file (``wat-manifest/1.0``
        or ``wat-manifest/2.0``). Empty string if the file failed to
        parse far enough to carry a version.
    schema_ok:
        True when JSON-Schema validation passed. False on schema
        failure; ``failure_reason`` carries the offending JSON pointer.
    integrity_ok:
        True when cross-module integrity (event-count / leaves /
        merkle_root rebuild / multi_cap consistency) holds. False on
        any mismatch; ``failure_reason`` carries a human-readable
        diagnostic.
    multi_cap_root_status:
        For v2 manifests: one of ``"verified"`` (strict mode +
        recompute matched), ``"deferred"`` (lenient mode, OQ-1
        pending), ``"mismatch"`` (strict mode + recompute did not
        match — also forces ``integrity_ok = False``). Empty string
        for v1 manifests.
    failure_reason:
        Diagnostic for the first failure encountered, empty on the
        all-OK path. Format: ``<phase>: <human message>`` where
        ``<phase>`` is ``schema``, ``integrity``, or
        ``multi_cap_root``.
    """

    manifest_path: str
    version: str
    schema_ok: bool
    integrity_ok: bool
    multi_cap_root_status: str = ""
    failure_reason: str = ""

    @property
    def ok(self) -> bool:
        """True when both schema and integrity checks passed."""
        return self.schema_ok and self.integrity_ok

    def as_dict(self) -> dict:
        """Return a JSON-serialisable dict representation.

        This is the **manifest-centric** verifier-result schema —
        single-file manifest validation outcome. It is intentionally
        *separate* from the event-centric ``wakir verify`` output
        (per-event-id audit-result, aggregated across an archive).
        Frontend consumers that render hour-aggregate / multi-receipt
        snapshots should aggregate on top of this rather than expect
        a 1:1 field map. Schema fields and meanings are pinned in
        ``docs/wat-manifest-v2-spec.md`` §10.

        Schema (stable for v0; additive-only changes promised):

        - ``schema_version`` — string literal ``"wakir-verify-manifest-v2/0"``
          so consumers can branch on a future ``/1`` without
          probe-by-field heuristics.
        - ``manifest_path`` — string, echo of the input path.
        - ``manifest_version`` — string, the ``version`` field as
          read from the manifest (e.g. ``"wat-manifest/2.0"``); empty
          string when parsing did not reach the version field.
        - ``ok`` — boolean, true iff schema and integrity both passed.
        - ``schema_ok`` — boolean, JSON-Schema validation outcome.
        - ``integrity_ok`` — boolean, cross-module integrity outcome.
        - ``multi_cap_root_status`` — string, one of
          ``"verified" | "deferred" | "mismatch" | ""`` (empty for v1).
        - ``failure_reason`` — string, ``"<phase>: <message>"`` on
          failure, empty on success.
        """
        return {
            "schema_version": "wakir-verify-manifest-v2/0",
            "manifest_path": self.manifest_path,
            "manifest_version": self.version,
            "ok": self.ok,
            "schema_ok": self.schema_ok,
            "integrity_ok": self.integrity_ok,
            "multi_cap_root_status": self.multi_cap_root_status,
            "failure_reason": self.failure_reason,
        }

    def as_audit_trail_entry(
        self,
        *,
        anchor_root_hex: str = "",
        hour_slot: str = "",
        event_count: Optional[int] = None,
    ) -> dict:
        """Return the audit-trail-browser export shape for this result.

        This is the **paired-update contract** between
        ``wat/verify/manifest_v2.py`` (this module) and the frontend
        ``AuditTrailEntry`` consumer (per
        ``infra/repos-skeleton/site/src/data/wakir-audit-trail-sample.ts``,
        published in Sprint-Frontend-1 Tag-3 outbox memo). The frontend
        provisional interface treats every entry as one of three
        ``kind`` values; a manifest-v2 verifier-result maps to
        ``"wat-tv-pin-pack"`` — the kind for "the runtime pinned a set
        of facts about an hour-aggregate".

        Encoding contract (additive-only across ``schema_version``
        ``wakir-verify-manifest-v2/0``):

        - ``kind`` — string literal ``"wat-tv-pin-pack"``. Pinned;
          a future v3 format would land as a separate kind, never
          re-purpose this one.
        - ``schema_version`` — string literal ``"wakir-verify-manifest-v2/0"``.
          Same string as :meth:`as_dict` so consumers can branch on a
          single field.
        - ``identity`` — short display string. ``manifest_path`` if
          ``hour_slot`` not provided; otherwise ``"wat-hour " + hour_slot``.
          NOT load-bearing for verification — only for rendering.
        - ``manifest_version`` — string, the ``version`` field of the
          underlying manifest (``"wat-manifest/2.0"`` etc.).
        - ``manifest_path`` — string, echo of input path.
        - ``hour_slot`` — string, the ``hour_slot`` from the manifest
          if known, else empty string. Caller passes it because
          ``ManifestV2Result`` does not carry the parsed manifest.
        - ``event_count`` — integer, number of events in the manifest,
          or ``-1`` if not provided. Caller passes it for the same
          reason as ``hour_slot``.
        - ``anchor_root_hex`` — string, the merkle_root of the hour
          (64 lowercase hex, NO ``"sha256:"`` prefix). Empty string if
          not provided. The frontend's display-convention is to
          re-prefix with ``"sha256:"`` at render-time when desired —
          we emit the raw hex here so the wire-format stays canonical
          (matches ``wat-manifest-v2.json`` schema's bare-hex pattern).
        - ``branches`` — list of one branch dict, the
          manifest-validity verdict:

          .. code-block:: text

              {
                "label": "manifest-validity",
                "verdict": "verified" | "rejected" | "pending",
                "detail": "<failure_reason or 'schema + integrity + multi_cap_root'>"
              }

          ``verdict`` is ``"verified"`` iff ``ok`` and not
          ``multi_cap_root_status == "deferred"``. ``"rejected"`` on
          any failure. ``"pending"`` is reserved for the
          deferred-multi-cap-root case (lenient + v2). The detail
          string is a human-readable diagnostic, never load-bearing.

        - ``ok`` — boolean, mirror of :meth:`as_dict` ``ok``. Provided
          redundantly so a renderer can short-circuit without parsing
          ``branches``.
        - ``failure_reason`` — string, mirror of :meth:`as_dict`
          ``failure_reason``. Empty on success.

        Determinism guarantees:

        - Key set is exactly the eleven keys above. No optional keys
          conditionally appear.
        - Field types are stable: every string is a Python ``str``,
          every list is a list, every int is an int. No ``None``
          values — missing data renders as empty string / -1 / empty
          list.
        - ``json.dumps(..., sort_keys=True, ensure_ascii=False)`` over
          the returned dict yields a canonical byte-string suitable
          for snapshot tests, content-hashing, and re-import.

        Schema-version evolution rule: a future revision that adds a
        field bumps the trailing kind-suffix once the field becomes
        load-bearing for downstream verification (e.g., a new
        ``caprefs_root_hex`` field would be additive and stay at
        ``/0``; renaming ``manifest_path`` to ``manifest_uri`` would
        bump to ``/1``).
        """
        if anchor_root_hex and not _is_lower_hex_64(anchor_root_hex):
            raise ValueError(
                "anchor_root_hex must be 64 lowercase-hex chars or empty; "
                f"got {anchor_root_hex!r}"
            )

        if self.ok and self.multi_cap_root_status == "deferred":
            verdict = "pending"
            detail = "schema + integrity ok; multi_cap_root deferred (OQ-1)"
        elif self.ok:
            verdict = "verified"
            detail = "schema + integrity + multi_cap_root"
        else:
            verdict = "rejected"
            detail = self.failure_reason or "verification failed"

        if hour_slot:
            identity = f"wat-hour {hour_slot}"
        else:
            identity = self.manifest_path

        return {
            "kind": "wat-tv-pin-pack",
            "schema_version": "wakir-verify-manifest-v2/0",
            "identity": identity,
            "manifest_version": self.version,
            "manifest_path": self.manifest_path,
            "hour_slot": hour_slot,
            "event_count": event_count if event_count is not None else -1,
            "anchor_root_hex": anchor_root_hex,
            "branches": [
                {
                    "label": "manifest-validity",
                    "verdict": verdict,
                    "detail": detail,
                }
            ],
            "ok": self.ok,
            "failure_reason": self.failure_reason,
        }


def _is_lower_hex_64(value: str) -> bool:
    """Return True iff ``value`` is exactly 64 lowercase-hex chars.

    Mirrors the ``^[0-9a-f]{64}$`` pattern enforced by
    ``wirelang/schemas/wat-manifest-v2.json`` for ``merkle_root``.
    Kept module-private — there is exactly one shape we accept for
    the audit-trail export contract, and it is the same shape the
    schema enforces on the wire.
    """
    if len(value) != 64:
        return False
    for ch in value:
        if ch not in "0123456789abcdef":
            return False
    return True


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _load_schema(schema_path: Path) -> dict:
    with schema_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate_schema(
    manifest: dict,
    schema_path: Path,
) -> Tuple[bool, str]:
    """Return ``(ok, failure_reason)`` for a schema-validation pass.

    Imports ``jsonschema`` lazily so callers that only need integrity
    checks (e.g. tests using their own builders) do not pay the import
    cost. ``jsonschema`` is already a runtime dep for the schema-smoke
    tests, so this is not a new dependency.
    """
    try:
        import jsonschema  # noqa: F401  (used below as Draft202012Validator)
        from jsonschema import Draft202012Validator
    except ImportError:
        return (
            False,
            "schema: jsonschema package not available; install jsonschema",
        )

    schema = _load_schema(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.path)
    if not errors:
        return (True, "")

    first = errors[0]
    pointer = "/" + "/".join(str(p) for p in first.absolute_path) if first.absolute_path else "/"
    return (False, f"schema: {pointer}: {first.message}")


def _validate_real_manifest_against_schema(
    manifest: dict,
    schema_path: Path,
) -> Tuple[bool, str]:
    """Return ``(ok, failure_reason)`` for a v1-schema validation pass.

    Sister of :func:`_validate_schema` for the v1 wire-form. Imports
    ``jsonschema`` lazily; when the package is missing this returns a
    descriptive failure rather than raising — callers (most notably
    ``verify_real_manifest_file`` with ``use_schema_file=True``) can
    surface the failure directly to the operator. The in-code
    field-by-field validator (:func:`_validate_real_manifest_fields`)
    remains the redundant hermetic-no-deps path so that a missing
    install does not block real-manifest verification.

    Failure-reason format mirrors :func:`_validate_schema`: a
    pointer-style ``"field /<pointer>: <jsonschema-message>"`` so the
    schema-file-based diagnostic is byte-comparable to the in-code
    validator's diagnostic for the same field.
    """
    try:
        import jsonschema  # noqa: F401  (used below as Draft202012Validator)
        from jsonschema import Draft202012Validator
    except ImportError:
        return (
            False,
            "schema: jsonschema package not available; install jsonschema",
        )

    schema = _load_schema(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.path)
    if not errors:
        return (True, "")

    first = errors[0]
    pointer = "/" + "/".join(str(p) for p in first.absolute_path) if first.absolute_path else ""
    if pointer:
        return (False, f"field {pointer}: {first.message}")
    return (False, f"schema: {first.message}")


# ---------------------------------------------------------------------------
# Cross-module integrity
# ---------------------------------------------------------------------------


def _hex_to_bytes(hex_str: str, *, label: str) -> bytes:
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError as exc:
        raise ValueError(f"{label} is not valid hex: {exc}") from exc
    if len(raw) != 32:
        raise ValueError(
            f"{label} is {len(raw)} bytes, expected 32"
        )
    return raw


def _check_event_count(manifest: dict) -> Optional[str]:
    """Verify ``event_count == len(events) == len(leaves)``."""
    declared = manifest["event_count"]
    n_events = len(manifest["events"])
    n_leaves = len(manifest["leaves"])
    if declared != n_events:
        return (
            f"event_count drift: manifest claims {declared} but "
            f"events[] has {n_events} entries"
        )
    if declared != n_leaves:
        return (
            f"event_count drift: manifest claims {declared} but "
            f"leaves[] has {n_leaves} entries"
        )
    return None


def _check_leaves_match_events(manifest: dict) -> Optional[str]:
    """Recompute leaves from event B1 fields when present.

    Events that do not carry the full B1 four-tuple (``event_id``,
    ``time``, ``payload_hash``, ``capability_token_hash``) are
    skipped — the schema permits a slim ``events[]`` shape with only
    ``event_id`` + ``leaf`` (see ``test_manifest_v2_schema_smoke``).
    For those entries we instead require an explicit ``leaf`` field
    matching ``leaves[i]``.
    """
    for idx, ev in enumerate(manifest["events"]):
        recorded_leaf_hex = manifest["leaves"][idx]
        b1_fields = ("event_id", "time", "payload_hash", "capability_token_hash")
        if all(k in ev for k in b1_fields):
            recomputed = compute_leaf_hash(
                event_id=ev["event_id"],
                time=ev["time"],
                payload_hash=ev["payload_hash"],
                capability_token_hash=ev["capability_token_hash"],
            )
            if recomputed.hex() != recorded_leaf_hex:
                return (
                    f"leaf drift at index {idx} (event_id={ev.get('event_id')!r}): "
                    f"events[] B1 fields hash to {recomputed.hex()} but "
                    f"leaves[{idx}] is {recorded_leaf_hex}"
                )
            continue
        leaf_hex_in_event = ev.get("leaf")
        if leaf_hex_in_event is not None and leaf_hex_in_event != recorded_leaf_hex:
            return (
                f"leaf drift at index {idx}: events[{idx}].leaf is "
                f"{leaf_hex_in_event} but leaves[{idx}] is {recorded_leaf_hex}"
            )
    return None


def _check_merkle_root(manifest: dict) -> Optional[str]:
    """Rebuild the Merkle tree from leaves and compare to root + levels.

    The v2 schema's ``merkle_root`` pattern (``^[0-9a-f]{64}$``)
    forbids the ``null`` empty-hour sentinel that the v1 aggregator
    emits today, which means a legitimate v1-empty-hour manifest
    fails schema-validation up-front and never reaches this check.
    The smoke tests do construct an empty-events manifest with
    placeholder hex ``merkle_root`` though, and we treat that as an
    integrity failure here (no leaves, no tree to rebuild) so the
    stub does not silently green-light an unverifiable shape.
    """
    leaves_hex: List[str] = list(manifest["leaves"])
    declared_root = manifest["merkle_root"]
    declared_levels: List[List[str]] = list(manifest["tree_levels"])

    if not leaves_hex:
        return (
            "empty-hour-with-hex-root not supported by v2 verifier-stub: "
            "leaves[] is empty but merkle_root is "
            f"{declared_root}; the v1 aggregator emits null roots for "
            "quiet hours which fail schema-validation up-front, so a "
            "non-null root with empty leaves indicates a producer bug."
        )

    leaves_bytes: List[bytes] = []
    for idx, leaf_hex in enumerate(leaves_hex):
        try:
            leaves_bytes.append(_hex_to_bytes(leaf_hex, label=f"leaves[{idx}]"))
        except ValueError as exc:
            return f"leaves shape: {exc}"

    rebuilt_root, rebuilt_levels = build_merkle_tree(leaves_bytes)
    if rebuilt_root.hex() != declared_root:
        return (
            f"merkle_root mismatch: rebuilt {rebuilt_root.hex()} from "
            f"leaves[] but manifest claims {declared_root}"
        )

    rebuilt_levels_hex = [[node.hex() for node in level] for level in rebuilt_levels]
    if rebuilt_levels_hex != declared_levels:
        return (
            "tree_levels mismatch: rebuilt tree shape differs from manifest "
            "tree_levels (length / node-hash mismatch). Aggregator and "
            "verifier disagree on duplication-and-pair semantics."
        )

    return None


def _caprefs_canonical_root_ordered(caprefs_full: Sequence[str]) -> bytes:
    """Compute the canonical (ordered, OQ-1 proposal) caprefs Merkle.

    ``caprefs_full`` items are ``"sha256:<64hex>"``. We strip the
    prefix, decode, and feed those 32-byte digests as Merkle leaves.
    Ordering is **preserved verbatim** — that is the OQ-1 proposal.
    Producers and verifiers must agree on the strip-and-decode rule;
    this is the only place that rule lives until Zone-2 sign-off
    bumps the spec.

    Note: this is *provisional* per docs/wat-manifest-v2-spec.md §9.
    External implementers should not duplicate this function in their
    own verifiers; they should consume it through the schema-pinned
    reference once OQ-1 locks.
    """
    leaves: List[bytes] = []
    for idx, ref in enumerate(caprefs_full):
        if not ref.startswith("sha256:"):
            raise ValueError(
                f"caprefs_full[{idx}] missing 'sha256:' prefix: {ref!r}"
            )
        hex_part = ref[len("sha256:"):]
        leaves.append(_hex_to_bytes(hex_part, label=f"caprefs_full[{idx}]"))
    if len(leaves) < 2:
        # Trigger condition guarantees >= 2; defensive, not load-bearing.
        raise ValueError(
            "caprefs_full must have minItems: 2 by trigger condition; "
            f"got {len(leaves)}"
        )
    root, _levels = build_merkle_tree(leaves)
    return root


def _check_multi_cap_consistency(
    manifest: dict,
    *,
    strict_multi_cap_root: bool,
) -> Tuple[Optional[str], str]:
    """Cross-check the v2 multi-cap sidecar against ``events`` + summary.

    Returns ``(failure_reason, multi_cap_root_status)``. Failure reason
    is None on the OK path. Status is one of ``verified`` (strict +
    recompute matched), ``deferred`` (lenient + warning),
    ``mismatch`` (strict + recompute failed; failure_reason is also
    populated).
    """
    multi_cap_events = manifest.get("multi_cap_events", {})
    multi_cap_summary = manifest.get("multi_cap_summary", {})

    # Every multi_cap_events key must correspond to an event_id in events[].
    event_ids_in_events = {
        ev.get("event_id") for ev in manifest["events"] if "event_id" in ev
    }
    for key in multi_cap_events:
        if key not in event_ids_in_events:
            return (
                (
                    f"multi_cap_events references event_id {key!r} which is "
                    "not present in events[]"
                ),
                "",
            )

    # Summary fields must agree with sidecar.
    declared_count = multi_cap_summary.get("events_with_multi_cap")
    actual_count = len(multi_cap_events)
    if declared_count != actual_count:
        return (
            (
                f"multi_cap_summary.events_with_multi_cap drift: claims "
                f"{declared_count} but multi_cap_events has {actual_count} entries"
            ),
            "",
        )

    if multi_cap_events:
        actual_max = max(
            len(entry["caprefs_full"]) for entry in multi_cap_events.values()
        )
    else:
        actual_max = 0
    declared_max = multi_cap_summary.get("max_caprefs_in_any_event")
    if declared_max != actual_max:
        return (
            (
                f"multi_cap_summary.max_caprefs_in_any_event drift: claims "
                f"{declared_max} but multi_cap_events max is {actual_max}"
            ),
            "",
        )

    # Multi-cap-root recompute (provisional under OQ-1).
    if strict_multi_cap_root:
        for ev_id, entry in multi_cap_events.items():
            try:
                recomputed = _caprefs_canonical_root_ordered(
                    entry["caprefs_full"]
                )
            except ValueError as exc:
                return (
                    f"multi_cap_root: caprefs_full shape error for {ev_id!r}: {exc}",
                    "mismatch",
                )
            if recomputed.hex() != entry["caprefs_root"]:
                return (
                    (
                        f"multi_cap_root: recomputed root {recomputed.hex()} for "
                        f"event {ev_id!r} does not match claimed "
                        f"{entry['caprefs_root']}"
                    ),
                    "mismatch",
                )
        return (None, "verified")

    return (None, "deferred")


def _check_trigger_discipline(manifest: dict) -> Optional[str]:
    """Code-side double-check of the schema-side trigger condition."""
    version = manifest.get("version")
    has_multi_cap = (
        "multi_cap_events" in manifest or "multi_cap_summary" in manifest
    )
    if version == _VERSION_V1 and has_multi_cap:
        return (
            "trigger discipline: v1 manifest carries multi-cap sidecar keys "
            "(producer bug; schema would also reject this)"
        )
    if version == _VERSION_V2 and not (
        "multi_cap_events" in manifest and "multi_cap_summary" in manifest
    ):
        return (
            "trigger discipline: v2 manifest is missing multi_cap_events or "
            "multi_cap_summary (producer bug; schema would also reject)"
        )
    return None


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def verify_manifest_v2_file(
    manifest_path: str | Path,
    *,
    schema_path: str | Path | None = None,
    strict_multi_cap_root: bool = True,
) -> ManifestV2Result:
    """Verify a single WAT manifest file end-to-end.

    Parameters
    ----------
    manifest_path:
        Filesystem path to a ``manifest.json`` produced by an
        aggregator. The file is opened, JSON-parsed, schema-validated,
        and integrity-checked against itself.
    schema_path:
        Optional override for the schema location. Defaults to
        ``wirelang/schemas/wat-manifest-v2.json`` next to the
        repo-root.
    strict_multi_cap_root:
        When True (default since Sprint-2 Tag-4, OQ-1 ratified
        ordered-Merkle 2026-05-07), recompute ``caprefs_root`` for
        every entry in ``multi_cap_events`` and reject on mismatch.
        When False (lenient escape hatch for third-party verifiers
        that have not yet adopted the locked ordering), skip the
        recompute and report ``multi_cap_root_status = "deferred"``
        so external callers can wire their own posture.
    """
    path = Path(manifest_path)
    if not path.exists():
        return ManifestV2Result(
            manifest_path=str(path),
            version="",
            schema_ok=False,
            integrity_ok=False,
            failure_reason=f"schema: manifest file not found: {path}",
        )

    try:
        with path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except json.JSONDecodeError as exc:
        return ManifestV2Result(
            manifest_path=str(path),
            version="",
            schema_ok=False,
            integrity_ok=False,
            failure_reason=f"schema: malformed JSON: {exc}",
        )

    schema_p = Path(schema_path) if schema_path is not None else DEFAULT_SCHEMA_PATH
    schema_ok, schema_msg = _validate_schema(manifest, schema_p)
    version = manifest.get("version", "") if isinstance(manifest, dict) else ""

    if not schema_ok:
        return ManifestV2Result(
            manifest_path=str(path),
            version=version,
            schema_ok=False,
            integrity_ok=False,
            failure_reason=schema_msg,
        )

    # Schema passed; now cross-module integrity.
    trigger_msg = _check_trigger_discipline(manifest)
    if trigger_msg:
        return ManifestV2Result(
            manifest_path=str(path),
            version=version,
            schema_ok=True,
            integrity_ok=False,
            failure_reason=f"integrity: {trigger_msg}",
        )

    count_msg = _check_event_count(manifest)
    if count_msg:
        return ManifestV2Result(
            manifest_path=str(path),
            version=version,
            schema_ok=True,
            integrity_ok=False,
            failure_reason=f"integrity: {count_msg}",
        )

    leaves_msg = _check_leaves_match_events(manifest)
    if leaves_msg:
        return ManifestV2Result(
            manifest_path=str(path),
            version=version,
            schema_ok=True,
            integrity_ok=False,
            failure_reason=f"integrity: {leaves_msg}",
        )

    root_msg = _check_merkle_root(manifest)
    if root_msg:
        return ManifestV2Result(
            manifest_path=str(path),
            version=version,
            schema_ok=True,
            integrity_ok=False,
            failure_reason=f"integrity: {root_msg}",
        )

    multi_cap_status = ""
    if version == _VERSION_V2:
        multi_msg, multi_cap_status = _check_multi_cap_consistency(
            manifest,
            strict_multi_cap_root=strict_multi_cap_root,
        )
        if multi_msg:
            phase = (
                "multi_cap_root"
                if multi_cap_status == "mismatch"
                else "integrity"
            )
            return ManifestV2Result(
                manifest_path=str(path),
                version=version,
                schema_ok=True,
                integrity_ok=False,
                multi_cap_root_status=multi_cap_status,
                failure_reason=f"{phase}: {multi_msg}",
            )

    return ManifestV2Result(
        manifest_path=str(path),
        version=version,
        schema_ok=True,
        integrity_ok=True,
        multi_cap_root_status=multi_cap_status,
        failure_reason="",
    )


# ---------------------------------------------------------------------------
# Real-manifest mode (Sprint-2 Tag-5)
# ---------------------------------------------------------------------------


#: Manifest version strings recognised in real-manifest mode. The v1
#: real aggregator emits ``wakir-wat-manifest/v1``; future v2 producer-
#: code (``wat/aggregator.py`` v2 branch) will emit
#: ``wakir-wat-manifest/v2`` once it lands. Anything outside this set
#: is rejected up-front with an explicit field-validation diagnostic.
_REAL_VERSION_V1 = "wakir-wat-manifest/v1"
_REAL_VERSION_V2 = "wakir-wat-manifest/v2"
_REAL_VERSIONS = frozenset({_REAL_VERSION_V1, _REAL_VERSION_V2})


#: Mandatory top-level fields on every real-manifest. Field-by-field
#: validation in real-manifest mode rejects on missing fields with a
#: pointer-style diagnostic ``"/<field>"`` matching the JSON-Schema
#: failure idiom even though we are not running the schema validator.
_REAL_MANDATORY_FIELDS = (
    "version",
    "hour_slot",
    "merkle_root",
    "event_count",
    "events",
    "leaves",
    "tree_levels",
    "build_time",
)


def _validate_real_manifest_fields(manifest: dict) -> Optional[str]:
    """Return a failure reason or None for real-manifest field shape.

    Field-by-field validation independent of the v2 JSON-Schema. Real
    manifests use ``leaf_hash`` (not ``leaf``) and carry full leaves
    objects, so the v2 schema would reject them; we do the structural
    check here with explicit diagnostics.
    """
    for field in _REAL_MANDATORY_FIELDS:
        if field not in manifest:
            return f"field /{field}: required field missing"

    version = manifest["version"]
    if version not in _REAL_VERSIONS:
        return (
            f"field /version: unrecognised real-manifest version {version!r}; "
            f"expected one of {sorted(_REAL_VERSIONS)}"
        )

    if not isinstance(manifest["merkle_root"], str) or not _is_lower_hex_64(
        manifest["merkle_root"]
    ):
        return (
            "field /merkle_root: must be exactly 64 lowercase-hex chars; "
            f"got {manifest['merkle_root']!r}"
        )

    if not isinstance(manifest["event_count"], int) or manifest["event_count"] < 0:
        return (
            "field /event_count: must be a non-negative integer; "
            f"got {manifest['event_count']!r}"
        )

    if not isinstance(manifest["events"], list):
        return "field /events: must be a JSON array"
    if not isinstance(manifest["leaves"], list):
        return "field /leaves: must be a JSON array"
    if not isinstance(manifest["tree_levels"], list):
        return "field /tree_levels: must be a JSON array"

    if not isinstance(manifest["hour_slot"], str) or not manifest["hour_slot"]:
        return "field /hour_slot: must be a non-empty string"

    # Optional anchor_height — when present, must be a positive int.
    if "anchor_height" in manifest:
        ah = manifest["anchor_height"]
        if not isinstance(ah, int) or ah <= 0:
            return (
                "field /anchor_height: must be a positive integer when present; "
                f"got {ah!r}"
            )

    return None


def _normalise_real_leaves(manifest: dict) -> Tuple[Optional[str], List[str]]:
    """Extract the per-event leaf hashes from a real-manifest.

    Real-manifest ``leaves[i]`` is one of:

    - a hex string (v2-spec shape, also accepted),
    - a dict with ``leaf_hash`` field (v1-aggregator shape).

    Returns ``(failure_reason or None, normalised_hex_leaves)``.
    """
    out: List[str] = []
    for idx, entry in enumerate(manifest["leaves"]):
        if isinstance(entry, str):
            if not _is_lower_hex_64(entry):
                return (
                    (
                        f"field /leaves/{idx}: must be 64 lowercase-hex chars "
                        f"or {{leaf_hash: ...}} object; got {entry!r}"
                    ),
                    [],
                )
            out.append(entry)
        elif isinstance(entry, dict):
            leaf_hex = entry.get("leaf_hash")
            if not isinstance(leaf_hex, str) or not _is_lower_hex_64(leaf_hex):
                return (
                    (
                        f"field /leaves/{idx}/leaf_hash: must be 64 "
                        f"lowercase-hex chars; got {leaf_hex!r}"
                    ),
                    [],
                )
            out.append(leaf_hex)
        else:
            return (
                (
                    f"field /leaves/{idx}: must be a hex string or "
                    f"{{leaf_hash: ...}} object; got {type(entry).__name__}"
                ),
                [],
            )
    return (None, out)


def _check_real_event_leaves(
    manifest: dict, normalised_leaves: Sequence[str]
) -> Optional[str]:
    """Cross-check events[].leaf_hash / leaf against normalised leaves.

    Real v1 events carry ``leaf_hash``; v2-shape events carry ``leaf``;
    we accept either. When both fields are present they must agree
    with the corresponding entry in ``leaves[]``.
    """
    declared_count = manifest["event_count"]
    n_events = len(manifest["events"])
    n_leaves = len(normalised_leaves)
    if declared_count != n_events:
        return (
            f"event_count drift: manifest claims {declared_count} but "
            f"events[] has {n_events} entries"
        )
    if declared_count != n_leaves:
        return (
            f"event_count drift: manifest claims {declared_count} but "
            f"leaves[] has {n_leaves} entries"
        )

    for idx, ev in enumerate(manifest["events"]):
        leaf_in_event = ev.get("leaf_hash") or ev.get("leaf")
        if leaf_in_event is None:
            # Slim event without leaf — recompute from B1 fields if present.
            b1 = ("event_id", "time", "payload_hash", "capability_token_hash")
            if all(k in ev for k in b1):
                recomputed = compute_leaf_hash(
                    event_id=ev["event_id"],
                    time=ev["time"],
                    payload_hash=ev["payload_hash"],
                    capability_token_hash=ev["capability_token_hash"],
                )
                if recomputed.hex() != normalised_leaves[idx]:
                    return (
                        f"leaf drift at index {idx} (event_id={ev.get('event_id')!r}): "
                        f"events[] B1 fields hash to {recomputed.hex()} but "
                        f"leaves[{idx}] is {normalised_leaves[idx]}"
                    )
            continue
        if leaf_in_event != normalised_leaves[idx]:
            return (
                f"leaf drift at index {idx}: events[{idx}].leaf_hash is "
                f"{leaf_in_event} but leaves[{idx}] is {normalised_leaves[idx]}"
            )
    return None


def _check_real_merkle_root(
    manifest: dict, normalised_leaves: Sequence[str]
) -> Optional[str]:
    """Rebuild the Merkle tree from real-manifest leaves and verify root."""
    declared_root = manifest["merkle_root"]
    if not normalised_leaves:
        return (
            "empty-hour real-manifest: leaves[] is empty but merkle_root is "
            f"{declared_root}; real-aggregator should not emit a non-null "
            "root for an empty hour."
        )

    leaves_bytes: List[bytes] = []
    for idx, leaf_hex in enumerate(normalised_leaves):
        try:
            leaves_bytes.append(_hex_to_bytes(leaf_hex, label=f"leaves[{idx}]"))
        except ValueError as exc:
            return f"leaves shape: {exc}"

    rebuilt_root, rebuilt_levels = build_merkle_tree(leaves_bytes)
    if rebuilt_root.hex() != declared_root:
        return (
            f"merkle_root mismatch: rebuilt {rebuilt_root.hex()} from "
            f"leaves[] but manifest claims {declared_root}"
        )

    declared_levels = manifest["tree_levels"]
    rebuilt_levels_hex = [[node.hex() for node in level] for level in rebuilt_levels]
    if rebuilt_levels_hex != declared_levels:
        return (
            "tree_levels mismatch: rebuilt tree shape differs from manifest "
            "tree_levels (length / node-hash mismatch)."
        )
    return None


@dataclasses.dataclass(frozen=True)
class OtsAnchorCheck:
    """Outcome of the OTS-pin-anchor side-file verification.

    Attributes
    ----------
    checked:
        True iff the caller asked for the OTS-anchor check (i.e.
        :func:`verify_real_manifest_file` was called with
        ``check_ots_anchor=True``). False means the fields below are
        not load-bearing.
    root_bin_present:
        True iff ``root.bin`` exists next to the manifest.
    root_bin_matches_manifest:
        True iff ``root.bin`` is exactly 32 bytes and its hex matches
        ``manifest.merkle_root``.
    ots_present:
        True iff ``root.bin.ots`` exists next to the manifest.
    ots_magic_ok:
        True iff ``root.bin.ots`` starts with the OpenTimestamps magic
        header. False on missing file or magic-byte mismatch.
    full_verify_attempted:
        True iff the caller asked for the off-default
        ``ots verify``-Voll-Integration (Sprint-3 Tag-4) by passing
        ``ots_full_verify=True`` (or via env / CLI flag — see
        :func:`_full_verify_enabled` below). False means the
        ``full_verify_*`` fields are not load-bearing and the OTS
        check stops at the magic-header level (the pin-anchor
        contract).
    full_verify_ok:
        When ``full_verify_attempted`` is True: True iff
        :func:`wat.anchor.ots_anchor.verify_receipt` returned True
        for the receipt sitting next to the manifest (with the merkle
        root as the original-file payload). False on any verifier-
        side rejection. When ``full_verify_attempted`` is False this
        field is False but does not gate :attr:`ok`.
    full_verify_skipped_reason:
        Diagnostic when full-verify was requested but skipped at
        runtime (e.g. ``ots`` CLI missing, receipt not finalised yet,
        Esplora HTTP fallback unreachable). Empty when full-verify
        was not requested or completed successfully.
    failure_reason:
        Diagnostic on first failure; empty when all sub-checks passed
        or when ``checked`` is False.
    """

    checked: bool = False
    root_bin_present: bool = False
    root_bin_matches_manifest: bool = False
    ots_present: bool = False
    ots_magic_ok: bool = False
    full_verify_attempted: bool = False
    full_verify_ok: bool = False
    full_verify_skipped_reason: str = ""
    failure_reason: str = ""

    @property
    def ok(self) -> bool:
        if not self.checked:
            return True
        magic_ok = (
            self.root_bin_present
            and self.root_bin_matches_manifest
            and self.ots_present
            and self.ots_magic_ok
        )
        if not magic_ok:
            return False
        # Full-verify is off-default; only gates ``ok`` when it was
        # actually attempted AND reached a definitive verdict.
        # Skipped-with-reason (e.g. ots CLI missing, receipt still
        # pending, Esplora unreachable) is treated as a soft outcome
        # at the magic-header level — ``full_verify_skipped_reason``
        # surfaces the detail without blocking the manifest pipeline.
        if self.full_verify_attempted and not self.full_verify_skipped_reason:
            return self.full_verify_ok
        return True


#: Environment variable that flips the off-default
#: ``ots verify``-Voll-Integration on without changing call sites.
#: When set to a truthy value (``1``, ``true``, ``yes``, ``on``),
#: :func:`verify_real_manifest_file` runs the full verifier even
#: without an explicit ``ots_full_verify=True`` argument. The CLI
#: ``--ots-full-verify`` flag is the explicit-and-preferred path;
#: the env-flag exists for cron-style invocations that cannot
#: easily inject CLI flags. Sprint-3 Tag-4.
_OTS_FULL_VERIFY_ENV_VAR = "WAKIR_OTS_FULL_VERIFY"


def _full_verify_env_enabled() -> bool:
    """Return True iff :data:`_OTS_FULL_VERIFY_ENV_VAR` is truthy."""
    import os  # local — keeps the module-level surface clean.

    raw = os.environ.get(_OTS_FULL_VERIFY_ENV_VAR, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _run_ots_full_verify(
    manifest_path: Path, merkle_root_bytes: bytes
) -> tuple[bool, str]:
    """Invoke :func:`wat.anchor.ots_anchor.verify_receipt`.

    Returns ``(ok, skipped_reason)``:

    - ``ok=True, skipped_reason=""`` — receipt finalised on Bitcoin
      (or cross-validated via Esplora HTTP) and attests to
      ``merkle_root_bytes``.
    - ``ok=False, skipped_reason=""`` — verifier rejected the
      receipt (mismatch, tampered, fake).
    - ``ok=False, skipped_reason=<msg>`` — verifier could not
      conclude either way (``ots`` CLI missing, receipt still
      pending and Esplora HTTP unreachable). Caller treats this as
      a soft outcome — does NOT gate ``ok`` because the magic-
      header pin still passed.

    The receipt path is hard-coded as ``root.bin.ots`` next to the
    manifest, matching the aggregator-side persistence convention
    enforced by :func:`_check_ots_anchor_side_files`. The 90s
    subprocess timeout in :mod:`wat.anchor.ots_anchor` is inherited.
    """
    receipt_path = manifest_path.parent / "root.bin.ots"
    # Lazy import keeps the call cheap on the default
    # magic-header-only path: the anchor module pulls in subprocess
    # + esplora + urllib transitively.
    try:
        from wat.anchor import ots_anchor  # noqa: WPS433 — lazy on purpose.
    except ImportError as exc:  # pragma: no cover — anchor is in-repo.
        return False, f"ots_anchor module import failed: {exc}"

    try:
        verified = ots_anchor.verify_receipt(
            receipt_path,
            merkle_root_bytes,
            esplora_fallback=True,
        )
    except ots_anchor.AnchorError as exc:
        # AnchorError is the documented soft-failure path for
        # missing CLI / receipt, timeouts, etc. Surface as a
        # skipped_reason so the caller can decide whether to gate.
        return False, f"ots verifier soft-failure: {exc}"
    except Exception as exc:  # pragma: no cover — defensive.
        return False, f"ots verifier unexpected error: {exc}"

    if verified:
        return True, ""
    # Hard-False — receipt did not validate. No skipped_reason
    # because the verifier reached a definitive verdict.
    return False, ""


def _check_ots_anchor_side_files(
    manifest_path: Path, declared_root_hex: str, *, full_verify: bool = False
) -> OtsAnchorCheck:
    """Verify root.bin + root.bin.ots side-files next to a real-manifest.

    The aggregator places ``root.bin`` (32 bytes, raw merkle_root) and
    ``root.bin.ots`` (OpenTimestamps proof) in the same directory as
    ``manifest.json``. We assert (a) ``root.bin`` exists, is 32 bytes,
    and its hex equals ``manifest.merkle_root``; (b) ``root.bin.ots``
    exists and starts with the OTS magic header.

    We deliberately do not run ``ots verify`` — that needs Bitcoin RPC
    and would make the verifier non-hermetic. ``ots verify`` belongs in
    the operator-tool chain, not in the manifest-validity stub.
    """
    parent = manifest_path.parent
    root_bin = parent / "root.bin"
    ots_file = parent / "root.bin.ots"

    if not root_bin.exists():
        return OtsAnchorCheck(
            checked=True,
            failure_reason=f"ots: root.bin not found next to manifest at {root_bin}",
        )

    # Sidecar read can fail on a present-but-unreadable file (e.g.
    # restrictive umask on the aggregator side, ops sandbox that
    # denies the verifier service account, transient I/O errors).
    # The verifier must not crash; it must surface a structured
    # rejection. Sprint-4 Tag-1 receipt-persistence-edge-case
    # hardening (see tests/wat/test_tv3_receipt_persistence_edges.py).
    try:
        raw = root_bin.read_bytes()
    except OSError as exc:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            failure_reason=(
                f"ots: root.bin present but unreadable at {root_bin}: {exc}"
            ),
        )
    if len(raw) != 32:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            failure_reason=(
                f"ots: root.bin is {len(raw)} bytes, expected 32 raw bytes"
            ),
        )

    if raw.hex() != declared_root_hex:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            failure_reason=(
                f"ots: root.bin hex {raw.hex()} does not match "
                f"manifest.merkle_root {declared_root_hex}"
            ),
        )

    if not ots_file.exists():
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            root_bin_matches_manifest=True,
            failure_reason=f"ots: root.bin.ots not found at {ots_file}",
        )

    try:
        head = ots_file.read_bytes()[: len(_OTS_MAGIC_HEADER)]
    except OSError as exc:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            root_bin_matches_manifest=True,
            failure_reason=(
                f"ots: root.bin.ots present but unreadable at {ots_file}: {exc}"
            ),
        )
    if head != _OTS_MAGIC_HEADER:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            root_bin_matches_manifest=True,
            ots_present=True,
            failure_reason=(
                "ots: root.bin.ots does not start with OpenTimestamps magic "
                f"header; first {len(_OTS_MAGIC_HEADER)} bytes are {head!r}"
            ),
        )

    # Magic-header pin passed. Off-default: run full ``ots verify``
    # if the caller asked. Bitcoin-RPC dependency is gated here:
    # this branch is the only one that may shell out to ``ots`` and
    # potentially hit the network (Esplora HTTP fallback).
    if not full_verify:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            root_bin_matches_manifest=True,
            ots_present=True,
            ots_magic_ok=True,
            failure_reason="",
        )

    full_ok, skipped_reason = _run_ots_full_verify(manifest_path, raw)
    if skipped_reason:
        # Soft outcome — magic-header still authoritative for the
        # pin contract; surface diagnostic without flipping ``ok``.
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            root_bin_matches_manifest=True,
            ots_present=True,
            ots_magic_ok=True,
            full_verify_attempted=True,
            full_verify_ok=False,
            full_verify_skipped_reason=skipped_reason,
            failure_reason="",
        )
    if not full_ok:
        return OtsAnchorCheck(
            checked=True,
            root_bin_present=True,
            root_bin_matches_manifest=True,
            ots_present=True,
            ots_magic_ok=True,
            full_verify_attempted=True,
            full_verify_ok=False,
            failure_reason=(
                "ots: full ots verify rejected the receipt — Bitcoin "
                "attestation does not attest to manifest.merkle_root "
                f"{declared_root_hex}"
            ),
        )

    return OtsAnchorCheck(
        checked=True,
        root_bin_present=True,
        root_bin_matches_manifest=True,
        ots_present=True,
        ots_magic_ok=True,
        full_verify_attempted=True,
        full_verify_ok=True,
        failure_reason="",
    )


@dataclasses.dataclass(frozen=True)
class RealManifestResult:
    """Outcome of verifying a real on-disk manifest file.

    Sister type to :class:`ManifestV2Result`; carries the same
    schema/integrity flags plus an :class:`OtsAnchorCheck` for the
    OTS-pin-anchor side-files.
    """

    manifest_path: str
    version: str
    fields_ok: bool
    integrity_ok: bool
    multi_cap_root_status: str = ""
    ots_anchor: OtsAnchorCheck = dataclasses.field(default_factory=OtsAnchorCheck)
    failure_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.fields_ok and self.integrity_ok and self.ots_anchor.ok


def verify_real_manifest_file(
    manifest_path: str | Path,
    *,
    check_ots_anchor: bool = True,
    strict_multi_cap_root: bool = True,
    use_schema_file: bool = False,
    real_schema_path: str | Path | None = None,
    ots_full_verify: bool = False,
) -> RealManifestResult:
    """Verify a real on-disk manifest file (v1 or v2 wire-form).

    Parameters
    ----------
    manifest_path:
        Filesystem path to ``manifest.json`` produced by the real
        aggregator (``.runtime/wat-tv*-archive/<RUN>/<HOUR>/``). Real
        manifests use ``wakir-wat-manifest/v1`` (current) or
        ``wakir-wat-manifest/v2`` (future v2 producer); the v2-spec
        JSON-Schema is *not* applied here because the on-disk shape
        diverges in additive ways (``leaf_hash`` vs ``leaf``, leaves
        as objects vs hex strings).
    check_ots_anchor:
        When True (default), verify ``root.bin`` (32 raw bytes equal
        to ``merkle_root``) and ``root.bin.ots`` (OpenTimestamps magic
        header) side-files next to the manifest. The actual
        timestamp-completeness check is delegated to ``ots verify``;
        this stub only asserts the side-files exist and are
        well-formed.
    strict_multi_cap_root:
        When True (default since Sprint-2 Tag-4), runs the same
        ordered-Merkle ``caprefs_root`` recompute as
        :func:`verify_manifest_v2_file` *if* the manifest carries
        ``multi_cap_events``. v1 manifests do not, so this flag is
        a no-op against today's real manifests.
    use_schema_file:
        When True (off-default since Sprint-2 Tag-6), additionally
        validate the manifest against the formal v1 JSON-Schema file
        at ``real_schema_path`` (or :data:`DEFAULT_REAL_SCHEMA_PATH`
        when not given) before running the in-code field-by-field
        validator. The schema-file path is the contract with external
        verifier implementers; the in-code path is the redundant
        hermetic-no-deps fallback. Both paths are run together when
        this flag is True so that drift between the two is caught
        immediately. When False (default) the in-code path alone
        validates, matching Sprint-2 Tag-5 behaviour.
    real_schema_path:
        Override the default location of the v1 schema file. Useful
        for tests; production callers should leave this None.
    ots_full_verify:
        When True (off-default since Sprint-3 Tag-4), additionally
        invoke :func:`wat.anchor.ots_anchor.verify_receipt` against
        ``root.bin.ots`` to confirm the OTS receipt is finalised on
        Bitcoin (or cross-validated via the Esplora HTTP fallback)
        and attests to ``manifest.merkle_root``. This Bitcoin-RPC-
        dependent path is the strongest available proof but adds a
        subprocess call (and potentially a single network round-
        trip to the configured Esplora endpoint), which is why it
        is off by default. The CLI ``--ots-full-verify`` flag and
        the ``WAKIR_OTS_FULL_VERIFY=1`` env var both flip this on.
        See ``docs/wat-manifest-v2-spec.md`` §11 (Sprint-3 Tag-4
        entry).
    """
    path = Path(manifest_path)
    if not path.exists():
        return RealManifestResult(
            manifest_path=str(path),
            version="",
            fields_ok=False,
            integrity_ok=False,
            failure_reason=f"fields: manifest file not found: {path}",
        )

    try:
        with path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except json.JSONDecodeError as exc:
        return RealManifestResult(
            manifest_path=str(path),
            version="",
            fields_ok=False,
            integrity_ok=False,
            failure_reason=f"fields: malformed JSON: {exc}",
        )

    if not isinstance(manifest, dict):
        return RealManifestResult(
            manifest_path=str(path),
            version="",
            fields_ok=False,
            integrity_ok=False,
            failure_reason="fields: top-level JSON must be an object",
        )

    version = manifest.get("version", "") if isinstance(manifest, dict) else ""

    if use_schema_file:
        schema_p = (
            Path(real_schema_path)
            if real_schema_path is not None
            else DEFAULT_REAL_SCHEMA_PATH
        )
        schema_ok, schema_failure = _validate_real_manifest_against_schema(
            manifest, schema_p
        )
        if not schema_ok:
            return RealManifestResult(
                manifest_path=str(path),
                version=version if isinstance(version, str) else "",
                fields_ok=False,
                integrity_ok=False,
                failure_reason=f"fields: {schema_failure}",
            )

    field_msg = _validate_real_manifest_fields(manifest)
    if field_msg:
        return RealManifestResult(
            manifest_path=str(path),
            version=version if isinstance(version, str) else "",
            fields_ok=False,
            integrity_ok=False,
            failure_reason=f"fields: {field_msg}",
        )

    leaves_msg, normalised_leaves = _normalise_real_leaves(manifest)
    if leaves_msg:
        return RealManifestResult(
            manifest_path=str(path),
            version=version,
            fields_ok=False,
            integrity_ok=False,
            failure_reason=f"fields: {leaves_msg}",
        )

    event_msg = _check_real_event_leaves(manifest, normalised_leaves)
    if event_msg:
        return RealManifestResult(
            manifest_path=str(path),
            version=version,
            fields_ok=True,
            integrity_ok=False,
            failure_reason=f"integrity: {event_msg}",
        )

    root_msg = _check_real_merkle_root(manifest, normalised_leaves)
    if root_msg:
        return RealManifestResult(
            manifest_path=str(path),
            version=version,
            fields_ok=True,
            integrity_ok=False,
            failure_reason=f"integrity: {root_msg}",
        )

    multi_cap_status = ""
    if "multi_cap_events" in manifest or "multi_cap_summary" in manifest:
        # Treat any multi-cap presence as an opt-in to the v2 multi-cap
        # consistency check; the same strict/lenient flag governs.
        multi_msg, multi_cap_status = _check_multi_cap_consistency(
            manifest, strict_multi_cap_root=strict_multi_cap_root
        )
        if multi_msg:
            phase = (
                "multi_cap_root"
                if multi_cap_status == "mismatch"
                else "integrity"
            )
            return RealManifestResult(
                manifest_path=str(path),
                version=version,
                fields_ok=True,
                integrity_ok=False,
                multi_cap_root_status=multi_cap_status,
                failure_reason=f"{phase}: {multi_msg}",
            )

    ots = OtsAnchorCheck()
    if check_ots_anchor:
        # Env-flag flips full-verify on without changing call sites.
        # The explicit kwarg still wins; env is only checked when the
        # caller did not pass an explicit decision.
        effective_full_verify = ots_full_verify or _full_verify_env_enabled()
        ots = _check_ots_anchor_side_files(
            path,
            manifest["merkle_root"],
            full_verify=effective_full_verify,
        )
        if not ots.ok:
            return RealManifestResult(
                manifest_path=str(path),
                version=version,
                fields_ok=True,
                integrity_ok=True,
                multi_cap_root_status=multi_cap_status,
                ots_anchor=ots,
                failure_reason=ots.failure_reason,
            )

    return RealManifestResult(
        manifest_path=str(path),
        version=version,
        fields_ok=True,
        integrity_ok=True,
        multi_cap_root_status=multi_cap_status,
        ots_anchor=ots,
        failure_reason="",
    )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wakir-verify-manifest-v2",
        description=(
            "Validate a WAT hour-manifest file against the v2 JSON-Schema "
            "and re-derive its leaves / Merkle root / multi-cap sidecar to "
            "check internal consistency. Sister utility to wakir-verify; "
            "this one operates on a single manifest file rather than an "
            "event_id + archive directory."
        ),
    )
    parser.add_argument(
        "manifest",
        help="Path to a manifest.json file (v1 or v2).",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help=(
            "Path to the wat-manifest-v2 JSON-Schema file. "
            "Defaults to the in-tree wirelang/schemas copy."
        ),
    )
    parser.add_argument(
        "--strict-multi-cap-root",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Recompute caprefs_root from caprefs_full under the ordered-"
            "Merkle convention (OQ-1 ratified 2026-05-07 by wirelang-"
            "engineering Cross-Review-Zone-2) and reject on mismatch. "
            "On by default since Sprint-2 Tag-4. Use "
            "--no-strict-multi-cap-root for lenient mode (deferred-"
            "warning) — escape hatch for third-party verifiers that "
            "have not yet adopted the locked ordering."
        ),
    )
    parser.add_argument(
        "--real-manifest",
        action="store_true",
        help=(
            "Treat the input as a real on-disk manifest "
            "(wakir-wat-manifest/v1 wire-form, as emitted by "
            "wat/aggregator.py and stored under "
            ".runtime/wat-tv*-archive/<RUN>/<HOUR>/manifest.json) "
            "instead of v2-spec-shaped. Skips JSON-Schema validation "
            "and runs field-by-field validation + Merkle rebuild + "
            "OTS-anchor side-file check. See "
            "docs/wat-manifest-v2-spec.md §10 (Sprint-2 Tag-5 entry)."
        ),
    )
    parser.add_argument(
        "--check-ots-anchor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "In --real-manifest mode, verify root.bin (32 raw bytes "
            "equal to merkle_root) and root.bin.ots (OpenTimestamps "
            "magic header) side-files next to manifest.json. Default "
            "ON. Use --no-check-ots-anchor for hermetic test fixtures "
            "or staged manifests where the anchor is not yet present. "
            "Note: this stub only checks well-formedness of the .ots "
            "file at the magic-header level; full Bitcoin-attestation "
            "completeness is delegated to 'ots verify'."
        ),
    )
    parser.add_argument(
        "--use-schema-file",
        action="store_true",
        help=(
            "In --real-manifest mode, additionally validate against the "
            "formal v1 JSON-Schema file (wirelang/schemas/wakir-wat-"
            "manifest-v1.json by default). Off by default; the in-code "
            "field-by-field validator runs in either case as the "
            "redundant hermetic-no-deps path. See "
            "docs/wat-manifest-v2-spec.md §11 (Sprint-2 Tag-6 entry)."
        ),
    )
    parser.add_argument(
        "--real-schema",
        default=None,
        help=(
            "Override the v1 JSON-Schema file path used by "
            "--use-schema-file. Defaults to the in-tree "
            "wirelang/schemas/wakir-wat-manifest-v1.json. Most callers "
            "should leave this unset."
        ),
    )
    parser.add_argument(
        "--ots-full-verify",
        action="store_true",
        help=(
            "In --real-manifest mode, additionally invoke "
            "'wat.anchor.ots_anchor.verify_receipt' against root.bin.ots "
            "to confirm the OpenTimestamps receipt is finalised on "
            "Bitcoin (or cross-validated via the Esplora HTTP fallback) "
            "and attests to manifest.merkle_root. Off by default since "
            "Sprint-3 Tag-4: the magic-header pin is the hermetic path; "
            "full verify shells out to the 'ots' CLI and may consult "
            "Esplora over the network. Equivalent to setting "
            "WAKIR_OTS_FULL_VERIFY=1 in the environment. See "
            "docs/wat-manifest-v2-spec.md §11 (Sprint-3 Tag-4 entry)."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-step reporting; emit only ok / fail line.",
    )
    parser.add_argument(
        "--output",
        choices=("human", "json", "audit-trail-entry"),
        default="human",
        help=(
            "Output format. 'human' (default) emits the multi-line "
            "diagnostic block; 'json' emits a single-line JSON object "
            "with the manifest-centric verifier-result schema "
            "(schema_version 'wakir-verify-manifest-v2/0'); "
            "'audit-trail-entry' emits the eleven-field paired-update "
            "shape consumed by the frontend audit-trail-browser "
            "(see ManifestV2Result.as_audit_trail_entry). The JSON "
            "schema and the audit-trail-entry contract are pinned in "
            "docs/wat-manifest-v2-spec.md §10. --quiet is ignored when "
            "--output is not 'human'."
        ),
    )
    return parser


def _format_human(result: ManifestV2Result, *, quiet: bool) -> str:
    if quiet:
        if result.ok:
            return f"ok\t{result.version or '(unknown)'}\t{result.manifest_path}"
        return f"fail\t{result.failure_reason}\t{result.manifest_path}"
    lines = [
        f"manifest:        {result.manifest_path}",
        f"version:         {result.version or '(unknown)'}",
        f"schema_ok:       {result.schema_ok}",
        f"integrity_ok:    {result.integrity_ok}",
    ]
    if result.multi_cap_root_status:
        lines.append(f"multi_cap_root:  {result.multi_cap_root_status}")
    if result.failure_reason:
        lines.append(f"failure_reason:  {result.failure_reason}")
    elif result.multi_cap_root_status == "deferred":
        lines.append(
            "warning:         multi_cap_root not yet verified (OQ-1 pending)"
        )
    return "\n".join(lines)


def _format_human_real(result: RealManifestResult, *, quiet: bool) -> str:
    if quiet:
        if result.ok:
            return f"ok\t{result.version or '(unknown)'}\t{result.manifest_path}"
        return f"fail\t{result.failure_reason}\t{result.manifest_path}"
    lines = [
        f"manifest:        {result.manifest_path}",
        f"version:         {result.version or '(unknown)'}",
        f"fields_ok:       {result.fields_ok}",
        f"integrity_ok:    {result.integrity_ok}",
    ]
    if result.multi_cap_root_status:
        lines.append(f"multi_cap_root:  {result.multi_cap_root_status}")
    if result.ots_anchor.checked:
        lines.append(f"ots_root_bin:    {result.ots_anchor.root_bin_matches_manifest}")
        lines.append(f"ots_magic_ok:    {result.ots_anchor.ots_magic_ok}")
        if result.ots_anchor.full_verify_attempted:
            lines.append(
                f"ots_full_verify: {result.ots_anchor.full_verify_ok}"
            )
            if result.ots_anchor.full_verify_skipped_reason:
                lines.append(
                    "ots_full_verify_skipped: "
                    f"{result.ots_anchor.full_verify_skipped_reason}"
                )
    if result.failure_reason:
        lines.append(f"failure_reason:  {result.failure_reason}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code.

    Exit codes
    ----------

    0   manifest validates and is internally consistent
    1   schema, integrity, or multi_cap_root failure
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.real_manifest:
        real_result = verify_real_manifest_file(
            args.manifest,
            check_ots_anchor=args.check_ots_anchor,
            strict_multi_cap_root=args.strict_multi_cap_root,
            use_schema_file=args.use_schema_file,
            real_schema_path=args.real_schema,
            ots_full_verify=args.ots_full_verify,
        )
        if args.output == "json":
            payload = {
                "schema_version": "wakir-verify-manifest-v2/0",
                "manifest_path": real_result.manifest_path,
                "manifest_version": real_result.version,
                "ok": real_result.ok,
                "fields_ok": real_result.fields_ok,
                "integrity_ok": real_result.integrity_ok,
                "multi_cap_root_status": real_result.multi_cap_root_status,
                "ots_anchor_checked": real_result.ots_anchor.checked,
                "ots_anchor_ok": real_result.ots_anchor.ok,
                "ots_full_verify_attempted": (
                    real_result.ots_anchor.full_verify_attempted
                ),
                "ots_full_verify_ok": real_result.ots_anchor.full_verify_ok,
                "ots_full_verify_skipped_reason": (
                    real_result.ots_anchor.full_verify_skipped_reason
                ),
                "failure_reason": real_result.failure_reason,
            }
            print(json.dumps(payload, sort_keys=True))
        elif args.output == "audit-trail-entry":
            # Audit-trail-entry shape mirrors the v2-spec output. Real-
            # manifest mode carries the same eleven keys, mapping
            # ots_anchor sub-status into the branch detail when relevant.
            try:
                with open(args.manifest, "r", encoding="utf-8") as fh:
                    manifest_dict = json.load(fh)
                hour_slot = (
                    str(manifest_dict.get("hour_slot", "") or "")
                    if isinstance(manifest_dict, dict)
                    else ""
                )
                root_candidate = (
                    manifest_dict.get("merkle_root", "")
                    if isinstance(manifest_dict, dict)
                    else ""
                ) or ""
                anchor_root_hex = (
                    root_candidate
                    if isinstance(root_candidate, str)
                    and _is_lower_hex_64(root_candidate)
                    else ""
                )
                ec = (
                    manifest_dict.get("event_count")
                    if isinstance(manifest_dict, dict)
                    else None
                )
                event_count: Optional[int] = ec if isinstance(ec, int) else None
            except (OSError, json.JSONDecodeError):
                hour_slot = ""
                anchor_root_hex = ""
                event_count = None

            # Bridge to ManifestV2Result.as_audit_trail_entry by
            # constructing a synthetic equivalent (preserves the
            # eleven-field paired-update contract).
            bridge = ManifestV2Result(
                manifest_path=real_result.manifest_path,
                version=real_result.version,
                schema_ok=real_result.fields_ok,
                integrity_ok=real_result.integrity_ok and real_result.ots_anchor.ok,
                multi_cap_root_status=real_result.multi_cap_root_status,
                failure_reason=real_result.failure_reason,
            )
            entry = bridge.as_audit_trail_entry(
                anchor_root_hex=anchor_root_hex,
                hour_slot=hour_slot,
                event_count=event_count,
            )
            print(json.dumps(entry, sort_keys=True, ensure_ascii=False))
        else:
            print(_format_human_real(real_result, quiet=args.quiet))
        return 0 if real_result.ok else 1

    result = verify_manifest_v2_file(
        args.manifest,
        schema_path=args.schema,
        strict_multi_cap_root=args.strict_multi_cap_root,
    )
    if args.output == "json":
        print(json.dumps(result.as_dict(), sort_keys=True))
    elif args.output == "audit-trail-entry":
        # Re-parse the manifest only for the optional fields the
        # audit-trail-entry shape carries (hour_slot, merkle_root,
        # event_count). Failures here are non-fatal: a malformed
        # manifest already failed verification above and the entry
        # still renders with empty defaults so consumers see the
        # rejected branch.
        hour_slot = ""
        anchor_root_hex = ""
        event_count: Optional[int] = None
        try:
            with open(args.manifest, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            if isinstance(manifest, dict):
                hour_slot = str(manifest.get("hour_slot", "") or "")
                root_candidate = manifest.get("merkle_root", "") or ""
                if isinstance(root_candidate, str) and _is_lower_hex_64(root_candidate):
                    anchor_root_hex = root_candidate
                ec = manifest.get("event_count")
                if isinstance(ec, int):
                    event_count = ec
        except (OSError, json.JSONDecodeError):
            pass
        entry = result.as_audit_trail_entry(
            anchor_root_hex=anchor_root_hex,
            hour_slot=hour_slot,
            event_count=event_count,
        )
        print(json.dumps(entry, sort_keys=True, ensure_ascii=False))
    else:
        print(_format_human(result, quiet=args.quiet))
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DEFAULT_REAL_SCHEMA_PATH",
    "DEFAULT_SCHEMA_PATH",
    "ManifestV2Result",
    "OtsAnchorCheck",
    "RealManifestResult",
    "build_parser",
    "main",
    "verify_manifest_v2_file",
    "verify_real_manifest_file",
]
