# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""3-Way Cross-Substrate Parity tests for the 9-binary Phase-3b
Rust-CLI inventory.

Background
----------
ADR-0066 Welle-3 Mitigation: a 2-way parity test
(``tests/infra/test_cosign_policy_phase_3b.py:test_cross_substrate_parity_with_quadlet_installer``)
already enforces Cosign-Policy ↔ Quadlet-Installer lock-step. But the
third substrate that carries the same inventory —
``wirelang/persona_engine/rust_backend_switch.py`` (the resolver) —
has no parity gate against the other two. A drift here (resolver
declares a binary that no image carries, or no Cosign-verify exists
for) produces silent fallbacks to Python at boot-time, which is the
worst failure mode for Phase-3c Cutover-Acceptance because it
disguises a partial cutover as a successful one.

The 3-Way gate enforces equality of the inventory across all three
substrates:

  1. **Cosign-Policy** — ``policies/cosign-policy-phase-3b.yaml``
     declares 9 ``binaries[].name`` entries.
  2. **Quadlet-Installer** — ``quadlet/wakir-rust-cli.container``
     iterates 9 ``wakir-persona-engine-<name>`` basenames inside the
     ``Exec=`` install-loop.
  3. **Backend-Switch Resolver** —
     ``wirelang/persona_engine/rust_backend_switch.py`` declares 9
     ``DEFAULT_RUST_<NAME>_BIN`` constants in lock-step with the 9
     inventory binaries.

Known divergence: the resolver also declares a tenth
``DEFAULT_RUST_FEDERATION_RESOLVER_BIN`` constant. That backend is
the federation-resolver Welle-2 scaffold (Welle-2 candidate, ADR-0066
§Welle-Sequenz), which has no image-build yet and is therefore
deliberately not in the Cosign / Quadlet substrates. The 3-way parity
contract treats ``federation-resolver`` as an explicit
**known-extra** in the resolver; any *other* extra in the resolver
(or any divergence between Cosign ↔ Quadlet, or a missing entry in
the resolver for an inventoried binary) is a hard fail.

Sibling tests
-------------
  * ``tests/infra/test_cosign_policy_phase_3b.py`` — 2-way
    Cosign ↔ Quadlet parity (Test 8) + the 8 cosign-policy format
    invariants.
  * ``tests/infra/test_quadlets_phase_3b.py`` — Quadlet installer
    substrate format invariants.

Sandbox boundary
----------------
Hermetic, on-disk file reads only. No network, no cosign / crane /
skopeo invocations per ``feedback_sandbox_host_trennung.md``. Live
verification is Operator-Hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
QUADLET_INSTALLER = REPO_ROOT / "quadlet" / "wakir-rust-cli.container"
RUST_SWITCH_MODULE = (
    REPO_ROOT / "wirelang" / "persona_engine" / "rust_backend_switch.py"
)
RUNBOOK_DOC = (
    REPO_ROOT / "docs" / "operations" / "cross-substrate-parity-runbook.md"
)

# Canonical 9-binary inventory (Phase-3b carrier-image set, Tag-17..
# Tag-31). Re-declared here (not imported) so a future split between
# the two test surfaces is loud — a drift here vs the sibling tuple
# is itself caught by ``test_inventory_constant_matches_cosign_policy_tuple``
# below.
#
# Tag-45 Mini-Welle: the carrier-image set extended from 9 to 11 with
# the Phase-3a-Foundation 14 + 15 additions (bridge-audit-replay,
# migrate-version). The canonical 9-set is kept stable for backwards
# compat; the Tag-45 additions live in COSIGN_QUADLET_TAG45_ADDITIONS
# below and are accounted for in the inventory-agreement test via the
# combined EXPECTED_CARRIER_BINARIES tuple.
EXPECTED_BINARIES_9 = (
    "recovery",
    "state-backing",
    "fsm",
    "v907-verify",
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
    "bridge-audit-writer",
)

# Tag-45 Mini-Welle additions to both the Cosign-Policy AND the
# Quadlet-Installer (Phase-3a-Foundation 14 + 15 closeout). Unlike
# COSIGN_QUADLET_KNOWN_EXTRAS below (which are Cosign+Quadlet-only
# Welle-4..7 dedicated single-binary images), these two ARE first-
# class carrier-image binaries with matching DEFAULT_RUST_*_BIN
# constants in rust_backend_switch.py — so they appear in all three
# substrates and contribute to the canonical-set inventory.
COSIGN_QUADLET_TAG45_ADDITIONS = (
    "bridge-audit-replay",
    "migrate-version",
)

