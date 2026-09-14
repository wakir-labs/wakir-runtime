<!--
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
SPDX-License-Identifier: CC-BY-4.0
-->

# Offline verification by a third party

Status: current as of 2026-09-14 (ADR-0074).

If you want to check a Wakir Audit Trail anchor **without operating any
Wakir-controlled runtime**, use the standalone Apache-2.0 package:

**<https://github.com/wakir-labs/wakir-verify>**

This repository no longer ships an in-tree offline verifier. A copy used
to live at `wat/anchor/external_verifier/` and was exposed as the console
script `wat-verify`; ADR-0074 removed it. It had drifted out of sync with
the maintained implementation and returned positive verdicts on inputs it
should have rejected. One implementation, one place for the next fix.

## What `wakir-verify` actually tells you

It reports four distinct things, and it is worth reading them separately —
a "pass" on one is not a "pass" on another:

* **Hashlist consistency** — the manifest's own event hashes reduce to the
  Merkle root the manifest claims. This is a statement about the file's
  internal arithmetic and nothing else.
* **Event binding** — a named event is actually a leaf under that root, via
  the inclusion proof supplied with it. Without this, a consistent hashlist
  says nothing about *your* event.
* **Payload** — the bytes you hold hash to the `payload_hash` recorded for
  that event. This is the step that connects the trail to a document you
  can read.
* **Root authenticity** — the OpenTimestamps receipt attests *this* root,
  and the attested Bitcoin block Merkle root matches a block header you
  supply. Offline and without a block header, the honest verdict is
  `not_checked`, and the tool says so rather than claiming a pass.

A receipt that has not yet been upgraded past the calendar stage carries no
Bitcoin attestation at all. `wakir-verify` reports `structural_ok` for it —
"un-upgraded", not "verified" and not "bad".

## What it does *not* tell you

The removed copy's README claimed that a tampered receipt "would have to
fool four independently-maintained verifiers in the same direction". That
claim did not hold: three of the four probes never compared the root they
were handed, so a tampered input only had to satisfy checks that were not
looking. Treat any surviving copy of that wording as withdrawn.

Independent probes are worth running — the value is in seeing *where* two
sources disagree, not in counting votes. A quorum of checks that do not
bind the root is not evidence.

## Installing

`wakir-verify` is installed from git until a wheel is published
(ADR-0073 stage E):

```sh
pip install 'git+https://github.com/wakir-labs/wakir-verify@main'
wakir-verify --help
```

Operators of this runtime who want the local, BUSL-1.1 convenience
verifier — which reads the per-hour manifest archive directory and is a
different contract — want `wakir-wat-verify` instead; see the root
[`README.md`](../README.md).
