// Renders the real webview panels with data from a running, seeded backend into static HTML
// files (extension/out-preview/) for a visual and automated accessibility check.
//   PREVIEW_SERVER_URL=http://localhost:8000 PREVIEW_PASSWORD=<SEED_PASSWORD> node out-test/preview/render.js
// Submits two demo bugs (one with AI switched off); run `make seed-reset` afterwards.
import { mkdirSync, writeFileSync } from "node:fs";
import * as path from "node:path";
import { pathToFileURL } from "node:url";

import { ApiClient } from "../../src/api/client";
import type { Session } from "../../src/session";
import { AdminPanel } from "../../src/webview/admin";
import { BugPanel } from "../../src/webview/bugDetail";
import { DashboardPanel } from "../../src/webview/dashboard";
import type { PanelContext } from "../../src/webview/panel";
import { ReportBugPanel } from "../../src/webview/reportBug";
import { Uri, panels } from "./vscodeStub";

const SERVER = process.env.PREVIEW_SERVER_URL ?? "http://localhost:8000";
const PASSWORD = process.env.PREVIEW_PASSWORD ?? "";
const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "out-preview");

async function context(email: string): Promise<{ ctx: PanelContext; api: ApiClient }> {
  const auth: { token?: string } = {};
  const api = new ApiClient({ baseUrl: () => SERVER, token: () => Promise.resolve(auth.token) });
  auth.token = (await api.login(email, PASSWORD)).access_token;
  const ctx: PanelContext = {
    extensionUri: Uri.file(ROOT) as never,
    session: { api } as unknown as Session,
    refreshViews: () => undefined,
  };
  return { ctx, api };
}

function save(name: string, title: string): void {
  const panel = [...panels].reverse().find((p) => p.title.startsWith(title));
  if (!panel) {
    throw new Error(`no panel titled ${title}; have ${panels.map((p) => p.title).join(", ")}`);
  }
  let html = panel.html
    .replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, "")
    .replaceAll(pathToFileURL(path.join(ROOT, "media")).toString(), "../media");
  // Emulate VS Code's default light theme variables for the preview.
  html = html.replace(
    "</head>",
    `<link rel="stylesheet" href="../test/preview/theme-light.css" /></head>`,
  );
  // Accessibility scan (axe-core from node_modules), results are printed into the page.
  html = html.replace(
    "</body>",
    `<script src="../node_modules/axe-core/axe.min.js"></script><script src="../test/preview/a11y.js"></script></body>`,
  );
  // Apply the in-page updates the extension sent (e.g. duplicate list).
  for (const m of panel.messages as { type: string; id?: string; html?: string }[]) {
    if (m.type === "replace" && m.id && m.html !== undefined) {
      html = html.replace(
        new RegExp(`(<div id="${m.id}"[^>]*>)[\\s\\S]*?(</div>)`),
        (_all, open: string, close: string) => `${open}${m.html}${close}`,
      );
    }
  }
  writeFileSync(path.join(OUT, `${name}.html`), html);
  console.log(`wrote out-preview/${name}.html (${panel.title})`);
}

const tick = (): Promise<void> => new Promise((r) => setTimeout(r, 300));

async function main(): Promise<void> {
  mkdirSync(OUT, { recursive: true });
  const pm = await context("pm@example.com");
  const rita = await context("rita@example.com");
  const admin = await context("admin@example.com");

  // Report Bug form with live duplicates
  await ReportBugPanel.show(rita.ctx);
  const projects = await rita.api.projects();
  const payments = projects.find((p) => p.name === "Payments Platform") ?? projects[0];
  if (!payments) {
    throw new Error("the seeded projects are missing (make seed)");
  }
  const original = (await rita.api.searchBugs({ project_id: payments.id, sort: "created_asc" }))
    .items[0];
  const source = original ? await rita.api.bug(original.id) : undefined;
  const values = {
    project_id: String(payments.id),
    title: `${source?.title ?? "Refund fails"} again`,
    description: source?.description ?? "Refunds fail with HTTP 500 for partial captures.",
    steps_to_reproduce: "1. Refund a partially captured payment\n2. See HTTP 500",
    environment: "Preview run",
    components: (source?.components ?? []).join(", "),
  };
  panels[panels.length - 1]?.send({ type: "checkDuplicates", values });
  await tick();
  save("report-form", "Report Bug");

  // Submit -> result page with severity, recommendations and duplicates
  panels[panels.length - 1]?.send({ type: "submit", values });
  await new Promise((r) => setTimeout(r, 1500));
  save("report-result", "Bug #");

  // AI switched off -> result page with the NFR-10 notice
  await admin.api.updateSettings({ ai_enabled: 0 });
  try {
    panels[panels.length - 1]?.send({ type: "reportAnother" });
    await tick();
    panels[panels.length - 1]?.send({
      type: "submit",
      values: { ...values, title: "Preview: bug submitted while AI is off" },
    });
    await new Promise((r) => setTimeout(r, 1500));
    save("report-ai-off", "Bug #");
  } finally {
    await admin.api.updateSettings({ ai_enabled: 1 });
  }

  // Bug detail of the AI-triaged bug, as the Project Manager (assign, severity, transitions)
  const created = (
    await rita.api.searchBugs({ project_id: payments.id, sort: "created_desc" })
  ).items.find((b) => b.ai_status === "ok");
  const shown = created ?? original;
  if (shown) {
    await BugPanel.show(pm.ctx, shown.id);
    save("bug-detail", `#${shown.id} `);
  }
  await DashboardPanel.show(pm.ctx);
  save("dashboard", "Dashboard");
  await AdminPanel.show(admin.ctx);
  save("admin", "Admin");
}

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