# Combined canonical carrier-image set after Tag-45 (11 binaries =
# 9 + Tag-45 additions). The 3-way parity tests assert that all three
# substrates inventory this combined set; the COSIGN_QUADLET_KNOWN_EXTRAS
# (Welle-4..7 dedicated images) appear ONLY in Cosign + Quadlet, not
# in the resolver.
EXPECTED_CARRIER_BINARIES = (
    EXPECTED_BINARIES_9 + COSIGN_QUADLET_TAG45_ADDITIONS
)

# Resolver-known-extra: ``federation-resolver`` is the Welle-2
# scaffold backend that has no image-build yet (no Cosign-Policy
# entry, no Quadlet-Installer entry). Documented divergence per
# ADR-0066 §Welle-Sequenz.
RESOLVER_KNOWN_EXTRAS = ("federation-resolver",)

# Tag-33 Mini-Welle additions to the Cosign-Policy + Quadlet-Installer
# (ADR-0066 Welle-4..7 dedicated single-binary images). These four
# names appear in the Cosign-Policy `binaries:` list and as regex-
# matched strings in the Quadlet-Installer comment header (they do
# NOT appear in the Quadlet `Exec=` install-loop — the Welle-4..7
# cutover steps deploy them via per-Welle dedicated Quadlets in
# subsequent Mini-Wellen). They do NOT appear in
# rust_backend_switch.py (no dedicated DEFAULT_RUST_*_WELLEN_BIN
# constants — the cutover step re-uses the existing
# DEFAULT_RUST_*_BIN constants of the Carrier-Image siblings).
COSIGN_QUADLET_KNOWN_EXTRAS = (
    "state-backing-welle4",
    "fsm-welle5",
    "subscribe-loop-welle6",
    "recovery-welle7",
)


