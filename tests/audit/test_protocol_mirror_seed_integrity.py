# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Integrity invariants for the protocol mirror seed.

`wirelang/specs/protocol-mirror-seed/schemas/` holds the runtime-side
copy of the four canonical Wirelang layer schemas that `wakir-protocol`
mirrors. The mirror only has evidentiary value while it is provably a
copy, so this module pins the properties that make it one:

  * the four canonical seed files exist,
  * each is well-formed JSON carrying a Wirelang schema `$id`,
  * each carries the Apache-2.0 SPDX posture of the seed tree,
  * each is **byte-identical** to its counterpart under
    `wirelang/schemas/` — the actual drift invariant,
  * the seed README names every seed file, so a reader of the mirror
    can tell what it is supposed to contain.

Predecessor: this file replaces a suite that additionally pinned a
one-off re-sync *score* ("92 / ENFORCE-READY") produced by
`tooling/ci/audit_cross_repo_drift_allowlist.py`. That helper was
removed with the dead Phase-3c tooling in PR #526, which left the old
module with an unsatisfiable import and blocked collection of the whole
`tests/audit/` directory. The score pinned a migration state that no
longer exists; the invariants above survive it, so they are carried
forward here and the scoring suite is archived under
`docs/archive/dead-tests/`.

Hermetic: stdlib + pytest only, no network, no subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_ROOT = REPO_ROOT / "wirelang" / "specs" / "protocol-mirror-seed"
SEED_SCHEMAS_DIR = SEED_ROOT / "schemas"
RUNTIME_SCHEMAS_DIR = REPO_ROOT / "wirelang" / "schemas"

SEED_FILES = (
    "layer-0-transport.json",
    "layer-1-wire.json",
    "layer-2-semantic.json",
    "aip-document.json",
)

SCHEMA_URI_PREFIX = "https://wakir.dev/wirelang/schema/"


@pytest.mark.parametrize("seed_name", SEED_FILES)
def test_seed_file_exists(seed_name: str) -> None:
    """Each canonical mirror-seed file is present on disk."""
    assert (SEED_SCHEMAS_DIR / seed_name).is_file(), (
        f"missing seed file: {SEED_SCHEMAS_DIR / seed_name}"
    )


@pytest.mark.parametrize("seed_name", SEED_FILES)
def test_seed_file_is_valid_json_with_wirelang_id(seed_name: str) -> None:
    """Seed files are well-formed JSON with a Wirelang schema `$id`."""
    doc = json.loads((SEED_SCHEMAS_DIR / seed_name).read_text(encoding="utf-8"))
    assert "$id" in doc, f"{seed_name}: missing $id"
    assert doc["$id"].startswith(SCHEMA_URI_PREFIX), (
        f"{seed_name}: $id is not a Wirelang schema URI"
    )


@pytest.mark.parametrize("seed_name", SEED_FILES)
def test_seed_file_has_apache_spdx_header(seed_name: str) -> None:
    """Seed files match the seed-tree Apache-2.0 SPDX posture."""
    doc = json.loads((SEED_SCHEMAS_DIR / seed_name).read_text(encoding="utf-8"))
    # REUSE-IgnoreStart
    assert doc.get("x-spdx-license-identifier") == "Apache-2.0", (
        f"{seed_name}: SPDX-License-Identifier is not Apache-2.0"
    )
    # REUSE-IgnoreEnd


@pytest.mark.parametrize("seed_name", SEED_FILES)
def test_seed_file_byte_identical_to_runtime_schema(seed_name: str) -> None:
    """The seed is a byte-exact mirror of the runtime schema.

    This is the invariant the mirror exists : any divergence means a
    schema landed on one side only, and the cross-repo compatibility
    gate would be comparing against a stale copy.
    """
    seed_bytes = (SEED_SCHEMAS_DIR / seed_name).read_bytes()
    runtime_bytes = (RUNTIME_SCHEMAS_DIR / seed_name).read_bytes()
    assert seed_bytes == runtime_bytes, (
        f"{seed_name}: seed bytes differ from runtime schema — mirror drift"
    )


def test_seed_readme_names_every_seed_file() -> None:
    """The seed README documents the full seed inventory."""
    readme = (SEED_ROOT / "README.md").read_text(encoding="utf-8")
    for seed_name in SEED_FILES:
        assert seed_name in readme, f"seed README does not name {seed_name}"


def test_seed_tree_holds_no_unexpected_schema_files() -> None:
    """The seed schema directory holds exactly the canonical inventory.

    An extra file here is either an un-mirrored addition or a leftover;
    both make the "this is a mirror" claim false.
    """
    on_disk = sorted(p.name for p in SEED_SCHEMAS_DIR.glob("*.json"))
    assert on_disk == sorted(SEED_FILES), (
        f"seed schema inventory drifted: {on_disk}"
    )
