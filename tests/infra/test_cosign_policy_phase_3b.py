# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic format invariants for the Phase-3b Rust-CLI Cosign-Policy.

Sibling tests:
  * ``tests/infra/test_python_image_pin_form.py`` — python base-layer
    pin (Containerfile).
  * ``tests/infra/test_wakir_provisioner_image_pin_form.py`` — published
    wakir-provisioner image pin (Quadlet).
  * ``infra/spire/federation/tests/test_image_pin_digest_form.py`` —
    SPIRE-Server + SPIRE-Agent pins (compose + quadlet).

This test surface validates the Tag-20 Mini-Welle cosign-policy
substrate (`policies/cosign-policy-phase-3b.yaml`) for the four
Phase-3b Rust-CLI binaries that
``wirelang.persona_engine.rust_backend_switch`` subprocess-bridges to
(recovery, state-backing, fsm, v907-verify; landed in PRs #167, #169,
#171 across Tag-17/18/19 Mini-Welles).

Sandbox boundary
----------------
The hermetic tests read files on disk only — no network, no cosign /
skopeo / crane invocations against ``ghcr.io`` per
``feedback_sandbox_host_trennung.md``. Live verification is
Operator-Hand per ``docs/operations/cosign-policy-phase-3b.md`` §3.

What is NOT covered here
------------------------
  * The YAML's schema does NOT have a formal JSON-Schema substrate
    (deliberate — the file is small enough that a Python-side shape
    test is the higher-signal substrate). If the YAML grows past
    ~5 binaries, promote to a `cue` or `JSON-Schema` validator.
  * The ``mismatch-rejects`` fixture tests the SHAPE-level rejection
    logic (placeholder vs canonical digest, missing binary entry)
    only — it does NOT exercise live Sigstore-Rekor mismatch flows;
    those are Operator-Hand.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
RUST_SWITCH_MODULE = (
    REPO_ROOT / "wirelang" / "persona_engine" / "rust_backend_switch.py"
)
OPERATIONS_DOC = (
    REPO_ROOT / "docs" / "operations" / "cosign-policy-phase-3b.md"
)

EXPECTED_SCHEMA_VERSION = "wakir.cosign-policy.phase-3b/1"
EXPECTED_BINARIES = (
    "recovery",
    "state-backing",
    "fsm",
    "v907-verify",
)
EXPECTED_IN_IMAGE_PATHS = {
    "recovery": "/opt/wakir/bin/wakir-persona-engine-recovery",
    "state-backing": "/opt/wakir/bin/wakir-persona-engine-state-backing",
    "fsm": "/opt/wakir/bin/wakir-persona-engine-fsm",
    "v907-verify": "/opt/wakir/bin/wakir-persona-engine-v907-verify",
}
EXPECTED_ENV_SWITCHES = {
    "recovery": "WAKIR_RECOVERY_BACKEND",
    "state-backing": "WAKIR_STATE_BACKING_BACKEND",
    "fsm": "WAKIR_FSM_BACKEND",
    "v907-verify": "WAKIR_V907_VERIFY_BACKEND",
}
PLACEHOLDER_DIGEST = "sha256:DIGEST_PENDING_KAI_CROSS_REVIEW"
CANONICAL_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
PLACEHOLDER_OR_CANONICAL_RE = re.compile(
    r"^(?:sha256:DIGEST_PENDING_KAI_CROSS_REVIEW|sha256:[a-f0-9]{64})$"
)


@pytest.fixture(scope="module")
def policy() -> dict:
    """Parse the cosign-policy YAML once per test-module."""
    assert POLICY_FILE.exists(), (
        f"required policy file missing: {POLICY_FILE}"
    )
    with POLICY_FILE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), (
        f"policy YAML must parse to a mapping, got {type(data).__name__}"
    )
    return data


