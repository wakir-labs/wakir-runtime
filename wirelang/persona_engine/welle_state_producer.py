# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-69 / Tag-70 Welle-N State-File Producer (Selin, persona-engine).

Implements the engine-side producer-path for ``state/welle-N.json``
top-level rollup-files per the Tag-68 Producer-Wiring-Plan
(``docs/persona-engine/state-file-producer-wiring-plan.md``).

Scope (Tag-69 + Tag-70, per Mira-Auftrag and plan-doc §5.1)
-----------------------------------------------------------

This module is the **producer-substrate** that Tag-69+ engine-side
event-handlers will call. It is intentionally **decoupled** from
``engine.py`` / ``engine_async.py``: the handlers in those modules
(``handle_welle_cutover_event``, ``handle_welle_sign_off_event``,
``handle_welle_rollback_event``, ``handle_welle_sealing_event``)
construct a :class:`WelleStateProducer` and delegate the
transition + atomic-write to this module. The decoupling keeps the
hot-path engine code free of filesystem-layout knowledge and lets
the producer-substrate be unit-tested in hermetic isolation.

Tag-69 shipped the **Welle-1 producer-path** (Cutover-T0 first-fire)
+ Sign-Off path. Tag-72 (this PR) adds the **Welle-4 State-Backing
sign-off** path (KW-25 Mo): a sign-off variant that additionally
requires a ``snapshot_restore_marker_status == "restored"``
precondition. Welle-4 is the only Welle whose sign-off is gated by
the snapshot-restore-marker (state-backing rust<->python switch is
the 10th pre-boot BackendDecision per the Tag-57-emit-order-pin;
the snapshot-restore-workflow is captured in
Tomas-Tag-56-Rollback-Workflow §J4). Tag-70 (earlier) added:

* **Welle-2 Doppelbetrieb-Sealing** trigger (KW-24 Mi, plan-doc §2.3):
  a sign-off variant that additionally requires a
  ``doppelbetrieb_sealed_marker_status == "sealed"`` precondition.
  Welle-2 is the only Welle whose sign-off is gated by the
  Doppelbetrieb-Sealing-marker (legacy↔new dual-write window closed).
* **Rollback-Writer** (``handle_rollback_event``) covering the three
  plan-doc §3.1 rollback transitions ``pending -> rolled-back``,
  ``in-progress -> rolled-back``, ``signed-off -> rolled-back``,
  gated by a ``rollback_marker_status == "rollback-authorized"``
  precondition. Rollback is terminal (plan-doc §3.2).

The implementation is parametric over ``welle_number`` (1..7) and
is therefore reused verbatim by Tag-71+ follow-ups for the
remaining Wellen.

Lifecycle-state-machine (plan-doc §3.1)
---------------------------------------

Allowed transitions::

    pending      -> in-progress    (Cutover-T0-Event)
    pending      -> rolled-back    (pre-cutover-rollback, rare)
    in-progress  -> signed-off     (Sign-Off-Event, with W3/W7 extra-guard)
    in-progress  -> rolled-back    (Rollback-Event)
    signed-off   -> rolled-back    (post-sign-off-rollback)

Forbidden transitions (plan-doc §3.2)::

    signed-off   -> in-progress    (no un-sign-off)
    signed-off   -> pending        (no state-erasure)
    rolled-back  -> *              (rollback terminal)
    in-progress  -> pending        (no demotion)
    X            -> X              (no-op, not an error)

Atomicity
---------

Writes use the write-tmp + rename idiom (POSIX rename(2) is atomic
on the same filesystem). The temp-file is created in the same
directory as the target. On rename failure the temp-file is
cleaned up.

Audit-trail
-----------

Each successful transition emits an audit-record via the
:class:`AuditRecordEmitter` protocol. The default emitter is a
no-op; production wires it to
:class:`wirelang.persona_engine.bridge_audit_writer.BridgeAuditWriter`
through the :func:`audit_record_emitter_from_bridge_writer` adapter.

Sandbox-Boundary
----------------

This module is stdlib-only. No network, no NATS, no SPIRE, no
subprocess. Filesystem writes are confined to repo-local
``state/welle-N.json`` paths (path-traversal is rejected).

