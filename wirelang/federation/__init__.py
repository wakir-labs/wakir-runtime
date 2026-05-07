# SPDX-License-Identifier: Apache-2.0
"""Wakir Wirelang federation sub-package (V-908).

Phase-1b Sprint-2 Tag-3 introduces the live ``peer_org`` /
``federation_route`` Datalog-predicate evaluator. The federation
substrate proper (DNS-anchor resolver, FTD verifier, federation
resolver pipeline) lives in :mod:`wirelang.identity`; this
sub-package owns the *predicate-evaluator* layer that consumes
those primitives and exposes a deterministic accept/reject
verdict for Wirelang Layer-3 tokens that carry V-908 caveats.

Public surface:

- :class:`wirelang.federation.n2_evaluator.FederationContext`
- :class:`wirelang.federation.n2_evaluator.FederationEvaluator`
- :class:`wirelang.federation.n2_evaluator.RouteRegistry`
- :class:`wirelang.federation.n2_evaluator.RouteRegistryEntry`
- exception hierarchy: :class:`PeerOrgMismatchError`,
  :class:`FederationRouteUnknownError`,
  :class:`FederationRouteExpiredError`,
  :class:`FederationPredicateArgumentError`.
"""
