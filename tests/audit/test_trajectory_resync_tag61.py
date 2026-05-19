# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-61 Cross-Repo-Drift-Allowlist Trajectory-Re-Sync tests (Reza).

Pins:

  * The four canonical mirror-seed files exist under
    `wirelang/specs/protocol-mirror-seed/schemas/`.
  * Each seed file is a structural JSON document with the documented
    Wirelang schema `$id`.
  * `detect_trajectory_resync` finds exactly 4 expected re-sync rows
    and marks all 4 as seeded against the runtime repo root.
  * `compute_post_resync_score` blends the locked coverage with the
    post-re-sync trajectory and yields `score=92` /
    `ENFORCE-READY` for the current Tag-61 seed state.
  * `run_audit` exposes the new stages alongside the locked Tag-60
    baseline (score 76 / ENFORCE-CAUTION stays the
    score-of-record).
  * `_canonical_protocol_subpath` strips the `wakir_protocol/`
    prefix correctly and leaves other paths intact.
  * The README documents the Tag-61 extension table.
  * The seed schemas keep the Apache-2.0 SPDX header (matches the
    rest of the seed tree).
  * Sandbox-boundary discipline: zero edits in `wakir-protocol`.
  * Sub-path constants (`PROTOCOL_MIRROR_SEED_DIR`,
    `RESYNC_STRATEGIES`) are stable contract surface.

Sandbox boundary: pure-Python stdlib + pytest. No network, no
gh-CLI. The audit-helper is module-loaded from disk to mirror the
Tag-60 test pattern.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (workspace runs without an installed package).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "audit_cross_repo_drift_allowlist.py"
SEED_ROOT = REPO_ROOT / "wirelang" / "specs" / "protocol-mirror-seed"
SEED_SCHEMAS_DIR = SEED_ROOT / "schemas"
ALLOWLIST_PATH = REPO_ROOT / ".cross-repo-drift-allowlist.yaml"

