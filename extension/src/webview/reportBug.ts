import * as path from "node:path";

import * as vscode from "vscode";

import { NetworkError, errorMessage } from "../api/client";
import type { Bug, Project, Severity } from "../api/types";
import { type SafeHtml, html } from "./html";
import { aiNotice, duplicateList, percent, recommendationList, severityBadge } from "./fragments";
import { BasePanel, type PanelContext, type WebviewMessage, splitList, str } from "./panel";

export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const OVERRIDABLE: readonly Exclude<Severity, "Unclassified">[] = [
  "Low",
  "Medium",
  "High",
  "Critical",
];

/** FR-05 form + FR-10 live duplicate check + FR-11/FR-12 results after submission. */
export class ReportBugPanel extends BasePanel {
  private static current: ReportBugPanel | undefined;
  private projects: Project[] = [];
  private files: vscode.Uri[] = [];
  private checkSeq = 0;
  private created: Bug | undefined;

  static async show(ctx: PanelContext, projectId?: number): Promise<ReportBugPanel> {
    if (ReportBugPanel.current && !ReportBugPanel.current.isDisposed) {
      ReportBugPanel.current.reveal();
      return ReportBugPanel.current;
    }
    const panel = new ReportBugPanel(ctx);
    ReportBugPanel.current = panel;
    await panel.load(projectId);
    return panel;
  }

  private constructor(ctx: PanelContext) {
    super("bugTracker.reportBug", "Report Bug", ctx);
  }

  private async load(projectId?: number): Promise<void> {
    try {
      this.projects = (await this.api.projects()).filter((p) => !p.is_archived);
    } catch (error) {
      this.projects = [];
      this.renderForm(projectId);
      this.showError(error, "Loading your projects");
      return;
    }
    this.renderForm(projectId);
  }

  private renderForm(projectId?: number): void {
    this.created = undefined;
    this.files = [];
    const selected = projectId ?? (this.projects.length === 1 ? this.projects[0]?.id : undefined);
    this.setTitle("Report Bug");
    this.render(
      "Report a bug",
      html`<p class="hint">
          Fields marked * are required. While you type, similar reports in the project are shown so
          you can avoid filing a duplicate.
        </p>
        <form id="report" data-submit="submit" novalidate>
          <div class="field">
            <label for="project_id">Project *</label>
            <select id="project_id" name="project_id" required data-change="checkDuplicates">
              <option value="">Choose a project…</option>
              ${this.projects.map(
                (p) =>
                  html`<option value="${p.id}" ${p.id === selected ? "selected" : ""}>
                    ${p.name}
                  </option>`,
              )}
            </select>
          </div>
          <div class="field">
            <label for="title">Title *</label>
            <input
              id="title"
              name="title"
              required
              minlength="5"
              maxlength="200"
              aria-describedby="title-hint"
              data-debounce="checkDuplicates"
            />
            <span id="title-hint" class="hint">5–200 characters, one line.</span>
          </div>
          <div class="field">
            <label for="description">Description *</label>
            <textarea
              id="description"
              name="description"
              required
              minlength="20"
              maxlength="20000"
              aria-describedby="description-hint"
              data-debounce="checkDuplicates"
            ></textarea>
            <span id="description-hint" class="hint"
              >At least 20 characters: what happens and what you expected.</span
            >
          </div>
          <section aria-labelledby="dup-heading">
            <h2 id="dup-heading">Possible duplicates</h2>
            <div id="duplicates" aria-live="polite">
              <p class="hint">Start typing a title and description to check.</p>
            </div>
          </section>
          <div class="field">
            <label for="steps_to_reproduce">Steps to reproduce *</label>
            <textarea
              id="steps_to_reproduce"
              name="steps_to_reproduce"
              required
              maxlength="10000"
            ></textarea>
          </div>
          <div class="field">
            <label for="environment">Environment *</label>
            <input
              id="environment"
              name="environment"
              required
              maxlength="500"
              placeholder="e.g. VS Code 1.105, macOS 15, app v3.8"
            />
          </div>
          <div class="field">
            <label for="components">Components</label>
            <input
              id="components"
              name="components"
              aria-describedby="components-hint"
              placeholder="e.g. checkout, payments-api"
            />
            <span id="components-hint" class="hint">Optional, comma separated (max 10).</span>
          </div>
          <div class="field">
            <span id="attachments-label"><strong>Attachments</strong></span>
            <div id="attachments" role="group" aria-labelledby="attachments-label">
              ${this.fileList()}
            </div>
            <div class="row">
              <button type="button" class="secondary" data-action="addFiles">Add files…</button>
            </div>
            <span class="hint">Images, PDF, text or logs; up to 10 MB each.</span>
          </div>
          <div class="row">
            <button type="submit" data-busy-disable>Submit bug</button>
            <button type="button" class="secondary" data-action="discard" data-busy-disable>
              Discard
            </button>
          </div>
        </form>`,
    );
  }

