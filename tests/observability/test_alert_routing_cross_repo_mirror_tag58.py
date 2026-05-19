# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-58 Alert-Routing-Spec Cross-Repo-Mirror Audit regression tests.

Pins properties of:

* the helper module ``tooling/ci/audit_alert_routing_cross_repo_mirror.py``;
* the workflow ``.github/workflows/alert-routing-cross-repo-mirror.yml``;
* the allowlist ``.alert-routing-cross-repo-allowlist.yaml``;
* the canonical-form-normalisation contract.

The tests are hermetic stdlib + pytest. They construct synthetic
runtime/protocol directory trees in ``tmp_path`` to drive the audit
through MIRROR-OK, MIRROR-DRIFT (real and allowlisted), and missing-
side verdict states. They also pin workflow YAML properties so a
silent path-filter regression or job-name rename surfaces in CI.

Hermetic discipline
-------------------
No subprocess outside the helper module itself, no network, no Rust
build, no engine boot, no NATS, no real wakir-protocol clone.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling/ci/audit_alert_routing_cross_repo_mirror.py"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/alert-routing-cross-repo-mirror.yml"
ALLOWLIST_PATH = REPO_ROOT / ".alert-routing-cross-repo-allowlist.yaml"


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_helper_module():
    mod_name = "audit_alert_routing_cross_repo_mirror"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(HELPER_PATH))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper():
    return _load_helper_module()


# ---------------------------------------------------------------------------
# Synthetic runtime/protocol tree fixture
# ---------------------------------------------------------------------------


def _materialise_pair_files(
    root: Path,
    pair_paths: Iterator[tuple[str, str]],
) -> None:
    """Write a placeholder file at ``root / path`` for each path."""
    for path, body in pair_paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


@pytest.fixture
# REUSE-IgnoreStart
def twin_roots(tmp_path: Path, helper):
    """Build a runtime + protocol root that mirror cleanly."""
    runtime = tmp_path / "runtime"
    protocol = tmp_path / "protocol"
    runtime.mkdir()
    protocol.mkdir()

    # Two pairs differ ONLY in SPDX banner (runtime BUSL, protocol
    # Apache); canonical form should match.
    body_md = (
        "<!-- SPDX-License-Identifier: BUSL-1.1 -->\n"
        "<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH -->\n"
        "\n"
        "# Pre-Mortem Notify-Catalog\n"
        "\n"
        "Body content line one.\n"
    )
    body_md_protocol = body_md.replace(
        "SPDX-License-Identifier: BUSL-1.1",
        "SPDX-License-Identifier: Apache-2.0",
    )

    body_yaml = (
        "# SPDX-License-Identifier: BUSL-1.1\n"
        "# SPDX-FileCopyrightText: 2026 Callandor GmbH\n"
        "\n"
        "groups:\n"
        "  - name: phase-3-marathon\n"
        "    rules:\n"
        "      - alert: WakirPhase3FailureModeA1\n"
        "        expr: foo > 0\n"
    )
    body_yaml_protocol = body_yaml.replace(
        "SPDX-License-Identifier: BUSL-1.1",
        "SPDX-License-Identifier: Apache-2.0",
    )

    body_burn = (
        "# SPDX-License-Identifier: BUSL-1.1\n"
        "groups:\n"
        "  - name: phase-3-marathon-slo-burn\n"
        "    rules:\n"
        "      - alert: WakirSloBurn\n"
        "        expr: bar > 0\n"
    )
    body_burn_protocol = body_burn.replace(
        "SPDX-License-Identifier: BUSL-1.1",
        "SPDX-License-Identifier: Apache-2.0",
    )

    body_py = (
        "# SPDX-License-Identifier: BUSL-1.1\n"
        "# Copyright (c) 2026 Callandor GmbH\n"
        "ALERT_CATALOG = {\n"
        "    'WakirPhase3FailureModeA1': 'A1',\n"
        "}\n"
    )
    body_py_protocol = body_py.replace(
        "SPDX-License-Identifier: BUSL-1.1",
        "SPDX-License-Identifier: Apache-2.0",
    )

    runtime_files = {
        "docs/observability/pre-mortem-failure-mode-notify-catalog.md": body_md,
        "dashboards/phase-3-marathon-alerts.yaml": body_yaml,
        "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml": body_burn,
        "scripts/observability/alert-rule-to-mira-notify-bridge.py": body_py,
    }
    protocol_files = {
        "docs/observability/pre-mortem-failure-mode-notify-catalog.md": body_md_protocol,
        "dashboards/phase-3-marathon-alerts.yaml": body_yaml_protocol,
        "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml": body_burn_protocol,
        "scripts/observability/alert-rule-to-mira-notify-bridge.py": body_py_protocol,
    }

    _materialise_pair_files(runtime, runtime_files.items())
    _materialise_pair_files(protocol, protocol_files.items())

    return runtime, protocol


