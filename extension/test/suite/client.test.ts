// API client against a mock HTTP server (no VS Code APIs involved).
import * as assert from "node:assert/strict";

import { ApiClient, ApiError, NetworkError, buildQuery, errorMessage } from "../../src/api/client";
import { MockServer, ME, standardBackend } from "../mockServer";

describe("ApiClient", () => {
  const server = standardBackend(new MockServer());
  let token: string | undefined;
  let unauthorized = 0;
  const reachability: boolean[] = [];
  const client = new ApiClient({
    baseUrl: () => server.url,
    token: () => Promise.resolve(token),
    onUnauthorized: () => {
      unauthorized++;
    },
    onReachability: (r) => reachability.push(r),
  });

  before(async () => {
    server
      .on("POST", "/api/v1/bugs", () => ({
        status: 422,
        json: {
          code: "validation_error",
          message: "Invalid request",
          details: [
            { loc: ["body", "description"], msg: "String should have at least 20 characters" },
          ],
        },
      }))
      .on("POST", "/api/v1/bugs/\\d+/attachments", (req) => ({
        status: 201,
        json: { id: 1, original_filename: "log.txt", size_bytes: req.body.length },
      }))
      .on("GET", "/api/v1/ai/status", () => ({ json: {}, delayMs: 400 }));
    await server.start();
  });

  after(() => server.stop());

  it("logs in with a form body and returns the user", async () => {
    const result = await client.login("rita@example.com", "Passw0rd!");
    assert.equal(result.access_token, "token-abc");
    assert.equal(result.user.full_name, ME.full_name);
    const req = server.last("/api/v1/auth/login");
    assert.ok(req);
    assert.equal(req.headers["content-type"], "application/x-www-form-urlencoded;charset=UTF-8");
    assert.equal(req.headers.authorization, undefined); // login never sends a token
  });

  it("sends the bearer token and repeated query parameters", async () => {
    token = "token-abc";
    await client.searchBugs({ status: ["Open", "InProgress"], q: "crash", project_id: 1 });
    const req = server.last("/api/v1/bugs");
    assert.ok(req);
    assert.equal(req.headers.authorization, "Bearer token-abc");
    assert.deepEqual(req.query.getAll("status"), ["Open", "InProgress"]);
    assert.equal(req.query.get("q"), "crash");
  });

  it("turns error bodies into ApiError with field details", async () => {
    await assert.rejects(
      client.createBug({
        project_id: 1,
        title: "Short",
        description: "too short",
        steps_to_reproduce: "x",
        environment: "y",
        components: [],
      }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 422);
        assert.match(error.describe(), /description: String should have at least 20 characters/);
        return true;
      },
    );
  });

  it("reports 401 so the session can be cleared", async () => {
    token = "expired";
    const before = unauthorized;
    await assert.rejects(client.me(), (e: unknown) => e instanceof ApiError && e.status === 401);
    assert.equal(unauthorized, before + 1);
    token = "token-abc";
  });

  it("uploads attachments as multipart form data", async () => {
    const data = new TextEncoder().encode("line 1\nline 2\n");
    const result = await client.uploadAttachment(11, "log.txt", data);
    assert.equal(result.original_filename, "log.txt");
    const req = server.last("/api/v1/bugs/11/attachments");
    assert.match(String(req?.headers["content-type"]), /^multipart\/form-data; boundary=/);
    assert.match(req?.body.toString() ?? "", /filename="log.txt"/);
  });

  it("raises NetworkError when the server is unreachable or slow", async () => {
    const offline = new ApiClient({
      baseUrl: () => "http://127.0.0.1:9", // nothing listens on the discard port
      token: () => Promise.resolve(undefined),
      onReachability: (r) => reachability.push(r),
    });
    await assert.rejects(offline.projects(), (e: unknown) => e instanceof NetworkError);
    assert.equal(reachability.at(-1), false);
    await assert.rejects(
      client.request("GET", "/api/v1/ai/status", { timeoutMs: 100 }),
      (e: unknown) => e instanceof NetworkError && e.timedOut,
    );
    assert.match(errorMessage(new NetworkError("x")), /x/);
  });

  it("builds query strings without empty values", () => {
    assert.equal(buildQuery({ a: 1, b: undefined, c: "", d: ["x", "y"] }), "?a=1&d=x&d=y");
    assert.equal(buildQuery({}), "");
  });
});
