# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# This file is part of the Wakir Persona-Engine module. Licensed
# under the Business Source License 1.1; see ../LICENSE-BSL.md
# (the wirelang-package canonical header). Change Date: four (4)
# years after first publication; Change License: Apache 2.0.
"""Per-org-per-persona NATS-JetStream KV bucket schema (Phase-2 Sprint-
Pengine-7 Tag-5 OI-PILOT-2).

This module is the single source of truth for the persona-state
bucket family. The provisioner driver
``bin/nats-kv-bucket-provision`` imports the constants here
verbatim; the Quadlet-side init oneshot
``wakir-nats-kv-bucket-init.service`` re-uses the same driver to
provision the family per per-host onboarded-orgs roster ×
onboarded-personas roster.

Bucket family identity
----------------------

One bucket per ``(org_id, persona_id)`` pair. The bucket name is

    wakir-persona-state-<org_id>-<persona_id>

This is **deliberately** a different shape than the marker-stack
and sequence-ledger families (which key on ``org_id`` only). The
persona-state family carries persona-scoped lifecycle records
(spawn/despawn/recovery-drill events plus the persona-id-bound
session ``state_pack``); a single bucket per persona keeps the
operator-observable substrate aligned with the persona-engine
recovery-drill model from Sprint-Pengine-7 Tag-3/§3.7.4.

Why a separate family
---------------------

The Sprint-8 Tag-4 ``wakir-marker-stack-<org_id>`` bucket carries
capability-marker events (Reza-owned domain). The persona-state
bucket carries persona-lifecycle events (Selin-owned domain). The
two MUST NOT share a bucket — they have different drift policies,
different replay semantics, and different cross-domain isolation
contracts:

- marker-stack: append-only, sort-stable reducer (Sprint-8 Tag-3
  ``reduce_marker_stack``), cross-org isolation via
  ``MarkerStackCrossOrgBoundaryError``.
- persona-state: key-per-event with persona-scoped namespacing,
  state-pack overwrite-with-CAS semantics for the current spawn-
  session, append-only for recovery-drill audit records (the
  ``recovery_drill_outcome`` envelopes that Tag-4 §3.7.4
  recovery-workflows emit and OI-PILOT-4 anchors hourly to WAT).

Bucket configuration
--------------------

- ``description``: "Wakir persona-engine state log (Phase-2 Pengine-7)"
- ``history``: 1 (we never reach back further than the current
  spawn-session; recovery-drill audit records are replayed from
  ``RECOVERY_AUDIT_*`` keys, not from history).
- ``ttl_seconds``: 0 (unbounded; audit-trail invariant).
- ``max_value_size``: 65_536 (64 KiB; persona-state-pack envelope
  ceiling — the persona-state-pack can be larger than a marker-
  stack event because it inlines the canonical persona-JSON +
  the spawn-session conversation tail. The 64 KiB ceiling is
  comfortable for the pilot phase; once we have empirical
  envelope-size telemetry from Tomás-Pilot we can re-evaluate
  in a follow-up paired-update).
- ``storage``: "file" (durability-first, pilot phase single-node).
- ``replicas``: 1 (Phase-1c single-node; Phase-3 promotes to ≥3).

Key schema
----------

The bucket carries three kinds of keys, distinguished by prefix:

- ``state-pack/current`` — the live spawn-session state-pack. One
  per bucket (one persona per bucket). Overwrite-with-CAS on every
  spawn-state mutation. The value envelope carries the canonical
  persona-JSON (V-907-hashed), the spawn-session-id, the
  conversation-tail tip-pointer, and the per-axis-A lifecycle
  state (``spawned`` / ``running`` / ``draining`` /
  ``despawned``).
- ``lifecycle-events/<sequence>`` — append-only per-persona
  lifecycle event log. Each event is a Tag-3 §3.7.2 / Tag-4
  §3.7.4 lifecycle envelope (spawn / despawn / recovery-trigger /
  recovery-r1..r4 / recovery-outcome). Sequence numbers are
  1-indexed and zero-padded to 12 digits so KV list-key
  iteration returns events in append order without a sort step.
- ``recovery-audit/<drill_run_id>`` — one envelope per executed
  recovery-drill (Tag-3 §3.7.2.1 drill registry, closed three-
  class set: ``DRILL_CONTAINER_CRASH``, ``DRILL_NATS_BUCKET_LOST``,
  ``DRILL_SPIRE_SVID_EXPIRED``). The
  ``recovery_drill_outcome`` envelope is the OI-PILOT-4 cron
  source: a periodic Quadlet timer (Selin OI-PILOT-4 +
  Reza-Cross-Pair OI-PEF-11) reads these keys from NATS-KV and
  spools each one as a WAT leaf via
  ``wat.anchor.bridge_audit_writer.write_bridge_audit``. The cron
  is idempotent: once spooled, the WAT-anchored marker is
  written back to the same envelope as
  ``wat_anchored_at`` / ``wat_leaf_hash`` so a re-run skips
  already-anchored drills.

Identifier conventions
----------------------

``org_id`` and ``persona_id`` both follow the same permitted-
character regex as Sprint-8 Tag-4
``wirelang.federation.marker_stack_kv._IDENT_RE`` (URI-safe
ASCII subset, no slashes, no whitespace). Cross-Review Zone-B
parity with Reza-side bucket-name derivation: the regex is the
**same** pattern, re-declared here so this module is
import-independent of the federation tree (constants-only posture
for Sprint-9 Tag-4 lessons-learned).

Cross-trust-domain isolation
----------------------------

Each ``(org_id, persona_id)`` pair operates against its own
bucket; reads against a bucket whose name does not match the
calling persona's ``(org_id, persona_id)`` pair MUST be refused
at the consumer layer (no in-bucket cross-org boundary check —
the bucket name itself carries the boundary). This module does
NOT implement that consumer; it ships the substrate-shaping
contract only.

Sandbox boundary
----------------

Live NATS connections are operator-hand (per
``feedback_sandbox_host_trennung.md``). All tests in this module
run against an in-memory mock that mirrors the
``test_nats_kv_bucket_provision_multi_family.py`` mock shape.

References
----------

- Sprint-Pengine-7 Tag-3 §3.7.2 — recovery-drill registry (axis-A).
- Sprint-Pengine-7 Tag-4 §3.7.4 — recovery-workflow (impl-axis).
- ADR-0058 — Pilot-Persona-Migrations-Plan, Tomás-Pilot.
- Sprint-8 Tag-4 ``wirelang.federation.marker_stack_kv`` — pattern
  source for per-org bucket families.
- Sprint-9 Tag-1 ``bin/nats-kv-bucket-provision`` — provisioner
  driver, multi-family registry consumer.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Tuple


# ---------------------------------------------------------------------------
# Bucket identity / key derivation
# ---------------------------------------------------------------------------


#: Bucket name prefix; the full bucket name is
#: ``BUCKET_NAME_PREFIX + "<org_id>-<persona_id>"``.
BUCKET_NAME_PREFIX = "wakir-persona-state-"

#: Documented bucket configuration. Drift-policy: any deviation
#: between the live cluster and these values is reported as drift,
#: never auto-corrected (same contract as the marker-stack /
#: sequence-ledger families).
BUCKET_CONFIG: Mapping[str, Any] = {
    "description": "Wakir persona-engine state log (Phase-2 Pengine-7)",
    "history": 1,
    "ttl_seconds": 0,
    "max_value_size": 65_536,
    "storage": "file",
    "replicas": 1,
}

#: Schema URI embedded in the ``state-pack/current`` value envelope.
STATE_PACK_VALUE_SCHEMA = "wakir.persona.state-pack/1"

#: Schema URI embedded in each ``lifecycle-events/<seq>`` envelope.
LIFECYCLE_EVENT_VALUE_SCHEMA = "wakir.persona.lifecycle-event/1"

#: Schema URI embedded in each ``recovery-audit/<drill_run_id>``
#: envelope. This is the schema that the OI-PILOT-4 cron + Reza
#: OI-PEF-11 schema-registry-Entry pin together.
RECOVERY_DRILL_OUTCOME_VALUE_SCHEMA = "wakir.persona.recovery-drill-outcome/1"

#: Permitted-character regex for ``org_id`` and ``persona_id``
#: (URI-safe ASCII subset, no slashes). Same pattern as
#: ``wirelang.federation.marker_stack_kv._IDENT_RE`` but
#: independently declared so this module does NOT import the
#: federation tree (constants-only posture).
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")

#: Key prefixes for the three distinguished key kinds.
KEY_PREFIX_STATE_PACK = "state-pack/"
KEY_PREFIX_LIFECYCLE = "lifecycle-events/"
KEY_PREFIX_RECOVERY_AUDIT = "recovery-audit/"

#: The single state-pack key (one per bucket, overwrite-with-CAS).
STATE_PACK_KEY = "state-pack/current"


def _validate_identifier(name: str, kind: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{kind} must be a non-empty string, got {name!r}")
    if not _IDENT_RE.match(name):
        raise ValueError(
            f"{kind} {name!r} does not match permitted-character "
            f"pattern {_IDENT_RE.pattern!r}"
        )


def bucket_name_for_pair(org_id: str, persona_id: str) -> str:
    """Return the canonical bucket name for ``(org_id, persona_id)``.

    Raises :class:`ValueError` if either identifier does not match
    the permitted-character regex. The derivation is deterministic
    and bijective: ``bucket_name_for_pair`` and
    :func:`pair_for_bucket_name` round-trip byte-equal.
    """
    _validate_identifier(org_id, "org_id")
    _validate_identifier(persona_id, "persona_id")
    return f"{BUCKET_NAME_PREFIX}{org_id}-{persona_id}"


def pair_for_bucket_name(bucket_name: str) -> Tuple[str, str]:
    """Inverse of :func:`bucket_name_for_pair`. Returns
    ``(org_id, persona_id)``. Raises :class:`ValueError` for a
    non-matching prefix or a malformed payload.

    Note: the split point between ``org_id`` and ``persona_id`` is
    the FIRST ``-`` in the payload. ``org_id`` MUST NOT contain a
    bare ``-`` if the operator relies on the inverse function; the
    permitted-character regex permits ``-`` inside identifiers, so
    a defensive operator should constrain ``org_id`` to a
    no-hyphen subset (e.g. ``acme``, ``orbit``) at onboarding
    time. The forward function does NOT enforce this, by design —
    the provisioner driver only uses the forward derivation.
    """
    if not isinstance(bucket_name, str):
        raise ValueError(f"bucket_name must be a string, got {bucket_name!r}")
    if not bucket_name.startswith(BUCKET_NAME_PREFIX):
        raise ValueError(
            f"bucket_name must start with {BUCKET_NAME_PREFIX!r}: "
            f"{bucket_name!r}"
        )
    payload = bucket_name[len(BUCKET_NAME_PREFIX):]
    if "-" not in payload:
        raise ValueError(
            f"bucket_name payload must contain '-' separator: "
            f"{bucket_name!r}"
        )
    org_id, _, persona_id = payload.partition("-")
    _validate_identifier(org_id, "org_id")
    _validate_identifier(persona_id, "persona_id")
    return org_id, persona_id


def bucket_name_for_org(combined: str) -> str:
    """Driver-compatible shim: accept a single combined ``<org_id>-
    <persona_id>`` token and return the bucket name.

    The Sprint-9 Tag-1 provisioner driver's :class:`BucketFamily`
    surface treats each family as keyed by ONE identifier (``org_id``).
    For the persona-state family, the driver-side identifier is the
    combined token ``"<org_id>-<persona_id>"``. This shim lets the
    family register with the driver's existing per-org idiom
    without splitting the driver's iteration shape.

    Validation: the combined token must satisfy ``_IDENT_RE`` and
    contain at least one ``-``. The ``-`` split is **not** validated
    here against the permitted-character regex for the two halves;
    callers that require the strict pair-shape MUST use
    :func:`bucket_name_for_pair` directly.
    """
    _validate_identifier(combined, "persona_state_id")
    if "-" not in combined:
        raise ValueError(
            f"persona_state_id must contain a '-' separating "
            f"<org_id> and <persona_id>, got {combined!r}"
        )
    return f"{BUCKET_NAME_PREFIX}{combined}"


def key_for_lifecycle_event(sequence: int) -> str:
    """Derive the canonical KV key for a lifecycle event.

    Format: ``lifecycle-events/<sequence>``. Sequence is 1-indexed
    and zero-padded to 12 digits so KV list-key iteration returns
    events in append order without a sort step.

    Raises :class:`ValueError` for a non-positive sequence.
    """
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError(
            f"sequence must be a positive int, got {sequence!r}"
        )
    return f"{KEY_PREFIX_LIFECYCLE}{sequence:012d}"


def key_for_recovery_audit(drill_run_id: str) -> str:
    """Derive the canonical KV key for a recovery-drill-outcome
    envelope.

    Format: ``recovery-audit/<drill_run_id>``. ``drill_run_id`` is
    the operator-assigned identifier for a single drill execution
    (e.g. ``svid-expired-2026-05-15T04-12-00Z``). Permitted-
    character regex applies.
    """
    _validate_identifier(drill_run_id, "drill_run_id")
    return f"{KEY_PREFIX_RECOVERY_AUDIT}{drill_run_id}"


__all__ = [
    "BUCKET_CONFIG",
    "BUCKET_NAME_PREFIX",
    "KEY_PREFIX_LIFECYCLE",
    "KEY_PREFIX_RECOVERY_AUDIT",
    "KEY_PREFIX_STATE_PACK",
    "LIFECYCLE_EVENT_VALUE_SCHEMA",
    "RECOVERY_DRILL_OUTCOME_VALUE_SCHEMA",
    "STATE_PACK_KEY",
    "STATE_PACK_VALUE_SCHEMA",
    "bucket_name_for_org",
    "bucket_name_for_pair",
    "key_for_lifecycle_event",
    "key_for_recovery_audit",
    "pair_for_bucket_name",
]