# ---------------------------------------------------------------------------
# Test 1 — policy-format-validate
# ---------------------------------------------------------------------------
def test_policy_format_validate(policy: dict) -> None:
    """Top-level shape: schema_version, policy:, binaries:,
    verification: sections all present with the expected types.

    A schema-version drift (e.g. someone bumps to ``phase-3b/2``
    without updating the consumer recipe in
    ``docs/operations/cosign-policy-phase-3b.md``) is a coordinated
    rollout — this test pins the version slot so the bump cannot
    sneak through.
    """
    assert policy.get("schema_version") == EXPECTED_SCHEMA_VERSION, (
        f"schema_version drift: expected {EXPECTED_SCHEMA_VERSION!r}, "
        f"got {policy.get('schema_version')!r}"
    )

    # Required sections, all mappings or lists.
    assert isinstance(policy.get("policy"), dict), (
        "policy: section missing or not a mapping"
    )
    assert isinstance(policy.get("binaries"), list), (
        "binaries: section missing or not a list"
    )
    assert isinstance(policy.get("verification"), dict), (
        "verification: section missing or not a mapping"
    )

    # policy: subsection — Sigstore-keyless OIDC identity, carrier image.
    pol = policy["policy"]
    assert pol.get("name") == "phase-3b-rust-cli-binaries", (
        f"unexpected policy.name: {pol.get('name')!r}"
    )
    assert "certificate_identity_regexp" in pol, (
        "policy.certificate_identity_regexp missing"
    )
    assert "certificate_oidc_issuer" in pol, (
        "policy.certificate_oidc_issuer missing"
    )
    assert (
        pol["certificate_oidc_issuer"]
        == "https://token.actions.githubusercontent.com"
    ), (
        "policy.certificate_oidc_issuer drift: expected the GitHub-"
        "Actions OIDC issuer"
    )
    assert re.match(
        r"^https://github\\?\.com/wakir-labs/wakir-runtime/",
        pol["certificate_identity_regexp"],
    ), (
        "policy.certificate_identity_regexp drift: expected "
        "wakir-labs/wakir-runtime build-workflow identity"
    )

    # carrier_image subsection.
    carrier = pol.get("carrier_image")
    assert isinstance(carrier, dict), (
        "policy.carrier_image missing or not a mapping"
    )
    assert carrier.get("registry") == "ghcr.io", (
        f"unexpected carrier_image.registry: {carrier.get('registry')!r}"
    )
    assert (
        carrier.get("repository") == "wakir-labs/wakir-persona-engine"
    ), (
        f"unexpected carrier_image.repository: "
        f"{carrier.get('repository')!r}"
    )
    assert carrier.get("build_workflow") == (
        ".github/workflows/build-wakir-persona-engine.yml"
    ), "carrier_image.build_workflow drift"
    assert carrier.get("containerfile") == (
        "infra/persona-engine/Containerfile.real"
    ), "carrier_image.containerfile drift"


# ---------------------------------------------------------------------------
# Test 2 — all-4-binaries-listed
# ---------------------------------------------------------------------------
def test_all_4_phase_3b_binaries_listed(policy: dict) -> None:
    """The binaries: inventory MUST list EXACTLY the four Phase-3b
    Rust-CLI components: recovery, state-backing, fsm, v907-verify.

    A drift either way (missing entry OR extra entry) is a substrate
    breach:

      * Missing entry: a production-mode subprocess-bridge has no
        cosign-policy gate; an unverified binary on the hot-path is
        the supply-chain breach this whole substrate is built to
        prevent.
      * Extra entry: a binary that the persona-engine does NOT
        actually subprocess-bridge to is being advertised as
        verified by this policy; that grows the trust surface
        without a real consumer.
    """
    binaries = policy["binaries"]
    assert isinstance(binaries, list)
    names_in_order = [b.get("name") for b in binaries]
    assert names_in_order == list(EXPECTED_BINARIES), (
        f"binary inventory drift: expected exactly {EXPECTED_BINARIES} "
        f"in that order, got {tuple(names_in_order)}"
    )

    # Every entry carries the required keys and the correct in-image
    # path + ENV-switch wiring.
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
    for entry in binaries:
        assert isinstance(entry, dict), (
            f"binary entry not a mapping: {entry!r}"
        )
        missing = REQUIRED_KEYS - set(entry.keys())
        assert not missing, (
            f"binary entry {entry.get('name')!r} missing keys: {missing}"
        )
        name = entry["name"]
        assert entry["in_image_path"] == EXPECTED_IN_IMAGE_PATHS[name], (
            f"in_image_path drift for {name}: "
            f"{entry['in_image_path']!r} vs expected "
            f"{EXPECTED_IN_IMAGE_PATHS[name]!r}"
        )
        assert entry["env_switch"] == EXPECTED_ENV_SWITCHES[name], (
            f"env_switch drift for {name}: {entry['env_switch']!r} "
            f"vs expected {EXPECTED_ENV_SWITCHES[name]!r}"
        )
        # Each crate path must exist on disk (catches refactor drift
        # where a crate is renamed but the policy file is not updated).
        crate_dir = REPO_ROOT / entry["crate_path"]
        assert crate_dir.is_dir(), (
            f"crate_path for {name} does not exist on disk: "
            f"{crate_dir}"
        )
        assert (crate_dir / "Cargo.toml").exists(), (
            f"crate_path for {name} has no Cargo.toml: {crate_dir}"
        )


