# SPDX-License-Identifier: Apache-2.0
"""Operator CLI ``--target persona-v2`` test pack (Phase-1b Sprint-3 Tag-4).

Covers the ``wakir-persona migrate --target persona-v2`` surface
introduced de-facto by Phase-1b Sprint-3 Tag-3 (the
``PERSONA_SCHEMA_VERSION_LIST`` extension that wired ``persona-v2``
into the CLI's ``--target`` choices automatically).

Tag-4 scope (this file):

- ``--target persona-v2`` is accepted by argparse (single-step lift
  from a v9 input).
- ``--target persona-v2`` resolves a multi-step chain
  ``[V0ToV1Step(), V1ToV2Step()]`` from a v8 input.
- ``--expect-hash`` against ``PERSONA_HASH_PIN_V9_MIGRATED_TO_V2``
  matches for both single-step (v9 -> v2) and chain (v8 -> v2) entry
  points (M-1 direct-anchor through the operator surface).
- ``--target persona-v0`` is rejected at resolver time with exit
  code 1 (forward-only chain; v0 is in choices but no inverse step
  is registered — Default-Lock A-2).
- ``--emit-hash`` carries the v2-target pin on stderr.

Anchors:

- Sprint-3 Tag-1 sketch §3 (V0->V1->V2 forward chain design).
- Sprint-3 Tag-3 outbox §"Substanz-Bilanz" (V1ToV2Step + chain pins).
- Tag-4 box: "V0V1Step + V1V2Step Operator-CLI-Erweiterung —
  ``wakir-persona migrate`` jetzt mit ``--target persona-v2`` Option."

The CLI surface itself needed **no Python edit** for Tag-4 — the
``--target`` argparse choice list is sourced from
``PERSONA_SCHEMA_VERSION_LIST``, which Tag-3 already extended to
``("persona-v0", "persona-v1", "persona-v2")``. This test file is
therefore the explicit operator-surface contract: any future
regression that drops v2 from the CLI choices, or that breaks the
multi-step chain through the CLI dispatch path, will trip an
assertion here rather than only in the lower-level converter tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirelang.persona._internal.pin_pack_constants import (
    PERSONA_HASH_PIN_V8_MIGRATED_TO_V2,
    PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
)
from wirelang.persona.cli import (
    EXIT_MIGRATION_ERROR,
    build_parser,
    main,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "persona_definitions"
)
V8_FIXTURE = FIXTURE_DIR / "v8-persona-pre-framework.md"
V9_FIXTURE = FIXTURE_DIR / "v9-persona-framework-native.md"


# ---------------------------------------------------------------------------
# Parser surface: --target persona-v2 must be an accepted choice
# ---------------------------------------------------------------------------


def test_build_parser_accepts_target_persona_v2():
    """argparse must accept ``--target persona-v2`` after Tag-3.

    Regression guard for the Tag-3 ``PERSONA_SCHEMA_VERSION_LIST``
    extension: if a future refactor narrows the list back to
    ``("persona-v0", "persona-v1")``, this assertion fails before
    we even hit the resolver.
    """
    parser = build_parser()
    namespace = parser.parse_args(
        ["migrate", str(V9_FIXTURE), "--target", "persona-v2"]
    )
    assert namespace.command == "migrate"
    assert namespace.target == "persona-v2"


# ---------------------------------------------------------------------------
# Single-step CLI path: v9 -> v2 (V1ToV2Step)
# ---------------------------------------------------------------------------


def test_cli_v9_to_v2_single_step_emits_v2_canonical_subset(
    capsys: pytest.CaptureFixture[str],
):
    """A v9 input with ``--target persona-v2`` must lift to v2.

    The chain is single-step (V1ToV2Step alone). stdout JSON carries
    ``schema_version=persona-v2``; stderr is silent under ``--quiet``
    without ``--emit-hash``.
    """
    rc = main(
        [
            "migrate",
            str(V9_FIXTURE),
            "--target",
            "persona-v2",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "persona-v2"
    assert captured.err == ""


def test_cli_v9_to_v2_emit_hash_matches_v9_migrated_to_v2_pin(
    capsys: pytest.CaptureFixture[str],
):
    """``--emit-hash`` must surface the V9-to-V2 pin on stderr.

    Pinned against :data:`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` so that
    a CLI-dispatch regression (e.g. accidentally re-hashing the v1
    intermediate instead of the v2 endpoint) trips this assertion
    rather than silently emitting the wrong pin.
    """
    rc = main(
        [
            "migrate",
            str(V9_FIXTURE),
            "--target",
            "persona-v2",
            "--quiet",
            "--emit-hash",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert stderr_lines == [PERSONA_HASH_PIN_V9_MIGRATED_TO_V2]


# ---------------------------------------------------------------------------
# Multi-step CLI path: v8 -> v0 -> v1 -> v2 (M-1 direct anchor)
# ---------------------------------------------------------------------------


def test_cli_v8_to_v2_multi_step_chain_emits_v2_canonical_subset(
    capsys: pytest.CaptureFixture[str],
):
    """A v8 input with ``--target persona-v2`` must chain through v1.

    The resolver builds ``[V0ToV1Step(), V1ToV2Step()]`` automatically
    when the source is v0 (the v8 fixture's recorded
    ``schema_version``) and the target is v2. This is the M-1
    direct-anchor surface through the CLI: a multi-step chain whose
    endpoint hash equals the V8-MIGRATED-V2 pin by construction.
    """
    rc = main(
        [
            "migrate",
            str(V8_FIXTURE),
            "--target",
            "persona-v2",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "persona-v2"


def test_cli_v8_to_v2_chain_expect_hash_passes(
    capsys: pytest.CaptureFixture[str],
):
    """``--expect-hash`` against the V8-MIGRATED-V2 pin must pass.

    Direct-anchor M-1 assertion through the operator surface:
    chain endpoint hash equals
    :data:`PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`, which by construction
    equals :data:`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` (the v8 and v9
    fixtures share every canonical-subset key except
    ``schema_version``, and the chain endpoint sets v2 either way).

    The CLI accepts both bare 64-hex and full ``sha256:<64hex>`` form;
    we exercise the full form here and let
    ``test_persona_migration_cli.py`` cover the bare-hex branch on
    the v1 surface.
    """
    rc = main(
        [
            "migrate",
            str(V8_FIXTURE),
            "--target",
            "persona-v2",
            "--quiet",
            "--expect-hash",
            PERSONA_HASH_PIN_V8_MIGRATED_TO_V2,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    # No stderr noise under --quiet without --emit-hash.
    assert captured.err == ""


# ---------------------------------------------------------------------------
# Negative path: --target persona-v0 is forward-only-rejected
# ---------------------------------------------------------------------------


def test_cli_target_persona_v0_from_v9_input_rejects_with_exit_1(
    capsys: pytest.CaptureFixture[str],
):
    """Forward-only chain: v9 -> v0 must fail at resolver time.

    ``persona-v0`` is in ``PERSONA_SCHEMA_VERSION_LIST`` (so argparse
    accepts it) but no inverse migration step is registered (Default-
    Lock A-2: forward-only, additive-only). The resolver therefore
    raises :class:`PersonaMigrationError` and the CLI maps that to
    exit code 1.

    This is the operator-surface counterpart to the converter-level
    ``test_v2_to_v1_inverse_is_not_supported`` (Sprint-3 Tag-3 §6 of
    the V1V2 test pack).
    """
    rc = main(
        [
            "migrate",
            str(V9_FIXTURE),
            "--target",
            "persona-v0",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    assert rc == EXIT_MIGRATION_ERROR
    assert "migration failed" in captured.err
