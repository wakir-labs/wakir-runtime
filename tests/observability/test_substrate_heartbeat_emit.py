# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/substrate-heartbeat-emit.sh``.

The emitter is the one piece of the melder that runs inside the private
network. It takes whatever the probe said, signs it, and pushes it out.

The contract that matters most is the one that is easy to get wrong in
the comfortable direction: **the emitter sends bad news too.** If it only
transmitted ``green``, silence would carry two meanings — "all well" and
"badly broken" — and that ambiguity is exactly what let a dead substrate
look like a running one for four months. Three tests pin it: green, red
and unmeasurable all go on the wire, and all exit 0.

The other contracts:

* the payload is the probe's bytes **verbatim**; the emitter adds no
  interpretation of its own, so the leak guarantees tested on the probe
  still hold on the wire;
* a key file whose content ends in a newline and an environment variable
  holding the same secret must produce the same signature — otherwise
  two operators configure "the same" key and get silent rejection;
* no key, or a probe that answers nothing, exits 2 rather than sending
  something unauthenticated or empty.

Nothing here touches the network: ``WAKIR_POST_CMD`` replaces curl, and
``WAKIR_PROBE_CMD`` replaces the probe. The final test closes the loop by
piping the emitter's real output into the real evaluator.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EMITTER = REPO_ROOT / "scripts" / "observability" / "substrate-heartbeat-emit.sh"
WINDOW = REPO_ROOT / "scripts" / "observability" / "substrate-liveness-window.py"

KEY = "test-key-not-a-real-secret"
NOW = 1790065485  # 2026-09-22T08:24:45Z

# The verbatim output of the probe against live node A on 2026-09-22
# 08:24:45 UTC. Recorded, not invented.
RECORDED_RED = (
    '{"schema":"wakir.substrate-liveness/v1","node":"node-a",'
    '"observed_at_epoch":1790065485,"observed_at":"2026-09-22T08:24:45Z",'
    '"verdict":"red","reason":"bundle_expired","svid_ttl_seconds":3600,'
    '"grace_seconds":3600,"state_max_age_seconds":21600,'
    '"svid_not_after_epoch":1778833955,"svid_expired_for_seconds":11231530,'
    '"bundle_newest_not_after_epoch":1778884579,'
    '"bundle_expired_for_seconds":11180906,"bundle_cert_count":3,'
    '"state_mtime_epoch":1778830355,"state_age_seconds":11235130}'
)


def fake_probe(tmp_path: Path, stdout: str, exit_code: int = 0) -> Path:
    """A stand-in probe. Its exit code is variable on purpose: the emitter
    must not treat a red or unmeasurable probe as a reason to stay quiet."""
    path = tmp_path / "fake-probe.sh"
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"cat <<'PROBE_EOF'\n{stdout}\nPROBE_EOF\n"
        f"exit {exit_code}\n"
    )
    path.chmod(0o755)
    return path


def emit(
    tmp_path: Path,
    *,
    probe_stdout: str,
    probe_exit: int = 0,
    key: str | None = KEY,
    key_file: str | None = None,
):
    sink = tmp_path / "sent.txt"
    env = dict(os.environ)
    for name in (
        "WAKIR_HEARTBEAT_HMAC_KEY",
        "WAKIR_HMAC_KEY_FILE",
        "WAKIR_NTFY_TOPIC",
    ):
        env.pop(name, None)
    if key is not None:
        env["WAKIR_HEARTBEAT_HMAC_KEY"] = key
    if key_file is not None:
        env["WAKIR_HMAC_KEY_FILE"] = key_file
    env["WAKIR_PROBE_CMD"] = str(fake_probe(tmp_path, probe_stdout, probe_exit))
    env["WAKIR_POST_CMD"] = f"tee {sink}"

    proc = subprocess.run(
        ["bash", str(EMITTER)], env=env, capture_output=True, text=True, timeout=120
    )
    sent = sink.read_text().strip() if sink.exists() else ""
    return proc, sent


