# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic invariants for the Tag-45 Quadlet+Cosign 15-binary
substrate refresh.

Tag-45 Mini-Welle closes Reza's Phase-3a-Foundation 15-module sweep
by extending both the Cosign-Policy (13 -> 15 binaries) and the
Quadlet installer Exec= loop (9 -> 11 carrier-image binaries). The
two additions are:

  * ``bridge-audit-replay`` (Tag-37 Mini-Welle PR #246 — 14. Phase-3a
    Modul; deterministic-replay-oracle canonical-trace bridge).
  * ``migrate-version`` (Tag-38 Mini-Welle PR #250 — 15. Phase-3a
    Modul; engine-version migration pre-flight decision canonical-
    trace; closes the Phase-3a-Foundation sweep at 15/15).

This module ships 12 hermetic invariants covering the Tag-45 substrate
slice. Live verification (cosign, crane, podman, systemctl) is
Operator-Hand per ``feedback_sandbox_host_trennung.md`` + ADR-0051;
this test surface reads files on disk only.

Sibling tests
-------------
  * ``tests/infra/test_cosign_policy_phase_3b.py`` — Cosign-Policy
    full-shape invariants (extended to 15 binaries at Tag-45).
  * ``tests/infra/test_quadlets_phase_3b.py`` — Quadlet installer
    full-shape invariants (extended to 11 carrier-image binaries at
    Tag-45).
  * ``tests/infra/test_quadlet_selinux_relabel.py`` — global
    SELinux-relabel discipline.

Test-Vector index
-----------------
  * ``TV-T45-01`` policy at 15-binary inventory.
  * ``TV-T45-02`` Quadlet installer at 11-binary carrier-image set.
  * ``TV-T45-03`` Tag-45 additions present in policy with required keys.
  * ``TV-T45-04`` Tag-45 additions present in Quadlet Exec= loop.
  * ``TV-T45-05`` Tag-45 DEFAULT_RUST_*_BIN constants declared.
  * ``TV-T45-06`` Tag-45 ENV-switches documented in operations doc.
  * ``TV-T45-07`` Tag-45 in-image paths match Quadlet basenames.
  * ``TV-T45-08`` Tag-45 crate paths exist on disk with Cargo.toml.
  * ``TV-T45-09`` Carrier-image set is 11, not 15 (Welle-4..7
    dedicated images stay out of the installer).
  * ``TV-T45-10`` Tag-45 recipe doc present and anchors policy.
  * ``TV-T45-11`` Tag-45 landed-PR anchors correct (#246, #250).
  * ``TV-T45-12`` Sandbox boundary stamp preserved post-Tag-45.

-- Kai
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
QUADLET_CONTAINER = REPO_ROOT / "quadlet" / "wakir-rust-cli.container"
RUST_SWITCH_MODULE = (
    REPO_ROOT / "wirelang" / "persona_engine" / "rust_backend_switch.py"
)
OPERATIONS_DOC = (
    REPO_ROOT / "docs" / "operations" / "cosign-policy-phase-3b.md"
)
TAG45_RECIPE_DOC = (
    REPO_ROOT / "docs" / "phase-3c" / "quadlet-cosign-15-binary-installer.md"
)

# Tag-45 binary additions — canonical-only bridges shipped in the
# carrier image (no dedicated single-binary images).
TAG45_BINARIES = ("bridge-audit-replay", "migrate-version")
TAG45_IN_IMAGE_PATHS = {
    "bridge-audit-replay": (
        "/opt/wakir/bin/wakir-persona-engine-bridge-audit-replay"
    ),
    "migrate-version": (
        "/opt/wakir/bin/wakir-persona-engine-migrate-version"
    ),
}
TAG45_ENV_SWITCHES = {
    "bridge-audit-replay": "WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND",
    "migrate-version": "WAKIR_MIGRATE_VERSION_BACKEND",
}
TAG45_DEFAULT_RUST_BIN_CONSTANTS = {
    "bridge-audit-replay": (
        "DEFAULT_RUST_BRIDGE_AUDIT_REPLAY_BIN",
        "/opt/wakir/bin/wakir-persona-engine-bridge-audit-replay",
    ),
    "migrate-version": (
        "DEFAULT_RUST_MIGRATE_VERSION_BIN",
        "/opt/wakir/bin/wakir-persona-engine-migrate-version",
    ),
}
TAG45_LANDED_PR_ANCHORS = {
    "bridge-audit-replay": "#246",
    "migrate-version": "#250",
}
TAG45_CRATE_PATHS = {
    "bridge-audit-replay": (
        "wirelang-rust/crates/persona-engine-bridge-audit-replay"
    ),
    "migrate-version": (
        "wirelang-rust/crates/persona-engine-migrate-version"
    ),
}

# The 11 carrier-image binaries the installer Exec= loop deploys.
# The Welle-4..7 dedicated single-binary images (state-backing-welle4
# etc.) are NOT in this set — they have their own per-Welle Quadlets.
EXPECTED_CARRIER_BINARIES = (
    "wakir-persona-engine-recovery",
    "wakir-persona-engine-state-backing",
    "wakir-persona-engine-fsm",
    "wakir-persona-engine-v907-verify",
    "wakir-persona-engine-bridge-diff",
    "wakir-persona-engine-subscribe-loop",
    "wakir-persona-engine-anchor-emitter",
    "wakir-persona-engine-svid-workload-identity",
    "wakir-persona-engine-bridge-audit-writer",
    # Tag-45 additions.
    "wakir-persona-engine-bridge-audit-replay",
    "wakir-persona-engine-migrate-version",
)
EXPECTED_POLICY_BINARY_COUNT = 15
EXPECTED_CARRIER_BINARY_COUNT = 11


@pytest.fixture(scope="module")
def policy() -> dict:
    """Parse the Cosign-Policy YAML once per test-module."""
    assert POLICY_FILE.exists(), (
        f"required policy file missing: {POLICY_FILE}"
    )
    with POLICY_FILE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), (
        f"policy YAML must parse to a mapping, got {type(data).__name__}"
    )
    return data


