import * as vscode from "vscode";

export const CONFIG_SECTION = "bugTracker";
export const SERVER_URL_KEY = "serverUrl";
export const DEFAULT_SERVER_URL = "http://localhost:8000";

/** Returns the configured backend base URL without a trailing slash. */
export function getServerUrl(): string {
  const value = vscode.workspace
    .getConfiguration(CONFIG_SECTION)
    .get<string>(SERVER_URL_KEY, DEFAULT_SERVER_URL);
  return normalizeServerUrl(value) ?? DEFAULT_SERVER_URL;
}

/**
 * Validates and normalizes a user-entered server URL.
 * Returns `undefined` when the value is not an http(s) URL.
 */
export function normalizeServerUrl(raw: string): string | undefined {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return undefined;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return undefined;
  }
  if (url.username || url.password || url.search || url.hash) {
    return undefined;
  }
  return url.toString().replace(/\/+$/, "");
}
