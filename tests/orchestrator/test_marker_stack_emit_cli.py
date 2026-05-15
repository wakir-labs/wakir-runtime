# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``wirelang.cli.marker_stack_emit`` and the
``bin/wakir-marker-stack-emit`` CLI entrypoint (Sprint-Pengine-7
Tag-5 OI-PILOT-3).

Coverage axes (T-EMIT-01..12):

1. ``jcs_dumps`` is byte-deterministic on the same logical payload
   (sorted keys + compact separators).
2. ``jcs_dumps`` rejects non-Mapping input at the top level.
3. ``sha256_hex`` returns 64-char hex.
4. ``compute_chain_hash`` rejects malformed-length inputs.
5. ``compute_chain_hash`` is deterministic on inputs (same in →
   same out).
6. ``compute_chain_hash`` chains: H(prev || curr) depends on
   prev — flipping prev changes the result.
7. ``build_envelope`` happy-path returns the canonical schema +
   marker_kind + payload + hashes.
8. ``build_envelope`` rejects unknown marker_kind.
9. ``build_envelope`` rejects empty org_id.
10. ``envelope_to_jcs_bytes`` produces sorted-keys compact JSON.
11. CLI ``main`` with ``--mode stdout --payload-stdin`` writes one
    JCS line and exits 0.
12. CLI ``main`` with ``--marker-kind custom`` round-trips through
    the chain: passing one envelope's ``payload_hash`` as the next
    envelope's ``--chain-prev-hash`` produces a hash-chain whose
    chain_hash is reproducible via :func:`compute_chain_hash`.

All tests are hermetic: no NATS, no filesystem mutation outside
``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mod():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from wirelang.cli import marker_stack_emit
    return marker_stack_emit


# ---------------------------------------------------------------------------
# T-EMIT-01..03 — JCS + hash primitives
# ---------------------------------------------------------------------------


def test_jcs_dumps_is_byte_deterministic_on_same_logical_payload(mod):
    a = {"alpha": 1, "beta": [3, 2, 1], "gamma": "string"}
    b = {"gamma": "string", "alpha": 1, "beta": [3, 2, 1]}
    assert mod.jcs_dumps(a) == mod.jcs_dumps(b)
    # Sorted keys + compact separators → no whitespace.
    out = mod.jcs_dumps(a)
    assert b" " not in out
    assert out.startswith(b'{"alpha":')


def test_jcs_dumps_rejects_non_mapping_at_top_level(mod):
    with pytest.raises(ValueError):
        mod.jcs_dumps([1, 2, 3])  # type: ignore[arg-type]


def test_sha256_hex_returns_64_char_hex(mod):
    digest = mod.sha256_hex(b"hello")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# ---------------------------------------------------------------------------
# T-EMIT-04..06 — chain hash
# ---------------------------------------------------------------------------


def test_compute_chain_hash_rejects_malformed_length_inputs(mod):
    with pytest.raises(ValueError):
        mod.compute_chain_hash("tooshort", "a" * 64)
    with pytest.raises(ValueError):
        mod.compute_chain_hash("a" * 64, "tooshort")


def test_compute_chain_hash_is_deterministic_on_inputs(mod):
    a = mod.compute_chain_hash("a" * 64, "b" * 64)
    b = mod.compute_chain_hash("a" * 64, "b" * 64)
    assert a == b


def test_compute_chain_hash_chains_dependency_on_prev(mod):
    a = mod.compute_chain_hash("a" * 64, "b" * 64)
    b = mod.compute_chain_hash("c" * 64, "b" * 64)
    assert a != b


# ---------------------------------------------------------------------------
# T-EMIT-07..09 — build_envelope
# ---------------------------------------------------------------------------


def test_build_envelope_happy_path_returns_canonical_shape(mod):
    env = mod.build_envelope(
        marker_kind="setup",
        org_id="acme",
        persona_id="tomas",
        payload={"phase": "pilot", "step": 4},
        emitted_at="2026-05-15T12:00:00Z",
        chain_prev_hash=mod.CHAIN_ZERO_SENTINEL,
    )
    assert env["schema"] == mod.ENVELOPE_SCHEMA
    assert env["marker_kind"] == "setup"
    assert env["org_id"] == "acme"
    assert env["persona_id"] == "tomas"
    assert env["emitted_at"] == "2026-05-15T12:00:00Z"
    assert env["payload"] == {"phase": "pilot", "step": 4}
    assert len(env["payload_hash"]) == 64
    assert env["chain_prev_hash"] == mod.CHAIN_ZERO_SENTINEL
    # chain_hash matches the recomputed chain step.
    assert env["chain_hash"] == mod.compute_chain_hash(
        mod.CHAIN_ZERO_SENTINEL, env["payload_hash"]
    )