@pytest.fixture(scope="module")
def quadlet_text() -> str:
    """Read the Quadlet installer container unit once per test-module."""
    assert QUADLET_CONTAINER.exists(), (
        f"Quadlet installer missing at {QUADLET_CONTAINER}"
    )
    return QUADLET_CONTAINER.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-T45-01 — policy at 15-binary inventory
# ---------------------------------------------------------------------------
def test_policy_at_15_binary_inventory(policy: dict) -> None:
    """The Tag-45 Cosign-Policy MUST list exactly 15 binary entries.

    The 15-entry set is composed of:
      * 9 carrier-image Phase-3b binaries (recovery, state-backing,
        fsm, v907-verify, bridge-diff, subscribe-loop, anchor-emitter,
        svid-workload-identity, bridge-audit-writer).
      * 4 Welle-4..7 dedicated single-binary images (state-backing-
        welle4, fsm-welle5, subscribe-loop-welle6, recovery-welle7).
      * 2 Tag-45 canonical-trace bridges (bridge-audit-replay,
        migrate-version).

    Drift-guard: any inventory change MUST update this count in
    lock-step with the EXPECTED_BINARIES constant in
    tests/infra/test_cosign_policy_phase_3b.py.
    """
    binaries = policy.get("binaries")
    assert isinstance(binaries, list), (
        "policy.binaries: must be a list"
    )
    assert len(binaries) == EXPECTED_POLICY_BINARY_COUNT, (
        f"Tag-45 policy inventory drift: expected "
        f"{EXPECTED_POLICY_BINARY_COUNT} entries, got {len(binaries)}"
    )


# ---------------------------------------------------------------------------
# TV-T45-02 — Quadlet installer at 11-binary carrier-image set
# ---------------------------------------------------------------------------
def test_quadlet_installer_at_11_binary_carrier_image(
    quadlet_text: str,
) -> None:
    """The Quadlet installer Exec= shell loop MUST iterate exactly
    the 11 carrier-image binary basenames declared by
    EXPECTED_CARRIER_BINARIES.

    The Exec= form is a single ``for b in <space-separated-list>;``
    loop in a one-line shell script; this test parses the loop tokens
    and asserts the SET match (order is acceptable to vary; the
    contract is the set).

    Drift-guard: dropping or adding a carrier-image binary without
    a matching Cosign-Policy entry update breaks the cross-substrate
    parity gate (test_cross_substrate_parity_with_quadlet_installer
    in test_cosign_policy_phase_3b.py).
    """
    # Find the Exec= line (single-line in our Quadlet form).
    exec_lines = [
        line for line in quadlet_text.splitlines()
        if line.startswith("Exec=")
    ]
    assert len(exec_lines) == 1, (
        f"Quadlet must declare exactly one Exec= line, "
        f"got {len(exec_lines)}"
    )
    exec_line = exec_lines[0]

    # Extract all binary basenames mentioned in the Exec= line. We
    # match the canonical wakir-persona-engine-<component> shape.
    basenames = set(
        re.findall(r"wakir-persona-engine-[a-z0-9-]+", exec_line)
    )

    # Filter to the Exec= loop body — the shell loop variable ``$b``
    # is referenced in the body via ``\"/opt/wakir/bin/$b\"`` so the
    # canonical paths above also appear; dedupe via set() captures
    # both.
    expected_set = set(EXPECTED_CARRIER_BINARIES)
    assert basenames == expected_set, (
        f"Tag-45 carrier-image installer set drift: expected "
        f"{sorted(expected_set)}, got {sorted(basenames)}"
    )
    assert len(basenames) == EXPECTED_CARRIER_BINARY_COUNT, (
        f"Tag-45 carrier-image installer count drift: expected "
        f"{EXPECTED_CARRIER_BINARY_COUNT}, got {len(basenames)}"
    )


