import * as vscode from "vscode";

import { NetworkError, errorMessage } from "../api/client";
import type { Session } from "../session";
import { type SafeHtml, html, nonce } from "./html";

export interface PanelContext {
  extensionUri: vscode.Uri;
  session: Session;
  /** Ask the tree views to reload (after a change made in a webview). */
  refreshViews: () => void;
}

export interface WebviewMessage {
  type: string;
  values?: Record<string, unknown>;
  value?: string;
  [key: string]: unknown;
}

/**
 * Base class for the Bug Tracker webviews: strict CSP (no inline script, no remote content),
 * one shared script and stylesheet, theme colours, and uniform error reporting.
 */
export abstract class BasePanel implements vscode.Disposable {
  protected readonly panel: vscode.WebviewPanel;
  private readonly disposables: vscode.Disposable[] = [];
  private disposed = false;

  protected constructor(
    viewType: string,
    title: string,
    protected readonly ctx: PanelContext,
  ) {
    this.panel = vscode.window.createWebviewPanel(viewType, title, vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, "media")],
    });
    this.panel.iconPath = vscode.Uri.joinPath(ctx.extensionUri, "media", "bug.svg");
    this.disposables.push(
      this.panel.onDidDispose(() => {
        this.dispose();
      }),
      this.panel.webview.onDidReceiveMessage((message: WebviewMessage) => {
        void this.handle(message);
      }),
    );
  }

  get api(): Session["api"] {
    return this.ctx.session.api;
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  reveal(): void {
    this.panel.reveal();
  }

  protected setTitle(title: string): void {
    this.panel.title = title;
  }

  /** Render a full page. `body` must come from `html` (escaped). */
  protected render(heading: string, body: SafeHtml): void {
    const webview = this.panel.webview;
    const media = (file: string): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, "media", file));
    const n = nonce();
    const csp = [
      "default-src 'none'",
      `style-src ${webview.cspSource}`,
      `img-src ${webview.cspSource} data:`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${n}'`,
    ].join("; ");
    webview.html = html`<!doctype html>
      <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta http-equiv="Content-Security-Policy" content="${csp}" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <link rel="stylesheet" href="${media("webview.css").toString()}" />
          <title>${heading}</title>
        </head>
        <body>
          <a class="skip-link" href="#main">Skip to content</a>
          <main id="main" tabindex="-1">
            <h1>${heading}</h1>
            <div id="error" class="notice error" role="alert"></div>
            <div id="status" class="notice" role="status" aria-live="polite"></div>
            ${body}
          </main>
          <script nonce="${n}" src="${media("webview.js").toString()}"></script>
        </body>
      </html>`.value;
  }

  protected replace(id: string, markup: SafeHtml): void {
    void this.panel.webview.postMessage({ type: "replace", id, html: markup.value });
  }

  protected status(text: string, kind: "info" | "warning" | "error" = "info"): void {
    void this.panel.webview.postMessage({ type: "status", text, kind });
  }

  protected clearMessages(): void {
    this.status("");
    this.status("", "error");
  }

  protected focus(id: string): void {
    void this.panel.webview.postMessage({ type: "focus", id });
  }

  protected busy(value: boolean): void {
    void this.panel.webview.postMessage({ type: "busy", busy: value });
  }

  /** Report an error inside the page (role="alert"), keeping whatever the user typed. */
  protected showError(error: unknown, action: string): void {
    const offline = error instanceof NetworkError;
    const text = offline
      ? `${action} failed: the server is unreachable. Nothing was saved; your input is kept. ` +
        "Check the connection (status bar) and try again."
      : `${action} failed: ${errorMessage(error)}`;
    this.status(text, "error");
  }

  private async handle(message: WebviewMessage): Promise<void> {
    try {
      await this.onMessage(message);
    } catch (error) {
      this.busy(false);
      this.showError(error, "The action");
    }
  }

  protected abstract onMessage(message: WebviewMessage): Promise<void>;

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.panel.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
    this.onDispose();
  }

  protected onDispose(): void {
    // overridden by panels that keep a registry
  }
}

export function str(values: Record<string, unknown> | undefined, key: string): string {
  const value = values?.[key];
  return typeof value === "string" ? value.trim() : "";
}

export function splitList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}
