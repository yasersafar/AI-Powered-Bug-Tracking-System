// Small render helpers shared by the webviews (all output escaped via `html`).

import type { AiDetails, Bug, DeveloperSuggestion, DuplicateMatch, Severity } from "../api/types";
import { type SafeHtml, html } from "./html";

export const AI_UNAVAILABLE = "AI unavailable – severity set to Unclassified";

const STATUS_LABEL: Record<string, string> = {
  Open: "Open",
  InProgress: "In progress",
  Resolved: "Resolved",
  Verified: "Verified",
  Closed: "Closed",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

export function severityBadge(severity: Severity | null): SafeHtml {
  const value = severity ?? "Unclassified";
  return html`<span class="badge sev-${value}">${value}</span>`;
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${Math.round(value * 100)}%`;
}

export function duplicateList(duplicates: readonly DuplicateMatch[], likely?: boolean): SafeHtml {
  if (duplicates.length === 0) {
    return html`<p class="hint">No similar reports found in this project.</p>`;
  }
  return html`${
      likely
        ? html`<p class="notice warning">
            This looks like a duplicate of an existing report. Please check it.
          </p>`
        : ""
    }
    <ul class="plain">
      ${duplicates.map(
        (d) =>
          html`<li>
            <button
              class="link"
              data-action="openBug"
              data-id="${d.bug_id}"
              aria-label="Open bug ${d.bug_id}: ${d.title}, similarity ${percent(d.score)}"
            >
              #${d.bug_id} ${d.title}
            </button>
            <span class="hint">— ${statusLabel(d.status)}, similarity ${percent(d.score)}</span>
          </li>`,
      )}
    </ul>`;
}

export function recommendationList(recs: readonly DeveloperSuggestion[]): SafeHtml {
  if (recs.length === 0) {
    return html`<p class="hint">No developer recommendation available.</p>`;
  }
  return html`<ol>
    ${recs.map(
      (r) =>
        html`<li>
          <strong>${r.name}</strong> — ${r.reason}
          <span class="hint"
            >(score ${r.score.toFixed(2)}; history weight α =
            ${r.alpha.toFixed(2)}${r.explored ? "; exploration slot" : ""})</span
          >
          ${r.notes.length ? html`<div class="hint">${r.notes.join("; ")}</div>` : ""}
        </li>`,
    )}
  </ol>`;
}

/** Message shown when the triage pipeline was degraded (NFR-10). */
export function aiNotice(bug: Pick<Bug, "ai_status" | "severity">, details: AiDetails): SafeHtml {
  if (bug.ai_status !== "degraded") {
    return html``;
  }
  const headline = bug.severity === "Unclassified" ? AI_UNAVAILABLE : "AI partly unavailable";
  return html`<div class="notice warning" role="note">
    <strong>${headline}.</strong>
    ${details.notice ?? "This report was saved without AI triage results."}
  </div>`;
}
