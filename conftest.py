# SPDX-License-Identifier: Apache-2.0
"""Repository-root pytest configuration.

Ensures the repository root is on ``sys.path`` so test modules can
``import wirelang`` (and ``import wat`` etc.) without requiring a
``pip install -e .`` step. With ``pyproject.toml`` providing proper
editable-install support, this file becomes redundant once an editable
install is performed; it is harmless either way.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