# ---------------------------------------------------------------------------
# 01–03: Helper module loads, MIRROR_PAIRS shape, verdict constants
# ---------------------------------------------------------------------------


def test_01_helper_module_loads(helper):
    """Helper module imports cleanly and exposes the public API."""
    for name in (
        "MIRROR_PAIRS",
        "MirrorPair",
        "audit",
        "audit_pair",
        "canonicalise",
        "sha256_canonical",
        "load_allowlist",
        "render_json",
        "render_markdown",
        "render_github_annotations",
        "VERDICT_MIRROR_OK",
        "VERDICT_MIRROR_DRIFT",
        "STATUS_OK",
        "STATUS_DRIFT",
        "STATUS_DRIFT_ALLOWED",
        "STATUS_MISSING_RUNTIME",
        "STATUS_MISSING_PROTOCOL",
        "STATUS_MISSING_BOTH",
    ):
        assert hasattr(helper, name), f"missing public symbol: {name}"


def test_02_mirror_pairs_table_pinned(helper):
    """MIRROR_PAIRS includes the four canonical alert-routing artifacts."""
    runtime_paths = {p.runtime_path for p in helper.MIRROR_PAIRS}
    expected = {
        "docs/observability/pre-mortem-failure-mode-notify-catalog.md",
        "dashboards/phase-3-marathon-alerts.yaml",
        "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
        "scripts/observability/alert-rule-to-mira-notify-bridge.py",
    }
    assert runtime_paths == expected, runtime_paths
    # Table is small by design (Zone-I additions need review).
    assert 4 <= len(helper.MIRROR_PAIRS) <= 10


def test_03_verdict_constants_stable(helper):
    """Verdict + status constants must not drift silently."""
    assert helper.VERDICT_MIRROR_OK == "MIRROR-OK"
    assert helper.VERDICT_MIRROR_DRIFT == "MIRROR-DRIFT"
    assert helper.STATUS_OK == "ok"
    assert helper.STATUS_DRIFT == "DRIFT"
    assert helper.STATUS_DRIFT_ALLOWED == "drift-allowed"
    assert helper.STATUS_MISSING_RUNTIME == "missing-runtime"
    assert helper.STATUS_MISSING_PROTOCOL == "missing-protocol"
    assert helper.STATUS_MISSING_BOTH == "missing-both"


# ---------------------------------------------------------------------------
# 04–06: Canonicaliser semantics (SPDX strip, body fidelity, idempotence)
# ---------------------------------------------------------------------------


def test_04_canonicaliser_strips_spdx_banner(helper):
    """Two files differing only in SPDX banner collapse to same canonical."""
    a = (
        "# SPDX-License-Identifier: BUSL-1.1\n"
        "# SPDX-FileCopyrightText: 2026 Callandor GmbH\n"
        "\n"
        "body line one\n"
    )
    b = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# SPDX-FileCopyrightText: 2026 Callandor GmbH\n"
        "\n"
        "body line one\n"
    )
    assert helper.sha256_canonical(a.encode(), helper.NORMALISER_PY) == helper.sha256_canonical(
        b.encode(), helper.NORMALISER_PY
    )


def test_05_canonicaliser_preserves_body_drift(helper):
    """A real body-line difference must still surface as drift."""
    a = "# SPDX-License-Identifier: Apache-2.0\n\nbody line ONE\n"
    b = "# SPDX-License-Identifier: Apache-2.0\n\nbody line TWO\n"
    assert helper.sha256_canonical(a.encode(), helper.NORMALISER_PY) != helper.sha256_canonical(
        b.encode(), helper.NORMALISER_PY
    )


def test_06_canonicaliser_idempotent(helper):
    """canonicalise(canonicalise(x)) == canonicalise(x)."""
    body = (
        "# SPDX-License-Identifier: Apache-2.0\n"
        "# Copyright (c) 2026 Callandor GmbH\n"
        "\n"
        "alpha\n"
        "beta\n"
        "\n"
    )
    once = helper.canonicalise(body.encode(), helper.NORMALISER_PY)
    twice = helper.canonicalise(once, helper.NORMALISER_PY)
    assert once == twice


# REUSE-IgnoreEnd

# ---------------------------------------------------------------------------
# 07–10: audit() verdicts under MIRROR-OK, MIRROR-DRIFT, missing, allowed
# ---------------------------------------------------------------------------


