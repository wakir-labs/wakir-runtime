# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the operator-facing marker-stack reducer CLI.

Phase-2 Sprint-9 Tag-3 Teil A. The CLI lives in
:mod:`wirelang.cli.marker_stack_reduce`; the live NATS-JetStream
connection factory is **never invoked** from this suite. Tests
construct an :class:`OperatorRunner` with an injected
``open_backend_async`` that hands back an in-memory backend stub
exposing the :meth:`get_marker_stack` shape the CLI consumes.

Coverage axes (T-CLI-MSR-01..11):

- T-CLI-MSR-01: pretty-print format stability — a fixed stack
  renders to a byte-equal expected text block.
- T-CLI-MSR-02: JSON-mode schema stability — same stack renders
  to a byte-equal expected JSON document with sorted keys.
- T-CLI-MSR-03: empty-stack pretty rendering — ACTIVE/ACTIVE
  verdict with ``(no markers)`` / ``(no anchors)`` blocks.
- T-CLI-MSR-04: empty-stack JSON rendering — ACTIVE/ACTIVE
  verdict with empty ``audit_trace`` / ``wat_anchor_chain`` lists.
- T-CLI-MSR-05: not-found token (backend returns ``None``) —
  exit code 3; JSON ``found=false`` shape.
- T-CLI-MSR-06: marker-symbol legend — every event-kind the
  reducer can emit maps to a non-empty symbol; the legend is
  exposed as the module-level ``MARKER_SYMBOLS`` dict.
- T-CLI-MSR-07: multi-marker-reduction-vorbereitung — a stack
  with revoke + unrevoke + revoke reduces to the expected
  REVOKED verdict; pretty + JSON both reflect the correct
  audit-trace ordering and outcome strings.
- T-CLI-MSR-08: caveat-override stack — the JSON path serialises
  ``narrowed_caveat_set`` as a list-of-lists; the pretty path
  renders the canonical tuple via ``repr``.
- T-CLI-MSR-09: argparse contract — ``--format`` rejects
  unsupported values via the parser; ``--org`` and
  ``--capability-token`` are required.
- T-CLI-MSR-10: bridge-revoked rendering — the BR symbol appears
  in the audit trace; pretty + JSON both surface
  ``bridge_blocked: true`` when the marker fires.
- T-CLI-MSR-11: backend exception path — a backend that raises
  on ``get_marker_stack`` produces exit code 1 and an error line
  on stderr; stdout stays empty.

