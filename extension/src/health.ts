export type ConnectionState =
  { kind: "online"; version: string } | { kind: "offline"; reason: string };

interface HealthBody {
  status?: unknown;
  version?: unknown;
}

/** Calls GET {serverUrl}/health with a timeout and reports whether the backend is reachable. */
export async function checkHealth(serverUrl: string, timeoutMs = 3000): Promise<ConnectionState> {
  try {
    const response = await fetch(`${serverUrl}/health`, {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      return { kind: "offline", reason: `HTTP ${response.status}` };
    }
    const body = (await response.json()) as HealthBody;
    if (body.status !== "ok") {
      return { kind: "offline", reason: "unexpected health response" };
    }
    return { kind: "online", version: typeof body.version === "string" ? body.version : "?" };
  } catch (error) {
    const reason =
      error instanceof Error && error.name === "TimeoutError"
        ? `no response within ${timeoutMs} ms`
        : "server unreachable";
    return { kind: "offline", reason };
  }
}
