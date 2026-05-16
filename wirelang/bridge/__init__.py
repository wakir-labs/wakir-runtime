# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Wirelang bridge sub-package (Sprint-Bridge-Forward-CLI-MINI, 2026-05-16).

Houses operator-facing CLI surfaces for Bridge-Forward-Pipe inspection
and synthetic-injection (Amara PR #116 §5 owner-verantwortungs-klausel:
Reza primary, Selin co-owner).

This package is intentionally thin. The substantive Bridge-Forward
publisher CLI continues to live at :mod:`wirelang.cli.bridge_forward`
(Sprint-10 Tag-6 substrate-closer). This sub-package adds the
operator-facing *probe* surfaces:

- :mod:`wirelang.bridge.cli` — ``bridge-forward subscribe-loop-summary``
  emits a single-shot snapshot of subscribe-loop telemetry (lag, count,
  consumer-count, last-message-at) keyed by subject-pattern. Default
  output ``--json``; ``--summary`` switches to a human-readable line.

Hermetic-test discipline (parity with ``cli/bridge_forward.py``):

- The hermetic test surface MUST NOT import ``nats-py``. The CLI
  accepts a ``--snapshot-file`` argument so a mock fixture can hand
  the CLI a deterministic input dict.
- The live path (``--live --nats-url ...``) lazy-imports ``nats-py``
  and probes JetStream stream-info + consumer-info. That path is
  exercised by Operator-Hand-Live-VM smoke (Amara TV-LVD), not by
  this package's hermetic tests.

Spec-Anker:
- ``wirelang/specs/bridge-forward-pipe-v1.md`` (Sprint-10 Tag-6)
- ``wirelang/persona_engine/nats_subscribe_loop.py`` (subscribe-loop
  primary owner)
- Amara PR #116 §5 (CLI-Substance-Bestätigung)
- Selin Sprint-Pengine-13 Bug-42 (subscribe-loop inventory trigger)
"""
