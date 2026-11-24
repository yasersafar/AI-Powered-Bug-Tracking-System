import * as vscode from "vscode";

import { errorMessage } from "./api/client";
import type { BugListItem, Notification, ProjectRole } from "./api/types";
import { SEARCH_HELP, parseSearch } from "./search";
import type { Session } from "./session";
import { statusLabel } from "./webview/fragments";
import type { PanelContext } from "./webview/panel";
import { AdminPanel } from "./webview/admin";
import { BugPanel } from "./webview/bugDetail";
import { DashboardPanel } from "./webview/dashboard";
import { ReportBugPanel } from "./webview/reportBug";

const PASSWORD_RULE = "At least 8 characters with an uppercase letter, a number and a symbol.";

export function passwordProblem(value: string): string | undefined {
  if (value.length < 8) {
    return "At least 8 characters.";
  }
  if (!/[A-Z]/.test(value) || !/\d/.test(value) || !/[^A-Za-z0-9]/.test(value)) {
    return PASSWORD_RULE;
  }
  return undefined;
}

/** Runs a command body and turns any error into one clear message. */
async function guarded(title: string, body: () => Promise<void>): Promise<void> {
  try {
    await body();
  } catch (error) {
    void vscode.window.showErrorMessage(`Bug Tracker – ${title}: ${errorMessage(error)}`);
  }
}

function requireLogin(session: Session): boolean {
  if (session.currentUser) {
    return true;
  }
  void vscode.window
    .showInformationMessage("Bug Tracker: please log in first.", "Log In")
    .then((choice) => {
      if (choice) {
        void vscode.commands.executeCommand("bugTracker.login");
      }
    });
  return false;
}