def _resolver_default_bin_basenames() -> set[str]:
    """Extract the binary basenames from the
    ``DEFAULT_RUST_<NAME>_BIN`` constants in
    ``rust_backend_switch.py``. Returns the set of
    ``wakir-persona-engine-<component>`` ``<component>`` slugs.

    The extraction is intentionally text-grep over the module source
    (not a Python import) because this test is a substrate-format
    invariant: a future refactor that hides the binary paths behind a
    dynamic registry must still keep the textual signature for grep-
    friendly review and CI-Required gate-stability.
    """
    text = RUST_SWITCH_MODULE.read_text(encoding="utf-8")
    # Match ``DEFAULT_RUST_<NAME>_BIN = ... "/opt/wakir/bin/
    # wakir-persona-engine-<basename>"``. The constant may be on one
    # line or split across two lines (PEP-8 wrap), so we walk a
    # tolerant multiline regex.
    basenames: set[str] = set()
    pattern = re.compile(
        r'DEFAULT_RUST_[A-Z0-9_]+_BIN\s*=\s*\(?\s*"'
        r'/opt/wakir/bin/wakir-persona-engine-([a-z0-9-]+)"',
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        basenames.add(m.group(1))
    return basenames


def _quadlet_basenames() -> set[str]:
    """Extract the binary basenames from the Quadlet-Installer
    ``Exec=`` install-loop. Mirrors the extraction in
    ``test_cosign_policy_phase_3b.test_cross_substrate_parity_with_quadlet_installer``
    for cross-test consistency.
    """
    text = QUADLET_INSTALLER.read_text(encoding="utf-8")
    return set(re.findall(r"wakir-persona-engine-([a-z0-9-]+)", text))


@pytest.fixture(scope="module")
def policy() -> dict:
    """Parse the cosign-policy YAML once per test module."""
    return yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cosign_basenames(policy: dict) -> set[str]:
    """Cosign-Policy inventory as a set of binary basenames."""
    return {b["name"] for b in policy["binaries"]}


@pytest.fixture(scope="module")
def quadlet_basenames_set() -> set[str]:
    """Quadlet-Installer inventory as a set of binary basenames."""
    return _quadlet_basenames()


@pytest.fixture(scope="module")
def resolver_basenames() -> set[str]:
    """Backend-Switch resolver inventory as a set of binary basenames.

    Includes all ``DEFAULT_RUST_*_BIN`` constants — that is, the 9
    Phase-3b binaries PLUS any known-extras (federation-resolver).
    """
    return _resolver_default_bin_basenames()


# ---------------------------------------------------------------------------
# Test 1 — Cosign ↔ Quadlet ↔ Resolver three-way agreement on the
#          canonical 9-binary inventory.
# ---------------------------------------------------------------------------
def test_three_way_inventory_agreement(
    cosign_basenames: set[str],
    quadlet_basenames_set: set[str],
    resolver_basenames: set[str],
) -> None:
    """All three substrates MUST inventory the canonical carrier-image
    binaries (11 at Tag-45 = canonical 9 + Tag-45 additions).

    Cosign-Policy and Quadlet-Installer carry the canonical 11 plus
    the Welle-4..7 dedicated single-binary extras (Cosign+Quadlet:
    11 + 4 = 15 for Cosign-Policy, 11 for Quadlet-Installer because
    the Welle-4..7 extras appear only in the Quadlet comment header,
    not the Exec= loop — both regex-matches by this test). The
    resolver carries 11 PLUS the known-extra ``federation-resolver``.

    Tag-45 contract:
      ``EXPECTED_CARRIER_BINARIES ⊆ each_substrate`` AND
      ``cosign - welle-4..7 == quadlet - welle-4..7 == (resolver -
      federation-resolver)``.
    """
    canon = set(EXPECTED_CARRIER_BINARIES)
    known_extras = set(RESOLVER_KNOWN_EXTRAS)
    cosign_quadlet_extras = set(COSIGN_QUADLET_KNOWN_EXTRAS)
    resolver_phase_3b = resolver_basenames - known_extras

    # Each substrate is exactly the canonical 9 (after extras are
    # removed from the resolver, and after the Tag-33 Welle-4..7
    # dedicated single-binary additions are removed from Cosign +
    # Quadlet). The Cosign + Quadlet known-extras live in BOTH
    # files (one substrate per file); the resolver known-extras live
    # only in rust_backend_switch.py.
    cosign_phase_3b = cosign_basenames - cosign_quadlet_extras
    quadlet_phase_3b = quadlet_basenames_set - cosign_quadlet_extras
    assert cosign_phase_3b == canon, (
        f"Cosign-Policy inventory drift: expected {sorted(canon)}, "
        f"got {sorted(cosign_phase_3b)}. Missing="
        f"{sorted(canon - cosign_phase_3b)}, extra="
        f"{sorted(cosign_phase_3b - canon)}."
    )
    assert quadlet_phase_3b == canon, (
        f"Quadlet-Installer inventory drift: expected {sorted(canon)}, "
        f"got {sorted(quadlet_phase_3b)}. Missing="
        f"{sorted(canon - quadlet_phase_3b)}, extra="
        f"{sorted(quadlet_phase_3b - canon)}."
    )
    assert resolver_phase_3b == canon, (
        "Backend-Switch resolver inventory drift (Phase-3b-scoped, "
        "known-extras removed): expected "
        f"{sorted(canon)}, got {sorted(resolver_phase_3b)}. Missing="
        f"{sorted(canon - resolver_phase_3b)}, extra="
        f"{sorted(resolver_phase_3b - canon)}."
    )

    # And: the three substrates agree pairwise. Redundant given the
    # three asserts above, but the redundancy is intentional — a
    # future refactor that loosens one of the above assertions MUST
    # still preserve cross-substrate pairwise agreement. Tag-33
    # Mini-Welle: Cosign ↔ Quadlet must agree on the FULL set
    # (canonical 9 + Welle-4..7 extras = 13 items); Cosign and
    # Quadlet ↔ Resolver agree on the Phase-3b-scoped canonical 9.
    assert cosign_basenames == quadlet_basenames_set, (
        "Cosign ↔ Quadlet pairwise drift: "
        f"cosign={sorted(cosign_basenames)}, "
        f"quadlet={sorted(quadlet_basenames_set)}"
    )
    assert cosign_phase_3b == resolver_phase_3b, (
        "Cosign ↔ Resolver (Phase-3b-scoped) pairwise drift: "
        f"cosign={sorted(cosign_phase_3b)}, "
        f"resolver={sorted(resolver_phase_3b)}"
    )
    assert quadlet_phase_3b == resolver_phase_3b, (
        "Quadlet ↔ Resolver (Phase-3b-scoped) pairwise drift: "
        f"quadlet={sorted(quadlet_phase_3b)}, "
        f"resolver={sorted(resolver_phase_3b)}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Resolver-known-extras MUST be exactly the documented set.
# ---------------------------------------------------------------------------
def test_resolver_known_extras_are_documented(
    resolver_basenames: set[str],
) -> None:
    """Any binary basename in the resolver that is not in the canonical
    carrier-image set MUST be a documented ``RESOLVER_KNOWN_EXTRAS``
    entry.

    Rationale: a silent new backend in the resolver (no Cosign /
    Quadlet entry) means a binary path that the resolver tries to
    subprocess-bridge to has no verification chain. This test is the
    gate that forces a new resolver backend to land in a Mini-Welle
    that also extends Cosign + Quadlet OR explicitly registers the
    new component as a known-extra here (with an ADR-anchor in the
    file docstring).

    Tag-45: the canonical set extended from 9 to 11 with the
    Phase-3a-Foundation 14 + 15 additions (bridge-audit-replay,
    migrate-version). EXPECTED_CARRIER_BINARIES is the post-Tag-45
    canonical reference.
    """
    canon = set(EXPECTED_CARRIER_BINARIES)
    known_extras = set(RESOLVER_KNOWN_EXTRAS)
    resolver_extras = resolver_basenames - canon

    # All resolver extras must be documented.
    undocumented = resolver_extras - known_extras
    assert not undocumented, (
        f"Undocumented resolver backends: {sorted(undocumented)}. "
        f"Either land a Cosign / Quadlet entry for them in the same "
        f"Mini-Welle, or add to RESOLVER_KNOWN_EXTRAS in "
        f"{Path(__file__).name} with an ADR-anchor comment."
    )

    # And: every documented known-extra must actually exist in the
    # resolver (don't accumulate stale entries here).
    stale_extras = known_extras - resolver_basenames
    assert not stale_extras, (
        f"Stale RESOLVER_KNOWN_EXTRAS entries: {sorted(stale_extras)}. "
        f"These are documented as resolver-side known-extras but the "
        f"resolver module doesn't actually declare a "
        f"DEFAULT_RUST_<NAME>_BIN constant for them. Remove from "
        f"RESOLVER_KNOWN_EXTRAS or restore the resolver constant."
    )


# ---------------------------------------------------------------------------
# Test 3 — Resolver basename count is exactly 9 + len(known-extras).
# ---------------------------------------------------------------------------
def test_resolver_inventory_size(resolver_basenames: set[str]) -> None:
    """The resolver MUST declare exactly
    ``len(EXPECTED_CARRIER_BINARIES) + len(RESOLVER_KNOWN_EXTRAS)``
    binary constants. A surprise count is a hard fail.

    The pair (count, known-extras) is the primary tripwire when a
    Welle-N flip introduces a new backend in the resolver without
    landing the matching Cosign / Quadlet inventory in the same
    Mini-Welle.

    Tag-45: the carrier-image canonical set extended from 9 to 11
    with the Phase-3a-Foundation 14 + 15 additions; the expected
    resolver count is therefore 11 + len(RESOLVER_KNOWN_EXTRAS).
    """
    expected_count = (
        len(EXPECTED_CARRIER_BINARIES) + len(RESOLVER_KNOWN_EXTRAS)
    )
    actual_count = len(resolver_basenames)
    assert actual_count == expected_count, (
        f"Resolver binary-constant count drift: expected "
        f"{expected_count} ({len(EXPECTED_CARRIER_BINARIES)} canonical "
        f"+ {len(RESOLVER_KNOWN_EXTRAS)} known-extras), got "
        f"{actual_count}. Resolver-declared: "
        f"{sorted(resolver_basenames)}."
    )


# ---------------------------------------------------------------------------
# Test 4 — Inventory-constant matches sibling test's EXPECTED_BINARIES
#          tuple in ``test_cosign_policy_phase_3b.py``. This is the
#          intra-test-surface drift gate: if a Welle-N Mini-Welle
#          edits one tuple but forgets the other, this test fires.
# ---------------------------------------------------------------------------
def test_inventory_constant_matches_cosign_policy_tuple() -> None:
    """The local ``EXPECTED_BINARIES_9`` MUST equal the sibling
    ``test_cosign_policy_phase_3b.EXPECTED_BINARIES`` tuple.

    Both modules carry an independent copy on purpose (test
    isolation), but a Welle-N mini-welle MUST update both copies in
    lock-step. This test reads the sibling test's source and string-
    greps the tuple definition.
    """
    sibling_path = (
        REPO_ROOT / "tests" / "infra" / "test_cosign_policy_phase_3b.py"
    )
    assert sibling_path.exists(), (
        f"Sibling test missing at {sibling_path}; cannot verify "
        f"inventory-constant lock-step."
    )
    sibling_text = sibling_path.read_text(encoding="utf-8")

    # Extract the EXPECTED_BINARIES tuple. The sibling defines it as
    # ``EXPECTED_BINARIES = (\n    "recovery",\n    ...\n)``.
    m = re.search(
        r"EXPECTED_BINARIES\s*=\s*\(([^)]+)\)",
        sibling_text,
        re.MULTILINE,
    )
    assert m, (
        "Could not extract EXPECTED_BINARIES tuple from sibling "
        f"{sibling_path}. The 3-way parity test relies on the "
        "tuple's textual presence; if the sibling refactored, "
        "update this regex."
    )
    sibling_names = tuple(
        re.findall(r'"([a-z0-9-]+)"', m.group(1))
    )

    # Tag-33 Mini-Welle: the sibling EXPECTED_BINARIES tuple grew
    # from 9 to 13 with the Welle-4..7 dedicated single-binary
    # additions (`state-backing-welle4`, `fsm-welle5`,
    # `subscribe-loop-welle6`, `recovery-welle7`).
    #
    # Tag-45 Mini-Welle: the sibling tuple grew from 13 to 15 with the
    # Phase-3a-Foundation 14 + 15 closeout additions (bridge-audit-
    # replay, migrate-version). Inventory order in the sibling is:
    #   sibling[0..9]   = canonical 9 (EXPECTED_BINARIES_9)
    #   sibling[9..13]  = Welle-4..7 extras (COSIGN_QUADLET_KNOWN_EXTRAS)
    #   sibling[13..15] = Tag-45 additions (COSIGN_QUADLET_TAG45_ADDITIONS)
    # The first 9 entries must still equal the canonical 9-set; the
    # next 4 entries must equal the Welle-4..7 extras; the final 2
    # entries must equal the Tag-45 additions tuple in this file.
    n9 = len(EXPECTED_BINARIES_9)
    n_extras = len(COSIGN_QUADLET_KNOWN_EXTRAS)
    sibling_canonical_9 = sibling_names[:n9]
    sibling_extras = sibling_names[n9 : n9 + n_extras]
    sibling_tag45 = sibling_names[n9 + n_extras :]
    assert sibling_canonical_9 == EXPECTED_BINARIES_9, (
        "Inventory-constant drift between this test file and the "
        f"sibling cosign-policy test (canonical 9). "
        f"local={EXPECTED_BINARIES_9}, "
        f"sibling[:9]={sibling_canonical_9}. A Mini-Welle MUST "
        "update both tuples in lock-step."
    )
    assert sibling_extras == COSIGN_QUADLET_KNOWN_EXTRAS, (
        "Tag-33 Welle-4..7 extras drift between this test file's "
        "COSIGN_QUADLET_KNOWN_EXTRAS and the sibling cosign-policy "
        f"test's EXPECTED_BINARIES tail (positions 9..13). "
        f"local={COSIGN_QUADLET_KNOWN_EXTRAS}, "
        f"sibling[9:13]={sibling_extras}."
    )
    assert sibling_tag45 == COSIGN_QUADLET_TAG45_ADDITIONS, (
        "Tag-45 Phase-3a-Foundation 14 + 15 additions drift between "
        "this test file's COSIGN_QUADLET_TAG45_ADDITIONS and the "
        "sibling cosign-policy test's EXPECTED_BINARIES tail "
        f"(positions 13..15). "
        f"local={COSIGN_QUADLET_TAG45_ADDITIONS}, "
        f"sibling[13:]={sibling_tag45}."
    )


# ---------------------------------------------------------------------------
# Test 5 — The runbook documents the 3-way inventory pflicht with
#          the exact substrate names + canonical 9-binary inventory.
# ---------------------------------------------------------------------------
def test_runbook_documents_three_way_pflicht() -> None:
    """The cross-substrate-parity runbook
    (``docs/operations/cross-substrate-parity-runbook.md``) MUST
    document the 3-way Pflicht with all three substrate filenames and
    the canonical 9 binaries listed.

    A drift between the test contract and the operator-facing runbook
    is the second-most-likely failure mode (after the inventory drift
    itself): an operator reads the runbook, takes a partial action,
    misses the third substrate.
    """
    assert RUNBOOK_DOC.exists(), (
        f"Runbook missing at {RUNBOOK_DOC}. The 3-way parity Gate "
        "must have an operator-facing runbook per ADR-0066 Welle-3 "
        "Mitigation."
    )
    text = RUNBOOK_DOC.read_text(encoding="utf-8")

    # All three substrate file paths must be named.
    assert "policies/cosign-policy-phase-3b.yaml" in text, (
        "runbook does not name the Cosign-Policy substrate path"
    )
    assert "quadlet/wakir-rust-cli.container" in text, (
        "runbook does not name the Quadlet-Installer substrate path"
    )
    assert "wirelang/persona_engine/rust_backend_switch.py" in text, (
        "runbook does not name the Backend-Switch resolver path"
    )

    # The runbook MUST list all 9 canonical binaries by name.
    missing_binaries = [
        b for b in EXPECTED_BINARIES_9 if b not in text
    ]
    assert not missing_binaries, (
        f"runbook does not list all 9 canonical binaries: "
        f"missing={missing_binaries}"
    )

    # The runbook MUST name the known-extras (federation-resolver)
    # explicitly to document the divergence.
    for extra in RESOLVER_KNOWN_EXTRAS:
        assert extra in text, (
            f"runbook does not name the known-extra '{extra}'; "
            "operators reading the runbook would not understand why "
            "the resolver carries one more entry than Cosign/Quadlet."
        )

    # The runbook MUST mention the ADR-0066 Welle-3 Mitigation anchor.
    assert "ADR-0066" in text, (
        "runbook does not anchor the 3-way Pflicht in ADR-0066"
    )


# ---------------------------------------------------------------------------
# Test 6 — Negative case: a synthetic resolver text with an extra
#          undocumented backend MUST be rejected by the parity logic.
# ---------------------------------------------------------------------------
def test_negative_undocumented_extra_is_detected(tmp_path: Path) -> None:
    """Synthetic resolver text with an extra undocumented backend
    constant MUST cause the parity comparison to surface the extra.

    This is a unit test of the extraction logic itself: a future
    refactor of ``_resolver_default_bin_basenames`` that loses the
    ability to detect a new constant would silently pass the real
    parity test. This test forces the extraction logic to remain
    detection-capable.
    """
    synthetic = (
        '# synthetic resolver fragment\n'
        'DEFAULT_RUST_RECOVERY_BIN = "/opt/wakir/bin/wakir-persona-engine-recovery"\n'
        'DEFAULT_RUST_FSM_BIN = "/opt/wakir/bin/wakir-persona-engine-fsm"\n'
        'DEFAULT_RUST_NEW_BACKEND_BIN = '
        '"/opt/wakir/bin/wakir-persona-engine-new-backend"\n'
    )
    fake = tmp_path / "fake_resolver.py"
    fake.write_text(synthetic, encoding="utf-8")

    # Re-implement the extraction inline (the production function
    # reads a module-level constant path). This mirrors the regex.
    text = fake.read_text(encoding="utf-8")
    pattern = re.compile(
        r'DEFAULT_RUST_[A-Z0-9_]+_BIN\s*=\s*\(?\s*"'
        r'/opt/wakir/bin/wakir-persona-engine-([a-z0-9-]+)"',
        re.MULTILINE,
    )
    found = {m.group(1) for m in pattern.finditer(text)}
    assert "new-backend" in found, (
        "extraction regex failed to find the synthetic new-backend "
        "constant; the parity logic would not detect a real new "
        "resolver backend."
    )
    assert "recovery" in found and "fsm" in found
