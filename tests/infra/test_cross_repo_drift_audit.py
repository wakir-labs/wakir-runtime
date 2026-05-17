# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the cross-repo-drift-audit workflow logic.

Follow-up to PR #105 (workflow introduction) per ADR-0062 Cut-2/Cut-3.
The workflow ``.github/workflows/cross-repo-drift-audit.yml`` introduced
a *signal* tripwire that compares mirrored substance files between
``wakir-runtime`` (BUSL-dominant) and ``wakir-protocol``
(Apache-2.0 + CC-BY) and surfaces byte-level drift as CI annotations.

PR #105 carries the workflow shell-substance. The Cut-2 hand-off
explicitly defers the *hermetic* test layer for the audit-logic
itself to this follow-up welle. This file delivers that layer.

Scope
-----
We test the *logic* of the workflow — hash-comparison, allowlist-
parsing, mirror-pair mapping, audit-vs-enforce verdict — by re-
implementing the same comparison primitives in Python against
synthetic fixtures. We do **not** clone the live ``wakir-protocol``
repo and we do **not** invoke the GitHub Actions runtime; the suite
is 100% hermetic so it runs in any sandbox (and so the workflow itself
remains the single source of truth for the production shell-glue).

Trade-off: a workflow-internal shell-bash regression that diverges
from this Python re-implementation will not be caught here — it
would require an act-runner harness, which is out of scope for the
Cut-3 follow-up. Cross-Review-Zone-3 (OTS-Schema-Anker compatibility)
flags this gap explicitly: the hermetic suite covers the *contract*
of the audit, not the *implementation* of the shell glue. A future
sprint can add an act-runner lane if Mira/Priya green-light the
container surface.

Test-Vector matrix (≥ 10 vectors, all hermetic):

* TV-CRD-01..05: Hash-comparison logic correctness (synthetic files,
  five distinct outcomes: identical, byte-drift, runtime-missing,
  protocol-missing, both-missing).
* TV-CRD-06..08: Allowlist parsing robustness (well-formed entries,
  malformed YAML, missing keys / escaping edge cases).
* TV-CRD-09..10: Mirror-pair-mapping inventory test — the ten pairs
  hard-coded in PR #105 must (a) cover Wirelang Layer 0..3 plus AIP +
  Datalog + Federation-Trust + canonical caveat-set + Identity-
  Substrate, and (b) encode the folder rename
  ``wirelang/identity/`` <-> ``wakir_protocol/identity_substrate/``.
* TV-CRD-11..13: Audit-mode vs enforce-mode behavior — drift never
  fails in audit-mode, drift fails in enforce-mode, clean run passes
  in both modes.

Sub-items the suite does *not* touch:

* The actual sha256sum binary call inside bash — we re-implement
  with hashlib.
* The GitHub workflow event-trigger surface (paths-filter, branches).
* The cross-repo-clone step itself; we never reach the network.
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "cross-repo-drift-audit.yml"
ALLOWLIST_PATH = REPO_ROOT / ".cross-repo-drift-allowlist.yaml"


# ---------------------------------------------------------------------------
# Re-implementation of the workflow's comparison primitives.
#
# Kept tiny + pure so the audit-logic invariants are testable without
# running bash. The shapes mirror the workflow exactly:
#
#   * ``sha256_of(path)`` -> hex digest of file content.
#   * ``compare_pair(runtime_root, protocol_root, runtime_rel, protocol_rel,
#                    allowlist)`` -> status string in
#       {"ok", "DRIFT", "drift-allowed",
#        "missing-runtime", "missing-protocol", "missing-both"}.
#   * ``audit_verdict(tally, enforce)`` -> (exit_code, message).
#   * ``parse_allowlist(text)`` -> list[(runtime, protocol)] | "__MALFORMED__".
# ---------------------------------------------------------------------------


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compare_pair(
    runtime_root: Path,
    protocol_root: Path,
    runtime_rel: str,
    protocol_rel: str,
    allowlist: list[tuple[str, str]],
) -> str:
    runtime_abs = runtime_root / runtime_rel
    protocol_abs = protocol_root / protocol_rel

    runtime_exists = runtime_abs.is_file()
    protocol_exists = protocol_abs.is_file()

    if not runtime_exists and not protocol_exists:
        return "missing-both"
    if not runtime_exists:
        return "missing-runtime"
    if not protocol_exists:
        return "missing-protocol"

    if _sha256_of(runtime_abs) == _sha256_of(protocol_abs):
        return "ok"

    if (runtime_rel, protocol_rel) in allowlist:
        return "drift-allowed"
    return "DRIFT"