# ---------------------------------------------------------------------------
# TV-T45-03 — Tag-45 additions present in policy with required keys
# ---------------------------------------------------------------------------
def test_tag45_additions_present_in_policy(policy: dict) -> None:
    """Both Tag-45 binary entries (bridge-audit-replay,
    migrate-version) MUST be first-class policy entries carrying the
    required key set (name, component, crate_path, in_image_path,
    env_switch, env_switch_value, env_binary_override, landed_pr,
    landed_tag, purpose).

    Drift-guard: a half-resolved Tag-45 substrate-refresh (e.g. the
    YAML entry is present but missing the crate_path field) would
    leak through the existing parity tests; this test pins the full
    key shape per Tag-45 addition.
    """
    REQUIRED_KEYS = {
        "name",
        "component",
        "crate_path",
        "in_image_path",
        "env_switch",
        "env_switch_value",
        "env_binary_override",
        "landed_pr",
        "landed_tag",
        "purpose",
    }
    by_name = {b["name"]: b for b in policy["binaries"]}
    for tag45_name in TAG45_BINARIES:
        assert tag45_name in by_name, (
            f"Tag-45 binary {tag45_name!r} missing from policy"
        )
        entry = by_name[tag45_name]
        missing = REQUIRED_KEYS - set(entry.keys())
        assert not missing, (
            f"Tag-45 binary {tag45_name!r} missing required keys: "
            f"{missing}"
        )
        # Path + env-switch shape pins.
        assert entry["in_image_path"] == TAG45_IN_IMAGE_PATHS[tag45_name], (
            f"Tag-45 binary {tag45_name!r} in_image_path drift: "
            f"{entry['in_image_path']!r} vs expected "
            f"{TAG45_IN_IMAGE_PATHS[tag45_name]!r}"
        )
        assert entry["env_switch"] == TAG45_ENV_SWITCHES[tag45_name], (
            f"Tag-45 binary {tag45_name!r} env_switch drift: "
            f"{entry['env_switch']!r} vs expected "
            f"{TAG45_ENV_SWITCHES[tag45_name]!r}"
        )


# ---------------------------------------------------------------------------
# TV-T45-04 — Tag-45 additions present in Quadlet Exec= loop
# ---------------------------------------------------------------------------
def test_tag45_additions_present_in_quadlet_exec_loop(
    quadlet_text: str,
) -> None:
    """Both Tag-45 binary basenames (wakir-persona-engine-bridge-
    audit-replay, wakir-persona-engine-migrate-version) MUST appear
    in the Quadlet installer Exec= shell loop.

    Drift-guard: a Cosign-Policy entry without a matching installer
    deployment is the inventory-gap class this gate prevents.
    """
    exec_lines = [
        line for line in quadlet_text.splitlines()
        if line.startswith("Exec=")
    ]
    assert len(exec_lines) == 1, (
        f"Quadlet must declare exactly one Exec= line, "
        f"got {len(exec_lines)}"
    )
    exec_line = exec_lines[0]

    for tag45_name in TAG45_BINARIES:
        canonical_basename = f"wakir-persona-engine-{tag45_name}"
        assert canonical_basename in exec_line, (
            f"Tag-45 binary basename {canonical_basename!r} missing "
            f"from Quadlet Exec= shell loop"
        )


