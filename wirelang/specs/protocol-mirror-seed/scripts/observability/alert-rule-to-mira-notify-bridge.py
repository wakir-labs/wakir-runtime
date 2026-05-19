#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Alert-Rule -> Mira-Notify Bridge (Phase-3c, Tag-47, Noa SRE).

Context
-------

Tag-45 PR #292 added the Pre-Mortem-Failure-Mode Prometheus alert
rules (``dashboards/phase-3-marathon-alerts.yaml``) and the
companion Notify-Catalog
(``docs/observability/pre-mortem-failure-mode-notify-catalog.md``).
Tag-46 PR #296 added the Mira-Notify emitter+receiver substrate
that materialises a uniformly-formatted notify-event into the
Mira-Hand inbox (``agents-workspaces/mira/inbox/``).

What was missing: the **wire** between Prometheus AlertManager
webhook payloads and the Mira-Notify emitter.  AlertManager fires
on its native v4 webhook envelope:

.. code-block:: json

    {
      "version": "4",
      "groupKey": "...",
      "status": "firing",
      "alerts": [
        {
          "status": "firing",
          "labels": {
            "alertname": "WakirPhase3FailureModeA1...",
            "severity": "page",
            "welle": "welle-3",
            ...
          },
          "annotations": {
            "summary": "...",
            "runbook_url": "...",
            "description": "..."
          },
          "startsAt": "2026-05-18T10:11:12Z",
          ...
        }
      ]
    }

This bridge ingests that envelope (file, stdin, or HTTP-POST
payload-equivalent on disk), maps each alert through the Tag-45
catalog to the Tag-46 NotifyEvent schema, and calls the
Tag-46 emitter library API to append into
``infra/notify-log.jsonl``.  The Tag-46 receiver (separate process,
already deployed) then materialises the Mira-Hand inbox file.

Scope
-----

The bridge is the **adapter** layer.  It does:

1. Parse the AlertManager v4 webhook JSON envelope (one or many
   ``alerts[]`` entries).
2. For each alert, look up the catalog entry by ``alertname`` and
   derive ``failure_mode_id`` + canonical ``runbook_url`` if absent.
3. Construct a Tag-46 NotifyEvent via ``emitter.make_event()``.
4. Append-emit via ``emitter.emit_notify()`` to the notify-log JSONL.
5. Skip resolved alerts (``status="resolved"``) by default; the
   ``--include-resolved`` flag opts-in.
6. Skip alerts whose ``alertname`` is not in the catalog **and**
   ``--strict-catalog`` is set; otherwise pass them through with
   ``failure_mode_id=null`` (free-form).

It does NOT do: PagerDuty/ntfy fan-out, AlertManager HTTP server
binding, Receiver materialisation.  Those belong to other
substances (Kai Zone-H operator, Tag-46 receiver respectively).

Catalog mapping
---------------

The mapping table ``ALERT_CATALOG`` is hand-maintained in this
module and mirrors Section 2 of
``docs/observability/pre-mortem-failure-mode-notify-catalog.md``.
A test (``test_alert_rule_to_mira_notify_bridge.py``) cross-checks
that every alert-name in ``dashboards/phase-3-marathon-alerts.yaml``
is either in the catalog OR explicitly listed in the
``CATALOG_NON_PRE_MORTEM`` set (Tag-40 baseline alerts that pre-date
the Tag-45 Pre-Mortem extension).

CLI surface
-----------

* ``python alert-rule-to-mira-notify-bridge.py route --input
  alertmanager-webhook.json --log-path infra/notify-log.jsonl``
* ``python alert-rule-to-mira-notify-bridge.py route --stdin
  --stdout``
* ``python alert-rule-to-mira-notify-bridge.py validate-catalog
  --rules dashboards/phase-3-marathon-alerts.yaml``

Determinism
-----------

The bridge derives event ids via the Tag-46 emitter's deterministic
``derive_event_id`` (hash of alert_name + startsAt + labels).  The
Tag-46 receiver dedupes on event_id, so repeated AlertManager
re-fires are idempotent end-to-end.

Tag-64 Cutover-Day-Morgen Trinary-Verdict-Reactive-Routing
----------------------------------------------------------

Three new catalog entries (Section 6) plus an in-module routing-class
-> channel-set table. The Selin Tag-64 Cutover-Day-Morgen Auto-
Scheduler emits one of three verdict classes (READY/CAUTION/BLOCK),
each materialised as a Prometheus alert carrying a `routing_class`
label that the bridge consumes to enrich the NotifyEvent labels with
`notify_channels` (comma-separated channel-set) and
`escalation_after_seconds`. The bridge does NOT call the channels --
that remains a Kai-Zone-H Operator-Hand surface.

