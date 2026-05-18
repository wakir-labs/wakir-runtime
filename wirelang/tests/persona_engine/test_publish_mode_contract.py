# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-41 Bug-42 publish/subscribe surface contract.

These tests close out the Bug-42 substrate-drift identified in
Mira's Tag-41 brief: the existing Sprint-Pengine-13 substrate
shipped the subscribe-mode resolver but did NOT enforce the
spec wirelang-spec-v0-2 §13.2 compatibility matrix at bring-up.
A broken-pipe pair (core publisher + jetstream-pull subscriber)
silently dropped messages even though the Sprint-13 substrate
named the failure mode.

Tag-41 fix
----------
- :mod:`wirelang.persona_engine.publish_mode_contract` declares the
  publish-mode constants, the compatibility matrix, and the
  :func:`require_compatible` gate.
- :mod:`wirelang.persona_engine.cli` calls ``require_compatible`` at
  bring-up; broken-pipe pairs exit with EXIT_ENV_MISCONFIG.
- :mod:`wirelang.cli.bridge_forward` exposes ``--publish-mode``
  (Adapter B substrate) so operators can rewrite producers to
  ``js.publish`` against a captured JetStream stream.

Tests below cover:

- §1 mode-constant invariants + compatibility-matrix correctness
  (eight pairs × verdict shape)
- §2 :func:`require_compatible` raises :class:`SurfaceMismatchError`
  on broken pairs and tolerates fan-out only with explicit opt-in
- §3 env-var resolver parses ``WAKIR_NATS_PUBLISH_MODE`` defaults
  and rejects unknown values
- §4 subscribe-surface mapper translates the four
  :mod:`nats_subscribe_loop` mode-strings to surfaces correctly
- §5 ``bridge_forward`` ``--publish-mode jetstream`` requires
  ``--jetstream-stream`` (fail-fast contract)
- §6 dry-run preserves envelope-line position for byte-stability
  with sprint-10 tests, while emitting publish_mode trailer
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from wirelang.persona_engine.publish_mode_contract import (
    CompatibilityVerdict,
    DEFAULT_PUBLISH_MODE,
    PUBLISH_MODE_CORE,
    PUBLISH_MODE_ENV_VAR,
    PUBLISH_MODE_JETSTREAM,
    SUBSCRIBE_SURFACE_CORE,
    SUBSCRIBE_SURFACE_JS_PULL,
    SUBSCRIBE_SURFACE_JS_PUSH,
    SurfaceMismatchError,
    VALID_PUBLISH_MODES,
    VALID_SUBSCRIBE_SURFACES,
    VERDICT_BROKEN,
    VERDICT_COMPATIBLE,
    VERDICT_FANOUT,
    check_compatibility,
    require_compatible,
    resolve_publish_mode,
    resolve_subscribe_surface_from_subscribe_mode,
)


# ---------------------------------------------------------------------------
# §1 — constants + matrix invariants
# ---------------------------------------------------------------------------


def test_constants_match_spec_string_literals():
    """Tag-41 string-literal contract — spec §13.1 mode strings.

    These literals are operator-facing (env-vars, CLI flags, runbook
    docs). Any drift requires an explicit ADR/spec patch.
    """
    assert PUBLISH_MODE_CORE == "core"
    assert PUBLISH_MODE_JETSTREAM == "jetstream"
    assert SUBSCRIBE_SURFACE_CORE == "core"
    assert SUBSCRIBE_SURFACE_JS_PUSH == "jetstream-push"
    assert SUBSCRIBE_SURFACE_JS_PULL == "jetstream-pull"
    assert DEFAULT_PUBLISH_MODE == PUBLISH_MODE_CORE
    assert PUBLISH_MODE_ENV_VAR == "WAKIR_NATS_PUBLISH_MODE"
    assert set(VALID_PUBLISH_MODES) == {
        PUBLISH_MODE_CORE, PUBLISH_MODE_JETSTREAM,
    }
    assert set(VALID_SUBSCRIBE_SURFACES) == {
        SUBSCRIBE_SURFACE_CORE,
        SUBSCRIBE_SURFACE_JS_PUSH,
        SUBSCRIBE_SURFACE_JS_PULL,
    }


def test_compatibility_matrix_hard_yes_pairs():
    """Spec §13.2 — three hard-compatible pairs.

    (core, core), (jetstream, jetstream-push), (jetstream, jetstream-pull).
    """
    for pair in (
        (PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_CORE),
        (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_JS_PUSH),
        (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_JS_PULL),
    ):
        verdict = check_compatibility(*pair)
        assert verdict.verdict == VERDICT_COMPATIBLE, pair
        assert verdict.failure_mode_id is None
        assert verdict.recommended_adapter is None