export function registerCommands(ctx: PanelContext): vscode.Disposable[] {
  const { session } = ctx;
  const api = session.api;

  const login = (): Promise<void> =>
    guarded("Log in", async () => {
      const email = await vscode.window.showInputBox({
        title: "Bug Tracker: Log In (1/2)",
        prompt: "E-mail address",
        placeHolder: "you@example.com",
        ignoreFocusOut: true,
        validateInput: (v) => (v.includes("@") ? undefined : "Enter your e-mail address"),
      });
      if (!email) {
        return;
      }
      const password = await vscode.window.showInputBox({
        title: "Bug Tracker: Log In (2/2)",
        prompt: `Password for ${email}`,
        password: true,
        ignoreFocusOut: true,
      });
      if (!password) {
        return;
      }
      const user = await session.login(email.trim(), password);
      void vscode.window.showInformationMessage(
        `Bug Tracker: logged in as ${user.full_name} (${user.role}).`,
      );
    });

  const register = (): Promise<void> =>
    guarded("Create account", async () => {
      const email = await vscode.window.showInputBox({
        title: "Bug Tracker: Create Account (1/3)",
        prompt: "E-mail address",
        ignoreFocusOut: true,
        validateInput: (v) => (/^\S+@\S+\.\S+$/.test(v) ? undefined : "Enter a valid e-mail"),
      });
      if (!email) {
        return;
      }
      const name = await vscode.window.showInputBox({
        title: "Bug Tracker: Create Account (2/3)",
        prompt: "Full name",
        ignoreFocusOut: true,
        validateInput: (v) => (v.trim().length >= 2 ? undefined : "Enter your name"),
      });
      if (!name) {
        return;
      }
      const password = await vscode.window.showInputBox({
        title: "Bug Tracker: Create Account (3/3)",
        prompt: `Password. ${PASSWORD_RULE}`,
        password: true,
        ignoreFocusOut: true,
        validateInput: passwordProblem,
      });
      if (!password) {
        return;
      }
      await api.register(email.trim(), name.trim(), password);
      await session.login(email.trim(), password);
      void vscode.window.showInformationMessage(
        "Bug Tracker: account created. Ask a Project Manager to add you to a project, then " +
          "use “Report Bug”.",
      );
    });

  const openBug = (): Promise<void> =>
    guarded("Open bug", async () => {
      if (!requireLogin(session)) {
        return;
      }
      const value = await vscode.window.showInputBox({
        title: "Bug Tracker: Open Bug",
        prompt: "Bug number",
        validateInput: (v) =>
          /^#?\d+$/.test(v.trim()) ? undefined : "Enter a bug number, e.g. 42",
      });
      if (value) {
        await BugPanel.show(ctx, Number(value.trim().replace("#", "")));
      }
    });

  const searchBugs = (): Promise<void> =>
    guarded("Search", async () => {
      if (!requireLogin(session)) {
        return;
      }
      const projects = await api.projects(true);
      type Item = vscode.QuickPickItem & { bugId?: number };
      const pick = vscode.window.createQuickPick<Item>();
      pick.title = "Bug Tracker: Search Bugs";
      pick.placeholder = "e.g. crash status:open severity:critical project:payments assignee:me";
      pick.matchOnDescription = true;
      pick.matchOnDetail = true;
      let timer: NodeJS.Timeout | undefined;
      let seq = 0;
      const run = async (text: string): Promise<void> => {
        const mine = ++seq;
        const parsed = parseSearch(text, projects, session.currentUser?.id);
        pick.busy = true;
        try {
          const page = await api.searchBugs(parsed.search);
          if (mine !== seq) {
            return;
          }
          const items: Item[] = page.items.map((b: BugListItem) => ({
            label: `#${b.id} ${b.title}`,
            description: `${b.severity} · ${statusLabel(b.status)}`,
            detail: `${projects.find((p) => p.id === b.project_id)?.name ?? ""} · ${
              b.assignee?.full_name ?? "unassigned"
            }`,
            bugId: b.id,
            alwaysShow: true,
          }));
          const header: Item[] = [
            {
              label: `${page.total} result${page.total === 1 ? "" : "s"}${
                page.total > page.items.length ? ` (first ${page.items.length})` : ""
              }`,
              kind: vscode.QuickPickItemKind.Separator,
            },
          ];
          const problems: Item[] = parsed.problems.length
            ? [
                {
                  label: `$(warning) ${parsed.problems.join("; ")}`,
                  detail: SEARCH_HELP,
                  alwaysShow: true,
                },
              ]
            : [];
          pick.items = [...problems, ...header, ...items];
        } catch (error) {
          pick.items = [{ label: `$(error) ${errorMessage(error)}`, alwaysShow: true }];
        } finally {
          if (mine === seq) {
            pick.busy = false;
          }
        }
      };
      pick.onDidChangeValue((value) => {
        clearTimeout(timer);
        timer = setTimeout(() => void run(value), 350);
      });
      pick.onDidAccept(() => {
        const id = pick.selectedItems[0]?.bugId;
        if (id !== undefined) {
          pick.hide();
          void BugPanel.show(ctx, id);
        }
      });
      pick.onDidHide(() => {
        clearTimeout(timer);
        pick.dispose();
      });
      pick.show();
      await run("");
    });

  const myProfile = (): Promise<void> =>
    guarded("My profile", async () => {
      if (!requireLogin(session)) {
        return;
      }
      const me = await api.me();
      const choice = await vscode.window.showQuickPick(
        [
          { label: "Change name", description: me.full_name, id: "name" },
          {
            label: `${me.email_notifications ? "Turn off" : "Turn on"} e-mail notifications`,
            id: "email",
          },
          {
            label: `${me.push_notifications ? "Turn off" : "Turn on"} push (ntfy) notifications`,
            id: "push",
          },
          { label: "Change password", id: "password" },
          { label: "Copy my ntfy topic", description: me.ntfy_topic, id: "topic" },
        ],
        { title: `Bug Tracker: ${me.full_name} (${me.email}, ${me.role})` },
      );
      if (!choice) {
        return;
      }
      if (choice.id === "name") {
        const name = await vscode.window.showInputBox({ prompt: "Full name", value: me.full_name });
        if (name?.trim()) {
          await api.updateMe({ full_name: name.trim() });
        }
      } else if (choice.id === "email") {
        await api.updateMe({ email_notifications: !me.email_notifications });
      } else if (choice.id === "push") {
        await api.updateMe({ push_notifications: !me.push_notifications });
      } else if (choice.id === "topic") {
        await vscode.env.clipboard.writeText(me.ntfy_topic);
        void vscode.window.showInformationMessage(
          "Topic copied. Subscribe to it in the ntfy app on the team's ntfy server.",
        );
        return;
      } else {
        const current = await vscode.window.showInputBox({
          prompt: "Current password",
          password: true,
        });
        if (!current) {
          return;
        }
        const next = await vscode.window.showInputBox({
          prompt: `New password. ${PASSWORD_RULE}`,
          password: true,
          validateInput: passwordProblem,
        });
        if (!next) {
          return;
        }
        const token = await api.changePassword(current, next);
        await session.storeToken(token.access_token); // other sessions are signed out
      }
      await session.refreshUser();
      void vscode.window.showInformationMessage("Bug Tracker: profile updated.");
    });

  const createProject = (): Promise<void> =>
    guarded("Create project", async () => {
      const name = await vscode.window.showInputBox({
        title: "Bug Tracker: New Project",
        prompt: "Project name",
        validateInput: (v) => (v.trim().length >= 2 ? undefined : "Enter a name"),
      });
      if (!name) {
        return;
      }
      const description = await vscode.window.showInputBox({ prompt: "Description (optional)" });
      const project = await api.createProject(name.trim(), description?.trim() ?? "");
      ctx.refreshViews();
      void vscode.window.showInformationMessage(`Bug Tracker: project “${project.name}” created.`);
    });

  const addMember = (): Promise<void> =>
    guarded("Add member", async () => {
      const projects = (await api.projects()).filter(
        (p) => p.my_role === "ProjectManager" || session.currentUser?.role === "Administrator",
      );
      const project = await vscode.window.showQuickPick(
        projects.map((p) => ({ label: p.name, id: p.id })),
        { title: "Add a member to which project?" },
      );
      if (!project) {
        return;
      }
      const query = await vscode.window.showInputBox({ prompt: "Search users by name or e-mail" });
      if (query === undefined) {
        return;
      }
      const users = await api.searchUsers(query);
      const user = await vscode.window.showQuickPick(
        users.items.map((u) => ({
          label: u.full_name,
          description: `${u.email} · ${u.role}`,
          id: u.id,
        })),
        { title: "Choose the user" },
      );
      if (!user) {
        return;
      }
      const roles: ProjectRole[] = ["Reporter", "Developer", "ProjectManager"];
      const picked = await vscode.window.showQuickPick(roles, { title: "Project role" });
      const role = roles.find((r) => r === picked);
      if (!role) {
        return;
      }
      await api.addMember(project.id, user.id, role);
      ctx.refreshViews();
      void vscode.window.showInformationMessage(
        `Bug Tracker: ${user.label} added to ${project.label} as ${role}.`,
      );
    });

  const openNotification = (n: Notification): Promise<void> =>
    guarded("Notification", async () => {
      if (!n.is_read) {
        await api.markRead(n.id);
        ctx.refreshViews();
      }
      if (n.bug_id) {
        await BugPanel.show(ctx, n.bug_id);
      }
    });

  return [
    vscode.commands.registerCommand("bugTracker.login", login),
    vscode.commands.registerCommand("bugTracker.register", register),
    vscode.commands.registerCommand("bugTracker.logout", async () => {
      await session.clear();
      void vscode.window.showInformationMessage("Bug Tracker: logged out.");
    }),
    vscode.commands.registerCommand("bugTracker.reportBug", async (projectId?: number) => {
      if (requireLogin(session)) {
        await ReportBugPanel.show(ctx, typeof projectId === "number" ? projectId : undefined);
      }
    }),
    vscode.commands.registerCommand("bugTracker.openBug", openBug),
    vscode.commands.registerCommand("bugTracker.openBugById", async (id: number) => {
      if (requireLogin(session)) {
        await BugPanel.show(ctx, id);
      }
    }),
    vscode.commands.registerCommand("bugTracker.searchBugs", searchBugs),
    vscode.commands.registerCommand("bugTracker.openDashboard", async () => {
      if (requireLogin(session)) {
        await DashboardPanel.show(ctx);
      }
    }),
    vscode.commands.registerCommand("bugTracker.adminProfiles", async () => {
      if (session.currentUser?.role !== "Administrator") {
        void vscode.window.showWarningMessage("Bug Tracker: only Administrators can do this.");
        return;
      }
      await AdminPanel.show(ctx);
    }),
    vscode.commands.registerCommand("bugTracker.myProfile", myProfile),
    vscode.commands.registerCommand("bugTracker.createProject", createProject),
    vscode.commands.registerCommand("bugTracker.addProjectMember", addMember),
    vscode.commands.registerCommand("bugTracker.openNotification", openNotification),
    vscode.commands.registerCommand("bugTracker.markAllNotificationsRead", () =>
      guarded("Notifications", async () => {
        await api.markAllRead();
        ctx.refreshViews();
      }),
    ),
    vscode.commands.registerCommand("bugTracker.refresh", () => {
      ctx.refreshViews();
      void BugPanel.refreshAll();
    }),
  ];
}
