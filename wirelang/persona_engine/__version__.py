# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see ./LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.

"""Canonical version anchor for the Wakir Persona-Engine package.

This module is the **single Python source of truth** for the engine's
version string. ``wirelang.persona_engine.__init__`` re-exports
``__version__`` from here, and ``engine.py`` re-exports
``ENGINE_VERSION`` from here. The Tag-58 0.5.3-rc1 bump factored the
literal out of ``__init__.py`` and ``engine.py`` into this dedicated
file so the hermetic version-consistency tests have a single import
target to assert against. Tag-62 (this bump) promotes the RC to
``0.5.3`` final — the rc1-suffix drop is a strict no-substrate
metadata-only seal in preparation for the KW-24 cutover-T0 window
(2026-06-08/09).

The version string is intentionally **machine-readable**:

* It MUST match the version stamped in the latest
  ``wirelang/persona_engine/MANIFEST-*.md`` §0 Version Header.
* It MUST match the ``manifest_version`` field in the matching
  ``infra/persona-engine/pin-pack-*.yaml``.
* It MUST match the release-notes filename under
  ``docs/persona-engine/<version>-release-notes.md``.

Tag-62 (2026-05-19) — Final-Bump Pre-Cutover-Sealing.
``0.5.3`` is the **rc1-suffix-drop** of ``0.5.3-rc1`` (Tag-58,
PR #372). It is a strict superset of ``0.5.3-rc1`` and a strict
superset of ``0.5.2-final-pre-cutover`` (Tag-52, PR #335) with the
Tag-57 OPEN-K1/K2/J1 closeouts absorbed as carry-forward
acknowledgements and the Tag-61 G5-PRE-CUTOVER-READY compositum
verdict sealed. The byte-shape of the ten BackendDecision boot
fan-out is unchanged vs. 0.5.3-rc1 — no record added, no record
renamed, no ENV-flag flipped, no crate version bumped, no
V-907-baseline refresh (the Tag-59 seal at
``v907-hash-baseline.json`` survives because the engine_version
metadata literal is the only changed surface and the V-907
composite hash is bounded to manifest §1 + pin-pack
``boot_wired_crates`` + engine.py resolver-block).

Scope discipline (Selin, ADR-0036/0043/0065/0066): this file
documents the engine version. It does **not** modify persona
definitions (Aisha-Domäne), WAT-core logic (Tomás-Domäne, Zone-K),
identity-substrate design (Reza-Domäne, Zone-L), or container-infra
beyond label-level coordination (Kai-Domäne, Zone-J).
"""

from __future__ import annotations

__all__ = ["__version__", "ENGINE_VERSION", "MANIFEST_RELPATH", "RELEASE_NOTES_RELPATH"]

# Canonical engine version. Bump in lockstep with the matching manifest
# and release-notes filenames.
__version__ = "0.5.3"

# Mirror alias used by engine.py for backend-decision payload stamping.
ENGINE_VERSION = __version__

# Repo-relative paths to the companion artefacts that pin this version.
# Tests assert these files exist and that their headers carry the same
# version string.
MANIFEST_RELPATH = "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md"
RELEASE_NOTES_RELPATH = "docs/persona-engine/0-5-3-final-release-notes.md"
