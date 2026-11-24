import * as vscode from "vscode";

import { errorMessage } from "../api/client";
import type { BugListItem, BugStatus, Notification, Project, Severity } from "../api/types";
import { BUG_STATUSES } from "../api/types";
import type { Session } from "../session";
import { statusLabel } from "../webview/fragments";

const PAGE = 50;
const ACTIVE: BugStatus[] = ["Open", "InProgress"];

const SEVERITY_ICON: Record<Severity, [string, string | undefined]> = {
  Critical: ["error", "errorForeground"],
  High: ["warning", "editorWarning.foreground"],
  Medium: ["circle-filled", undefined],
  Low: ["circle-outline", undefined],
  Unclassified: ["question", "descriptionForeground"],
};

export function bugItem(bug: BugListItem): vscode.TreeItem {
  const item = new vscode.TreeItem(`#${bug.id} ${bug.title}`);
  const [icon, color] = SEVERITY_ICON[bug.severity];
  item.iconPath = new vscode.ThemeIcon(icon, color ? new vscode.ThemeColor(color) : undefined);
  item.description = `${bug.severity} · ${statusLabel(bug.status)}`;
  item.tooltip = new vscode.MarkdownString(
    `**#${bug.id} ${escapeMd(bug.title)}**\n\n` +
      `Severity: ${bug.severity} · Status: ${statusLabel(bug.status)}\n\n` +
      `Assignee: ${escapeMd(bug.assignee?.full_name ?? "unassigned")}` +
      (bug.ai_status === "degraded" ? "\n\n_AI triage was unavailable for this bug._" : ""),
  );
  item.accessibilityInformation = {
    label: `Bug ${bug.id}, ${bug.title}, severity ${bug.severity}, status ${statusLabel(bug.status)}`,
  };
  item.contextValue = "bug";
  item.id = `bug-${bug.id}-${bug.updated_at}`;
  item.command = { command: "bugTracker.openBugById", title: "Open Bug", arguments: [bug.id] };
  return item;
}

