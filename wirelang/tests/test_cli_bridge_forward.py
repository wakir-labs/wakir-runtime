# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-10 Tag-6 Bridge-Forward-Pipe publisher CLI.

The CLI is in ``wirelang/cli/bridge_forward.py``. The ``--dry-run`` path
is fully hermetic (no nats-py import, no network); these tests exercise
that path.

Spec: ``wirelang/specs/bridge-forward-pipe-v1.md``.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from wirelang.cli.bridge_forward import (
    AGENT_TASK_ASSIGNED_SCHEMA,
    AuftragEnvelope,
    EnvelopeFormatError,
    MAX_AUFTRAG_ID_OCTETS,
    MAX_PROMPT_PAYLOAD_BYTES,
    SizeLimitError,
    build_subject,
    envelope_to_jcs_bytes,
    main,
    validate_envelope,
)


# ---------------------------------------------------------------------
# build_subject
# ---------------------------------------------------------------------


def test_build_subject_canonical_form():
    assert build_subject("dev", "tomas") == (
        "wakir.dev.agent.agent.task.assigned.tomas"
    )


def test_build_subject_rejects_bad_env():
    with pytest.raises(EnvelopeFormatError):
        build_subject("production", "tomas")


def test_build_subject_rejects_bad_persona_slug():
    with pytest.raises(EnvelopeFormatError):
        build_subject("dev", "Tomas")  # uppercase
    with pytest.raises(EnvelopeFormatError):
        build_subject("dev", "1tomas")  # leading digit
    with pytest.raises(EnvelopeFormatError):
        build_subject("dev", "to.mas")  # dot


def test_build_subject_matches_layer_0_transport_schema_regex():
    """The subject MUST match the schemas/layer-0-transport.json regex.

    Single source of truth for the subject-pattern is the schema regex.
    """
    import re

    schema_pattern = re.compile(
        r"^wakir\.(dev|staging|prod)\."
        r"[a-z][a-z0-9_-]*\."
        r"[a-z][a-z0-9_.-]*"
        r"(\.[a-zA-Z0-9_.-]+)?$"
    )
    for env in ("dev", "staging", "prod"):
        for slug in ("tomas", "reza", "kai", "selin"):
            subj = build_subject(env, slug)
            assert schema_pattern.match(subj), (
                f"subject {subj!r} fails subject-mapping-v1 regex"
            )


# ---------------------------------------------------------------------
# Envelope shape + determinism
# ---------------------------------------------------------------------


def test_envelope_to_jcs_bytes_is_deterministic():
    e1 = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="sprint-10-tag-6",
        ts_utc="2026-05-15T17:30:00Z",
        source="mira-sandbox",
        prompt_payload="hello world",
        metadata={"sprint": "sprint-10"},
    )
    a = envelope_to_jcs_bytes(e1.to_dict())
    b = envelope_to_jcs_bytes(e1.to_dict())
    assert a == b


def test_envelope_prompt_sha256_matches_hashlib():
    e = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="x",
        ts_utc="2026-05-15T17:30:00Z",
        source="mira-sandbox",
        prompt_payload="hello world",
    )
    expected = f"sha256:{hashlib.sha256(b'hello world').hexdigest()}"
    assert e.prompt_sha256 == expected


def test_envelope_dict_includes_schema_literal():
    e = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="x",
        ts_utc="2026-05-15T17:30:00Z",
        source="mira-sandbox",
        prompt_payload="hi",
    )
    d = e.to_dict()
    assert d["schema"] == AGENT_TASK_ASSIGNED_SCHEMA
    assert d["event_kind"] == "agent.task.assigned"


# ---------------------------------------------------------------------
# Size envelope
# ---------------------------------------------------------------------


def test_validate_envelope_rejects_oversize_prompt():
    e = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="x",
        ts_utc="2026-05-15T17:30:00Z",
        source="mira-sandbox",
        prompt_payload="x" * (MAX_PROMPT_PAYLOAD_BYTES + 1),
    )
    with pytest.raises(SizeLimitError):
        validate_envelope(e)


def test_validate_envelope_rejects_oversize_auftrag_id():
    e = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="a" * (MAX_AUFTRAG_ID_OCTETS + 1),
        ts_utc="2026-05-15T17:30:00Z",
        source="mira-sandbox",
        prompt_payload="hi",
    )
    with pytest.raises(SizeLimitError):
        validate_envelope(e)