Author: Noa Bergstroem (SRE)
Anchor: Tag-45 catalog PR #292; Tag-46 emitter+receiver PR #296;
        Tag-47 bridge substance; Tag-64 trinary-routing extension.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Emitter module loader (the emitter file has a hyphen in its
# filename so we cannot ``import`` it conventionally).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_EMITTER_PATH = _HERE / "mira-notify-emitter.py"


def _load_emitter():
    spec = importlib.util.spec_from_file_location(
        "mira_notify_emitter", str(_EMITTER_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("mira_notify_emitter", mod)
    spec.loader.exec_module(mod)
    return mod


emitter = _load_emitter()


# ---------------------------------------------------------------------------
# Catalog: alert-name -> {failure_mode_id, severity, runbook_url}.
# Hand-maintained to mirror Section 2 of
# docs/observability/pre-mortem-failure-mode-notify-catalog.md.
# ---------------------------------------------------------------------------

ALERT_CATALOG: dict[str, dict[str, str]] = {
    # Tag-45 Pre-Mortem Failure-Mode alerts (Section 2).
    "WakirPhase3FailureModeA1CrossModulDriftPerWelle": {
        "failure_mode_id": "A1",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-a1-cross-modul-drift"
        ),
    },
    "WakirPhase3FailureModeA2FsmPhantomTransition": {
        "failure_mode_id": "A2",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-a2-fsm-phantom"
        ),
    },
    "WakirPhase3FailureModeA4NatsModeMismatch": {
        "failure_mode_id": "A4",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-a4-nats-mode-mismatch"
        ),
    },
    "WakirPhase3FailureModeA5SelfReferenceTrapWelle3Critical": {
        "failure_mode_id": "A5",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-a5-self-reference-trap"
        ),
    },
    "WakirPhase3FailureModeB1ArHandStopMissingTrigger": {
        "failure_mode_id": "B1",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-b1-ar-hand-stop-missing"
        ),
    },
    "WakirPhase3FailureModeB3Iia1130DefaultPath": {
        "failure_mode_id": "B3",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-b3-iia-1130-default"
        ),
    },
    "WakirPhase3FailureModeC1MarkerFalsePositiveCond1": {
        "failure_mode_id": "C1",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-c1-marker-false-positive-cond1"
        ),
    },
    "WakirPhase3FailureModeC1MarkerFalsePositiveCond4": {
        "failure_mode_id": "C1",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "failure-mode-c1-marker-false-positive-cond4"
        ),
    },
    "WakirPhase3HotSpotWelle3Welle4Coupling": {
        "failure_mode_id": "A1-A5-Hotspot",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "hot-spot-welle3-welle4-coupling"
        ),
    },
    "WakirPhase3HotSpotWelle4Welle5Welle7Coupling": {
        "failure_mode_id": "A3-Hotspot",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "hot-spot-welle4-welle5-welle7-coupling"
        ),
    },
    # Tag-50 Welle-N-Specific Alert-Rules (Section 5 of catalog).
    # failure_mode_id encodes "Welle-N" for the welle-scoped alarms;
    # this keeps the bridge audit-trail consistent with the per-welle
    # group naming convention.
    "WakirWelle1V907VerifyRustRateCollapse": {
        "failure_mode_id": "Welle-1",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-1-rust-rate-collapse"
        ),
    },
    "WakirWelle1Welle2DoppelDivergence": {
        "failure_mode_id": "Welle-1",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-1-2-doppel-divergence"
        ),
    },
    "WakirWelle2SvidRotationFailure": {
        "failure_mode_id": "Welle-2",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-2-svid-rotation-failure"
        ),
    },
    "WakirWelle2SelfScoreCollapse": {
        "failure_mode_id": "Welle-2",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-2-self-score-collapse"
        ),
    },
    "WakirWelle3SelfReferenceTrapFire": {
        "failure_mode_id": "Welle-3",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-3-self-reference-trap-fire"
        ),
    },
    "WakirWelle3SoloTopologyViolation": {
        "failure_mode_id": "Welle-3",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-3-solo-topology-violation"
        ),
    },
    "WakirWelle3StressOracleDivergence": {
        "failure_mode_id": "Welle-3",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-3-stress-oracle-divergence"
        ),
    },
    "WakirWelle4StateReadFail": {
        "failure_mode_id": "Welle-4",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-4-state-read-fail"
        ),
    },
    "WakirWelle4StateBackingMigrationRollback": {
        "failure_mode_id": "Welle-4",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-4-migration-rollback"
        ),
    },
    "WakirWelle4WriteLatencyP99Excess": {
        "failure_mode_id": "Welle-4",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-4-write-latency"
        ),
    },
    "WakirWelle5FsmPhantomTransition": {
        "failure_mode_id": "Welle-5",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-5-fsm-phantom"
        ),
    },
    "WakirWelle5LifecycleOrphanState": {
        "failure_mode_id": "Welle-5",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-5-orphan-state"
        ),
    },
    "WakirWelle5SignedOffBeforeWelle4Stable": {
        "failure_mode_id": "Welle-5",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-5-signoff-ordering"
        ),
    },
    "WakirWelle6SubscribeLoopStall": {
        "failure_mode_id": "Welle-6",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-6-subscribe-loop-stall"
        ),
    },
    "WakirWelle6SubscribeLoopReplayStorm": {
        "failure_mode_id": "Welle-6",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-6-replay-storm"
        ),
    },
    "WakirWelle7RecoveryRehearsalFail": {
        "failure_mode_id": "Welle-7",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-7-recovery-rehearsal-fail"
        ),
    },
    "WakirWelle7RecoveryWithoutPreAuditWarning": {
        "failure_mode_id": "Welle-7",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-7-iia-1130-default"
        ),
    },
    "WakirWelle7RecoveryReplayDivergence": {
        "failure_mode_id": "Welle-7",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-7-replay-divergence"
        ),
    },
    # Tag-64 Cutover-Day-Morgen Trinary-Verdict-Reactive-Routing
    # (Section 6 of catalog). The three alerts feed off the same
    # recording rule `wakir_cutover_day_morgen_verdict_class`; the
    # `routing_class` label on each alert steers the AlertManager
    # route-tree fan-out (standard / ops-on-call / ops-on-call-plus-
    # management). The bridge maps each alert through the trinary
    # ROUTING_CLASS_CHANNELS table below and the emitter receives
    # the channel-set as part of the labels passthrough.
    "WakirCutoverDayMorgenVerdictReady": {
        "failure_mode_id": "Tag-64-Ready",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/cutover-day-morgen-ready"
        ),
    },
    "WakirCutoverDayMorgenVerdictCaution": {
        "failure_mode_id": "Tag-64-Caution",
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/cutover-day-morgen-caution"
        ),
    },
    "WakirCutoverDayMorgenVerdictBlock": {
        "failure_mode_id": "Tag-64-Block",
        "severity": "page-storm",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/cutover-day-morgen-block"
        ),
    },
    # Tag-71 Welle-3 Pre-Auditor Routing Element (Noa SRE).
    # Positive-confirmation counterpart to the Tag-45 Class-B3
    # default-path warning; fires when Welle-3 Schluss-Audit-Signoff
    # arrives from an AR-designated external Pre-Auditor. Severity
    # info, routing class welle-3-pre-auditor-info. See
    # docs/observability/live-smoke-stability-window-operator-runbook.md
    # Section 6.
    "WakirPhase3Welle3PreAuditorDesignated": {
        "failure_mode_id": "Tag-71-B3-PositiveAck",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-3-pre-auditor-designated"
        ),
    },
    # Tag-72 Welle-4 State-Backing-Alert-Routing-Erweiterung
    # (Noa SRE). Two alerts close the state-backing positive-
    # confirmation + rollback-Pfad routing gap. Both carry the
    # `welle-4-state-backing-info` routing class; bridge routes
    # via ROUTING_CLASS_CHANNELS to ntfy:ar-hand-info +
    # activity-log:append. No on-call page from this block.
    "WakirPhase3Welle4StateBackingActive": {
        "failure_mode_id": "Tag-72-Welle4-StateBacking-Active",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-4-state-backing-active"
        ),
    },
    "WakirPhase3Welle4SnapshotRestoreTriggered": {
        "failure_mode_id": "Tag-72-Welle4-SnapshotRestore",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-4-snapshot-restore-triggered"
        ),
    },
    # Tag-73 Welle-5 Capability-Token-Rotation-Alert-Routing-
    # Erweiterung (Noa SRE). Two alerts close the Welle-5
    # capability-token rotation positive-confirmation + rotation-
    # lag routing gap. Both carry the
    # `welle-5-capability-token-info` routing class; bridge routes
    # via ROUTING_CLASS_CHANNELS to ntfy:ar-hand-info +
    # activity-log:append. No on-call page from this block.
    "WakirPhase3Welle5CapabilityTokenRotated": {
        "failure_mode_id": "Tag-73-Welle5-CapToken-Rotated",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-5-capability-token-rotated"
        ),
    },
    "WakirPhase3Welle5CapabilityTokenRotationLag": {
        "failure_mode_id": "Tag-73-Welle5-CapToken-RotationLag",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-5-capability-token-rotation-lag"
        ),
    },
    # Tag-74 Welle-6 Cross-Substrate-Parity-Alert-Routing-
    # Erweiterung (Noa SRE). Two alerts close the Welle-6
    # subscribe-loop positive-confirmation + consumer-lag
    # routing gap. Both carry the
    # `welle-6-subscribe-loop-info` routing class; bridge routes
    # via ROUTING_CLASS_CHANNELS to ntfy:ar-hand-info +
    # activity-log:append. No on-call page from this block.
    "WakirPhase3Welle6SubscribeLoopHealthy": {
        "failure_mode_id": "Tag-74-Welle6-SubscribeLoop-Healthy",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-6-subscribe-loop-healthy"
        ),
    },
    "WakirPhase3Welle6JetStreamConsumerLag": {
        "failure_mode_id": "Tag-74-Welle6-SubscribeLoop-ConsumerLag",
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-6-jetstream-consumer-lag"
        ),
    },
    # Tag-75 Welle-7 Final-Sealing-Alert-Routing-Erweiterung
    # (Noa SRE). Two alerts close the Welle-7 final-sealing
    # positive-confirmation + Pre-Auditor-signal routing gap.
    # Both carry the `welle-7-final-sealing-info` routing class;
    # bridge routes via ROUTING_CLASS_CHANNELS to
    # ntfy:ar-hand-info + activity-log:append. No on-call page
    # from this block.
    "WakirPhase3Welle7FinalSealingComplete": {
        "failure_mode_id": "Tag-75-Welle7-FinalSealing-Complete",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-7-final-sealing-complete"
        ),
    },
    "WakirPhase3Welle7PreAuditorSignalReceived": {
        "failure_mode_id": "Tag-75-Welle7-FinalSealing-PreAuditorSignal",
        "severity": "info",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "welle-7-pre-auditor-signal-received"
        ),
    },
}

