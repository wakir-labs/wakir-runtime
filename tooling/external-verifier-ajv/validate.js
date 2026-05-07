// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// External-verifier validator for wakir-wat-manifest-v1.
//
// Runs the same set of test-vectors that the Python jsonschema-side
// validator runs (see scripts/external_verifier_validation.py and
// tests/wat/test_manifest_v1_schema_smoke.py) under Node.js + ajv.
// Prints a JSON report to stdout describing each vector's verdict.
//
// Cross-tool parity is the contract: every vector's verdict here
// (accept / reject) must equal the Python-side verdict. Any drift is a
// schema-correctness bug, not an implementation peculiarity.
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
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

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
const vectorsPath = resolve(__dirname, args.vectors || "test-vectors.json");

const schema = loadJson(schemaPath);
const vectors = loadJson(vectorsPath);

if (!Array.isArray(vectors)) {
  fail(
    `vectors file ${vectorsPath} must be a JSON array of {name, expect, manifest}`,
    2,
  );
}

const ajv = new Ajv2020({
  strict: false,
  allErrors: true,
});
addFormats(ajv);

let validate;
try {
  validate = ajv.compile(schema);
} catch (err) {
  fail(`schema compile failure: ${err.message}`, 2);
}

const report = {
  tool: "ajv",
  ajv_version: "2020",
  schema_id: schema.$id || null,
  total: vectors.length,
  matched: 0,
  mismatched: 0,
  results: [],
};

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

  const ok = validate(manifest);
  const verdict = ok ? "accept" : "reject";
  const matched = verdict === expect;

  if (matched) {
    report.matched += 1;
  } else {
    report.mismatched += 1;
  }

  const errors = validate.errors
    ? validate.errors.map((e) => ({
        instancePath: e.instancePath,
        keyword: e.keyword,
        message: e.message,
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