def _audit_verdict(
    drift_count: int,
    missing_count: int,
    enforce: bool,
) -> tuple[int, str]:
    """Mirror of the workflow's `Audit verdict` step.

    Returns ``(exit_code, message)`` where ``exit_code`` is 0 for
    pass / 1 for fail. In audit-mode the verdict is *always* 0 even
    when drift / missing are non-zero (signal-only).
    """
    if enforce:
        if drift_count > 0 or missing_count > 0:
            return (
                1,
                f"enforce-mode failure: drift={drift_count}, missing={missing_count}",
            )
        return (0, "enforce-mode pass")
    if drift_count > 0 or missing_count > 0:
        return (
            0,
            f"audit-only observed drift={drift_count}, missing={missing_count}",
        )
    return (0, "audit-only clean")


def _parse_allowlist(text: str):
    """Re-implementation of the workflow's allowlist loader.

    Returns ``"__MALFORMED__"`` on YAML parse failure, otherwise a
    list of ``(runtime, protocol)`` tuples. Entries missing either
    key are silently dropped (the workflow does the same).
    """
    try:
        import yaml  # PyYAML; available on ubuntu-latest + in the test extra
    except ImportError:  # pragma: no cover — yaml ships with the test env
        pytest.skip("PyYAML not available — the workflow uses ubuntu-latest's PyYAML")

    try:
        data = yaml.safe_load(text) or {}
    except Exception:
        return "__MALFORMED__"

    out: list[tuple[str, str]] = []
    entries = (data or {}).get("allow") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        r = entry.get("runtime", "")
        p = entry.get("protocol", "")
        if r and p:
            out.append((r, p))
    return out


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_pair(tmp_path: Path):
    """Two scratch trees that mimic runtime + protocol layouts."""
    runtime = tmp_path / "runtime"
    protocol = tmp_path / "protocol"
    runtime.mkdir()
    protocol.mkdir()
    return runtime, protocol


# ---------------------------------------------------------------------------
# TV-CRD-01..05 — hash-comparison logic.
# ---------------------------------------------------------------------------


def test_tv_crd_01_identical_content_is_ok(synthetic_pair):
    """TV-CRD-01: byte-identical files compare as ``ok``."""
    runtime, protocol = synthetic_pair
    (runtime / "schema.json").write_text('{"k":1}\n', encoding="utf-8")
    (protocol / "schema.json").write_text('{"k":1}\n', encoding="utf-8")

    status = _compare_pair(
        runtime, protocol, "schema.json", "schema.json", allowlist=[]
    )
    assert status == "ok"


def test_tv_crd_02_byte_drift_is_drift_when_not_allowlisted(synthetic_pair):
    """TV-CRD-02: any byte difference flips status to ``DRIFT`` when
    the pair is not on the allowlist (single trailing newline difference
    must already trip the audit — SHA-256 is content-exact)."""
    runtime, protocol = synthetic_pair
    (runtime / "schema.json").write_text('{"k":1}\n', encoding="utf-8")
    (protocol / "schema.json").write_text('{"k":1}', encoding="utf-8")  # no trailing \n

    status = _compare_pair(
        runtime, protocol, "schema.json", "schema.json", allowlist=[]
    )
    assert status == "DRIFT"


def test_tv_crd_03_byte_drift_is_allowed_when_pair_on_allowlist(synthetic_pair):
    """TV-CRD-03: same drift, but the (runtime, protocol) pair is on
    the allowlist -> ``drift-allowed`` (SPDX-header-track use case)."""
    runtime, protocol = synthetic_pair
    # REUSE-IgnoreStart
    (runtime / "spdx.txt").write_text("SPDX-License-Identifier: BUSL-1.1\n", encoding="utf-8")
    (protocol / "spdx.txt").write_text("SPDX-License-Identifier: Apache-2.0\n", encoding="utf-8")
    # REUSE-IgnoreEnd

    status = _compare_pair(
        runtime, protocol, "spdx.txt", "spdx.txt",
        allowlist=[("spdx.txt", "spdx.txt")],
    )
    assert status == "drift-allowed"


def test_tv_crd_04_runtime_missing_is_distinct_status(synthetic_pair):
    """TV-CRD-04: protocol has the file, runtime doesn't -> ``missing-runtime``.
    Important to keep distinct from ``missing-protocol`` because the
    fix-direction is asymmetric (runtime forgot to mirror vs. protocol
    deleted a contract surface)."""
    runtime, protocol = synthetic_pair
    (protocol / "only_protocol.json").write_text("{}\n", encoding="utf-8")

    status = _compare_pair(
        runtime, protocol, "only_protocol.json", "only_protocol.json",
        allowlist=[],
    )
    assert status == "missing-runtime"