# ---------------------------------------------------------------------------
# Test 3 — sha256-format-correct
# ---------------------------------------------------------------------------
def test_sha256_format_correct(policy: dict) -> None:
    """The carrier_image.expected_image_digest slot MUST be either the
    pre-resolution placeholder ``sha256:DIGEST_PENDING_KAI_CROSS_REVIEW``
    OR a canonical ``sha256:<64-hex>`` digest.

    A half-resolved state (e.g. ``sha256:abcdef`` truncated; or a
    bare ``DIGEST_PENDING`` without the ``sha256:`` prefix) is a
    Phase-3b cosign-policy invariant breach. The regex enforces the
    alternation; this test makes the invariant explicit so a future
    loosening of the regex breaks the suite first.
    """
    carrier = policy["policy"]["carrier_image"]
    digest = carrier.get("expected_image_digest")
    assert isinstance(digest, str), (
        f"expected_image_digest missing or not a string: {digest!r}"
    )
    assert PLACEHOLDER_OR_CANONICAL_RE.match(digest), (
        f"non-canonical expected_image_digest: {digest!r}; "
        f"must be {PLACEHOLDER_DIGEST!r} or sha256:<64-hex>"
    )

    # Tag slot — must be a non-empty string, no placeholder.
    tag = carrier.get("expected_tag")
    assert isinstance(tag, str) and tag.strip(), (
        f"expected_tag missing or empty: {tag!r}"
    )
    # The tag must follow the wakir-persona-engine pilot-cadence
    # naming (e.g. 0.1.0-pilot, 0.5.0-pilot, ...). Bare tag refs
    # without a ``-pilot`` suffix are rejected — those are reserved
    # for the post-pilot release line.
    assert re.match(r"^\d+\.\d+\.\d+-pilot$", tag), (
        f"expected_tag does not match pilot-cadence naming: {tag!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — mismatch-rejects-fixture
# ---------------------------------------------------------------------------
def test_mismatch_fixture_rejects(policy: dict) -> None:
    """Synthesise three drift fixtures in memory and assert the
    SHAPE-validation logic rejects each one. This is the SHAPE-level
    mirror of the runtime ``cosign verify`` rejection — live drift is
    Operator-Hand per
    ``docs/operations/cosign-policy-phase-3b.md`` §4.

    Drift fixture A: dropped binary entry (only 3 of 4 components).
    Drift fixture B: malformed digest (sha256-prefixed but only 8 hex).
    Drift fixture C: identity-regex pointing at a non-wakir-runtime
                     repository (rogue signer).
    """

    def _shape_reject_dropped_binary(p: dict) -> str | None:
        names = [b.get("name") for b in p.get("binaries", [])]
        if list(names) != list(EXPECTED_BINARIES):
            return f"binary-inventory-drift: {names}"
        return None

    def _shape_reject_bad_digest(p: dict) -> str | None:
        d = p.get("policy", {}).get("carrier_image", {}).get(
            "expected_image_digest", ""
        )
        if not PLACEHOLDER_OR_CANONICAL_RE.match(d):
            return f"bad-digest-shape: {d!r}"
        return None

    def _shape_reject_rogue_identity(p: dict) -> str | None:
        ident = p.get("policy", {}).get(
            "certificate_identity_regexp", ""
        )
        if "wakir-labs/wakir-runtime" not in ident:
            return f"rogue-identity-regex: {ident!r}"
        return None

    # Fixture A — drop the ``v907-verify`` entry.
    fix_a = copy.deepcopy(policy)
    fix_a["binaries"] = [
        b for b in fix_a["binaries"] if b.get("name") != "v907-verify"
    ]
    rejection = _shape_reject_dropped_binary(fix_a)
    assert rejection is not None and "binary-inventory-drift" in rejection, (
        "shape-validator must reject a policy with a dropped binary "
        "entry; got no rejection"
    )

    # Fixture B — malformed digest (truncated hex).
    fix_b = copy.deepcopy(policy)
    fix_b["policy"]["carrier_image"]["expected_image_digest"] = (
        "sha256:deadbeef"
    )
    rejection = _shape_reject_bad_digest(fix_b)
    assert rejection is not None and "bad-digest-shape" in rejection, (
        "shape-validator must reject a policy with a malformed "
        "digest; got no rejection"
    )

    # Fixture C — rogue signer identity (points at a fork).
    fix_c = copy.deepcopy(policy)
    fix_c["policy"]["certificate_identity_regexp"] = (
        r"https://github\.com/attacker-org/wakir-runtime-fork/"
    )
    rejection = _shape_reject_rogue_identity(fix_c)
    assert rejection is not None and "rogue-identity-regex" in rejection, (
        "shape-validator must reject a policy with a rogue signer "
        "identity; got no rejection"
    )

    # And: the SAME validators all return None on the real policy
    # (sanity-check — guards against an accidentally-too-strict
    # rejection rule).
    assert _shape_reject_dropped_binary(policy) is None
    assert _shape_reject_bad_digest(policy) is None
    assert _shape_reject_rogue_identity(policy) is None


# ---------------------------------------------------------------------------
# Test 5 — in-image-paths-match-rust-backend-switch-defaults
# ---------------------------------------------------------------------------
def test_in_image_paths_match_rust_backend_switch_defaults() -> None:
    """The policy's in_image_path values MUST match the
    ``DEFAULT_RUST_*_BIN`` constants in
    ``wirelang/persona_engine/rust_backend_switch.py``.

    A drift here is a cross-substrate divergence: the orchestrator
    will subprocess-fork ``/opt/wakir/bin/wakir-persona-engine-fsm``
    while the cosign-policy verifies a binary at a different path —
    the bridge silently falls back to Python (logged via
    ``fallback_reason: missing_binary``), and the cosign-policy gate
    becomes a no-op for production traffic.
    """
    assert RUST_SWITCH_MODULE.exists(), (
        f"rust_backend_switch.py missing at {RUST_SWITCH_MODULE}"
    )
    text = RUST_SWITCH_MODULE.read_text(encoding="utf-8")
    # The defaults are declared as module-level constants — string-grep
    # them out (this test deliberately avoids importing the module so
    # it stays hermetic and import-side-effect-free).
    for name, expected_path in EXPECTED_IN_IMAGE_PATHS.items():
        # Match shape: ``DEFAULT_RUST_X_BIN = "<path>"``.
        # The constant name is derived from the binary name:
        #   recovery       -> DEFAULT_RUST_RECOVERY_BIN
        #   state-backing  -> DEFAULT_RUST_STATE_BACKING_BIN
        #   fsm            -> DEFAULT_RUST_FSM_BIN
        #   v907-verify    -> DEFAULT_RUST_V907_VERIFY_BIN
        const_name = "DEFAULT_RUST_" + name.upper().replace("-", "_") + "_BIN"
        # The constant may be defined as a single-line string OR as a
        # parenthesised continuation across two lines; match both.
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
            f"constant {const_name} not found in rust_backend_switch.py"
        )
        observed = match.group(1)
        assert observed == expected_path, (
            f"path drift for {name}: rust_backend_switch.py declares "
            f"{const_name}={observed!r}, policy declares "
            f"in_image_path={expected_path!r}"
        )


