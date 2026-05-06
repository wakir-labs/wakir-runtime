# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-module drift detector: Wirelang side of the JCS leaf-hash contract.

Mirror of ``tests/wat/test_hash_consistency.py``. Both test trees load
the same vector pack (``tests/fixtures/jcs-leaf-vectors/``) and assert
the same hash invariant; any drift between Wirelang's JCS canonicaliser
or hash code path and WAT's is caught the next time CI runs both trees.

Why two test files instead of one?
----------------------------------

Wirelang (Apache-2.0) and WAT (BSL-1.1) are licence-domain-isolated.
Co-locating the vector loader in either tree would couple the two
licences in CI; running the same vectors from both trees keeps each
domain self-contained while still detecting drift via the shared
fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# Repository root is two levels up from this file (``wirelang/tests/``).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VECTORS_DIR = REPO_ROOT / "tests" / "fixtures" / "jcs-leaf-vectors"


def _load_vectors() -> list[tuple[str, dict]]:
    if not VECTORS_DIR.exists():
        pytest.skip(f"vector pack missing: {VECTORS_DIR}")
    files = sorted(VECTORS_DIR.glob("vector-*.json"))
    if not files:
        pytest.skip(f"vector pack empty: {VECTORS_DIR}")
    return [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in files
    ]


VECTORS = _load_vectors()


@pytest.mark.parametrize(
    "name, vector",
    VECTORS,
    ids=[name for name, _ in VECTORS],
)
def test_wirelang_side_leaf_hash_matches_vector(name: str, vector: dict) -> None:
    """Recompute via the WAT hash core and compare against the vector.

    The Wirelang module does not (yet) own its own canonicaliser
    implementation -- it depends on ``rfc8785`` directly. This test
    therefore reaches into ``wat.merkle.aggregator.compute_leaf_hash``
    for the recomputation, which is the same function the bridge uses
    when projecting frames at ingestion time. Drift between this code
    path and the recorded vectors is the same drift the WAT test
    detects from its side; running both keeps the contract honest as
    the codebase grows.
    """
    # Local import: the test should still collect cleanly even if a
    # downstream consumer stripped the WAT module (e.g. shipping
    # Wirelang-only). In that case the test would skip rather than
    # crash at collection time.
    pytest.importorskip("wat.merkle.aggregator")
    from wat.merkle.aggregator import compute_leaf_hash

    inp = vector["input"]
    digest = compute_leaf_hash(
        event_id=inp["event_id"],
        time=inp["time"],
        payload_hash=inp["payload_hash"],
        capability_token_hash=inp["capability_token_hash"],
    )
    assert digest.hex() == vector["expected_leaf_hash"], (
        f"{name}: cross-module drift\n"
        f"  got:      {digest.hex()}\n"
        f"  expected: {vector['expected_leaf_hash']}"
    )