# ---------------------------------------------------------------------------
# TV-T45-05 — Tag-45 DEFAULT_RUST_*_BIN constants declared
# ---------------------------------------------------------------------------
def test_tag45_additions_have_default_rust_bin_constants() -> None:
    """Both Tag-45 binaries MUST have a corresponding
    ``DEFAULT_RUST_*_BIN`` constant declared in
    ``wirelang/persona_engine/rust_backend_switch.py`` that resolves
    to the canonical ``/opt/wakir/bin/`` path declared by the policy.

    Drift-guard: the orchestrator subprocess-fork path resolves
    binaries via the DEFAULT_RUST_*_BIN constants; if the constant is
    missing, the bridge silently falls back to Python with a
    ``fallback_reason: missing_binary`` audit-record line — which
    defeats the Tag-45 substrate-refresh intent.
    """
    assert RUST_SWITCH_MODULE.exists(), (
        f"rust_backend_switch.py missing at {RUST_SWITCH_MODULE}"
    )
    text = RUST_SWITCH_MODULE.read_text(encoding="utf-8")

    for tag45_name in TAG45_BINARIES:
        const_name, expected_path = TAG45_DEFAULT_RUST_BIN_CONSTANTS[
            tag45_name
        ]
        # Match shape: ``CONST = "<path>"`` or parenthesised form
        # ``CONST = (\n    "<path>"\n)``.
        single_line = re.search(
            rf'^{re.escape(const_name)}\s*=\s*"([^"]+)"',
            text,
            re.MULTILINE,
        )
        paren_continued = re.search(
            rf'^{re.escape(const_name)}\s*=\s*\(\s*\n\s*"([^"]+)"',
            text,
            re.MULTILINE,
        )
        match = single_line or paren_continued
        assert match, (
            f"Tag-45 constant {const_name} not found in "
            f"rust_backend_switch.py"
        )
        observed = match.group(1)
        assert observed == expected_path, (
            f"Tag-45 path drift for {tag45_name}: "
            f"{const_name}={observed!r} vs expected {expected_path!r}"
        )


# ---------------------------------------------------------------------------
# TV-T45-06 — Tag-45 ENV-switches documented in operations doc
# ---------------------------------------------------------------------------
def test_tag45_env_switches_documented_in_operations_doc() -> None:
    """Both Tag-45 ENV-switches (WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND,
    WAKIR_MIGRATE_VERSION_BACKEND) MUST appear in the operations doc
    (``docs/operations/cosign-policy-phase-3b.md``).

    Drift-guard: an operator following the prose recipe must find
    the new switches; an undocumented switch is operator-invisible.
    """
    assert OPERATIONS_DOC.exists(), (
        f"operations doc missing at {OPERATIONS_DOC}"
    )
    text = OPERATIONS_DOC.read_text(encoding="utf-8")

    for tag45_name in TAG45_BINARIES:
        env_switch = TAG45_ENV_SWITCHES[tag45_name]
        assert env_switch in text, (
            f"Tag-45 ENV-switch {env_switch!r} missing from "
            f"operations doc"
        )


# ---------------------------------------------------------------------------
# TV-T45-07 — Tag-45 in-image paths match Quadlet basenames
# ---------------------------------------------------------------------------
def test_tag45_in_image_paths_match_quadlet_install_loop(
    policy: dict,
    quadlet_text: str,
) -> None:
    """For each Tag-45 binary the in-image path from the policy MUST
    decompose to a basename that appears in the Quadlet Exec= loop
    and reassembles to the canonical /opt/wakir/bin/ form.

    Drift-guard: a path-vs-basename mismatch (e.g. policy says
    /opt/wakir/bin/wakir-persona-engine-bridge-audit-replay but the
    Quadlet only ships .../bridge-audit-replay) would silently leave
    the bridge resolving the wrong binary.
    """
    by_name = {b["name"]: b for b in policy["binaries"]}
    for tag45_name in TAG45_BINARIES:
        entry = by_name[tag45_name]
        in_image_path = entry["in_image_path"]
        assert in_image_path.startswith("/opt/wakir/bin/"), (
            f"Tag-45 binary {tag45_name!r} in_image_path not under "
            f"/opt/wakir/bin/: {in_image_path!r}"
        )
        basename = in_image_path[len("/opt/wakir/bin/"):]
        assert basename in quadlet_text, (
            f"Tag-45 binary {tag45_name!r} basename {basename!r} "
            f"missing from Quadlet installer"
        )
        # And: the full canonical path must also appear in the
        # Quadlet (the Exec= loop expands $b to /opt/wakir/bin/$b).
        # Either form is acceptable substring-match.
        assert (
            basename in quadlet_text
            or in_image_path in quadlet_text
        )


