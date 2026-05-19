# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-59 Cut-3 Protocol-Mirror-Seed tests (Reza Wirelang).

These tests target the new ``protocol-mirror-seed-detect`` stage in
``tooling/ci/audit_alert_routing_cross_repo_mirror.py`` introduced
on Tag-59 to seed the canonical protocol-side spec content from
within the runtime repo (sandbox-boundary).

Invariants under test
---------------------

1. The seed prefix exists on main and contains all four mirror-
   pair files at their canonical protocol-relative paths.
2. Each seed file ships with an ``Apache-2.0`` SPDX-License-
   Identifier header (matching protocol-side licensing) regardless
   of the runtime-side BUSL-1.1 posture.
3. The canonicaliser strips SPDX/copyright banners identically on
   both sides; seed canonical SHA equals the runtime-side canonical
   SHA for every mirror-pair (otherwise the seed has drifted from
   its source-of-truth).
4. ``detect_protocol_mirror_seeds`` emits one SeedMarker per pair
   whose seed file is present, never raises on a missing seed
   tree, and never flips ``PairResult.status``.
5. SeedMarker JSON serialisation surfaces the marker constant
   ``protocol-mirror-seed-ready`` and the seed_relpath under the
   ``wirelang/specs/protocol-mirror-seed`` prefix.
6. The markdown renderer surfaces a dedicated seed-marker table
   when markers are present, and omits it when markers are absent.
7. The github annotation renderer emits ``::notice`` lines (never
   ``::error``) for seed markers; ``::notice`` does not fail CI.

Discipline
----------

stdlib + pytest only. No network. Fixtures use ``tmp_path`` for
isolated runtime/protocol roots.

-- Reza
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "tooling" / "ci" / "audit_alert_routing_cross_repo_mirror.py"
SEED_PREFIX = REPO_ROOT / "wirelang" / "specs" / "protocol-mirror-seed"


