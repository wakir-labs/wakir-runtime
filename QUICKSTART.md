# Quickstart — verify the proof path yourself

This repository makes one claim: an event that an agent produced can
be turned into a record that a third party can check, years later,
without trusting us. This page is the shortest path to testing that
claim on your own machine.

One command drives the whole chain. A protocol event is materialised
as a canonical Wirelang frame, pushed through the runtime bridge into
the WAT spool, aggregated into an hourly Merkle manifest, and reduced
to an inclusion proof for that single event. Then the proof is handed
to `wakir-verify` — a separate repository, separate Apache-2.0
codebase, no shared code with the runtime — which re-derives the
Merkle root with its own implementation and re-checks the proof. What
you get back is one JSON report with one record per step. Nothing in
it has to be believed: `proof.json` contains the sibling hashes with
their side markers, so you can recompute the root yourself with plain
SHA-256 and no Wakir code at all.

## Prerequisites

- **Python ≥ 3.11** (`requires-python` in `pyproject.toml`). Measured
  below on CPython 3.13.15.
- **`bash`** and **`git`**. `make` is convenience only —
  `bash scripts/demo-proof.sh` is exactly what `make demo-proof` runs.
- **Network** only for cloning and for the one `pip install` below.
  The proof path itself is hermetic: no network call, no Bitcoin
  lookup, no API key, no daemon, no container.
- **No `jq`**, no Node, no Rust toolchain, no build tools. The driver
  is bash plus `python3` from the standard library.

A minimal image such as `python:3.13-slim` ships neither `git` nor
`make`; install them first:

```sh
apt-get update && apt-get install -y --no-install-recommends git make
```

## Three commands

```sh
# 1. get the code
git clone --depth=1 https://github.com/wakir-labs/wakir-runtime.git
cd wakir-runtime

# 2. install the independent verifier (the only install the proof
#    path needs; without it step 5 reports `skipped`, see below)
pip install "git+https://github.com/wakir-labs/wakir-verify@main"

# 3. run the chain — the report goes to stdout
make demo-proof
```

To keep the artefacts (spool file, manifest, `proof.json`, report)
instead of a throwaway tmpdir, pin the working directory:

```sh
DEMO_PROOF_WORKDIR=/tmp/wakir-demo make demo-proof
ls /tmp/wakir-demo
```

The run is deterministic: the hour slot is pinned, so the Merkle root
is byte-identical on every machine. If yours differs from the root in
someone else's report for the same commit, that is a finding, not
noise.

## Reading the report

The report has the shape `{schema, hour, workdir, commits, steps[],
exit_code}` with exactly five step records, always all five, always in
this order:

| # | Step | What it proves | Artefact |
|---|------|----------------|----------|
| 1 | `protocol_event` | a canonical event exists with the four consensus fields (`event_id`, `time`, `payload_hash`, `capability_token_hash`) | `event.json` |
| 2 | `runtime_bridge` | the event reached both sinks — WAT spool and activity log — under the atomicity contract | `spool/…jsonl` |
| 3 | `merkle_manifest` | the hour's events aggregate to one Merkle root | `<hour>/manifest.json` |
| 4 | `inclusion_proof` | this event is in that root, with recomputable sibling hashes | `proof.json` |
| 5 | `external_verify` | an independent implementation agrees — root re-derived, proof re-checked | `verify-result.json` |

Each step carries a `status` and an `exit_code`:

- `ok` (0) — the step ran and its assertion held.
- `skipped` (20) — the step could not run and says why in
  `details.reason`. It is never omitted and never faked as `ok`.
- `failed` (10) — the assertion did not hold.
- `not_run` (30) — a step upstream failed, so this one was not
  attempted.

The process exits `0` when no step failed (a `skipped` step still
exits `0`) and `10` when a step failed.

**Why `external_verify` may say `skipped`.** The cross-repo leg
imports `wakir_verify` from the active Python environment. On a fresh
clone without the verifier installed, the step reports
`reason: wakir_verify not importable …` — the interesting half of the
claim, an outside check, is then simply missing. Command 2 above is
what turns it into `ok`; if you skipped it, run it now and re-run
`make demo-proof`. The steps 1–4 report is genuine either way, but
only a run with all five `ok` demonstrates the full claim.

For a machine-readable pass/fail instead of reading JSON by eye, use
the same validator the CI gate uses:

```sh
python scripts/ci/validate_demo_proof_report.py \
  /tmp/wakir-demo/demo-report.json --require-external-verify-ok
```

It exits `0` only when the schema matches, all five steps are present
in order, none failed, and `external_verify` is `ok`.

## Measured on a bare container

Reproduced in a bare `python:3.13-slim` container (Debian trixie,
x86_64), from `git clone` to a report with five `ok` steps:

| Step | Wall clock |
|---|---|
| `apt-get install git make` (image bootstrap, not part of the path) | 6.5 s |
| `git clone --depth=1` | 2.1 s |
| `make demo-proof`, nothing installed → 4 × `ok`, `external_verify: skipped` | 0.7 s |
| `pip install git+…/wakir-verify` | 266.2 s |
| `make demo-proof` → 5 × `ok` | 0.6 s |
| **clone → verified report** | **269.7 s (4 min 30 s)** |

**Four and a half minutes, and 99 % of it is `pip` fetching the
verifier over the network.** That one step varied between 124 s and
266 s across four runs on the same connection; it is the only part of
the path that can push you towards the ten-minute mark, and it is not
our code. The evidence chain itself runs in under a second.

The Merkle root was byte-identical across all four runs, installed or
not, so skipping the editable install is not a lesser variant of the CI
run — it is the same computation.

You do not need `pip install -e .` for the proof path; the driver puts
the repository root on `sys.path` itself. Install the runtime the
regular way (see [Setup](README.md#setup)) when you want the console
scripts (`wakir-merkle`, `wakir-anchor`, `wakir-wat-verify`) or intend
to develop against the code.

## Where to go next

- [`docs/architecture/layers.md`](docs/architecture/layers.md) — how
  the layers fit together and which repository owns what.
- [`STABILITY.md`](STABILITY.md) — which surfaces are stable, which
  are experimental, and which are internal. Read this before you build
  on anything.
- [README, one-command proof demo](README.md#one-command-proof-demo-make-demo-proof)
  — the same five steps in more detail, plus the environment overrides
  including online mode against a real OpenTimestamps receipt.
- [`docs/operations/demo-proof-runbook.md`](docs/operations/demo-proof-runbook.md)
  — the operator walkthrough, including failure diagnosis.
- [`wakir-protocol`](https://github.com/wakir-labs/wakir-protocol) —
  the wire formats; [`wakir-verify`](https://github.com/wakir-labs/wakir-verify)
  — the independent checker you installed in command 2.