def test_validate_envelope_accepts_boundary_sizes():
    """Boundary case: exactly MAX_PROMPT_PAYLOAD_BYTES bytes must pass."""
    e = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="x",
        ts_utc="2026-05-15T17:30:00Z",
        source="mira-sandbox",
        prompt_payload="x" * MAX_PROMPT_PAYLOAD_BYTES,
    )
    validate_envelope(e)  # must not raise


# ---------------------------------------------------------------------
# CLI dry-run
# ---------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    """Run ``main(argv)`` capturing stdout; return (rc, stdout_text)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def test_cli_dry_run_emits_subject_comment_and_envelope(tmp_path: Path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Tomás, baue X.", encoding="utf-8")
    rc, out = _run_cli([
        "--persona-slug", "tomas",
        "--auftrag-id", "sprint-10-tag-6",
        "--prompt-file", str(prompt_file),
        "--ts-utc", "2026-05-15T17:30:00Z",
        "--dry-run",
    ])
    assert rc == 0, out
    lines = out.strip().split("\n")
    assert lines[0] == "# subject: wakir.dev.agent.agent.task.assigned.tomas"
    envelope = json.loads(lines[1])
    assert envelope["schema"] == AGENT_TASK_ASSIGNED_SCHEMA
    assert envelope["persona_id"] == "tomas"
    assert envelope["auftrag_id"] == "sprint-10-tag-6"
    assert envelope["org_id"] == "acme"
    assert envelope["ts_utc"] == "2026-05-15T17:30:00Z"
    assert envelope["prompt_payload"] == "Tomás, baue X."
    # prompt_sha256 must match the actual hashlib digest of the
    # prompt-payload UTF-8 bytes.
    expected = f"sha256:{hashlib.sha256('Tomás, baue X.'.encode('utf-8')).hexdigest()}"
    assert envelope["prompt_sha256"] == expected


def test_cli_dry_run_byte_deterministic_across_repeats(tmp_path: Path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("hello", encoding="utf-8")
    argv = [
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--ts-utc", "2026-05-15T17:30:00Z",
        "--dry-run",
    ]
    _, a = _run_cli(argv)
    _, b = _run_cli(argv)
    assert a == b


def test_cli_dry_run_carries_metadata(tmp_path: Path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("hello", encoding="utf-8")
    rc, out = _run_cli([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--ts-utc", "2026-05-15T17:30:00Z",
        "--metadata", "sprint=sprint-10",
        "--metadata", "tag=tag-6",
        "--dry-run",
    ])
    assert rc == 0
    envelope = json.loads(out.strip().split("\n")[1])
    assert envelope["metadata"] == {"sprint": "sprint-10", "tag": "tag-6"}


def test_cli_dry_run_does_not_import_nats(tmp_path: Path, monkeypatch):
    """The hermetic test surface MUST NOT touch nats-py.

    Inject a sys.modules entry that raises on attribute access so any
    accidental import surface failure becomes a loud test error.
    """
    # Ensure nats is NOT imported via the dry-run path.
    sentinel_calls: list[str] = []

    class _Forbidden:
        def __getattr__(self, name):  # pragma: no cover
            sentinel_calls.append(name)
            raise AssertionError(
                "dry-run path must not access nats-py"
            )

    monkeypatch.setitem(sys.modules, "nats", _Forbidden())

    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("hi", encoding="utf-8")
    rc, _ = _run_cli([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--dry-run",
    ])
    assert rc == 0
    assert sentinel_calls == [], sentinel_calls


def test_cli_rejects_oversize_prompt_with_exit_2(tmp_path: Path):
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("x" * (MAX_PROMPT_PAYLOAD_BYTES + 1), encoding="utf-8")
    rc, _ = _run_cli([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-file", str(prompt_file),
        "--dry-run",
    ])
    assert rc == 2


def test_cli_rejects_missing_prompt_source():
    """Argparse mutual-exclusion: no --prompt-file AND no --prompt-stdin."""
    with pytest.raises(SystemExit):
        main([
            "--persona-slug", "tomas",
            "--auftrag-id", "x",
            "--dry-run",
        ])


def test_cli_stdin_prompt_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "stdin", io.StringIO("stdin-prompt"))
    rc, out = _run_cli([
        "--persona-slug", "tomas",
        "--auftrag-id", "x",
        "--prompt-stdin",
        "--ts-utc", "2026-05-15T17:30:00Z",
        "--dry-run",
    ])
    assert rc == 0
    envelope = json.loads(out.strip().split("\n")[1])
    assert envelope["prompt_payload"] == "stdin-prompt"
