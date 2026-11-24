// End-to-end against the real, seeded backend (`make up && make seed`). Skipped unless
// E2E_SERVER_URL and E2E_PASSWORD (the SEED_PASSWORD from .env) are set:
//   E2E_SERVER_URL=http://localhost:8000 E2E_PASSWORD=... npm test
// It creates bugs, comments and attachments in that database; run `make seed-reset` before and
// after. It logs in 6 times; the API allows 10 logins per minute per address (HTTP 429 above).
import * as assert from "node:assert/strict";

import * as vscode from "vscode";

import { ApiClient } from "../../src/api/client";
import type { Bug } from "../../src/api/types";
import type { BugTrackerApi } from "../../src/extension";

const SERVER = process.env.E2E_SERVER_URL ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";

function clientFor(): { api: ApiClient; login: (email: string) => Promise<void> } {
  let token: string | undefined;
  const api = new ApiClient({ baseUrl: () => SERVER, token: () => Promise.resolve(token) });
  return {
    api,
    login: async (email: string) => {
      token = (await api.login(email, PASSWORD)).access_token;
    },
  };
}

function webviewTitles(): string[] {
  return vscode.window.tabGroups.all
    .flatMap((g) => g.tabs)
    .filter((t) => t.input instanceof vscode.TabInputWebview)
    .map((t) => t.label);
}

async function waitFor(check: () => boolean, timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!check()) {
    if (Date.now() > deadline) {
      throw new Error(`timed out; open webviews: ${webviewTitles().join(", ")}`);
    }
    await new Promise((r) => setTimeout(r, 100));
  }
}

(SERVER && PASSWORD ? describe : describe.skip)("end-to-end with the seeded backend", function () {
  this.timeout(60_000);
  const reporter = clientFor();
  const manager = clientFor();
  const developer = clientFor();
  const admin = clientFor();
  let bug: Bug;
  let ext: BugTrackerApi;

  before(async () => {
    await Promise.all([
      reporter.login("rita@example.com"),
      manager.login("pm@example.com"),
      developer.login("dana@example.com"),
      admin.login("admin@example.com"),
    ]);
    await vscode.workspace
      .getConfiguration("bugTracker")
      .update("serverUrl", SERVER, vscode.ConfigurationTarget.Global);
    const extension = vscode.extensions.getExtension<BugTrackerApi>("aau-capstone.ai-bug-tracker");
    assert.ok(extension);
    ext = await extension.activate();
  });

  after(async () => {
    await vscode.commands.executeCommand("workbench.action.closeAllEditors");
    await ext.session.clear();
  });

  it("checks duplicates while typing and submits with AI triage", async () => {
    const projects = await reporter.api.projects();
    const payments = projects.find((p) => p.name === "Payments Platform");
    assert.ok(payments);
    const original = (
      await reporter.api.searchBugs({ project_id: payments.id, sort: "created_asc" })
    ).items[0];
    assert.ok(original);
    const draft = await reporter.api.bug(original.id);
    const dup = await reporter.api.duplicates(payments.id, draft.title, draft.description);
    assert.equal(dup.ai_status, "ok");
    assert.equal(dup.duplicates[0]?.bug_id, original.id);

    bug = await reporter.api.createBug({
      project_id: payments.id,
      title: "E2E: refund endpoint returns 500 again",
      description: `${draft.description} (seen again during the end-to-end test)`,
      steps_to_reproduce: "1. Refund a partially captured payment",
      environment: "E2E test",
      components: draft.components,
    });
    assert.notEqual(bug.severity, "Unclassified");
    assert.equal(bug.ai_status, "ok");
    assert.ok(bug.recommended_developers.length > 0);
    assert.ok(bug.recommended_developers.every((r) => r.reason.length > 0));
    assert.ok(bug.duplicate_candidates.some((c) => c.bug_id === original.id));
  });

  it("assigns, works through the lifecycle, comments and attaches", async () => {
    const dana = bug.recommended_developers.find((r) => r.name.startsWith("Dana"));
    assert.ok(dana, "Dana is recommended (she fixed the original)");
    let current = await manager.api.assign(bug.id, dana.developer_id);
    assert.equal(current.assignee?.id, dana.developer_id);
    assert.equal(current.status, "InProgress"); // assigning an Open bug starts the work
    current = await developer.api.bug(bug.id);
    assert.deepEqual(current.allowed_transitions, ["Resolved"]);
    await developer.api.addComment(bug.id, "Looking into it from the extension e2e test.");
    await developer.api.uploadAttachment(
      bug.id,
      "trace.txt",
      new TextEncoder().encode("Traceback: refund 500\n"),
    );
    current = await developer.api.transition(bug.id, "Resolved");
    assert.equal(current.status, "Resolved");
    const [comments, attachments, audit] = await Promise.all([
      reporter.api.comments(bug.id),
      reporter.api.attachments(bug.id),
      reporter.api.audit(bug.id),
    ]);
    assert.equal(comments.length, 1);
    assert.equal(attachments[0]?.original_filename, "trace.txt");
    const downloaded = await reporter.api.downloadAttachment(attachments[0].id);
    assert.equal(new TextDecoder().decode(downloaded), "Traceback: refund 500\n");
    assert.ok(audit.some((e) => e.action === "status_changed" && e.new_value === "Resolved"));
    const notes = await developer.api.notifications(true);
    assert.ok(notes.items.some((n) => n.bug_id === bug.id && n.kind === "assigned"));
  });

  it("admin sees profiles, stats and settings", async () => {
    const [profiles, stats, settings] = await Promise.all([
      admin.api.profiles(),
      admin.api.developerStats(),
      admin.api.settings(),
    ]);
    assert.ok(profiles.some((p) => p.is_cold_start && p.resolved_count === 0));
    assert.ok(stats.length >= profiles.length);
    assert.ok(settings.some((s) => s.key === "ai_enabled"));
  });

  it("renders every webview with real data in the extension", async () => {
    await ext.session.login("pm@example.com", PASSWORD);
    await vscode.commands.executeCommand("bugTracker.openBugById", bug.id);
    await waitFor(() => webviewTitles().some((t) => t.startsWith(`#${bug.id} `)));
    await vscode.commands.executeCommand("bugTracker.openDashboard");
    await waitFor(() => webviewTitles().some((t) => t.startsWith("Dashboard: ")));
    await vscode.commands.executeCommand("bugTracker.reportBug");
    await waitFor(() => webviewTitles().includes("Report Bug"));
    await ext.session.login("admin@example.com", PASSWORD);
    await vscode.commands.executeCommand("bugTracker.adminProfiles");
    await waitFor(() => webviewTitles().includes("Admin: Developers"));
  });
});
