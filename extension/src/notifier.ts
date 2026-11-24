import * as vscode from "vscode";

import type { Notification } from "./api/types";
import type { Session } from "./session";

/**
 * FR-17: turns new server notifications into VS Code notifications. The extension polls
 * `/notifications` (allowed by the design as an alternative to listening on the ntfy topic):
 * it needs no extra connection or token, and phones keep using the user's ntfy topic.
 */
export class Notifier implements vscode.Disposable {
  private timer: NodeJS.Timeout | undefined;
  private lastSeen: number | undefined;
  private polling = false;

  constructor(
    private readonly session: Session,
    private readonly onChange: (unread: number) => void,
    private readonly intervalMs = 30_000,
  ) {}

  start(): void {
    this.stop();
    this.lastSeen = undefined;
    void this.poll();
    this.timer = setInterval(() => void this.poll(), this.intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
  }

  async poll(): Promise<void> {
    if (this.polling || !this.session.currentUser) {
      return;
    }
    this.polling = true;
    try {
      const page = await this.session.api.notifications(true, 20);
      const newest = page.items.reduce((max, n) => Math.max(max, n.id), 0);
      if (this.lastSeen === undefined) {
        // First poll after login: one summary instead of a burst of old alerts.
        if (page.total > 0) {
          void this.summary(page.total);
        }
      } else {
        const fresh = page.items.filter((n) => n.id > (this.lastSeen ?? 0)).slice(0, 3);
        for (const n of fresh.reverse()) {
          void this.show(n);
        }
      }
      this.lastSeen = Math.max(this.lastSeen ?? 0, newest);
      this.onChange(page.total);
    } catch {
      // Offline or logged out: the status bar already says so; try again next time.
    } finally {
      this.polling = false;
    }
  }

  private async summary(count: number): Promise<void> {
    const choice = await vscode.window.showInformationMessage(
      `Bug Tracker: you have ${count} unread notification${count === 1 ? "" : "s"}.`,
      "Show",
    );
    if (choice) {
      await vscode.commands.executeCommand("bugTracker.notifications.focus");
    }
  }

  private async show(n: Notification): Promise<void> {
    const show =
      n.kind === "critical_bug"
        ? vscode.window.showWarningMessage
        : vscode.window.showInformationMessage;
    const choice = await show(`${n.title}: ${n.message}`, ...(n.bug_id ? ["Open Bug"] : []));
    if (choice === "Open Bug") {
      await vscode.commands.executeCommand("bugTracker.openNotification", n);
    }
  }

  dispose(): void {
    this.stop();
  }
}