Scope discipline (Selin)
------------------------

This module does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K),
identity-substrate design (Reza-Domaene, Zone-L), or
container-infra (Kai-Domaene, Zone-J). It writes
``state/welle-N.json`` rollup-fields only -- the sign-off-marker,
validation-verdict, pre-auditor-decision, hot-spot-trend files
remain in their respective domain owners' control (plan-doc §6.2).

References
~~~~~~~~~~

* Plan-doc: ``docs/persona-engine/state-file-producer-wiring-plan.md``
* Schema-pin: ``docs/quality-gates/welle-n-state-file-conventions.md``
* Verifier: ``tooling/ci/verify_welle_state_file_conventions.py``
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Canonical constants (must stay byte-equivalent to the Tag-67 schema-pin).
# ---------------------------------------------------------------------------

SCHEMA_VERSION_PIN = "tag-67-v1"
PHASE_LITERAL = "phase-3-marathon"

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in-progress"
STATUS_SIGNED_OFF = "signed-off"
STATUS_ROLLED_BACK = "rolled-back"

ALLOWED_STATUSES = (
    STATUS_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_SIGNED_OFF,
    STATUS_ROLLED_BACK,
)

VALID_WELLE_NUMBERS = frozenset(range(1, 8))
VALID_KW_ANCHORS = frozenset({f"KW-2{d}" for d in range(2, 8)})

# RFC 3339 / ISO-8601, second precision, UTC `Z` or numeric offset.
ISO_TS_NONEMPTY_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$"
)

# Wellen for which the sign-off path requires a designated pre-auditor
# (Henrik-cannot-self-sign-off constraint -- plan-doc §2.2,
# schema-pin §2.5 / §5).
PRE_AUDITOR_GUARDED_WELLEN = frozenset({3, 7})

# Wellen for which the sign-off path additionally requires the
# Doppelbetrieb-Sealing-marker to report ``sealed`` (plan-doc §2.3,
# Tag-70 add-on). Welle-2 is the legacy↔new dual-write window
# closure; sign-off without sealed-marker is refused.
DOPPELBETRIEB_SEALED_WELLEN = frozenset({2})

# Rollback-marker authority literal: callers MUST pass this exact
# value as ``rollback_marker_status`` to authorise a rollback
# transition. Any other value is refused (Tag-70 §2.4).
ROLLBACK_MARKER_AUTHORIZED = "rollback-authorized"

# Doppelbetrieb-Sealing-marker literal: callers MUST pass this exact
# value as ``doppelbetrieb_sealed_marker_status`` to authorise the
# Welle-2 Doppelbetrieb-Sealing sign-off (Tag-70 §2.3).
DOPPELBETRIEB_SEALED = "sealed"

# Wellen for which the sign-off path additionally requires the
# snapshot-restore-marker to report ``restored`` (Tag-72 §2.5,
# Tomas-Tag-56-Rollback-Workflow §J4). Welle-4 is the State-Backing
# Welle (KW-25 Mo); the 10th pre-boot BackendDecision (state_backing
# rust<->python) is the only Welle whose sign-off requires a verified
# snapshot-restore. Without the restore-marker the Welle-4 sign-off
# would leave the state-backing substrate in an unverified state at
# the moment of cutover finalisation.
SNAPSHOT_RESTORE_GUARDED_WELLEN = frozenset({4})

# Snapshot-restore-marker literal: callers MUST pass this exact value
# as ``snapshot_restore_marker_status`` to authorise the Welle-4
# State-Backing sign-off (Tag-72 §2.5). Mirrors the
# :data:`DOPPELBETRIEB_SEALED` design.
SNAPSHOT_RESTORE_VERIFIED = "restored"

# Allowed lifecycle-state-machine transitions (plan-doc §3.1).
ALLOWED_TRANSITIONS = frozenset({
    (STATUS_PENDING, STATUS_IN_PROGRESS),
    (STATUS_PENDING, STATUS_ROLLED_BACK),
    (STATUS_IN_PROGRESS, STATUS_SIGNED_OFF),
    (STATUS_IN_PROGRESS, STATUS_ROLLED_BACK),
    (STATUS_SIGNED_OFF, STATUS_ROLLED_BACK),
})


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class WelleProducerError(RuntimeError):
    """Base class for producer-substrate refusal-to-write errors."""


