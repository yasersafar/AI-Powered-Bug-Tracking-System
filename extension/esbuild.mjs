// Bundles the extension host code into dist/extension.js (CommonJS, as VS Code expects).
// `--tests` bundles the test runner and suites into out-test/ (used by `npm test`).
import { readdirSync } from "node:fs";

import * as esbuild from "esbuild";

const production = process.argv.includes("--production");
const watch = process.argv.includes("--watch");
const tests = process.argv.includes("--tests");
const preview = process.argv.includes("--preview");

const common = {
  bundle: true,
  format: "cjs",
  platform: "node",
  target: "node20",
  external: ["vscode"],
  logLevel: "info",
};

const options = preview
  ? {
      // Static webview previews: the real panels with `vscode` replaced by a small stub.
      ...common,
      entryPoints: ["test/preview/render.ts"],
      outfile: "out-test/preview/render.js",
      external: [],
      alias: { vscode: "./test/preview/vscodeStub.ts" },
    }
  : tests
    ? {
        ...common,
        entryPoints: [
          "test/runTest.ts",
          "test/suite/index.ts",
          ...readdirSync("test/suite")
            .filter((f) => f.endsWith(".test.ts"))
            .map((f) => `test/suite/${f}`),
        ],
        outdir: "out-test",
        outbase: "test",
        external: ["vscode", "mocha", "@vscode/test-electron"],
        sourcemap: true,
      }
    : {
        ...common,
        entryPoints: ["src/extension.ts"],
        outfile: "dist/extension.js",
        sourcemap: !production,
        minify: production,
      };

const context = await esbuild.context(options);
if (watch) {
  await context.watch();
} else {
  await context.rebuild();
  await context.dispose();
}
