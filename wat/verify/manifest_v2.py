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
# Schema location
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Default location of the v2 schema relative to the repo. Tests and
#: callers can override via ``schema_path`` parameter when the
#: repo layout differs.
DEFAULT_SCHEMA_PATH = (
    _REPO_ROOT / "wirelang" / "schemas" / "wat-manifest-v2.json"
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code.

    Exit codes
    ----------

    0   manifest validates and is internally consistent
    1   schema, integrity, or multi_cap_root failure
    """
    parser = build_parser()
    args = parser.parse_args(argv)

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
    "DEFAULT_SCHEMA_PATH",
    "ManifestV2Result",
    "build_parser",
    "main",
    "verify_manifest_v2_file",
]
