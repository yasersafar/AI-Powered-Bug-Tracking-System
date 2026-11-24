// Downloads a VS Code build (cached in .vscode-test/) and runs the mocha suites inside it.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";

import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, "..");
  const extensionTestsPath = path.resolve(__dirname, "suite", "index.js");
  const userDataDir = mkdtempSync(path.join(tmpdir(), "bugtracker-test-"));
  await runTests({
    version: process.env.VSCODE_TEST_VERSION ?? "stable",
    extensionDevelopmentPath,
    extensionTestsPath,
    // Opt-in end-to-end run against a real backend (see test/suite/e2e.test.ts).
    extensionTestsEnv: {
      E2E_SERVER_URL: process.env.E2E_SERVER_URL ?? "",
      E2E_PASSWORD: process.env.E2E_PASSWORD ?? "",
    },
    launchArgs: [
      "--disable-extensions",
      "--disable-workspace-trust",
      "--skip-welcome",
      "--skip-release-notes",
      // Secrets stay in memory: no OS keychain prompt during tests.
      "--use-inmemory-secretstorage",
      `--user-data-dir=${userDataDir}`,
    ],
  });
}

main().catch((error: unknown) => {
  console.error("Extension tests failed:", error);
  process.exit(1);
});
