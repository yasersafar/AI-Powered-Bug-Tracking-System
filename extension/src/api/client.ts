// HTTP client for the Bug Tracker REST API. Runs in the extension host only: the JWT never
// reaches a webview. No `vscode` import, so it can be tested against a plain mock server.

import type {
  AiStatusResponse,
  Attachment,
  AuditEntry,
  Bug,
  BugCreate,
  BugListItem,
  BugSearch,
  BugStatus,
  Comment,
  Dashboard,
  DeveloperStats,
  Member,
  Notification,
  Page,
  Profile,
  ProfileFields,
  Project,
  ProjectRole,
  Setting,
  Severity,
  TokenResponse,
  TriageResponse,
  UserMe,
  UserSummary,
} from "./types";

const API = "/api/v1";
export const DEFAULT_TIMEOUT_MS = 15_000;

/** The server answered with an error ({code, message, details}). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** One readable line, including field errors from 422 responses. */
  describe(): string {
    if (this.status === 422 && Array.isArray(this.details)) {
      const fields = (this.details as { loc?: unknown[]; msg?: string }[])
        .map((d) => `${(d.loc ?? []).filter((p) => p !== "body").join(".")}: ${d.msg ?? ""}`)
        .join("; ");
      return fields ? `${this.message} (${fields})` : this.message;
    }
    return this.message;
  }
}

/** The server could not be reached (offline, DNS, refused, timeout). */
export class NetworkError extends Error {
  constructor(
    message: string,
    readonly timedOut = false,
  ) {
    super(message);
    this.name = "NetworkError";
  }
}

export interface ClientOptions {
  baseUrl: () => string;
  token: () => Promise<string | undefined>;
  /** Called when a request fails with 401 so the caller can clear the stored session. */
  onUnauthorized?: () => void;
  /** Called after every request with whether the server was reachable. */
  onReachability?: (reachable: boolean) => void;
  fetchImpl?: typeof fetch;
}

interface RequestOptions {
  query?: Record<string, string | number | boolean | readonly (string | number)[] | undefined>;
  json?: unknown;
  form?: FormData | URLSearchParams;
  timeoutMs?: number;
  auth?: boolean;
  raw?: boolean;
}