def test_compatibility_matrix_fanout_pair():
    """Spec §13.2 — (jetstream, core) is fan-out-dependent.

    Not hard YES (server config governs fan-out); not hard NO either.
    The diagnosis must mention fan-out so operators know.
    """
    verdict = check_compatibility(
        PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_CORE,
    )
    assert verdict.verdict == VERDICT_FANOUT
    assert "fan-out" in verdict.diagnosis.lower()


def test_compatibility_matrix_broken_pairs_classify_failure_modes():
    """Spec §13.3 — F-1 and F-2 silent-drop modes.

    Both broken pairs must surface a recommended_adapter pointing to
    Adapter A (stream-mirror) or Adapter B (producer-rewrite) so
    operator runbooks can remediate from the verdict alone.
    """
    f1 = check_compatibility(
        PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_JS_PULL,
    )
    assert f1.verdict == VERDICT_BROKEN
    assert f1.failure_mode_id == "F-1"
    assert f1.recommended_adapter is not None
    assert "Adapter A" in f1.recommended_adapter
    assert "Adapter B" in f1.recommended_adapter

    f2 = check_compatibility(
        PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_JS_PUSH,
    )
    assert f2.verdict == VERDICT_BROKEN
    assert f2.failure_mode_id == "F-2"
    assert f2.recommended_adapter is not None


def test_check_compatibility_rejects_unknown_modes():
    with pytest.raises(ValueError, match="publish_mode must be one of"):
        check_compatibility("nonsense", SUBSCRIBE_SURFACE_CORE)
    with pytest.raises(ValueError, match="subscribe_surface must be one of"):
        check_compatibility(PUBLISH_MODE_CORE, "nonsense")


# ---------------------------------------------------------------------------
# §2 — require_compatible enforcement
# ---------------------------------------------------------------------------


def test_require_compatible_accepts_hard_yes_pairs():
    """Hard-YES pairs must not raise."""
    for pair in (
        (PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_CORE),
        (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_JS_PULL),
        (PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_JS_PUSH),
    ):
        verdict = require_compatible(*pair)
        assert verdict.verdict == VERDICT_COMPATIBLE, pair


def test_require_compatible_raises_on_broken_pipe():
    """F-1 broken pipe (core publisher + jetstream-pull subscriber).

    This is the exact Bug-42 silent-drop scenario the Tag-41 fix
    intercepts at bring-up.
    """
    with pytest.raises(SurfaceMismatchError) as excinfo:
        require_compatible(
            PUBLISH_MODE_CORE, SUBSCRIBE_SURFACE_JS_PULL,
        )
    verdict = excinfo.value.verdict
    assert isinstance(verdict, CompatibilityVerdict)
    assert verdict.failure_mode_id == "F-1"
    assert "broken pipe" in verdict.diagnosis


def test_require_compatible_rejects_fanout_by_default():
    """Fan-out dependence MUST NOT be treated as compatible.

    Spec §13.2 footnote ¹ — operators must explicitly opt-in via
    ``allow_fanout=True`` if their NATS server is configured for
    fan-out.
    """
    with pytest.raises(SurfaceMismatchError):
        require_compatible(
            PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_CORE,
        )


def test_require_compatible_allows_fanout_with_explicit_opt_in():
    verdict = require_compatible(
        PUBLISH_MODE_JETSTREAM, SUBSCRIBE_SURFACE_CORE,
        allow_fanout=True,
    )
    assert verdict.verdict == VERDICT_FANOUT


# ---------------------------------------------------------------------------
# §3 — env-var resolver
# ---------------------------------------------------------------------------


def test_resolve_publish_mode_defaults_to_core():
    assert resolve_publish_mode(env={}) == PUBLISH_MODE_CORE
    assert resolve_publish_mode(env={PUBLISH_MODE_ENV_VAR: ""}) == PUBLISH_MODE_CORE


def test_resolve_publish_mode_honours_env_var():
    assert resolve_publish_mode(
        env={PUBLISH_MODE_ENV_VAR: "jetstream"},
    ) == PUBLISH_MODE_JETSTREAM


def test_resolve_publish_mode_rejects_unknown():
    with pytest.raises(ValueError, match="WAKIR_NATS_PUBLISH_MODE"):
        resolve_publish_mode(env={PUBLISH_MODE_ENV_VAR: "kafka"})


# ---------------------------------------------------------------------------
# §4 — subscribe-mode → surface mapping
# ---------------------------------------------------------------------------


