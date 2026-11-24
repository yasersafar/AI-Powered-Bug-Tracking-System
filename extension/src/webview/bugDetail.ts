import { homedir } from "node:os";
import * as path from "node:path";

import * as vscode from "vscode";

import { errorMessage } from "../api/client";
import type {
  Attachment,
  AuditEntry,
  Bug,
  BugStatus,
  Comment,
  Member,
  Severity,
} from "../api/types";
import { type SafeHtml, formatDate, html } from "./html";
import {
  aiNotice,
  duplicateList,
  percent,
  recommendationList,
  severityBadge,
  statusLabel,
} from "./fragments";
import { BasePanel, type PanelContext, type WebviewMessage, str } from "./panel";
import { MAX_ATTACHMENT_BYTES } from "./reportBug";

const OVERRIDABLE: readonly Exclude<Severity, "Unclassified">[] = [
  "Low",
  "Medium",
  "High",
  "Critical",
];

interface Loaded {
  bug: Bug;
  comments: Comment[];
  attachments: Attachment[];
  audit: AuditEntry[];
  developers: Member[];
}

/** FR-06, FR-08, FR-09, FR-11 override, FR-12 assignment, FR-14 attachments. */
export class BugPanel extends BasePanel {
  private static readonly open = new Map<number, BugPanel>();
  private data: Loaded | undefined;

  static async show(ctx: PanelContext, bugId: number): Promise<void> {
    const existing = BugPanel.open.get(bugId);
    if (existing && !existing.isDisposed) {
      existing.reveal();
      await existing.reload();
      return;
    }
    const panel = new BugPanel(ctx, bugId);
    BugPanel.open.set(bugId, panel);
    await panel.reload();
  }

  /** Reload every open bug panel (e.g. after a change elsewhere). */
  static async refreshAll(): Promise<void> {
    await Promise.all([...BugPanel.open.values()].map((p) => p.reload()));
  }

  private constructor(
    ctx: PanelContext,
    private readonly bugId: number,
  ) {
    super("bugTracker.bug", `Bug #${bugId}`, ctx);
  }

  async reload(): Promise<void> {
    try {
      const bug = await this.api.bug(this.bugId);
      const [comments, attachments, audit, members] = await Promise.all([
        this.api.comments(this.bugId),
        this.api.attachments(this.bugId),
        this.api.audit(this.bugId),
        bug.can_assign ? this.api.members(bug.project_id) : Promise.resolve([]),
      ]);
      this.data = {
        bug,
        comments,
        attachments,
        audit,
        developers: members.filter((m) => m.role === "Developer"),
      };
      this.draw();
    } catch (error) {
      if (!this.data) {
        this.render(`Bug #${this.bugId}`, html`<p>Could not load this bug.</p>`);
      }
      this.showError(error, "Loading the bug");
    }
  }

  private draw(): void {
    const data = this.data;
    if (!data) {
      return;
    }
    const { bug } = data;
    this.setTitle(`#${bug.id} ${bug.title}`);
    this.render(
      `#${bug.id} ${bug.title}`,
      html`<p class="row">
          <span class="badge">${statusLabel(bug.status)}</span>
          ${severityBadge(bug.severity)}
          ${bug.severity_overridden ? html`<span class="hint">(severity set by a person)</span>` : ""}
        </p>
        ${aiNotice(bug, bug.ai_details)} ${this.actions(data)}
        <h2>Details</h2>
        <dl class="meta">
          <dt>Reporter</dt>
          <dd>${bug.reporter?.full_name ?? "-"}</dd>
          <dt>Assignee</dt>
          <dd>${bug.assignee?.full_name ?? "Unassigned"}</dd>
          <dt>Components</dt>
          <dd>${bug.components.join(", ") || "-"}</dd>
          <dt>Environment</dt>
          <dd>${bug.environment}</dd>
          <dt>Created</dt>
          <dd>${formatDate(bug.created_at)}</dd>
          <dt>Updated</dt>
          <dd>${formatDate(bug.updated_at)}</dd>
          ${
            bug.close_reason
              ? html`<dt>Close reason</dt>
                  <dd>
                    ${bug.close_reason}${
                      bug.duplicate_of_id
                        ? html` of
                            <button
                              class="link"
                              data-action="openBug"
                              data-id="${bug.duplicate_of_id}"
                            >
                              #${bug.duplicate_of_id}
                            </button>`
                        : ""
                    }
                  </dd>`
              : ""
          }
        </dl>
        <h2>Description</h2>
        <div class="text">${bug.description}</div>
        <h2>Steps to reproduce</h2>
        <div class="text">${bug.steps_to_reproduce}</div>
        <h2>AI triage</h2>
        <dl class="meta">
          <dt>Predicted severity</dt>
          <dd>
            ${bug.predicted_severity ?? "none"}
            ${
              bug.predicted_severity
                ? html`<span class="hint">(confidence ${percent(bug.severity_confidence)})</span>`
                : ""
            }
          </dd>
        </dl>
        <h3>Recommended developers</h3>
        ${recommendationList(bug.recommended_developers)}
        <h3>Similar reports at submission</h3>
        ${duplicateList(bug.duplicate_candidates, bug.ai_details.is_likely_duplicate)}
        ${this.comments(data.comments)} ${this.attachments(data.attachments)}
        ${this.audit(data.audit)}`,
    );
  }

