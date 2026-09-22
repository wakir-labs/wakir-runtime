#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Private (RFC1918) addresses do not belong in a public working tree.

Why this file exists
--------------------

Not publishing the operator's own network topology has been a standing
directive since 2026-05-03. On 2026-09-22 this lint, run against the
commit before the scrub, reported 85 occurrences across 23 files: the
operator's two pilot VMs, the federation bridge subnet, and eleven
prose wildcards of the form `192.168.<n>.*`. The directive had been in
force for four months and nothing had ever compared it to the tree.

There is a secret-scanning lane. It runs gitleaks over the full history
with ``useDefault = true``. Default gitleaks rules look for credentials
-- keys, tokens, connection strings -- and an internal IP address is not
a credential, so no rule ever fired. The rule existed only in prose:

    a check that is written down but never executed is not a check.

This module is the executed half. The scrub without it repeats in three
months.

Scope, and the reason for it
----------------------------

**The tree, not the history.** ``git log`` is deliberately out of scope.
Rewriting the history of a public repository with 550+ pull requests is
a larger operational risk than a non-routable address in the log, and
that call was made explicitly rather than by omission. So this lint
reads files, never commits, and a green run says nothing whatsoever
about what is in the history.

**All of RFC1918, not one prefix.** ``10.0.0.0/8``, ``172.16.0.0/12``
and ``192.168.0.0/16``. A lint that only knew the one prefix found in
the 2026-09 scrub would be guarding the past: the next operator, or the
next lab network, will not use it.

**Allow-list entries expire.** ADR-0075 §3, same semantics as
``tooling/ci/exemption_expiry.py``: the date is compared against the
calendar, and an expired entry turns this gate red rather than quietly
ceasing to apply. An exception with no end date is the class that ADR
closed.

What this does NOT catch
------------------------

Written down here because a gate whose gaps are undocumented gets cited
tomorrow as coverage:

1. **The git history.** By design, see above.
2. **Other non-public address space.** Carrier-grade NAT
   (``100.64.0.0/10``), link-local (``169.254.0.0/16``), IPv6 unique
   local addresses (``fc00::/7``) and IPv6 link-local (``fe80::/10``)
   are *not* enforced. Only RFC1918 is. They are cheap to add to
   ``RULES`` below if someone decides to.
3. **Public addresses.** An operator's static WAN address, or a cloud
   host's public IP, is more sensitive than anything in RFC1918 and is
   invisible here. There is no way to tell one from an example in a
   doc without a list of what is ours.
4. **Hostnames, usernames, SSH key paths, MAC addresses.** A separate
   class, and a populated one: as of 2026-09-22 the tree still carries
   32 occurrences of an operator home-directory path across 19 files,
   including functional quadlet mount paths and Rust integration
   tests. Removing those changes behaviour on the substrate, so it was
   left out of the change that introduced this lint rather than
   bundled into it. The rule table above is a tuple so that class can
   be added as data once someone owns the behaviour change.
5. **Anything not a literal in a text file.** An address assembled at
   runtime, stored in a binary or an image, base64-encoded, or written
   as a 32-bit integer, passes.
6. **Untracked files.** The scan walks ``git ls-files``, so a file that
   was never added is not examined -- it is also not published.

Usage::

    python tooling/ci/private_address_lint.py --check     # exit 1 on finding
    python tooling/ci/private_address_lint.py --summary   # markdown, never fails
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPO_ROOT / "tooling" / "ci" / "private-address-allowlist.json"

ALLOWLIST_SCHEMA = "wakir-private-address-allowlist/v1"

#: Mandatory members of an allow-list entry. Deliberately the same shape
#: as ``tooling/compat/compat-allowlist.json`` -- this repository has a
#: pattern for a time-boxed allow-list and a fourth one would be a
#: fourth thing to read.
REQUIRED_KEYS = frozenset({"path", "addresses", "reason", "owner", "until", "tracking"})

#: Warning window before ``until``, matching ADR-0075 §3's damper.
WARN_DAYS = 14

#: A reason short enough to fit in a commit subject is not a reason.
#: Same threshold as ``exemption_expiry.MIN_RENEWAL_REASON``.
MIN_REASON = 60

_TRACKING_RE = re.compile(
    r"^https://github\.com/wakir-labs/[A-Za-z0-9_.-]+/(pull|issues)/[0-9]+$"
)

#: A decimal octet, 0-255. Strict, so a version string like `10.300.1.1`
#: or a four-part release number with an out-of-range part does not
#: register as an address.
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"

#: A last octet written as a wildcard or a placeholder: `192.168.178.*`,
#: `192.168.178.x`, `192.168.178.<peer>`. Three files in the 2026-09
#: scrub used exactly this form in prose, and it is the obvious way
#: around a lint that only matches four numeric octets -- while still
#: disclosing the /24 the host sits in, which is the part that matters.
_WILDCARD = r"(?:\*|[xX]{1,3}|<[A-Za-z][A-Za-z0-9_-]*>)"

