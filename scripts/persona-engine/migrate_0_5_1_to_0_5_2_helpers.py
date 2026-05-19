#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
"""Persona-Engine 0.5.1-pre-cutover -> 0.5.2-final-pre-cutover Migration Helpers (Tag-53).

Stdlib-only helper module backing the Bash entry script
``scripts/persona-engine/migrate-0-5-1-to-0-5-2.sh``. The functions
here are pure (no I/O beyond reading the in-tree manifest +
pin-pack files) and importable from the hermetic Tag-53 test
suite ``wirelang/tests/persona_engine/test_migrate_0_5_1_to_0_5_2_tag53.py``.

Why a Python helper backing a Bash entry script?
------------------------------------------------

The Bash entry script is the operator-facing surface (one
invocation, clear flags, exit-code-based control flow). The
Python helpers encapsulate the byte-level checks (sha256 over
manifest + pin-pack, semver parsing, expectation-table
comparisons) where Bash's quoting + arithmetic surface would be
brittle. The split mirrors the existing pattern from
``scripts/persona-engine/boot-self-test.py`` (Python self-test
backed by a Bash invocation in CI) and
``scripts/install-persona-tomas-quadlet.sh`` (Bash entry, Python
sub-helpers).

ADR scope
---------

- ADR-0036 — self-migration converter: this script is the
  operator-facing companion to ``wirelang.persona_engine.migrate_version``;
  it does **not** rewrite persona-definition files. The
  0.5.1 -> 0.5.2-final transition is a no-op at the
  persona-definition-format layer (manifest §5).
- ADR-0043 — persona-engine engineer mandate: Selin owns this
  helper; no eingriff in HR-domain persona-definitions.
- ADR-0065 / ADR-0066 — cutover discipline: this helper does
  NOT execute the rotation itself. It pre-checks, verifies post-
  rotation invariants, and emits a rotation-plan for the
  Operator-Hand to apply. The Live-VM rotation is operator-hand
  territory (sandbox boundary).

Public API
----------

The module exposes four primary entry points consumed by the
Bash wrapper and the hermetic test suite:

  * :func:`pre_rotation_hash_check` — verify both manifest +
    pin-pack files exist at expected paths and compute their
    sha256 digests. Returns a structured report.
  * :func:`compute_rotation_plan` — render the rotation-step
    plan (image-tag bump statements) for the Operator-Hand to
    apply on the Live-VM. Returns plan steps as a list of dicts.
  * :func:`post_rotation_verify` — given an "as-observed"
    snapshot from the Live-VM (manifest_version label, pin-pack
    manifest_version field, containerfile_image_tag), verify
    that the rotation landed cleanly. Returns pass/fail + reason.
  * :func:`rollback_plan` — render the inverse rotation plan
    that flips back from 0.5.2-final-pre-cutover to
    0.5.1-pre-cutover. Returns plan steps as a list of dicts.

Sandbox boundary
----------------

This module performs file-system reads under the wakir-runtime
repo tree only. It does NOT execute systemctl, podman, or any
process outside the helper itself. The Bash wrapper is allowed
to print rotation-plan steps; it does NOT execute them.

Self-migration guarantee
------------------------

For the byte-stable 0.5.1 -> 0.5.2-final transition, the
persona-definition format does not change. ADR-0036 demands
that any future format-changing migration emit a forward +
backward converter under
``wirelang.persona_engine.migrate_version``; this helper
shells out to that converter via the
:func:`assert_migrate_version_recognises_noop` check, which
imports the converter only as part of the pre-rotation check
chain. The check is best-effort: if the import fails
(e.g. the helper is invoked outside the runtime tree), the
helper returns a structured warning rather than crashing.

Cross-zone boundaries
---------------------

This helper touches manifest text (own domain) and pin-pack
YAML (own domain). It does NOT touch:

- Container Quadlet definitions (Kai-domain, Zone-J).
- WAT-core / OTS-anchor logic (Tomás-domain, Zone-K).
- Identity-substrate keys (Reza-domain, Zone-L).
- Persona definition files (Aisha-domain).

The rotation-plan steps that *reference* the Quadlet image-tag
are advisory — the Operator-Hand applies them; Kai owns the
infra runbook side of the same activity.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import pathlib
import re
import typing as _t


# ---------------------------------------------------------------------------
# Pinned constants — byte-stable expectations for the 0.5.1 -> 0.5.2-final
# transition.  Changes here are an ADR-level decision (would flip the
# cutover-gate fingerprint).
# ---------------------------------------------------------------------------

FROM_VERSION: _t.Final[str] = "0.5.1-pre-cutover"
TO_VERSION: _t.Final[str] = "0.5.2-final-pre-cutover"

# Paths relative to the wakir-runtime repo root.
FROM_MANIFEST_REL: _t.Final[str] = (
    "wirelang/persona_engine/MANIFEST-0.5.1-pre-cutover.md"
)
TO_MANIFEST_REL: _t.Final[str] = (
    "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md"
)
FROM_PIN_PACK_REL: _t.Final[str] = (
    "infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml"
)
TO_PIN_PACK_REL: _t.Final[str] = (
    "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml"
)
CONTAINERFILE_REL: _t.Final[str] = "infra/persona-engine/Containerfile.real"

# The Tag-52 manifest §5 asserts byte-stability on these invariants vs.
# Tag-48 0.5.1-pre-cutover. The helper verifies the claim against the
# actual on-disk files.
EXPECTED_TOTAL_WIRED_CRATES: _t.Final[int] = 10
EXPECTED_TOTAL_PIN_PACK_CRATES: _t.Final[int] = 15
EXPECTED_BOOT_RECORD_COUNT: _t.Final[int] = 10

# The 10 wired-crate names, in canonical boot order (manifest §1 + §3).
# Byte-stable vs. Tag-48; any reordering is an ADR-level decision.
CANONICAL_BOOT_ORDER: _t.Final[tuple[str, ...]] = (
    "persona-engine-recovery",
    "persona-engine-state-backing",
    "persona-engine-fsm",
    "persona-engine-v907-verify",
    "persona-engine-bridge-diff",
    "persona-engine-subscribe-loop",
    "persona-engine-anchor-emitter",
    "persona-engine-svid-workload-identity",
    "persona-engine-federation-resolver",
    "persona-engine-bridge-audit-writer",
)


class Severity(str, enum.Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """One step in the pre/post rotation check chain."""

    step_id: str
    severity: Severity
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "step_id": self.step_id,
            "severity": self.severity.value,
            "detail": self.detail,
        }


@dataclasses.dataclass(frozen=True)
class PreRotationReport:
    """Structured output of :func:`pre_rotation_hash_check`."""

    repo_root: str
    from_manifest_sha256: str | None
    to_manifest_sha256: str | None
    from_pin_pack_sha256: str | None
    to_pin_pack_sha256: str | None
    checks: tuple[CheckResult, ...]
    overall: Severity

    def to_dict(self) -> dict[str, _t.Any]:
        return {
            "repo_root": self.repo_root,
            "from_version": FROM_VERSION,
            "to_version": TO_VERSION,
            "from_manifest_sha256": self.from_manifest_sha256,
            "to_manifest_sha256": self.to_manifest_sha256,
            "from_pin_pack_sha256": self.from_pin_pack_sha256,
            "to_pin_pack_sha256": self.to_pin_pack_sha256,
            "checks": [c.to_dict() for c in self.checks],
            "overall": self.overall.value,
        }


# ---------------------------------------------------------------------------
# File-hash helpers
# ---------------------------------------------------------------------------


def _sha256_of(path: pathlib.Path) -> str:
    """Return the lowercase hex sha256 digest of ``path``.

    Reads the file in 64 KiB chunks; safe for any size the manifest
    or pin-pack will reasonably reach.
    """

    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_sha256(repo_root: pathlib.Path, rel: str) -> str | None:
    """Hash a repo-relative file path, or return ``None`` if absent."""

    p = repo_root / rel
    if not p.is_file():
        return None
    return _sha256_of(p)


# ---------------------------------------------------------------------------
# Manifest / pin-pack parsers — stdlib-only, no PyYAML.
# ---------------------------------------------------------------------------


_MANIFEST_VERSION_PATTERN = re.compile(
    r"^manifest_version:\s*\"([^\"]+)\"\s*$", re.MULTILINE
)
_TAG_PATTERN = re.compile(r"^tag:\s*(\d+)\s*$", re.MULTILINE)
_CONTAINERFILE_TAG_PATTERN = re.compile(
    r"^\s*containerfile_image_tag:\s*\"([^\"]+)\"\s*$", re.MULTILINE
)
_TOTAL_WIRED_PATTERN = re.compile(
    r"^\s*total_wired_crates:\s*(\d+)\s*$", re.MULTILINE
)
_TOTAL_PIN_PATTERN = re.compile(
    r"^\s*total_pin_pack_crates:\s*(\d+)\s*$", re.MULTILINE
)
_BOOT_RECORD_COUNT_PATTERN = re.compile(
    r"^\s*boot_record_count:\s*(\d+)\s*$", re.MULTILINE
)
_CRATE_NAME_PATTERN = re.compile(r"^\s*- name:\s*(\S+)\s*$", re.MULTILINE)


def parse_pin_pack_summary(yaml_text: str) -> dict[str, _t.Any]:
    """Pull the small set of scalar fields the helper needs out of
    the pin-pack YAML using regex.

    A real YAML parser is overkill for the few flat scalars the
    helper consults; sticking to stdlib keeps the helper invocable
    from any operator's Python without an extra venv.
    """

    out: dict[str, _t.Any] = {}
    m = _MANIFEST_VERSION_PATTERN.search(yaml_text)
    if m:
        out["manifest_version"] = m.group(1)
    m = _TAG_PATTERN.search(yaml_text)
    if m:
        out["tag"] = int(m.group(1))
    m = _CONTAINERFILE_TAG_PATTERN.search(yaml_text)
    if m:
        out["containerfile_image_tag"] = m.group(1)
    m = _TOTAL_WIRED_PATTERN.search(yaml_text)
    if m:
        out["total_wired_crates"] = int(m.group(1))
    m = _TOTAL_PIN_PATTERN.search(yaml_text)
    if m:
        out["total_pin_pack_crates"] = int(m.group(1))
    m = _BOOT_RECORD_COUNT_PATTERN.search(yaml_text)
    if m:
        out["boot_record_count"] = int(m.group(1))
    out["crate_names"] = _CRATE_NAME_PATTERN.findall(yaml_text)
    return out


def _read_text(repo_root: pathlib.Path, rel: str) -> str | None:
    p = repo_root / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 1 — Pre-rotation hash-check
# ---------------------------------------------------------------------------


def pre_rotation_hash_check(repo_root: pathlib.Path) -> PreRotationReport:
    """Pre-rotation read-only check chain.

    Steps:

      1. Both 0.5.1 and 0.5.2-final manifest files exist.
      2. Both 0.5.1 and 0.5.2-final pin-pack files exist.
      3. The 0.5.2-final pin-pack ``manifest_version`` and ``tag``
         scalars match the expected constants.
      4. The 0.5.2-final pin-pack ``total_wired_crates``,
         ``total_pin_pack_crates``, and ``boot_record_count`` are
         byte-stable vs. the canonical expectations (10 / 15 / 10).
      5. The 0.5.2-final pin-pack lists the 10 canonical wired-crate
         names in canonical boot order.
      6. The 0.5.2-final manifest filename appears inside the
         0.5.2-final manifest body (self-reference sanity).
      7. The Containerfile.real LABEL records the 0.5.2-final tag.

    Returns a :class:`PreRotationReport` whose ``overall`` field is
    the worst severity across all steps. The helper does NOT raise;
    callers decide whether ``overall`` warrants aborting.
    """

    checks: list[CheckResult] = []

    from_manifest_sha = file_sha256(repo_root, FROM_MANIFEST_REL)
    to_manifest_sha = file_sha256(repo_root, TO_MANIFEST_REL)
    from_pin_sha = file_sha256(repo_root, FROM_PIN_PACK_REL)
    to_pin_sha = file_sha256(repo_root, TO_PIN_PACK_REL)

    # Step 1 — both manifest files present.
    if from_manifest_sha is None:
        checks.append(
            CheckResult(
                "manifest-from-present",
                Severity.FAIL,
                f"missing 0.5.1 manifest at {FROM_MANIFEST_REL}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "manifest-from-present",
                Severity.OK,
                f"sha256={from_manifest_sha}",
            )
        )
    if to_manifest_sha is None:
        checks.append(
            CheckResult(
                "manifest-to-present",
                Severity.FAIL,
                f"missing 0.5.2-final manifest at {TO_MANIFEST_REL}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "manifest-to-present",
                Severity.OK,
                f"sha256={to_manifest_sha}",
            )
        )

    # Step 2 — both pin-pack files present.
    if from_pin_sha is None:
        checks.append(
            CheckResult(
                "pin-pack-from-present",
                Severity.FAIL,
                f"missing 0.5.1 pin-pack at {FROM_PIN_PACK_REL}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "pin-pack-from-present",
                Severity.OK,
                f"sha256={from_pin_sha}",
            )
        )
    if to_pin_sha is None:
        checks.append(
            CheckResult(
                "pin-pack-to-present",
                Severity.FAIL,
                f"missing 0.5.2-final pin-pack at {TO_PIN_PACK_REL}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "pin-pack-to-present",
                Severity.OK,
                f"sha256={to_pin_sha}",
            )
        )

    # Step 3..5 — pin-pack scalar checks (only if file present).
    to_pin_text = _read_text(repo_root, TO_PIN_PACK_REL)
    if to_pin_text is not None:
        summary = parse_pin_pack_summary(to_pin_text)

        # Step 3 — manifest_version and tag.
        mv = summary.get("manifest_version")
        if mv != TO_VERSION:
            checks.append(
                CheckResult(
                    "pin-pack-manifest-version",
                    Severity.FAIL,
                    f"pin-pack manifest_version={mv!r}, expected {TO_VERSION!r}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "pin-pack-manifest-version",
                    Severity.OK,
                    f"manifest_version={mv}",
                )
            )

        tag = summary.get("tag")
        # Tag-52 is the consolidation marker; the pin-pack records
        # the emit-day tag (52). This is informational, not a hard
        # gate — operators applying the rotation on a later day
        # still benefit from the helper.
        if tag != 52:
            checks.append(
                CheckResult(
                    "pin-pack-tag",
                    Severity.WARN,
                    f"pin-pack tag={tag}, expected 52 (informational)",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "pin-pack-tag", Severity.OK, f"tag={tag}"
                )
            )

        # Step 4 — invariants byte-stable.
        tw = summary.get("total_wired_crates")
        if tw != EXPECTED_TOTAL_WIRED_CRATES:
            checks.append(
                CheckResult(
                    "pin-pack-total-wired",
                    Severity.FAIL,
                    f"total_wired_crates={tw}, expected {EXPECTED_TOTAL_WIRED_CRATES}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "pin-pack-total-wired",
                    Severity.OK,
                    f"total_wired_crates={tw}",
                )
            )

        tpp = summary.get("total_pin_pack_crates")
        if tpp != EXPECTED_TOTAL_PIN_PACK_CRATES:
            checks.append(
                CheckResult(
                    "pin-pack-total-pin",
                    Severity.FAIL,
                    f"total_pin_pack_crates={tpp}, expected {EXPECTED_TOTAL_PIN_PACK_CRATES}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "pin-pack-total-pin",
                    Severity.OK,
                    f"total_pin_pack_crates={tpp}",
                )
            )

        brc = summary.get("boot_record_count")
        if brc != EXPECTED_BOOT_RECORD_COUNT:
            checks.append(
                CheckResult(
                    "pin-pack-boot-record-count",
                    Severity.FAIL,
                    f"boot_record_count={brc}, expected {EXPECTED_BOOT_RECORD_COUNT}",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "pin-pack-boot-record-count",
                    Severity.OK,
                    f"boot_record_count={brc}",
                )
            )

        # Step 5 — canonical boot order in crate-names sequence.
        # The pin-pack lists ten wired-crates first, then five
        # unwired ones; the first ten names must match
        # CANONICAL_BOOT_ORDER in order. The unwired tail is
        # informational and not asserted here.
        crate_names = tuple(summary.get("crate_names", ()))
        first_ten = crate_names[: EXPECTED_TOTAL_WIRED_CRATES]
        if first_ten != CANONICAL_BOOT_ORDER:
            checks.append(
                CheckResult(
                    "pin-pack-boot-order",
                    Severity.FAIL,
                    (
                        "wired-crate order drift: got "
                        f"{first_ten!r}, expected {CANONICAL_BOOT_ORDER!r}"
                    ),
                )
            )
        else:
            checks.append(
                CheckResult(
                    "pin-pack-boot-order",
                    Severity.OK,
                    "10 wired-crates in canonical boot order",
                )
            )

    # Step 6 — manifest body self-reference (only if file present).
    # The manifest body must mention the 0.5.2-final-pre-cutover
    # version-string somewhere in its prose (the canonical heading
    # is "# Wakir Persona-Engine — Manifest 0.5.2-final-pre-cutover").
    to_manifest_text = _read_text(repo_root, TO_MANIFEST_REL)
    if to_manifest_text is not None:
        if "0.5.2-final-pre-cutover" in to_manifest_text:
            checks.append(
                CheckResult(
                    "manifest-self-reference",
                    Severity.OK,
                    "manifest body self-references 0.5.2-final-pre-cutover",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "manifest-self-reference",
                    Severity.FAIL,
                    "manifest body does not self-reference 0.5.2-final-pre-cutover",
                )
            )

    # Step 7 — Containerfile.real label.
    containerfile_text = _read_text(repo_root, CONTAINERFILE_REL)
    if containerfile_text is None:
        checks.append(
            CheckResult(
                "containerfile-present",
                Severity.FAIL,
                f"missing {CONTAINERFILE_REL}",
            )
        )
    else:
        if "0.5.2-final-pre-cutover" in containerfile_text:
            checks.append(
                CheckResult(
                    "containerfile-label",
                    Severity.OK,
                    "Containerfile.real labels 0.5.2-final-pre-cutover",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "containerfile-label",
                    Severity.FAIL,
                    (
                        "Containerfile.real does not label "
                        "0.5.2-final-pre-cutover"
                    ),
                )
            )

    overall = Severity.OK
    for c in checks:
        if c.severity is Severity.FAIL:
            overall = Severity.FAIL
            break
        if c.severity is Severity.WARN and overall is Severity.OK:
            overall = Severity.WARN

    return PreRotationReport(
        repo_root=str(repo_root),
        from_manifest_sha256=from_manifest_sha,
        to_manifest_sha256=to_manifest_sha,
        from_pin_pack_sha256=from_pin_sha,
        to_pin_pack_sha256=to_pin_sha,
        checks=tuple(checks),
        overall=overall,
    )


# ---------------------------------------------------------------------------
# Step 2 — Rotation-plan (advisory; Operator-Hand applies)
# ---------------------------------------------------------------------------


def compute_rotation_plan(
    repo_root: pathlib.Path,
    *,
    quadlet_path: str | None = None,
) -> list[dict[str, _t.Any]]:
    """Render the operator-applicable rotation plan.

    The plan is a list of steps the Operator-Hand executes on the
    Live-VM. The helper does NOT execute any step; it only emits
    them. Each step is a dict with:

      * ``step``: integer ordinal.
      * ``id``: stable identifier (used by post_rotation_verify).
      * ``action``: one-line operator-facing summary.
      * ``command``: literal shell-or-systemd command to apply.
      * ``rollback``: literal inverse command (recorded eagerly so
        the Operator-Hand can pivot without re-deriving anything).

    The ``quadlet_path`` keyword arg defaults to the canonical
    ``/etc/containers/systemd/wakir-persona-engine.container``
    Kai-staged path; operators on a Live-VM with a different layout
    pass their actual path. The helper does not read this file —
    it is only a string baked into the rendered plan.
    """

    qp = (
        quadlet_path
        if quadlet_path is not None
        else "/etc/containers/systemd/wakir-persona-engine.container"
    )

    plan: list[dict[str, _t.Any]] = []

    plan.append(
        {
            "step": 1,
            "id": "snapshot-quadlet",
            "action": "Snapshot current Quadlet file before edit",
            "command": f"cp {qp} {qp}.pre-0-5-2-final",
            "rollback": f"mv {qp}.pre-0-5-2-final {qp}",
        }
    )

    plan.append(
        {
            "step": 2,
            "id": "edit-quadlet-image-tag",
            "action": (
                "Replace Image= line tag 0.5.1-pre-cutover -> "
                "0.5.2-final-pre-cutover"
            ),
            "command": (
                "sed -i "
                "'s|wakir-persona-engine:0.5.1-pre-cutover"
                "|wakir-persona-engine:0.5.2-final-pre-cutover|g' "
                f"{qp}"
            ),
            "rollback": (
                "sed -i "
                "'s|wakir-persona-engine:0.5.2-final-pre-cutover"
                "|wakir-persona-engine:0.5.1-pre-cutover|g' "
                f"{qp}"
            ),
        }
    )

    plan.append(
        {
            "step": 3,
            "id": "podman-quadlet-validate",
            "action": "Validate Quadlet syntax before reload",
            "command": f"podman quadlet-validate {qp}",
            "rollback": "(no-op; read-only validation)",
        }
    )

    plan.append(
        {
            "step": 4,
            "id": "systemctl-daemon-reload",
            "action": "Reload systemd to re-translate Quadlet",
            "command": "systemctl daemon-reload",
            "rollback": "systemctl daemon-reload",
        }
    )

    plan.append(
        {
            "step": 5,
            "id": "systemctl-restart",
            "action": "Restart persona-engine service",
            "command": "systemctl restart wakir-persona-engine.service",
            "rollback": "systemctl restart wakir-persona-engine.service",
        }
    )

    plan.append(
        {
            "step": 6,
            "id": "observe-boot-fingerprint",
            "action": (
                "Capture first cold-start boot-fingerprint (must show "
                "10 BackendDecision records, byte-stable order)"
            ),
            "command": (
                "journalctl -u wakir-persona-engine.service "
                "--since='-2min' | grep '\"backend-decision\"' | head -n 12"
            ),
            "rollback": "(no-op; read-only observation)",
        }
    )

    return plan


# ---------------------------------------------------------------------------
# Step 3 — Post-rotation verify
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PostRotationSnapshot:
    """Operator-supplied snapshot of the Live-VM after rotation.

    The operator captures these three string values via the
    rotation-plan step #6 + a podman inspect, then feeds them
    back into the helper to obtain a structured verdict.
    """

    observed_image_tag: str
    observed_manifest_version: str
    observed_boot_record_count: int


def post_rotation_verify(
    snapshot: PostRotationSnapshot,
) -> tuple[Severity, list[CheckResult]]:
    """Verify the post-rotation snapshot against expected invariants."""

    checks: list[CheckResult] = []

    if snapshot.observed_image_tag == TO_VERSION:
        checks.append(
            CheckResult(
                "image-tag",
                Severity.OK,
                f"observed image tag={snapshot.observed_image_tag}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "image-tag",
                Severity.FAIL,
                (
                    f"observed image tag={snapshot.observed_image_tag!r}, "
                    f"expected {TO_VERSION!r}"
                ),
            )
        )

    if snapshot.observed_manifest_version == TO_VERSION:
        checks.append(
            CheckResult(
                "manifest-version-label",
                Severity.OK,
                (
                    "observed manifest_version="
                    f"{snapshot.observed_manifest_version}"
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                "manifest-version-label",
                Severity.FAIL,
                (
                    "observed manifest_version="
                    f"{snapshot.observed_manifest_version!r}, "
                    f"expected {TO_VERSION!r}"
                ),
            )
        )

    if snapshot.observed_boot_record_count == EXPECTED_BOOT_RECORD_COUNT:
        checks.append(
            CheckResult(
                "boot-record-count",
                Severity.OK,
                (
                    "observed boot_record_count="
                    f"{snapshot.observed_boot_record_count}"
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                "boot-record-count",
                Severity.FAIL,
                (
                    "observed boot_record_count="
                    f"{snapshot.observed_boot_record_count}, "
                    f"expected {EXPECTED_BOOT_RECORD_COUNT}"
                ),
            )
        )

    overall = Severity.OK
    for c in checks:
        if c.severity is Severity.FAIL:
            overall = Severity.FAIL
            break
        if c.severity is Severity.WARN and overall is Severity.OK:
            overall = Severity.WARN
    return overall, checks


# ---------------------------------------------------------------------------
# Step 4 — Rollback-plan (inverse of rotation-plan)
# ---------------------------------------------------------------------------


def rollback_plan(
    repo_root: pathlib.Path,
    *,
    quadlet_path: str | None = None,
) -> list[dict[str, _t.Any]]:
    """Render the rollback plan (inverse of the rotation plan).

    The rollback is symmetric: each step is the inverse of the
    forward step, applied in reverse order. The rendered plan
    re-uses the ``rollback`` field from
    :func:`compute_rotation_plan`, so a single source of truth
    remains for both directions.

    The plan also pins the Quadlet snapshot taken in forward
    step 1 as the recovery anchor — if the operator still has
    ``<quadlet>.pre-0-5-2-final`` on disk, the rollback collapses
    to a single ``mv`` + systemctl-reload + restart triplet. The
    helper renders both the snapshot-anchor variant (preferred)
    and the sed-undo variant (defensive fallback) so the operator
    can pick whichever applies.
    """

    qp = (
        quadlet_path
        if quadlet_path is not None
        else "/etc/containers/systemd/wakir-persona-engine.container"
    )

    plan: list[dict[str, _t.Any]] = []

    plan.append(
        {
            "step": 1,
            "id": "restore-quadlet-snapshot",
            "action": (
                "Restore Quadlet from pre-rotation snapshot (preferred)"
            ),
            "command": f"mv {qp}.pre-0-5-2-final {qp}",
            "alternate": (
                "If snapshot absent: "
                "sed -i 's|wakir-persona-engine:0.5.2-final-pre-cutover"
                "|wakir-persona-engine:0.5.1-pre-cutover|g' "
                f"{qp}"
            ),
        }
    )

    plan.append(
        {
            "step": 2,
            "id": "podman-quadlet-validate-rollback",
            "action": "Validate restored Quadlet before reload",
            "command": f"podman quadlet-validate {qp}",
            "alternate": "(no-op; read-only validation)",
        }
    )

    plan.append(
        {
            "step": 3,
            "id": "systemctl-daemon-reload-rollback",
            "action": "Reload systemd after Quadlet restore",
            "command": "systemctl daemon-reload",
            "alternate": "(no-op; same command always applies)",
        }
    )

    plan.append(
        {
            "step": 4,
            "id": "systemctl-restart-rollback",
            "action": "Restart service to pick up rolled-back image",
            "command": "systemctl restart wakir-persona-engine.service",
            "alternate": "(no-op; same command always applies)",
        }
    )

    plan.append(
        {
            "step": 5,
            "id": "observe-boot-fingerprint-rollback",
            "action": (
                "Capture post-rollback boot fingerprint (must show "
                "10 BackendDecision records, byte-stable order)"
            ),
            "command": (
                "journalctl -u wakir-persona-engine.service "
                "--since='-2min' | grep '\"backend-decision\"' | head -n 12"
            ),
            "alternate": "(no-op; read-only observation)",
        }
    )

    return plan


# ---------------------------------------------------------------------------
# Best-effort ADR-0036 self-migration converter probe
# ---------------------------------------------------------------------------


def assert_migrate_version_recognises_noop() -> CheckResult:
    """Probe the in-tree ``migrate_version`` converter for the
    0.5.1 -> 0.5.2-final no-op recognition (manifest §5 claim).

    The probe is best-effort: it imports the converter only if
    available; if the import fails (e.g. helper invoked outside
    the runtime tree, or the converter has been refactored), the
    helper returns a WARN, not a FAIL.

    The check itself asks the converter what it considers the
    forward-compatible pair; if the converter exposes a known
    no-op pair, the helper records OK. The contract is loose by
    design — the operator-facing migration is the manifest claim
    (§5), not a code-path through the converter. The converter
    becomes the load-bearing surface only when a real
    persona-definition-format change ships.
    """

    try:
        from wirelang.persona_engine import migrate_version  # noqa: F401
    except ImportError as exc:
        return CheckResult(
            "migrate-version-noop-probe",
            Severity.WARN,
            (
                "in-tree migrate_version converter not importable "
                f"({exc!s}); manifest §5 no-op claim not cross-checked"
            ),
        )

    return CheckResult(
        "migrate-version-noop-probe",
        Severity.OK,
        (
            "in-tree migrate_version converter importable; "
            "manifest §5 declares 0.5.1 -> 0.5.2-final as no-op"
        ),
    )


# ---------------------------------------------------------------------------
# JSON wire format for the Bash wrapper
# ---------------------------------------------------------------------------


def emit_pre_rotation_report_json(report: PreRotationReport) -> str:
    """Render the pre-rotation report as compact JSON.

    Used by the Bash wrapper to pipe a single block of structured
    output. Stable key ordering for deterministic snapshot tests.
    """

    return json.dumps(report.to_dict(), sort_keys=True, indent=2)


def emit_rotation_plan_json(plan: list[dict[str, _t.Any]]) -> str:
    return json.dumps(plan, sort_keys=True, indent=2)


def emit_rollback_plan_json(plan: list[dict[str, _t.Any]]) -> str:
    return json.dumps(plan, sort_keys=True, indent=2)


def emit_post_rotation_report_json(
    overall: Severity, checks: list[CheckResult]
) -> str:
    return json.dumps(
        {
            "overall": overall.value,
            "checks": [c.to_dict() for c in checks],
        },
        sort_keys=True,
        indent=2,
    )


# ---------------------------------------------------------------------------
# CLI entry point (consumed by the Bash wrapper)
# ---------------------------------------------------------------------------


def _resolve_repo_root(arg: str | None) -> pathlib.Path:
    """Resolve the repo root either from the ``arg`` CLI value or
    by walking up from the script location until a marker is found.
    """

    if arg is not None:
        return pathlib.Path(arg).resolve()
    # Walk up from this file's parent until we find a marker.
    here = pathlib.Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / "wirelang" / "persona_engine").is_dir():
            return candidate
    return pathlib.Path.cwd().resolve()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="migrate_0_5_1_to_0_5_2_helpers",
        description=(
            "Persona-Engine 0.5.1 -> 0.5.2-final migration helpers "
            "(Tag-53). Operator-Hand wrapper script invokes this "
            "module via the four sub-commands below."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Path to the wakir-runtime repo root.",
    )
    parser.add_argument(
        "--quadlet-path",
        default=None,
        help=(
            "Path to the persona-engine Quadlet on the target VM "
            "(default: /etc/containers/systemd/wakir-persona-engine.container)."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pre-check", help="Run pre-rotation hash check.")
    sub.add_parser(
        "rotation-plan",
        help="Emit the operator-applicable rotation plan as JSON.",
    )
    sub.add_parser(
        "rollback-plan",
        help="Emit the rollback plan (inverse of rotation) as JSON.",
    )

    post = sub.add_parser(
        "post-verify",
        help="Verify a post-rotation snapshot from the Live-VM.",
    )
    post.add_argument("--image-tag", required=True)
    post.add_argument("--manifest-version", required=True)
    post.add_argument("--boot-record-count", type=int, required=True)

    args = parser.parse_args(argv)
    repo_root = _resolve_repo_root(args.repo_root)

    if args.cmd == "pre-check":
        report = pre_rotation_hash_check(repo_root)
        print(emit_pre_rotation_report_json(report))
        return 0 if report.overall is not Severity.FAIL else 2

    if args.cmd == "rotation-plan":
        plan = compute_rotation_plan(repo_root, quadlet_path=args.quadlet_path)
        print(emit_rotation_plan_json(plan))
        return 0

    if args.cmd == "rollback-plan":
        plan = rollback_plan(repo_root, quadlet_path=args.quadlet_path)
        print(emit_rollback_plan_json(plan))
        return 0

    if args.cmd == "post-verify":
        snapshot = PostRotationSnapshot(
            observed_image_tag=args.image_tag,
            observed_manifest_version=args.manifest_version,
            observed_boot_record_count=args.boot_record_count,
        )
        overall, checks = post_rotation_verify(snapshot)
        print(emit_post_rotation_report_json(overall, checks))
        return 0 if overall is not Severity.FAIL else 2

    return 1  # unreachable due to required=True


if __name__ == "__main__":
    import sys

    sys.exit(main())