class InvalidWelleNumberError(WelleProducerError):
    """Raised when welle_number is not in 1..7."""


class InvalidStatusTransitionError(WelleProducerError):
    """Raised when the requested status transition is forbidden."""


class TimeInvariantViolationError(WelleProducerError):
    """Raised when ISO timestamps violate plan-doc §3.4 invariants."""


class PreAuditorGuardError(WelleProducerError):
    """Raised on a Welle-3 / Welle-7 sign-off without pre-auditor."""


class SignOffPreconditionError(WelleProducerError):
    """Raised when the companion sign-off-marker file gates the write."""


class StateFileShapeError(WelleProducerError):
    """Raised when the on-disk state-file violates schema invariants."""


class PathTraversalError(WelleProducerError):
    """Raised when state_dir resolves outside the repo (defensive)."""


class RollbackAuthorityError(WelleProducerError):
    """Raised on a rollback without rollback-marker-authority (Tag-70 §2.4)."""


class DoppelbetriebSealingError(WelleProducerError):
    """Raised on a Welle-2 sign-off without sealed-marker (Tag-70 §2.3)."""


class SnapshotRestoreError(WelleProducerError):
    """Raised on a Welle-4 sign-off without snapshot-restore-marker (Tag-72 §2.5).

    Welle-4 is the State-Backing Welle (KW-25 Mo). The 10th pre-boot
    BackendDecision (state_backing rust<->python switch) flips during
    this Welle; the sign-off is only authorised once the operator-curated
    snapshot-restore-marker has flipped to
    :data:`SNAPSHOT_RESTORE_VERIFIED`. Mirrors the
    :class:`DoppelbetriebSealingError` design for Welle-2.
    """


