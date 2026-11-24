// Mocha entry point loaded by VS Code's extension test host.
import { readdirSync } from "node:fs";
import * as path from "node:path";

import Mocha from "mocha";

export function run(): Promise<void> {
  const mocha = new Mocha({ ui: "bdd", color: true, timeout: 20_000 });
  for (const file of readdirSync(__dirname)
    .filter((f) => f.endsWith(".test.js"))
    .sort()) {
    mocha.addFile(path.join(__dirname, file));
  }
  return new Promise((resolve, reject) => {
    mocha.run((failures) => {
      if (failures > 0) {
        reject(new Error(`${failures} test(s) failed`));
      } else {
        resolve();
      }
    });
  });
}
