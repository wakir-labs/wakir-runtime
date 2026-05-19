# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Tests for the Tag-61 REUSE-IgnoreStart/End wrap pre-merge lint helper.

Anchors
-------

* Helper: ``tooling/ci/lint_reuse_ignore_wrap_pattern.py``
* Workflow: ``.github/workflows/reuse-wrap-pre-merge-lint.yml``

Pattern these tests pin down
----------------------------

Three consecutive hot-fix commits show that test files which include
SPDX-string-literal payloads (``Apache-2.0``, ``BUSL-1.1``, ...) in
fixture data trip the License-Hygiene Gate unless they are wrapped
in ``# REUSE-IgnoreStart`` / ``# REUSE-IgnoreEnd`` sentinels. This
suite proves the helper detects the missing-wrap case, accepts the
wrapped case, does not flag the file's own header banner, and does
not trip on its own internals (self-verify).

Hermetic
--------

stdlib + pytest. No subprocess into the network. The workflow YAML
is parsed via ``yaml`` only when present; structural assertions on
the workflow file use plain string scanning to keep the test
dependency-light.
"""

# REUSE-IgnoreEnd

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "lint_reuse_ignore_wrap_pattern.py"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "reuse-wrap-pre-merge-lint.yml"
)


def _load_helper():
    """Load the helper as a module.

    The helper uses ``@dataclass``; Python's dataclass machinery
    resolves forward-reference annotations via ``sys.modules`` at
    class-creation time, so the module MUST be registered in
    ``sys.modules`` BEFORE ``exec_module`` runs. Otherwise Python
    3.14's dataclass path raises ``AttributeError`` on the missing
    module entry.
    """
    mod_name = "reuse_wrap_lint_helper_tag61"
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def helper():
    """Module-scoped fixture giving every test the loaded helper."""
    return _load_helper()


# ---------------------------------------------------------------------------
# 1. Helper file exists on disk
# ---------------------------------------------------------------------------

def test_helper_file_exists():
    assert HELPER_PATH.is_file(), (
        f"Helper missing at {HELPER_PATH} - Tag-61 substance not in tree."
    )


# ---------------------------------------------------------------------------
# 2. Workflow file exists on disk
# ---------------------------------------------------------------------------

def test_workflow_file_exists():
    assert WORKFLOW_PATH.is_file(), (
        f"Workflow missing at {WORKFLOW_PATH} - Tag-61 wiring incomplete."
    )


# ---------------------------------------------------------------------------
# 3. Self-verify: helper does not trip on its own internals
# ---------------------------------------------------------------------------

def test_helper_self_verify_clean(helper):
    """The helper file MUST be wrap-clean against its own scanner."""
    findings = helper._scan_file(HELPER_PATH)
    assert findings == [], (
        f"Helper file itself has unwrapped SPDX literals: "
        f"{[(f.line_no, f.matched_token) for f in findings]}"
    )


# ---------------------------------------------------------------------------
# 4. Self-verify CLI exit code is 0
# ---------------------------------------------------------------------------

def test_helper_self_verify_cli_exit_zero(helper, capsys):
    rc = helper.main(["--mode", "self-verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SELF-VERIFY-OK" in out


# ---------------------------------------------------------------------------
# 5. Wrapped SPDX literal: no findings
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_WRAPPED_FIXTURE = """\
# SPDX-License-Identifier: BUSL-1.1
# REUSE-IgnoreStart
PAYLOAD = "SPDX-License-Identifier: Apache-2.0"
# REUSE-IgnoreEnd
def test_x():
    assert PAYLOAD
"""
# REUSE-IgnoreEnd


def test_wrapped_block_produces_no_findings(tmp_path, helper):
    f = tmp_path / "test_wrapped.py"
    f.write_text(_WRAPPED_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert findings == [], (
        f"Wrapped block should produce no findings, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 6. Unwrapped SPDX literal: at least one finding
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_UNWRAPPED_FIXTURE = """\
# SPDX-License-Identifier: BUSL-1.1
PAYLOAD = "SPDX-License-Identifier: Apache-2.0"
COPYRIGHT = "SPDX-FileCopyrightText: 2026 Callandor GmbH"
def test_x():
    assert PAYLOAD and COPYRIGHT
"""
# REUSE-IgnoreEnd


def test_unwrapped_block_produces_findings(tmp_path, helper):
    f = tmp_path / "test_unwrapped.py"
    f.write_text(_UNWRAPPED_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert len(findings) >= 2, (
        f"Expected >=2 findings (License-Identifier + FileCopyrightText literals), "
        f"got: {findings!r}"
    )
    matched = {f.matched_token for f in findings}
    assert any("SPDX-License-Identifier" in t for t in matched)
    assert any("SPDX-FileCopyrightText" in t for t in matched)


# ---------------------------------------------------------------------------
# 7. Header banner is NOT a finding
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_HEADER_ONLY_FIXTURE = """\
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
\"\"\"Module docstring without any SPDX payload.\"\"\"
def test_noop():
    assert True