def verify(message: str, key: str = KEY) -> dict | None:
    """Verify + decode using the evaluator's own implementation.

    Importing the evaluator rather than re-implementing HMAC here is
    deliberate: a test that reimplements the thing under test can agree
    with itself while both are wrong.
    """
    sys.path.insert(0, str(WINDOW.parent))
    import importlib.util

    spec = importlib.util.spec_from_file_location("window_mod", WINDOW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_and_decode(message, key.encode())


# --- the contract that is easy to get wrong the comfortable way -------


@pytest.mark.parametrize(
    "verdict,reason,probe_exit",
    [("green", "ok", 0), ("red", "bundle_expired", 1), ("unmeasurable", "missing_tool_openssl", 2)],
)
def test_the_emitter_sends_bad_news_too(tmp_path, verdict, reason, probe_exit):
    """Green, red and unmeasurable all go on the wire, and all exit 0.

    An emitter that suppressed anything would make silence ambiguous, and
    an ambiguous silence is the whole incident in one word.
    """
    body = json.dumps(
        {
            "schema": "wakir.substrate-liveness/v1",
            "node": "node-a",
            "observed_at_epoch": NOW,
            "verdict": verdict,
            "reason": reason,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    proc, sent = emit(tmp_path, probe_stdout=body, probe_exit=probe_exit)
    assert proc.returncode == 0, proc.stderr
    decoded = verify(sent)
    assert decoded is not None, f"emitted message did not verify: {sent[:120]}"
    assert decoded["verdict"] == verdict
    assert decoded["reason"] == reason


def test_payload_is_the_probe_output_verbatim(tmp_path):
    """The emitter adds no interpretation, so the probe's leak guarantees
    survive the trip."""
    proc, sent = emit(tmp_path, probe_stdout=RECORDED_RED)
    assert proc.returncode == 0, proc.stderr
    decoded = verify(sent)
    assert decoded == json.loads(RECORDED_RED)
    for needle in ("192.168.", "spiffe://", "join_token", "BEGIN CERTIFICATE"):
        assert needle not in sent


def test_wire_format_is_three_fields(tmp_path):
    _, sent = emit(tmp_path, probe_stdout=RECORDED_RED)
    parts = sent.split(" ")
    assert len(parts) == 3, sent[:120]
    assert parts[0] == "wakir-hb1"
    assert len(parts[1]) == 64, "HMAC-SHA256 hex is 64 characters"


# --- the two ways to give it the same secret --------------------------


def test_key_file_with_trailing_newline_matches_the_env_key(tmp_path):
    """A key file written with `echo` ends in a newline; the same secret
    pasted into an environment variable does not. If those produced
    different signatures, two operators would configure the same key and
    get silent rejection — a watchdog that is off for a reason nobody can
    see."""
    key_path = tmp_path / "key"
    key_path.write_text(KEY + "\n")

    _, from_file = emit(tmp_path, probe_stdout=RECORDED_RED, key=None, key_file=str(key_path))
    _, from_env = emit(tmp_path, probe_stdout=RECORDED_RED, key=KEY)
    assert from_file == from_env
    assert verify(from_file) is not None


def test_key_file_takes_precedence_over_the_environment(tmp_path):
    """The file is the documented place; if both are set, the one that is
    not visible in /proc wins."""
    key_path = tmp_path / "key"
    key_path.write_text(KEY)
    _, sent = emit(
        tmp_path,
        probe_stdout=RECORDED_RED,
        key="a-different-key-entirely",
        key_file=str(key_path),
    )
    assert verify(sent, KEY) is not None


# --- refusing to send something meaningless ---------------------------


def test_no_key_exits_two_and_sends_nothing(tmp_path):
    proc, sent = emit(tmp_path, probe_stdout=RECORDED_RED, key=None)
    assert proc.returncode == 2
    assert sent == ""
    assert "HMAC key" in proc.stderr


def test_unreadable_key_file_exits_two(tmp_path):
    proc, sent = emit(
        tmp_path, probe_stdout=RECORDED_RED, key=None, key_file=str(tmp_path / "absent")
    )
    assert proc.returncode == 2
    assert sent == ""


def test_probe_that_answers_nothing_exits_two(tmp_path):
    """An empty answer is the one thing that cannot be forwarded. It is
    also what a check that never started looks like."""
    proc, sent = emit(tmp_path, probe_stdout="", probe_exit=2)
    assert proc.returncode == 2
    assert sent == ""
    assert "nothing to attest to" in proc.stderr


def test_failing_post_exits_one_not_zero(tmp_path):
    env = dict(os.environ)
    env["WAKIR_HEARTBEAT_HMAC_KEY"] = KEY
    env["WAKIR_PROBE_CMD"] = str(fake_probe(tmp_path, RECORDED_RED))
    env["WAKIR_POST_CMD"] = "false"
    proc = subprocess.run(
        ["bash", str(EMITTER)], env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 1


# --- the loop, closed -------------------------------------------------


def test_end_to_end_emitter_output_is_read_by_the_window(tmp_path):
    """The emitter's real output, through the real evaluator.

    Two node payloads, both the recorded May-frozen state, both punctual.
    The window must come out red — this is the drill in miniature, run
    across the actual boundary rather than against a hand-written wire
    format on each side.
    """
    _, message = emit(tmp_path, probe_stdout=RECORDED_RED)
    messages = [message]

    proc = subprocess.run(
        [
            sys.executable,
            str(WINDOW),
            "--source",
            "-",
            "--expect",
            "node-a",
            "--now-epoch",
            str(NOW),
            "--json-out",
            str(tmp_path / "report.json"),
        ],
        input="\n".join(messages),
        env={**os.environ, "WAKIR_HEARTBEAT_HMAC_KEY": KEY, "WAKIR_NTFY_TOPIC": "t"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1, proc.stdout
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["nodes"]["node-a"]["state"] == "red"
    assert report["nodes"]["node-a"]["probe_reason"] == "bundle_expired"
    assert report["rejected_messages"] == 0, "the emitter's own output must verify"