# Tag-40 baseline alerts that pre-date the Pre-Mortem-extension.
# These are catalogued only to a runbook URL; failure_mode_id is null.
CATALOG_NON_PRE_MORTEM: dict[str, dict[str, str | None]] = {
    "WakirPhase3MarathonWelleRollback": {
        "failure_mode_id": None,
        "severity": "page",
        "runbook_url": "https://wakir-labs.example/runbooks/welle-rollback",
    },
    "WakirPhase3MarathonWelle3SoloViolation": {
        "failure_mode_id": None,
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/welle-3-solo-violation"
        ),
    },
    "WakirPhase3CompleteMarkerFalsePositive": {
        "failure_mode_id": None,
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "phase-3-complete-marker-drift"
        ),
    },
    "WakirPhase3CrossModulDriftDetected": {
        "failure_mode_id": None,
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/cross-modul-drift"
        ),
    },
    "WakirPhase3CrossModulStressScoreHigh": {
        "failure_mode_id": None,
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "cross-modul-stress-score-high"
        ),
    },
    "WakirPhase3MarathonHealthScoreLow": {
        "failure_mode_id": None,
        "severity": "warning",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "marathon-health-score-low"
        ),
    },
    "WakirPhase3MarathonHealthScoreCritical": {
        "failure_mode_id": None,
        "severity": "page",
        "runbook_url": (
            "https://wakir-labs.example/runbooks/"
            "marathon-health-score-critical"
        ),
    },
}


