# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hash-consistency tests against the JCS leaf-hash test vector pack.

The five vectors in ``tests/fixtures/jcs-leaf-vectors/`` are the
shared cross-domain fixture between Wirelang (Apache-2.0) and WAT
(BSL-1.1). They pin down the JCS+SHA-256+hex-lower contract
(``docs/wat-hash-spec.md``) and the four-field B1 leaf shape
(``wirelang/specs/wat-leaf-projection.md``).

Every vector carries the full 9-field hour-spool tuple plus an
``expected_leaf_hash``. This test file consumes the same vectors from
the WAT side; ``wirelang/tests/test_jcs_drift.py`` does the same from
the Wirelang side. A drift between the two consumers (e.g. a JCS
canonicaliser version bump) is caught by both files diverging.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wat.merkle.aggregator import compute_leaf_hash


VECTORS_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "jcs-leaf-vectors"
)


def _load_vectors() -> list[tuple[str, dict]]:
    """Load every ``vector-*.json`` file in the fixture directory.

    Returns a list of ``(name, vector_dict)`` tuples sorted by file name
    so test parametrisation produces stable, ordered IDs in pytest
    output. A vector file without an ``input`` block is skipped with
    a clear error -- the file format is the contract.
    """
    if not VECTORS_DIR.exists():
        pytest.skip(f"vector pack missing: {VECTORS_DIR}")
    files = sorted(VECTORS_DIR.glob("vector-*.json"))
    if not files:
        pytest.skip(f"vector pack empty: {VECTORS_DIR}")
    out: list[tuple[str, dict]] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "input" in data, f"{path.name}: missing 'input' block"
        assert "expected_leaf_hash" in data, (
            f"{path.name}: missing 'expected_leaf_hash'"
        )
        out.append((path.stem, data))
    return out


VECTORS = _load_vectors()


@pytest.mark.parametrize(
    "name, vector",
    VECTORS,
    ids=[name for name, _ in VECTORS],
)
def test_leaf_hash_matches_vector(name: str, vector: dict) -> None:
    """Recompute the leaf hash and compare against the recorded value.

    Any mismatch indicates either:

    1. The reference canonicaliser drifted (rfc8785 version bump?).
    2. ``compute_leaf_hash`` drifted (signature or key-order change?).
    3. The vector file was edited without re-running the pre-computation
       step.

    All three are CI-blocking. If the spec genuinely needs to change,
    the vectors must be regenerated and committed in the same patch.
    """
    inp = vector["input"]
    digest = compute_leaf_hash(
        event_id=inp["event_id"],
        time=inp["time"],
        payload_hash=inp["payload_hash"],
        capability_token_hash=inp["capability_token_hash"],
    )
    assert digest.hex() == vector["expected_leaf_hash"], (
        f"{name}: leaf hash drift\n"
        f"  got:      {digest.hex()}\n"
        f"  expected: {vector['expected_leaf_hash']}"
    )


def test_vector_pack_count() -> None:
    """The Tag-6 spec pack ships with five vectors. Pin the count.

    Adding a vector is fine -- bump this expected count in the same
    patch. Removing one without updating the count would be silently
    dropping coverage, which we catch here.
    """
    assert len(VECTORS) == 5, (
        f"expected 5 JCS leaf-hash vectors, got {len(VECTORS)}"
    )


def test_vectors_carry_underscore_metadata_keys() -> None:
    """Sprint-Hygiene-Tag-2: enforce ``x-spdx-*`` top-level convention.

    The fixture format reserves ``x-spdx-license-identifier`` and
    ``x-spdx-file-copyright-text`` keys at the JSON-object top level for
    SPDX metadata. The ``x-`` prefix mirrors the OpenAPI/Swagger
    extension convention and is ignored by JSON-Schema validators while
    being machine-readable for license scanners (ADR-0061 §Folgeartefakte,
    external-audit recommendation #6). The previous ``_spdx`` /
    ``_copyright`` convention was abandoned because SPDX scanners did not
    recognise embedded SPDX expressions inside arbitrary string values.

    The check here is structural: every vector MUST carry
    ``x-spdx-license-identifier`` and ``x-spdx-file-copyright-text``.
    ``_notes`` (descriptive prose) is encouraged but not required.
    """
    for name, vector in VECTORS:
        assert "x-spdx-license-identifier" in vector, (
            f"{name}: missing 'x-spdx-license-identifier' metadata key "
            f"(Sprint-Hygiene-Tag-2 SPDX-migration convention)"
        )
        assert "x-spdx-file-copyright-text" in vector, (
            f"{name}: missing 'x-spdx-file-copyright-text' metadata key"
        )
        assert vector["x-spdx-license-identifier"] in {"Apache-2.0", "BUSL-1.1"}, (
            f"{name}: 'x-spdx-license-identifier' value "
            f"{vector['x-spdx-license-identifier']!r} not in allowed set"
        )