  private actions(data: Loaded): SafeHtml {
    const { bug } = data;
    const recommended = new Set(bug.recommended_developers.map((r) => r.developer_id));
    return html`<section aria-labelledby="actions-heading">
      <h2 id="actions-heading">Actions</h2>
      ${
        bug.allowed_transitions.length
          ? html`<div class="row" role="group" aria-label="Change status">
              ${bug.allowed_transitions.map(
                (s) =>
                  html`<button
                    class="${s === "Closed" ? "secondary" : ""}"
                    data-action="transition"
                    data-to="${s}"
                    data-busy-disable
                  >
                    ${transitionLabel(bug.status, s)}
                  </button>`,
              )}
            </div>`
          : html`<p class="hint">No status change is available to you for this bug.</p>`
      }
      ${
        bug.can_assign
          ? html`<form id="assign" class="row" data-submit="assign">
              <label for="assignee">Assign to</label>
              <select id="assignee" name="assignee" required>
                <option value="">Choose a developer…</option>
                ${data.developers.map(
                  (m) =>
                    html`<option
                      value="${m.user.id}"
                      ${m.user.id === bug.assignee?.id ? "selected" : ""}
                    >
                      ${m.user.full_name}${recommended.has(m.user.id) ? " (recommended)" : ""}
                    </option>`,
                )}
              </select>
              <button type="submit" class="secondary" data-busy-disable>Assign</button>
            </form>`
          : ""
      }
      ${
        bug.can_override_severity
          ? html`<form id="override" class="row" data-submit="overrideSeverity">
              <label for="severity">Severity</label>
              <select id="severity" name="severity">
                ${OVERRIDABLE.map(
                  (s) =>
                    html`<option value="${s}" ${s === bug.severity ? "selected" : ""}>
                      ${s}
                    </option>`,
                )}
              </select>
              <button type="submit" class="secondary" data-busy-disable>Set severity</button>
            </form>`
          : ""
      }
    </section>`;
  }

  private comments(comments: Comment[]): SafeHtml {
    return html`<section aria-labelledby="comments-heading">
      <h2 id="comments-heading">Comments (${comments.length})</h2>
      ${
        comments.length
          ? html`<ul class="plain">
              ${comments.map(
                (c) =>
                  html`<li class="card">
                    <div class="hint">
                      ${c.author?.full_name ?? "Deleted user"} · ${formatDate(c.created_at)}
                    </div>
                    <div class="text">${c.body}</div>
                  </li>`,
              )}
            </ul>`
          : html`<p class="hint">No comments yet.</p>`
      }
      <form id="comment" class="stack" data-submit="comment">
        <div class="field">
          <label for="body">Add a comment</label>
          <textarea id="body" name="body" required maxlength="5000"></textarea>
        </div>
        <div class="row"><button type="submit" data-busy-disable>Post comment</button></div>
      </form>
    </section>`;
  }

  private attachments(attachments: Attachment[]): SafeHtml {
    return html`<section aria-labelledby="files-heading">
      <h2 id="files-heading">Attachments (${attachments.length})</h2>
      ${
        attachments.length
          ? html`<table>
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Type</th>
                  <th scope="col">Size</th>
                  <th scope="col">Uploaded</th>
                  <th scope="col"><span class="visually-hidden">Download</span></th>
                </tr>
              </thead>
              <tbody>
                ${attachments.map(
                  (a) =>
                    html`<tr>
                      <td>${a.original_filename}</td>
                      <td>${a.content_type}</td>
                      <td>${formatSize(a.size_bytes)}</td>
                      <td>${a.uploader?.full_name ?? "-"}, ${formatDate(a.created_at)}</td>
                      <td>
                        <button
                          class="link"
                          data-action="download"
                          data-id="${a.id}"
                          data-name="${a.original_filename}"
                          aria-label="Download ${a.original_filename}"
                        >
                          Download
                        </button>
                      </td>
                    </tr>`,
                )}
              </tbody>
            </table>`
          : html`<p class="hint">No attachments.</p>`
      }
      <div class="row">
        <button class="secondary" data-action="upload" data-busy-disable>Upload file…</button>
      </div>
    </section>`;
  }