# Severity in the Prometheus rule label-namespace.  AlertManager
# does not normalise; the bridge maps the catalog severity onto the
# emitter severity-vocabulary (page/warning/info).
#
# Tag-64 addition: `page-storm` is a new severity for BLOCK-class
# Cutover-Day-Morgen verdicts. The emitter vocabulary tops out at
# `page`; the bridge maps `page-storm` -> `page` for the emitter
# event-severity field, but the `routing_class` label is preserved
# verbatim so the receiver/route-tree can fan out to the management
# channel as well as the on-call channel.
PROM_SEVERITY_TO_NOTIFY: dict[str, str] = {
    "page-storm": "page",
    "page": "page",
    "critical": "page",
    "warning": "warning",
    "ticket": "warning",
    "info": "info",
    "informational": "info",
}


# ---------------------------------------------------------------------------
# Tag-64 trinary-class -> channel-set routing table.
#
# The Selin Tag-64 Cutover-Day-Morgen Auto-Scheduler emits ONE of three
# verdict classes (READY / CAUTION / BLOCK) and the three new Tag-64
# alerts (WakirCutoverDayMorgenVerdictReady/Caution/Block) carry a
# `routing_class` label set to one of:
#
#   * "standard"                      (READY)
#   * "ops-on-call"                   (CAUTION)
#   * "ops-on-call-plus-management"   (BLOCK)
#
# The bridge looks up the routing_class via ROUTING_CLASS_CHANNELS
# and merges the channel-set into the NotifyEvent labels under the
# key `notify_channels` (comma-separated, deterministic order). The
# receiver-side route-tree consumes the channel-set; the bridge
# itself does NOT call the channels (no PagerDuty HTTP, no SMTP,
# no ntfy.sh -- those are Kai-Zone-H Operator-Hand surfaces).
#
# Each routing_class also pins an `escalation_after_seconds` value
# that the receiver consumes to schedule the unacknowledged-storm
# escalation (READY = no escalation; CAUTION = 600s = 10min;
# BLOCK = 300s = 5min, with AR escalation as the final hop).
# ---------------------------------------------------------------------------