# ---------------------------------------------------------------------------
# Audit-record emitter protocol.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WelleAuditRecord:
    """One audit-record emitted on a successful welle-N transition.

    The producer-substrate is decoupled from the bridge-audit-writer:
    callers wire an emitter via :class:`AuditRecordEmitter`. The
    record is intentionally minimal -- the bridge-audit-writer
    enriches it with org/persona/session IDs at emit-time.
    """

    welle_number: int
    prior_status: str
    new_status: str
    cutover_iso: str  # "" if not yet set
    signoff_iso: str  # "" if not yet set
    trigger: str  # "cutover" | "sign-off" | "rollback" | "sealing"

    def to_json_bytes(self) -> bytes:
        """Canonical JSON bytes for downstream audit-hash anchoring."""
        return json.dumps(
            {
                "cutover_iso": self.cutover_iso,
                "new_status": self.new_status,
                "prior_status": self.prior_status,
                "signoff_iso": self.signoff_iso,
                "trigger": self.trigger,
                "welle_number": self.welle_number,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


AuditRecordEmitter = Callable[[WelleAuditRecord], None]


def _noop_emitter(_record: WelleAuditRecord) -> None:
    """Default emitter: drops the record. Tag-69 wiring overrides."""


def audit_record_emitter_from_bridge_writer(
    bridge_writer: Any,
) -> AuditRecordEmitter:
    """Adapter: wrap a :class:`BridgeAuditWriter` as an emitter.

    The emitter calls ``bridge_writer.emit(output_kind="audit_annotation",
    payload=<canonical-json-bytes>)``. This keeps the producer-substrate
    free of a direct import of the bridge-audit-writer (no circular
    dependency).
    """

    def _emit(record: WelleAuditRecord) -> None:
        bridge_writer.emit(
            "audit_annotation",
            record.to_json_bytes(),
        )

    return _emit


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _validate_welle_number(welle_number: int) -> None:
    if welle_number not in VALID_WELLE_NUMBERS:
        raise InvalidWelleNumberError(
            f"welle_number must be in 1..7, got {welle_number!r}"
        )


def _validate_iso_timestamp(value: str, field_name: str) -> None:
    if not ISO_TS_NONEMPTY_RE.match(value):
        raise TimeInvariantViolationError(
            f"{field_name} must match RFC 3339 second-precision UTC "
            f"or numeric-offset; got {value!r}"
        )


def _is_under_repo_state_dir(target: Path, state_dir: Path) -> bool:
    """Return True iff ``target`` resolves under ``state_dir``.

    Path-traversal defence: rename-into-state-dir-only.
    """
    try:
        target.resolve().relative_to(state_dir.resolve())
    except ValueError:
        return False
    return True


def _state_file_path(state_dir: Path, welle_number: int) -> Path:
    _validate_welle_number(welle_number)
    target = state_dir / f"welle-{welle_number}.json"
    if not _is_under_repo_state_dir(target, state_dir):
        raise PathTraversalError(
            f"refusing to write outside state_dir: {target!r}"
        )
    return target


def _load_state_file(path: Path) -> Dict[str, Any]:
    """Read the on-disk state-file with shape validation."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StateFileShapeError(
            f"state-file missing: {path}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateFileShapeError(
            f"state-file not parseable JSON: {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise StateFileShapeError(
            f"state-file must be a JSON object, got {type(data).__name__}: {path}"
        )
    return data


def _required_shape_keys() -> Tuple[str, ...]:
    return (
        "welle_number",
        "schema_version",
        "phase",
        "kw_cutover_anchor",
        "cutover_iso",
        "signoff_iso",
        "status",
        "rollup_links",
        "audit_trail_anchor",
    )


def _enforce_shape(data: Mapping[str, Any], path: Path) -> None:
    for key in _required_shape_keys():
        if key not in data:
            raise StateFileShapeError(
                f"state-file missing required key {key!r}: {path}"
            )
    if data.get("schema_version") != SCHEMA_VERSION_PIN:
        raise StateFileShapeError(
            f"state-file schema_version mismatch: "
            f"expected {SCHEMA_VERSION_PIN!r}, "
            f"got {data.get('schema_version')!r}: {path}"
        )
    if data.get("phase") != PHASE_LITERAL:
        raise StateFileShapeError(
            f"state-file phase mismatch: "
            f"expected {PHASE_LITERAL!r}, got {data.get('phase')!r}: {path}"
        )
    status = data.get("status")
    if status not in ALLOWED_STATUSES:
        raise StateFileShapeError(
            f"state-file status out-of-enum: {status!r}: {path}"
        )


def _atomic_write_json(target: Path, payload: Dict[str, Any]) -> None:
    """Atomic write: temp-file + rename(2)."""
    target_dir = target.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target_dir),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(target))
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _check_transition(prior: str, new: str) -> None:
    """Reject forbidden transitions (plan-doc §3.2). Self-transition is no-op."""
    if prior == new:
        # No-op idempotent self-fire is OK and is handled higher up.
        return
    if (prior, new) not in ALLOWED_TRANSITIONS:
        raise InvalidStatusTransitionError(
            f"forbidden transition {prior!r} -> {new!r} "
            f"(plan-doc §3.2)"
        )


def _check_time_invariants(
    cutover_iso: str, signoff_iso: str
) -> None:
    """Plan-doc §3.4: cutover_iso <= signoff_iso when both non-empty."""
    if cutover_iso and signoff_iso and cutover_iso > signoff_iso:
        raise TimeInvariantViolationError(
            f"cutover_iso > signoff_iso: "
            f"{cutover_iso!r} > {signoff_iso!r}"
        )


# ---------------------------------------------------------------------------
# Producer.
# ---------------------------------------------------------------------------


@dataclass
class WelleStateProducer:
    """Engine-side producer for one ``state/welle-N.json`` rollup-file.

    The producer is **stateless across handler invocations**: each
    handler call re-reads the on-disk state-file, applies the
    transition, and writes back atomically. This matches the
    plan-doc §3.3 cross-Welle ordering invariant (per-Welle local,
    no cross-Welle coupling at the engine side).
    """

    state_dir: Path
    audit_emitter: AuditRecordEmitter = _noop_emitter

    # -- Transition: pending -> in-progress (Cutover-T0-Event) --

    def handle_cutover_event(
        self,
        welle_number: int,
        cutover_iso: str,
    ) -> WelleAuditRecord:
        """Apply the Cutover-T0 transition (plan-doc §2.1).

        Sets ``status = "in-progress"`` and ``cutover_iso`` to the
        event-iso. No-op (returns an audit-record with prior_status
        == new_status) if the on-disk status is already not
        ``pending`` (idempotency-guard per plan-doc §2.1).
        """
        _validate_welle_number(welle_number)
        _validate_iso_timestamp(cutover_iso, "cutover_iso")
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        prior_status = data["status"]
        if prior_status != STATUS_PENDING:
            # Idempotent no-op: the cutover-event has been seen before
            # (double-fire on retried workflow event, plan-doc §2.1).
            record = WelleAuditRecord(
                welle_number=welle_number,
                prior_status=prior_status,
                new_status=prior_status,
                cutover_iso=data.get("cutover_iso", ""),
                signoff_iso=data.get("signoff_iso", ""),
                trigger="cutover",
            )
            self.audit_emitter(record)
            return record
        _check_transition(prior_status, STATUS_IN_PROGRESS)
        new_data = dict(data)
        new_data["status"] = STATUS_IN_PROGRESS
        new_data["cutover_iso"] = cutover_iso
        _check_time_invariants(
            new_data["cutover_iso"], new_data.get("signoff_iso", "")
        )
        _atomic_write_json(target, new_data)
        record = WelleAuditRecord(
            welle_number=welle_number,
            prior_status=prior_status,
            new_status=STATUS_IN_PROGRESS,
            cutover_iso=cutover_iso,
            signoff_iso=new_data.get("signoff_iso", ""),
            trigger="cutover",
        )
        self.audit_emitter(record)
        return record

    # -- Transition: in-progress -> signed-off (Sign-Off-Event) --

    def handle_sign_off_event(
        self,
        welle_number: int,
        signoff_iso: str,
        *,
        sign_off_marker_status: str,
        pre_auditor_decision: Optional[str] = None,
    ) -> WelleAuditRecord:
        """Apply the Sign-Off transition (plan-doc §2.2).

        Pre-conditions (refusal-to-write):

        * on-disk status MUST be ``in-progress``,
        * ``sign_off_marker_status`` MUST be ``"signed-off"`` (the
          companion ``state/welle-N-sign-off.json`` marker must
          already report signed-off),
        * for ``welle_number in {3, 7}``,
          ``pre_auditor_decision`` MUST be ``"designated"``.
        """
        _validate_welle_number(welle_number)
        _validate_iso_timestamp(signoff_iso, "signoff_iso")
        if sign_off_marker_status != STATUS_SIGNED_OFF:
            raise SignOffPreconditionError(
                f"sign-off-marker for welle-{welle_number} not "
                f"signed-off: got {sign_off_marker_status!r}"
            )
        if welle_number in PRE_AUDITOR_GUARDED_WELLEN:
            if pre_auditor_decision != "designated":
                raise PreAuditorGuardError(
                    f"welle-{welle_number} sign-off requires a "
                    f"designated pre-auditor (Henrik-cannot-self-"
                    f"sign-off); got pre_auditor_decision="
                    f"{pre_auditor_decision!r}"
                )
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        prior_status = data["status"]
        if prior_status == STATUS_SIGNED_OFF:
            # Idempotent no-op: sign-off already recorded.
            record = WelleAuditRecord(
                welle_number=welle_number,
                prior_status=prior_status,
                new_status=prior_status,
                cutover_iso=data.get("cutover_iso", ""),
                signoff_iso=data.get("signoff_iso", ""),
                trigger="sign-off",
            )
            self.audit_emitter(record)
            return record
        _check_transition(prior_status, STATUS_SIGNED_OFF)
        new_data = dict(data)
        new_data["status"] = STATUS_SIGNED_OFF
        new_data["signoff_iso"] = signoff_iso
        _check_time_invariants(
            new_data.get("cutover_iso", ""), new_data["signoff_iso"]
        )
        _atomic_write_json(target, new_data)
        record = WelleAuditRecord(
            welle_number=welle_number,
            prior_status=prior_status,
            new_status=STATUS_SIGNED_OFF,
            cutover_iso=new_data.get("cutover_iso", ""),
            signoff_iso=signoff_iso,
            trigger="sign-off",
        )
        self.audit_emitter(record)
        return record

    # -- Transition: Welle-2 Doppelbetrieb-Sealing sign-off (Tag-70 §2.3) --

    def handle_welle_2_sealing_event(
        self,
        signoff_iso: str,
        *,
        sign_off_marker_status: str,
        doppelbetrieb_sealed_marker_status: str,
    ) -> WelleAuditRecord:
        """Apply the Welle-2 Doppelbetrieb-Sealing sign-off (Tag-70 §2.3).

        Welle-2 closes the legacy↔new dual-write window (KW-24 Mi).
        The sign-off is structurally an in-progress -> signed-off
        transition with **two** marker preconditions:

        * the standard ``sign_off_marker_status == "signed-off"``
          companion marker (same as :meth:`handle_sign_off_event`),
        * the additional ``doppelbetrieb_sealed_marker_status ==
          "sealed"`` marker which confirms the dual-write window
          has been observed-closed by the operator (no legacy-side
          writes remain). Refused otherwise.

        Welle-2 is **not** in :data:`PRE_AUDITOR_GUARDED_WELLEN`, so
        no pre-auditor guard applies here. The audit-record carries
        ``trigger="sealing"`` to disambiguate from a vanilla Welle-2
        sign-off in the downstream audit-stream.
        """
        welle_number = 2
        _validate_iso_timestamp(signoff_iso, "signoff_iso")
        if sign_off_marker_status != STATUS_SIGNED_OFF:
            raise SignOffPreconditionError(
                f"sign-off-marker for welle-{welle_number} not "
                f"signed-off: got {sign_off_marker_status!r}"
            )
        if doppelbetrieb_sealed_marker_status != DOPPELBETRIEB_SEALED:
            raise DoppelbetriebSealingError(
                f"welle-{welle_number} Doppelbetrieb-Sealing sign-off "
                f"requires sealed-marker; got "
                f"doppelbetrieb_sealed_marker_status="
                f"{doppelbetrieb_sealed_marker_status!r}"
            )
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        prior_status = data["status"]
        if prior_status == STATUS_SIGNED_OFF:
            # Idempotent no-op: sealing-sign-off already recorded.
            record = WelleAuditRecord(
                welle_number=welle_number,
                prior_status=prior_status,
                new_status=prior_status,
                cutover_iso=data.get("cutover_iso", ""),
                signoff_iso=data.get("signoff_iso", ""),
                trigger="sealing",
            )
            self.audit_emitter(record)
            return record
        _check_transition(prior_status, STATUS_SIGNED_OFF)
        new_data = dict(data)
        new_data["status"] = STATUS_SIGNED_OFF
        new_data["signoff_iso"] = signoff_iso
        _check_time_invariants(
            new_data.get("cutover_iso", ""), new_data["signoff_iso"]
        )
        _atomic_write_json(target, new_data)
        record = WelleAuditRecord(
            welle_number=welle_number,
            prior_status=prior_status,
            new_status=STATUS_SIGNED_OFF,
            cutover_iso=new_data.get("cutover_iso", ""),
            signoff_iso=signoff_iso,
            trigger="sealing",
        )
        self.audit_emitter(record)
        return record

    # -- Transition: Welle-4 State-Backing sign-off (Tag-72 §2.5) --

    def handle_welle_4_signoff_event(
        self,
        signoff_iso: str,
        *,
        sign_off_marker_status: str,
        snapshot_restore_marker_status: str,
    ) -> WelleAuditRecord:
        """Apply the Welle-4 State-Backing sign-off (Tag-72 §2.5).

        Welle-4 is the State-Backing Welle (KW-25 Mo). The 10th pre-boot
        BackendDecision (``state_backing`` rust<->python switch,
        Tag-57-emit-order-pin) flips during this Welle. The sign-off
        is structurally an in-progress -> signed-off transition with
        **two** marker preconditions:

        * the standard ``sign_off_marker_status == "signed-off"``
          companion marker (same as :meth:`handle_sign_off_event`),
        * the additional ``snapshot_restore_marker_status ==
          "restored"`` marker which confirms the state-backing
          snapshot-restore-workflow (Tomas-Tag-56-Rollback-Workflow
          §J4) has been observed-complete by the operator (the new
          state-backing substrate has been re-hydrated from the
          pre-cutover snapshot and a parity-check against the legacy
          substrate has returned clean). Refused otherwise.

        Welle-4 is **not** in :data:`PRE_AUDITOR_GUARDED_WELLEN`, so
        no pre-auditor guard applies here. The audit-record carries
        ``trigger="snapshot-restore"`` to disambiguate from a vanilla
        Welle-4 sign-off in the downstream audit-stream and from the
        Welle-2 ``trigger="sealing"`` record.

        Idempotency: a double-fire after a successful Welle-4 sign-off
        returns an audit-record with ``prior_status == new_status ==
        "signed-off"`` and ``trigger="snapshot-restore"`` (no on-disk
        mutation). Mirrors the Welle-2 sealing idempotency path.

        Forensic note: the snapshot-restore-iso itself is not stored
        in the schema-pinned state-file (the schema-pin is unchanged
        per Tag-67); it is recoverable from the audit-stream via the
        ``trigger="snapshot-restore"`` record + ``signoff_iso``.
        """
        welle_number = 4
        _validate_iso_timestamp(signoff_iso, "signoff_iso")
        if sign_off_marker_status != STATUS_SIGNED_OFF:
            raise SignOffPreconditionError(
                f"sign-off-marker for welle-{welle_number} not "
                f"signed-off: got {sign_off_marker_status!r}"
            )
        if snapshot_restore_marker_status != SNAPSHOT_RESTORE_VERIFIED:
            raise SnapshotRestoreError(
                f"welle-{welle_number} State-Backing sign-off "
                f"requires snapshot-restore-marker; got "
                f"snapshot_restore_marker_status="
                f"{snapshot_restore_marker_status!r}"
            )
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        prior_status = data["status"]
        if prior_status == STATUS_SIGNED_OFF:
            # Idempotent no-op: state-backing sign-off already recorded.
            record = WelleAuditRecord(
                welle_number=welle_number,
                prior_status=prior_status,
                new_status=prior_status,
                cutover_iso=data.get("cutover_iso", ""),
                signoff_iso=data.get("signoff_iso", ""),
                trigger="snapshot-restore",
            )
            self.audit_emitter(record)
            return record
        _check_transition(prior_status, STATUS_SIGNED_OFF)
        new_data = dict(data)
        new_data["status"] = STATUS_SIGNED_OFF
        new_data["signoff_iso"] = signoff_iso
        _check_time_invariants(
            new_data.get("cutover_iso", ""), new_data["signoff_iso"]
        )
        _atomic_write_json(target, new_data)
        record = WelleAuditRecord(
            welle_number=welle_number,
            prior_status=prior_status,
            new_status=STATUS_SIGNED_OFF,
            cutover_iso=new_data.get("cutover_iso", ""),
            signoff_iso=signoff_iso,
            trigger="snapshot-restore",
        )
        self.audit_emitter(record)
        return record

    # -- Transition: ANY -> rolled-back (Tag-70 §2.4 Rollback-Writer) --

    def handle_rollback_event(
        self,
        welle_number: int,
        rollback_iso: str,
        *,
        rollback_marker_status: str,
    ) -> WelleAuditRecord:
        """Apply a rollback transition (Tag-70 §2.4 Rollback-Writer).

        Allowed prior states (plan-doc §3.1)::

            pending      -> rolled-back   (pre-cutover-rollback, rare)
            in-progress  -> rolled-back   (mid-Welle rollback)
            signed-off   -> rolled-back   (post-sign-off rollback)

        Refusal-to-write preconditions:

        * ``rollback_marker_status`` MUST equal
          :data:`ROLLBACK_MARKER_AUTHORIZED` ("rollback-authorized");
          any other value raises :class:`RollbackAuthorityError`.
          This guards against a stale or accidental rollback-event
          (the rollback-marker file is operator-curated).
        * the on-disk state-file MUST be shape-valid (same as the
          other handlers).
        * if the on-disk status is already ``rolled-back``, the call
          is a no-op (idempotency; rolled-back is terminal so this
          is the only no-op path for rollback).

        The handler writes the rollback by updating ``status`` to
        :data:`STATUS_ROLLED_BACK`. ``cutover_iso`` and ``signoff_iso``
        are preserved (forensic: the rolled-back Welle still has a
        cutover-iso for audit-trail purposes; rollback-iso itself
        is captured in the audit-record, not in the state-file
        schema -- the schema is pinned).

        Note: rollback is a unidirectional terminal transition --
        the plan-doc §3.2 prohibition on ``rolled-back -> *`` is
        enforced by :func:`_check_transition`.
        """
        _validate_welle_number(welle_number)
        _validate_iso_timestamp(rollback_iso, "rollback_iso")
        if rollback_marker_status != ROLLBACK_MARKER_AUTHORIZED:
            raise RollbackAuthorityError(
                f"rollback for welle-{welle_number} requires "
                f"rollback_marker_status="
                f"{ROLLBACK_MARKER_AUTHORIZED!r}; got "
                f"{rollback_marker_status!r}"
            )
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        prior_status = data["status"]
        if prior_status == STATUS_ROLLED_BACK:
            # Idempotent no-op: rollback already recorded (terminal).
            record = WelleAuditRecord(
                welle_number=welle_number,
                prior_status=prior_status,
                new_status=prior_status,
                cutover_iso=data.get("cutover_iso", ""),
                signoff_iso=data.get("signoff_iso", ""),
                trigger="rollback",
            )
            self.audit_emitter(record)
            return record
        _check_transition(prior_status, STATUS_ROLLED_BACK)
        new_data = dict(data)
        new_data["status"] = STATUS_ROLLED_BACK
        # Time-invariants on cutover_iso/signoff_iso continue to hold
        # because we preserve them (rollback does not modify them).
        _check_time_invariants(
            new_data.get("cutover_iso", ""), new_data.get("signoff_iso", "")
        )
        _atomic_write_json(target, new_data)
        record = WelleAuditRecord(
            welle_number=welle_number,
            prior_status=prior_status,
            new_status=STATUS_ROLLED_BACK,
            cutover_iso=new_data.get("cutover_iso", ""),
            signoff_iso=new_data.get("signoff_iso", ""),
            trigger="rollback",
        )
        self.audit_emitter(record)
        return record

    # -- Read-only convenience: current status snapshot. --

    def current_status(self, welle_number: int) -> str:
        """Return the on-disk status of ``state/welle-N.json``."""
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        return data["status"]

    def snapshot(self, welle_number: int) -> Dict[str, Any]:
        """Return a deep-copy snapshot of the rollup-file."""
        target = _state_file_path(self.state_dir, welle_number)
        data = _load_state_file(target)
        _enforce_shape(data, target)
        return json.loads(json.dumps(data))


# ---------------------------------------------------------------------------
# Module-level public API summary (for static-tooling auditors).
# ---------------------------------------------------------------------------

__all__ = [
    "ALLOWED_STATUSES",
    "ALLOWED_TRANSITIONS",
    "AuditRecordEmitter",
    "DOPPELBETRIEB_SEALED",
    "DOPPELBETRIEB_SEALED_WELLEN",
    "DoppelbetriebSealingError",
    "InvalidStatusTransitionError",
    "InvalidWelleNumberError",
    "ISO_TS_NONEMPTY_RE",
    "PHASE_LITERAL",
    "PRE_AUDITOR_GUARDED_WELLEN",
    "PathTraversalError",
    "PreAuditorGuardError",
    "ROLLBACK_MARKER_AUTHORIZED",
    "RollbackAuthorityError",
    "SCHEMA_VERSION_PIN",
    "SNAPSHOT_RESTORE_GUARDED_WELLEN",
    "SNAPSHOT_RESTORE_VERIFIED",
    "STATUS_IN_PROGRESS",
    "STATUS_PENDING",
    "STATUS_ROLLED_BACK",
    "STATUS_SIGNED_OFF",
    "SignOffPreconditionError",
    "SnapshotRestoreError",
    "StateFileShapeError",
    "TimeInvariantViolationError",
    "VALID_KW_ANCHORS",
    "VALID_WELLE_NUMBERS",
    "WelleAuditRecord",
    "WelleProducerError",
    "WelleStateProducer",
    "audit_record_emitter_from_bridge_writer",
]