def test_tv_crd_05_protocol_missing_and_both_missing_are_distinct(synthetic_pair):
    """TV-CRD-05: protocol missing (runtime-side fork) vs both missing
    (clean inventory drift) are distinct verdicts."""
    runtime, protocol = synthetic_pair
    (runtime / "only_runtime.json").write_text("{}\n", encoding="utf-8")

    status_proto = _compare_pair(
        runtime, protocol, "only_runtime.json", "only_runtime.json",
        allowlist=[],
    )
    status_both = _compare_pair(
        runtime, protocol, "ghost.json", "ghost.json", allowlist=[]
    )
    assert status_proto == "missing-protocol"
    assert status_both == "missing-both"


# ---------------------------------------------------------------------------
# TV-CRD-06..08 — allowlist parsing robustness.
# ---------------------------------------------------------------------------


def test_tv_crd_06_wellformed_allowlist_parses_into_pairs():
    """TV-CRD-06: a normal allowlist with two entries parses into two
    (runtime, protocol) tuples."""
    text = textwrap.dedent(
        """
        allow:
          - runtime: wirelang/schemas/foo.json
            protocol: wakir_protocol/schemas/foo.json
            reason: SPDX-header-only
          - runtime: wirelang/canonical/caveat_set.py
            protocol: wakir_protocol/canonical/caveat_set.py
            reason: version-bump-in-flight
            follow_up: sprint-cut-3
        """
    )
    parsed = _parse_allowlist(text)
    assert parsed == [
        ("wirelang/schemas/foo.json", "wakir_protocol/schemas/foo.json"),
        ("wirelang/canonical/caveat_set.py", "wakir_protocol/canonical/caveat_set.py"),
    ]


def test_tv_crd_07_malformed_yaml_returns_sentinel_not_crash():
    """TV-CRD-07: a malformed YAML file returns the ``__MALFORMED__``
    sentinel so the workflow can surface an annotation without
    crashing the job (soft-fail in audit-mode is the contract)."""
    # Unterminated mapping value -> YAML parse error.
    text = "allow:\n  - runtime: foo\n    protocol: [\n"
    parsed = _parse_allowlist(text)
    assert parsed == "__MALFORMED__"


def test_tv_crd_08_missing_keys_and_empty_file_are_treated_as_no_waivers():
    """TV-CRD-08: entries with missing ``runtime`` or missing ``protocol``
    keys are silently dropped (not crashes), and a completely empty file
    yields an empty list. Mirrors the workflow's permissive loader."""
    parsed_missing = _parse_allowlist(
        textwrap.dedent(
            """
            allow:
              - runtime: only-runtime-key.json
              - protocol: only-protocol-key.json
              - runtime: ""
                protocol: ""
              - runtime: ok-runtime.json
                protocol: ok-protocol.json
            """
        )
    )
    parsed_empty_doc = _parse_allowlist("")
    parsed_no_allow_key = _parse_allowlist("# only a comment\n")

    assert parsed_missing == [("ok-runtime.json", "ok-protocol.json")]
    assert parsed_empty_doc == []
    assert parsed_no_allow_key == []


# ---------------------------------------------------------------------------
# TV-CRD-09..10 — mirror-pair mapping inventory (couples this test to
# PR #105 substance; if the workflow's pair list changes, this test
# must be re-validated).
# ---------------------------------------------------------------------------


def _extract_workflow_pairs() -> list[tuple[str, str]]:
    """Pull the ``pairs=(...)`` array literal out of the workflow YAML.

    We deliberately parse the bash array shape rather than re-listing
    the pairs in Python; that way the test fails the moment the
    workflow's inventory changes without a coordinated update here.
    """
    assert WORKFLOW_PATH.is_file(), f"workflow file missing: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    m = re.search(r"pairs=\(\s*(.*?)\s*\)\s*\n", text, re.DOTALL)
    assert m, "could not locate `pairs=(...)` array in workflow YAML"
    block = m.group(1)
    pairs: list[tuple[str, str]] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Lines look like: "runtime/path|protocol/path"
        stripped = line.strip().strip('"')
        if "|" not in stripped:
            continue
        runtime_rel, protocol_rel = stripped.split("|", 1)
        pairs.append((runtime_rel, protocol_rel))
    return pairs


