// Escaping, charts, fragments and search parsing (pure functions).
import * as assert from "node:assert/strict";

import type { Project } from "../../src/api/types";
import { parseSearch } from "../../src/search";
import { barChart, lineChart } from "../../src/webview/charts";
import { AI_UNAVAILABLE, aiNotice, duplicateList } from "../../src/webview/fragments";
import { escapeHtml, html, nonce } from "../../src/webview/html";

describe("html escaping (XSS safety of webviews)", () => {
  it("escapes interpolated values but not nested html", () => {
    const evil = `<img src=x onerror="alert(1)">`;
    const out = html`<p title="${evil}">${evil}${html`<b>ok</b>`}</p>`.value;
    assert.ok(!out.includes("<img"));
    assert.ok(out.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
    assert.ok(out.includes("<b>ok</b>"));
  });

  it("escapes every special character and renders lists", () => {
    assert.equal(escapeHtml(`&<>"'\``), "&amp;&lt;&gt;&quot;&#39;&#96;");
    assert.equal(html`${["a", "<b>"]}`.value, "a&lt;b&gt;");
    assert.equal(html`${null}${undefined}${false}`.value, "");
  });

  it("creates unpredictable CSP nonces", () => {
    const a = nonce();
    assert.match(a, /^[A-Za-z0-9_-]{24}$/);
    assert.notEqual(a, nonce());
  });
});

describe("charts", () => {
  it("bar chart has an accessible label and a data table", () => {
    const out = barChart("s", "By status", [
      { label: "Open", value: 3 },
      { label: "<Closed>", value: 1 },
    ]).value;
    assert.match(out, /role="img"/);
    assert.match(out, /aria-label="By status: Open 3, &lt;Closed&gt; 1"/);
    assert.match(out, /<th scope="col">Bugs<\/th>/);
    assert.ok(!out.includes("<Closed>"));
  });

  it("line chart summarises totals", () => {
    const out = lineChart("t", "Per day", [
      { day: "2026-11-01", created: 2, resolved: 1 },
      { day: "2026-11-02", created: 1, resolved: 3 },
    ]).value;
    assert.match(out, /3 created, 4 resolved/);
    assert.match(out, /<polyline/);
  });
});

describe("fragments", () => {
  it("shows the NFR-10 message when AI was degraded and severity is Unclassified", () => {
    const out = aiNotice(
      { ai_status: "degraded", severity: "Unclassified" },
      { notice: "AI triage is switched off by an administrator." },
    ).value;
    assert.ok(out.includes(AI_UNAVAILABLE));
    assert.ok(out.includes("switched off"));
    assert.equal(aiNotice({ ai_status: "ok", severity: "High" }, {}).value, "");
    const silent = aiNotice({ ai_status: "degraded", severity: "High" }, {}).value;
    assert.match(silent, /saved without AI triage results/);
  });

  it("lists duplicates with a similarity and a likely-duplicate warning", () => {
    const out = duplicateList(
      [{ bug_id: 4, title: "Crash <on> save", status: "Open", score: 0.873 }],
      true,
    ).value;
    assert.match(out, /similarity 87%/);
    assert.match(out, /looks like a duplicate/);
    assert.match(out, /data-action="openBug"/);
    assert.ok(out.includes("Crash &lt;on&gt; save"));
  });
});

describe("search parsing (FR-07)", () => {
  const projects = [
    { id: 1, name: "Payments Platform" },
    { id: 2, name: "Mobile App" },
  ] as Project[];

  it("splits words and filters", () => {
    const { search, problems } = parseSearch(
      'crash "card declined" status:open status:in-progress severity:Critical project:mobile assignee:me since:2026-11-01',
      projects,
      7,
    );
    assert.deepEqual(problems, []);
    assert.equal(search.q, 'crash "card declined"');
    assert.equal(search.sort, "relevance");
    assert.deepEqual(search.status, ["Open", "InProgress"]);
    assert.deepEqual(search.severity, ["Critical"]);
    assert.equal(search.project_id, 2);
    assert.equal(search.assignee_id, 7);
    assert.equal(search.created_from, "2026-11-01T00:00:00Z");
  });

  it("reports unknown filters instead of ignoring them", () => {
    const { search, problems } = parseSearch("status:done project:nope until:yesterday", projects);
    assert.equal(problems.length, 3);
    assert.equal(search.q, undefined);
    assert.equal(search.sort, "updated_desc");
  });
});
