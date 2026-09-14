# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Fail-open guard for required status contexts that use ``needs``.

The failure class
-----------------

A job that declares ``needs:`` and no job-level ``if: always()`` is
**skipped** when one of its dependencies fails. GitHub does not block a
merge on a skipped required status check, so a required context built
that way fails open: the gate disappears exactly when it matters.
Reference (verified 2026-09-14, HTTP 200):
https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks

``if: always()`` alone is not the fix either. It makes the job run, but
whatever the job then does — typically a green aggregate test — decides
the context's colour, so a red dependency can still end up reported
green. The job must additionally turn every ``needs.<job>.result`` into
its own exit code, and it must do that *before* it runs its own
substance, so a later green step cannot paper over an earlier red
dependency.

This module pins both halves for every required context in
``wakir-labs/wakir-runtime`` branch protection. It parses YAML on disk;
no GitHub API calls.

Found by the external re-review of 2026-09-14 (finding R6) in
``runtime-acceptance-gates.yml``; the repository-wide sweep in this
module additionally caught ``tests.yml``'s ``drift-detection``.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: Live ``required_status_checks.contexts`` of
#: ``wakir-labs/wakir-runtime`` ``main``, read 2026-09-14 via
#: ``gh api repos/wakir-labs/wakir-runtime/branches/main/protection``.
#: Enforcement is ``non_admins`` (``enforce_admins: false``).
#: Canonical inventory: ``docs/ci/branch-protection-required-checks.md`` §1.
REQUIRED_CONTEXTS: tuple[str, ...] = (
    "License-Hygiene Gate (ADR-0061)",
    "wirelang suite with rfc8785 + jsonschema",
    "production-vs-sandbox drift envelope",
    "wirelang suite without rfc8785 / jsonschema (shadow)",
    "verify-containerfile-base-image-digest-pins",
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "wirelang spec v0.4.3 freeze-seal probe",
    "cosign verify SPIRE images",
    "Cosign-Keyless-OIDC-Drift-Probe (daily)",
    "runtime acceptance gates",
    "proof-path",
    "secret-scan",
    "cross-repo compatibility (protocol ↔ runtime ↔ verify)",
)


def _load_workflows() -> Dict[Path, Dict[str, Any]]:
    out: Dict[Path, Dict[str, Any]] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out[path] = data
    return out


def _required_jobs_with_needs() -> List[tuple[Path, str, Dict[str, Any]]]:
    """Every (file, job-id, job) whose display name is a required
    context and which declares ``needs``."""
    found: List[tuple[Path, str, Dict[str, Any]]] = []
    for path, data in _load_workflows().items():
        for job_id, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            name = job.get("name", job_id)
            if name not in REQUIRED_CONTEXTS:
                continue
            if not job.get("needs"):
                continue
            found.append((path, job_id, job))
    return found


def _needs_list(job: Dict[str, Any]) -> List[str]:
    needs = job.get("needs")
    if isinstance(needs, str):
        return [needs]
    return list(needs or [])


def _step_result_refs(step: Dict[str, Any]) -> set[str]:
    """Job ids whose ``.result`` this step's body references."""
    body = yaml.safe_dump(step, allow_unicode=True)
    return set(re.findall(r"needs\.([A-Za-z0-9_\-]+)\.result", body))


def test_the_sweep_finds_the_jobs_it_is_supposed_to_guard():
    """Negative control for the test itself: if the discovery predicate
    silently matched nothing, every assertion below would pass
    vacuously."""
    found = {job_id for _, job_id, _ in _required_jobs_with_needs()}
    assert "runtime-acceptance-gates" in found
    assert "drift-detection" in found


@pytest.mark.parametrize(
    "path,job_id,job",
    _required_jobs_with_needs(),
    ids=[f"{p.name}:{j}" for p, j, _ in _required_jobs_with_needs()],
)
def test_required_context_with_needs_runs_even_when_a_dependency_fails(
    path: Path, job_id: str, job: Dict[str, Any]
) -> None:
    condition = str(job.get("if", ""))
    assert "always()" in condition, (
        f"{path.name}:{job_id} ({job.get('name')}) is a required status "
        f"context and declares needs={_needs_list(job)}, but has no "
        f"job-level `if: always()`. A failed dependency would skip it, and "
        f"GitHub does not block a merge on a skipped required check — the "
        f"gate would fail open."
    )


@pytest.mark.parametrize(
    "path,job_id,job",
    _required_jobs_with_needs(),
    ids=[f"{p.name}:{j}" for p, j, _ in _required_jobs_with_needs()],
)
def test_required_context_checks_every_dependency_result_first(
    path: Path, job_id: str, job: Dict[str, Any]
) -> None:
    steps = job.get("steps") or []
    assert steps, f"{path.name}:{job_id} has no steps"

    guard = steps[0]
    assert "if" not in guard, (
        f"{path.name}:{job_id}: the first step is the dependency-result "
        f"guard and must not be conditional — a conditional guard can be "
        f"skipped and then fails open again."
    )

    checked = _step_result_refs(guard)
    missing = [n for n in _needs_list(job) if n not in checked]
    assert not missing, (
        f"{path.name}:{job_id} ({job.get('name')}) runs with `always()` but "
        f"its first step does not check needs.{{{','.join(missing)}}}.result. "
        f"`always()` alone only guarantees the job runs; without an explicit "
        f"per-dependency `result == success` check a green aggregate step "
        f"reports the required context green while a dependency was red."
    )


def test_required_context_list_matches_the_branch_protection_audit():
    """One drift point, not two: the check-names audit under
    ``tests/ci/`` pins the same live context list."""
    audit_path = (
        REPO_ROOT / "tests" / "ci" / "test_branch_protection_check_names_audit.py"
    )
    spec = importlib.util.spec_from_file_location("_bp_audit", audit_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(REQUIRED_CONTEXTS) == set(module.REQUIRED_NAMES_RUNTIME), (
        "REQUIRED_CONTEXTS here and REQUIRED_NAMES_RUNTIME in "
        "tests/ci/test_branch_protection_check_names_audit.py disagree about "
        "the live branch-protection context set."
    )