def test_tv_crd_09_mirror_pair_inventory_substance_and_size():
    """TV-CRD-09: the workflow ships ≥ 10 mirror-pairs that collectively
    cover Wirelang Layer 0..3 plus AIP + Datalog + Federation-Trust +
    canonical caveat-set + Identity-Substrate per ADR-0062 Cut-2."""
    pairs = _extract_workflow_pairs()
    assert len(pairs) >= 10, f"expected ≥ 10 mirror-pairs, got {len(pairs)}"

    runtime_paths = {r for r, _ in pairs}

    # Substance markers — each must appear at least once on the runtime
    # side of the inventory. Wording from ADR-0062 Cut-2.
    required_substance_markers = {
        "layer-0": "Wirelang Layer-0",
        "layer-1": "Wirelang Layer-1",
        "layer-2": "Wirelang Layer-2",
        "layer-3": "Wirelang Layer-3 / Capability-Token",
        "aip-document": "AIP-Wrapper",
        "datalog-caveat": "Datalog caveat schema",
        "federation-trust": "Federation-Trust-Document",
        "caveat_set": "canonical caveat-set",
        "wirelang/identity/": "Identity-Substrate (runtime-side folder)",
    }
    for marker, description in required_substance_markers.items():
        assert any(marker in r for r in runtime_paths), (
            f"missing substance marker {marker!r} ({description}) in mirror-pair inventory"
        )


def test_tv_crd_10_folder_rename_runtime_identity_to_protocol_identity_substrate():
    """TV-CRD-10: the folder rename ``wirelang/identity/`` (runtime) <->
    ``wakir_protocol/identity_substrate/`` (protocol) is encoded in
    the inventory — i.e. at least one row must pair the two distinct
    folder roots without claiming drift on the rename itself."""
    pairs = _extract_workflow_pairs()
    renamed_rows = [
        (r, p)
        for r, p in pairs
        if r.startswith("wirelang/identity/")
        and p.startswith("wakir_protocol/identity_substrate/")
    ]
    assert renamed_rows, (
        "expected at least one (wirelang/identity/* <-> "
        "wakir_protocol/identity_substrate/*) pair to encode the folder rename"
    )
    # Sanity: rename must be folder-only — the basename should match.
    for r, p in renamed_rows:
        assert Path(r).name == Path(p).name, (
            f"folder-rename row {r!r} <-> {p!r} basenames differ — that is "
            "a real rename, not the tolerated folder-rename"
        )


# ---------------------------------------------------------------------------
# TV-CRD-11..13 — audit-mode vs enforce-mode verdict.
# ---------------------------------------------------------------------------


def test_tv_crd_11_audit_mode_never_fails_on_drift():
    """TV-CRD-11: in audit-mode (the introduction-cut default) drift
    and missing counts produce warnings only — exit-code is always 0."""
    code, msg = _audit_verdict(drift_count=3, missing_count=2, enforce=False)
    assert code == 0
    assert "audit-only observed" in msg


def test_tv_crd_12_enforce_mode_fails_on_drift_or_missing():
    """TV-CRD-12: in enforce-mode any non-zero drift or missing flips
    exit-code to 1 (the future state once the baseline allowlist is
    seeded per Cross-Review-Zone-3 sign-off)."""
    code_drift, _ = _audit_verdict(drift_count=1, missing_count=0, enforce=True)
    code_missing, _ = _audit_verdict(drift_count=0, missing_count=1, enforce=True)
    code_both, _ = _audit_verdict(drift_count=2, missing_count=3, enforce=True)
    assert code_drift == 1
    assert code_missing == 1
    assert code_both == 1


def test_tv_crd_13_clean_run_passes_in_both_modes():
    """TV-CRD-13: drift=0 + missing=0 is green regardless of mode."""
    code_audit, msg_audit = _audit_verdict(0, 0, enforce=False)
    code_enforce, msg_enforce = _audit_verdict(0, 0, enforce=True)
    assert code_audit == 0
    assert code_enforce == 0
    assert "clean" in msg_audit
    assert "pass" in msg_enforce


# ---------------------------------------------------------------------------
# Workflow-anchor sanity: the workflow file and allowlist file exist
# in the repo. These are guard rails so a future rename of either
# artifact does not silently strand this test suite.
# ---------------------------------------------------------------------------


def test_workflow_and_allowlist_artifacts_exist():
    """Sanity guard: the workflow + allowlist files live at the paths
    this suite assumes. If either moves, the inventory test
    (``_extract_workflow_pairs``) silently goes stale; this assertion
    keeps the wiring honest."""
    assert WORKFLOW_PATH.is_file(), f"missing workflow: {WORKFLOW_PATH}"
    assert ALLOWLIST_PATH.is_file(), f"missing allowlist: {ALLOWLIST_PATH}"
