#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Expectation window for substrate heartbeats — who notices the silence.

The other half of ``scripts/observability/substrate-liveness-probe.sh``.
The probe runs on a substrate node and produces a verdict. It cannot
deliver one, and a probe nobody reads is the defect it was written
against. This is the reader.

Direction, and why
------------------

Push, not pull. Pull needs a route into the private network, and three
named live-evidence lanes died on exactly that. Push needs outbound
HTTPS, which is measured to work from both nodes. So the node posts a
signed heartbeat to a message topic, and this evaluator — running on a
GitHub-hosted runner that never touches the private network — asks one
question: *is there a fresh, authentic, green heartbeat for every node I
expect?*

The three answers that are not "yes" are all red.

Why the signature is not optional
---------------------------------

Anyone who learns the topic name can post to it. Without a signature
they could post a forged ``green`` and silence the alarm — a watchdog
that can be switched off from the outside is not a watchdog. Every
heartbeat carries an HMAC-SHA256 over the exact probe payload, and a
message that does not verify is discarded before its contents are
looked at.

``unmeasurable`` counts as red
------------------------------

Wired here, not written in a comment. The probe answers ``unmeasurable``
whenever it could not do its job — no tools, no target, an unreadable
state file. That answer exists because the substrate taught us what the
alternative looks like: the SPIRE container healthchecks have returned
``ExitCode 1, Output ""`` every ten seconds since May, because podman
wraps a string ``HealthCmd`` in ``/bin/sh -c`` and the image has no
shell, and the container published ``unhealthy`` on the strength of it
while the same command run directly answers ``Server is healthy.``

A probe that could not measure is not a sign of life. It is treated
exactly like a bad verdict, and a test asserts it.

The same rule applies to this evaluator. If it cannot read its own
inputs — no topic, no key, a source it cannot fetch or parse — it exits
2 and says ``unmeasurable``. It never exits 0 on a question it did not
answer.

Exit codes
----------

    0   every expected node has a fresh, authentic, green heartbeat
    1   at least one expected node is red, stale, missing or unmeasurable
    2   the evaluator itself could not measure

The consuming lane must treat 1 and 2 alike; both are a failed job and
both reach the receiver. The distinction is for the human reading the
report, not for the gate.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

#: Wire format of one heartbeat message, three space-separated fields::
#:
#:     wakir-hb1 <hmac-sha256-hex> <base64(probe-json)>
#:
#: Deliberately flat. The producer is a bash script on a host with no
#: python and no jq; anything that needs a JSON encoder on the sending
#: side would have been a dependency in the one place that cannot carry
#: one.
WIRE_PREFIX = "wakir-hb1"

#: Default expectation window. Eight probe cadences at 15 minutes.
#: One lost push — a reboot, a network blip, a dropped scheduled run —
#: must not fire; eight in a row is not chance.
DEFAULT_WINDOW_SECONDS = 7200

#: How far back to ask the message broker for. Wider than the window so
#: that a delayed scheduled run still sees the messages it needs, and so
#: that a message which arrived just outside the window is *seen and
#: judged stale* rather than not seen at all. Those two look identical
#: in the verdict but not in the report, and the report is what somebody
#: reads at 9am.
DEFAULT_LOOKBACK_SECONDS = 4 * DEFAULT_WINDOW_SECONDS

GREEN = "green"
RED = "red"
UNMEASURABLE = "unmeasurable"

#: Per-node states. Only ``ok`` is not a failure.
OK = "ok"
STATE_RED = "red"
STATE_STALE = "stale"
STATE_MISSING = "missing"
STATE_UNMEASURABLE = "unmeasurable"


class Unmeasurable(Exception):
    """The evaluator could not do its job. Exit 2, never exit 0."""


