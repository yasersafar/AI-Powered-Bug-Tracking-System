import * as vscode from "vscode";

import { registerCommands } from "./commands";
import { CONFIG_SECTION, SERVER_URL_KEY, getServerUrl, normalizeServerUrl } from "./config";
import { type ConnectionState, checkHealth } from "./health";
import { Notifier } from "./notifier";
import { Session } from "./session";
import { ActionsTree, MyBugsTree, NotificationsTree, ProjectBugsTree } from "./views/trees";
import type { PanelContext } from "./webview/panel";

/** Exposed for the extension tests. */
export interface BugTrackerApi {
  session: Session;
  connection: () => ConnectionState | undefined;
}

let statusItem: vscode.StatusBarItem | undefined;
let lastState: ConnectionState | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<BugTrackerApi> {
  const session = new Session(context.secrets);
  const actions = new ActionsTree(() => session.currentUser?.role);
  const myBugs = new MyBugsTree(session);
  const projectBugs = new ProjectBugsTree(session);
  const notificationsTree = new NotificationsTree(session);
  const notificationsView = vscode.window.createTreeView("bugTracker.notifications", {
    treeDataProvider: notificationsTree,
  });

  const refreshViews = (): void => {
    actions.refresh();
    myBugs.refresh();
    projectBugs.refresh();
    notificationsTree.refresh();
  };
  const notifier = new Notifier(session, (unread) => {
    notificationsView.badge = unread
      ? { value: unread, tooltip: `${unread} unread notification${unread === 1 ? "" : "s"}` }
      : undefined;
    notificationsTree.refresh();
  });
  const ctx: PanelContext = { extensionUri: context.extensionUri, session, refreshViews };

  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusItem.command = "bugTracker.checkConnection";

  context.subscriptions.push(
    session,
    notifier,
    statusItem,
    notificationsView,
    vscode.window.registerTreeDataProvider("bugTracker.actions", actions),
    vscode.window.registerTreeDataProvider("bugTracker.myBugs", myBugs),
    vscode.window.registerTreeDataProvider("bugTracker.projectBugs", projectBugs),
    ...registerCommands(ctx),
    vscode.commands.registerCommand("bugTracker.setServerUrl", setServerUrl),
    vscode.commands.registerCommand("bugTracker.checkConnection", () =>
      refreshConnection(session, { notify: true }),
    ),
    vscode.commands.registerCommand("bugTracker.statusMenu", () => showStatusMenu(session)),
    vscode.workspace.onDidChangeConfiguration(async (event) => {
      if (event.affectsConfiguration(`${CONFIG_SECTION}.${SERVER_URL_KEY}`)) {
        // A token belongs to one server: changing the server signs out.
        await session.clear();
        await refreshConnection(session, { notify: false });
      }
    }),
    session.onDidChangeUser((user) => {
      refreshViews();
      renderStatus(session);
      if (user) {
        notifier.start();
      } else {
        notifier.stop();
        notificationsView.badge = undefined;
      }
    }),
    session.onDidChangeReachability((reachable) => {
      if (!reachable) {
        lastState = { kind: "offline", reason: "server unreachable" };
        renderStatus(session);
      } else {
        void refreshConnection(session, { notify: false });
      }
    }),
  );

  await vscode.commands.executeCommand("setContext", "bugTracker.loggedIn", false);
  void refreshConnection(session, { notify: false }).then(() => session.restore());
  return { session, connection: () => lastState };
}

export function deactivate(): void {
  statusItem = undefined;
}

async function setServerUrl(): Promise<void> {
  const value = await vscode.window.showInputBox({
    title: "Bug Tracker: Server URL",
    prompt: "Base URL of the Bug Tracker backend",
    value: getServerUrl(),
    ignoreFocusOut: true,
    validateInput: (input) =>
      normalizeServerUrl(input) ? undefined : "Enter an http:// or https:// URL",
  });
  const normalized = value === undefined ? undefined : normalizeServerUrl(value);
  if (!normalized) {
    return;
  }
  await vscode.workspace
    .getConfiguration(CONFIG_SECTION)
    .update(SERVER_URL_KEY, normalized, vscode.ConfigurationTarget.Global);
}

async function refreshConnection(
  session: Session,
  options: { notify: boolean },
): Promise<ConnectionState> {
  const serverUrl = getServerUrl();
  const state = await checkHealth(serverUrl);
  lastState = state;
  renderStatus(session);
  if (options.notify) {
    if (state.kind === "online") {
      void vscode.window.showInformationMessage(
        `Bug Tracker: connected to ${serverUrl} (v${state.version}).`,
      );
    } else {
      void vscode.window.showWarningMessage(
        `Bug Tracker: cannot reach ${serverUrl} (${state.reason}). Forms stay open; nothing ` +
          "is queued or sent until the server is back.",
      );
    }
  }
  return state;
}

/** Menu behind the status bar item when logged in: the everyday actions in one place. */
async function showStatusMenu(session: Session): Promise<void> {
  const items: { label: string; command: string }[] = [
    { label: "$(add) Report Bug", command: "bugTracker.reportBug" },
    { label: "$(search) Search Bugs", command: "bugTracker.searchBugs" },
    { label: "$(graph) Open Dashboard", command: "bugTracker.openDashboard" },
    { label: "$(account) My Profile and Notifications", command: "bugTracker.myProfile" },
  ];
  if (session.currentUser?.role === "Administrator") {
    items.push({
      label: "$(settings-gear) Admin: Manage Developer Profiles",
      command: "bugTracker.adminProfiles",
    });
  }
  items.push(
    { label: "$(plug) Check Server Connection", command: "bugTracker.checkConnection" },
    { label: "$(sign-out) Log Out", command: "bugTracker.logout" },
  );
  const pick = await vscode.window.showQuickPick(items, { placeHolder: "Bug Tracker" });
  if (pick) {
    await vscode.commands.executeCommand(pick.command);
  }
}

function renderStatus(session: Session): void {
  if (!statusItem || !lastState) {
    return;
  }
  const serverUrl = getServerUrl();
  const user = session.currentUser;
  if (lastState.kind === "online") {
    statusItem.text = user ? `$(bug) ${user.full_name}` : "$(bug) Bug Tracker: log in";
    // Logged out: the item says "log in", so clicking it opens the login.
    statusItem.command = user ? "bugTracker.statusMenu" : "bugTracker.login";
    statusItem.tooltip = user
      ? `Connected to ${serverUrl} (v${lastState.version}) as ${user.email} (${user.role}). Click for Bug Tracker actions.`
      : `Connected to ${serverUrl} (v${lastState.version}). Click to log in.`;
    statusItem.backgroundColor = undefined;
    statusItem.accessibilityInformation = {
      label: user
        ? `Bug Tracker connected as ${user.full_name}`
        : "Bug Tracker connected, not logged in",
    };
  } else {
    statusItem.text = "$(warning) Bug Tracker offline";
    statusItem.command = "bugTracker.checkConnection";
    statusItem.tooltip = `Cannot reach ${serverUrl}: ${lastState.reason}. Click to retry.`;
    statusItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    statusItem.accessibilityInformation = {
      label: `Bug Tracker offline: ${lastState.reason}`,
    };
  }
  statusItem.show();
}
