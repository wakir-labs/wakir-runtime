// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// External-verifier fourth-pole validator for wakir-wat-manifest-v1.
//
// Runs the same set of test-vectors as the three existing poles
// (python-jsonschema, ajv, python-fastjsonschema) under Node.js +
// @hyperjump/json-schema. Prints a JSON report to stdout describing
// each vector's verdict.
//
// Why a fourth pole, and why Hyperjump:
//
//   The first three poles cover Python (jsonschema + fastjsonschema)
//   and one JS implementation (ajv, Ben McMahen). Cross-tool parity
//   means little if every implementation cribbed from the same
//   ancestor; the real witness is independent re-implementation of
//   the spec. Hyperjump (Jason Desrosiers) is a separately-maintained
//   pure-JS Draft-2020-12 implementation listed as a reference in the
//   JSON-Schema-Org's own conformance tracking; it is NOT a fork of
//   ajv. A drift between ajv and Hyperjump on the same test-vector
//   set therefore reveals a real schema-side ambiguity, not a
//   shared-implementation peculiarity.
//
//   Sprint-6 Tag-6 wanted a Rust/Go/Java pole for second-language-
//   family witness. None of those toolchains are present on this
//   sandbox host (no go, cargo, rustc, java), and the sandbox is not
//   permitted to install system packages. Hyperjump-as-fourth-pole
//   preserves cross-library witness substance without forcing an
//   operator-side toolchain bootstrap and is documented as a
//   pragmatic substitution in docs/external-verifier-conformance.md
//   §7; a real second-language-family pole remains open as a Phase-
//   1c / operator-host follow-up.
//
// Usage:
//
//   node validate.js \
//     --schema=../../wirelang/schemas/wakir-wat-manifest-v1.json \
//     --vectors=test-vectors.json
//
// Exit codes:
//
//   0  All vectors produced the expected verdict.
//   1  At least one vector mismatched its expected verdict.
//   2  CLI / file-loading error (schema or vectors unreadable).

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  registerSchema,
  validate,
  setShouldValidateSchema,
} from "@hyperjump/json-schema/draft-2020-12";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function parseArgs(argv) {
  const out = {};
  for (const arg of argv.slice(2)) {
    const m = arg.match(/^--([^=]+)=(.+)$/);
    if (m) out[m[1]] = m[2];
  }
  return out;
}

function fail(msg, code) {
  process.stderr.write(`error: ${msg}\n`);
  process.exit(code);
}

function loadJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch (err) {
    fail(`cannot load JSON from ${path}: ${err.message}`, 2);
  }
}

const args = parseArgs(process.argv);
const schemaPath = resolve(
  __dirname,
  args.schema || "../../wirelang/schemas/wakir-wat-manifest-v1.json",
);
// Default vectors live in the AJV sibling tool; using the same file
// is the entire point of cross-tool parity. The driver does not
// maintain its own vector copy.
const vectorsPath = resolve(
  __dirname,
  args.vectors || "../external-verifier-ajv/test-vectors.json",
);

const schema = loadJson(schemaPath);
const vectors = loadJson(vectorsPath);

if (!Array.isArray(vectors)) {
  fail(
    `vectors file ${vectorsPath} must be a JSON array of {name, expect, manifest}`,
    2,
  );
}

// Hyperjump validates the schema itself against the dialect meta-
// schema on registerSchema; this is enabled by default and we keep
// it on because a malformed schema is itself a parity-relevant fact
// we want the driver to surface.
setShouldValidateSchema(true);

// Hyperjump uses retrieval URIs (RFC 3986 absolute URIs) as schema
// keys. The wakir manifest schema carries its own $id, but if a
// caller passes a schema without one we synthesize a stable opaque
// URI so registerSchema does not throw.
const schemaUri =
  schema.$id || "urn:wakir:external-verifier-hyperjump:anonymous-schema";

try {
  registerSchema(schema, schemaUri);
} catch (err) {
  fail(`schema register failure: ${err.message}`, 2);
}

const report = {
  tool: "hyperjump",
  hyperjump_dialect: "draft-2020-12",
  schema_id: schema.$id || null,
  total: vectors.length,
  matched: 0,
  mismatched: 0,
  results: [],
};

// Hyperjump's validate() is async (it follows $ref / $dynamicRef
// across network/file fetchers under the hood). Compiling once and
// reusing per-vector is the production pattern.
const validator = await validate(schemaUri);

for (const v of vectors) {
  if (!v || typeof v !== "object") {
    fail("each vector must be an object {name, expect, manifest}", 2);
  }
  const name = v.name || "<unnamed>";
  const expect = v.expect; // "accept" | "reject"
  const manifest = v.manifest;

  if (expect !== "accept" && expect !== "reject") {
    fail(`vector "${name}": expect must be "accept" or "reject"`, 2);
  }

  // BASIC output gives us per-error annotation; FLAG would be just
  // a boolean. BASIC matches the shape ajv emits in `validate.errors`.
  const output = validator(manifest, "BASIC");
  const verdict = output.valid ? "accept" : "reject";
  const matched = verdict === expect;

  if (matched) {
    report.matched += 1;
  } else {
    report.mismatched += 1;
  }

  const errors = !output.valid && Array.isArray(output.errors)
    ? output.errors.map((e) => ({
        // Hyperjump uses instanceLocation (JSON Pointer) where ajv uses
        // instancePath. Same RFC 6901 syntax; renamed to instancePath
        // in the rendered report so the parity comparator sees an
        // identical shape across all four poles.
        instancePath: e.instanceLocation || "",
        keyword: e.keyword || "<unknown>",
        message: e.absoluteKeywordLocation || "",
      }))
    : [];

  report.results.push({
    name,
    expect,
    verdict,
    matched,
    errors,
  });
}

process.stdout.write(JSON.stringify(report, null, 2) + "\n");
process.exit(report.mismatched === 0 ? 0 : 1);