These tests are hermetic: no I/O, no NATS, no filesystem
mutation outside ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from wirelang.cli.marker_stack_reduce import (
    MARKER_SYMBOLS,
    OperatorRunner,
    main,
    not_found_to_json,
    pretty_print_verdict,
    verdict_to_json,
)
from wirelang.federation.marker_composition import (
    BridgeRevokedEvent,
    CaveatOverrideEvent,
    MarkerStack,
    RevokeEvent,
    UnrevokeEvent,
    reduce_marker_stack,
)
from wirelang.federation.cross_org_attenuation_verifier import (
    BridgeRevocationMarker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_ORG = "orbit"
_TOKEN = "cap-token-42"
_T0 = datetime(2026, 5, 13, 7, 0, 0, tzinfo=timezone.utc)


@dataclass
class _BackendStub:
    """In-memory backend stub exposing the
    :meth:`NatsKvMarkerStackBackend.get_marker_stack` shape.

    The CLI consumes exactly one method; the stub is the smallest
    surface that lets us drive the runner without touching the
    real NATS-py-aware backend (which would require a mock-KV
    handle and a deep simulation of the envelope layer).
    """

    stack: Optional[MarkerStack]
    raise_exc: Optional[Exception] = None

    async def get_marker_stack(
        self,
        *,
        org_id: str,
        capability_token_id: str,
    ) -> Optional[MarkerStack]:
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.stack


def _make_opener(backend: _BackendStub):
    async def _open(
        servers: str, token: Optional[str], org_id: str
    ) -> Any:
        return backend

    return _open


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _runner_with(
    backend: _BackendStub,
) -> tuple[OperatorRunner, io.StringIO, io.StringIO]:
    out = io.StringIO()
    err = io.StringIO()
    runner = OperatorRunner(
        open_backend_async=_make_opener(backend),
        stdout=out,
        stderr=err,
    )
    return runner, out, err


# ---------------------------------------------------------------------------
# Stack builders
# ---------------------------------------------------------------------------


def _three_marker_revoke_unrevoke_revoke() -> MarkerStack:
    """Pattern stack for T-CLI-MSR-01/02/07 — revoke@T0, unrevoke@T0+30m,
    revoke@T0+1h. Final state REVOKED."""
    return MarkerStack(
        token_id=_TOKEN,
        minted_at=_T0 - timedelta(hours=1),
        original_caveat_set=None,
        events=(
            RevokeEvent(
                event_at=_T0,
                revocation_reason="initial-compromise",
            ),
            UnrevokeEvent(
                event_at=_T0 + timedelta(minutes=30),
                previous_revoked_at=_T0,
                unrevoke_reason="false-alarm",
            ),
            RevokeEvent(
                event_at=_T0 + timedelta(hours=1),
                revocation_reason="compromise",
                wat_anchor_manifest_id="manifest-7",
            ),
        ),
    )


def _empty_stack() -> MarkerStack:
    return MarkerStack(
        token_id=_TOKEN,
        minted_at=_T0 - timedelta(hours=1),
        original_caveat_set=None,
        events=(),
    )


def _caveat_override_stack() -> MarkerStack:
    """One-event stack carrying a CaveatOverrideEvent. The
    ``original_caveat_set`` matches the stack's mint-time
    caveat-set; the narrowed set drops one predicate.
    """
    original = (
        ("ttl_until", (1700000000,)),
        ("audience", ("partner-a",)),
    )
    narrowed = (("ttl_until", (1700000000,)),)
    return MarkerStack(
        token_id=_TOKEN,
        minted_at=_T0 - timedelta(hours=1),
        original_caveat_set=original,
        events=(
            CaveatOverrideEvent(
                event_at=_T0,
                original_caveat_set=original,
                narrowed_caveat_set=narrowed,
                override_reason="issuer-side-narrowing",
            ),
        ),
    )


def _bridge_revoked_stack() -> MarkerStack:
    """Single-event stack that bridge-blocks an otherwise-active
    token. The bridge marker's ``revoked_at`` precedes the
    ``minted_at`` so :meth:`bridge_was_revoked_for_mint` fires
    on the reducer's cross-check."""
    # bridge_was_revoked_for_mint fires when minted_at >= revoked_at:
    # set minted strictly after the bridge revocation.
    bridge_revoked_at = _T0
    minted = _T0 + timedelta(minutes=10)
    marker = BridgeRevocationMarker(
        source_ftd_id="ftd-a",
        target_ftd_id="ftd-b",
        revoked_at=bridge_revoked_at,
    )
    return MarkerStack(
        token_id=_TOKEN,
        minted_at=minted,
        original_caveat_set=None,
        events=(BridgeRevokedEvent(marker=marker),),
    )


# ---------------------------------------------------------------------------
# T-CLI-MSR-01..11
# ---------------------------------------------------------------------------


def test_t_cli_msr_01_pretty_print_format_stability():
    """T-CLI-MSR-01: a fixed three-marker stack renders to the
    canonical pretty-print text block. This locks the
    operator-facing surface across Tag-3+ releases.
    """
    stack = _three_marker_revoke_unrevoke_revoke()
    verdict = reduce_marker_stack(stack)
    rendered = pretty_print_verdict(
        verdict, token_id=_TOKEN, org_id=_ORG
    )

    # Lock the headers + verdict block lines first.
    assert rendered.startswith(
        "capability-token: cap-token-42\n"
        "org: orbit\n"
        "final-verdict:\n"
    )
    assert "  state:               revoked" in rendered
    assert "  effective:           revoked" in rendered
    assert "  bridge_blocked:      false" in rendered
    assert "  revocation_reason:   compromise" in rendered
    assert "  new_token_id:        (none)" in rendered
    assert "  narrowed_caveat_set: (none)" in rendered

    # Audit-trace section: three rows, chronological, symbols
    # mapped to R/U/R.
    assert "audit-trace (3 markers, chronological):" in rendered
    assert (
        "  [001] 2026-05-13T07:00:00+00:00  R   "
        "revoke               transition:active->revoked"
    ) in rendered
    assert (
        "  [002] 2026-05-13T07:30:00+00:00  U   "
        "unrevoke             transition:revoked->active"
    ) in rendered
    assert (
        "  [003] 2026-05-13T08:00:00+00:00  R   "
        "revoke               transition:active->revoked"
    ) in rendered

    # Anchor-chain block.
    assert "wat-anchor-chain (3):" in rendered
    assert "  [001] (none)" in rendered
    assert "  [002] (none)" in rendered
    assert "  [003] manifest-7" in rendered


def test_t_cli_msr_02_json_mode_schema_stability():
    """T-CLI-MSR-02: the JSON path emits a stable shape with
    sort_keys=True; downstream pipelines can rely on the schema.
    """
    stack = _three_marker_revoke_unrevoke_revoke()
    verdict = reduce_marker_stack(stack)
    rendered = verdict_to_json(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    payload = json.loads(rendered)

    # Top-level shape.
    assert payload["capability_token"] == _TOKEN
    assert payload["org"] == _ORG
    assert payload["found"] is True

    verdict_payload = payload["verdict"]
    assert verdict_payload["state"] == "revoked"
    assert verdict_payload["effective"] == "revoked"
    assert verdict_payload["bridge_blocked"] is False
    assert verdict_payload["revocation_reason"] == "compromise"
    assert verdict_payload["revoked_at"] == (
        "2026-05-13T08:00:00+00:00"
    )
    assert verdict_payload["new_token_id"] is None
    assert verdict_payload["narrowed_caveat_set"] is None

    trace = verdict_payload["audit_trace"]
    assert len(trace) == 3
    assert trace[0]["symbol"] == "R"
    assert trace[0]["event_kind"] == "revoke"
    assert trace[0]["outcome"] == "transition:active->revoked"
    assert trace[1]["symbol"] == "U"
    assert trace[1]["event_kind"] == "unrevoke"
    assert trace[1]["outcome"] == "transition:revoked->active"
    assert trace[2]["symbol"] == "R"
    assert trace[2]["wat_anchor_manifest_id"] == "manifest-7"

    anchors = verdict_payload["wat_anchor_chain"]
    assert anchors == [None, None, "manifest-7"]

    # sort_keys + compact separators contract: the rendered string
    # has no embedded whitespace and the top-level keys appear in
    # sorted order.
    assert ", " not in rendered  # compact separators
    assert ": " not in rendered
    # First three top-level keys in sorted order:
    # capability_token, found, org.
    first_keys = [
        rendered.split('"', 2)[1],
    ]
    assert first_keys[0] == "capability_token"


def test_t_cli_msr_03_empty_stack_pretty():
    """T-CLI-MSR-03: an empty stack reduces to ACTIVE/ACTIVE; the
    pretty render carries the explicit ``(no markers)`` and
    ``(no anchors)`` placeholders.
    """
    verdict = reduce_marker_stack(_empty_stack())
    rendered = pretty_print_verdict(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    assert "  state:               active" in rendered
    assert "  effective:           active" in rendered
    assert "  bridge_blocked:      false" in rendered
    assert "audit-trace (0 markers, chronological):" in rendered
    assert "  (no markers)" in rendered
    assert "wat-anchor-chain (0):" in rendered
    assert "  (no anchors)" in rendered


def test_t_cli_msr_04_empty_stack_json():
    """T-CLI-MSR-04: empty-stack JSON path carries ``found=true``,
    empty ``audit_trace`` and ``wat_anchor_chain`` lists.
    """
    verdict = reduce_marker_stack(_empty_stack())
    rendered = verdict_to_json(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    payload = json.loads(rendered)
    assert payload["found"] is True
    assert payload["verdict"]["state"] == "active"
    assert payload["verdict"]["effective"] == "active"
    assert payload["verdict"]["audit_trace"] == []
    assert payload["verdict"]["wat_anchor_chain"] == []


def test_t_cli_msr_05_not_found_token_exit_code_three():
    """T-CLI-MSR-05: a backend that returns ``None`` produces
    exit code 3 and the JSON ``found=false`` shape on stdout.
    """
    backend = _BackendStub(stack=None)
    runner, out, err = _runner_with(backend)
    code = _run(
        runner.reduce_one(
            servers="ignored",
            token=None,
            org_id=_ORG,
            capability_token_id=_TOKEN,
            output_format="json",
        )
    )
    assert code == 3
    payload = json.loads(out.getvalue().strip())
    assert payload == {
        "capability_token": _TOKEN,
        "org": _ORG,
        "found": False,
    }
    # Pretty mode emits a human-friendly diagnostic on stdout
    # without an error to stderr.
    runner2, out2, err2 = _runner_with(_BackendStub(stack=None))
    code2 = _run(
        runner2.reduce_one(
            servers="ignored",
            token=None,
            org_id=_ORG,
            capability_token_id=_TOKEN,
            output_format="pretty",
        )
    )
    assert code2 == 3
    assert "no events logged for this token-id" in out2.getvalue()
    assert err2.getvalue() == ""


def test_t_cli_msr_06_marker_symbol_legend_complete():
    """T-CLI-MSR-06: every event-kind the reducer can emit has a
    non-empty symbol in :data:`MARKER_SYMBOLS`. Adding a new
    event-kind without registering a symbol must be loud.
    """
    expected_kinds = {
        "revoke",
        "unrevoke",
        "re_issuance",
        "caveat_override",
        "bridge_revoked",
    }
    assert set(MARKER_SYMBOLS.keys()) == expected_kinds
    for kind, sym in MARKER_SYMBOLS.items():
        assert isinstance(sym, str) and sym, (
            f"symbol for {kind!r} must be a non-empty string"
        )


def test_t_cli_msr_07_multi_marker_reduction_end_to_end():
    """T-CLI-MSR-07: the runner consumes a three-marker stack
    from an injected backend, reduces it, and emits the JSON
    document with the expected audit-trace ordering.
    """
    stack = _three_marker_revoke_unrevoke_revoke()
    backend = _BackendStub(stack=stack)
    runner, out, err = _runner_with(backend)
    code = _run(
        runner.reduce_one(
            servers="ignored",
            token=None,
            org_id=_ORG,
            capability_token_id=_TOKEN,
            output_format="json",
        )
    )
    assert code == 0
    assert err.getvalue() == ""
    payload = json.loads(out.getvalue().strip())
    assert payload["verdict"]["state"] == "revoked"
    trace = payload["verdict"]["audit_trace"]
    assert [e["symbol"] for e in trace] == ["R", "U", "R"]
    assert [e["event_kind"] for e in trace] == [
        "revoke",
        "unrevoke",
        "revoke",
    ]


def test_t_cli_msr_08_caveat_override_json_serialisation():
    """T-CLI-MSR-08: a CaveatOverrideEvent stack reduces to
    CAVEAT_OVERRIDDEN; the JSON path serialises
    ``narrowed_caveat_set`` as a list-of-lists. The pretty path
    renders the canonical tuple repr.
    """
    stack = _caveat_override_stack()
    verdict = reduce_marker_stack(stack)

    # JSON path: list-of-lists.
    rendered_json = verdict_to_json(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    payload = json.loads(rendered_json)
    narrowed = payload["verdict"]["narrowed_caveat_set"]
    assert narrowed == [["ttl_until", [1700000000]]]
    assert payload["verdict"]["state"] == "caveat_overridden"

    # Pretty path: repr of the tuple.
    pretty = pretty_print_verdict(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    # Symbol CO must be present in the audit trace block.
    assert "CO " in pretty
    assert (
        "  state:               caveat_overridden" in pretty
    )


def test_t_cli_msr_09_argparse_required_args(capsys):
    """T-CLI-MSR-09: argparse rejects calls that omit ``--org`` or
    ``--capability-token``; ``--format`` rejects unknown values.
    """
    # Missing --org and --capability-token.
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0

    # --format=garbage rejected by argparse.
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--org",
                "orbit",
                "--capability-token",
                "x",
                "--format",
                "garbage",
            ]
        )
    assert exc.value.code != 0


def test_t_cli_msr_10_bridge_revoked_rendering():
    """T-CLI-MSR-10: a BridgeRevokedEvent stack renders the BR
    symbol in the audit trace and surfaces
    ``bridge_blocked=true`` on the final verdict.
    """
    stack = _bridge_revoked_stack()
    verdict = reduce_marker_stack(stack)
    pretty = pretty_print_verdict(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    json_str = verdict_to_json(
        verdict, token_id=_TOKEN, org_id=_ORG
    )
    payload = json.loads(json_str)
    assert payload["verdict"]["bridge_blocked"] is True
    assert payload["verdict"]["effective"] == "bridge_blocked"
    # Pretty contains the BR symbol.
    assert "BR " in pretty
    assert "  bridge_blocked:      true" in pretty


def test_t_cli_msr_11_backend_exception_exit_code_one():
    """T-CLI-MSR-11: a backend that raises on
    :meth:`get_marker_stack` produces exit code 1 and an error
    line on stderr; stdout stays empty.
    """
    backend = _BackendStub(stack=None, raise_exc=RuntimeError("kv-down"))
    runner, out, err = _runner_with(backend)
    code = _run(
        runner.reduce_one(
            servers="ignored",
            token=None,
            org_id=_ORG,
            capability_token_id=_TOKEN,
            output_format="pretty",
        )
    )
    assert code == 1
    assert out.getvalue() == ""
    assert "backend error" in err.getvalue()
    assert "RuntimeError" in err.getvalue()
    assert "kv-down" in err.getvalue()
