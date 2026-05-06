/**
 * CI drift check: regenerate types/api.ts from the OpenAPI schema and compare
 * them to the committed file. Exits with code 1 if they differ so CI fails.
 *
 * Usage:
 *   node scripts/check_types_drift.mjs        # from the frontend/ directory
 *   npm run check:types-drift
 *
 * How it works:
 *   1. Run openapi-typescript into a temp file next to the committed one.
 *   2. Diff the two files (ignoring trailing whitespace).
 *   3. If there's a diff, print it and exit 1.
 *   4. Clean up the temp file on exit.
 */

import { execSync } from "node:child_process";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SCHEMA_PATH = "../../shared/openapi/openapi.json";
const COMMITTED_TYPES = "src/types/api.ts";
const TMP_TYPES = join(tmpdir(), `api_types_drift_check_${process.pid}.ts`);

function cleanup() {
  if (existsSync(TMP_TYPES)) {
    try {
      unlinkSync(TMP_TYPES);
    } catch {
      /* ignore */
    }
  }
}

process.on("exit", cleanup);
process.on("SIGINT", () => { cleanup(); process.exit(130); });

if (!existsSync(COMMITTED_TYPES)) {
  console.error(
    `❌  ${COMMITTED_TYPES} does not exist.\n` +
    `    Run \`npm run generate:types\` and commit the result.`
  );
  process.exit(1);
}

try {
  execSync(
    `npx openapi-typescript ${SCHEMA_PATH} -o ${TMP_TYPES}`,
    { stdio: "pipe" }
  );
} catch (err) {
  console.error("❌  openapi-typescript failed:\n", err.stderr?.toString());
  process.exit(1);
}

const committed = readFileSync(COMMITTED_TYPES, "utf8").replace(/\r\n/g, "\n").trimEnd();
const fresh = readFileSync(TMP_TYPES, "utf8").replace(/\r\n/g, "\n").trimEnd();

if (committed === fresh) {
  console.log("✅  src/types/api.ts is in sync with the OpenAPI schema.");
  process.exit(0);
}

// Print a compact unified-style diff so CI logs show exactly what drifted.
console.error(
  "❌  src/types/api.ts is out of sync with shared/openapi/openapi.json.\n" +
  "    Run `npm run generate:types` and commit the updated file.\n"
);

const committedLines = committed.split("\n");
const freshLines = fresh.split("\n");
const maxLines = Math.max(committedLines.length, freshLines.length);
let diffCount = 0;
for (let i = 0; i < maxLines && diffCount < 30; i++) {
  const a = committedLines[i] ?? "(missing)";
  const b = freshLines[i] ?? "(missing)";
  if (a !== b) {
    console.error(`  line ${i + 1}:`);
    console.error(`  - ${a}`);
    console.error(`  + ${b}`);
    diffCount++;
  }
}
if (diffCount === 30) {
  console.error("  … (truncated — run generate:types locally for the full diff)");
}

process.exit(1);
