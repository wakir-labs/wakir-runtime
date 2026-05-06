# SPDX-License-Identifier: Apache-2.0
"""Wirelang frame-builder helper package.

Convenience constructors for Wirelang Layer-1 frames used in tests and
integration code. The builder produces dicts that conform to
``wirelang/schemas/layer-1-wire.json``; producers that need the
canonical hash are expected to round-trip through ``rfc8785`` as in
the WAT leaf-projection module.

Public surface:

- :func:`build_layer_1_frame` — single-call constructor for Layer-1
  frames with optional Layer-2 envelope and Layer-3 capability refs.
- :class:`FrameBuilder` — fluent builder with sane Wakir defaults for
  test scenarios.

The package is import-light: it depends on the standard library only.
"""

from __future__ import annotations

from .frame_builder import (
    FrameBuilder,
    build_layer_1_frame,
    capability_token_hash_ref,
)

__all__ = [
    "FrameBuilder",
    "build_layer_1_frame",
    "capability_token_hash_ref",
]
