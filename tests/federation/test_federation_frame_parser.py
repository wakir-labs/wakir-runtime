# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Auftrag-literal-path re-export of the federation-frame parser tests.

The Tag-14 Mini-Welle Auftrag named this path explicitly:

    "10+ Python-Tests in `tests/federation/test_federation_frame_parser.py`"

The canonical suite lives at
``wirelang/tests/test_federation_frame_parser.py`` because the Wakir
CI lane (``.github/workflows/tests.yml``) invokes pytest as
``python -m pytest wirelang/`` and only files under ``wirelang/`` are
collected by the production / sandbox lanes. This file re-exports the
same tests so a developer running ``pytest tests/`` from the repo
root sees them at the auftrag-literal location.

If you change the canonical suite, you do NOT need to touch this file —
the re-export below picks the new tests up automatically.
"""

from __future__ import annotations

# `noqa: F401, F403` — wildcard re-export is intentional; flake8 should
# not complain about names imported but not used.
from wirelang.tests.test_federation_frame_parser import *  # noqa: F401, F403