function escapeMd(text: string): string {
  return text.replace(/[\\`*_{}[\]()#+\-.!|<>]/g, "\\$&");
}

function messageItem(text: string, icon = "info"): vscode.TreeItem {
  const item = new vscode.TreeItem(text);
  item.iconPath = new vscode.ThemeIcon(icon);
  return item;
}

abstract class BaseTree<T> implements vscode.TreeDataProvider<T | vscode.TreeItem> {
  private readonly emitter = new vscode.EventEmitter<undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  constructor(protected readonly session: Session) {}

  refresh(): void {
    this.emitter.fire(undefined);
  }

  getTreeItem(element: T | vscode.TreeItem): vscode.TreeItem {
    return element instanceof vscode.TreeItem ? element : this.toItem(element);
  }

  async getChildren(element?: T | vscode.TreeItem): Promise<(T | vscode.TreeItem)[]> {
    if (!this.session.currentUser) {
      return []; // the view shows its welcome content (Log In button)
    }
    try {
      return await this.children(element);
    } catch (error) {
      return [messageItem(`Could not load: ${errorMessage(error)}`, "warning")];
    }
  }

  protected abstract toItem(element: T): vscode.TreeItem;
  protected abstract children(element?: T | vscode.TreeItem): Promise<(T | vscode.TreeItem)[]>;
}

/** Bugs assigned to me that still need work (Open, In progress), most severe first. */
export class MyBugsTree extends BaseTree<BugListItem> {
  protected toItem(bug: BugListItem): vscode.TreeItem {
    return bugItem(bug);
  }

  protected async children(): Promise<(BugListItem | vscode.TreeItem)[]> {
    const me = this.session.currentUser;
    if (!me) {
      return [];
    }
    const page = await this.session.api.searchBugs({
      assignee_id: me.id,
      status: ACTIVE,
      sort: "severity_desc",
      page_size: 100,
    });
    return page.items.length ? page.items : [messageItem("No open bugs assigned to you.", "check")];
  }
}

interface ProjectNode {
  kind: "project";
  project: Project;
}
interface StatusNode {
  kind: "status";
  project: Project;
  status: BugStatus;
  total: number;
}
type Node = ProjectNode | StatusNode | BugListItem;

/** Project Bugs: project -> status group (with count) -> bugs. */
export class ProjectBugsTree extends BaseTree<Node> {
  protected toItem(node: Node): vscode.TreeItem {
    if ("kind" in node && node.kind === "project") {
      const item = new vscode.TreeItem(node.project.name, vscode.TreeItemCollapsibleState.Expanded);
      item.iconPath = new vscode.ThemeIcon(node.project.is_archived ? "archive" : "project");
      item.description = node.project.is_archived
        ? "archived (read-only)"
        : (node.project.my_role ?? "");
      item.contextValue = "project";
      item.id = `project-${node.project.id}`;
      return item;
    }
    if ("kind" in node) {
      const item = new vscode.TreeItem(
        `${statusLabel(node.status)} (${node.total})`,
        node.total
          ? node.status === "Open" || node.status === "InProgress"
            ? vscode.TreeItemCollapsibleState.Expanded
            : vscode.TreeItemCollapsibleState.Collapsed
          : vscode.TreeItemCollapsibleState.None,
      );
      item.iconPath = new vscode.ThemeIcon("list-tree");
      item.id = `status-${node.project.id}-${node.status}`;
      return item;
    }
    return bugItem(node);
  }

  protected async children(element?: Node | vscode.TreeItem): Promise<(Node | vscode.TreeItem)[]> {
    const api = this.session.api;
    if (!element) {
      const projects = await api.projects(true);
      return projects.length
        ? projects.map((project) => ({ kind: "project" as const, project }))
        : [messageItem("You are not a member of any project yet.")];
    }
    if (element instanceof vscode.TreeItem || !("kind" in element)) {
      return [];
    }
    if (element.kind === "project") {
      const totals = await Promise.all(
        BUG_STATUSES.map((status) =>
          api.searchBugs({ project_id: element.project.id, status: [status], page_size: 1 }),
        ),
      );
      return BUG_STATUSES.map((status, i) => ({
        kind: "status" as const,
        project: element.project,
        status,
        total: totals[i]?.total ?? 0,
      }));
    }
    const page = await api.searchBugs({
      project_id: element.project.id,
      status: [element.status],
      sort: "severity_desc",
      page_size: PAGE,
    });
    const items: (Node | vscode.TreeItem)[] = [...page.items];
    if (page.total > page.items.length) {
      const more = messageItem(
        `${page.total - page.items.length} more – use Search Bugs`,
        "search",
      );
      more.command = { command: "bugTracker.searchBugs", title: "Search Bugs" };
      items.push(more);
    }
    return items;
  }
}

/** In-app alerts (FR-17), unread first. */
export class NotificationsTree extends BaseTree<Notification> {
  unread = 0;

  protected toItem(n: Notification): vscode.TreeItem {
    const item = new vscode.TreeItem(n.title);
    item.description = n.is_read ? "" : "new";
    item.tooltip = n.message;
    item.iconPath = new vscode.ThemeIcon(
      n.kind === "critical_bug" ? "flame" : n.kind === "assigned" ? "person" : "bell",
      n.is_read ? undefined : new vscode.ThemeColor("notificationsInfoIcon.foreground"),
    );
    item.accessibilityInformation = {
      label: `${n.is_read ? "" : "Unread: "}${n.title}. ${n.message}`,
    };
    item.contextValue = n.is_read ? "notification" : "notification-unread";
    item.command = {
      command: "bugTracker.openNotification",
      title: "Open",
      arguments: [n],
    };
    return item;
  }

  protected async children(): Promise<(Notification | vscode.TreeItem)[]> {
    const page = await this.session.api.notifications(false, 50);
    this.unread = page.items.filter((n) => !n.is_read).length;
    const sorted = [...page.items].sort((a, b) => Number(a.is_read) - Number(b.is_read));
    return sorted.length ? sorted : [messageItem("No notifications.")];
  }
}

/** Named, clickable entry points to every page, so nothing depends on hover icons or typing. */
export class ActionsTree implements vscode.TreeDataProvider<vscode.TreeItem> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(private readonly role: () => string | undefined) {}

  refresh(): void {
    this.changed.fire();
  }

  getTreeItem(item: vscode.TreeItem): vscode.TreeItem {
    return item;
  }

  getChildren(): vscode.TreeItem[] {
    const role = this.role();
    if (!role) {
      return []; // the welcome text offers Log In / Create Account
    }
    const rows: [string, string, string][] = [
      ["Report Bug", "add", "bugTracker.reportBug"],
      ["Search Bugs", "search", "bugTracker.searchBugs"],
      ["Open Dashboard", "graph", "bugTracker.openDashboard"],
      ["My Profile and Notifications", "account", "bugTracker.myProfile"],
    ];
    if (role === "ProjectManager" || role === "Administrator") {
      rows.push(["Create Project", "new-folder", "bugTracker.createProject"]);
      rows.push(["Add Project Member", "person-add", "bugTracker.addProjectMember"]);
    }
    if (role === "Administrator") {
      rows.push(["Admin: Manage Developer Profiles", "settings-gear", "bugTracker.adminProfiles"]);
    }
    rows.push(["Check Server Connection", "plug", "bugTracker.checkConnection"]);
    rows.push(["Log Out", "sign-out", "bugTracker.logout"]);
    return rows.map(([label, icon, command]) => {
      const item = new vscode.TreeItem(label);
      item.iconPath = new vscode.ThemeIcon(icon);
      item.command = { command, title: label };
      return item;
    });
  }
}