ROUTING_CLASS_STANDARD = "standard"
ROUTING_CLASS_OPS_ON_CALL = "ops-on-call"
ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT = "ops-on-call-plus-management"
# Tag-71 Welle-3 Pre-Auditor positive-acknowledgement routing class.
# Same channels as the Tag-64 standard class (ntfy info + activity-log),
# but distinct routing-class string so the AlertManager route-tree can
# treat the Welle-3 Pre-Auditor designation as a named, auditable event
# rather than blending it into the standard info stream.
ROUTING_CLASS_WELLE_3_PRE_AUDITOR_INFO = "welle-3-pre-auditor-info"
# Tag-72 Welle-4 State-Backing routing class. Same channel-set as the
# standard / Welle-3 Pre-Auditor info classes (ntfy:ar-hand-info +
# activity-log:append) but distinct routing-class string so the
# AlertManager route-tree and audit-trail can attribute the events
# specifically to the Welle-4 state-backing routing extension.
ROUTING_CLASS_WELLE_4_STATE_BACKING_INFO = "welle-4-state-backing-info"
# Tag-73 Welle-5 Capability-Token-Rotation routing class. Same
# channel-set as the standard / Welle-3 Pre-Auditor / Welle-4
# State-Backing info classes (ntfy:ar-hand-info +
# activity-log:append) but distinct routing-class string so the
# AlertManager route-tree and audit-trail attribute the events
# specifically to the Welle-5 capability-token rotation extension.
ROUTING_CLASS_WELLE_5_CAPABILITY_TOKEN_INFO = "welle-5-capability-token-info"
# Tag-74 Welle-6 Cross-Substrate-Parity-Subscribe-Loop routing
# class. Same channel-set as the standard / Welle-3 Pre-Auditor /
# Welle-4 State-Backing / Welle-5 Capability-Token info classes
# (ntfy:ar-hand-info + activity-log:append) but distinct routing-
# class string so the AlertManager route-tree and audit-trail
# attribute the events specifically to the Welle-6 subscribe-loop
# cross-substrate-parity routing extension.
ROUTING_CLASS_WELLE_6_SUBSCRIBE_LOOP_INFO = "welle-6-subscribe-loop-info"
# Tag-75 Welle-7 Final-Sealing routing class. Same channel-set as
# the standard / Welle-3 Pre-Auditor / Welle-4 State-Backing /
# Welle-5 Capability-Token / Welle-6 Subscribe-Loop info classes
# (ntfy:ar-hand-info + activity-log:append) but distinct routing-
# class string so the AlertManager route-tree and audit-trail
# attribute the events specifically to the Welle-7 final-sealing
# routing extension (terminal welle in the KW-27 doppel-cutover
# sequence; closes the sealing handshake + Pre-Auditor-Signal
# positive-acknowledgement).
ROUTING_CLASS_WELLE_7_FINAL_SEALING_INFO = "welle-7-final-sealing-info"

VALID_ROUTING_CLASSES: frozenset[str] = frozenset(
    {
        ROUTING_CLASS_STANDARD,
        ROUTING_CLASS_OPS_ON_CALL,
        ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT,
        ROUTING_CLASS_WELLE_3_PRE_AUDITOR_INFO,
        ROUTING_CLASS_WELLE_4_STATE_BACKING_INFO,
        ROUTING_CLASS_WELLE_5_CAPABILITY_TOKEN_INFO,
        ROUTING_CLASS_WELLE_6_SUBSCRIBE_LOOP_INFO,
        ROUTING_CLASS_WELLE_7_FINAL_SEALING_INFO,
    }
)