#: Enforced ranges. A tuple rather than one regex so the failure message
#: can name which block was hit, and so adding a class later (see gap 2
#: in the module docstring) is a data change.
RULES: tuple[tuple[str, str], ...] = (
    ("RFC1918 10.0.0.0/8", rf"10(?:\.{_OCTET}){{3}}"),
    ("RFC1918 172.16.0.0/12", rf"172\.(?:1[6-9]|2[0-9]|3[01])(?:\.{_OCTET}){{2}}"),
    ("RFC1918 192.168.0.0/16", rf"192\.168(?:\.{_OCTET}){{2}}"),
    (
        "RFC1918 prefix with wildcard octet",
        rf"(?:10(?:\.{_OCTET}){{2}}"
        rf"|172\.(?:1[6-9]|2[0-9]|3[01])\.{_OCTET}"
        rf"|192\.168\.{_OCTET})\.{_WILDCARD}",
    ),
)

#: Guards against matching inside a longer dotted run (a five-part
#: version, a trailing octet of something else). The trailing form
#: still allows a sentence-ending period.
_BODY = "|".join(body for _, body in RULES)
ADDRESS_RE = re.compile(rf"(?<![0-9.])(?:{_BODY})(?!\.?[0-9])")

_RULE_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rf"(?<![0-9.])(?:{body})(?!\.?[0-9])")) for name, body in RULES
)

#: Never scanned, and the list is asserted to be exactly this in
#: ``tests/ci/test_private_address_lint.py``. Each of the three files
#: has to contain address literals in order to do its job: the lint
#: carries the patterns, the allow-list names the addresses it tolerates,
#: and the test needs fixtures to prove the lint fires. A self-exclusion
#: is a hole, so it is pinned at three paths rather than a directory --
#: widening it means editing a test that says why it is three.
SELF_EXCLUDED: tuple[str, ...] = (
    "tooling/ci/private_address_lint.py",
    "tooling/ci/private-address-allowlist.json",
    "tests/ci/test_private_address_lint.py",
)

BINARY_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2",
        ".ots", ".bin", ".gz", ".zip", ".tar", ".whl", ".so", ".jks", ".p12",
    }
)


class AllowlistError(ValueError):
    """The allow-list file or one of its entries is invalid."""


@dataclass(frozen=True)
class Finding:
    """One private address literal, at one place in one file."""

    path: str
    line: int
    address: str
    rule: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.address} ({self.rule})"


@dataclass(frozen=True)
class AllowlistEntry:
    path: str
    addresses: tuple[str, ...]
    reason: str
    owner: str
    until: dt.date
    tracking: str

    def covers(self, finding: Finding) -> bool:
        return finding.path == self.path and finding.address in self.addresses

    def days_left(self, today: dt.date) -> int:
        return (self.until - today).days

    def is_expired(self, today: dt.date) -> bool:
        return self.until < today


@dataclass(frozen=True)
class Report:
    """Everything one run learned, before anything decides to exit 1."""

    findings: tuple[Finding, ...]
    violations: tuple[Finding, ...]
    allowed: tuple[Finding, ...]
    expired: tuple[AllowlistEntry, ...]
    warning: tuple[AllowlistEntry, ...]
    unused: tuple[AllowlistEntry, ...]

    @property
    def ok(self) -> bool:
        return not self.violations and not self.expired


# ---------------------------------------------------------------------------
# Allow-list
# ---------------------------------------------------------------------------