  private fileList(): SafeHtml {
    if (this.files.length === 0) {
      return html`<p class="hint">No files added.</p>`;
    }
    return html`<ul class="plain">
      ${this.files.map(
        (f, i) =>
          html`<li>
            ${path.basename(f.fsPath)}
            <button
              type="button"
              class="link"
              data-action="removeFile"
              data-index="${i}"
              aria-label="Remove ${path.basename(f.fsPath)}"
            >
              Remove
            </button>
          </li>`,
      )}
    </ul>`;
  }

  protected async onMessage(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case "checkDuplicates":
        await this.checkDuplicates(message.values);
        return;
      case "submit":
        await this.submit(message.values);
        return;
      case "discard":
        await this.discard();
        return;
      case "addFiles":
        await this.addFiles();
        return;
      case "removeFile":
        this.files.splice(Number(message.index), 1);
        this.replace("attachments", this.fileList());
        return;
      case "openBug":
        await vscode.commands.executeCommand("bugTracker.openBugById", Number(message.id));
        return;
      case "overrideSeverity":
        await this.overrideSeverity(str(message.values, "severity"));
        return;
      case "reportAnother":
        this.renderForm(this.created?.project_id);
        return;
      default:
        return;
    }
  }

  private async checkDuplicates(values: Record<string, unknown> | undefined): Promise<void> {
    const projectId = Number(str(values, "project_id"));
    const title = str(values, "title");
    const description = str(values, "description");
    if (!projectId || (title + description).length < 3) {
      return;
    }
    const seq = ++this.checkSeq;
    this.replace("duplicates", html`<p class="hint">Checking for similar reports…</p>`);
    try {
      const result = await this.api.duplicates(projectId, title, description);
      if (seq !== this.checkSeq) {
        return; // a newer check is running; ignore this stale answer
      }
      if (result.ai_status === "degraded") {
        this.replace(
          "duplicates",
          html`<p class="notice warning">
            Duplicate check unavailable right now. ${result.notice ?? ""} You can still submit.
          </p>`,
        );
        return;
      }
      this.replace("duplicates", duplicateList(result.duplicates, result.is_likely_duplicate));
    } catch (error) {
      if (seq !== this.checkSeq) {
        return;
      }
      const text =
        error instanceof NetworkError
          ? "Server unreachable: duplicate check paused. Your text is kept."
          : `Duplicate check failed: ${errorMessage(error)}`;
      this.replace("duplicates", html`<p class="notice warning">${text}</p>`);
    }
  }

  private async addFiles(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({
      canSelectMany: true,
      openLabel: "Attach",
      title: "Attach files to the bug report",
    });
    if (!picked) {
      return;
    }
    for (const uri of picked) {
      const stat = await vscode.workspace.fs.stat(uri);
      if (stat.size > MAX_ATTACHMENT_BYTES) {
        this.status(
          `${path.basename(uri.fsPath)} is larger than 10 MB and was not added.`,
          "error",
        );
        continue;
      }
      if (!this.files.some((f) => f.toString() === uri.toString())) {
        this.files.push(uri);
      }
    }
    this.replace("attachments", this.fileList());
  }

  private async discard(): Promise<void> {
    const choice = await vscode.window.showWarningMessage(
      "Discard this bug report? Nothing will be saved.",
      { modal: true },
      "Discard",
    );
    if (choice === "Discard") {
      this.dispose();
    }
  }

  private async submit(values: Record<string, unknown> | undefined): Promise<void> {
    this.clearMessages();
    const projectId = Number(str(values, "project_id"));
    if (!projectId) {
      this.status("Choose a project.", "error");
      this.focus("project_id");
      return;
    }
    this.busy(true);
    this.status("Submitting and running AI triage…");
    let bug: Bug;
    try {
      bug = await this.api.createBug({
        project_id: projectId,
        title: str(values, "title"),
        description: str(values, "description"),
        steps_to_reproduce: str(values, "steps_to_reproduce"),
        environment: str(values, "environment"),
        components: splitList(str(values, "components")),
      });
    } catch (error) {
      this.busy(false);
      this.status("");
      this.showError(error, "Submitting the bug");
      return;
    }
    const uploadErrors: string[] = [];
    for (const file of this.files) {
      try {
        const data = await vscode.workspace.fs.readFile(file);
        await this.api.uploadAttachment(bug.id, path.basename(file.fsPath), data);
      } catch (error) {
        uploadErrors.push(`${path.basename(file.fsPath)}: ${errorMessage(error)}`);
      }
    }
    this.created = bug;
    this.ctx.refreshViews();
    this.renderResult(bug, uploadErrors);
  }

  private renderResult(bug: Bug, uploadErrors: string[]): void {
    this.setTitle(`Bug #${bug.id}`);
    this.render(
      `Bug #${bug.id} submitted`,
      html`<p><strong>${bug.title}</strong></p>
        ${aiNotice(bug, bug.ai_details)}
        ${
          uploadErrors.length
            ? html`<div class="notice error" role="alert">
                Some attachments were not uploaded: ${uploadErrors.join("; ")}
              </div>`
            : ""
        }
        <section aria-labelledby="sev-heading">
          <h2 id="sev-heading">Predicted severity</h2>
          <p>
            ${severityBadge(bug.severity)}
            ${
              bug.predicted_severity
                ? html`<span class="hint">confidence ${percent(bug.severity_confidence)}</span>`
                : ""
            }
          </p>
          ${
            bug.can_override_severity
              ? html`<form id="override" class="row" data-submit="overrideSeverity">
                  <label for="severity">Override severity</label>
                  <select id="severity" name="severity">
                    ${OVERRIDABLE.map(
                      (s) =>
                        html`<option value="${s}" ${s === bug.severity ? "selected" : ""}>
                          ${s}
                        </option>`,
                    )}
                  </select>
                  <button type="submit" class="secondary" data-busy-disable>Apply</button>
                </form>`
              : html`<p class="hint">
                  A Developer or Project Manager of the project can change the severity.
                </p>`
          }
        </section>
        <section aria-labelledby="rec-heading">
          <h2 id="rec-heading">Recommended developers</h2>
          ${recommendationList(bug.recommended_developers)}
        </section>
        <section aria-labelledby="dups-heading">
          <h2 id="dups-heading">Similar reports</h2>
          ${duplicateList(bug.duplicate_candidates, bug.ai_details.is_likely_duplicate)}
        </section>
        <div class="row">
          <button data-action="openBug" data-id="${bug.id}">Open bug #${bug.id}</button>
          <button class="secondary" data-action="reportAnother">Report another bug</button>
        </div>`,
    );
    this.focus("main");
  }

  private async overrideSeverity(value: string): Promise<void> {
    const bug = this.created;
    const severity = OVERRIDABLE.find((s) => s === value);
    if (!bug || !severity) {
      return;
    }
    this.busy(true);
    try {
      const updated = await this.api.overrideSeverity(bug.id, severity);
      this.created = updated;
      this.ctx.refreshViews();
      this.renderResult(updated, []);
      this.status(`Severity set to ${updated.severity}. The change is in the audit trail.`);
    } finally {
      this.busy(false);
    }
  }

  protected override onDispose(): void {
    if (ReportBugPanel.current === this) {
      ReportBugPanel.current = undefined;
    }
  }
}