def _now(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def verify_and_decode(line: str, key: bytes) -> dict | None:
    """Return the probe payload of one heartbeat, or ``None``.

    ``None`` means: this message is not a heartbeat we accept. Malformed,
    wrong version, bad signature, undecodable payload — all the same
    answer, because none of them may be allowed to influence a verdict.
    A caller that wanted to distinguish them would be building a reason
    to make an exception for one of them.
    """
    parts = line.strip().split(" ")
    if len(parts) != 3 or parts[0] != WIRE_PREFIX:
        return None
    _, mac_hex, payload_b64 = parts
    try:
        payload = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError):
        return None

    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac_hex.strip().lower()):
        return None

    try:
        decoded = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    if not isinstance(decoded.get("node"), str):
        return None
    if not isinstance(decoded.get("observed_at_epoch"), int):
        return None
    if not isinstance(decoded.get("verdict"), str):
        return None
    return decoded


def newest_per_node(messages: list[str], key: bytes) -> tuple[dict[str, dict], int]:
    """Newest accepted heartbeat per node label, plus the rejected count.

    Newest is decided by the probe's own ``observed_at_epoch``, not by
    the broker's receive time. The broker's clock is not the one the
    verdict is about, and a replayed old message must not be able to
    present itself as recent.
    """
    newest: dict[str, dict] = {}
    rejected = 0
    for line in messages:
        payload = verify_and_decode(line, key)
        if payload is None:
            rejected += 1
            continue
        node = payload["node"]
        current = newest.get(node)
        if current is None or payload["observed_at_epoch"] > current["observed_at_epoch"]:
            newest[node] = payload
    return newest, rejected


def classify(payload: dict | None, now: int, window: int) -> tuple[str, int | None]:
    """One node's state and the age of its newest accepted heartbeat."""
    if payload is None:
        return STATE_MISSING, None
    age = now - payload["observed_at_epoch"]
    if age > window:
        return STATE_STALE, age
    verdict = payload["verdict"]
    if verdict == GREEN:
        return OK, age
    if verdict == RED:
        return STATE_RED, age
    # Everything else, ``unmeasurable`` included and anything a future
    # probe version might invent. An answer this evaluator does not
    # understand is not a sign of life.
    return STATE_UNMEASURABLE, age


def unwrap_stream(body: str) -> list[str]:
    """Heartbeat lines out of a broker poll stream.

    The stream carries ``open`` and ``keepalive`` events alongside the
    messages. A keepalive is not a heartbeat: it proves the broker is
    alive, which is not the question.
    """
    lines = []
    for raw in body.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "message":
            message = event.get("message")
            if isinstance(message, str):
                lines.append(message)
    return lines