def _parse_date(value: object, where: str) -> dt.date:
    if not isinstance(value, str):
        raise AllowlistError(f"{where}: expected an ISO date string, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise AllowlistError(f"{where}: {value!r} is not an ISO date ({exc})") from exc


def load_allowlist(path: Path = ALLOWLIST_PATH) -> tuple[AllowlistEntry, ...]:
    """Parse and validate the allow-list.

    A malformed entry raises rather than being skipped. An allow-list
    entry that cannot be read is an exemption nobody can check, which is
    the same failure as an expired one.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AllowlistError(
            f"allow-list not found at {path}. The gate needs the file to "
            "exist even when it is empty: an absent allow-list and an empty "
            "one look identical at the call site, and only one of them is a "
            "decision."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AllowlistError(f"{path}: not valid JSON ({exc})") from exc

    schema = document.get("schema")
    if schema != ALLOWLIST_SCHEMA:
        raise AllowlistError(
            f"{path}: schema is {schema!r}, expected {ALLOWLIST_SCHEMA!r}"
        )
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise AllowlistError(f"{path}: `entries` must be a list")

    entries: list[AllowlistEntry] = []
    for index, raw in enumerate(raw_entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(raw, dict):
            raise AllowlistError(f"{where}: must be an object")
        keys = set(raw)
        missing = REQUIRED_KEYS - keys
        if missing:
            raise AllowlistError(
                f"{where}: missing {sorted(missing)}. Every member is "
                "mandatory: an allow-list entry has to say which file, "
                "which addresses, why, who, until when, and where it is "
                "tracked."
            )
        extra = keys - REQUIRED_KEYS
        if extra:
            raise AllowlistError(f"{where}: unexpected member(s) {sorted(extra)}")

        addresses = raw["addresses"]
        if not isinstance(addresses, list) or not addresses:
            raise AllowlistError(
                f"{where}: `addresses` must be a non-empty list of the exact "
                "literals tolerated in this file. A path-only entry would "
                "allow every future address in it too."
            )
        for address in addresses:
            if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
                raise AllowlistError(
                    f"{where}: {address!r} is not a private address this lint "
                    "would flag, so allow-listing it hides nothing and only "
                    "rots."
                )

        reason = str(raw["reason"]).strip()
        if len(reason) < MIN_REASON:
            raise AllowlistError(
                f"{where}: `reason` is {len(reason)} characters. It has to say "
                "why the address is legitimate here and what removes the "
                f"entry; at least {MIN_REASON} characters."
            )
        tracking = str(raw["tracking"])
        if not _TRACKING_RE.match(tracking):
            raise AllowlistError(
                f"{where}: `tracking` must be a wakir-labs pull or issue URL, "
                f"got {tracking!r}"
            )
        owner = str(raw["owner"]).strip()
        if not owner:
            raise AllowlistError(f"{where}: `owner` must be non-empty")

        entries.append(
            AllowlistEntry(
                path=str(raw["path"]),
                addresses=tuple(addresses),
                reason=reason,
                owner=owner,
                until=_parse_date(raw["until"], f"{where}.until"),
                tracking=tracking,
            )
        )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def tracked_files(root: Path) -> tuple[str, ...]:
    """Repo-relative paths of tracked files. The tree, never the history."""
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`git ls-files` failed in {root}: {proc.stderr.decode(errors='replace')}"
        )
    return tuple(p for p in proc.stdout.decode("utf-8").split("\0") if p)


def _is_probably_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def scan_file(root: Path, rel_path: str) -> list[Finding]:
    """Findings in one file. Unreadable or binary files yield nothing."""
    if Path(rel_path).suffix.lower() in BINARY_SUFFIXES:
        return []
    full = root / rel_path
    try:
        data = full.read_bytes()
    except (OSError, ValueError):
        return []
    if _is_probably_binary(data):
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule_name, pattern in _RULE_RES:
            for match in pattern.finditer(line):
                findings.append(
                    Finding(
                        path=rel_path,
                        line=lineno,
                        address=match.group(0),
                        rule=rule_name,
                    )
                )
    return findings


def scan_tree(root: Path, paths: tuple[str, ...] | None = None) -> tuple[Finding, ...]:
    """Every finding in the tracked tree, minus the three self-exclusions."""
    candidates = tracked_files(root) if paths is None else paths
    findings: list[Finding] = []
    for rel_path in candidates:
        if rel_path in SELF_EXCLUDED:
            continue
        findings.extend(scan_file(root, rel_path))
    return tuple(findings)


def evaluate(
    findings: tuple[Finding, ...],
    entries: tuple[AllowlistEntry, ...],
    today: dt.date,
    warn_days: int = WARN_DAYS,
) -> Report:
    """Split findings into violations and allowed, and age the entries.

    An expired entry does not stop covering its findings quietly -- it
    fails the gate in its own right (ADR-0075 §3). Otherwise the expiry
    date would just be a slower way of deleting the entry.
    """
    live = [entry for entry in entries if not entry.is_expired(today)]
    violations: list[Finding] = []
    allowed: list[Finding] = []
    used: set[int] = set()
    for finding in findings:
        covering = next(
            (index for index, entry in enumerate(live) if entry.covers(finding)),
            None,
        )
        if covering is None:
            violations.append(finding)
        else:
            allowed.append(finding)
            used.add(covering)

    expired = tuple(entry for entry in entries if entry.is_expired(today))
    warning = tuple(
        entry for entry in live if 0 <= entry.days_left(today) <= warn_days
    )
    unused = tuple(entry for index, entry in enumerate(live) if index not in used)
    return Report(
        findings=findings,
        violations=tuple(violations),
        allowed=tuple(allowed),
        expired=expired,
        warning=warning,
        unused=unused,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def failure_text(report: Report) -> str:
    """The message an engineer reads on the day the gate goes red."""
    lines: list[str] = []
    if report.violations:
        lines += [
            "private addresses in the working tree "
            f"({len(report.violations)} occurrence(s)):",
            "",
        ]
        lines += [f"  {finding.render()}" for finding in report.violations]
        lines += [
            "",
            "Not publishing the operator's network topology is a standing "
            "directive. These are non-routable, so this is hygiene rather "
            "than an incident -- but hygiene that is not enforced is how "
            "sixty of them accumulated over four months.",
            "",
            "Pick per site, not mechanically:",
            "  * A default in a script should not be a concrete address. "
            "Require the environment variable and abort loudly when it is "
            "missing -- and make the abort say what to set, because a "
            "script that silently stops working is worse than the address.",
            "  * A test fixture needs an address but not a real one. Use "
            "the RFC 5737 documentation ranges: 192.0.2.0/24, "
            "198.51.100.0/24, 203.0.113.0/24.",
            "  * A comment or an example needs only a placeholder.",
            "  * A historical report is a record. Redact it and say in the "
            "document that you did, with the date -- do not rewrite it "
            "silently.",
            "",
            "If an address genuinely has to stay, add it to "
            "tooling/ci/private-address-allowlist.json with a reason, an "
            "owner, an expiry date and a tracking link.",
        ]
    if report.expired:
        if lines:
            lines.append("")
        lines += [
            "expired allow-list entries (ADR-0075 §3): an entry whose date "
            "has passed fails this gate. It does not quietly stop applying.",
            "",
        ]
        for entry in report.expired:
            lines.append(
                f"  {entry.path}: until {entry.until} passed "
                f"{-entry.days_left(dt.date.today())} day(s) ago -- owner "
                f"{entry.owner}, tracked at {entry.tracking}"
            )
        lines += [
            "",
            "Either do the thing the date was for and delete the entry, or "
            "move the date in a reviewed diff that says why it is still "
            "true.",
        ]
    return "\n".join(lines)


def render_markdown(report: Report, today: dt.date) -> str:
    lines = [
        "## Private-address lint (RFC1918, working tree)",
        "",
        f"Evaluated against `{today.isoformat()}`. "
        f"{len(report.findings)} literal(s) found, "
        f"{len(report.violations)} not allow-listed.",
        "",
        "Scans the tracked tree only. The git history is out of scope by "
        "decision, so a green run says nothing about what is in the log.",
        "",
    ]
    if report.violations:
        lines += ["| file | line | address | rule |", "|---|---:|---|---|"]
        lines += [
            f"| `{f.path}` | {f.line} | `{f.address}` | {f.rule} |"
            for f in report.violations
        ]
        lines.append("")
    else:
        lines += ["No un-allow-listed private addresses in the tree.", ""]

    if report.expired:
        lines += ["**Expired allow-list entries — this gate is red.**", ""]
        lines += [
            f"- `{e.path}` → {e.until} ({e.owner})" for e in report.expired
        ]
        lines.append("")
    if report.warning:
        lines += [
            f"**Within the warning window** (`until − {WARN_DAYS}` days). "
            "Nothing is failing yet:",
            "",
        ]
        lines += [
            f"- `{e.path}` → {e.until} ({e.owner})" for e in report.warning
        ]
        lines.append("")
    if report.unused:
        lines += [
            "**Allow-list entries that matched nothing.** The address they "
            "cover is gone; delete them:",
            "",
        ]
        lines += [f"- `{e.path}` ({e.owner})" for e in report.unused]
        lines.append("")
    return "\n".join(lines) + "\n"


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RFC1918 lint for the working tree")
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero on a finding"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="write the markdown table to $GITHUB_STEP_SUMMARY (or stdout)",
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--allowlist", default=str(ALLOWLIST_PATH))
    args = parser.parse_args(argv)

    # Deliberately no `--today` override, for the reason given in
    # tooling/ci/exemption_expiry.py: a flag that moves the calendar is a
    # flag that turns the expiry check off, and it would be used on
    # exactly the day it should not be. Tests inject a date through
    # `evaluate(...)`, which no workflow can reach.
    today = dt.date.today()
    root = Path(args.root).resolve()

    try:
        entries = load_allowlist(Path(args.allowlist))
    except AllowlistError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = evaluate(scan_tree(root), entries, today)

    if args.summary:
        table = render_markdown(report, today)
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(table)
        else:
            sys.stdout.write(table)

    if args.check:
        if not report.ok:
            print(failure_text(report), file=sys.stderr)
            return 1
        print(
            f"private-address lint ok on {today}: "
            f"{len(report.findings)} literal(s), all allow-listed "
            f"({len(entries)} entry/entries, {len(report.warning)} in the "
            "warning window)"
        )
    elif not args.summary:
        sys.stdout.write(render_markdown(report, today))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
