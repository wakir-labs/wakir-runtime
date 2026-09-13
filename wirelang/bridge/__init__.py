# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Wirelang bridge sub-package.

Houses operator-facing CLI surfaces for Bridge-Forward-Pipe inspection
and synthetic injection (contract: PR #116 §5).

This package is intentionally thin. The substantive Bridge-Forward
publisher CLI continues to live at :mod:`wirelang.cli.bridge_forward`
(substrate-closer). This sub-package adds the
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
  exercised by the operator-hand live-VM smoke, not by
  this package's hermetic tests.

Spec-Anker:
- ``wirelang/specs/bridge-forward-pipe-v1.md``
- ``wirelang/persona_engine/nats_subscribe_loop.py`` (subscribe-loop
  primary owner)
- PR #116 §5 (CLI substance confirmation)
- Bug-42 (subscribe-loop inventory trigger)
"""
