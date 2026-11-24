// Runs inside VS Code: activation, contributed commands, login and webviews.
import * as assert from "node:assert/strict";

import * as vscode from "vscode";

import type { BugTrackerApi } from "../../src/extension";
import { MockServer, standardBackend } from "../mockServer";

const EXTENSION_ID = "aau-capstone.ai-bug-tracker";

const COMMANDS = [
  "bugTracker.login",
  "bugTracker.logout",
  "bugTracker.register",
  "bugTracker.reportBug",
  "bugTracker.openBug",
  "bugTracker.openBugById",
  "bugTracker.searchBugs",
  "bugTracker.openDashboard",
  "bugTracker.adminProfiles",
  "bugTracker.myProfile",
  "bugTracker.setServerUrl",
  "bugTracker.checkConnection",
  "bugTracker.refresh",
  "bugTracker.markAllNotificationsRead",
];

async function waitFor(check: () => boolean, timeoutMs = 5000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!check()) {
    if (Date.now() > deadline) {
      throw new Error("condition not met in time");
    }
    await new Promise((r) => setTimeout(r, 50));
  }
}

function webviewTabs(): vscode.Tab[] {
  return vscode.window.tabGroups.all
    .flatMap((g) => g.tabs)
    .filter((t) => t.input instanceof vscode.TabInputWebview);
}

describe("extension", function () {
  this.timeout(30_000);
  const server = standardBackend(new MockServer());
  let api: BugTrackerApi;

  before(async () => {
    await server.start();
    await vscode.workspace
      .getConfiguration("bugTracker")
      .update("serverUrl", server.url, vscode.ConfigurationTarget.Global);
    const extension = vscode.extensions.getExtension<BugTrackerApi>(EXTENSION_ID);
    assert.ok(extension, "extension is installed in the test host");
    api = await extension.activate();
  });

  after(async () => {
    await vscode.commands.executeCommand("workbench.action.closeAllEditors");
    await api.session.clear();
    await server.stop();
  });

  it("activates and registers every command", async () => {
    const all = await vscode.commands.getCommands(true);
    for (const command of COMMANDS) {
      assert.ok(all.includes(command), `${command} is registered`);
    }
  });

  it("checks the server health on start", async () => {
    await vscode.commands.executeCommand("bugTracker.checkConnection");
    assert.deepEqual(api.connection(), { kind: "online", version: "test" });
    assert.ok(server.requests.some((r) => r.path === "/health"));
  });

  it("logs in, stores the token only in SecretStorage, and restores the session", async () => {
    await api.session.login("rita@example.com", "Passw0rd!");
    assert.equal(api.session.currentUser?.email, "rita@example.com");
    const settings = JSON.stringify(vscode.workspace.getConfiguration("bugTracker"));
    assert.ok(!settings.includes("token-abc"), "token is not in the settings");
    await api.session.restore();
    assert.equal(api.session.currentUser.full_name, "Rita Reporter");
    const me = server.last("/api/v1/users/me");
    assert.ok(me);
    assert.equal(me.headers.authorization, "Bearer token-abc");
  });

  it("rejects wrong credentials with the server's message", async () => {
    await assert.rejects(
      api.session.login("rita@example.com", "wrong"),
      /Invalid email or password/,
    );
  });

  it("opens the Report Bug webview and runs the duplicate check", async () => {
    await api.session.login("rita@example.com", "Passw0rd!");
    await vscode.commands.executeCommand("bugTracker.reportBug");
    await waitFor(() => webviewTabs().some((t) => t.label === "Report Bug"));
    // The webview's debounced call reaches the API through the extension host.
    const result = await api.session.api.duplicates(1, "Card declined", "crash when paying");
    assert.equal(result.duplicates[0]?.bug_id, 11);
  });

  it("opens a bug detail webview", async () => {
    await vscode.commands.executeCommand("bugTracker.openBugById", 11);
    await waitFor(() => webviewTabs().some((t) => t.label.startsWith("#11 ")));
    assert.ok(server.requests.some((r) => r.path === "/api/v1/bugs/11/audit"));
  });

  it("opens the dashboard webview", async () => {
    server.on("GET", "/api/v1/projects/1/dashboard", () => ({
      json: {
        project_id: 1,
        total_bugs: 1,
        open_bugs: 1,
        open_critical: 0,
        by_status: { Open: 1 },
        by_severity: { High: 1 },
        over_time: [{ day: "2026-11-20", created: 1, resolved: 0 }],
        average_resolution_hours: null,
        top_components: [],
        days: 30,
      },
    }));
    await vscode.commands.executeCommand("bugTracker.openDashboard");
    await waitFor(() => webviewTabs().some((t) => t.label.startsWith("Dashboard")));
  });

  it("refuses the admin panel for non-administrators", async () => {
    await vscode.commands.executeCommand("bugTracker.adminProfiles");
    assert.ok(!webviewTabs().some((t) => t.label.startsWith("Admin")));
  });

  it("shows the offline state when the server goes away", async () => {
    await server.stop();
    await vscode.commands.executeCommand("bugTracker.checkConnection");
    assert.equal(api.connection()?.kind, "offline");
    await server.start();
    await vscode.workspace
      .getConfiguration("bugTracker")
      .update("serverUrl", server.url, vscode.ConfigurationTarget.Global);
  });

  it("logs out and forgets the session", async () => {
    await vscode.commands.executeCommand("bugTracker.logout");
    assert.equal(api.session.currentUser, undefined);
  });
});