  private audit(entries: AuditEntry[]): SafeHtml {
    return html`<section aria-labelledby="audit-heading">
      <h2 id="audit-heading">History</h2>
      <table>
        <caption class="visually-hidden">
          Audit trail: every change with who made it and when (UTC)
        </caption>
        <thead>
          <tr>
            <th scope="col">When (UTC)</th>
            <th scope="col">Who</th>
            <th scope="col">What</th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          ${entries.map(
            (e) =>
              html`<tr>
                <td>${formatDate(e.created_at)}</td>
                <td>${e.actor?.full_name ?? "System (AI)"}</td>
                <td>${e.action.replace(/_/g, " ")}${e.field ? html` (${e.field})` : ""}</td>
                <td>${e.old_value ?? "–"} → ${e.new_value ?? "–"}</td>
              </tr>`,
          )}
        </tbody>
      </table>
    </section>`;
  }

  protected async onMessage(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case "transition":
        await this.transition(String(message.to) as BugStatus);
        return;
      case "assign":
        await this.change("Assignment", () =>
          this.api.assign(this.bugId, Number(str(message.values, "assignee"))),
        );
        return;
      case "overrideSeverity": {
        const severity = OVERRIDABLE.find((s) => s === str(message.values, "severity"));
        if (severity) {
          await this.change("Severity change", () =>
            this.api.overrideSeverity(this.bugId, severity),
          );
        }
        return;
      }
      case "comment":
        await this.change("Posting the comment", () =>
          this.api.addComment(this.bugId, str(message.values, "body")),
        );
        return;
      case "upload":
        await this.upload();
        return;
      case "download":
        await this.download(Number(message.id), String(message.name));
        return;
      case "openBug":
        await BugPanel.show(this.ctx, Number(message.id));
        return;
      default:
        return;
    }
  }

  private async transition(to: BugStatus): Promise<void> {
    let reason: "invalid" | "duplicate" | undefined;
    let duplicateOf: number | undefined;
    if (to === "Closed" && this.data?.bug.status === "Open") {
      const pick = await vscode.window.showQuickPick(
        [
          { label: "Invalid", description: "Not a bug or cannot be reproduced", value: "invalid" },
          { label: "Duplicate", description: "Same as another report", value: "duplicate" },
        ] as const,
        { title: `Close bug #${this.bugId}`, placeHolder: "Why is this bug being closed?" },
      );
      if (!pick) {
        return;
      }
      reason = pick.value;
      if (reason === "duplicate") {
        const suggested = this.data.bug.duplicate_candidates[0]?.bug_id;
        const input = await vscode.window.showInputBox({
          title: "Duplicate of which bug?",
          prompt: "Bug number of the original report",
          value: suggested ? String(suggested) : "",
          validateInput: (v) => (/^\d+$/.test(v.trim()) ? undefined : "Enter a bug number"),
        });
        if (!input) {
          return;
        }
        duplicateOf = Number(input.trim());
      }
    }
    await this.change(`Moving to ${statusLabel(to)}`, () =>
      this.api.transition(this.bugId, to, reason, duplicateOf),
    );
  }

  private async change(action: string, call: () => Promise<unknown>): Promise<void> {
    this.busy(true);
    try {
      await call();
    } catch (error) {
      this.busy(false);
      this.showError(error, action);
      return;
    }
    this.ctx.refreshViews();
    await this.reload();
    this.status(`${action} saved.`);
  }

  private async upload(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({
      canSelectMany: false,
      openLabel: "Upload",
    });
    const file = picked?.[0];
    if (!file) {
      return;
    }
    const stat = await vscode.workspace.fs.stat(file);
    if (stat.size > MAX_ATTACHMENT_BYTES) {
      this.status("The file is larger than 10 MB.", "error");
      return;
    }
    const data = await vscode.workspace.fs.readFile(file);
    await this.change("Uploading the file", () =>
      this.api.uploadAttachment(this.bugId, path.basename(file.fsPath), data),
    );
  }

  private async download(attachmentId: number, name: string): Promise<void> {
    const target = await vscode.window.showSaveDialog({
      defaultUri: vscode.Uri.file(path.join(homedir(), path.basename(name))),
      title: `Save ${name}`,
    });
    if (!target) {
      return;
    }
    try {
      const data = await this.api.downloadAttachment(attachmentId);
      await vscode.workspace.fs.writeFile(target, data);
      this.status(`Saved ${path.basename(target.fsPath)}.`);
    } catch (error) {
      this.status(`Download failed: ${errorMessage(error)}`, "error");
    }
  }

  protected override onDispose(): void {
    if (BugPanel.open.get(this.bugId) === this) {
      BugPanel.open.delete(this.bugId);
    }
  }
}

function transitionLabel(from: BugStatus, to: BugStatus): string {
  if (to === "InProgress") {
    return from === "Open" ? "Start progress" : "Reopen";
  }
  if (to === "Resolved") {
    return "Mark resolved";
  }
  if (to === "Verified") {
    return "Verify fix";
  }
  if (to === "Closed") {
    return "Close";
  }
  return statusLabel(to);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
