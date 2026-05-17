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
  * ``tests/infra/test_quadlets_phase_3b.py`` — Tag-22 Quadlet
    installer; inventories the same five binaries.

This test surface validates the cosign-policy substrate
(`policies/cosign-policy-phase-3b.yaml`) for the eight Phase-3b
Rust-CLI binaries that
``wirelang.persona_engine.rust_backend_switch`` subprocess-bridges to
(recovery, state-backing, fsm, v907-verify, bridge-diff,
subscribe-loop, anchor-emitter, svid-workload-identity; landed in
PRs #167, #169, #171, #175, #181, #184, #191 across Tag-17 through
Tag-29 Mini-Welles).

Tag-23 Mini-Welle update
------------------------
Inventory extended from 4 to 5 binaries; ``bridge-diff`` (Tag-20
Mini-Welle PR #175) is now a first-class policy entry. The
``EXPECTED_BINARIES`` tuple grew accordingly and the dropped-binary
fixture in ``test_mismatch_fixture_rejects`` now drops a different
binary (still recovers the same SHAPE-rejection invariant).

Tag-24 Mini-Welle update (ADR-0065 Phase-3c Trigger-Gate 2)
-----------------------------------------------------------
Inventory extended from 5 to 7 binaries in lock-step with the
Quadlet installer Tag-24 update (Trigger-Gate 3). Added
``subscribe-loop`` (Tag-22 Mini-Welle PR #181) and ``anchor-emitter``
(Tag-23 Mini-Welle PR #184). ``EXPECTED_BINARIES``,
``EXPECTED_IN_IMAGE_PATHS``, and ``EXPECTED_ENV_SWITCHES`` grew
together.

Tag-29 Mini-Welle update (ADR-0066 Welle-2 image-build)
-------------------------------------------------------
Inventory extended from 7 to 8 binaries in lock-step with the
Quadlet installer Tag-29 update. Added ``svid-workload-identity``
(Tag-25 Mini-Welle PR #191 wired the Python resolver; Tag-29
Mini-Welle ships the Rust crate skeleton + image-build pipeline).
The dropped-binary fixture now drops ``svid-workload-identity``
(the newest member) and exercises the rejection logic against
the latest inventory addition. The cross-substrate parity test
(``test_cross_substrate_parity_with_quadlet_installer``) enforces
the lock-step agreement with the Quadlet installer.

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
    ~10 binaries, promote to a `cue` or `JSON-Schema` validator.
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
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
)
EXPECTED_IN_IMAGE_PATHS = {
    "recovery": "/opt/wakir/bin/wakir-persona-engine-recovery",
    "state-backing": "/opt/wakir/bin/wakir-persona-engine-state-backing",
    "fsm": "/opt/wakir/bin/wakir-persona-engine-fsm",
    "v907-verify": "/opt/wakir/bin/wakir-persona-engine-v907-verify",
    "bridge-diff": "/opt/wakir/bin/wakir-persona-engine-bridge-diff",
    "subscribe-loop": "/opt/wakir/bin/wakir-persona-engine-subscribe-loop",
    "anchor-emitter": "/opt/wakir/bin/wakir-persona-engine-anchor-emitter",
    "svid-workload-identity": (
        "/opt/wakir/bin/wakir-persona-engine-svid-workload-identity"
    ),
}
EXPECTED_ENV_SWITCHES = {
    "recovery": "WAKIR_RECOVERY_BACKEND",
    "state-backing": "WAKIR_STATE_BACKING_BACKEND",
    "fsm": "WAKIR_FSM_BACKEND",
    "v907-verify": "WAKIR_V907_VERIFY_BACKEND",
    "bridge-diff": "WAKIR_BRIDGE_DIFF_BACKEND",
    "subscribe-loop": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
    "anchor-emitter": "WAKIR_ANCHOR_EMITTER_BACKEND",
    "svid-workload-identity": "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
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
# Test 2 — all-8-binaries-listed
# ---------------------------------------------------------------------------
def test_all_8_phase_3b_binaries_listed(policy: dict) -> None:
    """The binaries: inventory MUST list EXACTLY the eight Phase-3b
    Rust-CLI components: recovery, state-backing, fsm, v907-verify,
    bridge-diff, subscribe-loop, anchor-emitter, svid-workload-identity.

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

    Tag-23 update: inventory grew from 4 to 5 (added ``bridge-diff``;
    Tag-20 Mini-Welle PR #175).
    Tag-24 update (ADR-0065 Phase-3c Trigger-Gate 2): inventory grew
    from 5 to 7 (added ``subscribe-loop`` Tag-22 Mini-Welle PR #181
    and ``anchor-emitter`` Tag-23 Mini-Welle PR #184). The Tag-24
    Quadlet installer update (Trigger-Gate 3) iterates the same
    seven binaries.
    Tag-29 update (ADR-0066 Welle-2 image-build): inventory grew from
    7 to 8 (added ``svid-workload-identity`` — Tag-25 Mini-Welle PR
    #191 wired the Python resolver, Tag-29 Mini-Welle ships the
    crate substrate + image-build pipeline). The Tag-29 Quadlet
    installer update iterates the same eight binaries; this test
    enforces the cross-substrate parity via Test 8 below.
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

    Drift fixture A: dropped binary entry (only 4 of 5 components).
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

    # Fixture A — drop the ``svid-workload-identity`` entry (the
    # Tag-29 addition; exercises the rejection logic specifically
    # against the newest inventory member).
    fix_a = copy.deepcopy(policy)
    fix_a["binaries"] = [
        b
        for b in fix_a["binaries"]
        if b.get("name") != "svid-workload-identity"
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

    Tag-24 update: anchors now cover all SEVEN canonical in-image
    paths and all SEVEN ENV-switches (the loop over
    ``EXPECTED_IN_IMAGE_PATHS`` / ``EXPECTED_ENV_SWITCHES`` picks the
    subscribe-loop + anchor-emitter entries up automatically; the
    pre-Tag-24 helper text said ``FIVE`` and ``bridge-diff`` after
    the Tag-23 extension).
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

    # Anchor: all seven canonical in-image paths are documented in
    # the operator recipe (the binary-presence probe in §3.3).
    for path in EXPECTED_IN_IMAGE_PATHS.values():
        assert path in text, (
            f"operations doc does not document the canonical in-image "
            f"path {path}"
        )

    # Anchor: the seven ENV-switches are listed in the §5 wiring table.
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


# ---------------------------------------------------------------------------
# Test 8 — cross-substrate-parity-with-quadlet-installer
# ---------------------------------------------------------------------------
QUADLET_INSTALLER = (
    REPO_ROOT / "quadlet" / "wakir-rust-cli.container"
)


def test_cross_substrate_parity_with_quadlet_installer(policy: dict) -> None:
    """The Tag-22 Quadlet installer (``quadlet/wakir-rust-cli.container``,
    PR #180) and this Cosign-Policy MUST inventory the SAME set of
    carrier-image binary names in the Quadlet for-loop. A drift
    between the two substrates is the worst failure mode in the
    Tag-22-vs-Tag-20 inventory-gap class — one substrate copies a
    binary onto the host without a matching verification gate, or
    vice versa.

    Tag-23 Mini-Welle landed this parity-test alongside the
    bridge-diff inventory extension. Future inventory grows
    (e.g. subscribe-loop, PR #181 Tag-22 follow-up) MUST land in
    BOTH substrates in the same Mini-Welle — this test enforces
    that gate at policy-author time.

    Tag-32 Mini-Welle update (ADR-0066 Welle-4-7 image-build bundle):
    The Quadlet installer now also installs four standalone-image
    binary-name aliases (after the carrier-image for-loop). The
    Cosign-Policy adds a ``standalone_images`` block listing the
    same four. This parity test now checks BOTH halves:

      * carrier-image inventory (policy ``binaries`` vs Quadlet
        for-loop) — 8 binaries as of Tag-29.
      * standalone-image inventory (policy ``standalone_images``
        vs Quadlet alias installs) — 4 binaries as of Tag-32.
    """
    assert QUADLET_INSTALLER.exists(), (
        f"Quadlet installer missing at {QUADLET_INSTALLER}"
    )
    quadlet_text = QUADLET_INSTALLER.read_text(encoding="utf-8")

    # Carrier-image inventory: parse only the Exec= for-loop body to
    # extract the eight ``wakir-persona-engine-<component>`` binary
    # basenames the carrier image actually ships. The for-loop body
    # is the canonical truth for which binaries the carrier image
    # advertises; the surrounding comment block and the Tag-32 alias
    # install lines are separate substrates.
    for_loop_match = re.search(r"for b in (.+?); do test", quadlet_text)
    assert for_loop_match is not None, (
        "Quadlet installer no longer has the expected `for b in ...; do test` shape"
    )
    for_loop_body = for_loop_match.group(1)
    quadlet_carrier_basenames = set(
        re.findall(
            r"wakir-persona-engine-([a-z0-9-]+)\b", for_loop_body
        )
    )

    policy_carrier_basenames = {b["name"] for b in policy["binaries"]}

    # Both substrates must agree on the SET of CARRIER-IMAGE components.
    assert quadlet_carrier_basenames == policy_carrier_basenames, (
        "cross-substrate inventory drift between Cosign-Policy "
        f"binaries ({sorted(policy_carrier_basenames)}) and Quadlet "
        f"installer for-loop ({sorted(quadlet_carrier_basenames)}). "
        "Both files must list the same set of carrier-image Rust-CLI "
        "binaries; a drift means one substrate copies a binary onto "
        "the host without a matching verification gate, or advertises "
        "verification for a binary that the installer does not "
        "actually deploy."
    )

    # And: the agreed-on set must be exactly the canonical inventory.
    assert policy_carrier_basenames == set(EXPECTED_BINARIES), (
        f"Cosign-Policy + Quadlet agree on {sorted(policy_carrier_basenames)}, "
        f"but the canonical Tag-29 carrier-image inventory is "
        f"{sorted(EXPECTED_BINARIES)} — both substrates have drifted "
        "from the EXPECTED_BINARIES contract in the same direction."
    )

    # Tag-32 standalone-image inventory: the policy's
    # ``standalone_images`` block must agree with the Quadlet
    # installer alias lines on the SET of binary names.
    standalone_entries = policy.get("standalone_images", [])
    assert isinstance(standalone_entries, list) and standalone_entries, (
        "Cosign-Policy must declare a `standalone_images` block as of "
        "Tag-32 Mini-Welle (ADR-0066 Welle-4-7 image-build bundle)"
    )
    policy_standalone_binaries = {
        entry["binary_name"] for entry in standalone_entries
    }
    # The Quadlet alias install lines reference each standalone-image
    # binary name in either an `install` command target or an in-image
    # path. Validate that every standalone-image binary name is
    # mentioned somewhere in the Quadlet text — the structural test
    # in tests/workflows/test_build_rust_cli_welle_4_5_6_7.py handles
    # the precise install-line check.
    for binary in policy_standalone_binaries:
        assert binary in quadlet_text, (
            f"standalone-image binary {binary} listed in Cosign-Policy "
            f"`standalone_images` but absent from Quadlet installer"
        )