def _load_audit_module():
    module_name = "audit_alert_routing_cross_repo_mirror_tag59"
    spec = importlib.util.spec_from_file_location(module_name, AUDIT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module so that the
    # dataclasses machinery (Python 3.14) can resolve forward
    # references against the module namespace.
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit_mod():
    return _load_audit_module()


# ---------------------------------------------------------------------------
# Invariant 1: Seed-Prefix existence + completeness
# ---------------------------------------------------------------------------


def test_seed_prefix_exists_on_main(audit_mod):
    """The Tag-59 seed prefix must exist as a directory."""
    assert SEED_PREFIX.is_dir(), f"missing seed prefix: {SEED_PREFIX}"
    assert audit_mod.PROTOCOL_MIRROR_SEED_PREFIX == "wirelang/specs/protocol-mirror-seed"


def test_seed_prefix_contains_all_four_mirror_pairs(audit_mod):
    """Every MIRROR_PAIRS entry has a corresponding seed file."""
    missing: list[str] = []
    for pair in audit_mod.MIRROR_PAIRS:
        seed_file = SEED_PREFIX / pair.protocol_path
        if not seed_file.is_file():
            missing.append(pair.protocol_path)
    assert not missing, f"missing seed files: {missing}"


def test_seed_readme_documents_cut_3_purpose():
    """README.md inside the seed prefix names Tag-59 Cut-3 + sandbox-boundary."""
    readme = SEED_PREFIX / "README.md"
    assert readme.is_file(), "seed README.md missing"
    text = readme.read_text(encoding="utf-8")
    assert "Tag-59" in text
    assert "Cut-3" in text or "cut-3" in text.lower()
    assert "sandbox-boundary" in text.lower() or "Sandbox-Boundary" in text
    assert "wakir-protocol" in text


# ---------------------------------------------------------------------------
# Invariant 2: Apache-2.0 header on every seed file
# ---------------------------------------------------------------------------


def test_seed_files_carry_apache_2_0_spdx_header(audit_mod):
    """Each seed file must show Apache-2.0 SPDX-License-Identifier on a top line."""
    offenders: list[str] = []
    for pair in audit_mod.MIRROR_PAIRS:
        seed_file = SEED_PREFIX / pair.protocol_path
        head = "\n".join(seed_file.read_text(encoding="utf-8").splitlines()[:10])
        if "SPDX-License-Identifier" not in head or "Apache-2.0" not in head:
            offenders.append(pair.protocol_path)
    assert not offenders, f"seed files without Apache-2.0 SPDX header: {offenders}"


# ---------------------------------------------------------------------------
# Invariant 3: canonical SHA equality runtime-side vs seed
# ---------------------------------------------------------------------------


def test_seed_canonical_sha_equals_runtime_canonical_sha(audit_mod):
    """Seed canonical bytes must hash identical to runtime-side originals."""
    mismatches: list[tuple[str, str, str]] = []
    for pair in audit_mod.MIRROR_PAIRS:
        runtime_file = REPO_ROOT / pair.runtime_path
        seed_file = SEED_PREFIX / pair.protocol_path
        runtime_sha = audit_mod.sha256_canonical(
            runtime_file.read_bytes(), pair.normaliser
        )
        seed_sha = audit_mod.sha256_canonical(
            seed_file.read_bytes(), pair.normaliser
        )
        if runtime_sha != seed_sha:
            mismatches.append((pair.runtime_path, runtime_sha, seed_sha))
    assert not mismatches, f"seed canonical SHA drift: {mismatches}"


# ---------------------------------------------------------------------------
# Invariant 4: detect_protocol_mirror_seeds semantics
# ---------------------------------------------------------------------------


def _build_runtime_with_seed(audit_mod, tmp_path: Path, include_seed: bool):
    """Create a minimal runtime checkout with the four mirror-pair files."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for pair in audit_mod.MIRROR_PAIRS:
        rel = runtime / pair.runtime_path
        rel.parent.mkdir(parents=True, exist_ok=True)
        rel.write_bytes(
            b"# SPDX-License-Identifier: Apache-2.0\n# body line\nhello\n"
        )
        if include_seed:
            seed_rel = (
                runtime / audit_mod.PROTOCOL_MIRROR_SEED_PREFIX / pair.protocol_path
            )
            seed_rel.parent.mkdir(parents=True, exist_ok=True)
            seed_rel.write_bytes(
                b"# SPDX-License-Identifier: Apache-2.0\n# body line\nhello\n"
            )
    return runtime


def test_detect_emits_marker_per_present_seed(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=True)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    assert len(result.seed_markers) == len(audit_mod.MIRROR_PAIRS)
    for m in result.seed_markers:
        assert m.marker == audit_mod.SYNC_MARKER_PROTOCOL_SEED_READY
        assert m.seed_relpath.startswith(audit_mod.PROTOCOL_MIRROR_SEED_PREFIX)
        assert m.canonical_match is True


def test_detect_emits_no_markers_when_seed_tree_absent(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=False)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    assert result.seed_markers == ()


def test_seed_marker_never_flips_pair_status(audit_mod, tmp_path):
    """Presence of seed must not alter the underlying pair verdict."""
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=True)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    # protocol side intentionally empty: every pair must remain
    # ``missing-protocol`` despite the seed being present.
    for r in result.results:
        assert r.status == audit_mod.STATUS_MISSING_PROTOCOL
    assert result.verdict == audit_mod.VERDICT_MIRROR_DRIFT


def test_seed_marker_canonical_match_false_on_seed_drift(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=True)
    pair = audit_mod.MIRROR_PAIRS[0]
    seed_rel = (
        runtime / audit_mod.PROTOCOL_MIRROR_SEED_PREFIX / pair.protocol_path
    )
    # Mutate the seed body so its canonical SHA diverges from the
    # runtime-side original.
    seed_rel.write_bytes(b"# SPDX-License-Identifier: Apache-2.0\nDRIFTED BODY\n")
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    by_path = {m.protocol_path: m for m in result.seed_markers}
    assert by_path[pair.protocol_path].canonical_match is False
    # Other markers should still match.
    for other in audit_mod.MIRROR_PAIRS[1:]:
        assert by_path[other.protocol_path].canonical_match is True


# ---------------------------------------------------------------------------
# Invariant 5: JSON serialisation surface
# ---------------------------------------------------------------------------


def test_render_json_includes_seed_markers_block(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=True)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    payload = json.loads(audit_mod.render_json(result))
    assert "seed_markers" in payload
    assert len(payload["seed_markers"]) == len(audit_mod.MIRROR_PAIRS)
    for m in payload["seed_markers"]:
        assert m["marker"] == "protocol-mirror-seed-ready"
        assert m["seed_relpath"].startswith(
            "wirelang/specs/protocol-mirror-seed"
        )
        assert isinstance(m["canonical_match"], bool)


# ---------------------------------------------------------------------------
# Invariant 6: markdown renderer surface
# ---------------------------------------------------------------------------


def test_render_markdown_includes_seed_marker_table_when_present(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=True)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    md = audit_mod.render_markdown(result)
    assert "Tag-59 Cut-3 Protocol-Mirror-Seed markers" in md
    assert "protocol-mirror-seed-ready" in md


def test_render_markdown_omits_seed_section_when_no_markers(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=False)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    md = audit_mod.render_markdown(result)
    assert "Tag-59 Cut-3 Protocol-Mirror-Seed markers" not in md


# ---------------------------------------------------------------------------
# Invariant 7: GitHub annotations -> ::notice (not ::error)
# ---------------------------------------------------------------------------


def test_github_annotations_use_notice_for_seed_markers(audit_mod, tmp_path):
    runtime = _build_runtime_with_seed(audit_mod, tmp_path, include_seed=True)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    result = audit_mod.audit(runtime, protocol)
    annotations = audit_mod.render_github_annotations(result)
    notice_lines = [ln for ln in annotations if ln.startswith("::notice")]
    error_lines_for_seed = [
        ln for ln in annotations
        if ln.startswith("::error") and "Cut-3" in ln
    ]
    assert len(notice_lines) >= len(audit_mod.MIRROR_PAIRS)
    assert not error_lines_for_seed, (
        "Tag-59 seed markers must never surface as ::error annotations"
    )
