// A tiny in-process stand-in for the backend (SYNTHETIC data, tests only).
import { type IncomingMessage, type Server, type ServerResponse, createServer } from "node:http";
import type { AddressInfo } from "node:net";

export interface Recorded {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: IncomingMessage["headers"];
  body: Buffer;
}

export type Handler = (
  req: Recorded,
) => { status?: number; json?: unknown; body?: string | Buffer; delayMs?: number } | undefined;

export class MockServer {
  readonly requests: Recorded[] = [];
  private readonly routes = new Map<string, Handler>();
  private server: Server | undefined;
  url = "";

  on(method: string, path: string, handler: Handler): this {
    this.routes.set(`${method} ${path}`, handler);
    return this;
  }

  async start(): Promise<string> {
    this.server = createServer((req, res) => {
      void this.handle(req, res);
    });
    await new Promise<void>((resolve) => this.server?.listen(0, "127.0.0.1", resolve));
    const address = this.server.address() as AddressInfo;
    this.url = `http://127.0.0.1:${address.port}`;
    return this.url;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => {
      this.server?.closeAllConnections();
      this.server?.close(() => {
        resolve();
      });
    });
  }

  last(path: string): Recorded | undefined {
    return [...this.requests].reverse().find((r) => r.path === path);
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const chunks: Buffer[] = [];
    for await (const chunk of req) {
      chunks.push(chunk as Buffer);
    }
    const url = new URL(req.url ?? "/", "http://localhost");
    const recorded: Recorded = {
      method: req.method ?? "GET",
      path: url.pathname,
      query: url.searchParams,
      headers: req.headers,
      body: Buffer.concat(chunks),
    };
    this.requests.push(recorded);
    const handler =
      this.routes.get(`${recorded.method} ${recorded.path}`) ??
      [...this.routes.entries()].find(([key]) => {
        const [method, pattern] = key.split(" ");
        return (
          method === recorded.method && pattern && new RegExp(`^${pattern}$`).test(recorded.path)
        );
      })?.[1];
    const result = handler?.(recorded) ?? {
      status: 404,
      json: { code: "not_found", message: "Not found" },
    };
    if (result.delayMs) {
      await new Promise((r) => setTimeout(r, result.delayMs));
    }
    if (res.destroyed) {
      return;
    }
    res.statusCode = result.status ?? 200;
    if (result.json !== undefined) {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result.json));
    } else {
      res.end(result.body ?? "");
    }
  }
}

export const ME = {
  id: 7,
  email: "rita@example.com",
  full_name: "Rita Reporter",
  role: "Reporter",
  is_active: true,
  created_at: "2026-11-01T10:00:00Z",
  email_notifications: true,
  push_notifications: true,
  ntfy_topic: "bugtracker-test",
};

export const PROJECT = {
  id: 1,
  name: "Payments Platform",
  description: "",
  is_archived: false,
  archived_at: null,
  created_at: "2026-11-01T10:00:00Z",
  my_role: "Reporter",
};

export function listItem(id: number, title: string, extra: Record<string, unknown> = {}): object {
  return {
    id,
    project_id: 1,
    title,
    status: "Open",
    severity: "High",
    ai_status: "ok",
    assignee: null,
    reporter: { id: 7, full_name: "Rita Reporter", email: "rita@example.com", role: "Reporter" },
    components: ["checkout"],
    created_at: "2026-11-20T10:00:00Z",
    updated_at: "2026-11-20T10:00:00Z",
    ...extra,
  };
}

export function fullBug(id: number, extra: Record<string, unknown> = {}): object {
  return {
    ...listItem(id, "Checkout fails <script>alert(1)</script>"),
    description: "The card form throws when the card is declined.",
    steps_to_reproduce: "1. Pay with a declined card",
    environment: "Chrome 131",
    close_reason: null,
    duplicate_of_id: null,
    predicted_severity: "High",
    severity_confidence: 0.72,
    severity_overridden: false,
    duplicate_candidates: [],
    recommended_developers: [],
    ai_details: { steps: {}, notice: null, is_likely_duplicate: false },
    resolved_at: null,
    closed_at: null,
    allowed_transitions: [],
    can_override_severity: false,
    can_assign: false,
    can_edit: true,
    ...extra,
  };
}

/** A backend with a logged-in Reporter, one project and a few bugs. */
export function standardBackend(server: MockServer): MockServer {
  return server
    .on("GET", "/health", () => ({ json: { status: "ok", version: "test", environment: "test" } }))
    .on("POST", "/api/v1/auth/login", (req) => {
      const form = new URLSearchParams(req.body.toString());
      return form.get("password") === "Passw0rd!"
        ? { json: { access_token: "token-abc", token_type: "bearer", expires_in: 28800, user: ME } }
        : {
            status: 401,
            json: { code: "invalid_credentials", message: "Invalid email or password" },
          };
    })
    .on("GET", "/api/v1/users/me", (req) =>
      req.headers.authorization === "Bearer token-abc"
        ? { json: ME }
        : { status: 401, json: { code: "unauthorized", message: "Not authenticated" } },
    )
    .on("GET", "/api/v1/projects", () => ({ json: [PROJECT] }))
    .on("GET", "/api/v1/bugs", (req) => {
      const items = req.query.get("assignee_id") ? [] : [listItem(11, "Card declined crash")];
      return { json: { items, total: items.length, page: 1, page_size: 50 } };
    })
    .on("GET", "/api/v1/bugs/\\d+", (req) => ({ json: fullBug(Number(req.path.split("/").pop())) }))
    .on("GET", "/api/v1/bugs/\\d+/(comments|attachments|audit)", () => ({ json: [] }))
    .on("GET", "/api/v1/notifications", () => ({
      json: { items: [], total: 0, page: 1, page_size: 20 },
    }))
    .on("POST", "/api/v1/ai/duplicates", () => ({
      json: {
        ai_status: "ok",
        notice: null,
        duplicates: [{ bug_id: 11, title: "Card declined crash", status: "Open", score: 0.91 }],
        is_likely_duplicate: true,
        severity: { severity: null, confidence: null, probabilities: {} },
        recommendations: [],
        steps: {},
        total_ms: 12,
      },
    }));
}