def test_07_audit_mirror_ok_on_canonical_twins(helper, twin_roots):
    """All pairs match (modulo SPDX): verdict MIRROR-OK, drift=0."""
    runtime, protocol = twin_roots
    result = helper.audit(runtime, protocol, allowlist_path=None)
    assert result.verdict == helper.VERDICT_MIRROR_OK, [
        (r.pair.runtime_path, r.status) for r in result.results
    ]
    assert result.drift_count == 0
    assert result.missing_count == 0
    assert result.ok_count == len(helper.MIRROR_PAIRS)


def test_08_audit_mirror_drift_on_body_change(helper, twin_roots, tmp_path):
    """Mutating one protocol-side body flips verdict to MIRROR-DRIFT."""
    runtime, protocol = twin_roots
    # Mutate one mirror-pair body on the protocol side.
    target = protocol / "dashboards/phase-3-marathon-alerts.yaml"
    body = target.read_text(encoding="utf-8")
    target.write_text(body + "      - alert: SneakyAdd\n        expr: never > 0\n", encoding="utf-8")

    result = helper.audit(runtime, protocol, allowlist_path=None)
    assert result.verdict == helper.VERDICT_MIRROR_DRIFT
    assert result.drift_count == 1
    drift_pair = next(r for r in result.results if r.status == helper.STATUS_DRIFT)
    assert drift_pair.pair.runtime_path == "dashboards/phase-3-marathon-alerts.yaml"


def test_09_audit_missing_protocol_surfaces_as_missing(helper, twin_roots):
    """Removing a protocol-side file surfaces as missing-protocol."""
    runtime, protocol = twin_roots
    (protocol / "scripts/observability/alert-rule-to-mira-notify-bridge.py").unlink()

    result = helper.audit(runtime, protocol, allowlist_path=None)
    assert result.verdict == helper.VERDICT_MIRROR_DRIFT  # missing counts as drift verdict
    assert result.missing_count == 1
    missing_pair = next(
        r for r in result.results if r.status == helper.STATUS_MISSING_PROTOCOL
    )
    assert missing_pair.pair.runtime_path == "scripts/observability/alert-rule-to-mira-notify-bridge.py"


def test_10_audit_drift_allowed_via_allowlist(helper, twin_roots, tmp_path):
    """Mutated pair listed in allowlist surfaces as drift-allowed (verdict OK)."""
    runtime, protocol = twin_roots
    # Cause real drift on one pair.
    target = protocol / "dashboards/phase-3-marathon-alerts.yaml"
    target.write_text(target.read_text() + "\n# tail drift\n", encoding="utf-8")

    # Emit an allowlist with that pair waived.
    allow = tmp_path / "allow.yaml"
    allow.write_text(
        "allow:\n"
        "  - runtime: dashboards/phase-3-marathon-alerts.yaml\n"
        "    protocol: dashboards/phase-3-marathon-alerts.yaml\n"
        "    reason: tag-58 baseline observation pre-Tomas-Zone-I-review\n",
        encoding="utf-8",
    )

    result = helper.audit(runtime, protocol, allowlist_path=allow)
    assert result.drift_count == 0
    assert result.drift_allowed_count == 1
    assert result.verdict == helper.VERDICT_MIRROR_OK
    waived = next(
        r for r in result.results if r.status == helper.STATUS_DRIFT_ALLOWED
    )
    assert waived.pair.runtime_path == "dashboards/phase-3-marathon-alerts.yaml"


# ---------------------------------------------------------------------------
# 11–13: Allowlist loader edge cases
# ---------------------------------------------------------------------------


def test_11_allowlist_missing_file_is_empty(helper, tmp_path):
    """Missing allowlist file: empty set, no warning."""
    pairs, warn = helper.load_allowlist(tmp_path / "does-not-exist.yaml")
    assert pairs == set()
    assert warn is None


def test_12_allowlist_repo_root_file_is_empty_by_design(helper):
    """Tag-58 introduction cut: repo-root allowlist file must be empty."""
    assert ALLOWLIST_PATH.exists(), f"allowlist not at expected path: {ALLOWLIST_PATH}"
    pairs, warn = helper.load_allowlist(ALLOWLIST_PATH)
    assert pairs == set(), (
        f"Tag-58 allowlist must start empty (Tomas Zone-I review pending); "
        f"got {pairs}"
    )
    # warn may be None or a soft-fail tag; both are acceptable on the
    # empty file. We assert *not* a malformed-warning state.
    assert warn is None or "malformed" not in (warn or ""), warn


# ---------------------------------------------------------------------------
# 14–16: Renderer contracts (json structure, markdown headers, github annotations)
# ---------------------------------------------------------------------------


