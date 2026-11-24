import * as vscode from "vscode";

import { ApiClient, ApiError, NetworkError, errorMessage } from "./api/client";
import type { UserMe } from "./api/types";
import { getServerUrl } from "./config";

const TOKEN_KEY = "bugTracker.accessToken";

/**
 * Login state. The JWT lives only in SecretStorage (OS keychain), never in settings or in a
 * webview. Context keys drive menu/command visibility (`bugTracker.loggedIn`,
 * `bugTracker.isAdmin`, `bugTracker.canManageProjects`).
 */
export class Session implements vscode.Disposable {
  private user: UserMe | undefined;
  private reachable = true;
  private readonly changed = new vscode.EventEmitter<UserMe | undefined>();
  private readonly reachability = new vscode.EventEmitter<boolean>();
  readonly onDidChangeUser = this.changed.event;
  readonly onDidChangeReachability = this.reachability.event;
  readonly api: ApiClient;

  constructor(private readonly secrets: vscode.SecretStorage) {
    this.api = new ApiClient({
      baseUrl: getServerUrl,
      token: () => Promise.resolve(this.secrets.get(TOKEN_KEY)),
      onUnauthorized: () => {
        if (this.user) {
          void this.clear().then(() =>
            vscode.window
              .showWarningMessage("Bug Tracker: your session has expired.", "Log In")
              .then((choice) => {
                if (choice) {
                  void vscode.commands.executeCommand("bugTracker.login");
                }
              }),
          );
        }
      },
      onReachability: (value) => {
        if (value !== this.reachable) {
          this.reachable = value;
          this.reachability.fire(value);
        }
      },
    });
  }

  get currentUser(): UserMe | undefined {
    return this.user;
  }

  get isReachable(): boolean {
    return this.reachable;
  }

  /** Restore a stored session (token still valid) when the extension starts. */
  async restore(): Promise<void> {
    if (!(await this.secrets.get(TOKEN_KEY))) {
      await this.setUser(undefined);
      return;
    }
    try {
      await this.setUser(await this.api.me());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        await this.clear();
      } else if (!(error instanceof NetworkError)) {
        void vscode.window.showWarningMessage(`Bug Tracker: ${errorMessage(error)}`);
      }
      // Offline: keep the token; the next successful call restores the user.
    }
  }

  async login(email: string, password: string): Promise<UserMe> {
    const token = await this.api.login(email, password);
    await this.secrets.store(TOKEN_KEY, token.access_token);
    await this.setUser(token.user);
    return token.user;
  }

  async storeToken(token: string): Promise<void> {
    await this.secrets.store(TOKEN_KEY, token);
  }

  async refreshUser(): Promise<void> {
    await this.setUser(await this.api.me());
  }

  async clear(): Promise<void> {
    await this.secrets.delete(TOKEN_KEY);
    await this.setUser(undefined);
  }

  private async setUser(user: UserMe | undefined): Promise<void> {
    this.user = user;
    await Promise.all([
      vscode.commands.executeCommand("setContext", "bugTracker.loggedIn", user !== undefined),
      vscode.commands.executeCommand(
        "setContext",
        "bugTracker.isAdmin",
        user?.role === "Administrator",
      ),
      vscode.commands.executeCommand(
        "setContext",
        "bugTracker.canManageProjects",
        user?.role === "ProjectManager" || user?.role === "Administrator",
      ),
    ]);
    this.changed.fire(user);
  }

  dispose(): void {
    this.changed.dispose();
    this.reachability.dispose();
  }
}
