# SPDX-License-Identifier: Apache-2.0
"""Wirelang-side adapter modules.

This package contains wirelang-owned indirection layers over third-party
or substrate-specific APIs. Persona-container code imports adapter
surfaces; the adapters delegate to upstream libraries internally.

The adapter pattern is wirelang's stable surface boundary: upstream
library breaking changes touch only the adapter implementation; the
adapter-surface contract is the wirelang-side stable interface.

Current adapters:

- :mod:`wirelang.adapters.spiffe_workload_api` (Sprint-6 Tag-4 skeleton +
  Sprint-6 Tag-5 mock impl) — SPIFFE Workload API surface stub,
  indirection over the upstream ``spiffe`` PyPI package. Surface +
  hermetic in-process :class:`MockSpiffeWorkloadApiAdapter` for tests;
  real upstream-``spiffe``-backed functional implementation deferred to
  Sprint-6 Tag-6+ / Phase-2c.

Protocol-layer consolidation (ADR-0062 Cut-2, 2026-05-16)
---------------------------------------------------------
The Apache-2.0 adapter surface (``spiffe_workload_api``,
``real_spiffe_workload_api``, and the Stub-tier of
``real_nats_adapter``) is also published as
``wakir_protocol.adapters`` under the standalone
``wakir-labs/wakir-protocol`` repository.

The BUSL-1.1 live-tier of ``real_nats_adapter`` (``adapter.py``,
``connect_retry.py``) is runtime-internal and stays in this
repository.

External adopters who want the protocol-side adapter contracts
should depend on ``wakir-protocol`` and import from
``wakir_protocol.adapters`` directly.
"""