# ---------------------------------------------------------------------------
# TV-T45-08 — Tag-45 crate paths exist on disk with Cargo.toml
# ---------------------------------------------------------------------------
def test_tag45_crate_paths_exist_on_disk(policy: dict) -> None:
    """The crate_path for both Tag-45 binaries MUST point at a
    directory that exists on disk and carries a Cargo.toml.

    Drift-guard: a typo in the crate_path field (e.g.
    persona-engine-migrate-versions with trailing 's') would leak
    through the YAML parse but break the live image-build pipeline
    silently.
    """
    by_name = {b["name"]: b for b in policy["binaries"]}
    for tag45_name in TAG45_BINARIES:
        entry = by_name[tag45_name]
        expected_path = TAG45_CRATE_PATHS[tag45_name]
        assert entry["crate_path"] == expected_path, (
            f"Tag-45 binary {tag45_name!r} crate_path drift: "
            f"{entry['crate_path']!r} vs expected {expected_path!r}"
        )
        crate_dir = REPO_ROOT / entry["crate_path"]
        assert crate_dir.is_dir(), (
            f"Tag-45 binary {tag45_name!r} crate_path does not exist "
            f"on disk: {crate_dir}"
        )
        assert (crate_dir / "Cargo.toml").exists(), (
            f"Tag-45 binary {tag45_name!r} crate has no Cargo.toml: "
            f"{crate_dir}"
        )


# ---------------------------------------------------------------------------
# TV-T45-09 — Carrier-image set is 11, not 15
# ---------------------------------------------------------------------------
def test_tag45_carrier_image_set_is_11_not_15(quadlet_text: str) -> None:
    """The Quadlet installer Exec= loop MUST iterate exactly 11
    carrier-image binaries, NOT the full 15 from the Cosign-Policy.

    The four Welle-4..7 dedicated single-binary images (state-
    backing-welle4, fsm-welle5, subscribe-loop-welle6, recovery-
    welle7) are deployed by their own per-Welle Quadlets, not by
    this installer.

    Drift-guard: an operator copying the Cosign-Policy 15-binary set
    into the installer Exec= loop would deploy the four Welle-4..7
    dedicated-image binaries via the wrong substrate; this test
    pins the boundary.
    """
    exec_lines = [
        line for line in quadlet_text.splitlines()
        if line.startswith("Exec=")
    ]
    exec_line = exec_lines[0]

    welle_4_7_suffixes = (
        "-welle4",
        "-welle5",
        "-welle6",
        "-welle7",
    )
    for suffix in welle_4_7_suffixes:
        # The Exec= loop must NOT carry any -welleN-suffixed basename;
        # those are deployed by per-Welle Quadlets, not by this
        # carrier-image installer.
        forbidden_basename = f"wakir-persona-engine-state-backing{suffix}"
        # Construct candidates for each -welleN dedicated binary.
        for component in (
            "state-backing",
            "fsm",
            "subscribe-loop",
            "recovery",
        ):
            forbidden = f"wakir-persona-engine-{component}{suffix}"
            assert forbidden not in exec_line, (
                f"carrier-image installer must NOT deploy the "
                f"Welle-4..7 dedicated binary {forbidden!r}; deploy "
                f"it via the per-Welle Quadlet instead"
            )