# ---------------------------------------------------------------------------
# Test 6 — operations-doc-anchors-policy-file
# ---------------------------------------------------------------------------
def test_operations_doc_anchors_policy_file() -> None:
    """The Operator-Hand recipe in
    ``docs/operations/cosign-policy-phase-3b.md`` MUST anchor on the
    policy file (path-reference + the OIDC identity-regex + the
    canonical in-image paths). A doc-recipe that drifts from the
    declarative substrate is the worst-of-both-worlds: humans follow
    the prose, the policy YAML is the source-of-truth, and the two
    silently disagree.
    """
    assert OPERATIONS_DOC.exists(), (
        f"operations doc missing at {OPERATIONS_DOC}"
    )
    text = OPERATIONS_DOC.read_text(encoding="utf-8")

    # Anchor: path reference to the policy YAML.
    assert "policies/cosign-policy-phase-3b.yaml" in text, (
        "operations doc does not reference the policy YAML"
    )

    # Anchor: Sigstore-keyless OIDC identity regex (same shape as the
    # IMAGE_PINS.md §2.5 wakir-provisioner recipe).
    assert "wakir-labs/wakir-runtime" in text, (
        "operations doc does not document the wakir-runtime OIDC "
        "identity"
    )
    assert "token.actions.githubusercontent.com" in text, (
        "operations doc does not document the GitHub-Actions OIDC "
        "issuer"
    )

    # Anchor: all four canonical in-image paths are documented in the
    # operator recipe (the binary-presence probe in §3.3).
    for path in EXPECTED_IN_IMAGE_PATHS.values():
        assert path in text, (
            f"operations doc does not document the canonical in-image "
            f"path {path}"
        )

    # Anchor: the four ENV-switches are listed in the §5 wiring table.
    for env in EXPECTED_ENV_SWITCHES.values():
        assert env in text, (
            f"operations doc does not document the ENV-switch {env}"
        )

    # Anchor: digest-mismatch handling is documented (the
    # ``on_digest_mismatch`` posture).
    assert "digest mismatch" in text.lower() or "mismatch" in text.lower(), (
        "operations doc does not document the digest-mismatch posture"
    )
    # The Zone-C cross-review escalation must be named.
    assert "Zone-C" in text or "Zone C" in text, (
        "operations doc does not document the Zone-C cross-review "
        "escalation on digest mismatch"
    )