def test_build_envelope_rejects_unknown_marker_kind(mod):
    with pytest.raises(ValueError):
        mod.build_envelope(
            marker_kind="nonsense",
            org_id="acme",
            persona_id="",
            payload={},
            emitted_at="2026-05-15T12:00:00Z",
            chain_prev_hash=mod.CHAIN_ZERO_SENTINEL,
        )


def test_build_envelope_rejects_empty_org_id(mod):
    with pytest.raises(ValueError):
        mod.build_envelope(
            marker_kind="setup",
            org_id="",
            persona_id="",
            payload={},
            emitted_at="2026-05-15T12:00:00Z",
            chain_prev_hash=mod.CHAIN_ZERO_SENTINEL,
        )


# ---------------------------------------------------------------------------
# T-EMIT-10 — envelope_to_jcs_bytes produces sorted-keys compact JSON
# ---------------------------------------------------------------------------


def test_envelope_to_jcs_bytes_is_sorted_keys_compact(mod):
    env = mod.build_envelope(
        marker_kind="custom",
        org_id="acme",
        persona_id="",
        payload={"k": "v"},
        emitted_at="2026-05-15T12:00:00Z",
        chain_prev_hash=mod.CHAIN_ZERO_SENTINEL,
    )
    canonical = mod.envelope_to_jcs_bytes(env)
    text = canonical.decode("utf-8")
    # Sorted keys: schema appears after payload_hash alphabetically?
    # No — sort order is lexicographic; "chain_hash" < "chain_prev_hash"
    # < "emitted_at" < "marker_kind" < "org_id" < "payload" <
    # "payload_hash" < "persona_id" < "schema". Confirm:
    keys_in_order = []
    decoded = json.loads(text)
    # json.loads preserves insertion order in CPython 3.7+; the
    # canonical bytes are sorted by key.
    keys_in_order = list(decoded.keys())
    # The first key must be the smallest-lexicographic key.
    assert keys_in_order[0] == "chain_hash"
    assert keys_in_order[-1] == "schema"


# ---------------------------------------------------------------------------
# T-EMIT-11 — CLI main with --mode stdout writes one JCS line
# ---------------------------------------------------------------------------


def test_cli_main_stdout_writes_one_jcs_line_and_exits_zero(
    mod, tmp_path, capsys, monkeypatch
):
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({"phase": "pilot", "step": 4}),
        encoding="utf-8",
    )
    rc = mod.main(
        [
            "--marker-kind", "setup",
            "--org-id", "acme",
            "--persona-id", "tomas",
            "--payload-file", str(payload_path),
            "--emitted-at", "2026-05-15T12:00:00Z",
            "--mode", "stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip().count("\n") == 0, captured.out
    # Decodes as a JSON object carrying the documented schema.
    line = captured.out.strip()
    decoded = json.loads(line)
    assert decoded["schema"] == mod.ENVELOPE_SCHEMA
    assert decoded["marker_kind"] == "setup"
    assert decoded["org_id"] == "acme"
    assert decoded["persona_id"] == "tomas"


# ---------------------------------------------------------------------------
# T-EMIT-12 — hash-chain round-trip via --chain-prev-hash
# ---------------------------------------------------------------------------


def test_cli_main_round_trip_chain_via_chain_prev_hash_flag(
    mod, tmp_path, capsys
):
    payload_a = tmp_path / "a.json"
    payload_a.write_text(json.dumps({"seq": 1}), encoding="utf-8")
    rc_a = mod.main(
        [
            "--marker-kind", "custom",
            "--org-id", "acme",
            "--payload-file", str(payload_a),
            "--emitted-at", "2026-05-15T12:00:00Z",
            "--mode", "stdout",
        ]
    )
    assert rc_a == 0
    line_a = capsys.readouterr().out.strip()
    env_a = json.loads(line_a)
    # First marker: chain_prev_hash is the zero-sentinel.
    assert env_a["chain_prev_hash"] == mod.CHAIN_ZERO_SENTINEL

    payload_b = tmp_path / "b.json"
    payload_b.write_text(json.dumps({"seq": 2}), encoding="utf-8")
    rc_b = mod.main(
        [
            "--marker-kind", "custom",
            "--org-id", "acme",
            "--payload-file", str(payload_b),
            "--emitted-at", "2026-05-15T12:00:01Z",
            "--mode", "stdout",
            "--chain-prev-hash", env_a["payload_hash"],
        ]
    )
    assert rc_b == 0
    line_b = capsys.readouterr().out.strip()
    env_b = json.loads(line_b)

    # The second marker's chain_prev_hash matches the first
    # marker's payload_hash; the chain_hash is reproducible.
    assert env_b["chain_prev_hash"] == env_a["payload_hash"]
    expected_chain_hash = mod.compute_chain_hash(
        env_a["payload_hash"], env_b["payload_hash"]
    )
    assert env_b["chain_hash"] == expected_chain_hash
