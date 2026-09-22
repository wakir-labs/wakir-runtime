# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""The evidence-citation lint over the two public trust documents.

Rule
----

``STABILITY.md`` and ``docs/architecture/layers.md`` are the two
documents in which we tell a reader what to believe about this
repository and why. Every artefact they cite as the *reason* for a
claim has to be real, and a cited test module additionally has to be
one that something actually executes. A maturity row whose evidence is
a test nobody runs is not a weaker claim than it looks — it is a claim
with no evidence at all, dressed as one with evidence.

Three checks, one rule-art, two documents:

1. **Cited test module** — exists on disk, has an entry in
   ``tests/lanes/lane_assignment.json``, and that entry's profile is one
   that is actually executed.
2. **Cited workflow file** — exists under ``.github/workflows/``, or is
   registered in ``docs/ci/retired-workflows.md`` with the change that
   removed it. Registration is not amnesty: a registered workflow that
   exists again fails too.
3. **Any other cited repository path** — exists.

Why not the simpler lint
------------------------

The obvious version — "every workflow filename a document mentions must
exist" — was measured against ``main`` on 2026-09-14 and produced three
false positives, all of them careful historical prose, including a
sentence whose entire point was that the workflow no longer exists. A
lint that is wrong about correct writing gets switched off. Hence the
register in check 2: history stays legal and stays checkable.

What this lint would have caught, tested below against the real text
---------------------------------------------------------------------

``STABILITY.md`` line 82 was written three times in two days, and the
first two versions are the same defect in two sub-species. The
``real_generations`` cases replay all three verbatim from git history:

* pre-PR-#540 — credits ``external-verifier-drift.yml`` as an active
  drift watcher. The file had already been deleted. Check 2, red.
* PR #540 — replaces it with ``tests/wat/test_external_verifier_parity.py``
  "in the ordinary test lane". No workflow ran that module. Check 1,
  red — the correction had stayed inside the error class and only
  changed sub-species.
* after Box A — the module is in a mandatory lane and the harness
  actually runs. Green.

What it cannot catch, stated so nobody reads more into a green run
------------------------------------------------------------------

This lint is hermetic. It knows whether a workflow file exists and
whether a module sits in a lane; it does not know how often anything
has run. Two of the four PR-#540 corrections were of that second kind —
``live-vm-acceptance.yml`` existed and had had zero runs since
2026-05-16; the real-VM leg of ``e2e-vm-acceptance-gate.yml`` existed
and had never been dispatched. Only the Actions API can say that. Both
were withdrawn on 2026-09-22 under ADR-0077, which is the point worth
keeping: this lint would have gone on passing either way, because a
file that exists satisfies check 2 no matter how often it runs. The
counterpart here is the ``execution_evidence`` block that every standing
exemption in ``lane_assignment.json`` carries.