export function buildQuery(query: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === "") {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value as readonly (string | number)[]) {
        params.append(key, String(item));
      }
    } else {
      params.append(key, String(value));
    }
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export class ApiClient {
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly options: ClientOptions) {
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.auth !== false) {
      const token = await this.options.token();
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
    }
    let body: BodyInit | undefined;
    if (options.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.json);
    } else if (options.form !== undefined) {
      body = options.form;
    }
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const url = `${this.options.baseUrl()}${path}${buildQuery(options.query)}`;
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method,
        headers,
        body: body ?? null,
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (error) {
      this.options.onReachability?.(false);
      const timedOut = error instanceof Error && error.name === "TimeoutError";
      throw new NetworkError(
        timedOut
          ? `The server did not answer within ${Math.round(timeoutMs / 1000)} s.`
          : `Cannot reach the Bug Tracker server at ${this.options.baseUrl()}.`,
        timedOut,
      );
    }
    this.options.onReachability?.(true);
    if (!response.ok) {
      throw await toApiError(response, this.options.onUnauthorized);
    }
    if (options.raw) {
      return response as unknown as T;
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  // ------------------------------------------------------------------ auth and profile
  login(email: string, password: string): Promise<TokenResponse> {
    const form = new URLSearchParams({ username: email, password });
    return this.request("POST", `${API}/auth/login`, { form, auth: false });
  }

  register(email: string, fullName: string, password: string): Promise<UserMe> {
    return this.request("POST", `${API}/auth/register`, {
      json: { email, full_name: fullName, password },
      auth: false,
    });
  }

  me(): Promise<UserMe> {
    return this.request("GET", `${API}/users/me`);
  }

  updateMe(changes: {
    full_name?: string;
    email_notifications?: boolean;
    push_notifications?: boolean;
  }): Promise<UserMe> {
    return this.request("PATCH", `${API}/users/me`, { json: changes });
  }

  changePassword(currentPassword: string, newPassword: string): Promise<TokenResponse> {
    return this.request("POST", `${API}/users/me/password`, {
      json: { current_password: currentPassword, new_password: newPassword },
    });
  }

  searchUsers(q: string): Promise<Page<UserSummary>> {
    return this.request("GET", `${API}/users`, { query: { q, page_size: 50 } });
  }

  // ------------------------------------------------------------------ projects
  projects(includeArchived = false): Promise<Project[]> {
    return this.request("GET", `${API}/projects`, {
      query: { include_archived: includeArchived },
    });
  }

  createProject(name: string, description: string): Promise<Project> {
    return this.request("POST", `${API}/projects`, { json: { name, description } });
  }

  members(projectId: number): Promise<Member[]> {
    return this.request("GET", `${API}/projects/${projectId}/members`);
  }

  addMember(projectId: number, userId: number, role: ProjectRole): Promise<Member> {
    return this.request("POST", `${API}/projects/${projectId}/members`, {
      json: { user_id: userId, role },
    });
  }

  dashboard(projectId: number, days = 30): Promise<Dashboard> {
    return this.request("GET", `${API}/projects/${projectId}/dashboard`, { query: { days } });
  }

  // ------------------------------------------------------------------ bugs
  searchBugs(search: BugSearch): Promise<Page<BugListItem>> {
    return this.request("GET", `${API}/bugs`, { query: { ...search } });
  }

  bug(id: number): Promise<Bug> {
    return this.request("GET", `${API}/bugs/${id}`);
  }

  /** Submission runs the full AI triage on the server; allow for a slow first model call. */
  createBug(data: BugCreate): Promise<Bug> {
    return this.request("POST", `${API}/bugs`, { json: data, timeoutMs: 30_000 });
  }

  transition(
    id: number,
    toStatus: BugStatus,
    closeReason?: "invalid" | "duplicate",
    duplicateOfId?: number,
  ): Promise<Bug> {
    return this.request("POST", `${API}/bugs/${id}/transitions`, {
      json: {
        to_status: toStatus,
        close_reason: closeReason ?? null,
        duplicate_of_id: duplicateOfId ?? null,
      },
    });
  }

  assign(id: number, assigneeId: number): Promise<Bug> {
    return this.request("POST", `${API}/bugs/${id}/assign`, { json: { assignee_id: assigneeId } });
  }

  overrideSeverity(id: number, severity: Exclude<Severity, "Unclassified">): Promise<Bug> {
    return this.request("POST", `${API}/bugs/${id}/severity`, { json: { severity } });
  }

  audit(id: number): Promise<AuditEntry[]> {
    return this.request("GET", `${API}/bugs/${id}/audit`);
  }

  comments(id: number): Promise<Comment[]> {
    return this.request("GET", `${API}/bugs/${id}/comments`);
  }

  addComment(id: number, body: string): Promise<Comment> {
    return this.request("POST", `${API}/bugs/${id}/comments`, { json: { body } });
  }

  attachments(id: number): Promise<Attachment[]> {
    return this.request("GET", `${API}/bugs/${id}/attachments`);
  }

  uploadAttachment(id: number, filename: string, data: Uint8Array): Promise<Attachment> {
    const form = new FormData();
    form.append("file", new Blob([data as Uint8Array<ArrayBuffer>]), filename);
    return this.request("POST", `${API}/bugs/${id}/attachments`, { form, timeoutMs: 60_000 });
  }

  async downloadAttachment(attachmentId: number): Promise<Uint8Array> {
    const response = await this.request<Response>(
      "GET",
      `${API}/attachments/${attachmentId}/download`,
      { raw: true, timeoutMs: 60_000 },
    );
    return new Uint8Array(await response.arrayBuffer());
  }

  // ------------------------------------------------------------------ AI triage
  duplicates(
    projectId: number,
    title: string,
    description: string,
    excludeBugId?: number,
  ): Promise<TriageResponse> {
    return this.request("POST", `${API}/ai/duplicates`, {
      json: {
        project_id: projectId,
        title,
        description,
        exclude_bug_id: excludeBugId ?? null,
      },
      timeoutMs: 5_000,
    });
  }

  aiStatus(): Promise<AiStatusResponse> {
    return this.request("GET", `${API}/ai/status`);
  }

  // ------------------------------------------------------------------ notifications
  notifications(unreadOnly = false, pageSize = 50): Promise<Page<Notification>> {
    return this.request("GET", `${API}/notifications`, {
      query: { unread_only: unreadOnly, page_size: pageSize },
    });
  }

  markRead(id: number): Promise<unknown> {
    return this.request("POST", `${API}/notifications/${id}/read`);
  }

  markAllRead(): Promise<unknown> {
    return this.request("POST", `${API}/notifications/read-all`);
  }

  // ------------------------------------------------------------------ admin
  profiles(): Promise<Profile[]> {
    return this.request("GET", `${API}/admin/profiles`);
  }

  createProfile(userId: number, fields: ProfileFields): Promise<Profile> {
    return this.request("POST", `${API}/admin/profiles`, { json: { user_id: userId, ...fields } });
  }

  updateProfile(id: number, fields: ProfileFields): Promise<Profile> {
    return this.request("PATCH", `${API}/admin/profiles/${id}`, { json: fields });
  }

  developerStats(): Promise<DeveloperStats[]> {
    return this.request("GET", `${API}/admin/developers/stats`);
  }

  settings(): Promise<Setting[]> {
    return this.request("GET", `${API}/admin/settings`);
  }

  updateSettings(values: Record<string, number>): Promise<Setting[]> {
    return this.request("PUT", `${API}/admin/settings`, { json: { values } });
  }
}

async function toApiError(response: Response, onUnauthorized?: () => void): Promise<ApiError> {
  if (response.status === 401) {
    onUnauthorized?.();
  }
  try {
    const body = (await response.json()) as {
      code?: unknown;
      message?: unknown;
      details?: unknown;
    };
    return new ApiError(
      response.status,
      typeof body.code === "string" ? body.code : "error",
      typeof body.message === "string" ? body.message : `HTTP ${response.status}`,
      body.details ?? null,
    );
  } catch {
    return new ApiError(response.status, "error", `HTTP ${response.status}`);
  }
}

/** Message for any error thrown by the client, suitable for the UI. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.describe();
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