ROUTING_CLASS_CHANNELS: dict[str, tuple[str, ...]] = {
    ROUTING_CLASS_STANDARD: (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
    ROUTING_CLASS_OPS_ON_CALL: (
        "pagerduty:sre-oncall",
        "ntfy:ar-hand",
        "activity-log:append",
    ),
    ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT: (
        "pagerduty:sre-oncall",
        "pagerduty:management",
        "ntfy:ar-hand",
        "activity-log:hold-marker",
    ),
    ROUTING_CLASS_WELLE_3_PRE_AUDITOR_INFO: (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
    ROUTING_CLASS_WELLE_4_STATE_BACKING_INFO: (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
    ROUTING_CLASS_WELLE_5_CAPABILITY_TOKEN_INFO: (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
    ROUTING_CLASS_WELLE_6_SUBSCRIBE_LOOP_INFO: (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
    ROUTING_CLASS_WELLE_7_FINAL_SEALING_INFO: (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
}

ROUTING_CLASS_ESCALATION_SECONDS: dict[str, int] = {
    ROUTING_CLASS_STANDARD: 0,
    ROUTING_CLASS_OPS_ON_CALL: 600,
    ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT: 300,
    ROUTING_CLASS_WELLE_3_PRE_AUDITOR_INFO: 0,
    ROUTING_CLASS_WELLE_4_STATE_BACKING_INFO: 0,
    ROUTING_CLASS_WELLE_5_CAPABILITY_TOKEN_INFO: 0,
    ROUTING_CLASS_WELLE_6_SUBSCRIBE_LOOP_INFO: 0,
    ROUTING_CLASS_WELLE_7_FINAL_SEALING_INFO: 0,
}

# Set of alertnames that REQUIRE a routing_class label (Tag-64
# trinary-routing contract). Used by the validator to fail-closed
# when an alert in this set is missing the label.
TRINARY_ROUTING_ALERTNAMES: frozenset[str] = frozenset(
    {
        "WakirCutoverDayMorgenVerdictReady",
        "WakirCutoverDayMorgenVerdictCaution",
        "WakirCutoverDayMorgenVerdictBlock",
    }
)

# Pin the expected (alertname, routing_class) pairs as a structural
# invariant: the trinary contract requires these exact three.
EXPECTED_TRINARY_ROUTING: dict[str, str] = {
    "WakirCutoverDayMorgenVerdictReady": ROUTING_CLASS_STANDARD,
    "WakirCutoverDayMorgenVerdictCaution": ROUTING_CLASS_OPS_ON_CALL,
    "WakirCutoverDayMorgenVerdictBlock": (
        ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT
    ),
}


def lookup_routing_class_channels(routing_class: str) -> tuple[str, ...]:
    """Return the channel-tuple for a routing_class, or () if unknown."""
    return ROUTING_CLASS_CHANNELS.get(routing_class, ())


def lookup_routing_class_escalation_seconds(routing_class: str) -> int:
    """Return the escalation-deadline for a routing_class (0 = none)."""
    return ROUTING_CLASS_ESCALATION_SECONDS.get(routing_class, 0)


def validate_trinary_routing_table_shape() -> dict[str, list[str]]:
    """Validate the in-module trinary routing-table structural invariants.

    Returns a dict with three lists:
    * ``missing_class`` -- routing-classes referenced by
      ``EXPECTED_TRINARY_ROUTING`` but not present in
      ``ROUTING_CLASS_CHANNELS``.
    * ``missing_channels`` -- routing-classes in
      ``ROUTING_CLASS_CHANNELS`` whose channel-tuple is empty.
    * ``missing_escalation`` -- routing-classes that lack an entry
      in ``ROUTING_CLASS_ESCALATION_SECONDS``.

    All three lists empty == trinary routing-table shape OK.
    """
    referenced_classes = set(EXPECTED_TRINARY_ROUTING.values())
    missing_class = sorted(referenced_classes - set(ROUTING_CLASS_CHANNELS))
    missing_channels = sorted(
        cls
        for cls in ROUTING_CLASS_CHANNELS
        if not ROUTING_CLASS_CHANNELS[cls]
    )
    missing_escalation = sorted(
        cls
        for cls in ROUTING_CLASS_CHANNELS
        if cls not in ROUTING_CLASS_ESCALATION_SECONDS
    )
    return {
        "missing_class": missing_class,
        "missing_channels": missing_channels,
        "missing_escalation": missing_escalation,
    }


# ---------------------------------------------------------------------------
# Pure-function core (no I/O).  These are the unit-test surface.
# ---------------------------------------------------------------------------


def lookup_catalog(alert_name: str) -> dict[str, Any] | None:
    """Return the catalog entry for an alert-name, or None."""
    if alert_name in ALERT_CATALOG:
        return dict(ALERT_CATALOG[alert_name])
    if alert_name in CATALOG_NON_PRE_MORTEM:
        return dict(CATALOG_NON_PRE_MORTEM[alert_name])
    return None


def normalise_severity(
    prom_severity: str | None, catalog_severity: str | None
) -> str:
    """Pick a notify-severity in the emitter vocabulary.

    Preference order: explicit Prometheus-label severity (if it maps),
    else catalog severity, else fallback ``info``.
    """
    if prom_severity and prom_severity in PROM_SEVERITY_TO_NOTIFY:
        return PROM_SEVERITY_TO_NOTIFY[prom_severity]
    if catalog_severity and catalog_severity in PROM_SEVERITY_TO_NOTIFY:
        return PROM_SEVERITY_TO_NOTIFY[catalog_severity]
    return "info"


def _truncate_summary(s: str, limit: int = 200) -> str:
    """Hard-cap the summary to ``limit`` chars (emitter validation)."""
    s = s.strip()
    if len(s) <= limit:
        return s
    # Reserve 3 chars for the ellipsis sentinel.
    return s[: limit - 3] + "..."


def map_alert_to_event_kwargs(
    alert: Mapping[str, Any],
    *,
    strict_catalog: bool = False,
) -> dict[str, Any] | None:
    """Map one AlertManager v4 ``alert`` object to ``make_event`` kwargs.

    Returns ``None`` if the alert should be skipped (resolved, or
    not in catalog under ``strict_catalog``).  Raises ``ValueError`` on
    malformed input (missing alertname, missing startsAt).
    """
    status = alert.get("status", "firing")
    if status == "resolved":
        return None

    labels = dict(alert.get("labels") or {})
    annotations = dict(alert.get("annotations") or {})

    alert_name = labels.get("alertname")
    if not alert_name:
        raise ValueError(
            "alert missing labels.alertname (cannot route)"
        )

    starts_at = alert.get("startsAt") or alert.get("starts_at")
    if not starts_at:
        raise ValueError(
            f"alert {alert_name!r} missing startsAt (cannot route)"
        )

    # AlertManager emits RFC3339 with sub-second precision and a
    # potential ``+00:00`` zone.  Normalise to ``YYYY-MM-DDTHH:MM:SSZ``
    # for emitter discipline.
    fired_at_utc = _normalise_starts_at(starts_at)

    catalog = lookup_catalog(alert_name)
    if catalog is None:
        if strict_catalog:
            return None
        catalog = {
            "failure_mode_id": None,
            "severity": labels.get("severity"),
            "runbook_url": annotations.get("runbook_url"),
        }

    severity = normalise_severity(
        labels.get("severity"), catalog.get("severity")
    )

    summary_raw = annotations.get("summary") or alert_name
    summary = _truncate_summary(summary_raw)

    description = annotations.get("description")
    runbook_url = annotations.get("runbook_url") or catalog.get("runbook_url")
    failure_mode_id = catalog.get("failure_mode_id")

    # Strip the alertname out of labels (the emitter records it
    # separately in ``alert_name``) so we don't double-store it.
    label_passthrough = {k: v for k, v in labels.items() if k != "alertname"}

    # Tag-64 trinary-routing enrichment: if the alert carries a
    # `routing_class` label that the bridge recognises, attach
    # the channel-set + escalation-deadline so the receiver-side
    # route-tree can fan out without re-reading the routing table.
    routing_class = labels.get("routing_class")
    if routing_class and routing_class in VALID_ROUTING_CLASSES:
        channels = lookup_routing_class_channels(routing_class)
        if channels:
            label_passthrough["notify_channels"] = ",".join(channels)
        esc = lookup_routing_class_escalation_seconds(routing_class)
        # Always set the escalation hint (0 == no escalation, still
        # informative for the receiver-side audit log).
        label_passthrough["escalation_after_seconds"] = str(esc)

    return {
        "alert_name": alert_name,
        "severity": severity,
        "summary": summary,
        "description": description,
        "runbook_url": runbook_url,
        "failure_mode_id": failure_mode_id,
        "labels": label_passthrough,
        "annotations": annotations,
        "source": "alert-rule-to-mira-notify-bridge",
        "fired_at_utc": fired_at_utc,
    }


_RFC3339_FRAC_TZ = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def _normalise_starts_at(value: str) -> str:
    """Normalise an AlertManager startsAt to ``YYYY-MM-DDTHH:MM:SSZ``.

    Accepts:
    * ``2026-05-18T10:11:12Z``
    * ``2026-05-18T10:11:12.345Z``
    * ``2026-05-18T10:11:12+00:00``
    * ``2026-05-18T10:11:12.345+02:00`` (caller's responsibility to
      normalise the zone; here we DO NOT shift, just append Z to mark
      UTC; the upstream Prometheus is expected to emit UTC).

    Strict variant: if neither fractional seconds nor a zone marker is
    present, append ``Z``.  If a non-Z zone is present, keep the
    timestamp and rewrite the zone to ``Z`` (we treat the value as
    already-UTC because Prometheus exports UTC by default).
    """
    s = value.strip()
    m = _RFC3339_FRAC_TZ.match(s)
    if not m:
        raise ValueError(f"startsAt not RFC-3339-like: {value!r}")
    base = m.group(1)
    return base + "Z"


# ---------------------------------------------------------------------------
# Envelope parsing.
# ---------------------------------------------------------------------------


def iter_envelope_alerts(envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract the ``alerts[]`` list from an AlertManager v4 envelope.

    Accepts both the canonical AlertManager v4 envelope (``{"version":
    "4", "alerts": [...]}``) and a bare alert-array (``[{...}, ...]``)
    for hermetic-test ergonomics.
    """
    if isinstance(envelope, list):
        return list(envelope)
    alerts = envelope.get("alerts")
    if alerts is None:
        raise ValueError("envelope missing 'alerts' key")
    if not isinstance(alerts, list):
        raise ValueError("envelope 'alerts' must be a list")
    return list(alerts)


# ---------------------------------------------------------------------------
# Routing surface (calls into the emitter library).
# ---------------------------------------------------------------------------


def route_envelope(
    envelope: Mapping[str, Any] | list,
    *,
    log_path: Path | None,
    also_stdout: bool = False,
    include_resolved: bool = False,
    strict_catalog: bool = False,
) -> dict[str, int]:
    """Route every alert in an envelope through the emitter.

    Returns a dict with counters:
    ``{"routed": N, "skipped_resolved": M, "skipped_unknown": K,
       "errors": E}``.
    """
    counters = {
        "routed": 0,
        "skipped_resolved": 0,
        "skipped_unknown": 0,
        "errors": 0,
    }
    alerts = iter_envelope_alerts(envelope)
    for alert in alerts:
        status = alert.get("status", "firing")
        if status == "resolved" and not include_resolved:
            counters["skipped_resolved"] += 1
            continue
        try:
            kwargs = map_alert_to_event_kwargs(
                alert, strict_catalog=strict_catalog
            )
        except ValueError as exc:
            counters["errors"] += 1
            sys.stderr.write(f"bridge: drop ({exc})\n")
            continue

        if kwargs is None:
            counters["skipped_unknown"] += 1
            continue

        try:
            event = emitter.make_event(**kwargs)
        except ValueError as exc:
            counters["errors"] += 1
            sys.stderr.write(
                f"bridge: emitter rejected "
                f"{kwargs.get('alert_name')!r}: {exc}\n"
            )
            continue

        emitter.emit_notify(
            event,
            log_path=log_path,
            also_stdout=also_stdout,
        )
        counters["routed"] += 1
    return counters


# ---------------------------------------------------------------------------
# Catalog cross-validator (parses the rules YAML and audits coverage).
# ---------------------------------------------------------------------------


def extract_alert_names_from_rules_yaml(yaml_text: str) -> list[str]:
    """Return alert names from a Prometheus rules YAML text.

    Uses a regex instead of a YAML library to keep the bridge
    stdlib-only and hermetic-test-friendly.  The Prometheus rules
    YAML format requires each alert at top-level of the rule item:
    ``- alert: <Name>`` on its own line.
    """
    names: list[str] = []
    pattern = re.compile(r"^\s*-\s*alert:\s*([A-Za-z0-9_]+)\s*$", re.MULTILINE)
    for match in pattern.finditer(yaml_text):
        names.append(match.group(1))
    return names


def audit_catalog_against_rules(
    yaml_text: str,
) -> dict[str, list[str]]:
    """Cross-check the rules YAML against the bridge catalog.

    Returns:
    * ``missing``  : alert-names found in the YAML that have no
      catalog entry (neither pre-mortem nor baseline).  Each such
      name SHOULD trigger an explicit catalog update.
    * ``stale``    : alert-names in the catalog that are no longer in
      the YAML (rule deleted but bridge still references it).
    """
    found = set(extract_alert_names_from_rules_yaml(yaml_text))
    catalogued = set(ALERT_CATALOG.keys()) | set(CATALOG_NON_PRE_MORTEM.keys())
    return {
        "missing": sorted(found - catalogued),
        "stale": sorted(catalogued - found),
    }


# ---------------------------------------------------------------------------
# CLI surface.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alert-rule-to-mira-notify-bridge",
        description=(
            "Bridge Prometheus AlertManager webhook payloads "
            "to Tag-46 Mira-Notify emitter."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    route = sub.add_parser(
        "route", help="Route an AlertManager envelope into the notify-log."
    )
    src = route.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--input",
        type=Path,
        help="Path to AlertManager v4 webhook JSON file.",
    )
    src.add_argument(
        "--stdin",
        action="store_true",
        help="Read AlertManager envelope JSON from stdin.",
    )
    route.add_argument(
        "--log-path",
        type=Path,
        default=Path(emitter.DEFAULT_NOTIFY_LOG),
        help=(
            "JSONL append-path the emitter writes to "
            f"(default {emitter.DEFAULT_NOTIFY_LOG})."
        ),
    )
    route.add_argument(
        "--stdout",
        action="store_true",
        help="Also echo each routed JSONL line to stdout.",
    )
    route.add_argument(
        "--include-resolved",
        action="store_true",
        help="Route 'resolved' alerts too (default: drop).",
    )
    route.add_argument(
        "--strict-catalog",
        action="store_true",
        help=(
            "Drop alerts whose alertname is not in ALERT_CATALOG "
            "nor CATALOG_NON_PRE_MORTEM."
        ),
    )

    audit = sub.add_parser(
        "validate-catalog",
        help=(
            "Cross-check the rules YAML against the bridge catalog "
            "and report missing/stale entries."
        ),
    )
    audit.add_argument(
        "--rules",
        type=Path,
        required=True,
        help="Path to phase-3-marathon-alerts.yaml (or compatible).",
    )

    # Tag-64: validate-trinary-routing subcommand. Confirms the
    # in-module trinary routing-table shape (3 classes, each with
    # at least one channel + an escalation deadline entry).
    sub.add_parser(
        "validate-trinary-routing",
        help=(
            "Validate Tag-64 trinary routing-table shape: 3 classes "
            "(standard/ops-on-call/ops-on-call-plus-management), "
            "non-empty channel-tuples, escalation-deadline entries."
        ),
    )

    return p


def cmd_route(args: argparse.Namespace) -> int:
    if args.stdin:
        text = sys.stdin.read()
    else:
        text = args.input.read_text(encoding="utf-8")
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid envelope JSON: {exc}", file=sys.stderr)
        return 2

    try:
        counters = route_envelope(
            envelope,
            log_path=args.log_path,
            also_stdout=args.stdout,
            include_resolved=args.include_resolved,
            strict_catalog=args.strict_catalog,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    summary = (
        f"routed={counters['routed']} "
        f"skipped_resolved={counters['skipped_resolved']} "
        f"skipped_unknown={counters['skipped_unknown']} "
        f"errors={counters['errors']}"
    )
    print(summary, file=sys.stderr)
    return 1 if counters["errors"] else 0


def cmd_validate_catalog(args: argparse.Namespace) -> int:
    text = args.rules.read_text(encoding="utf-8")
    audit = audit_catalog_against_rules(text)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 1 if (audit["missing"] or audit["stale"]) else 0


def cmd_validate_trinary_routing(_args: argparse.Namespace) -> int:
    shape = validate_trinary_routing_table_shape()
    print(json.dumps(shape, indent=2, sort_keys=True))
    bad = any(shape[k] for k in shape)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "route":
        return cmd_route(args)
    if args.cmd == "validate-catalog":
        return cmd_validate_catalog(args)
    if args.cmd == "validate-trinary-routing":
        return cmd_validate_trinary_routing(args)
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
