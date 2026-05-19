#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-60 — Smoke-validate the G1+G2 Operator-Hand setup-guide recipe.

The Tag-56 PR #360 guide
``docs/operations/cosign-g1-g2-operator-setup.md`` embeds operational
shell-recipes — ``crane digest`` invocations, ``cosign initialize``
captures, ``gh workflow run`` calls, and edits against
``policies/cosign-policy-phase-3b.yaml`` +
``state/cosign-drift/pinned-trust-root.json``. Tag-58 PR #369 produced
the strict-flip readiness-map (G3..G6 GREEN, G1+G2 still BLOCKED).

This module validates that the embedded recipes remain SYNTACTICALLY
and SEMANTICALLY consistent with what an operator-host would actually
need to run. The validation is HERMETIC — no real cosign / crane /
gh / podman binaries are invoked. We only parse the markdown
code-fences against a known-argument vocabulary, parse the embedded
YAML snippets as YAML, and shape-check the embedded ``gh api`` calls
against a known-shape table.

Verdict vocabulary (Stage-4 aggregate):

    RECIPE-INTACT          — all stages green; recipe usable on the
                             operator-host without further patches.
    RECIPE-SYNTAX-DRIFT    — at least one code-block has an unknown
                             flag/arg or invalid YAML (recipe still
                             readable, but mechanical edits required
                             before an operator can copy-paste it).
    RECIPE-SEMANTIC-DRIFT  — code-block parses, but the args /
                             shapes diverge from the substrate the
                             guide claims to operate on (e.g. the
                             guide references a workflow name that
                             has no matching ``.github/workflows/*.yml``
                             file).

The CLI exits 0 only on RECIPE-INTACT. Both drift verdicts exit 1,
with the structured findings list rendered on stderr.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 this helper
NEVER calls cosign / crane / gh / podman / network. It parses files
on disk only: the guide markdown, the workflows directory listing,
and (for the gh-api Stage-3 shape-check) the embedded shape table
below. The Stage-3 known-shape table is the canonical pinned
contract for the gh api shapes the guide is allowed to embed; a
new shape needs an explicit table entry plus a corresponding test
case.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants — pinned at module load
# ---------------------------------------------------------------------------

DOC_DEFAULT = "docs/operations/cosign-g1-g2-operator-setup.md"

# Stage-1 — cosign / crane / gh / cosign-initialize / curl CLI known
# argument vocabulary. The values are tuples ``(positional_argv0,
# allowed_flags)``. A flag here means "the literal token starts with
# `-` and is in the allowed set"; positional args are not flag-checked
# (we only ensure flags do not leak unknown long-options that would
# fail on the operator-host).
KNOWN_CLI_VOCAB: dict[str, dict[str, Any]] = {
    "crane": {
        "subcommands": {"digest", "manifest", "ls"},
        "flags": {"--platform", "--full-ref"},
    },
    "cosign": {
        "subcommands": {"initialize", "verify", "verify-blob", "sign"},
        "flags": {
            "--key",
            "--certificate-identity",
            "--certificate-oidc-issuer",
            "--certificate-identity-regexp",
            "--rekor-url",
            "--fulcio-url",
            "--tlog-upload",
        },
    },
    "gh": {
        "subcommands": {"workflow", "api", "pr", "run"},
        "flags": {
            "-R",
            "-f",
            "--repo",
            "--method",
            "-X",
            "-H",
            "--input",
            "--json",
        },
    },
    "grep": {
        "subcommands": set(),
        "flags": {"-r", "-n", "-rn", "-h", "-E", "-l", "-c", "-v", "-i", "-rni"},
    },
    "curl": {
        "subcommands": set(),
        "flags": {"-fsSL", "-fsSLI", "-s", "-S", "-L", "-X", "-H", "-o"},
    },
    "sed": {
        "subcommands": set(),
        "flags": {"-E", "-e", "-n", "-i"},
    },
    "find": {
        "subcommands": set(),
        "flags": {"-name", "-type"},
    },
    "head": {
        "subcommands": set(),
        "flags": {"-n", "-c"},
    },
    "tail": {
        "subcommands": set(),
        "flags": {"-n", "-f"},
    },
    "awk": {
        "subcommands": set(),
        "flags": set(),
    },
    "echo": {
        "subcommands": set(),
        "flags": {"-n", "-e"},
    },
    "xargs": {
        "subcommands": set(),
        "flags": {"-I", "-n", "-0"},
    },
    "sha256sum": {
        "subcommands": set(),
        "flags": {"-c", "-b"},
    },
    "python3": {
        "subcommands": set(),
        "flags": {"-c", "-m"},
    },
    "for": {
        # Bash for-loop keyword used inline in the recipe; we accept
        # bare "for" as a known token so the parser does not flag it.
        "subcommands": set(),
        "flags": set(),
    },
    "done": {
        "subcommands": set(),
        "flags": set(),
    },
}


# Stage-3 — known gh-api / gh-workflow call shapes the guide is
# allowed to embed. Each entry is a regex against the joined command
# line (newlines collapsed to single spaces). A call that does not
# match any entry is RECIPE-SEMANTIC-DRIFT.
GH_KNOWN_SHAPES: tuple[tuple[str, str], ...] = (
    (
        "readiness-check",
        r"^gh workflow run cosign-strict-mode-readiness-check "
        r"(-R|--repo) wakir-labs/wakir-runtime\s*$",
    ),
    (
        "drift-probe",
        r"^gh workflow run cosign-keyless-oidc-drift-probe "
        r"(-R|--repo) wakir-labs/wakir-runtime "
        r"-f mode=fixture "
        r"-f exit_non_zero_on_drift=true\s*$",
    ),
)


# Stage-3 — workflow names the gh-shapes reference must exist as
# ``.github/workflows/<name>.yml`` files.
WORKFLOW_REFS: tuple[str, ...] = (
    "cosign-strict-mode-readiness-check",
    "cosign-keyless-oidc-drift-probe",
)


# Stage-2 — embedded YAML/JSON snippets the validator inspects. The
# table here is the canonical contract for "what shape the recipe
# must produce on the operator-host" and is checked against the
# on-disk substrate at Stage-3.
PINNED_TRUST_ROOT_PATH = "state/cosign-drift/pinned-trust-root.json"
COSIGN_POLICY_PATH = "policies/cosign-policy-phase-3b.yaml"
QUADLET_GLOB = "quadlet/wakir-rust-cli*.container"

PLACEHOLDER_TOKEN = "DIGEST_PENDING_KAI_CROSS_REVIEW"
PENDING_TRUST_ROOT_TOKEN = "PENDING_OPERATOR_HAND_REFRESH"


# ---------------------------------------------------------------------------
# Finding model
# ---------------------------------------------------------------------------


class Finding:
    """Single validation finding. Plain class for importlib-import compat."""

    __slots__ = ("stage", "severity", "subject", "message")

    def __init__(
        self,
        stage: str,
        severity: str,
        subject: str,
        message: str,
    ) -> None:
        self.stage = stage
        self.severity = severity
        self.subject = subject
        self.message = message

    def render(self) -> str:
        return (
            f"[{self.severity.upper()}] {self.stage}/{self.subject}: "
            f"{self.message}"
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "severity": self.severity,
            "subject": self.subject,
            "message": self.message,
        }

    def __repr__(self) -> str:  # for pytest diagnostics
        return self.render()


# ---------------------------------------------------------------------------
# Markdown code-block extraction
# ---------------------------------------------------------------------------


CODE_FENCE_RE = re.compile(
    r"^```(?P<lang>[A-Za-z0-9_+-]*)\s*$",
    re.MULTILINE,
)


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return ``[(lang, body), ...]`` for every fenced block.

    Empty-fence (no language tag) returns ``("", body)``. The body
    excludes the fence lines themselves.
    """
    out: list[tuple[str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = CODE_FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        lang = m.group("lang") or ""
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            if CODE_FENCE_RE.match(lines[j]) and lines[j].strip() == "```":
                break
            body.append(lines[j])
            j += 1
        out.append((lang, "\n".join(body)))
        i = j + 1
    return out


# ---------------------------------------------------------------------------
# Stage-1 — CLI argument vocabulary check
# ---------------------------------------------------------------------------


def _quote_aware_semi_split(line: str) -> list[str]:
    """Split on ';' but skip ';' inside single / double quotes."""
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == ";" and not in_single and not in_double:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def tokenize_command(line: str) -> list[str]:
    """Cheap shell-tokeniser: split on whitespace, strip trailing ``\\``.

    Good enough for the recipe-vocabulary check; we never execute
    these lines.
    """
    stripped = line.rstrip()
    if stripped.endswith("\\"):
        stripped = stripped[:-1].rstrip()
    return [tok for tok in stripped.split() if tok]


def parse_cli_args_against_vocab(
    blocks: list[tuple[str, str]],
) -> list[Finding]:
    """Stage 1: parse bash code-blocks against KNOWN_CLI_VOCAB.

    Returns one Finding per unknown argv0 or unknown long-option.
    """
    findings: list[Finding] = []
    for lang, body in blocks:
        if lang not in ("bash", "sh", "shell", ""):
            continue
        # Logical-line join: collapse ``\\`` continuations so the
        # `crane digest <image>` multi-line command parses as one
        # line with all tokens visible.
        joined_lines: list[str] = []
        buf: list[str] = []
        for raw in body.splitlines():
            stripped = raw.rstrip()
            if stripped.endswith("\\"):
                buf.append(stripped[:-1].rstrip())
            else:
                buf.append(stripped)
                joined_lines.append(" ".join(buf))
                buf = []
        if buf:
            joined_lines.append(" ".join(buf))
        # Split semicolon-separated multi-statement lines into atoms.
        # Quote-aware: we only split on ';' that sit outside single /
        # double quotes (Python inline-snippets carry ';' inside
        # quotes, e.g. ``python3 -c 'import x; ...'``).
        atoms: list[str] = []
        for jl in joined_lines:
            atoms.extend(_quote_aware_semi_split(jl))
        for line in atoms:
            # Strip comments + skip empty lines.
            if "#" in line:
                line = line.split("#", 1)[0]
            line = line.strip()
            if not line:
                continue
            # Skip pure variable assignments (FOO=bar ... or foo=...).
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
                continue
            # Skip pipe / shell-control fragments — we only care about
            # the head-command argument shapes, not the pipe targets.
            head_segment = line.split("|", 1)[0].strip()
            if not head_segment:
                continue
            # Bash subshell prefix ``$(`` — peel it.
            while head_segment.startswith("$("):
                head_segment = head_segment[2:].rstrip(")")
            tokens = tokenize_command(head_segment)
            if not tokens:
                continue
            # Skip control-flow tokens.
            if tokens[0] in {"if", "fi", "then", "else", "elif", "while", "do"}:
                continue
            argv0 = tokens[0]
            # Strip env-prefix (``COSIGN_EXPERIMENTAL=1 cosign ...``).
            while "=" in argv0 and not argv0.startswith("-"):
                if len(tokens) < 2:
                    break
                tokens = tokens[1:]
                argv0 = tokens[0]
            vocab = KNOWN_CLI_VOCAB.get(argv0)
            if vocab is None:
                # Unknown binary — semantic drift (will be re-flagged
                # in Stage-3 if it is gh-related, otherwise here).
                findings.append(
                    Finding(
                        stage="stage-1",
                        severity="error",
                        subject=argv0,
                        message=(
                            f"unknown argv0 '{argv0}' — add to "
                            "KNOWN_CLI_VOCAB or remove from recipe"
                        ),
                    )
                )
                continue
            # Subcommand vocab check (positional after argv0 if first
            # non-flag).
            subcommands = vocab["subcommands"]
            allowed_flags = vocab["flags"]
            for tok in tokens[1:]:
                if tok.startswith("--") or (
                    tok.startswith("-") and not tok[1:].isdigit()
                ):
                    flag = tok.split("=", 1)[0]
                    if flag not in allowed_flags:
                        findings.append(
                            Finding(
                                stage="stage-1",
                                severity="error",
                                subject=argv0,
                                message=(
                                    f"unknown flag '{flag}' for '{argv0}'"
                                ),
                            )
                        )
                else:
                    # First positional after argv0 — if vocab declares
                    # subcommands, the first must be in the set.
                    if subcommands and tok not in subcommands:
                        # Don't error if the positional could just be a
                        # plain argument (e.g. ``grep PATTERN PATH``).
                        if argv0 in {"cosign", "crane", "gh"}:
                            findings.append(
                                Finding(
                                    stage="stage-1",
                                    severity="error",
                                    subject=argv0,
                                    message=(
                                        f"unknown subcommand '{tok}' "
                                        f"for '{argv0}'"
                                    ),
                                )
                            )
                    # We only check the FIRST positional for subcommand
                    # membership.
                    break
    return findings


# ---------------------------------------------------------------------------
# Stage-2 — embedded YAML / JSON snippets validate as YAML / JSON
# ---------------------------------------------------------------------------


def validate_embedded_yaml_json(
    blocks: list[tuple[str, str]],
) -> list[Finding]:
    """Stage 2: every yaml/json/jsonc fenced block must parse."""
    findings: list[Finding] = []
    for lang, body in blocks:
        if lang in ("yaml", "yml"):
            try:
                import yaml  # noqa: WPS433 — optional dep, hermetic
            except ImportError:
                # PyYAML not on path; do a minimal hand-roll: every
                # non-comment, non-empty line must be a key: value
                # or list item.
                for ln in body.splitlines():
                    stripped = ln.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if not (
                        ":" in stripped
                        or stripped.startswith("-")
                        or stripped.startswith("|")
                        or stripped.startswith(">")
                    ):
                        findings.append(
                            Finding(
                                stage="stage-2",
                                severity="error",
                                subject="yaml-fallback",
                                message=(
                                    f"non-YAML-shaped line: {stripped!r}"
                                ),
                            )
                        )
                continue
            try:
                yaml.safe_load(body)
            except Exception as exc:  # noqa: BLE001 — surface error
                findings.append(
                    Finding(
                        stage="stage-2",
                        severity="error",
                        subject="yaml-parse",
                        message=f"yaml.safe_load failed: {exc}",
                    )
                )
        elif lang in ("json", "jsonc"):
            try:
                json.loads(body)
            except json.JSONDecodeError as exc:
                findings.append(
                    Finding(
                        stage="stage-2",
                        severity="error",
                        subject="json-parse",
                        message=f"json.loads failed: {exc}",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Stage-3 — gh-shape table + workflow-existence cross-check
# ---------------------------------------------------------------------------


def find_gh_calls(blocks: list[tuple[str, str]]) -> list[str]:
    """Return joined-line ``gh ...`` commands from bash blocks."""
    out: list[str] = []
    for lang, body in blocks:
        if lang not in ("bash", "sh", "shell", ""):
            continue
        # Join continuations.
        joined: list[str] = []
        buf: list[str] = []
        for raw in body.splitlines():
            stripped = raw.rstrip()
            if stripped.endswith("\\"):
                buf.append(stripped[:-1].rstrip())
            else:
                buf.append(stripped)
                joined.append(" ".join(buf))
                buf = []
        if buf:
            joined.append(" ".join(buf))
        for line in joined:
            line = line.split("#", 1)[0].strip()
            if line.startswith("gh "):
                # Normalise multi-space to single-space.
                out.append(re.sub(r"\s+", " ", line).strip())
    return out


def validate_gh_shapes(
    gh_calls: list[str],
    repo_root: Path,
) -> list[Finding]:
    """Stage 3: every ``gh ...`` call matches a known shape AND the
    referenced workflow file exists under ``.github/workflows/``.
    """
    findings: list[Finding] = []
    workflows_dir = repo_root / ".github" / "workflows"
    for call in gh_calls:
        matched = False
        for label, shape_re in GH_KNOWN_SHAPES:
            if re.match(shape_re, call):
                matched = True
                break
        if not matched:
            findings.append(
                Finding(
                    stage="stage-3",
                    severity="error",
                    subject="gh-shape",
                    message=(
                        f"unknown gh-call shape: {call!r}; add to "
                        "GH_KNOWN_SHAPES if intentional"
                    ),
                )
            )
    # Workflow-existence cross-check.
    for wf in WORKFLOW_REFS:
        if not (workflows_dir / f"{wf}.yml").exists():
            findings.append(
                Finding(
                    stage="stage-3",
                    severity="error",
                    subject="workflow-ref",
                    message=(
                        f"recipe references workflow '{wf}' but "
                        f"'.github/workflows/{wf}.yml' is missing"
                    ),
                )
            )
    return findings


def validate_substrate_tokens(
    text: str,
    repo_root: Path,
) -> list[Finding]:
    """Stage 3b: placeholder tokens the guide names must exist on disk.

    This is the cross-substrate consistency check — if the guide says
    "the placeholder is ``DIGEST_PENDING_KAI_CROSS_REVIEW``", the
    repository grep must return matches in the documented files.
    Tag-58 readiness-map post-cutover this can become zero; the
    semantic-drift verdict tolerates zero matches but the guide MUST
    still reference the token literally (otherwise the recipe is
    stale).
    """
    findings: list[Finding] = []
    if PLACEHOLDER_TOKEN not in text:
        findings.append(
            Finding(
                stage="stage-3b",
                severity="error",
                subject="placeholder-token",
                message=(
                    f"guide does not mention placeholder token "
                    f"{PLACEHOLDER_TOKEN!r}"
                ),
            )
        )
    if PENDING_TRUST_ROOT_TOKEN not in text:
        findings.append(
            Finding(
                stage="stage-3b",
                severity="error",
                subject="pending-token",
                message=(
                    f"guide does not mention pending-trust-root token "
                    f"{PENDING_TRUST_ROOT_TOKEN!r}"
                ),
            )
        )
    # Substrate files the guide claims to operate on must exist.
    for rel in (PINNED_TRUST_ROOT_PATH, COSIGN_POLICY_PATH):
        if not (repo_root / rel).exists():
            findings.append(
                Finding(
                    stage="stage-3b",
                    severity="error",
                    subject="substrate-file",
                    message=(
                        f"guide references substrate file '{rel}' "
                        "but it is missing on disk"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Stage-4 — aggregate verdict
# ---------------------------------------------------------------------------


def aggregate_verdict(findings: list[Finding]) -> str:
    """Return RECIPE-INTACT / RECIPE-SYNTAX-DRIFT / RECIPE-SEMANTIC-DRIFT."""
    if not findings:
        return "RECIPE-INTACT"
    # Stage-1 + Stage-2 are syntax-level; Stage-3 + Stage-3b are
    # semantic-level. If ANY semantic finding is present, the
    # aggregate is RECIPE-SEMANTIC-DRIFT (strictly worse than syntax).
    has_semantic = any(
        f.stage.startswith("stage-3") for f in findings
    )
    if has_semantic:
        return "RECIPE-SEMANTIC-DRIFT"
    return "RECIPE-SYNTAX-DRIFT"


# ---------------------------------------------------------------------------
# Top-level entry — pure-function for tests + CLI
# ---------------------------------------------------------------------------


def validate_recipe(doc_text: str, repo_root: Path) -> dict[str, Any]:
    """Run all four stages and return a structured result dict.

    Returns:
        ``{"verdict": ..., "findings": [Finding, ...], "stages": {...}}``
    """
    blocks = extract_code_blocks(doc_text)
    stage1 = parse_cli_args_against_vocab(blocks)
    stage2 = validate_embedded_yaml_json(blocks)
    gh_calls = find_gh_calls(blocks)
    stage3 = validate_gh_shapes(gh_calls, repo_root)
    stage3b = validate_substrate_tokens(doc_text, repo_root)
    all_findings = stage1 + stage2 + stage3 + stage3b
    verdict = aggregate_verdict(all_findings)
    return {
        "verdict": verdict,
        "findings": all_findings,
        "stages": {
            "stage-1-cli-vocab": [f.to_dict() for f in stage1],
            "stage-2-yaml-json": [f.to_dict() for f in stage2],
            "stage-3-gh-shapes": [f.to_dict() for f in stage3],
            "stage-3b-substrate": [f.to_dict() for f in stage3b],
        },
        "code_block_count": len(blocks),
        "gh_call_count": len(gh_calls),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the G1+G2 Operator-Hand setup-guide recipe "
            "for syntactic + semantic consistency (Tag-60 smoke)."
        )
    )
    parser.add_argument(
        "--doc",
        default=DOC_DEFAULT,
        help=f"path to guide (default: {DOC_DEFAULT})",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="repository root (default: cwd)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON on stdout",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    doc_path = repo_root / args.doc
    if not doc_path.exists():
        print(
            f"[FATAL] guide not found: {doc_path}",
            file=sys.stderr,
        )
        return 1
    doc_text = doc_path.read_text(encoding="utf-8")
    result = validate_recipe(doc_text, repo_root)

    if args.json:
        # Render structured result (Finding objects -> dicts via the
        # stages map).
        out = {
            "verdict": result["verdict"],
            "code_block_count": result["code_block_count"],
            "gh_call_count": result["gh_call_count"],
            "stages": result["stages"],
        }
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"verdict: {result['verdict']}")
        print(f"code-blocks parsed: {result['code_block_count']}")
        print(f"gh-calls parsed:    {result['gh_call_count']}")
        if result["findings"]:
            print("findings:", file=sys.stderr)
            for f in result["findings"]:
                print(f"  {f.render()}", file=sys.stderr)

    return 0 if result["verdict"] == "RECIPE-INTACT" else 1


if __name__ == "__main__":
    sys.exit(main())
