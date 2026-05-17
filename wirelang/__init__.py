# SPDX-License-Identifier: Apache-2.0
"""Wakir Wirelang package marker.

This file exists so that ``wirelang.identity`` (and future Python
sub-packages) can be imported by the test suite without requiring an
installed wheel. The package itself ships no top-level public API at
this stage; consumers should import from explicit sub-packages, e.g.::

    from wirelang.identity import generate_persona_did_document

Protocol-layer consolidation note (ADR-0062 Cut-2, 2026-05-16)
--------------------------------------------------------------
The Apache-2.0 substance under this package (``canonical/``,
``identity/`` minus ``federation_resolver.py``, ``schemas/``,
``builder/``, ``persona/`` minus ``persona_state_kv*``/
``recovery_drill_anchor``, ``nats/``, ``cli/`` minus
``marker_stack_*``, ``adapters/`` stub-tier, ``examples/``) has been
consolidated into the standalone Apache-2.0 + CC-BY-4.0 package
``wakir-protocol`` at https://github.com/wakir-labs/wakir-protocol.

In-tree imports under ``wirelang.*`` remain valid during the
transitional period. The BUSL-1.1 substance (``federation/``,
``persona_engine/``, the listed BUSL file-islands above) is
runtime-internal and stays in this repository permanently.

External adopters who want only the protocol layer should depend on
``wakir-protocol`` directly (``pip install 'wakir-runtime[protocol]'``
or ``pip install wakir-protocol``) and import from
``wakir_protocol.*`` instead of ``wirelang.*``. See
``docs/decisions/cut2-protocol-substance-classification.md`` for
the full path-to-target classification table.

Branch-Protection §4.2 promotion note (2026-05-17)
--------------------------------------------------
The ``cross-repo drift (wakir-runtime ↔ wakir-protocol)`` Required-
Status-Check was promoted into the wakir-runtime/main protection set
on 2026-05-17 04:35 CEST (Mira-Hand-Operator §4.2 command-block).
This touch ensures the post-apply doc-sync PR triggers the new gate
through the ``wirelang/**`` path-filter so the live state catches up.

Tag-15 mapping-fix trigger note (2026-05-17 05:40 CEST)
-------------------------------------------------------
PR #158 (Kai _RUNTIME_CHECKNAME_TO_WORKFLOW mapping-fix) needs the
cross-repo-drift Required-check to trigger; tests/-only PRs do not
match the workflow path-filter. Pfad A (workflow path-filter add for
this specific test file) is planned as a Tag-16 follow-up — for now,
no-op wirelang/__init__.py touch unblocks PR #158.

Tag-15 doppelbetrieb-score-aggregator trigger note (2026-05-17 06:00 CEST)
--------------------------------------------------------------------------
PR #160 (Tomás Doppelbetrieb-Score-Aggregator) is scripts/+tests/-only
and would not match the cross-repo-drift path-filter. No-op wirelang/
touch unblocks PR #160 per the PR #153/#158 pattern. Pfad A
(workflow path-filter precision-add) remains a Tag-16 follow-up.
"""