def read_messages(source: str, topic: str, lookback: int, source_format: str) -> list[str]:
    """Heartbeat lines from stdin, a file, or the message broker.

    ``source_format`` is explicit rather than sniffed. A reader that
    guesses whether it is holding an envelope or a bare message will one
    day guess wrong, and the failure mode of guessing wrong here is
    "found no heartbeats", which is indistinguishable from the incident.
    """
    if source == "-":
        body = sys.stdin.read()
    elif not source.startswith("http"):
        try:
            with open(source, "r", encoding="utf-8") as handle:
                body = handle.read()
        except OSError as exc:
            raise Unmeasurable(f"cannot read source file: {exc}") from exc
    else:
        body = None

    if body is not None:
        return unwrap_stream(body) if source_format == "stream" else body.splitlines()

    url = f"{source.rstrip('/')}/{topic}/json?poll=1&since={lookback}s"
    request = urllib.request.Request(url, headers={"User-Agent": "wakir-substrate-liveness-window"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # The broker being unreachable is not evidence that the substrate
        # is fine, and it is not evidence that it is broken either.
        raise Unmeasurable(f"cannot reach the message broker: {exc}") from exc

    # A broker URL always speaks the envelope format, whatever the flag
    # says — the flag describes local sources, which are a test and
    # replay affordance.
    return unwrap_stream(body)


def evaluate(
    messages: list[str],
    key: bytes,
    expected: list[str],
    now: int,
    window: int,
) -> dict:
    newest, rejected = newest_per_node(messages, key)

    nodes = {}
    for node in expected:
        state, age = classify(newest.get(node), now, window)
        payload = newest.get(node)
        nodes[node] = {
            "state": state,
            "age_seconds": age,
            "probe_verdict": payload["verdict"] if payload else None,
            "probe_reason": payload.get("reason") if payload else None,
            "observed_at_epoch": payload["observed_at_epoch"] if payload else None,
        }

    unexpected = sorted(set(newest) - set(expected))
    failing = sorted(n for n, r in nodes.items() if r["state"] != OK)

    return {
        "schema": "wakir.substrate-liveness-window/v1",
        "evaluated_at_epoch": now,
        "evaluated_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "window_seconds": window,
        "expected_nodes": sorted(expected),
        "nodes": nodes,
        "failing_nodes": failing,
        "unexpected_node_labels": unexpected,
        "rejected_messages": rejected,
        "accepted_messages": sum(1 for _ in newest),
        "verdict": GREEN if not failing else RED,
    }


def render(report: dict) -> str:
    lines = [
        f"substrate-liveness-window  verdict={report['verdict']}  "
        f"at={report['evaluated_at']}  window={report['window_seconds']}s",
    ]
    for node in report["expected_nodes"]:
        result = report["nodes"][node]
        age = result["age_seconds"]
        age_text = "never" if age is None else f"{age}s"
        reason = result["probe_reason"] or "-"
        lines.append(
            f"  {node:<16} {result['state']:<13} age={age_text:<12} "
            f"probe_verdict={result['probe_verdict'] or '-'} reason={reason}"
        )
    if report["unexpected_node_labels"]:
        lines.append(
            "  note: authentic heartbeats from unexpected labels: "
            + ", ".join(report["unexpected_node_labels"])
        )
    if report["rejected_messages"]:
        lines.append(
            f"  note: {report['rejected_messages']} message(s) rejected "
            "(bad signature, wrong format or undecodable payload)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="NODE",
        help="opaque node label that must report. Repeatable. At least one required.",
    )
    parser.add_argument("--window-seconds", type=int, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--lookback-seconds", type=int, default=None)
    parser.add_argument(
        "--source",
        default="https://ntfy.sh",
        help="broker base URL, a file path, or '-' for stdin.",
    )
    parser.add_argument(
        "--source-format",
        choices=("raw", "stream"),
        default="raw",
        help=(
            "how to read a local source: 'raw' = one heartbeat per line, "
            "'stream' = broker poll envelopes. Ignored for a broker URL, "
            "which is always a stream."
        ),
    )
    parser.add_argument("--now-epoch", type=int, default=None)
    parser.add_argument("--json-out", default=None, help="write the full report here.")
    args = parser.parse_args(argv)

    now = _now(args.now_epoch)
    lookback = args.lookback_seconds or max(args.window_seconds * 4, 3600)

    try:
        if not args.expect:
            # A window that expects nothing is satisfied by silence. That
            # is the failure mode this whole instrument exists to prevent,
            # so it is refused rather than defaulted.
            raise Unmeasurable(
                "no --expect given: a window that expects no node is green "
                "forever, which is the defect, not the configuration"
            )

        topic = os.environ.get("WAKIR_NTFY_TOPIC", "").strip()
        raw_key = os.environ.get("WAKIR_HEARTBEAT_HMAC_KEY", "").strip()
        needs_topic = args.source.startswith("http")
        if needs_topic and not topic:
            raise Unmeasurable("WAKIR_NTFY_TOPIC is unset or empty")
        if not raw_key:
            # Without the key every message would have to be trusted, and
            # a heartbeat anyone can forge is not evidence.
            raise Unmeasurable("WAKIR_HEARTBEAT_HMAC_KEY is unset or empty")

        messages = read_messages(args.source, topic, lookback, args.source_format)
        report = evaluate(messages, raw_key.encode("utf-8"), args.expect, now, args.window_seconds)
    except Unmeasurable as exc:
        report = {
            "schema": "wakir.substrate-liveness-window/v1",
            "evaluated_at_epoch": now,
            "verdict": UNMEASURABLE,
            "reason": str(exc),
            "expected_nodes": sorted(args.expect),
        }
        print(f"substrate-liveness-window  verdict=unmeasurable  reason={exc}")
        print(
            "unmeasurable is not green: this run answered nothing, so it "
            "fails like a bad answer.",
            file=sys.stderr,
        )
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, sort_keys=True)
        return 2

    print(render(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
    return 0 if report["verdict"] == GREEN else 1


if __name__ == "__main__":
    sys.exit(main())