"""
# REUSE-IgnoreEnd


def test_header_banner_is_not_a_finding(tmp_path, helper):
    f = tmp_path / "test_header_only.py"
    f.write_text(_HEADER_ONLY_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert findings == [], (
        f"File header banner must not be flagged, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 8. Bare SPDX-ID token in docstring prose is NOT flagged (anti-noise)
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_BARE_TOKEN_FIXTURE = '''\
# SPDX-License-Identifier: BUSL-1.1
"""Docstring referring to Apache-2.0 and BUSL-1.1 in prose."""
BANNER = "Apache-2.0"
'''
# REUSE-IgnoreEnd


def test_bare_token_in_prose_is_not_flagged(tmp_path, helper):
    """Plain ID tokens in docstring/string prose do not trip the
    upstream REUSE linter, so this helper deliberately ignores them
    to avoid a false-positive noise wall on the existing tree.
    """
    f = tmp_path / "test_bare_token.py"
    f.write_text(_BARE_TOKEN_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert findings == [], (
        f"Bare ID tokens in prose must not be flagged, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 9. Multi-line fixture with mid-block IgnoreStart works
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_MID_WRAP_FIXTURE = """\
# SPDX-License-Identifier: BUSL-1.1
def setup():
    pass
# REUSE-IgnoreStart
A = "SPDX-License-Identifier: Apache-2.0"
B = "BUSL-1.1"
# REUSE-IgnoreEnd
def teardown():
    pass