# ---------------------------------------------------------------------------
# Test 7 — sandbox-boundary-stamp-present
# ---------------------------------------------------------------------------
def test_sandbox_boundary_stamp_present(policy: dict) -> None:
    """The policy file MUST carry the sandbox-boundary stamp (no
    sandbox process calls cosign / crane / skopeo against ghcr.io —
    live verification is Operator-Hand). The stamp lives in a YAML
    comment at the bottom of the file; we read the raw bytes here.

    This test exists as a sibling to the
    ``IMAGE_PINS.md`` §4 sandbox-boundary clause — every cosign-policy
    file in the repo declares the same boundary explicitly, so a
    future ``cosign verify`` invocation accidentally wired into the
    hermetic sandbox surface is caught at policy-author time.
    """
    raw = POLICY_FILE.read_text(encoding="utf-8")
    assert "feedback_sandbox_host_trennung.md" in raw, (
        "policy file does not reference the sandbox-host-trennung "
        "feedback anchor"
    )
    assert "Operator-Hand" in raw, (
        "policy file does not declare the Operator-Hand boundary "
        "for live verification"
    )
    # And: the policy YAML, when parsed, does NOT contain any field
    # that asks for a sandbox-side cosign invocation. (The check is
    # negative — we assert no top-level ``run_in_sandbox: true``
    # leaked in.)
    assert "run_in_sandbox" not in policy, (
        "policy must not carry a run_in_sandbox flag — live cosign "
        "is Operator-Hand only"
    )
