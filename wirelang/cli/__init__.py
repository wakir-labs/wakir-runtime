# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Wirelang operator-facing CLI surfaces (Phase-2 Sprint-9 Tag-3+).

This package collects Wirelang-side CLI helpers that ship as
operator entry-points under ``bin/wakir-*``. Each CLI shim under
``bin/`` is a thin wrapper that re-exports a ``main(argv)`` callable
from a sub-module here; the sub-modules are pure-Python (no I/O at
import time) so the hermetic test surface can drive them without
spinning up the operator environment.

Modules
-------

- :mod:`wirelang.cli.marker_stack_reduce` — operator-facing
  marker-stack reducer with audit-trace pretty-print and JSON
  pipeline-mode (Phase-2 Sprint-9 Tag-3 Teil A).
"""