EXPECTED_SEED_FILES = (
    "layer-0-transport.json",
    "layer-1-wire.json",
    "layer-2-semantic.json",
    "aip-document.json",
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "audit_cross_repo_drift_allowlist", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


helper = _load_helper()


# ---------------------------------------------------------------------------
# Seed-file presence.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed_name", EXPECTED_SEED_FILES)
def test_seed_file_exists(seed_name: str) -> None:
    """Each Tag-61 canonical mirror-seed file is present on disk."""
    seed_path = SEED_SCHEMAS_DIR / seed_name
    assert seed_path.is_file(), f"missing seed file: {seed_path}"


@pytest.mark.parametrize("seed_name", EXPECTED_SEED_FILES)
def test_seed_file_is_valid_json(seed_name: str) -> None:
    """Seed files are well-formed JSON with a Wirelang `$id`."""
    seed_path = SEED_SCHEMAS_DIR / seed_name
    doc = json.loads(seed_path.read_text(encoding="utf-8"))
    assert "$id" in doc, f"{seed_name}: missing $id"
    assert doc["$id"].startswith("https://wakir.dev/wirelang/schema/"), (
        f"{seed_name}: $id is not a Wirelang schema URI"
    )


@pytest.mark.parametrize("seed_name", EXPECTED_SEED_FILES)
def test_seed_file_has_apache_spdx_header(seed_name: str) -> None:
    """Seed files match the seed-tree Apache-2.0 SPDX posture."""
    seed_path = SEED_SCHEMAS_DIR / seed_name
    doc = json.loads(seed_path.read_text(encoding="utf-8"))
    # REUSE-IgnoreStart
    assert doc.get("x-spdx-license-identifier") == "Apache-2.0", (
        f"{seed_name}: SPDX-License-Identifier is not Apache-2.0"
    )
    # REUSE-IgnoreEnd


def test_seed_files_byte_identical_to_runtime_schemas() -> None:
    """Seed files are canonical-form mirrors of the runtime schemas.

    The canonicaliser strips SPDX/copyright headers before hashing,
    so byte-identical content guarantees a clean post-mirror state.
    """
    runtime_root = REPO_ROOT / "wirelang" / "schemas"
    for seed_name in EXPECTED_SEED_FILES:
        seed_bytes = (SEED_SCHEMAS_DIR / seed_name).read_bytes()
        runtime_bytes = (runtime_root / seed_name).read_bytes()
        assert seed_bytes == runtime_bytes, (
            f"{seed_name}: seed bytes differ from runtime — re-sync drift"
        )


# ---------------------------------------------------------------------------
# detect_trajectory_resync — core invariants.
# ---------------------------------------------------------------------------


def test_detect_trajectory_resync_finds_four_rows() -> None:
    """Inventory has exactly 4 re-sync drift rows."""
    resync = helper.detect_trajectory_resync(REPO_ROOT)
    assert resync["expected_seeded"] == 4
    assert len(resync["resync_rows"]) == 4


def test_detect_trajectory_resync_all_seeded() -> None:
    """All 4 re-sync rows have a present seed file in this branch."""
    resync = helper.detect_trajectory_resync(REPO_ROOT)
    assert resync["actually_seeded"] == 4
    assert resync["resync_completion"] == 1.0
    for row in resync["resync_rows"]:
        assert row["seed_present"] is True, row


def test_detect_trajectory_resync_missing_seeds(tmp_path: Path) -> None:
    """An empty repo root surfaces 4 rows with `seed_present=False`."""
    resync = helper.detect_trajectory_resync(tmp_path)
    assert resync["expected_seeded"] == 4
    assert resync["actually_seeded"] == 0
    assert resync["resync_completion"] == 0.0
    for row in resync["resync_rows"]:
        assert row["seed_present"] is False, row


# ---------------------------------------------------------------------------
# compute_post_resync_score — locked formula.
# ---------------------------------------------------------------------------


def test_post_resync_score_all_seeded_yields_92() -> None:
    """All 4 seeds present -> trajectory 0.80 -> score 92."""
    coverage = helper.compute_coverage(allowlist=[])
    resync = helper.detect_trajectory_resync(REPO_ROOT)
    post = helper.compute_post_resync_score(coverage, resync)
    assert post["post_resync_trajectory_ratio"] == pytest.approx(0.8)
    assert post["post_resync_clean_count"] == 8
    assert post["post_resync_score"] == 92


def test_post_resync_score_zero_seeded_matches_baseline(tmp_path: Path) -> None:
    """Zero seeds collapses post-score back to the locked baseline 76."""
    coverage = helper.compute_coverage(allowlist=[])
    resync = helper.detect_trajectory_resync(tmp_path)
    post = helper.compute_post_resync_score(coverage, resync)
    assert post["post_resync_trajectory_ratio"] == pytest.approx(0.4)
    assert post["post_resync_clean_count"] == 4
    assert post["post_resync_score"] == 76


def test_post_resync_verdict_promotes_to_ready_with_full_seed() -> None:
    """Full seed-set promotes the post-resync verdict to ENFORCE-READY."""
    report = helper.run_audit(
        allowlist_path=ALLOWLIST_PATH,
        repo_root=REPO_ROOT,
    )
    assert report["stage_4_post_resync_verdict"] == helper.VERDICT_READY
    # The locked baseline verdict is unaffected.
    assert report["stage_4_verdict"] == helper.VERDICT_CAUTION
    assert report["stage_3_readiness_score"]["score"] == 76


def test_post_resync_does_not_mutate_locked_baseline() -> None:
    """Stage-3 score-of-record stays 76 regardless of seed state."""
    report = helper.run_audit(
        allowlist_path=ALLOWLIST_PATH,
        repo_root=REPO_ROOT,
    )
    assert report["stage_3_readiness_score"]["score"] == 76
    assert report["stage_3_readiness_score"]["trajectory_ratio"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Helper-surface contract.
# ---------------------------------------------------------------------------


def test_resync_strategies_constant_is_stable() -> None:
    """The two re-sync strategies are part of the public contract."""
    assert set(helper.RESYNC_STRATEGIES) == {
        "re-sync-protocol-from-runtime",
        "re-sync-runtime-from-protocol",
    }


def test_protocol_mirror_seed_dir_constant_is_stable() -> None:
    """Seed directory path constant is the public contract."""
    assert helper.PROTOCOL_MIRROR_SEED_DIR == "wirelang/specs/protocol-mirror-seed"


def test_canonical_protocol_subpath_strips_prefix() -> None:
    """`wakir_protocol/...` paths lose the prefix."""
    fn = helper._canonical_protocol_subpath
    assert fn("wakir_protocol/schemas/layer-0-transport.json") == (
        "schemas/layer-0-transport.json"
    )
    assert fn("wakir_protocol/identity_substrate/aip_document.py") == (
        "identity_substrate/aip_document.py"
    )


def test_canonical_protocol_subpath_leaves_others_intact() -> None:
    """Non-protocol paths are returned untouched (fail-closed lookup)."""
    fn = helper._canonical_protocol_subpath
    assert fn("foo/bar.json") == "foo/bar.json"
    assert fn("") == ""


# ---------------------------------------------------------------------------
# README documentation contract.
# ---------------------------------------------------------------------------


def test_readme_documents_tag_61_extension() -> None:
    """The seed README has a Tag-61 section with the 4-row table."""
    readme = (SEED_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Tag-61 extension" in readme
    for seed_name in EXPECTED_SEED_FILES:
        assert seed_name in readme, f"README missing {seed_name}"
    assert "post_resync" in readme.lower() or "post-resync" in readme.lower()


# ---------------------------------------------------------------------------
# Sandbox-boundary discipline.
# ---------------------------------------------------------------------------


def test_no_writes_outside_runtime_repo() -> None:
    """Sandbox discipline: all seed files live under the runtime repo.

    The seed paths returned by `detect_trajectory_resync` must resolve
    inside `<repo_root>/wirelang/specs/protocol-mirror-seed/`. This
    pins Reza's ADR-0023a boundary: no direct writes to
    `wakir-protocol` paths from inside this PR.
    """
    resync = helper.detect_trajectory_resync(REPO_ROOT)
    expected_prefix = "wirelang/specs/protocol-mirror-seed/schemas/"
    for row in resync["resync_rows"]:
        assert row["seed_path"].startswith(expected_prefix), row
        # Cross-check: the path on disk is under REPO_ROOT.
        absolute = (REPO_ROOT / row["seed_path"]).resolve()
        assert str(absolute).startswith(str(REPO_ROOT.resolve())), absolute
