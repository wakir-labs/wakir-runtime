# SPDX-License-Identifier: BUSL-1.1
"""Tests for v907_verify (spec §3.7.2.2 #1, §5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wirelang.persona_engine.v907_verify import (
    PersonaHashComputeError,
    PersonaHashDriftError,
    V907VerifyResult,
    compute_v907_pin,
    verify_v907_pin,
)


SAMPLE_AXIS_A = """---
name: tomas
description: Sample test persona for V-907 hashing
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: dev-engineering
---

Body content here — out of hash.
"""


def test_compute_v907_pin_returns_sha256_prefix():
    pin = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    assert pin.startswith("sha256:")
    assert len(pin) == len("sha256:") + 64


def test_compute_v907_pin_byte_deterministic():
    p1 = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    p2 = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    assert p1 == p2


def test_compute_v907_pin_body_does_not_affect_hash():
    """Per spec §5 the markdown body is out-of-hash."""
    alt = SAMPLE_AXIS_A.replace(
        "Body content here", "TOTALLY DIFFERENT BODY"
    )
    p1 = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    p2 = compute_v907_pin(alt.encode("utf-8"))
    assert p1 == p2


def test_compute_v907_pin_frontmatter_changes_affect_hash():
    alt = SAMPLE_AXIS_A.replace(
        "domain: dev-engineering", "domain: hr"
    )
    p1 = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    p2 = compute_v907_pin(alt.encode("utf-8"))
    assert p1 != p2


def test_compute_v907_pin_distinct_from_stub_format():
    """Real pin must be byte-distinct from the stub-mode 'sha256-stub:'
    prefix. The stub hashes raw bytes; real hashes JCS canonical subset."""
    import hashlib

    pin = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    stub = "sha256-stub:" + hashlib.sha256(
        SAMPLE_AXIS_A.encode("utf-8")
    ).hexdigest()
    assert not pin.startswith("sha256-stub:")
    assert pin != stub.replace("sha256-stub:", "sha256:")


def test_compute_v907_pin_no_frontmatter_raises():
    with pytest.raises(PersonaHashComputeError):
        compute_v907_pin(b"no front matter at all just markdown body")


def test_verify_v907_pin_no_expected_returns_unmatched_none(tmp_path):
    p = tmp_path / "tomas.md"
    p.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    result = verify_v907_pin("tomas", p, expected_pin=None)
    assert isinstance(result, V907VerifyResult)
    assert result.mode == "real"
    assert result.matched is None  # no expected supplied
    assert result.pin.startswith("sha256:")


def test_verify_v907_pin_match(tmp_path):
    p = tmp_path / "tomas.md"
    p.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    computed = compute_v907_pin(SAMPLE_AXIS_A.encode("utf-8"))
    result = verify_v907_pin("tomas", p, expected_pin=computed)
    assert result.matched is True


def test_verify_v907_pin_drift_raises(tmp_path):
    p = tmp_path / "tomas.md"
    p.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    bogus = "sha256:" + "0" * 64
    with pytest.raises(PersonaHashDriftError) as exc:
        verify_v907_pin("tomas", p, expected_pin=bogus)
    assert exc.value.expected == bogus
    assert exc.value.persona_id == "tomas"


def test_verify_v907_pin_empty_expected_treated_as_none(tmp_path):
    p = tmp_path / "tomas.md"
    p.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    result = verify_v907_pin("tomas", p, expected_pin="")
    assert result.matched is None


def test_verify_v907_pin_missing_file_raises(tmp_path):
    with pytest.raises(PersonaHashComputeError):
        verify_v907_pin("tomas", tmp_path / "nonexistent.md", None)


def test_persona_hash_drift_error_carries_context():
    err = PersonaHashDriftError(
        expected="sha256:" + "0" * 64,
        computed="sha256:" + "1" * 64,
        persona_id="tomas",
    )
    assert err.expected.startswith("sha256:0")
    assert err.computed.startswith("sha256:1")
    assert err.persona_id == "tomas"