"""
# REUSE-IgnoreEnd


def test_mid_block_wrap_protects_only_inside(tmp_path, helper):
    f = tmp_path / "test_mid.py"
    f.write_text(_MID_WRAP_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert findings == [], (
        f"Mid-block wrap should suppress all findings, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 10. Unwrapped block AFTER a wrapped block is still flagged
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_LEAK_AFTER_WRAP_FIXTURE = """\
# SPDX-License-Identifier: BUSL-1.1
# REUSE-IgnoreStart
A = "SPDX-License-Identifier: Apache-2.0"
# REUSE-IgnoreEnd
B = "SPDX-License-Identifier: BUSL-1.1"
"""
# REUSE-IgnoreEnd


def test_unwrapped_leak_after_wrap_is_flagged(tmp_path, helper):
    f = tmp_path / "test_leak.py"
    f.write_text(_LEAK_AFTER_WRAP_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert len(findings) == 1
    assert "BUSL-1.1" in findings[0].matched_token


# ---------------------------------------------------------------------------
# 11. Patch suggestion renders a sentinel pair
# ---------------------------------------------------------------------------

def test_patch_suggestion_renders_sentinel_pair(tmp_path, helper):
    f = tmp_path / "test_for_patch.py"
    f.write_text(_UNWRAPPED_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    patch = helper.render_patch_suggestion(findings)
    assert "REUSE-IgnoreStart" in patch
    assert "REUSE-IgnoreEnd" in patch
    assert str(f) in patch


# ---------------------------------------------------------------------------
# 12. CLI enforce mode exits 1 on findings
# ---------------------------------------------------------------------------

def test_cli_enforce_mode_exits_one_on_findings(tmp_path, helper, capsys):
    f = tmp_path / "test_enforce.py"
    f.write_text(_UNWRAPPED_FIXTURE, encoding="utf-8")
    rc = helper.main(["--mode", "enforce", str(f)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "REUSE-WRAP-MISSING" in out


# ---------------------------------------------------------------------------
# 13. CLI hint mode exits 0 even on findings
# ---------------------------------------------------------------------------

def test_cli_hint_mode_exits_zero_on_findings(tmp_path, helper, capsys):
    f = tmp_path / "test_hint.py"
    f.write_text(_UNWRAPPED_FIXTURE, encoding="utf-8")
    rc = helper.main(["--mode", "hint", str(f)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REUSE-WRAP-MISSING" in out


# ---------------------------------------------------------------------------
# 14. CLI any-mode on clean tree emits INTACT verdict
# ---------------------------------------------------------------------------

def test_cli_clean_tree_emits_intact_verdict(tmp_path, helper, capsys):
    f = tmp_path / "test_clean.py"
    f.write_text(_HEADER_ONLY_FIXTURE, encoding="utf-8")
    rc = helper.main(["--mode", "enforce", str(f)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REUSE-WRAP-INTACT" in out


# ---------------------------------------------------------------------------
# 15. Workflow YAML contains the three required stages by name
# ---------------------------------------------------------------------------

def test_workflow_has_three_stages():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "Stage 1 - Hint scan" in text
    assert "Stage 2 - Patch-suggestion" in text
    assert "Stage 3 - Verdict" in text


# ---------------------------------------------------------------------------
# 16. Workflow YAML triggers on pull_request with tests/**/*.py path filter
# ---------------------------------------------------------------------------

def test_workflow_trigger_and_path_filter():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert 'tests/**/*.py' in text or '"tests/**/*.py"' in text


# ---------------------------------------------------------------------------
# 17. Workflow YAML has self-verify step
# ---------------------------------------------------------------------------

def test_workflow_runs_self_verify():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "--mode self-verify" in text


# ---------------------------------------------------------------------------
# 18. Workflow YAML has sandbox-mode guard on PR comment
# ---------------------------------------------------------------------------

def test_workflow_sandbox_mode_guard():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "REUSE_WRAP_LINT_SANDBOX" in text
    assert "sandbox-mode" in text.lower()


# ---------------------------------------------------------------------------
# 19. scan() top-level API is exposed and accepts a list of paths
# ---------------------------------------------------------------------------

def test_top_level_scan_api_accepts_paths(tmp_path, helper):
    f = tmp_path / "test_scan_api.py"
    f.write_text(_UNWRAPPED_FIXTURE, encoding="utf-8")
    findings = helper.scan([tmp_path])
    assert len(findings) >= 1


# ---------------------------------------------------------------------------
# 20. Empty tree produces INTACT verdict (no false-positive on absence)
# ---------------------------------------------------------------------------

def test_empty_tree_produces_intact_verdict(tmp_path, helper, capsys):
    rc = helper.main(["--mode", "enforce", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "REUSE-WRAP-INTACT" in out


# ---------------------------------------------------------------------------
# 21. Triple-quoted-string interior is suppressed (anti-false-positive)
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_TRIPLE_QUOTED_FIXTURE = '''\
# SPDX-License-Identifier: BUSL-1.1
FIXTURE = """\
---
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH
---
content body
"""
'''
# REUSE-IgnoreEnd


def test_triple_quoted_interior_is_not_flagged(tmp_path, helper):
    """REUSE-3.0 does not parse triple-quoted-string interiors as
    SPDX headers, so this helper deliberately suppresses them too.
    """
    f = tmp_path / "test_triple.py"
    f.write_text(_TRIPLE_QUOTED_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert findings == [], (
        f"Triple-quoted interior must be suppressed, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 22. Hot-fix regression: simulate the Noa Tag-58 single-line-string trip
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_HISTORICAL_NOA_TRIP_FIXTURE = '''\
# SPDX-License-Identifier: BUSL-1.1
def twin_roots(tmp_path):
    body_md = (
        "<!-- SPDX-License-Identifier: BUSL-1.1 -->\\n"
        "<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH -->\\n"
        "\\n"
        "# Pre-Mortem Notify-Catalog\\n"
    )
    return body_md
'''
# REUSE-IgnoreEnd


def test_historical_noa_trip_is_detected(tmp_path, helper):
    """The exact line-string concat pattern that tripped Tag-59 hot-fix
    046a5e5 must be detected by this helper.
    """
    f = tmp_path / "test_historical_noa.py"
    f.write_text(_HISTORICAL_NOA_TRIP_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert len(findings) >= 2, (
        f"Historical Noa trip must surface >=2 findings, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 23. Wrapping the historical trip suppresses the findings
# ---------------------------------------------------------------------------

# REUSE-IgnoreStart
_HISTORICAL_NOA_FIXED_FIXTURE = '''\
# SPDX-License-Identifier: BUSL-1.1
# REUSE-IgnoreStart
def twin_roots(tmp_path):
    body_md = (
        "<!-- SPDX-License-Identifier: BUSL-1.1 -->\\n"
        "<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH -->\\n"
        "\\n"
        "# Pre-Mortem Notify-Catalog\\n"
    )
    return body_md
# REUSE-IgnoreEnd
'''
# REUSE-IgnoreEnd


def test_historical_noa_fix_suppresses_findings(tmp_path, helper):
    f = tmp_path / "test_historical_noa_fix.py"
    f.write_text(_HISTORICAL_NOA_FIXED_FIXTURE, encoding="utf-8")
    findings = helper._scan_file(f)
    assert findings == [], (
        f"Wrapped historical Noa trip must be clean, got: {findings!r}"
    )


# ---------------------------------------------------------------------------
# 24. Pre-commit-config registers the new hint-mode hook
# ---------------------------------------------------------------------------

def test_precommit_config_registers_wrap_lint_hook():
    """`.pre-commit-config.yaml` MUST include the Tag-61 wrap-lint
    hook so the developer's `git commit` invocation hits it before
    the server-side license-gate does.
    """
    cfg = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "reuse-wrap-pre-merge-lint" in cfg
    assert "tooling/ci/lint_reuse_ignore_wrap_pattern.py" in cfg
    assert "--mode hint" in cfg