def test_13_render_json_shape(helper, twin_roots):
    runtime, protocol = twin_roots
    result = helper.audit(runtime, protocol, allowlist_path=None)
    payload = json.loads(helper.render_json(result))
    assert payload["verdict"] in (helper.VERDICT_MIRROR_OK, helper.VERDICT_MIRROR_DRIFT)
    assert "pairs" in payload and isinstance(payload["pairs"], list)
    assert len(payload["pairs"]) == len(helper.MIRROR_PAIRS)
    for row in payload["pairs"]:
        for key in (
            "runtime_path",
            "protocol_path",
            "normaliser",
            "status",
            "runtime_sha",
            "protocol_sha",
            "runtime_present",
            "protocol_present",
            "description",
        ):
            assert key in row, key


def test_14_render_markdown_has_verdict_header(helper, twin_roots):
    runtime, protocol = twin_roots
    result = helper.audit(runtime, protocol, allowlist_path=None)
    md = helper.render_markdown(result)
    assert "# Alert-Routing-Spec Cross-Repo Mirror Audit (Tag-58)" in md
    assert "**Verdict:**" in md
    assert "**Tally**" in md


def test_15_render_github_annotations_only_on_problems(helper, twin_roots):
    """Annotation list is empty on MIRROR-OK, non-empty on MIRROR-DRIFT."""
    runtime, protocol = twin_roots
    ok_result = helper.audit(runtime, protocol, allowlist_path=None)
    assert helper.render_github_annotations(ok_result) == []

    # Introduce drift.
    (protocol / "dashboards/phase-3-marathon-alerts.yaml").write_text(
        "groups: []\n", encoding="utf-8"
    )
    drift_result = helper.audit(runtime, protocol, allowlist_path=None)
    annotations = helper.render_github_annotations(drift_result)
    assert annotations, "expected annotations on drift"
    assert any("::error file=" in a for a in annotations)


# ---------------------------------------------------------------------------
# 17–20: Workflow YAML pinning
# ---------------------------------------------------------------------------


def test_16_workflow_file_exists():
    assert WORKFLOW_PATH.exists(), f"missing workflow: {WORKFLOW_PATH}"


def test_17_workflow_job_display_name_for_required_status():
    """Job display name must remain stable so a Required-Status-Check can be wired."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Match the name: line on the job (not the top-level workflow name).
    # We require the exact display name we documented.
    assert "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)" in text


def test_18_workflow_triggers_on_alert_routing_paths():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for path in (
        "dashboards/phase-3-marathon-alerts.yaml",
        "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
        "docs/observability/pre-mortem-failure-mode-notify-catalog.md",
        "scripts/observability/alert-rule-to-mira-notify-bridge.py",
        "tooling/ci/audit_alert_routing_cross_repo_mirror.py",
        ".alert-routing-cross-repo-allowlist.yaml",
        ".github/workflows/alert-routing-cross-repo-mirror.yml",
    ):
        assert path in text, f"workflow path-trigger missing: {path}"


def test_19_workflow_uses_audit_only_default_and_enforce_input():
    """Default mode is audit-only; workflow_dispatch carries an enforce input."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "enforce" in text
    # Default value for the env must be "false" so the gate is non-fatal by default.
    assert re.search(
        r"ALERT_ROUTING_MIRROR_ENFORCE:\s*\$\{\{\s*github\.event\.inputs\.enforce\s*\|\|\s*'false'\s*\}\}",
        text,
    ), "default-audit-only env wiring missing/changed"


def test_20_workflow_clones_protocol_at_pinned_ref():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "PROTOCOL_REF: main" in text
    assert "wakir-labs/wakir-protocol" in text
    assert "git clone --depth=1" in text


# ---------------------------------------------------------------------------
# 21–22: CLI exit-code contract
# ---------------------------------------------------------------------------


def test_21_cli_exits_zero_in_audit_only_on_drift(helper, twin_roots, capsys):
    """Default (audit-only) returns 0 even when drift is observed."""
    runtime, protocol = twin_roots
    # Introduce drift.
    (protocol / "dashboards/phase-3-marathon-alerts.yaml").write_text(
        "drift body\n", encoding="utf-8"
    )
    rc = helper.main(
        [
            "--runtime-root",
            str(runtime),
            "--protocol-root",
            str(protocol),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["verdict"] == helper.VERDICT_MIRROR_DRIFT


def test_22_cli_exits_nonzero_with_enforce_on_drift(helper, twin_roots, capsys):
    runtime, protocol = twin_roots
    (protocol / "dashboards/phase-3-marathon-alerts.yaml").write_text(
        "drift body\n", encoding="utf-8"
    )
    rc = helper.main(
        [
            "--runtime-root",
            str(runtime),
            "--protocol-root",
            str(protocol),
            "--format",
            "json",
            "--enforce",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["verdict"] == helper.VERDICT_MIRROR_DRIFT