Anchors: CTO decision paper 2026-09-14 §2 · ADR-0075.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The two documents in scope. Deliberately not ``docs/**``: this is one
#: rule over the two documents that make trust claims, not a link
#: checker over the tree. The wider sweep is the archaeology offensive
#: ADR-0073 blocks.
TRUST_DOCUMENTS: tuple[str, ...] = (
    "STABILITY.md",
    "docs/architecture/layers.md",
)

WORKFLOWS_DIR = ".github/workflows"
LANE_ASSIGNMENT = "tests/lanes/lane_assignment.json"
RETIRED_REGISTER = "docs/ci/retired-workflows.md"

#: Lane profiles under which a module is executed by something.
#:
#: ``required`` blocks a merge; ``optional-ci`` runs on the pull-request
#: surface without blocking. Both are execution, and a trust document
#: may cite either — a non-blocking run is still a run.
#:
#: ``opt-in-marker`` and ``operator-hand`` are not. That is measured,
#: not assumed: every standing exemption group in ``lane_assignment.json``
#: carries an ``execution_evidence`` block, and for these groups it reads
#: ``runs_total: 0`` with ``last_actual_run: "never"``. Citing such a
#: module as the reason a claim holds is the defect this file exists for.
EXECUTED_PROFILES = frozenset({"required", "optional-ci"})
UNEXECUTED_PROFILES = frozenset({"opt-in-marker", "operator-hand"})

#: Backticked tokens that look like repository paths.
_TOKEN = re.compile(r"`([A-Za-z0-9_.][A-Za-z0-9_./*+-]*)`")

_SOURCE_SUFFIXES = (
    ".py",
    ".yml",
    ".yaml",
    ".json",
    ".md",
    ".sh",
    ".rs",
    ".toml",
    ".bin",
    ".ots",
)

_TEST_MODULE = re.compile(r"(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.py)$")


class Citation:
    """One backticked repository path found in a trust document."""

    __slots__ = ("document", "line", "path")

    def __init__(self, document: str, line: int, path: str) -> None:
        self.document = document
        self.line = line
        self.path = path

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"{self.document}:{self.line} `{self.path}`"


def is_workflow_citation(path: str) -> bool:
    return path.endswith((".yml", ".yaml"))


def is_test_module_citation(path: str) -> bool:
    return bool(_TEST_MODULE.search(path)) and "*" not in path


def extract_citations(document: str, text: str, top_level: set[str]) -> list[Citation]:
    """Return every backticked token in ``text`` that denotes a repo path.

    ``top_level`` is the set of names directly under the repository root.
    Two shapes count:

    * a bare workflow filename (``foo.yml``) — how both documents name
      workflows in practice, without the ``.github/workflows/`` prefix;
    * a token containing a ``/`` that either starts with a real
      top-level entry or carries a source-file suffix.

    Without the second filter, prose such as ``n/a`` and required-context
    names that happen to contain a slash would be linted as file paths.
    """
    out: list[Citation] = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in _TOKEN.finditer(line):
            token = match.group(1)
            if "://" in token:
                continue
            if "/" not in token:
                if not is_workflow_citation(token):
                    continue
            else:
                head = token.split("/", 1)[0]
                if head not in top_level and not token.endswith(_SOURCE_SUFFIXES):
                    continue
            out.append(Citation(document, number, token))
    return out


def _path_exists(repo_root: Path, path: str) -> bool:
    if "*" in path:
        return any(repo_root.glob(path.rstrip("/")))
    return (repo_root / path.rstrip("/")).exists()


def parse_retired_register(text: str) -> dict[str, str]:
    """Return ``{workflow file: removing change}`` from the register table.

    Rows look like ``| `name.yml` | `commit` or PR #n | date | why |``.
    A row without a removing change is not a registration — the whole
    point of the register is that a deletion is attributable.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0].strip("`")
        if not name.endswith((".yml", ".yaml")):
            continue
        removed_by = cells[1]
        if removed_by:
            out[name] = removed_by
    return out


def lint(
    *,
    repo_root: Path,
    documents: dict[str, str],
    workflow_files: set[str],
    lane_modules: dict[str, dict],
    retired: dict[str, str],
    top_level: set[str],
) -> list[str]:
    """Return one human-readable finding per violated citation."""
    findings: list[str] = []
    for document, text in documents.items():
        for cite in extract_citations(document, text, top_level):
            where = f"{cite.document}:{cite.line} `{cite.path}`"

            if is_workflow_citation(cite.path):
                name = cite.path.rsplit("/", 1)[-1]
                exists = name in workflow_files
                registered = name in retired
                if exists and registered:
                    findings.append(
                        f"{where}: workflow exists under {WORKFLOWS_DIR}/ *and* is "
                        f"listed in {RETIRED_REGISTER}. The register is a record of "
                        f"deletions, not a list of names that stop being checked; "
                        f"remove the entry."
                    )
                elif not exists and not registered:
                    findings.append(
                        f"{where}: no such workflow under {WORKFLOWS_DIR}/ and no "
                        f"entry in {RETIRED_REGISTER}. If the sentence is history, "
                        f"register the file with the change that removed it; if it "
                        f"is a claim, it is citing something that does not exist."
                    )
                continue

            if not _path_exists(repo_root, cite.path):
                findings.append(
                    f"{where}: cited path does not exist in the repository."
                )
                continue

            if not is_test_module_citation(cite.path):
                continue

            entry = lane_modules.get(cite.path)
            if entry is None:
                findings.append(
                    f"{where}: cited as evidence but has no entry in "
                    f"{LANE_ASSIGNMENT}, so nothing states whether it runs."
                )
                continue
            profile = entry.get("profile")
            if profile in EXECUTED_PROFILES:
                continue
            if profile in UNEXECUTED_PROFILES:
                findings.append(
                    f"{where}: cited as evidence, but its lane profile is "
                    f"'{profile}' — measured as never executed. Either put it in a "
                    f"lane that runs, or stop offering it as the reason the claim "
                    f"holds."
                )
            else:
                findings.append(
                    f"{where}: lane profile '{profile}' is not one this lint knows. "
                    f"Add it to EXECUTED_PROFILES or UNEXECUTED_PROFILES — an "
                    f"unclassified profile must not default to 'fine'."
                )
    return findings


# ---------------------------------------------------------------------------
# The lint itself, against the real tree.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_inputs() -> dict:
    documents = {
        name: (REPO_ROOT / name).read_text(encoding="utf-8")
        for name in TRUST_DOCUMENTS
    }
    lane = json.loads((REPO_ROOT / LANE_ASSIGNMENT).read_text(encoding="utf-8"))
    register_path = REPO_ROOT / RETIRED_REGISTER
    assert register_path.is_file(), (
        f"{RETIRED_REGISTER} must exist — it is the half of this lint that keeps "
        f"historical prose legal"
    )
    return {
        "repo_root": REPO_ROOT,
        "documents": documents,
        "workflow_files": {p.name for p in (REPO_ROOT / WORKFLOWS_DIR).glob("*.y*ml")},
        "lane_modules": lane["modules"],
        "retired": parse_retired_register(register_path.read_text(encoding="utf-8")),
        "top_level": {p.name for p in REPO_ROOT.iterdir()},
    }


def test_every_citation_in_the_trust_documents_resolves(real_inputs: dict) -> None:
    findings = lint(**real_inputs)
    assert findings == [], "\n".join(["evidence-citation lint failed:"] + findings)


def test_the_lint_actually_sees_the_documents(real_inputs: dict) -> None:
    """Guard against a vacuous pass.

    A token filter that silently stops matching turns this lint into a
    green no-op, which is the failure mode of every lint that checks
    documents. Both documents must yield citations, and the test-module
    citations — the ones the rule is really about — must be found.
    """
    top_level = real_inputs["top_level"]
    per_document = {
        name: extract_citations(name, text, top_level)
        for name, text in real_inputs["documents"].items()
    }
    for name, cites in per_document.items():
        assert len(cites) >= 10, f"{name}: only {len(cites)} citations extracted"
    modules = [
        c.path
        for cites in per_document.values()
        for c in cites
        if is_test_module_citation(c.path)
    ]
    assert len(modules) >= 5, f"only {len(modules)} test-module citations found"


def test_cited_test_modules_are_all_in_an_executed_lane(real_inputs: dict) -> None:
    """The measurement, spelled out rather than implied by a green lint.

    Read 2026-09-15 on the Box-A merge commit: seven citations, seven
    entries, all ``required``. The CTO paper's "five of seven red" and
    the mirrored number in the Box-B brief both predate Box A.
    """
    lane_modules = real_inputs["lane_modules"]
    cited = sorted(
        {
            c.path
            for name, text in real_inputs["documents"].items()
            for c in extract_citations(name, text, real_inputs["top_level"])
            if is_test_module_citation(c.path)
        }
    )
    profiles = {path: lane_modules.get(path, {}).get("profile") for path in cited}
    unexecuted = {p: v for p, v in profiles.items() if v not in EXECUTED_PROFILES}
    assert unexecuted == {}, f"cited but not executed: {unexecuted}"


def test_the_register_only_holds_workflows_that_are_really_gone(
    real_inputs: dict,
) -> None:
    present = real_inputs["workflow_files"]
    still_there = sorted(set(real_inputs["retired"]) & present)
    assert still_there == [], (
        f"{RETIRED_REGISTER} lists workflows that exist again: {still_there}. "
        f"An entry that outlives its deletion turns the register into a "
        f"suppression list."
    )


def test_every_register_entry_names_the_change_that_removed_it(
    real_inputs: dict,
) -> None:
    register = real_inputs["retired"]
    assert register, "the register parsed to nothing — check the table shape"
    for name, removed_by in register.items():
        assert removed_by.strip(), f"{name}: no removing change recorded"


# ---------------------------------------------------------------------------
# Negative controls. A lint whose failure path is untested is a comment.
# ---------------------------------------------------------------------------


def _inputs(tmp_path: Path, doc_text: str, **overrides) -> dict:
    base = {
        "repo_root": tmp_path,
        "documents": {"DOC.md": doc_text},
        "workflow_files": {"live.yml"},
        "lane_modules": {
            "tests/x/test_running.py": {"profile": "required"},
            "tests/x/test_watched.py": {"profile": "optional-ci"},
            "tests/x/test_drill.py": {"profile": "opt-in-marker"},
            "tests/x/test_manual.py": {"profile": "operator-hand"},
            "tests/x/test_future.py": {"profile": "somebody-invented-this"},
        },
        "retired": {"gone.yml": "`527508e`"},
        "top_level": {"tests", "docs", "scripts"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for name in (
        "test_running.py",
        "test_watched.py",
        "test_drill.py",
        "test_manual.py",
        "test_future.py",
        "test_orphan.py",
    ):
        (tmp_path / "tests" / "x").mkdir(parents=True, exist_ok=True)
        (tmp_path / "tests" / "x" / name).write_text("")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "real.md").write_text("")
    return tmp_path


def test_negative_cited_module_in_an_unexecuted_profile_is_red(tree: Path) -> None:
    findings = lint(**_inputs(tree, "pinned by `tests/x/test_drill.py`."))
    assert len(findings) == 1
    assert "opt-in-marker" in findings[0]


def test_negative_operator_hand_profile_is_red(tree: Path) -> None:
    findings = lint(**_inputs(tree, "pinned by `tests/x/test_manual.py`."))
    assert len(findings) == 1
    assert "operator-hand" in findings[0]


def test_negative_unknown_profile_does_not_default_to_fine(tree: Path) -> None:
    findings = lint(**_inputs(tree, "pinned by `tests/x/test_future.py`."))
    assert len(findings) == 1
    assert "not one this lint knows" in findings[0]


def test_negative_cited_module_with_no_lane_entry_is_red(tree: Path) -> None:
    findings = lint(**_inputs(tree, "pinned by `tests/x/test_orphan.py`."))
    assert len(findings) == 1
    assert "no entry in" in findings[0]


def test_negative_cited_module_that_does_not_exist_is_red(tree: Path) -> None:
    findings = lint(**_inputs(tree, "pinned by `tests/x/test_imaginary.py`."))
    assert len(findings) == 1
    assert "does not exist" in findings[0]


def test_negative_cited_path_that_does_not_exist_is_red(tree: Path) -> None:
    findings = lint(**_inputs(tree, "specified in `docs/imaginary.md`."))
    assert len(findings) == 1
    assert "does not exist" in findings[0]


def test_negative_unregistered_missing_workflow_is_red(tree: Path) -> None:
    findings = lint(**_inputs(tree, "watched by `vanished.yml`."))
    assert len(findings) == 1
    assert RETIRED_REGISTER in findings[0]


def test_registered_missing_workflow_is_allowed(tree: Path) -> None:
    findings = lint(**_inputs(tree, "`gone.yml` no longer exists."))
    assert findings == []


def test_negative_register_entry_for_a_live_workflow_is_red(tree: Path) -> None:
    findings = lint(
        **_inputs(tree, "see `live.yml`.", retired={"live.yml": "`527508e`"})
    )
    assert len(findings) == 1
    assert "not a list of names that stop being checked" in findings[0]


def test_both_executed_profiles_pass(tree: Path) -> None:
    doc = "pinned by `tests/x/test_running.py` and `tests/x/test_watched.py`."
    assert lint(**_inputs(tree, doc)) == []


def test_prose_that_is_not_a_path_is_not_linted(tree: Path) -> None:
    doc = (
        "the required context `wirelang suite without rfc8785 / jsonschema (shadow)` "
        "reports `n/a` and the issuer is `did:web:wakir.dev:treasury-agent`."
    )
    assert lint(**_inputs(tree, doc)) == []


# ---------------------------------------------------------------------------
# The three real generations of STABILITY.md line 82.
# ---------------------------------------------------------------------------

#: Verbatim from git history. `441c9d6~1` is the row PR #540 replaced,
#: `441c9d6` is PR #540's own correction, `e1f1555` is PR #541.
GENERATION_BEFORE_540 = (
    "Two independent JSON-Schema implementations validate our published schemas, "
    "with a drift workflow (`external-verifier-drift.yml`) watching for divergence. "
    "Not a required context, so drift is reported rather than blocking."
)

GENERATION_540 = (
    "Two independent JSON-Schema implementations validate our published schemas. "
    "What actually watches for divergence is `tests/wat/test_external_verifier_parity.py`, "
    "driven by `scripts/external_verifier_validation.py`, in the ordinary test lane."
)

GENERATION_AFTER_BOX_A = (
    "As of the Welle-3 lane promotion this is executed: the `Lane — WAT core` job of "
    "`runtime-acceptance-gates.yml` installs Node 22 and runs "
    "`tests/wat/test_external_verifier_parity.py`."
)


@pytest.fixture
def harness_tree(tmp_path: Path) -> Path:
    (tmp_path / "tests" / "wat").mkdir(parents=True)
    (tmp_path / "tests" / "wat" / "test_external_verifier_parity.py").write_text("")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "external_verifier_validation.py").write_text("")
    return tmp_path


def _harness_inputs(tree: Path, text: str, *, profile: str, retired: dict) -> dict:
    return {
        "repo_root": tree,
        "documents": {"STABILITY.md": text},
        "workflow_files": {"runtime-acceptance-gates.yml"},
        "lane_modules": (
            {"tests/wat/test_external_verifier_parity.py": {"profile": profile}}
            if profile
            else {}
        ),
        "retired": retired,
        "top_level": {"tests", "scripts"},
    }


def test_generation_before_540_credits_a_deleted_workflow(harness_tree: Path) -> None:
    """Sub-species one: the evidence is a workflow that no longer exists.

    No register existed at the time, so the register is empty here.
    """
    findings = lint(
        **_harness_inputs(
            harness_tree, GENERATION_BEFORE_540, profile="required", retired={}
        )
    )
    assert len(findings) == 1
    assert "external-verifier-drift.yml" in findings[0]


def test_generation_540_cites_a_module_nothing_runs(harness_tree: Path) -> None:
    """Sub-species two: the correction that stayed inside the error class.

    The workflow half is now legal via the register, which isolates the
    remaining defect — the module was cited as the watcher while no
    workflow executed it.
    """
    findings = lint(
        **_harness_inputs(
            harness_tree,
            GENERATION_540,
            profile=None,
            retired={"external-verifier-drift.yml": "`527508e`"},
        )
    )
    assert len(findings) == 1
    assert "test_external_verifier_parity.py" in findings[0]
    assert "no entry in" in findings[0]


def test_generation_after_box_a_passes(harness_tree: Path) -> None:
    """Positive control: the same sentence, once the module is in a lane."""
    findings = lint(
        **_harness_inputs(
            harness_tree,
            GENERATION_AFTER_BOX_A,
            profile="required",
            retired={},
        )
    )
    assert findings == []