def test_subscribe_surface_mapping_for_all_four_subscribe_modes():
    """All four documented subscribe-modes map to a surface."""
    assert resolve_subscribe_surface_from_subscribe_mode(
        "core-callback",
    ) == SUBSCRIBE_SURFACE_CORE
    assert resolve_subscribe_surface_from_subscribe_mode(
        "core-iterator",
    ) == SUBSCRIBE_SURFACE_CORE
    assert resolve_subscribe_surface_from_subscribe_mode(
        "jetstream-pull",
    ) == SUBSCRIBE_SURFACE_JS_PULL
    assert resolve_subscribe_surface_from_subscribe_mode(
        "jetstream-push",
    ) == SUBSCRIBE_SURFACE_JS_PUSH


def test_subscribe_surface_mapping_rejects_unknown():
    with pytest.raises(ValueError, match="unknown subscribe_mode"):
        resolve_subscribe_surface_from_subscribe_mode("websocket")


# ---------------------------------------------------------------------------
# §5 — bridge-forward CLI publish-mode contract
# ---------------------------------------------------------------------------


def _run_bridge_forward(argv, *, env=None) -> tuple[int, str, str]:
    """Run bridge_forward.main capturing stdout + stderr."""
    from wirelang.cli.bridge_forward import main
    out = io.StringIO()
    err = io.StringIO()
    saved_env = {}
    if env is not None:
        for k, v in env.items():
            saved_env[k] = os.environ.get(k)
            os.environ[k] = v
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
    finally:
        for k, prev in saved_env.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
    return rc, out.getvalue(), err.getvalue()


def test_bridge_forward_jetstream_publish_mode_requires_stream(tmp_path: Path):
    """Tag-41 Adapter-B contract — --publish-mode jetstream needs --jetstream-stream.

    Operator dry-run skips the live path so we exercise the live-path
    branch by NOT passing --dry-run; the resolver should fail-fast
    BEFORE nats-py is imported, giving an actionable error.
    """
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("hello", encoding="utf-8")
    rc, _out, err = _run_bridge_forward([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--ts-utc", "2026-05-18T00:00:00Z",
        "--publish-mode", "jetstream",
        # NO --jetstream-stream and NO env var
    ], env={"WAKIR_NATS_JETSTREAM_STREAM": ""})
    assert rc == 1
    assert "--publish-mode jetstream" in err
    assert "jetstream-stream" in err


def test_bridge_forward_dry_run_emits_publish_mode_trailer(tmp_path: Path):
    """Tag-41 dry-run records the operator's publish-mode declaration.

    Trailing comment line lets operators audit what surface they
    would have hit in live mode. Envelope position (line 1) is
    preserved for Sprint-10 byte-stable test parity.
    """
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("hello", encoding="utf-8")
    rc, out, _err = _run_bridge_forward([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--ts-utc", "2026-05-18T00:00:00Z",
        "--publish-mode", "jetstream",
        "--jetstream-stream", "WAKIR_AGENT_TASK",
        "--dry-run",
    ])
    assert rc == 0
    lines = out.strip().split("\n")
    # Line 0: subject comment (Sprint-10 contract).
    assert lines[0].startswith("# subject:")
    # Line 1: envelope (Sprint-10 byte-stable position).
    envelope = json.loads(lines[1])
    assert envelope["persona_id"] == "tomas"
    # Trailer: publish_mode comment.
    assert any(
        line == "# publish_mode: jetstream" for line in lines
    ), lines


def test_bridge_forward_dry_run_default_publish_mode_is_core(tmp_path: Path):
    """Without --publish-mode and without env-var, defaults to core."""
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("hi", encoding="utf-8")
    rc, out, _err = _run_bridge_forward([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--ts-utc", "2026-05-18T00:00:00Z",
        "--dry-run",
    ], env={"WAKIR_NATS_PUBLISH_MODE": ""})
    assert rc == 0
    assert "# publish_mode: core" in out


# ---------------------------------------------------------------------------
# §6 — symmetry-invariant matrix sweep (parametrised)
# ---------------------------------------------------------------------------


_ALL_PAIRS = [
    (p, s)
    for p in VALID_PUBLISH_MODES
    for s in VALID_SUBSCRIBE_SURFACES
]


@pytest.mark.parametrize("pair", _ALL_PAIRS)
def test_check_compatibility_returns_verdict_for_every_pair(pair):
    """Total-function invariant — every (mode, surface) pair has a verdict.

    No silent KeyError, no None-return. The matrix is exhaustive
    over the declared mode-product.
    """
    verdict = check_compatibility(*pair)
    assert isinstance(verdict, CompatibilityVerdict)
    assert verdict.verdict in (
        VERDICT_COMPATIBLE, VERDICT_FANOUT, VERDICT_BROKEN,
    )
    assert verdict.publish_mode == pair[0]
    assert verdict.subscribe_surface == pair[1]
    # Diagnosis is always populated — operator log-line ready.
    assert verdict.diagnosis