# ---------------------------------------------------------------------------
# TV-T45-10 — Tag-45 recipe doc present and anchors policy
# ---------------------------------------------------------------------------
def test_tag45_recipe_doc_present_and_anchors_policy() -> None:
    """The Tag-45 Operator-Hand recipe doc
    (``docs/phase-3c/quadlet-cosign-15-binary-installer.md``) MUST
    exist and anchor on:
      * the Cosign-Policy YAML path,
      * both Tag-45 binary names (bridge-audit-replay, migrate-version),
      * the Operator-Hand boundary stamp,
      * the 11-binary carrier-image installer set,
      * the Rollback-Pfad section,
      * the Cross-Welle-Coordination section.

    Drift-guard: a missing recipe doc would leave operators following
    the Tag-22/24 living recipe (which still says "7 binaries");
    this test pins the substrate-refresh recipe as a first-class
    deliverable.
    """
    assert TAG45_RECIPE_DOC.exists(), (
        f"Tag-45 recipe doc missing at {TAG45_RECIPE_DOC}"
    )
    text = TAG45_RECIPE_DOC.read_text(encoding="utf-8")

    # Anchor: Cosign-Policy YAML path.
    assert "policies/cosign-policy-phase-3b.yaml" in text, (
        "Tag-45 recipe does not reference the Cosign-Policy YAML"
    )
    # Anchor: Quadlet installer path.
    assert "quadlet/wakir-rust-cli.container" in text, (
        "Tag-45 recipe does not reference the Quadlet installer"
    )
    # Anchor: both Tag-45 binary names.
    for tag45_name in TAG45_BINARIES:
        assert tag45_name in text, (
            f"Tag-45 recipe does not mention {tag45_name!r}"
        )
    # Anchor: Operator-Hand boundary stamp.
    assert "Operator-Hand" in text, (
        "Tag-45 recipe does not declare the Operator-Hand boundary"
    )
    # Anchor: 11-binary carrier-image set (explicit count somewhere).
    assert "11" in text, (
        "Tag-45 recipe does not document the 11-binary carrier-image "
        "installer set"
    )
    # Anchor: 15-binary policy set (explicit count somewhere).
    assert "15" in text, (
        "Tag-45 recipe does not document the 15-binary policy set"
    )
    # Anchor: Rollback section.
    rollback_pattern = re.compile(
        r"Rollback[ -]?Pfad", re.IGNORECASE
    )
    assert rollback_pattern.search(text), (
        "Tag-45 recipe does not document the Rollback-Pfad section"
    )
    # Anchor: Cross-Welle-Coordination section.
    cross_welle_pattern = re.compile(
        r"Cross[- ]Welle[- ]Coordination", re.IGNORECASE
    )
    assert cross_welle_pattern.search(text), (
        "Tag-45 recipe does not document Cross-Welle-Coordination"
    )


# ---------------------------------------------------------------------------
# TV-T45-11 — Tag-45 landed-PR anchors correct (#246, #250)
# ---------------------------------------------------------------------------
def test_tag45_landed_pr_anchors_correct(policy: dict) -> None:
    """The Tag-45 policy entries MUST anchor on the correct landed-PR
    numbers — #246 for bridge-audit-replay (Tag-37 Mini-Welle, 14.
    Phase-3a Modul) and #250 for migrate-version (Tag-38 Mini-Welle,
    15. Phase-3a Modul).

    Drift-guard: a typo in the landed_pr field would break the
    traceability anchor between the Cosign-Policy inventory and the
    Reza-side Phase-3a-Foundation sweep tracker (ADR-0063
    §Folgeartefakte).
    """
    by_name = {b["name"]: b for b in policy["binaries"]}
    for tag45_name in TAG45_BINARIES:
        entry = by_name[tag45_name]
        expected_pr = TAG45_LANDED_PR_ANCHORS[tag45_name]
        assert entry["landed_pr"] == expected_pr, (
            f"Tag-45 binary {tag45_name!r} landed_pr drift: "
            f"{entry['landed_pr']!r} vs expected {expected_pr!r}"
        )


# ---------------------------------------------------------------------------
# TV-T45-12 — Sandbox boundary stamp preserved post-Tag-45
# ---------------------------------------------------------------------------
def test_tag45_sandbox_boundary_stamp_preserved(policy: dict) -> None:
    """The Cosign-Policy file MUST still carry the sandbox-boundary
    stamp after the Tag-45 inventory bump — no ``run_in_sandbox:
    true`` regression leaked in.

    Drift-guard: a future PR that accidentally adds a sandbox-side
    cosign invocation hook (``run_in_sandbox: true``) would
    contradict ``feedback_sandbox_host_trennung.md``; this test pins
    the boundary at policy-author time across all Tag-N inventory
    bumps.
    """
    raw = POLICY_FILE.read_text(encoding="utf-8")
    assert "feedback_sandbox_host_trennung.md" in raw, (
        "policy file lost the sandbox-host-trennung feedback anchor "
        "during the Tag-45 substrate refresh"
    )
    assert "Operator-Hand" in raw, (
        "policy file lost the Operator-Hand boundary declaration "
        "during the Tag-45 substrate refresh"
    )
    # Negative assertion: no run_in_sandbox flag.
    assert "run_in_sandbox" not in policy, (
        "policy gained a run_in_sandbox flag during the Tag-45 "
        "substrate refresh — sandbox boundary violation"
    )
    # And: the Tag-45 recipe doc carries the same boundary stamp.
    assert TAG45_RECIPE_DOC.exists()
    recipe_text = TAG45_RECIPE_DOC.read_text(encoding="utf-8")
    assert "feedback_sandbox_host_trennung.md" in recipe_text, (
        "Tag-45 recipe doc does not carry the sandbox-host-trennung "
        "boundary anchor"
    )
